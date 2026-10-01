"""``llama-server`` como proceso hijo gestionado (T021, research R7 y R10, ADR-0011).

``LlamaServerProcess`` lanza ``llama-server.exe`` (de ``component_dir("llama-cpp")``) con ``ManagedChild``:

- Escucha solo en ``127.0.0.1``, en un puerto libre elegido al construir el objeto.
- Línea de comandos de S2: ``-m <gguf> -ngl 99 -c 4096 -np 1 -fit off --no-webui`` y, por la RAM,
  ``--cache-ram 0`` (``spikes/traduccion/README.md``, «Configuración de llama-server recomendada»).
- No imprime una línea ``ready``: está listo cuando ``GET /health`` devuelve 200 (503 mientras carga el
  modelo), en 30 s como máximo.
- Salud cada 2 s; si falla, avisa por ``on_failure(servidor, motivo)`` (una sola vez por fallo) y quien
  recibe el aviso decide: ``restart_once()`` (el puerto no cambia, así que ``base_url`` sigue valiendo) o
  parada limpia.
- No tiene parada ordenada: se mata directamente (y, si el núcleo muere, lo mata el *Job Object*).

Uso::

    server = LlamaServerProcess(model_path(MtModel.HY_MT2_7B), on_failure=handle_failure)
    server.start()          # lanza el proceso
    server.wait_ready()     # espera a /health; EngineError(recoverable=False) si no llega
    translator = HyMt2Translator(server.base_url, MtModel.HY_MT2_7B)
    ...
    stop_all([server.child, ...])   # parada en paralelo con el resto de hijos
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from instanttraductor.contracts import EngineError
from instanttraductor.platform.children import (
    HEALTH_INTERVAL_S,
    ChildError,
    HealthCheck,
    ManagedChild,
    ReadyHttpHealth,
    http_get_ok,
)
from instanttraductor.setup.manifest import component_dir

__all__ = [
    "CONTEXT_SIZE",
    "ENGINE",
    "HOST",
    "N_GPU_LAYERS",
    "READY_TIMEOUT_S",
    "LlamaServerProcess",
    "find_free_port",
    "llama_server_exe",
]

logger = logging.getLogger(__name__)

#: Nombre con el que los errores de este módulo identifican al motor (``EngineError.engine``).
ENGINE: Final = "llama-server"
#: Solo el bucle local: el servidor no se expone fuera del equipo.
HOST: Final = "127.0.0.1"
EXE_NAME: Final = "llama-server.exe"
#: Tiempo máximo hasta que ``GET /health`` devuelve 200 (el 7B arranca en ~2 s con el modelo en caché).
READY_TIMEOUT_S: Final = 30.0
#: Todas las capas del modelo en la GPU.
N_GPU_LAYERS: Final = 99
#: Contexto por hueco: el *prompt* final de S2 llega a ~1 100 tokens.
CONTEXT_SIZE: Final = 4096
#: Tiempo máximo de cada comprobación de salud: con la GPU ocupada por otros procesos, una respuesta
#: lenta no debe contar como fallo (un fallo gasta el único reinicio de la sesión).
HEALTH_PROBE_TIMEOUT_S: Final = 3.0


def find_free_port() -> int:
    """Un puerto TCP libre en 127.0.0.1 (el sistema lo asigna; otro proceso podría tomarlo luego)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def llama_server_exe() -> Path:
    """Ruta de ``llama-server.exe``: ``component_dir("llama-cpp") / "llama-server.exe"``."""
    return component_dir("llama-cpp") / EXE_NAME


