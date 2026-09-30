"""Modos de captura comunes a las dos implementaciones del spike."""

import enum


class ModoCaptura(enum.Enum):
    EXCLUDE = "exclude"  # todo el audio del sistema salvo el arbol de procesos del PID
    INCLUDE = "include"  # solo el arbol de procesos del PID (control positivo)
    ENDPOINT = "endpoint"  # loopback clasico del dispositivo por defecto (todo, control)
