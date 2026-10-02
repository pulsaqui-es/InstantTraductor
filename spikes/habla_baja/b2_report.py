"""Tabla de B2 (posedición por reglas y reintento) a partir de `out/mt/b2_*.json`."""

from __future__ import annotations

import json

import detector
from common import OUT_DIR, RESULTS_DIR
from mt_lab import summarize_b0, wilson


def main() -> None:
    lines = [
        "| Ejecución | P % vosotros (IC95) | P % ustedes | P % tú | S % vosotros (daño) | T vos/ust | F vosotros | marcadas f (de 228) | reintentadas | arregladas | reintento ms p50 / p95 | coste medio por frase (ms) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for path in sorted((OUT_DIR / "mt").glob("b2_*.json")):
        d = json.loads(path.read_text("utf-8"))
        recs = d["records"]
        for r in recs:
            r["primary"] = detector.primary(r["text"], r["source"])
        s = summarize_b0(recs)
        x = d["summary"]
        p = s["P"]
        lo, hi = wilson(p["vos"], p["n"])
        lines.append(
            f"| {path.stem} | {100 * p['vos'] / p['n']:.0f} ({lo:.0f}-{hi:.0f}) | {100 * p['ust'] / p['n']:.0f} | "
            f"{100 * p['tu'] / p['n']:.0f} | {100 * s['S']['vos'] / s['S']['n']:.0f} | {s['T']['vos'] + s['T']['ust']}/19 | "
            f"{s['F']['vos']}/18 | {x['flagged']} {x['flag_kinds']} | {x['retried']} | {x['fixed_by_retry']} | "
            f"{x.get('retry_ms_p50', 0):.0f} / {x.get('retry_ms_p95', 0):.0f} | {x.get('retry_cost_per_sentence_ms', 0):.0f} |"
        )
    text = "\n".join(lines)
    (RESULTS_DIR / "b2_tabla.md").write_text(text, "utf-8")
    print(text)


if __name__ == "__main__":
    main()
