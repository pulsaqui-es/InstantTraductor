"""Candidatos de ASR del spike S5 (sherpa-onnx 1.13.8, CPU) y tubería con Silero VAD delante.

Dos tipos de tubería, con la misma puerta de VAD que S3 (Silero 6.2.3, umbral 0,5/0,35, 500 ms de silencio para cerrar,
tramos de menos de 250 ms descartados, relleno previo de 150 ms):

- ``StreamingPipeline``: transductor en streaming (X-ASR, zipformer-zh, Nemotron 3.5, zipformer coreano). Un stream nuevo
  por tramo; parciales tras cada trama; al cerrar el tramo se rellena con ceros (un trozo del modelo), ``input_finished()``
  y se decodifica el resto.
- ``OfflinePipeline``: modelo por segmentos (SenseVoice, Parakeet-ja CTC, ReazonSpeech). Se acumula el tramo y se decodifica
  entero al cerrarlo; sin parciales.

``simulate`` alimenta el audio en tramas de 32 ms con un **reloj virtual**: cada llamada a ``push`` cuesta su tiempo real
de cómputo; si el procesador va retrasado, las tramas siguientes esperan en cola, igual que en una captura real. Es
equivalente a la alimentación en tiempo real de S3 (``spikes/asr``) pero sin esperar el reloj de pared.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np
import psutil

from idiomas.paths import models_dir, silero_model_path
from idiomas.vad import FRAME, FRAME_S, SAMPLE_RATE, SileroOnnx, StreamingVad

PRE_ROLL_FRAMES = 10  # 320 ms de audio previo que se guardan por si el VAD llega tarde
SPEECH_PAD_MS = 150.0


@dataclass
class Candidate:
    key: str
    langs: tuple[str, ...]
    kind: str  # "stream" | "offline"
    label: str
    build: object  # (lang, threads) -> (recognizer, extra dict)
    chunk_ms: int = 0
    notes: str = ""
    extra: dict = field(default_factory=dict)


def _m(name: str) -> str:
    return str(models_dir() / name)


def _xasr(chunk_ms: int):
    def build(lang: str, threads: int):
        import sherpa_onnx as so

        b = _m(f"sherpa-onnx-x-asr-{chunk_ms}ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05")
        return so.OnlineRecognizer.from_transducer(
            tokens=f"{b}/tokens.txt",
            encoder=f"{b}/encoder.int8.onnx",
            decoder=f"{b}/decoder.onnx",
            joiner=f"{b}/joiner.int8.onnx",
            num_threads=threads,
            modeling_unit="cjkchar+bpe",
            bpe_vocab=f"{b}/bpe.model",
        )

    return build


def _zipformer_zh(lang: str, threads: int):
    import sherpa_onnx as so

    b = _m("sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30")
    return so.OnlineRecognizer.from_transducer(
        tokens=f"{b}/tokens.txt",
        encoder=f"{b}/encoder.int8.onnx",
        decoder=f"{b}/decoder.onnx",
        joiner=f"{b}/joiner.int8.onnx",
        num_threads=threads,
    )


def _nemotron35(blank_penalty: float):
    def build(lang: str, threads: int):
        import sherpa_onnx as so

        b = _m("sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11")
        return so.OnlineRecognizer.from_transducer(
            tokens=f"{b}/tokens.txt",
            encoder=f"{b}/encoder.int8.onnx",
            decoder=f"{b}/decoder.int8.onnx",
            joiner=f"{b}/joiner.int8.onnx",
            num_threads=threads,
            feature_dim=128,
            blank_penalty=blank_penalty,
        )

    return build


def _kangkyu(chunk: int):
    def build(lang: str, threads: int):
        import sherpa_onnx as so

        b = _m("kangkyu-ko-zipformer-174m")
        tag = f"epoch-99-avg-1-chunk-{chunk}-left-128.int8.onnx"
        return so.OnlineRecognizer.from_transducer(
            tokens=f"{b}/tokens.txt",
            encoder=f"{b}/encoder-{tag}",
            decoder=f"{b}/decoder-{tag}",
            joiner=f"{b}/joiner-{tag}",
            num_threads=threads,
        )

    return build


def _sensevoice(lang: str, threads: int):
    import sherpa_onnx as so

    b = _m("sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17")
    return so.OfflineRecognizer.from_sense_voice(
        model=f"{b}/model.int8.onnx", tokens=f"{b}/tokens.txt", num_threads=threads, language=lang, use_itn=True
    )


def _parakeet_ja(lang: str, threads: int):
    import sherpa_onnx as so

    b = _m("sherpa-onnx-nemo-parakeet-tdt_ctc-0.6b-ja-35000-int8")
    return so.OfflineRecognizer.from_nemo_ctc(model=f"{b}/model.int8.onnx", tokens=f"{b}/tokens.txt", num_threads=threads)


def _reazon_ja(lang: str, threads: int):
    import sherpa_onnx as so

    b = _m("sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01")
    return so.OfflineRecognizer.from_transducer(
        encoder=f"{b}/encoder-epoch-99-avg-1.int8.onnx",
        decoder=f"{b}/decoder-epoch-99-avg-1.int8.onnx",
        joiner=f"{b}/joiner-epoch-99-avg-1.int8.onnx",
        tokens=f"{b}/tokens.txt",
        num_threads=threads,
    )


CANDIDATES: dict[str, Candidate] = {
    c.key: c
    for c in [
        Candidate("xasr480", ("zh",), "stream", "X-ASR-zh-en 480 ms (punct, int8)", _xasr(480), 480),
        Candidate("xasr960", ("zh",), "stream", "X-ASR-zh-en 960 ms (punct, int8)", _xasr(960), 960),
        Candidate("zipformer_zh", ("zh",), "stream", "zipformer-zh streaming 2025-06-30 (int8)", _zipformer_zh, 320),
        Candidate("sensevoice", ("zh", "ja", "ko"), "offline", "SenseVoice-Small 2024-07-17 (int8, ITN)", _sensevoice),
        Candidate("nemotron35", ("ko", "ja", "zh"), "stream", "Nemotron 3.5 streaming 560 ms (int8)", _nemotron35(0.0), 560),
        Candidate("nemotron35_bp1", ("ko", "ja"), "stream", "Nemotron 3.5 560 ms, blank_penalty 1", _nemotron35(1.0), 560),
        Candidate("kangkyu32", ("ko",), "stream", "zipformer coreano kangkyu 174M, chunk 32 (640 ms)", _kangkyu(32), 640),
        Candidate("kangkyu64", ("ko",), "stream", "zipformer coreano kangkyu 174M, chunk 64 (1280 ms)", _kangkyu(64), 1280),
        Candidate("parakeet_ja", ("ja",), "offline", "Parakeet-tdt_ctc-0.6b-ja (cabeza CTC, int8)", _parakeet_ja),
        Candidate("reazon_ja", ("ja",), "offline", "ReazonSpeech zipformer k2 v2 (int8)", _reazon_ja),
    ]
}


class _Base:
    """Puerta de VAD común y contabilidad de cómputo."""

    def __init__(self, vad_threads: int = 1, min_silence_ms: float = 500.0) -> None:
        self.vad = StreamingVad(
            SileroOnnx(silero_model_path(), num_threads=vad_threads),
            min_silence_ms=min_silence_ms,
            min_speech_ms=250.0,
            speech_pad_ms=SPEECH_PAD_MS,
        )
        self._pending = np.zeros(0, dtype=np.float32)
        self._preroll: deque[np.ndarray] = deque(maxlen=PRE_ROLL_FRAMES)
        self.frame_idx = 0
        self.t_vad = 0.0
        self.t_asr = 0.0
        self.decode_ms: list[float] = []  # coste de cada vaciado/decodificación de segmento
        self.seg_audio_s: list[float] = []

    def push(self, chunk: np.ndarray) -> list[dict]:
        self._pending = np.concatenate([self._pending, chunk.astype(np.float32, copy=False)])
        out: list[dict] = []
        while len(self._pending) >= FRAME:
            frame, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            out += self._frame(frame)
        return out

    def _frame(self, frame: np.ndarray) -> list[dict]:
        raise NotImplementedError

    def flush(self) -> list[dict]:
        return []


class StreamingPipeline(_Base):
    def __init__(self, rec, tail_ms: int, language: str | None = None, **kw) -> None:
        super().__init__(**kw)
        self.rec = rec
        self.tail = int(SAMPLE_RATE * tail_ms / 1000)
        self.language = language
        self.stream = None
        self._last = ""
        self._span_start = 0.0

    def _open(self) -> None:
        self.stream = self.rec.create_stream()
        if self.language:
            self.stream.set_option("language", self.language)
        self._last = ""

    def _feed(self, x: np.ndarray) -> None:
        c0 = time.perf_counter()
        self.stream.accept_waveform(SAMPLE_RATE, x)
        self.t_asr += time.perf_counter() - c0

    def _poll(self) -> list[dict]:
        if self.stream is None:
            return []
        c0 = time.perf_counter()
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)
        text = self.rec.get_result_all(self.stream).text.strip()
        self.t_asr += time.perf_counter() - c0
        if text and text != self._last:
            self._last = text
            return [{"type": "partial", "text": text}]
        return []

    def _frame(self, frame: np.ndarray) -> list[dict]:
        t_start = self.frame_idx * FRAME_S
        self.frame_idx += 1
        c0 = time.perf_counter()
        evs = self.vad.push(frame)
        self.t_vad += time.perf_counter() - c0
        out: list[dict] = []
        opened = False
        for ev in evs:
            if ev.kind == "start":
                self._open()
                pre = list(self._preroll)
                if pre:
                    self._feed(np.concatenate(pre))
                self._feed(frame)
                opened = True
        if self.stream is not None and not opened:
            self._feed(frame)
        out += self._poll()
        for ev in evs:
            if ev.kind in ("end", "cancel") and self.stream is not None:
                if ev.kind == "end":
                    c0 = time.perf_counter()
                    self.stream.accept_waveform(SAMPLE_RATE, np.zeros(self.tail, dtype=np.float32))
                    self.stream.input_finished()
                    while self.rec.is_ready(self.stream):
                        self.rec.decode_stream(self.stream)
                    text = self.rec.get_result_all(self.stream).text.strip()
                    dt = time.perf_counter() - c0
                    self.t_asr += dt
                    self.decode_ms.append(dt * 1000)
                    out.append(
                        {"type": "final", "text": text, "span": [ev.speech_start, ev.speech_end], "decided_at": ev.decided_at}
                    )
                else:
                    out.append({"type": "discard", "span": [ev.speech_start, ev.speech_end]})
                self.stream = None
        self._preroll.append(frame)
        return out


class OfflinePipeline(_Base):
    def __init__(self, rec, **kw) -> None:
        super().__init__(**kw)
        self.rec = rec
        self._seg: list[np.ndarray] | None = None
        self._seg_t0 = 0.0

    def _frame(self, frame: np.ndarray) -> list[dict]:
        t_start = self.frame_idx * FRAME_S
        self.frame_idx += 1
        c0 = time.perf_counter()
        evs = self.vad.push(frame)
        self.t_vad += time.perf_counter() - c0
        out: list[dict] = []
        opened = False
        for ev in evs:
            if ev.kind == "start":
                pre = list(self._preroll)
                self._seg = [*pre, frame]
                self._seg_t0 = t_start - len(pre) * FRAME_S
                opened = True
        if self._seg is not None and not opened:
            self._seg.append(frame)
        for ev in evs:
            if ev.kind in ("end", "cancel") and self._seg is not None:
                if ev.kind == "end":
                    keep = int(np.ceil((ev.boundary - self._seg_t0) / FRAME_S))
                    audio = np.concatenate(self._seg[: max(1, keep)])
                    c0 = time.perf_counter()
                    s = self.rec.create_stream()
                    s.accept_waveform(SAMPLE_RATE, audio)
                    self.rec.decode_stream(s)
                    text = s.result.text.strip()
                    dt = time.perf_counter() - c0
                    self.t_asr += dt
                    self.decode_ms.append(dt * 1000)
                    self.seg_audio_s.append(len(audio) / SAMPLE_RATE)
                    out.append(
                        {
                            "type": "final",
                            "text": text,
                            "span": [ev.speech_start, ev.speech_end],
                            "decided_at": ev.decided_at,
                            "seg_s": len(audio) / SAMPLE_RATE,
                            "event": getattr(s.result, "event", ""),
                        }
                    )
                else:
                    out.append({"type": "discard", "span": [ev.speech_start, ev.speech_end]})
                self._seg = None
        self._preroll.append(frame)
        return out


def make_recognizer(key: str, lang: str, threads: int = 2):
    return CANDIDATES[key].build(lang, threads)


def make_pipeline(key: str, lang: str, rec, **kw):
    """Tubería nueva (VAD y estado limpios) sobre un reconocedor ya cargado."""
    cand = CANDIDATES[key]
    if cand.kind == "stream":
        language = lang if key.startswith("nemotron") else None
        return StreamingPipeline(rec, tail_ms=cand.chunk_ms, language=language, **kw)
    return OfflinePipeline(rec, **kw)


def simulate(pipe, samples: np.ndarray) -> dict:
    """Alimenta ``samples`` en tramas de 32 ms con reloj virtual. Devuelve eventos con su instante ``t`` (s) y el coste."""
    proc = psutil.Process()
    cpu0 = sum(proc.cpu_times()[:2])
    wall0 = time.perf_counter()
    free = 0.0
    events: list[dict] = []
    lateness: list[float] = []
    compute = 0.0
    n = len(samples)
    for pos in range(0, n, FRAME):
        chunk = samples[pos : pos + FRAME]
        arrival = (pos + len(chunk)) / SAMPLE_RATE
        start = max(free, arrival)
        lateness.append(start - arrival)
        c0 = time.perf_counter()
        evs = pipe.push(chunk)
        cost = time.perf_counter() - c0
        compute += cost
        free = start + cost
        for e in evs:
            e["t"] = free
            events.append(e)
    # Cierre del audio: tramo abierto
    start = max(free, n / SAMPLE_RATE)
    c0 = time.perf_counter()
    for e in pipe.flush():
        e["t"] = start + (time.perf_counter() - c0)
        events.append(e)
    audio_s = n / SAMPLE_RATE
    cpu = sum(proc.cpu_times()[:2]) - cpu0
    return {
        "events": events,
        "audio_s": audio_s,
        "compute_s": compute,
        "rtf": compute / audio_s,
        "cpu_cores": cpu / audio_s,  # núcleos de media durante el flujo emitido en tiempo real
        "wall_s": time.perf_counter() - wall0,
        "lateness_p95": float(np.percentile(lateness, 95)),
        "lateness_max": float(np.max(lateness)),
        "t_vad": pipe.t_vad,
        "t_asr": pipe.t_asr,
        "decode_ms": pipe.decode_ms,
    }
