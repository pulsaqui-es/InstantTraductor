"""Catálogo de voces castellanas empaquetadas en la app (T042, FR-028 y research R12).

Las voces viven en ``src/instanttraductor/setup/voices/``: un ``<voice_id>.wav`` de referencia y un
``<voice_id>.json`` con ``voice_id``, ``name``, ``gender`` (``"f"`` o ``"m"``), ``source``,
``license`` y ``ref_text`` (lo que dice el audio). Se leen con ``importlib.resources``: no hay
descargas y funcionan sin red.

El manifiesto (``manifest.py``) tiene una entrada ``kind="voz"`` por voz (``component_id =
"voz-<voice_id>"``) con el ``sha256`` y el tamaño de sus dos ficheros. ``install_voices`` las copia
a ``AppPaths.voices`` de forma idempotente, verificando el ``sha256`` del original y del destino.

- ``list_voices()``: el catálogo, ordenado por ``voice_id``.
- ``get_voice(voice_id)``: una voz (``KeyError`` si no existe).
- ``install_voices(paths=None)``: copia las voces; devuelve los ids de las que ha copiado o repuesto.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final, Literal

from instanttraductor.config import DEFAULT_VOICE, AppPaths
from instanttraductor.setup import manifest

__all__ = [
    "DEFAULT_VOICE",
    "VOICES_PACKAGE",
    "VOICES_RESOURCE_DIR",
    "Voice",
    "get_voice",
    "install_voices",
    "list_voices",
    "voice_component_id",
]

VOICES_PACKAGE: Final = "instanttraductor.setup"
VOICES_RESOURCE_DIR: Final = "voices"

_VOICE_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")
_GENDERS: Final = ("f", "m")

Gender = Literal["f", "m"]


@dataclass(frozen=True, slots=True)
class Voice:
    """Una voz del catálogo (metadatos del JSON). El audio se obtiene con ``wav_path`` o ``wav_bytes``."""

    voice_id: str
    name: str
    gender: Gender
    source: str
    license: str
    ref_text: str

    @property
    def wav_name(self) -> str:
        return f"{self.voice_id}.wav"

    @property
    def json_name(self) -> str:
        return f"{self.voice_id}.json"

    def wav_bytes(self) -> bytes:
        """El WAV de referencia empaquetado."""
        return _resource_dir().joinpath(self.wav_name).read_bytes()

    def installed_wav_path(self, paths: AppPaths | None = None) -> Path:
        """Ruta del WAV instalado en ``AppPaths.voices`` (puede no existir si no se ha preparado)."""
        return (paths or AppPaths()).voices / self.wav_name


def voice_component_id(voice_id: str) -> str:
    """Id del componente del manifiesto que corresponde a una voz."""
    return f"voz-{voice_id}"


def _resource_dir() -> Traversable:
    return resources.files(VOICES_PACKAGE).joinpath(VOICES_RESOURCE_DIR)


def _invalid(json_name: str, reason: str) -> ValueError:
    return ValueError(f"Voz empaquetada «{json_name}» no válida: {reason}")


def _parse_voice(json_name: str, raw: object) -> Voice:
    if not isinstance(raw, dict):
        raise _invalid(json_name, "el JSON debe ser un objeto")
    fields: dict[str, str] = {}
    for key in ("voice_id", "name", "gender", "source", "license", "ref_text"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise _invalid(json_name, f"falta «{key}» o está vacío")
        fields[key] = value
    voice_id = fields["voice_id"]
    if not (voice_id.isascii() and _VOICE_ID.fullmatch(voice_id)):
        raise _invalid(json_name, "voice_id debe ser ASCII en minúsculas, sin espacios")
    if json_name != f"{voice_id}.json":
        raise _invalid(json_name, f"el nombre del fichero no coincide con voice_id «{voice_id}»")
    if fields["gender"] not in _GENDERS:
        raise _invalid(json_name, "gender debe ser «f» o «m»")
    return Voice(
        voice_id=voice_id,
        name=fields["name"],
        gender=fields["gender"],  # type: ignore[arg-type]
        source=fields["source"],
        license=fields["license"],
        ref_text=fields["ref_text"],
    )


def list_voices() -> tuple[Voice, ...]:
    """Las voces del catálogo empaquetado, ordenadas por ``voice_id``."""
    voices: list[Voice] = []
    for entry in _resource_dir().iterdir():
        if not entry.name.endswith(".json"):
            continue
        voice = _parse_voice(entry.name, json.loads(entry.read_text(encoding="utf-8")))
        if not _resource_dir().joinpath(voice.wav_name).is_file():
            raise _invalid(entry.name, f"falta el audio «{voice.wav_name}»")
        voices.append(voice)
    return tuple(sorted(voices, key=lambda voice: voice.voice_id))


def get_voice(voice_id: str) -> Voice:
    """La voz con ese id. ``KeyError`` si no existe en el catálogo."""
    for voice in list_voices():
        if voice.voice_id == voice_id:
            return voice
    raise KeyError(f"Voz desconocida: {voice_id!r}")


# --- instalación ---


def _sha256_of_file(path: Path) -> str | None:
    """``sha256`` de un fichero o ``None`` si no existe o no se puede leer."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _write_atomically(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    temporary.write_bytes(data)
    os.replace(temporary, target)


def install_voices(paths: AppPaths | None = None) -> tuple[str, ...]:
    """Copia las voces empaquetadas a ``paths.voices`` (por defecto ``AppPaths().voices``).

    Idempotente: un fichero que ya existe con el ``sha256`` esperado no se toca; uno ausente o con otro
    contenido se (re)copia. Antes de copiar se comprueba que el original empaquetado coincide con el
    ``sha256`` del manifiesto (``ValueError`` si el paquete está dañado).

    Devuelve los ids de las voces de las que se ha copiado o repuesto algún fichero en esta llamada
    (vacía si todo estaba ya instalado y correcto).
    """
    target_dir = (paths or AppPaths()).voices
    source_dir = _resource_dir()
    changed: list[str] = []
    for voice in list_voices():
        component = manifest.get_component(voice_component_id(voice.voice_id))
        copied = False
        for file in component.files:
            target = target_dir / file.rel_path
            if _sha256_of_file(target) == file.sha256:
                continue
            data = source_dir.joinpath(file.rel_path).read_bytes()
            if hashlib.sha256(data).hexdigest() != file.sha256:
                raise ValueError(
                    f"El fichero empaquetado «{file.rel_path}» no coincide con el sha256 del manifiesto"
                )
            _write_atomically(target, data)
            copied = True
        if copied:
            changed.append(voice.voice_id)
    return tuple(changed)
