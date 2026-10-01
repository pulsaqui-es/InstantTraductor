"""Integración de ``HyMt2Translator`` con ``llama-server`` y los modelos Hy-MT2 reales (T022).

Marcadores ``gpu`` y ``model``: necesita la GPU, ``llama-server`` y los GGUF colocados por ``preparar``
(``%LOCALAPPDATA%\\InstantTraductor``). Solo la ejecuta el orquestador, de una en una:

    uv run pytest tests/integration/test_hymt2_model.py -m "gpu and model"

Usa el corpus del spike S2 (``spikes/traduccion/corpus.py``): 65 líneas de diálogo en 11 escenas, las 4
frases previas de la escena como contexto y el glosario inventado de la escena 11. Comprueba, con el 7B y
con la reserva 1.8B, que ninguna salida es algo distinto de una traducción, y con el 7B que el modo
CONCISE acorta al menos un 20 % las palabras en las 10 frases largas del banco de pruebas de S2.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from instanttraductor.contracts import (
    GlossaryEntry,
    TranslationMode,
    TranslationRequest,
    TranslationResult,
    TranslationUnit,
)
from instanttraductor.mt.hymt2 import HyMt2Translator, count_words
from instanttraductor.mt.llama_server import LlamaServerProcess, llama_server_exe
from instanttraductor.mt.selection import MtModel, model_path
from instanttraductor.pipeline.clock import SessionClock

pytestmark = [pytest.mark.gpu, pytest.mark.model, pytest.mark.timeout(900)]

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPO_ROOT / "spikes" / "traduccion" / "corpus.py"
#: Frases previas de la misma escena que se dan como contexto (ADR-0011).
CONTEXT_PAIRS = 4
#: Reducción mínima de palabras del modo CONCISE del 7B respecto al modo normal (T022).
MIN_CONCISE_REDUCTION = 0.20

#: Palabras inglesas que no existen en español: dos o más en la salida indican texto sin traducir.
ENGLISH_STOPWORDS = frozenset(
    {"the", "and", "you", "is", "are", "of", "that", "this", "with", "for", "was", "have", "but", "your"}
    | {"what", "they", "she", "my", "at", "be", "do", "can", "will", "on", "it"}
)
_WORDS = re.compile(r"[\w']+")


@pytest.fixture(scope="module")
def corpus() -> ModuleType:
    """El corpus de S2, cargado por ruta (``spikes/`` no es un paquete importable)."""
    if not CORPUS_PATH.is_file():
        pytest.skip(f"falta {CORPUS_PATH}")
    spec = importlib.util.spec_from_file_location("spike_traduccion_corpus", CORPUS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # los dataclasses del corpus buscan su módulo en sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module", params=list(MtModel), ids=lambda model: model.value)
def served(request: pytest.FixtureRequest) -> Iterator[tuple[MtModel, HyMt2Translator]]:
    """``llama-server`` con el modelo de la parametrización y su traductor. Uno cada vez: no caben juntos."""
    model: MtModel = request.param
    path = model_path(model)
    for needed in (llama_server_exe(), path):
        if not needed.is_file():
            pytest.skip(f"falta {needed}: ejecuta «instanttraductor preparar»")
    server = LlamaServerProcess(path)
    server.start()
    try:
        server.wait_ready()
        translator = HyMt2Translator(server.base_url, model, clock=SessionClock())
        try:
            yield model, translator
        finally:
            translator.close()
    finally:
        server.stop()


def _glossary_for(
    corpus: ModuleType, source: str, context: tuple[tuple[str, str], ...]
) -> tuple[GlossaryEntry, ...]:
    """Entradas del glosario del corpus cuyo término aparece en la frase o en el contexto (como en S2)."""
    haystack = " ".join([source, *(original for original, _ in context)])
    return tuple(
        GlossaryEntry(term, target)
        for term, target in corpus.GLOSSARY
        if re.search(rf"\b{re.escape(term)}\b", haystack, re.IGNORECASE)
    )


def _request(
    unit_id: int,
    text: str,
    mode: TranslationMode,
    context: tuple[tuple[str, str], ...],
    glossary: tuple[GlossaryEntry, ...],
) -> TranslationRequest:
    unit = TranslationUnit(
        unit_id=unit_id, source_text=text, t_start=0.0, t_end=1.0, is_sentence_end=True, ready_at=1.0
    )
    return TranslationRequest(unit=unit, context=context, glossary=glossary, mode=mode)


def _non_translation_problems(source: str, result: TranslationResult) -> list[str]:
    """Motivos por los que la salida no es una traducción (los filtros del traductor y dos más, de S2)."""
    if result.rejected:
        return ["rechazada por los filtros de salida"]
    problems = []
    text = result.text
    if not text.strip():
        problems.append("vacía")
    leaked = ENGLISH_STOPWORDS.intersection(word.lower() for word in _WORDS.findall(text))
    if len(leaked) >= 2:
        problems.append(f"inglés sin traducir ({sorted(leaked)})")
    if text.lower().strip(" .!?¡¿") == source.lower().strip(" .!?"):
        problems.append("copia del original")
    return problems


Results = dict[int, tuple[str, TranslationResult]]


def _translate_scene_by_scene(corpus: ModuleType, translator: HyMt2Translator) -> Results:
    """Traduce las 65 líneas en orden. El contexto son las traducciones reales previas de la misma escena."""
    results: Results = {}
    for index, line in enumerate(corpus.LINES):
        context: list[tuple[str, str]] = []
        previous = index - 1
        while previous >= 0 and corpus.LINES[previous].scene == line.scene and len(context) < CONTEXT_PAIRS:
            earlier = corpus.LINES[previous]
            if earlier.id in results and results[earlier.id][1].text:
                context.append((earlier.text, results[earlier.id][1].text))
            previous -= 1
        history = tuple(reversed(context))
        glossary = _glossary_for(corpus, line.text, history)
        request = _request(line.id, line.text, TranslationMode.NORMAL, history, glossary)
        results[line.id] = (line.text, translator.translate(request))
    return results


@pytest.fixture(scope="module")
def normal_results(corpus: ModuleType, served: tuple[MtModel, HyMt2Translator]) -> Results:
    """Las 65 líneas en modo normal, una sola vez por modelo."""
    return _translate_scene_by_scene(corpus, served[1])


def test_no_output_of_the_corpus_is_a_non_translation(
    served: tuple[MtModel, HyMt2Translator], normal_results: Results
) -> None:
    model, translator = served
    assert translator.supports_concise is (model is MtModel.HY_MT2_7B)

    failures = {
        line_id: (problems, result.text)
        for line_id, (source, result) in normal_results.items()
        if (problems := _non_translation_problems(source, result))
    }
    assert len(normal_results) == 65
    assert not failures, f"{len(failures)} salidas de {model.value} que no son traducción: {failures}"
    assert all(result.unit_id == line_id for line_id, (_, result) in normal_results.items())


def test_the_glossary_of_the_corpus_is_respected(
    corpus: ModuleType, served: tuple[MtModel, HyMt2Translator], normal_results: Results
) -> None:
    """Las 5 frases de la escena 11 llevan términos inventados: tienen que salir tal cual del glosario."""
    model, _ = served

    missing = [
        (line.id, expected, normal_results[line.id][1].text)
        for line in corpus.LINES
        for expected in line.glossary_expect
        if expected.casefold() not in normal_results[line.id][1].text.casefold()
    ]
    # S2 midió 10/10 con ambos modelos; se tolera 1 fallo por el muestreo.
    assert len(missing) <= 1, f"{model.value}: términos del glosario que no salen: {missing}"


def test_concise_mode_of_the_7b_cuts_at_least_20_percent_of_the_words(
    corpus: ModuleType, served: tuple[MtModel, HyMt2Translator], normal_results: Results
) -> None:
    model, translator = served
    if model is not MtModel.HY_MT2_7B:
        pytest.skip("solo el 7B sabe resumir")

    normal_words = 0
    concise_words = 0
    for line_id in corpus.CONCISE_IDS:  # las 10 primeras frases largas (>= 15 palabras)
        line = corpus.BY_ID[line_id]
        concise = translator.translate(_request(line_id, line.text, TranslationMode.CONCISE, (), ()))
        assert concise.mode is TranslationMode.CONCISE
        assert not concise.rejected, f"línea {line_id}: el resumen se rechazó"
        assert _non_translation_problems(line.text, concise) == []
        normal_words += count_words(normal_results[line_id][1].text)
        concise_words += count_words(concise.text)

    reduction = 1 - concise_words / normal_words
    assert reduction >= MIN_CONCISE_REDUCTION, (
        f"CONCISE recorta solo un {reduction:.0%} de las palabras ({concise_words} frente a {normal_words}); "
        f"hacía falta al menos un {MIN_CONCISE_REDUCTION:.0%}"
    )


def test_the_1_8b_cannot_summarise_so_it_answers_in_normal_mode(
    corpus: ModuleType, served: tuple[MtModel, HyMt2Translator]
) -> None:
    model, translator = served
    if model is not MtModel.HY_MT2_1_8B:
        pytest.skip("solo la reserva 1.8B ignora el modo resumen")
    line = corpus.BY_ID[corpus.CONCISE_IDS[0]]

    result = translator.translate(_request(line.id, line.text, TranslationMode.CONCISE, (), ()))

    assert result.mode is TranslationMode.NORMAL
    assert not result.rejected
