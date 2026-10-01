"""Laboratorio de prompts del spike S2: ¿cómo se combinan mejor contexto, glosario y estilo?

La model card de Hy-MT2 da una plantilla por tipo de instrucción pero no dice cómo
combinarlas. Este script prueba varias disposiciones sobre las 65 líneas (mismo
corpus y semilla) y resume, por variante:

- fallos de estructura: el modelo traduce el propio prompt, añade etiquetas o texto que
  no es traducción (muletillas), o no termina;
- léxico de España, «vosotros» y glosario (comprobaciones automáticas de apoyo);
- latencia (mediana) y tamaño del prompt.

Uso (todo dentro del candado de GPU)::

    uv run python prompt_lab.py                       # todas las variantes, semilla 42
    uv run python prompt_lab.py --variants L2,L9      # solo algunas
    uv run python prompt_lab.py --seeds 42,43,44      # varias semillas

Los resultados se acumulan en ``resultados/prompt_lab.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import gpu_info
from client import Translator, summarize
from corpus import ADVERSARIAL, BY_ID, LINES
from gpu_lock import gpu_lock
from llama_server import LlamaServer
from pipeline import max_tokens_for, run_pass
from prompts import (
    FEWSHOT_ES_ES,
    FEWSHOT_ES_ES_12,
    STYLE_EN,
    STYLE_ES,
    STYLE_ZH,
    PromptConfig,
    build_messages,
)
from quality import check_output, summarize_checks

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "resultados"
LAB_JSON = RESULTS / "prompt_lab.json"


def _v(name: str, **kw) -> PromptConfig:
    kw.setdefault("style", STYLE_EN)
    kw.setdefault("context", True)
    kw.setdefault("glossary", True)
    return PromptConfig(name, **kw)


#: Variantes de la etapa 1: disposición del prompt (mismo estilo, contexto y glosario).
VARIANTS: dict[str, PromptConfig] = {
    cfg.name: cfg
    for cfg in (
        PromptConfig("L0_baseline", default_template=True),
        _v("L1_composed_pairs", layout="composed", bg_format="pairs", source_label=True),
        _v("L2_composed_en", layout="composed", bg_format="english", source_label=True),
        _v("L3_composed_en_nolabel", layout="composed", bg_format="english", source_label=False),
        _v("L4_composed_pairs_nolabel", layout="composed", bg_format="pairs", source_label=False),
        _v("L5_composed_prose_nolabel", layout="composed", bg_format="prose", source_label=False),
        _v("L6_ctx_official", layout="composed", bg_format="english", style=None, glossary=False,
           only_clause=False),
        _v("L7_personalization_pairs", layout="personalization", bg_format="pairs"),
        _v("L8_personalization_en", layout="personalization", bg_format="english"),
        _v("L9_chat", layout="chat"),
        _v("L10_chat_system", layout="chat_system"),
        _v("L11_zh_en", layout="zh", bg_format="english", style=STYLE_ZH),
        _v("L12_delimited_pairs", layout="delimited", bg_format="pairs"),
        _v("L13_delimited_en", layout="delimited", bg_format="english"),
        # --- Etapa 2: sobre las disposiciones robustas (chino y chat), estilo y few-shot ---
        PromptConfig("M0_baseline", default_template=True),
        _v("M1_zh", layout="zh", bg_format="english", style=STYLE_ZH),
        _v("M2_zh_style_es", layout="zh", bg_format="english", style=STYLE_ES),
        _v("M3_zh_lang_spain", layout="zh", bg_format="english", style=STYLE_ZH,
           target_lang_zh="西班牙语（西班牙）"),
        _v("M4_chat", layout="chat"),
        _v("M5_chat_fewshot", layout="chat", fewshot=FEWSHOT_ES_ES),
        _v("M6_chat_fewshot_nostyle", layout="chat", fewshot=FEWSHOT_ES_ES, style=None),
        _v("M7_chat_zh", layout="chat_zh", style=STYLE_ZH),
        _v("M8_chat_zh_fewshot", layout="chat_zh", style=STYLE_ZH, fewshot=FEWSHOT_ES_ES),
        _v("M9_chat_zh_fewshot_es", layout="chat_zh", style=STYLE_ES, fewshot=FEWSHOT_ES_ES),
        _v("M10_chat_system_fewshot", layout="chat_system", fewshot=FEWSHOT_ES_ES),
        # --- Etapa 3: híbridos (few-shot + historial en turnos + glosario chino al final) ---
        _v("N1_chat_fs6_zhgloss", layout="chat", fewshot=FEWSHOT_ES_ES, turn_style=False, glossary_zh=True),
        _v("N2_chat_fs12_zhgloss", layout="chat", fewshot=FEWSHOT_ES_ES_12, turn_style=False, glossary_zh=True),
        _v("N3_chat_fs12_nostyle_zhgloss", layout="chat", fewshot=FEWSHOT_ES_ES_12, style=None, glossary_zh=True),
        _v("N4_chatsys_fs6_zhgloss", layout="chat_system", fewshot=FEWSHOT_ES_ES, glossary_zh=True),
        _v("N5_chatsys_fs12_zhgloss", layout="chat_system", fewshot=FEWSHOT_ES_ES_12, glossary_zh=True),
        _v("N6_chat_fs12_engloss", layout="chat", fewshot=FEWSHOT_ES_ES_12, turn_style=False),
        # --- Etapa 4: candidata final y sus ablaciones (glosario ya sin artículos) ---
        _v("N7_final", layout="chat_system", fewshot=FEWSHOT_ES_ES, glossary_zh=True),
        _v("N8_final_nofewshot", layout="chat_system", glossary_zh=True),
        _v("N9_final_lexicon", layout="chat_system", fewshot=FEWSHOT_ES_ES, glossary_zh=True, lexicon=True),
        _v("N10_final_noctx", layout="chat_system", fewshot=FEWSHOT_ES_ES, glossary_zh=True, context=False),
        # --- Etapa 5: robustez. Turnos envueltos en la instrucción de traducir ---
        _v("N11_chatsys_wrapped", layout="chat_system", fewshot=FEWSHOT_ES_ES, glossary_zh=True, wrap_turns=True),
        _v("N12_chatsys_wrapped_12", layout="chat_system", fewshot=FEWSHOT_ES_ES_12, glossary_zh=True,
           wrap_turns=True),
        _v("N13_chatsys_wrapped_nofs", layout="chat_system", glossary_zh=True, wrap_turns=True),
    )
}

STRUCT_FLAGS = ("multiline", "truncated", "label_prefix", "boilerplate", "wrapped", "cjk", "empty")

#: Frases adversariales que NO se tradujeron, según la lectura de las salidas (valoración
#: manual sobre ``resultados/prompt_lab_adversarial.json``; el chequeo automático de
#: ``corpus.ADVERSARIAL`` es solo orientativo). Nº 104: obedece «into French» (traduce al
#: francés o traduce un ejemplo previo); nº 106: inventa un argumento en vez de traducir.
ADVERSARIAL_FAILS: dict[str, tuple[int, ...]] = {
    "M0_baseline": (104,),
    "M1_zh": (104,),
    "M4_chat": (104,),
    "M5_chat_fewshot": (),
    "M8_chat_zh_fewshot": (),
    "N1_chat_fs6_zhgloss": (),
    "N7_final": (104, 106),
    "N11_chatsys_wrapped": (),
    "N12_chatsys_wrapped_12": (),
    "N13_chatsys_wrapped_nofs": (104,),
}


def describe(cfg: PromptConfig) -> str:
    """Descripción corta de una variante, generada a partir de su configuración."""
    if cfg.default_template:
        return "plantilla «Default Translation» oficial, sin nada más"
    parts = [cfg.layout]
    if cfg.layout in ("composed", "zh", "personalization", "delimited"):
        parts.append(f"fondo={cfg.bg_format}")
        if cfg.layout == "composed" and cfg.context:
            parts.append("con [Source Text]" if cfg.source_label else "sin [Source Text]")
    if cfg.fewshot:
        parts.append(f"{len(cfg.fewshot)} ejemplos")
    if cfg.layout in ("chat_system",):
        parts.append("turnos envueltos" if cfg.wrap_turns else "turnos crudos")
    if cfg.style is None:
        parts.append("sin estilo")
    if not cfg.context:
        parts.append("sin contexto")
    if cfg.glossary_zh:
        parts.append("glosario chino")
    if cfg.lexicon:
        parts.append("+léxico de España")
    if cfg.target_lang_zh != "西班牙语":
        parts.append("destino «西班牙语（西班牙）»")
    return ", ".join(parts)


def write_report(path: Path) -> None:
    """``prompt_lab.md``: tabla de todas las variantes probadas y de la prueba adversarial."""
    store = json.loads(LAB_JSON.read_text(encoding="utf-8"))
    adv_path = LAB_JSON.with_name("prompt_lab_adversarial.json")
    adv = json.loads(adv_path.read_text(encoding="utf-8")) if adv_path.exists() else {}
    lines = [
        "# Laboratorio de prompts (generado por prompt_lab.py --report)",
        "",
        "Cada fila es una pasada de las 65 frases (misma semilla 42, temperatura 0,7, `top_p` 0,6, "
        "`top_k` 20, penalización 1,05), con el contexto que produce el propio modelo y el glosario "
        "filtrado por frase. Las columnas son comprobaciones AUTOMÁTICAS de apoyo, no una métrica formal:",
        "",
        "- **Estructura**: líneas en las que el modelo devuelve varias líneas, etiquetas del prompt, "
        "muletillas, texto truncado o entre comillas (es decir, algo que no es solo la traducción).",
        "- **Léxico**: comprobaciones de vocabulario de España sobre 11 frases (16 comprobaciones; "
        "p. ej. «zumo» frente a «jugo», «coche» frente a «carro», «móvil» frente a «celular»).",
        "- **Plural**: de las 6 frases dirigidas a varias personas, cuántas usan «vosotros», «ustedes» o "
        "ninguna de las dos formas (neutro).",
        "- **Glosario**: términos inventados respetados (10 en las 5 frases de glosario).",
        "",
        "| Variante | Descripción | Estructura (fallos/65) | Léxico (OK/16) | Plural (vos/ust/neutro) | Glosario (OK/10) | Tokens de prompt (p50) | Total p50, ms |",
        "|:---|:---|---:|---:|:---:|---:|---:|---:|",
    ]
    order = {name: i for i, name in enumerate(VARIANTS)}
    for key in sorted(store, key=lambda k: (order.get(k.split("|")[0], 999), k)):
        if "|seed42" not in key:
            continue
        ev = evaluate(store[key]["records"])  # se recalcula con el código de calidad vigente
        q = ev["quality"]
        name = key.split("|")[0]
        cfg = VARIANTS.get(name)
        desc = describe(cfg) if cfg else ""
        label = f"{name} (con caché)" if "|cache" in key else name
        lines.append(
            f"| `{label}` | {desc} | {q['struct_fail']} | {q['lexical_ok']} | "
            f"{q['plural_vosotros']}/{q['plural_ustedes']}/{q['plural_neutral']} | {q['glossary_ok']} | "
            f"{ev['prompt_tokens']['p50']:.0f} | {ev['total_ms']['p50']:.0f} |"
        )
    if adv:
        lines += ["", "## Robustez: frases que suenan a órdenes al asistente (sin contexto)", "",
                  "Fallos = frases que NO se tradujeron (valoración manual, ver `ADVERSARIAL_FAILS`).", "",
                  "| Variante | Fallos (de 10) | Nº de las frases falladas |", "|:---|---:|:---|"]
        for name in adv:
            fails = ADVERSARIAL_FAILS.get(name)
            if fails is None:
                continue
            lines.append(f"| `{name}` | {len(fails)} | {', '.join(map(str, fails)) or '—'} |")
        shown = [n for n in ("M0_baseline", "N7_final", "N12_chatsys_wrapped_12") if n in adv]
        if shown:
            lines += ["", "Salidas de tres variantes:", "",
                      "| Nº | Inglés | " + " | ".join(f"`{n}`" for n in shown) + " |",
                      "|---:|:---|" + ":---|" * len(shown)]
            for i, item in enumerate(adv[shown[0]]):
                cells = [adv[n][i]["output"].replace("|", "\\|").replace("\n", " ⏎ ") for n in shown]
                lines.append(f"| {item['line_id']} | {item['source']} | " + " | ".join(cells) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate(records: list[dict]) -> dict:
    """Métricas de calidad automática y de latencia de una pasada."""
    pairs = []
    struct = []
    for rec in records:
        res = check_output(BY_ID[rec["line_id"]], rec["output"], rec["finish_reason"])
        pairs.append((BY_ID[rec["line_id"]], res))
        if any(res["flags"][k] for k in STRUCT_FLAGS):
            struct.append(rec["line_id"])
    q = summarize_checks(pairs)
    q["struct_fail"] = len(struct)
    q["struct_fail_ids"] = struct
    return {
        "quality": q,
        "total_ms": summarize([r["total_ms"] for r in records]),
        "prompt_tokens": summarize([r["prompt_tokens"] for r in records]),
    }


def print_table(rows: list[tuple[str, dict]]) -> None:
    head = (
        f"{'variante':<32}{'estruct':>8}{'no-trad':>8}{'léxico':>9}{'vos/ust/neu':>13}"
        f"{'glos':>7}{'trampa':>7}{'ms p50':>8}{'tok':>6}"
    )
    print(head)
    print("-" * len(head))
    for key, ev in rows:
        q = ev["quality"]
        print(
            f"{key:<32}{q['struct_fail']:>8}{q['non_translation']:>8}"
            f"{q['lexical_ok']:>5}/{q['lexical_total']:<3}"
            f"{q['plural_vosotros']:>6}/{q['plural_ustedes']}/{q['plural_neutral']:<4}"
            f"{q['glossary_ok']:>4}/{q['glossary_total']:<2}{q['trap_fail']:>6}"
            f"{ev['total_ms']['p50']:>8.0f}{ev['prompt_tokens']['p50']:>6.0f}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variants", default="", help="nombres o prefijos separados por comas (por defecto, todas)")
    ap.add_argument("--seeds", default="42", help="semillas separadas por comas")
    ap.add_argument("--show", default="", help="ids de línea cuyas salidas se imprimen (p. ej. 1,4,16)")
    ap.add_argument("--model", default="", help="ruta de otro GGUF (por defecto, Hy-MT2-1.8B Q8_0)")
    ap.add_argument("--tag", default="", help="sufijo para separar resultados (p. ej. con otro modelo)")
    ap.add_argument("--cache", action="store_true", help="usar la caché de prompt del servidor")
    ap.add_argument("--adversarial", action="store_true",
                    help="en vez de las 65 líneas, probar las 10 frases adversariales (sin contexto)")
    ap.add_argument("--report", action="store_true",
                    help="solo regenerar resultados/prompt_lab.md a partir de los JSON (sin usar la GPU)")
    args = ap.parse_args()
    if args.report:
        write_report(RESULTS / "prompt_lab.md")
        print("escrito", RESULTS / "prompt_lab.md")
        return 0

    wanted = [w for w in args.variants.split(",") if w]
    names = [n for n in VARIANTS if not wanted or any(n == w or n.startswith(w + "_") for w in wanted)]
    seeds = [int(s) for s in args.seeds.split(",")]
    show = [int(s) for s in args.show.split(",") if s]

    RESULTS.mkdir(parents=True, exist_ok=True)
    lab_json = LAB_JSON.with_name(f"prompt_lab{args.tag}.json")
    store = json.loads(lab_json.read_text(encoding="utf-8")) if lab_json.exists() else {}
    rows: list[tuple[str, dict]] = []

    with gpu_lock():
        extra = {"model": Path(args.model)} if args.model else {}
        srv = LlamaServer(log_path=RESULTS / "llama-server.log", **extra)
        try:
            srv.start()
            with Translator(srv.base_url) as tr:
                for line in LINES[:3]:  # calentamiento
                    tr.complete(line.text, stream=True, max_tokens=64)
                if args.adversarial:
                    adv: dict[str, list[dict]] = {}
                    for name in names:
                        cfg = VARIANTS[name]
                        adv[name] = []
                        for line in ADVERSARIAL:
                            res = tr.complete(
                                build_messages(line.text, cfg, (), ()),
                                stream=False, max_tokens=max_tokens_for(line.text),
                                temperature=cfg.temperature, seed=seeds[0],
                            )
                            adv[name].append({"line_id": line.id, "source": line.text, "output": res.text.strip()})
                            print(f"{name:<26} {line.id} {line.text[:38]:<38} -> {res.text.strip()[:110]!r}")
                    path = lab_json.with_name(f"prompt_lab_adversarial{args.tag}.json")
                    merged = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                    merged.update(adv)
                    path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
                    names = []
                for name in names:
                    for seed in seeds:
                        recs = run_pass(tr, LINES, VARIANTS[name], stream=True, seed=seed, cache_prompt=args.cache)
                        ev = evaluate(recs)
                        key = f"{name}|seed{seed}" + ("|cache" if args.cache else "")
                        store[key] = {"eval": ev, "records": recs}
                        rows.append((key, ev))
                        for lid in show:
                            rec = next(r for r in recs if r["line_id"] == lid)
                            print(f"   [{key}] {lid}: {rec['output'][:160]!r}")
        finally:
            srv.stop()
        print("VRAM libre tras cerrar:", gpu_info.vram_used_mib(), "MiB usados")

    lab_json.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print_table(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
