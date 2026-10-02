"""Genera los fixtures de audio de ``tests/fixtures/``: WAV PCM de 16 bits, 16 kHz y mono.

Uso, desde la raíz del repositorio::

    uv run python tests/fixtures/generate_fixtures.py

Los ficheros generados se versionan (suman unos 4 MB): este script solo hace falta para
regenerarlos. Los tres primeros no necesitan red; el diálogo descarga (y deja en la caché de
Hugging Face del usuario) el dataset pequeño ``hf-internal-testing/librispeech_asr_dummy``.

Qué produce:

- ``tono_1k_1s.wav``: seno de 1 kHz y 1 s, amplitud 0,5 (-6 dBFS de pico). Son 1000 ciclos
  exactos, así que se puede repetir sin clics.
- ``silencio_3s.wav``: 3 s de ceros digitales (lo que entrega el *process loopback* cuando no suena
  nada).
- ``ruido_rosa_5s.wav``: 5 s de ruido rosa (misma energía por octava), RMS de -20 dBFS y semilla fija.
- ``dialogo_en_2min.wav`` y ``dialogo_en_2min.txt``: los primeros enunciados de LibriSpeech (CC BY 4.0,
  ver ``ATTRIBUTION.md``), en su orden y sin tocar, mientras quepan en 2 min. Cada enunciado va seguido
  de una pausa de 0,8 s de ceros digitales (la última también, para que el VAD cierre el último). La
  transcripción lleva una línea por enunciado, tal cual la da LibriSpeech (mayúsculas, sin puntuación).
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf

SAMPLE_RATE = 16_000
OUTPUT_DIR = Path(__file__).resolve().parent

DATASET_REPO = "hf-internal-testing/librispeech_asr_dummy"
#: Commit fijado del dataset (73 enunciados de 16 kHz), para que el diálogo sea reproducible.
DATASET_REVISION = "5be91486e11a2d616f4ec5db8d3fd248585ac07a"

DIALOGUE_TARGET_S = 120.0
DIALOGUE_PAUSE_S = 0.8
PINK_NOISE_SEED = 20261001

Pcm16 = npt.NDArray[np.int16]


@dataclass(frozen=True, eq=False)
class Utterance:
    """Un enunciado de LibriSpeech: id (``locutor-capítulo-número``), texto y audio PCM de 16 bits."""

    utterance_id: str
    text: str
    samples: Pcm16


# --------------------------------------------------------------------------- audio sintético


def to_pcm16(signal: npt.ArrayLike) -> Pcm16:
    """Convierte una señal en [-1, 1] a PCM de 16 bits (redondea y recorta a ±32767)."""
    scaled = np.rint(np.asarray(signal, dtype=np.float64) * 32767.0)
    return np.clip(scaled, -32767, 32767).astype(np.int16)


def make_tone(frequency_hz: float = 1000.0, duration_s: float = 1.0, amplitude: float = 0.5) -> Pcm16:
    """Seno puro. A 1 kHz y 16 kHz son 16 muestras por ciclo, sin fundidos."""
    n = round(duration_s * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    return to_pcm16(amplitude * np.sin(2 * np.pi * frequency_hz * t))


def make_silence(duration_s: float = 3.0) -> Pcm16:
    """Silencio digital (ceros)."""
    return np.zeros(round(duration_s * SAMPLE_RATE), dtype=np.int16)


def make_pink_noise(duration_s: float = 5.0, rms_dbfs: float = -20.0, seed: int = PINK_NOISE_SEED) -> Pcm16:
    """Ruido rosa (potencia proporcional a 1/f) con el RMS indicado, sin componente continua."""
    n = round(duration_s * SAMPLE_RATE)
    spectrum = np.fft.rfft(np.random.default_rng(seed).standard_normal(n))
    frequencies = np.fft.rfftfreq(n, d=1 / SAMPLE_RATE)
    spectrum[1:] /= np.sqrt(frequencies[1:])
    spectrum[0] = 0.0
    noise = np.fft.irfft(spectrum, n)
    noise *= 10 ** (rms_dbfs / 20) / np.sqrt(np.mean(noise**2))
    if np.abs(noise).max() >= 0.99:
        raise ValueError(f"El ruido rosa recortaría con un RMS de {rms_dbfs} dBFS")
    return to_pcm16(noise)


def write_wav(path: Path, samples: Pcm16) -> None:
    """Escribe un WAV PCM de 16 bits, 16 kHz y mono."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, samples, SAMPLE_RATE, subtype="PCM_16", format="WAV")


