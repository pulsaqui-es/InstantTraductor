"""Tabla de resultados de B1/B2 a partir de `out/mt/*.json` (todas las ejecuciones de `mt_lab.py` y `b2_retry.py`).

Columnas:
- P (167 frases con «you» plural informal): % vosotros (IC 95 % de Wilson), % ustedes, % tú, % sin marca.
- Daño en controles: S = «you» singular informal que sale como «vosotros»; T = 3.ª plural legítima que sale como
  «vosotros» o «ustedes» (no debería); F = formales (informativo).
- S2: calidad en el corpus de la spec 001 con `quality.py` (no traducción, trampas falladas, léxico de España OK,
  rechazadas por los filtros), para comprobar que el prompt nuevo no empeora lo ya medido.
- Latencia por petición (p50/p95, ms) y tokens de prompt medios.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import detector
from common import OUT_DIR, RESULTS_DIR
from mt_lab import summarize_b0, wilson

MT = OUT_DIR / "mt"


def pct(k: int, n: int) -> str:
    return f"{100 * k / max(1, n):.0f}"


def row(path: Path) -> str | None:
    d = json.loads(path.read_text("utf-8"))
    name = path.stem
    if "b0" in d:
        recs = d["b0"]["records"]
        s2 = d.get("s2", {})
    elif "summary" in d:
        recs, s2 = d["records"], {}
    else:
        return None
    for r in recs:  # se recalcula con el detector actual (usa el inglés para los 3.ª plural)
        r["primary"] = detector.primary(r["text"], r["source"])
    s = summarize_b0(recs)
    p, sg, f, t = s["P"], s["S"], s["F"], s["T"]
    lo, hi = wilson(p["vos"], p["n"])
    q = s2.get("summary", {})
    return (
        f"| {name} | {pct(p['vos'], p['n'])} ({lo:.0f}-{hi:.0f}) | {pct(p['ust'], p['n'])} | {pct(p['tu'], p['n'])} | "
        f"{pct(p['neu'], p['n'])} | {pct(sg['vos'], sg['n'])} | {t['vos'] + t['ust']}/{t['n']} | {f['vos']}/{f['n']} | "
        f"{q.get('non_translation', '-')} | {s2.get('adversarial_trap_fail', '-')} | "
        f"{q.get('lexical_ok', '-')}/{q.get('lexical_total', '-')} | {s2.get('rejected', '-')} | "
        f"{s['ms_p50']:.0f} / {s['ms_p95']:.0f} | {s['prompt_n_mean']:.0f} |"
    )


def main() -> None:
    names = sys.argv[1:]
    paths = sorted(MT.glob("*.json"))
    if names:
        paths = [p for p in paths if any(n in p.stem for n in names)]
    lines = [
        "| Ejecución | P % vosotros (IC95) | P % ustedes | P % tú | P % sin marca | S % vosotros (daño) | T vos/ust (daño) | F vosotros | S2 no-traducción | S2 trampas | S2 léxico OK | S2 rechazadas | ms p50 / p95 | tokens prompt |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for p in paths:
        r = row(p)
        if r:
            lines.append(r)
    text = "\n".join(lines)
    (RESULTS_DIR / "b1_tabla.md").write_text(text, "utf-8")
    print(text)


if __name__ == "__main__":
    main()
