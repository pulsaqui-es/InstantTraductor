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
