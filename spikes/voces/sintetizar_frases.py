"""Sintetiza las 4 frases comunes con el motor de producción para cada candidata (A diseñadas y B de estudio).

Motor de producción (ADR-0008, R8): Qwen3-TTS-12Hz-0.6B-Base + faster-qwen3-tts 0.5.3, modo ICL con el `ref_text` de la referencia,
`language="Spanish"`, `chunk_size=4`, 0,5 s de silencio al final de la referencia contra el «phoneme bleeding» (mismas funciones que
`spikes/voz/qwen3/bench_qwen3.py`, que se importan tal cual). Entorno: el de `spikes/voz/qwen3` sin modificar; GPU bajo `gpu.lock`.

    uv run --project spikes/voz/qwen3 python spikes/voces/sintetizar_frases.py                  # todas las `<id>_ref.wav` de la carpeta de salida
    uv run --project spikes/voz/qwen3 python spikes/voces/sintetizar_frases.py --ids es-f-dis-01,es-f-est-01 --semilla-base 9000

Lee `<out>/<id>_ref.wav` y `<out>/<id>_ref.json` (campo `ref_text`) y escribe `<out>/<id>_frase1.wav` ... `<id>_frase4.wav` y
`<out>/<id>_sintesis.json` (semilla, duración, primer audio y factor tiempo real por frase).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "voz" / "qwen3"))
import common as c  # noqa: E402

vb = c.vb
import bench_qwen3 as bq  # noqa: E402  (preparar_prompt y una_peticion del spike S1; no ejecuta nada al importarse)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", default="", help="lista separada por comas; vacío = todas las que tengan <id>_ref.wav")
    ap.add_argument("--chunk-size", type=int, default=4)
    ap.add_argument("--semilla-base", type=int, default=4242)
    ap.add_argument("--rehacer", action="store_true", help="vuelve a sintetizar aunque ya existan las 4 frases")
    ap.add_argument("--modelo", default=str(vb.models_dir() / c.QWEN3_BASE_DIR))
    args = ap.parse_args()

    out = c.out_dir()
    ids = [x.strip() for x in args.ids.split(",") if x.strip()] or sorted(p.name[: -len("_ref.wav")] for p in out.glob("*_ref.wav"))
    pendientes = [i for i in ids if args.rehacer or not all((out / f"{i}_frase{f['n']}.wav").exists() for f in c.FRASES)]
    print("candidatas:", ids, "| a sintetizar:", pendientes, flush=True)
    if not pendientes:
        return

    with vb.gpu_lock() as esperado:
        import torch
        from faster_qwen3_tts import FasterQwen3TTS

        sampler = vb.VramSampler(interval_s=0.1)
        with sampler:
            t0 = time.perf_counter()
            model = FasterQwen3TTS.from_pretrained(args.modelo, device="cuda", dtype=torch.bfloat16, attn_implementation="sdpa", max_seq_len=2048)
            torch.cuda.synchronize()
            print(f"Qwen3-TTS 0.6B Base cargado en {time.perf_counter() - t0:.1f} s (espera del candado {esperado:.0f} s)", flush=True)
            model.warmup(prefill_len=100)
            primera = True
            for cid in pendientes:
                ref_wav = out / f"{cid}_ref.wav"
                meta = c.leer_json(out / f"{cid}_ref.json")
                audio, sr = vb.read_wav_mono(ref_wav)
                items, prep_s = bq.preparar_prompt(model, ref_wav, audio, sr, meta["ref_text"], "icl")
                if primera:  # una petición de calentamiento sin guardar (los grafos ya están capturados por warmup)
                    bq.una_peticion(model, c.FRASES[0]["texto"], items, meta["ref_text"], args.chunk_size, "icl", seed=100)
                    primera = False
                regs = []
                for f in c.FRASES:
                    seed = args.semilla_base + f["n"]
                    ttfa, total, wav, sr_out, ft, n = bq.una_peticion(model, f["texto"], items, meta["ref_text"], args.chunk_size, "icl", seed=seed)
                    dur = len(wav) / sr_out
                    vb.write_wav(out / f"{cid}_frase{f['n']}.wav", wav, sr_out)
                    regs.append({"frase": f["n"], "tipo": f["tipo"], "semilla": seed, "duracion_s": round(dur, 2), "primer_audio_s": round(ttfa, 3),
                                 "rtf": round(total / dur, 3)})
                    print(f"{cid} frase {f['n']} ({f['tipo']}): {dur:.1f} s | primer audio {ttfa * 1000:.0f} ms | RTF {total / dur:.2f}", flush=True)
                c.guardar_json(out / f"{cid}_sintesis.json", {"id": cid, "motor": "Qwen3-TTS-12Hz-0.6B-Base + faster-qwen3-tts 0.5.3 (ICL, chunk_size=%d)" % args.chunk_size,
                                                             "ref_text": meta["ref_text"], "preparar_referencia_s": round(prep_s, 3), "frases": regs})
            print("VRAM pico (torch asignado):", round(torch.cuda.max_memory_allocated() / 2**20), "MiB | NVML pico:", round(sampler.peak_mib), "MiB", flush=True)


if __name__ == "__main__":
    main()
