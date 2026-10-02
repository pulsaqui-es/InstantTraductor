"""Procesos hijos gestionados: arranque, espera de «listo», salud, un reinicio y parada en paralelo.

Lo usan ``mt/llama_server.py`` (``llama-server``) y ``tts/service_process.py`` (servicio de voz).
Cubre research R10, FR-015 y FR-018:

- Cada hijo se lanza con ``platform.windows.launch_child``: sin ventana, con ``stdout`` y ``stderr``
  en tuberías (que ``ManagedChild`` vacía siempre, para que el hijo nunca se bloquee) y dentro del
  *Job Object* con ``KILL_ON_JOB_CLOSE``: si el núcleo muere, mueren ellos y sus descendientes.
- «Listo» es una estrategia con tiempo máximo: ``ReadyJsonLine`` (una línea JSON en ``stdout`` que
  cumple un predicado, como la línea ``ready`` del servicio de voz) o ``ReadyHttpHealth``
  (``GET /health`` devuelve 200, como ``llama-server``).
- ``HealthCheck`` comprueba la salud cada 2 s y avisa por *callback* de un fallo. Es una sola
  notificación por fallo: quien la recibe decide (``restart_once()`` o parada limpia).
- ``restart_once()`` reinicia el hijo como máximo una vez por sesión.
- ``stop_all()`` pide la parada ordenada a todos en paralelo, espera la gracia y cierra el job, que
  mata de inmediato lo que quede: todo en <= 2 s en total.

Uso típico, ``llama-server`` (puerto elegido antes; sin parada ordenada: lo mata el job)::

    llama = ManagedChild(
        [str(exe), "-m", str(model), "--port", str(port)],
        ready=ReadyHttpHealth(f"http://127.0.0.1:{port}/health", timeout_s=30),
        health=HealthCheck(probe=lambda c: http_get_ok(health_url), on_failure=on_llama_failure),
    )

Servicio de voz (``--port 0``: el puerto llega en la línea ``ready``; los *callbacks* reciben el
hijo y lo leen de ``child.ready_info``, que se actualiza si se reinicia)::

    def base_url(child: ManagedChild) -> str:
        return f"http://127.0.0.1:{child.ready_info['port']}"

    voice = ManagedChild(
        [*uv_command, "tts-service", "--port", "0"],
        ready=ReadyJsonLine(timeout_s=120),
        env={"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        health=HealthCheck(
            probe=lambda c: http_get_ok(base_url(c) + "/health"), on_failure=on_voice_failure
        ),
        graceful_stop=lambda c: httpx.post(base_url(c) + "/shutdown", timeout=0.5),
    )

Después: ``child.start()``, ``child.wait_ready()`` y, al terminar, ``stop_all([llama, voice])``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn, TextIO

import httpx
import psutil

from instanttraductor.platform import windows

__all__ = [
    "HEALTH_INTERVAL_S",
    "MAX_RESTARTS",
    "OUTPUT_TAIL_LINES",
    "STOP_BUDGET_S",
    "ChildError",
    "ChildExitedError",
    "ChildTimeoutError",
    "HealthCheck",
    "ManagedChild",
    "ReadyHttpHealth",
    "ReadyJsonLine",
    "ReadyStrategy",
    "http_get_ok",
    "stop_all",
]

logger = logging.getLogger(__name__)

#: Cada cuántos segundos se comprueba la salud de un hijo (R10).
HEALTH_INTERVAL_S = 2.0
#: Máximo de reinicios de un hijo por sesión (R10).
MAX_RESTARTS = 1
#: Presupuesto total de la parada de todos los hijos (R10, FR-015).
STOP_BUDGET_S = 2.0
#: Líneas de salida de cada hijo que se conservan para los mensajes de error.
OUTPUT_TAIL_LINES = 200

_POLL_INTERVAL_S = 0.05
# En Windows una conexión rechazada tarda 1-2 s en fallar; con un tiempo de conexión corto se
# reintenta antes (en el bucle local una conexión que sí se acepta tarda menos de 1 ms).
_CONNECT_TIMEOUT_S = 0.25
_READER_JOIN_S = 1.0


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------
class ChildError(RuntimeError):
    """Error de un proceso hijo gestionado."""


class ChildTimeoutError(ChildError, TimeoutError):
    """El hijo no quedó listo en el tiempo máximo (se ha terminado el proceso)."""


class ChildExitedError(ChildError):
    """El hijo terminó antes de quedar listo."""


# ---------------------------------------------------------------------------
# Estrategias de «listo» y de salud
# ---------------------------------------------------------------------------
def http_get_ok(url: str, *, timeout_s: float = 1.0) -> bool:
    """``True`` si ``GET url`` devuelve 200 en ``timeout_s``; ``False`` ante cualquier fallo de red.

    No usa las variables de proxy del entorno: los hijos escuchan solo en 127.0.0.1.
    """
    timeout = httpx.Timeout(timeout_s, connect=min(timeout_s, _CONNECT_TIMEOUT_S))
    try:
        return httpx.get(url, timeout=timeout, trust_env=False).status_code == 200
    except httpx.HTTPError:
        return False


def _is_ready_event(message: dict[str, Any]) -> bool:
    """Predicado por defecto: la línea ``ready`` del servicio de voz (contracts/tts-service.md)."""
    return message.get("event") == "ready"


@dataclass(frozen=True)
class ReadyJsonLine:
    """Listo cuando el hijo escribe en ``stdout`` una línea JSON (objeto) que cumple el predicado.

    ``ManagedChild.wait_ready()`` devuelve ese objeto (p. ej. con el puerto elegido por el sistema).
    """

    predicate: Callable[[dict[str, Any]], bool] = _is_ready_event
    timeout_s: float = 120.0


@dataclass(frozen=True)
class ReadyHttpHealth:
    """Listo cuando ``GET url`` devuelve 200 (``llama-server``: 503 mientras carga el modelo)."""

    url: str
    timeout_s: float = 30.0


ReadyStrategy = ReadyJsonLine | ReadyHttpHealth


@dataclass(frozen=True)
class HealthCheck:
    """Salud periódica de un hijo que ya está listo.

    - Falla si el proceso ha terminado o si ``probe(child)`` devuelve ``False`` o lanza una
      excepción. Sin ``probe`` solo se comprueba que el proceso sigue vivo.
    - ``on_failure(child, motivo)`` se llama **una sola vez** por fallo, desde el hilo de salud. No
      se llama si el hijo se detiene a propósito (``stop`` o ``stop_all``).
    """

    interval_s: float = HEALTH_INTERVAL_S
    probe: Callable[[ManagedChild], bool] | None = None
    on_failure: Callable[[ManagedChild, str], None] | None = None


# ---------------------------------------------------------------------------
# Hijo gestionado
# ---------------------------------------------------------------------------
class _Run:
    """Estado de una ejecución concreta del proceso (cada arranque o reinicio crea una nueva)."""

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc
        self.started_at = time.monotonic()
        self.ready = threading.Event()
        self.ready_info: dict[str, Any] | None = None
        self.stopping = threading.Event()  # parada pedida: que el proceso muera no es un fallo
        self.confirmed = False  # wait_ready() ya terminó con éxito (y la salud ya está en marcha)
        self.readers: list[threading.Thread] = []


def _parse_json_object(line: str) -> dict[str, Any] | None:
    text = line.strip()
    if not text.startswith("{"):
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    """Mata al proceso y a sus descendientes (``uv run`` lanza a Python como proceso nieto)."""
    victims: list[psutil.Process] = []
    with contextlib.suppress(psutil.Error):
        victims = psutil.Process(proc.pid).children(recursive=True)
    for victim in victims:
        with contextlib.suppress(psutil.Error):
            victim.kill()
    with contextlib.suppress(OSError):
        proc.kill()


class ManagedChild:
    """Proceso hijo con «listo», salud periódica, un reinicio y parada ordenada.

    Parámetros:

    - ``args``: línea de comandos.
    - ``ready``: estrategia de «listo» (``ReadyJsonLine`` o ``ReadyHttpHealth``), con tiempo máximo.
    - ``env``: variables que se añaden o sustituyen a las del proceso actual.
    - ``health``: salud periódica (``HealthCheck``); ``None`` si no hace falta.
    - ``graceful_stop``: ``callback(child)`` que pide la parada ordenada (p. ej. ``POST /shutdown``).
      Se ejecuta en su propio hilo y ``stop_all`` no espera más de la gracia por él; aun así, usa
      tiempos de espera cortos (en Windows una conexión rechazada tarda 1-2 s en fallar). ``None``
      si el hijo no tiene parada ordenada: entonces se mata directamente (``llama-server``).
    - ``cwd``: directorio de trabajo. ``name``: nombre para los mensajes y el registro.
    """

    def __init__(
        self,
        args: Sequence[str | os.PathLike[str]],
        *,
        ready: ReadyStrategy,
        env: Mapping[str, str] | None = None,
        health: HealthCheck | None = None,
        graceful_stop: Callable[[ManagedChild], None] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        name: str = "hijo",
    ) -> None:
        self._args = tuple(args)
        self._ready = ready
        self._env = dict(env) if env else None
        self._health = health
        self._graceful_stop = graceful_stop
        self._cwd = cwd
        self.name = name
        self._lock = threading.Lock()
        self._run: _Run | None = None
        self._restarts = 0
        self._stop_requested = False
        self._output: deque[str] = deque(maxlen=OUTPUT_TAIL_LINES)
        self._output_lock = threading.Lock()

    def __repr__(self) -> str:
        return f"ManagedChild(name={self.name!r}, pid={self.pid})"

    # -- estado ------------------------------------------------------------
    @property
    def pid(self) -> int | None:
        """PID del último proceso lanzado (se conserva tras pararlo); ``None`` si no se lanzó."""
        run = self._run
        return run.proc.pid if run is not None else None

    @property
    def returncode(self) -> int | None:
        """Código de salida; ``None`` si sigue vivo o no se lanzó."""
        run = self._run
        return run.proc.poll() if run is not None else None

    @property
    def ready_info(self) -> dict[str, Any] | None:
        """Objeto JSON de «listo» (``{}`` con ``ReadyHttpHealth``); ``None`` si aún no está listo."""
        run = self._run
        return run.ready_info if run is not None else None

    @property
    def restart_count(self) -> int:
        """Reinicios consumidos (``restart_once``): 0 o 1."""
        return self._restarts

    def is_alive(self) -> bool:
        run = self._run
        return run is not None and run.proc.poll() is None

    def output_tail(self, lines: int = 40) -> str:
        """Las últimas líneas que el hijo escribió por ``stdout`` y ``stderr``."""
        with self._output_lock:
            tail = list(self._output)[-lines:] if lines > 0 else []
        return "\n".join(tail)

    # -- arranque ----------------------------------------------------------
    def start(self) -> None:
        """Lanza el proceso (sin esperar a que esté listo: ver ``wait_ready``)."""
        with self._lock:
            self._stop_requested = False
            self._launch_locked()

    def _launch_locked(self) -> None:
        if self._run is not None and self._run.proc.poll() is None:
            raise RuntimeError(f"«{self.name}» ya está en marcha")
        proc = windows.launch_child(self._args, env=self._env, cwd=self._cwd)
        run = _Run(proc)
        run.readers = [
            threading.Thread(
                target=self._pump, args=(run, proc.stdout, True), name=f"{self.name}-stdout", daemon=True
            ),
            threading.Thread(
                target=self._pump, args=(run, proc.stderr, False), name=f"{self.name}-stderr", daemon=True
            ),
        ]
        for reader in run.readers:
            reader.start()
        self._run = run
        logger.info("«%s» lanzado (pid %s)", self.name, proc.pid)

    def _pump(self, run: _Run, stream: TextIO | None, is_stdout: bool) -> None:
        """Vacía una tubería del hijo; en ``stdout`` busca además la línea de «listo»."""
        if stream is None:
            return
        looks_for_ready = is_stdout and isinstance(self._ready, ReadyJsonLine)
        try:
            for raw in stream:
                line = raw.rstrip("\r\n")
                with self._output_lock:
                    self._output.append(line)
                logger.debug("[%s] %s", self.name, line)
                if looks_for_ready and not run.ready.is_set():
                    self._check_ready_line(run, line)
        except (OSError, ValueError):  # tubería cerrada durante la parada
            pass

    def _check_ready_line(self, run: _Run, line: str) -> None:
        message = _parse_json_object(line)
        if message is None:
            return
        assert isinstance(self._ready, ReadyJsonLine)
        try:
            matches = self._ready.predicate(message)
        except Exception:
            logger.exception("El predicado de «listo» de «%s» lanzó una excepción", self.name)
            return
        if matches:
            run.ready_info = message
            run.ready.set()

    def wait_ready(self) -> dict[str, Any]:
        """Espera a que el hijo esté listo y arranca su salud periódica.

        Devuelve el objeto JSON de la línea de «listo» (``{}`` con ``ReadyHttpHealth``). Si el hijo
        muere o no queda listo a tiempo, lo termina y lanza ``ChildExitedError`` o
        ``ChildTimeoutError`` (con las últimas líneas que escribió).
        """
        run = self._run
        if run is None:
            raise RuntimeError(f"«{self.name}» no se ha lanzado: falta llamar a start()")
        with self._lock:
            if run.confirmed:
                return run.ready_info or {}
        deadline = run.started_at + self._ready.timeout_s
        if isinstance(self._ready, ReadyJsonLine):
            self._wait_json_line(run, deadline)
        else:
            self._wait_http_health(run, self._ready.url, deadline)
        with self._lock:
            if not run.confirmed:
                run.confirmed = True
                self._start_monitor(run)
        return run.ready_info or {}

    def _wait_json_line(self, run: _Run, deadline: float) -> None:
        while not run.ready.wait(_POLL_INTERVAL_S):
            if run.proc.poll() is not None:
                # Pudo escribir «ready» justo antes de morir: se deja que su lector termine.
                run.readers[0].join(timeout=_READER_JOIN_S)
                if run.ready.is_set():
                    return
                self._fail_start_exited(run)
            if time.monotonic() >= deadline:
                self._fail_start_timeout(run)

    def _wait_http_health(self, run: _Run, url: str, deadline: float) -> None:
        while True:
            if run.proc.poll() is not None:
                self._fail_start_exited(run)
            if http_get_ok(url):
                run.ready_info = {}
                run.ready.set()
                return
            if time.monotonic() >= deadline:
                self._fail_start_timeout(run)
            time.sleep(_POLL_INTERVAL_S)

    def _fail_start_exited(self, run: _Run) -> NoReturn:
        code = run.proc.poll()
        self._kill_run(run)  # también mata a posibles descendientes y recoge toda su salida
        raise ChildExitedError(self._with_tail(f"«{self.name}» terminó durante el arranque (código {code})."))

    def _fail_start_timeout(self, run: _Run) -> NoReturn:
        self._kill_run(run)
        raise ChildTimeoutError(
            self._with_tail(f"«{self.name}» no quedó listo en {self._ready.timeout_s:g} s.")
        )

    def _with_tail(self, message: str) -> str:
        tail = self.output_tail()
        return f"{message}\n{tail}" if tail else message

    # -- salud -------------------------------------------------------------
    def _start_monitor(self, run: _Run) -> None:
        if self._health is None:
            return
        threading.Thread(
            target=self._monitor, args=(run, self._health), name=f"{self.name}-salud", daemon=True
        ).start()

    def _monitor(self, run: _Run, health: HealthCheck) -> None:
        while not run.stopping.wait(health.interval_s):
            reason = self._health_failure(run, health)
            if reason is None:
                continue
            if run.stopping.is_set():  # se detuvo a propósito mientras se comprobaba
                return
            logger.warning("«%s» (pid %s) falló: %s", self.name, run.proc.pid, reason)
            if health.on_failure is not None:
                try:
                    health.on_failure(self, reason)
                except Exception:
                    logger.exception("El callback de fallo de «%s» lanzó una excepción", self.name)
            return  # una sola notificación por fallo; un reinicio arranca su propia vigilancia

    def _health_failure(self, run: _Run, health: HealthCheck) -> str | None:
        code = run.proc.poll()
        if code is not None:
            return f"el proceso terminó (código {code})"
        if health.probe is None:
            return None
        try:
            healthy = health.probe(self)
        except Exception as exc:
            return f"la comprobación de salud falló: {exc}"
        return None if healthy else "la comprobación de salud no pasó"

    # -- reinicio ----------------------------------------------------------
    def restart_once(self) -> bool:
        """Reinicia el hijo como máximo una vez por sesión (R10).

        Termina el proceso actual (con sus descendientes), lanza uno nuevo y espera a que esté
        listo. Devuelve ``True`` si el nuevo está listo; ``False`` si el reinicio ya se gastó, si se
        pidió parar o si el nuevo no queda listo (entonces no queda ningún proceso corriendo).
        """
        with self._lock:
            if self._stop_requested or self._restarts >= MAX_RESTARTS:
                return False
            self._restarts += 1
            old = self._run
        if old is not None:
            self._kill_run(old)
        try:
            with self._lock:
                if self._stop_requested:
                    return False
                self._launch_locked()
            self.wait_ready()
        except (ChildError, OSError) as exc:
            logger.warning("No se pudo reiniciar «%s»: %s", self.name, exc)
            return False
        logger.info("«%s» reiniciado (pid %s)", self.name, self.pid)
        return True

    # -- parada ------------------------------------------------------------
    def stop(self, grace_s: float = 1.0) -> None:
        """Para este hijo: parada ordenada (si la tiene), hasta ``grace_s`` de gracia y después se
        mata al proceso y a sus descendientes. Es idempotente y no hace nada si no se lanzó.

        Para varios hijos a la vez y con el job, usa ``stop_all``.
        """
        with self._lock:
            self._stop_requested = True
            run = self._run
        if run is None:
            return
        run.stopping.set()
        if run.proc.poll() is None and self._graceful_stop is not None:
            self._request_graceful_stop(run)
            self._wait_exit(run, time.monotonic() + grace_s)
        self._kill_run(run)

    def _request_graceful_stop(self, run: _Run) -> None:
        """Lanza el *callback* de parada ordenada en un hilo propio (puede tardar o colgarse)."""
        callback = self._graceful_stop
        if callback is None:
            return

        def call() -> None:
            try:
                callback(self)
            except Exception as exc:
                logger.warning("La parada ordenada de «%s» falló: %s", self.name, exc)

        threading.Thread(target=call, name=f"{self.name}-parada", daemon=True).start()

    @staticmethod
    def _wait_exit(run: _Run, deadline: float) -> bool:
        """Espera a que el proceso termine hasta ``deadline`` (``time.monotonic``)."""
        try:
            run.proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return False
        return True

    def _kill_run(self, run: _Run) -> None:
        """Mata el proceso y sus descendientes, espera a que muera y cierra las tuberías."""
        run.stopping.set()
        _kill_tree(run.proc)
        with contextlib.suppress(subprocess.TimeoutExpired):
            run.proc.wait(timeout=5.0)
        self._finalize(run, time.monotonic() + 2 * _READER_JOIN_S)

    @staticmethod
    def _finalize(run: _Run, deadline: float) -> None:
        """Con el proceso muerto: espera a los lectores y cierra las tuberías."""
        current = threading.current_thread()
        for reader in run.readers:
            if reader is not current:
                reader.join(timeout=max(0.0, min(_READER_JOIN_S, deadline - time.monotonic())))
        if any(reader.is_alive() for reader in run.readers):
            return  # un descendiente aún tiene la tubería abierta: se cierra sola al morir
        for stream in (run.proc.stdout, run.proc.stderr):
            if stream is not None:
                with contextlib.suppress(OSError, ValueError):
                    stream.close()


# ---------------------------------------------------------------------------
# Parada de todos
# ---------------------------------------------------------------------------
def stop_all(children: Iterable[ManagedChild], grace_s: float = 1.0) -> None:
    """Para todos los hijos en <= 2 s (R10): parada ordenada en paralelo y después el job.

    1. Desde este momento, que un hijo muera no cuenta como fallo de salud ni se reinicia.
    2. Envía la parada ordenada (``graceful_stop``) a **todos a la vez**, cada una en su hilo: un
       *callback* colgado no retrasa la parada.
    3. Espera hasta ``grace_s`` a que salgan los que tienen parada ordenada (menos si salen antes).
    4. Cierra el job (``close_job``): Windows mata de inmediato lo que quede, con sus descendientes
       (también a los procesos lanzados con ``launch_child`` que no estén en ``children``).
    5. Confirma que han muerto y cierra las tuberías.

    El total es ``grace_s`` más lo que tarda Windows en matar (milisegundos): con la gracia por
    defecto de 1 s cumple el presupuesto de 2 s; con una gracia mayor de 1,5 s ya no se garantiza.
    """
    started = time.monotonic()
    runs: list[tuple[ManagedChild, _Run]] = []
    for child in children:
        with child._lock:
            child._stop_requested = True
            run = child._run
        if run is not None:
            run.stopping.set()
            runs.append((child, run))

    polite = [(child, run) for child, run in runs if run.proc.poll() is None and child._graceful_stop]
    for child, run in polite:
        child._request_graceful_stop(run)
    grace_deadline = started + grace_s
    for _, run in polite:
        ManagedChild._wait_exit(run, grace_deadline)

    windows.close_job()

    confirm_deadline = max(time.monotonic() + 0.5, started + STOP_BUDGET_S)
    for child, run in runs:
        if not ManagedChild._wait_exit(run, confirm_deadline):
            logger.warning("«%s» (pid %s) sigue vivo tras cerrar el job", child.name, run.proc.pid)
            continue
        ManagedChild._finalize(run, confirm_deadline)
    elapsed = time.monotonic() - started
    if elapsed > STOP_BUDGET_S:
        logger.warning("La parada de los hijos tardó %.2f s (presupuesto: %.1f s)", elapsed, STOP_BUDGET_S)
