"""Línea de comandos (T032, T037, T043): opciones y códigos de salida de contracts/cli.md, sin motores."""

from __future__ import annotations

from pathlib import Path

import pytest

from instanttraductor import cli
from instanttraductor.config import load_settings


@pytest.fixture(autouse=True)
def temp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Una carpeta de datos vacía: nada preparado, ajustes y registro aparte."""
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("command", [["directo"], ["archivo", "entrada.mp4"]])
def test_without_preparation_it_exits_with_code_3(
    command: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(command) == cli.EXIT_NOT_PREPARED
    assert "instanttraductor preparar" in capsys.readouterr().out


def test_a_missing_input_file_exits_with_code_5(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "_missing_components", lambda: [])
    assert cli.main(["archivo", str(tmp_path / "no_existe.mp4")]) == cli.EXIT_BAD_INPUT
    assert not (tmp_path / "no_existe_es").exists()


def test_an_unknown_voice_for_archivo_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_missing_components", lambda: [])
    assert cli.main(["archivo", "entrada.mp4", "--voz", "no-existe"]) == cli.EXIT_USAGE


@pytest.mark.parametrize("argv", [[], ["archivo"], ["directo", "--volumen", "201"], ["voces", "--otra"]])
def test_bad_usage_exits_with_code_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(argv)
    assert exited.value.code == cli.EXIT_USAGE


def test_voces_lists_the_catalog_and_marks_the_chosen_one(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["voces"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "es-f-dvx-01" in out and "Lucía" in out and "●" in out


def test_voces_elegir_saves_the_voice(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["voces", "--elegir", "es-f-dvx-08"]) == cli.EXIT_OK
    assert load_settings().voice == "es-f-dvx-08"


def test_voces_elegir_rejects_an_unknown_voice() -> None:
    assert cli.main(["voces", "--elegir", "no-existe"]) == cli.EXIT_USAGE
    assert load_settings().voice == "es-f-dvx-01"


def test_voces_escuchar_without_samples_asks_for_preparar(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["voces", "--escuchar", "es-f-dvx-01"]) == cli.EXIT_NOT_PREPARED
    assert "preparar" in capsys.readouterr().out


def test_an_unknown_voice_for_directo_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_missing_components", lambda: [])
    assert cli.main(["directo", "--voz", "no-existe"]) == cli.EXIT_USAGE


def test_an_unexpected_error_exits_with_code_1_and_a_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(args: object) -> int:
        raise RuntimeError("algo raro")

    monkeypatch.setattr(cli, "cmd_voces", explode)
    assert cli.main(["voces"]) == cli.EXIT_ERROR
    out = capsys.readouterr().out
    assert "Error inesperado: algo raro" in out and "registro" in out


# --- spec 002: idioma y app que se escucha ------------------------------------------------------------
from instanttraductor.audio.app_types import AppIdentity, AudioApp  # noqa: E402

CHROME = AppIdentity(r"C:\Apps\Chrome\chrome.exe", "Google Chrome", 100, 1.0)
DISCORD = AppIdentity(r"C:\Apps\Discord\app-1.0\Discord.exe", "Discord", 200, 2.0)


@pytest.fixture
def fake_apps(monkeypatch: pytest.MonkeyPatch) -> list[AudioApp]:
    import instanttraductor.audio.apps as apps_module

    apps = [AudioApp(CHROME, True, -20.0), AudioApp(DISCORD, False, -90.0)]
    monkeypatch.setattr(apps_module, "list_audio_apps", lambda **_: list(apps))

    def find(name: str, **_: object) -> list[AppIdentity]:
        return [
            a.identity
            for a in apps
            if name.lower() in (a.identity.display_name + a.identity.exe_path).lower()
        ]

    monkeypatch.setattr(apps_module, "find_app", find)
    return apps


def resolve(argv: list[str], settings=None):  # type: ignore[no-untyped-def]
    from rich.console import Console

    from instanttraductor.config import Settings

    args = cli.build_parser().parse_args(["directo", *argv])
    base = settings or Settings()
    return cli._resolve_listening(args, base, base, Console(file=None))


def test_idioma_shows_and_saves_the_source_language(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["idioma"]) == cli.EXIT_OK
    assert "inglés" in capsys.readouterr().out
    assert cli.main(["idioma", "--elegir", "ja"]) == cli.EXIT_OK
    assert load_settings().source_language == "ja"


def test_an_unknown_language_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exited:
        cli.main(["directo", "--idioma", "es"])
    assert exited.value.code == cli.EXIT_USAGE


def test_app_options_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        cli.main(["directo", "--app", "chrome", "--todo-el-pc"])


def test_app_by_name_is_used_only_for_this_session(fake_apps: list[AudioApp]) -> None:
    saved, session = resolve(["--app", "chrome"])
    assert session.capture_app == CHROME.exe_path
    assert saved.capture_app == ""
    assert load_settings().capture_app == ""


def test_an_app_that_is_not_open_is_a_usage_error(fake_apps: list[AudioApp]) -> None:
    assert resolve(["--app", "vlc"]) == cli.EXIT_USAGE


def test_elegir_app_saves_the_chosen_app(fake_apps: list[AudioApp], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    saved, session = resolve(["--elegir-app"])
    assert session.capture_app == saved.capture_app == DISCORD.exe_path
    assert load_settings().capture_app == DISCORD.exe_path


def test_elegir_app_can_be_cancelled(fake_apps: list[AudioApp], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert resolve(["--elegir-app"]) == cli.EXIT_USAGE


def test_todo_el_pc_ignores_the_saved_app_for_this_session(fake_apps: list[AudioApp]) -> None:
    from instanttraductor.config import Settings

    _, session = resolve(["--todo-el-pc"], Settings(capture_app=CHROME.exe_path))
    assert session.capture_app == ""


def test_a_saved_app_that_moved_after_an_update_is_found_by_its_exe_name(fake_apps: list[AudioApp]) -> None:
    from instanttraductor.config import Settings

    old = r"C:\Apps\Discord\app-0.9\Discord.exe"  # ya no existe: Discord se actualizó a app-1.0
    saved, session = resolve([], Settings(capture_app=old))
    assert session.capture_app == saved.capture_app == DISCORD.exe_path
