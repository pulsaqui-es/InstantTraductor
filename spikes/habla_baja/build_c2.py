"""Construye el corpus C2 (sintético y controlado) y el clip de música y efectos sin diálogo.

Fuentes (todas libres, ver README):
- 10 enunciados de `tests/fixtures/dialogo_en_2min.wav` (LibriSpeech, CC BY 4.0), separados por sus silencios
  digitales, y 30 de LibriSpeech test-clean (CC BY 4.0), uno por locutor, de 3 a 9 s.
- Música CC0 de Wikimedia Commons (`find_music.py`) y efectos sintéticos (`dsp_tools.py`).

Condiciones (cada una con los mismos 40 enunciados; nivel = RMS de los tramos activos del habla, en dBFS):
  n20 / n30 / n40 / n50   habla a -20, -30, -40 y -50 dBFS
  mus_a, mus_b            habla a -26 con música a -34 (SNR +8) y a -30 con música a -32 (SNR +2)
  whisper, whisper_q      susurro por DSP a -30 y a -42 dBFS
  stretch                 3 vocales alargadas ×2,8 (WSOLA), habla a -30
  slow                    habla lenta (×1,6 en todo el enunciado), a -30
  after_loud              una explosión a -12 dBFS y, 0,4 s después, habla a -35 dBFS (relajación del AGC)

Cada clip: 1,5 s de margen + enunciado + 1,5 s de margen, con ruido de fondo de -70 dBFS (un loopback real
no es silencio digital). `manifest.json` guarda para cada clip la referencia y dónde está el habla real.

Uso: `uv run python build_c2.py`
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr

from common import C2_DIR, DL_DIR, SR, active_rms_dbfs, read_wav, scale_to_rms, write_wav
from dsp_tools import effects_track, elongate_words, mix_at, sfx_explosion, whisperize, wsola

REPO = Path(__file__).resolve().parents[2]
FIXTURE_WAV = REPO / "tests" / "fixtures" / "dialogo_en_2min.wav"
FIXTURE_TXT = REPO / "tests" / "fixtures" / "dialogo_en_2min.txt"
LIBRI = DL_DIR / "LibriSpeech" / "test-clean"
SEED = 7
N_TEST_CLEAN = 30
MARGIN_S = 1.5
NOISE_FLOOR_DBFS = -70.0


def split_fixture() -> list[tuple[str, np.ndarray, str]]:
    """Los 10 enunciados del fixture, separados por los 0,8 s de silencio digital."""
    audio = read_wav(FIXTURE_WAV)
    texts = FIXTURE_TXT.read_text("utf-8").strip().splitlines()
    idx = np.flatnonzero(np.abs(audio) >= 1e-6)
    # Un hueco de ceros de más de 0,5 s separa dos enunciados (los internos de la lectura no llegan a tanto).
    breaks = np.flatnonzero(np.diff(idx) > int(0.5 * SR))
    starts = np.r_[idx[0], idx[breaks + 1]]
    ends = np.r_[idx[breaks], idx[-1]]
    out = []
    for i, (a, b) in enumerate(zip(starts, ends, strict=True)):
        if i < len(texts):
            out.append((f"fx{i:02d}", audio[a : b + 1], texts[i]))
    return out


def trim_silence(x: np.ndarray, rel_db: float = 35.0, pad_s: float = 0.05) -> np.ndarray:
    """Recorta el silencio de los extremos (tramas de 10 ms a más de `rel_db` dB por debajo del pico)."""
    frame = 160
    n = len(x) // frame
    e = 10 * np.log10(np.mean(x[: n * frame].reshape(n, frame).astype(np.float64) ** 2, axis=1) + 1e-12)
    idx = np.flatnonzero(e > e.max() - rel_db)
    a = max(0, int(idx[0] * frame - pad_s * SR))
    b = min(len(x), int((idx[-1] + 1) * frame + pad_s * SR))
    return x[a:b]


def load_test_clean(n: int, rng: random.Random) -> list[tuple[str, np.ndarray, str]]:
    speakers = sorted(p for p in LIBRI.iterdir() if p.is_dir())
    rng.shuffle(speakers)
    picked: list[tuple[str, np.ndarray, str]] = []
    for spk in speakers:
        cands: list[tuple[str, str]] = []
        for chap in sorted(spk.iterdir()):
            trans = chap / f"{spk.name}-{chap.name}.trans.txt"
            for line in trans.read_text("utf-8").splitlines():
                uid, text = line.split(" ", 1)
                cands.append((str(chap / f"{uid}.flac"), text))
        rng.shuffle(cands)
        for path, text in cands:
            info = sf.info(path)
            dur = info.frames / info.samplerate
            if 3.0 <= dur <= 9.0:
                data, rate = sf.read(path, dtype="float32")
                if rate != SR:
                    data = soxr.resample(data, rate, SR)
                picked.append((Path(path).stem, data.astype(np.float32), text))
                break
        if len(picked) == n:
            break
    return picked


def load_music(paths: list[Path], rng: np.random.Generator) -> list[np.ndarray]:
    tracks = []
    for p in paths:
        data, rate = sf.read(str(p), dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
        if rate != SR:
            mono = soxr.resample(mono, rate, SR)
        tracks.append(mono.astype(np.float32))
    return tracks


def music_slice(tracks: list[np.ndarray], n: int, rng: np.random.Generator) -> np.ndarray:
    t = tracks[int(rng.integers(len(tracks)))]
    if len(t) <= n:
        return np.resize(t, n)
    a = int(rng.integers(0, len(t) - n))
    return t[a : a + n]


def noise_floor(n: int, rng: np.random.Generator) -> np.ndarray:
    return (rng.standard_normal(n) * 10 ** (NOISE_FLOOR_DBFS / 20)).astype(np.float32)


def frame_clip(body: np.ndarray, rng: np.random.Generator, lead: np.ndarray | None = None) -> tuple[np.ndarray, float, float]:
    """Pone márgenes (y un `lead` opcional) alrededor del enunciado. Devuelve (clip, t_inicio, t_fin) del habla."""
    pre = lead if lead is not None else np.zeros(int(MARGIN_S * SR), np.float32)
    post = np.zeros(int(MARGIN_S * SR), np.float32)
    clip = np.concatenate([pre, body, post])
    clip = clip + noise_floor(len(clip), rng)
    return clip.astype(np.float32), len(pre) / SR, (len(pre) + len(body)) / SR


def main() -> None:
    rng_py = random.Random(SEED)
    rng = np.random.default_rng(SEED)
    utts = [(u, trim_silence(x), t) for u, x, t in split_fixture() + load_test_clean(N_TEST_CLEAN, rng_py)]
    print(f"{len(utts)} enunciados base")

    music_dir = DL_DIR / "music"
    music_files = sorted(music_dir.glob("*.ogg")) + sorted(music_dir.glob("*.flac")) + sorted(music_dir.glob("*.wav"))
    # La mitad de las pistas para mezclar bajo el habla; la otra mitad para el clip de falsas alarmas.
    mix_tracks = load_music(music_files[0::2], rng)
    manifest: list[dict] = []

    def add(cond: str, uid: str, clip: np.ndarray, ref: str, t0: float, t1: float, **extra: object) -> None:
        name = f"{cond}__{uid}.wav"
        write_wav(C2_DIR / name, clip)
        manifest.append(
            {"clip": name, "cond": cond, "uid": uid, "ref": ref, "speech_start": t0, "speech_end": t1, **extra}
        )

    for uid, utt, ref in utts:
        utt = utt.astype(np.float32)
        base = scale_to_rms(utt, -20.0)
        for lvl in (20, 30, 40, 50):
            clip, t0, t1 = frame_clip(scale_to_rms(utt, -float(lvl)), rng)
            add(f"n{lvl}", uid, clip, ref, t0, t1, level_dbfs=-lvl)
        for cond, sp, bg in (("mus_a", -26.0, -34.0), ("mus_b", -30.0, -32.0)):
            n = len(utt) + int(2 * MARGIN_S * SR)
            music = music_slice(mix_tracks, n, rng)
            sp_full = np.concatenate([np.zeros(int(MARGIN_S * SR), np.float32), scale_to_rms(utt, sp), np.zeros(int(MARGIN_S * SR), np.float32)])
            mixed = mix_at(sp_full, music, sp, bg)  # escala la voz de nuevo: ya está a `sp` (sin efecto)
            clip = mixed + noise_floor(len(mixed), rng)
            add(cond, uid, clip.astype(np.float32), ref, MARGIN_S, MARGIN_S + len(utt) / SR, level_dbfs=sp, music_dbfs=bg)
        wh = whisperize(base, rng)
        for cond, lvl in (("whisper", -30.0), ("whisper_q", -42.0)):
            clip, t0, t1 = frame_clip(scale_to_rms(wh, lvl), rng)
            add(cond, uid, clip, ref, t0, t1, level_dbfs=lvl)
        el, spans = elongate_words(base, rng)
        clip, t0, t1 = frame_clip(scale_to_rms(el, -30.0), rng)
        add("stretch", uid, clip, ref, t0, t1, level_dbfs=-30.0, stretched=[(t0 + a, t0 + b) for a, b in spans])
        slow = wsola(base, 1.6)
        clip, t0, t1 = frame_clip(scale_to_rms(slow, -30.0), rng)
        add("slow", uid, clip, ref, t0, t1, level_dbfs=-30.0)
        boom = scale_to_rms(sfx_explosion(rng, 1.5), -12.0)
        lead = np.concatenate([np.zeros(int(0.5 * SR), np.float32), boom, np.zeros(int(0.4 * SR), np.float32)])
        clip, t0, t1 = frame_clip(scale_to_rms(utt, -35.0), rng, lead=lead)
        add("after_loud", uid, clip, ref, t0, t1, level_dbfs=-35.0, loud_burst_dbfs=-12.0)

    (C2_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), "utf-8")
    print(f"{len(manifest)} clips en {C2_DIR}")

    # --- Música y efectos SIN diálogo: 10 min para las falsas alarmas (SC-007) ---
    fa_tracks = load_music(music_files[1::2], rng)
    parts: list[np.ndarray] = []
    total = 0
    target = 7 * 60
    order = list(range(len(fa_tracks)))
    k = 0
    while total < target * SR:
        t = fa_tracks[order[k % len(order)]]
        k += 1
        seg = t[: 90 * SR]
        seg = scale_to_rms(seg, -26.0 + float(rng.uniform(-4, 4)))
        parts.append(seg)
        total += len(seg)
    music = np.concatenate(parts)[: target * SR]
    sfx = effects_track(rng, 3 * 60, level_dbfs=-22.0)
    fa = np.concatenate([music, sfx])
    fa = fa + noise_floor(len(fa), rng)
    write_wav(C2_DIR / "fa_music_sfx_10min.wav", fa)
    print(f"falsas alarmas: {len(fa) / SR:.0f} s ({k} pistas)")


if __name__ == "__main__":
    main()
