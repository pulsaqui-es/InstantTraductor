"""Motor A: Nemotron Speech Streaming EN 0.6B (int8) en sherpa-onnx, CPU, con Silero VAD delante.

Uso (desde ``spikes/asr``; antes ``fetch_assets.py`` y ``build_corpus.py``)::

    uv run python run_engine_a.py --stream gapped --chunk-ms 160 --mode paced --label a160_vad_gapped_paced
    uv run python run_engine_a.py --stream continuous --chunk-ms 560 --mode fast --threads 4

``--mode paced`` entrega el audio a ritmo de tiempo real (latencias válidas); ``--mode fast`` lo
entrega sin esperar (solo cómputo, RTF y WER; las latencias son las «algorítmicas», sin cómputo).
El resultado se guarda en ``results/<etiqueta>.json`` (y, con ``--save-events``, los eventos crudos
en ``results/events/``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json

import numpy as np

from asrspike import events_io, paths, realtime, sysinfo
from asrspike.analysis import analyze
from asrspike.data import SAMPLE_RATE, StreamPlan, cut_plan
from asrspike.engine_a import NemotronPipeline


def fmt(p: dict | None) -> str:
    if not p or not p.get("n"):
        return "-"
    return f"p50 {p['p50']:.3f} s  p95 {p['p95']:.3f} s  (n={p['n']})"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stream", choices=["gapped", "continuous"], default="gapped")
    ap.add_argument("--chunk-ms", type=int, choices=[80, 160, 560, 1120], default=160, help="trozo de decodificación")
    ap.add_argument("--policy", choices=["vad", "native"], default="vad", help="quién decide el fin de frase")
    ap.add_argument("--mode", choices=["paced", "fast"], default="paced")
    ap.add_argument("--threads", type=int, default=2, help="hilos de sherpa-onnx")
    ap.add_argument("--blank-penalty", type=float, default=1.0)
    ap.add_argument("--device-chunk-ms", type=float, default=32.0, help="tamaño del trozo de entrada (20-100 ms)")
    ap.add_argument("--min-silence-ms", type=float, default=500.0, help="silencio que cierra el turno (VAD)")
    ap.add_argument("--preroll-ms", type=float, default=300.0)
    ap.add_argument("--tail-pad-ms", type=float, default=None, help="relleno de ceros al vaciar (por defecto, un trozo)")
    ap.add_argument("--rule2", type=float, default=0.8, help="silencio del endpoint nativo (política native)")
    ap.add_argument("--max-segment-s", type=float, default=None, help="corte forzado (solo política vad)")
    ap.add_argument("--limit", type=int, default=None, help="usar solo los N primeros enunciados")
    ap.add_argument("--label", default=None)
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--save-events", action="store_true", help="guarda los eventos crudos (results/events/)")
    ap.add_argument("--show-text", type=int, default=0, help="imprime los N primeros textos finales")
    args = ap.parse_args()

    plan = StreamPlan.load(paths.corpus_dir(), args.stream)
    if args.limit:
        plan = cut_plan(plan, args.limit)
    label = args.label or f"a{args.chunk_ms}_{args.policy}_{args.stream}_{args.mode}"
    paced = args.mode == "paced"

    pipe = NemotronPipeline(
        args.chunk_ms,
        threads=args.threads,
        blank_penalty=args.blank_penalty,
        policy=args.policy,
        min_silence_ms=args.min_silence_ms,
        preroll_ms=args.preroll_ms,
        tail_pad_ms=args.tail_pad_ms,
        rule2_silence_s=args.rule2,
        max_segment_s=args.max_segment_s,
    )

    # Calentamiento: primeros 8 s en modo rápido (inicializa ONNX Runtime y las cachés); no cuenta.
    warm = plan.samples[: 8 * SAMPLE_RATE]
    realtime.feed(warm, pipe, args.device_chunk_ms, paced=False)
    pipe.reset()

    snapshot = sysinfo.system_snapshot()
    tracker = sysinfo.LoadTracker()
    tracker.start()
    run = realtime.feed(plan.samples, pipe, args.device_chunk_ms, paced=paced)
    load = tracker.stop()

    result = analyze(plan, pipe.events, paced=paced)
    run["compute_split_s"] = {"vad": pipe.t_vad, "asr": pipe.t_asr, "of_which_flush": pipe.t_flush}
    run["rtf_vad"] = pipe.t_vad / run["audio_s"]
    run["rtf_asr"] = pipe.t_asr / run["audio_s"]
    run["gate_open_fraction"] = pipe.gate_frames / max(pipe.total_frames, 1)
    run["flush_ms"] = {
        "p50": float(np.percentile(pipe.flush_ms, 50)) if pipe.flush_ms else None,
        "p95": float(np.percentile(pipe.flush_ms, 95)) if pipe.flush_ms else None,
    }
    out = {
        "label": label,
        "when": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine": "A",
        "stream": {"name": plan.name, "description": plan.description, "duration_s": plan.duration, "limit": args.limit},
        "config": {**pipe.config, "device_chunk_ms": args.device_chunk_ms, "mode": args.mode},
        "run": run,
        "load": load,
        "result": result,
        "system": snapshot,
    }

    print(f"== {label} ==")
    print(f"audio {run['audio_s']:.1f} s | pared {run['wall_s']:.1f} s | RTF {run['rtf']:.3f} "
          f"(vad {run['rtf_vad']:.3f} + asr {run['rtf_asr']:.3f}) | puerta abierta {100 * run['gate_open_fraction']:.0f} %")
    print(f"CPU propia: {load['own_cores_avg']} núcleos de media = {load['own_cpu_pct_of_machine']} % del equipo "
          f"| CPU del equipo {load['system_cpu_pct_mean']} % (máx. {load['system_cpu_pct_max']} %) "
          f"| otros: {load['others_total_cores_avg']} núcleos")
    print("  mayor consumo ajeno:", ", ".join(f"{p['name']} {p['cores_avg']}" for p in load["others_top"][:6]))
    print(f"retraso del alimentador p50/p95/max: {run['lateness_ms']['p50']:.1f}/{run['lateness_ms']['p95']:.1f}/{run['lateness_ms']['max']:.1f} ms"
          f" | vaciado del reconocedor p50/p95: {run['flush_ms']['p50'] or 0:.0f}/{run['flush_ms']['p95'] or 0:.0f} ms | RAM {run['ram_rss_mb']} MB (pico {run['ram_peak_mb']} MB)")
    print(f"push() por trozo p50/p95/p99/max: {run['push_ms']['p50']:.1f}/{run['push_ms']['p95']:.1f}/{run['push_ms']['p99']:.1f}/{run['push_ms']['max']:.1f} ms"
          f" | RTF por tercios {[round(x, 3) for x in run['rtf_by_third']]} | retraso medio por tercios (ms) {[round(x, 1) for x in run['lateness_mean_ms_by_third']]}")
    w = result["wer"]
    print(f"WER normalizado {100 * w['wer']:.2f} % (S {w['sub']} D {w['del']} I {w['ins']} de {w['ref_words']} palabras) "
          f"| segmentos {result['n_segments']} (cortes forzados o a mitad de habla {result['n_forced_cuts']}; descartados {result['n_discarded']})")
    print(f"  latencias{' (algorítmicas: modo rápido, sin cómputo)' if not paced else ''}:")
    print(f"    primer parcial           {fmt(result['first_partial_latency_s'])}")
    print(f"    final (desde fin real)   {fmt(result['final_latency_s'])}")
    print(f"    texto completo           {fmt(result['text_complete_latency_s'])}")
    bd = result["latency_breakdown"]
    print(f"    desglose del final: decisión {fmt(bd['vad_delay_s'])} ; después de decidir {fmt(bd['post_decision_s'])}")
    if result["utterance"]:
        print(f"    por enunciado: primer texto {fmt(result['utterance']['first_text_latency_s'])} ; final {fmt(result['utterance']['final_latency_s'])}")
    print(f"  parciales: retracción en {100 * (result['partial_retraction_rate'] or 0):.1f} % de {result['partial_transitions']} transiciones; "
          f"cola inestable p95 {result['partial_unstable_tail_chars']['p95']:.0f} car.; acaban a mitad de palabra "
          f"{100 * (result['partial_mid_word_rate'] or 0):.1f} %; final = último parcial en {result['final_equals_last_partial_pct'] or 0:.0f} % de los segmentos")
    pu = result["punctuation"]
    print(f"  puntuación: {pu['commas_per_100_words']:.1f} comas y {pu['terminal_marks_per_100_words']:.1f} marcas finales por 100 palabras; "
          f"finales que acaban en . ? ! = {pu['finals_ending_with_terminal_pct']:.0f} %; empiezan en mayúscula = {pu['finals_starting_uppercase_pct']:.0f} %")

    for row in result["segments"][: args.show_text]:
        print(f"  [{row['emitted_at']:7.2f}] {row['text']}")

    if not args.no_save:
        paths.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        dest = paths.RESULTS_DIR / f"{label}.json"
        dest.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
        print(f"-> {dest}")
        if args.save_events:
            print(f"-> {events_io.save_events(label, pipe.events)}")


if __name__ == "__main__":
    main()
