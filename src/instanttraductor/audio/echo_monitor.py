"""Monitor de eco (T024, research R14, SC-002): ¿vuelve la voz en español a la captura?

Si la exclusión de la captura falla (por ejemplo, el PID objetivo murió y la captura sigue viva sin excluir:
T1c), la voz sintetizada se recapta, se reconoce como si fuera inglés y se traduce otra vez. El autotest de
arranque no cubre los cambios a mitad de sesión, así que `EchoMonitor` compara de forma continua lo que
suena con lo que se capta y hace medible «0 ecos en 30 min» (`diagnostics.echo_events`).

Cómo funciona
-------------
- **Entradas**, cada una con su hora en el reloj de sesión: `feed_played(samples, at)` (lo que se entrega al
  dispositivo; es el gancho `DeviceSink.on_rendered`) y `feed_captured(chunk, arrival)` (los chunks de la
  captura y su hora de llegada).
- **Envolventes a 50 Hz:** de cada señal se calcula el valor RMS de cada bin de 20 ms sobre un eje de tiempo
  común. Los bins se rellenan por hora y recuento de muestras, así que el *jitter* de las horas no deja
  huecos ni duplica audio, y lo que no sonó cuenta como cero.
- **Ventana de 2 s:** cada 0,5 s se toma la envolvente captada de los últimos 2 s y se correlaciona
  (Pearson) con la reproducida desplazada de 0 a 0,6 s (el retardo del bucle: búfer de salida, mezcla de
  Windows y captura, de unas decenas a pocos cientos de ms). Antes de correlacionar se resta a cada
  envolvente su media móvil de 0,3 s, para quedarse con la modulación silábica y no con el ritmo lento de
  pausas y frases. El resultado de la ventana es la mayor correlación entre los retardos.
- **Decisión (con histéresis):** un eco es una racha de `confirm_windows` (3) ventanas seguidas con
  correlación ≥ `threshold`. Una racha cuenta **un** evento (`echo_events`) y lanza el aviso `on_echo`. El
  episodio acaba tras `clear_windows` (4) ventanas seguidas por debajo del umbral de salida (`threshold` −
  0,3, y no menos de 0,4), o tras 5 s sin voz propia. Con un eco que el audio original tapa en parte, la
  correlación de cada ventana oscila entre 0,5 y 0,95 (el original suena también en las pausas de la voz):
  el umbral de salida bajo evita partir un mismo eco en varios. Con la voz callada no hay nada que comparar
  y no se evalúa; con la captura muda la correlación es 0.

Calibración del umbral ---------------------- Entre dos hablas independientes (la voz en español y el audio
original) la correlación de envolventes no es cero: ambas tienen ritmo silábico parecido y el máximo sobre
31 retardos la infla. Un experimento sintético con habla artificial contra habla independiente dio, para el
máximo por ventana, mediana 0,39, p99 0,67 y máximo 0,76. Con `threshold` = 0,8 y 3 ventanas seguidas, esta
implementación no dio ningún falso eco en 2,5 h simuladas (1,5 h de habla, 0,5 h de música y 0,5 h de ruido
como audio original). Un eco 6 dB por encima del audio original se detectó siempre en unos 3 s; a +3 dB,
siempre y en 4 s (mediana); a 0 dB, el 97 % y en 10 s; a -3 dB, solo el 30 % en 40 s. Eso fija
`DEFAULT_THRESHOLD`: lo que sea más flojo que el audio original no se detecta. El autotest lo ajusta a cada
equipo con `calibrate_threshold`, entre `MIN_THRESHOLD` y `MAX_THRESHOLD`.

Hilos
-----
`feed_played` se llama desde el hilo de audio y `feed_captured` desde el consumidor de la captura: ambos son
seguros entre hilos y baratos (decenas de microsegundos). La evaluación y `on_echo` corren en el hilo de
`feed_captured`, fuera del cerrojo; `on_echo` debe volver enseguida.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Final

import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import PLAYBACK_RATE, AudioChunk

logger = logging.getLogger(__name__)

__all__ = [
    "BINS_PER_S",
    "DEFAULT_THRESHOLD",
    "MAX_THRESHOLD",
    "MIN_THRESHOLD",
    "EchoMonitor",
    "best_correlation",
    "calibrate_threshold",
    "detrend",
    "envelope_bins",
]

Samples = npt.NDArray[np.float32]
Envelope = npt.NDArray[np.float64]

BINS_PER_S: Final = 50  # la envolvente se calcula a 50 Hz: un bin cada 20 ms
WINDOW_S: Final = 2.0  # ventana de correlación
HOP_S: Final = 0.5  # cada cuánto se evalúa
MAX_DELAY_S: Final = 0.6  # retardos buscados: de 0 a 0,6 s
DETREND_BINS: Final = 15  # media móvil de 0,3 s que se resta a cada envolvente
DEFAULT_THRESHOLD: Final = 0.8
MIN_THRESHOLD: Final = 0.7  # por debajo, el habla independiente da falsos ecos (ver «Calibración»)
MAX_THRESHOLD: Final = 0.9
CONFIRM_WINDOWS: Final = 3  # ventanas seguidas por encima del umbral para dar un eco
CLEAR_WINDOWS: Final = 4  # ventanas seguidas por debajo del umbral de salida para dar el eco por terminado
RELEASE_MARGIN: Final = 0.3  # el umbral de salida es el de entrada menos esto...
MIN_RELEASE: Final = 0.4  # ...y nunca baja de aquí
REARM_SILENCE_S: Final = 5.0  # sin voz propia durante tanto tiempo, el episodio acaba
MIN_ACTIVITY: Final = 0.25  # fracción mínima de la ventana en que tiene que sonar la voz
ACTIVE_RMS: Final = 1e-4  # un bin con menos RMS (-80 dBFS) cuenta como silencio
HISTORY_S: Final = 30.0  # historial de las envolventes
_EPS: Final = 1e-9


# --------------------------------------------------------------------------------------------------
# Piezas puras: envolvente y correlación
# --------------------------------------------------------------------------------------------------


def envelope_bins(samples: Samples, rate: int) -> Envelope:
    """Envolvente RMS a 50 Hz de un array continuo que empieza en un límite de bin (se descarta el resto)."""
    size = rate // BINS_PER_S
    count = len(samples) // size
    if count == 0:
        return np.zeros(0)
    data = np.asarray(samples[: count * size], dtype=np.float64).reshape(count, size)
    return np.sqrt(np.mean(data * data, axis=1))


def detrend(envelope: Envelope, bins: int = DETREND_BINS) -> Envelope:
    """Resta a la envolvente su media móvil de `bins` bins (centrada, con los bordes repetidos)."""
    if len(envelope) == 0:
        return envelope
    padded = np.pad(envelope, (bins // 2, bins // 2), mode="edge")
    trend = np.convolve(padded, np.ones(bins) / bins, mode="valid")[: len(envelope)]
    return envelope - trend


def best_correlation(captured: Envelope, played: Envelope, max_lag: int) -> tuple[float, int] | None:
    """Mayor correlación (Pearson) entre `captured` y `played` desplazada de 0 a `max_lag` bins.

    `captured` tiene la longitud de la ventana y `played`, la de la ventana más `max_lag` bins: acaba en el
    mismo bin que `captured` y empieza `max_lag` bins antes. Devuelve `(correlación, retardo en bins)`. Si
    la captura es plana no hay nada que se parezca: `(0.0, 0)`. Si lo reproducido es plano en todos los
    retardos, `None`: no hay información. Las dos envolventes se pasan sin la tendencia (`detrend`) dentro
    de esta función.
    """
    window = len(captured)
    if len(played) != window + max_lag:
        raise ValueError(f"`played` debe tener {window + max_lag} bins y tiene {len(played)}.")
    c = detrend(captured)
    c = c - c.mean()
    c_norm = float(np.sqrt(np.dot(c, c)))
    if c_norm < _EPS:
        return 0.0, 0
    p = detrend(played)
    windows = np.lib.stride_tricks.sliding_window_view(p, window)  # (max_lag + 1, window)
    windows = windows - windows.mean(axis=1, keepdims=True)
    norms = np.sqrt(np.einsum("ij,ij->i", windows, windows))
    valid = norms > _EPS
    if not valid.any():
        return None
    r = np.full(len(windows), -1.0)
    r[valid] = (windows[valid] @ c) / (norms[valid] * c_norm)
    best = int(np.argmax(r))
    return float(r[best]), max_lag - best  # la fila `i` de las ventanas es el retardo `max_lag - i`


def calibrate_threshold(echo_correlation: float, clean_correlation: float) -> float:
    """Umbral de correlación según las dos medidas del autotest, entre `MIN_THRESHOLD` y `MAX_THRESHOLD`.

    - `echo_correlation`: lo que vale un eco de verdad en este equipo (el tono propio en la captura INCLUDE).
    - `clean_correlation`: lo que da el azar con el audio que suena ahora (el mismo tono contra la captura
      EXCLUDE).

    El umbral es el 80 % de lo que alcanza un eco real, y nunca menos que el azar más 0,3: así sigue por
    encima del ruido de fondo de este equipo y por debajo del eco más flojo que el equipo es capaz de dar.
    """
    echo = min(1.0, max(0.0, echo_correlation))
    clean = min(1.0, max(0.0, clean_correlation))
    return min(MAX_THRESHOLD, max(MIN_THRESHOLD, 0.8 * echo, clean + 0.3))


# --------------------------------------------------------------------------------------------------
# Envolventes por bins sobre un eje de tiempo común
# --------------------------------------------------------------------------------------------------


class _EnvelopeTrack:
    """Energía por bins de 20 ms sobre el eje de tiempo absoluto (reloj de sesión), con historial acotado.

    Cada bin guarda la suma de cuadrados y el número de muestras recibidas: el RMS se obtiene al leerlo. Un
    hueco del anillo solo vale para el bin que lo ocupa (`_tag`): lo que no se escribió (o ya salió del
    historial) es 0.
    """

    def __init__(self, size: int) -> None:
        self._size = size
        self._sumsq = np.zeros(size)
        self._count = np.zeros(size)
        self._tag = np.full(size, -1, dtype=np.int64)
        self.first = -1  # primer bin con datos
        self.newest = -1  # último bin con datos (puede estar a medias)

    def add(self, samples: Samples, rate: int, t_start: float) -> None:
        """Suma las muestras de un bloque que empieza en `t_start` (reloj de sesión)."""
        count = len(samples)
        if count == 0:
            return
        data = np.asarray(samples, dtype=np.float64)
        if not np.isfinite(data).all():
            data = np.where(np.isfinite(data), data, 0.0)
        bins = np.floor((t_start + np.arange(count) / rate) * BINS_PER_S).astype(np.int64)
        first = int(bins[0])
        local = bins - first
        sums = np.bincount(local, weights=data * data)
        counts = np.bincount(local)
        for offset in range(len(sums)):
            index = first + offset
            slot = index % self._size
            if self._tag[slot] != index:
                self._tag[slot] = index
                self._sumsq[slot] = 0.0
                self._count[slot] = 0.0
            self._sumsq[slot] += sums[offset]
            self._count[slot] += counts[offset]
        last = first + len(sums) - 1
        if self.first < 0:
            self.first = first
        self.newest = max(self.newest, last)

    def envelope(self, start: int, stop: int) -> Envelope:
        """RMS de los bins `start <= bin < stop` (0 donde no hay datos)."""
        bins = np.arange(start, stop)
        slots = bins % self._size
        valid = self._tag[slots] == bins
        counts = np.where(valid, self._count[slots], 0.0)
        sums = np.where(valid, self._sumsq[slots], 0.0)
        return np.sqrt(np.divide(sums, counts, out=np.zeros_like(sums), where=counts > 0))


# --------------------------------------------------------------------------------------------------
# EchoMonitor
# --------------------------------------------------------------------------------------------------


class EchoMonitor:
    """Detecta que la voz en español vuelve a la captura (ver el docstring del módulo).

    - `threshold`: correlación mínima por ventana; el autotest da el calibrado para el equipo
      (`SelftestResult.correlation_threshold`).
    - `on_echo(texto)`: aviso en español cuando empieza un eco. Se llama desde el hilo de `feed_captured`.
    - El resto de parámetros (`window_s`, `hop_s`, `max_delay_s`, `confirm_windows`, `clear_windows`,
      `rearm_silence_s`, `min_activity`, `history_s`) tienen los valores de la investigación y solo se tocan
      en pruebas.

    Uso desde la sesión: `DeviceSink(clock, on_rendered=monitor.feed_played)` y, por cada chunk leído,
    `monitor.feed_captured(chunk, arrival)` con `arrival` = `source.arrival_time(chunk.t_end)` (o
    `clock.now()`).
    """

    def __init__(
        self,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        on_echo: Callable[[str], None] | None = None,
        window_s: float = WINDOW_S,
        hop_s: float = HOP_S,
        max_delay_s: float = MAX_DELAY_S,
        confirm_windows: int = CONFIRM_WINDOWS,
        clear_windows: int = CLEAR_WINDOWS,
        rearm_silence_s: float = REARM_SILENCE_S,
        min_activity: float = MIN_ACTIVITY,
        history_s: float = HISTORY_S,
    ) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError(f"threshold debe estar en (0, 1] (recibido: {threshold}).")
        if confirm_windows < 1 or clear_windows < 1:
            raise ValueError("confirm_windows y clear_windows deben ser al menos 1.")
        self._threshold = float(threshold)
        self._release = min(self._threshold, max(MIN_RELEASE, self._threshold - RELEASE_MARGIN))
        self._on_echo = on_echo
        self._window = round(window_s * BINS_PER_S)
        self._hop = max(1, round(hop_s * BINS_PER_S))
        self._max_lag = round(max_delay_s * BINS_PER_S)
        if self._window < 2 * DETREND_BINS:
            raise ValueError(f"window_s debe ser de al menos {2 * DETREND_BINS / BINS_PER_S:.1f} s.")
        self._confirm = confirm_windows
        self._clear = clear_windows
        self._rearm_windows = max(1, round(rearm_silence_s / (self._hop / BINS_PER_S)))
        self._min_activity = min_activity
        size = round(history_s * BINS_PER_S)
        if size < self._window + self._max_lag + self._hop + 2:
            raise ValueError("history_s es demasiado corto para la ventana y el retardo máximo.")
        self._lock = threading.Lock()
        self._played = _EnvelopeTrack(size)
        self._captured = _EnvelopeTrack(size)
        self._last_end: int | None = None  # fin de la última ventana evaluada
        # Estado de la decisión.
        self._hits = 0  # ventanas seguidas por encima del umbral
        self._misses = 0  # ventanas seguidas por debajo
        self._quiet = 0  # evaluaciones seguidas sin voz propia
        self._in_echo = False
        self._events = 0
        self._evaluations = 0
        self._last_correlation: float | None = None
        self._last_delay_s: float | None = None

    # --- Entradas --------------------------------------------------------------------------------

    def feed_played(self, samples: Samples, at: float, rate: int = PLAYBACK_RATE) -> None:
        """Lo que se entregó al dispositivo: `samples` (mono, a `rate`) cuya primera muestra sonó en `at`.

        Es la firma del gancho `DeviceSink.on_rendered`. Los instantes sin llamada cuentan como silencio.
        """
        with self._lock:
            self._played.add(samples, rate, at)

    def feed_captured(self, chunk: AudioChunk, arrival: float) -> None:
        """Un chunk de la captura y su hora de llegada (reloj de sesión).

        El chunk cubre el intervalo `[arrival - duración, arrival]`.
        """
        with self._lock:
            self._captured.add(chunk.samples, chunk.sample_rate, arrival - chunk.duration)
        self._evaluate()

    # --- Estado ----------------------------------------------------------------------------------

    @property
    def echo_events(self) -> int:
        """Ecos detectados hasta ahora (`diagnostics.echo_events`): uno por episodio."""
        with self._lock:
            return self._events

    @property
    def in_echo(self) -> bool:
        """True mientras dura un eco ya detectado."""
        with self._lock:
            return self._in_echo

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def evaluations(self) -> int:
        """Ventanas evaluadas con voz propia, para diagnóstico."""
        with self._lock:
            return self._evaluations

    @property
    def last_correlation(self) -> float | None:
        """Correlación de la última ventana evaluada (None si aún no hubo ninguna)."""
        with self._lock:
            return self._last_correlation

    @property
    def last_delay_s(self) -> float | None:
        """Retardo (s) de la mayor correlación de la última ventana evaluada."""
        with self._lock:
            return self._last_delay_s

    def reset(self) -> None:
        """Olvida el historial y el episodio en curso, pero no el contador de eventos."""
        with self._lock:
            size = len(self._played._tag)
            self._played = _EnvelopeTrack(size)
            self._captured = _EnvelopeTrack(size)
            self._last_end = None
            self._hits = self._misses = self._quiet = 0
            self._in_echo = False

    # --- Evaluación ------------------------------------------------------------------------------

    def _evaluate(self) -> None:
        """Si ha pasado un `hop` de captura, correlaciona la última ventana y actualiza el episodio."""
        with self._lock:
            end = self._captured.newest  # los bins anteriores al último con datos están completos
            first = self._captured.first
            if end < 0 or end - first < self._window:
                return
            if self._last_end is not None and end - self._last_end < self._hop:
                return
            self._last_end = end
            captured = self._captured.envelope(end - self._window, end)
            played = self._played.envelope(end - self._window - self._max_lag, end)
        result = self._score(captured, played)
        message: str | None = None
        with self._lock:
            message = self._update_locked(result)
        if message is not None:
            logger.warning(message)
            self._notify(message)

    def _score(self, captured: Envelope, played: Envelope) -> tuple[float, int] | None:
        """Mayor correlación de la ventana, o None si no sonó la voz propia lo bastante para compararla."""
        if float(np.mean(played > ACTIVE_RMS)) < self._min_activity:
            return None
        return best_correlation(captured, played, self._max_lag)

    def _update_locked(self, result: tuple[float, int] | None) -> str | None:
        """Aplica el resultado de una ventana a la decisión. Devuelve el aviso si empieza un eco."""
        if result is None:
            self._quiet += 1
            self._hits = 0
            if self._quiet >= self._rearm_windows:
                self._in_echo = False
                self._misses = 0
            return None
        self._quiet = 0
        correlation, lag = result
        self._evaluations += 1
        self._last_correlation = correlation
        self._last_delay_s = lag / BINS_PER_S
        if correlation >= self._threshold:
            self._hits += 1
            self._misses = 0
            if not self._in_echo and self._hits >= self._confirm:
                self._in_echo = True
                self._events += 1
                return (
                    "Eco: la voz en español vuelve a la captura "
                    f"(correlación {correlation:.2f}, retardo {round(self._last_delay_s * 1000)} ms). "
                    "Es posible que la exclusión de la captura haya dejado de funcionar."
                )
            return None
        self._hits = 0
        if correlation >= self._release and self._in_echo:
            self._misses = 0  # un eco algo más flojo no cuenta como que haya terminado
        else:
            self._misses += 1
            if self._in_echo and self._misses >= self._clear:
                self._in_echo = False
        return None

    def _notify(self, message: str) -> None:
        callback = self._on_echo
        if callback is None:
            return
        try:
            callback(message)
        except Exception:
            logger.exception("Falló el callback on_echo del monitor de eco")
