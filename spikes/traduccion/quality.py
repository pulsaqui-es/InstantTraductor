"""Heurísticas de observación de calidad (NO es una métrica formal).

Sirven para detectar de forma automática lo evidente (muletillas tipo «Aquí tienes la
traducción», texto que no está en español, respuestas en vez de traducciones, léxico
no peninsular, glosario no respetado...) y dirigir la lectura humana de las salidas.
Son los filtros de seguridad que plantea el ADR-0007: idioma de salida, proporción de
longitud y lista negra de muletillas.
"""

from __future__ import annotations

import re

from corpus import KEY_TERMS, Line, count_words

_FLAGS = re.IGNORECASE | re.UNICODE

#: Muletillas al principio de la salida («Aquí tienes la traducción:», «Sure, ...»).
BOILERPLATE_START = re.compile(
    r"^\W*(aqu[ií]\s+(tienes|est[aá]|va|te\s+dejo)|"
    r"(claro|por supuesto|desde luego|sure|of course)\s*[,:;!.]\s*\S+|"
    r"la traducci[oó]n|traducci[oó]n\s*:|esta es la traducci[oó]n|resultado\s*:|"
    r"here(?:'s|\s+is)\b|translation\s*:|translated\b|note\s*:|nota\s*:|"
    r"\(nota|\(note|espero que|como (?:pediste|solicitaste)|en espa[ñn]ol\s*:)",
    _FLAGS,
)
#: Indicios de explicación en cualquier parte de la salida.
BOILERPLATE_ANYWHERE = re.compile(
    r"\b(traducci[oó]n|translation|explicaci[oó]n|explanation|nota|note)\s*:", _FLAGS
)
LABEL_PREFIX = re.compile(
    r"^\s*(\[|<)?\s*(spanish|espa[ñn]ol|english|ingl[eé]s|source text|texto (de origen|original|fuente|a traducir)|background|informaci[oó]n de fondo|contexto|antecedentes|source|fuente)\b(\]|>)?\s*:?",
    _FLAGS,
)
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
#: Palabras inglesas que no existen en español (para detectar texto sin traducir).
ENGLISH_STOPWORDS = frozenset({
    "the", "and", "you", "is", "are", "of", "that", "this", "with", "for", "was", "have", "but",
    "your", "what", "they", "she", "my", "at", "be", "do", "can", "will", "on", "it",
})
SPANISH_MARKERS = re.compile(
    r"[áéíóúñ¿¡]|\b(el|la|los|las|de|del|que|y|en|un|una|es|no|me|te|se|lo|por|con|para|al|mi|tu|su|a)\b",
    _FLAGS,
)
QUOTE_CHARS = "\"'“”‘’«»`"


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower(), re.UNICODE)


def length_ratio(source: str, output: str) -> float:
    """Caracteres de la salida entre caracteres de la fuente."""
    return len(output.strip()) / max(1, len(source.strip()))


