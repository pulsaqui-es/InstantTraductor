"""Fuente de audio desde un fichero: `FileSource` (T035), la entrada del modo archivo.

Implementa `AudioSource` (16 kHz, mono, float32, chunks contiguos de 20 ms) con `ffmpeg` por tubería:
`ffmpeg -map 0:a:0 -vn -sn -dn -ac 1 -ar 16000 -f f32le -`. Vale para cualquier audio o vídeo que lea
ffmpeg (WAV, MP3, MP4, MKV...): solo se decodifica la primera pista de audio.

Ritmo
-----
Con `realtime=True` (lo normal) la fuente se comporta como la captura en directo, para que las métricas del
modo archivo sean comparables con las del modo directo (FR-021): un hilo productor entrega cada chunk
cuando `clock.now() >= origen + t_end`, donde el origen es `clock.now()` al entrar en `start()`. Si el
arranque de ffmpeg tarda, los primeros chunks salen de golpe hasta alcanzar el ritmo (el audio nunca se
desplaza). Con `realtime=False` los chunks salen lo más rápido posible (con una cola acotada), para los
tests y para quien solo quiera decodificar.

`arrival_time(t)` da el instante de reloj de sesión en que llegó el chunk que contiene el instante de audio
`t`, igual que `ProcessLoopbackSource.arrival_time`: se registra antes de encolar el chunk.

Validación
----------
`probe_input(path)` valida el fichero con `ffprobe` SIN arrancar el ritmo real y lanza `InputFileError` si
no existe, está dañado o no tiene audio; el orquestador (`FileSession`) la llama antes de arrancar los
motores. `FileSource.start()` vuelve a validar (con `ffprobe` y con la primera lectura de ffmpeg, que
atrapa los ficheros con cabecera buena y datos rotos) y no vuelve hasta tener el primer chunk listo.
Sin ffmpeg, `EngineError(recoverable=False)`.
"""

from __future__ import annotations

import bisect
import contextlib
import json
import logging
import shutil
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Final

import numpy as np

from instanttraductor.config import ffmpeg_path
from instanttraductor.contracts import CAPTURE_RATE, AudioChunk, Clock, EngineError

logger = logging.getLogger(__name__)

__all__ = ["ENGINE_NAME", "FileSource", "InputFileError", "InputInfo", "ffprobe_path", "probe_input"]

ENGINE_NAME: Final = "audio-file"

DEFAULT_CHUNK_S: Final = 0.02
_BYTES_PER_SAMPLE: Final = 4  # f32le
_PROBE_TIMEOUT_S: Final = 30.0
_FIRST_CHUNK_TIMEOUT_S: Final = 60.0
_POLL_S: Final = 0.01  # tope de espera del productor: el reloj puede ser manual y no avisar
_MAX_QUEUED_CHUNKS: Final = 500  # 10 s: con `realtime=False` el productor no se come la memoria
_NO_WINDOW: Final = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class InputFileError(Exception):
    """El fichero de entrada no existe, está dañado, no es admitido o no tiene audio (código de salida 5)."""


@dataclass(frozen=True, slots=True)
class InputInfo:
    """Lo que `probe_input` averigua del fichero de entrada."""

    duration_s: float | None  # None si no se pudo medir (sin ffprobe o sin duración en el contenedor)
    has_video: bool


def ffprobe_path() -> Path | None:
    """`ffprobe` junto al `ffmpeg` configurado; si no, el del PATH; si no, None."""
    ffmpeg = ffmpeg_path()
    if ffmpeg is not None:
        sibling = ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe")
        if sibling.is_file():
            return sibling
    found = shutil.which("ffprobe")
    return Path(found) if found else None


def _require_ffmpeg() -> Path:
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        raise EngineError(
            "No se encuentra ffmpeg: instálalo con `instanttraductor preparar` o ponlo en el PATH.",
            engine=ENGINE_NAME,
            recoverable=False,
        )
    return ffmpeg


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 and np.isfinite(number) else None


