"""Instalador de ``instanttraductor preparar`` (T041, FR-025 a FR-027, SC-008 y research R12).

``prepare()`` deja el equipo listo: comprueba los requisitos, descarga y verifica lo que falte o esté
corrupto, prepara el entorno del servicio de voz y muestra una tabla con cada componente.

Pasos y códigos de salida (``contracts/cli.md``)
------------------------------------------------
1. **Comprobaciones previas** (código 6 si falla alguna de las bloqueantes, y no se descarga nada):
   Windows ``build`` ≥ ``MIN_WINDOWS_BUILD``; GPU NVIDIA con un driver que admita CUDA ≥
   ``MIN_CUDA_VERSION`` (``nvidia-smi``); espacio libre ≥ lo que falta por descargar + ``SPACE_MARGIN_BYTES``.
   ffmpeg es opcional: si falta, aparece como «falta (opcional)» y se sigue.
2. **Componentes**, cada uno con ``sha256`` de **cada fichero**. Estados:
   ``ausente`` → ``descargado`` → ``verificado`` | ``corrupto``. Un fichero corrupto se borra y se
   vuelve a descargar; lo que ya está verificado no se toca (la 2.ª ejecución no descarga nada).
3. **Entorno de la voz**: ``uv sync --frozen --project engines/tts-qwen3`` (solo si
   ``uv sync --frozen --check`` dice que no está al día).
4. **Salida**: tabla ``rich`` con nombre, versión, licencia, tamaño y estado.

``check_only=True`` (``--comprobar``) solo verifica: no crea carpetas, no descarga ni copia nada.
Quedan fuera de este módulo las muestras de las voces y los subcomandos (T043, orquestador).

Orígenes de un componente (ver ``manifest.py``)
-----------------------------------------------
- ``hf_repo_id``: ``snapshot_download(repo_id, revision, allow_patterns, local_dir=<carpeta>)``.
- ``source_url`` directa: ``httpx`` en *streaming* a ``<fichero>.part``, que solo se renombra si el
  ``sha256`` es el esperado. Los ``.zip`` de un binario se extraen junto al archivo (así deja T013 a
  llama.cpp: ``llama-server.exe`` queda en la carpeta del componente).
- ``source_url`` de metadatos de PyPI (``https://pypi.org/pypi/<paquete>/<versión>/json``): se baja el
  wheel, se comprueba su ``sha256`` contra PyPI y se extraen los ficheros del manifiesto por nombre
  (Silero VAD, como hace ``spikes/asr/fetch_assets.py``).
- ``package``: recursos empaquetados (las voces); los copia ``voices.install_voices``.

Todo lo que toca el sistema (``nvidia-smi``, ``uv``, disco, build de Windows) y la red entra por
``SystemProbe`` y ``Downloader``, para poder probar con dobles.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final, Protocol
from urllib.parse import urlparse

from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from instanttraductor.config import AppPaths
from instanttraductor.platform import windows
from instanttraductor.setup import manifest, voices
from instanttraductor.setup.manifest import Component, ComponentFile

__all__ = [
    "MIN_CUDA_VERSION",
    "MIN_WINDOWS_BUILD",
    "SPACE_MARGIN_BYTES",
    "VOICE_ENV_PROJECT",
    "Check",
    "CommandResult",
    "ComponentReport",
    "ComponentState",
    "Downloader",
    "GpuInfo",
    "HttpDownloader",
    "PrepareResult",
    "RealSystem",
    "SystemProbe",
    "VoiceEnvReport",
    "is_pypi_metadata_url",
    "parse_cuda_version",
    "prepare",
]

#: Windows 11 mínimo (compilación 20348 = Windows Server 2022 / base de Windows 11), contracts/cli.md.
MIN_WINDOWS_BUILD: Final = 20348
#: Los binarios (torch y llama.cpp) son cu130: el driver debe admitir CUDA 13.0 (decisión del orquestador).
MIN_CUDA_VERSION: Final = (13, 0)
#: Espacio libre que debe sobrar tras descargar lo que falta (2 GB).
SPACE_MARGIN_BYTES: Final = 2 * 1024**3
#: Proyecto de uv del servicio de voz, en la raíz del repositorio (junto a ``src``).
VOICE_ENV_PROJECT: Final = Path(__file__).resolve().parents[3] / "engines" / "tts-qwen3"

_HASH_BLOCK: Final = 8 * 1024 * 1024
_SUBPROCESS_TIMEOUT_S: Final = 3600
_CUDA_VERSION_RE: Final = re.compile(r"CUDA Version:\s*(\d+)\.(\d+)")


class ComponentState(StrEnum):
    """Estado de un componente (el texto es el que ve la persona usuaria en la tabla)."""

    ABSENT = "ausente"
    DOWNLOADED = "descargado"
    VERIFIED = "verificado"
    CORRUPT = "corrupto"
    OPTIONAL_MISSING = "falta (opcional)"


class InstallError(Exception):
    """Un componente no se ha podido instalar (el mensaje va en español, para la tabla)."""


# --- resultados ---


@dataclass(frozen=True, slots=True)
class Check:
    """Una comprobación previa. ``blocking=False`` solo avisa (no cambia el código de salida)."""

    name: str
    ok: bool
    detail: str
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class ComponentReport:
    """Estado de un componente tras ``prepare``; ``history`` es la secuencia de estados recorridos."""

    component: Component
    state: ComponentState
    detail: str = ""
    history: tuple[ComponentState, ...] = ()

    @property
    def ok(self) -> bool:
        return self.state is ComponentState.VERIFIED or (
            self.state is ComponentState.OPTIONAL_MISSING and self.component.optional
        )

    @property
    def size_bytes(self) -> int:
        return sum(file.size_bytes for file in self.component.files)


@dataclass(frozen=True, slots=True)
class VoiceEnvReport:
    """Entorno del servicio de voz. ``synced`` es verdadero si esta ejecución lo ha sincronizado."""

    ok: bool
    detail: str
    synced: bool = False


@dataclass(frozen=True, slots=True)
class PrepareResult:
    """Resultado de ``prepare``.

    - ``checks``: comprobaciones previas (y la de espacio, salvo con ``check_only``).
    - ``components``: un informe por componente del manifiesto, en su orden.
    - ``voice_env``: entorno de la voz.
    - ``downloaded``: ids de los componentes que se han descargado (y verificado) en esta ejecución.
    - ``voices_installed``: ids de las voces copiadas o repuestas en esta ejecución.
    """

    checks: tuple[Check, ...]
    components: tuple[ComponentReport, ...]
    voice_env: VoiceEnvReport
    downloaded: tuple[str, ...] = ()
    voices_installed: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        """0 correcto; 6 si el equipo no cumple los requisitos; 3 si la preparación está incompleta."""
        if any(not check.ok and check.blocking for check in self.checks):
            return 6
        if not self.voice_env.ok or not all(report.ok for report in self.components):
            return 3
        return 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


# --- sistema y red (inyectables) ---


@dataclass(frozen=True, slots=True)
class GpuInfo:
    """GPU NVIDIA según ``nvidia-smi``. ``cuda_version`` es la máxima que admite el driver."""

    name: str
    driver_version: str
    cuda_version: tuple[int, int] | None


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    output: str


class SystemProbe(Protocol):
    """Todo lo que ``prepare`` pregunta o ejecuta en el sistema."""

    def windows_build(self) -> int: ...

    def gpu_info(self) -> GpuInfo | None:
        """``None`` si no hay GPU NVIDIA o ``nvidia-smi`` no responde."""
        ...

    def free_bytes(self, path: Path) -> int: ...

    def find_ffmpeg(self, paths: AppPaths) -> Path | None: ...

    def run_command(self, args: Sequence[str]) -> CommandResult: ...


class Downloader(Protocol):
    """Descargas de red (inyectable en los tests)."""

    def download_file(self, url: str, dest: Path, progress: Callable[[int], None] | None = None) -> None:
        """Descarga ``url`` en ``dest``. ``progress`` recibe los bytes de cada trozo."""
        ...

    def get_json(self, url: str) -> dict[str, object]: ...

    def snapshot_download(
        self,
        *,
        repo_id: str,
        revision: str | None,
        allow_patterns: Sequence[str] | None,
        local_dir: Path,
    ) -> None: ...


def parse_cuda_version(nvidia_smi_output: str) -> tuple[int, int] | None:
    """Extrae «CUDA Version: 13.1» de la cabecera de ``nvidia-smi``."""
    match = _CUDA_VERSION_RE.search(nvidia_smi_output)
    return (int(match.group(1)), int(match.group(2))) if match else None


class RealSystem:
    """Implementación real de ``SystemProbe`` (Windows, ``nvidia-smi`` y ``uv`` del PATH)."""

    def windows_build(self) -> int:
        return windows.windows_build()

    def gpu_info(self) -> GpuInfo | None:
        exe = shutil.which("nvidia-smi")
        if exe is None:
            return None
        query = self._run([exe, "--query-gpu=name,driver_version", "--format=csv,noheader"], 30)
        if query.returncode != 0 or not query.output.strip():
            return None
        name, _, driver = query.output.strip().splitlines()[0].partition(",")
        header = self._run([exe], 30)
        return GpuInfo(name.strip(), driver.strip(), parse_cuda_version(header.output))

    def free_bytes(self, path: Path) -> int:
        probe = path
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return shutil.disk_usage(probe).free

    def find_ffmpeg(self, paths: AppPaths) -> Path | None:
        local = paths.bin / "ffmpeg" / "bin" / "ffmpeg.exe"
        if local.is_file():
            return local
        found = shutil.which("ffmpeg")
        return Path(found) if found else None

    def run_command(self, args: Sequence[str]) -> CommandResult:
        command = list(args)
        exe = shutil.which(command[0])
        if exe is None:
            return CommandResult(127, f"«{command[0]}» no está en el PATH")
        return self._run([exe, *command[1:]], _SUBPROCESS_TIMEOUT_S)

    @staticmethod
    def _run(command: list[str], timeout: int) -> CommandResult:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return CommandResult(1, str(error))
        return CommandResult(completed.returncode, (completed.stdout or "") + (completed.stderr or ""))


class HttpDownloader:
    """Descargas reales: ``httpx`` en *streaming* y ``huggingface_hub.snapshot_download``."""

    def download_file(self, url: str, dest: Path, progress: Callable[[int], None] | None = None) -> None:
        import httpx

        dest.parent.mkdir(parents=True, exist_ok=True)
        timeout = httpx.Timeout(30.0, read=120.0)
        with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes(1 << 20):
                    handle.write(chunk)
                    if progress is not None:
                        progress(len(chunk))

    def get_json(self, url: str) -> dict[str, object]:
        import httpx

        response = httpx.get(url, follow_redirects=True, timeout=60.0)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise InstallError(f"Respuesta de {url} no válida (se esperaba un objeto JSON)")
        return data

    def snapshot_download(
        self,
        *,
        repo_id: str,
        revision: str | None,
        allow_patterns: Sequence[str] | None,
        local_dir: Path,
    ) -> None:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=repo_id,
            revision=revision,
            allow_patterns=list(allow_patterns) if allow_patterns is not None else None,
            local_dir=str(local_dir),
        )


# --- verificación de ficheros ---


def is_pypi_metadata_url(url: str) -> bool:
    """¿Es una URL de metadatos JSON de PyPI (``https://pypi.org/pypi/<paquete>/<versión>/json``)?"""
    parsed = urlparse(url)
    return parsed.hostname == "pypi.org" and parsed.path.endswith("/json")


def _hash_file(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(_HASH_BLOCK), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _file_state(base: Path, file: ComponentFile) -> ComponentState:
    """``ausente`` (no existe), ``corrupto`` (tamaño o ``sha256`` distintos) o ``verificado``."""
    path = base / file.rel_path
    try:
        if not path.exists():
            return ComponentState.ABSENT
        if not path.is_file() or path.stat().st_size != file.size_bytes:
            return ComponentState.CORRUPT
    except OSError:
        return ComponentState.CORRUPT
    return ComponentState.VERIFIED if _hash_file(path) == file.sha256 else ComponentState.CORRUPT


def _discard(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _discard_with_hf_metadata(base: Path, rel_path: str) -> None:
    """Borra un fichero corrupto y los metadatos de Hugging Face que lo darían por al día."""
    _discard(base / rel_path)
    metadata = base / ".cache" / "huggingface" / "download" / rel_path
    for suffix in (".metadata", ".lock", ".incomplete"):
        _discard(metadata.with_name(metadata.name + suffix))


# --- zips ---


def _zip_is_extracted(archive_path: Path, base: Path) -> bool:
    """¿Están todos los ficheros del zip junto a él, con su tamaño?"""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            return all(
                (base / info.filename).is_file() and (base / info.filename).stat().st_size == info.file_size
                for info in archive.infolist()
                if not info.is_dir()
            )
    except (OSError, zipfile.BadZipFile):
        return False


def _safe_target(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    if not target.is_relative_to(root):
        raise InstallError(f"El archivo contiene una ruta fuera de su carpeta: «{name}»")
    return target


def _write_stream(source: object, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    with temporary.open("wb") as handle:
        shutil.copyfileobj(source, handle)  # type: ignore[arg-type]
    os.replace(temporary, target)


def _extract_zip(archive_path: Path, base: Path) -> None:
    """Extrae el zip en ``base``. Si alguna ruta se sale de ``base``, no extrae nada."""
    root = base.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        targets = [_safe_target(root, info.filename) for info in infos]
        for info, target in zip(infos, targets, strict=True):
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                with archive.open(info) as source:
                    _write_stream(source, target)


def _extracts_zips(component: Component) -> bool:
    return component.kind == "binario" and any(f.rel_path.endswith(".zip") for f in component.files)


# --- trabajo por componente ---


@dataclass
class _Work:
    """Estado mutable de un componente durante ``prepare``."""

    component: Component
    base: Path
    files: dict[str, ComponentState] = field(default_factory=dict)
    state: ComponentState = ComponentState.ABSENT
    detail: str = ""
    history: list[ComponentState] = field(default_factory=list)
    installed: bool = False  # descargado y verificado en esta ejecución

    def bad_files(self) -> list[ComponentFile]:
        return [f for f in self.component.files if self.files[f.rel_path] is not ComponentState.VERIFIED]

    def extraction_pending(self) -> bool:
        return _extracts_zips(self.component) and any(
            self.files[f.rel_path] is ComponentState.VERIFIED
            and f.rel_path.endswith(".zip")
            and not _zip_is_extracted(self.base / f.rel_path, self.base)
            for f in self.component.files
        )

    def refresh(self) -> None:
        """Recalcula ``state`` a partir de los estados de sus ficheros."""
        values = set(self.files.values())
        if ComponentState.CORRUPT in values:
            self.state = ComponentState.CORRUPT
        elif ComponentState.ABSENT in values:
            self.state = ComponentState.ABSENT
        elif self.extraction_pending():
            self.state = ComponentState.DOWNLOADED
        else:
            self.state = ComponentState.VERIFIED

    def record(self, state: ComponentState) -> None:
        if not self.history or self.history[-1] is not state:
            self.history.append(state)

    def report(self) -> ComponentReport:
        return ComponentReport(self.component, self.state, self.detail, tuple(self.history))


def _inspect(component: Component, paths: AppPaths, ffmpeg: Path | None) -> _Work:
    base = paths.home / component.install_dir
    work = _Work(component, base)
    if not component.files:
        if component.component_id == "ffmpeg" and ffmpeg is not None:
            work.state = ComponentState.VERIFIED
            work.detail = str(ffmpeg)
        elif component.optional:
            work.state = ComponentState.OPTIONAL_MISSING
            work.detail = "no es imprescindible"
        else:
            work.state = ComponentState.ABSENT
            work.detail = "sin ficheros declarados en el manifiesto"
    else:
        work.files = {f.rel_path: _file_state(base, f) for f in component.files}
        work.refresh()
    work.record(work.state)
    return work


def _missing_bytes(works: Sequence[_Work]) -> int:
    return sum(file.size_bytes for work in works for file in work.bad_files())


def _check_requirements(system: SystemProbe, ffmpeg: Path | None) -> list[Check]:
    checks: list[Check] = []
    build = system.windows_build()
    checks.append(
        Check(
            "windows",
            build >= MIN_WINDOWS_BUILD,
            f"Windows build {build} (se necesita ≥ {MIN_WINDOWS_BUILD})",
        )
    )

    gpu = system.gpu_info()
    needed = ".".join(map(str, MIN_CUDA_VERSION))
    if gpu is None:
        checks.append(Check("gpu", False, "No se detecta una GPU NVIDIA (nvidia-smi no responde)"))
    elif gpu.cuda_version is None:
        checks.append(
            Check("gpu", True, f"{gpu.name}, driver {gpu.driver_version} (versión de CUDA no determinada)")
        )
    elif gpu.cuda_version < MIN_CUDA_VERSION:
        found = ".".join(map(str, gpu.cuda_version))
        checks.append(
            Check(
                "gpu",
                False,
                f"{gpu.name}: el driver {gpu.driver_version} solo admite CUDA {found}; "
                f"se necesita CUDA ≥ {needed} (actualiza el driver de NVIDIA)",
            )
        )
    else:
        found = ".".join(map(str, gpu.cuda_version))
        checks.append(Check("gpu", True, f"{gpu.name}, driver {gpu.driver_version}, CUDA {found}"))

    if ffmpeg is not None:
        checks.append(Check("ffmpeg", True, str(ffmpeg), blocking=False))
    else:
        checks.append(Check("ffmpeg", False, "falta (opcional)", blocking=False))
    return checks


def _check_space(system: SystemProbe, paths: AppPaths, missing: int) -> Check:
    needed = missing + SPACE_MARGIN_BYTES
    free = system.free_bytes(paths.home)
    detail = (
        f"libre {_format_size(free)}; hacen falta {_format_size(needed)} "
        f"({_format_size(missing)} por descargar + {_format_size(SPACE_MARGIN_BYTES)} de margen)"
    )
    return Check("espacio", free >= needed, detail)


# --- descargas ---


def _download_url_files(work: _Work, downloader: Downloader, progress: Progress, errors: list[str]) -> bool:
    """Descarga cada fichero que falta o está corrupto; devuelve si bajó alguno entero y válido."""
    component = work.component
    fetched = False
    for file in work.bad_files():
        target = work.base / file.rel_path
        part = target.with_name(target.name + ".part")
        _discard(target)
        _discard(part)
        task = progress.add_task(escape(file.rel_path), total=file.size_bytes)
        try:
            downloader.download_file(
                component.file_url(file), part, lambda n, t=task: progress.update(t, advance=n)
            )
        except Exception as error:  # red, disco... un fallo no debe parar el resto de componentes
            _discard(part)
            errors.append(f"{file.rel_path}: {error}")
            continue
        finally:
            progress.remove_task(task)
        if _file_state(part.parent, ComponentFile(part.name, file.sha256, file.size_bytes)) is not (
            ComponentState.VERIFIED
        ):
            _discard(part)
            work.files[file.rel_path] = ComponentState.CORRUPT
            errors.append(f"{file.rel_path}: el sha256 de lo descargado no coincide")
            fetched = True
            continue
        os.replace(part, target)
        work.files[file.rel_path] = ComponentState.VERIFIED
        fetched = True
    return fetched


def _download_hugging_face(work: _Work, downloader: Downloader, console: Console) -> bool:
    component = work.component
    if component.hf_revision is None:
        raise InstallError("la revisión (hf_revision) no está fijada en el manifiesto")
    for file in work.bad_files():
        _discard_with_hf_metadata(work.base, file.rel_path)
    console.print(f"Descargando {escape(component.name)} de Hugging Face…")
    work.base.mkdir(parents=True, exist_ok=True)
    downloader.snapshot_download(
        repo_id=component.hf_repo_id or "",
        revision=component.hf_revision,
        allow_patterns=component.allow_patterns,
        local_dir=work.base,
    )
    for file in work.bad_files():
        work.files[file.rel_path] = _file_state(work.base, file)
    return True


def _pick_wheel(metadata: dict[str, object]) -> dict[str, object]:
    urls = metadata.get("urls")
    if isinstance(urls, list):
        for entry in urls:
            if isinstance(entry, dict) and str(entry.get("filename", "")).endswith(".whl"):
                return entry
    raise InstallError("PyPI no ofrece ningún wheel para esa versión")


def _download_pypi_wheel(work: _Work, downloader: Downloader, progress: Progress) -> bool:
    component = work.component
    entry = _pick_wheel(downloader.get_json(component.source_url or ""))
    digests = entry.get("digests")
    expected = digests.get("sha256") if isinstance(digests, dict) else None
    if not isinstance(expected, str) or not isinstance(entry.get("url"), str):
        raise InstallError("los metadatos de PyPI no traen la URL o el sha256 del wheel")
    wheel_path = work.base / (str(entry["filename"]) + ".part")
    wanted = work.bad_files()
    for file in wanted:
        _discard(work.base / file.rel_path)
    task = progress.add_task(escape(str(entry["filename"])), total=None)
    try:
        try:
            downloader.download_file(
                str(entry["url"]), wheel_path, lambda n: progress.update(task, advance=n)
            )
        finally:
            progress.remove_task(task)
        if _hash_file(wheel_path) != expected:
            raise InstallError("el sha256 del wheel no coincide con el de PyPI")
        with zipfile.ZipFile(wheel_path) as wheel:
            for file in wanted:
                name = PurePosixPath(file.rel_path).name
                matches = [n for n in wheel.namelist() if PurePosixPath(n).name == name]
                if len(matches) != 1:
                    raise InstallError(f"no se encuentra «{file.rel_path}» en el wheel")
                with wheel.open(matches[0]) as source:
                    _write_stream(source, work.base / file.rel_path)
    finally:
        _discard(wheel_path)
    for file in wanted:
        work.files[file.rel_path] = _file_state(work.base, file)
    return True


def _install_component(work: _Work, downloader: Downloader, progress: Progress, console: Console) -> None:
    """Deja un componente verificado: descarga lo que falta, verifica y extrae. No lanza."""
    component = work.component
    before = work.state
    errors: list[str] = []
    fetched = False
    try:
        if work.bad_files():
            work.base.mkdir(parents=True, exist_ok=True)
            if component.hf_repo_id is not None:
                fetched = _download_hugging_face(work, downloader, console)
            elif component.source_url is not None and is_pypi_metadata_url(component.source_url):
                fetched = _download_pypi_wheel(work, downloader, progress)
            elif component.source_url is not None:
                fetched = _download_url_files(work, downloader, progress, errors)
            else:
                raise InstallError("no tiene origen de descarga en el manifiesto")
            if fetched:
                work.record(ComponentState.DOWNLOADED)
        work.refresh()
        if work.state is ComponentState.DOWNLOADED:  # ficheros verificados, falta extraer los zips
            for file in component.files:
                if file.rel_path.endswith(".zip") and not _zip_is_extracted(
                    work.base / file.rel_path, work.base
                ):
                    _extract_zip(work.base / file.rel_path, work.base)
            work.refresh()
    except Exception as error:  # un componente que falla no debe parar a los demás
        errors.append(str(error))
        work.refresh()
    work.detail = "; ".join(errors)
    if work.state is ComponentState.VERIFIED and fetched:
        work.installed = True
    if work.state is not before or fetched:
        work.record(work.state)


# --- entorno de la voz ---


def _voice_env(system: SystemProbe, console: Console, *, check_only: bool) -> VoiceEnvReport:
    project = str(VOICE_ENV_PROJECT)
    check = system.run_command(("uv", "sync", "--frozen", "--check", "--project", project))
    if check.returncode == 0:
        return VoiceEnvReport(True, "al día")
    if check_only:
        return VoiceEnvReport(False, "falta preparar el entorno del servicio de voz")
    with console.status("Preparando el entorno del servicio de voz (uv sync; puede tardar unos minutos)…"):
        sync = system.run_command(("uv", "sync", "--frozen", "--project", project))
    if sync.returncode == 0:
        return VoiceEnvReport(True, "sincronizado", synced=True)
    tail = " | ".join(line.strip() for line in sync.output.strip().splitlines()[-3:])
    return VoiceEnvReport(False, f"uv sync falló (código {sync.returncode}): {tail}")


# --- salida ---


def _format_size(size: int) -> str:
    if size < 1000:
        return f"{size} B"
    for unit, factor in (("KB", 1e3), ("MB", 1e6), ("GB", 1e9)):
        if size < factor * 1000 or unit == "GB":
            return f"{size / factor:.1f} {unit}".replace(".", ",")
    raise AssertionError("inalcanzable")  # pragma: no cover


_STATE_STYLE: Final = {
    ComponentState.VERIFIED: "green",
    ComponentState.DOWNLOADED: "yellow",
    ComponentState.ABSENT: "red",
    ComponentState.CORRUPT: "red",
    ComponentState.OPTIONAL_MISSING: "yellow",
}


def _print_checks(console: Console, checks: Sequence[Check]) -> None:
    for check in checks:
        label, style = (
            ("OK", "green") if check.ok else (("FALLA", "red") if check.blocking else ("aviso", "yellow"))
        )
        console.print(f"[{style}]{label:<5}[/{style}] {check.name}: {escape(check.detail)}")


def _print_table(console: Console, result: PrepareResult) -> None:
    table = Table(title="Componentes")
    for heading in ("Componente", "Versión", "Licencia", "Tamaño", "Estado"):
        table.add_column(heading)
    for report in result.components:
        component = report.component
        style = _STATE_STYLE[report.state]
        table.add_row(
            escape(component.name),
            escape(component.version),
            escape(component.license),
            _format_size(report.size_bytes) if component.files else "-",
            f"[{style}]{report.state.value}[/{style}]",
        )
    env_style = "green" if result.voice_env.ok else "red"
    table.add_row(
        "Entorno del servicio de voz",
        "uv.lock",
        "-",
        "-",
        f"[{env_style}]{'verificado' if result.voice_env.ok else 'incompleto'}[/{env_style}]",
    )
    console.print(table)
    for report in result.components:
        if report.detail and not report.ok:
            console.print(f"[red]{escape(report.component.name)}[/red]: {escape(report.detail)}")
    if not result.voice_env.ok:
        console.print(f"[red]Entorno del servicio de voz[/red]: {escape(result.voice_env.detail)}")


# --- punto de entrada ---


def prepare(
    paths: AppPaths | None = None,
    *,
    check_only: bool = False,
    downloader: Downloader | None = None,
    console: Console | None = None,
    components: Sequence[Component] | None = None,
    system: SystemProbe | None = None,
) -> PrepareResult:
    """Prepara el equipo (ver el docstring del módulo).

    - ``paths``: carpetas de datos (por defecto ``AppPaths()``).
    - ``check_only``: solo verifica; no crea carpetas ni descarga ni copia nada.
    - ``downloader`` y ``system``: dobles para los tests (por defecto, red y sistema reales).
    - ``console``: salida de ``rich`` (por defecto, la consola estándar).
    - ``components``: lista a preparar (por defecto, ``manifest.COMPONENTS``).

    Los fallos de requisitos (código 6) o de un componente (código 3) no lanzan: se devuelven en el
    resultado. Siempre se imprimen las comprobaciones y la tabla.
    """
    paths = paths or AppPaths()
    console = console or Console()
    system = system or RealSystem()
    selected = tuple(manifest.COMPONENTS if components is None else components)

    ffmpeg = system.find_ffmpeg(paths)
    checks = _check_requirements(system, ffmpeg)
    works = [_inspect(component, paths, ffmpeg) for component in selected]
    if not check_only:
        checks.append(_check_space(system, paths, _missing_bytes(works)))

    voices_installed: tuple[str, ...] = ()
    if any(not check.ok and check.blocking for check in checks):
        voice_env = VoiceEnvReport(False, "no comprobado (el equipo no cumple los requisitos)")
    else:
        if not check_only:
            voices_installed = _install_everything(works, paths, downloader, console)
        voice_env = _voice_env(system, console, check_only=check_only)

    result = PrepareResult(
        checks=tuple(checks),
        components=tuple(work.report() for work in works),
        voice_env=voice_env,
        downloaded=tuple(work.component.component_id for work in works if work.installed),
        voices_installed=voices_installed,
    )
    _print_checks(console, result.checks)
    _print_table(console, result)
    return result


def _install_everything(
    works: Sequence[_Work], paths: AppPaths, downloader: Downloader | None, console: Console
) -> tuple[str, ...]:
    """Instala las voces empaquetadas y descarga el resto de componentes."""
    installed_voices: tuple[str, ...] = ()
    voice_works = [work for work in works if work.component.kind == "voz" and work.bad_files()]
    if voice_works:
        try:
            installed_voices = voices.install_voices(paths)
        except Exception as error:  # paquete dañado, disco lleno...
            for work in voice_works:
                work.detail = str(error)
        for work in voice_works:
            work.files = {f.rel_path: _file_state(work.base, f) for f in work.component.files}
            work.refresh()
            work.record(work.state)

    pending = [
        work
        for work in works
        if work.component.kind != "voz" and work.component.files and work.state is not ComponentState.VERIFIED
    ]
    if pending:
        downloader = downloader or HttpDownloader()
        columns = (
            TextColumn("{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
        )
        with Progress(*columns, console=console, transient=True) as progress:
            for work in pending:
                _install_component(work, downloader, progress, console)
    return installed_voices
