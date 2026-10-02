"""Traducción ja/zh/ko -> español de España con Hy-MT2-7B Q4_K_M (el instalado por la app) y el prompt de producción.

Importa las constantes y los constructores de mensajes de ``src/instanttraductor/mt/hymt2.py`` (sin modificarlo) y habla
con ``llama-server`` (``component_dir("llama-cpp")``) con los mismos parámetros que ``HyMt2Translator._complete``.
Toda la medición va dentro de ``gpu_lock()``.

Variantes de prompt (misma plantilla, distinto ejemplo de cebado):
- ``prod``: el de producción tal cual (12 ejemplos fijos en inglés).
- ``native``: los mismos 12 ejemplos con el original traducido al idioma de origen (el español de destino es el mismo).
- ``zero``: sin ejemplos (solo mensaje de sistema y turno).
Entradas: ``ref`` (referencia de FLEURS con puntuación), ``nopunct`` (la misma sin puntuación ni espacios sobrantes, como un
ASR sin puntuación) y ``asr:<fichero de resultados>`` (lo que reconoció un candidato de ASR, sin música).

Uso: ``uv run python translate.py --jobs prod,ja,ref native,ja,ref ...`` (``--all-variants`` para el conjunto principal).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from pathlib import Path

import httpx
import numpy as np

from idiomas.paths import CORPUS_MANIFEST, RESULTS_DIR, SPIKE_DIR

REPO = SPIKE_DIR.parent.parent
sys.path.insert(0, str(REPO / "src"))  # constantes de producción (solo lectura)
sys.path.insert(0, str(SPIKE_DIR.parent / "traduccion"))  # gpu_lock y llama_server del spike S2 (solo lectura)

from gpu_lock import gpu_lock  # noqa: E402
from instanttraductor.mt import hymt2  # noqa: E402
from instanttraductor.setup.manifest import component_dir  # noqa: E402
from llama_server import LlamaServer  # noqa: E402

#: 12 ejemplos de cebado traducidos al idioma de origen. El destino (español de España) es el de producción.
FEWSHOT_NATIVE: dict[str, list[str]] = {
    "ja": [
        "みんなお腹空いてる？マッシュポテトを作れるよ。",
        "サングラスをかけて、外はすごく日差しが強いよ。",
        "ねえ、二人とも今夜のチケットは買った？",
        "みんな入って座って。",
        "すごい！そのTシャツ、気に入ったよ。",
        "タクシーを拾って。プールで会おう。",
        "君たち、またちゃんと遅刻だね。今回は何があったの？",
        "上着を持って、寒くなってきたよ。",
        "二人とも、一緒にスーパーに行く？",
        "言ってくれなかったなんて信じられないよ、おい。",
        "電気を消して寝なさい、子どもたち。",
        "地下鉄でスタジアムまで行こう。",
    ],
    "zh": [
        "你们饿了吗？我可以做点土豆泥。",
        "戴上太阳镜，外面太阳很大。",
        "嘿，你们俩买今晚的票了吗？",
        "你们都进来坐下吧。",
        "太酷了！我喜欢你的T恤。",
        "打辆出租车吧，我们在游泳池见。",
        "你们又迟到了。这次又怎么了？",
        "把外套拿上，天气开始变冷了。",
        "你们俩想和我们一起去超市吗？",
        "你居然没告诉我，真不敢相信，老兄。",
        "关灯睡觉，孩子们。",
        "我们坐地铁去体育场。",
    ],
    "ko": [
        "너희들 배고프니? 내가 으깬 감자 좀 만들어 줄게.",
        "선글라스 써, 밖에 해가 정말 쨍쨍해.",
        "저기, 너희 둘 오늘 밤 표 샀어?",
        "다들 들어와서 앉아.",
        "진짜 멋지다! 네 티셔츠 마음에 들어.",
        "택시 잡아, 수영장에서 만나자.",
        "너희들 또 늦었네. 이번엔 무슨 일이야?",
        "재킷 챙겨, 점점 추워지고 있어.",
        "너희 둘, 우리랑 같이 슈퍼마켓 갈래?",
        "나한테 말 안 했다니 믿을 수가 없어, 친구야.",
        "불 끄고 자, 얘들아.",
        "우리는 지하철을 타고 경기장에 갈 거야.",
    ],
}


def messages_for(variant: str, lang: str, source: str) -> list[dict[str, str]]:
    system = {"role": "system", "content": hymt2.SYSTEM_PROMPT}
    last = {"role": "user", "content": hymt2.TURN_TEMPLATE.format(text=source)}
    if variant == "prod":
        return hymt2.build_normal_messages(source, (), hymt2.select_glossary(source))
    if variant == "zero":
        return [system, last]
    if variant == "native":
        out = [system]
        for original, (_, target) in zip(FEWSHOT_NATIVE[lang], hymt2.FEWSHOT_ES_ES, strict=True):
            out.append({"role": "user", "content": hymt2.TURN_TEMPLATE.format(text=original)})
            out.append({"role": "assistant", "content": target})
        return [*out, last]
    raise ValueError(variant)


def strip_punct(text: str) -> str:
    """Quita la puntuación y los símbolos (deja los espacios internos) como un ASR sin puntuación."""
    out = "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c)[0] not in "PS")
    return " ".join(out.split())


def complete(client: httpx.Client, messages: list[dict[str, str]], max_tokens: int) -> dict:
    body = {
        "messages": messages,
        "temperature": hymt2.TEMPERATURE,
        "top_p": hymt2.TOP_P,
        "top_k": hymt2.TOP_K,
        "repeat_penalty": hymt2.REPEAT_PENALTY,
        "max_tokens": max_tokens,
        "seed": hymt2.SEED,
        "cache_prompt": True,
        "stream": False,
    }
    t0 = time.perf_counter()
    r = client.post(hymt2.CHAT_PATH, json=body)
    dt = time.perf_counter() - t0
    r.raise_for_status()
    data = r.json()
    ch = data["choices"][0]
    return {
        "text": (ch["message"].get("content") or "").strip(),
        "finish": ch.get("finish_reason"),
        "latency_s": dt,
        "completion_tokens": data.get("usage", {}).get("completion_tokens"),
        "prompt_tokens": data.get("usage", {}).get("prompt_tokens"),
    }


def source_texts(job_input: str, lang: str, items: list[dict]) -> list[str]:
    if job_input == "ref":
        return [it["ref"] for it in items]
    if job_input == "nopunct":
        return [strip_punct(it["ref"]) for it in items]
    if job_input.startswith("asr:"):
        data = json.loads((RESULTS_DIR / job_input[4:].split("@")[0]).read_text(encoding="utf-8"))
        cond = job_input.split("@")[1] if "@" in job_input else "clean"
        by_id = {x["id"]: x["hyp"] for x in data["conds"][cond]["items"]}
        return [by_id[it["id"]] for it in items]
    raise ValueError(job_input)


def chrf(hyps: list[str], refs: list[str]) -> float:
    from sacrebleu.metrics import CHRF

    return CHRF().corpus_score(hyps, [refs]).score


def run_job(client: httpx.Client, variant: str, lang: str, job_input: str, items: list[dict], max_tokens_mode: str) -> dict:
    sources = source_texts(job_input, lang, items)
    rows = []
    for it, src in zip(items, sources, strict=True):
        if not src.strip():
            rows.append({"id": it["id"], "source": src, "text": "", "finish": "vacío", "latency_s": 0.0, "reject": "vacía"})
            continue
        max_tokens = hymt2.max_tokens_for(src) if max_tokens_mode == "prod" else 256
        res = complete(client, messages_for(variant, lang, src), max_tokens)
        res["reject"] = hymt2.rejection_reason(src, res["text"], finish_reason=res["finish"])
        res.update({"id": it["id"], "source": src, "max_tokens": max_tokens})
        rows.append(res)
    lat = [r["latency_s"] for r in rows if r["latency_s"] > 0]
    refs = [it["ref_es"] for it in items]
    return {
        "variant": variant,
        "lang": lang,
        "input": job_input,
        "max_tokens_mode": max_tokens_mode,
        "chrf_vs_es419": chrf([r["text"] for r in rows], refs),
        "latency_p50_s": float(np.percentile(lat, 50)),
        "latency_p95_s": float(np.percentile(lat, 95)),
        "latency_max_s": float(np.max(lat)),
        "rejected": sum(1 for r in rows if r.get("reject")),
        "reject_reasons": {k: sum(1 for r in rows if r.get("reject") == k) for k in {r.get("reject") for r in rows if r.get("reject")}},
        "truncated": sum(1 for r in rows if r.get("finish") == "length"),
        "rows": rows,
    }


def write_md(lang: str, items: list[dict], res: dict) -> Path:
    names = {"ja": "japonés", "zh": "chino (mandarín)", "ko": "coreano"}
    by_id = {r["id"]: r for r in res["rows"]}
    path = SPIKE_DIR / f"traducciones_{lang}.md"
    lines = [
        f"# Traducciones {names[lang]} → español (Hy-MT2-7B Q4_K_M, prompt de producción)",
        "",
        "Para juzgar SC-002: marca cada fila como buena (mismo sentido que la referencia y español de España natural) o no. "
        "El original y las referencias son de FLEURS (CC BY 4.0); la referencia en español es **es_419** (latinoamericano), "
        "así que no usa «vosotros» ni el léxico peninsular. La traducción es del modelo, con el texto original (con su "
        "puntuación) como entrada.",
        "",
        f"Variante: `{res['variant']}`, entrada `{res['input']}`. Latencia por frase: p50 {res['latency_p50_s'] * 1000:.0f} ms, "
        f"p95 {res['latency_p95_s'] * 1000:.0f} ms. chrF contra es_419: {res['chrf_vs_es419']:.1f}. "
        f"Rechazadas por los filtros de salida de producción: {res['rejected']} de {len(items)}.",
        "",
        "| # | Original | Referencia es_419 | Referencia en inglés | Traducción | ¿Buena? |",
        "|---|---|---|---|---|---|",
    ]
    esc = lambda s: s.replace("|", "\\|").replace("\n", " ")  # noqa: E731
    for i, it in enumerate(items, 1):
        r = by_id[it["id"]]
        text = r["text"] + (f" **[rechazada: {r['reject']}]**" if r.get("reject") else "")
        lines.append(f"| {i} | {esc(it['ref'])} | {esc(it['ref_es'])} | {esc(it['ref_en'])} | {esc(text)} | |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", nargs="*", default=[], help="variante,idioma,entrada[,max_tokens], p. ej. prod,ja,ref (max_tokens: prod o free)")
    ap.add_argument("--all-variants", action="store_true", help="prod, native y zero con ref en ja, zh y ko")
    ap.add_argument("--md", action="store_true", help="escribe traducciones_<idioma>.md con la variante prod/ref")
    ap.add_argument("--out", default="translate")
    ap.add_argument("--n-ctx", type=int, default=4096)
    args = ap.parse_args()
    jobs = [j for j in (_parse(j) for j in args.jobs)]
    if args.all_variants:
        jobs += [(v, lg, "ref", "prod") for lg in ("ja", "zh", "ko") for v in ("prod", "native", "zero")]
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    server_dir = component_dir("llama-cpp")
    model = component_dir("hy-mt2-7b-q4") / "Hy-MT2-7B-Q4_K_M.gguf"
    results = []
    with gpu_lock() as waited:
        server = LlamaServer(server_dir=server_dir, model=model, n_ctx=args.n_ctx, extra_args=("--cache-ram", "0"))
        try:
            startup = server.start()
            print(f"llama-server listo en {startup:.1f} s (candado esperado {waited:.0f} s)", flush=True)
            client = httpx.Client(base_url=server.base_url, timeout=60.0, trust_env=False)
            complete(client, messages_for("prod", "ja", "テスト"), 64)  # calentamiento
            for variant, lang, job_input, mt_mode in jobs:
                items = manifest["phrases"][lang]["items"]
                t0 = time.time()
                res = run_job(client, variant, lang, job_input, items, mt_mode)
                res["gpu_wait_s"] = waited
                results.append(res)
                print(
                    f"[{variant} {lang} {job_input} {mt_mode}] chrF {res['chrf_vs_es419']:.1f}  p50/p95 "
                    f"{res['latency_p50_s'] * 1000:.0f}/{res['latency_p95_s'] * 1000:.0f} ms  rechazadas {res['rejected']} "
                    f"{res['reject_reasons']}  truncadas {res['truncated']}  ({time.time() - t0:.0f} s)",
                    flush=True,
                )
        finally:
            server.stop()
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"{args.out}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.md:
        for res in results:
            if res["variant"] == "prod" and res["input"] == "ref" and res["max_tokens_mode"] == "prod":
                print("md:", write_md(res["lang"], manifest["phrases"][res["lang"]]["items"], res))


def _parse(job: str) -> tuple[str, str, str, str]:
    parts = job.split(",")  # variante,idioma,entrada[,max_tokens]
    variant, lang, job_input = parts[0], parts[1], parts[2]
    return variant, lang, job_input, parts[3] if len(parts) > 3 else "prod"


if __name__ == "__main__":
    main()
