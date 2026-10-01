"""Métricas: WER normalizado, percentiles, estabilidad de parciales y puntuación."""

from __future__ import annotations

import re
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _normalizer():
    from whisper_normalizer.english import EnglishTextNormalizer

    return EnglishTextNormalizer()


def normalize_en(text: str) -> str:
    """Normalizador inglés de Whisper (minúsculas, sin puntuación, números y ortografía unificados).

    Se aplica igual a la referencia y a la hipótesis, como en el Open ASR Leaderboard.
    """
    return _normalizer()(text).strip()


def wer_stats(refs: list[str], hyps: list[str]) -> dict:
    """WER de corpus (errores totales / palabras de referencia) sobre textos YA normalizados."""
    import jiwer

    pairs = [(r, h) for r, h in zip(refs, hyps, strict=True) if r.strip()]
    if not pairs:
        return {"wer": float("nan"), "sub": 0, "del": 0, "ins": 0, "ref_words": 0}
    r_list = [p[0] for p in pairs]
    h_list = [p[1] if p[1].strip() else "" for p in pairs]
    out = jiwer.process_words(r_list, h_list)
    n_ref = sum(len(r.split()) for r in r_list)
    return {
        "wer": (out.substitutions + out.deletions + out.insertions) / n_ref,
        "sub": out.substitutions,
        "del": out.deletions,
        "ins": out.insertions,
        "ref_words": n_ref,
    }


def corpus_wer(ref_texts: list[str], hyp_texts: list[str]) -> dict:
    """WER normalizado sobre la concatenación (robusto a cómo se haya segmentado la hipótesis)."""
    ref = normalize_en(" ".join(ref_texts))
    hyp = normalize_en(" ".join(hyp_texts))
    return wer_stats([ref], [hyp])


def per_utterance_wer(ref_texts: list[str], hyp_texts: list[str]) -> list[float]:
    vals = []
    for r, h in zip(ref_texts, hyp_texts, strict=True):
        rn, hn = normalize_en(r), normalize_en(h)
        if rn:
            vals.append(wer_stats([rn], [hn])["wer"])
    return vals


def pct(values, qs=(50, 95)) -> dict:
    """Percentiles de una lista (en las unidades de entrada). Vacía: NaN."""
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    out = {"n": int(arr.size)}
    if arr.size == 0:
        out.update({f"p{q}": float("nan") for q in qs})
        out.update({"mean": float("nan"), "min": float("nan"), "max": float("nan")})
        return out
    for q in qs:
        out[f"p{q}"] = float(np.percentile(arr, q))
    out.update({"mean": float(arr.mean()), "min": float(arr.min()), "max": float(arr.max())})
    return out


def common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def partial_stability(partials: list[str], final: str) -> dict:
    """Estabilidad de los parciales de un segmento respecto a su texto final.

    - ``retracted``: caracteres del parcial anterior que el siguiente parcial cambia o borra.
    - ``unstable_tail``: caracteres de cada parcial que NO coinciden con el prefijo del final
      (sirve para fijar ``stable_len = len(text) - K``).
    - ``mid_word``: el parcial termina a mitad de palabra (el final la alarga), es decir, la
      última palabra aún no es fiable aunque no se haya retractado ningún carácter.
    """
    retracted, unstable, mid_word = [], [], []
    prev = ""
    for p in partials:
        retracted.append(len(prev) - common_prefix_len(prev, p))
        unstable.append(len(p) - common_prefix_len(p, final))
        mid_word.append(len(final) > len(p) and final.startswith(p) and p[-1:].isalnum() and final[len(p)].isalnum())
        prev = p
    return {"retracted": retracted, "unstable_tail": unstable, "mid_word": mid_word}


_TERMINAL = re.compile(r"[.?!…]+[\"')\]]*$")


def punctuation_profile(text: str) -> dict:
    """Recuento simple de puntuación y mayúsculas de una hipótesis (para A frente a B)."""
    words = text.split()
    n = max(len(words), 1)
    commas = text.count(",")
    terminal = len(re.findall(r"[.?!]", text))
    return {
        "words": len(words),
        "commas": commas,
        "terminal_marks": terminal,
        "other_marks": len(re.findall(r"[;:\-—\"]", text)),
        "capitalized_words": sum(1 for w in words if w[:1].isupper()),
        "ends_with_terminal": bool(_TERMINAL.search(text.strip())),
        "marks_per_100_words": 100.0 * (commas + terminal) / n,
    }
