"""Bucle de traducción por escenas: contexto previo + glosario + petición al servidor.

Imita lo que hará la aplicación: las frases llegan en orden, el contexto son los
últimos 3-5 pares (fuente, lo que REALMENTE se tradujo) de la misma escena y el
glosario solo incluye los términos que aparecen en la frase o en ese contexto.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

from client import Translator
from corpus import GLOSSARY, SPAIN_LEXICON, Line, count_words
from prompts import Glossary, History, PromptConfig, build_messages, messages_to_text

#: Pares de contexto por defecto (el ADR pide entre 3 y 5).
N_PAIRS = 4


def max_tokens_for(text: str) -> int:
    """Tope de tokens de salida: ~4 por palabra de origen, entre 64 y 512."""
    return min(512, max(64, 4 * count_words(text)))


def history_for(lines: tuple[Line, ...], idx: int, outputs: dict[int, str], n_pairs: int = N_PAIRS) -> History:
    """Los ``n_pairs`` pares previos de la MISMA escena (más antiguo primero)."""
    scene = lines[idx].scene
    pairs: list[tuple[str, str]] = []
    j = idx - 1
    while j >= 0 and lines[j].scene == scene and len(pairs) < n_pairs:
        if lines[j].id in outputs:
            pairs.append((lines[j].text, outputs[lines[j].id]))
        j -= 1
    return tuple(reversed(pairs))


def glossary_for(source: str, history: History, glossary: Glossary = GLOSSARY) -> Glossary:
    """Entradas del glosario cuyo término aparece (como palabra) en la frase o el contexto."""
    haystack = " ".join([source, *[en for en, _es in history]])
    return tuple(
        (s, t) for s, t in glossary if re.search(rf"\b{re.escape(s)}\b", haystack, re.IGNORECASE)
    )


def run_pass(
    tr: Translator,
    lines: tuple[Line, ...],
    cfg: PromptConfig,
    *,
    stream: bool,
    seed: int = 42,
    frozen: dict[int, str] | None = None,
    pace_s: float = 0.0,
    n_pairs: int = N_PAIRS,
    glossary_mode: str = "match",
    cache_prompt: bool = False,
    on_record: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Traduce todas las líneas en orden. Devuelve un registro por petición.

    ``frozen``: si se da, el contexto se construye con esas traducciones (así varias
    pasadas usan prompts idénticos byte a byte); si no, con las de esta misma pasada.
    ``glossary_mode``: ``match`` (solo entradas presentes), ``all`` o ``none``.
    """
    outputs: dict[int, str] = {}
    records: list[dict] = []
    for idx, line in enumerate(lines):
        source_map = frozen if frozen is not None else outputs
        history = history_for(lines, idx, source_map, n_pairs) if cfg.context else ()
        entries = GLOSSARY + SPAIN_LEXICON if cfg.lexicon else GLOSSARY
        if not cfg.glossary or glossary_mode == "none":
            glossary: Glossary = ()
        elif glossary_mode == "all":
            glossary = entries
        else:
            glossary = glossary_for(line.text, history, entries)
        messages = build_messages(line.text, cfg, history, glossary)
        if pace_s and idx:
            time.sleep(pace_s)
        res = tr.complete(
            messages,
            stream=stream,
            max_tokens=max_tokens_for(line.text),
            temperature=cfg.temperature,
            seed=seed,
            cache_prompt=cache_prompt,
        )
        text = res.text.strip()
        outputs[line.id] = text
        rec = {
            "line_id": line.id,
            "config": cfg.name,
            "seed": seed,
            "n_history": len(history),
            "n_glossary": len(glossary),
            "prompt": messages_to_text(messages),
            "output": text,
            **{k: v for k, v in res.as_dict().items() if k != "text"},
        }
        records.append(rec)
        if on_record:
            on_record(rec)
    return records
