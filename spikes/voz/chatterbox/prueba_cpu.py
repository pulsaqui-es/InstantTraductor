"""Prueba funcional en CPU (sin GPU, sin candado) del envoltorio de Chatterbox es-ES: carga, síntesis completa y streaming.

    cd spikes/voz/chatterbox
    uv run python prueba_cpu.py <referencia.wav> [carpeta_salida]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import vozbench as vb  # noqa: E402
import cb_es  # noqa: E402

ref = Path(sys.argv[1])
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
out.mkdir(parents=True, exist_ok=True)

t0 = time.perf_counter()
m = cb_es.ChatterboxEs(vb.models_dir() / vb.CHATTERBOX_MODEL_DIR, device="cpu")
print(f"carga CPU: {time.perf_counter() - t0:.1f} s")
print("S3Gen missing:", m.load_report["s3gen_missing"][:10], "| unexpected:", m.load_report["s3gen_unexpected"][:10])
t0 = time.perf_counter()
m.prepare_conditionals(ref)
print(f"referencia: {time.perf_counter() - t0:.1f} s")

texto = "Vale, ¿vosotros venís en coche o cogéis el autobús?"
t0 = time.perf_counter()
wav = m.synthesize(texto, seed=1)
print(f"síntesis completa: {len(wav) / m.sr:.2f} s de audio en {time.perf_counter() - t0:.1f} s (CPU) | pico {np.abs(wav).max():.2f}")
vb.write_wav(out / "cpu_completa.wav", wav, m.sr)

t0 = time.perf_counter()
chunks, tt = [], []
for c in m.stream(texto, seed=1, first_chunk_tokens=10, chunk_tokens=15):
    chunks.append(c["audio"])
    tt.append(time.perf_counter() - t0)
    print(f"  chunk {len(chunks)}: {len(c['audio']) / m.sr:.2f} s de audio, tokens {c['n_tokens']}, a los {tt[-1]:.1f} s")
s = np.concatenate(chunks)
print(f"streaming: {len(s) / m.sr:.2f} s de audio (completa: {len(wav) / m.sr:.2f} s)")
vb.write_wav(out / "cpu_streaming.wav", s, m.sr)
