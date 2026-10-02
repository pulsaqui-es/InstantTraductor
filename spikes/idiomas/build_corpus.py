"""Monta el corpus del spike S5 a partir de FLEURS (google/fleurs, CC BY 4.0) y música de dominio público.

Salida (fuera del repo, ``%LOCALAPPDATA%\\InstantTraductor\\spikes\\idiomas\\corpus``):
- ``clean/<idioma>/<id>.wav``: frases de FLEURS (16 kHz mono). 50 por ja/zh/ko (las mismas frases en los tres,
  porque FLEURS es paralelo), 30 en español (es_419) y 30 en inglés (en_us) para el filtro de idioma.
- ``stream_<idioma>_clean.wav`` y ``stream_<idioma>_music.wav``: las 50 frases separadas por huecos de 1,2-2,2 s, sin
  y con música a -10 dB por debajo del habla (la música suena también en los huecos).
- ``lid/<idioma>/<id>.wav`` y ``lid_music/<idioma>/<id>.wav``: recortes de 1-6 s para el filtro de idioma.

En el repo: ``corpus_manifest.json`` (referencias de texto, tiempos y procedencia; sin audio).
"""

from __future__ import annotations

import io
import json

import numpy as np
import soundfile as sf
from huggingface_hub import hf_hub_download

from idiomas.audio import (
    SAMPLE_RATE,
    energy_speech_intervals,
    mix_music,
    music_loop,
    noise,
    speech_rms_db,
)
from idiomas.paths import CORPUS_MANIFEST, FLEURS, LANGS, corpus_dir, music_dir, silero_model_path
from idiomas.vad import FRAME, FRAME_S, SileroOnnx

N_PHRASES = 50
N_LID = 30
SEED = 20261002
NOISE_DB = -66.0
GAP_RANGE = (1.2, 2.2)
MUSIC_SNR_DB = 10.0
SPEECH_LEVEL_DB = -22.0


def load_split(lang: str) -> dict[int, list[dict]]:
    """Filas de test de FLEURS por id de frase (varias grabaciones por frase)."""
    import pyarrow.parquet as pq

    path = hf_hub_download(
        "google/fleurs", f"parquet-data/{FLEURS[lang]}/test-00000-of-00001.parquet", repo_type="dataset"
    )
    rows: dict[int, list[dict]] = {}
    for r in pq.read_table(path).to_pylist():
        rows.setdefault(r["id"], []).append(r)
    return rows


def decode(row: dict) -> np.ndarray:
    """Audio de una fila de FLEURS, con el nivel de habla normalizado a -22 dBFS (RMS de los tramos con habla).

    Las grabaciones de FLEURS varían mucho de nivel (de -18 a -40 dBFS); una película mezclada no.
    """
    audio, sr = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32", always_2d=True)
    assert sr == SAMPLE_RATE, sr
    x = audio.mean(axis=1)
    level = speech_rms_db(x, energy_speech_intervals(x))
    x = x * 10 ** ((SPEECH_LEVEL_DB - level) / 20)
    peak = float(np.max(np.abs(x)))
    return (x * (0.95 / peak) if peak > 0.95 else x).astype(np.float32)


def silero_span(model: SileroOnnx, x: np.ndarray, thr: float = 0.5) -> tuple[float, float] | None:
    """Primera y última trama con probabilidad de habla de Silero >= ``thr`` (s).

    Es el «fin real del habla» de las latencias: en FLEURS el oráculo por energía de S3 falla en grabaciones con ruido
    (llega a marcar el fin varios segundos antes), así que se usa la probabilidad de Silero sobre el clip limpio.
    """
    model.reset()
    n = len(x) // FRAME
    probs = np.array([model.prob(x[i * FRAME : (i + 1) * FRAME]) for i in range(n)])
    idx = np.flatnonzero(probs >= thr)
    if idx.size == 0:
        return None
    return float(idx[0] * FRAME_S), float((idx[-1] + 1) * FRAME_S)


