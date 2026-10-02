"""Normalización de texto y métricas (CER) del spike S5.

Normalización (igual para referencia e hipótesis):
1. NFKC (unifica anchos: ``ＡＢＣ１２３`` y ``ABC123``, kana de medio ancho, ``１５`` y ``15``).
2. Minúsculas.
3. Fuera toda puntuación y símbolos (categorías Unicode ``P*`` y ``S*``) y todos los espacios y controles.
4. Solo en japonés y chino: los números escritos con ideogramas (``千九百六十七``, ``二〇一一``) pasan a cifras.
   Se aplica por igual a referencia e hipótesis, de modo que solo se unifica ``2011`` con ``二〇一一``.
El CER es el de corpus (errores de carácter / caracteres de referencia), con ``jiwer``.
"""

from __future__ import annotations

import re
import unicodedata

import jiwer

_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_SMALL = {"十": 10, "百": 100, "千": 1000}
_BIG = {"万": 10_000, "萬": 10_000, "億": 100_000_000, "亿": 100_000_000}
_NUMERAL_RUN = re.compile("[" + "".join([*_DIGITS, *_SMALL, *_BIG]) + "]+")


def _numeral_to_int(run: str) -> str:
    """Convierte una tira de numerales de ideogramas a cifras (``二〇一一`` -> 2011; ``千九百六十七`` -> 1967)."""
    if not any(c in _SMALL or c in _BIG for c in run):
        return "".join(str(_DIGITS[c]) for c in run)  # notación posicional
    total, section, digit = 0, 0, 0
    for c in run:
        if c in _DIGITS:
            digit = _DIGITS[c]
        elif c in _SMALL:
            section += (digit or 1) * _SMALL[c]
            digit = 0
        else:
            total += (section + digit or 1) * _BIG[c]
            section = digit = 0
    return str(total + section + digit)


def normalize(text: str, lang: str) -> str:
    """Texto comparable para el CER (ver el docstring del módulo)."""
    text = unicodedata.normalize("NFKC", text).lower()
    if lang in ("ja", "zh"):
        text = _NUMERAL_RUN.sub(lambda m: _numeral_to_int(m.group(0)), text)
    return "".join(c for c in text if unicodedata.category(c)[0] not in "PSZC")


def cer(refs: list[str], hyps: list[str], lang: str) -> dict:
    """CER de corpus: errores de carácter / caracteres de la referencia (tras normalizar)."""
    r = [normalize(x, lang) for x in refs]
    h = [normalize(x, lang) for x in hyps]
    pairs = [(a, b) for a, b in zip(r, h, strict=True) if a]
    if not pairs:
        return {"cer": float("nan"), "ref_chars": 0}
    out = jiwer.process_characters([a for a, _ in pairs], [b for _, b in pairs])
    n = sum(len(a) for a, _ in pairs)
    return {
        "cer": (out.substitutions + out.deletions + out.insertions) / n,
        "sub": out.substitutions,
        "del": out.deletions,
        "ins": out.insertions,
        "ref_chars": n,
    }


def per_item_cer(ref: str, hyp: str, lang: str) -> float:
    a, b = normalize(ref, lang), normalize(hyp, lang)
    if not a:
        return float("nan")
    o = jiwer.process_characters(a, b)
    return (o.substitutions + o.deletions + o.insertions) / len(a)


# --- Escritura del texto reconocido (filtro de idioma por proporción de caracteres) -------------------------
_SCRIPT_RANGES = {
    "kana": [(0x3040, 0x30FF), (0x31F0, 0x31FF), (0xFF66, 0xFF9F)],
    "han": [(0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF)],
    "hangul": [(0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)],
    "latin": [(0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x24F)],
}


def script_of(ch: str) -> str | None:
    cp = ord(ch)
    for name, ranges in _SCRIPT_RANGES.items():
        if any(a <= cp <= b for a, b in ranges):
            return name
    return None


def script_fraction(text: str, lang: str) -> float:
    """Fracción de las letras del texto que pertenecen a la escritura propia del idioma.

    ja: kana o ideogramas (con kana presente); zh: ideogramas; ko: hangul. Texto sin letras: 0.
    """
    letters = [c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c)[0] == "L"]
    if not letters:
        return 0.0
    own = {"ja": {"kana", "han"}, "zh": {"han"}, "ko": {"hangul"}}[lang]
    good = sum(1 for c in letters if script_of(c) in own)
    return good / len(letters)
