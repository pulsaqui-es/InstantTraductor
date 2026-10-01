"""Spike S1 - candidato B: Chatterbox Multilingual con el finetune es-ES en la RTX 5070 con Windows nativo.

Mide, con la referencia ya cacheada y tras calentamiento (el arranque en frío se mide aparte con --fase fria):
  - TTFA en streaming por chunks (envoltorio propio, ver cb_es.py) para varias configuraciones de chunk;
  - tiempo hasta el audio completo de la frase (ruta oficial generate) y RTF;
  - coste de la marca de agua PerTh (solo en la ruta completa);
  - VRAM pico (torch.cuda.max_memory_allocated y nvidia-smi/NVML) y tiempo de carga;
  - genera las 6 muestras comunes (WAV) para que el humano las escuche.

Toda la parte con GPU va dentro del candado %LOCALAPPDATA%\\InstantTraductor\\gpu.lock.

    cd spikes/voz/chatterbox
    uv run python bench_chatterbox.py --fase fria
    uv run python bench_chatterbox.py --fase completa
"""

from __future__ import annotations

import argparse
import gc
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import vozbench as vb  # noqa: E402
import cb_es  # noqa: E402

PACKAGES = ["chatterbox-tts", "transformers", "torch", "torchaudio", "numpy", "librosa", "safetensors", "huggingface-hub", "resemble-perth", "s3tokenizer", "diffusers", "spacy-pkuseg"]

# Configuraciones de streaming: (nombre, primer chunk en tokens [1 token = 40 ms], chunk siguiente, contexto a la izquierda)
STREAM_CFGS = {
    "p5": dict(first_chunk_tokens=5, chunk_tokens=15, ctx_tokens=10),
    "p10": dict(first_chunk_tokens=10, chunk_tokens=25, ctx_tokens=10),
    "p15": dict(first_chunk_tokens=15, chunk_tokens=25, ctx_tokens=10),
}


def sync():
    import torch

    torch.cuda.synchronize()


