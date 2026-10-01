"""Servidor HTTP local del servicio de voz (T025): la API exacta de ``contracts/tts-service.md``.

Arranque::

    uv run --project engines/tts-qwen3 tts-service --host 127.0.0.1 --port 0 \\
        --voices-dir <ruta> --models-dir <ruta>

- Escucha solo en ``127.0.0.1``. Con ``--port 0`` el sistema elige un puerto libre.
- Abre el puerto enseguida y carga el motor en segundo plano: hasta que está listo, todo responde ``503``.
- Cuando el motor está cargado (modelo, voces y calentamiento) y el servidor ya acepta conexiones, escribe
  **una línea JSON** en ``stdout`` y la vacía::

      {"event": "ready", "port": 51234, "sample_rate": 24000, "engine": "qwen3-tts", "supports_speed": false}

  El resto de ``stdout`` se desvía a ``stderr`` mientras carga (las bibliotecas de CUDA imprimen ahí).
- Los errores de arranque salen por ``stderr`` con un código de salida distinto de 0.

Endpoints: ``GET /health``, ``GET /voices``, ``POST /synthesize`` (PCM ``float32`` little-endian mono en
*streaming*, con la cabecera ``X-Sample-Rate``) y ``POST /shutdown``. Los errores son JSON ``{"error": str}``.

Todo el trabajo del motor (carga, calentamiento y cada síntesis) lo hace **un único hilo** (``EngineHost``):
los CUDA graphs tienen buffers estáticos, así que no admiten dos síntesis a la vez, y capturarlos y
reproducirlos en el mismo hilo evita sorpresas. Las peticiones esperan su turno en orden de llegada.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import socket
import sys
import threading
import traceback
from collections.abc import AsyncIterator, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import numpy as np
import numpy.typing as npt
import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from tts_service.engine import (
    CHUNK_SIZE,
    Engine,
    EngineLoadError,
    ServiceConfig,
    load_engine,
)

__all__ = [
    "HOST",
    "MAX_SPEED",
    "MAX_TEXT_CHARS",
    "MIN_SPEED",
    "EngineHost",
    "SynthesizeBody",
    "create_app",
    "main",
]

logger = logging.getLogger(__name__)

Samples = npt.NDArray[np.float32]
EngineFactory = Callable[[ServiceConfig], Engine]

#: El servicio escucha solo en el bucle local.
HOST: Final = "127.0.0.1"
#: Límites de ``POST /synthesize`` (contracts/tts-service.md).
MAX_TEXT_CHARS: Final = 1000
MIN_SPEED: Final = 1.0
MAX_SPEED: Final = 1.5
#: Espera máxima a que terminen las peticiones en curso al parar (el contrato pide parar en <= 2 s).
SHUTDOWN_GRACE_S: Final = 1
#: Tiempo máximo para que el motor suelte la GPU al parar.
ENGINE_CLOSE_TIMEOUT_S: Final = 1.0
KEEP_ALIVE_S: Final = 60


# ---------------------------------------------------------------------------
# El motor y su hilo
# ---------------------------------------------------------------------------
class EngineHost:
    """Dueño del motor: un hilo propio carga el motor y hace todas las síntesis, una cada vez, en orden.

    ``engine`` es ``None`` mientras carga o si la carga falló (entonces ``error`` dice por qué); ``loaded`` se
    activa al terminar la carga, bien o mal. ``factory`` se ejecuta en el hilo del motor, con ``stdout``
    desviado a ``stderr`` (las bibliotecas de CUDA imprimen por ``stdout`` y ahí solo va la línea ``ready``).
    """

    def __init__(self, factory: Callable[[], Engine]) -> None:
        self._factory = factory
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts-engine")
        self._engine: Engine | None = None
        self.error: Exception | None = None
        self.loaded = threading.Event()

    @property
    def engine(self) -> Engine | None:
        return self._engine

    def start(self) -> None:
        """Empieza a cargar el motor en su hilo (no espera: ver ``loaded``)."""
        self._executor.submit(self._load)

    def _load(self) -> None:
        try:
            with contextlib.redirect_stdout(sys.stderr):
                self._engine = self._factory()
        except Exception as error:
            self.error = error
        finally:
            self.loaded.set()

    def submit(self, job: Callable[[], None]) -> None:
        """Pone un trabajo en la cola del hilo del motor. Lanza ``RuntimeError`` si ya se cerró."""
        self._executor.submit(job)

    def close(self, timeout_s: float = ENGINE_CLOSE_TIMEOUT_S) -> None:
        """Deja de aceptar trabajo, suelta el motor (hasta ``timeout_s``) y para el hilo. Es idempotente."""
        engine, self._engine = self._engine, None
        released = threading.Event()

        def release() -> None:
            try:
                if engine is not None:
                    engine.close()
            finally:
                released.set()

        try:
            self._executor.submit(release)
        except RuntimeError:  # ya cerrado
            return
        released.wait(timeout_s)
        self._executor.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class SynthesizeBody(BaseModel):
    """Cuerpo de ``POST /synthesize``. Los límites los comprueba el *endpoint* (``400`` con ``{"error"}``)."""

    text: str
    voice_id: str
    speed: float = 1.0


@dataclass(frozen=True, slots=True)
class _Item:
    """Lo que el hilo del motor entrega a la petición: un trozo de audio, el final o un error."""

    kind: Literal["audio", "end", "error"]
    data: bytes = b""
    error: Exception | None = None


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _not_ready(host: EngineHost) -> JSONResponse:
    if host.error is not None:
        return _error(503, f"El motor no ha podido arrancar: {host.error}")
    return _error(503, "El modelo aún no está listo.")


#: Los motivos de validación más habituales de pydantic, en español (el resto se deja como viene).
_VALIDATION_REASONS: Final = {
    "missing": "es obligatorio",
    "string_type": "debe ser un texto",
    "float_type": "debe ser un número",
    "float_parsing": "debe ser un número",
}


def _validation_message(error: RequestValidationError) -> str:
    details = []
    for item in error.errors():
        if item.get("type") == "json_invalid":
            details.append("el cuerpo no es un JSON válido")
            continue
        place = ".".join(str(part) for part in item.get("loc", ()) if part != "body")
        reason = _VALIDATION_REASONS.get(item.get("type", ""), str(item.get("msg", "no válido")))
        details.append(f"{place} {reason}" if place else reason)
    return "Petición no válida: " + "; ".join(details) + "."


def _pcm_bytes(samples: npt.ArrayLike) -> bytes:
    """PCM ``float32`` little-endian mono, finito y dentro de [-1, 1] (el contrato de audio del núcleo)."""
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    if x.size and not np.isfinite(x).all():
        x = np.nan_to_num(x, nan=0.0, posinf=1.0, neginf=-1.0)
    return np.clip(x, -1.0, 1.0).astype("<f4", copy=False).tobytes()


def _deliver(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[_Item], item: _Item) -> None:
    """Pasa un ``_Item`` del hilo del motor al bucle de eventos."""
    with contextlib.suppress(RuntimeError):  # el bucle ya se cerró: el servidor está parando
        loop.call_soon_threadsafe(queue.put_nowait, item)


def _run_synthesis(
    engine: Engine,
    text: str,
    voice_id: str,
    speed: float,
    deliver: Callable[[_Item], None],
    cancelled: threading.Event,
) -> None:
    """En el hilo del motor: genera el audio y lo entrega trozo a trozo, hasta el final o hasta cancelarlo."""
    stream = None
    try:
        if not cancelled.is_set():
            stream = iter(engine.synthesize(text, voice_id, speed))
            for samples in stream:
                if cancelled.is_set():
                    break
                data = _pcm_bytes(samples)
                if data:
                    deliver(_Item("audio", data))
        deliver(_Item("end"))
    except Exception as error:
        logger.exception("Error del motor al sintetizar")
        deliver(_Item("error", error=error))
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            with contextlib.suppress(Exception):
                close()


def create_app(host: EngineHost, *, request_shutdown: Callable[[], None] | None = None) -> FastAPI:
    """La aplicación FastAPI del servicio. ``request_shutdown`` es lo que hace ``POST /shutdown``."""
    app = FastAPI(
        title="Servicio de voz de InstantTraductor", docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: object, error: RequestValidationError) -> JSONResponse:
        return _error(400, _validation_message(error))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: object, error: StarletteHTTPException) -> JSONResponse:
        return _error(error.status_code, str(error.detail))

    @app.get("/health", response_model=None)
    async def health() -> Response:
        engine = host.engine
        if engine is None:
            return _not_ready(host)
        try:
            vram_mb = int(engine.vram_mb())
        except Exception:
            vram_mb = 0
        return JSONResponse(
            {
                "status": "ok",
                "engine": engine.name,
                "model": engine.model_name,
                "sample_rate": engine.sample_rate,
                "supports_speed": engine.supports_speed,
                "vram_mb": vram_mb,
            }
        )

    @app.get("/voices", response_model=None)
    async def voices() -> Response:
        engine = host.engine
        if engine is None:
            return _not_ready(host)
        return JSONResponse([voice.public() for voice in engine.voices()])

    @app.post("/synthesize", response_model=None)
    async def synthesize(body: SynthesizeBody) -> Response:
        engine = host.engine
        if engine is None:
            return _not_ready(host)
        if len(body.text) > MAX_TEXT_CHARS:
            return _error(
                400, f"El texto no puede pasar de {MAX_TEXT_CHARS} caracteres (recibidos {len(body.text)})."
            )
        text = body.text.strip()
        if not text:
            return _error(400, "El texto está vacío.")
        if not MIN_SPEED <= body.speed <= MAX_SPEED:  # también falso para NaN
            return _error(
                400, f"speed debe estar entre {MIN_SPEED:g} y {MAX_SPEED:g} (recibido {body.speed})."
            )
        if body.voice_id not in {voice.voice_id for voice in engine.voices()}:
            return _error(400, f"voice_id desconocido: {body.voice_id!r}.")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[_Item] = asyncio.Queue()
        cancelled = threading.Event()

        def job() -> None:
            _run_synthesis(
                engine, text, body.voice_id, body.speed, lambda item: _deliver(loop, queue, item), cancelled
            )

        try:
            host.submit(job)
        except RuntimeError:
            return _error(503, "El servicio se está cerrando.")
        try:
            first = await queue.get()
        except BaseException:  # petición cancelada mientras esperaba su turno
            cancelled.set()
            raise
        if first.kind == "error":
            return _error(500, str(first.error) or type(first.error).__name__)
        if first.kind == "end":
            return _error(500, "El motor no generó audio.")

        async def audio() -> AsyncIterator[bytes]:
            item = first
            try:
                while item.kind == "audio":
                    yield item.data
                    item = await queue.get()
                if item.kind == "error" and item.error is not None:
                    raise item.error  # a mitad de respuesta: se corta la conexión y el cliente lo nota
            finally:
                cancelled.set()  # cliente desconectado o audio completo: que el motor no siga de más

        return StreamingResponse(
            audio(),
            media_type="application/octet-stream",
            headers={"X-Sample-Rate": str(engine.sample_rate)},
        )

    @app.post("/shutdown", status_code=202, response_model=None)
    async def shutdown() -> Response:
        if request_shutdown is not None:
            request_shutdown()
        return JSONResponse({"status": "stopping"}, status_code=202)

    return app


# ---------------------------------------------------------------------------
# Proceso
# ---------------------------------------------------------------------------
class _Server(uvicorn.Server):
    """``uvicorn.Server`` que avisa cuando ya acepta conexiones (el momento de la línea ``ready``)."""

    def __init__(self, config: uvicorn.Config, on_started: Callable[[], None]) -> None:
        super().__init__(config)
        self._on_started = on_started

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            self._on_started()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tts-service", description="Servicio local de voz de InstantTraductor (Qwen3-TTS)."
    )
    parser.add_argument("--host", default=HOST, help=f"Dirección de escucha: solo se admite {HOST}.")
    parser.add_argument(
        "--port", type=int, default=0, help="Puerto; 0 (por defecto) = uno libre que elige el sistema."
    )
    parser.add_argument(
        "--voices-dir", type=Path, required=True, help="Carpeta con <voice_id>.wav y <voice_id>.json."
    )
    parser.add_argument(
        "--models-dir", type=Path, required=True, help="Carpeta de modelos (con qwen3-tts-12hz-0.6b-base)."
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Pasos de códec por trozo de audio (1 paso = 83 ms; por defecto {CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--x-vector-only",
        action="store_true",
        help="Rescate: clona las voces solo con el embedding del hablante, sin el modo ICL.",
    )
    args = parser.parse_args(argv)
    if args.host != HOST:
        parser.error(f"el servicio solo escucha en {HOST} (recibido {args.host!r})")
    if not 0 <= args.port <= 65535:
        parser.error(f"--port debe estar entre 0 y 65535 (recibido {args.port})")
    if not 1 <= args.chunk_size <= 12:
        parser.error(f"--chunk-size debe estar entre 1 y 12 (recibido {args.chunk_size})")
    return args


def _use_utf8(stream: object) -> None:
    """``stdout`` y ``stderr`` en UTF-8: el núcleo los lee así (por defecto Windows usaría la página ANSI)."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        with contextlib.suppress(Exception):
            reconfigure(encoding="utf-8", errors="replace")


