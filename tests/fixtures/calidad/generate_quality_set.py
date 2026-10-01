"""Conjunto de calidad (T046, SC-004): 50 frases en inglés del corpus del spike S2, habladas por Qwen3-TTS.

Se ejecuta en el entorno del servicio de voz, que tiene torch y faster-qwen3-tts:

    uv run --project engines/tts-qwen3 python tests/fixtures/calidad/generate_quality_set.py

- **Frases:** las 50 primeras líneas normales de `spikes/traduccion/corpus.py`, sin trampas ni términos
  inventados del glosario.
- **Voz inglesa:** clonada del primer enunciado de `tests/fixtures/dialogo_en_2min.wav` (LibriSpeech,
  CC BY 4.0; grabación original de LibriVox en dominio público; ver `tests/fixtures/ATTRIBUTION.md`).
- **Salida, fuera del repo** (`%LOCALAPPDATA%\\InstantTraductor\\calidad\\`):
  - `frases_en.wav`: las frases separadas por 1,5 s de silencio (16 bits, 24 kHz, mono);
  - `frases_en.txt`: el texto de cada una, en orden, con su id del corpus.

Después: `instanttraductor archivo <ruta>\\frases_en.wav` y la persona revisa `traduccion.srt`.
"""

from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

import numpy as np
import soundfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "spikes" / "traduccion"))
import corpus  # noqa: E402  (corpus del spike S2)

COUNT = 50
GAP_S = 1.5
REFERENCE = ROOT / "tests" / "fixtures" / "dialogo_en_2min.wav"
REFERENCE_SPAN_S = (0.56, 5.38)  # primer enunciado
REFERENCE_TEXT = "Mister Quilter is the apostle of the middle classes, and we are glad to welcome his gospel."


def app_home() -> Path:
    """La carpeta de datos de la app (la misma regla que ``AppPaths``)."""
    override = os.environ.get("INSTANTTRADUCTOR_HOME")
    return Path(override) if override else Path(os.environ["LOCALAPPDATA"]) / "InstantTraductor"


def sentences() -> list[tuple[int, str]]:
    regular = [
        line for line in corpus.LINES[: corpus.N_REGULAR] if not line.trap and "glosario" not in line.tags
    ]
    if len(regular) < COUNT:
        raise SystemExit(f"El corpus solo tiene {len(regular)} frases normales (hacen falta {COUNT}).")
    return [(line.id, line.text) for line in regular[:COUNT]]


def main() -> int:
    import torch
    from faster_qwen3_tts import FasterQwen3TTS

    model = FasterQwen3TTS.from_pretrained(
        str(app_home() / "models" / "qwen3-tts-12hz-0.6b-base"),
        device="cuda",
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
        max_seq_len=2048,
    )
    audio, rate = soundfile.read(REFERENCE, dtype="float32")
    start, end = (round(t * rate) for t in REFERENCE_SPAN_S)
    reference = np.concatenate([audio[start:end], np.zeros(rate // 2, np.float32)])
    prompt = model.model.create_voice_clone_prompt(ref_audio=(reference, rate), ref_text=REFERENCE_TEXT)

    pieces: list[np.ndarray] = []
    out_rate = 24_000
    lines = sentences()
    for index, (line_id, text) in enumerate(lines, start=1):
        print(f"{index:2d}/{len(lines)} [{line_id}] {text}", flush=True)
        chunks = []
        for chunk, chunk_rate, _timing in model.generate_voice_clone_streaming(
            text=text, language="English", ref_text=REFERENCE_TEXT, voice_clone_prompt=prompt, chunk_size=8
        ):
            out_rate = chunk_rate
            chunks.append(np.asarray(chunk, dtype=np.float32).reshape(-1))
        pieces += [np.concatenate(chunks), np.zeros(round(GAP_S * out_rate), np.float32)]

    target = app_home() / "calidad"
    target.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(np.concatenate([np.zeros(out_rate, np.float32), *pieces]), -1, 1) * 32767).astype("<i2")
    with wave.open(str(target / "frases_en.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(out_rate)
        out.writeframes(pcm.tobytes())
    (target / "frases_en.txt").write_text(
        "".join(f"{line_id}\t{text}\n" for line_id, text in lines), encoding="utf-8"
    )
    print(f"Listo: {target / 'frases_en.wav'} ({len(pcm) / out_rate / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
