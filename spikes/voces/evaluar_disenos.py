"""Evalúa en CPU las referencias diseñadas (ASR con Whisper large-v3-turbo, F0, duración, indicio de acento) y elige la mejor toma.

    uv run --project spikes/voces python spikes/voces/evaluar_disenos.py                     # tabla de todas las tomas
    uv run --project spikes/voces python spikes/voces/evaluar_disenos.py --auto              # elige una toma por voz y ortografía y escribe <id>_ref.wav/.json
    uv run --project spikes/voces python spikes/voces/evaluar_disenos.py --elegir es-f-dis-01=es-f-dis-01_en_normal_t2

El `ref_text` de una referencia diseñada es el texto NORMAL con el que se generó (aunque a VoiceDesign se le enviara la reescritura con «th»).
Una toma de ortografía normal solo se acepta si Whisper la transcribe sin diferencias de palabras (WER 0): un `ref_text` que no coincide con el
audio estropea el modo ICL. Una toma «th» admite WER <= 0,20 porque Whisper confunde algunas /θ/ con /t/ o /d/ (ver README).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import disenos as d  # noqa: E402

DUR_MIN, DUR_MAX, DUR_IDEAL = 7.8, 10.6, 9.0
WER_MAX = {"normal": 0.0, "th": 0.20}


def evaluar_toma(wav: Path, texto: str, cache: dict) -> dict:
    clave = f"{wav.name}|{wav.stat().st_size}"
    if clave in cache:
        return cache[clave]
    a, sr = c.vb.read_wav_mono(wav)
    asr = c.transcribir(a, sr)
    tokens = c.acento_tokens(a, sr, asr["chunks"])
    ev = {
        "fichero": wav.name,
        "duracion_s": round(len(a) / sr, 2),
        "asr_texto": asr["text"],
        "wer": round(c.wer(texto, asr["text"]), 3),
        "tokens": tokens,
        "pico_dbfs": round(float(20 * np.log10(np.max(np.abs(a)) + 1e-12)), 1),
        "rms_dbfs": round(c.rms_dbfs(a), 1),
        **c.f0_stats(a, sr),
    }
    cache[clave] = ev
    return ev


def puntuacion(ev: dict, ort: str) -> float:
    """Mayor es mejor: dentro de rango de duración y de WER; luego acento (th) o expresividad (normal), y cercanía a 9 s."""
    if not (DUR_MIN <= ev["duracion_s"] <= DUR_MAX) or ev["wer"] > WER_MAX[ort]:
        return -1e9
    ac = c.acento_resumen(ev["tokens"]).get("delta_s_menos_theta_db")
    base = (ac if (ort == "th" and ac is not None) else 0.0) + 1.0 * ev.get("f0_rango_p10_p90_st", 0.0)
    return base - abs(ev["duracion_s"] - DUR_IDEAL)


def escribir_ref(salida: str, e: dict, ev: dict, dis_dir: Path) -> None:
    a, sr = c.vb.read_wav_mono(dis_dir / e["fichero"])
    a = c.normalizar(c.recortar_silencios(a, sr), sr)
    c.vb.write_wav(c.out_dir() / f"{salida}_ref.wav", a, sr)
    voz = next(x for x in d.DISENOS if x["id"] == e["id"])
    ort = e.get("ortografia", "normal")
    meta = {"voice_id": salida, "name": f"{voz['nombre']} (diseñada{', ortografía th' if ort == 'th' else ''})", "gender": "f",
            "source": "Diseñada con Qwen3-TTS-12Hz-1.7B-VoiceDesign (Apache-2.0); descripción: " + e["instruct"]
                      + (" | texto enviado al modelo con z/ce/ci reescritos como «th»: " + e["texto_enviado"] if ort == "th" else ""),
            "license": "Apache-2.0 (modelo); audio sintético sin voz humana de origen",
            "ref_text": e["texto"], "duracion_s": round(len(a) / sr, 2), "fichero_origen": e["fichero"], "semilla": e["semilla"], "ortografia": ort,
            "asr_texto": ev["asr_texto"], "wer_ref": ev["wer"],
            "indicio_acento_db": c.acento_resumen(ev["tokens"]).get("delta_s_menos_theta_db"), **{k: ev[k] for k in ev if k.startswith("f0_")}}
    c.guardar_json(c.out_dir() / f"{salida}_ref.json", meta)
    print(f"{salida}: referencia escrita ({meta['duracion_s']} s, WER {ev['wer']}, Δ {meta['indicio_acento_db']}) <- {e['fichero']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--elegir", default="", help="id_salida=fichero(sin .wav) separados por comas")
    ap.add_argument("--auto", action="store_true", help="una toma por voz y ortografía según la puntuación")
    args = ap.parse_args()

    dis_dir = c.work_dir("dis")
    log = c.leer_json(dis_dir / "disenos_log.json")
    cache_path = dis_dir / "eval_cache.json"
    cache = c.leer_json(cache_path) if cache_path.exists() else {}
    evs: list[tuple[dict, dict]] = []
    for e in log["entradas"]:
        wav = dis_dir / e["fichero"]
        if not wav.exists():
            continue
        ev = evaluar_toma(wav, e["texto"], cache)
        evs.append((e, ev))
    c.guardar_json(cache_path, cache)

    print(f"{'toma':32s} {'dur':>5s} {'WER':>5s} {'F0med':>6s} {'rango st':>8s} {'ΔT':>3s} {'Δ s-θ':>6s} {'punt':>7s}")
    grupos: dict[tuple[str, str], list] = {}
    for e, ev in evs:
        ort = e.get("ortografia", "normal")
        grupos.setdefault((e["id"], ort), []).append((e, ev))
    for (vid, ort), lst in sorted(grupos.items()):
        for e, ev in lst:
            ac = c.acento_resumen(ev["tokens"])
            print(f"{ev['fichero']:32s} {ev['duracion_s']:5.1f} {ev['wer']:5.2f} {ev.get('f0_mediana_hz', float('nan')):6.0f} "
                  f"{ev.get('f0_rango_p10_p90_st', float('nan')):8.1f} {ac['n_theta']:3d} {str(ac['delta_s_menos_theta_db']):>6s} {puntuacion(ev, ort):7.1f}")
        ac = c.acento_resumen(c.juntar_tokens([ev["tokens"] for _, ev in lst]))
        print(f"   -> {vid} [{ort}] agrupado: n_θ={ac['n_theta']} n_s={ac['n_s']} Δ(s−θ)={ac['delta_s_menos_theta_db']} dB p={ac['p_mann_whitney']}")

    if args.auto:
        for (vid, ort), lst in sorted(grupos.items()):
            mejor = max(lst, key=lambda t: puntuacion(t[1], ort))
            if puntuacion(mejor[1], ort) < -1e8:
                print(f"AVISO {vid} [{ort}]: ninguna toma cumple duración y WER; no se escribe referencia")
                continue
            escribir_ref(vid + ("th" if ort == "th" else ""), mejor[0], mejor[1], dis_dir)
    for par in [p for p in args.elegir.split(",") if p]:
        salida, stem = par.split("=")
        e, ev = next((e, ev) for e, ev in evs if Path(e["fichero"]).stem == stem)
        escribir_ref(salida, e, ev, dis_dir)


if __name__ == "__main__":
    main()
