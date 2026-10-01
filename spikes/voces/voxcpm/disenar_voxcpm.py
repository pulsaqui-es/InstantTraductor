"""Camino A2: diseña las 8 voces femeninas con VoxCPM2 (descripción entre paréntesis delante del texto) y guarda sus referencias en bruto.

Mismas descripciones de timbre que `disenos.py` (Qwen3-VoiceDesign), con la cláusula de acento elegida con `sondear_voxcpm.py`. Entorno propio
(`spikes/voces/voxcpm`), GPU bajo `gpu.lock`:

    uv run --project spikes/voces/voxcpm python spikes/voces/voxcpm/disenar_voxcpm.py --takes 3 --acento distincion_es

Escribe `<out>/_trabajo/dis_vox/<id>_<acento>_t<k>.wav` (24 kHz) y `disenos_log.json`; la elección de la toma la hace `evaluar_disenos.py --carpeta dis_vox`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from math import gcd
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common as c  # noqa: E402
import disenos as d  # noqa: E402

vb = c.vb

ACENTOS = {
    "espana": ", native Castilian Spanish speaker from {lugar}, Spain",
    "distincion": ", native speaker from {lugar}, Spain, with a Castilian accent: she pronounces z and ce/ci as the interdental th sound /θ/ like English 'think', distinct from s, no seseo",
    # La sonda (`sondear_voxcpm.py`) dio Δ 12,0 dB solo con la descripción entera en español (inglés: 0,8 dB), así que esta es la que se usa.
    "distincion_es": "; hablante nativa de castellano de {lugar}, España, con acento peninsular: pronuncia la z y ce/ci con la zeta interdental /θ/, distinta de la s, sin seseo",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--takes", type=int, default=2)
    ap.add_argument("--acento", choices=sorted(ACENTOS), default="distincion_es")
    ap.add_argument("--ids", default="", help="subconjunto de es-f-dis-NN; vacío = todos")
    ap.add_argument("--modelo", default=str(vb.models_dir() / "voxcpm2"))
    ap.add_argument("--semilla-base", type=int, default=4100)
    ap.add_argument("--cfg", type=float, default=2.0)
    ap.add_argument("--pasos", type=int, default=10)
    args = ap.parse_args()

    ids = {x.strip() for x in args.ids.split(",") if x.strip()}
    voces = [v for v in d.DISENOS if not ids or v["id"] in ids]
    dst = c.work_dir("dis_vox")
    nuevos: list[dict] = []
    with vb.gpu_lock():
        import torch
        from scipy.signal import resample_poly
        from voxcpm import VoxCPM

        sampler = vb.VramSampler(interval_s=0.1)
        with sampler:
            model = VoxCPM.from_pretrained(args.modelo, load_denoiser=False, optimize=False, device="cuda")
            sr = int(getattr(model.tts_model, "sample_rate", 48000))
            for v in voces:
                texto = d.REF_TEXTOS[v["ref"]]
                if args.acento.endswith("_es"):
                    desc = "(" + v["es"].rstrip(".") + ACENTOS[args.acento].format(lugar=v["lugar"]) + ")"
                else:
                    desc = "(" + v["en"].rstrip(".").replace("Female, ", "A ", 1) + ACENTOS[args.acento].format(lugar=v["lugar"]) + ")"
                for k in range(args.takes):
                    seed = args.semilla_base + 100 * int(v["id"][-2:]) + k
                    torch.manual_seed(seed)  # la versión 2.0.3 publicada en PyPI no admite `seed=` en generate()
                    t1 = time.perf_counter()
                    wav = model.generate(text=f"{desc}{texto}", cfg_value=args.cfg, inference_timesteps=args.pasos)
                    a = np.asarray(wav, dtype=np.float32).reshape(-1)
                    if sr != c.SR:
                        g = gcd(sr, c.SR)
                        a = resample_poly(a, c.SR // g, sr // g).astype(np.float32)
                    fich = f"{v['id']}_{args.acento}_t{k + 1}.wav"
                    vb.write_wav(dst / fich, a, c.SR)
                    print(f"{fich}: {len(a) / c.SR:.1f} s en {time.perf_counter() - t1:.1f} s", flush=True)
                    nuevos.append({"fichero": fich, "id": v["id"], "variante": args.acento, "ortografia": "normal", "toma": k + 1, "semilla": seed,
                                   "ref_texto_clave": v["ref"], "texto": texto, "texto_enviado": texto, "instruct": desc, "sr_origen": sr,
                                   "gen_s": round(time.perf_counter() - t1, 2)})
            print("VRAM pico torch:", round(torch.cuda.max_memory_allocated() / 2**20), "MiB | NVML delta:", round(sampler.peak_mib - sampler.baseline_mib), "MiB", flush=True)
    log_p = dst / "disenos_log.json"
    previo = json.loads(log_p.read_text(encoding="utf-8")) if log_p.exists() else {"entradas": []}
    previo["entradas"] += nuevos
    log_p.write_text(json.dumps(previo, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
