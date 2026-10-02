"""Banco de pruebas de «vosotros» con Hy-MT2-7B sobre llama-server (B0, B1, B2).

- Arranca `llama-server` (spikes/traduccion/llama_server.py, mismo binario y flags que S2 y producción) con el 7B
  Q4_K_M, SIEMPRE dentro de `gpu_lock()` (spikes/traduccion/gpu_lock.py), y lo cierra al terminar el lote.
- Traduce el corpus B0 (escenas, con el contexto que produce el propio modelo, como en la sesión) y el corpus S2
  (65 líneas + 10 adversariales, para comprobar que la calidad no empeora con `quality.py` de S2).
- Aplica los filtros de salida de producción (`rejection_reason`).

Uso:  uv run python mt_lab.py run --variants base,style_turn --seeds 42 [--corpora b0,s2] [--tag x]
Salidas en `%LOCALAPPDATA%\\InstantTraductor\\spikes\\habla_baja\\out\\mt\\<variante>_s<seed>.json`.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from common import APP_DIR, OUT_DIR

SPIKE_TRAD = Path(__file__).resolve().parents[1] / "traduccion"
sys.path.insert(0, str(SPIKE_TRAD))

import corpus as s2corpus  # noqa: E402
import quality as s2quality  # noqa: E402
from gpu_lock import gpu_lock  # noqa: E402
from llama_server import LlamaServer  # noqa: E402

import corpus_b0  # noqa: E402
import detector  # noqa: E402
from instanttraductor.contracts import GlossaryEntry  # noqa: E402
from instanttraductor.mt.hymt2 import (  # noqa: E402
    REPEAT_PENALTY,
    TEMPERATURE,
    TOP_K,
    TOP_P,
    max_tokens_for,
    rejection_reason,
    select_glossary,
)
from prompts_b1 import VARIANTS  # noqa: E402

MODEL_7B = APP_DIR / "models" / "hy-mt2-7b-q4" / "Hy-MT2-7B-Q4_K_M.gguf"
MT_DIR = OUT_DIR / "mt"
MT_DIR.mkdir(parents=True, exist_ok=True)
CONTEXT_PAIRS = 4


class Client:
    """Cliente mínimo de /v1/chat/completions con las mismas opciones de muestreo que producción."""

    def __init__(self, base_url: str) -> None:
        self._c = httpx.Client(
            base_url=base_url,
            timeout=30.0,
            transport=httpx.HTTPTransport(socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]),
            trust_env=False,
        )

    def complete(
        self, messages: list[dict], max_tokens: int, seed: int, *, logit_bias: Any = None, cache: bool = True
    ) -> tuple[str, str | None, float, dict]:
        body: dict[str, Any] = {
            "messages": messages,
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "top_k": TOP_K,
            "repeat_penalty": REPEAT_PENALTY,
            "max_tokens": max_tokens,
            "seed": seed,
            "cache_prompt": cache,
            "stream": False,
        }
        if logit_bias is not None:
            body["logit_bias"] = logit_bias
        t0 = time.perf_counter()
        r = self._c.post("/v1/chat/completions", json=body)
        dt = (time.perf_counter() - t0) * 1000
        r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]
        return (choice["message"].get("content") or ""), choice.get("finish_reason"), dt, data.get("timings", {})


_NOTE_ECHO = re.compile(r"\n\s*\n\s*[\(\[].*$", re.DOTALL)


def clean_output(text: str) -> str:
    """Quita la nota de estilo que el modelo a veces repite tras la traducción (salto doble y paréntesis)."""
    return _NOTE_ECHO.sub("", text).strip()


def translate_line(
    client: Client, build, source: str, context: list[tuple[str, str]], glossary: list[GlossaryEntry], concise: bool, seed: int
) -> dict:
    messages = build(source, context, glossary, concise)
    try:
        out, finish, ms, timings = client.complete(messages, max_tokens_for(source), seed)
        out = clean_output(out)
        reason = rejection_reason(source, out, finish_reason=finish)
    except httpx.HTTPStatusError as err:  # p. ej. el prompt no cabe en el contexto del servidor
        return {"text": "", "raw": "", "rejected": f"http {err.response.status_code}", "ms": 0.0, "prompt_n": None, "cache_n": None}
    return {
        "text": "" if reason else out.strip(),
        "raw": out.strip(),
        "rejected": reason,
        "ms": ms,
        "prompt_n": timings.get("prompt_n"),
        "cache_n": timings.get("cache_n"),
    }


def run_b0(client: Client, variant: str, seed: int, *, concise: bool = False, sanitize=None) -> list[dict]:
    """Traduce las 228 líneas de B0 escena a escena (el contexto son las últimas traducciones del modelo)."""
    build = VARIANTS[variant]
    results: list[dict] = []
    by_scene: dict[int, list[corpus_b0.Line]] = {}
    for line in corpus_b0.LINES:
        by_scene.setdefault(line.scene, []).append(line)
    for scene, lines in by_scene.items():
        history: list[tuple[str, str]] = []
        for line in lines:
            ctx = history[-CONTEXT_PAIRS:]
            if sanitize is not None:
                ctx = [(o, sanitize(o, t)) for o, t in ctx]
            rec = translate_line(client, build, line.text, ctx, [], concise, seed)
            rec.update(
                {
                    "idx": line.idx,
                    "scene": scene,
                    "label": line.label,
                    "kind": line.kind,
                    "marked": line.marked,
                    "source": line.text,
                    "primary": detector.primary(rec["text"], line.text),
                    "marks": sorted(detector.classify(rec["text"], line.text)),
                }
            )
            results.append(rec)
            if rec["text"]:
                history.append((line.text, rec["text"]))
    return results


def run_s2(client: Client, variant: str, seed: int, *, concise: bool = False, sanitize=None) -> dict:
    """Traduce el corpus S2 (65 líneas con contexto y glosario + 10 adversariales sin contexto) y lo puntúa."""
    build = VARIANTS[variant]
    user_glossary = [GlossaryEntry(s, t) for s, t in s2corpus.GLOSSARY]
    results: list[tuple[s2corpus.Line, dict]] = []
    records: list[dict] = []
    by_scene: dict[str, list[s2corpus.Line]] = {}
    for line in s2corpus.LINES:
        by_scene.setdefault(line.scene, []).append(line)
    for lines in by_scene.values():
        history: list[tuple[str, str]] = []
        for line in lines:
            ctx = history[-CONTEXT_PAIRS:]
            if sanitize is not None:
                ctx = [(o, sanitize(o, t)) for o, t in ctx]
            glossary = [] if concise else list(select_glossary(line.text, user_glossary))
            rec = translate_line(client, build, line.text, ctx, glossary, concise, seed)
            results.append((line, s2quality.check_output(line, rec["raw"] or "")))
            rec.update({"id": line.id, "source": line.text})
            records.append(rec)
            if rec["text"]:
                history.append((line.text, rec["text"]))
    adv: list[tuple[s2corpus.Line, dict]] = []
    for line in s2corpus.ADVERSARIAL:
        rec = translate_line(client, build, line.text, [], [], concise, seed)
        adv.append((line, s2quality.check_output(line, rec["raw"] or "")))
        rec.update({"id": line.id, "source": line.text})
        records.append(rec)
    return {
        "summary": s2quality.summarize_checks(results),
        "adversarial_trap_fail": sum(1 for _l, r in adv if r["trap_fail"]),
        "rejected": sum(1 for r in records if r["rejected"]),
        "records": records,
    }


def summarize_b0(results: list[dict]) -> dict:
    """Tasas sobre B0: P (vosotros/ustedes/tú/neutral), daño en S/F/T, latencia."""
    out: dict[str, Any] = {"n": len(results)}
    for label in ("P", "S", "F", "T"):
        rs = [r for r in results if r["label"] == label]
        c = Counter(r["primary"] for r in rs)
        out[label] = {"n": len(rs), **{k: c.get(k, 0) for k in ("vos", "ust", "tu", "usted", "neu")}, "rejected": sum(1 for r in rs if r["rejected"])}
    p = [r for r in results if r["label"] == "P"]
    out["P_by_kind"] = {
        k: {"n": sum(1 for r in p if r["kind"] == k), "vos": sum(1 for r in p if r["kind"] == k and r["primary"] == "vos")}
        for k in ("imp", "neg", "q", "st")
    }
    out["P_marked"] = {
        "n": sum(1 for r in p if r["marked"]),
        "vos": sum(1 for r in p if r["marked"] and r["primary"] == "vos"),
    }
    out["P_unmarked"] = {
        "n": sum(1 for r in p if not r["marked"]),
        "vos": sum(1 for r in p if not r["marked"] and r["primary"] == "vos"),
    }
    ms = sorted(r["ms"] for r in results)
    out["ms_p50"] = ms[len(ms) // 2]
    out["ms_p95"] = ms[int(len(ms) * 0.95)]
    out["prompt_n_mean"] = sum((r["prompt_n"] or 0) + (r["cache_n"] or 0) for r in results) / len(results)
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (100 * (c - h), 100 * (c + h))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--variants", required=True)
    r.add_argument("--seeds", default="42")
    r.add_argument("--corpora", default="b0,s2")
    r.add_argument("--concise", action="store_true")
    r.add_argument("--sanitize", action="store_true", help="contexto saneado con la posedición por reglas (B2)")
    r.add_argument("--tag", default="")
    r.add_argument("--ctx", type=int, default=8192, help="contexto del servidor (producción: 4096)")
    args = ap.parse_args()

    sanitize = None
    if args.sanitize:
        from postedit import postedit_for_context

        sanitize = postedit_for_context
    variants = args.variants.split(",")
    seeds = [int(s) for s in args.seeds.split(",")]
    corpora = args.corpora.split(",")
    with gpu_lock():
        server = LlamaServer(model=MODEL_7B, n_ctx=args.ctx, extra_args=("--cache-ram", "0"), log_path=OUT_DIR / "llama_server.log")
        try:
            print(f"llama-server listo en {server.start():.1f} s", flush=True)
            client = Client(server.base_url)
            for variant in variants:
                for seed in seeds:
                    name = f"{variant}{'_concise' if args.concise else ''}{'_san' if args.sanitize else ''}{args.tag}_s{seed}"
                    rec: dict[str, Any] = {"variant": variant, "seed": seed, "concise": args.concise}
                    t = time.perf_counter()
                    if "b0" in corpora:
                        b0 = run_b0(client, variant, seed, concise=args.concise, sanitize=sanitize)
                        rec["b0"] = {"summary": summarize_b0(b0), "records": b0}
                    if "s2" in corpora:
                        rec["s2"] = run_s2(client, variant, seed, concise=args.concise, sanitize=sanitize)
                    (MT_DIR / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=0), "utf-8")
                    s = rec.get("b0", {}).get("summary", {})
                    print(f"{name}: {time.perf_counter() - t:.0f} s  P={s.get('P')}  S={s.get('S')}  T={s.get('T')}", flush=True)
        finally:
            server.stop()


if __name__ == "__main__":
    main()
