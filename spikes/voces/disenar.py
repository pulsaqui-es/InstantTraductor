"""Camino A: diseña voces femeninas con Qwen3-TTS-12Hz-1.7B-VoiceDesign y genera su referencia (8-10 s) en bruto.

Se ejecuta en el entorno de `spikes/voz/qwen3` (sin modificar su pyproject), todo el uso de GPU bajo el candado `gpu.lock`:

    uv run --project spikes/voz/qwen3 python spikes/voces/disenar.py --takes 2
    uv run --project spikes/voz/qwen3 python spikes/voces/disenar.py --ids es-f-dis-01,es-f-dis-02 --variante es --takes 1

Escribe `<out>/_trabajo/dis/<id>_<variante>_t<k>.wav` (24 kHz, sin normalizar) y `disenos_log.json` con el texto, el `instruct`,
la semilla, la duración y el tiempo de generación. La elección de la mejor toma (ASR, F0, duración) la hace `evaluar_disenos.py` en CPU.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import disenos as d  # noqa: E402

vb = c.vb


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--takes", type=int, default=2)
    ap.add_argument("--ids", default="", help="lista separada por comas; vacío = todos")
    ap.add_argument("--variante", choices=["en", "es"], default="en", help="idioma de la descripción de la voz")
    ap.add_argument("--ortografia", choices=["normal", "th"], default="normal",
                    help="th = z/ce/ci reescritos con «th» en el texto enviado a VoiceDesign (para forzar /θ/)")
    ap.add_argument("--semilla-base", type=int, default=2026)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--modelo", default=str(vb.models_dir() / c.QWEN3_DESIGN_DIR))
    ap.add_argument("--max-s", type=float, default=15.0, help="duración máxima de cada referencia (corta bucles degenerados)")
    args = ap.parse_args()

    ids = {x.strip() for x in args.ids.split(",") if x.strip()}
    voces = [x for x in d.DISENOS if not ids or x["id"] in ids]
    dst = c.work_dir("dis")
    log_path = dst / "disenos_log.json"
    log: dict = {"entradas": []}  # solo lo de esta ejecución; al final se mezcla con el fichero (varias ejecuciones seguidas no se pisan)

    with vb.gpu_lock() as esperado:
        import torch
        from faster_qwen3_tts import FasterQwen3TTS

        sampler = vb.VramSampler(interval_s=0.1)
        base = sampler.baseline_mib
        with sampler:
            t0 = time.perf_counter()
            model = FasterQwen3TTS.from_pretrained(args.modelo, device="cuda", dtype=torch.bfloat16, attn_implementation="sdpa", max_seq_len=2048)
            torch.cuda.synchronize()
            carga_s = time.perf_counter() - t0
            print(f"VoiceDesign 1.7B cargado en {carga_s:.1f} s | VRAM torch {torch.cuda.memory_allocated() / 2**20:.0f} MiB", flush=True)
            log["carga_s"] = round(carga_s, 1)
            log["espera_candado_s"] = round(esperado, 1)
            for v in voces:
                texto = d.REF_TEXTOS[v["ref"]]
                enviado = d.respell_th(texto) if args.ortografia == "th" else texto
                instr = d.instruct(v, args.variante)
                for k in range(args.takes):
                    seed = args.semilla_base + 100 * int(v["id"][-2:]) + k
                    torch.manual_seed(seed)
                    torch.cuda.synchronize()
                    t1 = time.perf_counter()
                    audios, sr = model.generate_voice_design(text=enviado, instruct=instr, language="Spanish", max_new_tokens=int(args.max_s * 12),
                                                             temperature=args.temperature)
                    torch.cuda.synchronize()
                    gen_s = time.perf_counter() - t1
                    a = np.asarray(audios[0], dtype=np.float32).reshape(-1)
                    nombre = f"{v['id']}_{args.variante}_{args.ortografia}_t{k + 1}.wav"
                    vb.write_wav(dst / nombre, a, sr)
                    dur = len(a) / sr
                    print(f"{nombre}: {dur:.1f} s de audio en {gen_s:.1f} s (RTF {gen_s / dur:.2f}) semilla {seed}", flush=True)
                    log["entradas"].append({"fichero": nombre, "id": v["id"], "variante": args.variante, "ortografia": args.ortografia, "toma": k + 1, "semilla": seed,
                                            "ref_texto_clave": v["ref"], "texto": texto, "texto_enviado": enviado, "instruct": instr, "temperature": args.temperature,
                                            "duracion_s": round(dur, 2), "gen_s": round(gen_s, 2), "sr": sr})
            log["vram"] = {"torch_pico_asignado_mib": round(torch.cuda.max_memory_allocated() / 2**20), "torch_pico_reservado_mib": round(torch.cuda.max_memory_reserved() / 2**20),
                           "nvml_linea_base_mib": round(base), "nvml_pico_total_mib": round(sampler.peak_mib), "delta_nvml_mib": round(sampler.peak_mib - base)}
            print("VRAM:", log["vram"], flush=True)
    previo = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {"entradas": [], "ejecuciones": []}
    previo["entradas"] += log["entradas"]
    previo.setdefault("ejecuciones", []).append({k: v for k, v in log.items() if k != "entradas"} | {"ortografia": args.ortografia, "variante": args.variante})
    log_path.write_text(json.dumps(previo, ensure_ascii=False, indent=2), encoding="utf-8")
    print("log:", log_path)


if __name__ == "__main__":
    main()
