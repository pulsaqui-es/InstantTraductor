"""Añade al manifiesto de C2 las condiciones con susurro de Qwen3-TTS (`tts_whisper.py` ya ha generado los WAV).

  whisper_tts     habla susurrada sintetizada, a -30 dBFS
  whisper_tts_q   la misma, a -42 dBFS
  whisper_tts_mus la misma, a -36 dBFS sobre música a -34 dBFS (SNR -2 dB)
"""

from __future__ import annotations

import json
import random

import numpy as np

from build_c2 import MARGIN_S, SEED, frame_clip, load_music, music_slice, noise_floor, trim_silence
from common import C2_DIR, DL_DIR, SR, read_wav, scale_to_rms, write_wav
from dsp_tools import mix_at


def main() -> None:
    rng = np.random.default_rng(SEED + 2)
    random.Random(SEED)
    manifest = json.loads((C2_DIR / "manifest.json").read_text("utf-8"))
    manifest = [m for m in manifest if not m["cond"].startswith("whisper_tts")]
    refs = {m["uid"]: m["ref"] for m in manifest if m["cond"] == "n20"}
    music_dir = DL_DIR / "music"
    files = sorted(music_dir.glob("*.ogg")) + sorted(music_dir.glob("*.flac")) + sorted(music_dir.glob("*.wav"))
    tracks = load_music(files[0::2], rng)
    n_done = 0
    for wav in sorted((C2_DIR / "tts_whisper").glob("*.wav")):
        uid = wav.stem
        if uid not in refs:
            continue
        x = trim_silence(read_wav(wav))
        for cond, lvl in (("whisper_tts", -30.0), ("whisper_tts_q", -42.0)):
            clip, t0, t1 = frame_clip(scale_to_rms(x, lvl), rng)
            write_wav(C2_DIR / f"{cond}__{uid}.wav", clip)
            manifest.append({"clip": f"{cond}__{uid}.wav", "cond": cond, "uid": uid, "ref": refs[uid], "speech_start": t0, "speech_end": t1, "level_dbfs": lvl})
        n = len(x) + int(2 * MARGIN_S * SR)
        sp_full = np.concatenate([np.zeros(int(MARGIN_S * SR), np.float32), scale_to_rms(x, -36.0), np.zeros(int(MARGIN_S * SR), np.float32)])
        mixed = mix_at(sp_full, music_slice(tracks, n, rng), -36.0, -34.0) + noise_floor(n, rng)
        write_wav(C2_DIR / f"whisper_tts_mus__{uid}.wav", mixed.astype(np.float32))
        manifest.append({"clip": f"whisper_tts_mus__{uid}.wav", "cond": "whisper_tts_mus", "uid": uid, "ref": refs[uid], "speech_start": MARGIN_S, "speech_end": MARGIN_S + len(x) / SR, "level_dbfs": -36.0})
        n_done += 1
    (C2_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    print(f"{n_done} enunciados susurrados añadidos; manifiesto: {len(manifest)} clips")


if __name__ == "__main__":
    main()
