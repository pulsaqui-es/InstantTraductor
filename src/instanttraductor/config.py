"""Ajustes de la persona usuaria y rutas estándar de InstantTraductor.

Ajustes
-------
Persisten en un TOML (``ajustes.toml``) cuyas claves, las que ve el humano, van en español. En el
código los atributos de ``Settings`` van en inglés; ``TOML_KEYS`` es la tabla de correspondencia
atributo → clave. Los rangos y los valores por defecto son los de ``data-model.md`` (tabla «Ajustes»).

Un valor del TOML fuera de rango (o de otro tipo) nunca se ignora en silencio: ``load_settings``
lo avisa con ``logging.warning`` y usa el valor por defecto de esa clave. Un TOML ilegible o con
errores de sintaxis también avisa y devuelve los ajustes por defecto.

Rutas
-----
- El TOML está en ``<home>/ajustes.toml`` si ``INSTANTTRADUCTOR_HOME`` está definida (así se aíslan
  los tests y las pruebas manuales) y, si no, en ``%APPDATA%\\InstantTraductor\\ajustes.toml``.
- ``AppPaths.home`` es ``INSTANTTRADUCTOR_HOME`` si está definida y, si no,
  ``%LOCALAPPDATA%\\InstantTraductor``. De ahí cuelgan ``models``, ``bin``, ``voices``, ``logs`` e
  ``informes``. Nada de esto va dentro del repositorio.
"""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import tomli_w

logger = logging.getLogger(__name__)

APP_DIR_NAME: Final = "InstantTraductor"
HOME_ENV_VAR: Final = "INSTANTTRADUCTOR_HOME"
SETTINGS_FILE_NAME: Final = "ajustes.toml"

#: Voz por defecto. Provisional: es la única voz que deja colocada la preparación manual (T013).
#: Cuando el catálogo de voces (T042) fije la femenina preferida, se cambia aquí.
DEFAULT_VOICE: Final = "es-m-tux"

