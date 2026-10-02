"""«Vosotros» con ``llama-server`` y Hy-MT2-7B reales (T019, SC-006).

Marcadores ``gpu`` y ``model``: necesita la GPU, ``llama-server`` y el GGUF del 7B colocado por ``preparar``
(``%LOCALAPPDATA%\\InstantTraductor``). Solo la ejecuta el orquestador, de una en una:

    uv run pytest tests/integration/test_vosotros_model.py -m "gpu and model"

Usa el corpus B0 del spike S7 (``spikes/habla_baja/corpus_b0.py``): 228 frases inglesas en 38 escenas de 6
líneas, con la etiqueta esperada de cada una (P = «you» plural informal, S = singular, F = formal, T = 3.ª
persona del plural). Cada frase se traduce en modo normal con las 4 traducciones previas de su escena como
contexto (lo que verá la sesión) y se mide con el detector del mismo spike (``spikes/habla_baja/detector.py``,
precisión del 97,6 % en «vosotros» contra el etiquetado a mano).

SC-006 (revisado el 2026-10-02): en las frases con plural informal, al menos el 80 % usa «vosotros» y como
mucho el 2 % usa «ustedes».
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from instanttraductor.contracts import (
    TranslationMode,
    TranslationRequest,
    TranslationResult,
    TranslationUnit,
)
from instanttraductor.mt.hymt2 import HyMt2Translator
from instanttraductor.mt.llama_server import LlamaServerProcess, llama_server_exe
from instanttraductor.mt.selection import MtModel, model_path
from instanttraductor.pipeline.clock import SessionClock

pytestmark = [pytest.mark.gpu, pytest.mark.model, pytest.mark.timeout(1800)]

SPIKE_DIR = Path(__file__).resolve().parents[2] / "spikes" / "habla_baja"
#: Frases previas de la misma escena que se dan como contexto (ADR-0011).
CONTEXT_PAIRS = 4
#: SC-006: mínimo de plurales informales en «vosotros» y máximo en «ustedes».
MIN_VOSOTROS = 0.80
MAX_USTEDES = 0.02

Results = list[tuple[object, TranslationResult]]  # (línea del corpus, resultado)


def _load(name: str) -> ModuleType:
    """Un módulo del spike, cargado por ruta (``spikes/`` no es un paquete importable)."""
    path = SPIKE_DIR / f"{name}.py"
    if not path.is_file():
        pytest.skip(f"falta {path}")
    spec = importlib.util.spec_from_file_location(f"spike_habla_baja_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # los dataclasses del corpus buscan su módulo en sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def corpus() -> ModuleType:
    return _load("corpus_b0")


@pytest.fixture(scope="module")
def detector() -> ModuleType:
    return _load("detector")


@pytest.fixture(scope="module")
def translator() -> Iterator[HyMt2Translator]:
    """``llama-server`` con el 7B y su traductor."""
    path = model_path(MtModel.HY_MT2_7B)
    for needed in (llama_server_exe(), path):
        if not needed.is_file():
            pytest.skip(f"falta {needed}: ejecuta «instanttraductor preparar»")
    server = LlamaServerProcess(path)
    server.start()
    try:
        server.wait_ready()
        instance = HyMt2Translator(server.base_url, MtModel.HY_MT2_7B, clock=SessionClock())
        try:
            yield instance
        finally:
            instance.close()
    finally:
        server.stop()


def _request(unit_id: int, text: str, context: tuple[tuple[str, str], ...]) -> TranslationRequest:
    unit = TranslationUnit(
        unit_id=unit_id, source_text=text, t_start=0.0, t_end=1.0, is_sentence_end=True, ready_at=1.0
    )
    return TranslationRequest(unit=unit, context=context, glossary=(), mode=TranslationMode.NORMAL)


@pytest.fixture(scope="module")
def results(corpus: ModuleType, translator: HyMt2Translator) -> Results:
    """Las 228 líneas de B0, escena a escena, con sus 4 traducciones previas como contexto."""
    by_scene: dict[int, list[object]] = {}
    for line in corpus.LINES:
        by_scene.setdefault(line.scene, []).append(line)
    translated: Results = []
    for lines in by_scene.values():
        history: list[tuple[str, str]] = []
        for line in lines:
            result = translator.translate(_request(line.idx, line.text, tuple(history[-CONTEXT_PAIRS:])))
            translated.append((line, result))
            if result.text:
                history.append((line.text, result.text))
    return translated


def _plural_marks(detector: ModuleType, results: Results) -> tuple[int, list[str]]:
    """Número de frases con plural informal (etiqueta P) y la marca principal de cada una."""
    primaries = [detector.primary(result.text, line.text) for line, result in results if line.label == "P"]
    return len(primaries), primaries


def test_the_corpus_has_the_228_lines_and_all_of_them_were_translated(
    corpus: ModuleType, results: Results
) -> None:
    assert len(corpus.LINES) == len(results) == 228
    assert all(result.unit_id == line.idx for line, result in results)


def test_at_least_80_percent_of_the_informal_plurals_use_vosotros(
    detector: ModuleType, results: Results
) -> None:
    total, primaries = _plural_marks(detector, results)
    share = primaries.count("vos") / total

    assert total == 167
    assert share >= MIN_VOSOTROS, f"«vosotros» en {share:.1%} de {total} plurales (mínimo {MIN_VOSOTROS:.0%})"


def test_at_most_2_percent_of_the_informal_plurals_use_ustedes(
    detector: ModuleType, results: Results
) -> None:
    total, primaries = _plural_marks(detector, results)
    share = primaries.count("ust") / total

    assert share <= MAX_USTEDES, f"«ustedes» en {share:.1%} de {total} plurales (máximo {MAX_USTEDES:.0%})"
