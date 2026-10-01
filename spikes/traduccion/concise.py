"""Modo resumen (traducción concisa) del spike S2.

Cuando la voz en español vaya con retraso, la aplicación pedirá traducciones más cortas
que conserven lo esencial. Este script compara, sobre 10 frases largas (>= 15 palabras)
del corpus, la traducción normal (prompt final) con varias formas de pedir una
traducción concisa:

- ``official_style_en`` / ``official_style_es`` / ``official_style_zh``: la plantilla
  oficial «Style» de Hy-MT2 con un estilo conciso (en inglés, en español —la
  formulación del orquestador— y en chino), tal cual, en un solo mensaje;
- ``official_style_budget``: plantilla «Style» + tope de palabras;
- ``official_personalization``: plantilla oficial «Personalization» con la preferencia
  de concisión y un tope de palabras;
- ``final_sys_concise``: el prompt final (sistema + ejemplos + historial) con el estilo
  conciso en el mensaje de sistema;
- ``final_concise_fs``: igual, pero los ejemplos previos son traducciones CONCISAS;
- ``final_concise_fs_budget``: ejemplos concisos y tope de palabras en cada turno;
- ``two_step``: traducción normal y una segunda llamada que la acorta.

Mide reducción de longitud (palabras y caracteres, en %), latencia y cuántos elementos
clave de la frase conserva (aproximación automática; la valoración del sentido es
manual, ver ``ASSESSMENT``).

Uso::

    uv run python concise.py            # mide (dentro del candado de GPU) y escribe resultados/
    uv run python concise.py --report   # solo regenera modo_resumen.md desde el JSON (sin GPU)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import gpu_info
from client import Translator, summarize
from corpus import BY_ID, CONCISE_IDS, LINES, count_words
from gpu_lock import gpu_lock
from llama_server import LlamaServer
from pipeline import N_PAIRS, glossary_for, history_for, max_tokens_for, run_pass
from prompts import (
    CONCISE_STYLE_EN,
    CONCISE_STYLE_ES,
    FEWSHOT_ES_ES_12,
    build_messages,
    final_config,
    word_budget,
)
from quality import check_output, key_recall, reduction_pct, words_and_chars

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "resultados"
MD_PATH = RESULTS / "modo_resumen.md"

SEEDS = (42, 43, 44)
FINAL_CFG = final_config()

CONCISE_STYLE_ZH = "极其简洁，只保留最核心的意思，使用西班牙本土西班牙语"

#: Ejemplos de traducción concisa (inglés largo -> español de España breve). Vocabulario
#: distinto del corpus de prueba. Sirven para cebar la brevedad como turnos previos.
FEWSHOT_CONCISE: tuple[tuple[str, str], ...] = (
    (
        "If you two don't finish cleaning the kitchen before your mother gets home, she's going to be really angry with both of you.",
        "Limpiad la cocina antes de que llegue vuestra madre o se enfadará.",
    ),
    (
        "I've been waiting at the train station for over an hour, and nobody has told me why the train is delayed.",
        "Una hora esperando en la estación y nadie explica el retraso.",
    ),
    (
        "We need to leave the hotel before noon, so please pack your things and meet me downstairs in ten minutes.",
        "Salimos antes del mediodía: haced las maletas y bajad en diez minutos.",
    ),
    (
        "The doctor said that the test results will be ready by Friday, but she wants to see you again next week anyway.",
        "Resultados el viernes; y la doctora quiere verte la semana que viene.",
    ),
    (
        "I know you're upset about what happened at the party, but I promise I never meant to embarrass you in front of everyone.",
        "Sé que estás enfadado, pero te prometo que no quise avergonzarte.",
    ),
    (
        "Honestly, I think the best plan is to wait until the storm passes and then drive to the coast early tomorrow morning.",
        "Lo mejor: esperar a que pase la tormenta y salir mañana temprano hacia la costa.",
    ),
)

VARIANTS: tuple[str, ...] = (
    "normal",
    "official_style_en",
    "official_style_es",
    "official_style_zh",
    "official_style_budget",
    "official_style_subtitle_en",
    "official_style_subtitle_zh",
    "official_style_telegraphic",
    "official_personalization",
    "official_personalization_zh",
    "final_sys_concise",
    "final_concise_fs",
    "final_concise_fs_budget",
    "two_step",
)

#: Variantes cuyo detalle línea a línea (semilla 42) se imprime en el informe: la que más acorta
#: de las que usan el modelo y la referencia derivada (descartar la última oración).
#: Clave = sufijo de los ficheros (``""`` para el 1,8B, ``"_7b"`` para el 7B).
DETAIL_VARIANTS: dict[str, tuple[str, ...]] = {
    "": ("official_personalization_zh", "derived_drop_last_sentence"),
    "_7b": ("official_style_telegraphic", "official_personalization", "derived_drop_last_sentence"),
}

_DERIVED_ASSESSMENT: dict[int, tuple[str, str]] = {
    1: ("n/a", "una sola oración: no hay nada que quitar"),
    9: ("parcial", "pierde la conclusión («nada coincide con su piso»)"),
    11: ("no", "pierde la orden (conseguir las grabaciones), que es lo accionable"),
    24: ("parcial", "pierde el descanso y el café, secundarios"),
    33: ("n/a", "una sola oración: no hay nada que quitar"),
    34: ("parcial", "pierde el sueldo y el mal carácter"),
    42: ("parcial", "pierde el destino (el aparcamiento)"),
    43: ("parcial", "pierde el motivo (el bocadillo y el baño)"),
    49: ("no", "pierde quién concursa (Marcus de Detroit)"),
    55: ("no", "queda solo «Escuchad»: pierde todo el plan"),
}

#: Valoración MANUAL del sentido (semilla 42), tras leer las salidas: sufijo -> variante ->
#: línea -> (veredicto, nota). Veredictos: «sí» conserva lo esencial, «parcial» pierde un dato
#: secundario, «no» pierde algo clave o cambia el sentido, «n/a» no hay reducción que valorar.
#: Es una lectura del autor del spike, no una revisión humana externa.
ASSESSMENT: dict[str, dict[str, dict[int, tuple[str, str]]]] = {
    "": {  # Hy-MT2-1.8B Q8_0
        "official_personalization_zh": {
            1: ("sí", "quita «volviste a poner»: -18 %, mismo sentido"),
            9: ("sí", "casi igual (-7 %); mantiene el error de «victimario»"),
            11: ("sí", "más larga que la normal (+25 %)"),
            24: ("sí", "«ha regresado»…, -11 %"),
            33: ("n/a", "idéntica a la normal"),
            34: ("n/a", "idéntica salvo «violento» por «terrible»"),
            42: ("sí", "-14 %, pero pasa a «tomen sus laptops» (peor castellano)"),
            43: ("n/a", "idéntica salvo «siguiente» por «próxima»"),
            49: ("n/a", "idéntica salvo signos de exclamación"),
            55: ("sí", "-11 %: «Escuchen todos»; mantiene el error de «cofre»"),
        },
        "derived_drop_last_sentence": _DERIVED_ASSESSMENT,
    },
    "_7b": {  # Hy-MT2-7B Q4_K_M
        "official_style_telegraphic": {
            1: ("parcial", "pasa de pregunta en 2.ª persona a afirmación en 3.ª: pierde «¿De verdad…?»"),
            9: ("sí", "telegráfico (sin artículos ni preposiciones) pero con los 6 elementos"),
            11: ("sí", "«Quieren…» en plural en vez de «alguien»; conserva la orden"),
            24: ("sí", "conserva los 4 elementos"),
            33: ("sí", "pierde «invierno» y «de verdad»"),
            34: ("sí", "«Buscan trabajo» (persona cambiada); mismo sentido"),
            42: ("sí", "conserva la orden, el destino y el «hoy»"),
            43: ("sí", "infinitivo («Parar…»); conserva los 4 elementos"),
            49: ("sí", "pierde «¿Están listos?»"),
            55: ("parcial", "«la caja» por la bóveda y pierde «Escuchad todos»"),
        },
        "official_personalization": {
            1: ("parcial", "pierde «vacío» y la nevera"),
            9: ("sí", "«nada corresponde a su apartamento»"),
            11: ("parcial", "pierde la primera frase (alguien quiere que lo creamos)"),
            24: ("parcial", "pierde el descanso y el café"),
            33: ("sí", "pierde «invierno»"),
            34: ("sí", "conserva trabajo, herrero, sueldo y carácter"),
            42: ("no", "«Todos, a los ordenadores, al aparcamiento»: pierde «seguidme» y cambia el sentido"),
            43: ("no", "«Para un sándwich y baño, ¿puede parar?»: pierde la gasolinera y pasa a «usted»"),
            49: ("no", "«¡Bienvenido, Marcus! ¿Estás listo?»: cambia el sentido y pierde Lucky Hour y Detroit"),
            55: ("sí", "«Abre el bóveda» (género mal); conserva el plan"),
        },
        "derived_drop_last_sentence": _DERIVED_ASSESSMENT,
    },
}

NO_REDUCTION_FLAGS = ("boilerplate", "label_prefix", "multiline", "wrapped", "cjk", "english_leak", "truncated", "empty")


# ---------------------------------------------------------------------------
# Construcción de prompts
# ---------------------------------------------------------------------------
def _system(style: str) -> dict:
    return {
        "role": "system",
        "content": (
            "Translate every user message into Spanish. "
            f"The translation style must strictly conform to [{style}]. "
            "ONLY output the translated result without any additional explanation."
        ),
    }


def _wrap(text: str, budget: int | None = None) -> str:
    """Turno de usuario con la instrucción de la plantilla «Default Translation»."""
    if budget:
        instr = (
            f"Translate the following text into Spanish in at most {budget} words, keeping only "
            "the essential meaning. Note that you must ONLY output the translated result "
            "without any additional explanation:"
        )
    else:
        instr = (
            "Translate the following text into Spanish. Note that you must ONLY output the "
            "translated result without any additional explanation:"
        )
    return f"{instr}\n\n{text}"


def concise_messages(variant: str, source: str, history: tuple, n_words: int) -> list[dict]:
    """Mensajes de una sola llamada para el modo resumen (``two_step`` usa dos llamadas)."""
    budget = word_budget(n_words)
    if variant == "official_style_en":
        return [{"role": "user", "content": (
            "Please translate the following text into Spanish. Note that the translation style "
            f"must strictly conform to [{CONCISE_STYLE_EN}]:\n\n{source}")}]
    if variant == "official_style_es":
        return [{"role": "user", "content": (
            "Please translate the following text into Spanish. Note that the translation style "
            f"must strictly conform to [{CONCISE_STYLE_ES}]:\n\n{source}")}]
    if variant == "official_style_zh":
        return [{"role": "user", "content": (
            f"请将以下文本翻译为西班牙语。\n注意翻译的风格要严格符合【{CONCISE_STYLE_ZH}】\n\n{source}")}]
    if variant == "official_style_budget":
        style = f"very concise Spanish from Spain, at most {budget} words: keep only the essential meaning"
        return [{"role": "user", "content": (
            "Please translate the following text into Spanish. Note that the translation style "
            f"must strictly conform to [{style}]:\n\n{source}")}]
    if variant == "official_style_subtitle_en":
        style = "video subtitles: concise, natural spoken Spanish from Spain, short enough to be read quickly"
        return [{"role": "user", "content": (
            "Please translate the following text into Spanish. Note that the translation style "
            f"must strictly conform to [{style}]:\n\n{source}")}]
    if variant == "official_style_subtitle_zh":
        return [{"role": "user", "content": (
            "请将以下文本翻译为西班牙语。\n注意翻译的风格要严格符合【视频字幕风格：简洁、口语化、便于快速阅读的"
            f"西班牙本土西班牙语】\n\n{source}")}]
    if variant == "official_style_telegraphic":
        style = f"telegraphic Spanish from Spain, like a news headline: drop filler words, at most {budget} words"
        return [{"role": "user", "content": (
            "Please translate the following text into Spanish. Note that the translation style "
            f"must strictly conform to [{style}]:\n\n{source}")}]
    if variant == "official_personalization_zh":
        return [{"role": "user", "content": (
            f"【待翻译文本】\n{source}\n\n【翻译任务】\n1、译文要尽可能简短，只保留核心意思，省略次要细节\n"
            f"2、译文不超过{budget}个单词\n3、使用自然的西班牙本土西班牙语\n4、将【待翻译文本】翻译为西班牙语。")}]
    if variant == "official_personalization":
        tasks = [
            "Make the translation as concise as possible: keep only the essential meaning and "
            "drop filler words and secondary details.",
            f"The translation must have at most {budget} words.",
            "Use natural Spanish from Spain.",
            "Translate the [Source Text] into Spanish.",
            "Output ONLY the translated result without any additional explanation.",
        ]
        numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(tasks, 1))
        return [{"role": "user", "content": f"[Source Text]\n{source}\n\n[Translation Tasks]\n{numbered}"}]
    if variant in ("final_sys_concise", "final_concise_fs", "final_concise_fs_budget"):
        msgs = [_system(CONCISE_STYLE_EN)]
        if variant == "final_sys_concise":
            for en, es in FEWSHOT_ES_ES_12:
                msgs += [{"role": "user", "content": _wrap(en)}, {"role": "assistant", "content": es}]
        else:
            with_budget = variant == "final_concise_fs_budget"
            for en, es in FEWSHOT_CONCISE:
                b = word_budget(count_words(en)) if with_budget else None
                msgs += [{"role": "user", "content": _wrap(en, b)}, {"role": "assistant", "content": es}]
        for en, es in history:  # el contexto previo son traducciones normales
            msgs += [{"role": "user", "content": _wrap(en)}, {"role": "assistant", "content": es}]
        final_budget = budget if variant == "final_concise_fs_budget" else None
        msgs.append({"role": "user", "content": _wrap(source, final_budget)})
        return msgs
    raise ValueError(f"Variante desconocida: {variant!r}")


def shorten_messages(text_es: str, n_words: int) -> list[dict]:
    """Segunda llamada de ``two_step``: acorta un texto ya traducido."""
    budget = word_budget(n_words)
    return [{"role": "user", "content": (
        f"Shorten the following Spanish text to at most {budget} words, keeping only the essential "
        "meaning and the same register. Note that you must ONLY output the shortened text without "
        f"any additional explanation:\n\n{text_es}")}]


# ---------------------------------------------------------------------------
# Medición
# ---------------------------------------------------------------------------
def measure(model: Path | None = None, seeds: tuple[int, ...] = SEEDS) -> dict:
    RESULTS.mkdir(parents=True, exist_ok=True)
    data: dict = {"seeds": list(seeds), "variants": list(VARIANTS), "records": []}
    with gpu_lock() as waited:
        data["lock_wait_s"] = waited
        extra = {"model": model} if model else {}
        srv = LlamaServer(log_path=RESULTS / "llama-server.log", **extra)
        data["model"] = srv.model.name
        try:
            srv.start()
            with Translator(srv.base_url) as tr:
                for line in LINES[:3]:  # calentamiento
                    tr.complete(build_messages(line.text, FINAL_CFG), stream=True, max_tokens=96)
                # Contexto: la traducción normal de las 65 líneas (semilla 42).
                base = run_pass(tr, LINES, FINAL_CFG, stream=True, seed=42)
                frozen = {r["line_id"]: r["output"] for r in base}
                print(f"[concise] contexto listo ({len(frozen)} líneas)", flush=True)
                for seed in seeds:
                    normal_out: dict[int, dict] = {}
                    for variant in VARIANTS:
                        for lid in CONCISE_IDS:
                            idx = next(i for i, ln in enumerate(LINES) if ln.id == lid)
                            line = LINES[idx]
                            n_words = count_words(line.text)
                            history = history_for(LINES, idx, frozen, N_PAIRS)
                            if variant == "normal":
                                glossary = glossary_for(line.text, history)
                                msgs = build_messages(line.text, FINAL_CFG, history, glossary)
                                res = tr.complete(msgs, stream=True, max_tokens=max_tokens_for(line.text), seed=seed)
                                normal_out[lid] = {"text": res.text.strip(), "total_ms": res.total_ms}
                                rec = _record(variant, seed, lid, res.text.strip(), res, res.total_ms, res.ttft_ms)
                            elif variant == "two_step":
                                first = normal_out[lid]
                                res = tr.complete(shorten_messages(first["text"], n_words), stream=True,
                                                  max_tokens=max_tokens_for(line.text), seed=seed)
                                total = first["total_ms"] + res.total_ms
                                ttft = first["total_ms"] + (res.ttft_ms or res.total_ms)
                                rec = _record(variant, seed, lid, res.text.strip(), res, total, ttft)
                            else:
                                msgs = concise_messages(variant, line.text, history, n_words)
                                res = tr.complete(msgs, stream=True, max_tokens=max_tokens_for(line.text), seed=seed)
                                rec = _record(variant, seed, lid, res.text.strip(), res, res.total_ms, res.ttft_ms)
                            data["records"].append(rec)
                    print(f"[concise] semilla {seed} hecha", flush=True)
        finally:
            srv.stop()
        data["vram_after_stop_mib"] = gpu_info.vram_used_mib()
    return data


def _record(variant: str, seed: int, lid: int, text: str, res, total_ms: float, ttft_ms: float | None) -> dict:
    return {
        "variant": variant, "seed": seed, "line_id": lid, "output": text,
        "total_ms": total_ms, "ttft_ms": ttft_ms,
        "completion_tokens": res.completion_tokens, "prompt_tokens": res.prompt_tokens,
        "finish_reason": res.finish_reason,
    }


# ---------------------------------------------------------------------------
# Análisis e informe (sin GPU)
# ---------------------------------------------------------------------------
#: Variante DERIVADA (no es una petición al modelo): la traducción normal sin su última
#: oración. Referencia de lo que se ganaría simplemente descartando contenido.
DERIVED = "derived_drop_last_sentence"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def drop_last_sentence(text: str) -> str:
    """Quita la última oración (si hay dos o más); si solo hay una, la deja como está."""
    parts = _SENTENCE_SPLIT.split(text.strip())
    return " ".join(parts[:-1]) if len(parts) >= 2 else text.strip()


def _row(r: dict, normal_text: str, text: str) -> dict:
    """Métricas de una salida frente a la traducción normal de la misma frase y semilla."""
    w_n, c_n = words_and_chars(normal_text)
    w_c, c_c = words_and_chars(text)
    kr = key_recall(r["line_id"], text)
    chk = check_output(BY_ID[r["line_id"]], text, r.get("finish_reason", "stop"))
    budget = word_budget(count_words(BY_ID[r["line_id"]].text))
    return {
        "seed": r["seed"], "line_id": r["line_id"], "output": text,
        "total_ms": r.get("total_ms"), "ttft_ms": r.get("ttft_ms"), "completion_tokens": r.get("completion_tokens"),
        "words_normal": w_n, "words": w_c, "chars_normal": c_n, "chars": c_c,
        "red_words": reduction_pct(w_n, w_c), "red_chars": reduction_pct(c_n, c_c),
        "key_hit": kr["n_hit"], "key_total": kr["n_total"], "key_missing": kr["missing"],
        "bad_flags": [k for k in NO_REDUCTION_FLAGS if chk["flags"][k]],
        "over_budget": w_c > budget,
    }


def _variant_summary(rows: list[dict]) -> dict:
    ok = [x for x in rows if not x["bad_flags"]]
    key_share = [x["key_hit"] / x["key_total"] for x in rows]
    return {
        "n": len(rows),
        "red_words": summarize([x["red_words"] for x in rows]),
        "red_chars": summarize([x["red_chars"] for x in rows]),
        "share_reduced_25": sum(1 for x in rows if x["red_words"] >= 25) / len(rows),
        "share_not_shorter": sum(1 for x in rows if x["red_words"] <= 0) / len(rows),
        "key_recall_mean": sum(key_share) / len(key_share),
        "total_ms": summarize([x["total_ms"] for x in rows if x["total_ms"] is not None]),
        "ttft_ms": summarize([x["ttft_ms"] for x in rows if x["ttft_ms"] is not None]),
        "completion_tokens": summarize([x["completion_tokens"] for x in rows if x["completion_tokens"] is not None]),
        "bad_output": len(rows) - len(ok),
        "over_budget": sum(1 for x in rows if x["over_budget"]),
        "words_mean": sum(x["words"] for x in rows) / len(rows),
        "rows": rows,
    }


def analyse(data: dict) -> dict:
    """Reducción, elementos clave y latencia por variante, frente a la traducción normal."""
    recs = data["records"]
    normal = {(r["seed"], r["line_id"]): r for r in recs if r["variant"] == "normal"}
    out: dict = {"variants": {}, "lines": {}}
    for variant in data["variants"]:
        rows = [
            _row(r, normal[(r["seed"], r["line_id"])]["output"], r["output"])
            for r in recs
            if r["variant"] == variant
        ]
        out["variants"][variant] = _variant_summary(rows)
    derived_rows = []
    for (seed, lid), n in normal.items():
        derived_rows.append(_row({"seed": seed, "line_id": lid, "finish_reason": "stop"}, n["output"],
                                 drop_last_sentence(n["output"])))
    out["variants"][DERIVED] = _variant_summary(derived_rows)
    return out


def fmt(x: float | None, nd: int = 0) -> str:
    if x is None:
        return "—"
    s = f"{x:.{nd}f}"
    if float(s) == 0:  # evita «-0»
        s = s.lstrip("-")
    return s.replace(".", ",")


def write_report(data: dict, ana: dict, md_path: Path = MD_PATH, tag: str = "") -> None:
    v = ana["variants"]
    lines = [
        "# Modo resumen: traducción concisa con Hy-MT2 (generado por concise.py)",
        "",
        f"Modelo: `{data.get('model', 'Hy-MT2-1.8B-Q8_0.gguf')}`.",
        "",
        f"Diez frases largas del corpus (≥ 15 palabras: líneas {', '.join(map(str, CONCISE_IDS))}), "
        f"{len(data['seeds'])} semillas ({', '.join(map(str, data['seeds']))}) por variante = "
        f"{len(CONCISE_IDS) * len(data['seeds'])} traducciones por variante. La reducción se calcula "
        "contra la traducción normal (prompt final) de la misma frase y la misma semilla.",
        "",
        "## Resumen por variante",
        "",
        "| Variante | Palabras de media | Reducción de palabras: mediana / media | Reducción de caracteres: mediana | Frases con ≥ 25 % menos | Frases sin acortar | Elementos clave conservados | Salidas que no son traducción | Total p50, ms | 1.er token p50, ms | Tokens generados (media) |",
        "|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    names = [*data["variants"], DERIVED]

    def ms(stat: dict, key: str) -> str:
        return fmt(stat[key]) if stat.get("n") else "—"

    for name in names:
        s = v[name]
        tokens = fmt(s["completion_tokens"]["mean"], 1) if s["completion_tokens"].get("n") else "—"
        lines.append(
            f"| `{name}` | {fmt(s['words_mean'], 1)} | {fmt(s['red_words']['p50'])} % / {fmt(s['red_words']['mean'])} % | "
            f"{fmt(s['red_chars']['p50'])} % | {s['share_reduced_25']:.0%} | {s['share_not_shorter']:.0%} | "
            f"{s['key_recall_mean']:.0%} | {s['bad_output']} | {ms(s['total_ms'], 'p50')} | "
            f"{ms(s['ttft_ms'], 'p50')} | {tokens} |"
        )
    lines += ["", "Descripción de las variantes:", "",
              "- `normal`: prompt final, sin pedir concisión (referencia).",
              "- `official_style_en` / `official_style_es` / `official_style_zh`: plantilla oficial «Style» en un solo "
              "mensaje (sin contexto ni ejemplos) con el estilo conciso en inglés / en español («traduce de forma muy "
              "concisa, solo lo esencial, en español de España») / en chino.",
              "- `official_style_budget`: como `official_style_en` más «at most N words» (N = 60 % de las palabras de la frase inglesa).",
              "- `official_style_subtitle_en` / `official_style_subtitle_zh`: plantilla «Style» con estilo de subtítulos de vídeo "
              "(conciso, hablado, fácil de leer rápido), en inglés y en chino.",
              "- `official_style_telegraphic`: plantilla «Style» con estilo telegráfico, de titular, con tope de palabras.",
              "- `official_personalization` / `official_personalization_zh`: plantilla oficial «Personalization» con la preferencia de "
              "concisión y el tope de palabras, en inglés y en chino.",
              "- `final_sys_concise`: prompt final con el estilo conciso en el mensaje de sistema (ejemplos normales).",
              "- `final_concise_fs`: igual, con 6 ejemplos previos de traducción CONCISA en lugar de los 12 normales.",
              "- `final_concise_fs_budget`: ejemplos concisos y tope de palabras en cada turno.",
              "- `two_step`: traducción normal y una segunda llamada que la acorta (latencia = suma de las dos).",
              f"- `{DERIVED}`: NO es una petición al modelo; es la traducción normal sin su última oración (si tiene dos o más). "
              "Referencia de lo que se ganaría descartando contenido.",
              ""]

    lines += ["## Salidas de todas las variantes (semilla 42)", ""]
    outs = {(n, r["line_id"]): r["output"] for n in names for r in v[n]["rows"] if r["seed"] == 42}
    for lid in CONCISE_IDS:
        lines.append(f"### {lid} · {BY_ID[lid].text}")
        lines.append("")
        for name in names:
            row = next(x for x in v[name]["rows"] if x["seed"] == 42 and x["line_id"] == lid)
            lines.append(
                f"- `{name}` ({row['words']} pal., {fmt(row['red_words'])} %, claves {row['key_hit']}/{row['key_total']}): "
                f"{outs[(name, lid)]}"
            )
        lines.append("")

    for best in DETAIL_VARIANTS.get(tag, ()):
        if best not in v:
            continue
        assess = ASSESSMENT.get(tag, {}).get(best, {})
        lines += [f"## Detalle de `{best}` (semilla 42)", "",
                  "| Nº | Inglés | Normal | Conciso | Palabras (normal → conciso) | Caracteres (normal → conciso) | Total, ms (normal → conciso) | Elementos clave | Sentido (valoración manual) |",
                  "|---:|:---|:---|:---|---:|---:|---:|---:|:---|"]
        for lid in CONCISE_IDS:
            row = next(x for x in v[best]["rows"] if x["seed"] == 42 and x["line_id"] == lid)
            nrm = next(x for x in v["normal"]["rows"] if x["seed"] == 42 and x["line_id"] == lid)
            verdict, note = assess.get(lid, ("—", ""))
            miss = f" (falta: {', '.join(row['key_missing'])})" if row["key_missing"] else ""
            lines.append(
                f"| {lid} | {BY_ID[lid].text} | {outs[('normal', lid)]} | {outs[(best, lid)]} | "
                f"{row['words_normal']} → {row['words']} ({fmt(-row['red_words'])} %) | "
                f"{row['chars_normal']} → {row['chars']} ({fmt(-row['red_chars'])} %) | "
                f"{fmt(nrm['total_ms'])} → {fmt(row['total_ms'])} | {row['key_hit']}/{row['key_total']}{miss} | "
                f"**{verdict}**{(' — ' + note) if note else ''} |"
            )
        sense = [assess.get(lid, ("—", ""))[0] for lid in CONCISE_IDS]
        lines += ["", f"Sentido (manual): {sense.count('sí')} «sí», {sense.count('parcial')} «parcial», "
                      f"{sense.count('no')} «no», {sense.count('n/a')} sin reducción que valorar, de {len(CONCISE_IDS)} frases.", ""]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true", help="solo regenerar el informe desde el JSON (sin GPU)")
    ap.add_argument("--model", default="", help="ruta de otro GGUF (por defecto, Hy-MT2-1.8B Q8_0)")
    ap.add_argument("--tag", default="", help="sufijo de los ficheros de resultados (p. ej. _7b)")
    ap.add_argument("--seeds", default="42,43,44", help="semillas separadas por comas")
    args = ap.parse_args()
    json_path = RESULTS / f"modo_resumen{args.tag}.json"
    md_path = RESULTS / f"modo_resumen{args.tag}.md"
    if args.report:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        seeds = tuple(int(s) for s in args.seeds.split(","))
        data = measure(Path(args.model) if args.model else None, seeds)
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    ana = analyse(data)
    write_report(data, ana, md_path, args.tag)
    print(f"[concise] informe: {md_path}")
    for name in [*data["variants"], DERIVED]:
        s = ana["variants"][name]
        ms = f"{s['total_ms']['p50']:.0f}" if s["total_ms"].get("n") else "—"
        print(f"{name:<28} palabras={s['words_mean']:.1f} reducción(p50)={s['red_words']['p50']:.0f} % "
              f"claves={s['key_recall_mean']:.0%} ms(p50)={ms} mal={s['bad_output']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
