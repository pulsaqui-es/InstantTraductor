"""Análisis de una ejecución: latencias, WER, estabilidad de parciales y puntuación.

Todos los tiempos están en segundos del reloj de audio. La referencia de "habla real" son los
intervalos de energía del flujo (``StreamPlan.oracle_intervals``), independientes de Silero.
"""

from __future__ import annotations

import numpy as np

from . import metrics
from .data import StreamPlan


def _true_span(intervals: list[tuple[float, float]], seg_start: float, emitted_at: float):
    """Inicio y fin reales de la habla de un segmento, y si el final llegó con habla en curso."""
    # Fin: el último intervalo de habla que terminó antes de emitirse el final.
    ended = [iv for iv in intervals if iv[1] <= emitted_at]
    true_end = ended[-1][1] if ended else None
    mid_speech = any(iv[0] < emitted_at < iv[1] for iv in intervals)
    # Inicio: el primer intervalo que termina después del comienzo del segmento.
    started = [iv for iv in intervals if iv[1] > seg_start and iv[0] < emitted_at]
    true_start = started[0][0] if started else None
    return true_start, true_end, mid_speech


def analyze(plan: StreamPlan, events: list[dict], *, paced: bool) -> dict:
    iv = plan.oracle_intervals
    finals = sorted((e for e in events if e["type"] == "final"), key=lambda e: e["emitted_at"])
    partials_by_seg: dict[int, list[dict]] = {}
    for e in events:
        if e["type"] == "partial":
            partials_by_seg.setdefault(e["seg"], []).append(e)

    first_partial, first_text, final_lat, complete_lat, forced_lag = [], [], [], [], []
    seg_durations, n_partials = [], []
    retracted_all, unstable_all = [], []
    mid_word_count = 0
    partial_count = 0
    transitions = retracted_transitions = 0
    forced = 0
    rows = []
    for f in finals:
        ts, te, mid = _true_span(iv, f.get("t_start") or 0.0, f["emitted_at"])
        parts = partials_by_seg.get(f["seg"], [])
        row = {
            "seg": f["seg"],
            "text": f["text"],
            "emitted_at": round(f["emitted_at"], 3),
            "true_start": ts,
            "true_end": te,
            "forced": bool(f.get("forced")) or mid,
            "n_partials": len(parts),
        }
        if f.get("forced") or mid:
            forced += 1
        if parts and ts is not None:
            fp = parts[0]["emitted_at"] - ts
            row["first_partial_latency_s"] = round(fp, 3)
            first_partial.append(fp)
        if ts is not None:
            # Primer texto del segmento: el primer parcial o, si el motor no da parciales, el final.
            ft = (parts[0]["emitted_at"] if parts else f["emitted_at"]) - ts
            row["first_text_latency_s"] = round(ft, 3)
            first_text.append(ft)
        if f.get("forced") and f.get("t_end") is not None:
            forced_lag.append(f["emitted_at"] - f["t_end"])
        if te is not None and not row["forced"]:
            fl = f["emitted_at"] - te
            row["final_latency_s"] = round(fl, 3)
            final_lat.append(fl)
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
            n_partials.append(len(parts))
            st = metrics.partial_stability([p["text"] for p in parts], f["text"])
            retracted_all.extend(st["retracted"])
            unstable_all.extend(st["unstable_tail"])
            transitions += len(st["retracted"])
            mid_word_count += sum(st["mid_word"])
            partial_count += len(st["mid_word"])
            retracted_transitions += sum(1 for r in st["retracted"] if r > 0)
        rows.append(row)

    # WER de corpus sobre la concatenación (robusto a la segmentación).
    ref_texts = [u["text"] for u in plan.utterances]
    hyp_texts = [f["text"] for f in finals]
    wer = metrics.corpus_wer(ref_texts, hyp_texts)

    per_utt = None
    if plan.name == "gapped":
        hyp_per_utt = [[] for _ in plan.utterances]
        for f in finals:
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
                hyp_per_utt[best].append(f["text"])
        joined = [" ".join(h) for h in hyp_per_utt]
        w = metrics.per_utterance_wer(ref_texts, joined)
        per_utt = {
            "wer_mean": float(np.mean(w)),
            "wer_p95": float(np.percentile(w, 95)),
            "perfect": int(sum(1 for v in w if v == 0)),
            "n": len(w),
            "empty_utterances": int(sum(1 for h in hyp_per_utt if not h)),
            "finals_per_utterance": metrics.pct([len(h) for h in hyp_per_utt], qs=(50, 95)),
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
        "segment_duration_s": metrics.pct(seg_durations, qs=(50, 95)),
        "first_partial_latency_s": metrics.pct(first_partial),
        "first_text_latency_s": metrics.pct(first_text),
        "forced_cut_lag_s": metrics.pct(forced_lag),
        "final_latency_s": metrics.pct(final_lat),
        "text_complete_latency_s": metrics.pct(complete_lat),
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
