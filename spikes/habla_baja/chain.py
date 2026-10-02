"""La cadena actual (AGC -> VAD -> ASR -> segmentador) en modo archivo, instrumentada por etapa.

Reproduce `Pipeline._listen_loop` de `src/instanttraductor/pipeline/session.py` con las piezas REALES
(`AutoGain`, `SileroVad`, `NemotronStreamingAsr`, `PauseClauseSegmenter`; se importan, no se modifican):
chunks de 20 ms, AGC, VAD, relleno previo de 0,5 s alimentando al ASR solo con habla, `flush()` del ASR en
cada `SPEECH_END` y el segmentador recibiendo START, parciales, END y FINAL en ese orden.

Para barrer configuraciones sin repetir cálculo:
- Las probabilidades de Silero se cachean por (clip, configuración de AGC): `CachedProbModel` las reproduce.
- El ASR se cachea por el audio exacto que ha recibido (`CachingAsr`): un tramo igual da el mismo resultado.
Ambas cachés son deterministas, así que las cifras son las de la cadena real sin caché.

Reloj: el de audio. `clock.now()` = fin del último chunk alimentado, es decir, retardo ALGORÍTMICO sin el cómputo
(el RTF del ASR se mide aparte).
"""

from __future__ import annotations

import hashlib
import pickle
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from common import NEMOTRON_DIR, OUT_DIR, SILERO_ONNX, SR
from instanttraductor.asr.sherpa_streaming import NemotronStreamingAsr, create_recognizer
from instanttraductor.audio.agc import AutoGain
from instanttraductor.contracts import AsrEvent, AudioChunk, TranslationUnit, VadEvent, VadEventKind
from instanttraductor.pipeline.segmenter import PauseClauseSegmenter
from instanttraductor.vad.silero import FRAME_SAMPLES, SileroOnnx, SileroVad

CHUNK = 320  # 20 ms, como la captura
PRE_ROLL_S = 0.5  # `PRE_ROLL_S` de session.py