def probe_input(path: str | Path) -> InputInfo:
    """Valida el fichero de entrada y devuelve su duración y si trae vídeo.

    No arranca ningún ritmo real: tarda lo que tarde `ffprobe`. Lanza `InputFileError` si el fichero no
    existe, está dañado, no es admitido o no tiene pista de audio, y `EngineError(recoverable=False)` si
    no hay ffmpeg. Sin `ffprobe` (pero con ffmpeg), valida decodificando un instante y `duration_s` es None.
    """
    source = Path(path)
    if not source.is_file():
        raise InputFileError(f"No existe el fichero de entrada: {source}")
    ffmpeg = _require_ffmpeg()
    ffprobe = ffprobe_path()
    if ffprobe is None:
        return _probe_with_ffmpeg(ffmpeg, source)
    command = [
        str(ffprobe),
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,duration:stream_disposition=attached_pic:format=duration",
        "-of",
        "json",
        str(source.resolve()),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=_PROBE_TIMEOUT_S, check=False, creationflags=_NO_WINDOW
        )
    except subprocess.TimeoutExpired as exc:
        raise InputFileError(f"No se pudo leer {source.name}: ffprobe no responde.") from exc
    except OSError as exc:
        raise EngineError(
            f"No se pudo ejecutar ffprobe: {exc}", engine=ENGINE_NAME, recoverable=False
        ) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise InputFileError(
            f"El fichero {source.name} está dañado o no es de un formato admitido"
            + (f" ({detail[-1]})." if detail else ".")
        )
    try:
        data = json.loads(result.stdout.decode("utf-8", "replace") or "{}")
    except ValueError as exc:
        raise InputFileError(f"El fichero {source.name} está dañado o no es admitido.") from exc
    streams = data.get("streams") or []
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio:
        raise InputFileError(f"El fichero {source.name} no tiene pista de audio.")
    has_video = any(
        s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
        for s in streams
    )
    duration = _positive_float(audio[0].get("duration")) or _positive_float(
        (data.get("format") or {}).get("duration")
    )
    return InputInfo(duration_s=duration, has_video=has_video)


