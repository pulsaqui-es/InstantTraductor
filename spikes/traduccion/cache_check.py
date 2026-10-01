"""Efecto de ``cache_prompt`` y de ``--cache-ram`` en latencia y en RAM del proceso.

En el *benchmark* la RAM de ``llama-server`` pasó de 2,3 a 4,2 GB tras muchas pasadas. Este
script averigua de dónde viene: mide el prompt final con dos configuraciones del servidor
(la de por defecto, con caché de prompt en RAM de hasta 8 GiB, y ``--cache-ram 0``) y, en
cada una, con ``cache_prompt: false`` y con ``cache_prompt: true``, anotando la RAM del
proceso después de cada pasada de 65 frases.

Uso (dentro del candado de GPU)::

    uv run python cache_check.py               # cache_prompt y --cache-ram
    uv run python cache_check.py --sequence    # RAM tras cada etapa del benchmark
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import gpu_info
from bench import CONFIGS, FINAL_CFG
from client import Translator, summarize
from corpus import LINES
from gpu_lock import gpu_lock
from llama_server import LlamaServer
from pipeline import run_pass
from prompts import build_messages

HERE = Path(__file__).resolve().parent
OUT = HERE / "resultados" / "cache_ram.json"

CASES = (
    ("por defecto (--cache-ram 8192)", ()),
    ("--cache-ram 0", ("--cache-ram", "0")),
)
#: (etapa, valor de cache_prompt, nº de pasadas de 65 frases)
STAGES = (
    ("cache_prompt: false", False, 6),
    ("cache_prompt: true", True, 3),
)


def sequence() -> int:
    """Repite en orden las etapas del benchmark anotando la RAM del proceso tras cada una.

    Sirve para localizar qué etapa hace crecer la RAM de 2,3 a 4,2 GB (ver ``bench.py``).
    """
    out_path = HERE / "resultados" / "cache_ram_secuencia.json"
    steps: list[dict] = []
    with gpu_lock():
        srv = LlamaServer(log_path=HERE / "resultados" / "llama-server.log")
        try:
            srv.start()
            pid = srv.pid

            def mark(name: str) -> None:
                ram = gpu_info.process_working_set_mib(pid)
                steps.append({"step": name, "ram_mib": ram})
                print(f"[secuencia] {name:<34} RAM {ram:.0f} MiB", flush=True)

            mark("tras arrancar")
            with Translator(srv.base_url) as tr:
                for line in LINES[:3]:
                    tr.complete(build_messages(line.text, FINAL_CFG), stream=True, max_tokens=96)
                mark("tras el calentamiento")
                frozen: dict[int, str] = {}
                for cfg in CONFIGS:
                    recs = run_pass(tr, LINES, cfg, stream=True)
                    if cfg.name == FINAL_CFG.name:
                        frozen = {r["line_id"]: r["output"] for r in recs}
                    mark(f"config {cfg.name}")
                run_pass(tr, LINES, FINAL_CFG, stream=False, frozen=frozen)
                mark("pasada sin streaming")
                run_pass(tr, LINES, FINAL_CFG, stream=True, frozen=frozen, cache_prompt=True)
                mark("pasada con cache_prompt")
                run_pass(tr, LINES, FINAL_CFG, stream=True, frozen=frozen, n_pairs=5, glossary_mode="all")
                mark("pasada de peor caso")
        finally:
            srv.stop()
    out_path.write_text(json.dumps(steps, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[secuencia] escrito", out_path)
    return 0


def main() -> int:
    if "--sequence" in sys.argv:
        return sequence()
    results = []
    with gpu_lock():
        for label, extra in CASES:
            srv = LlamaServer(log_path=HERE / "resultados" / "llama-server.log", extra_args=extra)
            try:
                srv.start()
                case = {"case": label, "ram_mib_start": gpu_info.process_working_set_mib(srv.pid), "stages": []}
                with Translator(srv.base_url) as tr:
                    for line in LINES[:3]:  # calentamiento
                        tr.complete(build_messages(line.text, FINAL_CFG), stream=True, max_tokens=96)
                    first = run_pass(tr, LINES, FINAL_CFG, stream=True)  # contexto propio
                    frozen = {r["line_id"]: r["output"] for r in first}
                    case["ram_mib_after_first_pass"] = gpu_info.process_working_set_mib(srv.pid)
                    for stage, cache_prompt, n_passes in STAGES:
                        recs: list[dict] = []
                        ram_after_each = []
                        for _ in range(n_passes):
                            recs += run_pass(tr, LINES, FINAL_CFG, stream=True, frozen=frozen, cache_prompt=cache_prompt)
                            ram_after_each.append(gpu_info.process_working_set_mib(srv.pid))
                        case["stages"].append({
                            "stage": stage,
                            "n": len(recs),
                            "total_ms": summarize([r["total_ms"] for r in recs]),
                            "ttft_ms": summarize([r["ttft_ms"] for r in recs if r["ttft_ms"] is not None]),
                            "ram_mib_after_each_pass": ram_after_each,
                        })
                    case["process_vram_mib"] = gpu_info.process_vram_mib(srv.pid)
                results.append(case)
                print(f"[cache] {label}: RAM inicio {case['ram_mib_start']:.0f}, tras la 1.ª pasada "
                      f"{case['ram_mib_after_first_pass']:.0f} MiB; VRAM {case['process_vram_mib']:.0f} MiB", flush=True)
                for st in case["stages"]:
                    rams = ", ".join(f"{x:.0f}" for x in st["ram_mib_after_each_pass"])
                    print(f"[cache]   {st['stage']}: total p50/p95 = {st['total_ms']['p50']:.0f}/{st['total_ms']['p95']:.0f} ms, "
                          f"1.er token p50 = {st['ttft_ms']['p50']:.0f} ms, RAM tras cada pasada: {rams}", flush=True)
            finally:
                srv.stop()
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[cache] escrito", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
