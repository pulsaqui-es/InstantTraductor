"""Escuchar la app elegida con el dispositivo real (T011). Marcador `device`: solo los lanza el orquestador.

OJO: suenan en los auriculares, bajos (-30 dBFS): uno o dos tonos continuos de `ffplay` (777 y 1500 Hz) de
unos segundos cada vez, y un tono de 0,3 s por cada autotest. Hace falta `ffplay` en el PATH. Qué se
comprueba, con la captura por proceso real y emisores propios (nunca el audio de terceros):

- La lista (`list_audio_apps`) muestra al emisor como «suena» y oculta la propia app y sus antepasados.
- `AppLoopbackSource` oye el tono de su emisor y no el de un segundo emisor (otra instancia de `ffplay`).
- Al matar y relanzar el emisor, la fuente pasa a «esperando» y reanuda en ≤ 5 s (SC-004).
- El autotest invertido de la ADR-0012 (R5): `make_source(False)` = INCLUDE del emisor y
  `make_source(True)` = INCLUDE propia da `ok`.
- `AudioSourceContract` con la fuente real (en vivo: `finite=False`).

El detector de tonos es el del autotest (compara con el fondo): aguanta que suene otra cosa mientras tanto.
Las dos instancias de `ffplay` comparten ejecutable: la fuente escucha la raíz **más antigua**, la primera
que se lanza.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator

import numpy as np
import pytest

from instanttraductor.audio.app_source import AppCaptureState, AppLoopbackSource
from instanttraductor.audio.apps import SystemProcessTable, list_audio_apps, resolve_root
from instanttraductor.audio.selftest import PRESENT_DB, run_echo_selftest, tone_ratio_db
from instanttraductor.audio.wasapi_capture import ProcessLoopbackSource
from instanttraductor.audio.wasapi_playback import DeviceSink
from instanttraductor.contracts import CAPTURE_RATE, AudioSource
from instanttraductor.pipeline.clock import SessionClock
from tests.contract.test_audio_contract import AudioSourceContract

pytestmark = pytest.mark.device

CREATE_NO_WINDOW = 0x08000000
TARGET_HZ = 777.0
OTHER_HZ = 1500.0
APPEAR_TIMEOUT_S = 15.0
RESUME_LIMIT_S = 5.0  # SC-004
AUDIBLE_PEAK = 0.01  # el tono llega a la captura a -24 dBFS (0,06); el silencio digital, a 0


def require_ffplay() -> str:
    path = shutil.which("ffplay")
    if path is None:
        pytest.skip("Hace falta `ffplay` en el PATH para lanzar emisores propios.")
    return path


class Emitters:
    """Lanza instancias de `ffplay` con un tono a -30 dBFS y las mata al terminar."""

    def __init__(self) -> None:
        self._ffplay = require_ffplay()
        self._processes: list[subprocess.Popen[bytes]] = []

    def launch(self, freq_hz: float, *, seconds: int = 120) -> subprocess.Popen[bytes]:
        # `sine` de lavfi sale a -18 dBFS: con -12 dB de volumen queda a -30 dBFS.
        command = [
            self._ffplay,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "quiet",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq_hz}:sample_rate=48000:duration={seconds}",
            "-af",
            "volume=-12dB",
        ]
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW
        )
        self._processes.append(process)
        return process

    def kill(self, process: subprocess.Popen[bytes]) -> None:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        process.wait(timeout=10)

    def kill_all(self) -> None:
        for process in self._processes:
            if process.poll() is None:
                self.kill(process)


@pytest.fixture
def emitters() -> Iterator[Emitters]:
    emitters = Emitters()
    yield emitters
    emitters.kill_all()


def exe_of(process: subprocess.Popen[bytes]) -> str:
    """Ruta real del ejecutable en marcha (el `ffplay` del PATH puede ser un enlace)."""
    deadline = time.perf_counter() + APPEAR_TIMEOUT_S
    while time.perf_counter() < deadline:
        info = SystemProcessTable().info(process.pid)
        if info is not None and info.exe:
            return info.exe
        time.sleep(0.1)
    raise AssertionError("El emisor no arrancó.")


def wait_for_root(exe: str, pid: int) -> None:
    """Espera a que `pid` sea la raíz más antigua de esa app."""
    deadline = time.perf_counter() + APPEAR_TIMEOUT_S
    while True:
        root = resolve_root(exe)
        if root is not None and root.root_pid == pid:
            return
        assert time.perf_counter() < deadline, "el emisor no aparece como raíz"
        time.sleep(0.1)


def wait_for_audio(source: AppLoopbackSource | ProcessLoopbackSource, seconds: float) -> bool:
    """¿Llega audio audible a la fuente en los próximos `seconds` s?"""
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        chunk = source.read(0.2)
        if chunk is not None and float(np.max(np.abs(chunk.samples))) >= AUDIBLE_PEAK:
            return True
    return False


def capture_samples(source: AudioSource, seconds: float) -> np.ndarray:
    """Lee `seconds` s de audio de la fuente (por su duración, no por el reloj de pared)."""
    pieces: list[np.ndarray] = []
    total = 0.0
    deadline = time.perf_counter() + seconds + 5.0
    while total < seconds and time.perf_counter() < deadline:
        chunk = source.read(0.2)
        if chunk is not None:
            pieces.append(chunk.samples)
            total += chunk.duration
    assert total >= seconds, f"la fuente solo entregó {total:.1f} s de {seconds} s"
    return np.concatenate(pieces)


# --------------------------------------------------------------------------------------------------
# La lista
# --------------------------------------------------------------------------------------------------


def test_the_list_shows_the_emitter_as_sounding_and_hides_our_own_app(emitters: Emitters) -> None:
    emitter = emitters.launch(TARGET_HZ)
    exe = exe_of(emitter)
    time.sleep(1.5)  # la sesión de audio tarda un poco en aparecer
    apps = list_audio_apps()
    mine = [a for a in apps if a.identity.exe_path.lower() == exe.lower()]
    assert len(mine) == 1, [a.identity.display_name for a in apps]
    row = mine[0]
    assert row.sounding is True
    assert -45.0 <= row.level_dbfs <= -10.0  # un tono a -30 dBFS (llega unos 6 dB más alto)
    assert row.identity.root_pid == emitter.pid
    assert row.endpoints
    hidden = SystemProcessTable().hidden_pids()
    assert hidden  # nosotros y todos nuestros antepasados
    assert not [a for a in apps if a.identity.root_pid in hidden]
    assert all(a.sounding for a in apps[: apps.index(row)])  # las que suenan van primero


# --------------------------------------------------------------------------------------------------
# INCLUDE del emisor
# --------------------------------------------------------------------------------------------------


def test_include_of_the_emitter_hears_its_tone_and_not_the_one_of_a_second_emitter(
    emitters: Emitters,
) -> None:
    target = emitters.launch(TARGET_HZ)
    exe = exe_of(target)
    wait_for_root(exe, target.pid)
    emitters.launch(OTHER_HZ)  # misma imagen, más joven: la fuente debe quedarse con el primero
    time.sleep(1.5)
    clock = SessionClock()
    source = AppLoopbackSource(clock, exe)
    source.start()
    try:
        assert source.current_pid == target.pid
        assert wait_for_audio(source, 5.0), "no llegó audio del emisor"
        samples = capture_samples(source, 3.0)
    finally:
        source.stop()
    target_ratio = tone_ratio_db(samples, CAPTURE_RATE, TARGET_HZ)
    other_ratio = tone_ratio_db(samples, CAPTURE_RATE, OTHER_HZ)
    assert target_ratio >= PRESENT_DB, f"el tono del emisor no se oye ({target_ratio:.1f} dB)"
    assert other_ratio < PRESENT_DB, f"se cuela el tono del otro emisor ({other_ratio:.1f} dB)"


def test_waiting_for_an_app_that_is_not_open_gives_only_zeros() -> None:
    clock = SessionClock()
    states: list[AppCaptureState] = []
    source = AppLoopbackSource(
        clock, r"C:\No\Existe\nada_de_nada.exe", on_state=lambda state, name: states.append(state)
    )
    source.start()
    try:
        samples = capture_samples(source, 1.0)
        assert not samples.any()
        assert source.current_pid is None
        assert states == [AppCaptureState.WAITING]
    finally:
        source.stop()


def test_killing_and_relaunching_the_emitter_resumes_in_under_5_seconds(emitters: Emitters) -> None:
    first = emitters.launch(TARGET_HZ)
    exe = exe_of(first)
    clock = SessionClock()
    states: list[tuple[AppCaptureState, float]] = []
    source = AppLoopbackSource(clock, exe, on_state=lambda state, name: states.append((state, clock.now())))
    source.start()
    try:
        assert wait_for_audio(source, 8.0), "no llegó audio del primer emisor"
        killed_at = clock.now()
        emitters.kill(first)
        waiting_at = None
        deadline = time.perf_counter() + RESUME_LIMIT_S
        while time.perf_counter() < deadline:
            source.read(0.1)
            if source.state is AppCaptureState.WAITING:
                waiting_at = clock.now()
                break
        assert waiting_at is not None, "no pasó a esperando tras matar al emisor"
        assert waiting_at - killed_at <= RESUME_LIMIT_S
        assert source.current_pid is None

        relaunched_at = clock.now()
        second = emitters.launch(TARGET_HZ)
        resumed_at = None
        deadline = time.perf_counter() + 2 * RESUME_LIMIT_S
        while time.perf_counter() < deadline:
            chunk = source.read(0.1)
            if chunk is not None and float(np.max(np.abs(chunk.samples))) >= AUDIBLE_PEAK:
                arrival = source.arrival_time(chunk.t_end)
                resumed_at = clock.now() if arrival is None else arrival
                break
        assert resumed_at is not None, "no volvió el audio tras relanzar el emisor"
        assert resumed_at - relaunched_at <= RESUME_LIMIT_S, f"reanudó en {resumed_at - relaunched_at:.1f} s"
        assert source.current_pid == second.pid
        assert [state for state, _ in states] == [
            AppCaptureState.WAITING,
            AppCaptureState.PLAYING,
            AppCaptureState.WAITING,
            AppCaptureState.PLAYING,
        ]
    finally:
        source.stop()


# --------------------------------------------------------------------------------------------------
# Autotest invertido (ADR-0012, R5)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("through_app_source", [False, True], ids=["process-loopback", "app-loopback-source"])
def test_the_inverted_selftest_passes_with_the_emitter(emitters: Emitters, through_app_source: bool) -> None:
    """`make_source(False)` = captura de la app (INCLUDE del emisor); `make_source(True)` = INCLUDE propia."""
    emitter = emitters.launch(OTHER_HZ)  # un emisor ajeno que suena mientras el autotest toca su tono
    exe = exe_of(emitter)
    time.sleep(1.5)
    clock = SessionClock()

    def make_source(control: bool) -> AudioSource:
        if control:
            return ProcessLoopbackSource(clock, include=True, target_pid=os.getpid())
        if through_app_source:
            return AppLoopbackSource(clock, exe)
        return ProcessLoopbackSource(clock, include=True, target_pid=emitter.pid)

    sink = DeviceSink(clock)
    sink.start(lambda event: None)
    try:
        result = run_echo_selftest(sink, make_source)
    finally:
        sink.stop()
    assert result.ok, result.reason
    assert result.include_ratio_db is not None and result.include_ratio_db >= PRESENT_DB
    assert result.exclude_ratio_db is not None and result.exclude_ratio_db < PRESENT_DB


# --------------------------------------------------------------------------------------------------
# Contrato con la fuente real
# --------------------------------------------------------------------------------------------------


class TestAppLoopbackSourceOnTheDevice(AudioSourceContract):
    """`AppLoopbackSource` cumple el contrato de `AudioSource` con un emisor real."""

    finite = False

    @pytest.fixture
    def make_impl(self, emitters: Emitters) -> Callable[[], AudioSource]:
        emitter = emitters.launch(TARGET_HZ)
        exe = exe_of(emitter)
        time.sleep(1.0)
        return lambda: AppLoopbackSource(SessionClock(), exe)
