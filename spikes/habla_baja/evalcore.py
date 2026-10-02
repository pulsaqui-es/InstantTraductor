"""Métricas y evaluación de una configuración de la cadena sobre el corpus C2 (y sobre el clip sin diálogo)."""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from pathlib import Path

import jiwer
import numpy as np
from whisper_normalizer.english import EnglishTextNormalizer

from chain import CHUNK, ChainConfig, ChainRunner
from common import C2_DIR, SR, read_wav
from instanttraductor.contracts import AudioChunk

_norm = EnglishTextNormalizer()

#: Una frase cuenta como «traducida» si el texto de las unidades recupera al menos esta fracción de las palabras
#: de la referencia (proxy de SC-005: el traductor no está en el bucle).
RECOVERED_MIN = 0.6
COMPLETE_MIN = 0.9


def normalize(text: str) -> str:
    return _norm(text).strip()


def word_recall(ref: str, hyp: str) -> float:
    """Fracción de palabras de la referencia que aparecen bien (alineación de jiwer, textos normalizados)."""
    r, h = normalize(ref), normalize(hyp)
    n = len(r.split())
    if n == 0:
        return 1.0
    if not h:
        return 0.0
    out = jiwer.process_words(r, h)
    return out.hits / n


def pct(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else math.nan


def load_manifest() -> list[dict]:
    return json.loads((C2_DIR / "manifest.json").read_text("utf-8"))


def asr_on_region(runner: ChainRunner, samples: np.ndarray, t0: float, t1: float, tag: str) -> str:
    """ASR sobre una región con VAD perfecto: audio desde t0 - 0,15 s hasta t1 + 0,5 s, como un solo tramo."""
    a = max(0, int((t0 - 0.15) * SR))
    b = min(len(samples), int((t1 + 0.5) * SR))
    region = samples[a:b]
    runner.clock.t = 0.0
    asr = runner.asr
    asr.reset()
    n = len(region) // CHUNK
    for i in range(n):
        c = AudioChunk(samples=region[i * CHUNK : (i + 1) * CHUNK].astype(np.float32), sample_rate=SR, t_start=(a + i * CHUNK) / SR)
        runner.clock.t = c.t_end
        asr.accept(c)
    events = asr.flush()
    return events[-1].text if events else ""


def clip_metrics(runner: ChainRunner, item: dict, cfg: ChainConfig, samples: np.ndarray, *, deep: bool = False) -> dict:
    """Ejecuta la cadena sobre un clip y resume: texto emitido, recall, retardo y, con `deep`, el embudo por etapa."""
    res = runner.run(item["clip"], samples, cfg, keep_audio=deep)
    text = " ".join(u.source_text for u in res.units)
    rec = word_recall(item["ref"], text)
    t0, t1 = item["speech_start"], item["speech_end"]
    inside = [u for u in res.units if u.t_end > t0 and u.t_start < t1 + 1.0]
    last_ready = max((u.ready_at for u in inside), default=None)
    first_ready = min((u.ready_at for u in inside), default=None)
    out: dict = {
        "clip": item["clip"],
        "cond": item["cond"],
        "recall": rec,
        "emitted": len(res.units) > 0,
        "n_units": len(res.units),
        "unit_words": [len(u.source_text.split()) for u in res.units],
        "delay_end_s": (last_ready - t1) if last_ready is not None else None,
        "delay_start_s": (first_ready - t0) if first_ready is not None else None,
        "vad_segments": [(round(a, 2), round(b, 2)) for a, b in res.vad_segments],
        "text": text,
    }
    if deep:
        agc_audio = res.agc_audio
        assert agc_audio is not None and res.gains_db is not None and res.probs is not None
        # Etapa 0: techo del ASR (ganancia ideal, VAD perfecto)
        region = samples[int(t0 * SR) : int(t1 * SR)]
        cur = _active_rms(region)
        ideal = (samples * 10 ** ((-20.0 - cur) / 20)).astype(np.float32)
        text_ideal = asr_on_region(runner, ideal[: len(agc_audio)], t0, t1, "ideal")
        text_agc = asr_on_region(runner, agc_audio, t0, t1, "agc")
        text_vad = " ".join(t for _, _, t in res.asr_finals)
        out.update(
            {
                "recall_ideal": word_recall(item["ref"], text_ideal),
                "recall_agc": word_recall(item["ref"], text_agc),
                "recall_vad": word_recall(item["ref"], text_vad),
                "text_ideal": text_ideal,
                "text_agc": text_agc,
                "text_vad": text_vad,
                "speech_level_in_dbfs": cur,
                "speech_level_after_agc_dbfs": _active_rms(agc_audio[int(t0 * SR) : int(t1 * SR)]),
                "gain_at_start_db": float(res.gains_db[min(len(res.gains_db) - 1, int(t0 / (CHUNK / SR)))]),
                "gain_at_end_db": float(res.gains_db[min(len(res.gains_db) - 1, int(t1 / (CHUNK / SR)))]),
                "vad_pmax_in_speech": float(np.max(res.probs[int(t0 * SR / 512) : int(t1 * SR / 512) + 1])),
                "vad_frac_above_05": float(np.mean(res.probs[int(t0 * SR / 512) : int(t1 * SR / 512) + 1] >= 0.5)),
                "vad_overlap_frac": _overlap(res.vad_segments, t0, t1),
            }
        )
    return out


def _active_rms(x: np.ndarray, frame: int = 320, margin_db: float = 30.0) -> float:
    n = len(x) // frame
    if n == 0:
        return -120.0
    fr = x[: n * frame].reshape(n, frame).astype(np.float64)
    e = 10 * np.log10(np.mean(fr**2, axis=1) + 1e-12)
    keep = e > (e.max() - margin_db)
    return float(10 * np.log10(np.mean(fr[keep] ** 2) + 1e-12))


def _overlap(segs: list[tuple[float, float]], t0: float, t1: float) -> float:
    covered = sum(max(0.0, min(b, t1) - max(a, t0)) for a, b in segs)
    return covered / max(1e-9, t1 - t0)


def evaluate(
    runner: ChainRunner, cfg: ChainConfig, manifest: list[dict], conds: list[str] | None = None, *, deep: bool = False
) -> list[dict]:
    rows = []
    cache: dict[str, np.ndarray] = {}
    for item in manifest:
        if conds and item["cond"] not in conds:
            continue
        if item["clip"] not in cache:
            cache[item["clip"]] = read_wav(C2_DIR / item["clip"])
        rows.append(clip_metrics(runner, item, cfg, cache[item["clip"]], deep=deep))
    return rows


def summarize(rows: list[dict]) -> dict[str, dict]:
    """Por condición y total: % de frases traducidas (recall ≥ 0,6), % completas, recall medio, retardo, fragmentos."""
    out: dict[str, dict] = {}
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["cond"], []).append(r)
        groups.setdefault("TODO", []).append(r)
    for cond, rs in groups.items():
        delays = [r["delay_end_s"] for r in rs if r["delay_end_s"] is not None]
        words = [w for r in rs for w in r["unit_words"]]
        out[cond] = {
            "n": len(rs),
            "pct_translated": 100 * np.mean([r["recall"] >= RECOVERED_MIN for r in rs]),
            "pct_complete": 100 * np.mean([r["recall"] >= COMPLETE_MIN for r in rs]),
            "mean_recall": 100 * np.mean([r["recall"] for r in rs]),
            "pct_emitted": 100 * np.mean([r["emitted"] for r in rs]),
            "delay_p50": pct(delays, 50),
            "delay_p95": pct(delays, 95),
            "units_per_clip": float(np.mean([r["n_units"] for r in rs])),
            "pct_units_le3": 100 * np.mean([w <= 3 for w in words]) if words else math.nan,
        }
    return out


def false_alarms(runner: ChainRunner, cfg: ChainConfig, wav: Path | None = None) -> dict:
    """Pasa por la cadena el clip de música y efectos sin diálogo: frases emitidas y segundos de «habla»."""
    path = wav or (C2_DIR / "fa_music_sfx_10min.wav")
    samples = read_wav(path)
    t = time.perf_counter()
    res = runner.run("fa10min", samples, cfg)
    dur = len(samples) / SR
    texts = [u.source_text for u in res.units if u.source_text.strip()]
    return {
        "dur_s": dur,
        "vad_segments": len(res.vad_segments),
        "vad_speech_s": float(sum(b - a for a, b in res.vad_segments)),
        "units": len(texts),
        "unit_samples": texts[:8],
        "per_10min": len(texts) * 600.0 / dur,
        "wall_s": time.perf_counter() - t,
    }


def cfg_dict(cfg: ChainConfig) -> dict:
    return asdict(cfg)
