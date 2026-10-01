"""Autotest de la exclusión (T024, ADR-0010): ¿la voz propia llega a la captura?

La captura por proceso excluye el sonido del propio núcleo (`include=False`). Si la exclusión falla, la voz en
español se recapta, se reconoce como inglés y se traduce otra vez. El autotest lo comprueba al arrancar y tras
cada reapertura de la captura, con un **control positivo** para que un «no aparece» valga algo:

1. Abre dos capturas del mismo proceso: la EXCLUDE (la de la app) y una INCLUDE temporal (solo el sonido
   propio).
2. Hace sonar por el *sink* un tono de 0,3 s a 1234 Hz y -30 dBFS (una frecuencia poco común y muy bajo).
3. El tono **NO** debe aparecer en la captura EXCLUDE y **SÍ** en la INCLUDE. Si no aparece en la INCLUDE, el
   sonido no salió (volumen a 0, dispositivo mudo...) y no se puede afirmar nada: también es un fallo.

Detección del tono: la del spike S4 (`spikes/audio/audio_spike/analisis.py`). Se mide la amplitud del seno a
1234 Hz (demodulación con ventana de Hann) frente a la **mediana** de la amplitud en 40 frecuencias vecinas.
Un tono puro destaca decenas de dB sobre esa mediana; la música y el ruido no, así que el resultado no
depende de que suene otra cosa en el PC: el spike midió 118-139 dB con tono y 0-13 dB sin él, y el umbral es
de 15 dB.

Umbral del monitor de eco: con las mismas dos capturas se mide, con la envolvente a 50 Hz del `EchoMonitor`,
cuánto se parece el tono a un pulso de 0,3 s en la INCLUDE (lo que vale un eco de verdad en este equipo) y
en la EXCLUDE (lo que da el azar con el audio que suena ahora), y `calibrate_threshold` saca de ahí el
umbral de correlación.

El autotest bloquea unos 1,5 s (lo que dura el audio que lee de las capturas; más si la cola del sink tenía
voz por delante del tono) y no usa relojes: el tiempo lo da el propio audio capturado. Se llama desde la
sesión, **en un hilo propio** cuando se repite tras una reapertura (`on_reopen` de la captura se llama desde
su hilo y debe volver enseguida).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import numpy.typing as npt

from instanttraductor.audio.echo_monitor import (
    BINS_PER_S,
    DEFAULT_THRESHOLD,
    calibrate_threshold,
    envelope_bins,
)
from instanttraductor.contracts import (
    CAPTURE_RATE,
    PLAYBACK_RATE,
    AudioChunk,
    AudioSink,
    AudioSource,
    SpeechPiece,
)

logger = logging.getLogger(__name__)

__all__ = [
    "PRESENT_DB",
    "SELFTEST_UNIT_ID",
    "TONE_DBFS",
    "TONE_HZ",
    "TONE_S",
    "SelftestResult",
    "make_tone",
    "pulse_correlation",
    "run_echo_selftest",
    "tone_ratio_db",
]

Samples = npt.NDArray[np.float32]

SELFTEST_UNIT_ID: Final = -1  # reservado: el planificador ignora los eventos de unidades que no conoce
TONE_HZ: Final = 1234.0
TONE_S: Final = 0.3
TONE_DBFS: Final = -30.0
FADE_S: Final = 0.005  # fundidos de coseno elevado: sin chasquidos de banda ancha
PRESENT_DB: Final = (
    15.0  # a partir de aquí el tono «aparece» (el spike midió 118-139 dB con tono y 0-13 sin él)
)
SETTLE_S: Final = 0.4  # audio de cada captura que se lee antes del tono: ya están dando datos
TAIL_S: Final = 0.8  # audio que se sigue leyendo cuando el tono ha acabado de sonar: latencia de la captura
MAX_QUEUE_WAIT_S: Final = 6.0  # tope de lo que se espera a que el tono suene si había voz por delante
READ_TIMEOUT_S: Final = 0.2
IDLE_LIMIT_S: Final = 3.0  # sin audio durante tanto tiempo, la captura no funciona
_WINDOW_S: Final = 0.3  # ventana de la detección del tono
_STEP_S: Final = 0.05
_REF_COUNT: Final = 40  # frecuencias de referencia para la mediana
_REF_BAND: Final = (0.55, 1.8)  # zona del espectro de las referencias, relativa a la del tono
_REF_EXCLUDE: Final = 0.08  # banda alrededor del tono que no se usa de referencia
_CONTEXT_BINS: Final = 10  # bins de silencio a cada lado del pulso de la plantilla (0,2 s)
_EPS: Final = 1e-9


@dataclass(frozen=True, slots=True)
class SelftestResult:
    """Resultado del autotest.

    - `ok`: el tono propio no aparece en la captura EXCLUDE y sí en la INCLUDE.
    - `reason`: si no es `ok`, el motivo en español para la persona; vacío si es `ok`.
    - `correlation_threshold`: umbral de correlación para el `EchoMonitor`, calibrado con esta ejecución
      (`DEFAULT_THRESHOLD` si el autotest falló o no pudo medirlo).
    - `include_ratio_db` / `exclude_ratio_db`: cuánto destaca el tono sobre el fondo en cada captura (para el
      registro); None si no se pudo medir.
    """

    ok: bool
    reason: str
    correlation_threshold: float
    include_ratio_db: float | None = field(default=None, compare=False)
    exclude_ratio_db: float | None = field(default=None, compare=False)


# --------------------------------------------------------------------------------------------------
# Tono y detección
# --------------------------------------------------------------------------------------------------


def make_tone(
    freq_hz: float = TONE_HZ,
    seconds: float = TONE_S,
    dbfs: float = TONE_DBFS,
    rate: int = PLAYBACK_RATE,
    fade_s: float = FADE_S,
) -> Samples:
    """Seno mono float32 con fundidos de coseno elevado en los extremos."""
    count = round(seconds * rate)
    tone = (10 ** (dbfs / 20)) * np.sin(2 * np.pi * freq_hz * np.arange(count) / rate)
    fade = min(round(fade_s * rate), count // 2)
    if fade > 0:
        ramp = 0.5 * (1 - np.cos(np.pi * np.arange(fade) / fade))
        tone[:fade] *= ramp
        tone[count - fade :] *= ramp[::-1]
    return tone.astype(np.float32)


def tone_ratio_db(
    samples: Samples,
    rate: int,
    freq_hz: float = TONE_HZ,
    *,
    window_s: float = _WINDOW_S,
    step_s: float = _STEP_S,
) -> float:
    """Mayor relación (dB) entre la amplitud del seno a `freq_hz` y la mediana de 40 frecuencias vecinas.

    Una ventana deslizante de `window_s` con ventana de Hann. Con silencio digital (o con menos audio que
    una ventana) da 0 dB. Es la detección del spike S4: robusta a que suene otra cosa, porque compara con el
    fondo.
    """
    size, step = round(window_s * rate), max(1, round(step_s * rate))
    if len(samples) < size:
        return 0.0
    refs = np.linspace(_REF_BAND[0] * freq_hz, min(_REF_BAND[1] * freq_hz, 0.45 * rate), _REF_COUNT)
    refs = refs[np.abs(refs - freq_hz) > _REF_EXCLUDE * freq_hz]
    window = np.hanning(size)
    phase = np.exp(-2j * np.pi * np.outer(np.concatenate([[freq_hz], refs]), np.arange(size)) / rate)
    frames = np.lib.stride_tricks.sliding_window_view(np.asarray(samples, dtype=np.float64), size)[::step]
    amplitude = 2.0 * np.abs((frames * window) @ phase.T) / window.sum()  # (ventanas, 1 + referencias)
    tone = np.maximum(amplitude[:, 0], _EPS)
    background = np.maximum(np.median(amplitude[:, 1:], axis=1), _EPS)
    return float(np.max(20.0 * np.log10(tone / background)))


def pulse_correlation(samples: Samples, rate: int) -> float:
    """Mayor correlación (Pearson) entre la envolvente a 50 Hz de `samples` y un pulso de `TONE_S` aislado.

    Es la medida que calibra el umbral del `EchoMonitor`: con el tono propio en la captura INCLUDE da casi
    1; en la EXCLUDE, lo que dé el azar con el audio que suene. Con silencio (o sin audio suficiente) da 0.
    """
    envelope = envelope_bins(samples, rate)
    pulse = round(TONE_S * BINS_PER_S)
    template = np.concatenate([np.zeros(_CONTEXT_BINS), np.ones(pulse), np.zeros(_CONTEXT_BINS)])
    if len(envelope) < len(template):
        return 0.0
    windows = np.lib.stride_tricks.sliding_window_view(envelope, len(template))
    windows = windows - windows.mean(axis=1, keepdims=True)
    centred = template - template.mean()
    norms = np.sqrt(np.einsum("ij,ij->i", windows, windows))
    valid = norms > _EPS
    if not valid.any():
        return 0.0
    r = (windows[valid] @ centred) / (norms[valid] * np.sqrt(np.dot(centred, centred)))
    return float(max(0.0, np.max(r)))


# --------------------------------------------------------------------------------------------------
# Lectura de las capturas
# --------------------------------------------------------------------------------------------------


class _NoAudio(Exception):
    """Una captura no entrega audio: no funciona."""


class _Capture:
    """Una fuente y el audio que se ha leído de ella."""

    def __init__(self, label: str, source: AudioSource) -> None:
        self.label = label
        self.source = source
        self.chunks: list[AudioChunk] = []
        self.heard_s = 0.0

    def audio(self) -> Samples:
        if not self.chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate([chunk.samples for chunk in self.chunks]).astype(np.float32)


def _listen(captures: Sequence[_Capture], seconds: float) -> None:
    """Lee de cada captura `seconds` más de audio (por la duración de los chunks, sin relojes).

    Termina antes si una fuente se acaba (`exhausted`). Lanza `_NoAudio` si una captura pasa `IDLE_LIMIT_S`
    sin dar un solo chunk.
    """
    targets = {capture.label: capture.heard_s + seconds for capture in captures}
    idle = {capture.label: 0.0 for capture in captures}
    finished: set[str] = set()  # fuentes que se acabaron: no se espera más de ellas
    while True:
        pending = [c for c in captures if c.label not in finished and c.heard_s < targets[c.label] - _EPS]
        if not pending:
            return
        for capture in pending:
            chunk = capture.source.read(READ_TIMEOUT_S)
            if chunk is not None:
                idle[capture.label] = 0.0
                capture.chunks.append(chunk)
                capture.heard_s += chunk.duration
            elif capture.source.exhausted:
                if not capture.chunks:
                    raise _NoAudio(capture.label)
                finished.add(capture.label)
            else:
                idle[capture.label] += READ_TIMEOUT_S
                if idle[capture.label] >= IDLE_LIMIT_S:
                    raise _NoAudio(capture.label)


# --------------------------------------------------------------------------------------------------
# El autotest
# --------------------------------------------------------------------------------------------------


def _failure(reason: str, **extra: float | None) -> SelftestResult:
    logger.warning("Autotest de la exclusión fallido: %s", reason)
    return SelftestResult(False, reason, DEFAULT_THRESHOLD, **extra)


def run_echo_selftest(sink: AudioSink, make_source: Callable[[bool], AudioSource]) -> SelftestResult:
    """Comprueba que la voz propia no llega a la captura EXCLUDE (con la INCLUDE como control positivo).

    - `sink`: por donde suena el tono; ya arrancado (`sink.start`). Se usa la unidad reservada
      `SELFTEST_UNIT_ID`.
    - `make_source(include)`: crea una fuente nueva y sin arrancar: la de la app si `include` es False
      (EXCLUDE) y la temporal de control si es True (INCLUDE), ambas sobre el mismo proceso.

    Bloquea mientras lee audio de las capturas (unos 1,5 s). Nunca lanza por un fallo de la captura: lo
    devuelve en `SelftestResult.reason`. Las dos fuentes se paran siempre.
    """
    exclude_source: AudioSource | None = None
    include_source: AudioSource | None = None
    try:
        try:
            exclude_source = make_source(False)
            exclude_source.start()
            include_source = make_source(True)
            include_source.start()
        except Exception as exc:
            return _failure(f"No se pudo abrir la captura del autotest: {exc}")
        exclude = _Capture("EXCLUDE", exclude_source)
        include = _Capture("INCLUDE", include_source)
        try:
            _listen([exclude, include], SETTLE_S)
            sink.enqueue(SpeechPiece(unit_id=SELFTEST_UNIT_ID, samples=make_tone(), is_last=True))
            wait_s = min(max(sink.pending_seconds(), TONE_S), MAX_QUEUE_WAIT_S)  # hasta que acaba el tono
            _listen([exclude, include], wait_s + TAIL_S)
        except _NoAudio as exc:
            return _failure(
                f"La captura {exc} no entregó audio durante el autotest: no se puede comprobar la exclusión."
            )
        except Exception as exc:
            return _failure(f"El autotest no pudo completarse: {exc}")
        return _evaluate(exclude, include)
    finally:
        for source in (exclude_source, include_source):
            if source is not None:
                try:
                    source.stop()
                except Exception:
                    logger.exception("No se pudo parar la captura del autotest")


def _evaluate(exclude: _Capture, include: _Capture) -> SelftestResult:
    exclude_audio, include_audio = exclude.audio(), include.audio()
    exclude_db = tone_ratio_db(exclude_audio, CAPTURE_RATE)
    include_db = tone_ratio_db(include_audio, CAPTURE_RATE)
    measures = {"include_ratio_db": include_db, "exclude_ratio_db": exclude_db}
    logger.info("Autotest: el tono destaca %.1f dB en INCLUDE y %.1f dB en EXCLUDE", include_db, exclude_db)
    if exclude_db >= PRESENT_DB:
        return _failure(
            f"El tono propio ({TONE_HZ:.0f} Hz) reaparece en la captura que debería excluirlo (destaca "
            f"{exclude_db:.0f} dB sobre el fondo): hay realimentación y la voz en español "
            "se volvería a traducir.",
            **measures,
        )
    if include_db < PRESENT_DB:
        return _failure(
            f"El control positivo no oyó el tono propio (destaca {include_db:.0f} dB sobre el fondo): "
            "el sonido no llegó a la captura. ¿Está la voz a volumen 0, la salida silenciada o la "
            "reproducción ocupada? Sin esa comprobación no se puede afirmar que la exclusión funcione.",
            **measures,
        )
    echo_correlation = pulse_correlation(include_audio, CAPTURE_RATE)
    clean_correlation = pulse_correlation(exclude_audio, CAPTURE_RATE)
    threshold = calibrate_threshold(echo_correlation, clean_correlation)
    logger.info(
        "Autotest correcto: correlación del eco %.2f, del azar %.2f; umbral del monitor de eco %.2f",
        echo_correlation,
        clean_correlation,
        threshold,
    )
    return SelftestResult(True, "", threshold, **measures)
