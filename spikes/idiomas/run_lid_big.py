"""Filtro de idioma con más recortes: 300 por idioma (ja, zh, ko, es, en) de FLEURS test, para acotar mejor los porcentajes.

Con 30 recortes de español, «0 aceptados» solo garantiza < 10 % (regla de tres); con 300, < 1 %. Mismos recortes de 1-6 s
y misma mezcla de música a -10 dB que en ``build_corpus.py`` (semilla distinta; frases elegidas al azar entre todas las
grabaciones de test, no solo las 50 del corpus principal). Solo Whisper (ventana de 6 s por defecto).

Uso: ``uv run python run_lid_big.py [--n 300] [--window 6]``; informe: ``uv run python report_lid.py lid_big_w6.json``.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import soundfile as sf

from build_corpus import decode, load_split
from idiomas.audio import SAMPLE_RATE, energy_speech_intervals, mix_music, music_loop, speech_rms_db
from idiomas.lid import WhisperLid
from idiomas.paths import RESULTS_DIR, music_dir

KEEP = ("ja", "zh", "ko", "es", "en")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--window", type=float, default=6.0)
    ap.add_argument("--threads", type=int, default=1)
    args = ap.parse_args()
    rng = np.random.default_rng(77)
    tracks = [sf.read(p, dtype="float32")[0] for p in sorted(music_dir().glob("track*.wav"))]
    models = {s: WhisperLid(s, args.threads, args.window) for s in ("tiny", "base")}
    items = []
    for lang in KEEP:
        rows = [r for rs in load_split(lang).values() for r in rs]
        pick = rng.choice(len(rows), size=min(args.n, len(rows)), replace=False)
        for k, idx in enumerate(pick):
            row = rows[int(idx)]
            x = decode(row)
            ivs = energy_speech_intervals(x)
            a0, b0 = (ivs[0][0], ivs[-1][1]) if ivs else (0.0, len(x) / SAMPLE_RATE)
            length = min(float(rng.uniform(1.0, 6.0)), max(1.0, b0 - a0))
            t0 = float(rng.uniform(a0, max(a0, b0 - length)))
            seg = x[int(t0 * SAMPLE_RATE) : int((t0 + length) * SAMPLE_RATE)]
            level = speech_rms_db(seg, [(0.0, len(seg) / SAMPLE_RATE)])
            mixed = mix_music(seg, music_loop(tracks, len(seg), rng), level, 10.0)
            for cond, audio in (("clean", seg), ("music", mixed)):
                rec = {"cond": cond, "lang": lang, "id": int(row["id"]), "dur": round(len(seg) / SAMPLE_RATE, 2)}
                for name, m in models.items():
                    lg = m.logits(audio)
                    rec[f"{name}_logits"] = {c: float(lg[m.lang_codes.index(c)]) for c in KEEP}
                    rec[f"{name}_top1"] = m.lang_codes[int(np.argmax(lg))]
                items.append(rec)
            if k % 100 == 99:
                print(lang, k + 1, flush=True)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = {"threads": args.threads, "window_s": args.window, "n_per_lang": args.n, "items": items}
    (RESULTS_DIR / f"lid_big_w{int(args.window)}.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