class LlamaServerProcess:
    """``llama-server`` con un modelo GGUF, como proceso hijo gestionado por ``ManagedChild``.

    Parámetros:

    - ``model_path``: el GGUF (``mt.selection.model_path(...)``).
    - ``executable``: comando que sustituye a ``llama-server.exe``; los argumentos de ``llama-server``
      se añaden a continuación. Solo se cambia en los tests (por ejemplo ``[sys.executable, "falso.py"]``).
    - ``port``: puerto fijo; por defecto se elige uno libre.
    - ``ready_timeout_s``: tiempo máximo hasta que ``/health`` devuelve 200.
    - ``health_interval_s``: cada cuánto se comprueba la salud una vez listo.
    - ``on_failure``: ``callback(servidor, motivo)``, llamado una sola vez por fallo desde el hilo de salud.
      No se llama si el servidor se detiene a propósito.
    - ``extra_args``: argumentos añadidos al final de la línea de comandos.
    """

    def __init__(
        self,
        model_path: str | os.PathLike[str],
        *,
        executable: Sequence[str | os.PathLike[str]] | None = None,
        port: int | None = None,
        ready_timeout_s: float = READY_TIMEOUT_S,
        health_interval_s: float = HEALTH_INTERVAL_S,
        on_failure: Callable[[LlamaServerProcess, str], None] | None = None,
        extra_args: Sequence[str] = (),
    ) -> None:
        self.model_path = Path(model_path)
        self._default_executable = executable is None
        self._executable = (llama_server_exe(),) if executable is None else tuple(executable)
        if not self._executable:
            raise ValueError("executable no puede estar vacío.")
        self.port = find_free_port() if port is None else port
        self._on_failure = on_failure
        self._extra_args = tuple(extra_args)
        self._child = ManagedChild(
            self.command(),
            ready=ReadyHttpHealth(f"{self.base_url}/health", timeout_s=ready_timeout_s),
            health=HealthCheck(
                interval_s=health_interval_s, probe=self._probe, on_failure=self._child_failed
            ),
            graceful_stop=None,  # llama-server no tiene parada ordenada: se mata directamente
            cwd=Path(os.fspath(self._executable[0])).parent,  # las DLL de CUDA están junto al .exe
            name=ENGINE,
        )

    def __repr__(self) -> str:
        return f"LlamaServerProcess(model={self.model_path.name!r}, port={self.port}, pid={self.pid})"

    # -- datos ---------------------------------------------------------------
    @property
    def base_url(self) -> str:
        """URL base de la API (``/health``, ``/v1/chat/completions``...)."""
        return f"http://{HOST}:{self.port}"

    @property
    def child(self) -> ManagedChild:
        """El ``ManagedChild`` subyacente, para ``stop_all([...])`` con el resto de hijos."""
        return self._child

    @property
    def pid(self) -> int | None:
        return self._child.pid

    def is_alive(self) -> bool:
        return self._child.is_alive()

    def output_tail(self, lines: int = 40) -> str:
        """Las últimas líneas que escribió ``llama-server`` (útil en los avisos de fallo)."""
        return self._child.output_tail(lines)

    def command(self) -> list[str]:
        """Línea de comandos completa con la que se lanza el servidor."""
        return [
            *(os.fspath(part) for part in self._executable),
            "-m",
            str(self.model_path),
            "--host",
            HOST,
            "--port",
            str(self.port),
            "-ngl",
            str(N_GPU_LAYERS),
            "-c",
            str(CONTEXT_SIZE),
            "-np",
            "1",  # un solo hueco: es el uso real y deja los 4 096 de contexto enteros
            "-fit",
            "off",  # sin autoajuste: lo que se pide es lo que se carga
            "--no-webui",
            "--cache-ram",
            "0",  # acota la RAM del servidor sin coste de latencia (S2)
            *self._extra_args,
        ]

    # -- ciclo de vida -------------------------------------------------------
    def start(self) -> None:
        """Lanza el proceso sin esperar a que esté listo (ver ``wait_ready``).

        Lanza ``EngineError(recoverable=False)`` si faltan el ejecutable o el modelo (hay que ejecutar
        ``preparar``) o si el sistema no puede lanzar el proceso.
        """
        if self._default_executable and not Path(self._executable[0]).is_file():
            raise EngineError(
                f"Falta {self._executable[0]}: ejecuta «instanttraductor preparar».",
                engine=ENGINE,
                recoverable=False,
            )
        if not self.model_path.is_file():
            raise EngineError(
                f"Falta el modelo {self.model_path}: ejecuta «instanttraductor preparar».",
                engine=ENGINE,
                recoverable=False,
            )
        try:
            self._child.start()
        except OSError as error:
            raise EngineError(
                f"No se pudo lanzar llama-server: {error}", engine=ENGINE, recoverable=False
            ) from error

    def wait_ready(self) -> None:
        """Espera a que ``GET /health`` devuelva 200 (en ``ready_timeout_s``) y arranca la salud.

        Si el proceso muere o no queda listo a tiempo, ya está terminado y se lanza
        ``EngineError(recoverable=False)`` con las últimas líneas que escribió.
        """
        try:
            self._child.wait_ready()
        except ChildError as error:
            raise EngineError(str(error), engine=ENGINE, recoverable=False) from error

    def restart_once(self) -> bool:
        """Reinicia el servidor como máximo una vez por sesión, en el mismo puerto.

        Devuelve ``True`` si el nuevo proceso está listo y ``False`` si el reinicio ya se gastó, si se
        pidió parar o si no quedó listo.
        """
        return self._child.restart_once()

    def stop(self, grace_s: float = 1.0) -> None:
        """Para el servidor (idempotente). Para varios hijos a la vez, usa ``stop_all`` con ``child``."""
        self._child.stop(grace_s)

    # -- salud ---------------------------------------------------------------
    def _probe(self, child: ManagedChild) -> bool:
        return http_get_ok(f"{self.base_url}/health", timeout_s=HEALTH_PROBE_TIMEOUT_S)

    def _child_failed(self, child: ManagedChild, reason: str) -> None:
        if self._on_failure is not None:
            self._on_failure(self, reason)
