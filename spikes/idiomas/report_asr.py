"""Tablas (Markdown) de la campaña de ASR a partir de ``results/asr_*.json``.

Uso: ``uv run python report_asr.py [--lang ja]``
"""

from __future__ import annotations

import argparse
import json

from idiomas.paths import RESULTS_DIR


def fmt(x, nd=2, pct=False):
    if x is None:
        return "-"
    return f"{x * 100:.{nd}f} %" if pct else f"{x:.{nd}f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang")
    args = ap.parse_args()
    runs = []
    for p in sorted(RESULTS_DIR.glob("asr_*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        r["tag"] = p.stem.split(f"_t{r['threads']}", 1)[1]  # "", "_carga", "_paced"...
        runs.append(r)
    for lang, tag in [(lg, t) for t in sorted({r["tag"] for r in runs}) for lg in ("ja", "zh", "ko")]:
        if args.lang and args.lang != lang:
            continue
        rs = sorted((r for r in runs if r["lang"] == lang and r["tag"] == tag), key=lambda r: r["conds"]["clean"]["cer"]["cer"])
        if tag:
            print(f"\n(variante `{tag}`)")
        if not rs:
            continue
        print(f"\n### {lang}\n")
        print(
            "| Candidato | CER limpio | CER con música | Final p50 / p95 (s) | Con música p50 / p95 (s) | 1.er parcial p50 (s) | RTF | "
            "Núcleos | RAM cargado / pico (MB) | Puntuación (signos/100 car.; frases con cierre) | Segmentos (esp.) |"
        )
        print("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in rs:
            c, m = r["conds"]["clean"], r["conds"].get("music")
            print(
                f"| {r['label']} ({r['threads']} h) | {fmt(c['cer']['cer'], 2, True)} | {fmt(m['cer']['cer'], 2, True) if m else '-'} | "
                f"{fmt(c['final_latency_s']['p50'])} / {fmt(c['final_latency_s']['p95'])} | "
                f"{fmt(m['final_latency_s']['p50']) + ' / ' + fmt(m['final_latency_s']['p95']) if m else '-'} | "
                f"{fmt(c['first_partial_s'].get('p50')) if c['first_partial_s']['n'] else '-'} | {fmt(c['rtf'], 3)} | {fmt(c['cpu_cores'])} | "
                f"{r['rss_loaded_mb']:.0f} / {r['rss_peak_mb']:.0f} | {fmt(c['punct_per_100_chars'], 1)}; {c['clips_ending_with_mark']}/{r['n_phrases']} | "
                f"{c['segments']} ({c['spurious_finals']}{'/' + str(m['spurious_finals']) if m else ''}) |"
            )
        print()
        print("Detalle: CER con partición de errores (sustituciones/borrados/inserciones), mediana y p90 por frase, frases sin texto.\n")
        print("| Candidato | S / D / I (limpio) | CER mediano por frase | CER p90 por frase | Frases sin texto (limpio / música) | Decodificación por segmento p50 / p95 (ms) |")
        print("|---|---|---|---|---|---|")
        for r in rs:
            c, m = r["conds"]["clean"], r["conds"].get("music")
            print(
                f"| {r['label']} | {c['cer']['sub']} / {c['cer']['del']} / {c['cer']['ins']} | {fmt(c['cer_median_item'], 1, True)} | "
                f"{fmt(c['cer_p90_item'], 1, True)} | {c['empty_clips']} / {m['empty_clips'] if m else '-'} | "
                f"{fmt(c['decode_ms']['p50'], 0)} / {fmt(c['decode_ms']['p95'], 0)} |"
            )


if __name__ == "__main__":
    main()
