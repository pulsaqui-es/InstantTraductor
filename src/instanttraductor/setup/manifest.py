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
  - ``package`` + ``package_dir``: recurso empaquetado en la propia app (sin URL ni red). ``package``
    es el paquete de Python (p. ej. ``instanttraductor.setup``) y ``package_dir`` la carpeta de
    recursos dentro de él (p. ej. ``voices``); se leen con ``importlib.resources`` y se copian a
    ``component_dir(...)``. Es el origen de las voces.
- Un componente sin ficheros declarados nunca cuenta como instalado (no hay nada que verificar).
- Las voces (``kind="voz"``) son una entrada por voz, con ``component_id="voz-<voice_id>"``. Comparten
  carpeta (``voices``, que es ``AppPaths().voices``). El valor exacto ``"voz"`` importa:
  ``session.report_components()`` las excluye del informe.
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


def _is_dotted(value: object) -> bool:
    return isinstance(value, str) and all(part.isidentifier() for part in value.split("."))


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
    package: str | None = None  # alternativa a las dos anteriores: paquete de Python con recursos...
    package_dir: str | None = None  # ...y carpeta de recursos dentro de él (sin red)
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
        if files and self.source_url is None and self.hf_repo_id is None and self.package is None:
            raise _invalid(owner, "source_url", "hay ficheros pero no se sabe de dónde bajarlos")
        object.__setattr__(self, "files", files)

    def _check_package(self, owner: str) -> None:
        if self.package is None:
            if self.package_dir is not None:
                raise _invalid(owner, "package_dir", "solo se usa con package")
            return
        if not _is_dotted(self.package):
            raise _invalid(owner, "package", "debe ser un nombre de paquete de Python")
        _check_relative_path(self.package_dir, owner, "package_dir")
        if self.source_url is not None or self.hf_repo_id is not None:
            raise _invalid(owner, "package", "no puede combinarse con source_url ni hf_repo_id")

    def _check_source(self, owner: str) -> None:
        self._check_package(owner)
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
                "(se baja de Hugging Face, viene empaquetado en la app o está pendiente de fijar)"
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
        license="Apache-2.0",  # LICENSE.txt estándar, sin restricciones territoriales (verificado 2026-10-01)
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
        hf_revision="52056fdc070914a48dcd68b31b44d6a6f5b85902",
        allow_patterns=("tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx"),
        files=(
            ComponentFile(
                "tokens.txt", "dc0b4584ab2e4ddbf888425c076c61b736e7356a015250db7d307e6f1a8188ff", 8_952
            ),
            ComponentFile(
                "encoder.int8.onnx",
                "7d932213491ad355c6e5576705dc3494731a52af87d7a1b954559340147909d8",
                652_916_849,
            ),
            ComponentFile(
                "decoder.int8.onnx",
                "0be9702c2f427a2b6bb241d298e0d3836a558de1f5b9fd3018f1cce6e2b3fa98",
                7_257_753,
            ),
            ComponentFile(
                "joiner.int8.onnx",
                "a35eac38a22ebceb04d230ed7afe0d68f446ba6914a036b97f14fece95967e23",
                1_735_862,
            ),
        ),
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
        files=(
            ComponentFile(
                "silero_vad.onnx",
                "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
                2_327_524,
            ),
            ComponentFile(
                "LICENSE", "2e63e9a38b6e8fc0c7bc37ce174caca1862870856c6daf5697cfb785e925520b", 1_075
            ),
        ),
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
        hf_revision="5d83992436eae1d760afd27aff78a71d676296fc",
        allow_patterns=None,  # el spike descargó el repositorio entero
        files=(
            ComponentFile(
                ".gitattributes", "11ad7efa24975ee4b0c3c3a38ed18737f0658a5f75a0a96787b576a78a023361", 1_519
            ),
            ComponentFile(
                "README.md", "181187b6057906bd960bc7f938d0b7a16652509776a0d52c4885b4ae5ccda0ea", 3_640
            ),
            ComponentFile(
                "config.json", "2e714c787c8edb98b05432685cddb634add2de4d4e645f653d68251ef72ba011", 4_494
            ),
            ComponentFile(
                "generation_config.json",
                "f1b90b4513f3b34c62851049e2492d7b4c5940daf1276f89c82b8ef04127f3aa",
                245,
            ),
            ComponentFile(
                "merges.txt", "599bab54075088774b1733fde865d5bd747cbcc7a547c5bc12610e874e26f5e3", 1_671_839
            ),
            ComponentFile(
                "model.safetensors",
                "180b3b10eb1c9f1b4db7806d5475bae3071c0243c299d49926bab1da3b6946f6",
                1_829_344_272,
            ),
            ComponentFile(
                "preprocessor_config.json",
                "efdde1022ea9d76928bf7a9cd53139138f5ba2e466e837f08f6105ab1af1c119",
                127,
            ),
            ComponentFile(
                "speech_tokenizer/config.json",
                "ee65bb901c876664ab8707c487157aa1a6ee57c65969b28fb5ec9dc211e68167",
                2_336,
            ),
            ComponentFile(
                "speech_tokenizer/configuration.json",
                "6bc26d64eb5024b4d1dab5a52371958b429256d6c9d59787f1f5294a54e0cebd",
                76,
            ),
            ComponentFile(
                "speech_tokenizer/model.safetensors",
                "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258",
                682_293_092,
            ),
            ComponentFile(
                "speech_tokenizer/preprocessor_config.json",
                "fcb3805e597e786d4067706e602f6688524640f8d3396790e2e09b5942fcbdfb",
                234,
            ),
            ComponentFile(
                "tokenizer_config.json",
                "dc3c31c3bdaedd5016382bb3cbe07323026775ad51f5a4fb564505992ae4a670",
                7_344,
            ),
            ComponentFile(
                "vocab.json", "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910", 2_776_833
            ),
        ),
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
    # Voces (kind="voz"): empaquetadas en src/instanttraductor/setup/voices/ (T042), sin descarga.
    # sha256 y tamaños de los ficheros del paquete; tests/unit/setup/test_voices.py comprueba que coinciden.
    Component(
        component_id="voz-es-f-dvx-01",
        name="Voz Lucía",
        version="catálogo 1",
        kind="voz",
        license="Apache-2.0 (modelo VoxCPM2; audio sintético)",
        install_dir="voices",  # = AppPaths().voices; todas las voces comparten carpeta
        package="instanttraductor.setup",
        package_dir="voices",
        files=(
            ComponentFile(
                "es-f-dvx-01.wav",
                "7f4fdeb1c936e7c443090b540087eb28618601d995b22e6934bcfb0b368bb04d",
                453_164,
            ),
            ComponentFile(
                "es-f-dvx-01.json",
                "c8ee0620d0a298972a5e8a9fad4f071a3c5a7b8de93602c158b1ff47c00083e7",
                794,
            ),
        ),
    ),
    Component(
        component_id="voz-es-f-dvx-08",
        name="Voz Clara",
        version="catálogo 1",
        kind="voz",
        license="Apache-2.0 (modelo VoxCPM2; audio sintético)",
        install_dir="voices",  # = AppPaths().voices; todas las voces comparten carpeta
        package="instanttraductor.setup",
        package_dir="voices",
        files=(
            ComponentFile(
                "es-f-dvx-08.wav",
                "95ef2047f54ed8e408c5ccf82b1c8c9b2922570f7a35b9e8a5d199e8c9164856",
                376_364,
            ),
            ComponentFile(
                "es-f-dvx-08.json",
                "ceb8973f79dca009e9bb801e4168b62ce613d2f9075127177fc0b5f26ad69c74",
                778,
            ),
        ),
    ),
    Component(
        component_id="voz-es-f-est-01",
        name="Voz humana 2 (VoxPopuli)",
        version="catálogo 1",
        kind="voz",
        license="CC0 1.0 (VoxPopuli, Parlamento Europeo)",
        install_dir="voices",  # = AppPaths().voices; todas las voces comparten carpeta
        package="instanttraductor.setup",
        package_dir="voices",
        files=(
            ComponentFile(
                "es-f-est-01.wav",
                "6de8b0a8f8094014754c6175d152b7fc9d5f5a0fcdb08c89044c6a2c9c1f7196",
                439_722,
            ),
            ComponentFile(
                "es-f-est-01.json",
                "5b849fc2b8400b167d66167c6dba38cedaae496de909c688b92e84bbf89ce55b",
                562,
            ),
        ),
    ),
    Component(
        component_id="voz-es-f-est-04",
        name="Voz humana 1 (VoxPopuli)",
        version="catálogo 1",
        kind="voz",
        license="CC0 1.0 (VoxPopuli, Parlamento Europeo)",
        install_dir="voices",  # = AppPaths().voices; todas las voces comparten carpeta
        package="instanttraductor.setup",
        package_dir="voices",
        files=(
            ComponentFile(
                "es-f-est-04.wav",
                "af6a8c2d6d4ebf900764776941d861aa62d7f43b615b4a23931542963ff37938",
                480_048,
            ),
            ComponentFile(
                "es-f-est-04.json",
                "371401922a1700f86faf0bbc88cb67feadd6e1f4d625b838093107d51a08daf1",
                574,
            ),
        ),
    ),
    Component(
        component_id="voz-es-m-tux",
        name="Voz Tux (LibriVox)",
        version="catálogo 1",
        kind="voz",
        license="Dominio público",
        install_dir="voices",  # = AppPaths().voices; todas las voces comparten carpeta
        package="instanttraductor.setup",
        package_dir="voices",
        files=(
            ComponentFile(
                "es-m-tux.wav",
                "f3cbcbf48452b4554c666805faca8065b19b7b77bd0f99fc76ce742bc32b2542",
                329_324,
            ),
            ComponentFile(
                "es-m-tux.json",
                "1afe2e8494acee89757a0cb631c9d80fefbd1891a4a26d36fade55b21efec56e",
                495,
            ),
        ),
    ),
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
