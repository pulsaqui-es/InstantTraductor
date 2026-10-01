"""Repite el análisis de ejecuciones ya medidas a partir de sus eventos crudos guardados.

Útil si se corrige una definición de métrica: no hace falta volver a medir en tiempo real.
Sustituye la clave ``result`` de ``results/<etiqueta>.json`` (el resto queda igual).

Uso (desde ``spikes/asr``)::

    uv run python reanalyze.py a160_vad_gapped_paced b_gapped_paced
    uv run python reanalyze.py --all
"""

from __future__ import annotations

import argparse
import json

from asrspike import events_io, paths
from asrspike.analysis import analyze
from asrspike.data import StreamPlan, cut_plan


def reanalyze(label: str) -> None:
    dest = paths.RESULTS_DIR / f"{label}.json"
    res = json.loads(dest.read_text(encoding="utf-8"))
    plan = StreamPlan.load(paths.corpus_dir(), res["stream"]["name"])
    if res["stream"].get("limit"):
        plan = cut_plan(plan, res["stream"]["limit"])
    events = events_io.load_events(label)
    res["result"] = analyze(plan, events, paced=res["config"]["mode"] == "paced")
    dest.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
    w = res["result"]["wer"]
    print(f"{label}: WER {100 * w['wer']:.2f} %, {res['result']['n_segments']} segmentos")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labels", nargs="*")
    ap.add_argument("--all", action="store_true", help="todas las ejecuciones con eventos guardados")
    args = ap.parse_args()
    labels = args.labels
    if args.all:
        labels = sorted(p.name.removesuffix(".events.json.gz") for p in (paths.RESULTS_DIR / "events").glob("*.events.json.gz"))
    for label in labels:
        reanalyze(label)


if __name__ == "__main__":
    main()
