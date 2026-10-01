"""Análisis de una ejecución: latencias, WER, estabilidad de parciales y puntuación.

Todos los tiempos están en segundos del reloj de audio. La referencia de "habla real" son los
intervalos de energía del flujo (``StreamPlan.oracle_intervals``), independientes de Silero.

Definiciones (por segmento final ``f``):

- ``first_partial_latency_s``: primer parcial con texto menos el inicio real de la habla.
- ``first_text_latency_s``: lo mismo, pero si el motor no da parciales (motor B) cuenta el final.
- ``final_latency_s``: instante en que se emite el ``final`` menos el fin real de la habla.
- ``text_complete_latency_s``: primer parcial cuyo texto normalizado ya es igual al del final,
  menos el fin real de la habla (cuándo estaba disponible el texto, aunque el evento final llegue después).
- ``latency_breakdown``: ``vad_delay_s`` (decisión de cerrar el tramo menos fin real) y
  ``post_decision_s`` (emisión del final menos decisión: vaciado, cola e inferencia).
- ``utterance``: lo mismo por enunciado completo (solo en el flujo con huecos).
"""

from __future__ import annotations

import numpy as np

from . import metrics
from .data import StreamPlan


def _true_span(intervals: list[tuple[float, float]], f: dict):
    """Inicio y fin reales de la habla de un segmento final y si llegó con habla en curso.

    - Con fin de habla del VAD (``t_end``) y sin corte forzado, el fin real es el del último
      intervalo de habla que empezó antes de ese fin del VAD.
    - Sin él (endpoint nativo) o con corte forzado, el fin real es el del último intervalo
      terminado antes de emitirse el final; si hay habla en curso al emitirlo, es un corte a
      mitad de habla (``mid``).
    """
    emitted = f["emitted_at"]
    seg_start = f.get("t_start") or 0.0
    t_end = f.get("t_end")
    forced = bool(f.get("forced"))
    vad_closed = t_end is not None and not forced
    horizon = t_end if vad_closed else emitted
    started = [iv for iv in intervals if iv[1] > seg_start and iv[0] < horizon]
    true_start = started[0][0] if started else None
    if vad_closed:
        cand = [iv for iv in intervals if iv[0] < t_end]
        return true_start, (cand[-1][1] if cand else None), False
    ended = [iv for iv in intervals if iv[1] <= emitted]
    mid = any(iv[0] < emitted < iv[1] for iv in intervals)
    return true_start, (ended[-1][1] if ended else None), mid


