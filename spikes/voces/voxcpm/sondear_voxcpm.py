"""Camino A2: ¿VoxCPM2 (Apache-2.0) puede DISEÑAR una voz con acento castellano que distinga /θ/ de /s/?

Misma sonda que `sondear_acento.py` (frase densa en z/ce/ci y s) con la misma voz base y distintas formas de pedir el acento. La descripción
va entre paréntesis delante del texto, como dice la ficha del modelo. Entorno propio (`spikes/voces/voxcpm`), GPU bajo `gpu.lock`:

    uv run --project spikes/voces/voxcpm python spikes/voces/voxcpm/sondear_voxcpm.py --takes 2
    uv run --project spikes/voces python spikes/voces/evaluar_sonda.py sonda_vox          # mide Δ s−θ y WER en CPU

El modelo está en `%LOCALAPPDATA%\\InstantTraductor\\models\\voxcpm2` (descargado con `huggingface_hub`, sin cuenta).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common as c  # noqa: E402
from sondear_acento import TEXTO_SONDA  # noqa: E402  (no ejecuta nada al importarse; no usa torch)

vb = c.vb

BASE = "A young woman around 25 years old, soft and warm medium-pitched voice, gentle and friendly, natural expressive intonation, clear diction, relaxed pace"

VARIANTES: dict[str, str] = {
    "sin_acento": f"({BASE})",
    "espana": f"({BASE}, native Castilian Spanish speaker from Spain)",
    "distincion": f"({BASE}, native speaker from Madrid, Spain, with a Castilian accent: she pronounces z and ce/ci as the interdental th sound /θ/ like English 'think', distinct from s, no seseo)",
    "distincion_es": "(Una mujer joven de unos 25 años, voz suave y cálida de tono medio, amable, entonación natural y expresiva, dicción clara; hablante nativa de castellano de Madrid, España, con acento peninsular: pronuncia la z y ce/ci con la zeta interdental /θ/, distinta de la s, sin seseo)",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--takes", type=int, default=2)
    ap.add_argument("--variantes", default="")
    ap.add_argument("--modelo", default=str(vb.models_dir() / "voxcpm2"))
    ap.add_argument("--semilla-base", type=int, default=555)
    ap.add_argument("--cfg", type=float, default=2.0)
    ap.add_argument("--pasos", type=int, default=10)
    args = ap.parse_args()

    nombres = [x for x in VARIANTES if not args.variantes or x in args.variantes.split(",")]
    dst = c.work_dir("sonda_vox")
    log_p = dst / "sonda_log.json"
    nuevos = []
    with vb.gpu_lock():
        import torch
        from voxcpm import VoxCPM

        sampler = vb.VramSampler(interval_s=0.1)
        with sampler:
            t0 = time.perf_counter()
            model = VoxCPM.from_pretrained(args.modelo, load_denoiser=False, optimize=False, device="cuda")
            sr = int(getattr(model.tts_model, "sample_rate", 48000))
            print(f"VoxCPM2 cargado en {time.perf_counter() - t0:.1f} s | sr {sr} | VRAM torch {torch.cuda.memory_allocated() / 2**20:.0f} MiB", flush=True)
            for nombre in nombres:
                for k in range(args.takes):
                    seed = args.semilla_base + k
                    torch.manual_seed(seed)  # la versión 2.0.3 publicada en PyPI no admite `seed=` en generate()
                    t1 = time.perf_counter()
                    wav = model.generate(text=f"{VARIANTES[nombre]}{TEXTO_SONDA}", cfg_value=args.cfg, inference_timesteps=args.pasos)
                    a = np.asarray(wav, dtype=np.float32).reshape(-1)
                    if sr != c.SR:
                        from math import gcd

                        from scipy.signal import resample_poly

                        g = gcd(sr, c.SR)
                        a = resample_poly(a, c.SR // g, sr // g).astype(np.float32)
                    fich = f"sonda_{nombre}_t{k + 1}.wav"
                    vb.write_wav(dst / fich, a, c.SR)
                    print(f"{fich}: {len(a) / c.SR:.1f} s en {time.perf_counter() - t1:.1f} s", flush=True)
                    nuevos.append({"fichero": fich, "variante": nombre, "toma": k + 1, "semilla": seed, "instruct": VARIANTES[nombre], "texto": TEXTO_SONDA})
            print("VRAM pico torch:", round(torch.cuda.max_memory_allocated() / 2**20), "MiB | NVML delta:", round(sampler.peak_mib - sampler.baseline_mib), "MiB", flush=True)
    previo = json.loads(log_p.read_text(encoding="utf-8")) if log_p.exists() else []
    log_p.write_text(json.dumps(previo + nuevos, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
