"""Mide un candidato de ASR sobre los flujos de un idioma (limpio y con música a -10 dB).

Uso: ``uv run python run_asr.py --model parakeet_ja --lang ja [--threads 2] [--conds clean,music] [--limit N]``

Guarda ``results/asr_<modelo>_<idioma>[_t<hilos>].json`` con CER, latencias, RTF, CPU, RAM y el texto de cada frase.
"""

from __future__ import annotations

import argparse
import json
import time
import unicodedata

import numpy as np
import psutil
import soundfile as sf

from idiomas.asr import CANDIDATES, make_pipeline, make_recognizer, simulate
from idiomas.paths import CORPUS_MANIFEST, RESULTS_DIR, corpus_dir
from idiomas.text import cer, per_item_cer


def pct(values: list[float], qs=(50, 95)) -> dict:
    arr = np.asarray([v for v in values if v is not None and not np.isnan(v)], dtype=float)
    if arr.size == 0:
        return {"n": 0, **{f"p{q}": None for q in qs}}
    return {"n": int(arr.size), **{f"p{q}": float(np.percentile(arr, q)) for q in qs}, "mean": float(arr.mean())}


def analyze(items: list[dict], lang: str, sim: dict) -> dict:
    events = sim["events"]
    finals = [e for e in events if e["type"] == "final"]
    partials = [e for e in events if e["type"] == "partial"]
    hyp: list[list[str]] = [[] for _ in items]
    last_t: list[float | None] = [None] * len(items)
    spurious: list[dict] = []
    for e in finals:
        mid = (e["span"][0] + e["span"][1]) / 2
        idx = next((i for i, it in enumerate(items) if it["start"] <= mid <= it["end"]), None)
        if idx is None:
            if e["text"]:
                spurious.append({"t": round(e["t"], 2), "span": [round(x, 2) for x in e["span"]], "text": e["text"]})
            continue
        if e["text"]:
            hyp[idx].append(e["text"])
            last_t[idx] = e["t"]
    hyps = [" ".join(h) for h in hyp]
    latency = [None if last_t[i] is None else last_t[i] - it["speech_end"] for i, it in enumerate(items)]
    # primer parcial desde el inicio real del habla (solo streaming)
    first_partial: list[float | None] = []
    for i, it in enumerate(items):
        lo = it["start"]
        hi = items[i + 1]["start"] if i + 1 < len(items) else 1e9
        ts = [p["t"] for p in partials if lo <= p["t"] < hi and p["t"] >= it["speech_start"]]
        first_partial.append(min(ts) - it["speech_start"] if ts else None)
    refs = [it["ref"] for it in items]
    total = cer(refs, hyps, lang)
    per = [per_item_cer(r, h, lang) for r, h in zip(refs, hyps, strict=True)]
    punct_chars = sum(1 for h in hyps for c in h if unicodedata.category(c).startswith("P"))
    ends = sum(1 for h in hyps if h and h.rstrip()[-1:] in "。.!?？！…")
    n_chars = sum(len(h) for h in hyps) or 1
    return {
        "cer": total,
        "cer_median_item": float(np.nanmedian(per)),
        "cer_p90_item": float(np.nanpercentile(per, 90)),
        "empty_clips": sum(1 for h in hyps if not h),
        "final_latency_s": pct(latency),
        "first_partial_s": pct([x for x in first_partial]),
        "segments": len(finals),
        "spurious_finals": len(spurious),
        "spurious": spurious[:20],
        "punct_per_100_chars": 100 * punct_chars / n_chars,
        "clips_ending_with_mark": ends,
        "decode_ms": pct(sim["decode_ms"]),
        "items": [
            {"id": it["id"], "ref": it["ref"], "hyp": h, "cer": None if np.isnan(c) else round(float(c), 4), "latency": None if lt is None else round(lt, 3)}
            for it, h, c, lt in zip(items, hyps, per, latency, strict=True)
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(CANDIDATES))
    ap.add_argument("--lang", required=True, choices=["ja", "zh", "ko"])
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--conds", default="clean,music")
    ap.add_argument("--limit", type=int, default=0, help="solo las N primeras frases (prueba de humo)")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    cand = CANDIDATES[args.model]
    if args.lang not in cand.langs:
        raise SystemExit(f"{args.model} no declara {args.lang}")
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    items = manifest["phrases"][args.lang]["items"]
    if args.limit:
        items = items[: args.limit]
    proc = psutil.Process()
    rss0 = proc.memory_info().rss
    t0 = time.perf_counter()
    rec = make_recognizer(args.model, args.lang, args.threads)
    load_s = time.perf_counter() - t0
    rss_loaded = proc.memory_info().rss
    out: dict = {
        "model": args.model,
        "label": cand.label,
        "lang": args.lang,
        "threads": args.threads,
        "load_s": load_s,
        "rss_loaded_mb": rss_loaded / 1e6,
        "rss_delta_mb": (rss_loaded - rss0) / 1e6,
        "n_phrases": len(items),
        "conds": {},
    }
    # Calentamiento: 10 s de audio que no cuentan
    wu = sf.read(corpus_dir() / f"stream_{args.lang}_clean.wav", dtype="float32", frames=10 * 16000)[0]
    simulate(make_pipeline(args.model, args.lang, rec), wu)
    for cond in args.conds.split(","):
        samples = sf.read(corpus_dir() / f"stream_{args.lang}_{cond}.wav", dtype="float32")[0]
        if args.limit:
            samples = samples[: int((items[-1]["end"] + 1.5) * 16000)]
        sim = simulate(make_pipeline(args.model, args.lang, rec), samples)
        res = analyze(items, args.lang, sim)
        res.update({k: sim[k] for k in ("audio_s", "compute_s", "rtf", "cpu_cores", "lateness_p95", "lateness_max", "t_vad", "t_asr")})
        out["conds"][cond] = res
        print(
            f"[{args.model} {args.lang} {cond}] CER {res['cer']['cer']:.2%}  final p50/p95 "
            f"{res['final_latency_s']['p50']}/{res['final_latency_s']['p95']}  RTF {sim['rtf']:.3f}  "
            f"cpu {sim['cpu_cores']:.2f}  segs {res['segments']}  espurias {res['spurious_finals']}",
            flush=True,
        )
    mem = proc.memory_info()
    out["rss_peak_mb"] = getattr(mem, "peak_wset", mem.rss) / 1e6
    RESULTS_DIR.mkdir(exist_ok=True)
    name = f"asr_{args.model}_{args.lang}_t{args.threads}{args.tag}.json"
    if not args.limit:
        (RESULTS_DIR / name).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("RAM tras cargar", round(out["rss_loaded_mb"]), "MB; pico", round(out["rss_peak_mb"]), "MB")


if __name__ == "__main__":
    main()
