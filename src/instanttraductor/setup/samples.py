"""Muestras de las voces (FR-028, T043): se generan en ``preparar`` y se escuchan con ``voces --escuchar``.

Cada muestra es una frase en español dicha con la voz, sintetizada con el mismo servicio de voz que usa la
traducción: se oye exactamente como sonará. Se guardan en ``<voces>/muestras/<id>.wav`` (16 bits, a la
frecuencia del motor). El servicio de voz solo lee los ``*.json`` de la carpeta de voces, no las subcarpetas.
"""

from __future__ import annotations

import logging
import threading
import wave
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt

from instanttraductor.config import AppPaths
from instanttraductor.contracts import (
    PLAYBACK_RATE,
    PlaybackEventKind,
    SpeechPiece,
    SynthesisRequest,
    VoiceRef,
)

logger = logging.getLogger(__name__)

SAMPLE_TEXT = (
    "Hola, soy {name}. Así sonará en español lo que veas: series, películas y vídeos. ¿Te gusta cómo hablo?"
)
#: Tope de espera a que termine de sonar una muestra (las muestras duran unos 6 s).
PLAY_TIMEOUT_S = 30.0


def samples_dir(paths: AppPaths) -> Path:
    return paths.voices / "muestras"


def sample_path(paths: AppPaths, voice_id: str) -> Path:
    return samples_dir(paths) / f"{voice_id}.wav"


def missing_samples(paths: AppPaths, voice_ids: Sequence[str]) -> list[str]:
    return [voice_id for voice_id in voice_ids if not sample_path(paths, voice_id).is_file()]


def generate_samples(
    paths: AppPaths,
    voices: Sequence[tuple[str, str]],
    *,
    on_progress: Callable[[str], None] = logger.info,
) -> list[str]:
    """Sintetiza la muestra de cada ``(voice_id, nombre)`` que no la tenga. Devuelve los ids generados.

    Arranca el servicio de voz solo si falta alguna muestra, y lo para al terminar.
    """
    from instanttraductor.platform.children import stop_all
    from instanttraductor.tts.service_process import TtsServiceProcess

    pending = [(voice_id, name) for voice_id, name in voices if not sample_path(paths, voice_id).is_file()]
    if not pending:
        return []
    on_progress("Arrancando la voz para generar las muestras…")
    service = TtsServiceProcess(voices_dir=paths.voices, models_dir=paths.models)
    try:
        service.start()
        service.wait_ready()
        synthesizer = service.synthesizer()
        generated = []
        for unit_id, (voice_id, name) in enumerate(pending, start=1):
            on_progress(f"Muestra de {name}…")
            request = SynthesisRequest(unit_id, SAMPLE_TEXT.format(name=name), VoiceRef(voice_id))
            pieces = [chunk.samples for chunk in synthesizer.synthesize(request) if chunk.samples.size]
            audio = np.concatenate(pieces) if pieces else np.zeros(0, np.float32)
            _write_wav(sample_path(paths, voice_id), audio, synthesizer.sample_rate)
            generated.append(voice_id)
        return generated
    finally:
        stop_all([service.child], grace_s=1.0)


def play_sample(paths: AppPaths, voice_id: str, *, volume: float = 1.0) -> None:
    """Reproduce la muestra por la salida por defecto y vuelve al terminar. ``FileNotFoundError`` si falta."""
    import soxr

    from instanttraductor.audio.wasapi_playback import DeviceSink
    from instanttraductor.pipeline.clock import SessionClock

    audio, rate = _read_wav(sample_path(paths, voice_id))
    audio = soxr.resample(audio, rate, PLAYBACK_RATE).astype(np.float32)
    done = threading.Event()

    def on_event(event: object) -> None:
        if getattr(event, "kind", None) in (PlaybackEventKind.FINISHED, PlaybackEventKind.CANCELLED):
            done.set()

    sink = DeviceSink(SessionClock())
    sink.start(on_event)
    try:
        sink.set_volume(volume)
        sink.enqueue(SpeechPiece(unit_id=1, samples=audio, is_last=True))
        done.wait(PLAY_TIMEOUT_S)
    finally:
        sink.stop()


def _write_wav(path: Path, audio: npt.NDArray[np.float32], rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".wav.part")
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(tmp), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    tmp.replace(path)


def _read_wav(path: Path) -> tuple[npt.NDArray[np.float32], int]:
    with wave.open(str(path), "rb") as src:
        rate = src.getframerate()
        pcm = np.frombuffer(src.readframes(src.getnframes()), dtype="<i2")
    return (pcm.astype(np.float32) / 32768.0), rate
