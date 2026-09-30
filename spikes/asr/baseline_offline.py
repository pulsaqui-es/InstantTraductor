"""WER de referencia SIN segmentación ni VAD: cada enunciado completo de una vez.

Sirve para aislar cuánto WER añade la tubería (puerta de VAD, cortes, vaciados) frente a lo que da
cada modelo por sí solo sobre estos mismos 73 enunciados de LibriSpeech.

- Motor A (CPU): sherpa-onnx con el enunciado entero y relleno final (``--engine a``).
- Motor B (GPU, con candado): faster-whisper con el enunciado entero (``--engine b``).

Uso (desde ``spikes/asr``)::

    uv run python baseline_offline.py --engine a --chunk-ms 160 --blank-penalty 1
    uv run python baseline_offline.py --engine b --beam 5
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time

import numpy as np

from asrspike import data, metrics, paths
from asrspike.data import SAMPLE_RATE


def run_a(utts, chunk_ms: int, blank_penalty: float, threads: int) -> tuple[list[str], float]:
    from asrspike.engine_a import make_recognizer

    rec = make_recognizer(chunk_ms, threads=threads, blank_penalty=blank_penalty)
    tail = np.zeros(int(0.66 * SAMPLE_RATE), dtype=np.float32)
    hyps, t0 = [], time.perf_counter()
    for u in utts:
        s = rec.create_stream()
        s.accept_waveform(SAMPLE_RATE, u.samples)
        s.accept_waveform(SAMPLE_RATE, tail)
        s.input_finished()
        while rec.is_ready(s):
            rec.decode_stream(s)
        hyps.append(rec.get_result_all(s).text.strip())
    return hyps, time.perf_counter() - t0


def run_b(utts, beams: list[int]) -> dict[int, tuple[list[str], float, dict]]:
    """Enunciados enteros con faster-whisper, un haz tras otro bajo UN solo candado de GPU."""
    from asrspike.engine_b import load_model
    from asrspike.gpumem import GpuProcMemSampler

    results: dict[int, tuple[list[str], float, dict]] = {}
    with paths.gpu_lock(timeout_s=30 * 60):
        model = load_model()
        sampler = GpuProcMemSampler()
        sampler.start()
        seg, _ = model.transcribe(utts[0].samples, language="en", beam_size=1, without_timestamps=True)
        list(seg)
        for beam in beams:
            hyps, t0 = [], time.perf_counter()
            for u in utts:
                seg, _ = model.transcribe(
                    u.samples,
                    language="en",
                    beam_size=beam,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    without_timestamps=True,
                    vad_filter=False,
                )
                hyps.append(" ".join(s.text.strip() for s in seg).strip())
            results[beam] = (hyps, time.perf_counter() - t0, {"peak_mb": max((m for _, m in sampler.samples), default=None)})
        sampler.stop()
    return results


def summarize(label: str, engine: str, cfg: dict, utts, hyps: list[str], elapsed: float, extra: dict | None = None) -> None:
    """Calcula WER y puntuación de una pasada completa, la imprime y la guarda en results/."""
    refs = [u.text for u in utts]
    audio_s = sum(u.duration for u in utts)
    wer = metrics.corpus_wer(refs, hyps)
    per = metrics.per_utterance_wer(refs, hyps)
    prof = [metrics.punctuation_profile(h) for h in hyps]
    words = sum(p["words"] for p in prof) or 1
    out = {
        "label": label,
        "when": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine": engine,
        "kind": "baseline_whole_utterances",
        "config": cfg,
        "utterances": len(utts),
        "audio_s": round(audio_s, 1),
        "elapsed_s": round(elapsed, 1),
        "rtf": round(elapsed / audio_s, 3),
        "wer": wer,
        "per_utterance_wer_mean": float(np.mean(per)),
        "punctuation": {
            "commas_per_100_words": 100 * sum(p["commas"] for p in prof) / words,
            "terminal_marks_per_100_words": 100 * sum(p["terminal_marks"] for p in prof) / words,
            "texts_ending_with_terminal_pct": 100 * sum(p["ends_with_terminal"] for p in prof) / len(prof),
        },
        **(extra or {}),
    }
    print(f"== {label} ==")
    print(
        f"WER normalizado {100 * wer['wer']:.2f} % (S {wer['sub']} D {wer['del']} I {wer['ins']} de {wer['ref_words']}) | "
        f"{len(utts)} enunciados, {audio_s:.0f} s de audio en {elapsed:.0f} s (RTF {elapsed / audio_s:.3f})"
    )
    pu = out["punctuation"]
    print(
        f"puntuación: {pu['commas_per_100_words']:.1f} comas y {pu['terminal_marks_per_100_words']:.1f} marcas finales "
        f"por 100 palabras; textos que acaban en . ? ! = {pu['texts_ending_with_terminal_pct']:.0f} %",
        flush=True,
    )
    paths.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (paths.RESULTS_DIR / f"{label}.json").write_text(
        json.dumps({**out, "texts": hyps}, indent=1, ensure_ascii=False, default=float), encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["a", "b"], required=True)
    ap.add_argument("--chunk-ms", type=int, default=160)
    ap.add_argument("--blank-penalty", type=float, default=1.0)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--beam", type=int, nargs="+", default=[5], help="motor B: uno o varios tamaños de haz")
    ap.add_argument("--label", default=None)
    args = ap.parse_args()

    utts = data.load_utterances()
    if args.engine == "a":
        hyps, elapsed = run_a(utts, args.chunk_ms, args.blank_penalty, args.threads)
        label = args.label or f"baseline_a{args.chunk_ms}_bp{args.blank_penalty:g}"
        cfg = {"chunk_ms": args.chunk_ms, "blank_penalty": args.blank_penalty, "threads": args.threads}
        summarize(label, "A", cfg, utts, hyps, elapsed)
    else:
        for beam, (hyps, elapsed, mem) in run_b(utts, args.beam).items():
            label = args.label or f"baseline_b_beam{beam}"
            summarize(label, "B", {"beam": beam}, utts, hyps, elapsed, {"vram_peak_mb": mem["peak_mb"]})


if __name__ == "__main__":
    main()