#: Correspondencia atributo de ``Settings`` (inglés) → clave del TOML (español, la que ve el humano).
TOML_KEYS: Final[Mapping[str, str]] = MappingProxyType(
    {
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
)

#: Los tres umbrales de retraso, de menor a mayor: deben cumplir ``acelerar < resumir < descartar``.
_THRESHOLDS: Final = ("accelerate_after_s", "concise_after_s", "drop_after_s")

_VOICE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


# --- validación de cada ajuste ---
# Cada función devuelve el valor normalizado o lanza ValueError con el motivo (en español).


def _as_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("debe ser un número")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError("es demasiado grande") from None
    if not math.isfinite(number):
        raise ValueError("debe ser un número finito")
    return number


def _number_between(low: float, high: float) -> Callable[[object], float]:
    def check(value: object) -> float:
        number = _as_number(value)
        if not low <= number <= high:
            raise ValueError(f"debe estar entre {low:g} y {high:g}")
        return number

    return check


def _positive_number(value: object) -> float:
    number = _as_number(value)
    if number <= 0:
        raise ValueError("debe ser mayor que 0")
    return number


def _integer_between(low: int, high: int) -> Callable[[object], int]:
    def check(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("debe ser un número entero")
        if not low <= value <= high:
            raise ValueError(f"debe estar entre {low} y {high}")
        return value

    return check


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("debe ser true o false")
    return value


def _voice(value: object) -> str:
    if not isinstance(value, str) or _VOICE_ID.fullmatch(value) is None:
        raise ValueError("debe ser el identificador ASCII de una voz del catálogo, sin espacios")
    return value


def _glossary_entry(source: object, target: object) -> tuple[str, str]:
    if not (isinstance(source, str) and isinstance(target, str) and source.strip() and target.strip()):
        raise ValueError("cada entrada debe ser un par de textos no vacíos (inglés → español)")
    return source, target


def _glossary(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        pairs = list(value.items())
    elif isinstance(value, tuple | list):
        pairs = list(value)
    else:
        raise ValueError("debe ser una tabla de pares inglés → español")
    entries = []
    for pair in pairs:
        if not isinstance(pair, tuple | list) or len(pair) != 2:
            raise ValueError("cada entrada debe ser un par (inglés, español)")
        entries.append(_glossary_entry(*pair))
    return tuple(entries)


#: Validador de cada atributo (individual; el orden entre los tres umbrales se comprueba aparte).
_CHECKS: Final[Mapping[str, Callable[[object], Any]]] = MappingProxyType(
    {
        "voice": _voice,
        "voice_volume": _number_between(0.0, 2.0),
        "accelerate_after_s": _positive_number,
        "concise_after_s": _positive_number,
        "drop_after_s": _positive_number,
        "max_speed": _number_between(1.0, 1.5),
        "max_untranslated_s": _number_between(2.0, 15.0),
        "context_utterances": _integer_between(0, 8),
        "glossary": _glossary,
        "show_text": _boolean,
        "save_audio": _boolean,
    }
)


# --- Settings ---


@dataclass(frozen=True, slots=True)
class Settings:
    """Ajustes que persisten entre sesiones (FR-029). Un valor no válido lanza ``ValueError``.

    Los atributos van en inglés y las claves del TOML en español (ver ``TOML_KEYS``).
    ``glossary`` son pares ``(inglés, español)`` en el orden del fichero; admite también un
    ``Mapping`` al construirse.
    """

    voice: str = DEFAULT_VOICE  # voz
    voice_volume: float = 1.0  # volumen_voz: 0,0–2,0 (solo la voz en español)
    accelerate_after_s: float = 3.0  # umbral_acelerar_s: > 0
    concise_after_s: float = 5.0  # umbral_resumir_s: > umbral_acelerar_s
    drop_after_s: float = 8.0  # umbral_descartar_s: > umbral_resumir_s
    max_speed: float = 1.25  # velocidad_max: 1,0–1,5
    max_untranslated_s: float = 6.0  # max_habla_sin_traducir_s: 2–15
    context_utterances: int = 4  # frases_de_contexto: 0–8
    glossary: tuple[tuple[str, str], ...] = ()  # glosario: inglés → español
    show_text: bool = False  # mostrar_texto
    save_audio: bool = False  # guardar_audio (FR-030)

    def __post_init__(self) -> None:
        for name, check in _CHECKS.items():
            try:
                value = check(getattr(self, name))
            except ValueError as error:
                raise ValueError(f"Ajuste «{TOML_KEYS[name]}» ({name}) no válido: {error}") from None
            object.__setattr__(self, name, value)
        if not self.accelerate_after_s < self.concise_after_s < self.drop_after_s:
            raise ValueError(
                "Ajustes no válidos: los umbrales deben cumplir umbral_acelerar_s < umbral_resumir_s "
                f"< umbral_descartar_s (recibidos {self.accelerate_after_s:g}, {self.concise_after_s:g} "
                f"y {self.drop_after_s:g})"
            )

    def to_toml_dict(self) -> dict[str, Any]:
        """Los ajustes con las claves en español del TOML (el glosario, como tabla)."""
        data = {key: getattr(self, name) for name, key in TOML_KEYS.items()}
        data[TOML_KEYS["glossary"]] = dict(self.glossary)
        return data


_DEFAULTS: Final = Settings()


# --- rutas ---


def _windows_data_dir(variable: str, *fallback: str) -> Path:
    """Carpeta de datos de Windows (``%LOCALAPPDATA%``, ``%APPDATA%``) o su valor habitual si falta."""
    value = os.environ.get(variable)
    return Path(value) if value else Path.home().joinpath(*fallback)


def _default_home() -> Path:
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override)
    return _windows_data_dir("LOCALAPPDATA", "AppData", "Local") / APP_DIR_NAME


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Carpetas de datos de la app. ``AppPaths()`` resuelve ``home`` al crearse (lee el entorno).

    No crea ninguna carpeta: quien escribe en ellas (instalador, registro, informes) las crea.
    """

    home: Path = field(default_factory=_default_home)

    @property
    def models(self) -> Path:
        return self.home / "models"

    @property
    def bin(self) -> Path:
        return self.home / "bin"

    @property
    def voices(self) -> Path:
        return self.home / "voices"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def informes(self) -> Path:
        return self.home / "informes"


def settings_path() -> Path:
    """Ruta de ``ajustes.toml``: ``<home>/ajustes.toml`` si ``INSTANTTRADUCTOR_HOME`` está definida."""
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override) / SETTINGS_FILE_NAME
    return _windows_data_dir("APPDATA", "AppData", "Roaming") / APP_DIR_NAME / SETTINGS_FILE_NAME


def ffmpeg_path() -> Path | None:
    """``ffmpeg`` local (``bin/ffmpeg/bin/ffmpeg.exe``) si existe; si no, el del PATH; si no, ``None``."""
    local = AppPaths().bin / "ffmpeg" / "bin" / "ffmpeg.exe"
    if local.is_file():
        return local
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


# --- carga y guardado ---


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}  # primera ejecución: sin fichero, ajustes por defecto
    except (OSError, ValueError) as error:  # ValueError incluye TOMLDecodeError y UnicodeDecodeError
        logger.warning("No se pudo leer %s (%s); se usan los ajustes por defecto.", path, error)
        return {}


def _load_glossary(raw: object, origin: Path, key: str) -> tuple[tuple[str, str], ...]:
    """Glosario del TOML: una entrada no válida se avisa y se salta, sin perder las demás."""
    if not isinstance(raw, Mapping):
        logger.warning(
            "%s: «%s» debe ser una tabla de pares inglés → español; se usa el glosario vacío.", origin, key
        )
        return ()
    entries = []
    for source, target in raw.items():
        try:
            entries.append(_glossary_entry(source, target))
        except ValueError as error:
            logger.warning(
                "%s: entrada %r = %r de «%s» no válida (%s); se ignora.", origin, source, target, key, error
            )
    return tuple(entries)


def _reconcile_thresholds(values: dict[str, Any], origin: Path) -> None:
    """Garantiza ``acelerar < resumir < descartar``.

    Si no se cumple, se avisa y vuelve a su valor por defecto primero ``umbral_resumir_s`` y luego
    ``umbral_descartar_s``; si ni así encajan con ``umbral_acelerar_s``, los tres vuelven al suyo.
    """
    accelerate, concise, drop = (values.get(name, getattr(_DEFAULTS, name)) for name in _THRESHOLDS)
    if accelerate < concise < drop:
        return
    received = f"{accelerate:g}, {concise:g} y {drop:g}"
    reset = []
    if not accelerate < concise:
        concise = _DEFAULTS.concise_after_s
        reset.append("concise_after_s")
    if not concise < drop:
        drop = _DEFAULTS.drop_after_s
        reset.append("drop_after_s")
    if not accelerate < concise < drop:
        accelerate, concise, drop = (getattr(_DEFAULTS, name) for name in _THRESHOLDS)
        reset = list(_THRESHOLDS)
    values.update(zip(_THRESHOLDS, (accelerate, concise, drop), strict=True))
    logger.warning(
        "%s: los umbrales deben cumplir umbral_acelerar_s < umbral_resumir_s < umbral_descartar_s "
        "(recibidos %s); se usa el valor por defecto de: %s.",
        origin,
        received,
        ", ".join(TOML_KEYS[name] for name in reset),
    )


def _settings_from_toml(raw: Mapping[str, Any], origin: Path) -> Settings:
    known = set(TOML_KEYS.values())
    for key in raw:
        if key not in known:
            logger.warning("%s: «%s» no es un ajuste conocido y se ignora.", origin, key)

    values: dict[str, Any] = {}
    for name, key in TOML_KEYS.items():
        if key not in raw:
            continue
        if name == "glossary":
            values[name] = _load_glossary(raw[key], origin, key)
            continue
        try:
            values[name] = _CHECKS[name](raw[key])
        except ValueError as error:
            logger.warning(
                "%s: «%s» = %r no es válido (%s); se usa el valor por defecto (%r).",
                origin,
                key,
                raw[key],
                error,
                getattr(_DEFAULTS, name),
            )
    _reconcile_thresholds(values, origin)
    return Settings(**values)


def load_settings(path: Path | None = None) -> Settings:
    """Lee los ajustes de ``path`` (por defecto, ``settings_path()``).

    Sin fichero: ajustes por defecto, sin aviso. Un valor no válido: ``logging.warning`` y valor por
    defecto para esa clave; el resto de ajustes se conserva.
    """
    origin = settings_path() if path is None else path
    return _settings_from_toml(_read_toml(origin), origin)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Guarda los ajustes en ``path`` (por defecto, ``settings_path()``), con escritura atómica."""
    target = settings_path() if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(tomli_w.dumps(settings.to_toml_dict()), encoding="utf-8", newline="\n")
    os.replace(temporary, target)
