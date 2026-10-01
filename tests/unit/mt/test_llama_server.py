"""Tests de ``mt/llama_server.py``: ``LlamaServerProcess`` sobre ``ManagedChild``.

Usan un ``llama-server`` falso: un script de Python efímero que sirve ``/health`` (503 durante un tiempo y
después 200) y ``/argv`` (los argumentos que recibió). Son procesos reales del sistema, sin GPU ni modelos:
el modelo es un fichero vacío. El comportamiento del falso se elige con ``extra_args`` (``--fake-...``).
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import psutil
import pytest

from instanttraductor.contracts import EngineError
from instanttraductor.mt.llama_server import (
    CONTEXT_SIZE,
    HOST,
    N_GPU_LAYERS,
    READY_TIMEOUT_S,
    LlamaServerProcess,
    find_free_port,
    llama_server_exe,
)
from instanttraductor.platform import windows
from instanttraductor.platform.children import ManagedChild, http_get_ok, stop_all
from instanttraductor.setup.manifest import component_dir

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Solo para Windows")

#: Margen para esperas que NO miden ningún requisito de tiempo (el arranque de Python varía).
GENEROUS_S = 20.0

FAKE_SERVER_SOURCE = r'''
"""llama-server falso: /health (503 durante un tiempo y luego 200) y /argv."""
import http.server
import json
import sys
import time

args = sys.argv[1:]


def option(name, default=None):
    return args[args.index(name) + 1] if name in args else default


port = int(option("--port"))
mode = option("--fake-mode", "ok")
ready_delay = float(option("--fake-ready-delay", "0"))
started = time.monotonic()

if mode == "exit_early":
    print("error: no se pudo cargar el modelo", file=sys.stderr, flush=True)
    sys.exit(3)


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status, body=b""):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200 if time.monotonic() - started >= ready_delay else 503)
        elif self.path == "/argv":
            self._send(200, json.dumps(args).encode())
        else:
            self._send(404)

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


@pytest.fixture(autouse=True)
def _close_shared_job() -> Iterator[None]:
    """Cierra el job único tras cada test: no queda ningún hijo vivo ni estado compartido."""
    yield
    windows.close_job()


@pytest.fixture
def make_server(tmp_path: Path) -> Iterator[Callable[..., LlamaServerProcess]]:
    """Fábrica de ``LlamaServerProcess`` sobre el servidor falso. Al terminar el test los para a todos."""
    script = tmp_path / "fake_llama_server.py"
    script.write_text(FAKE_SERVER_SOURCE, encoding="utf-8")
    model = tmp_path / "modelo.gguf"
    model.write_bytes(b"")
    created: list[LlamaServerProcess] = []

    def factory(*fake_args: str, **kwargs) -> LlamaServerProcess:
        kwargs.setdefault("ready_timeout_s", GENEROUS_S)
        server = LlamaServerProcess(
            model, executable=[sys.executable, script], extra_args=fake_args, **kwargs
        )
        created.append(server)
        return server

    yield factory
    for server in created:
        server.stop(grace_s=0.0)


def _started(server: LlamaServerProcess) -> LlamaServerProcess:
    server.start()
    server.wait_ready()
    return server


def _wait_until_gone(pid: int, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not psutil.pid_exists(pid)


# ---------------------------------------------------------------------------
# Línea de comandos y rutas (sin lanzar nada)
# ---------------------------------------------------------------------------
def _option(command: list[str], name: str) -> str:
    return command[command.index(name) + 1]


def test_command_line_has_the_flags_of_the_task(tmp_path: Path) -> None:
    model = tmp_path / "Hy-MT2-7B-Q4_K_M.gguf"
    server = LlamaServerProcess(model, port=8123)

    command = server.command()

    assert command[0] == str(llama_server_exe())
    assert _option(command, "-m") == str(model)
    assert _option(command, "--host") == "127.0.0.1" == HOST
    assert _option(command, "--port") == "8123"
    assert _option(command, "-ngl") == "99" == str(N_GPU_LAYERS)
    assert _option(command, "--cache-ram") == "0"
    assert _option(command, "-c") == "4096" == str(CONTEXT_SIZE)
    # Lo medido en S2: un solo hueco (así el contexto es de 4 096 por hueco), sin autoajuste y sin web.
    assert _option(command, "-np") == "1"
    assert _option(command, "-fit") == "off"
    assert "--no-webui" in command


def test_extra_args_go_at_the_end(tmp_path: Path) -> None:
    server = LlamaServerProcess(tmp_path / "m.gguf", port=8123, extra_args=("--threads", "4"))
    assert server.command()[-2:] == ["--threads", "4"]


def test_default_executable_is_llama_server_in_the_llama_cpp_component() -> None:
    assert llama_server_exe() == component_dir("llama-cpp") / "llama-server.exe"


def test_the_port_is_free_and_each_server_gets_its_own(tmp_path: Path) -> None:
    port = find_free_port()
    assert 1024 <= port <= 65535
    with socket.socket() as sock:  # sigue libre: se puede abrir
        sock.bind((HOST, port))

    first = LlamaServerProcess(tmp_path / "m.gguf")
    second = LlamaServerProcess(tmp_path / "m.gguf")
    assert first.base_url == f"http://127.0.0.1:{first.port}"
    assert second.base_url.startswith("http://127.0.0.1:")
    assert _option(first.command(), "--port") == str(first.port)


def test_ready_timeout_defaults_to_30_seconds() -> None:
    assert READY_TIMEOUT_S == 30.0


def test_an_empty_executable_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        LlamaServerProcess(tmp_path / "m.gguf", executable=[])


# ---------------------------------------------------------------------------
# Falta algo: no se lanza nada
# ---------------------------------------------------------------------------
def test_start_without_the_server_executable_is_a_non_recoverable_engine_error(tmp_path: Path) -> None:
    model = tmp_path / "modelo.gguf"
    model.write_bytes(b"")
    server = LlamaServerProcess(model)  # el ejecutable por defecto no existe en el home aislado

    with pytest.raises(EngineError) as error:
        server.start()

    assert error.value.recoverable is False
    assert error.value.engine == "llama-server"
    assert "preparar" in str(error.value)
    assert server.pid is None


def test_start_without_the_model_is_a_non_recoverable_engine_error(tmp_path: Path) -> None:
    server = LlamaServerProcess(tmp_path / "no-existe.gguf", executable=[sys.executable, "-c", "pass"])

    with pytest.raises(EngineError) as error:
        server.start()

    assert error.value.recoverable is False
    assert "modelo" in str(error.value)
    assert server.pid is None


def test_start_with_an_unlaunchable_executable_is_an_engine_error(tmp_path: Path) -> None:
    model = tmp_path / "modelo.gguf"
    model.write_bytes(b"")
    server = LlamaServerProcess(model, executable=[str(tmp_path / "no-existe.exe")])

    with pytest.raises(EngineError) as error:
        server.start()

    assert error.value.recoverable is False


# ---------------------------------------------------------------------------
# Arranque y «listo» por /health
# ---------------------------------------------------------------------------
def test_start_and_wait_ready_serves_health_on_localhost(make_server) -> None:
    server = make_server()

    server.start()
    server.wait_ready()

    assert server.is_alive()
    assert server.pid is not None and psutil.pid_exists(server.pid)
    assert http_get_ok(f"{server.base_url}/health")
    assert httpx.get(f"{server.base_url}/argv", trust_env=False).json() == server.command()[2:]


def test_the_server_receives_the_flags_and_listens_only_on_localhost(make_server) -> None:
    server = _started(make_server())

    received = httpx.get(f"{server.base_url}/argv", trust_env=False).json()

    assert received[received.index("--host") + 1] == "127.0.0.1"
    assert received[received.index("--port") + 1] == str(server.port)
    assert received[received.index("-ngl") + 1] == "99"
    assert received[received.index("--cache-ram") + 1] == "0"
    assert received[received.index("-c") + 1] == "4096"
    # El python.exe de un venv es un redirector: el intérprete que escucha puede ser un proceso hijo.
    tree = [psutil.Process(server.pid), *psutil.Process(server.pid).children(recursive=True)]
    listening = [c for proc in tree for c in proc.net_connections("tcp") if c.status == "LISTEN"]
    assert listening, "el servidor no escucha en ningún puerto"
    assert {(c.laddr.ip, c.laddr.port) for c in listening} == {("127.0.0.1", server.port)}


def test_ready_waits_for_health_to_stop_answering_503(make_server) -> None:
    server = make_server("--fake-ready-delay", "0.8")

    started = time.monotonic()
    server.start()
    server.wait_ready()

    assert time.monotonic() - started >= 0.7
    assert http_get_ok(f"{server.base_url}/health")


def test_not_ready_in_time_is_a_non_recoverable_engine_error_and_leaves_no_process(make_server) -> None:
    server = make_server("--fake-ready-delay", "600", ready_timeout_s=1.5)
    server.start()
    pid = server.pid

    with pytest.raises(EngineError) as error:
        server.wait_ready()

    assert error.value.recoverable is False
    assert error.value.engine == "llama-server"
    assert "1,5" in str(error.value) or "1.5" in str(error.value)
    assert not server.is_alive()
    assert pid is not None and _wait_until_gone(pid)


def test_dying_during_startup_fails_fast_with_what_the_process_wrote(make_server) -> None:
    server = make_server("--fake-mode", "exit_early", ready_timeout_s=60.0)
    server.start()

    started = time.monotonic()
    with pytest.raises(EngineError) as error:
        server.wait_ready()

    assert time.monotonic() - started < 30.0  # no espera a agotar el tiempo máximo
    assert error.value.recoverable is False
    assert "no se pudo cargar el modelo" in str(error.value)
    assert "no se pudo cargar el modelo" in server.output_tail()


# ---------------------------------------------------------------------------
# Salud, reinicio y parada
# ---------------------------------------------------------------------------
def test_a_failure_is_reported_once_with_the_server_and_the_reason(make_server) -> None:
    failures: list[tuple[LlamaServerProcess, str]] = []
    reported = threading.Event()

    def on_failure(server: LlamaServerProcess, reason: str) -> None:
        failures.append((server, reason))
        reported.set()

    server = make_server(health_interval_s=0.1, on_failure=on_failure)
    _started(server)

    psutil.Process(server.pid).kill()  # muere de golpe

    assert reported.wait(GENEROUS_S), "no se avisó del fallo"
    time.sleep(0.5)  # una sola notificación por fallo
    assert len(failures) == 1
    assert failures[0][0] is server
    assert "terminó" in failures[0][1]


def test_stopping_on_purpose_is_not_a_failure(make_server) -> None:
    failures: list[str] = []
    server = make_server(health_interval_s=0.1, on_failure=lambda s, reason: failures.append(reason))
    _started(server)

    server.stop()
    time.sleep(0.6)

    assert failures == []


def test_restart_once_relaunches_on_the_same_port_and_only_once(make_server) -> None:
    server = _started(make_server())
    url, first_pid = server.base_url, server.pid

    assert server.restart_once() is True

    assert server.base_url == url  # los clientes siguen valiendo
    assert server.pid != first_pid
    assert http_get_ok(f"{url}/health")
    assert first_pid is not None and _wait_until_gone(first_pid)
    assert server.restart_once() is False  # un reinicio por sesión
    assert server.child.restart_count == 1


def test_stop_kills_the_process_and_is_idempotent(make_server) -> None:
    server = _started(make_server())
    pid = server.pid

    server.stop()
    server.stop()

    assert not server.is_alive()
    assert pid is not None and _wait_until_gone(pid)
    assert not http_get_ok(f"{server.base_url}/health")


def test_stop_without_starting_does_nothing(make_server) -> None:
    make_server().stop()


def test_stop_all_stops_it_through_its_child(make_server) -> None:
    server = _started(make_server())
    assert isinstance(server.child, ManagedChild)
    pid = server.pid

    stop_all([server.child])

    assert pid is not None and _wait_until_gone(pid)
    assert not server.is_alive()


def test_output_is_drained_and_available_for_diagnostics(make_server) -> None:
    server = make_server("--fake-mode", "exit_early", ready_timeout_s=60.0)
    server.start()
    with pytest.raises(EngineError):
        server.wait_ready()

    assert "no se pudo cargar el modelo" in server.output_tail(5)