def stream_request(m, texto, cfg, seed, gen_kw, ttfa_only=False):
    """Una petición en streaming. Devuelve (ttfa_s, total_s, audio, n_chunks, t_por_chunk)."""
    sync()
    t0 = time.perf_counter()
    g = m.stream(texto, seed=seed, **cfg, **gen_kw)
    ttfa = None
    chunks, times = [], []
    for c in g:
        now = time.perf_counter() - t0
        if ttfa is None:
            ttfa = now
        chunks.append(c["audio"])
        times.append(now)
        if ttfa_only:
            g.close()
            break
    total = time.perf_counter() - t0
    wav = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
    return ttfa, total, wav, len(chunks), times


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fase", choices=["fria", "completa", "velocidad", "optim", "contencion"], default="completa")
    ap.add_argument("--repeticiones", type=int, default=2, help="repeticiones sobre las 20 frases en la configuración principal (p10)")
    ap.add_argument("--repeticiones-ttfa", type=int, default=3, help="repeticiones (solo hasta el primer chunk) en cada configuración")
    ap.add_argument("--cfg-principal", default="p10", choices=list(STREAM_CFGS))
    ap.add_argument("--texto", choices=["space", "pip"], default="space", help="normalización del texto (ver cb_es.py)")
    ap.add_argument("--cfg-weight", type=float, default=0.5)
    ap.add_argument("--exaggeration", type=float, default=0.5)
    ap.add_argument("--sin-muestras", action="store_true")
    ap.add_argument("--variantes", default="", help="fase optim: nombres de variantes separados por comas (por defecto todas)")
    ap.add_argument("--ab-texto", action="store_true", help="genera las 6 muestras con las dos normalizaciones de texto (space/pip) en muestras/extra/ para compararlas con el ASR")
    ap.add_argument("--solo-muestras", action="store_true", help="solo cargar, calentar y generar las muestras (sin barridos)")
    ap.add_argument("--prefijo-muestras", default="B_chatterbox")
    ap.add_argument("--subcarpeta-muestras", default="")
    ap.add_argument("--muestras-stream", action="store_true", help="generar además las muestras por la ruta de streaming (comprobar empalmes)")
    ap.add_argument("--ref-wav", default=str(vb.ref_dir() / vb.REF_WAV))
    ap.add_argument("--modelo", default=str(vb.models_dir() / vb.CHATTERBOX_MODEL_DIR))
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()

    salida = args.salida or f"chatterbox_{args.fase}.json"
    gen_kw = dict(cfg_weight=args.cfg_weight, exaggeration=args.exaggeration)
    res: dict = {
        "candidato": "B: Chatterbox Multilingual es-ES (T3 es-es + S3Gen v3), PyTorch eager, fp32",
        "fase": args.fase,
        "parametros_generacion": {**gen_kw, "temperature": 0.8, "repetition_penalty": 1.2, "min_p": 0.05, "top_p": 1.0, "texto": args.texto},
        "referencia": {"wav": args.ref_wav},
        "frases_medicion": vb.MEASURE_SENTENCES,
    }

    with vb.gpu_lock() as esperado:
        res["espera_candado_s"] = round(esperado, 1)
        import torch

        res["entorno"] = vb.collect_env_info(PACKAGES)
        sampler = vb.VramSampler(interval_s=0.1)
        res["vram_linea_base_mib"] = {"nvml": round(sampler.baseline_mib, 1), "nvidia_smi": vb.vram_used_mib_smi(), "total": round(sampler.total_mib)}
        with sampler:
            torch.cuda.reset_peak_memory_stats()
            # ---------------------------------------------------------------- carga
            t0 = time.perf_counter()
            m = cb_es.ChatterboxEs(Path(args.modelo), device="cuda", text_norm=args.texto)
            sync()
            res["carga_modelo_s"] = round(time.perf_counter() - t0, 2)
            res["carga_s3gen_claves_ausentes"] = m.load_report["s3gen_missing"]
            res["carga_s3gen_claves_inesperadas"] = m.load_report["s3gen_unexpected"]
            res["vram_tras_carga"] = {
                "nvml_mib": round(sampler.read_mib(), 1),
                "torch_allocated_mib": round(torch.cuda.memory_allocated() / 2**20, 1),
                "torch_reserved_mib": round(torch.cuda.max_memory_reserved() / 2**20, 1),
            }
            print(f"modelo cargado en {res['carga_modelo_s']} s | VRAM (NVML) {res['vram_tras_carga']['nvml_mib']} MiB", flush=True)

            # ---------------------------------------------------------------- referencia (caché)
            sync()
            t0 = time.perf_counter()
            m.prepare_conditionals(Path(args.ref_wav), exaggeration=args.exaggeration)
            m._conditioning_embedding(args.exaggeration)
            sync()
            res["preparar_referencia_s"] = round(time.perf_counter() - t0, 3)
            print(f"referencia preparada en {res['preparar_referencia_s']} s", flush=True)

            frases = vb.MEASURE_SENTENCES
            cfg0 = STREAM_CFGS[args.cfg_principal]

            if args.fase == "fria":
                ttfa, total, wav, n, times = stream_request(m, frases[2], cfg0, 1, gen_kw)
                res["peticion_fria"] = {"ttfa_s": round(ttfa, 3), "total_s": round(total, 3), "audio_s": round(len(wav) / m.sr, 2), "config": args.cfg_principal}
                ttfa2, total2, wav2, n2, _ = stream_request(m, frases[3], cfg0, 2, gen_kw)
                res["segunda_peticion"] = {"ttfa_s": round(ttfa2, 3), "total_s": round(total2, 3), "audio_s": round(len(wav2) / m.sr, 2)}
                print(f"1ª petición (fría): TTFA {ttfa:.3f} s, total {total:.3f} s | 2ª: TTFA {ttfa2:.3f} s", flush=True)
            elif args.fase == "optim":
                # Optimizaciones baratas del camino del primer audio (sin tocar el modelo): TF32, menos pasos CFM y referencia
                # más corta para el decodificador. Las dos últimas pueden afectar a la calidad: se generan muestras para oírlas.
                for i in range(3):
                    stream_request(m, frases[i], STREAM_CFGS["p5"], 100 + i, gen_kw)
                variantes = [
                    ("p5_base", dict(cfg="p5", tf32=False, cfm=None, prompt=None)),
                    ("p5_tf32", dict(cfg="p5", tf32=True, cfm=None, prompt=None)),
                    ("p5_tf32_cfm5", dict(cfg="p5", tf32=True, cfm=5, prompt=None)),
                    ("p5_tf32_cfm5_ref3s", dict(cfg="p5", tf32=True, cfm=5, prompt=3.0)),
                    ("p5_tf32_cfm3_ref3s", dict(cfg="p5", tf32=True, cfm=3, prompt=3.0)),
                    ("p10_tf32_cfm5", dict(cfg="p10", tf32=True, cfm=5, prompt=None)),
                    ("p10_tf32_cfm3", dict(cfg="p10", tf32=True, cfm=3, prompt=None)),
                ]
                if args.variantes:
                    variantes = [x for x in variantes if x[0] in args.variantes.split(",")]
                salida_opt = {}
                for nombre, v in variantes:
                    torch.set_float32_matmul_precision("high" if v["tf32"] else "highest")
                    m.limit_decoder_prompt(v["prompt"])
                    cfg = dict(STREAM_CFGS[v["cfg"]])
                    if v["cfm"]:
                        cfg["n_cfm_timesteps"] = v["cfm"]
                    stream_request(m, frases[0], cfg, 99, gen_kw)  # recalienta tras cambiar la configuración
                    tt = []
                    for rep in range(3):
                        for i, frase in enumerate(frases):
                            ttfa, total, wav, n, times = stream_request(m, frase, cfg, 6000 + 10 * rep + i, gen_kw, ttfa_only=True)
                            tt.append(ttfa)
                    rr = []
                    for i in range(0, 16, 2):
                        ttfa, total, wav, n, times = stream_request(m, frases[i], cfg, 7000 + i, gen_kw)
                        rr.append(total / (len(wav) / m.sr))
                    salida_opt[nombre] = {**v, "ttfa_s": vb.summarize(tt), "rtf": vb.summarize(rr)}
                    print(f"{nombre:22s}: TTFA p50 {vb.summarize(tt)['p50'] * 1000:.0f} ms, p95 {vb.summarize(tt)['p95'] * 1000:.0f} ms | RTF p50 {vb.summarize(rr)['p50']:.3f}", flush=True)
                    if nombre in ("p5_tf32_cfm5", "p5_tf32_cfm5_ref3s", "p5_tf32_cfm3_ref3s"):
                        for i, frase in enumerate(vb.SAMPLE_SENTENCES, start=1):
                            ttfa, total, wav, n, times = stream_request(m, frase, cfg, 4242 + i, gen_kw)
                            vb.write_wav(vb.samples_dir() / "extra" / f"B_chatterbox_{nombre}_{i:02d}.wav", wav, m.sr)
                torch.set_float32_matmul_precision("highest")
                m.limit_decoder_prompt(None)
                res["optimizaciones"] = salida_opt
            elif args.fase == "contencion":
                # TTFA con otra carga compartiendo la GPU (proceso aparte que multiplica matrices fp16 con un ciclo de trabajo dado).
                for i in range(3):
                    stream_request(m, frases[i], STREAM_CFGS["p10"], 100 + i, gen_kw)
                hog = Path(__file__).resolve().parents[1] / "common" / "carga_gpu.py"
                resultados = {}
                for duty in (0, 50, 100):
                    proc = None
                    if duty:
                        proc = subprocess.Popen([sys.executable, str(hog), str(duty), "900"], stdout=subprocess.PIPE, text=True)
                        assert proc.stdout.readline().strip() == "listo"
                        time.sleep(1.0)
                    try:
                        for nombre in ("p5", "p10"):
                            tt = []
                            for rep in range(2):
                                for i, frase in enumerate(frases):
                                    ttfa, total, wav, n, times = stream_request(m, frase, STREAM_CFGS[nombre], 8000 + 10 * rep + i, gen_kw, ttfa_only=True)
                                    tt.append(ttfa)
                            resultados[f"carga{duty}_{nombre}"] = {"ciclo_carga_pct": duty, "config": nombre, "ttfa_s": vb.summarize(tt)}
                            r = resultados[f"carga{duty}_{nombre}"]
                            print(f"carga {duty:3d} %, {nombre}: TTFA p50 {r['ttfa_s']['p50'] * 1000:.0f} ms, p95 {r['ttfa_s']['p95'] * 1000:.0f} ms", flush=True)
                        rr = []
                        for i in range(0, 16, 2):
                            ttfa, total, wav, n, times = stream_request(m, frases[i], STREAM_CFGS["p10"], 9000 + i, gen_kw)
                            rr.append(total / (len(wav) / m.sr))
                        resultados[f"carga{duty}_p10"]["rtf"] = vb.summarize(rr)
                        print(f"carga {duty:3d} %, p10: RTF p50 {vb.summarize(rr)['p50']:.3f}", flush=True)
                    finally:
                        if proc:
                            proc.kill()
                            proc.wait()
                res["contencion"] = resultados
            elif args.fase == "velocidad":
                # ¿Se puede pedir 1,1x / 1,25x? Chatterbox no tiene parámetro de velocidad; solo hay controles indirectos
                # (cfg_weight «ritmo» y exaggeration). Se mide su efecto real en la duración del audio (mismas semillas).
                for i in range(2):
                    m.synthesize(frases[i], seed=100 + i, **gen_kw)
                variantes = {
                    "base_cfg0.5_exag0.5": dict(cfg_weight=0.5, exaggeration=0.5),
                    "cfg0.3": dict(cfg_weight=0.3, exaggeration=0.5),
                    "cfg0.8": dict(cfg_weight=0.8, exaggeration=0.5),
                    "cfg0.0": dict(cfg_weight=0.0, exaggeration=0.5),
                    "exag0.3": dict(cfg_weight=0.5, exaggeration=0.3),
                    "exag0.8": dict(cfg_weight=0.5, exaggeration=0.8),
                    "exag0.8_cfg0.3": dict(cfg_weight=0.3, exaggeration=0.8),
                    "exag1.2_cfg0.3": dict(cfg_weight=0.3, exaggeration=1.2),
                    "cfg1.0": dict(cfg_weight=1.0, exaggeration=0.5),
                    "cfg1.5": dict(cfg_weight=1.5, exaggeration=0.5),
                    "cfg2.5": dict(cfg_weight=2.5, exaggeration=0.5),
                }
                if args.variantes:
                    variantes = {k: v for k, v in variantes.items() if k.startswith("base") or k in args.variantes.split(",")}
                usadas = list(range(0, 20, 2))
                semillas = [11, 12]
                base_dur: dict = {}
                salida_vel = {}
                for nombre, kw in variantes.items():
                    durs = {}
                    for i in usadas:
                        for sd in semillas:
                            wav = m.synthesize(frases[i], seed=sd * 100 + i, **kw)
                            durs.setdefault(i, []).append(len(wav) / m.sr)
                    if nombre.startswith("base"):
                        base_dur = {i: float(np.mean(v)) for i, v in durs.items()}
                    # una muestra por variante para oír el efecto (y los artefactos con cfg_weight altos)
                    wav = m.synthesize(vb.SAMPLE_SENTENCES[1], seed=4243, **kw)
                    vb.write_wav(vb.samples_dir() / "velocidad" / f"B_chatterbox_{nombre}_02.wav", wav, m.sr)
                    ratios = [base_dur[i] / float(np.mean(v)) for i, v in durs.items()]  # >1 = más rápido que la base
                    salida_vel[nombre] = {**kw, "velocidad_efectiva_mediana": round(float(np.median(ratios)), 3), "velocidad_efectiva_min": round(min(ratios), 3), "velocidad_efectiva_max": round(max(ratios), 3)}
                    print(f"{nombre:18s}: velocidad efectiva mediana {np.median(ratios):.3f}x (min {min(ratios):.2f}, max {max(ratios):.2f})", flush=True)
                res["velocidad_controles_indirectos"] = salida_vel
            else:
                # ------------------------------------------------------------ calentamiento
                for i in range(3):
                    stream_request(m, frases[i], cfg0, 100 + i, gen_kw)
                m.synthesize(frases[3], seed=7, **gen_kw)

                if args.ab_texto:
                    salidas_ab = []
                    for norma in ("space", "pip"):
                        m.text_norm = norma
                        for i, frase in enumerate(vb.SAMPLE_SENTENCES, start=1):
                            sync()
                            t0 = time.perf_counter()
                            wav = m.synthesize(frase, seed=4242 + i, **gen_kw)
                            sync()
                            p = vb.samples_dir() / "extra" / f"B_chatterbox_{norma}_{i:02d}.wav"
                            vb.write_wav(p, wav, m.sr)
                            salidas_ab.append({"wav": str(p), "norma": norma, "audio_s": round(len(wav) / m.sr, 2), "tiempo_s": round(time.perf_counter() - t0, 2)})
                            print(f"A/B texto {norma} {i}: {len(wav) / m.sr:.1f} s", flush=True)
                    res["ab_texto"] = salidas_ab
                    m.text_norm = args.texto
                    args.solo_muestras = True
                    args.sin_muestras = True

                if not args.solo_muestras:
                    registros = []
                    # -------------------------------------------------------- streaming, configuración principal (con RTF)
                    ttfas, rtfs, xrts = [], [], []
                    for rep in range(args.repeticiones):
                        for i, frase in enumerate(frases):
                            ttfa, total, wav, n, times = stream_request(m, frase, cfg0, 1000 + 10 * rep + i, gen_kw)
                            dur = len(wav) / m.sr
                            ttfas.append(ttfa)
                            rtfs.append(total / dur)
                            xrts.append(dur / total)
                            registros.append({"modo": f"stream_{args.cfg_principal}", "rep": rep, "frase": i, "palabras": vb.count_words(frase), "ttfa_s": round(ttfa, 4), "total_s": round(total, 4), "audio_s": round(dur, 3), "rtf": round(total / dur, 4), "n_chunks": n})
                    res["stream_principal"] = {"config": {"nombre": args.cfg_principal, **cfg0}, "ttfa_s": vb.summarize(ttfas), "rtf": vb.summarize(rtfs), "xrt": vb.summarize(xrts)}
                    s = res["stream_principal"]
                    print(f"stream {args.cfg_principal}: TTFA p50 {s['ttfa_s']['p50'] * 1000:.0f} ms, p95 {s['ttfa_s']['p95'] * 1000:.0f} ms | RTF p50 {s['rtf']['p50']:.3f} p95 {s['rtf']['p95']:.3f} ({s['xrt']['p50']:.2f}x tiempo real)", flush=True)

                    # -------------------------------------------------------- desglose de la latencia (con sincronizaciones: solo diagnóstico)
                    desgloses = []
                    for i in range(0, 20, 2):
                        tr: dict = {}
                        g = m.stream(frases[i], seed=5000 + i, trace=tr, **cfg0, **gen_kw)
                        next(g)
                        g.close()
                        t0 = tr["t0"]
                        tt = tr["t_tokens"]
                        pasos = np.diff([tr["t_prefill_done"]] + tt)
                        desgloses.append({"frase": i, "prefill_tokens": tr["prefill_tokens"], "prefill_ms": (tr["t_prefill_done"] - t0) * 1000, "ms_por_paso_T3": float(np.mean(pasos) * 1000), "pasos_hasta_primer_chunk": len(tt), "s3gen_primer_chunk_ms": (tr["emit"][0][1] - tr["emit"][0][0]) * 1000, "ttfa_ms": (tr["emit"][0][1] - t0) * 1000})
                    res["desglose_primer_chunk"] = {
                        "prefill_ms_mediana": float(np.median([d["prefill_ms"] for d in desgloses])),
                        "ms_por_paso_T3_mediana": float(np.median([d["ms_por_paso_T3"] for d in desgloses])),
                        "pasos_hasta_primer_chunk": desgloses[0]["pasos_hasta_primer_chunk"],
                        "s3gen_primer_chunk_ms_mediana": float(np.median([d["s3gen_primer_chunk_ms"] for d in desgloses])),
                        "ttfa_ms_mediana": float(np.median([d["ttfa_ms"] for d in desgloses])),
                        "detalle": desgloses,
                    }
                    d = res["desglose_primer_chunk"]
                    print(f"desglose 1er chunk: prefill {d['prefill_ms_mediana']:.0f} ms + {d['pasos_hasta_primer_chunk']} pasos T3 x {d['ms_por_paso_T3_mediana']:.1f} ms + S3Gen {d['s3gen_primer_chunk_ms_mediana']:.0f} ms = {d['ttfa_ms_mediana']:.0f} ms", flush=True)

                    # -------------------------------------------------------- TTFA de otras configuraciones (se corta tras el primer chunk)
                    barrido = {}
                    for nombre, cfg in STREAM_CFGS.items():
                        tt = []
                        for rep in range(args.repeticiones_ttfa):
                            for i, frase in enumerate(frases):
                                ttfa, total, wav, n, times = stream_request(m, frase, cfg, 2000 + 10 * rep + i, gen_kw, ttfa_only=True)
                                tt.append(ttfa)
                                registros.append({"modo": f"ttfa_{nombre}", "rep": rep, "frase": i, "palabras": vb.count_words(frase), "ttfa_s": round(ttfa, 4)})
                        barrido[nombre] = {"config": cfg, "ttfa_s": vb.summarize(tt)}
                        print(f"TTFA {nombre}: p50 {barrido[nombre]['ttfa_s']['p50'] * 1000:.0f} ms, p95 {barrido[nombre]['ttfa_s']['p95'] * 1000:.0f} ms", flush=True)
                    res["barrido_ttfa"] = barrido

                    # -------------------------------------------------------- ruta oficial: frase completa (tiempo hasta el audio completo)
                    tt, rr = [], []
                    for i, frase in enumerate(frases):
                        sync()
                        t0 = time.perf_counter()
                        wav = m.synthesize(frase, seed=3000 + i, **gen_kw)
                        sync()
                        total = time.perf_counter() - t0
                        dur = len(wav) / m.sr
                        tt.append(total)
                        rr.append(total / dur)
                        registros.append({"modo": "frase_completa", "frase": i, "palabras": vb.count_words(frase), "total_s": round(total, 4), "audio_s": round(dur, 3), "rtf": round(total / dur, 4)})
                    res["frase_completa_sin_marca"] = {"tiempo_hasta_audio_completo_s": vb.summarize(tt), "rtf": vb.summarize(rr)}
                    print(f"frase completa: p50 {vb.summarize(tt)['p50']:.2f} s, p95 {vb.summarize(tt)['p95']:.2f} s | RTF p50 {vb.summarize(rr)['p50']:.3f}", flush=True)

                    # -------------------------------------------------------- cfg_weight = 0 (batch 1, sin guía): efecto en latencia
                    tt0, rr0 = [], []
                    kw0 = dict(gen_kw, cfg_weight=0.0)
                    for i, frase in enumerate(frases):
                        ttfa, total, wav, n, times = stream_request(m, frase, cfg0, 4000 + i, kw0)
                        tt0.append(ttfa)
                        rr0.append(total / (len(wav) / m.sr))
                    res["stream_cfg_weight_0"] = {"ttfa_s": vb.summarize(tt0), "rtf": vb.summarize(rr0), "nota": "batch 1 (sin secuencia sin condición)"}
                    print(f"cfg_weight=0: TTFA p50 {vb.summarize(tt0)['p50'] * 1000:.0f} ms p95 {vb.summarize(tt0)['p95'] * 1000:.0f} ms | RTF p50 {vb.summarize(rr0)['p50']:.3f}", flush=True)

                    # -------------------------------------------------------- coste de la marca de agua PerTh (CPU)
                    wav = m.synthesize(frases[14], seed=1, **gen_kw)
                    t0 = time.perf_counter()
                    m.watermark(wav)
                    t1 = time.perf_counter() - t0
                    t0 = time.perf_counter()
                    m.watermark(wav)
                    t2 = time.perf_counter() - t0
                    res["marca_agua_perth"] = {"audio_s": round(len(wav) / m.sr, 2), "primera_s": round(t1, 3), "segunda_s": round(t2, 3), "nota": "CPU; solo en la ruta de frase completa, omitida en streaming"}
                    print(f"marca de agua PerTh: {t2:.3f} s para {len(wav) / m.sr:.1f} s de audio", flush=True)
                    res["registros"] = registros

                # ------------------------------------------------------------ muestras para escuchar
                if not args.sin_muestras:
                    base = vb.samples_dir() / args.subcarpeta_muestras if args.subcarpeta_muestras else vb.samples_dir()
                    salidas = []
                    for i, frase in enumerate(vb.SAMPLE_SENTENCES, start=1):
                        sync()
                        t0 = time.perf_counter()
                        wav = m.synthesize(frase, seed=4242 + i, watermark=True, **gen_kw)
                        sync()
                        el = time.perf_counter() - t0
                        p = base / f"{args.prefijo_muestras}_{i:02d}.wav"
                        vb.write_wav(p, wav, m.sr)
                        item = {"wav": str(p), "frase": frase, "audio_s": round(len(wav) / m.sr, 2), "tiempo_s": round(el, 2), "pico": round(float(np.max(np.abs(wav))), 3), "ruta": "frase completa (oficial) con marca de agua"}
                        if args.muestras_stream:
                            ttfa, total, w2, n, _ = stream_request(m, frase, cfg0, 4242 + i, gen_kw)
                            p2 = base / f"{args.prefijo_muestras}_stream_{i:02d}.wav"
                            vb.write_wav(p2, w2, m.sr)
                            item["wav_stream"] = str(p2)
                            item["ttfa_stream_s"] = round(ttfa, 3)
                        salidas.append(item)
                        print(f"muestra {i}: {p.name} ({len(wav) / m.sr:.1f} s, pico {np.max(np.abs(wav)):.2f})", flush=True)
                    res["muestras"] = salidas

            # ---------------------------------------------------------------- VRAM pico
            sync()
            res["vram_pico"] = {
                "torch_max_allocated_mib": round(torch.cuda.max_memory_allocated() / 2**20, 1),
                "torch_max_reserved_mib": round(torch.cuda.max_memory_reserved() / 2**20, 1),
                "nvml_pico_total_mib": round(sampler.peak_mib, 1),
                "nvidia_smi_ahora_mib": vb.vram_used_mib_smi(),
                "nvml_pico_menos_linea_base_mib": round(sampler.peak_mib - sampler.baseline_mib, 1),
            }
            print("VRAM pico:", json.dumps(res["vram_pico"]), flush=True)
            del m
            gc.collect()
            torch.cuda.empty_cache()

    out = vb.save_json(salida, res)
    print("resultados ->", out)


if __name__ == "__main__":
    main()
