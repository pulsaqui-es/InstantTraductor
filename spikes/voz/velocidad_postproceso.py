"""¿Se puede pedir 1,1x y 1,25x de velocidad? Control por post-proceso (time-stretch en streaming) sobre el PCM de los candidatos.

Ni Qwen3-TTS Base ni Chatterbox tienen un parámetro de velocidad (ver README): la vía fiable es estirar el PCM que sale del motor.
Este script mide, para dos algoritmos con API de streaming (solo CPU, sin GPU ni candado):
  - TDHS (Time-Domain Harmonic Scaling, biblioteca C «stretch» de audiostretchy; la familia de Sonic),
  - WSOLA (audiotsm, NumPy, trama de 512 muestras),
la exactitud del factor, el coste de CPU y el retraso que añaden al primer audio cuando se les da el PCM por chunks del tamaño
que emite cada motor. Escribe los WAV estirados en %LOCALAPPDATA%\\InstantTraductor\\spikes\\voz\\muestras\\velocidad\\ para oírlos.

    cd spikes/voz
    uv run python velocidad_postproceso.py A_qwen3_01.wav B_chatterbox_01.wav
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "common"))
import vozbench as vb  # noqa: E402

CHUNKS_MS = {"qwen3_cs1_83ms": 83, "chatterbox_p5_200ms": 200, "qwen3_cs4_333ms": 333, "qwen3_cs8_667ms": 667}
FACTORES = [1.10, 1.25]


class Seguimiento:
    """Anota, tras cada chunk, cuánto audio ha salido frente al que debería haber salido (entrada/velocidad)."""

    def __init__(self, speed: float):
        self.speed = speed
        self.consumed = 0
        self.produced = 0
        self.t_first = None
        self.out_first = None
        self.lag_first_ms = None
        self.lag_max_ms = 0.0
        self.t_tot = 0.0

    def paso(self, n_in: int, n_out: int, dt: float, sr: int) -> None:
        self.consumed += n_in
        self.produced += n_out
        self.t_tot += dt
        lag = (self.consumed / self.speed - self.produced) / sr * 1000
        if self.t_first is None:
            self.t_first, self.out_first, self.lag_first_ms = dt, n_out / sr * 1000, lag
        self.lag_max_ms = max(self.lag_max_ms, lag)


def stretch_tdhs_stream(x: np.ndarray, sr: int, speed: float, chunk: int):
    """Streaming con la biblioteca C «stretch» (audiostretchy)."""
    from audiostretchy.stretch import TDHSAudioStretch

    ratio = 1.0 / speed  # ratio > 1 alarga; la velocidad 1,25x acorta a 0,8
    st = TDHSAudioStretch(sr // 333, sr // 55, 1, 0)  # mismos límites de frecuencia que audiostretchy por defecto
    pcm = np.clip(x * 32767.0, -32768, 32767).astype(np.int16)
    seg = Seguimiento(speed)
    outs = []
    for i in range(0, len(pcm), chunk):
        ch = np.ascontiguousarray(pcm[i : i + chunk])
        out = np.zeros(st.output_capacity(len(ch), ratio), dtype=np.int16)
        t0 = time.perf_counter()
        n = st.process_samples(ch, len(ch), out, ratio)
        seg.paso(len(ch), n, time.perf_counter() - t0, sr)
        outs.append(out[:n].copy())
    tail = np.zeros(st.output_capacity(chunk, ratio) + 65536, dtype=np.int16)
    n = st.flush(tail)
    outs.append(tail[:n].copy())
    st.deinit()
    return np.concatenate(outs).astype(np.float32) / 32768.0, seg


def stretch_wsola_stream(x: np.ndarray, sr: int, speed: float, chunk: int, frame_length: int = 512):
    """Streaming con WSOLA (audiotsm)."""
    from audiotsm import wsola
    from audiotsm.io.array import ArrayReader, ArrayWriter

    tsm = wsola(channels=1, speed=speed, frame_length=frame_length, analysis_hop=None, synthesis_hop=None, tolerance=None)
    writer = ArrayWriter(channels=1)
    seg = Seguimiento(speed)
    x32 = np.asarray(x, dtype=np.float32).reshape(1, -1)
    for i in range(0, x32.shape[1], chunk):
        ch = x32[:, i : i + chunk]
        antes = writer.data.shape[1]
        t0 = time.perf_counter()
        reader = ArrayReader(ch)
        while not reader.empty:  # el buffer interno de WSOLA es pequeño: hay que vaciar el lector por tandas
            tsm.read_from(reader)
            tsm.write_to(writer)
        seg.paso(ch.shape[1], writer.data.shape[1] - antes, time.perf_counter() - t0, sr)
    tsm.flush_to(writer)
    return writer.data.reshape(-1).astype(np.float32), seg


def main() -> None:
    nombres = sys.argv[1:]
    if not nombres:
        print(__doc__)
        return
    salida = vb.samples_dir() / "velocidad"
    salida.mkdir(parents=True, exist_ok=True)
    res: dict = {"algoritmos": ["tdhs (audiostretchy/stretch, C)", "wsola (audiotsm, trama 512)"], "muestras": {}}
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
                    y, seg = fn(x, sr, speed, chunk)
                    filas.append(
                        {
                            "velocidad": speed,
                            "algoritmo": algo,
                            "chunk": etiqueta,
                            "duracion_salida_s": round(len(y) / sr, 3),
                            "factor_real": round(dur / (len(y) / sr), 3),
                            "coste_cpu_ms_por_s_audio": round(seg.t_tot / dur * 1000, 2),
                            "t_primer_chunk_ms": round(seg.t_first * 1000, 3),
                            "audio_salido_en_primer_chunk_ms": round(seg.out_first, 1),
                            "audio_esperado_primer_chunk_ms": round(ms / speed, 1),
                            "retraso_tras_primer_chunk_ms": round(seg.lag_first_ms, 1),
                            "retraso_maximo_ms": round(seg.lag_max_ms, 1),
                        }
                    )
                    if etiqueta == "qwen3_cs8_667ms":
                        vb.write_wav(salida / f"{p.stem}_x{speed:.2f}_{algo}.wav", y, sr)
        res["muestras"][p.name] = {"duracion_entrada_s": round(dur, 3), "pruebas": filas}
        print(f"\n{p.name} ({dur:.2f} s)")
        print(f"{'vel':>5} {'algo':>6} {'chunk':>20} {'factor real':>11} {'CPU ms/s':>9} {'cómputo 1er chunk ms':>21} {'salió/esperado 1er chunk ms':>28} {'retraso máx. ms':>16}")
        for f in filas:
            print(f"{f['velocidad']:>5.2f} {f['algoritmo']:>6} {f['chunk']:>20} {f['factor_real']:>11.3f} {f['coste_cpu_ms_por_s_audio']:>9.2f} {f['t_primer_chunk_ms']:>21.3f} {f['audio_salido_en_primer_chunk_ms']:>12.1f} /{f['audio_esperado_primer_chunk_ms']:>6.1f} {f['retraso_maximo_ms']:>16.1f}")
    print("->", vb.save_json("velocidad_postproceso.json", res))


if __name__ == "__main__":
    main()