def analyze(plan: StreamPlan, events: list[dict], *, paced: bool) -> dict:
    iv = plan.oracle_intervals
    finals = sorted((e for e in events if e["type"] == "final"), key=lambda e: e["emitted_at"])
    partials_by_seg: dict[int, list[dict]] = {}
    for e in events:
        if e["type"] == "partial":
            partials_by_seg.setdefault(e["seg"], []).append(e)

    first_partial, first_text, final_lat, complete_lat, forced_lag = [], [], [], [], []
    vad_delay, post_decision = [], []
    seg_durations, n_partials = [], []
    retracted_all, unstable_all = [], []
    mid_word_count = partial_count = 0
    transitions = retracted_transitions = 0
    equals_last = with_partials = 0
    forced = 0
    rows = []
    first_text_at_by_row: list[float] = []
    for f in finals:
        ts, te, mid = _true_span(iv, f)
        parts = partials_by_seg.get(f["seg"], [])
        is_forced = bool(f.get("forced")) or mid
        first_text_at = parts[0]["emitted_at"] if parts else f["emitted_at"]
        first_text_at_by_row.append(first_text_at)
        row = {
            "seg": f["seg"],
            "text": f["text"],
            "t_start": f.get("t_start"),
            "t_end": f.get("t_end"),
            "decided_at": f.get("decided_at"),
            "emitted_at": round(f["emitted_at"], 3),
            "true_start": ts,
            "true_end": te,
            "forced": is_forced,
            "n_partials": len(parts),
        }
        if is_forced:
            forced += 1
        if parts and ts is not None:
            fp = parts[0]["emitted_at"] - ts
            row["first_partial_latency_s"] = round(fp, 3)
            first_partial.append(fp)
        if ts is not None:
            ft = first_text_at - ts
            row["first_text_latency_s"] = round(ft, 3)
            first_text.append(ft)
        if f.get("forced") and f.get("t_end") is not None:
            forced_lag.append(f["emitted_at"] - f["t_end"])
        if te is not None and not is_forced:
            fl = f["emitted_at"] - te
            row["final_latency_s"] = round(fl, 3)
            final_lat.append(fl)
            if f.get("decided_at") is not None:
                vd, pd = f["decided_at"] - te, f["emitted_at"] - f["decided_at"]
                row["vad_delay_s"], row["post_decision_s"] = round(vd, 3), round(pd, 3)
                vad_delay.append(vd)
                post_decision.append(pd)
            fin_norm = metrics.normalize_en(f["text"])
            for p in parts:
                if metrics.normalize_en(p["text"]) == fin_norm:
                    cl = p["emitted_at"] - te
                    row["text_complete_latency_s"] = round(cl, 3)
                    complete_lat.append(cl)
                    break
        if ts is not None and te is not None:
            seg_durations.append(te - ts)
        if parts:
            with_partials += 1
            equals_last += metrics.normalize_en(parts[-1]["text"]) == metrics.normalize_en(f["text"])
            n_partials.append(len(parts))
            st = metrics.partial_stability([p["text"] for p in parts], f["text"])
            retracted_all.extend(st["retracted"])
            unstable_all.extend(st["unstable_tail"])
            transitions += len(st["retracted"])
            retracted_transitions += sum(1 for r in st["retracted"] if r > 0)
            mid_word_count += sum(st["mid_word"])
            partial_count += len(st["mid_word"])
        rows.append(row)

    # WER de corpus sobre la concatenación (robusto a la segmentación).
    ref_texts = [u["text"] for u in plan.utterances]
    hyp_texts = [f["text"] for f in finals]
    wer = metrics.corpus_wer(ref_texts, hyp_texts)

    per_utt = None
    utterance_lat = None
    if plan.name == "gapped":
        assigned: list[list[int]] = [[] for _ in plan.utterances]
        for idx, f in enumerate(finals):
            a = f.get("t_start")
            b = f.get("t_end") if f.get("t_end") is not None else f["emitted_at"]
            if a is None:
                continue
            best, best_ov = None, 0.0
            for i, u in enumerate(plan.utterances):
                ov = min(u["end"], b) - max(u["start"], a)
                if ov > best_ov:
                    best, best_ov = i, ov
            if best is not None:
                assigned[best].append(idx)
        joined = [" ".join(finals[i]["text"] for i in idxs) for idxs in assigned]
        w = metrics.per_utterance_wer(ref_texts, joined)
        per_utt = {
            "wer_mean": float(np.mean(w)),
            "wer_p95": float(np.percentile(w, 95)),
            "perfect": int(sum(1 for v in w if v == 0)),
            "n": len(w),
            "empty_utterances": int(sum(1 for idxs in assigned if not idxs)),
            "finals_per_utterance": metrics.pct([len(idxs) for idxs in assigned], qs=(50, 95)),
        }
        u_first, u_final = [], []
        for u, idxs in zip(plan.utterances, assigned, strict=True):
            if not idxs or u.get("speech_start") is None or u.get("speech_end") is None:
                continue
            u_first.append(min(first_text_at_by_row[i] for i in idxs) - u["speech_start"])
            u_final.append(max(finals[i]["emitted_at"] for i in idxs) - u["speech_end"])
        utterance_lat = {
            "first_text_latency_s": metrics.pct(u_first),
            "final_latency_s": metrics.pct(u_final),
        }

    prof = [metrics.punctuation_profile(f["text"]) for f in finals]
    total_words = sum(p["words"] for p in prof) or 1
    punctuation = {
        "finals": len(prof),
        "commas_per_100_words": 100 * sum(p["commas"] for p in prof) / total_words,
        "terminal_marks_per_100_words": 100 * sum(p["terminal_marks"] for p in prof) / total_words,
        "finals_ending_with_terminal_pct": 100 * sum(p["ends_with_terminal"] for p in prof) / max(len(prof), 1),
        "finals_starting_uppercase_pct": 100 * sum(1 for f in finals if f["text"][:1].isupper()) / max(len(finals), 1),
        "capitalized_words_per_100_words": 100 * sum(p["capitalized_words"] for p in prof) / total_words,
    }

    return {
        "n_segments": len(finals),
        "n_forced_cuts": forced,
        "n_discarded": sum(1 for e in events if e["type"] == "discard"),
        "segment_duration_s": metrics.pct(seg_durations, qs=(50, 95)),
        "first_partial_latency_s": metrics.pct(first_partial),
        "first_text_latency_s": metrics.pct(first_text),
        "final_latency_s": metrics.pct(final_lat),
        "text_complete_latency_s": metrics.pct(complete_lat),
        "latency_breakdown": {
            "vad_delay_s": metrics.pct(vad_delay),
            "post_decision_s": metrics.pct(post_decision),
        },
        "forced_cut_lag_s": metrics.pct(forced_lag),
        "utterance": utterance_lat,
        "final_equals_last_partial_pct": (100 * equals_last / with_partials) if with_partials else None,
        "partials_per_segment": metrics.pct(n_partials),
        "partial_transitions": transitions,
        "partial_retraction_rate": (retracted_transitions / transitions) if transitions else None,
        "partial_mid_word_rate": (mid_word_count / partial_count) if partial_count else None,
        "partial_retracted_chars": metrics.pct(retracted_all, qs=(50, 95, 99)),
        "partial_unstable_tail_chars": metrics.pct(unstable_all, qs=(50, 95, 99)),
        "wer": wer,
        "per_utterance": per_utt,
        "punctuation": punctuation,
        "segments": rows,
    }
