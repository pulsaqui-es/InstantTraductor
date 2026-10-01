"""Manifiesto de componentes: lo que ``preparar`` descarga, verifica y lista (FR-025 y FR-026).

Cada ``Component`` fija su origen (sin «latest»), su licencia y los ficheros que lo forman, con el
``sha256`` y el tamaño de cada uno. El instalador (``installer.py``) usa estos datos; el resto del
núcleo solo pregunta por ``component_dir(...)`` e ``is_installed(...)``.

Convenciones
------------
- ``install_dir``: ruta relativa a ``AppPaths().home``, con «/» como separador. La ruta real es
  ``component_dir(component_id)`` y se calcula al llamar (lee ``INSTANTTRADUCTOR_HOME``).
- ``files[].rel_path``: relativa a ``component_dir(...)``.
- Origen, una de dos formas:
  - ``source_url``: URL base fijada (GitHub, Hugging Face ``resolve/...``, PyPI...). La URL de cada
    fichero es ``source_url + "/" + rel_path`` (ver ``Component.file_url``).
  - ``hf_repo_id`` + ``hf_revision`` (hash de commit) + ``allow_patterns``, para
    ``snapshot_download`` de los repositorios de Hugging Face con varios ficheros. ``allow_patterns``
    ``None`` significa todo el repositorio.
- Una entrada pendiente de fijar lleva ``files=()`` con el comentario ``# T013 rellena hashes y
  revisión``: ``scripts/dev_place_components.py`` (T013) calcula los ``sha256`` y los tamaños, y
  saca la ``hf_revision`` de la carpeta del *snapshot* de la caché de Hugging Face.
- Un componente sin ficheros declarados nunca cuenta como instalado (no hay nada que verificar).
- Las voces (``kind="voz"``) las añade T042.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Final, Literal, get_args

from instanttraductor.config import AppPaths

ComponentKind = Literal["binario", "modelo", "entorno", "voz"]

_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_COMPONENT_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")
_HF_REPO_ID = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")


def _invalid(owner: str, field_name: str, reason: str) -> ValueError:
    return ValueError(f"{owner}: {field_name} no válido ({reason})")


def _check_relative_path(value: object, owner: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(owner, field_name, "debe ser una ruta no vacía")
    if "\\" in value:
        raise _invalid(owner, field_name, "usa «/» como separador")
    path = PureWindowsPath(value)
    if path.drive or path.root or ".." in path.parts or not path.parts:
        raise _invalid(owner, field_name, "debe ser relativa y no salir de su carpeta")


@dataclass(frozen=True, slots=True)
class ComponentFile:
    """Un fichero de un componente: ruta relativa a su carpeta, ``sha256`` (minúsculas) y tamaño."""

    rel_path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        owner = f"Fichero «{self.rel_path}»"
        _check_relative_path(self.rel_path, owner, "rel_path")
        if not (isinstance(self.sha256, str) and _SHA256.fullmatch(self.sha256)):
            raise _invalid(owner, "sha256", "deben ser 64 dígitos hexadecimales en minúsculas")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes <= 0:
            raise _invalid(owner, "size_bytes", "debe ser un entero positivo")


@dataclass(frozen=True, slots=True)
class Component:
    """Un componente descargable (binario, modelo, entorno o voz) con su origen fijado y su licencia."""

    component_id: str  # ASCII y único; lo usan component_dir(), is_installed() y el informe
    name: str
    version: str
    kind: ComponentKind
    license: str  # obligatoria (FR-026)
    install_dir: str  # relativa a AppPaths().home, con «/»
    source_url: str | None = None  # URL base fijada (https, sin «latest»)
    hf_repo_id: str | None = None  # alternativa a source_url: repositorio de Hugging Face...
    hf_revision: str | None = None  # ...con hash de commit (None solo mientras T013 no lo fija)
    allow_patterns: tuple[str, ...] | None = None  # ...y patrones de ficheros (None = todo el repo)
    files: tuple[ComponentFile, ...] = ()  # vacío mientras T013 no calcula hashes y tamaños
    optional: bool = False  # True: la app funciona sin él (p. ej. ffmpeg, que puede estar en el PATH)

    def __post_init__(self) -> None:
        owner = f"Componente «{self.component_id}»"
        if not (isinstance(self.component_id, str) and _COMPONENT_ID.fullmatch(self.component_id)):
            raise _invalid(owner, "component_id", "ASCII en minúsculas: letras, dígitos, «-», «.» y «_»")
        for field_name in ("name", "version", "license"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise _invalid(owner, field_name, "es obligatorio")
        if self.kind not in get_args(ComponentKind):
            raise _invalid(owner, "kind", "debe ser " + ", ".join(get_args(ComponentKind)))
        _check_relative_path(self.install_dir, owner, "install_dir")
        if not isinstance(self.optional, bool):
            raise _invalid(owner, "optional", "debe ser true o false")

        self._check_source(owner)

        files = tuple(self.files)
        if not all(isinstance(file, ComponentFile) for file in files):
            raise _invalid(owner, "files", "debe ser una tupla de ComponentFile")
        if len({file.rel_path for file in files}) != len(files):
            raise _invalid(owner, "files", "hay rutas repetidas")
        if files and self.source_url is None and self.hf_repo_id is None:
            raise _invalid(owner, "source_url", "hay ficheros pero no se sabe de dónde bajarlos")
        object.__setattr__(self, "files", files)

    def _check_source(self, owner: str) -> None:
        if self.source_url is not None:
            if self.hf_repo_id is not None:
                raise _invalid(owner, "hf_repo_id", "no puede combinarse con source_url")
            if not isinstance(self.source_url, str) or not self.source_url.startswith("https://"):
                raise _invalid(owner, "source_url", "debe ser una URL https")
            if "latest" in self.source_url.lower():
                raise _invalid(owner, "source_url", "la URL debe estar fijada, sin «latest»")
        if self.hf_repo_id is None:
            if self.hf_revision is not None:
                raise _invalid(owner, "hf_revision", "solo se usa con hf_repo_id")
            if self.allow_patterns is not None:
                raise _invalid(owner, "allow_patterns", "solo se usa con hf_repo_id")
            return
        if not (isinstance(self.hf_repo_id, str) and _HF_REPO_ID.fullmatch(self.hf_repo_id)):
            raise _invalid(owner, "hf_repo_id", "debe tener la forma «organizacion/repositorio»")
        if self.hf_revision is not None and not (
            isinstance(self.hf_revision, str) and _COMMIT.fullmatch(self.hf_revision)
        ):
            raise _invalid(owner, "hf_revision", "debe ser un hash de commit de 40 dígitos hexadecimales")
        if self.allow_patterns is not None:
            patterns = tuple(self.allow_patterns)
            if not patterns or not all(isinstance(p, str) and p.strip() for p in patterns):
                raise _invalid(
                    owner, "allow_patterns", "usa None para todo el repositorio o patrones no vacíos"
                )
            object.__setattr__(self, "allow_patterns", patterns)

    def file_url(self, file: ComponentFile) -> str:
        """URL de descarga de un fichero: ``source_url`` + «/» + ``file.rel_path``."""
        if self.source_url is None:
            raise ValueError(
                f"Componente «{self.component_id}»: no tiene source_url "
                "(se baja de Hugging Face con snapshot_download o está pendiente de fijar)"
            )
        return f"{self.source_url.rstrip('/')}/{file.rel_path}"


# --- Lista de componentes ---
# Los URL, tamaños y sha256 salen de los spikes (descargas verificadas el 2026-09-30):
# spikes/traduccion/download.py (llama.cpp y Hy-MT2), spikes/asr/fetch_assets.py (Nemotron y Silero)
# y spikes/voz/common/descargar_modelos.py (Qwen3-TTS).

COMPONENTS: Final[tuple[Component, ...]] = (
    Component(
        component_id="llama-cpp",
        name="llama.cpp (llama-server, CUDA 13.4)",
        version="b11146",  # release v0.5.0
        kind="binario",
        license="MIT",
        install_dir="bin/llama-cpp",
        source_url="https://github.com/ggml-org/llama.cpp/releases/download/b11146",
        # Son los zips tal cual se descargan; el instalador los extrae en la misma carpeta, de modo
        # que llama-server.exe queda en component_dir("llama-cpp").
        files=(
            ComponentFile(
                "llama-b11146-bin-win-cuda-13.4-x64.zip",
                "b1866c0ce76bc7bfb0c24b33e9a37e9669f1be18539b12c74ce361f81c41f047",
                149_758_833,
            ),
            ComponentFile(
                "cudart-llama-bin-win-cuda-13.4-x64.zip",
                "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668",
                423_535_356,
            ),
        ),
    ),
    Component(
        component_id="hy-mt2-7b-q4",
        name="Hy-MT2-7B Q4_K_M (traducción)",
        version="Q4_K_M",
        kind="modelo",
        license="Apache-2.0",  # según su ficha de HF; T013 comprueba el LICENSE al fijar el GGUF
        install_dir="models/hy-mt2-7b-q4",
        source_url="https://huggingface.co/tencent/Hy-MT2-7B-GGUF/resolve/main",
        files=(
            ComponentFile(
                "Hy-MT2-7B-Q4_K_M.gguf",
                "9f96256500f3fc1ab4d64336b58f52a949a95ad7516b0c229476eef782f9f77b",
                4_624_648_896,
            ),
        ),
    ),
    Component(
        component_id="hy-mt2-1.8b-q8",
        name="Hy-MT2-1.8B Q8_0 (traducción, reserva)",
        version="Q8_0",
        kind="modelo",
        license="Apache-2.0",  # verificado el 2026-09-30 (research R20)
        install_dir="models/hy-mt2-1.8b-q8",
        source_url="https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/main",
        files=(
            ComponentFile(
                "Hy-MT2-1.8B-Q8_0.gguf",
                "5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4",
                1_908_528_192,
            ),
        ),
    ),
    Component(
        component_id="nemotron-en",
        name="Nemotron Speech Streaming EN 0.6B (reconocimiento de voz)",
        version="int8, trozo de 560 ms (2026-04-25)",
        kind="modelo",
        license="NVIDIA Open Model License",
        install_dir="models/nemotron-en",
        hf_repo_id="csukuangfj2/sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25",
        hf_revision=None,  # T013 rellena hashes y revisión
        allow_patterns=("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx"),
        files=(),  # T013 rellena hashes y revisión
    ),
    Component(
        component_id="silero-vad",
        name="Silero VAD (detección de voz)",
        version="6.2.3",
        kind="modelo",
        license="MIT",
        install_dir="models/silero-vad",
        # Metadatos de PyPI de la versión fijada: de ahí sale el wheel, del que se extrae
        # silero_vad/data/silero_vad.onnx (y el LICENSE), como hace spikes/asr/fetch_assets.py.
        source_url="https://pypi.org/pypi/silero-vad/6.2.3/json",
        files=(),  # T013 rellena hashes y revisión
    ),
    Component(
        component_id="qwen3-tts",
        name="Qwen3-TTS-12Hz-0.6B-Base (síntesis de voz)",
        version="0.6B-Base",
        kind="modelo",
        license="Apache-2.0",
        # El servicio de voz busca el modelo en <models>/qwen3-tts-12hz-0.6b-base (nombre de los spikes).
        install_dir="models/qwen3-tts-12hz-0.6b-base",
        hf_repo_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        hf_revision=None,  # T013 rellena hashes y revisión
        allow_patterns=None,  # el spike descargó el repositorio entero
        files=(),  # T013 rellena hashes y revisión
    ),
    Component(
        component_id="ffmpeg",
        name="ffmpeg (essentials, gyan.dev)",
        version="9.0.1",  # la del spike S4 (spikes/audio/README.md)
        kind="binario",
        license="GPL",
        install_dir="bin/ffmpeg",  # ffmpeg_path() busca bin/ffmpeg/bin/ffmpeg.exe
        # T013 fija la URL versionada de gyan.dev (ningún spike la descarga).
        source_url=None,
        files=(),  # T013 rellena hashes y revisión
        optional=True,  # puede estar ya en el PATH
    ),
    # Voces (kind="voz"): las añade T042.
)


# --- Consultas ---


def get_component(component_id: str) -> Component:
    """El componente con ese id. ``KeyError`` si no existe."""
    for component in COMPONENTS:
        if component.component_id == component_id:
            return component
    raise KeyError(f"Componente desconocido: {component_id!r}")


def component_dir(component_id: str) -> Path:
    """Carpeta del componente: ``AppPaths().home / install_dir`` (lee el entorno al llamar)."""
    return AppPaths().home / get_component(component_id).install_dir


def _has_size(path: Path, size_bytes: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size == size_bytes
    except OSError:
        return False


def is_installed(component_id: str) -> bool:
    """¿Existen todos los ficheros del componente con su tamaño?

    No calcula el ``sha256`` (con GGUF de varios GB sería lento en cada arranque): lo verifica el
    instalador al descargar. Un componente sin ficheros declarados nunca cuenta como instalado.
    """
    component = get_component(component_id)
    if not component.files:
        return False
    base = component_dir(component_id)
    return all(_has_size(base / file.rel_path, file.size_bytes) for file in component.files)
