"""Filtro de idioma (FR-003, SC-003b): mide cómo reconocer que un segmento de 1-6 s está en el idioma elegido.

Para cada recorte (ja/zh/ko: 50 cada uno; es y en: 30 cada uno; limpios y con música a -10 dB) guarda:
- logits de Whisper tiny y base (los 99 idiomas; se guardan los de ja, zh, ko, es, en y el top-1 completo), con el tiempo
  de reloj y de CPU de cada decisión;
- el idioma de sherpa-onnx (``SpokenLanguageIdentification``) como contraste de la implementación propia;
- SenseVoice-Small con idioma automático (etiqueta ``<|ja|>``...) y con idioma fijado (fracción de escritura correcta).
``report_lid.py`` combina esto en las tablas (conjuntos restringidos, umbrales).

Uso: ``uv run python run_lid.py [--threads 1]``
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import soundfile as sf

from idiomas.lid import WhisperLid
from idiomas.paths import CORPUS_MANIFEST, RESULTS_DIR, corpus_dir, models_dir
from idiomas.text import script_fraction

KEEP = ("ja", "zh", "ko", "es", "en")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--tag", default="")
    ap.add_argument("--window", type=float, default=30.0, help="ventana de Whisper en s (30 = la original)")
    ap.add_argument("--whisper-only", action="store_true", help="solo Whisper propio (sin API de sherpa ni SenseVoice)")
    args = ap.parse_args()
    import sherpa_onnx as so

    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    sizes = {s: WhisperLid(s, args.threads, args.window) for s in ("tiny", "base")}
    b = str(models_dir() / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17")
    sv_auto = None if args.whisper_only else so.OfflineRecognizer.from_sense_voice(
        model=f"{b}/model.int8.onnx", tokens=f"{b}/tokens.txt", num_threads=args.threads, language="", use_itn=True
    )
    sv_forced = {} if args.whisper_only else {
        lg: so.OfflineRecognizer.from_sense_voice(
            model=f"{b}/model.int8.onnx", tokens=f"{b}/tokens.txt", num_threads=args.threads, language=lg, use_itn=True
        )
        for lg in ("ja", "zh", "ko")
    }

    def sv(rec, x):
        s = rec.create_stream()
        s.accept_waveform(16000, x)
        t0, c0 = time.perf_counter(), time.process_time()
        rec.decode_stream(s)
        return s.result, time.perf_counter() - t0, time.process_time() - c0

    # calentamiento
    warm = sf.read(corpus_dir() / "lid" / "ja" / f"{manifest['lid']['ja']['items'][0]['id']}.wav", dtype="float32")[0]
    for w in sizes.values():
        w.probs(warm)
        if not args.whisper_only:
            w.sherpa_top1(warm)
    if sv_auto is not None:
        sv(sv_auto, warm)

    out: dict = {"threads": args.threads, "window_s": args.window, "items": []}
    for cond, sub in (("clean", "lid"), ("music", "lid_music")):
        for lang, info in manifest["lid"].items():
            for it in info["items"]:
                x = sf.read(corpus_dir() / sub / lang / f"{it['id']}.wav", dtype="float32")[0]
                rec: dict = {"cond": cond, "lang": lang, "id": it["id"], "dur": round(len(x) / 16000, 2)}
                for name, w in sizes.items():
                    t0, c0 = time.perf_counter(), time.process_time()
                    lg = w.logits(x)
                    rec[f"{name}_wall_ms"] = (time.perf_counter() - t0) * 1000
                    rec[f"{name}_cpu_ms"] = (time.process_time() - c0) * 1000
                    rec[f"{name}_logits"] = {c: float(lg[w.lang_codes.index(c)]) for c in KEEP}
                    rec[f"{name}_top1"] = w.lang_codes[int(np.argmax(lg))]
                    if args.whisper_only:
                        continue
                    t0 = time.perf_counter()
                    rec[f"{name}_sherpa_top1"] = w.sherpa_top1(x)
                    rec[f"{name}_sherpa_wall_ms"] = (time.perf_counter() - t0) * 1000
                if args.whisper_only:
                    out["items"].append(rec)
                    continue
                r, wall, cpu = sv(sv_auto, x)
                rec["sv_auto"] = {"lang": r.lang, "event": r.event, "text": r.text, "wall_ms": wall * 1000, "cpu_ms": cpu * 1000}
                rec["sv_forced"] = {}
                for tl, srec in sv_forced.items():
                    r, wall, cpu = sv(srec, x)
                    rec["sv_forced"][tl] = {"text": r.text, "script": script_fraction(r.text, tl), "wall_ms": wall * 1000}
                out["items"].append(rec)
        print(f"{cond}: {len(out['items'])} recortes", flush=True)
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"lid_t{args.threads}{args.tag}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
