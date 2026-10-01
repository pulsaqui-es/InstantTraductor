"""Captura por proceso con el dispositivo real (T015). Marcador `device`: solo los lanza el orquestador.

OJO: abren un `miniaudio.PlaybackDevice` en el dispositivo por defecto y reproducen un tono corto y bajo
(-30 dBFS): se oye en los auriculares. Qué se comprueba:

- `AudioSourceContract` con la captura real (EXCLUDE sobre el propio PID).
- Un tono propio NO aparece en la captura EXCLUDE y SÍ en la INCLUDE, que hace de control positivo: sin
  ella, un «no aparece» no probaría nada, porque el sonido podría no haber salido del equipo.
- La hora de llegada de los chunks sigue de cerca al reloj de audio.

El detector de tonos es el del spike S4 (`spikes/audio/audio_spike/analisis.py`): compara la amplitud del seno
con la mediana de las frecuencias vecinas, así que aguanta que suene otra cosa mientras tanto.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Generator

import miniaudio
import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource
from instanttraductor.contracts import CAPTURE_RATE, AudioChunk, AudioSource
from instanttraductor.pipeline.clock import SessionClock
from tests.contract.test_audio_contract import AudioSourceContract

pytestmark = pytest.mark.device

Samples = npt.NDArray[np.float32]

TONE_HZ = 1234.0  # frecuencia poco común: es la del autotest
TONE_S = 0.4
TONE_DBFS = -30.0
PRESENT_DB = 15.0  # el spike midió 118-139 dB con tono y 0-13 dB sin él


def peak_tone_ratio_db(
    x: Samples, rate: int, freq_hz: float, *, window_s: float = 0.3, step_s: float = 0.05
) -> float:
    """Mayor relación (dB) entre la amplitud del seno a `freq_hz` y la mediana de 40 frecuencias vecinas.

    Una ventana deslizante de `window_s` con ventana de Hann. Con silencio digital da 0 dB.
    """
    size, step = round(window_s * rate), round(step_s * rate)
    if len(x) < size:
        return 0.0
    window = np.hanning(size)
    refs = np.linspace(0.55 * freq_hz, min(1.8 * freq_hz, 0.45 * rate), 40)
    refs = refs[np.abs(refs - freq_hz) > 0.08 * freq_hz]
    phase = np.exp(-2j * np.pi * np.outer(np.concatenate([[freq_hz], refs]), np.arange(size)) / rate)
    eps = 1e-9
    best = 0.0
    for start in range(0, len(x) - size + 1, step):
        amplitude = 2.0 * np.abs(phase @ (x[start : start + size].astype(np.float64) * window)) / window.sum()
        tone = max(float(amplitude[0]), eps)
        background = max(float(np.median(amplitude[1:])), eps)
        best = max(best, 20.0 * np.log10(tone / background))
    return best


def drain(source: ProcessLoopbackSource) -> list[AudioChunk]:
    """Todos los chunks que la fuente tiene ya en cola."""
    chunks: list[AudioChunk] = []
    while (chunk := source.read(0.0)) is not None:
        chunks.append(chunk)
    return chunks


def samples_of(chunks: list[AudioChunk]) -> Samples:
    return np.concatenate([c.samples for c in chunks]) if chunks else np.zeros(0, dtype=np.float32)


class TonePlayer:
    """Dispositivo por defecto (48 kHz, float32, estéreo, periodos de 20 ms x 3) con ceros y tonos a demanda.

    Es la configuración de `DeviceSink` (ADR-0010), mínima y sin depender de él: el tono ya sale a 48 kHz.
    """

    RATE = 48_000

    def __init__(self) -> None:
        self._pending: deque[tuple[Samples, threading.Event]] = deque()
        self._current: Samples | None = None
        self._done: threading.Event | None = None
        self._pos = 0
        self._device: miniaudio.PlaybackDevice | None = None

    def __enter__(self) -> TonePlayer:
        self._device = miniaudio.PlaybackDevice(
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=2,
            sample_rate=self.RATE,
            buffersize_msec=20,
            callback_periods=3,
            backends=[miniaudio.Backend.WASAPI],
            app_name="InstantTraductor-tests",
        )
        generator = self._generate()
        next(generator)  # el generador tiene que estar ya arrancado
        self._device.start(generator)
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._device is not None:
            self._device.close()
            self._device = None

    def play(self, freq_hz: float, seconds: float, dbfs: float) -> threading.Event:
        """Encola un tono (con fundidos de 5 ms) y devuelve el evento que se activa al entregarlo entero."""
        count = round(seconds * self.RATE)
        tone = ((10 ** (dbfs / 20)) * np.sin(2 * np.pi * freq_hz * np.arange(count) / self.RATE)).astype(
            np.float32
        )
        fade = min(round(0.005 * self.RATE), count // 2)
        ramp = (0.5 * (1 - np.cos(np.pi * np.arange(fade) / fade))).astype(np.float32)
        tone[:fade] *= ramp
        tone[count - fade :] *= ramp[::-1]
        done = threading.Event()
        self._pending.append((tone, done))
        return done

    def _generate(self) -> Generator[npt.NDArray[np.float32] | bytes, int, None]:
        frames = yield b""
        while True:
            out = np.zeros((frames, 2), dtype=np.float32)
            if self._current is None and self._pending:
                self._current, self._done = self._pending.popleft()
                self._pos = 0
            if self._current is not None:
                piece = self._current[self._pos : self._pos + frames]
                out[: len(piece), :] = piece[:, None]
                self._pos += len(piece)
                if self._pos >= len(self._current):
                    self._current = None
                    assert self._done is not None
                    self._done.set()
            frames = yield out


class TestProcessLoopbackSourceDevice(AudioSourceContract):
    """El contrato de `AudioSource` con la captura real. Es una fuente en vivo: solo termina con `stop()`."""

    finite = False

    @pytest.fixture
    def make_impl(self) -> Callable[[], AudioSource]:
        return lambda: ProcessLoopbackSource(SessionClock())


def test_an_own_tone_is_absent_in_exclude_and_present_in_include() -> None:
    clock = SessionClock()
    exclude = ProcessLoopbackSource(clock)  # EXCLUDE sobre el propio PID: la captura que usará la app
    include = ProcessLoopbackSource(clock, include=True)  # INCLUDE sobre el mismo PID: control positivo
    exclude.start()
    include.start()
    try:
        with TonePlayer() as player:
            time.sleep(0.5)  # el dispositivo ya está abierto y reproduciendo ceros: hay una sesión activa
            assert player.play(TONE_HZ, TONE_S, TONE_DBFS).wait(5.0), "el dispositivo no entregó el tono"
            time.sleep(0.6)  # la captura tarda unas decenas de ms en recibirlo
        heard_exclude = samples_of(drain(exclude))
        heard_include = samples_of(drain(include))
    finally:
        exclude.stop()
        include.stop()
    ratio_exclude = peak_tone_ratio_db(heard_exclude, CAPTURE_RATE, TONE_HZ)
    ratio_include = peak_tone_ratio_db(heard_include, CAPTURE_RATE, TONE_HZ)
    assert ratio_include >= PRESENT_DB, (
        f"el control positivo (INCLUDE) no oyó el tono propio ({ratio_include:.1f} dB): "
        "el sonido no salió o la captura no funciona; el resultado de EXCLUDE no prueba nada"
    )
    assert ratio_exclude < PRESENT_DB, (
        f"el tono propio reapareció en la captura EXCLUDE ({ratio_exclude:.1f} dB): hay realimentación"
    )


def test_the_arrival_time_follows_the_audio_clock() -> None:
    clock = SessionClock()
    source = ProcessLoopbackSource(clock)
    source.start()
    try:
        chunks = [chunk for _ in range(150) if (chunk := source.read(1.0)) is not None]  # unos 3 s
        assert len(chunks) == 150
        delays = []
        for chunk in chunks[10:]:
            arrival = source.arrival_time(chunk.t_end)
            assert arrival is not None
            delays.append(arrival - chunk.t_end)
        # El audio llega con unas decenas de ms de retraso sobre su reloj: ni antes ni segundos tarde.
        assert min(delays) >= -0.01
        assert float(np.median(delays)) < 0.15
        assert max(delays) < 0.5
    finally:
        source.stop()


def test_a_second_capture_of_the_same_process_works_at_the_same_time() -> None:
    clock = SessionClock()
    first, second = ProcessLoopbackSource(clock), ProcessLoopbackSource(clock, include=True)
    first.start()
    second.start()
    try:
        assert first.read(2.0) is not None
        assert second.read(2.0) is not None
    finally:
        first.stop()
        second.stop()
