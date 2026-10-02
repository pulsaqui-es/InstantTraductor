"""Tablas (Markdown) del filtro de idioma a partir de ``results/lid_*.json``.

Uso: ``uv run python report_lid.py [fichero]`` (por defecto, ``results/lid_t1.json``).

Reglas evaluadas por idioma elegido T (ja, zh, ko). «Aceptar» = dejar pasar el segmento al ASR y al traductor:
- ``completo``: el idioma de mayor puntuación entre los 99 de Whisper es T.
- ``{T,es}``, ``{T,es,en}``, ``{ja,zh,ko,es,en}``: el de mayor puntuación dentro del subconjunto es T.
- ``p(T) >= θ`` sobre ``{T,es,en}``: probabilidad (softmax del subconjunto) de T mayor o igual que θ.
- ``sv-etiqueta``: SenseVoice con idioma automático emite la etiqueta ``<|T|>``.
- ``sv-escritura``: SenseVoice con el idioma T fijado; el texto tiene >= 90 % de letras de la escritura de T.
Positivos: recortes de T. Negativos: es, en y los otros dos idiomas asiáticos.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict

import numpy as np

from idiomas.paths import RESULTS_DIR

ASIAN = ("ja", "zh", "ko")


def softmax_subset(logits: dict[str, float], subset: tuple[str, ...]) -> dict[str, float]:
    v = np.array([logits[c] for c in subset])
    e = np.exp(v - v.max())
    return dict(zip(subset, (e / e.sum()).tolist(), strict=True))


def accepted(rule: str, rec: dict, target: str) -> bool:
    if rule == "completo":
        return rec["_top1"] == target
    if rule.startswith("{"):
        subset = tuple(rule.strip("{}").split(","))
        subset = tuple(target if s == "T" else s for s in subset)
        p = softmax_subset(rec["_logits"], subset)
        return max(p, key=p.get) == target
    if rule.startswith("p>="):
        p = softmax_subset(rec["_logits"], (target, "es", "en"))
        return p[target] >= float(rule[3:])
    if rule == "sv-etiqueta":
        return rec["sv_auto"]["lang"] == f"<|{target}|>"
    if rule == "sv-escritura":
        return rec["sv_forced"][target]["script"] >= 0.9
    raise ValueError(rule)


def rates(rule: str, recs: list[dict], target: str) -> dict[str, float]:
    out = {}
    groups = {"T": [r for r in recs if r["lang"] == target], "es": [r for r in recs if r["lang"] == "es"],
              "en": [r for r in recs if r["lang"] == "en"],
              "otros": [r for r in recs if r["lang"] in ASIAN and r["lang"] != target]}
    for g, rs in groups.items():
        out[g] = sum(accepted(rule, r, target) for r in rs) / max(1, len(rs))
    return out


def main() -> None:
    path = RESULTS_DIR / (sys.argv[1] if len(sys.argv) > 1 else "lid_t1.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["items"]
    print(f"Fichero: {path.name}; hilos: {data['threads']}; recortes: {len(items)}\n")

    # Acuerdo con sherpa-onnx y tiempos
    print(f"Ventana de Whisper: {data.get('window_s', 30.0)} s\n")
    has_sherpa = "tiny_sherpa_top1" in items[0]
    has_sv = "sv_auto" in items[0]
    for size in ("tiny", "base"):
        wall = [r[f"{size}_wall_ms"] for r in items]
        cpu = [r[f"{size}_cpu_ms"] for r in items]
        line = (f"- Whisper {size}: decisión propia p50/p95 {np.percentile(wall, 50):.0f}/{np.percentile(wall, 95):.0f} ms "
                f"(CPU {np.percentile(cpu, 50):.0f}/{np.percentile(cpu, 95):.0f} ms)")
        if has_sherpa:
            agree = sum(r[f"{size}_top1"] == r[f"{size}_sherpa_top1"] for r in items) / len(items)
            sh = [r[f"{size}_sherpa_wall_ms"] for r in items]
            line += f"; acuerdo con la API de sherpa-onnx {agree:.1%}; API de sherpa p50/p95 {np.percentile(sh, 50):.0f}/{np.percentile(sh, 95):.0f} ms"
        print(line)
    if has_sv:
        sva = [r["sv_auto"]["wall_ms"] for r in items]
        svc = [r["sv_auto"]["cpu_ms"] for r in items]
        print(f"- SenseVoice (idioma automático, ya hace el ASR): p50/p95 {np.percentile(sva, 50):.0f}/{np.percentile(sva, 95):.0f} ms (CPU {np.percentile(svc, 50):.0f}/{np.percentile(svc, 95):.0f} ms)")
    print()

    rules = ["completo", "{T,es}", "{T,es,en}", "{ja,zh,ko,es,en}", "p>=0.5", "p>=0.8", "p>=0.95"]
    for cond in ("clean", "music"):
        print(f"\n#### {'Sin música' if cond == 'clean' else 'Con música a -10 dB'}\n")
        for size in ("tiny", "base"):
            recs = []
            for r in items:
                if r["cond"] != cond:
                    continue
                x = dict(r)
                x["_top1"] = r[f"{size}_top1"]
                x["_logits"] = r[f"{size}_logits"]
                recs.append(x)
            print(f"**Whisper {size}**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %\n")
            print("| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |")
            print("|---|---|---|---|")
            for rule in rules:
                cells = []
                for t in ASIAN:
                    rr = rates(rule, recs, t)
                    cells.append(f"{rr['T']:.0%} / {rr['es']:.0%} / {rr['en']:.0%} / {rr['otros']:.0%}")
                print(f"| {rule} | " + " | ".join(cells) + " |")
            print()
        recs = [r for r in items if r["cond"] == cond]
        if not has_sv:
            continue
        print("**Alternativas baratas (SenseVoice)**\n")
        print("| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |")
        print("|---|---|---|---|")
        for rule in ("sv-etiqueta", "sv-escritura"):
            cells = []
            for t in ASIAN:
                rr = rates(rule, recs, t)
                cells.append(f"{rr['T']:.0%} / {rr['es']:.0%} / {rr['en']:.0%} / {rr['otros']:.0%}")
            print(f"| {rule} | " + " | ".join(cells) + " |")
        print()

    # Por duración, con la regla {T,es,en}
    print("\n#### Aceptación del idioma correcto por duración del recorte (regla {T,es,en}, sin música)\n")
    print("| Whisper | 1-2 s | 2-4 s | 4-6 s |")
    print("|---|---|---|---|")
    for size in ("tiny", "base"):
        row = []
        for lo, hi in ((1, 2), (2, 4), (4, 6.01)):
            ok = tot = 0
            for r in items:
                if r["cond"] != "clean" or r["lang"] not in ASIAN or not (lo <= r["dur"] < hi):
                    continue
                x = dict(r)
                x["_logits"] = r[f"{size}_logits"]
                ok += accepted("{T,es,en}", x, r["lang"])
                tot += 1
            row.append(f"{ok}/{tot} ({ok / max(1, tot):.0%})")
        print(f"| {size} | " + " | ".join(row) + " |")

    # Español rechazado: qué idioma detecta Whisper
    print("\n#### Qué detecta Whisper (idioma de mayor puntuación entre los 99) en los recortes sin música\n")
    for size in ("tiny", "base"):
        for lang in (*ASIAN, "es", "en"):
            c: dict[str, int] = defaultdict(int)
            for r in items:
                if r["cond"] == "clean" and r["lang"] == lang:
                    c[r[f"{size}_top1"]] += 1
            top = ", ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1])[:5])
            print(f"- {size}, audio {lang}: {top}")


if __name__ == "__main__":
    main()
