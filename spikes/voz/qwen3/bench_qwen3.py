"""Spike S1 - candidato A: Qwen3-TTS-0.6B Base + faster-qwen3-tts (CUDA graphs) en la RTX 5070 con Windows nativo.

Mide, con la referencia ya cacheada y tras calentamiento (el arranque en frío se mide aparte con --fase fria):
  - TTFA (tiempo hasta el primer audio) en streaming, p50 y p95, para varios chunk_size;
  - RTF (tiempo de generación / duración del audio) y xRT (su inverso);
  - VRAM pico (torch.cuda.max_memory_allocated y nvidia-smi/NVML) y tiempo de carga del modelo;
  - genera las 6 muestras comunes (WAV) para que el humano las escuche.

Toda la parte con GPU va dentro del candado %LOCALAPPDATA%\\InstantTraductor\\gpu.lock.

    cd spikes/voz/qwen3
    uv run python bench_qwen3.py --fase fria                 # arranque en frío (carga + 1ª petición con captura de grafos)
    uv run python bench_qwen3.py --fase completa             # calentamiento + barrido de chunk_size + muestras
    uv run python bench_qwen3.py --fase completa --modo xvec --sin-muestras --salida qwen3_xvec.json
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import vozbench as vb  # noqa: E402

LANG = "Spanish"
PACKAGES = ["faster-qwen3-tts", "qwen-tts-hf", "transformers", "accelerate", "torch", "torchaudio", "numpy", "soundfile", "huggingface-hub"]


def cargar_referencia(ref_wav: Path, ref_meta: Path) -> tuple[np.ndarray, int, str]:
    meta = json.loads(ref_meta.read_text(encoding="utf-8"))
    audio, sr = vb.read_wav_mono(ref_wav)
    return audio, sr, meta["texto"]


def preparar_prompt(model, ref_wav: Path, audio: np.ndarray, sr: int, ref_text: str, modo: str):
    """Construye UNA vez el prompt de clonación (lo que el producto cachearía por personaje) y mide su coste."""
    import torch

    torch.cuda.synchronize()
    t0 = time.perf_counter()
    if modo == "xvec":
        items = model.model.create_voice_clone_prompt(ref_audio=str(ref_wav), ref_text="", x_vector_only_mode=True)
    else:
        # Igual que el envoltorio: 0,5 s de silencio al final de la referencia contra el «phoneme bleeding» del modo ICL.
        silence = np.zeros(int(0.5 * sr), dtype=np.float32)
        items = model.model.create_voice_clone_prompt(ref_audio=(np.concatenate([audio, silence]), sr), ref_text=ref_text)
    torch.cuda.synchronize()
    return items, time.perf_counter() - t0


def una_peticion(model, texto: str, items, ref_text: str, chunk_size: int, modo: str, seed: int | None = None, instruct: str | None = None):
    """Una síntesis en streaming. Devuelve (ttfa_s, total_s, audio_np, sr, timing_primer_chunk, n_chunks)."""
    import torch

    if seed is not None:
        torch.manual_seed(seed)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    gen = model.generate_voice_clone_streaming(
        text=texto,
        language=LANG,
        ref_text=ref_text,
        voice_clone_prompt=items,
        chunk_size=chunk_size,
        xvec_only=(modo == "xvec"),
        instruct=instruct,
    )
    chunks = []
    ttfa = None
    first_timing = None
    for audio, sr, timing in gen:
        if ttfa is None:
            ttfa = time.perf_counter() - t0
            first_timing = dict(timing)
        chunks.append(np.asarray(audio, dtype=np.float32).reshape(-1))
    total = time.perf_counter() - t0
    wav = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    return ttfa, total, wav, sr, first_timing, len(chunks)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fase", choices=["fria", "completa", "velocidad"], default="completa")
    ap.add_argument("--modo", choices=["icl", "xvec"], default="icl", help="icl = referencia en contexto (ADR-0008); xvec = solo embedding del hablante")
    ap.add_argument("--chunk-sizes", default="1,2,4,8", help="pasos de códec por chunk (1 paso ~ 83 ms de audio)")
    ap.add_argument("--chunk-muestras", type=int, default=8)
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--sin-muestras", action="store_true")
    ap.add_argument("--ref-wav", default=str(vb.ref_dir() / vb.REF_WAV))
    ap.add_argument("--ref-meta", default=str(vb.ref_dir() / vb.REF_META))
    ap.add_argument("--modelo", default=str(vb.models_dir() / vb.QWEN3_MODEL_DIR))
    ap.add_argument("--prefijo-muestras", default="A_qwen3")
    ap.add_argument("--subcarpeta-muestras", default="", help="p. ej. extra: las muestras van a muestras/<subcarpeta>/")
    ap.add_argument("--salida", default=None, help="nombre del JSON de resultados")
    args = ap.parse_args()

    ref_wav, ref_meta = Path(args.ref_wav), Path(args.ref_meta)
    audio_ref, sr_ref, ref_text = cargar_referencia(ref_wav, ref_meta)
    chunk_sizes = [int(x) for x in args.chunk_sizes.split(",")]
    salida = args.salida or f"qwen3_{args.fase}_{args.modo}.json"
    print(f"referencia: {ref_wav.name} ({len(audio_ref) / sr_ref:.1f} s) | texto: {ref_text[:70]}...", flush=True)

    res: dict = {
        "candidato": "A: Qwen3-TTS-12Hz-0.6B-Base + faster-qwen3-tts (CUDA graphs)",
        "fase": args.fase,
        "modo": args.modo,
        "idioma": LANG,
        "referencia": {"wav": str(ref_wav), "duracion_s": round(len(audio_ref) / sr_ref, 2), "texto": ref_text},
        "frases_medicion": vb.MEASURE_SENTENCES,
    }

    with vb.gpu_lock() as esperado:
        res["espera_candado_s"] = round(esperado, 1)
        import torch
        from faster_qwen3_tts import FasterQwen3TTS

        res["entorno"] = vb.collect_env_info(PACKAGES)
        sampler = vb.VramSampler(interval_s=0.1)
        res["vram_linea_base_mib"] = {"nvml": round(sampler.baseline_mib, 1), "nvidia_smi": vb.vram_used_mib_smi(), "total": round(sampler.total_mib)}
        with sampler:
            torch.cuda.reset_peak_memory_stats()
            # ---------------------------------------------------------------- carga del modelo
            t0 = time.perf_counter()
            model = FasterQwen3TTS.from_pretrained(args.modelo, device="cuda", dtype=torch.bfloat16, attn_implementation="sdpa", max_seq_len=2048)
            torch.cuda.synchronize()
            res["carga_modelo_s"] = round(time.perf_counter() - t0, 2)
            res["vram_tras_carga"] = {
                "nvml_mib": round(sampler.read_mib(), 1),
                "torch_allocated_mib": round(torch.cuda.memory_allocated() / 2**20, 1),
                "torch_reserved_mib": round(torch.cuda.memory_reserved() / 2**20, 1),
            }
            print(f"modelo cargado en {res['carga_modelo_s']} s | VRAM (NVML) {res['vram_tras_carga']['nvml_mib']} MiB", flush=True)

            # ---------------------------------------------------------------- prompt de la referencia (caché por personaje)
            items, ref_prep_s = preparar_prompt(model, ref_wav, audio_ref, sr_ref, ref_text, args.modo)
            res["preparar_referencia_s"] = round(ref_prep_s, 3)
            print(f"prompt de la referencia creado en {ref_prep_s:.3f} s", flush=True)

            frases = vb.MEASURE_SENTENCES
            if args.fase == "fria":
                # Arranque en frío: SIN calentamiento explícito; la 1ª petición captura los CUDA graphs (perezoso).
                ttfa, total, wav, sr, ft, n = una_peticion(model, frases[2], items, ref_text, 8, args.modo, seed=1)
                res["peticion_fria"] = {"ttfa_s": round(ttfa, 3), "total_s": round(total, 3), "audio_s": round(len(wav) / sr, 2), "timing_primer_chunk": ft, "nota": "incluye captura perezosa de los CUDA graphs (chunk_size=8)"}
                ttfa2, total2, wav2, sr2, ft2, n2 = una_peticion(model, frases[3], items, ref_text, 8, args.modo, seed=2)
                res["segunda_peticion"] = {"ttfa_s": round(ttfa2, 3), "total_s": round(total2, 3), "audio_s": round(len(wav2) / sr2, 2)}
                print(f"1ª petición (fría): TTFA {ttfa:.3f} s, total {total:.3f} s | 2ª: TTFA {ttfa2:.3f} s", flush=True)
            elif args.fase == "velocidad":
                # ¿Se puede pedir 1,1x / 1,25x? Qwen3-TTS Base no tiene parámetro de velocidad; lo único «nativo» es el argumento
                # instruct (experimental en Base). Se mide el efecto real en la duración del audio y en el TTFA.
                model.warmup(prefill_len=100)
                for i in range(3):
                    una_peticion(model, frases[i], items, ref_text, 8, args.modo, seed=100 + i)
                instrucciones = {
                    "sin_instruccion": None,
                    "es_mas_rapido": "Habla más rápido de lo normal.",
                    "es_25_por_ciento": "Habla un 25 % más rápido.",
                    "en_25_percent": "Speak 25% faster than normal.",
                    "es_muy_deprisa": "Habla muy deprisa, con un ritmo ágil.",
                }
                usadas = list(range(0, 20, 2))  # 10 frases
                semillas = [11, 12]
                base_dur: dict = {}
                salida_vel = {}
                for nombre, instr in instrucciones.items():
                    durs, ttfas = {}, []
                    for i in usadas:
                        for sd in semillas:
                            ttfa, total, wav, sr, ft, n = una_peticion(model, frases[i], items, ref_text, 8, args.modo, seed=sd * 100 + i, instruct=instr)
                            durs.setdefault(i, []).append(len(wav) / sr)
                            ttfas.append(ttfa)
                    if nombre == "sin_instruccion":
                        base_dur = {i: float(np.mean(v)) for i, v in durs.items()}
                    ratios = [base_dur[i] / float(np.mean(v)) for i, v in durs.items()]  # >1 = más rápido que la base
                    salida_vel[nombre] = {"instruct": instr, "velocidad_efectiva_mediana": round(float(np.median(ratios)), 3), "velocidad_efectiva_min": round(min(ratios), 3), "velocidad_efectiva_max": round(max(ratios), 3), "ttfa_s": vb.summarize(ttfas)}
                    print(f"{nombre:18s}: velocidad efectiva mediana {np.median(ratios):.3f}x (min {min(ratios):.2f}, max {max(ratios):.2f}) | TTFA p50 {vb.summarize(ttfas)['p50'] * 1000:.0f} ms", flush=True)
                res["velocidad_instruct"] = salida_vel
            else:
                # ------------------------------------------------------------ calentamiento explícito (captura de grafos)
                t0 = time.perf_counter()
                model.warmup(prefill_len=100)
                torch.cuda.synchronize()
                res["calentamiento_capturar_grafos_s"] = round(time.perf_counter() - t0, 2)
                print(f"calentamiento (captura de CUDA graphs): {res['calentamiento_capturar_grafos_s']} s", flush=True)
                for i in range(3):  # peticiones de calentamiento no medidas
                    una_peticion(model, frases[i], items, ref_text, 8, args.modo, seed=100 + i)

                # ------------------------------------------------------------ barrido de chunk_size
                barrido = {}
                registros = []
                for cs in chunk_sizes:
                    ttfas, rtfs, xrts = [], [], []
                    for rep in range(args.repeticiones):
                        for i, frase in enumerate(frases):
                            ttfa, total, wav, sr, ft, n = una_peticion(model, frase, items, ref_text, cs, args.modo, seed=1000 * cs + 10 * rep + i)
                            dur = len(wav) / sr
                            ttfas.append(ttfa)
                            rtfs.append(total / dur)
                            xrts.append(dur / total)
                            registros.append({"chunk_size": cs, "rep": rep, "frase": i, "palabras": vb.count_words(frase), "ttfa_s": round(ttfa, 4), "total_s": round(total, 4), "audio_s": round(dur, 3), "rtf": round(total / dur, 4), "prefill_ms": round(ft.get("prefill_ms", 0), 1), "decode_primer_chunk_ms": round(ft.get("decode_ms", 0), 1), "n_chunks": n})
                    barrido[str(cs)] = {"ttfa_s": vb.summarize(ttfas), "rtf": vb.summarize(rtfs), "xrt": vb.summarize(xrts), "n_peticiones": len(ttfas)}
                    s = barrido[str(cs)]
                    print(f"chunk_size={cs}: TTFA p50 {s['ttfa_s']['p50'] * 1000:.0f} ms, p95 {s['ttfa_s']['p95'] * 1000:.0f} ms | RTF p50 {s['rtf']['p50']:.3f} ({s['xrt']['p50']:.1f}x tiempo real)", flush=True)
                res["barrido_chunk_size"] = barrido
                res["registros"] = registros
                torch.cuda.synchronize()

                # ------------------------------------------------------------ muestras para escuchar (mismas 6 frases en ambos candidatos)
                if not args.sin_muestras:
                    base = vb.samples_dir() / args.subcarpeta_muestras if args.subcarpeta_muestras else vb.samples_dir()
                    salidas = []
                    for i, frase in enumerate(vb.SAMPLE_SENTENCES, start=1):
                        ttfa, total, wav, sr, ft, n = una_peticion(model, frase, items, ref_text, args.chunk_muestras, args.modo, seed=4242 + i)
                        p = base / f"{args.prefijo_muestras}_{i:02d}.wav"
                        vb.write_wav(p, wav, sr)
                        salidas.append({"wav": str(p), "frase": frase, "audio_s": round(len(wav) / sr, 2), "ttfa_s": round(ttfa, 3), "pico": round(float(np.max(np.abs(wav))), 3)})
                        print(f"muestra {i}: {p.name} ({len(wav) / sr:.1f} s, pico {np.max(np.abs(wav)):.2f})", flush=True)
                    res["muestras"] = salidas

            # ---------------------------------------------------------------- VRAM pico
            torch.cuda.synchronize()
            res["vram_pico"] = {
                "torch_max_allocated_mib": round(torch.cuda.max_memory_allocated() / 2**20, 1),
                "torch_max_reserved_mib": round(torch.cuda.max_memory_reserved() / 2**20, 1),
                "nvml_pico_total_mib": round(sampler.peak_mib, 1),
                "nvidia_smi_ahora_mib": vb.vram_used_mib_smi(),
                "nvml_pico_menos_linea_base_mib": round(sampler.peak_mib - sampler.baseline_mib, 1),
            }
            print("VRAM pico:", json.dumps(res["vram_pico"]), flush=True)
            del model
            gc.collect()
            torch.cuda.empty_cache()

    out = vb.save_json(salida, res)
    print("resultados ->", out)


if __name__ == "__main__":
    main()
