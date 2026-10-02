"""Transcribe varios WAV seguidos (CPU) con tiempos por palabra: un JSON por cada entrada.

    cd spikes/voz/qwen3
    uv run python ../common/transcribir_varios.py a.wav b.wav     # escribe a.json y b.json junto a cada WAV
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asr_whisper as asr  # noqa: E402
import vozbench as vb  # noqa: E402

for arg in sys.argv[1:]:
    src = Path(arg)
    audio, sr = vb.read_wav_mono(src)
    t0 = time.perf_counter()
    out = asr.transcribe(audio, sr, words=True)
    dst = src.with_suffix(".json")
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{src.name}: {len(audio) / sr:.0f} s de audio transcritos en {time.perf_counter() - t0:.0f} s -> {dst.name}", flush=True)
