"""Transcribe todos los WAV de una o más carpetas (clips cortos) con Whisper-small en CPU y deja un .json junto a cada WAV.

    cd spikes/voz/qwen3
    uv run python ../common/transcribir_lote.py <carpeta1> [<carpeta2> ...]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asr_whisper as asr  # noqa: E402
import vozbench as vb  # noqa: E402

for carpeta in sys.argv[1:]:
    t0 = time.perf_counter()
    wavs = sorted(Path(carpeta).glob("*.wav"))
    for i, wavp in enumerate(wavs):
        jp = wavp.with_suffix(".json")
        if jp.exists():
            continue
        audio, sr = vb.read_wav_mono(wavp)
        out = asr.transcribe(audio, sr, words=True)
        jp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        if i % 15 == 0:
            print(f"{carpeta}: {i + 1}/{len(wavs)} ({time.perf_counter() - t0:.0f} s)", flush=True)
    print(f"{carpeta}: terminado en {time.perf_counter() - t0:.0f} s", flush=True)
