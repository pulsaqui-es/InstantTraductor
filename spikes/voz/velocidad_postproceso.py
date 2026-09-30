"""¿Se puede pedir 1,1x y 1,25x de velocidad? Control por post-proceso (time-stretch en streaming) sobre el PCM de los candidatos.

Ni Qwen3-TTS Base ni Chatterbox tienen un parámetro de velocidad (ver README): la vía fiable es estirar el PCM que sale del motor.
Este script mide, para dos algoritmos con API de streaming (solo CPU, sin GPU ni candado):
  - TDHS (Time-Domain Harmonic Scaling, biblioteca C «stretch» de audiostretchy; la familia de Sonic),
  - WSOLA (audiotsm, NumPy),
la exactitud del factor, el coste de CPU, y la latencia que añaden al primer audio con chunks del tamaño que emite cada motor.
Escribe los WAV estirados en %LOCALAPPDATA%\\InstantTraductor\\spikes\\voz\\muestras\\velocidad\\ para escucharlos.

    cd spikes/voz
    uv run python velocidad_postproceso.py A_qwen3_01.wav B_chatterbox_01.wav
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "common"))
import vozbench as vb  # noqa: E402

CHUNKS_MS = {"qwen3_cs1_83ms": 83, "chatterbox_p5_200ms": 200, "qwen3_cs4_333ms": 333, "qwen3_cs8_667ms": 667}
FACTORES = [1.10, 1.25]


def stretch_tdhs_stream(x: np.ndarray, sr: int, speed: float, chunk: int):
    """Streaming con la biblioteca C «stretch». Devuelve (audio, tiempo_primer_chunk_s, entrada_consumida_hasta_primera_salida)."""
    from audiostretchy.stretch import TDHSAudioStretch

    ratio = 1.0 / speed  # ratio > 1 alarga; la velocidad 1,25x acorta a 0,8
    st = TDHSAudioStretch(sr // 333, sr // 55, 1, 0)  # mismos límites de frecuencia que audiostretchy por defecto
    pcm = np.clip(x * 32767.0, -32768, 32767).astype(np.int16)
    outs = []
    t_first = None
    consumed_at_first = None
    consumed = 0
    t_tot = 0.0
    for i in range(0, len(pcm), chunk):
        ch = np.ascontiguousarray(pcm[i : i + chunk])
        out = np.zeros(st.output_capacity(len(ch), ratio), dtype=np.int16)
        t0 = time.perf_counter()
        n = st.process_samples(ch, len(ch), out, ratio)
        dt = time.perf_counter() - t0
        t_tot += dt
        consumed += len(ch)
        if n > 0 and t_first is None:
            t_first, consumed_at_first = dt, consumed
        outs.append(out[:n].copy())
    tail = np.zeros(st.output_capacity(chunk, ratio) + 65536, dtype=np.int16)
    n = st.flush(tail)
    outs.append(tail[:n].copy())
    st.deinit()
    y = np.concatenate(outs).astype(np.float32) / 32768.0
    return y, t_first, consumed_at_first, t_tot


def stretch_wsola_stream(x: np.ndarray, sr: int, speed: float, chunk: int, frame_length: int = 512):
    from audiotsm import wsola
    from audiotsm.io.array import ArrayReader, ArrayWriter

    tsm = wsola(channels=1, speed=speed, frame_length=frame_length, analysis_hop=None, synthesis_hop=None, tolerance=None)
    writer = ArrayWriter(channels=1)
    t_first = None
    consumed_at_first = None
    consumed = 0
    t_tot = 0.0
    x32 = np.asarray(x, dtype=np.float32).reshape(1, -1)
    for i in range(0, x32.shape[1], chunk):
        ch = x32[:, i : i + chunk]
        t0 = time.perf_counter()
        reader = ArrayReader(ch)
        while not reader.empty:  # el buffer interno de WSOLA es pequeño: hay que vaciar el lector por tandas
            tsm.read_from(reader)
            tsm.write_to(writer)
        dt = time.perf_counter() - t0
        t_tot += dt
        consumed += ch.shape[1]
        if writer.data.shape[1] > 0 and t_first is None:
            t_first, consumed_at_first = dt, consumed
    t0 = time.perf_counter()
    tsm.flush_to(writer)
    t_tot += time.perf_counter() - t0
    return writer.data.reshape(-1).astype(np.float32), t_first, consumed_at_first, t_tot


def main() -> None:
    nombres = sys.argv[1:]
    if not nombres:
        print(__doc__)
        return
    salida = vb.samples_dir() / "velocidad"
    salida.mkdir(parents=True, exist_ok=True)
    res: dict = {"algoritmos": ["tdhs (audiostretchy/stretch, C)", "wsola (audiotsm, frame 512)"], "muestras": {}}
    for nombre in nombres:
        p = Path(nombre)
        if not p.exists():
            p = vb.samples_dir() / nombre
        x, sr = vb.read_wav_mono(p)
        dur = len(x) / sr
        filas = []
        for speed in FACTORES:
            for algo, fn in (("tdhs", stretch_tdhs_stream), ("wsola", stretch_wsola_stream)):
                for etiqueta, ms in CHUNKS_MS.items():
                    chunk = int(sr * ms / 1000)
                    y, t_first, consumed_first, t_tot = fn(x, sr, speed, chunk)
                    filas.append(
                        {
                            "velocidad": speed,
                            "algoritmo": algo,
                            "chunk": etiqueta,
                            "duracion_salida_s": round(len(y) / sr, 3),
                            "factor_real": round(dur / (len(y) / sr), 3),
                            "coste_cpu_ms_por_s_audio": round(t_tot / dur * 1000, 2),
                            "t_primer_chunk_ms": round((t_first or 0) * 1000, 3),
                            "entrada_hasta_primera_salida_ms": round((consumed_first or 0) / sr * 1000, 1),
                        }
                    )
                    if etiqueta == "qwen3_cs8_667ms":
                        vb.write_wav(salida / f"{p.stem}_x{speed:.2f}_{algo}.wav", y, sr)
        res["muestras"][p.name] = {"duracion_entrada_s": round(dur, 3), "pruebas": filas}
        print(f"\n{p.name} ({dur:.2f} s)")
        print(f"{'vel':>5} {'algo':>6} {'chunk':>20} {'factor real':>11} {'CPU ms/s':>9} {'1er chunk ms':>12} {'entrada hasta 1ª salida ms':>27}")
        for f in filas:
            print(f"{f['velocidad']:>5.2f} {f['algoritmo']:>6} {f['chunk']:>20} {f['factor_real']:>11.3f} {f['coste_cpu_ms_por_s_audio']:>9.2f} {f['t_primer_chunk_ms']:>12.3f} {f['entrada_hasta_primera_salida_ms']:>27.1f}")
    print("->", vb.save_json("velocidad_postproceso.json", res))


if __name__ == "__main__":
    main()
