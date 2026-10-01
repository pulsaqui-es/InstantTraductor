"""Audio de prueba: LibriSpeech dummy (CC BY 4.0), montaje de los flujos y marcas de habla real.

Los WAV montados se guardan fuera del repo (``paths.corpus_dir()``).
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 16_000
DATASET_REPO = "hf-internal-testing/librispeech_asr_dummy"


@dataclass
class Utterance:
    id: str
    speaker_id: int
    text: str  # referencia de LibriSpeech (MAYÚSCULAS, sin puntuación)
    samples: np.ndarray  # float32, mono, 16 kHz

    @property
    def duration(self) -> float:
        return len(self.samples) / SAMPLE_RATE


def load_utterances() -> list[Utterance]:
    """Lee el dataset desde la caché de Hugging Face (``fetch_assets.py`` lo descarga)."""
    import pyarrow.parquet as pq
    from huggingface_hub import snapshot_download

    root = Path(snapshot_download(repo_id=DATASET_REPO, repo_type="dataset"))
    table = pq.read_table(next(root.glob("clean/*.parquet")))
    out: list[Utterance] = []
    for row in table.to_pylist():
        x, sr = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
        if x.ndim > 1:
            x = x.mean(axis=1)
        if sr != SAMPLE_RATE:
            raise ValueError(f"{row['id']}: se esperaba 16 kHz y llegó {sr}")
        out.append(Utterance(row["id"], int(row["speaker_id"]), row["text"], x.astype(np.float32)))
    return out


# --------------------------------------------------------------------------------------
# Marcas de habla "real" (oráculo por energía)
# --------------------------------------------------------------------------------------


def energy_speech_intervals(
    x: np.ndarray,
    sr: int = SAMPLE_RATE,
    frame_ms: float = 25.0,
    hop_ms: float = 10.0,
    rel_db: float = 28.0,
    floor_margin_db: float = 15.0,
    min_gap_s: float = 0.25,
    min_len_s: float = 0.15,
) -> list[tuple[float, float]]:
    """Intervalos de habla según la energía (LibriSpeech «clean» tiene muy poco ruido).

    Umbral = max(suelo de ruido + ``floor_margin_db``, percentil 95 de la energía - ``rel_db``).
    Se unen los huecos de menos de ``min_gap_s`` y se descartan tramos de menos de ``min_len_s``.
    Es un oráculo independiente de Silero, con una incertidumbre de unas decenas de ms.
    """
    frame, hop = int(sr * frame_ms / 1000), int(sr * hop_ms / 1000)
    if len(x) < frame:
        return []
    n = 1 + (len(x) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(x[idx].astype(np.float64) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    floor, peak = np.percentile(db, 5), np.percentile(db, 95)
    thr = max(floor + floor_margin_db, peak - rel_db)
    mask = db > thr

    runs: list[list[int]] = []
    start = None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            runs.append([start, i - 1])
            start = None
    if start is not None:
        runs.append([start, len(mask) - 1])
    # Unir huecos cortos.
    merged: list[list[int]] = []
    gap = int(min_gap_s * 1000 / hop_ms)
    for r in runs:
        if merged and r[0] - merged[-1][1] <= gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    hop_s = hop_ms / 1000
    out = []
    for a, b in merged:
        t0, t1 = a * hop_s, b * hop_s + frame_ms / 1000
        if t1 - t0 >= min_len_s:
            out.append((round(t0, 3), round(t1, 3)))
    return out


# --------------------------------------------------------------------------------------
# Montaje de los flujos de prueba
# --------------------------------------------------------------------------------------


@dataclass
class StreamPlan:
    """Flujo montado: audio + referencia + posición de cada enunciado."""

    name: str
    description: str
    samples: np.ndarray
    utterances: list[dict]  # id, text, start, end (s, en el flujo), speech_start, speech_end
    oracle_intervals: list[tuple[float, float]]

    @property
    def duration(self) -> float:
        return len(self.samples) / SAMPLE_RATE

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        sf.write(directory / f"{self.name}.wav", self.samples, SAMPLE_RATE, subtype="PCM_16")
        meta = {
            "name": self.name,
            "description": self.description,
            "duration_s": round(self.duration, 3),
            "utterances": self.utterances,
            "oracle_intervals": self.oracle_intervals,
        }
        (directory / f"{self.name}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    @staticmethod
    def load(directory: Path, name: str) -> StreamPlan:
        x, sr = sf.read(directory / f"{name}.wav", dtype="float32")
        assert sr == SAMPLE_RATE
        meta = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        return StreamPlan(
            meta["name"], meta["description"], x, meta["utterances"], [tuple(i) for i in meta["oracle_intervals"]]
        )


def _noise(n: int, level_db: float, rng: np.random.Generator) -> np.ndarray:
    """Ruido blanco de fondo (evita el silencio digital, que no existe en un loopback real)."""
    return (rng.standard_normal(n) * 10 ** (level_db / 20)).astype(np.float32)


def build_gapped(utts: list[Utterance], seed: int = 7, gap_range=(1.2, 2.2), noise_db: float = -66.0) -> StreamPlan:
    """Enunciados separados por huecos de 1,2-2,2 s de ruido muy bajo (frases sueltas)."""
    rng = np.random.default_rng(seed)
    parts: list[np.ndarray] = [_noise(int(1.0 * SAMPLE_RATE), noise_db, rng)]
    cursor = len(parts[0])
    meta = []
    for u in utts:
        x = u.samples
        start = cursor
        parts.append(x)
        cursor += len(x)
        ivs = energy_speech_intervals(x)
        meta.append(
            {
                "id": u.id,
                "text": u.text,
                "start": round(start / SAMPLE_RATE, 3),
                "end": round(cursor / SAMPLE_RATE, 3),
                "speech_start": round(start / SAMPLE_RATE + ivs[0][0], 3) if ivs else None,
                "speech_end": round(start / SAMPLE_RATE + ivs[-1][1], 3) if ivs else None,
            }
        )
        gap = _noise(int(rng.uniform(*gap_range) * SAMPLE_RATE), noise_db, rng)
        parts.append(gap)
        cursor += len(gap)
    parts.append(_noise(int(2.0 * SAMPLE_RATE), noise_db, rng))
    samples = np.concatenate(parts)
    return StreamPlan(
        "gapped",
        f"{len(utts)} enunciados de LibriSpeech separados por huecos de {gap_range[0]}-{gap_range[1]} s",
        samples,
        meta,
        energy_speech_intervals(samples),
    )


def build_continuous(utts: list[Utterance], min_duration_s: float = 120.0, noise_db: float = -66.0) -> StreamPlan:
    """Enunciados pegados sin hueco añadido: habla continua de al menos ``min_duration_s``."""
    rng = np.random.default_rng(11)
    parts: list[np.ndarray] = [_noise(int(0.5 * SAMPLE_RATE), noise_db, rng)]
    cursor = len(parts[0])
    meta = []
    for u in utts:
        start = cursor
        parts.append(u.samples)
        cursor += len(u.samples)
        ivs = energy_speech_intervals(u.samples)
        meta.append(
            {
                "id": u.id,
                "text": u.text,
                "start": round(start / SAMPLE_RATE, 3),
                "end": round(cursor / SAMPLE_RATE, 3),
                "speech_start": round(start / SAMPLE_RATE + ivs[0][0], 3) if ivs else None,
                "speech_end": round(start / SAMPLE_RATE + ivs[-1][1], 3) if ivs else None,
            }
        )
        if cursor / SAMPLE_RATE >= min_duration_s:
            break
    parts.append(_noise(int(2.0 * SAMPLE_RATE), noise_db, rng))
    samples = np.concatenate(parts)
    return StreamPlan(
        "continuous",
        f"{len(meta)} enunciados de LibriSpeech pegados sin hueco (habla continua, >= {min_duration_s:.0f} s)",
        samples,
        meta,
        energy_speech_intervals(samples),
    )


def cut_plan(plan: StreamPlan, n_utts: int) -> StreamPlan:
    """Recorta el flujo a los primeros ``n_utts`` enunciados (para pruebas rápidas)."""
    utts = plan.utterances[:n_utts]
    end = utts[-1]["end"] + 2.0
    return StreamPlan(
        plan.name,
        plan.description + f" (recortado a {n_utts} enunciados)",
        plan.samples[: int(end * SAMPLE_RATE)],
        utts,
        [iv for iv in plan.oracle_intervals if iv[1] <= end],
    )
