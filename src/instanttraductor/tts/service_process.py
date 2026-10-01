"""El servicio de voz como proceso hijo gestionado (T026, research R8 y R10, FR-018 y FR-027).

``TtsServiceProcess`` lanza el servicio de voz (``engines/tts-qwen3``, con su propio entorno de uv:
ADR-0004) con ``ManagedChild``::

    uv run --frozen --offline --project engines/tts-qwen3 tts-service \\
        --host 127.0.0.1 --port 0 --voices-dir <AppPaths.voices> --models-dir <AppPaths.models>

- ``--frozen --offline`` y las variables ``HF_HUB_OFFLINE=1`` y ``TRANSFORMERS_OFFLINE=1``: sin red tras la
  preparación (FR-027).
- ``--port 0``: el sistema elige un puerto libre y el servicio lo anuncia en su línea ``ready``
  (``{"event": "ready", "port": ..., "sample_rate": 24000, "engine": "qwen3-tts", "supports_speed": false}``).
  Está listo cuando escribe esa línea, en 120 s como máximo (carga del modelo y las voces, y calentamiento).
- Salud cada 2 s con ``GET /health``; si falla, avisa por ``on_failure(servicio, motivo)`` (una sola vez por
  fallo) y quien lo recibe decide: ``restart_once()`` (el puerto cambia, pero ``base_url`` y el sintetizador
  siguen al proceso nuevo) o parada limpia.
- Parada ordenada con ``POST /shutdown``; si no sale a tiempo, ``stop_all`` cierra el *Job Object* (R10).

Uso::

    voice = TtsServiceProcess(on_failure=handle_failure)
    voice.start()                         # lanza el proceso
    info = voice.wait_ready()             # EngineError(recoverable=False) si no llega la línea ready
    synthesizer = voice.synthesizer()     # HttpSynthesizer con lo que dijo la línea ready
    ...
    synthesizer.close()
    stop_all([voice.child, ...])          # parada en paralelo con el resto de hijos
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import httpx

from instanttraductor.config import AppPaths
from instanttraductor.contracts import EngineError
from instanttraductor.platform.children import (
    HEALTH_INTERVAL_S,
    ChildError,
    HealthCheck,
    ManagedChild,
    ReadyJsonLine,
    http_get_ok,
)
from instanttraductor.tts.http_client import HttpSynthesizer

__all__ = [
    "ENGINE",
    "HOST",
    "OFFLINE_ENV",
    "READY_TIMEOUT_S",
    "TtsServiceInfo",
    "TtsServiceProcess",
    "engine_project_dir",
]

logger = logging.getLogger(__name__)

#: Nombre con el que los errores de este módulo identifican al servicio (``EngineError.engine``).
ENGINE: Final = "tts-service"
#: Solo el bucle local: el servicio no se expone fuera del equipo.
HOST: Final = "127.0.0.1"
#: Tiempo máximo hasta la línea ``ready`` (contracts/tts-service.md).
READY_TIMEOUT_S: Final = 120.0
#: Tiempo máximo de cada comprobación de salud: con la GPU y la CPU ocupadas por otros procesos, una respuesta
#: lenta no debe contar como fallo (un fallo gasta el único reinicio de la sesión).
HEALTH_PROBE_TIMEOUT_S: Final = 3.0
#: Sin red tras la preparación (FR-027): ni Hugging Face ni transformers salen a internet.
OFFLINE_ENV: Final[Mapping[str, str]] = MappingProxyType({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})

# En Windows una conexión rechazada tarda 1-2 s en fallar: la parada ordenada usa tiempos cortos.
_SHUTDOWN_TIMEOUT: Final = httpx.Timeout(0.5, connect=0.25)


def engine_project_dir() -> Path:
    """``engines/tts-qwen3`` del repositorio: el proyecto uv del servicio de voz (ADR-0004)."""
    return Path(__file__).resolve().parents[3] / "engines" / "tts-qwen3"


@dataclass(frozen=True, slots=True)
class TtsServiceInfo:
    """Lo que el servicio dice de sí mismo en su línea ``ready``."""

    port: int
    sample_rate: int
    engine: str
    supports_speed: bool

    @classmethod
    def from_ready(cls, message: Mapping[str, Any] | None) -> TtsServiceInfo:
        """Lee y valida la línea ``ready``. Lanza ``EngineError(recoverable=False)`` si no es válida."""
        if not message:
            raise EngineError(
                "El servicio de voz aún no está listo (no ha escrito la línea «ready»).",
                engine=ENGINE,
                recoverable=False,
            )

        def invalid(key: str) -> EngineError:
            return EngineError(
                f"La línea «ready» del servicio de voz no es válida: «{key}» = {message.get(key)!r} "
                f"(recibida: {dict(message)}).",
                engine=ENGINE,
                recoverable=False,
            )

        port = message.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 0 < port < 65536:
            raise invalid("port")
        sample_rate = message.get("sample_rate")
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            raise invalid("sample_rate")
        engine = message.get("engine")
        if not isinstance(engine, str) or not engine.strip():
            raise invalid("engine")
        supports_speed = message.get("supports_speed")
        if not isinstance(supports_speed, bool):
            raise invalid("supports_speed")
        return cls(port=port, sample_rate=sample_rate, engine=engine, supports_speed=supports_speed)


class TtsServiceProcess:
    """El servicio de voz como proceso hijo: ``uv run`` con el entorno del motor y la línea ``ready``.

    Parámetros:

    - ``voices_dir`` y ``models_dir``: por defecto, ``AppPaths().voices`` y ``AppPaths().models``.
    - ``project_dir``: el proyecto uv del motor; por defecto, ``engines/tts-qwen3`` del repositorio.
    - ``executable``: comando que sustituye al prefijo ``uv run --frozen --offline --project ...
      tts-service``; las opciones del servicio se añaden a continuación. Solo se cambia en los tests
      (por ejemplo ``[sys.executable, "falso.py"]``).
    - ``ready_timeout_s``: tiempo máximo hasta la línea ``ready``. ``health_interval_s``: cada cuánto se
      comprueba la salud una vez listo.
    - ``on_failure``: ``callback(servicio, motivo)``, llamado una sola vez por fallo desde el hilo de
      salud. No se llama si el servicio se detiene a propósito.
    - ``extra_args``: opciones añadidas al final de la línea de comandos (``--chunk-size``,
      ``--x-vector-only``).
    """

    def __init__(
        self,
        *,
        voices_dir: str | os.PathLike[str] | None = None,
        models_dir: str | os.PathLike[str] | None = None,
        project_dir: str | os.PathLike[str] | None = None,
        executable: Sequence[str | os.PathLike[str]] | None = None,
        ready_timeout_s: float = READY_TIMEOUT_S,
        health_interval_s: float = HEALTH_INTERVAL_S,
        on_failure: Callable[[TtsServiceProcess, str], None] | None = None,
        extra_args: Sequence[str] = (),
    ) -> None:
        paths = AppPaths()
        self.voices_dir = Path(voices_dir) if voices_dir is not None else paths.voices
        self.models_dir = Path(models_dir) if models_dir is not None else paths.models
        self.project_dir = Path(project_dir) if project_dir is not None else engine_project_dir()
        self._executable = None if executable is None else tuple(executable)
        if self._executable is not None and not self._executable:
            raise ValueError("executable no puede estar vacío.")
        self._on_failure = on_failure
        self._extra_args = tuple(extra_args)
        self._child = ManagedChild(
            self.command(),
            ready=ReadyJsonLine(timeout_s=ready_timeout_s),
            env=OFFLINE_ENV,
            health=HealthCheck(
                interval_s=health_interval_s, probe=self._probe, on_failure=self._child_failed
            ),
            graceful_stop=self._graceful_stop,
            name=ENGINE,
        )

    def __repr__(self) -> str:
        return f"TtsServiceProcess(voices={str(self.voices_dir)!r}, pid={self.pid})"

    # -- datos ---------------------------------------------------------------------------------------
    @property
    def child(self) -> ManagedChild:
        """El ``ManagedChild`` subyacente, para ``stop_all([...])`` con el resto de hijos."""
        return self._child

    @property
    def pid(self) -> int | None:
        return self._child.pid

    @property
    def info(self) -> TtsServiceInfo:
        """Lo que dijo la línea ``ready`` (la del proceso vigente: cambia si se reinicia)."""
        return TtsServiceInfo.from_ready(self._child.ready_info)

    @property
    def base_url(self) -> str:
        """``http://127.0.0.1:<puerto>`` del proceso vigente. ``EngineError`` si aún no está listo."""
        return f"http://{HOST}:{self.info.port}"

    def is_alive(self) -> bool:
        return self._child.is_alive()

    def output_tail(self, lines: int = 40) -> str:
        """Las últimas líneas que escribió el servicio por ``stdout`` y ``stderr`` (útil en los avisos)."""
        return self._child.output_tail(lines)

    def command(self) -> list[str]:
        """Línea de comandos completa con la que se lanza el servicio."""
        if self._executable is None:
            prefix: Sequence[str | os.PathLike[str]] = (
                shutil.which("uv") or "uv",
                "run",
                "--frozen",
                "--offline",
                "--project",
                self.project_dir,
                "tts-service",
            )
        else:
            prefix = self._executable
        return [
            *(os.fspath(part) for part in prefix),
            "--host",
            HOST,
            "--port",
            "0",
            "--voices-dir",
            str(self.voices_dir),
            "--models-dir",
            str(self.models_dir),
            *self._extra_args,
        ]

    # -- ciclo de vida -----------------------------------------------------------------------------------
    def start(self) -> None:
        """Lanza el proceso sin esperar a que esté listo (ver ``wait_ready``).

        Lanza ``EngineError(recoverable=False)`` si falta uv o el proyecto del motor, o si el sistema no puede
        lanzar el proceso.
        """
        if self._executable is None:
            if shutil.which("uv") is None:
                raise EngineError(
                    "Falta uv en el PATH: hace falta para lanzar el servicio de voz.",
                    engine=ENGINE,
                    recoverable=False,
                )
            if not (self.project_dir / "pyproject.toml").is_file():
                raise EngineError(
                    f"Falta el proyecto del servicio de voz (engines/tts-qwen3) en {self.project_dir}.",
                    engine=ENGINE,
                    recoverable=False,
                )
        try:
            self._child.start()
        except OSError as error:
            raise EngineError(
                f"No se pudo lanzar el servicio de voz: {error}", engine=ENGINE, recoverable=False
            ) from error

    def wait_ready(self) -> TtsServiceInfo:
        """Espera la línea ``ready`` (en ``ready_timeout_s``) y arranca la salud periódica.

        Devuelve lo que dice la línea. Si el proceso muere o no queda listo a tiempo, ya está terminado y se
        lanza ``EngineError(recoverable=False)`` con las últimas líneas que escribió; igual si la línea
        ``ready`` no es válida (entonces se termina el proceso).
        """
        try:
            ready = self._child.wait_ready()
        except ChildError as error:
            raise EngineError(str(error), engine=ENGINE, recoverable=False) from error
        try:
            return TtsServiceInfo.from_ready(ready)
        except EngineError:
            self._child.stop(grace_s=0.0)  # no se deja en marcha un servicio del que no se sabe nada
            raise

    def synthesizer(self, **kwargs: Any) -> HttpSynthesizer:
        """Un ``HttpSynthesizer`` de este servicio, con el nombre, la frecuencia y ``supports_speed`` de la
        línea ``ready``. Sigue al proceso si se reinicia (lee el puerto vigente en cada petición).

        ``kwargs``: ``timeout_s`` y ``transport`` de ``HttpSynthesizer``. ``EngineError`` si no está listo.
        """
        info = self.info
        return HttpSynthesizer(
            lambda: self.base_url,
            name=info.engine,
            sample_rate=info.sample_rate,
            supports_speed=info.supports_speed,
            **kwargs,
        )

    def restart_once(self) -> bool:
        """Reinicia el servicio como máximo una vez por sesión; el puerto del proceso nuevo puede ser otro.

        Devuelve ``True`` si el nuevo proceso está listo y ``False`` si el reinicio ya se gastó, si se pidió
        parar o si no quedó listo.
        """
        return self._child.restart_once()

    def stop(self, grace_s: float = 1.0) -> None:
        """Para el servicio con ``POST /shutdown`` (idempotente). Para varios hijos a la vez: ``stop_all``."""
        self._child.stop(grace_s)

    # -- salud y parada ------------------------------------------------------------------------------------
    def _probe(self, child: ManagedChild) -> bool:
        return http_get_ok(f"{self.base_url}/health", timeout_s=HEALTH_PROBE_TIMEOUT_S)

    def _child_failed(self, child: ManagedChild, reason: str) -> None:
        if self._on_failure is not None:
            self._on_failure(self, reason)

    def _graceful_stop(self, child: ManagedChild) -> None:
        info = child.ready_info
        port = info.get("port") if info else None
        if not isinstance(port, int):
            return  # aún no estaba listo: no hay a quién pedírselo; la parada lo mata
        httpx.post(f"http://{HOST}:{port}/shutdown", timeout=_SHUTDOWN_TIMEOUT, trust_env=False)
