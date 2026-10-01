"""Mide en CPU lo generado por el motor de producción para cada candidata: acento, F0, duración e inteligibilidad (WER con Whisper).

    uv run --project spikes/voces python spikes/voces/evaluar_muestras.py                     # todas las que tengan <id>_frase1..4.wav
    uv run --project spikes/voces python spikes/voces/evaluar_muestras.py es-f-dis-01 es-f-est-02

Por candidata y frase: ASR de Whisper large-v3-turbo (tiempos por palabra), WER contra el texto pedido, duración, palabras por segundo y F0
(mediana, rango p10-p90 en semitonos, desviación en semitonos). Indicio de acento: `distincion.py` con las palabras de las 4 frases juntas
(Δ s−θ en dB; positivo grande = distingue /θ/ de /s/; control peninsular del spike S1: 15,5 dB; seseo argentino: 1,8 dB).
Una frase se marca ROTA si WER > 0,25, si dura menos de 0,6x o más de 1,8x lo esperado (2,4 palabras/s) o si tiene recortes.
Escribe `<out>/medidas.json` y una copia en `spikes/voces/resultados/medidas.json`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

WER_ROTA = 0.25
PALABRAS_POR_S_ESPERADAS = 2.6


def evaluar_wav(wav: Path, texto: str, cache: dict) -> dict:
    clave = f"{wav.name}|{wav.stat().st_size}|{wav.stat().st_mtime_ns}"
    if clave in cache:
        return cache[clave]
    a, sr = c.vb.read_wav_mono(wav)
    asr = c.transcribir(a, sr)
    tokens = c.acento_tokens(a, sr, asr["chunks"])
    n_pal = c.aw.normalize_text(texto)
    dur = len(a) / sr
    ev = {
        "fichero": wav.name,
        "duracion_s": round(dur, 2),
        "palabras": len(n_pal),
        "palabras_por_s": round(len(n_pal) / dur, 2),
        "asr_texto": asr["text"],
        "wer": round(c.wer(texto, asr["text"]), 3),
        "pico_dbfs": round(float(20 * np.log10(np.max(np.abs(a)) + 1e-12)), 1),
        "recortes": int(np.sum(np.abs(a) >= 0.999)),
        "tokens": tokens,
        **c.f0_stats(a, sr),
    }
    esperada = len(n_pal) / PALABRAS_POR_S_ESPERADAS
    ev["rota"] = bool(ev["wer"] > WER_ROTA or dur < 0.6 * esperada or dur > 1.8 * esperada or ev["recortes"] > 5)
    cache[clave] = ev
    return ev


def main() -> None:
    quiero = set(sys.argv[1:])
    out = c.out_dir()
    ids = sorted(p.name[: -len("_frase1.wav")] for p in out.glob("*_frase1.wav"))
    cache_p = c.work_dir() / "muestras_cache.json"
    cache = c.leer_json(cache_p) if cache_p.exists() else {}
    medidas: dict = {}
    print(f"{'id':20s} {'WER':>5s} {'F0med':>6s} {'rango st':>8s} {'desv st':>7s} {'dur total':>9s} {'nθ/ns':>7s} {'Δ s-θ':>6s} {'p':>7s} rotas")
    for cid in ids:
        if quiero and cid not in quiero:
            continue
        frases = []
        for f in c.FRASES:
            wav = out / f"{cid}_frase{f['n']}.wav"
            if not wav.exists():
                break
            frases.append({"n": f["n"], "tipo": f["tipo"], **evaluar_wav(wav, f["texto"], cache)})
        c.guardar_json(cache_p, cache)
        if len(frases) < len(c.FRASES):
            continue
        ac = c.acento_resumen(c.juntar_tokens([f["tokens"] for f in frases]))
        ref_wav = out / f"{cid}_ref.wav"
        ref = {}
        if ref_wav.exists():
            a, sr = c.vb.read_wav_mono(ref_wav)
            ref = {"duracion_s": round(len(a) / sr, 2), **c.f0_stats(a, sr)}
        m = {
            "wer_medio": round(float(np.mean([f["wer"] for f in frases])), 3),
            "wer_max": round(float(np.max([f["wer"] for f in frases])), 3),
            "f0_mediana_hz": round(float(np.median([f["f0_mediana_hz"] for f in frases if "f0_mediana_hz" in f])), 1),
            "f0_rango_st_medio": round(float(np.mean([f["f0_rango_p10_p90_st"] for f in frases if "f0_rango_p10_p90_st" in f])), 2),
            "f0_desv_st_medio": round(float(np.mean([f["f0_desv_st"] for f in frases if "f0_desv_st" in f])), 2),
            "duracion_total_s": round(float(sum(f["duracion_s"] for f in frases)), 1),
            "palabras_por_s_medio": round(float(np.mean([f["palabras_por_s"] for f in frases])), 2),
            "acento": ac,
            "frases_rotas": [f["n"] for f in frases if f["rota"]],
            "frases": [{k: v for k, v in f.items() if k != "tokens"} for f in frases],
            "referencia": ref,
        }
        medidas[cid] = m
        p = ac["p_mann_whitney"]
        print(f"{cid:20s} {m['wer_medio']:5.2f} {m['f0_mediana_hz']:6.0f} {m['f0_rango_st_medio']:8.1f} {m['f0_desv_st_medio']:7.1f} {m['duracion_total_s']:9.1f} "
              f"{ac['n_theta']:3d}/{ac['n_s']:<3d} {str(ac['delta_s_menos_theta_db']):>6s} {('%.4f' % p) if p is not None else '-':>7s} {m['frases_rotas'] or ''}")
    previo = c.leer_json(out / "medidas.json") if (out / "medidas.json").exists() else {}
    previo.update(medidas)
    c.guardar_json(out / "medidas.json", previo)
    repo = Path(__file__).resolve().parent / "resultados"
    repo.mkdir(exist_ok=True)
    c.guardar_json(repo / "medidas.json", previo)
    print("->", out / "medidas.json")


if __name__ == "__main__":
    main()
