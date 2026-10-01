"""Autotest y monitor de eco con el dispositivo real (T024). Marcador `device`: solo los lanza el orquestador.

OJO: suenan en los auriculares, bajos (-30 dBFS): un tono de 0,3 s por cada autotest y unos 12 s de ruido
con ritmo de habla en los tests del monitor de eco. Qué se comprueba, con la captura por proceso real:

- El autotest de un equipo sano da `ok` y un umbral de correlación dentro de los límites.
- Si la exclusión falla, el autotest lo dice y el monitor de eco lo oye. El fallo se provoca como el T1c: la
  captura «EXCLUDE» apunta a otro proceso vivo en vez de al propio, así que deja pasar nuestro sonido.
- Con la exclusión bien puesta, el monitor de eco no cuenta ningún eco.

El detector de tonos es el del spike S4 (compara con el fondo): aguanta que suene otra cosa mientras tanto. El
monitor de eco compara envolventes: otro audio independiente en el PC no cuenta como eco.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterator

import numpy as np
import pytest

from instanttraductor.audio.echo_monitor import MAX_THRESHOLD, MIN_THRESHOLD, EchoMonitor
from instanttraductor.audio.selftest import PRESENT_DB, run_echo_selftest
from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource
from instanttraductor.audio.wasapi_playback import DeviceSink
from instanttraductor.contracts import PLAYBACK_RATE, AudioSource, SpeechPiece
from instanttraductor.pipeline.clock import SessionClock
from tests.unit.audio.test_echo_monitor import speech_like

pytestmark = pytest.mark.device

VOICE_S = 12.0
VOICE_RMS = 0.03  # -30 dBFS, como el tono del autotest


@pytest.fixture
def other_process() -> Iterator[subprocess.Popen[bytes]]:
    """Un proceso vivo que no suena: el «PID equivocado» de una captura que no nos excluye."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    yield process
    process.kill()
    process.wait()


QUIET_DBFS = -50.0  # más alto que esto, el PC no está en silencio


@pytest.fixture
def quiet_pc() -> None:
    """Salta el test si suena otra cosa en el PC.

    El monitor de eco solo detecta ecos más fuertes que el audio original (docstring de `echo_monitor`):
    con la voz a -30 dBFS y, por ejemplo, música a -22 dBFS, no oír el eco es lo esperado.
    """
    clock = SessionClock()
    source = ProcessLoopbackSource(clock)
    source.start()
    pieces = []
    try:
        while sum(len(p) for p in pieces) < 16000:
            chunk = source.read(0.5)
            if chunk is not None:
                pieces.append(chunk.samples)
    finally:
        source.stop()
    level = 20 * np.log10(float(np.sqrt(np.mean(np.concatenate(pieces) ** 2))) + 1e-12)
    if level > QUIET_DBFS:
        pytest.skip(f"Suena audio en el PC ({level:.0f} dBFS): este test necesita el PC en silencio.")


def source_factory(clock: SessionClock, exclude_pid: int | None = None) -> Callable[[bool], AudioSource]:
    """`make_source` del autotest: la INCLUDE de control siempre sobre el propio proceso; la EXCLUDE, sobre el
    propio proceso (lo normal) o sobre `exclude_pid` (para provocar el fallo de la exclusión)."""

    def make(include: bool) -> AudioSource:
        pid = os.getpid() if include or exclude_pid is None else exclude_pid
        return ProcessLoopbackSource(clock, include=include, target_pid=pid)

    return make


# --------------------------------------------------------------------------------------------------
# Autotest
# --------------------------------------------------------------------------------------------------


def test_the_selftest_passes_on_a_healthy_setup() -> None:
    clock = SessionClock()
    sink = DeviceSink(clock)
    sink.start(lambda event: None)
    try:
        result = run_echo_selftest(sink, source_factory(clock))
    finally:
        sink.stop()
    assert result.ok, result.reason
    assert result.reason == ""
    assert MIN_THRESHOLD <= result.correlation_threshold <= MAX_THRESHOLD
    assert result.include_ratio_db is not None and result.include_ratio_db >= PRESENT_DB
    assert result.exclude_ratio_db is not None and result.exclude_ratio_db < PRESENT_DB


def test_the_selftest_can_be_repeated_on_the_same_sink() -> None:
    """Tras cada reapertura de la captura se vuelve a pasar: el sink tiene que seguir sirviendo."""
    clock = SessionClock()
    sink = DeviceSink(clock)
    sink.start(lambda event: None)
    try:
        results = [run_echo_selftest(sink, source_factory(clock)) for _ in range(2)]
    finally:
        sink.stop()
    assert all(result.ok for result in results), [result.reason for result in results]


def test_the_selftest_detects_an_exclude_capture_that_does_not_exclude_us(
    other_process: subprocess.Popen[bytes],
) -> None:
    clock = SessionClock()
    sink = DeviceSink(clock)
    sink.start(lambda event: None)
    try:
        result = run_echo_selftest(sink, source_factory(clock, exclude_pid=other_process.pid))
    finally:
        sink.stop()
    assert not result.ok
    assert "reaparece" in result.reason, result.reason
    assert result.exclude_ratio_db is not None and result.exclude_ratio_db >= PRESENT_DB
    assert (
        result.include_ratio_db is not None and result.include_ratio_db >= PRESENT_DB
    )  # el control positivo oyó


# --------------------------------------------------------------------------------------------------
# Monitor de eco, de extremo a extremo
# --------------------------------------------------------------------------------------------------


def play_and_monitor(clock: SessionClock, source: ProcessLoopbackSource, monitor: EchoMonitor) -> None:
    """Hace sonar `VOICE_S` de voz sintética y alimenta al monitor con lo que capta `source`."""
    voice = speech_like(VOICE_S, PLAYBACK_RATE, seed=77, rms=VOICE_RMS)
    sink = DeviceSink(clock, on_rendered=monitor.feed_played)
    sink.start(lambda event: None)
    try:
        source.start()
        sink.enqueue(SpeechPiece(unit_id=1, samples=voice, is_last=True))
        deadline = clock.now() + VOICE_S + 2.0  # la voz, más la latencia de la captura
        while clock.now() < deadline:
            chunk = source.read(0.2)
            if chunk is None:
                continue
            arrival = source.arrival_time(chunk.t_end)
            monitor.feed_captured(chunk, clock.now() if arrival is None else arrival)
    finally:
        source.stop()
        sink.stop()


def test_the_echo_monitor_hears_our_own_voice_when_the_exclusion_fails(
    quiet_pc: None, other_process: subprocess.Popen[bytes]
) -> None:
    clock = SessionClock()
    warnings: list[str] = []
    monitor = EchoMonitor(on_echo=warnings.append)
    # EXCLUDE de otro proceso: el sonido del nuestro vuelve a la captura (el fallo silencioso T1c).
    play_and_monitor(clock, ProcessLoopbackSource(clock, target_pid=other_process.pid), monitor)
    assert monitor.evaluations > 10
    assert monitor.echo_events >= 1, f"no se detectó el eco; última correlación: {monitor.last_correlation}"
    assert warnings and "Eco" in warnings[0]
    assert monitor.last_delay_s is not None and 0.0 <= monitor.last_delay_s <= 0.6


def test_the_echo_monitor_counts_nothing_when_the_exclusion_works() -> None:
    clock = SessionClock()
    monitor = EchoMonitor()
    play_and_monitor(clock, ProcessLoopbackSource(clock), monitor)  # EXCLUDE del propio proceso
    assert monitor.evaluations > 10
    assert monitor.echo_events == 0, f"falso eco; última correlación: {monitor.last_correlation}"
