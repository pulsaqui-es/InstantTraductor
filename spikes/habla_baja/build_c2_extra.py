"""Condiciones más duras del corpus C2 (se añaden al `manifest.json` con los mismos 40 enunciados).

  mus_c       habla a -32 con música a -30 (SNR -2 dB)
  mus_d       habla a -36 con música a -30 (SNR -6 dB)
  sfx_a       habla a -28 sobre efectos (explosiones, disparos, pasos, viento...) a -28 (SNR 0 dB)
  reverb      habla a -30 con reverberación de sala grande (RT60 ≈ 0,7 s, RIR sintética)
  whisper_mus susurro por DSP a -36 sobre música a -34 (SNR -2 dB): lo más difícil
  hesitate    habla a -26 con dos pausas de 0,65 s dentro del enunciado (dudas, «mmm...»), para la segmentación
  stretch4    cuatro vocales alargadas ×4 (WSOLA), habla a -30

Uso: `uv run python build_c2_extra.py` (después de `build_c2.py`).
"""

from __future__ import annotations

import json
import random

import numpy as np
from scipy import signal

from build_c2 import (
    MARGIN_S,
    N_TEST_CLEAN,
    SEED,
    frame_clip,
    load_music,
    load_test_clean,
    music_slice,
    noise_floor,
    split_fixture,
    trim_silence,
)
from common import C2_DIR, DL_DIR, SR, scale_to_rms, write_wav
from dsp_tools import effects_track, elongate_words, mix_at, whisperize


def synthetic_rir(rng: np.random.Generator, rt60: float = 0.7, dry_db: float = -3.0) -> np.ndarray:
    n = int(rt60 * 1.3 * SR)
    t = np.arange(n) / SR
    tail = rng.standard_normal(n) * 10 ** (-3 * t / rt60)  # -60 dB a los rt60 s
    tail[: int(0.012 * SR)] *= 0.1
    rir = tail / np.sqrt(np.sum(tail**2))
    rir[0] += 10 ** (dry_db / 20) * 1.0
    return rir.astype(np.float32)


def insert_pauses(x: np.ndarray, n: int, pause_s: float, rng: np.random.Generator) -> np.ndarray:
    """Inserta `n` pausas de `pause_s` s en los mínimos de energía del enunciado (entre palabras)."""
    frame = 160
    m = len(x) // frame
    e = np.sqrt(np.mean(x[: m * frame].reshape(m, frame) ** 2, axis=1))
    lo = int(0.15 * m)
    hi = int(0.85 * m)
    cands = np.argsort(e[lo:hi])[: max(8, m // 6)] + lo
    cuts: list[int] = []
    for c in rng.permutation(cands):
        if all(abs(int(c) - k) > int(0.8 * SR / frame) for k in cuts):
            cuts.append(int(c))
        if len(cuts) == n:
            break
    cuts.sort()
    parts, cur = [], 0
    for c in cuts:
        parts.append(x[cur : c * frame])
        parts.append(np.zeros(int(pause_s * SR), np.float32))
        cur = c * frame
    parts.append(x[cur:])
    return np.concatenate(parts)


def main() -> None:
    rng_py = random.Random(SEED)
    rng = np.random.default_rng(SEED + 1)
    utts = [(u, trim_silence(x), t) for u, x, t in split_fixture() + load_test_clean(N_TEST_CLEAN, rng_py)]
    music_dir = DL_DIR / "music"
    files = sorted(music_dir.glob("*.ogg")) + sorted(music_dir.glob("*.flac")) + sorted(music_dir.glob("*.wav"))
    mix_tracks = load_music(files[0::2], rng)
    manifest = json.loads((C2_DIR / "manifest.json").read_text("utf-8"))
    manifest = [m for m in manifest if m["cond"] not in {"mus_c", "mus_d", "sfx_a", "reverb", "whisper_mus", "hesitate", "stretch4"}]

    def add(cond: str, uid: str, clip: np.ndarray, ref: str, t0: float, t1: float, **extra: object) -> None:
        name = f"{cond}__{uid}.wav"
        write_wav(C2_DIR / name, clip)
        manifest.append({"clip": name, "cond": cond, "uid": uid, "ref": ref, "speech_start": t0, "speech_end": t1, **extra})

    def with_bg(utt: np.ndarray, bg: np.ndarray, sp_db: float, bg_db: float) -> tuple[np.ndarray, float, float]:
        n = len(utt) + int(2 * MARGIN_S * SR)
        sp_full = np.concatenate([np.zeros(int(MARGIN_S * SR), np.float32), scale_to_rms(utt, sp_db), np.zeros(int(MARGIN_S * SR), np.float32)])
        bgs = bg[:n] if len(bg) >= n else np.resize(bg, n)
        mixed = mix_at(sp_full, bgs, sp_db, bg_db) + noise_floor(n, rng)
        return mixed.astype(np.float32), MARGIN_S, MARGIN_S + len(utt) / SR

    for uid, utt, ref in utts:
        utt = utt.astype(np.float32)
        base = scale_to_rms(utt, -20.0)
        n = len(utt) + int(2 * MARGIN_S * SR)
        for cond, sp, bgl in (("mus_c", -32.0, -30.0), ("mus_d", -36.0, -30.0)):
            clip, t0, t1 = with_bg(utt, music_slice(mix_tracks, n, rng), sp, bgl)
            add(cond, uid, clip, ref, t0, t1, level_dbfs=sp, music_dbfs=bgl)
        clip, t0, t1 = with_bg(utt, effects_track(rng, n / SR + 1, level_dbfs=-24.0), -28.0, -28.0)
        add("sfx_a", uid, clip, ref, t0, t1, level_dbfs=-28.0, sfx_dbfs=-28.0)
        wet = signal.fftconvolve(base, synthetic_rir(rng))[: len(base) + int(0.5 * SR)].astype(np.float32)
        clip, t0, t1 = frame_clip(scale_to_rms(wet, -30.0), rng)
        add("reverb", uid, clip, ref, t0, t1, level_dbfs=-30.0)
        wh = whisperize(base, rng)
        clip, t0, t1 = with_bg(wh, music_slice(mix_tracks, n, rng), -36.0, -34.0)
        add("whisper_mus", uid, clip, ref, t0, t1, level_dbfs=-36.0, music_dbfs=-34.0)
        hes = insert_pauses(base, 2, 0.65, rng)
        clip, t0, t1 = frame_clip(scale_to_rms(hes, -26.0), rng)
        add("hesitate", uid, clip, ref, t0, t1, level_dbfs=-26.0, pauses=2, pause_s=0.65)
        el, spans = elongate_words(base, rng, n_spans=4, factor=4.0, span_s=0.26)
        clip, t0, t1 = frame_clip(scale_to_rms(el, -30.0), rng)
        add("stretch4", uid, clip, ref, t0, t1, level_dbfs=-30.0)
    (C2_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    print(f"{len(manifest)} clips en el manifiesto")


if __name__ == "__main__":
    main()
