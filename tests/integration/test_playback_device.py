"""Reproducción con el dispositivo real (T023). Marcador `device`: solo los lanza el orquestador.

OJO: abren el dispositivo de salida por defecto (WASAPI, 48 kHz, estéreo, 20 ms x 3). La suite de contrato usa
silencio, así que no se oye nada; los demás tests hacen sonar un tono corto y bajo (-30 dBFS), que se oye en
los auriculares. Qué se comprueba:

- `AudioSinkContract` con el `DeviceSink` real.
- El gancho `on_rendered` recibe exactamente lo que se encoló (y con el volumen aplicado).
- Sin carga, la sesión no tiene *underruns* y el dispositivo abre en menos de un segundo.
- Tras `stop()` el dispositivo queda libre: otro sink puede abrirlo.

No se prueba aquí el cambio de dispositivo (`rerouted`/`stopped`): necesita al humano desenchufando los
auriculares (`spikes/audio/probar_cambio_dispositivo.py`).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.audio.wasapi_playback import DeviceSink
from instanttraductor.contracts import (
    PLAYBACK_RATE,
    AudioSink,
    PlaybackEvent,
    PlaybackEventKind,
    SpeechPiece,
)
from instanttraductor.pipeline.clock import SessionClock
from tests.contract.test_audio_contract import AudioSinkContract

pytestmark = pytest.mark.device

Samples = npt.NDArray[np.float32]

TONE_HZ = 440.0
TONE_DBFS = -30.0
EVENT_TIMEOUT_S = 5.0


def tone(seconds: float, dbfs: float = TONE_DBFS) -> Samples:
    count = round(seconds * PLAYBACK_RATE)
    amplitude = 10 ** (dbfs / 20)
    return (amplitude * np.sin(2 * np.pi * TONE_HZ * np.arange(count) / PLAYBACK_RATE)).astype(np.float32)


class Recorder:
    """Un `DeviceSink` real con sus eventos y lo que recibió el gancho `on_rendered`."""

    def __init__(self) -> None:
        self.events: list[PlaybackEvent] = []
        self.rendered: list[tuple[Samples, float]] = []
        self.warnings: list[str] = []
        self.sink = DeviceSink(
            SessionClock(),
            on_warning=self.warnings.append,
            on_rendered=lambda samples, at: self.rendered.append((samples, at)),
        )
        self._finished = threading.Event()

    def start(self) -> Recorder:
        self.sink.start(self._on_event)
        return self

    def _on_event(self, event: PlaybackEvent) -> None:
        self.events.append(event)
        if event.kind is PlaybackEventKind.FINISHED:
            self._finished.set()

    def play(self, samples: Samples, unit_id: int = 1) -> None:
        self._finished.clear()
        self.sink.enqueue(SpeechPiece(unit_id=unit_id, samples=samples, is_last=True))
        assert self._finished.wait(EVENT_TIMEOUT_S), "el dispositivo no terminó de reproducir la unidad"
        assert self.sink.flush_events()

    def heard(self) -> Samples:
        """Todo lo que recibió el gancho, de seguido."""
        return (
            np.concatenate([block for block, _ in self.rendered])
            if self.rendered
            else np.zeros(0, np.float32)
        )


@pytest.fixture
def recorder() -> Iterator[Recorder]:
    recorder = Recorder().start()
    yield recorder
    recorder.sink.stop()


class TestDeviceSinkDevice(AudioSinkContract):
    """El contrato de `AudioSink` con el dispositivo real. Las unidades de prueba son silencios."""

    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSink]:
        return lambda: DeviceSink(SessionClock())


def test_the_device_opens_quickly() -> None:
    sink = DeviceSink(SessionClock())
    started = time.perf_counter()
    sink.start(lambda event: None)
    try:
        assert time.perf_counter() - started < 1.0  # el spike midió 21-41 ms
    finally:
        sink.stop()


def test_the_rendered_hook_receives_exactly_what_was_enqueued(recorder: Recorder) -> None:
    voice = tone(0.3)
    recorder.play(voice)
    heard = recorder.heard()
    assert len(heard) >= len(voice)
    assert np.array_equal(heard[: len(voice)], voice)
    assert not heard[len(voice) :].any()  # solo el resto del último bloque, en silencio
    started = next(e for e in recorder.events if e.kind is PlaybackEventKind.STARTED)
    assert recorder.rendered[0][1] == pytest.approx(started.at, abs=1e-9)  # misma hora: es el mismo bloque
    times = [at for _, at in recorder.rendered]
    assert times == sorted(times)


def test_the_rendered_hook_carries_the_volume(recorder: Recorder) -> None:
    recorder.sink.set_volume(0.5)
    time.sleep(0.1)  # que la rampa del cambio de volumen quede atrás
    voice = tone(0.5)
    recorder.play(voice)
    heard = recorder.heard()
    settled = heard[PLAYBACK_RATE // 10 : len(voice)]  # sin el primer cuarto de segundo del cambio
    assert float(np.max(np.abs(settled))) == pytest.approx(0.5 * float(np.max(np.abs(voice))), rel=0.02)


def test_a_quiet_session_has_no_underruns(recorder: Recorder) -> None:
    for unit_id in range(1, 11):
        recorder.play(tone(0.25), unit_id)
        time.sleep(0.05)
    assert recorder.sink.underruns == 0
    assert recorder.warnings == []


def test_after_stop_the_device_can_be_opened_again() -> None:
    first = DeviceSink(SessionClock())
    first.start(lambda event: None)
    first.stop()
    second = DeviceSink(SessionClock())
    second.start(lambda event: None)  # no lanza: el primero liberó el dispositivo
    second.stop()
