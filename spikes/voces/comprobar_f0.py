"""Contrasta la F0 del estimador por autocorrelación (`common.f0_stats`) con un segundo estimador (YIN) en unas tomas y referencias.

Sirve para descartar errores de octava: VoxCPM2 devolvió muchas tomas con F0 de 108-160 Hz aunque se pedía «mujer», y hay que saber si son graves de
verdad o un fallo del estimador. Resultado (2026-10-01): YIN da lo mismo o hasta un 15 % más; las tomas graves lo son (129-171 Hz), y los controles
(SLR61: hombre 112/128 Hz, mujer 237/235 Hz) salen donde deben.

    uv run --project spikes/voces python spikes/voces/comprobar_f0.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402


def yin_f0(a: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 450.0, frame_s: float = 0.04, hop_s: float = 0.01, thr: float = 0.15):
    """F0 mediana por YIN (diferencia acumulada normalizada, primer valle bajo el umbral); (None, n) si hay menos de 10 tramas sonoras."""
    n = int(frame_s * sr)
    hop = int(hop_s * sr)
    tmin, tmax = int(sr / fmax), int(sr / fmin)
    a = np.asarray(a, dtype=np.float64)
    gate = max(10 ** (-45 / 20), 0.05 * np.percentile(np.abs(a), 99))
    out = []
    for i in range(0, len(a) - n - tmax, hop):
        x = a[i : i + n + tmax]
        if np.sqrt(np.mean(x[:n] ** 2)) < gate:
            continue
        d = np.zeros(tmax + 1)
        for tau in range(1, tmax + 1):
            diff = x[:n] - x[tau : tau + n]
            d[tau] = np.sum(diff * diff)
        cm = np.ones_like(d)
        cs = np.cumsum(d[1:])
        cm[1:] = d[1:] * np.arange(1, tmax + 1) / np.maximum(cs, 1e-12)
        for t in range(tmin, tmax):
            if cm[t] < thr and cm[t] <= cm[t + 1]:
                out.append(sr / t)
                break
    v = np.array(out)
    return (float(np.median(v)), len(v)) if len(v) > 10 else (None, len(v))


def main() -> None:
    out = c.out_dir()
    slr = c.vb.data_root() / "spikes" / "voz" / "ref" / "raw" / "es_weather_messages" / "es-es"
    dv = out / "_trabajo" / "dis_vox"
    casos = [("SLR61 hombre 02484", slr / "esw_02484_00122340186.wav"), ("SLR61 mujer 03397", slr / "esw_03397_01415681039.wav")]
    casos += [(n, dv / f"{n}.wav") for n in ["es-f-dis-03_distincion_es_t1", "es-f-dis-03_distincion_es_t2", "es-f-dis-07_distincion_es_t1",
                                             "es-f-dis-07_distincion_es_t3", "es-f-dis-01_distincion_es_t1", "es-f-dis-01_distincion_es_t3",
                                             "es-f-dis-05_distincion_es_t1", "es-f-dis-05_distincion_es_t2"]]
    casos += [(f"{n}_ref", out / f"{n}_ref.wav") for n in ["es-f-dvx-06", "es-f-dvx-08", "es-f-dvx-01", "es-f-est-04", "es-f-dis-02", "es-f-dis-04"]]
    for nombre, p in casos:
        a, sr = c.vb.read_wav_mono(p)
        a = a[: int(8 * sr)]
        f0y, n = yin_f0(a, sr)
        print(f"{nombre:36s} autocorrelación {c.f0_stats(a, sr).get('f0_mediana_hz')} Hz | YIN {None if f0y is None else round(f0y)} Hz (n={n})")


if __name__ == "__main__":
    main()
