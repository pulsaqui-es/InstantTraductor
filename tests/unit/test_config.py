"""Tests de `instanttraductor.config`: ajustes (TOML con claves en español) y rutas estándar."""

from __future__ import annotations

import logging
import shutil
import tomllib
from dataclasses import fields
from pathlib import Path

import pytest
import tomli_w

from instanttraductor.config import (
    DEFAULT_VOICE,
    TOML_KEYS,
    AppPaths,
    Settings,
    ffmpeg_path,
    load_settings,
    save_settings,
    settings_path,
)

# --- utilidades ---


@pytest.fixture
def toml_file(tmp_path: Path) -> Path:
    """Ruta de un `ajustes.toml` temporal (todavía sin crear)."""
    return tmp_path / "ajustes.toml"


@pytest.fixture
def warnings_log(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.WARNING)
    return caplog


def warning_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Mensajes de los `logging.warning` capturados (y comprueba que no hay nada más grave)."""
    assert all(record.levelno == logging.WARNING for record in caplog.records)
    return [record.getMessage() for record in caplog.records]


# --- Settings: valores por defecto ---


def test_defaults_match_data_model() -> None:
    settings = Settings()

    assert settings.voice == DEFAULT_VOICE
    assert settings.voice_volume == 1.0
    assert settings.accelerate_after_s == 3.0
    assert settings.concise_after_s == 5.0
    assert settings.drop_after_s == 8.0
    assert settings.max_speed == 1.25
    assert settings.max_untranslated_s == 6.0
    assert settings.context_utterances == 4
    assert settings.glossary == ()
    assert settings.show_text is False
    assert settings.save_audio is False


def test_toml_keys_map_every_attribute_to_its_spanish_key() -> None:
    assert set(TOML_KEYS) == {field.name for field in fields(Settings)}
    assert dict(TOML_KEYS) == {
        "voice": "voz",
        "voice_volume": "volumen_voz",
        "accelerate_after_s": "umbral_acelerar_s",
        "concise_after_s": "umbral_resumir_s",
        "drop_after_s": "umbral_descartar_s",
        "max_speed": "velocidad_max",
        "max_untranslated_s": "max_habla_sin_traducir_s",
        "context_utterances": "frases_de_contexto",
        "glossary": "glosario",
        "show_text": "mostrar_texto",
        "save_audio": "guardar_audio",
    }


def test_integers_are_stored_as_floats_in_numeric_fields() -> None:
    settings = Settings(voice_volume=1, max_untranslated_s=6)

    assert isinstance(settings.voice_volume, float)
    assert isinstance(settings.max_untranslated_s, float)


def test_glossary_accepts_a_mapping_and_stores_pairs() -> None:
    settings = Settings(glossary={"juice": "zumo", "cell phone": "móvil"})

    assert settings.glossary == (("juice", "zumo"), ("cell phone", "móvil"))


def test_to_toml_dict_uses_spanish_keys() -> None:
    settings = Settings(voice="es-f-01", glossary=(("juice", "zumo"),))

    data = settings.to_toml_dict()

    assert set(data) == set(TOML_KEYS.values())
    assert data["voz"] == "es-f-01"
    assert data["glosario"] == {"juice": "zumo"}


# --- Settings: rangos ---


@pytest.mark.parametrize(
    "kwargs",
    [
        {"voice_volume": 0.0},
        {"voice_volume": 2.0},
        {"accelerate_after_s": 0.5, "concise_after_s": 0.75, "drop_after_s": 1.0},
        {"max_speed": 1.0},
        {"max_speed": 1.5},
        {"max_untranslated_s": 2},
        {"max_untranslated_s": 15},
        {"context_utterances": 0},
        {"context_utterances": 8},
    ],
)
def test_range_limits_are_inclusive(kwargs: dict[str, float]) -> None:
    Settings(**kwargs)  # no debe lanzar


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("voice", ""),
        ("voice", "   "),
        ("voice", "María"),
        ("voice", "con espacio"),
        ("voice", "../fuera"),
        ("voice", 3),
        ("voice_volume", -0.1),
        ("voice_volume", 2.1),
        ("voice_volume", float("nan")),
        ("voice_volume", float("inf")),
        ("voice_volume", 10**400),
        ("voice_volume", True),
        ("voice_volume", "alto"),
        ("accelerate_after_s", 0),
        ("accelerate_after_s", -1.0),
        ("max_speed", 0.99),
        ("max_speed", 1.51),
        ("max_untranslated_s", 1.99),
        ("max_untranslated_s", 15.01),
        ("context_utterances", -1),
        ("context_utterances", 9),
        ("context_utterances", 2.5),
        ("context_utterances", True),
        ("show_text", "sí"),
        ("show_text", 1),
        ("save_audio", None),
        ("glossary", "juice=zumo"),
        ("glossary", {"juice": 3}),
        ("glossary", {"": "zumo"}),
        ("glossary", (("juice",),)),
    ],
)
def test_out_of_range_value_in_constructor_raises(attribute: str, value: object) -> None:
    with pytest.raises(ValueError, match=rf"\({attribute}\)"):
        Settings(**{attribute: value})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"concise_after_s": 3.0},  # no supera a umbral_acelerar_s (3,0)
        {"concise_after_s": 2.0},
        {"drop_after_s": 5.0},  # no supera a umbral_resumir_s (5,0)
        {"drop_after_s": 4.0},
        {"accelerate_after_s": 6.0},  # deja de ser menor que umbral_resumir_s (5,0)
    ],
)
def test_thresholds_out_of_order_in_constructor_raise(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="umbral_acelerar_s < umbral_resumir_s < umbral_descartar_s"):
        Settings(**kwargs)


@pytest.mark.parametrize("voice", ["es-m-tux", "es-f-01", "voz_2", "A.b-c"])
def test_valid_voice_ids_are_accepted(voice: str) -> None:
    assert Settings(voice=voice).voice == voice


# --- load_settings / save_settings ---


def test_load_missing_file_returns_defaults_without_warning(
    toml_file: Path, warnings_log: pytest.LogCaptureFixture
) -> None:
    assert load_settings(toml_file) == Settings()
    assert warning_messages(warnings_log) == []


def test_save_then_load_roundtrip(toml_file: Path, warnings_log: pytest.LogCaptureFixture) -> None:
    original = Settings(
        voice="es-f-01",
        voice_volume=1.5,
        accelerate_after_s=2.0,
        concise_after_s=4.5,
        drop_after_s=9.0,
        max_speed=1.4,
        max_untranslated_s=8.0,
        context_utterances=2,
        glossary=(("cell phone", "móvil"), ("parking lot", "aparcamiento"), ("lorry", "camión")),
        show_text=True,
        save_audio=True,
    )

    save_settings(original, toml_file)

    assert load_settings(toml_file) == original
    assert warning_messages(warnings_log) == []


def test_save_writes_spanish_keys_in_utf8_and_leaves_no_temporary_file(toml_file: Path) -> None:
    nested = toml_file.parent / "sub" / "carpeta" / "ajustes.toml"

    save_settings(Settings(glossary=(("cell phone", "móvil"),)), nested)

    raw = tomllib.loads(nested.read_text(encoding="utf-8"))
    assert raw["voz"] == DEFAULT_VOICE
    assert raw["glosario"] == {"cell phone": "móvil"}
    assert set(raw) == set(TOML_KEYS.values())
    assert [path.name for path in nested.parent.iterdir()] == ["ajustes.toml"]


def test_save_overwrites_the_previous_file(toml_file: Path) -> None:
    save_settings(Settings(voice_volume=0.5), toml_file)
    save_settings(Settings(voice_volume=1.5), toml_file)

    assert load_settings(toml_file).voice_volume == 1.5


def test_load_reads_a_hand_written_file_with_integers(toml_file: Path) -> None:
    toml_file.write_text(
        'voz = "es-f-02"\nvolumen_voz = 1\nfrases_de_contexto = 2\n'
        "mostrar_texto = true\n\n[glosario]\n"
        '"cell phone" = "móvil"\njuice = "zumo"\n',
        encoding="utf-8",
    )

    settings = load_settings(toml_file)

    assert settings.voice == "es-f-02"
    assert settings.voice_volume == 1.0
    assert isinstance(settings.voice_volume, float)
    assert settings.context_utterances == 2
    assert settings.show_text is True
    assert settings.glossary == (("cell phone", "móvil"), ("juice", "zumo"))


@pytest.mark.parametrize(
    ("key", "attribute", "bad_value"),
    [
        ("voz", "voice", ""),
        ("voz", "voice", "María"),
        ("voz", "voice", 7),
        ("volumen_voz", "voice_volume", -0.1),
        ("volumen_voz", "voice_volume", 2.5),
        ("volumen_voz", "voice_volume", "fuerte"),
        ("volumen_voz", "voice_volume", True),
        ("volumen_voz", "voice_volume", float("nan")),
        ("umbral_acelerar_s", "accelerate_after_s", 0),
        ("umbral_acelerar_s", "accelerate_after_s", -3.0),
        ("velocidad_max", "max_speed", 0.9),
        ("velocidad_max", "max_speed", 1.6),
        ("max_habla_sin_traducir_s", "max_untranslated_s", 1.0),
        ("max_habla_sin_traducir_s", "max_untranslated_s", 20),
        ("frases_de_contexto", "context_utterances", -1),
        ("frases_de_contexto", "context_utterances", 9),
        ("frases_de_contexto", "context_utterances", 2.5),
        ("mostrar_texto", "show_text", "sí"),
        ("guardar_audio", "save_audio", 1),
    ],
)
def test_load_out_of_range_value_warns_and_uses_default(
    toml_file: Path,
    warnings_log: pytest.LogCaptureFixture,
    key: str,
    attribute: str,
    bad_value: object,
) -> None:
    toml_file.write_text(tomli_w.dumps({key: bad_value}), encoding="utf-8")

    settings = load_settings(toml_file)

    assert getattr(settings, attribute) == getattr(Settings(), attribute)
    messages = warning_messages(warnings_log)
    assert len(messages) == 1
    assert key in messages[0]


def test_load_keeps_valid_values_next_to_an_invalid_one(
    toml_file: Path, warnings_log: pytest.LogCaptureFixture
) -> None:
    toml_file.write_text(
        'voz = "es-f-01"\nvolumen_voz = 9.0\nvelocidad_max = 1.4\nmostrar_texto = true\n',
        encoding="utf-8",
    )

    settings = load_settings(toml_file)

    assert settings == Settings(voice="es-f-01", max_speed=1.4, show_text=True)
    assert len(warning_messages(warnings_log)) == 1


def test_load_warns_about_unknown_keys_and_keeps_the_rest(
    toml_file: Path, warnings_log: pytest.LogCaptureFixture
) -> None:
    toml_file.write_text("volumen = 1.5\nvolumen_voz = 0.5\n[otra_tabla]\nx = 1\n", encoding="utf-8")

    settings = load_settings(toml_file)

    assert settings == Settings(voice_volume=0.5)
    messages = warning_messages(warnings_log)
    assert any("volumen" in message and "volumen_voz" not in message for message in messages)
    assert any("otra_tabla" in message for message in messages)


def test_load_invalid_toml_syntax_warns_and_returns_defaults(
    toml_file: Path, warnings_log: pytest.LogCaptureFixture
) -> None:
    toml_file.write_text("esto = no es toml [", encoding="utf-8")

    assert load_settings(toml_file) == Settings()
    assert len(warning_messages(warnings_log)) == 1


def test_load_file_that_is_not_utf8_warns_and_returns_defaults(
    toml_file: Path, warnings_log: pytest.LogCaptureFixture
) -> None:
    toml_file.write_bytes(b'voz = "\xff\xfe"\n')

    assert load_settings(toml_file) == Settings()
    assert len(warning_messages(warnings_log)) == 1


# --- load_settings: umbrales de retraso ---


def thresholds_of(settings: Settings) -> tuple[float, float, float]:
    return settings.accelerate_after_s, settings.concise_after_s, settings.drop_after_s


@pytest.mark.parametrize(
    ("toml_text", "expected"),
    [
        # resumir no supera a acelerar: resumir vuelve a su valor por defecto (5,0)
        ("umbral_resumir_s = 2.0\n", (3.0, 5.0, 8.0)),
        ("umbral_resumir_s = 3.0\n", (3.0, 5.0, 8.0)),
        # descartar no supera a resumir: descartar vuelve a su valor por defecto (8,0)
        ("umbral_descartar_s = 4.0\n", (3.0, 5.0, 8.0)),
        ("umbral_descartar_s = 5.0\n", (3.0, 5.0, 8.0)),
        # se conserva lo que sí es coherente
        ("umbral_acelerar_s = 2.0\numbral_resumir_s = 2.5\numbral_descartar_s = 2.2\n", (2.0, 2.5, 8.0)),
        ("umbral_acelerar_s = 1.0\numbral_resumir_s = 0.5\n", (1.0, 5.0, 8.0)),
        # el valor por defecto tampoco encaja con el resto: los tres vuelven a su valor por defecto
        ("umbral_acelerar_s = 10.0\n", (3.0, 5.0, 8.0)),
        ("umbral_acelerar_s = 6.0\numbral_resumir_s = 5.5\n", (3.0, 5.0, 8.0)),
    ],
)
def test_load_incoherent_thresholds_warn_and_fall_back_to_defaults(
    toml_file: Path,
    warnings_log: pytest.LogCaptureFixture,
    toml_text: str,
    expected: tuple[float, float, float],
) -> None:
    toml_file.write_text(toml_text, encoding="utf-8")

    settings = load_settings(toml_file)

    assert thresholds_of(settings) == expected
    messages = warning_messages(warnings_log)
    assert len(messages) == 1
    assert "umbral_" in messages[0]


@pytest.mark.parametrize(
    "thresholds",
    [
        (1.0, 2.0, 3.0),
        (6.0, 7.0, 9.0),
        (0.5, 5.0, 8.0),
        (3.0, 3.5, 8.0),
    ],
)
def test_load_coherent_thresholds_are_kept_without_warning(
    toml_file: Path, warnings_log: pytest.LogCaptureFixture, thresholds: tuple[float, float, float]
) -> None:
    accelerate, concise, drop = thresholds
    toml_file.write_text(
        f"umbral_acelerar_s = {accelerate}\numbral_resumir_s = {concise}\numbral_descartar_s = {drop}\n",
        encoding="utf-8",
    )

    assert thresholds_of(load_settings(toml_file)) == thresholds
    assert warning_messages(warnings_log) == []


# --- load_settings: glosario ---


def test_load_glossary_skips_invalid_entries_with_a_warning(
    toml_file: Path, warnings_log: pytest.LogCaptureFixture
) -> None:
    toml_file.write_text(
        '[glosario]\njuice = "zumo"\nfridge = 3\n"" = "nada"\ncar = "coche"\n', encoding="utf-8"
    )

    settings = load_settings(toml_file)

    assert settings.glossary == (("juice", "zumo"), ("car", "coche"))
    messages = warning_messages(warnings_log)
    assert len(messages) == 2
    assert all("glosario" in message for message in messages)


def test_load_glossary_that_is_not_a_table_warns_and_is_empty(
    toml_file: Path, warnings_log: pytest.LogCaptureFixture
) -> None:
    toml_file.write_text('glosario = "juice=zumo"\n', encoding="utf-8")

    assert load_settings(toml_file).glossary == ()
    assert len(warning_messages(warnings_log)) == 1


# --- ruta del TOML ---


def test_settings_path_is_inside_home_when_environment_variable_is_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path / "mi_home"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))

    assert settings_path() == tmp_path / "mi_home" / "ajustes.toml"


def test_settings_path_defaults_to_appdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("INSTANTTRADUCTOR_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))

    assert settings_path() == tmp_path / "roaming" / "InstantTraductor" / "ajustes.toml"


def test_settings_path_ignores_an_empty_environment_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", "")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))

    assert settings_path() == tmp_path / "roaming" / "InstantTraductor" / "ajustes.toml"


def test_load_and_save_default_to_settings_path() -> None:
    expected = AppPaths().home / "ajustes.toml"
    assert settings_path() == expected
    assert not expected.exists()

    save_settings(Settings(voice="es-f-03", show_text=True))

    assert expected.is_file()
    assert load_settings() == Settings(voice="es-f-03", show_text=True)


# --- AppPaths ---


def test_app_paths_use_instanttraductor_home_when_defined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path))

    paths = AppPaths()

    assert paths.home == tmp_path
    assert paths.models == tmp_path / "models"
    assert paths.bin == tmp_path / "bin"
    assert paths.voices == tmp_path / "voices"
    assert paths.logs == tmp_path / "logs"
    assert paths.reports == tmp_path / "informes"


def test_app_paths_default_home_is_localappdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("INSTANTTRADUCTOR_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    assert AppPaths().home == tmp_path / "local" / "InstantTraductor"


def test_app_paths_default_home_without_localappdata_uses_the_user_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("INSTANTTRADUCTOR_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert AppPaths().home == tmp_path / "AppData" / "Local" / "InstantTraductor"


def test_app_paths_accept_an_explicit_home_and_do_not_create_folders(tmp_path: Path) -> None:
    paths = AppPaths(home=tmp_path / "otro")

    assert paths.voices == tmp_path / "otro" / "voices"
    assert not (tmp_path / "otro").exists()


def test_app_paths_are_resolved_when_created_not_at_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path / "uno"))
    first = AppPaths()
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path / "dos"))
    second = AppPaths()

    assert first.home == tmp_path / "uno"
    assert second.home == tmp_path / "dos"


# --- ffmpeg_path ---


def test_ffmpeg_path_prefers_the_local_install(monkeypatch: pytest.MonkeyPatch) -> None:
    local = AppPaths().bin / "ffmpeg" / "bin" / "ffmpeg.exe"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"")
    monkeypatch.setattr(shutil, "which", lambda name: "C:/en/el/path/ffmpeg.exe")

    assert ffmpeg_path() == local


def test_ffmpeg_path_falls_back_to_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda name: "C:/en/el/path/ffmpeg.exe" if name == "ffmpeg" else None
    )

    assert ffmpeg_path() == Path("C:/en/el/path/ffmpeg.exe")


def test_ffmpeg_path_is_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    assert ffmpeg_path() is None
