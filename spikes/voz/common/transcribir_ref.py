"""Transcribe un WAV/MP3 (tramo) con Whisper-small en CPU y guarda texto + tiempos por palabra en JSON.

    cd spikes/voz/qwen3
    uv run python ../common/transcribir_ref.py <entrada.wav> <salida.json>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asr_whisper as asr  # noqa: E402
import vozbench as vb  # noqa: E402

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
audio, sr = vb.read_wav_mono(src)
t0 = time.perf_counter()
out = asr.transcribe(audio, sr, words=True)
print(f"transcrito en {time.perf_counter() - t0:.1f} s (CPU)")
dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(out["text"][:1500])
