"""Tablas resumen (Markdown) de las ejecuciones guardadas en ``results/*.json``.

Uso (desde ``spikes/asr``)::

    uv run python report.py                                   # una fila por ejecución
    uv run python report.py --glob "sweep_*"                  # solo las que empiezan por sweep_
    uv run python report.py --compare a160_vad_gapped_paced a560_vad_gapped_paced b_gapped_paced
    uv run python report.py --out results/resumen.md

Con ``--compare`` las ejecuciones van en columnas y las métricas en filas. Las latencias (p50/p95)
solo existen en modo ``paced``.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path

from asrspike import paths


def load(label: str) -> dict:
    return json.loads((paths.RESULTS_DIR / f"{label}.json").read_text(encoding="utf-8"))


def fmt_pair(d: dict | None, digits: int = 2) -> str:
    if not d or d.get("n", 0) == 0 or d.get("p50") != d.get("p50"):
        return "-"
    return f"{d['p50']:.{digits}f} / {d['p95']:.{digits}f}"


def describe(res: dict) -> str:
    cfg = res.get("config", {})
    if res.get("engine") == "A":
        return f"A: Nemotron {cfg.get('chunk_ms')} ms, {cfg.get('policy')}, {cfg.get('threads')} h, bp {cfg.get('blank_penalty')}"
    cut = cfg.get("max_segment_s")
    return f"B: Whisper turbo FP16, haz {cfg.get('beam_size')}, corte {'sin' if not cut else str(cut) + ' s'}"


def column(res: dict) -> dict:
    cfg, run, load_, r = res.get("config", {}), res.get("run", {}), res.get("load", {}), res.get("result", {})
    w, pu = r.get("wer", {}), r.get("punctuation", {})
    paced = cfg.get("mode") == "paced"
    vram = res.get("vram", {})
    cells = {
        "Configuración": describe(res),
        "Flujo y modo": f"{res['stream']['name']} ({cfg.get('mode')}, {res['stream']['duration_s']:.0f} s)",
        "WER normalizado (%)": f"{100 * w.get('wer', float('nan')):.2f}",
        "Errores S/D/I de N palabras": f"{w.get('sub')}/{w.get('del')}/{w.get('ins')} de {w.get('ref_words')}",
        "1.er texto del segmento, p50 / p95 (s)": fmt_pair(r.get("first_text_latency_s")) if paced else "-",
        "1.er parcial, p50 / p95 (s)": fmt_pair(r.get("first_partial_latency_s")) if paced else "-",
        "Final desde el fin real del habla, p50 / p95 (s)": fmt_pair(r.get("final_latency_s")) if paced else "-",
        "Texto completo (parcial = final), p50 / p95 (s)": fmt_pair(r.get("text_complete_latency_s")) if paced else "-",
        "RTF (cómputo / audio)": f"{run.get('rtf', float('nan')):.3f}",
        "CPU propia (núcleos de media / % del equipo)": f"{load_.get('own_cores_avg')} / {load_.get('own_cpu_pct_of_machine')}",
        "CPU ajena (núcleos de media) y CPU global (media / máx. %)": (
            f"{load_.get('others_total_cores_avg')} ; {load_.get('system_cpu_pct_mean')} / {load_.get('system_cpu_pct_max')}"
        ),
        "RAM del proceso (MB)": run.get("ram_peak_mb", "-"),
        "VRAM del proceso, pico (MB)": vram.get("process_dedicated_peak_mb", "-"),
        "Segmentos (cortes forzados)": f"{r.get('n_segments')} ({r.get('n_forced_cuts')})",
        "Comas / marcas finales por 100 palabras": f"{pu.get('commas_per_100_words', float('nan')):.1f} / {pu.get('terminal_marks_per_100_words', float('nan')):.1f}",
        "Finales que acaban en . ? !": f"{pu.get('finals_ending_with_terminal_pct', float('nan')):.0f} %",
    }
    return cells


def compare(labels: list[str]) -> str:
    cols = [column(load(lab)) for lab in labels]
    rows = list(cols[0].keys())
    lines = ["| Métrica | " + " | ".join(labels) + " |", "|---|" + "|".join("---" for _ in labels) + "|"]
    for k in rows:
        lines.append(f"| {k} | " + " | ".join(str(c[k]) for c in cols) + " |")
    return "\n".join(lines)


def one_row_each(pattern: str) -> str:
    rows = []
    for f in sorted(paths.RESULTS_DIR.glob("*.json")):
        if not fnmatch.fnmatch(f.stem, pattern):
            continue
        res = json.loads(f.read_text(encoding="utf-8"))
        if "result" not in res:  # línea base o ejecución con error
            continue
        c = column(res)
        c = {"etiqueta": res["label"], **c}
        rows.append(c)
    if not rows:
        return "Sin resultados."
    keys = list(rows[0].keys())
    lines = ["| " + " | ".join(keys) + " |", "|" + "|".join("---" for _ in keys) + "|"]
    lines += ["| " + " | ".join(str(r[k]) for k in keys) + " |" for r in rows]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--glob", default="*")
    ap.add_argument("--compare", nargs="+", default=None, help="etiquetas a comparar en columnas")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    text = compare(args.compare) if args.compare else one_row_each(args.glob)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
