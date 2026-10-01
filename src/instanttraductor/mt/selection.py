"""Elección del modelo de traducción según la VRAM libre (ADR-0011, research R7).

- ``MtModel``: los dos modelos Hy-MT2 (7B por defecto y reserva 1.8B). Su valor es el ``component_id`` del
  manifiesto, que es también lo que se anota como ``mt_model`` en el informe.
- ``free_vram_mb()``: VRAM libre de la GPU, leída con ``nvidia-smi``.
- ``choose_mt_model(free_mb)``: el 7B si, **después de cargar la voz**, quedan 5 200 + 1 024 MiB; si no, la
  reserva 1.8B con 2 300 + 1 024 MiB; si no, ``EngineError`` no recuperable.
- ``model_path(model)``: ruta del GGUF dentro de la carpeta de datos de la app.

Uso típico (arranque de la sesión, con el servicio de voz ya cargado)::

    model = choose_mt_model(free_vram_mb())
    server = LlamaServerProcess(model_path(model))
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Final

from instanttraductor.contracts import EngineError
from instanttraductor.setup.manifest import component_dir

__all__ = [
    "MODEL_VRAM_MIB",
    "NVIDIA_SMI_COMMAND",
    "VRAM_MARGIN_MIB",
    "MtModel",
    "choose_mt_model",
    "free_vram_mb",
    "model_path",
]

logger = logging.getLogger(__name__)

#: Nombre con el que los errores de este módulo identifican al motor (``EngineError.engine``).
ENGINE: Final = "hy-mt2"

#: VRAM que ocupa cada modelo con ``llama-server`` (MiB, medida en S2: 5 202 y 2 289, redondeadas).
MODEL_VRAM_MIB: Final = {"hy-mt2-7b-q4": 5_200, "hy-mt2-1.8b-q8": 2_300}
#: Margen que debe sobrar tras cargar el modelo (MiB).
VRAM_MARGIN_MIB: Final = 1_024

#: Comando que da la VRAM libre (MiB) de la primera GPU, una línea por GPU y sin unidades.
NVIDIA_SMI_COMMAND: Final = ("nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits")
NVIDIA_SMI_TIMEOUT_S: Final = 10.0

_GGUF_NAMES: Final = {
    "hy-mt2-7b-q4": "Hy-MT2-7B-Q4_K_M.gguf",
    "hy-mt2-1.8b-q8": "Hy-MT2-1.8B-Q8_0.gguf",
}
_LEADING_NUMBER = re.compile(r"\s*(\d+(?:\.\d+)?)")


class MtModel(StrEnum):
    """Modelo de traducción. El valor es el ``component_id`` del manifiesto (``setup.manifest``)."""

    HY_MT2_7B = "hy-mt2-7b-q4"
    HY_MT2_1_8B = "hy-mt2-1.8b-q8"

    @property
    def component_id(self) -> str:
        return self.value

    @property
    def filename(self) -> str:
        """Nombre del GGUF dentro de ``component_dir(component_id)``."""
        return _GGUF_NAMES[self.value]

    @property
    def vram_mib(self) -> int:
        """VRAM que ocupa con ``llama-server``."""
        return MODEL_VRAM_MIB[self.value]

    @property
    def required_free_mib(self) -> int:
        """VRAM libre que hace falta para elegirlo: lo que ocupa más el margen."""
        return self.vram_mib + VRAM_MARGIN_MIB

    @property
    def supports_concise(self) -> bool:
        """Solo el 7B sabe resumir (modo CONCISE); el 1.8B no (ADR-0011)."""
        return self is MtModel.HY_MT2_7B

    @classmethod
    def parse(cls, value: MtModel | str) -> MtModel:
        """Acepta el propio ``MtModel``, su ``component_id`` o el alias corto (``"7b"``, ``"1.8b"``).

        No distingue mayúsculas de minúsculas. Lanza ``ValueError`` si no lo reconoce.
        """
        if isinstance(value, cls):
            return value
        model = _ALIASES.get(str(value).strip().lower())
        if model is None:
            raise ValueError(f"Modelo de traducción desconocido: {value!r} (usa «7b» o «1.8b»).")
        return model


_ALIASES: Final = {
    "7b": MtModel.HY_MT2_7B,
    "hy-mt2-7b": MtModel.HY_MT2_7B,
    "hy-mt2-7b-q4": MtModel.HY_MT2_7B,
    "1.8b": MtModel.HY_MT2_1_8B,
    "hy-mt2-1.8b": MtModel.HY_MT2_1_8B,
    "hy-mt2-1.8b-q8": MtModel.HY_MT2_1_8B,
}


def model_path(model: MtModel | str) -> Path:
    """Ruta del GGUF: ``component_dir(<componente>) / <fichero>`` (lee el entorno al llamar)."""
    kind = MtModel.parse(model)
    return component_dir(kind.component_id) / kind.filename


def free_vram_mb(
    *, command: Sequence[str] = NVIDIA_SMI_COMMAND, timeout_s: float = NVIDIA_SMI_TIMEOUT_S
) -> int:
    """VRAM libre (MiB) de la primera GPU, con ``nvidia-smi``.

    ``command`` solo se cambia en los tests, para sustituir a ``nvidia-smi`` por un proceso falso.
    Lanza ``EngineError(recoverable=False)`` si ``nvidia-smi`` no existe, falla, tarda más de
    ``timeout_s`` o da una salida que no es un número: sin la VRAM no se puede elegir modelo.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - comando fijo, sin shell
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as error:
        raise EngineError(
            "No se encontró nvidia-smi: ¿está instalado el driver de NVIDIA?",
            engine=ENGINE,
            recoverable=False,
        ) from error
    except subprocess.TimeoutExpired as error:
        raise EngineError(
            f"nvidia-smi no respondió en {timeout_s:g} s.", engine=ENGINE, recoverable=False
        ) from error
    except OSError as error:
        raise EngineError(
            f"No se pudo ejecutar nvidia-smi: {error}", engine=ENGINE, recoverable=False
        ) from error

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise EngineError(
            f"nvidia-smi terminó con código {completed.returncode}: {detail}",
            engine=ENGINE,
            recoverable=False,
        )
    first_line = next((line for line in completed.stdout.splitlines() if line.strip()), "")
    match = _LEADING_NUMBER.match(first_line)
    if match is None:
        raise EngineError(
            f"No se entiende la salida de nvidia-smi: {completed.stdout.strip()!r}.",
            engine=ENGINE,
            recoverable=False,
        )
    return int(float(match.group(1)))


