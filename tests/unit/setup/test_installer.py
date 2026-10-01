"""Tests de `instanttraductor.setup.installer` (T041) con un descargador y un sistema falsos.

Sin red, sin GPU y sin tocar el home real: cada test usa un `home` temporal.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from rich.console import Console

from instanttraductor.config import AppPaths
from instanttraductor.setup import installer, manifest
from instanttraductor.setup.installer import (
    SPACE_MARGIN_BYTES,
    CommandResult,
    ComponentState,
    GpuInfo,
    prepare,
)
from instanttraductor.setup.manifest import Component, ComponentFile

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def file_of(rel_path: str, data: bytes) -> ComponentFile:
    return ComponentFile(rel_path, sha(data), len(data))


# --- contenido falso ---

A_BIN = b"A" * 100
B_BIN = b"B" * 40
URL_BASE = "https://example.com/models/v1"

ZIP_BYTES = make_zip({"llama-server.exe": b"EXE" * 20, "ggml.dll": b"DLL" * 10})
ZIP_URL = "https://example.com/bin/v1/pack.zip"

HF_FILES = {"weights.bin": b"W" * 300, "config.json": b'{"k": 1}', "sub/tok.json": b"{}"}

WHEEL_BYTES = make_zip(
    {
        "fake_vad/data/model.onnx": b"ONNX" * 25,
        "fake_vad/__init__.py": b"",
        "fake_vad-1.0.dist-info/licenses/LICENSE": b"MIT License",
    }
)
PYPI_JSON_URL = "https://pypi.org/pypi/fake-vad/1.0/json"
WHEEL_URL = "https://files.example/fake_vad-1.0-py3-none-any.whl"

URL_COMPONENT = Component(
    component_id="fake-url",
    name="Modelo por URL",
    version="1.0",
    kind="modelo",
    license="MIT",
    install_dir="models/fake-url",
    source_url=URL_BASE,
    files=(file_of("a.bin", A_BIN), file_of("sub/b.bin", B_BIN)),
)
ZIP_COMPONENT = Component(
    component_id="fake-zip",
    name="Binario en zip",
    version="b1",
    kind="binario",
    license="MIT",
    install_dir="bin/fake-zip",
    source_url="https://example.com/bin/v1",
    files=(file_of("pack.zip", ZIP_BYTES),),
)
HF_COMPONENT = Component(
    component_id="fake-hf",
    name="Modelo de Hugging Face",
    version="r1",
    kind="modelo",
    license="Apache-2.0",
    install_dir="models/fake-hf",
    hf_repo_id="org/repo",
    hf_revision=COMMIT,
    allow_patterns=("*.json", "weights.bin"),
    files=tuple(file_of(rel, data) for rel, data in HF_FILES.items()),
)
PYPI_COMPONENT = Component(
    component_id="fake-pypi",
    name="Modelo del wheel",
    version="1.0",
    kind="modelo",
    license="MIT",
    install_dir="models/fake-pypi",
    source_url=PYPI_JSON_URL,
    files=(file_of("model.onnx", b"ONNX" * 25), file_of("LICENSE", b"MIT License")),
)
FFMPEG_COMPONENT = Component(
    component_id="ffmpeg",
    name="ffmpeg",
    version="9.0.1",
    kind="binario",
    license="GPL",
    install_dir="bin/ffmpeg",
    optional=True,
)
FAKE_COMPONENTS = (URL_COMPONENT, ZIP_COMPONENT, HF_COMPONENT, PYPI_COMPONENT, FFMPEG_COMPONENT)
VOICE_COMPONENTS = tuple(c for c in manifest.COMPONENTS if c.kind == "voz")


@dataclass
class FakeDownloader:
    """Sirve el contenido de los componentes falsos y apunta cada llamada."""

    urls: dict[str, bytes] = field(
        default_factory=lambda: {
            f"{URL_BASE}/a.bin": A_BIN,
            f"{URL_BASE}/sub/b.bin": B_BIN,
            ZIP_URL: ZIP_BYTES,
            WHEEL_URL: WHEEL_BYTES,
        }
    )
    hf: dict[str, dict[str, bytes]] = field(default_factory=lambda: {"org/repo": dict(HF_FILES)})
    metadata: dict[str, dict[str, object]] = field(
        default_factory=lambda: {
            PYPI_JSON_URL: {
                "urls": [
                    {
                        "filename": "fake_vad-1.0-py3-none-any.whl",
                        "url": WHEEL_URL,
                        "digests": {"sha256": sha(WHEEL_BYTES)},
                    }
                ]
            }
        }
    )
    calls: list[tuple[object, ...]] = field(default_factory=list)
    fail_urls: set[str] = field(default_factory=set)

    def download_file(self, url: str, dest: Path, progress: Callable[[int], None] | None = None) -> None:
        self.calls.append(("file", url))
        if url in self.fail_urls:
            raise ConnectionError(f"sin red para {url}")
        data = self.urls[url]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        if progress is not None:
            progress(len(data))

    def get_json(self, url: str) -> dict[str, object]:
        self.calls.append(("json", url))
        return self.metadata[url]

    def snapshot_download(
        self,
        *,
        repo_id: str,
        revision: str | None,
        allow_patterns: Sequence[str] | None,
        local_dir: Path,
    ) -> None:
        self.calls.append(("hf", repo_id, revision, allow_patterns))
        for rel, data in self.hf[repo_id].items():
            target = Path(local_dir) / rel
            if not target.exists():  # como Hugging Face: lo que ya está al día no se vuelve a bajar
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

    def downloaded(self, kind: str) -> list[tuple[object, ...]]:
        return [call for call in self.calls if call[0] == kind]


@dataclass
class FakeSystem:
    """Sistema falso: build, GPU, disco libre, ffmpeg y `uv`."""

    build: int = 26200
    gpu: GpuInfo | None = field(default_factory=lambda: GpuInfo("RTX 5070", "591.44", (13, 1)))
    free: int = 10**12
    ffmpeg: Path | None = Path("C:/ffmpeg/bin/ffmpeg.exe")
    env_synced: bool = False
    sync_returncode: int = 0
    commands: list[tuple[str, ...]] = field(default_factory=list)

    def windows_build(self) -> int:
        return self.build

    def gpu_info(self) -> GpuInfo | None:
        return self.gpu

    def free_bytes(self, path: Path) -> int:
        return self.free

    def find_ffmpeg(self, paths: AppPaths) -> Path | None:
        return self.ffmpeg

    def run_command(self, args: Sequence[str]) -> CommandResult:
        command = tuple(args)
        self.commands.append(command)
        if "--check" in command:
            return CommandResult(0 if self.env_synced else 1, "")
        if self.sync_returncode == 0:
            self.env_synced = True
        return CommandResult(self.sync_returncode, "error de uv" if self.sync_returncode else "")

    def sync_calls(self) -> list[tuple[str, ...]]:
        return [c for c in self.commands if c[:2] == ("uv", "sync") and "--check" not in c]


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(home=tmp_path / "home")


@pytest.fixture
def downloader() -> FakeDownloader:
    return FakeDownloader()


@pytest.fixture
def system() -> FakeSystem:
    return FakeSystem()


def run(
    paths: AppPaths,
    downloader: FakeDownloader,
    system: FakeSystem,
    *,
    components: Sequence[Component] = FAKE_COMPONENTS,
    check_only: bool = False,
) -> tuple[installer.PrepareResult, str]:
    output = io.StringIO()
    console = Console(file=output, width=200, force_terminal=False, color_system=None)
    result = prepare(
        paths,
        check_only=check_only,
        downloader=downloader,
        console=console,
        components=tuple(components),
        system=system,
    )
    return result, output.getvalue()


def report_of(result: installer.PrepareResult, component_id: str) -> installer.ComponentReport:
    return next(r for r in result.components if r.component.component_id == component_id)


def states(result: installer.PrepareResult) -> dict[str, ComponentState]:
    return {r.component.component_id: r.state for r in result.components}


# --- primera y segunda ejecución ---


def test_first_run_downloads_everything_and_verifies_it(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    result, _ = run(paths, downloader, system)

    assert result.ok
    assert result.exit_code == 0
    assert set(result.downloaded) == {"fake-url", "fake-zip", "fake-hf", "fake-pypi"}
    for component in (URL_COMPONENT, ZIP_COMPONENT, HF_COMPONENT, PYPI_COMPONENT):
        assert report_of(result, component.component_id).state is ComponentState.VERIFIED
        base = paths.home / component.install_dir
        for file in component.files:
            assert hashlib.sha256((base / file.rel_path).read_bytes()).hexdigest() == file.sha256
    assert states(result)["ffmpeg"] is ComponentState.VERIFIED
    assert result.voice_env.ok
    assert len(system.sync_calls()) == 1


def test_each_component_goes_absent_downloaded_verified(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    result, _ = run(paths, downloader, system)

    assert report_of(result, "fake-url").history == (
        ComponentState.ABSENT,
        ComponentState.DOWNLOADED,
        ComponentState.VERIFIED,
    )


def test_second_run_downloads_nothing(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)
    downloader.calls.clear()
    system.commands.clear()

    result, _ = run(paths, downloader, system)

    assert result.ok
    assert downloader.calls == []  # SC-008
    assert result.downloaded == ()
    assert system.sync_calls() == []  # el entorno de la voz ya estaba al día
    assert report_of(result, "fake-url").history == (ComponentState.VERIFIED,)
    assert all(ComponentState.DOWNLOADED not in r.history for r in result.components)


def test_corrupt_file_is_downloaded_again_and_the_rest_is_kept(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)
    base = paths.home / URL_COMPONENT.install_dir
    (base / "a.bin").write_bytes(b"X" * len(A_BIN))  # mismo tamaño, otro contenido
    downloader.calls.clear()

    result, _ = run(paths, downloader, system)

    assert result.ok
    assert downloader.calls == [("file", f"{URL_BASE}/a.bin")]
    assert (base / "a.bin").read_bytes() == A_BIN
    assert report_of(result, "fake-url").history[:2] == (ComponentState.CORRUPT, ComponentState.DOWNLOADED)
    assert report_of(result, "fake-url").state is ComponentState.VERIFIED


def test_file_with_a_wrong_size_counts_as_corrupt_and_is_replaced(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)
    target = paths.home / URL_COMPONENT.install_dir / "sub" / "b.bin"
    target.write_bytes(b"corto")
    downloader.calls.clear()

    result, _ = run(paths, downloader, system)

    assert result.ok
    assert downloader.calls == [("file", f"{URL_BASE}/sub/b.bin")]
    assert target.read_bytes() == B_BIN


def test_corrupt_hugging_face_file_is_removed_before_the_snapshot(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)
    target = paths.home / HF_COMPONENT.install_dir / "weights.bin"
    target.write_bytes(b"Z" * len(HF_FILES["weights.bin"]))
    downloader.calls.clear()

    result, _ = run(paths, downloader, system)

    assert result.ok
    assert downloader.calls == [("hf", "org/repo", COMMIT, ("*.json", "weights.bin"))]
    assert target.read_bytes() == HF_FILES["weights.bin"]


def test_missing_file_of_a_component_is_downloaded_again(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)
    (paths.home / URL_COMPONENT.install_dir / "sub" / "b.bin").unlink()
    downloader.calls.clear()

    result, _ = run(paths, downloader, system)

    assert result.ok
    assert downloader.calls == [("file", f"{URL_BASE}/sub/b.bin")]
    assert report_of(result, "fake-url").history[0] is ComponentState.ABSENT


# --- fuentes ---


def test_direct_downloads_leave_no_partial_files(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)

    assert not list(paths.home.rglob("*.part"))


def test_zip_is_extracted_next_to_the_archive_and_only_once(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)
    base = paths.home / ZIP_COMPONENT.install_dir
    assert (base / "pack.zip").is_file()
    assert (base / "llama-server.exe").read_bytes() == b"EXE" * 20
    assert (base / "ggml.dll").is_file()

    (base / "llama-server.exe").unlink()  # falta algo extraído: se vuelve a extraer, sin descargar
    downloader.calls.clear()
    result, _ = run(paths, downloader, system)

    assert result.ok
    assert downloader.calls == []
    assert (base / "llama-server.exe").read_bytes() == b"EXE" * 20


def test_zip_with_paths_outside_its_folder_is_rejected(paths: AppPaths, system: FakeSystem) -> None:
    evil = make_zip({"../fuera.txt": b"mal"})
    component = Component(
        component_id="evil-zip",
        name="Zip malicioso",
        version="1",
        kind="binario",
        license="MIT",
        install_dir="bin/evil-zip",
        source_url="https://example.com/evil",
        files=(file_of("evil.zip", evil),),
    )
    downloader = FakeDownloader(urls={"https://example.com/evil/evil.zip": evil})

    result, _ = run(paths, downloader, system, components=(component,))

    assert not result.ok
    assert not (paths.home / "bin" / "fuera.txt").exists()
    assert report_of(result, "evil-zip").state is ComponentState.DOWNLOADED


def test_pypi_wheel_members_are_extracted_by_name(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)

    base = paths.home / PYPI_COMPONENT.install_dir
    assert (base / "model.onnx").read_bytes() == b"ONNX" * 25
    assert (base / "LICENSE").read_bytes() == b"MIT License"
    assert not list(base.glob("*.whl*"))
    assert downloader.downloaded("json") == [("json", PYPI_JSON_URL)]


def test_pypi_wheel_with_a_wrong_digest_is_rejected(paths: AppPaths, system: FakeSystem) -> None:
    downloader = FakeDownloader()
    downloader.metadata[PYPI_JSON_URL]["urls"][0]["digests"]["sha256"] = "0" * 64  # type: ignore[index]

    result, _ = run(paths, downloader, system, components=(PYPI_COMPONENT,))

    assert not result.ok
    assert not (paths.home / PYPI_COMPONENT.install_dir / "model.onnx").exists()
    assert report_of(result, "fake-pypi").state is ComponentState.ABSENT
    assert "sha256" in report_of(result, "fake-pypi").detail


def test_hugging_face_component_without_a_pinned_revision_is_not_downloaded(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    component = Component(
        component_id="sin-revision",
        name="Sin revisión",
        version="1",
        kind="modelo",
        license="MIT",
        install_dir="models/sin-revision",
        hf_repo_id="org/repo",
        files=(file_of("config.json", HF_FILES["config.json"]),),
    )

    result, _ = run(paths, downloader, system, components=(component,))

    assert not result.ok
    assert downloader.calls == []
    assert "revisión" in report_of(result, "sin-revision").detail


# --- fallos ---


def test_wrong_hash_after_download_leaves_no_file_and_is_corrupt(paths: AppPaths, system: FakeSystem) -> None:
    downloader = FakeDownloader()
    downloader.urls[f"{URL_BASE}/a.bin"] = b"Q" * len(A_BIN)

    result, _ = run(paths, downloader, system, components=(URL_COMPONENT,))

    assert not result.ok
    assert result.exit_code == 3
    base = paths.home / URL_COMPONENT.install_dir
    assert not (base / "a.bin").exists()
    assert not list(base.rglob("*.part"))
    report = report_of(result, "fake-url")
    assert report.state is ComponentState.CORRUPT
    assert report.history[-2:] == (ComponentState.DOWNLOADED, ComponentState.CORRUPT)
    assert (base / "sub" / "b.bin").read_bytes() == B_BIN  # el otro fichero sí se bajó


def test_a_failing_download_does_not_stop_the_other_components(paths: AppPaths, system: FakeSystem) -> None:
    downloader = FakeDownloader(fail_urls={f"{URL_BASE}/a.bin"})

    result, _ = run(paths, downloader, system)

    assert result.exit_code == 3
    assert report_of(result, "fake-url").state is ComponentState.ABSENT
    assert "sin red" in report_of(result, "fake-url").detail
    assert report_of(result, "fake-hf").state is ComponentState.VERIFIED
    assert report_of(result, "fake-zip").state is ComponentState.VERIFIED
    assert "fake-url" not in result.downloaded


def test_failing_voice_environment_gives_exit_code_3(paths: AppPaths, downloader: FakeDownloader) -> None:
    system = FakeSystem(sync_returncode=2)

    result, _ = run(paths, downloader, system)

    assert result.exit_code == 3
    assert not result.voice_env.ok
    assert "error de uv" in result.voice_env.detail
    assert all(r.state is ComponentState.VERIFIED for r in result.components)


# --- comprobaciones previas (código 6) ---


@pytest.mark.parametrize(
    ("overrides", "check_name"),
    [
        ({"build": 19045}, "windows"),
        ({"gpu": None}, "gpu"),
        ({"gpu": GpuInfo("RTX 3060", "550.10", (12, 4))}, "gpu"),
    ],
)
def test_unmet_requirements_give_exit_code_6_and_download_nothing(
    paths: AppPaths, downloader: FakeDownloader, overrides: dict[str, object], check_name: str
) -> None:
    system = FakeSystem(**overrides)  # type: ignore[arg-type]

    result, text = run(paths, downloader, system)

    assert result.exit_code == 6
    assert not result.ok
    assert downloader.calls == []
    assert system.commands == []
    failed = {check.name for check in result.checks if not check.ok and check.blocking}
    assert failed == {check_name}
    assert not paths.home.exists()
    assert "FALLA" in text


def test_minimum_requirements_are_accepted(paths: AppPaths, downloader: FakeDownloader) -> None:
    system = FakeSystem(
        build=installer.MIN_WINDOWS_BUILD, gpu=GpuInfo("RTX", "580", installer.MIN_CUDA_VERSION)
    )

    result, _ = run(paths, downloader, system)

    assert result.exit_code == 0


def test_lack_of_space_is_detected_before_downloading(paths: AppPaths, downloader: FakeDownloader) -> None:
    missing = sum(f.size_bytes for c in FAKE_COMPONENTS for f in c.files)
    system = FakeSystem(free=missing + SPACE_MARGIN_BYTES - 1)

    result, text = run(paths, downloader, system)

    assert result.exit_code == 6
    assert downloader.calls == []
    assert system.commands == []
    assert [c.name for c in result.checks if not c.ok and c.blocking] == ["espacio"]
    assert "FALLA" in text


def test_exactly_enough_space_is_accepted(paths: AppPaths, downloader: FakeDownloader) -> None:
    missing = sum(f.size_bytes for c in FAKE_COMPONENTS for f in c.files)
    system = FakeSystem(free=missing + SPACE_MARGIN_BYTES)

    result, _ = run(paths, downloader, system)

    assert result.exit_code == 0


def test_space_only_counts_what_is_missing(paths: AppPaths, downloader: FakeDownloader) -> None:
    run(paths, downloader, FakeSystem())
    (paths.home / URL_COMPONENT.install_dir / "sub" / "b.bin").unlink()
    system = FakeSystem(free=len(B_BIN) + SPACE_MARGIN_BYTES, env_synced=True)

    result, _ = run(paths, downloader, system)

    assert result.exit_code == 0


# --- ffmpeg ---


def test_missing_ffmpeg_is_optional_and_does_not_fail(paths: AppPaths, downloader: FakeDownloader) -> None:
    system = FakeSystem(ffmpeg=None)

    result, text = run(paths, downloader, system)

    assert result.exit_code == 0
    assert states(result)["ffmpeg"] is ComponentState.OPTIONAL_MISSING
    assert "falta (opcional)" in text
    ffmpeg_check = next(check for check in result.checks if check.name == "ffmpeg")
    assert not ffmpeg_check.blocking


# --- --comprobar ---


def test_check_only_downloads_and_installs_nothing(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    result, _ = run(paths, downloader, system, check_only=True)

    assert result.exit_code == 3
    assert downloader.calls == []
    assert system.sync_calls() == []
    assert result.downloaded == ()
    assert not paths.home.exists()
    assert set(states(result).values()) == {ComponentState.ABSENT, ComponentState.VERIFIED}
    assert states(result)["fake-url"] is ComponentState.ABSENT
    assert not result.voice_env.ok


def test_check_only_after_preparing_is_ok(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)
    downloader.calls.clear()

    result, _ = run(paths, downloader, system, check_only=True)

    assert result.ok
    assert downloader.calls == []
    assert len(system.sync_calls()) == 1  # solo el de la primera ejecución


def test_check_only_reports_a_corrupt_file_without_touching_it(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)
    target = paths.home / URL_COMPONENT.install_dir / "a.bin"
    target.write_bytes(b"X" * len(A_BIN))

    result, _ = run(paths, downloader, system, check_only=True)

    assert result.exit_code == 3
    assert report_of(result, "fake-url").state is ComponentState.CORRUPT
    assert target.read_bytes() == b"X" * len(A_BIN)


def test_check_only_still_gives_6_when_the_pc_does_not_meet_the_requirements(
    paths: AppPaths, downloader: FakeDownloader
) -> None:
    result, _ = run(paths, downloader, FakeSystem(gpu=None), check_only=True)

    assert result.exit_code == 6


# --- entorno de la voz ---


def test_voice_environment_uses_uv_sync_frozen_for_the_qwen3_project(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system, components=(URL_COMPONENT,))

    check, sync = system.commands
    assert check[:2] == ("uv", "sync")
    assert {"--frozen", "--check", "--project"} <= set(check)
    assert sync[:2] == ("uv", "sync")
    assert "--frozen" in sync
    assert "--check" not in sync
    assert Path(sync[sync.index("--project") + 1]).parts[-2:] == ("engines", "tts-qwen3")


# --- voces ---


def test_voices_are_installed_by_prepare(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    result, _ = run(paths, downloader, system, components=(*VOICE_COMPONENTS, FFMPEG_COMPONENT))

    assert result.ok
    assert downloader.calls == []  # empaquetadas: sin red
    assert result.downloaded == ()
    assert len(result.voices_installed) == len(VOICE_COMPONENTS)
    for component in VOICE_COMPONENTS:
        assert report_of(result, component.component_id).state is ComponentState.VERIFIED
        for file in component.files:
            assert (paths.voices / file.rel_path).is_file()


def test_second_run_copies_no_voices(paths: AppPaths, downloader: FakeDownloader, system: FakeSystem) -> None:
    run(paths, downloader, system, components=VOICE_COMPONENTS)

    result, _ = run(paths, downloader, system, components=VOICE_COMPONENTS)

    assert result.ok
    assert result.voices_installed == ()


def test_check_only_does_not_copy_voices(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    result, _ = run(paths, downloader, system, components=VOICE_COMPONENTS, check_only=True)

    assert result.exit_code == 3
    assert not paths.voices.exists()
    assert all(r.state is ComponentState.ABSENT for r in result.components)


# --- tabla ---


def test_table_lists_name_version_license_size_and_state(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    _, text = run(paths, downloader, system)

    for component in FAKE_COMPONENTS:
        assert component.name in text
        assert component.license in text
    assert "1.0" in text
    assert "verificado" in text
    for heading in ("Componente", "Versión", "Licencia", "Tamaño", "Estado"):
        assert heading in text


def test_table_shows_corrupt_and_absent_states(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    run(paths, downloader, system)
    (paths.home / URL_COMPONENT.install_dir / "a.bin").write_bytes(b"x")
    (paths.home / HF_COMPONENT.install_dir / "weights.bin").unlink()

    _, text = run(paths, downloader, system, check_only=True)

    assert "corrupto" in text
    assert "ausente" in text


# --- el manifiesto real ---


def test_real_manifest_components_are_all_handled(
    paths: AppPaths, downloader: FakeDownloader, system: FakeSystem
) -> None:
    """Con `--comprobar` sobre un home vacío, el manifiesto real da un estado a cada componente."""
    result, _ = run(paths, downloader, system, components=manifest.COMPONENTS, check_only=True)

    assert len(result.components) == len(manifest.COMPONENTS)
    assert result.exit_code == 3
    assert downloader.calls == []


def test_the_real_pypi_component_is_recognised_by_its_metadata_url() -> None:
    assert installer.is_pypi_metadata_url(manifest.get_component("silero-vad").source_url or "")
    assert not installer.is_pypi_metadata_url("https://example.com/modelo.bin")


def test_default_arguments_do_not_touch_the_real_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path / "entorno"))
    downloader = FakeDownloader()

    output = io.StringIO()
    result = prepare(
        check_only=True,
        downloader=downloader,
        console=Console(file=output, width=200),
        components=(URL_COMPONENT,),
        system=FakeSystem(),
    )

    assert result.exit_code == 3
    assert not (tmp_path / "entorno").exists()


# --- nvidia-smi ---


def test_parse_cuda_version_reads_the_nvidia_smi_header() -> None:
    header = "| NVIDIA-SMI 591.44   Driver Version: 591.44   CUDA Version: 13.1 |"

    assert installer.parse_cuda_version(header) == (13, 1)
    assert installer.parse_cuda_version("sin versión") is None


def test_parse_cuda_version_reads_the_umd_header_of_recent_drivers() -> None:
    header = "| NVIDIA-SMI 616.64     KMD Version: 616.64        CUDA UMD Version: 13.4     |"

    assert installer.parse_cuda_version(header) == (13, 4)
