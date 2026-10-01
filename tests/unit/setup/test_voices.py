"""Tests de `instanttraductor.setup.voices`: catálogo empaquetado e instalación idempotente (T042)."""

from __future__ import annotations

import hashlib
import io
import wave
from pathlib import Path

import pytest

from instanttraductor.config import DEFAULT_VOICE, AppPaths
from instanttraductor.setup import manifest, voices
from instanttraductor.setup.voices import (
    get_voice,
    install_voices,
    list_voices,
    voice_component_id,
)


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(home=tmp_path / "home")


# --- catálogo ---


def test_voice_ids_are_unique_ascii_identifiers() -> None:
    ids = [voice.voice_id for voice in list_voices()]

    assert len(ids) == len(set(ids))
    assert all(
        voice_id.isascii() and voice_id == voice_id.strip() and " " not in voice_id for voice_id in ids
    )


def test_catalog_has_at_least_three_voices_of_both_genders() -> None:
    catalog = list_voices()

    assert len(catalog) >= 3  # FR-028
    assert {voice.gender for voice in catalog} == {"f", "m"}


def test_every_voice_has_name_source_license_and_ref_text() -> None:
    for voice in list_voices():
        assert voice.name.strip(), voice.voice_id
        assert voice.source.strip(), voice.voice_id
        assert voice.license.strip(), voice.voice_id
        assert voice.ref_text.strip(), voice.voice_id


def test_default_voice_exists_and_is_lucia() -> None:
    voice = get_voice(DEFAULT_VOICE)

    assert voice.voice_id == "es-f-dvx-01"
    assert voice.name == "Lucía"
    assert voice.gender == "f"


def test_catalog_is_sorted_and_stable() -> None:
    ids = [voice.voice_id for voice in list_voices()]

    assert ids == sorted(ids)
    assert list_voices() == list_voices()


def test_unknown_voice_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get_voice("no-existe")


def test_every_wav_is_a_readable_mono_wave() -> None:
    for voice in list_voices():
        with wave.open(io.BytesIO(voice.wav_bytes())) as wav:
            assert wav.getnchannels() == 1, voice.voice_id
            assert wav.getnframes() / wav.getframerate() >= 2.0, voice.voice_id


# --- coherencia con el manifiesto ---


def test_every_voice_has_a_manifest_component_with_matching_hashes() -> None:
    catalog = list_voices()
    voice_components = [c for c in manifest.COMPONENTS if c.kind == "voz"]

    assert {c.component_id for c in voice_components} == {voice_component_id(v.voice_id) for v in catalog}
    for voice in catalog:
        component = manifest.get_component(voice_component_id(voice.voice_id))
        by_name = {file.rel_path: file for file in component.files}
        assert set(by_name) == {voice.wav_name, voice.json_name}
        for name, file in by_name.items():
            data = voices._resource_dir().joinpath(name).read_bytes()
            assert hashlib.sha256(data).hexdigest() == file.sha256, name
            assert len(data) == file.size_bytes, name


def test_manifest_voice_dir_is_the_app_voices_dir(paths: AppPaths) -> None:
    for voice in list_voices():
        component = manifest.get_component(voice_component_id(voice.voice_id))
        assert paths.home / component.install_dir == paths.voices


# --- instalación ---


def installed_files(paths: AppPaths) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths.voices.iterdir())
    }


def test_install_copies_every_voice(paths: AppPaths) -> None:
    changed = install_voices(paths)

    assert set(changed) == {voice.voice_id for voice in list_voices()}
    files = installed_files(paths)
    assert len(files) == 2 * len(list_voices())
    for voice in list_voices():
        assert voice.installed_wav_path(paths).is_file()
        assert files[voice.wav_name] == hashlib.sha256(voice.wav_bytes()).hexdigest()
    assert not list(paths.voices.glob("*.part"))


def test_second_install_changes_nothing(paths: AppPaths) -> None:
    install_voices(paths)
    wav = get_voice(DEFAULT_VOICE).installed_wav_path(paths)
    modified = wav.stat().st_mtime_ns

    assert install_voices(paths) == ()
    assert wav.stat().st_mtime_ns == modified


def test_install_repairs_a_corrupt_file_and_a_missing_one(paths: AppPaths) -> None:
    install_voices(paths)
    default = get_voice(DEFAULT_VOICE)
    other = next(voice for voice in list_voices() if voice.voice_id != DEFAULT_VOICE)
    default.installed_wav_path(paths).write_bytes(b"corrupto")
    (paths.voices / other.json_name).unlink()

    assert set(install_voices(paths)) == {default.voice_id, other.voice_id}
    assert default.installed_wav_path(paths).read_bytes() == default.wav_bytes()
    assert (paths.voices / other.json_name).is_file()
    assert install_voices(paths) == ()


def test_install_uses_the_environment_home_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path / "entorno"))

    install_voices()

    assert get_voice(DEFAULT_VOICE).installed_wav_path(AppPaths()).is_file()
    assert (tmp_path / "entorno" / "voices" / f"{DEFAULT_VOICE}.json").is_file()


def test_install_refuses_a_damaged_package(monkeypatch: pytest.MonkeyPatch, paths: AppPaths) -> None:
    default = get_voice(DEFAULT_VOICE)
    original = manifest.get_component(voice_component_id(DEFAULT_VOICE))
    bad_files = tuple(
        manifest.ComponentFile(file.rel_path, "0" * 64, file.size_bytes) for file in original.files
    )
    damaged = manifest.Component(
        component_id=original.component_id,
        name=original.name,
        version=original.version,
        kind=original.kind,
        license=original.license,
        install_dir=original.install_dir,
        package=original.package,
        package_dir=original.package_dir,
        files=bad_files,
    )
    others = tuple(c for c in manifest.COMPONENTS if c.component_id != original.component_id)
    monkeypatch.setattr(manifest, "COMPONENTS", (*others, damaged))

    with pytest.raises(ValueError, match="sha256"):
        install_voices(paths)
    assert not default.installed_wav_path(paths).exists()
