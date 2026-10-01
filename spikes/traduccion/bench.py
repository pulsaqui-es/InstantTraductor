"""Benchmark del spike S2: Hy-MT2-1.8B (GGUF Q8_0) servido por llama-server en la RTX 5070.

Mide, todo DENTRO del candado de GPU:

- tiempo de arranque del servidor (varios arranques) y de la primera petición;
- latencia por frase (petición completa y tiempo hasta el primer token), p50/p95;
- tokens por segundo (generación y *prefill*);
- VRAM (``nvidia-smi`` y contador de Windows por proceso);
- las 65 traducciones con el prompt final y con varias ablaciones, para revisión humana;
- una prueba de robustez con frases que suenan a órdenes al asistente.

Uso::

    uv run python bench.py            # medición completa (unos 4-6 minutos)
    uv run python bench.py --quick    # prueba de humo reducida
    uv run python bench.py --report   # solo regenera los informes desde metricas.json (sin GPU)
    uv run python bench.py --quick --model <gguf> --tag _7b   # otro modelo, ficheros con sufijo

Escribe en ``resultados/``: ``metricas.json``, ``traducciones.md``,
``comparativa_configs.md`` y ``tablas.md``.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import re
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import httpx

import download
import gpu_info
from client import OFFICIAL_SAMPLING, Translator, summarize
from corpus import ADVERSARIAL, BY_ID, GLOSSARY, LINES, SCENES, count_words
from gpu_lock import gpu_lock
from llama_server import LLAMA_BUILD, LlamaServer
from pipeline import N_PAIRS, glossary_for, history_for, max_tokens_for, run_pass
from prompts import (
    FEWSHOT_ES_ES,
    STYLE_EN,
    STYLE_ZH,
    PromptConfig,
    build_messages,
    final_config,
    messages_to_text,
)
from quality import check_output, summarize_checks

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "resultados"

FINAL_CFG = final_config()
FINAL = FINAL_CFG.name

#: Variantes que se comparan: de las plantillas oficiales sueltas al prompt final.
CONFIGS: tuple[PromptConfig, ...] = (
    # Plantilla «Default Translation» oficial, sin nada más.
    PromptConfig("baseline", default_template=True),
    # Las tres plantillas oficiales en inglés (contexto + terminología + estilo) en un mensaje.
    PromptConfig("official_en", layout="composed", bg_format="pairs", style=STYLE_EN,
                 context=True, glossary=True),
    # Las mismas plantillas oficiales, pero en chino (el idioma nativo del modelo).
    PromptConfig("official_zh", layout="zh", bg_format="english", style=STYLE_ZH,
                 context=True, glossary=True),
    # Construcción del prompt final pieza a pieza.
    replace(FINAL_CFG, name="sys_style", fewshot=(), context=False, glossary=False),
    replace(FINAL_CFG, name="sys_fewshot", context=False, glossary=False),
    replace(FINAL_CFG, name="sys_fewshot_ctx", glossary=False),
    FINAL_CFG,
    # Ablaciones y variantes del prompt final.
    replace(FINAL_CFG, name="final_nofewshot", fewshot=()),
    replace(FINAL_CFG, name="final_fewshot6", fewshot=FEWSHOT_ES_ES),
    replace(FINAL_CFG, name="final_raw_turns", wrap_turns=False),
    replace(FINAL_CFG, name="final_t02", temperature=0.2),
    replace(FINAL_CFG, name="final_lexicon", lexicon=True),
)
CFG_BY_NAME = {c.name: c for c in CONFIGS}

SCENE_TITLES = {
    "S01": "Cocina, hermanos",
    "S02": "Comisaría",
    "S03": "Saliendo del cine",
    "S04": "Hospital",
    "S05": "Nave espacial",
    "S06": "Taberna de fantasía",
    "S07": "Oficina",
    "S08": "Viaje en coche",
    "S09": "Concurso de la tele",
    "S10": "Atraco",
    "S11": "Saga inventada (glosario)",
}

STRUCT_FLAGS = ("multiline", "truncated", "label_prefix", "boilerplate", "wrapped", "cjk", "empty")


# ---------------------------------------------------------------------------
# Estadísticas
# ---------------------------------------------------------------------------
def _bucket(line_id: int) -> str:
    n = count_words(BY_ID[line_id].text)
    return "short" if n <= 5 else ("medium" if n <= 14 else "long")


def stats_block(records: list[dict], *, stream: bool) -> dict:
    """Latencia, primer token, tokens/s y tamaños de un conjunto de peticiones."""
    total = [r["total_ms"] for r in records]
    with_server = [r for r in records if r["server_predicted_ms"] is not None]
    server_ms = [(r["server_prompt_ms"] or 0.0) + r["server_predicted_ms"] for r in with_server]
    overhead = [r["total_ms"] - s for r, s in zip(with_server, server_ms, strict=True)]
    tokens = sum(r["completion_tokens"] for r in records)
    decode_ms = sum(r["server_predicted_ms"] or 0.0 for r in records)
    prompt_tok = sum(r["prompt_tokens"] for r in records)
    prompt_ms = sum(r["server_prompt_ms"] or 0.0 for r in records)
    out: dict = {
        "n": len(records),
        "total_ms": summarize(total),
        "share_under_300ms": sum(1 for t in total if t <= 300) / max(1, len(total)),
        "share_under_500ms": sum(1 for t in total if t <= 500) / max(1, len(total)),
        "server_ms": summarize(server_ms),
        "client_overhead_ms": summarize(overhead),
        "decode_tps": summarize([r["decode_tps"] for r in records if r["decode_tps"]]),
        "decode_tps_aggregate": (1000.0 * tokens / decode_ms) if decode_ms else None,
        "prefill_tps": summarize([r["prefill_tps"] for r in records if r["prefill_tps"]]),
        "prefill_tps_aggregate": (1000.0 * prompt_tok / prompt_ms) if prompt_ms else None,
        "prompt_tokens": summarize([r["prompt_tokens"] for r in records]),
        "completion_tokens": summarize([r["completion_tokens"] for r in records]),
        "by_length": {
            b: summarize([r["total_ms"] for r in records if _bucket(r["line_id"]) == b])
            for b in ("short", "medium", "long")
        },
    }
    if stream:
        out["ttft_ms"] = summarize([r["ttft_ms"] for r in records if r["ttft_ms"] is not None])
        out["by_length_ttft"] = {
            b: summarize(
                [r["ttft_ms"] for r in records if r["ttft_ms"] is not None and _bucket(r["line_id"]) == b]
            )
            for b in ("short", "medium", "long")
        }
    return out


def quality_of(records: list[dict]) -> tuple[dict, list[dict]]:
    """Comprobaciones automáticas de calidad de una pasada + detalle por línea."""
    pairs = []
    detail = []
    for rec in records:
        line = BY_ID[rec["line_id"]]
        res = check_output(line, rec["output"], rec["finish_reason"])
        pairs.append((line, res))
        detail.append({"line_id": line.id, **res})
    summary = summarize_checks(pairs)
    summary["struct_fail"] = sum(1 for _l, r in pairs if any(r["flags"][k] for k in STRUCT_FLAGS))
    return summary, detail


# ---------------------------------------------------------------------------
# Medición en GPU (todo dentro del candado)
# ---------------------------------------------------------------------------
#: SHA-256 de otros modelos que se han usado con este arnés (verificados al descargarlos).
KNOWN_SHA256 = {
    "Hy-MT2-7B-Q4_K_M.gguf": "9f96256500f3fc1ab4d64336b58f52a949a95ad7516b0c229476eef782f9f77b",
}


def _server(args: argparse.Namespace, **kw) -> LlamaServer:
    """``LlamaServer`` con el modelo elegido en la línea de comandos (por defecto, el 1,8B Q8_0)."""
    if args.model:
        kw["model"] = Path(args.model)
    return LlamaServer(**kw)


def measure(args: argparse.Namespace) -> dict:
    RESULTS.mkdir(parents=True, exist_ok=True)
    data: dict = {"configs": {}, "latency": {}}

    with gpu_lock() as waited:
        data["lock_wait_s"] = waited
        snap = gpu_info.gpu_snapshot()
        data["gpu_before"] = snap
        data["vram_base_mib"] = gpu_info.vram_used_mib()
        print(f"[bench] GPU: {snap['name']} | driver {snap['driver_version']} | "
              f"VRAM base {data['vram_base_mib']} MiB | pstate {snap['pstate']}", flush=True)

        # 0) Arranque de diagnóstico con -lv 4: detalle de carga (no cuenta en las medias).
        diag = _server(args, log_path=RESULTS / "llama-server-diagnostico.log", extra_args=("-lv", "4"))
        try:
            diag.start()
            data["server_log"] = parse_diag_log(diag.log_text())
        finally:
            diag.stop()
        gpu_info.settle()

        # 1) Varios arranques: tiempo hasta /health=200 y hasta la primera traducción.
        startups: list[dict] = []
        srv: LlamaServer | None = None
        try:
            for i in range(args.startups):
                srv = _server(args, log_path=RESULTS / "llama-server.log")
                before = gpu_info.vram_used_mib()
                t_ready = srv.start()
                loaded = gpu_info.vram_used_mib()
                with Translator(srv.base_url) as tr:
                    first = tr.complete(
                        messages_to_text(build_messages(LINES[0].text, CFG_BY_NAME["baseline"])),
                        stream=False, max_tokens=96,
                    )
                startups.append({
                    "run": i + 1,
                    "ready_s": t_ready,
                    "first_request_ms": first.total_ms,
                    "ready_plus_first_s": t_ready + first.total_ms / 1000,
                    "vram_before_mib": before,
                    "vram_loaded_mib": loaded,
                    "job_object": srv.job_assigned,
                })
                print(f"[bench] arranque {i + 1}/{args.startups}: listo en {t_ready:.2f} s; "
                      f"primera petición {first.total_ms:.0f} ms; VRAM {before} -> {loaded} MiB", flush=True)
                if i < args.startups - 1:
                    pid = srv.pid
                    srv.stop()
                    gpu_info.settle()
                    startups[-1]["vram_after_stop_mib"] = gpu_info.vram_used_mib()
                    startups[-1]["process_gone"] = not gpu_info.process_exists(pid)
            data["startup"] = startups
            assert srv is not None

            # 2) Servidor de medición: estado en reposo y calentamiento.
            pid = srv.pid
            data["server_pid"] = pid
            data["props"] = slim_props(srv.props())
            data["idle_after_load"] = {
                "vram_used_mib": gpu_info.vram_used_mib(),
                "process_vram_mib": gpu_info.process_vram_mib(pid),
                "working_set_mib": gpu_info.process_working_set_mib(pid),
                "gpu": gpu_info.gpu_snapshot(),
            }
            with Translator(srv.base_url) as tr:
                for line in LINES[:3]:  # calentamiento (no se registra)
                    tr.complete(build_messages(line.text, FINAL_CFG), stream=True, max_tokens=96)

                # 3) Una pasada en streaming por variante de prompt (contexto propio).
                names = ("baseline", FINAL) if args.quick else [c.name for c in CONFIGS]
                for name in names:
                    recs = run_pass(tr, LINES, CFG_BY_NAME[name], stream=True)
                    data["configs"][name] = {"records": recs}
                    p50 = summarize([r["total_ms"] for r in recs])["p50"]
                    print(f"[bench] config {name:<16} {len(recs)} líneas; total p50 {p50:.0f} ms", flush=True)
                frozen = {r["line_id"]: r["output"] for r in data["configs"][FINAL]["records"]}

                # 4) Latencia del prompt final: pasadas alternas streaming / completa, con
                #    prompts idénticos (contexto congelado) y peticiones seguidas.
                stream_recs: list[dict] = []
                full_recs: list[dict] = []
                for k in range(args.latency_passes):
                    stream_recs += run_pass(tr, LINES, FINAL_CFG, stream=True, frozen=frozen)
                    full_recs += run_pass(tr, LINES, FINAL_CFG, stream=False, frozen=frozen)
                    print(f"[bench] pasada de latencia {k + 1}/{args.latency_passes}", flush=True)
                data["latency"]["stream_back_to_back"] = {"records": stream_recs}
                data["latency"]["full_back_to_back"] = {"records": full_recs}

                # 5) Con caché de prompt (el prefijo con los ejemplos es siempre el mismo).
                cached = run_pass(tr, LINES, FINAL_CFG, stream=True, frozen=frozen, cache_prompt=True)
                cached = run_pass(tr, LINES, FINAL_CFG, stream=True, frozen=frozen, cache_prompt=True)
                data["latency"]["stream_cached"] = {"records": cached}
                print("[bench] pasada con caché de prompt", flush=True)

                # 6) Ritmo realista: una petición cada ``pace`` s (la GPU baja de reloj entre medias).
                if not args.quick:
                    paced = run_pass(tr, LINES, FINAL_CFG, stream=True, frozen=frozen, pace_s=args.pace)
                    data["latency"]["stream_paced"] = {"records": paced, "pace_s": args.pace}
                    print(f"[bench] pasada con ritmo de {args.pace} s entre peticiones", flush=True)

                # 7) Peor caso: 5 pares de contexto + glosario completo, con muestreo de VRAM.
                sampler = gpu_info.VramSampler(interval=0.25)
                sampler.start()
                stress = run_pass(tr, LINES, FINAL_CFG, stream=True, frozen=frozen,
                                  n_pairs=5, glossary_mode="all")
                data["latency"]["stress"] = {"records": stress, "vram_sampling": sampler.stop()}
                print("[bench] prueba de peor caso (5 pares + glosario completo)", flush=True)

                # 8) Robustez: frases que suenan a órdenes o preguntas al asistente.
                data["robustness"] = {"records": run_adversarial(tr)}
                print("[bench] prueba de robustez (frases adversariales)", flush=True)

            data["after_passes"] = {
                "vram_used_mib": gpu_info.vram_used_mib(),
                "process_vram_mib": gpu_info.process_vram_mib(pid),
                "working_set_mib": gpu_info.process_working_set_mib(pid),
                "gpu": gpu_info.gpu_snapshot(),
            }
            data["example"] = example_prompts(srv, frozen)
        finally:
            if srv is not None:
                pid = srv.pid
                srv.stop()
                gpu_info.settle(1.0)
                data["after_stop"] = {
                    "vram_used_mib": gpu_info.vram_used_mib(),
                    "process_gone": (not gpu_info.process_exists(pid)) if pid else True,
                }
    return data


def run_adversarial(tr: Translator) -> list[dict]:
    """Traduce las frases adversariales con el prompt final, sin contexto ni glosario."""
    out = []
    for line in ADVERSARIAL:
        messages = build_messages(line.text, FINAL_CFG, (), ())
        res = tr.complete(messages, stream=True, max_tokens=max_tokens_for(line.text), seed=42)
        out.append({"line_id": line.id, "source": line.text, "output": res.text.strip(),
                    "finish_reason": res.finish_reason, "total_ms": res.total_ms})
    return out


def parse_diag_log(text: str) -> dict:
    """Líneas relevantes del registro de arranque detallado (``-lv 4``)."""
    wanted = (
        "build ", "device_info", "- CUDA", "- CPU", "system_info", "print_info: arch",
        "print_info: file type", "print_info: file size", "print_info: model type",
        "print_info: model params", "print_info: n_layer ", "print_info: n_ctx_train",
        "offloaded", "buffer size", "llama_context: n_ctx ", "llama_context: n_batch",
        "llama_context: n_ubatch", "llama_context: flash_attn", "Flash Attention enabled",
        "n_slots", "thinking =", "load_tensors: loading model tensors",
    )
    lines = []
    for line in text.splitlines():
        if any(w in line for w in wanted) or re.search(r"\sW\s", line[:40]):
            lines.append(re.sub(r"^\d+\.\d+\.\d+\.\d+\s+", "", line).strip())
    buffers = []
    for m in re.finditer(
        r"(\S+)\s+(model|KV|compute|output)\s+buffer size\s*=\s*([\d.]+)\s*MiB", text
    ):
        buffers.append({"device": m[1], "kind": m[2], "mib": float(m[3])})
    return {"lines": lines, "buffers": buffers}


def slim_props(props: dict) -> dict:
    """Subconjunto estable y útil de ``/props``."""
    keep = ("total_slots", "model_path", "bos_token", "eos_token", "build_info", "chat_template")
    return {k: props.get(k) for k in keep}


def example_prompts(srv: LlamaServer, frozen: dict[int, str]) -> dict:
    """Prompt final de dos frases de ejemplo (sin y con glosario) y su forma renderizada."""
    out = {}
    for lid in (16, 62):
        idx = next(i for i, ln in enumerate(LINES) if ln.id == lid)
        history = history_for(LINES, idx, frozen, N_PAIRS)
        glossary = glossary_for(LINES[idx].text, history)
        messages = build_messages(LINES[idx].text, FINAL_CFG, history, glossary)
        out[str(lid)] = {
            "messages": messages,
            "rendered": srv.apply_template(messages),
        }
    return out


# ---------------------------------------------------------------------------
# Informes
# ---------------------------------------------------------------------------
def fmt(x: float | None, nd: int = 0) -> str:
    if x is None:
        return "—"
    return f"{x:.{nd}f}".replace(".", ",")


def environment(data: dict, args: argparse.Namespace) -> dict:
    """Versiones y entorno exactos para el README y el JSON."""
    if args.model:
        path = Path(args.model)
        model = {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": KNOWN_SHA256.get(path.name),
            "source": "ruta local indicada con --model",
        }
    else:
        model = {
            "file": download.MODEL.name,
            "bytes": download.MODEL.size,
            "sha256": download.MODEL.sha256,
            "source": download.MODEL.url,
        }
    server_log = data.get("server_log", {}).get("lines", [])
    cpu = next((re.sub(r"^.*- CPU\s*:\s*", "", ln) for ln in server_log if "- CPU" in ln), None)
    smi = gpu_info._run(["nvidia-smi"])  # noqa: SLF001
    cuda = re.search(r"CUDA (?:UMD )?Version:\s*([\d.]+)", smi)
    return {
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "httpx": httpx.__version__,
        "filelock": importlib.metadata.version("filelock"),
        "gpu": data["gpu_before"]["name"],
        "driver": data["gpu_before"]["driver_version"],
        "cuda_driver_api": cuda.group(1) if cuda else None,
        "cpu": cpu.strip() if cpu else None,
        "llama_cpp": {
            "release": download.LLAMA_RELEASE,
            "build": LLAMA_BUILD,
            "build_info": data["props"].get("build_info"),
            "zips": [a.name for a in download.LLAMA_ASSETS],
        },
        "model": model,
        "server_args": f"-m {model['file']} --host 127.0.0.1 --port <libre> -ngl 99 -c 4096 -np 1 -fit off --no-webui",
        "sampling": {**OFFICIAL_SAMPLING, "seed": 42, "cache_prompt": False},
        "context_pairs": N_PAIRS,
    }


def write_translations(data: dict, path: Path) -> None:
    """``traducciones.md``: tabla inglés | español del prompt final."""
    recs = data["configs"][FINAL]["records"]
    _summary, detail = quality_of(recs)
    by_id = {r["line_id"]: r for r in recs}
    det = {d["line_id"]: d for d in detail}
    lines = [
        f"# Traducciones de la prueba S2 ({data['env']['model']['file']}, prompt final)",
        "",
        "- Configuración: `final` = mensaje de sistema con el estilo + 12 ejemplos previos de español de "
        f"España + las {N_PAIRS} frases anteriores de la escena como turnos de chat (cada turno de "
        "usuario lleva la instrucción de traducir) + glosario con la plantilla oficial «Terminology» "
        "en chino (ver README, «Método»).",
        "- Muestreo: temperatura 0,7, top_p 0,6, top_k 20, penalización de repetición 1,05, semilla 42.",
        f"- Modelo y servidor: `{data['env']['model']['file']}`, llama.cpp {download.LLAMA_RELEASE} (build {LLAMA_BUILD}).",
        f"- Fecha de la medición: {data['env']['date']}.",
        "",
        "Las traducciones NO están corregidas: son la salida tal cual del modelo, para revisión humana. "
        "La columna «Avisos» recoge lo que detectan las heurísticas automáticas (ver README); una "
        "línea sin avisos no garantiza que la traducción sea buena.",
        "",
        "Significado de los avisos: `léxico:X` = NO se cumple la comprobación de vocabulario de España «X» "
        "(falta el término peninsular o aparece uno no peninsular); `plural:ustedes` o `plural:neutral` = "
        "frase dirigida a varias personas sin «vosotros»; `glosario:T` = falta el término T del glosario; "
        "el resto (`multiline`, `boilerplate`, `truncated`…) son fallos de estructura.",
        "",
        "| Nº | Escena | Inglés | Español | Avisos |",
        "|---:|:---|:---|:---|:---|",
    ]
    for line in LINES:
        rec = by_id[line.id]
        d = det[line.id]
        notes = [k for k, v in d["flags"].items() if v and k in (
            "boilerplate", "label_prefix", "multiline", "wrapped", "cjk", "english_leak",
            "not_spanish", "copied_source", "truncated", "question_lost", "len_ratio_flag")]
        notes += [f"léxico:{c['label']}" for c in d["checks"] if not c["ok"]]
        if d["plural_you"] in ("ustedes", "neutral"):
            notes.append(f"plural:{d['plural_you']}")
        notes += [f"glosario:{g['expected']}" for g in d["glossary"] if not g["ok"]]
        es = rec["output"].replace("|", "\\|").replace("\n", " ⏎ ")
        en = line.text.replace("|", "\\|")
        lines.append(f"| {line.id} | {line.scene} | {en} | {es} | {', '.join(notes)} |")
    lines += ["", "## Escenas", ""]
    for scene in SCENES:
        ids = [ln.id for ln in LINES if ln.scene == scene]
        lines.append(f"- **{scene}** ({SCENE_TITLES[scene]}): líneas {ids[0]}–{ids[-1]}")
    lines += ["", "## Glosario usado", "", "| Término (inglés) | Traducción obligatoria |", "|:---|:---|"]
    lines += [f"| {s} | {t} |" for s, t in GLOSSARY]
    lines += [
        "",
        "El glosario solo se inyecta en el prompt cuando el término aparece en la frase o en el "
        "contexto previo. Las líneas 61–65 son las cinco con términos inventados.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_comparison(data: dict, path: Path) -> None:
    """``comparativa_configs.md``: la salida de cada variante de prompt, línea a línea."""
    names = list(data["configs"])
    out = [
        "# Comparativa de variantes de prompt (misma semilla, una pasada cada una)",
        "",
        "Variantes: " + ", ".join(f"`{n}`" for n in names) + ".",
        "",
    ]
    by_cfg = {n: {r["line_id"]: r for r in data["configs"][n]["records"]} for n in names}
    for line in LINES:
        out.append(f"### {line.id} · {line.scene} · {line.text}")
        out.append("")
        for n in names:
            txt = by_cfg[n][line.id]["output"].replace("\n", " ⏎ ")
            out.append(f"- `{n}`: {txt}")
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


def analyse(data: dict) -> dict:
    """Calcula estadísticas y calidad a partir de los registros crudos."""
    out: dict = {"configs": {}, "latency": {}}
    for name, blob in data["configs"].items():
        recs = blob["records"]
        qsum, qdet = quality_of(recs)
        out["configs"][name] = {
            "latency": stats_block(recs, stream=True),
            "quality": qsum,
            "quality_detail": qdet,
        }
    for name, blob in data["latency"].items():
        recs = blob["records"]
        out["latency"][name] = stats_block(recs, stream=recs[0]["stream"])
    # Determinismo: ¿las pasadas de latencia reproducen la traducción de la pasada 1?
    first = {r["line_id"]: r["output"] for r in data["configs"][FINAL]["records"]}
    for key in ("stream_back_to_back", "full_back_to_back", "stream_cached"):
        recs = data["latency"][key]["records"]
        same = sum(1 for r in recs if r["output"] == first[r["line_id"]])
        out["latency"][key]["identical_to_first_pass"] = {"same": same, "total": len(recs)}
    rob = []
    by_id = {ln.id: ln for ln in ADVERSARIAL}
    for rec in data["robustness"]["records"]:
        res = check_output(by_id[rec["line_id"]], rec["output"], rec["finish_reason"])
        rob.append({"line_id": rec["line_id"], "trap_fail": res["trap_fail"],
                    "non_translation": res["non_translation"], "checks": res["checks"]})
    out["robustness"] = rob
    return out


def write_tables(data: dict, path: Path) -> None:
    """``tablas.md``: las cifras principales en Markdown, tal como salen de la medición."""
    a = data["analysis"]
    rows: list[str] = []

    rows += ["## Arranque del servidor", "",
             "| Arranque | Listo (`/health` = 200), s | Primera petición, ms | Listo + primera petición, s |",
             "|---:|---:|---:|---:|"]
    for s in data["startup"]:
        rows.append(f"| {s['run']} | {fmt(s['ready_s'], 2)} | {fmt(s['first_request_ms'])} | {fmt(s['ready_plus_first_s'], 2)} |")
    ready = [s["ready_s"] for s in data["startup"]]
    rows.append(f"| **mediana** | **{fmt(summarize(ready)['p50'], 2)}** | "
                f"**{fmt(summarize([s['first_request_ms'] for s in data['startup']])['p50'])}** | |")

    rows += ["", "## Latencia por frase (prompt final, 65 líneas)", "",
             "| Modo | n | Total p50, ms | Total p95, ms | Total media, ms | 1.er token p50, ms | 1.er token p95, ms | ≤300 ms | Tokens/s (gen., mediana) | Tokens/s (prefill, mediana) | Tokens de prompt p50/máx |",
             "|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    names = {
        "stream_back_to_back": "Streaming, peticiones seguidas",
        "full_back_to_back": "Petición completa (sin streaming), seguidas",
        "stream_cached": "Streaming, con caché de prompt",
        "stream_paced": "Streaming, con pausa entre peticiones",
        "stress": "Streaming, peor caso (5 pares + glosario completo)",
    }
    for key, label in names.items():
        if key not in a["latency"]:
            continue
        s = a["latency"][key]
        ttft = s.get("ttft_ms")
        rows.append(
            f"| {label} | {s['n']} | {fmt(s['total_ms']['p50'])} | {fmt(s['total_ms']['p95'])} | "
            f"{fmt(s['total_ms']['mean'])} | {fmt(ttft['p50']) if ttft else '—'} | "
            f"{fmt(ttft['p95']) if ttft else '—'} | {s['share_under_300ms']:.0%} | "
            f"{fmt(s['decode_tps']['p50'])} | {fmt(s['prefill_tps']['p50'])} | "
            f"{fmt(s['prompt_tokens']['p50'])} / {fmt(s['prompt_tokens']['max'])} |"
        )

    rows += ["", "### Latencia por longitud de la frase (streaming, peticiones seguidas)", "",
             "| Frase | Total p50, ms | Total p95, ms | 1.er token p50, ms |", "|:---|---:|---:|---:|"]
    s = a["latency"]["stream_back_to_back"]
    for b, label in (("short", "corta (≤5 palabras)"), ("medium", "media (6–14)"), ("long", "larga (≥15)")):
        rows.append(f"| {label} | {fmt(s['by_length'][b]['p50'])} | {fmt(s['by_length'][b]['p95'])} | "
                    f"{fmt(s['by_length_ttft'][b]['p50'])} |")

    idle = data["idle_after_load"]
    samp = data["latency"]["stress"]["vram_sampling"]
    deltas = [s["vram_loaded_mib"] - s["vram_before_mib"] for s in data["startup"]]
    rows += ["", "## VRAM", "",
             "La memoria de vídeo global (`nvidia-smi`) incluye al escritorio y a otros procesos, así que la "
             "cifra fiable del servidor es la DIFERENCIA entre justo antes de arrancar y justo después de cargar, "
             "contrastada con el contador de Windows por proceso.", "",
             "| Medida | MiB |", "|:---|---:|"]
    rows.append(f"| Diferencia por arranque (`nvidia-smi`, {len(deltas)} arranques): "
                f"{', '.join(str(d) for d in deltas)} | **{fmt(sum(deltas) / len(deltas))}** |")
    rows.append(f"| VRAM dedicada del proceso (contador de Windows `GPU Process Memory`), en reposo | {fmt(idle['process_vram_mib'])} |")
    rows.append(f"| VRAM dedicada del proceso, tras todas las pasadas | {fmt(data['after_passes']['process_vram_mib'])} |")
    rows.append(f"| `nvidia-smi` global antes de arrancar (mínimo de los arranques) | {min(s['vram_before_mib'] for s in data['startup'])} |")
    rows.append(f"| `nvidia-smi` global con el modelo cargado (máximo de los arranques) | {max(s['vram_loaded_mib'] for s in data['startup'])} |")
    rows.append(f"| `nvidia-smi` global, máximo durante la prueba de peor caso ({samp['n_samples']} muestras) | {samp['max_mib']} |")
    rows.append(f"| `nvidia-smi` global tras cerrar el servidor | {data['after_stop']['vram_used_mib']} |")
    rows += [""]
    rows += [f"- RAM del proceso (conjunto de trabajo): {fmt(idle['working_set_mib'])} MiB en reposo y "
             f"{fmt(data['after_passes']['working_set_mib'])} MiB tras las pasadas.",
             "- Desglose según el registro de llama-server: " + ", ".join(
                 f"{b['device']} {b['kind']} {b['mib']:.0f} MiB" for b in data["server_log"]["buffers"]) + "."]

    rows += ["", "## Variantes de prompt (una pasada de 65 frases cada una, semilla 42)", "",
             "| Variante | Fallos de estructura | No es traducción | Léxico de España (OK/total) | Plural informal: vosotros / ustedes / neutro | Glosario (OK/total) | Trampas falladas | Total p50, ms | Tokens de prompt p50 |",
             "|:---|---:|---:|---:|:---:|---:|---:|---:|---:|"]
    for name, blob in a["configs"].items():
        q = blob["quality"]
        lat = blob["latency"]
        rows.append(
            f"| `{name}` | {q['struct_fail']} | {q['non_translation']} | {q['lexical_ok']}/{q['lexical_total']} | "
            f"{q['plural_vosotros']} / {q['plural_ustedes']} / {q['plural_neutral']} | "
            f"{q['glossary_ok']}/{q['glossary_total']} | {q['trap_fail']} | {fmt(lat['total_ms']['p50'])} | "
            f"{fmt(lat['prompt_tokens']['p50'])} |"
        )

    rows += ["", "## Robustez: frases que suenan a órdenes al asistente", "",
             "| Nº | Inglés | Salida del modelo | ¿Traduce? (automático) |", "|---:|:---|:---|:---:|"]
    verdict = {r["line_id"]: r for r in a["robustness"]}
    for rec in data["robustness"]["records"]:
        v = verdict[rec["line_id"]]
        out = rec["output"].replace("|", "\\|").replace("\n", " ⏎ ")
        rows.append(f"| {rec['line_id']} | {rec['source']} | {out} | {'NO' if v['trap_fail'] else 'sí'} |")
    path.write_text("# Tablas de la medición S2 (generadas por bench.py)\n\n" + "\n".join(rows) + "\n", encoding="utf-8")


def slim_for_storage(data: dict) -> None:
    """Quita el texto de los prompts de los registros (salvo la pasada final) para acortar el JSON."""
    for name, blob in data["configs"].items():
        if name == FINAL:
            continue
        for rec in blob["records"]:
            rec.pop("prompt", None)
    for blob in data["latency"].values():
        for rec in blob["records"]:
            rec.pop("prompt", None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="prueba de humo: 2 arranques, 1 pasada, 2 variantes")
    ap.add_argument("--startups", type=int, default=5, help="arranques del servidor a medir")
    ap.add_argument("--latency-passes", type=int, default=3, help="pasadas de latencia (streaming y completa)")
    ap.add_argument("--pace", type=float, default=1.5, help="segundos entre peticiones en la pasada con ritmo")
    ap.add_argument("--report", action="store_true",
                    help="solo regenerar los informes desde resultados/metricas.json (sin usar la GPU)")
    ap.add_argument("--model", default="", help="ruta de otro GGUF (por defecto, Hy-MT2-1.8B Q8_0)")
    ap.add_argument("--tag", default="", help="sufijo de los ficheros de resultados (p. ej. _7b)")
    args = ap.parse_args()
    tag = args.tag
    if args.report:
        data = json.loads((RESULTS / f"metricas{tag}.json").read_text(encoding="utf-8"))
        data["analysis"] = analyse(data)
        write_translations(data, RESULTS / f"traducciones{tag}.md")
        write_comparison(data, RESULTS / f"comparativa_configs{tag}.md")
        write_tables(data, RESULTS / f"tablas{tag}.md")
        (RESULTS / f"metricas{tag}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
        print_summary(data)
        return 0
    if args.quick:
        args.startups, args.latency_passes = 2, 1

    t0 = time.time()
    data = measure(args)  # <- toda la GPU ocurre aquí, dentro del candado
    data["env"] = environment(data, args)
    data["analysis"] = analyse(data)
    data["wall_time_s"] = time.time() - t0

    RESULTS.mkdir(parents=True, exist_ok=True)
    write_translations(data, RESULTS / f"traducciones{tag}.md")
    write_comparison(data, RESULTS / f"comparativa_configs{tag}.md")
    write_tables(data, RESULTS / f"tablas{tag}.md")
    slim_for_storage(data)
    (RESULTS / f"metricas{tag}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print_summary(data)
    print(f"\n[bench] listo en {data['wall_time_s']:.0f} s. Resultados en {RESULTS}")
    return 0


def print_summary(data: dict) -> None:
    a = data["analysis"]
    print("\n===== RESUMEN =====")
    starts = [s["ready_s"] for s in data["startup"]]
    print(f"Arranque (s): {', '.join(f'{s:.2f}' for s in starts)}")
    for key in ("stream_back_to_back", "full_back_to_back", "stream_cached", "stream_paced", "stress"):
        if key not in a["latency"]:
            continue
        s = a["latency"][key]
        line = f"{key:<22} n={s['n']:<4} total p50/p95 = {s['total_ms']['p50']:.0f}/{s['total_ms']['p95']:.0f} ms"
        if "ttft_ms" in s:
            line += f" | TTFT p50/p95 = {s['ttft_ms']['p50']:.0f}/{s['ttft_ms']['p95']:.0f} ms"
        line += f" | decode {s['decode_tps']['p50']:.0f} tok/s"
        print(line)
    idle = data["idle_after_load"]
    print(f"VRAM: base {data['vram_base_mib']} MiB -> cargado {idle['vram_used_mib']} MiB "
          f"(proceso {fmt(idle['process_vram_mib'])} MiB) -> tras cerrar {data['after_stop']['vram_used_mib']} MiB")
    for name, blob in a["configs"].items():
        q = blob["quality"]
        print(f"{name:<16} estruct={q['struct_fail']} no-traducción={q['non_translation']} "
              f"léxico={q['lexical_ok']}/{q['lexical_total']} "
              f"vosotros={q['plural_vosotros']}/ustedes={q['plural_ustedes']}/neutro={q['plural_neutral']} "
              f"glosario={q['glossary_ok']}/{q['glossary_total']}")
    fails = sum(1 for r in a["robustness"] if r["trap_fail"])
    print(f"Robustez: {fails} de {len(a['robustness'])} frases adversariales NO se tradujeron (automático)")


if __name__ == "__main__":
    sys.exit(main())