def _bind(host: str, port: int) -> socket.socket:
    """Abre el puerto ya (con ``port=0``, uno libre) para conocerlo antes de cargar el motor."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


def _report_startup_error(error: BaseException) -> None:
    """El error de arranque por ``stderr``; un fallo inesperado, con su traza."""
    print(f"error de arranque: {error}", file=sys.stderr, flush=True)
    if not isinstance(error, EngineLoadError):
        traceback.print_exception(error, file=sys.stderr)
        sys.stderr.flush()


def _announce(host: EngineHost, server: _Server, started: threading.Event, port: int) -> None:
    """Espera a que el motor esté cargado y el servidor acepte conexiones y escribe la línea ``ready``."""
    host.loaded.wait()
    engine = host.engine
    if engine is None:
        _report_startup_error(host.error if host.error is not None else RuntimeError("el motor no cargó"))
        server.should_exit = True
        return
    while not started.wait(0.05):
        if server.should_exit:
            return
    line = {
        "event": "ready",
        "port": port,
        "sample_rate": engine.sample_rate,
        "engine": engine.name,
        "supports_speed": engine.supports_speed,
    }
    with contextlib.suppress(OSError, ValueError):  # el núcleo ya no lee: nadie que avisar
        sys.stdout.write(json.dumps(line) + "\n")
        sys.stdout.flush()


def main(argv: Sequence[str] | None = None, *, engine_factory: EngineFactory | None = None) -> int:
    """Punto de entrada del servicio (``tts-service``). Devuelve el código de salida.

    ``engine_factory`` sustituye a la carga de Qwen3-TTS (los tests pasan un motor falso). Con el motor real,
    al terminar se sale con ``os._exit``: el contrato pide parar en <= 2 s y descargar torch y CUDA tarda más.
    """
    args = _parse_args(argv)
    _use_utf8(sys.stdout)
    _use_utf8(sys.stderr)
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = ServiceConfig(
        voices_dir=args.voices_dir,
        models_dir=args.models_dir,
        chunk_size=args.chunk_size,
        x_vector_only=args.x_vector_only,
    )
    factory = load_engine if engine_factory is None else engine_factory

    try:
        sock = _bind(args.host, args.port)
    except OSError as error:
        print(
            f"error de arranque: no se pudo abrir {args.host}:{args.port} ({error})",
            file=sys.stderr,
            flush=True,
        )
        return _finish(1, hard=engine_factory is None)
    port = int(sock.getsockname()[1])

    host = EngineHost(lambda: factory(config))
    started = threading.Event()

    def request_shutdown() -> None:
        server.should_exit = True

    server = _Server(
        uvicorn.Config(
            create_app(host, request_shutdown=request_shutdown),
            host=args.host,
            port=port,
            loop="asyncio",
            http="h11",
            ws="none",
            lifespan="off",
            log_level="warning",
            access_log=False,
            timeout_keep_alive=KEEP_ALIVE_S,
            timeout_graceful_shutdown=SHUTDOWN_GRACE_S,
        ),
        on_started=started.set,
    )
    host.start()
    threading.Thread(
        target=_announce, args=(host, server, started, port), name="tts-ready", daemon=True
    ).start()

    code = 0
    try:
        server.run(sockets=[sock])
    except SystemExit as exit_:  # uvicorn sale así si no puede arrancar
        code = exit_.code if isinstance(exit_.code, int) else 1
    except KeyboardInterrupt:  # Ctrl+C a mano: uvicorn ya paró con orden y relanza la señal
        pass
    except Exception as error:
        _report_startup_error(error)
        code = 1
    finally:
        host.close()
        with contextlib.suppress(OSError):  # uvicorn ya lo cierra al parar; aquí, si no llegó a arrancar
            sock.close()
    if host.error is not None:
        code = code or 1
    return _finish(code, hard=engine_factory is None)


def _finish(code: int, *, hard: bool) -> int:
    if hard:
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                stream.flush()
        os._exit(code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
