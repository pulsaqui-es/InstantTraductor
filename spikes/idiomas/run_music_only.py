"""Música sin diálogo (FR-016, SC-007): cuántas frases inventa cada candidato en 10 min de música de dominio público.

Monta 10 min de música (las 4 pistas de Musopen, con fundidos) a dos niveles: **fuerte** (RMS -22 dBFS, igual que el
diálogo del corpus) y **de fondo** (-32 dBFS). Pasa el flujo por la misma tubería (Silero + ASR) y cuenta los segmentos
que abre el VAD y los que acaban con texto. Con SenseVoice anota además la etiqueta de evento del segmento (``BGM``...).

Uso: ``uv run python run_music_only.py --model parakeet_ja --lang ja`` (varios ``--model`` seguidos de un único ``--lang``).
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import soundfile as sf

from idiomas.asr import CANDIDATES, make_pipeline, make_recognizer, simulate
from idiomas.audio import SAMPLE_RATE, music_loop, rms_db
from idiomas.paths import RESULTS_DIR, music_dir

MINUTES = 10
LEVELS = {"fuerte": -22.0, "fondo": -32.0}


def build(level_db: float, vocal: bool = False) -> np.ndarray:
    rng = np.random.default_rng(5)
    tracks = [sf.read(p, dtype="float32")[0] for p in sorted(music_dir().glob("vocal*.wav" if vocal else "track*.wav"))]
    x = music_loop(tracks, MINUTES * 60 * SAMPLE_RATE, rng)
    return (x * 10 ** ((level_db - rms_db(x)) / 20)).astype(np.float32)


def raw_decode(key: str, lang: str, rec, x: np.ndarray, seg_s: float = 4.0) -> dict:
    """Peor caso: la música llega al ASR sin puerta de VAD, en trozos de ``seg_s`` s. Cuenta los trozos con texto."""
    cand = CANDIDATES[key]
    n = int(seg_s * SAMPLE_RATE)
    texts = []
    total = 0
    for i in range(0, len(x) - n + 1, n):
        seg = x[i : i + n]
        total += 1
        if cand.kind == "stream":
            st = rec.create_stream()
            if key.startswith("nemotron"):
                st.set_option("language", lang)
            st.accept_waveform(SAMPLE_RATE, seg)
            st.accept_waveform(SAMPLE_RATE, np.zeros(int(SAMPLE_RATE * cand.chunk_ms / 1000), dtype=np.float32))
            st.input_finished()
            while rec.is_ready(st):
                rec.decode_stream(st)
            text = rec.get_result_all(st).text.strip()
        else:
            st = rec.create_stream()
            st.accept_waveform(SAMPLE_RATE, seg)
            rec.decode_stream(st)
            text = st.result.text.strip()
        if text:
            texts.append(text)
    return {"chunks": total, "chunks_with_text": len(texts), "chars": sum(len(t) for t in texts), "examples": texts[:5]}


def vad_stats(x: np.ndarray) -> dict:
    from idiomas.paths import silero_model_path
    from idiomas.vad import FRAME, SileroOnnx

    m = SileroOnnx(silero_model_path())
    probs = np.array([m.prob(x[i * FRAME : (i + 1) * FRAME]) for i in range(len(x) // FRAME)])
    return {"max_prob": float(probs.max()), "frames_over_0.5_pct": float((probs >= 0.5).mean() * 100), "frames_over_0.3_pct": float((probs >= 0.3).mean() * 100)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", nargs="+", required=True)
    ap.add_argument("--lang", required=True)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--vocal", action="store_true", help="pistas con voz cantada (aria y coros) en lugar de orquesta")
    args = ap.parse_args()
    out = {}
    for key in args.model:
        rec = make_recognizer(key, args.lang, args.threads)
        res = {}
        for name, level in LEVELS.items():
            sim = simulate(make_pipeline(key, args.lang, rec), build(level, args.vocal))
            finals = [e for e in sim["events"] if e["type"] == "final"]
            texts = [e["text"] for e in finals if e["text"]]
            segs = len(finals) + sum(1 for e in sim["events"] if e["type"] == "discard")
            audio = build(level, args.vocal)
            res[name] = {
                # con voz cantada solo interesa la tubería completa (el peor caso sin VAD ya está medido con la orquesta)
                "raw_decode": {"chunks": 0, "chunks_with_text": 0, "chars": 0, "examples": []}
                if args.vocal
                else raw_decode(key, args.lang, rec, audio),
                "vad": vad_stats(audio),
                "level_dbfs": level,
                "vad_segments": segs,
                "finals_with_text": len(texts),
                "finals_per_10min": len(texts) * 10 / MINUTES,
                "seg_seconds": float(sum(e["span"][1] - e["span"][0] for e in finals)),
                "events": sorted({e.get("event", "") for e in finals if e.get("event")}),
                "texts": texts[:12],
                "rtf": sim["rtf"],
            }
            print(f"[{key} {args.lang} música {name}] segmentos VAD {segs}, con texto {len(texts)}  {texts[:3]}  sin VAD: {res[name]['raw_decode']['chunks_with_text']}/{res[name]['raw_decode']['chunks']} trozos con texto; Silero máx {res[name]['vad']['max_prob']:.2f}", flush=True)
        out[key] = res
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"music_only_{'vocal_' if args.vocal else ''}{args.lang}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
