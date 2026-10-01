"""Tests de `instanttraductor.setup.manifest`: componentes fijados, rutas y estado de instalación."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from instanttraductor.config import AppPaths
from instanttraductor.setup import manifest
from instanttraductor.setup.manifest import (
    COMPONENTS,
    Component,
    ComponentFile,
    component_dir,
    get_component,
    is_installed,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
COMMIT = "0123456789abcdef0123456789abcdef01234567"

PENDING_MARKER = "# T013 rellena hashes y revisión"


def make_component(**overrides: object) -> Component:
    """Un componente válido de prueba; `overrides` cambia campos concretos."""
    fields: dict[str, object] = {
        "component_id": "fake-model",
        "name": "Modelo falso",
        "version": "1.0",
        "kind": "modelo",
        "license": "MIT",
        "install_dir": "models/fake-model",
        "source_url": "https://example.com/models/v1",
        "files": (ComponentFile("a.bin", SHA_A, 5), ComponentFile("sub/b.bin", SHA_B, 3)),
    }
    fields.update(overrides)
    return Component(**fields)


# --- la lista real: COMPONENTS ---


def test_component_ids_are_unique_ascii_and_stable_identifiers() -> None:
    ids = [component.component_id for component in COMPONENTS]

    assert len(ids) == len(set(ids))
    assert all(component_id.isascii() for component_id in ids)
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9._-]*", component_id) for component_id in ids)


def test_components_used_by_other_tasks_exist() -> None:
    # Ids que citan T018 (silero-vad), T019 (nemotron-en), T021 (llama-cpp) y el informe (hy-mt2-*).
    ids = {component.component_id for component in COMPONENTS}

    assert {
        "llama-cpp",
        "hy-mt2-7b-q4",
        "hy-mt2-1.8b-q8",
        "nemotron-en",
        "silero-vad",
        "qwen3-tts",
        "ffmpeg",
    } <= ids


def test_every_component_has_license_name_and_version() -> None:
    for component in COMPONENTS:
        assert component.license.strip(), component.component_id
        assert component.name.strip(), component.component_id
        assert component.version.strip(), component.component_id


def test_kinds_of_the_known_components() -> None:
    kinds = {component.component_id: component.kind for component in COMPONENTS}

    assert kinds["llama-cpp"] == "binario"
    assert kinds["ffmpeg"] == "binario"
    assert kinds["hy-mt2-7b-q4"] == "modelo"
    assert kinds["hy-mt2-1.8b-q8"] == "modelo"
    assert kinds["nemotron-en"] == "modelo"
    assert kinds["silero-vad"] == "modelo"
    assert kinds["qwen3-tts"] == "modelo"


def test_only_ffmpeg_is_optional() -> None:
    assert {component.component_id for component in COMPONENTS if component.optional} == {"ffmpeg"}


def test_no_url_contains_latest() -> None:
    for component in COMPONENTS:
        urls = [component.source_url, component.hf_repo_id, component.hf_revision]
        if component.source_url is not None:
            urls += [component.file_url(file) for file in component.files]
        for url in urls:
            assert url is None or "latest" not in url.lower(), (component.component_id, url)


def test_download_urls_are_https() -> None:
    for component in COMPONENTS:
        if component.source_url is not None:
            assert component.source_url.startswith("https://"), component.component_id


def test_components_with_files_have_a_source() -> None:
    for component in COMPONENTS:
        if component.files:
            assert component.source_url is not None or component.hf_repo_id is not None, (
                component.component_id
            )


def test_hugging_face_revisions_are_commit_hashes_when_present() -> None:
    for component in COMPONENTS:
        if component.hf_revision is not None:
            assert re.fullmatch(r"[0-9a-f]{40}", component.hf_revision), component.component_id


def test_values_taken_from_the_spikes_are_kept() -> None:
    """URL, tamaño y sha256 de `spikes/traduccion/download.py` (comprobados el 2026-09-30)."""
    expected = {
        "llama-b11146-bin-win-cuda-13.4-x64.zip": (
            "https://github.com/ggml-org/llama.cpp/releases/download/b11146/llama-b11146-bin-win-cuda-13.4-x64.zip",
            149_758_833,
            "b1866c0ce76bc7bfb0c24b33e9a37e9669f1be18539b12c74ce361f81c41f047",
        ),
        "cudart-llama-bin-win-cuda-13.4-x64.zip": (
            "https://github.com/ggml-org/llama.cpp/releases/download/b11146/cudart-llama-bin-win-cuda-13.4-x64.zip",
            423_535_356,
            "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668",
        ),
        "Hy-MT2-7B-Q4_K_M.gguf": (
            "https://huggingface.co/tencent/Hy-MT2-7B-GGUF/resolve/main/Hy-MT2-7B-Q4_K_M.gguf",
            4_624_648_896,
            "9f96256500f3fc1ab4d64336b58f52a949a95ad7516b0c229476eef782f9f77b",
        ),
        "Hy-MT2-1.8B-Q8_0.gguf": (
            "https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/main/Hy-MT2-1.8B-Q8_0.gguf",
            1_908_528_192,
            "5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4",
        ),
    }

    direct_download = {"llama-cpp", "hy-mt2-7b-q4", "hy-mt2-1.8b-q8"}
    found = {
        file.rel_path: (component.file_url(file), file.size_bytes, file.sha256)
        for component in COMPONENTS
        if component.component_id in direct_download
        for file in component.files
    }

    assert found == expected
    assert {file.rel_path for file in get_component("llama-cpp").files} == {
        "llama-b11146-bin-win-cuda-13.4-x64.zip",
        "cudart-llama-bin-win-cuda-13.4-x64.zip",
    }
    assert get_component("llama-cpp").version == "b11146"


def test_pending_hugging_face_components_declare_their_repo_and_patterns() -> None:
    nemotron = get_component("nemotron-en")
    qwen = get_component("qwen3-tts")

    assert (
        nemotron.hf_repo_id
        == "csukuangfj2/sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25"
    )
    assert set(nemotron.allow_patterns or ()) == {
        "tokens.txt",
        "encoder.int8.onnx",
        "decoder.int8.onnx",
        "joiner.int8.onnx",
    }
    assert qwen.hf_repo_id == "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
    assert get_component("silero-vad").version == "6.2.3"


def test_t013_filled_hashes_and_revisions() -> None:
    """T013 (2026-10-01) fijó ficheros, hashes y revisiones a partir de las descargas de los spikes."""
    for component_id in ("nemotron-en", "silero-vad", "qwen3-tts"):
        assert get_component(component_id).files, component_id
    for component_id in ("nemotron-en", "qwen3-tts"):
        assert re.fullmatch(r"[0-9a-f]{40}", get_component(component_id).hf_revision or ""), component_id


def test_only_optional_components_remain_without_files() -> None:
    pending = [component for component in COMPONENTS if not component.files]
    source = Path(manifest.__file__).read_text(encoding="utf-8")

    assert {component.component_id for component in pending} == {"ffmpeg"}
    assert all(component.optional for component in pending)
    assert source.count(PENDING_MARKER) >= len(pending)
    for component in pending:
        assert not is_installed(component.component_id), component.component_id


# --- rutas: component_dir ---


def test_component_dirs_are_under_home() -> None:
    home = AppPaths().home

    for component in COMPONENTS:
        directory = component_dir(component.component_id)
        assert directory.is_relative_to(home), component.component_id
        assert directory != home, component.component_id
        assert ".." not in directory.relative_to(home).parts


def test_component_dirs_follow_the_home_environment_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path / "uno"))
    first = component_dir("llama-cpp")
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path / "dos"))
    second = component_dir("llama-cpp")

    assert first.is_relative_to(tmp_path / "uno")
    assert second.is_relative_to(tmp_path / "dos")
    assert first.relative_to(tmp_path / "uno") == second.relative_to(tmp_path / "dos")


def test_component_dirs_are_distinct() -> None:
    directories = [component_dir(component.component_id) for component in COMPONENTS]

    assert len(directories) == len(set(directories))


def test_binaries_live_under_bin_and_models_under_models() -> None:
    paths = AppPaths()

    assert component_dir("llama-cpp").is_relative_to(paths.bin)
    assert component_dir("hy-mt2-7b-q4").is_relative_to(paths.models)
    assert component_dir("nemotron-en").is_relative_to(paths.models)
    assert component_dir("silero-vad").is_relative_to(paths.models)
    # ffmpeg_path() busca <bin>/ffmpeg/bin/ffmpeg.exe
    assert component_dir("ffmpeg") == paths.bin / "ffmpeg"


def test_unknown_component_raises_key_error() -> None:
    with pytest.raises(KeyError):
        component_dir("no-existe")
    with pytest.raises(KeyError):
        is_installed("no-existe")
    with pytest.raises(KeyError):
        get_component("no-existe")


# --- estado: is_installed ---


@pytest.fixture
def fake_component(monkeypatch: pytest.MonkeyPatch) -> Component:
    """Un componente pequeño añadido a la lista (los reales pesan gigas)."""
    component = make_component()
    monkeypatch.setattr(manifest, "COMPONENTS", (*manifest.COMPONENTS, component))
    return component


def place(component: Component, sizes: dict[str, int]) -> Path:
    base = component_dir(component.component_id)
    for rel_path, size in sizes.items():
        path = base / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    return base


def test_is_installed_when_every_file_exists_with_its_size(fake_component: Component) -> None:
    place(fake_component, {"a.bin": 5, "sub/b.bin": 3})

    assert is_installed("fake-model")


def test_is_not_installed_when_nothing_is_there(fake_component: Component) -> None:
    assert not is_installed("fake-model")


def test_is_not_installed_when_a_file_is_missing(fake_component: Component) -> None:
    place(fake_component, {"a.bin": 5})

    assert not is_installed("fake-model")


@pytest.mark.parametrize("wrong_size", [0, 4, 6])
def test_is_not_installed_when_a_file_has_a_different_size(
    fake_component: Component, wrong_size: int
) -> None:
    place(fake_component, {"a.bin": wrong_size, "sub/b.bin": 3})

    assert not is_installed("fake-model")


def test_is_not_installed_when_a_file_is_a_directory(fake_component: Component) -> None:
    base = place(fake_component, {"a.bin": 5})
    (base / "sub" / "b.bin").mkdir(parents=True)

    assert not is_installed("fake-model")


def test_extra_files_do_not_matter(fake_component: Component) -> None:
    place(fake_component, {"a.bin": 5, "sub/b.bin": 3, "otro.txt": 100})

    assert is_installed("fake-model")


def test_component_without_files_is_never_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = make_component(component_id="vacio", install_dir="models/vacio", files=())
    monkeypatch.setattr(manifest, "COMPONENTS", (*manifest.COMPONENTS, empty))
    component_dir("vacio").mkdir(parents=True)

    assert not is_installed("vacio")


# --- ComponentFile ---


def test_component_file_accepts_valid_values() -> None:
    file = ComponentFile("modelo/pesos.bin", SHA_A, 10)

    assert (file.rel_path, file.sha256, file.size_bytes) == ("modelo/pesos.bin", SHA_A, 10)


@pytest.mark.parametrize(
    ("rel_path", "sha256", "size_bytes", "field_name"),
    [
        ("", SHA_A, 1, "rel_path"),
        ("   ", SHA_A, 1, "rel_path"),
        ("/absoluta.bin", SHA_A, 1, "rel_path"),
        ("C:/absoluta.bin", SHA_A, 1, "rel_path"),
        ("C:relativa.bin", SHA_A, 1, "rel_path"),
        ("../fuera.bin", SHA_A, 1, "rel_path"),
        ("a/../../fuera.bin", SHA_A, 1, "rel_path"),
        ("a\\b.bin", SHA_A, 1, "rel_path"),
        ("a.bin", "", 1, "sha256"),
        ("a.bin", "abc", 1, "sha256"),
        ("a.bin", "A" * 64, 1, "sha256"),  # solo minúsculas
        ("a.bin", "g" * 64, 1, "sha256"),
        ("a.bin", SHA_A, 0, "size_bytes"),
        ("a.bin", SHA_A, -5, "size_bytes"),
        ("a.bin", SHA_A, True, "size_bytes"),
        ("a.bin", SHA_A, 1.5, "size_bytes"),
    ],
)
def test_component_file_rejects_invalid_values(
    rel_path: str, sha256: str, size_bytes: int, field_name: str
) -> None:
    with pytest.raises(ValueError, match=field_name):
        ComponentFile(rel_path, sha256, size_bytes)


# --- Component ---


def test_component_accepts_a_url_source() -> None:
    component = make_component()

    assert component.file_url(component.files[1]) == "https://example.com/models/v1/sub/b.bin"
    assert component.hf_repo_id is None
    assert component.optional is False


def test_file_url_does_not_double_the_slash() -> None:
    component = make_component(source_url="https://example.com/models/v1/")

    assert component.file_url(component.files[0]) == "https://example.com/models/v1/a.bin"


def test_component_accepts_a_hugging_face_source() -> None:
    component = make_component(
        source_url=None,
        hf_repo_id="org/repo",
        hf_revision=COMMIT,
        allow_patterns=["*.json", "model.safetensors"],
        files=(),
    )

    assert component.allow_patterns == ("*.json", "model.safetensors")
    assert component.hf_revision == COMMIT
    with pytest.raises(ValueError, match="source_url"):
        component.file_url(ComponentFile("model.safetensors", SHA_A, 1))


def test_hugging_face_revision_may_be_pending() -> None:
    component = make_component(source_url=None, hf_repo_id="org/repo", files=())

    assert component.hf_revision is None
    assert component.allow_patterns is None


@pytest.mark.parametrize(
    ("overrides", "field_name"),
    [
        ({"component_id": ""}, "component_id"),
        ({"component_id": "Con-Mayúsculas"}, "component_id"),
        ({"component_id": "con espacio"}, "component_id"),
        ({"component_id": "ñandú"}, "component_id"),
        ({"name": ""}, "name"),
        ({"version": " "}, "version"),
        ({"license": ""}, "license"),
        ({"license": "   "}, "license"),
        ({"kind": "otro"}, "kind"),
        ({"install_dir": ""}, "install_dir"),
        ({"install_dir": "/absoluta"}, "install_dir"),
        ({"install_dir": "C:/Datos"}, "install_dir"),
        ({"install_dir": "../fuera"}, "install_dir"),
        ({"install_dir": "."}, "install_dir"),
        ({"install_dir": "models\\x"}, "install_dir"),
        ({"source_url": "http://example.com/models/v1"}, "source_url"),
        ({"source_url": "https://example.com/models/latest"}, "source_url"),
        ({"source_url": "https://example.com/LATEST/modelo.bin"}, "source_url"),
        ({"hf_repo_id": "org/repo"}, "hf_repo_id"),  # no puede tener también source_url
        ({"source_url": None, "hf_repo_id": "sin-organizacion"}, "hf_repo_id"),
        ({"source_url": None, "hf_repo_id": "org/repo", "hf_revision": "main"}, "hf_revision"),
        ({"source_url": None, "hf_repo_id": "org/repo", "hf_revision": "latest"}, "hf_revision"),
        ({"source_url": None, "hf_repo_id": "org/repo", "hf_revision": COMMIT.upper()}, "hf_revision"),
        ({"source_url": None, "hf_repo_id": "org/repo", "hf_revision": COMMIT[:-1]}, "hf_revision"),
        ({"hf_revision": COMMIT}, "hf_revision"),  # revisión sin repo de Hugging Face
        ({"allow_patterns": ("*.json",)}, "allow_patterns"),  # patrones sin repo de Hugging Face
        ({"source_url": None, "hf_repo_id": "org/repo", "allow_patterns": ()}, "allow_patterns"),
        ({"source_url": None, "hf_repo_id": "org/repo", "allow_patterns": ("",)}, "allow_patterns"),
        ({"files": (ComponentFile("a.bin", SHA_A, 1), ComponentFile("a.bin", SHA_B, 2))}, "files"),
        ({"files": ("a.bin",)}, "files"),
        ({"optional": "no"}, "optional"),
    ],
)
def test_component_rejects_invalid_definitions(overrides: dict[str, object], field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_component(**overrides)


def test_component_without_any_source_is_allowed_only_while_pending() -> None:
    # Pendiente de fijar (T013): sin fuente y sin ficheros.
    make_component(source_url=None, files=())

    with pytest.raises(ValueError, match="source_url"):
        make_component(source_url=None)  # con ficheros, pero sin de dónde bajarlos
