"""Tipos de la escucha de una aplicación (spec 002, ADR-0012; data-model.md).

Los comparten `audio/apps.py` (lista), `audio/app_source.py` (vigilante) y los dobles de los tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AppIdentity:
    """Una aplicación que se puede escuchar.

    Se guarda `exe_path`. `root_pid` y `create_time` solo valen en la sesión: el PID cambia al reiniciarla.
    """

    exe_path: str  # ruta absoluta del ejecutable: la identidad que se recuerda (app_escuchada)
    display_name: str  # FileDescription del ejecutable o nombre del proceso
    root_pid: int  # proceso que se captura: la sesión de audio o su padre directo con la misma imagen
    create_time: float  # hora de creación del proceso raíz (psutil), para detectar reinicios


@dataclass(frozen=True, slots=True)
class AudioApp:
    """Una fila de la lista de apps que se muestra al elegir."""

    identity: AppIdentity
    sounding: bool  # la sonda INCLUDE de 0,6 s dio ≥ -60 dBFS RMS
    level_dbfs: float
    endpoints: tuple[str, ...] = ()  # dispositivos de salida por los que tiene sesión


class ProcessTable(Protocol):
    """Lo que el vigilante necesita del sistema de procesos (inyectable en los tests)."""

    def find_roots(self, exe_path: str) -> list[AppIdentity]:
        """Raíces vivas de esa app ahora mismo (vacío si no está abierta o no tiene sesión de audio)."""
        ...

    def is_alive(self, pid: int, create_time: float) -> bool:
        """¿Sigue vivo ese proceso (y es el mismo, no un PID reutilizado)?"""
        ...
