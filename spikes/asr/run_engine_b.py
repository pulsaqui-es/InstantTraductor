"""Motor B: faster-whisper large-v3-turbo FP16 en GPU, por segmentos de VAD (comparación).

Toda la medición en GPU va envuelta en el candado de fichero ``%LOCALAPPDATA%\\InstantTraductor\\gpu.lock``
(paquete ``filelock``, espera hasta 30 min), porque otros obreros miden en la misma tarjeta. Una sola
ejecución toma el candado UNA vez, carga el modelo una vez y recorre todas las variantes pedidas.

Uso (desde ``spikes/asr``; antes ``fetch_assets.py`` y ``build_corpus.py``)::

    # una variante (por defecto: flujo con huecos, tiempo real, haz 1, corte forzado a 5 s)
    uv run python run_engine_b.py --label b_gapped_paced

    # varias variantes bajo un mismo candado: etiqueta:flujo:modo:haz:corte_forzado_s (0 = sin corte)
    uv run python run_engine_b.py \\
        --variant b_gapped_fast_cut8:gapped:fast:1:8 --variant b_gapped_fast_nocut:gapped:fast:1:0

Si CTranslate2 falla en sm_120 (Blackwell), el error exacto se imprime y se guarda en el JSON.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import traceback

import numpy as np

from asrspike import paths, realtime, sysinfo
from asrspike.analysis import analyze
from asrspike.data import SAMPLE_RATE, StreamPlan, cut_plan
from asrspike.gpumem import GpuProcMemSampler


def parse_variant(text: str) -> dict:
    label, stream, mode, beam, cut = text.split(":")
    return {"label": label, "stream": stream, "mode": mode, "beam": int(beam), "max_segment_s": float(cut)}


def run_variant(model, sampler: GpuProcMemSampler, v: dict, args, common: dict) -> dict:
    from asrspike.engine_b import WhisperPipeline

    plan = StreamPlan.load(paths.corpus_dir(), v["stream"])
    if args.limit:
        plan = cut_plan(plan, args.limit)
    paced = v["mode"] == "paced"
    max_seg = v["max_segment_s"] or None

    pipe = WhisperPipeline(
        model,
        beam_size=v["beam"],
        max_segment_s=max_seg,
        min_silence_ms=args.min_silence_ms,
        preroll_ms=args.preroll_ms,
    )
    # Calentamiento con la propia tubería (no cuenta).
    realtime.feed(plan.samples[: 10 * SAMPLE_RATE], pipe, args.device_chunk_ms, paced=False)
    pipe.reset()

    mark = len(sampler.samples)
    gpu_before_run = sysinfo.gpu_query()
    tracker = sysinfo.LoadTracker()
    tracker.start(sample_gpu=True)
    run = realtime.feed(plan.samples, pipe, args.device_chunk_ms, paced=paced)
    load = tracker.stop()
    gpu_after_run = sysinfo.gpu_query()
    time.sleep(0.4)
    vals = [m for _, m in sampler.samples[mark:]]
    pipe.close()

    result = analyze(plan, pipe.events, paced=paced)
    finals = [e for e in pipe.events if e["type"] == "final"]
    infer = [e["infer_ms"] for e in finals]
    queue_ms = [e["queue_ms"] for e in finals]
    seg_audio = [e["audio_s"] for e in finals]
    run["rtf_vad"] = pipe.t_vad / run["audio_s"]
    run["rtf_asr"] = (sum(infer) / 1000) / run["audio_s"]  # ocupación de la GPU por segundo de audio
    run["infer_ms"] = {
        "p50": float(np.percentile(infer, 50)),
        "p95": float(np.percentile(infer, 95)),
        "max": float(max(infer)),
        "mean": float(np.mean(infer)),
    }
    run["queue_ms"] = {
        "p50": float(np.percentile(queue_ms, 50)),
        "p95": float(np.percentile(queue_ms, 95)),
        "max": float(max(queue_ms)),
    }
    seg_lat = [i + q for i, q in zip(infer, queue_ms, strict=True)]  # desde que el segmento se cierra hasta tener texto
    run["segment_latency_ms"] = {
        "p50": float(np.percentile(seg_lat, 50)),
        "p95": float(np.percentile(seg_lat, 95)),
        "max": float(max(seg_lat)),
    }
    run["segment_audio_s"] = {
        "p50": float(np.percentile(seg_audio, 50)),
        "p95": float(np.percentile(seg_audio, 95)),
        "max": float(max(seg_audio)),
    }
    run["infer_rtf_per_segment"] = float(sum(infer) / 1000 / sum(seg_audio))
    out = {
        **common,
        "label": v["label"],
        "when": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine": "B",
        "stream": {"name": plan.name, "description": plan.description, "duration_s": plan.duration},
        "config": {**pipe.config, "device_chunk_ms": args.device_chunk_ms, "mode": v["mode"], "compute_type": "float16"},
        "run": run,
        "load": load,
        "result": result,
        "vram": {
            "process_dedicated_after_load_mb": common["process_dedicated_after_load_mb"],
            "process_dedicated_peak_mb": max(vals) if vals else None,
            "gpu_total_used_before_run_mb": gpu_before_run.get("memory_used_mb"),
            "gpu_total_used_after_run_mb": gpu_after_run.get("memory_used_mb"),
            "gpu_total_used_peak_during_run_mb": load.get("gpu_mem_used_mb_max"),
        },
    }
    print_summary(out, paced)
    if not args.no_save:
        paths.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        dest = paths.RESULTS_DIR / f"{v['label']}.json"
        dest.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
        print(f"-> {dest}", flush=True)
    return out


def print_summary(out: dict, paced: bool) -> None:
    run, load, result, vram = out["run"], out["load"], out["result"], out["vram"]
    print(f"== {out['label']} ({out['stream']['name']}, {out['config']['mode']}, haz {out['config']['beam_size']}, "
          f"corte {out['config']['max_segment_s']}) ==")
    print(f"audio {run['audio_s']:.1f} s | pared {run['wall_s']:.1f} s | RTF total {run['rtf']:.3f} "
          f"(VAD {run['rtf_vad']:.3f} + GPU {run['rtf_asr']:.3f})")
    print(f"inferencia por segmento p50/p95/max: {run['infer_ms']['p50']:.0f}/{run['infer_ms']['p95']:.0f}/{run['infer_ms']['max']:.0f} ms "
          f"(audio del segmento p50 {run['segment_audio_s']['p50']:.1f} s, p95 {run['segment_audio_s']['p95']:.1f} s; "
          f"RTF de inferencia {run['infer_rtf_per_segment']:.3f}) | espera en cola p95 {run['queue_ms']['p95']:.0f} ms")
    print(f"latencia por segmento (cola + inferencia, desde que se cierra) p50/p95/max: "
          f"{run['segment_latency_ms']['p50']:.0f}/{run['segment_latency_ms']['p95']:.0f}/{run['segment_latency_ms']['max']:.0f} ms")
    print(f"VRAM del proceso: tras cargar {vram['process_dedicated_after_load_mb']} MB, pico {vram['process_dedicated_peak_mb']} MB | "
          f"GPU total usada antes/después/pico {vram['gpu_total_used_before_run_mb']}/{vram['gpu_total_used_after_run_mb']}/"
          f"{vram['gpu_total_used_peak_during_run_mb']} MB")
    print(f"CPU propia: {load['own_cores_avg']} núcleos = {load['own_cpu_pct_of_machine']} % del equipo | "
          f"GPU util media {load.get('gpu_util_pct_mean')} % (máx. {load.get('gpu_util_pct_max')} %) | RAM {run['ram_rss_mb']} MB")
    print("  mayor consumo ajeno:", ", ".join(f"{p['name']} {p['cores_avg']}" for p in load["others_top"][:6]))
    w = result["wer"]
    print(f"WER normalizado {100 * w['wer']:.2f} % (S {w['sub']} D {w['del']} I {w['ins']} de {w['ref_words']} palabras) "
          f"| segmentos {result['n_segments']} (cortes forzados {result['n_forced_cuts']})")
    if paced:
        for key, name in (
            ("first_text_latency_s", "primer texto del segmento"),
            ("final_latency_s", "final (desde el fin real del habla)"),
            ("forced_cut_lag_s", "corte forzado -> texto"),
        ):
            p = result[key]
            print(f"  latencia {name}: p50 {p['p50']:.3f} s  p95 {p['p95']:.3f} s  (n={p['n']})")
    pu = result["punctuation"]
    print(f"  puntuación: {pu['commas_per_100_words']:.1f} comas y {pu['terminal_marks_per_100_words']:.1f} marcas finales por 100 palabras; "
          f"finales que acaban en . ? ! = {pu['finals_ending_with_terminal_pct']:.0f} %; empiezan en mayúscula = {pu['finals_starting_uppercase_pct']:.0f} %",
          flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", action="append", default=[], help="etiqueta:flujo:modo:haz:corte_forzado_s")
    ap.add_argument("--stream", choices=["gapped", "continuous"], default="gapped")
    ap.add_argument("--mode", choices=["paced", "fast"], default="paced")
    ap.add_argument("--beam", type=int, default=1, help="tamaño del haz (1 = voraz)")
    ap.add_argument("--max-segment-s", type=float, default=5.0, help="corte forzado; 0 = sin corte forzado")
    ap.add_argument("--label", default=None)
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--device-chunk-ms", type=float, default=32.0)
    ap.add_argument("--min-silence-ms", type=float, default=500.0)
    ap.add_argument("--preroll-ms", type=float, default=300.0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--lock-timeout-min", type=float, default=30.0)
    args = ap.parse_args()

    variants = [parse_variant(t) for t in args.variant]
    if not variants:
        variants = [
            {
                "label": args.label or f"b_{args.stream}_{args.mode}",
                "stream": args.stream,
                "mode": args.mode,
                "beam": args.beam,
                "max_segment_s": args.max_segment_s,
            }
        ]

    print(f"[B] esperando el candado de GPU ({paths.gpu_lock_path()}) ...", flush=True)
    t_wait = time.perf_counter()
    common: dict = {}
    sampler = None
    try:
        with paths.gpu_lock(timeout_s=args.lock_timeout_min * 60):
            waited = time.perf_counter() - t_wait
            print(f"[B] candado obtenido tras {waited:.1f} s", flush=True)
            common["gpu_lock_wait_s"] = round(waited, 1)
            common["system"] = sysinfo.system_snapshot()
            common["gpu_before_load"] = sysinfo.gpu_query()

            from asrspike.engine_b import load_model

            t0 = time.perf_counter()
            model = load_model(compute_type=args.compute_type)
            common["model_load_s"] = round(time.perf_counter() - t0, 2)
            import ctranslate2

            common["ctranslate2"] = {
                "version": ctranslate2.__version__,
                "cuda_devices": ctranslate2.get_cuda_device_count(),
                "supported_compute_types_cuda": sorted(ctranslate2.get_supported_compute_types("cuda")),
            }
            print(f"[B] CTranslate2 {common['ctranslate2']}; modelo cargado en {common['model_load_s']} s", flush=True)

            sampler = GpuProcMemSampler()
            sampler.start()
            # Primera transcripción (inicializa cuBLAS y los núcleos CUDA): se cronometra aparte.
            plan0 = StreamPlan.load(paths.corpus_dir(), variants[0]["stream"])
            t0 = time.perf_counter()
            segs, _ = model.transcribe(plan0.samples[: 6 * SAMPLE_RATE], language="en", beam_size=1, without_timestamps=True)
            list(segs)
            common["first_transcribe_s"] = round(time.perf_counter() - t0, 2)
            time.sleep(0.8)
            common["process_dedicated_after_load_mb"] = sampler.current_mb()
            common["gpu_after_load"] = sysinfo.gpu_query()
            print(f"[B] primera transcripción (6 s de audio): {common['first_transcribe_s']} s; "
                  f"VRAM del proceso {common['process_dedicated_after_load_mb']} MB", flush=True)

            for v in variants:
                run_variant(model, sampler, v, args, common)
    except Exception as exc:  # noqa: BLE001 - se documenta el error exacto de CTranslate2/CUDA
        err = {**common, "error": {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}}
        print(f"[B] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        if not args.no_save:
            paths.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            (paths.RESULTS_DIR / "b_error.json").write_text(json.dumps(err, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        raise SystemExit(1) from exc
    finally:
        if sampler is not None:
            sampler.stop()


if __name__ == "__main__":
    main()
