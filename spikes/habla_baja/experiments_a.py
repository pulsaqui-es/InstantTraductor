"""Experimentos A1, A2 y siguientes sobre la cadena de habla baja (ver README).

Subcomandos:
  vad1      A1 nivel 1 (sin ASR): barrido de Silero con las probabilidades cacheadas. Por clip: ¿cubre el VAD el habla?
            Por el clip de música y efectos: tramos y segundos de «habla» falsa. Muy barato.
  full      A1/A3 nivel 2 (cadena completa con ASR) para una lista de configuraciones sobre un subconjunto de clips:
            % de frases traducidas, falsas alarmas en 10 min sin diálogo y retardo.
  curve     A2: curva WER/recall frente a la ganancia, sin AGC, con VAD perfecto, sobre el habla limpia.
  hesitate  Segmentación: dudas de 0,65 s dentro del enunciado frente al silencio mínimo del VAD y al segmentador.

Uso: `uv run python experiments_a.py vad1 | full --set NAME[,NAME] | curve | hesitate`
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace

import numpy as np

from chain import CHUNK, ChainConfig, ChainRunner, PersistentEntryModel, SmoothedModel, silero_probs
from common import C2_DIR, RESULTS_DIR, SR, read_wav
from evalcore import (
    RECOVERED_MIN,
    asr_on_region,
    clip_metrics,
    false_alarms,
    load_manifest,
    pct,
    word_recall,
)
from instanttraductor.contracts import AudioChunk
from instanttraductor.vad.silero import FRAME_SAMPLES, SileroVad

BASE = ChainConfig()
HARD = ["n40", "n50", "mus_b", "mus_c", "mus_d", "sfx_a", "whisper_q", "whisper_mus", "after_loud", "reverb",
        "whisper_tts", "whisper_tts_q", "whisper_tts_mus"]
FULL_CONDS = ["mus_b", "mus_c", "mus_d", "whisper_q", "whisper_mus", "after_loud", "reverb", "n20", "hesitate",
              "whisper_tts", "whisper_tts_mus"]
EASY = ["n20", "n30", "mus_a", "whisper", "stretch", "slow", "stretch4", "hesitate"]


def vad_cfgs() -> dict[str, ChainConfig]:
    c = BASE
    cfgs = {
        "base 0.5/0.35": c,
        "0.45/0.30": replace(c, vad_threshold=0.45, vad_neg_threshold=0.30),
        "0.40/0.25": replace(c, vad_threshold=0.40, vad_neg_threshold=0.25),
        "0.35/0.20": replace(c, vad_threshold=0.35, vad_neg_threshold=0.20),
        "0.30/0.15": replace(c, vad_threshold=0.30, vad_neg_threshold=0.15),
        "0.25/0.10": replace(c, vad_threshold=0.25, vad_neg_threshold=0.10),
        "0.40/0.35": replace(c, vad_threshold=0.40, vad_neg_threshold=0.35),
        "0.35/0.30": replace(c, vad_threshold=0.35, vad_neg_threshold=0.30),
        "0.40/0.25 sm3": replace(c, vad_threshold=0.40, vad_neg_threshold=0.25, vad_smooth=3),
        "0.5/0.35 +pers 0.3x4": replace(c, vad_persist_threshold=0.30, vad_persist_frames=4),
        "0.5/0.35 +pers 0.25x6": replace(c, vad_persist_threshold=0.25, vad_persist_frames=6),
        "0.5/0.35 +pers 0.35x3": replace(c, vad_persist_threshold=0.35, vad_persist_frames=3),
        "0.40/0.25 sil300": replace(c, vad_threshold=0.40, vad_neg_threshold=0.25, vad_min_silence_ms=300),
        "0.40/0.25 sil700": replace(c, vad_threshold=0.40, vad_neg_threshold=0.25, vad_min_silence_ms=700),
        "0.40/0.25 sil1000": replace(c, vad_threshold=0.40, vad_neg_threshold=0.25, vad_min_silence_ms=1000),
        "0.30/0.15 sil700": replace(c, vad_threshold=0.30, vad_neg_threshold=0.15, vad_min_silence_ms=700),
        "0.5/0.35 sil700": replace(c, vad_min_silence_ms=700),
    }
    return cfgs


def vad_segments(probs: np.ndarray, cfg: ChainConfig) -> list[tuple[float, float]]:
    """Tramos (inicio, fin) que da `SileroVad` con esas probabilidades, sin ASR."""
    from chain import CachedProbModel

    model = CachedProbModel(probs)
    if cfg.vad_smooth > 1:
        model = SmoothedModel(model, cfg.vad_smooth)  # type: ignore[assignment]
    if cfg.vad_persist_threshold is not None:
        model = PersistentEntryModel(model, cfg.vad_persist_threshold, cfg.vad_persist_frames)  # type: ignore[assignment]
    vad = SileroVad(
        model,
        threshold=cfg.vad_threshold,
        neg_threshold=min(cfg.vad_neg_threshold, cfg.vad_threshold),
        min_silence_ms=cfg.vad_min_silence_ms,
        speech_pad_ms=cfg.vad_pad_ms,
    )
    segs: list[tuple[float, float]] = []
    start = None
    zero = np.zeros(FRAME_SAMPLES, np.float32)
    for i in range(len(probs)):
        for ev in vad.accept(AudioChunk(samples=zero, sample_rate=SR, t_start=i * FRAME_SAMPLES / SR)):
            if ev.kind.value == "speech_start":
                start = ev.t
            elif start is not None:
                segs.append((start, ev.t))
                start = None
    if start is not None:
        segs.append((start, len(probs) * FRAME_SAMPLES / SR))
    return segs


def cover(segs: list[tuple[float, float]], t0: float, t1: float) -> float:
    return sum(max(0.0, min(b, t1) - max(a, t0)) for a, b in segs) / max(1e-9, t1 - t0)


def cmd_vad1(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    runner = ChainRunner(persist_cache=False)
    cfgs = vad_cfgs()
    probs_by_clip: dict[str, np.ndarray] = {}
    t = time.perf_counter()
    for item in manifest:
        samples = read_wav(C2_DIR / item["clip"])
        agc_audio, _ = runner.agc_audio(item["clip"], samples, BASE)
        probs_by_clip[item["clip"]] = silero_probs(agc_audio)
    fa_samples = read_wav(C2_DIR / "fa_music_sfx_10min.wav")
    fa_audio, _ = runner.agc_audio("fa10min", fa_samples, BASE)
    fa_probs = silero_probs(fa_audio)
    print(f"probabilidades: {time.perf_counter() - t:.0f} s")
    rows = []
    for name, cfg in cfgs.items():
        res = {"cfg": name}
        for group, conds in (("hard", HARD), ("easy", EASY)):
            cov, det, nseg, late = [], [], [], []
            for item in manifest:
                if item["cond"] not in conds:
                    continue
                segs = vad_segments(probs_by_clip[item["clip"]], cfg)
                c = cover(segs, item["speech_start"], item["speech_end"])
                cov.append(c)
                det.append(c >= 0.9)
                inside = [s for s in segs if s[1] > item["speech_start"] and s[0] < item["speech_end"]]
                nseg.append(len(inside))
                late.append(max(0.0, inside[0][0] - item["speech_start"]) if inside else float("nan"))
            res[group] = {
                "cover_mean": 100 * float(np.mean(cov)),
                "pct_cover_ge90": 100 * float(np.mean(det)),
                "segments_per_clip": float(np.mean(nseg)),
                "start_late_p50_s": float(np.nanmedian(late)),
            }
        fa = vad_segments(fa_probs, cfg)
        res["fa"] = {"segments": len(fa), "speech_s": sum(b - a for a, b in fa), "per_10min": len(fa) * 600 / (len(fa_samples) / SR)}
        rows.append(res)
        print(json.dumps(res))
    (RESULTS_DIR / "a1_vad_nivel1.json").write_text(json.dumps(rows, indent=1), "utf-8")
    md = [
        "| Config | duras: cubierto medio % | duras: % clips con ≥ 90 % cubierto | fáciles: % ≥ 90 % | tramos/clip (duras) | retraso de entrada p50 (s) | FA: tramos | FA: s de «habla» en 10 min |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        md.append(
            f"| {r['cfg']} | {r['hard']['cover_mean']:.1f} | {r['hard']['pct_cover_ge90']:.1f} | {r['easy']['pct_cover_ge90']:.1f} | "
            f"{r['hard']['segments_per_clip']:.2f} | {r['hard']['start_late_p50_s']:.2f} | {r['fa']['segments']} | {r['fa']['speech_s']:.0f} |"
        )
    (RESULTS_DIR / "a1_vad_nivel1.md").write_text("\n".join(md), "utf-8")
    print("\n".join(md))


def named_configs() -> dict[str, ChainConfig]:
    c = BASE
    named = dict(vad_cfgs())
    named.update(
        {
            "agc rel0.5": replace(c, agc_release_s=0.5),
            "agc rel0.25": replace(c, agc_release_s=0.25),
            "agc rel0.1": replace(c, agc_release_s=0.1),
            "agc max40": replace(c, agc_max_gain_db=40.0),
            "agc max40 rel0.25": replace(c, agc_max_gain_db=40.0, agc_release_s=0.25),
            "agc t-16": replace(c, agc_target_dbfs=-16.0),
            "agc gate-70": replace(c, agc_gate_dbfs=-70.0),
            "agc off": replace(c, agc=False),
        }
    )
    return named


TTS_CONDS = {"whisper_tts", "whisper_tts_q", "whisper_tts_mus"}


def subset(manifest: list[dict], conds: list[str], every: int) -> list[dict]:
    uids = sorted({m["uid"] for m in manifest})[::every]
    return [m for m in manifest if m["cond"] in conds and (m["uid"] in uids or m["cond"] in TTS_CONDS)]


def cmd_full(args: argparse.Namespace) -> None:
    manifest = load_manifest()
    items = subset(manifest, FULL_CONDS, args.every)
    runner = ChainRunner()
    named = named_configs()
    out_path = RESULTS_DIR / args.out
    results = json.loads(out_path.read_text("utf-8")) if out_path.exists() else {}
    samples_cache: dict[str, np.ndarray] = {}
    for name in args.set.split(","):
        cfg = named[name]
        t = time.perf_counter()
        rows = []
        for item in items:
            if item["clip"] not in samples_cache:
                samples_cache[item["clip"]] = read_wav(C2_DIR / item["clip"])
            rows.append(clip_metrics(runner, item, cfg, samples_cache[item["clip"]]))
        runner.asr.save()
        hard = [r for r in rows if r["cond"] in HARD]
        easy = [r for r in rows if r["cond"] not in HARD]
        fa = false_alarms(runner, cfg)
        runner.asr.save()
        d = [r["delay_end_s"] for r in rows if r["delay_end_s"] is not None]
        res = {
            "n_hard": len(hard),
            "hard_translated": 100 * float(np.mean([r["recall"] >= RECOVERED_MIN for r in hard])),
            "hard_recall": 100 * float(np.mean([r["recall"] for r in hard])),
            "easy_translated": 100 * float(np.mean([r["recall"] >= RECOVERED_MIN for r in easy])),
            "easy_recall": 100 * float(np.mean([r["recall"] for r in easy])),
            "by_cond": {
                c: 100 * float(np.mean([r["recall"] >= RECOVERED_MIN for r in rows if r["cond"] == c]))
                for c in sorted({r["cond"] for r in rows})
            },
            "delay_p50": pct(d, 50),
            "delay_p95": pct(d, 95),
            "units_per_clip": float(np.mean([r["n_units"] for r in rows])),
            "pct_units_le3": 100 * float(np.mean([w <= 3 for r in rows for w in r["unit_words"]] or [0])),
            "fa_units": fa["units"],
            "fa_segments": fa["vad_segments"],
            "fa_speech_s": fa["vad_speech_s"],
            "fa_samples": fa["unit_samples"][:3],
            "wall_s": time.perf_counter() - t,
            "asr_misses": runner.asr.misses,
        }
        results[name] = res
        out_path.write_text(json.dumps(results, indent=1, ensure_ascii=False), "utf-8")
        print(name, json.dumps({k: v for k, v in res.items() if k not in ("by_cond", "fa_samples")}))


def cmd_seg(args: argparse.Namespace) -> None:
    """Segmentador: palabras mínimas por cláusula y cortes por conjunción (reutiliza el ASR cacheado: sin cómputo nuevo)."""
    from evalcore import summarize

    manifest = [m for m in load_manifest() if m["cond"] in {"n20", "n40", "mus_b", "whisper", "stretch", "slow", "after_loud", "whisper_q", "n50", "mus_a", "n30"}]
    runner = ChainRunner()
    cfgs = {
        "base (6 pal., con conjunciones)": BASE,
        "8 pal.": replace(BASE, seg_min_clause_words=8),
        "10 pal.": replace(BASE, seg_min_clause_words=10),
        "solo comas, 6 pal.": replace(BASE, seg_conjunctions=False),
        "solo comas, 8 pal.": replace(BASE, seg_conjunctions=False, seg_min_clause_words=8),
        "6 pal., corte forzado 8 s": replace(BASE, max_untranslated_s=8.0),
        "6 pal., cola mínima 3": replace(BASE, seg_min_tail=3),
        "6 pal., cola mínima 4": replace(BASE, seg_min_tail=4),
        "6 pal., cola mínima 5": replace(BASE, seg_min_tail=5),
        "8 pal., cola mínima 4": replace(BASE, seg_min_clause_words=8, seg_min_tail=4),
    }
    samples_cache: dict[str, np.ndarray] = {}
    out = {}
    for name, cfg in cfgs.items():
        rows = []
        for item in manifest:
            if item["clip"] not in samples_cache:
                samples_cache[item["clip"]] = read_wav(C2_DIR / item["clip"])
            rows.append(clip_metrics(runner, item, cfg, samples_cache[item["clip"]]))
        out[name] = summarize(rows)["TODO"]
        lat = [x for r in rows for x in r["unit_lat_s"]]
        out[name]["unit_lat_p50"] = pct(lat, 50)
        out[name]["unit_lat_p95"] = pct(lat, 95)
        out[name]["asr_misses"] = runner.asr.misses
        print(name, json.dumps(out[name]))
    (RESULTS_DIR / "seg_segmentador.json").write_text(json.dumps(out, indent=1), "utf-8")
    md = ["| Segmentador | % frases traducidas | recall medio % | unidades/clip | % unidades ≤ 3 pal. | retardo del fin p50 / p95 (s) | latencia por unidad (listo - fin de la unidad) p50 / p95 (s) |", "|---|---:|---:|---:|---:|---:|---:|"]
    for k, v in out.items():
        md.append(f"| {k} | {v['pct_translated']:.1f} | {v['mean_recall']:.1f} | {v['units_per_clip']:.2f} | {v['pct_units_le3']:.1f} | {v['delay_p50']:.2f} / {v['delay_p95']:.2f} | {v['unit_lat_p50']:.2f} / {v['unit_lat_p95']:.2f} |")
    (RESULTS_DIR / "seg_segmentador.md").write_text("\n".join(md), "utf-8")
    print("\n".join(md))


def cmd_curve(args: argparse.Namespace) -> None:
    """A2: recall del ASR frente a la ganancia, sin AGC y con VAD perfecto."""
    manifest = [m for m in load_manifest() if m["cond"] == "n20"]
    manifest = manifest[:: args.every]
    runner = ChainRunner()
    levels = [-15, -20, -25, -30, -35, -40, -45, -50, -55, -60]
    out = {}
    for lvl in levels:
        recs = []
        for item in manifest:
            x = read_wav(C2_DIR / item["clip"])
            region = x[int(item["speech_start"] * SR) : int(item["speech_end"] * SR)]
            cur = 10 * np.log10(np.mean(region.astype(np.float64) ** 2) + 1e-12)
            gain = 10 ** ((lvl - 3 - cur) / 20)  # el RMS activo es ~3 dB sobre el RMS total del tramo
            y = (x * gain).astype(np.float32)
            text = asr_on_region(runner, y, item["speech_start"], item["speech_end"], f"curve{lvl}")
            recs.append(word_recall(item["ref"], text))
        out[lvl] = 100 * float(np.mean(recs))
        runner.asr.save()
        print(f"nivel {lvl} dBFS (RMS activo): recall {out[lvl]:.1f} % ({len(recs)} frases)")
    (RESULTS_DIR / "a2_curva_nivel.json").write_text(json.dumps(out, indent=1), "utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("vad1")
    f = sub.add_parser("full")
    f.add_argument("--set", required=True)
    f.add_argument("--every", type=int, default=2, help="usa 1 de cada N enunciados")
    f.add_argument("--out", default="a_full.json")
    sub.add_parser("seg")
    c = sub.add_parser("curve")
    c.add_argument("--every", type=int, default=2)
    args = ap.parse_args()
    {"vad1": cmd_vad1, "full": cmd_full, "curve": cmd_curve, "seg": cmd_seg}[args.cmd](args)


if __name__ == "__main__":
    main()
