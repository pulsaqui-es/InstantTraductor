"""Tests de ``tts/service_process.py``: ``TtsServiceProcess`` sobre ``ManagedChild`` (T026).

Usan un servicio de voz falso: un script de Python efímero que hace lo mismo que ``tts-service`` sin GPU ni
modelo (ruido de las bibliotecas, la línea ``ready`` con el puerto elegido por el sistema, ``/health``,
``/voices``, ``/synthesize`` con PCM en *streaming* y ``/shutdown``) y que, según ``--fake-mode``, no dice
nunca que está listo, muere al arrancar o miente en la línea ``ready``. Son procesos reales del sistema. El
último test lanza el comando de verdad (``uv run --frozen --offline --project engines/tts-qwen3 tts-service``)
si el entorno del motor existe.
"""

from __future__ import annotations

import shutil
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import numpy as np
import psutil
import pytest

from instanttraductor.config import AppPaths
from instanttraductor.contracts import EngineError, SynthesisRequest, VoiceRef
from instanttraductor.platform import windows
from instanttraductor.platform.children import http_get_ok, stop_all
from instanttraductor.tts.http_client import HttpSynthesizer
from instanttraductor.tts.service_process import (
    ENGINE,
    OFFLINE_ENV,
    READY_TIMEOUT_S,
    TtsServiceInfo,
    TtsServiceProcess,
    engine_project_dir,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Solo para Windows")

#: Margen para esperas que NO miden ningún requisito de tiempo (el arranque de Python varía).
GENEROUS_S = 20.0

FAKE_SERVICE_SOURCE = r'''
"""Servicio de voz falso: lo mismo que tts-service, sin GPU ni modelo."""
import array
import http.server
import json
import os
import sys
import threading
import time

args = sys.argv[1:]


def option(name, default=None):
    return args[args.index(name) + 1] if name in args else default


mode = option("--fake-mode", "ok")
marker = option("--fake-marker")
die_after = float(option("--fake-die-after", "0"))

if mode == "exit_early":
    print("No hay voces en la carpeta: ejecuta «instanttraductor preparar».", file=sys.stderr, flush=True)
    sys.exit(3)
if mode == "no_ready":
    print("cargando el modelo...", flush=True)
    time.sleep(60)
    sys.exit(0)

BLOCKS = [array.array("f", [0.1 * (index + 1)] * 2400).tobytes() for index in range(3)]


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"status": "ok", "engine": "fake-tts", "sample_rate": 24000})
        elif self.path == "/voices":
            voice = {"voice_id": "es-f-fake", "name": "Voz", "gender": "f", "source": "x", "license": "PD"}
            self._json(200, [voice])
        elif self.path == "/argv":
            self._json(200, args)
        elif self.path == "/env":
            self._json(200, {key: os.environ.get(key) for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")})
        else:
            self._json(404, {"error": "Not Found"})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/synthesize":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Sample-Rate", "24000")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for block in BLOCKS:
                self.wfile.write(b"%x\r\n" % len(block) + block + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        elif self.path == "/shutdown":
            if marker:
                with open(marker, "w") as handle:
                    handle.write("shutdown")
            self._json(202, {"status": "stopping"})
            threading.Thread(target=server.shutdown).start()
        else:
            self._json(404, {"error": "Not Found"})

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", int(option("--port"))), Handler)
print("Capturing CUDA graph... (ruido de la biblioteca)", flush=True)
ready = {"event": "ready", "port": server.server_address[1], "sample_rate": 24000, "engine": "fake-tts",
         "supports_speed": False, "pid": os.getpid()}
if mode == "bad_ready":
    del ready["port"]
print(json.dumps(ready), flush=True)
if die_after:
    threading.Timer(die_after, lambda: os._exit(7)).start()
server.serve_forever()
sys.exit(0)
'''


@pytest.fixture(autouse=True)
def _close_shared_job() -> Iterator[None]:
    """Cierra el job único tras cada test: no queda ningún hijo vivo ni estado compartido."""
    yield
    windows.close_job()


@pytest.fixture
def make_service(tmp_path: Path) -> Iterator[Callable[..., TtsServiceProcess]]:
    """Fábrica de ``TtsServiceProcess`` sobre el servicio falso. Al terminar el test los para a todos."""
    script = tmp_path / "fake_tts_service.py"
    script.write_text(FAKE_SERVICE_SOURCE, encoding="utf-8")
    created: list[TtsServiceProcess] = []

    def factory(*fake_args: str, **kwargs) -> TtsServiceProcess:
        kwargs.setdefault("ready_timeout_s", GENEROUS_S)
        service = TtsServiceProcess(
            voices_dir=tmp_path / "voces",
            models_dir=tmp_path / "modelos",
            executable=[sys.executable, script],
            extra_args=fake_args,
            **kwargs,
        )
        created.append(service)
        return service

    yield factory
    for service in created:
        service.stop(grace_s=0.0)


def _request() -> SynthesisRequest:
    return SynthesisRequest(unit_id=5, text="Hola, ¿qué tal?", voice=VoiceRef("es-f-fake"))


def started(service: TtsServiceProcess) -> TtsServiceInfo:
    service.start()
    return service.wait_ready()


def get_json(service: TtsServiceProcess, path: str):
    return httpx.get(f"{service.base_url}{path}", trust_env=False, timeout=GENEROUS_S).json()


def wait_until(predicate: Callable[[], bool], timeout_s: float = GENEROUS_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.02)
    return predicate()


# ---------------------------------------------------------------------------
# Línea de comandos y rutas (sin lanzar nada)
# ---------------------------------------------------------------------------
class TestCommandLine:
    def test_the_default_command_is_the_uv_run_of_the_task(self, tmp_path: Path) -> None:
        service = TtsServiceProcess(voices_dir=tmp_path / "v", models_dir=tmp_path / "m")

        command = service.command()

        assert Path(command[0]).stem == "uv"
        assert command[1:] == [
            "run",
            "--frozen",
            "--offline",
            "--project",
            str(engine_project_dir()),
            "tts-service",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--voices-dir",
            str(tmp_path / "v"),
            "--models-dir",
            str(tmp_path / "m"),
        ]

    def test_the_directories_default_to_the_app_paths(self) -> None:
        service = TtsServiceProcess()

        command = service.command()

        assert command[command.index("--voices-dir") + 1] == str(AppPaths().voices)
        assert command[command.index("--models-dir") + 1] == str(AppPaths().models)

    def test_the_engine_project_is_the_one_in_the_repository(self) -> None:
        project = engine_project_dir()

        assert project.name == "tts-qwen3" and project.parent.name == "engines"
        assert "tts-service" in (project / "pyproject.toml").read_text(encoding="utf-8")

    def test_the_service_is_launched_without_network_access(self) -> None:
        assert dict(OFFLINE_ENV) == {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}

    def test_ready_timeout_defaults_to_120_seconds(self) -> None:
        assert READY_TIMEOUT_S == 120.0

    def test_extra_args_go_at_the_end(self, tmp_path: Path) -> None:
        service = TtsServiceProcess(
            voices_dir=tmp_path, models_dir=tmp_path, extra_args=("--chunk-size", "8")
        )

        assert service.command()[-2:] == ["--chunk-size", "8"]

    def test_a_custom_executable_replaces_the_uv_prefix(self, tmp_path: Path) -> None:
        service = TtsServiceProcess(
            voices_dir=tmp_path, models_dir=tmp_path, executable=["python", "servicio.py"]
        )

        assert service.command()[:3] == ["python", "servicio.py", "--host"]

    def test_an_empty_executable_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            TtsServiceProcess(voices_dir=tmp_path, models_dir=tmp_path, executable=[])

    def test_the_url_and_the_synthesizer_need_a_ready_service(self, tmp_path: Path) -> None:
        service = TtsServiceProcess(voices_dir=tmp_path, models_dir=tmp_path)

        with pytest.raises(EngineError, match="listo"):
            service.base_url  # noqa: B018
        with pytest.raises(EngineError, match="listo"):
            service.info  # noqa: B018
        with pytest.raises(EngineError, match="listo"):
            service.synthesizer()


# ---------------------------------------------------------------------------
# Falta algo: no se lanza nada
# ---------------------------------------------------------------------------
class TestMissingPieces:
    def test_start_without_the_engine_project_is_a_non_recoverable_error(self, tmp_path: Path) -> None:
        service = TtsServiceProcess(
            voices_dir=tmp_path, models_dir=tmp_path, project_dir=tmp_path / "no-existe"
        )

        with pytest.raises(EngineError) as error:
            service.start()

        assert error.value.recoverable is False
        assert error.value.engine == ENGINE
        assert "engines" in str(error.value) or "tts-qwen3" in str(error.value)
        assert service.pid is None

    def test_start_without_uv_is_a_non_recoverable_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        service = TtsServiceProcess(voices_dir=tmp_path, models_dir=tmp_path)

        with pytest.raises(EngineError, match="uv") as error:
            service.start()

        assert error.value.recoverable is False
        assert service.pid is None

    def test_start_with_an_unlaunchable_executable_is_an_engine_error(self, tmp_path: Path) -> None:
        service = TtsServiceProcess(
            voices_dir=tmp_path, models_dir=tmp_path, executable=[str(tmp_path / "no-existe.exe")]
        )

        with pytest.raises(EngineError) as error:
            service.start()

        assert error.value.recoverable is False


# ---------------------------------------------------------------------------
# Arranque y línea «ready»
# ---------------------------------------------------------------------------
class TestStartup:
    def test_wait_ready_returns_what_the_ready_line_says(self, make_service) -> None:
        service = make_service()

        info = started(service)

        assert info == TtsServiceInfo(
            port=info.port, sample_rate=24_000, engine="fake-tts", supports_speed=False
        )
        assert info.port > 0
        assert service.info == info
        assert service.base_url == f"http://127.0.0.1:{info.port}"
        assert service.is_alive()
        assert service.pid is not None and psutil.pid_exists(service.pid)
        assert http_get_ok(f"{service.base_url}/health")

    def test_the_noise_before_the_ready_line_is_ignored_but_kept_for_the_logs(self, make_service) -> None:
        service = make_service()
        started(service)

        assert "ruido de la biblioteca" in service.output_tail()

    def test_the_service_gets_the_options_of_the_task(self, make_service, tmp_path: Path) -> None:
        service = make_service()
        started(service)

        received = get_json(service, "/argv")

        assert received[received.index("--host") + 1] == "127.0.0.1"
        assert received[received.index("--port") + 1] == "0"
        assert received[received.index("--voices-dir") + 1] == str(tmp_path / "voces")
        assert received[received.index("--models-dir") + 1] == str(tmp_path / "modelos")

    def test_the_service_gets_the_offline_environment(self, make_service) -> None:
        service = make_service()
        started(service)

        assert get_json(service, "/env") == {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}

    def test_a_service_that_never_says_ready_times_out_and_is_killed(self, make_service) -> None:
        service = make_service("--fake-mode", "no_ready", ready_timeout_s=1.0)
        service.start()
        pid = service.pid

        with pytest.raises(EngineError) as error:
            service.wait_ready()

        assert error.value.recoverable is False
        assert error.value.engine == ENGINE
        assert "no quedó listo" in str(error.value)
        assert pid is not None and wait_until(lambda: not psutil.pid_exists(pid), 5.0)

    def test_a_service_that_dies_during_startup_reports_what_it_wrote_on_stderr(self, make_service) -> None:
        service = make_service("--fake-mode", "exit_early")
        service.start()

        with pytest.raises(EngineError) as error:
            service.wait_ready()

        assert error.value.recoverable is False
        assert "terminó durante el arranque" in str(error.value)
        assert "código 3" in str(error.value)
        assert "No hay voces" in str(error.value)
        assert not service.is_alive()

    def test_a_ready_line_without_the_port_is_an_error_and_nothing_stays_running(self, make_service) -> None:
        service = make_service("--fake-mode", "bad_ready")
        service.start()
        pid = service.pid

        with pytest.raises(EngineError, match="port") as error:
            service.wait_ready()

        assert error.value.recoverable is False
        assert pid is not None and wait_until(lambda: not psutil.pid_exists(pid), 5.0)


@pytest.mark.parametrize(
    "message",
    [
        {"event": "ready", "port": 0, "sample_rate": 24000, "engine": "x", "supports_speed": False},
        {"event": "ready", "port": 70000, "sample_rate": 24000, "engine": "x", "supports_speed": False},
        {"event": "ready", "port": "51234", "sample_rate": 24000, "engine": "x", "supports_speed": False},
        {"event": "ready", "port": 51234, "sample_rate": 0, "engine": "x", "supports_speed": False},
        {"event": "ready", "port": 51234, "sample_rate": 24000, "engine": "", "supports_speed": False},
        {"event": "ready", "port": 51234, "sample_rate": 24000, "engine": "x", "supports_speed": "no"},
        {"event": "ready", "port": 51234, "engine": "x", "supports_speed": False},
        {"event": "ready", "port": True, "sample_rate": 24000, "engine": "x", "supports_speed": False},
    ],
)
def test_an_invalid_ready_line_is_rejected(message: dict) -> None:
    with pytest.raises(EngineError) as error:
        TtsServiceInfo.from_ready(message)

    assert error.value.recoverable is False


def test_a_missing_ready_info_is_rejected() -> None:
    with pytest.raises(EngineError, match="listo"):
        TtsServiceInfo.from_ready(None)


def test_extra_fields_of_the_ready_line_are_ignored() -> None:
    message = {
        "event": "ready",
        "port": 51234,
        "sample_rate": 24000,
        "engine": "x",
        "supports_speed": True,
        "pid": 1,
    }

    assert TtsServiceInfo.from_ready(message) == TtsServiceInfo(51234, 24000, "x", True)


# ---------------------------------------------------------------------------
# Parada, salud y reinicio
# ---------------------------------------------------------------------------
class TestShutdownAndHealth:
    def test_stop_asks_the_service_to_shut_down_with_post_shutdown(
        self, make_service, tmp_path: Path
    ) -> None:
        marker = tmp_path / "shutdown.txt"
        service = make_service("--fake-marker", str(marker))
        started(service)
        pid = service.pid

        service.stop()

        assert marker.read_text() == "shutdown"  # llegó el POST /shutdown: no se mató sin más
        assert not service.is_alive()
        assert service.child.returncode == 0  # salió él solo, con orden
        assert pid is not None and not psutil.pid_exists(pid)

    def test_stop_all_stops_it_in_parallel_within_two_seconds(self, make_service, tmp_path: Path) -> None:
        marker = tmp_path / "shutdown.txt"
        service = make_service("--fake-marker", str(marker))
        started(service)

        begun = time.monotonic()
        stop_all([service.child])
        elapsed = time.monotonic() - begun

        assert marker.exists()
        assert not service.is_alive()
        assert elapsed <= 2.0

    def test_stop_is_idempotent_and_harmless_if_never_started(self, make_service) -> None:
        service = make_service()

        service.stop()  # nunca se lanzó
        started(service)
        service.stop()
        service.stop()

    def test_a_service_that_dies_triggers_on_failure_once_with_the_reason(self, make_service) -> None:
        failures: list[tuple[TtsServiceProcess, str]] = []
        service = make_service(
            "--fake-die-after",
            "0.3",
            health_interval_s=0.1,
            on_failure=lambda svc, reason: failures.append((svc, reason)),
        )
        started(service)

        assert wait_until(lambda: len(failures) == 1)
        time.sleep(0.5)

        assert len(failures) == 1
        assert failures[0][0] is service
        # Según quién lo note primero: que el proceso terminó (código 7) o que la salud ya no responde.
        assert "terminó" in failures[0][1] or "salud" in failures[0][1]

    def test_a_deliberate_stop_is_not_a_failure(self, make_service) -> None:
        failures: list[str] = []
        service = make_service(health_interval_s=0.1, on_failure=lambda _svc, reason: failures.append(reason))
        started(service)

        service.stop()
        time.sleep(0.5)

        assert failures == []

    def test_restart_once_follows_the_new_process_and_only_works_once(self, make_service) -> None:
        service = make_service()
        started(service)
        assert service.child.ready_info is not None
        first_pid = service.child.ready_info["pid"]

        assert service.restart_once() is True

        assert service.child.ready_info is not None
        assert service.child.ready_info["pid"] != first_pid
        assert http_get_ok(f"{service.base_url}/health")
        assert service.info.port == service.child.ready_info["port"]
        assert service.restart_once() is False  # un solo reinicio por sesión


# ---------------------------------------------------------------------------
# El sintetizador de este servicio
# ---------------------------------------------------------------------------
class TestSynthesizer:
    def test_it_takes_its_description_from_the_ready_line(self, make_service) -> None:
        service = make_service()
        started(service)

        synth = service.synthesizer()
        try:
            assert isinstance(synth, HttpSynthesizer)
            assert (synth.name, synth.sample_rate, synth.supports_speed) == ("fake-tts", 24_000, False)
        finally:
            synth.close()

    def test_it_synthesizes_and_lists_voices_through_the_real_service(self, make_service) -> None:
        service = make_service()
        started(service)
        synth = service.synthesizer()

        try:
            chunks = list(synth.synthesize(_request()))
            voices = synth.list_voices()
        finally:
            synth.close()

        audio = np.concatenate([chunk.samples for chunk in chunks])
        expected = np.concatenate([np.full(2400, 0.1 * (index + 1), dtype=np.float32) for index in range(3)])
        assert np.array_equal(audio, expected)
        assert [chunk.is_last for chunk in chunks] == [False] * (len(chunks) - 1) + [True]
        assert {chunk.unit_id for chunk in chunks} == {5}
        assert [voice.voice_id for voice in voices] == ["es-f-fake"]

    def test_it_keeps_working_after_the_service_is_restarted_on_another_port(self, make_service) -> None:
        service = make_service()
        started(service)
        synth = service.synthesizer()
        try:
            assert list(synth.synthesize(_request()))
            pid = service.pid
            assert pid is not None
            psutil.Process(pid).kill()  # el servicio muere de golpe (un fallo)...
            assert wait_until(lambda: not psutil.pid_exists(pid), 5.0)
            with pytest.raises(EngineError):  # ...y mientras está caído la síntesis falla con EngineError
                list(synth.synthesize(_request()))

            assert service.restart_once() is True

            assert list(synth.synthesize(_request()))  # el mismo sintetizador sigue al proceso nuevo
        finally:
            synth.close()

    def test_the_synthesizer_is_a_thread_safe_client_of_the_service(self, make_service) -> None:
        service = make_service()
        started(service)
        synth = service.synthesizer()
        results: list[int] = []

        def work() -> None:
            results.append(sum(chunk.samples.size for chunk in synth.synthesize(_request())))

        threads = [threading.Thread(target=work) for _ in range(4)]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(GENEROUS_S)
        finally:
            synth.close()

        assert results == [3 * 2400] * 4


# ---------------------------------------------------------------------------
# El comando de verdad
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not (engine_project_dir() / ".venv").is_dir() or shutil.which("uv") is None,
    reason="Necesita uv y el entorno del motor: uv sync --project engines/tts-qwen3",
)
def test_the_real_command_line_reaches_the_service_and_it_fails_fast_without_voices(tmp_path: Path) -> None:
    """``uv run --frozen --offline --project engines/tts-qwen3 tts-service ...`` de verdad, sin GPU ni modelo.

    Sin voces, el servicio real (``tts_service``) escribe su error por ``stderr`` y sale con un código
    distinto de 0 antes de cargar torch: se comprueba que uv acepta las opciones, que el servicio acepta las
    suyas y que el error llega hasta ``EngineError``.
    """
    service = TtsServiceProcess(
        voices_dir=tmp_path / "voces", models_dir=tmp_path / "modelos", ready_timeout_s=120.0
    )
    try:
        service.start()
        with pytest.raises(EngineError) as error:
            service.wait_ready()
    finally:
        service.stop(grace_s=0.0)

    assert error.value.recoverable is False
    assert "terminó durante el arranque" in str(error.value)
    assert "error de arranque" in str(error.value)
    assert "voces" in str(error.value)
    assert "Traceback" not in str(error.value)  # un error esperado no lleva traza