def _probe_with_ffmpeg(ffmpeg: Path, source: Path) -> InputInfo:
    """Reserva sin ffprobe: decodifica un instante de audio y busca vídeo con ffmpeg."""
    base = [str(ffmpeg), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source.resolve())]
    try:
        audio = subprocess.run(
            [*base, "-map", "0:a:0", "-t", "0.1", "-f", "null", "-"],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
            creationflags=_NO_WINDOW,
        )
        video = subprocess.run(
            [*base, "-map", "0:V:0", "-c", "copy", "-t", "0.01", "-f", "null", "-"],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise InputFileError(f"No se pudo leer {source.name}: ffmpeg no responde.") from exc
    if audio.returncode != 0:
        raise InputFileError(f"El fichero {source.name} está dañado, no es admitido o no tiene audio.")
    return InputInfo(duration_s=None, has_video=video.returncode == 0)


class _ArrivalLog:
    """Hora de llegada (reloj de sesión) de cada chunk, por `t_end` creciente. Seguro entre hilos."""

    def __init__(self) -> None:
        self._t_ends: list[float] = []
        self._arrivals: list[float] = []
        self._lock = threading.Lock()

    def record(self, t_end: float, arrival: float) -> None:
        with self._lock:
            self._t_ends.append(t_end)
            self._arrivals.append(arrival)

    def lookup(self, t_audio: float) -> float | None:
        """Llegada del chunk que contiene `t_audio` (frontera: pertenece al chunk que acaba ahí)."""
        with self._lock:
            index = bisect.bisect_left(self._t_ends, t_audio - 1e-9)
            return self._arrivals[index] if index < len(self._arrivals) else None


class FileSource:
    """`AudioSource` de un fichero de audio o vídeo, decodificado con ffmpeg y a ritmo real.

    - `clock`: el reloj de sesión. Con `realtime=True` marca el ritmo; con `realtime=False` solo da las
      horas de llegada.
    - `chunk_s`: duración de cada chunk (20 ms). El último puede ser más corto.
    - `duration_s`: duración del fichero según ffprobe; se rellena en `start()` (None si no se supo).
    - `start()` lanza `InputFileError` si el fichero no vale y `EngineError(recoverable=False)` sin ffmpeg.
    """

    sample_rate: int = CAPTURE_RATE

    def __init__(
        self, clock: Clock, path: str | Path, *, chunk_s: float = DEFAULT_CHUNK_S, realtime: bool = True
    ) -> None:
        if chunk_s <= 0:
            raise ValueError("chunk_s debe ser positivo.")
        self._clock = clock
        self._path = Path(path)
        self._chunk_samples = max(1, round(chunk_s * CAPTURE_RATE))
        self._realtime = realtime
        self.duration_s: float | None = None
        self._arrivals = _ArrivalLog()
        self._cond = threading.Condition()
        self._queue: deque[AudioChunk] = deque()
        self._stop_event = threading.Event()
        self._first_ready = threading.Event()
        self._finished = False  # el productor ya no meterá más chunks
        self._error: Exception | None = None
        self._failure: InputFileError | None = None  # fallo a mitad del fichero (tras el primer chunk)
        self._started = False
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None

    # --- AudioSource -----------------------------------------------------------------------------

    def start(self) -> None:
        """Valida el fichero, arranca ffmpeg y el hilo productor; vuelve con el primer chunk listo."""
        origin = self._clock.now()
        if self._started:
            return
        info = probe_input(self._path)
        self.duration_s = info.duration_s
        ffmpeg = _require_ffmpeg()
        command = [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(self._path.resolve()),
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "1",
            "-ar",
            str(CAPTURE_RATE),
            "-f",
            "f32le",
            "-",
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
        except OSError as exc:
            raise EngineError(
                f"No se pudo ejecutar ffmpeg: {exc}", engine=ENGINE_NAME, recoverable=False
            ) from exc
        self._started = True
        self._thread = threading.Thread(
            target=self._run, args=(self._process, origin), name="file-source", daemon=True
        )
        self._thread.start()
        if not self._first_ready.wait(_FIRST_CHUNK_TIMEOUT_S):
            self.stop()
            raise InputFileError(f"El fichero {self._path.name} no produce audio (ffmpeg no responde).")
        if self._error is not None:
            self.stop()
            raise self._error

    @property
    def failure(self) -> InputFileError | None:
        """Si ffmpeg falló a mitad del fichero, el error (la fuente se agota igualmente). Si no, None."""
        return self._failure

    def read(self, timeout: float) -> AudioChunk | None:
        """Siguiente chunk; espera hasta `timeout` s. None si no hay datos o la fuente ha terminado."""
        with self._cond:
            if not self._queue and not self._finished and not self._stop_event.is_set():
                self._cond.wait_for(
                    lambda: bool(self._queue) or self._finished or self._stop_event.is_set(),
                    timeout=max(0.0, timeout),
                )
            if self._stop_event.is_set() or not self._queue:
                return None
            chunk = self._queue.popleft()
            self._cond.notify_all()  # el productor puede estar esperando hueco (realtime=False)
            return chunk

    @property
    def exhausted(self) -> bool:
        with self._cond:
            return self._stop_event.is_set() or (self._finished and not self._queue)

    def stop(self) -> None:
        """Detiene la fuente y mata ffmpeg. Idempotente."""
        self._stop_event.set()
        process = self._process
        if process is not None and process.poll() is None:
            with contextlib.suppress(OSError):
                process.kill()
        with self._cond:
            self._queue.clear()
            self._cond.notify_all()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        if process is not None:
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                process.wait(timeout=5.0)
            if process.stdout is not None:
                with contextlib.suppress(OSError, ValueError):
                    process.stdout.close()

    # --- Hora de llegada -------------------------------------------------------------------------

    def arrival_time(self, t_audio: float) -> float | None:
        """Instante (reloj de sesión) en que llegó el chunk que contiene el instante de audio `t_audio`.

        None si ese audio aún no ha llegado. Un instante justo en la frontera entre dos chunks pertenece al
        que acaba ahí (el de `t_end_audio`). Sirve para `StageTimings.captured_at`.
        """
        return self._arrivals.lookup(t_audio)

    # --- Hilo productor --------------------------------------------------------------------------

    def _read_chunk(self, stream: IO[bytes], position: int) -> AudioChunk | None:
        """Lee del tubo un chunk exacto (el último puede ser más corto); None al acabar el audio."""
        data = stream.read(self._chunk_samples * _BYTES_PER_SAMPLE)
        usable = len(data) - len(data) % _BYTES_PER_SAMPLE
        if usable <= 0:
            return None
        samples = np.frombuffer(data[:usable], dtype="<f4").astype(np.float32)
        samples = np.clip(np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0)
        return AudioChunk(samples=samples, sample_rate=CAPTURE_RATE, t_start=position / CAPTURE_RATE)

    def _run(self, process: subprocess.Popen[bytes], origin: float) -> None:
        stream = process.stdout
        assert stream is not None
        position = 0  # muestras ya producidas
        try:
            chunk = self._read_chunk(stream, position)
            if chunk is None:
                if not self._stop_event.is_set():
                    self._error = InputFileError(
                        f"El fichero {self._path.name} está dañado o no contiene audio que se pueda leer."
                    )
                return
            self._first_ready.set()
            while chunk is not None and not self._stop_event.is_set():
                if self._realtime and not self._wait_until(origin + chunk.t_end):
                    return
                if not self._deliver(chunk):
                    return
                position += len(chunk.samples)
                chunk = self._read_chunk(stream, position)
        except Exception as exc:  # un fallo del tubo no debe dejar al lector esperando para siempre
            logger.warning("Fallo leyendo el audio de %s: %s", self._path.name, exc)
            if not self._stop_event.is_set():
                self._failure = InputFileError(f"Fallo leyendo el audio de {self._path.name}: {exc}")
        finally:
            if process.poll() is None and self._stop_event.is_set():
                with contextlib.suppress(OSError):
                    process.kill()
            elif position > 0 and not self._stop_event.is_set():
                try:
                    code = process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    code = None
                if code not in (0, None):
                    logger.warning("ffmpeg terminó con código %s leyendo %s.", code, self._path.name)
                    second = position / self.sample_rate
                    self._failure = InputFileError(
                        f"El fichero {self._path.name} está dañado a partir del segundo {second:.0f}."
                    )
            with self._cond:
                self._finished = True
                self._cond.notify_all()
            self._first_ready.set()

    def _wait_until(self, deadline: float) -> bool:
        """Espera a que el reloj llegue a `deadline`. False si se paró la fuente."""
        while True:
            remaining = deadline - self._clock.now()
            if remaining <= 0:
                return not self._stop_event.is_set()
            if self._stop_event.wait(min(remaining, _POLL_S)):
                return False

    def _deliver(self, chunk: AudioChunk) -> bool:
        """Registra la llegada y encola el chunk. Con `realtime=False` espera si la cola está llena."""
        with self._cond:
            if not self._realtime:
                self._cond.wait_for(
                    lambda: len(self._queue) < _MAX_QUEUED_CHUNKS or self._stop_event.is_set()
                )
            if self._stop_event.is_set():
                return False
            self._arrivals.record(chunk.t_end, self._clock.now())  # antes de encolar
            self._queue.append(chunk)
            self._cond.notify_all()
            return True
