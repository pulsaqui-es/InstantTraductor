"""Tablas resumen (Markdown) de las ejecuciones guardadas en ``results/*.json``.

Uso (desde ``spikes/asr``)::

    uv run python report.py                                   # una fila por ejecución
    uv run python report.py --glob "sweep_*"                  # solo las que empiezan por sweep_
    uv run python report.py --compare a160_vad_gapped_paced a560_vad_gapped_paced b_gapped_paced
    uv run python report.py --section bp          # bp | threads | b | baselines | a-misc | load
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
        "  …solo finales que cierran un enunciado, p50 / p95 (s)": (
            fmt_pair((r.get("utterance") or {}).get("final_latency_s")) if paced else "-"
        ),
        "  …desglose p50: decisión del cierre / después (s)": (
            "{} / {}".format(
                *(
                    f"{(r.get('latency_breakdown') or {}).get(k, {}).get('p50', float('nan')):.2f}"
                    for k in ("vad_delay_s", "post_decision_s")
                )
            )
            if paced
            else "-"
        ),
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


def md(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def try_load(label: str) -> dict | None:
    try:
        return load(label)
    except FileNotFoundError:
        return None


def sdi(w: dict) -> str:
    return f"{w['sub']}/{w['del']}/{w['ins']}"


def sec_bp() -> str:
    """Barrido de blank_penalty (modo rápido, flujo con huecos completo)."""
    rows = []
    for chunk in (160, 560):
        for bp in (0, 1, 2, 3):
            res = try_load(f"sweep_a{chunk}_bp{bp}_gapped_fast")
            if not res:
                continue
            r = res["result"]
            w, pu = r["wer"], r["punctuation"]
            rows.append(
                [chunk, bp, f"{100 * w['wer']:.2f}", sdi(w), f"{pu['commas_per_100_words']:.1f}",
                 f"{pu['terminal_marks_per_100_words']:.1f}", f"{pu['finals_ending_with_terminal_pct']:.0f} %", r["n_segments"]]
            )
    return md(["Trozo (ms)", "blank_penalty", "WER %", "S/D/I", "Comas / 100 pal.", "Marcas finales / 100 pal.", "Finales con . ? !", "Segmentos"], rows)


def sec_threads() -> str:
    """Hilos de sherpa-onnx (habla continua, tiempo real: el peor caso de CPU)."""
    rows = []
    for chunk in (160, 560):
        for th, suffix in ((1, "_t1"), (2, ""), (4, "_t4")):
            res = try_load(f"a{chunk}_vad_continuous_paced{suffix}")
            if not res:
                continue
            r, run, ld = res["result"], res["run"], res["load"]
            rows.append(
                [chunk, th, f"{run['rtf']:.3f}", f"{ld['own_cores_avg']}", f"{ld['own_cpu_pct_of_machine']}",
                 f"{run['push_ms']['p95']:.0f} / {run['push_ms']['max']:.0f}", f"{run['lateness_ms']['p95']:.0f} / {run['lateness_ms']['max']:.0f}",
                 fmt_pair(r["final_latency_s"]), fmt_pair(r["first_partial_latency_s"]), f"{100 * r['wer']['wer']:.2f}",
                 f"{ld['others_total_cores_avg']}"]
            )
    return md(["Trozo (ms)", "Hilos", "RTF", "CPU propia (núcleos)", "% del equipo", "push() p95 / máx. (ms)", "Retraso del alimentador p95 / máx. (ms)",
               "Final p50 / p95 (s)", "1.er parcial p50 / p95 (s)", "WER %", "CPU ajena (núcleos)"], rows)


def sec_b() -> str:
    """Motor B: corte forzado y haz (mismo VAD; flujo con huecos)."""
    rows = []
    for label, mode in (
        ("b_gapped_paced", "tiempo real"),
        ("b_gapped_fast_beam1_cut3", "rápido"),
        ("b_gapped_fast_beam1_cut8", "rápido"),
        ("b_gapped_fast_beam1_cut15", "rápido"),
        ("b_gapped_fast_beam1_nocut", "rápido"),
        ("b_gapped_fast_beam5_cut5", "rápido"),
        ("b_gapped_fast_beam5_nocut", "rápido"),
    ):
        res = try_load(label)
        if not res:
            continue
        r, run, cfg = res["result"], res["run"], res["config"]
        cut = cfg["max_segment_s"]
        pu = r["punctuation"]
        rows.append(
            [label, cfg["beam_size"], "sin corte" if not cut else f"{cut:g} s", mode, f"{100 * r['wer']['wer']:.2f}", sdi(r["wer"]),
             f"{r['n_segments']} ({r['n_forced_cuts']})", f"{run['infer_ms']['p50']:.0f} / {run['infer_ms']['p95']:.0f}",
             f"{run['segment_audio_s']['p50']:.1f} / {run['segment_audio_s']['p95']:.1f}", f"{pu['finals_ending_with_terminal_pct']:.0f} %"]
        )
    return md(["Etiqueta", "Haz", "Corte forzado", "Modo", "WER %", "S/D/I", "Segmentos (cortes)", "Inferencia por segmento p50 / p95 (ms)",
               "Audio por segmento p50 / p95 (s)", "Finales con . ? !"], rows)


def sec_baselines() -> str:
    """WER sin segmentación ni VAD (cada enunciado entero)."""
    rows = []
    for label, name in (
        ("baseline_a160_bp1", "A: Nemotron 160 ms, bp 1"),
        ("baseline_a560_bp1", "A: Nemotron 560 ms, bp 1"),
        ("baseline_b_beam1", "B: Whisper turbo FP16, haz 1"),
        ("baseline_b_beam5", "B: Whisper turbo FP16, haz 5"),
    ):
        res = try_load(label)
        if not res:
            continue
        w, pu = res["wer"], res["punctuation"]
        rows.append([name, f"{100 * w['wer']:.2f}", sdi(w), f"{pu['commas_per_100_words']:.1f}", f"{pu['terminal_marks_per_100_words']:.1f}",
                     f"{pu['texts_ending_with_terminal_pct']:.0f} %", f"{res['rtf']:.3f}"])
    return md(["Motor", "WER %", "S/D/I", "Comas / 100 pal.", "Marcas finales / 100 pal.", "Textos con . ? !", "RTF (sin pacing)"], rows)


def sec_a_misc() -> str:
    """Silencio de cierre, trozo de entrada y relleno de vaciado del motor A."""
    out = []
    rows = []
    for label, name in (
        ("a560_vad_gapped_paced", "500 ms (por defecto)"),
        ("a560_vad_gapped_paced_minsil300", "300 ms"),
    ):
        res = try_load(label)
        if res:
            r = res["result"]
            rows.append([name, f"{100 * r['wer']['wer']:.2f}", r["n_segments"], fmt_pair(r["final_latency_s"]), fmt_pair((r.get("utterance") or {}).get("final_latency_s")),
                         fmt_pair(r["text_complete_latency_s"])])
    out.append("**Silencio que cierra el turno (A 560 ms, tiempo real, flujo con huecos)**\n\n" + md(
        ["Silencio", "WER %", "Segmentos", "Final p50 / p95 (s)", "Final por enunciado p50 / p95 (s)", "Texto completo p50 / p95 (s)"], rows))

    rows = []
    for dev in (20, 32, 100):
        res = try_load(f"a560_vad_gapped_paced_dev{dev}_lim25")
        if res:
            r, run = res["result"], res["run"]
            rows.append([dev, fmt_pair(r["first_partial_latency_s"]), fmt_pair(r["final_latency_s"]), f"{run['rtf']:.3f}",
                         f"{run['push_ms']['p95']:.0f}", f"{100 * r['wer']['wer']:.2f}"])
    out.append("**Tamaño del trozo de entrada (A 560 ms, tiempo real, 25 primeros enunciados)**\n\n" + md(
        ["Trozo de entrada (ms)", "1.er parcial p50 / p95 (s)", "Final p50 / p95 (s)", "RTF", "push() p95 (ms)", "WER %"], rows))

    rows = []
    for chunk in (160, 560):
        for pad in (0, 160, 560):
            res = try_load(f"a{chunk}_fast_tail{pad}_lim40")
            if res:
                r, run = res["result"], res["run"]
                rows.append([chunk, pad, f"{100 * r['wer']['wer']:.2f}", sdi(r["wer"]),
                             f"{run['flush_ms']['p50']:.0f} / {run['flush_ms']['p95']:.0f}", f"{r['final_equals_last_partial_pct']:.0f} %"])
    out.append("**Relleno de ceros al vaciar el reconocedor (modo rápido, 40 primeros enunciados)**\n\n" + md(
        ["Trozo (ms)", "Relleno (ms)", "WER %", "S/D/I", "Vaciado p50 / p95 (ms)", "Final = último parcial"], rows))

    rows = []
    for label, name in (("a560_fast_minsil300", "300"), ("sweep_a560_bp1_gapped_fast", "500"), ("a560_fast_minsil800", "800")):
        res = try_load(label)
        if res:
            r = res["result"]
            rows.append([name, f"{100 * r['wer']['wer']:.2f}", sdi(r["wer"]), r["n_segments"], f"{r['segment_duration_s']['p50']:.1f} / {r['segment_duration_s']['p95']:.1f}"])
    out.append("**Silencio de cierre y segmentación (A 560 ms, modo rápido, flujo con huecos completo)**\n\n" + md(
        ["Silencio (ms)", "WER %", "S/D/I", "Segmentos", "Duración del segmento p50 / p95 (s)"], rows))
    return "\n\n".join(out)


def sec_load() -> str:
    """Qué más corría en el equipo durante cada ejecución en tiempo real (otros obreros incluidos)."""
    rows = []
    for f in sorted(paths.RESULTS_DIR.glob("*.json")):
        res = json.loads(f.read_text(encoding="utf-8"))
        if "load" not in res or res.get("config", {}).get("mode") != "paced":
            continue
        ld = res["load"]
        top = ", ".join(f"{p['name'].removesuffix('.exe')} {p['cores_avg']}" for p in ld["others_top"][:4])
        rows.append([res["label"], res["when"][11:16], ld["own_cores_avg"], ld["others_total_cores_avg"],
                     f"{ld['system_cpu_pct_mean']} / {ld['system_cpu_pct_max']}", top])
    return md(["Ejecución", "Hora de fin (2026-10-01)", "CPU propia (núcleos)", "CPU ajena (núcleos)", "CPU global media / máx. (%)",
               "Procesos ajenos con más CPU (núcleos de media)"], rows)


SECTIONS = {
    "bp": sec_bp,
    "threads": sec_threads,
    "b": sec_b,
    "baselines": sec_baselines,
    "a-misc": sec_a_misc,
    "load": sec_load,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--glob", default="*")
    ap.add_argument("--compare", nargs="+", default=None, help="etiquetas a comparar en columnas")
    ap.add_argument("--section", choices=sorted(SECTIONS), default=None, help="tabla preparada para el README")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.section:
        text = SECTIONS[args.section]()
    elif args.compare:
        text = compare(args.compare)
    else:
        text = one_row_each(args.glob)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