def write_synthetic_fixtures(output_dir: Path = OUTPUT_DIR) -> list[Path]:
    """Genera el tono, el silencio y el ruido rosa."""
    files = {
        "tono_1k_1s.wav": make_tone(),
        "silencio_3s.wav": make_silence(),
        "ruido_rosa_5s.wav": make_pink_noise(),
    }
    paths = []
    for name, samples in files.items():
        path = output_dir / name
        write_wav(path, samples)
        paths.append(path)
    return paths


# --------------------------------------------------------------------------- diálogo de LibriSpeech


def load_utterances(revision: str = DATASET_REVISION) -> list[Utterance]:
    """Lee los enunciados del dataset (lo descarga a la caché de Hugging Face si hace falta)."""
    import pyarrow.parquet as pq
    from huggingface_hub import snapshot_download

    root = Path(
        snapshot_download(
            repo_id=DATASET_REPO,
            repo_type="dataset",
            revision=revision,
            allow_patterns=["clean/*.parquet"],
        )
    )
    table = pq.read_table(next(root.glob("clean/*.parquet")))
    utterances = []
    for row in table.to_pylist():
        samples, rate = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="int16")
        if rate != SAMPLE_RATE or samples.ndim != 1:
            raise ValueError(
                f"{row['id']}: se esperaba audio mono a 16 kHz y llegó {rate} Hz, {samples.shape}"
            )
        utterances.append(Utterance(row["id"], row["text"], samples))
    return utterances


def select_utterances(
    utterances: Sequence[Utterance],
    target_s: float = DIALOGUE_TARGET_S,
    pause_s: float = DIALOGUE_PAUSE_S,
) -> list[Utterance]:
    """Los primeros enunciados, en orden, mientras quepan en ``target_s`` contando una pausa tras cada uno."""
    budget = round(target_s * SAMPLE_RATE)
    pause = round(pause_s * SAMPLE_RATE)
    selected: list[Utterance] = []
    used = 0
    for utterance in utterances:
        cost = len(utterance.samples) + pause
        if used + cost > budget:
            break
        selected.append(utterance)
        used += cost
    if not selected:
        raise ValueError(f"Ningún enunciado cabe en {target_s} s")
    return selected


def assemble_dialogue(utterances: Sequence[Utterance], pause_s: float = DIALOGUE_PAUSE_S) -> Pcm16:
    """Une los enunciados, cada uno seguido de ``pause_s`` segundos de silencio digital."""
    pause = make_silence(pause_s)
    parts: list[Pcm16] = []
    for utterance in utterances:
        parts += [utterance.samples, pause]
    return np.concatenate(parts)


def write_transcript(path: Path, utterances: Sequence[Utterance]) -> None:
    """Una línea por enunciado, en UTF-8 y con saltos de línea LF."""
    path.write_text("".join(f"{u.text}\n" for u in utterances), encoding="utf-8", newline="\n")


def write_dialogue_fixtures(
    output_dir: Path = OUTPUT_DIR, utterances: Sequence[Utterance] | None = None
) -> list[Utterance]:
    """Genera ``dialogo_en_2min.wav`` y ``dialogo_en_2min.txt``. Devuelve los enunciados usados."""
    selected = select_utterances(load_utterances() if utterances is None else utterances)
    write_wav(output_dir / "dialogo_en_2min.wav", assemble_dialogue(selected))
    write_transcript(output_dir / "dialogo_en_2min.txt", selected)
    return selected


def main() -> None:
    for path in write_synthetic_fixtures():
        print(f"{path.name}: {sf.info(path).duration:.3f} s")
    selected = write_dialogue_fixtures()
    duration = sf.info(OUTPUT_DIR / "dialogo_en_2min.wav").duration
    print(f"dialogo_en_2min.wav: {duration:.3f} s con {len(selected)} enunciados")
    print("Enunciados:", ", ".join(u.utterance_id for u in selected))


if __name__ == "__main__":
    main()