def check_output(line: Line, output: str, finish_reason: str | None = "stop") -> dict:
    """Devuelve las banderas y comprobaciones de una traducción."""
    out = output.strip()
    words = _words(out)
    en_hits = sorted(ENGLISH_STOPWORDS.intersection(words))
    ratio = length_ratio(line.text, out)

    flags = {
        "empty": not out,
        "boilerplate": bool(BOILERPLATE_START.search(out) or BOILERPLATE_ANYWHERE.search(out)),
        "label_prefix": bool(LABEL_PREFIX.search(out)),
        "multiline": "\n" in out,
        "wrapped": len(out) >= 2 and out[0] in QUOTE_CHARS and out[-1] in QUOTE_CHARS,
        "cjk": bool(CJK.search(out)),
        "english_leak": len(en_hits) >= 2,
        "not_spanish": len(words) >= 4 and not SPANISH_MARKERS.search(out) and len(en_hits) >= 1,
        "copied_source": out.lower().strip(" .!?") == line.text.lower().strip(" .!?"),
        "truncated": finish_reason not in ("stop", None),
        "question_lost": line.text.rstrip().endswith("?") and "?" not in out,
        "len_ratio_flag": len(line.text) >= 20 and not (0.55 <= ratio <= 2.0),
    }

    checks = []
    for label, expect, forbid in line.checks:
        ok_expect = True if expect is None else bool(re.search(expect, out, _FLAGS))
        ok_forbid = True if forbid is None else not re.search(forbid, out, _FLAGS)
        checks.append({"label": label, "ok": ok_expect and ok_forbid, "expect": ok_expect, "forbid": ok_forbid})

    plural = None
    if line.plural_you is not None:
        vos_rx, ust_rx = line.plural_you
        if re.search(vos_rx, out, _FLAGS):
            plural = "vosotros"
        elif re.search(ust_rx, out, _FLAGS):
            plural = "ustedes"
        else:
            plural = "neutral"

    glossary = [
        {"expected": term, "ok": term.casefold() in out.casefold()} for term in line.glossary_expect
    ]

    trap_fail = line.trap and any(not c["ok"] for c in checks)
    non_translation = any(
        flags[k]
        for k in (
            "empty",
            "boilerplate",
            "label_prefix",
            "cjk",
            "english_leak",
            "not_spanish",
            "copied_source",
            "truncated",
        )
    ) or trap_fail

    return {
        "flags": flags,
        "len_ratio": round(ratio, 2),
        "english_hits": en_hits,
        "checks": checks,
        "plural_you": plural,
        "glossary": glossary,
        "trap_fail": trap_fail,
        "non_translation": non_translation,
    }


def summarize_checks(results: list[tuple[Line, dict]]) -> dict:
    """Agrega las comprobaciones de un conjunto de salidas (una configuración)."""
    n = len(results)
    count = lambda key: sum(1 for _l, r in results if r["flags"][key])  # noqa: E731
    lex = [c for ln, r in results if not ln.trap for c in r["checks"]]
    plural = [r["plural_you"] for _l, r in results if r["plural_you"] is not None]
    gloss = [g for _l, r in results for g in r["glossary"]]
    return {
        "n": n,
        "boilerplate": count("boilerplate"),
        "label_prefix": count("label_prefix"),
        "multiline": count("multiline"),
        "wrapped": count("wrapped"),
        "cjk": count("cjk"),
        "english_leak": count("english_leak"),
        "not_spanish": count("not_spanish"),
        "copied_source": count("copied_source"),
        "truncated": count("truncated"),
        "question_lost": count("question_lost"),
        "len_ratio_flag": count("len_ratio_flag"),
        "trap_fail": sum(1 for _l, r in results if r["trap_fail"]),
        "non_translation": sum(1 for _l, r in results if r["non_translation"]),
        "lexical_ok": sum(1 for c in lex if c["ok"]),
        "lexical_total": len(lex),
        "plural_vosotros": plural.count("vosotros"),
        "plural_ustedes": plural.count("ustedes"),
        "plural_neutral": plural.count("neutral"),
        "plural_total": len(plural),
        "glossary_ok": sum(1 for g in gloss if g["ok"]),
        "glossary_total": len(gloss),
    }


def key_recall(line_id: int, text: str) -> dict:
    """Elementos clave de una frase del modo resumen que conserva la traducción."""
    keys = KEY_TERMS[line_id]
    hit = [label for label, rx in keys if re.search(rx, text, _FLAGS)]
    missing = [label for label, _rx in keys if label not in hit]
    return {"hit": hit, "missing": missing, "n_hit": len(hit), "n_total": len(keys)}


def reduction_pct(normal: int | float, concise: int | float) -> float:
    """Reducción porcentual de longitud del texto conciso respecto al normal."""
    if not normal:
        return 0.0
    return 100.0 * (1.0 - concise / normal)


def words_and_chars(text: str) -> tuple[int, int]:
    """Palabras y caracteres (con espacios) de un texto."""
    return count_words(text), len(text.strip())
