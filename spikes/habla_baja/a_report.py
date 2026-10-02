"""Tabla de A1/A3 nivel 2 (cadena completa con ASR) a partir de `resultados/a_full*.json`."""

from __future__ import annotations

import json

from common import RESULTS_DIR


def main() -> None:
    rows = []
    for path in sorted(RESULTS_DIR.glob("a_full*.json")):
        for name, v in json.loads(path.read_text("utf-8")).items():
            rows.append((name, v))
    conds = sorted({c for _, v in rows for c in v["by_cond"]})
    head = (
        "| Configuración | % frases traducidas (duras) | recall duras % | % traducidas (fáciles) | "
        "retardo del fin p50 / p95 (s) | unidades/clip | % unidades ≤ 3 pal. | FA: frases en 10 min | FA: tramos | FA: s de «habla» |"
    )
    lines = [head, "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, v in rows:
        lines.append(
            f"| {name} | {v['hard_translated']:.1f} | {v['hard_recall']:.1f} | {v['easy_translated']:.1f} | "
            f"{v['delay_p50']:.2f} / {v['delay_p95']:.2f} | {v['units_per_clip']:.2f} | {v['pct_units_le3']:.1f} | "
            f"{v['fa_units']} | {v['fa_segments']} | {v['fa_speech_s']:.1f} |"
        )
    lines += ["", "% de frases traducidas por condición:", "", "| Configuración | " + " | ".join(conds) + " |", "|---|" + "---:|" * len(conds)]
    for name, v in rows:
        lines.append(f"| {name} | " + " | ".join(f"{v['by_cond'].get(c, float('nan')):.0f}" for c in conds) + " |")
    text = "\n".join(lines)
    (RESULTS_DIR / "a_full_tabla.md").write_text(text, "utf-8")
    print(text)


if __name__ == "__main__":
    main()
