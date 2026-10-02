"""B2: posedición por reglas sobre las salidas ya generadas (no necesita GPU).

Para cada variante de `out/mt/*.json` aplica `postedit(en, es)` a las 228 salidas de B0 y mide, con el detector:
- P: % vosotros antes y después, % ustedes antes y después;
- daño: líneas S, F, T que cambian (en S y T no debería cambiar ninguna) y conversiones de P que dejan mixta la frase;
- coste: microsegundos por frase.
Imprime las conversiones de una variante para revisión a ciegas (`--show`).

Uso: `uv run python b2_postedit_eval.py base_s42.json [--show]`
"""

from __future__ import annotations

import json
import sys
import time

import detector
import postedit
from common import OUT_DIR, RESULTS_DIR


def evaluate(records: list[dict]) -> dict:
    out: dict = {}
    t0 = time.perf_counter()
    edited = [postedit.postedit(r["source"], r["text"]) for r in records]
    dt = (time.perf_counter() - t0) / len(records) * 1e6
    out["us_per_sentence"] = dt
    for label in ("P", "S", "F", "T"):
        idx = [i for i, r in enumerate(records) if r["label"] == label]
        before = [detector.primary(records[i]["text"], records[i]["source"]) for i in idx]
        after = [detector.primary(edited[i].text, records[i]["source"]) for i in idx]
        out[label] = {
            "n": len(idx),
            "vos_before": before.count("vos"),
            "vos_after": after.count("vos"),
            "ust_before": before.count("ust"),
            "ust_after": after.count("ust"),
            "changed": sum(1 for i in idx if edited[i].changed),
            "mixed_after": sum(1 for i in idx if detector.mixed(edited[i].text, records[i]["source"])),
        }
    return out


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "base_s42.json"
    records = json.loads((OUT_DIR / "mt" / name).read_text("utf-8"))["b0"]["records"]
    res = evaluate(records)
    print(json.dumps(res, indent=1))
    if "--show" in sys.argv:
        lines = []
        for r in records:
            e = postedit.postedit(r["source"], r["text"])
            if e.changed:
                lines.append(f"{r['idx']:3d} {r['label']} | {r['source']}\n      {r['text']}\n   -> {e.text}  {e.rules}")
        text = "\n".join(lines)
        (RESULTS_DIR / f"b2_conversiones_{name.removesuffix('.json')}.txt").write_text(text, "utf-8")
        print(text)


if __name__ == "__main__":
    main()
