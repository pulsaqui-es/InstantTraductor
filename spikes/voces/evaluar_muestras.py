"""Mide en CPU lo generado por el motor de producción para cada candidata: acento, F0, duración e inteligibilidad (WER con Whisper).

    uv run --project spikes/voces python spikes/voces/evaluar_muestras.py                     # todas las que tengan <id>_frase1..4.wav
    uv run --project spikes/voces python spikes/voces/evaluar_muestras.py es-f-dis-01 es-f-est-02

Por candidata y frase: ASR de Whisper large-v3-turbo (tiempos por palabra), WER contra el texto pedido, duración, palabras por segundo y F0
(mediana, rango p10-p90 en semitonos, desviación en semitonos). Indicio de acento: `distincion.py` con las palabras de las 4 frases juntas
(Δ s−θ en dB; positivo grande = distingue /θ/ de /s/; control peninsular del spike S1: 15,5 dB; seseo argentino: 1,8 dB).
Los tokens de acento se miden sobre las palabras del texto pedido alineadas con las de Whisper (`acento`) y, aparte, sobre las que escribió
Whisper (`acento_asr_literal`): la diferencia delata /θ/ que Whisper oye como /t/ o /d/. Una frase se marca ROTA si WER > 0,25, si dura menos de 0,45x o más de 2x lo esperado (2,6 palabras/s) o si tiene recortes.
Escribe `<out>/medidas.json` y una copia en `spikes/voces/resultados/medidas.json`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
from sondear_acento import TEXTO_SONDA  # noqa: E402  (solo el texto; no importa torch)

WER_ROTA = 0.25
PALABRAS_POR_S_ESPERADAS = 2.6
DUR_MIN_REL, DUR_MAX_REL = 0.45, 2.0  # fracción de la duración esperada: solo para cazar frases truncadas o con bucles (hay voces que hablan a 4,4 palabras/s)


def es_rota(ev: dict, n_palabras: int) -> bool:
    esperada = n_palabras / PALABRAS_POR_S_ESPERADAS
    return bool(ev["wer"] > WER_ROTA or ev["duracion_s"] < DUR_MIN_REL * esperada or ev["duracion_s"] > DUR_MAX_REL * esperada or ev["recortes"] > 5)


def evaluar_wav(wav: Path, texto: str, cache: dict) -> dict:
    clave = f"v2|{wav.name}|{wav.stat().st_size}|{wav.stat().st_mtime_ns}"
    if clave in cache:  # el ASR ya está hecho: se recalcula solo lo que depende del texto (WER con números normalizados, «rota»)
        ev = cache[clave]
        ev["wer"] = round(c.wer(texto, ev["asr_texto"]), 3)
        ev["rota"] = es_rota(ev, len(c.aw.normalize_text(texto)))
        return ev
    a, sr = c.vb.read_wav_mono(wav)
    asr = c.transcribir(a, sr)
    tokens = c.acento_tokens(a, sr, asr["chunks"], texto)  # palabras del texto pedido, con los tiempos de lo que oyó Whisper
    tokens_asr = c.acento_tokens(a, sr, asr["chunks"])  # palabras tal como las escribió Whisper
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
        "tokens_asr": tokens_asr,
        **c.f0_stats(a, sr),
    }
    ev["rota"] = es_rota(ev, len(n_pal))
    cache[clave] = ev
    return ev


def main() -> None:
    quiero = set(sys.argv[1:])
    out = c.out_dir()
    ids = sorted(p.name[: -len("_frase1.wav")] for p in out.glob("*_frase1.wav"))
    cache_p = c.work_dir() / "muestras_cache.json"
    cache = c.leer_json(cache_p) if cache_p.exists() else {}
    medidas: dict = {}
    print(f"{'id':20s} {'WER':>5s} {'F0med':>6s} {'rango st':>8s} {'desv st':>7s} {'dur total':>9s} {'nθ/ns':>7s} {'Δ s-θ':>6s} {'p':>7s} {'Δ con sonda':>12s} rotas")
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
        sonda = None
        if (out / f"{cid}_sonda.wav").exists():  # frase extra, densa en z/ce/ci y s, solo para tener más palabras en el indicio de acento
            sonda = {"n": "sonda", "tipo": "sonda de acento", **evaluar_wav(out / f"{cid}_sonda.wav", TEXTO_SONDA, cache)}
            c.guardar_json(cache_p, cache)
        ac = c.acento_resumen(c.juntar_tokens([f["tokens"] for f in frases]))
        ac_sonda = c.acento_resumen(c.juntar_tokens([f["tokens"] for f in frases] + ([sonda["tokens"]] if sonda else [])))
        ac_asr = c.acento_resumen(c.juntar_tokens([f["tokens_asr"] for f in frases]))
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
            "acento_asr_literal": ac_asr,
            "acento_con_sonda": ac_sonda if sonda else None,
            "sonda": {k: v for k, v in sonda.items() if k not in ("tokens", "tokens_asr")} if sonda else None,
            "frases_rotas": [f["n"] for f in frases if f["rota"]],
            "frases": [{k: v for k, v in f.items() if k not in ("tokens", "tokens_asr")} for f in frases],
            "referencia": ref,
        }
        medidas[cid] = m
        p = ac["p_mann_whitney"]
        print(f"{cid:20s} {m['wer_medio']:5.2f} {m['f0_mediana_hz']:6.0f} {m['f0_rango_st_medio']:8.1f} {m['f0_desv_st_medio']:7.1f} {m['duracion_total_s']:9.1f} "
              f"{ac['n_theta']:3d}/{ac['n_s']:<3d} {str(ac['delta_s_menos_theta_db']):>6s} {('%.4f' % p) if p is not None else '-':>7s} "
              f"{('%s (n %d)' % (ac_sonda['delta_s_menos_theta_db'], ac_sonda['n_theta'])) if sonda else '':>12s} {m['frases_rotas'] or ''}")
    previo = c.leer_json(out / "medidas.json") if (out / "medidas.json").exists() else {}
    previo.update(medidas)
    c.guardar_json(out / "medidas.json", previo)
    repo = Path(__file__).resolve().parent / "resultados"
    repo.mkdir(exist_ok=True)
    c.guardar_json(repo / "medidas.json", previo)
    print("->", out / "medidas.json")


if __name__ == "__main__":
    main()