def choose_mt_model(free_mb: float) -> MtModel:
    """Elige el modelo de traducción con la VRAM libre (MiB) **tras cargar la voz** (ADR-0011).

    - ``>= 5 200 + 1 024``: Hy-MT2-7B Q4_K_M (con modo resumen).
    - ``>= 2 300 + 1 024``: la reserva Hy-MT2-1.8B Q8_0 (sin modo resumen); se avisa en el registro.
    - Menos: ``EngineError(recoverable=False)``.
    """
    big, small = MtModel.HY_MT2_7B, MtModel.HY_MT2_1_8B
    if free_mb >= big.required_free_mib:
        return big
    if free_mb >= small.required_free_mib:
        logger.warning(
            "VRAM libre insuficiente para Hy-MT2-7B (%.0f MiB libres, hacen falta %d): se usa la reserva "
            "Hy-MT2-1.8B, sin modo resumen.",
            free_mb,
            big.required_free_mib,
        )
        return small
    raise EngineError(
        f"No hay VRAM libre para ningún modelo de traducción: quedan {free_mb:.0f} MiB y la reserva "
        f"Hy-MT2-1.8B necesita {small.required_free_mib} MiB ({small.vram_mib} del modelo más "
        f"{VRAM_MARGIN_MIB} de margen). Cierra las aplicaciones que usen la GPU.",
        engine=ENGINE,
        recoverable=False,
    )
