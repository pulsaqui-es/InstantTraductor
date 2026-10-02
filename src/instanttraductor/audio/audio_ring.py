"""Anillo del audio captado (spec 002, T023): los últimos segundos, para el verificador de idioma.

El hilo de escucha añade los chunks (ya con el AGC) y el de traducción pide el tramo de una unidad por su
tiempo de audio (`TranslationUnit.t_start` y `t_end`). Es seguro entre esos dos hilos.
"""

from __future__ import annotations

import threading

import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import AudioChunk

Samples = npt.NDArray[np.float32]


class AudioRing:
    """Guarda los últimos `capacity_s` segundos de audio contiguo de una fuente (búfer circular)."""

    def __init__(self, sample_rate: int, capacity_s: float = 30.0) -> None:
        if capacity_s <= 0:
            raise ValueError("capacity_s debe ser positivo.")
        self.sample_rate = sample_rate
        self._capacity = int(round(capacity_s * sample_rate))
        self._buffer = np.zeros(self._capacity, dtype=np.float32)
        # Índice absoluto (en muestras desde t=0 del audio) del final de lo guardado; None si aún no hay nada.
        self._end_sample: int | None = None
        self._lock = threading.Lock()

    def append(self, chunk: AudioChunk) -> None:
        samples = np.asarray(chunk.samples, dtype=np.float32)
        start = int(round(chunk.t_start * self.sample_rate))
        with self._lock:
            if self._end_sample is None:
                self._end_sample = start
            elif start > self._end_sample:  # hueco: se rellena con silencio
                self._write(np.zeros(min(start - self._end_sample, self._capacity), np.float32))
                self._end_sample = start
            self._write(samples)

    def _write(self, samples: Samples) -> None:
        """Escribe a partir de `_end_sample` y lo avanza. Si no cabe, solo cuenta lo último."""
        assert self._end_sample is not None
        n = len(samples)
        if n == 0:
            return
        if n > self._capacity:
            self._end_sample += n - self._capacity
            samples = samples[-self._capacity :]
            n = self._capacity
        pos = self._end_sample % self._capacity
        first = min(n, self._capacity - pos)
        self._buffer[pos : pos + first] = samples[:first]
        self._buffer[: n - first] = samples[first:]
        self._end_sample += n

    def slice(self, t_start: float, t_end: float) -> Samples:
        """Audio entre `t_start` y `t_end` (tiempo de audio).

        Solo se devuelve la parte que hay: lo que ya salió del anillo o aún no ha llegado falta (puede quedar
        vacío).
        """
        with self._lock:
            if self._end_sample is None or t_end <= t_start:
                return np.zeros(0, dtype=np.float32)
            oldest = self._end_sample - self._capacity
            a = max(int(round(t_start * self.sample_rate)), oldest, 0)
            b = min(int(round(t_end * self.sample_rate)), self._end_sample)
            if b <= a:
                return np.zeros(0, dtype=np.float32)
            idx = np.arange(a, b) % self._capacity
            return self._buffer[idx].copy()
