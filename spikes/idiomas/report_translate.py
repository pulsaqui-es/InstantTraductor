"""Tablas (Markdown) de la traducción a partir de ``results/translate_*.json``."""

from __future__ import annotations

import json

import numpy as np

from idiomas.paths import RESULTS_DIR


def main() -> None:
    results = []
    for name in ("translate_main.json", "translate_asr.json"):
        p = RESULTS_DIR / name
        if p.exists():
            results += json.loads(p.read_text(encoding="utf-8"))
    print("| Variante | Idioma | Entrada | max_tokens | chrF vs es_419 | p50 / p95 / máx. (ms) | Rechazadas por los filtros | Truncadas |")
    print("|---|---|---|---|---|---|---|---|")
    for r in results:
        print(
            f"| {r['variant']} | {r['lang']} | {r['input'].replace('asr:asr_', 'ASR ').replace('_t2.json', '')} | {r['max_tokens_mode']} | {r['chrf_vs_es419']:.1f} | "
            f"{r['latency_p50_s'] * 1000:.0f} / {r['latency_p95_s'] * 1000:.0f} / {r['latency_max_s'] * 1000:.0f} | "
            f"{r['rejected']} / 50 {r['reject_reasons'] or ''} | {r['truncated']} |"
        )
    print("\nProporción de longitud (caracteres de la traducción / caracteres del original) y tokens, variante prod con la referencia:\n")
    print("| Idioma | Longitud p50 / p95 / máx. | Rechazadas con el tope de 3 | Con tope 6 | Tokens de salida p50 / p95 / máx. | Tope de tokens de producción (min / mediana) |")
    print("|---|---|---|---|---|---|")
    for lang in ("ja", "zh", "ko"):
        r = next(x for x in results if x["variant"] == "prod" and x["lang"] == lang and x["input"] == "ref" and x["max_tokens_mode"] == "free")
        ratios = [len(x["text"]) / len(x["source"].strip()) for x in r["rows"] if x["text"]]
        toks = [x["completion_tokens"] for x in r["rows"] if x.get("completion_tokens")]
        rp = next(x for x in results if x["variant"] == "prod" and x["lang"] == lang and x["input"] == "ref" and x["max_tokens_mode"] == "prod")
        caps = [x["max_tokens"] for x in rp["rows"]]
        print(
            f"| {lang} | {np.percentile(ratios, 50):.1f} / {np.percentile(ratios, 95):.1f} / {max(ratios):.1f} | "
            f"{sum(x > 3 for x in ratios)} | {sum(x > 6 for x in ratios)} | {np.percentile(toks, 50):.0f} / {np.percentile(toks, 95):.0f} / {max(toks)} | "
            f"{min(caps)} / {int(np.median(caps))} |"
        )


if __name__ == "__main__":
    main()