def main() -> None:
    silero = SileroOnnx(silero_model_path())
    rng = np.random.default_rng(SEED)
    root = corpus_dir()
    splits = {lang: load_split(lang) for lang in ("ja", "zh", "ko", "es", "en")}
    common = sorted(set(splits["ja"]) & set(splits["zh"]) & set(splits["ko"]) & set(splits["es"]) & set(splits["en"]))
    print(f"frases paralelas ja+zh+ko+es+en en test: {len(common)}")
    chosen = sorted(int(i) for i in rng.choice(common, size=N_PHRASES, replace=False))

    tracks = [sf.read(p, dtype="float32")[0] for p in sorted(music_dir().glob("track*.wav"))]
    print(f"{len(tracks)} pistas de música")

    manifest: dict = {
        "source": "google/fleurs (test), CC BY 4.0, https://huggingface.co/datasets/google/fleurs",
        "seed": SEED,
        "music_snr_db": MUSIC_SNR_DB,
        "music": json.loads((CORPUS_MANIFEST.parent / "music_licenses.json").read_text(encoding="utf-8")),
        "phrases": {},
        "lid": {},
    }

    # --- 50 frases por idioma, flujos con huecos -------------------------------------------------------
    for lang in LANGS:
        (root / "clean" / lang).mkdir(parents=True, exist_ok=True)
        parts = [noise(int(1.0 * SAMPLE_RATE), NOISE_DB, rng)]
        cursor = len(parts[0])
        items = []
        for sid in chosen:
            row = splits[lang][sid][0]
            x = decode(row)
            sf.write(root / "clean" / lang / f"{sid}.wav", x, SAMPLE_RATE, subtype="PCM_16")
            ivs = energy_speech_intervals(x)
            span = silero_span(silero, x)
            start = cursor
            parts.append(x)
            cursor += len(x)
            items.append(
                {
                    "id": sid,
                    "ref": row["raw_transcription"],
                    "ref_norm_fleurs": row["transcription"],
                    "ref_es": splits["es"][sid][0]["raw_transcription"],
                    "ref_en": splits["en"][sid][0]["raw_transcription"],
                    "gender": row["gender"],
                    "duration": round(len(x) / SAMPLE_RATE, 2),
                    "start": round(start / SAMPLE_RATE, 3),
                    "end": round(cursor / SAMPLE_RATE, 3),
                    "speech_start": round(start / SAMPLE_RATE + span[0], 3) if span else None,
                    "speech_end": round(start / SAMPLE_RATE + span[1], 3) if span else None,
                    "energy_start": round(start / SAMPLE_RATE + ivs[0][0], 3) if ivs else None,
                    "energy_end": round(start / SAMPLE_RATE + ivs[-1][1], 3) if ivs else None,
                    "speech_intervals": [[round(start / SAMPLE_RATE + a, 3), round(start / SAMPLE_RATE + b, 3)] for a, b in ivs],
                }
            )
            gap = noise(int(rng.uniform(*GAP_RANGE) * SAMPLE_RATE), NOISE_DB, rng)
            parts.append(gap)
            cursor += len(gap)
        parts.append(noise(int(2.0 * SAMPLE_RATE), NOISE_DB, rng))
        stream = np.concatenate(parts)
        sf.write(root / f"stream_{lang}_clean.wav", stream, SAMPLE_RATE, subtype="PCM_16")
        level = speech_rms_db(stream, [(it["speech_start"], it["speech_end"]) for it in items])
        music = music_loop(tracks, len(stream), rng)
        mixed = mix_music(stream, music, level, MUSIC_SNR_DB)
        sf.write(root / f"stream_{lang}_music.wav", mixed, SAMPLE_RATE, subtype="PCM_16")
        manifest["phrases"][lang] = {
            "fleurs": FLEURS[lang],
            "duration": round(len(stream) / SAMPLE_RATE, 1),
            "speech_level_db": round(level, 1),
            "items": items,
        }
        print(f"{lang}: flujo de {len(stream) / SAMPLE_RATE:.0f} s, habla a {level:.1f} dBFS")

    # --- recortes de 1-6 s para el filtro de idioma ----------------------------------------------------
    lid_sets = {
        "ja": [(sid, 0) for sid in chosen],
        "zh": [(sid, 0) for sid in chosen],
        "ko": [(sid, 0) for sid in chosen],
        "es": [(int(i), 0) for i in rng.choice(sorted(splits["es"]), size=N_LID, replace=False)],
        "en": [(int(i), 0) for i in rng.choice(sorted(splits["en"]), size=N_LID, replace=False)],
    }
    for lang, picks in lid_sets.items():
        for sub in ("clean", "lid", "lid_music"):
            (root / sub / lang).mkdir(parents=True, exist_ok=True)
        entries = []
        for sid, k in picks:
            x = decode(splits[lang][sid][k])
            sf.write(root / "clean" / lang / f"{sid}.wav", x, SAMPLE_RATE, subtype="PCM_16")
            ivs = energy_speech_intervals(x)
            a0, b0 = (ivs[0][0], ivs[-1][1]) if ivs else (0.0, len(x) / SAMPLE_RATE)
            length = float(rng.uniform(1.0, 6.0))
            length = min(length, max(1.0, b0 - a0))
            t0 = float(rng.uniform(a0, max(a0, b0 - length)))
            seg = x[int(t0 * SAMPLE_RATE) : int((t0 + length) * SAMPLE_RATE)]
            seg_level = speech_rms_db(seg, [(0.0, len(seg) / SAMPLE_RATE)])
            music = music_loop(tracks, len(seg), rng)
            sf.write(root / "lid" / lang / f"{sid}.wav", seg, SAMPLE_RATE, subtype="PCM_16")
            sf.write(
                root / "lid_music" / lang / f"{sid}.wav",
                mix_music(seg, music, seg_level, MUSIC_SNR_DB),
                SAMPLE_RATE,
                subtype="PCM_16",
            )
            entries.append({"id": sid, "crop_start": round(t0, 2), "crop_len": round(len(seg) / SAMPLE_RATE, 2)})
        manifest["lid"][lang] = {"fleurs": FLEURS[lang], "items": entries}
    CORPUS_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("manifiesto:", CORPUS_MANIFEST)


if __name__ == "__main__":
    main()
