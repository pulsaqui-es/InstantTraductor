"""Mide el detector contra las etiquetas a mano de las 228 salidas del 7B con el prompt de producción (base, semilla 42).

Las etiquetas (`GOLD`, una letra por línea de B0) las puse yo leyendo cada traducción, no la persona usuaria
(README, límites). Letras: v = vosotros, u = ustedes (o 3.ª plural dirigida al oyente), t = tú (singular),
s = usted (formal singular), m = mezclada (formas de varias personas), x = voseo, n = sin marca de persona.
"""

from __future__ import annotations

import json
from collections import Counter

import detector
from common import OUT_DIR, RESULTS_DIR

GOLD = (
    "vuvvvumvvv" "vvvttuttun" "ttvtvvvvvt" "vtvvvtuvtv" "vvvvtvvnuv" "mtvmvttttt" "uvvtttnvtt" "ttvtttvvuu"
    "vtttuvvvtv" "uvuuvvuvtt" "mvunvvvutu" "vtvvuuvuuv"
    "nutvvvvtmv" "ttttttvtuv" "tvvvnvvvvt" "vtvnuvuvvv" "vvvtvttutt" "tttttttttx" "tvtttttttv" "ttssssssss"
    "ssssuuuuss" "nnnnnnnnnnnnnnnnnn"
)
MAP = {"vos": "v", "ust": "u", "tu": "t", "usted": "s", "neu": "n"}


def main() -> None:
    assert len(GOLD) == 228, len(GOLD)
    d = json.loads((OUT_DIR / "mt" / "base_s42.json").read_text("utf-8"))
    recs = d["b0"]["records"]
    conf: Counter = Counter()
    wrong = []
    for r, g in zip(recs, GOLD, strict=True):
        p = MAP[detector.primary(r["text"], r["source"])]
        if g == "m" and detector.mixed(r["text"], r["source"]):
            p = "m"
        conf[(g, p)] += 1
        if p != g:
            wrong.append((r["idx"], g, p, r["source"], r["text"]))
    out = [
        "# Detector de «vosotros»: precisión y cobertura frente a mi etiquetado de 228 salidas "
        "(7B, prompt actual, semilla 42)",
        "",
    ]
    for cls, name in (("v", "vosotros"), ("u", "ustedes"), ("t", "tú"), ("s", "usted")):
        tp = conf[(cls, cls)]
        fp = sum(c for (g, p), c in conf.items() if p == cls and g != cls)
        fn = sum(c for (g, p), c in conf.items() if g == cls and p != cls)
        out.append(
            f"- **{name}**: n gold = {tp + fn}, precisión {100 * tp / max(1, tp + fp):.1f} % ({tp}/{tp + fp}), "
            f"cobertura {100 * tp / max(1, tp + fn):.1f} % ({tp}/{tp + fn})"
        )
    out += ["", "Errores (idx, gold, detector):", ""]
    for idx, g, p, s, t in wrong:
        out.append(f"- {idx} gold={g} det={p} | {s} => {t}")
    text = "\n".join(out)
    (RESULTS_DIR / "b0_detector.md").write_text(text, "utf-8")
    print(text)


if __name__ == "__main__":
    main()
