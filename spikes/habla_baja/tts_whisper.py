"""Genera habla SUSURRADA con Qwen3-TTS-12Hz-1.7B-VoiceDesign (Apache-2.0) para el corpus C2 (condición `whisper_tts`).

Se ejecuta en el entorno de `engines/tts-qwen3` (torch + qwen-tts), con el candado de GPU:

    uv run --directory engines/tts-qwen3 --frozen python ../../spikes/habla_baja/tts_whisper.py

Lee las referencias de `c2/manifest.json` (condición n20), sintetiza cada texto con una instrucción de voz susurrada y
guarda `c2/tts_whisper/<uid>.wav` a 16 kHz mono. No hay una voz de referencia susurrada con licencia libre: se usa el
control por lenguaje natural del modelo (VoiceDesign). Es habla SINTÉTICA susurrada, no una persona susurrando (README).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

APP = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "InstantTraductor"
WORK = APP / "spikes" / "habla_baja"
MODEL = APP / "models" / "qwen3-tts-12hz-1.7b-voicedesign"
INSTRUCT = (
    "A person whispering very softly and breathily, with no voiced pitch, like whispering a secret "
    "right next to someone's ear. Quiet, airy, intimate whisper."
)


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "traduccion"))
    from gpu_lock import gpu_lock

    manifest = json.loads((WORK / "c2" / "manifest.json").read_text("utf-8"))
    items = [(m["uid"], m["ref"]) for m in manifest if m["cond"] == "n20"]
    out_dir = WORK / "c2" / "tts_whisper"
    out_dir.mkdir(parents=True, exist_ok=True)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(items)
    with gpu_lock():
        import soxr
        import torch
        from qwen_tts import Qwen3TTSModel

        model = Qwen3TTSModel.from_pretrained(str(MODEL), device_map="cuda:0", dtype=torch.bfloat16)
        t0 = time.perf_counter()
        for uid, ref in items[:limit]:
            dest = out_dir / f"{uid}.wav"
            if dest.exists():
                continue
            text = ref.lower().capitalize()
            wavs, sr = model.generate_voice_design(text=text, language="English", instruct=INSTRUCT)
            x = np.asarray(wavs[0], dtype=np.float32)
            if x.ndim > 1:
                x = x.mean(axis=-1)
            x = soxr.resample(x, sr, 16000).astype(np.float32)
            sf.write(str(dest), x, 16000, subtype="PCM_16")
            print(f"{uid}: {len(x) / 16000:.1f} s de audio ({time.perf_counter() - t0:.0f} s acumulados)", flush=True)
        del model
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
