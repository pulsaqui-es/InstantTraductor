"""Imprime las salidas de B0 de una ejecución con la etiqueta del detector (para etiquetar a mano)."""
import json
import sys

from common import OUT_DIR

d = json.loads((OUT_DIR / "mt" / sys.argv[1]).read_text("utf-8"))
lo, hi = int(sys.argv[2]), int(sys.argv[3])
for r in d["b0"]["records"][lo:hi]:
    print(f"{r['idx']:3d} {r['label']} {r['primary']:<5}| {r['source']}  =>  {r['text']}")