class AudioClock:
    """Reloj de sesión = reloj de audio (fin del último chunk procesado)."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t


# ---------------------------------------------------------------------------
# VAD con probabilidades cacheadas
# ---------------------------------------------------------------------------
class CachedProbModel:
    """`SpeechProbabilityModel` que reproduce probabilidades ya calculadas (en orden de trama)."""

    def __init__(self, probs: np.ndarray) -> None:
        self._probs = probs
        self._i = 0

    def prob(self, frame: np.ndarray) -> float:
        p = float(self._probs[self._i]) if self._i < len(self._probs) else 0.0
        self._i += 1
        return p

    def reset(self) -> None:
        self._i = 0


class SmoothedModel:
    """Envuelve un modelo de probabilidad con media móvil de `n` tramas (para el barrido A1)."""

    def __init__(self, inner: Any, n: int) -> None:
        self._inner = inner
        self._buf: deque[float] = deque(maxlen=n)

    def prob(self, frame: np.ndarray) -> float:
        self._buf.append(self._inner.prob(frame))
        return float(np.mean(self._buf))

    def reset(self) -> None:
        self._inner.reset()
        self._buf.clear()


_silero_model: SileroOnnx | None = None


def silero_probs(samples: np.ndarray) -> np.ndarray:
    """Probabilidad de habla de cada trama de 512 muestras (las que completan los chunks de 20 ms)."""
    global _silero_model
    if _silero_model is None:
        _silero_model = SileroOnnx(SILERO_ONNX)
    _silero_model.reset()
    n = len(samples) // FRAME_SAMPLES
    return np.array(
        [_silero_model.prob(samples[i * FRAME_SAMPLES : (i + 1) * FRAME_SAMPLES]) for i in range(n)],
        dtype=np.float32,
    )


# ---------------------------------------------------------------------------
# ASR con caché por audio recibido
# ---------------------------------------------------------------------------
class CachingAsr:
    """Envuelve `NemotronStreamingAsr`: si ya recibió exactamente este audio en este orden, devuelve lo mismo.

    Clave de cada llamada = (t_start del primer chunk del tramo, hash acumulado del audio, nº de llamada,
    «a»/«f»). En un fallo de caché se alimenta al motor real, en orden, todo lo que aún no había visto del
    tramo (los aciertos anteriores no pasaron por el motor) y se guardan las salidas de cada paso.
    """

    CACHE_FILE = OUT_DIR / "asr_cache.pkl"

    def __init__(self, clock: AudioClock, recognizer: Any | None = None, *, persist: bool = True) -> None:
        self._clock = clock
        self._recognizer = recognizer
        self._engine: NemotronStreamingAsr | None = None
        self._persist = persist
        self.cache: dict[tuple, list[AsrEvent]] = {}
        if persist and self.CACHE_FILE.exists():
            try:
                self.cache = pickle.loads(self.CACHE_FILE.read_bytes())
            except Exception:
                self.cache = {}
        self._h: Any = None
        self._t0 = 0.0
        self._open = False
        self._history: list[AudioChunk] = []
        self._keys: list[tuple] = []
        self._synced = 0  # chunks del tramo que ya ha visto el motor real
        self.compute_s = 0.0  # CPU real del ASR (solo fallos de caché)
        self.audio_s = 0.0  # audio que ha procesado el motor real
        self.misses = 0

    @property
    def engine(self) -> NemotronStreamingAsr:
        if self._engine is None:
            if self._recognizer is None:
                self._recognizer = create_recognizer(NEMOTRON_DIR, num_threads=4)
            self._engine = NemotronStreamingAsr(self._clock, recognizer=self._recognizer)
        return self._engine

    def _begin(self, chunk: AudioChunk) -> None:
        self._h = hashlib.blake2b(digest_size=16)
        self._t0 = round(chunk.t_start, 6)
        self._open = True
        self._history = []
        self._keys = []
        self._synced = 0
        if self._engine is not None:
            self._engine.reset()

    def accept(self, chunk: AudioChunk) -> list[AsrEvent]:
        if not self._open:
            self._begin(chunk)
        self._h.update(chunk.samples.tobytes())
        self._history.append(chunk)
        key = (self._t0, self._h.hexdigest(), len(self._history), "a")
        self._keys.append(key)
        hit = self.cache.get(key)
        if hit is not None:
            return list(hit)
        self._sync()
        return list(self.cache[key])

    def _sync(self) -> None:
        """Alimenta al motor real con los chunks pendientes y guarda lo que devuelve cada uno."""
        eng = self.engine
        saved = self._clock.t
        t0 = time.perf_counter()
        self.misses += 1
        for j in range(self._synced, len(self._history)):
            c = self._history[j]
            self._clock.t = c.t_end
            self.cache[self._keys[j]] = eng.accept(c)
            self.audio_s += c.duration
        self._synced = len(self._history)
        self._clock.t = saved
        self.compute_s += time.perf_counter() - t0

    def flush(self) -> list[AsrEvent]:
        if not self._open:
            return []
        key = (self._t0, self._h.hexdigest(), len(self._history), "f")
        self._open = False
        hit = self.cache.get(key)
        if hit is not None:
            if self._engine is not None:
                self._engine.reset()
            return list(hit)
        self._sync()
        t0 = time.perf_counter()
        events = self.engine.flush()
        self.compute_s += time.perf_counter() - t0
        self.engine.reset()
        self.cache[key] = events
        return list(events)

    def reset(self) -> None:
        self._open = False
        if self._engine is not None:
            self._engine.reset()

    def save(self) -> None:
        if self._persist:
            tmp = self.CACHE_FILE.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(self.cache))
            tmp.replace(self.CACHE_FILE)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Cadena
# ---------------------------------------------------------------------------
@dataclass
class ChainConfig:
    """Parámetros de la cadena. Los valores por defecto son los de producción."""

    # AGC (audio/agc.py)
    agc: bool = True
    agc_target_dbfs: float = -20.0
    agc_attack_s: float = 0.05
    agc_release_s: float = 1.0
    agc_max_gain_db: float = 30.0
    agc_min_gain_db: float = -20.0
    agc_gate_dbfs: float = -60.0
    # VAD (vad/silero.py)
    vad_threshold: float = 0.5
    vad_neg_threshold: float = 0.35
    vad_min_silence_ms: float = 500.0
    vad_pad_ms: float = 150.0
    vad_smooth: int = 1  # media móvil de tramas (1 = sin suavizar)
    vad_persist_threshold: float | None = None  # entrada «persistente»: ver `PersistentEntryModel`
    vad_persist_frames: int = 4
    # Segmentador
    max_untranslated_s: float = 6.0

    def agc_key(self) -> tuple:
        return (
            self.agc,
            self.agc_target_dbfs,
            self.agc_attack_s,
            self.agc_release_s,
            self.agc_max_gain_db,
            self.agc_min_gain_db,
            self.agc_gate_dbfs,
        )

    def label(self) -> str:
        return (
            f"agc[{'on' if self.agc else 'off'} t{self.agc_target_dbfs:g} r{self.agc_release_s:g} "
            f"max{self.agc_max_gain_db:g}] vad[{self.vad_threshold:g}/{self.vad_neg_threshold:g} "
            f"s{self.vad_min_silence_ms:g} sm{self.vad_smooth}"
            + (f" pers{self.vad_persist_threshold:g}x{self.vad_persist_frames}" if self.vad_persist_threshold else "")
            + "]"
        )


class PersistentEntryModel:
    """Entrada «persistente» (A1): además de abrir con `threshold`, abre si la probabilidad se mantiene
    ≥ `low` durante `frames` tramas seguidas.

    Se implementa subiendo la probabilidad a 1.0 en la trama en que se cumple la condición (el VAD solo mira
    si supera su umbral de entrada). Mientras dura el habla, las tramas intermedias siguen valiendo lo que
    valen (no cierran por debajo de `neg_threshold`).
    """

    def __init__(self, inner: Any, low: float, frames: int) -> None:
        self._inner = inner
        self._low = low
        self._frames = frames
        self._run = 0

    def prob(self, frame: np.ndarray) -> float:
        p = self._inner.prob(frame)
        self._run = self._run + 1 if p >= self._low else 0
        return 1.0 if self._run >= self._frames else p

    def reset(self) -> None:
        self._inner.reset()
        self._run = 0


@dataclass
class ChainResult:
    units: list[TranslationUnit] = field(default_factory=list)
    vad_segments: list[tuple[float, float]] = field(default_factory=list)  # (start, end) de SPEECH_START/END
    asr_finals: list[tuple[float, float, str]] = field(default_factory=list)  # (t_start, t_end, texto)
    agc_audio: np.ndarray | None = None
    gains_db: np.ndarray | None = None  # ganancia del AGC al final de cada chunk
    probs: np.ndarray | None = None


def apply_agc(samples: np.ndarray, cfg: ChainConfig) -> tuple[np.ndarray, np.ndarray]:
    """Pasa todo el audio por el AGC en chunks de 20 ms. Devuelve (audio, ganancia en dB por chunk)."""
    n = len(samples) // CHUNK
    if not cfg.agc:
        return samples[: n * CHUNK].astype(np.float32), np.zeros(n, dtype=np.float32)
    agc = AutoGain(
        target_dbfs=cfg.agc_target_dbfs,
        attack_s=cfg.agc_attack_s,
        release_s=cfg.agc_release_s,
        max_gain_db=cfg.agc_max_gain_db,
        min_gain_db=cfg.agc_min_gain_db,
        gate_dbfs=cfg.agc_gate_dbfs,
    )
    out = np.empty(n * CHUNK, dtype=np.float32)
    gains = np.empty(n, dtype=np.float32)
    for i in range(n):
        c = AudioChunk(samples=samples[i * CHUNK : (i + 1) * CHUNK].astype(np.float32), sample_rate=SR, t_start=i * CHUNK / SR)
        out[i * CHUNK : (i + 1) * CHUNK] = agc.process(c).samples
        gains[i] = agc.gain_db
    return out, gains


class ChainRunner:
    """Ejecuta la cadena sobre clips. Comparte el reconocedor y las cachés entre ejecuciones."""

    def __init__(self, *, persist_cache: bool = True) -> None:
        self.clock = AudioClock()
        self.asr = CachingAsr(self.clock, persist=persist_cache)
        self._prob_cache: dict[tuple, np.ndarray] = {}
        self._agc_cache: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}

    def agc_audio(self, clip_id: str, samples: np.ndarray, cfg: ChainConfig) -> tuple[np.ndarray, np.ndarray]:
        key = (clip_id, cfg.agc_key())
        if key not in self._agc_cache:
            self._agc_cache[key] = apply_agc(samples, cfg)
            if len(self._agc_cache) > 400:  # acota la memoria
                self._agc_cache.pop(next(iter(self._agc_cache)))
        return self._agc_cache[key]

    def probs(self, clip_id: str, agc_samples: np.ndarray, cfg: ChainConfig) -> np.ndarray:
        key = (clip_id, cfg.agc_key())
        if key not in self._prob_cache:
            self._prob_cache[key] = silero_probs(agc_samples)
            if len(self._prob_cache) > 2000:
                self._prob_cache.pop(next(iter(self._prob_cache)))
        return self._prob_cache[key]

    def run(self, clip_id: str, samples: np.ndarray, cfg: ChainConfig, *, keep_audio: bool = False) -> ChainResult:
        clock = self.clock
        clock.t = 0.0
        agc_audio, gains = self.agc_audio(clip_id, samples, cfg)
        probs = self.probs(clip_id, agc_audio, cfg)
        model: Any = CachedProbModel(probs)
        if cfg.vad_smooth > 1:
            model = SmoothedModel(model, cfg.vad_smooth)
        if cfg.vad_persist_threshold is not None:
            model = PersistentEntryModel(model, cfg.vad_persist_threshold, cfg.vad_persist_frames)
        vad = SileroVad(
            model,
            threshold=cfg.vad_threshold,
            neg_threshold=min(cfg.vad_neg_threshold, cfg.vad_threshold),
            min_silence_ms=cfg.vad_min_silence_ms,
            speech_pad_ms=cfg.vad_pad_ms,
        )
        asr = self.asr
        asr.reset()
        segmenter = PauseClauseSegmenter(clock, max_untranslated_s=cfg.max_untranslated_s)
        res = ChainResult()
        if keep_audio:
            res.agc_audio, res.gains_db, res.probs = agc_audio, gains, probs

        pre_roll: deque[AudioChunk] = deque()
        in_speech = False
        seg_start: float | None = None

        def feed_asr(c: AudioChunk) -> list[TranslationUnit]:
            units: list[TranslationUnit] = []
            for ev in asr.accept(c):
                units.extend(segmenter.accept(ev))
            return units

        def flush_asr() -> list[TranslationUnit]:
            units: list[TranslationUnit] = []
            for ev in asr.flush():
                res.asr_finals.append((ev.t_start, ev.t_end, ev.text))
                units.extend(segmenter.accept(ev))
            return units

        n = len(agc_audio) // CHUNK
        for i in range(n):
            chunk = AudioChunk(samples=agc_audio[i * CHUNK : (i + 1) * CHUNK], sample_rate=SR, t_start=i * CHUNK / SR)
            clock.t = chunk.t_end
            pre_roll.append(chunk)
            while pre_roll and pre_roll[-1].t_end - pre_roll[0].t_start > PRE_ROLL_S:
                pre_roll.popleft()
            units: list[TranslationUnit] = []
            fed = False
            for event in vad.accept(chunk):
                if event.kind is VadEventKind.SPEECH_START:
                    in_speech = True
                    seg_start = event.t
                    units.extend(segmenter.accept(event))
                    for buffered in pre_roll:
                        piece = _trim_start(buffered, event.t)
                        if piece is not None:
                            units.extend(feed_asr(piece))
                    fed = True
                elif event.kind is VadEventKind.SPEECH_END:
                    if in_speech and not fed:
                        units.extend(feed_asr(chunk))
                        fed = True
                    units.extend(segmenter.accept(event))
                    units.extend(flush_asr())
                    if seg_start is not None:
                        res.vad_segments.append((seg_start, event.t))
                    in_speech = False
                    seg_start = None
            if in_speech and not fed:
                units.extend(feed_asr(chunk))
            res.units.extend(units)
        if in_speech:
            res.units.extend(flush_asr())
            if seg_start is not None:
                res.vad_segments.append((seg_start, clock.t))
        res.units.extend(segmenter.flush())
        return res


def _trim_start(chunk: AudioChunk, t: float) -> AudioChunk | None:
    """Recorta el chunk para que empiece en `t` (el SPEECH_START ya lleva el relleno previo). Igual que session.py."""
    if chunk.t_end <= t:
        return None
    if chunk.t_start >= t:
        return chunk
    skip = int(round((t - chunk.t_start) * chunk.sample_rate))
    if skip >= len(chunk.samples):
        return None
    return AudioChunk(samples=chunk.samples[skip:], sample_rate=chunk.sample_rate, t_start=chunk.t_start + skip / chunk.sample_rate)
