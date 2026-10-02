"""A0: embudo por etapa de la cadena actual sobre el corpus C2 (modo archivo, piezas reales).

Para cada clip se mide el recall de palabras (palabras de la referencia que salen bien) en cuatro puntos:

  ideal  ASR con ganancia ideal (habla a -20 dBFS) y VAD perfecto           -> techo del ASR con ese audio
  agc    ASR tras el AGC real, con VAD perfecto                             -> pérdida del AGC = ideal - agc
  vad    ASR alimentado solo con lo que deja pasar Silero (AGC + VAD real)  -> pérdida del VAD = agc - vad
  unit   texto de las unidades que emite el segmentador                     -> pérdida del segmentador = vad - unit

Pérdida del ASR/audio = 1 - ideal (no se arregla con ganancia ni con VAD). Con el recall medio por condición
se reparte el 100 % de las palabras entre las cuatro etapas. También: % de clips con recall >= 0,6
(«frase traducida»), nivel del habla tras el AGC, ganancia al empezar, probabilidad máxima de Silero, retardo y
fragmentación. Más las falsas alarmas del clip de 10 min de música y efectos sin diálogo.

Uso: `uv run python a0_funnel.py` (escribe resultados/a0_clips.json y resultados/a0_resumen.md).
"""

from __future__ import annotations

import json
import time

import numpy as np

from chain import ChainConfig, ChainRunner
from common import RESULTS_DIR
from evalcore import (
    COMPLETE_MIN,
    RECOVERED_MIN,
    evaluate,
    false_alarms,
    load_manifest,
    pct,
    summarize,
)

CONDS = [
    "n20", "n30", "n40", "n50", "mus_a", "mus_b", "whisper", "whisper_q", "stretch", "slow", "after_loud",
    "mus_c", "mus_d", "sfx_a", "reverb", "whisper_mus", "hesitate", "stretch4",
    "whisper_tts", "whisper_tts_q", "whisper_tts_mus",
]


def funnel_table(rows: list[dict]) -> str:
    out = [
        "| Condición | n | Techo ASR perdido | AGC pierde | VAD pierde | Segmentador pierde | Recall final | % frases traducidas (≥ 0,6) | % completas (≥ 0,9) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cond in [*CONDS, "TODO"]:
        rs = rows if cond == "TODO" else [r for r in rows if r["cond"] == cond]
        if not rs:
            continue
        m = {k: 100 * np.mean([r[k] for r in rs]) for k in ("recall_ideal", "recall_agc", "recall_vad", "recall")}
        out.append(
            f"| {cond} | {len(rs)} | {100 - m['recall_ideal']:.1f} | {m['recall_ideal'] - m['recall_agc']:.1f} | "
            f"{m['recall_agc'] - m['recall_vad']:.1f} | {m['recall_vad'] - m['recall']:.1f} | {m['recall']:.1f} | "
            f"{100 * np.mean([r['recall'] >= RECOVERED_MIN for r in rs]):.0f} | "
            f"{100 * np.mean([r['recall'] >= COMPLETE_MIN for r in rs]):.0f} |"
        )
    return "\n".join(out)


def level_table(rows: list[dict]) -> str:
    out = [
        "| Condición | Nivel de entrada (dBFS) | Tras el AGC (dBFS) | Ganancia al empezar (dB) | P(Silero) máx. | % tramas ≥ 0,5 | Habla cubierta por VAD | Retardo del fin p50 / p95 (s) | Unidades/clip | % unidades ≤ 3 pal. |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cond in CONDS:
        rs = [r for r in rows if r["cond"] == cond]
        if not rs:
            continue
        d = [r["delay_end_s"] for r in rs if r["delay_end_s"] is not None]
        w = [x for r in rs for x in r["unit_words"]]
        out.append(
            f"| {cond} | {np.mean([r['speech_level_in_dbfs'] for r in rs]):.0f} | "
            f"{np.mean([r['speech_level_after_agc_dbfs'] for r in rs]):.0f} | "
            f"{np.mean([r['gain_at_start_db'] for r in rs]):.0f} | "
            f"{np.mean([r['vad_pmax_in_speech'] for r in rs]):.2f} | "
            f"{100 * np.mean([r['vad_frac_above_05'] for r in rs]):.0f} | "
            f"{100 * np.mean([r['vad_overlap_frac'] for r in rs]):.0f} % | "
            f"{pct(d, 50):.2f} / {pct(d, 95):.2f} | {np.mean([r['n_units'] for r in rs]):.1f} | "
            f"{100 * np.mean([x <= 3 for x in w]) if w else float('nan'):.0f} |"
        )
    return "\n".join(out)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--conds", default="")
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-fa", action="store_true")
    args = ap.parse_args()
    manifest = load_manifest()
    if args.every > 1:
        uids = sorted({m["uid"] for m in manifest})[:: args.every]
        manifest = [m for m in manifest if m["uid"] in uids]
    runner = ChainRunner()
    cfg = ChainConfig()
    t = time.perf_counter()
    rows = evaluate(runner, cfg, manifest, args.conds.split(",") if args.conds else None, deep=True)
    runner.asr.save()
    print(f"embudo: {len(rows)} clips en {time.perf_counter() - t:.0f} s; ASR real: {runner.asr.compute_s:.0f} s "
          f"para {runner.asr.audio_s:.0f} s de audio (RTF {runner.asr.compute_s / max(1, runner.asr.audio_s):.2f})")
    (RESULTS_DIR / f"a0_clips{args.tag}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0), "utf-8")
    if args.no_fa:
        fa = {"units": "-", "vad_segments": "-", "vad_speech_s": 0.0, "unit_samples": []}
    else:
        fa = false_alarms(runner, cfg)
        runner.asr.save()
        print("falsas alarmas:", {k: v for k, v in fa.items() if k != "unit_samples"}, fa["unit_samples"][:3])
        (RESULTS_DIR / "a0_falsas_alarmas.json").write_text(json.dumps(fa, ensure_ascii=False, indent=1), "utf-8")
    md = [
        "# A0: embudo por etapa (cadena actual, corpus C2)",
        "",
        "Pérdida = puntos porcentuales de palabras de la referencia (recall medio). Columnas en orden de la cadena.",
        "",
        funnel_table(rows),
        "",
        level_table(rows),
        "",
        f"Falsas alarmas (10 min de música y efectos sin diálogo): {fa['units']} frases emitidas, "
        f"{fa['vad_segments']} tramos de VAD ({float(fa['vad_speech_s']):.0f} s).",
        "",
        "Resumen por condición (retardo, fragmentación):",
        "",
        "```json",
        json.dumps(summarize(rows), indent=1, default=float),
        "```",
    ]
    (RESULTS_DIR / f"a0_resumen{args.tag}.md").write_text("\n".join(md), "utf-8")
    print("\n".join(md[:30]))


if __name__ == "__main__":
    main()
