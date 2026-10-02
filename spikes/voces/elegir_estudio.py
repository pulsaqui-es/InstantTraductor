"""Camino B: criba hablantes femeninas de VoxPopuli es (CC0) y extrae tramos de 8-10 s con su transcripción.

    uv run --project spikes/voces python spikes/voces/elegir_estudio.py cribar --max-hablantes 14
    uv run --project spikes/voces python spikes/voces/elegir_estudio.py tramos --hablante 135491 [--n 3]

`cribar`: de cada hablante femenina con más material (tras `voxpopuli_explorar.py descargar/resumen`) toma hasta 4 segmentos largos,
los transcribe con Whisper large-v3-turbo (CPU, tiempos por palabra) y mide F0, suelo de ruido, ritmo y el indicio de acento
(`distincion.py`) agrupando todos los segmentos del hablante. Escribe `cribado_hablantes.json` y `cribado_asr.json` (caché del ASR).
`tramos`: para un hablante, lista ventanas de 8-10 s entre pausas reales (>= 0,15 s) con su texto, para elegir una a mano.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import voxpopuli_explorar as vx  # noqa: E402


def cargar_audio(ids: set[str]) -> dict[str, np.ndarray]:
    import pyarrow.parquet as pq

    out: dict[str, np.ndarray] = {}
    for f in vx.FICHEROS:
        pf = pq.ParquetFile(vx.carpeta() / f)
        for batch in pf.iter_batches(batch_size=32, columns=["audio_id", "audio"]):
            d = batch.to_pydict()
            for i, aid in enumerate(d["audio_id"]):
                if aid in ids:
                    a, sr = sf.read(io.BytesIO(d["audio"][i]["bytes"]), dtype="float32", always_2d=False)
                    out[aid] = (a if a.ndim == 1 else a.mean(axis=1), sr)  # type: ignore[assignment]
    return out


def suelo_ruido_db(a: np.ndarray, sr: int) -> tuple[float, float]:
    n = int(0.02 * sr)
    fr = a[: len(a) // n * n].reshape(-1, n)
    e = 10 * np.log10(np.mean(fr**2, axis=1) + 1e-12)
    return float(np.percentile(e, 10)), float(np.percentile(e, 90) - np.percentile(e, 10))


def cribar(max_hablantes: int, por_hablante: int, min_s: float) -> None:
    carp = vx.carpeta()
    segs = c.leer_json(carp / "segmentos.json")
    res = c.leer_json(carp / "resumen_hablantes.json")
    mujeres = [k for k, v in res.items() if str(v["gender"]).lower().startswith("f") and v["dur"] >= min_s]
    mujeres.sort(key=lambda k: -res[k]["dur"])
    mujeres = mujeres[:max_hablantes]
    elegidos: dict[str, list[dict]] = {}
    for k in mujeres:
        cand = [s for s in segs if s["speaker_id"] == k and 12.0 <= s["dur_s"] <= 28.0 and s["gold"]]
        cand.sort(key=lambda s: -s["dur_s"])
        elegidos[k] = cand[:por_hablante]
    ids = {s["audio_id"] for lst in elegidos.values() for s in lst}
    print(len(mujeres), "hablantes,", len(ids), "segmentos a transcribir", flush=True)
    audio = cargar_audio(ids)
    asr_cache_p = carp / "cribado_asr.json"
    asr_cache = c.leer_json(asr_cache_p) if asr_cache_p.exists() else {}
    resumen = {}
    for k in mujeres:
        f0s, ruido, snrs, palabras, dur_total, tokens = [], [], [], 0, 0.0, []
        for s in elegidos[k]:
            a, sr = audio[s["audio_id"]]
            if s["audio_id"] not in asr_cache:
                asr_cache[s["audio_id"]] = c.transcribir(a, sr)
                c.guardar_json(asr_cache_p, asr_cache)
            asr = asr_cache[s["audio_id"]]
            tokens.append(c.acento_tokens(a, sr, asr["chunks"]))
            st = c.f0_stats(a, sr)
            f0s.append(st)
            r, snr = suelo_ruido_db(a, sr)
            ruido.append(r)
            snrs.append(snr)
            palabras += len(asr["chunks"])
            dur_total += len(a) / sr
        ac = c.acento_resumen(c.juntar_tokens(tokens))
        resumen[k] = {"segmentos": [s["audio_id"] for s in elegidos[k]], "dur_total_s": round(dur_total, 1),
                      "f0_mediana_hz": round(float(np.median([x["f0_mediana_hz"] for x in f0s if "f0_mediana_hz" in x])), 1),
                      "f0_rango_st": round(float(np.median([x["f0_rango_p10_p90_st"] for x in f0s if "f0_rango_p10_p90_st" in x])), 2),
                      "suelo_ruido_db": round(float(np.median(ruido)), 1), "snr_aprox_db": round(float(np.median(snrs)), 1),
                      "palabras_por_s": round(palabras / dur_total, 2), "acento": ac}
        r = resumen[k]
        print(f"{k}: {r['dur_total_s']:5.0f} s | F0 {r['f0_mediana_hz']:5.0f} Hz rango {r['f0_rango_st']:4.1f} st | ruido {r['suelo_ruido_db']:6.1f} dB (SNR {r['snr_aprox_db']:4.1f}) | "
              f"{r['palabras_por_s']:.2f} pal/s | Δ(s−θ) {ac['delta_s_menos_theta_db']} dB (n_θ={ac['n_theta']}, n_s={ac['n_s']}, p={ac['p_mann_whitney']})", flush=True)
        c.guardar_json(carp / "cribado_hablantes.json", resumen)


def tramos(hablante: str, n: int, minimo: float, maximo: float) -> None:
    carp = vx.carpeta()
    segs = {s["audio_id"]: s for s in c.leer_json(carp / "segmentos.json")}
    asr_cache = c.leer_json(carp / "cribado_asr.json")
    cand = []
    for aid, asr in asr_cache.items():
        if segs[aid]["speaker_id"] != hablante:
            continue
        w = asr["chunks"]
        for i in range(len(w)):
            ini = w[i]["timestamp"][0]
            antes = ini - (w[i - 1]["timestamp"][1] if i else ini - 1.0)
            if i and antes < 0.15:
                continue  # el tramo debe empezar tras una pausa real
            for j in range(i + 8, len(w)):
                fin = w[j]["timestamp"][1]
                dur = fin - ini
                if dur > maximo:
                    break
                despues = (w[j + 1]["timestamp"][0] - fin) if j + 1 < len(w) else 1.0
                if dur >= minimo and despues >= 0.15:
                    texto = "".join(x["text"] for x in w[i : j + 1]).strip()
                    cand.append({"audio_id": aid, "t0": round(ini, 2), "t1": round(fin, 2), "dur": round(dur, 2), "pausa_antes": round(antes, 2),
                                 "pausa_despues": round(despues, 2), "palabras": j - i + 1, "texto": texto})
    cand.sort(key=lambda x: -x["palabras"] / x["dur"] * 0 - min(x["pausa_antes"], 0.6) - min(x["pausa_despues"], 0.6))
    for x in cand[:n]:
        print(x)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("cribar")
    p.add_argument("--max-hablantes", type=int, default=14)
    p.add_argument("--por-hablante", type=int, default=4)
    p.add_argument("--min-s", type=float, default=400.0)
    t = sub.add_parser("tramos")
    t.add_argument("--hablante", required=True)
    t.add_argument("--n", type=int, default=10)
    t.add_argument("--min", type=float, default=8.0)
    t.add_argument("--max", type=float, default=10.2)
    args = ap.parse_args()
    if args.cmd == "cribar":
        cribar(args.max_hablantes, args.por_hablante, args.min_s)
    else:
        tramos(args.hablante, args.n, args.min, args.max)


if __name__ == "__main__":
    main()
