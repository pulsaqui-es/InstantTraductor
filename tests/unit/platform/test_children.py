"""Tests de ``platform/children.py``: arranque, «listo», salud, un reinicio y parada en paralelo.

Usan hijos falsos: un script de Python efímero (en ``tmp_path``) que, según el modo, imprime la
línea ``ready``, no la imprime, muere, sirve ``/health`` por HTTP o ignora la parada ordenada.
Son procesos reales del sistema (sin hardware de audio ni GPU).
"""

from __future__ import annotations

import json
import queue
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import psutil
import pytest

from instanttraductor.platform import windows
from instanttraductor.platform.children import (
    OUTPUT_TAIL_LINES,
    ChildExitedError,
    ChildTimeoutError,
    HealthCheck,
    ManagedChild,
    ReadyHttpHealth,
    ReadyJsonLine,
    http_get_ok,
    stop_all,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Solo para Windows")

#: Margen para esperas que NO miden ningún requisito de tiempo (el arranque de Python varía).
GENEROUS_S = 20.0
#: Código de salida con el que el hijo ``stoppable`` indica que paró por sí mismo (parada ordenada).
GRACEFUL_EXIT_CODE = 42

FAKE_CHILD_SOURCE = r'''
"""Hijo falso: el primer argumento elige el comportamiento."""
import http.server
import json
import os
import subprocess
import sys
import time

mode, args = sys.argv[1], sys.argv[2:]


def ready(**extra):
    print(json.dumps({"event": "ready", **extra}), flush=True)


if mode == "ready":  # listo y vivo
    ready(port=4242)
    time.sleep(60)
elif mode == "echo_env":  # dice qué variable de entorno y qué directorio de trabajo recibió
    ready(value=os.environ.get("IT_FAKE_VAR"), path=os.environ.get("PATH"), cwd=os.getcwd())
    time.sleep(60)
elif mode == "noisy":  # ruido antes de la línea ready
    print("cargando modelo...", flush=True)
    print("{esto no es json", flush=True)
    print(json.dumps({"event": "loading", "progress": 0.5}), flush=True)
    print(json.dumps(["no", "es", "un", "objeto"]), flush=True)
    ready(port=4242)
    time.sleep(60)
elif mode == "no_ready":  # nunca dice que está listo
    print("cargando...", flush=True)
    time.sleep(60)
elif mode == "exit_early":  # muere durante el arranque
    print("fallo al cargar el modelo", file=sys.stderr, flush=True)
    sys.exit(3)
elif mode == "die_after":  # listo, y muere a los N segundos
    ready()
    time.sleep(float(args[0]))
    sys.exit(7)
elif mode == "flood":  # llena stdout y stderr: se bloquearía si nadie vacía las tuberías
    chunk = "x" * 1000
    for _ in range(3000):
        print(chunk, flush=True)
        print(chunk, file=sys.stderr, flush=True)
    ready()
    time.sleep(60)
elif mode == "lines":  # 300 líneas numeradas y después ready
    for n in range(1, 301):
        print(f"linea {n}", flush=True)
    ready()
    time.sleep(60)
elif mode == "http":  # GET -> 503 durante N segundos y después 200
    port, delay = int(args[0]), float(args[1])
    started = time.monotonic()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            status = 200 if time.monotonic() - started >= delay else 503
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
elif mode == "stoppable":  # listo; para por sí mismo cuando aparece el fichero indicado
    ready()
    while not os.path.exists(args[0]):
        time.sleep(0.02)
    sys.exit(42)
elif mode == "spawner":  # listo, con un proceso nieto (como `uv run` y su Python)
    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    ready(grandchild=grandchild.pid)
    time.sleep(60)
elif mode == "ready_once":  # solo el primer arranque funciona (marca en un fichero)
    if os.path.exists(args[0]):
        print("segundo arranque: falla", file=sys.stderr, flush=True)
        sys.exit(5)
    open(args[0], "w").close()
    ready()
    time.sleep(60)
'''


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _touch_on_stop(path: Path) -> Callable[[ManagedChild], None]:
    """Parada ordenada del hijo ``stoppable``: crea el fichero que espera."""

    def graceful_stop(child: ManagedChild) -> None:
        path.touch()

    return graceful_stop


def _ignore_stop(child: ManagedChild) -> None:
    """Parada ordenada que no hace nada: el hijo la ignora."""


def _wait_until_gone(pid: int, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not psutil.pid_exists(pid)


def _wait_for_output(child: ManagedChild, text: str, timeout_s: float = GENEROUS_S) -> None:
    deadline = time.monotonic() + timeout_s
    while text not in child.output_tail() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert text in child.output_tail(), f"el hijo no escribió {text!r}"


@pytest.fixture
def make_child(tmp_path: Path) -> Iterator[Callable[..., ManagedChild]]:
    """Fábrica de ``ManagedChild`` sobre el hijo falso. Al terminar el test para a todos."""
    script = tmp_path / "fake_child.py"
    script.write_text(FAKE_CHILD_SOURCE, encoding="utf-8")
    created: list[ManagedChild] = []

    def factory(
        mode: str,
        *mode_args: object,
        ready: ReadyJsonLine | ReadyHttpHealth | None = None,
        name: str = "falso",
        **kwargs,
    ) -> ManagedChild:
        child = ManagedChild(
            [sys.executable, str(script), mode, *map(str, mode_args)],
            ready=ready or ReadyJsonLine(timeout_s=GENEROUS_S),
            name=name,
            **kwargs,
        )
        created.append(child)
        return child

    yield factory
    for child in created:
        child.stop(grace_s=0.0)


def _started(child: ManagedChild) -> ManagedChild:
    child.start()
    child.wait_ready()
    return child


# ---------------------------------------------------------------------------
# «Listo»: línea JSON en stdout
# ---------------------------------------------------------------------------
def test_json_line_ready_returns_the_line_that_matches_the_predicate(make_child) -> None:
    child = make_child("noisy")  # ruido, JSON mal formado y otras líneas JSON antes de «ready»

    child.start()
    info = child.wait_ready()

    assert info["event"] == "ready"
    assert info["port"] == 4242
    assert child.ready_info == info
    assert child.is_alive()
    assert child.pid is not None and psutil.pid_exists(child.pid)
    assert child.wait_ready() == info  # idempotente


def test_json_line_ready_uses_the_given_predicate(make_child) -> None:
    ready = ReadyJsonLine(predicate=lambda message: message.get("event") == "loading", timeout_s=GENEROUS_S)
    child = make_child("noisy", ready=ready)

    child.start()

    assert child.wait_ready() == {"event": "loading", "progress": 0.5}


def test_json_line_ready_times_out_and_leaves_no_process_behind(make_child) -> None:
    child = make_child("no_ready", ready=ReadyJsonLine(timeout_s=0.5), name="sin-ready")
    child.start()
    pid = child.pid
    _wait_for_output(child, "cargando...")  # el tiempo máximo cuenta desde start(): ya habrá vencido

    with pytest.raises(ChildTimeoutError) as error:
        child.wait_ready()

    assert isinstance(error.value, TimeoutError)
    assert "sin-ready" in str(error.value)
    assert "cargando..." in str(error.value)  # incluye lo último que dijo el hijo
    assert not child.is_alive()
    assert pid is not None and _wait_until_gone(pid)


def test_wait_ready_fails_fast_when_the_child_exits_during_startup(make_child) -> None:
    child = make_child("exit_early", ready=ReadyJsonLine(timeout_s=60.0), name="muere")
    child.start()

    started = time.monotonic()
    with pytest.raises(ChildExitedError) as error:
        child.wait_ready()

    assert time.monotonic() - started < 30.0  # no espera a agotar el tiempo máximo
    assert "3" in str(error.value)  # código de salida
    assert "fallo al cargar el modelo" in str(error.value)  # y lo que escribió por stderr


def test_stdout_and_stderr_are_drained_so_a_noisy_child_never_blocks(make_child) -> None:
    child = make_child("flood")  # ~6 MB entre stdout y stderr antes de decir «ready»

    child.start()

    assert child.wait_ready()["event"] == "ready"


def test_output_tail_keeps_only_the_last_lines(make_child) -> None:
    child = make_child("lines")
    child.start()
    child.wait_ready()

    tail = child.output_tail(3).splitlines()

    assert tail[:2] == ["linea 299", "linea 300"]
    assert json.loads(tail[2])["event"] == "ready"
    assert len(child.output_tail(10_000).splitlines()) <= OUTPUT_TAIL_LINES


def test_a_ready_line_written_right_before_exiting_still_counts(make_child) -> None:
    child = make_child("die_after", 0)  # escribe «ready» y sale enseguida

    child.start()

    assert child.wait_ready()["event"] == "ready"


def test_env_is_added_to_the_current_environment_and_cwd_is_applied(make_child, tmp_path: Path) -> None:
    workdir = tmp_path / "trabajo"
    workdir.mkdir()
    child = make_child("echo_env", env={"IT_FAKE_VAR": "hola"}, cwd=workdir)

    child.start()
    info = child.wait_ready()

    assert info["value"] == "hola"
    assert info["path"]  # el resto del entorno (PATH) se conserva
    assert Path(info["cwd"]).samefile(workdir)


def test_starting_a_running_child_twice_is_an_error(make_child) -> None:
    child = make_child("ready")
    child.start()

    with pytest.raises(RuntimeError):
        child.start()


def test_wait_ready_before_start_is_an_error(make_child) -> None:
    with pytest.raises(RuntimeError):
        make_child("ready").wait_ready()


# ---------------------------------------------------------------------------
# «Listo»: GET /health devuelve 200
# ---------------------------------------------------------------------------
def test_http_ready_waits_for_health_to_answer_200(make_child) -> None:
    port = _free_port()
    ready = ReadyHttpHealth(f"http://127.0.0.1:{port}/health", timeout_s=GENEROUS_S)
    child = make_child("http", port, 0.6, ready=ready)  # 503 durante 0.6 s

    started = time.monotonic()
    child.start()
    child.wait_ready()

    assert time.monotonic() - started >= 0.5
    assert http_get_ok(f"http://127.0.0.1:{port}/health")


def test_http_ready_times_out_if_health_never_answers_200(make_child) -> None:
    port = _free_port()
    ready = ReadyHttpHealth(f"http://127.0.0.1:{port}/health", timeout_s=1.5)
    child = make_child("http", port, 600, ready=ready)  # siempre 503
    child.start()

    with pytest.raises(ChildTimeoutError):
        child.wait_ready()

    assert not child.is_alive()


def test_http_ready_fails_fast_when_the_child_exits(make_child) -> None:
    ready = ReadyHttpHealth(f"http://127.0.0.1:{_free_port()}/health", timeout_s=60.0)
    child = make_child("exit_early", ready=ready)
    child.start()

    started = time.monotonic()
    with pytest.raises(ChildExitedError):
        child.wait_ready()

    assert time.monotonic() - started < 30.0


def test_http_get_ok_is_false_without_a_server_and_does_not_wait_for_windows_retries() -> None:
    # En Windows una conexión rechazada tarda 1-2 s en fallar si no hay un tiempo de conexión corto.
    started = time.monotonic()

    assert not http_get_ok(f"http://127.0.0.1:{_free_port()}/health")

    assert time.monotonic() - started < 1.0


# ---------------------------------------------------------------------------
# Salud periódica
# ---------------------------------------------------------------------------
def test_health_is_checked_every_2_seconds_by_default() -> None:
    assert HealthCheck().interval_s == 2.0


def test_health_failure_is_reported_once_when_the_child_dies(make_child) -> None:
    failures: queue.Queue = queue.Queue()
    health = HealthCheck(interval_s=0.1, on_failure=lambda child, reason: failures.put((child, reason)))
    child = make_child("die_after", 0.3, health=health)
    child.start()
    child.wait_ready()

    failed_child, reason = failures.get(timeout=GENEROUS_S)

    assert failed_child is child
    assert "7" in reason  # código de salida del hijo
    time.sleep(0.5)
    assert failures.empty()  # una sola notificación por fallo


def test_health_probe_returning_false_is_reported_while_the_process_is_alive(make_child) -> None:
    failures: queue.Queue = queue.Queue()
    calls: list[int] = []

    def probe(child: ManagedChild) -> bool:
        calls.append(1)
        return len(calls) <= 2  # las dos primeras comprobaciones van bien

    health = HealthCheck(interval_s=0.05, probe=probe, on_failure=lambda child, reason: failures.put(reason))
    child = make_child("ready", health=health)
    child.start()
    child.wait_ready()

    reason = failures.get(timeout=GENEROUS_S)

    assert "salud" in reason
    assert len(calls) == 3
    assert child.is_alive()  # avisar no mata: decide quien recibe el aviso


def test_health_probe_that_raises_counts_as_a_failure(make_child) -> None:
    failures: queue.Queue = queue.Queue()

    def probe(child: ManagedChild) -> bool:
        raise RuntimeError("boom")

    health = HealthCheck(interval_s=0.05, probe=probe, on_failure=lambda child, reason: failures.put(reason))
    child = make_child("ready", health=health)
    child.start()
    child.wait_ready()

    assert "boom" in failures.get(timeout=GENEROUS_S)


def test_no_failure_is_reported_while_the_child_is_healthy(make_child) -> None:
    failures: queue.Queue = queue.Queue()
    health = HealthCheck(interval_s=0.05, probe=lambda child: True, on_failure=lambda c, r: failures.put(r))
    child = make_child("ready", health=health)
    child.start()
    child.wait_ready()

    time.sleep(0.5)

    assert failures.empty()


def test_http_child_dying_is_detected_with_an_http_probe(make_child) -> None:
    port = _free_port()
    url = f"http://127.0.0.1:{port}/health"
    failures: queue.Queue = queue.Queue()
    health = HealthCheck(
        interval_s=0.1, probe=lambda child: http_get_ok(url), on_failure=lambda c, r: failures.put(r)
    )
    child = make_child("http", port, 0, ready=ReadyHttpHealth(url, timeout_s=GENEROUS_S), health=health)
    child.start()
    child.wait_ready()
    assert child.pid is not None

    psutil.Process(child.pid).kill()  # el servidor muere de golpe

    assert failures.get(timeout=GENEROUS_S)


def test_no_failure_is_reported_after_an_intentional_stop(make_child, tmp_path: Path) -> None:
    failures: queue.Queue = queue.Queue()
    stop_file = tmp_path / "stop"
    health = HealthCheck(interval_s=0.05, on_failure=lambda c, r: failures.put(r))
    child = make_child("stoppable", stop_file, health=health, graceful_stop=_touch_on_stop(stop_file))
    child.start()
    child.wait_ready()

    child.stop()
    time.sleep(0.4)

    assert not child.is_alive()
    assert failures.empty()


# ---------------------------------------------------------------------------
# Reinicio (una sola vez)
# ---------------------------------------------------------------------------
def test_restart_once_restarts_the_child_only_one_time(make_child) -> None:
    results: queue.Queue = queue.Queue()

    def on_failure(child: ManagedChild, reason: str) -> None:
        results.put((child.restart_once(), child.pid))

    child = make_child("die_after", 0.3, health=HealthCheck(interval_s=0.1, on_failure=on_failure))
    child.start()
    child.wait_ready()
    first_pid = child.pid

    restarted, second_pid = results.get(timeout=GENEROUS_S)  # el primer fallo se recupera
    assert restarted is True
    assert second_pid is not None and second_pid != first_pid
    assert child.restart_count == 1

    restarted_again, _ = results.get(timeout=GENEROUS_S)  # el nuevo proceso también muere
    assert restarted_again is False  # solo un reinicio por sesión
    assert child.restart_count == 1


def test_restart_once_kills_the_whole_old_process_tree(make_child) -> None:
    child = make_child("spawner")
    child.start()
    old_info = child.wait_ready()
    old_pid, old_grandchild = child.pid, old_info["grandchild"]
    assert old_pid is not None

    assert child.restart_once() is True

    assert child.pid != old_pid
    assert child.ready_info["grandchild"] != old_grandchild
    assert _wait_until_gone(old_pid)
    assert _wait_until_gone(old_grandchild), "el nieto del proceso viejo sigue vivo"


def test_restart_once_returns_false_when_the_new_process_does_not_get_ready(
    make_child, tmp_path: Path
) -> None:
    child = make_child("ready_once", tmp_path / "marker", ready=ReadyJsonLine(timeout_s=GENEROUS_S))
    child.start()
    child.wait_ready()

    assert child.restart_once() is False  # el segundo arranque falla antes de decir «ready»
    assert not child.is_alive()
    assert child.restart_count == 1

    assert child.restart_once() is False  # el único reinicio ya se gastó
    assert child.restart_count == 1


# ---------------------------------------------------------------------------
# Parada de un hijo
# ---------------------------------------------------------------------------
def test_stop_uses_the_graceful_stop_before_killing(make_child, tmp_path: Path) -> None:
    stop_file = tmp_path / "stop"
    child = make_child("stoppable", stop_file, graceful_stop=_touch_on_stop(stop_file))
    child.start()
    child.wait_ready()

    child.stop(grace_s=GENEROUS_S)

    assert child.returncode == GRACEFUL_EXIT_CODE  # paró por sí mismo, sin que lo mataran


def test_stop_kills_the_child_when_it_ignores_the_graceful_stop(make_child) -> None:
    child = make_child("ready", graceful_stop=_ignore_stop)
    child.start()
    child.wait_ready()

    started = time.monotonic()
    child.stop(grace_s=0.3)

    assert time.monotonic() - started < 2.0
    assert not child.is_alive()


def test_stop_kills_the_descendants_too(make_child) -> None:
    child = make_child("spawner")
    child.start()
    grandchild = child.wait_ready()["grandchild"]
    assert psutil.pid_exists(grandchild)

    child.stop(grace_s=0.2)

    assert _wait_until_gone(grandchild), "el nieto sigue vivo"


def test_stop_is_idempotent_and_safe_before_start(make_child) -> None:
    child = make_child("ready")

    child.stop()  # sin arrancar
    child.start()
    child.wait_ready()
    child.stop()
    child.stop()  # ya parado

    assert not child.is_alive()
    assert child.pid is not None  # el último PID se conserva para diagnóstico


# ---------------------------------------------------------------------------
# stop_all: todos en paralelo y después el job, en <= 2 s
# ---------------------------------------------------------------------------
def test_stop_all_sends_the_graceful_stop_to_every_child_in_parallel(make_child, tmp_path: Path) -> None:
    barrier = threading.Barrier(3, timeout=5.0)
    children = []
    for number in range(3):
        stop_file = tmp_path / f"stop{number}"

        def graceful_stop(child: ManagedChild, stop_file: Path = stop_file) -> None:
            barrier.wait()  # solo pasan si los tres callbacks se ejecutan a la vez
            stop_file.touch()

        children.append(make_child("stoppable", stop_file, graceful_stop=graceful_stop, name=f"hijo{number}"))
    for child in children:
        _started(child)

    stop_all(children, grace_s=1.0)

    assert [child.returncode for child in children] == [GRACEFUL_EXIT_CODE] * 3


def test_stop_all_meets_the_two_second_budget_with_children_that_ignore_the_graceful_stop(
    make_child, tmp_path: Path
) -> None:
    stop_file = tmp_path / "stop"
    stubborn = [make_child("ready", graceful_stop=_ignore_stop, name=f"terco{n}") for n in range(2)]
    polite = make_child("stoppable", stop_file, graceful_stop=_touch_on_stop(stop_file), name="educado")
    children = [*stubborn, polite]
    for child in children:
        _started(child)

    started = time.monotonic()
    stop_all(children, grace_s=1.0)
    elapsed = time.monotonic() - started

    assert 0.9 <= elapsed <= 2.0  # primero 1 s de gracia y después el job, que mata de inmediato
    assert not any(child.is_alive() for child in children)
    assert polite.returncode == GRACEFUL_EXIT_CODE
    assert all(child.returncode != GRACEFUL_EXIT_CODE for child in stubborn)


def test_stop_all_does_not_wait_for_a_graceful_stop_that_hangs(make_child) -> None:
    release = threading.Event()

    def hanging_stop(child: ManagedChild) -> None:
        release.wait(30.0)  # p. ej. un POST /shutdown contra un servicio colgado

    child = make_child("ready", graceful_stop=hanging_stop)
    _started(child)

    try:
        started = time.monotonic()
        stop_all([child], grace_s=1.0)
        elapsed = time.monotonic() - started

        assert elapsed <= 2.0
        assert not child.is_alive()
    finally:
        release.set()


def test_stop_all_returns_as_soon_as_every_child_has_exited(make_child, tmp_path: Path) -> None:
    children = []
    for number in range(2):
        stop_file = tmp_path / f"stop{number}"
        children.append(
            make_child("stoppable", stop_file, graceful_stop=_touch_on_stop(stop_file), name=f"hijo{number}")
        )
    for child in children:
        _started(child)

    started = time.monotonic()
    stop_all(children, grace_s=10.0)

    assert time.monotonic() - started < 2.0  # no agota los 10 s de gracia
    assert [child.returncode for child in children] == [GRACEFUL_EXIT_CODE] * 2


def test_stop_all_does_not_wait_for_children_without_a_graceful_stop(make_child) -> None:
    children = [_started(make_child("ready", name=f"sin-parada{n}")) for n in range(2)]

    started = time.monotonic()
    stop_all(children, grace_s=1.0)

    assert time.monotonic() - started < 0.9  # nadie tiene parada ordenada: se cierra el job ya
    assert not any(child.is_alive() for child in children)


def test_stop_all_kills_descendants_through_the_job(make_child) -> None:
    child = _started(make_child("spawner"))
    grandchild = child.ready_info["grandchild"]
    assert psutil.pid_exists(grandchild)

    stop_all([child], grace_s=1.0)

    assert _wait_until_gone(grandchild), "el nieto sigue vivo: quedaría un proceso huérfano"


def test_stop_all_closes_the_job_and_kills_unmanaged_children_too() -> None:
    proc = windows.launch_child([sys.executable, "-c", "import time; time.sleep(60)"])

    stop_all([])

    proc.wait(timeout=2.0)


def test_stop_all_accepts_children_that_were_never_started(make_child) -> None:
    stop_all([make_child("ready")])


def test_stop_all_does_not_report_intentional_stops_as_failures(make_child, tmp_path: Path) -> None:
    failures: queue.Queue = queue.Queue()
    stop_file = tmp_path / "stop"
    health = HealthCheck(interval_s=0.05, on_failure=lambda c, r: failures.put(r))
    polite = _started(
        make_child("stoppable", stop_file, health=health, graceful_stop=_touch_on_stop(stop_file))
    )
    other = _started(make_child("ready", health=health))

    stop_all([polite, other], grace_s=1.0)
    time.sleep(0.4)

    assert failures.empty()
