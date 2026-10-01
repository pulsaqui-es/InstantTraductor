"""Registrador de métricas de la sesión: frases, serie de retraso, memoria y `diagnostics` (T030).

`MetricsRecorder` es el almacén que alimenta el informe (`metrics/report.py`, esquema de
`contracts/informe.md`). La sesión lo conecta al resto así::

    recorder = MetricsRecorder(drop_after_s=settings.drop_after_s)
    scheduler = Scheduler(..., on_record=recorder.add_record, on_lag_sample=recorder.add_lag_sample)
    recorder.set_startup_s(...)      # tras el arranque de los motores
    recorder.set_mt_model("hy-mt2-7b-q4")
    recorder.sample_memory(clock.now(), [llama.pid, voice.pid])   # desde el bucle de control, en cada vuelta
    recorder.count_echo_event()      # cada vez que el monitor de eco avisa
    recorder.count_component_restart()
    ...
    recorder.sample_memory(clock.now(), [llama.pid, voice.pid], force=True)   # la memoria del final
    recorder.set_underruns(sink.underruns)
    report = build_report(recorder, ...)

Todos los métodos son seguros entre hilos. Una sonda de memoria que falla (un proceso que desaparece, falta de
permisos) nunca rompe la sesión: se avisa en el registro y se salta la muestra.

Memoria (SC-005)
----------------
`sample_memory` lee la RSS del proceso núcleo y la suma de la de los procesos hijos (`psutil`): para cada PID
de la lista se cuenta el proceso y **todos sus descendientes**, sin contar ninguno dos veces (`uv` lanza el
servicio de voz como un proceso nieto). Ignora las llamadas que llegan antes de `memory_interval_s` desde la
última muestra (10 s), salvo con `force=True`, así la sesión puede llamarlo en cada vuelta de su bucle.
`rss_mb_min5` es la primera muestra desde el minuto 5 (`MEMORY_REFERENCE_S`), y `rss_mb_end`, la última; en
una sesión de menos de 5 minutos no hay minuto 5 y `rss_mb_min5` vale `None`. Los valores son megabytes
(MiB) enteros.

Retraso (SC-005)
----------------
`max_lag_s` es el máximo de la serie y `lag_over_drop_max_streak_s`, la racha continua más larga con el
retraso por encima de `drop_after_s`. La serie se muestrea cada 0,5 s y cada muestra vale hasta la
siguiente (se mantiene), así que una racha dura desde su primera muestra por encima hasta la primera por
debajo; si acaba la serie estando por encima, hasta `end_t` (la duración de la sesión) o, sin él, hasta una
muestra más. Es una estimación por exceso: nunca oculta un incumplimiento del límite de 10 s.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

import psutil

from instanttraductor.contracts import UtteranceRecord

__all__ = [
    "LAG_SAMPLE_INTERVAL_S",
    "MEMORY_INTERVAL_S",
    "MEMORY_REFERENCE_S",
    "MemorySample",
    "MetricsRecorder",
    "longest_streak_above",
    "max_lag",
    "process_rss_mb",
    "process_tree_rss_mb",
]

logger = logging.getLogger(__name__)

LAG_SAMPLE_INTERVAL_S: Final = 0.5  # separación de la serie de retraso (la misma que la del planificador)
MEMORY_REFERENCE_S: Final = 300.0  # «minuto 5» de SC-005: desde aquí, la memoria de referencia
MEMORY_INTERVAL_S: Final = 10.0  # separación mínima entre muestras de memoria
_MIB: Final = 1024 * 1024
_TIME_TOLERANCE_S: Final = 1e-9

LagSeries = Sequence[tuple[float, float]]


# --- sondas de memoria (psutil) ---------------------------------------------------------------------


def process_rss_mb(pid: int | None = None) -> float:
    """RSS (MiB) de un proceso, sin sus hijos; por defecto, el actual. Lanza `psutil.Error` si falla."""
    return psutil.Process(pid).memory_info().rss / _MIB


def process_tree_rss_mb(pids: Iterable[int]) -> float:
    """RSS (MiB) sumada de los procesos `pids` y de todos sus descendientes, sin contar ninguno dos veces.

    Un proceso que ya no existe, o al que no se puede acceder, cuenta 0 (sin excepción).
    """
    members: dict[int, psutil.Process] = {}
    for pid in pids:
        try:
            root = psutil.Process(pid)
            tree = [root, *root.children(recursive=True)]
        except psutil.Error:
            continue
        for process in tree:
            members.setdefault(process.pid, process)
    total = 0
    for process in members.values():
        try:
            total += process.memory_info().rss
        except psutil.Error:
            continue
    return total / _MIB


# --- retraso -----------------------------------------------------------------------------------------


def max_lag(series: LagSeries) -> float:
    """El mayor retraso de la serie `(t, lag)`; 0 si está vacía."""
    return max((lag for _, lag in series), default=0.0)


def longest_streak_above(
    series: LagSeries,
    threshold: float,
    *,
    end_t: float | None = None,
    interval_s: float = LAG_SAMPLE_INTERVAL_S,
) -> float:
    """Racha continua más larga (s) con el retraso por encima de `threshold`; ver el módulo.

    Cada muestra `(t, lag)` se mantiene hasta la siguiente. Una racha que sigue abierta al final de la serie
    acaba en `end_t` (si es posterior a la última muestra) o, si no, `interval_s` después de ella.
    """
    longest = 0.0
    start: float | None = None
    for t, lag in series:
        if lag > threshold:
            if start is None:
                start = t
        elif start is not None:
            longest = max(longest, t - start)
            start = None
    if start is not None:
        last_t = series[-1][0]
        end = end_t if end_t is not None and end_t > last_t else last_t + interval_s
        longest = max(longest, end - start)
    return longest


# --- registrador -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemorySample:
    """Memoria en un instante: `t` en el reloj de sesión; las RSS, en MiB."""

    t: float
    core_mb: float
    children_mb: float


class MetricsRecorder:
    """Guarda lo que alimenta el informe y calcula sus `diagnostics`.

    - `drop_after_s`: `umbral_descartar_s` de los ajustes, para la racha de retraso.
    - `lag_interval_s`: separación de la serie de retraso (lo que dura la última muestra de una racha
      abierta).
    - `memory_interval_s`: separación mínima entre muestras de memoria.
    - `core_rss_mb` y `children_rss_mb`: sondas de memoria (se sustituyen en los tests). La primera no recibe
      nada y devuelve MiB del núcleo; la segunda recibe los PID hijos y devuelve MiB de ellos y de sus
      descendientes.
    """

    def __init__(
        self,
        *,
        drop_after_s: float = 8.0,
        lag_interval_s: float = LAG_SAMPLE_INTERVAL_S,
        memory_interval_s: float = MEMORY_INTERVAL_S,
        core_rss_mb: Callable[[], float] = process_rss_mb,
        children_rss_mb: Callable[[Iterable[int]], float] = process_tree_rss_mb,
    ) -> None:
        if not drop_after_s > 0:
            raise ValueError(f"drop_after_s debe ser positivo (recibido: {drop_after_s}).")
        self._drop_after_s = drop_after_s
        self._lag_interval_s = lag_interval_s
        self._memory_interval_s = memory_interval_s
        self._core_rss_mb = core_rss_mb
        self._children_rss_mb = children_rss_mb

        self._lock = threading.Lock()
        self._records: dict[int, UtteranceRecord] = {}
        self._lag_series: list[tuple[float, float]] = []
        self._memory: list[MemorySample] = []
        self._startup_s: float | None = None
        self._echo_events = 0
        self._component_restarts = 0
        self._underruns = 0
        self._mt_model: str | None = None

    # --- entrada ---------------------------------------------------------------------------------------

    def add_record(self, record: UtteranceRecord) -> None:
        """Guarda el registro de una frase cerrada (el *callback* `on_record` del planificador).

        Si llega otro con el mismo `unit_id`, sustituye al anterior.
        """
        with self._lock:
            self._records[record.unit_id] = record

    def add_lag_sample(self, t: float, lag_s: float) -> None:
        """Guarda una muestra `(t, lag)` de la serie de retraso (el *callback* `on_lag_sample`).

        Una muestra con algún valor que no es finito (NaN, infinito) se ignora.
        """
        if not (math.isfinite(t) and math.isfinite(lag_s)):
            return
        with self._lock:
            self._lag_series.append((t, lag_s))

    def sample_memory(
        self, t: float, child_pids: Iterable[int | None] = (), *, force: bool = False
    ) -> MemorySample | None:
        """Mide la memoria del núcleo y de los hijos en `t` (reloj de sesión).

        Devuelve la muestra, o `None` si se saltó: por llegar antes de `memory_interval_s` desde la anterior
        (salvo con `force=True`) o porque una sonda falló (se avisa en el registro). Los PID `None` (un hijo
        sin arrancar) se ignoran.
        """
        with self._lock:
            last = self._memory[-1].t if self._memory else None
        if not force and last is not None and t - last < self._memory_interval_s - _TIME_TOLERANCE_S:
            return None
        pids = [pid for pid in child_pids if pid is not None]
        try:
            sample = MemorySample(t=t, core_mb=self._core_rss_mb(), children_mb=self._children_rss_mb(pids))
        except Exception as error:  # una sonda que falla no puede romper la sesión
            logger.warning("No se pudo medir la memoria (%s): se salta la muestra.", error)
            return None
        with self._lock:
            self._memory.append(sample)
        return sample

    def set_startup_s(self, seconds: float) -> None:
        """Tiempo de arranque de los motores (`startup_s`), medido aparte de la sesión.

        Si no es un número finito, el informe lo deja en `null`.
        """
        with self._lock:
            self._startup_s = seconds

    def set_mt_model(self, name: str) -> None:
        """Modelo de traducción usado (`mt_model`): el 7B o la reserva 1.8B."""
        with self._lock:
            self._mt_model = name

    def count_echo_event(self, count: int = 1) -> None:
        """Suma `count` veces que el monitor de eco detectó la voz propia en la captura."""
        if count < 0:
            raise ValueError(f"El recuento de eco no puede ser negativo (recibido: {count}).")
        with self._lock:
            self._echo_events += count

    def count_component_restart(self, count: int = 1) -> None:
        """Suma `count` reinicios de un componente (llama-server, servicio de voz...)."""
        if count < 0:
            raise ValueError(f"El recuento de reinicios no puede ser negativo (recibido: {count}).")
        with self._lock:
            self._component_restarts += count

    def set_underruns(self, count: int) -> None:
        """Total de cortes de audio (`underruns`) que cuenta el sink; es un total, no un incremento."""
        if count < 0:
            raise ValueError(f"El recuento de underruns no puede ser negativo (recibido: {count}).")
        with self._lock:
            self._underruns = count

    # --- salida ----------------------------------------------------------------------------------------

    @property
    def records(self) -> tuple[UtteranceRecord, ...]:
        """Los registros guardados, en orden de `unit_id` (una copia)."""
        with self._lock:
            return tuple(self._records[unit_id] for unit_id in sorted(self._records))

    @property
    def lag_series(self) -> tuple[tuple[float, float], ...]:
        """La serie de retraso `(t, lag)` (una copia)."""
        with self._lock:
            return tuple(self._lag_series)

    @property
    def memory_samples(self) -> tuple[MemorySample, ...]:
        """Las muestras de memoria (una copia)."""
        with self._lock:
            return tuple(self._memory)

    def diagnostics(self, *, end_t: float | None = None, drop_after_s: float | None = None) -> dict[str, Any]:
        """El bloque `diagnostics` de `contracts/informe.md`, con sus claves en ese orden.

        `end_t`: duración de la sesión, donde acaba una racha de retraso que sigue abierta (ver el módulo).
        `drop_after_s`: umbral de descarte para la racha, si no es el del constructor (el informe pasa el de
        los ajustes que él mismo recoge). Segundos con 3 decimales y memoria en MiB enteros; lo que no se
        midió, `None`.
        """
        with self._lock:
            series = tuple(self._lag_series)
            memory = tuple(self._memory)
            startup_s, mt_model = self._startup_s, self._mt_model
            echo_events, restarts, underruns = self._echo_events, self._component_restarts, self._underruns
        reference = next((m for m in memory if m.t >= MEMORY_REFERENCE_S - _TIME_TOLERANCE_S), None)
        last = memory[-1] if memory else None
        streak = longest_streak_above(
            series,
            self._drop_after_s if drop_after_s is None else drop_after_s,
            end_t=end_t,
            interval_s=self._lag_interval_s,
        )
        return {
            "startup_s": None if startup_s is None or not math.isfinite(startup_s) else round(startup_s, 3),
            "rss_mb_min5": None if reference is None else round(reference.core_mb),
            "rss_mb_end": None if last is None else round(last.core_mb),
            "rss_children_mb_min5": None if reference is None else round(reference.children_mb),
            "rss_children_mb_end": None if last is None else round(last.children_mb),
            "max_lag_s": round(max_lag(series), 3),
            "lag_over_drop_max_streak_s": round(streak, 3),
            "echo_events": echo_events,
            "component_restarts": restarts,
            "underruns": underruns,
            "mt_model": mt_model,
        }
