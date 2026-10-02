"""Anillo del audio captado (spec 002, T023)."""

from __future__ import annotations

import numpy as np
import pytest

from instanttraductor.audio.audio_ring import AudioRing
from instanttraductor.contracts import AudioChunk

RATE = 100  # 100 Hz: índices fáciles de leer


def chunk(t_start: float, values: list[float]) -> AudioChunk:
    return AudioChunk(np.asarray(values, np.float32), RATE, t_start)


def test_returns_the_requested_slice_by_audio_time() -> None:
    ring = AudioRing(RATE, capacity_s=10.0)
    ring.append(chunk(0.0, list(range(100))))  # 0..99 entre 0 y 1 s
    np.testing.assert_array_equal(ring.slice(0.2, 0.25), np.arange(20, 25, dtype=np.float32))


def test_old_audio_falls_out_of_the_ring() -> None:
    ring = AudioRing(RATE, capacity_s=1.0)
    for i in range(3):
        ring.append(chunk(float(i), [float(i)] * 100))
    assert ring.slice(0.0, 1.0).size == 0  # ya salió
    np.testing.assert_array_equal(ring.slice(2.0, 2.1), np.full(10, 2.0, np.float32))


def test_a_slice_that_straddles_the_wrap_is_contiguous() -> None:
    ring = AudioRing(RATE, capacity_s=1.0)
    ring.append(chunk(0.0, [1.0] * 70))
    ring.append(chunk(0.7, [2.0] * 70))  # da la vuelta al búfer
    out = ring.slice(0.6, 1.0)
    np.testing.assert_array_equal(out, np.array([1.0] * 10 + [2.0] * 30, np.float32))


def test_a_gap_is_filled_with_silence() -> None:
    ring = AudioRing(RATE, capacity_s=10.0)
    ring.append(chunk(0.0, [1.0] * 10))
    ring.append(chunk(0.5, [3.0] * 10))
    np.testing.assert_array_equal(ring.slice(0.1, 0.5), np.zeros(40, np.float32))


def test_audio_that_has_not_arrived_is_missing() -> None:
    ring = AudioRing(RATE, capacity_s=10.0)
    ring.append(chunk(0.0, [1.0] * 50))
    assert ring.slice(0.4, 2.0).size == 10
    assert AudioRing(RATE).slice(0.0, 1.0).size == 0


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        AudioRing(RATE, capacity_s=0.0)
