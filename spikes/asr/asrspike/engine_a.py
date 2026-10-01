"""Motor A: Nemotron Speech Streaming EN 0.6B (int8) sobre sherpa-onnx, en CPU, con Silero delante.

Dos políticas de fin de frase:

- ``vad``: Silero hace de puerta (solo entra audio con habla, más un relleno previo) y de detector
  de fin de turno (``min_silence_ms`` de silencio). Al cerrarse el tramo se vacía el reconocedor y
  se emite el ``final``. Cada tramo usa un stream nuevo (estado limpio).
- ``native``: sin VAD, todo el audio entra en un único stream y el ``final`` lo marca el detector
  de endpoint de sherpa (reglas por silencio decodificado).

Los eventos siguen el contrato del informe (§4.4): ``speech_start``, ``partial``, ``final`` y
``endpoint``, con ``segment_id``, ``revision`` y tiempos en el reloj de audio.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

import numpy as np

from . import paths
from .vad import FRAME, FRAME_S, SAMPLE_RATE, SileroOnnx, StreamingVad


def make_recognizer(
    chunk_ms: int,
    threads: int = 2,
    blank_penalty: float = 1.0,
    endpoint: bool = False,
    rule2_silence_s: float = 0.8,
    rule3_max_utt_s: float = 20.0,
):
    """Crea el OnlineRecognizer de sherpa-onnx con el modelo int8 del trozo indicado."""
    import sherpa_onnx

    base = paths.nemotron_dir(chunk_ms)
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(base / "tokens.txt"),
        encoder=str(base / "encoder.int8.onnx"),
        decoder=str(base / "decoder.int8.onnx"),
        joiner=str(base / "joiner.int8.onnx"),
        num_threads=threads,
        sample_rate=SAMPLE_RATE,
        feature_dim=128,
        decoding_method="greedy_search",
        blank_penalty=blank_penalty,
        enable_endpoint_detection=endpoint,
        rule1_min_trailing_silence=2.4,
        rule2_min_trailing_silence=rule2_silence_s,
        rule3_min_utterance_length=rule3_max_utt_s,
    )


class NemotronPipeline:
    """Puerta Silero + Nemotron en streaming. Acumula eventos en ``self.events``."""

    def __init__(
        self,
        chunk_ms: int,
        *,
        threads: int = 2,
        blank_penalty: float = 1.0,
        policy: str = "vad",
        min_silence_ms: float = 500.0,
        min_speech_ms: float = 250.0,
        preroll_ms: float = 300.0,
        tail_pad_ms: float | None = None,
        rule2_silence_s: float = 0.8,
        rule3_max_utt_s: float = 20.0,
        max_segment_s: float | None = None,
        vad_threads: int = 1,
    ) -> None:
        if policy not in ("vad", "native"):
            raise ValueError(policy)
        self.chunk_ms = chunk_ms
        self.policy = policy
        self.preroll_frames = int(round(preroll_ms / 1000 / FRAME_S))
        # Relleno de ceros al vaciar: por defecto, un trozo del modelo.
        self.tail_pad = int(SAMPLE_RATE * (chunk_ms if tail_pad_ms is None else tail_pad_ms) / 1000)
        self.max_segment_s = max_segment_s
        self.config = {
            "engine": "nemotron-speech-streaming-en-0.6b int8 (sherpa-onnx)",
            "chunk_ms": chunk_ms,
            "threads": threads,
            "blank_penalty": blank_penalty,
            "policy": policy,
            "min_silence_ms": min_silence_ms,
            "min_speech_ms": min_speech_ms,
            "preroll_ms": preroll_ms,
            "tail_pad_ms": self.tail_pad * 1000 / SAMPLE_RATE,
            "rule2_silence_s": rule2_silence_s if policy == "native" else None,
            "rule3_max_utt_s": rule3_max_utt_s if policy == "native" else None,
            "max_segment_s": max_segment_s,
        }
        self.rec = make_recognizer(
            chunk_ms,
            threads=threads,
            blank_penalty=blank_penalty,
            endpoint=(policy == "native"),
            rule2_silence_s=rule2_silence_s,
            rule3_max_utt_s=rule3_max_utt_s,
        )
        self.vad: StreamingVad | None = None
        if policy == "vad":
            self.vad = StreamingVad(
                SileroOnnx(paths.silero_model_path(), num_threads=vad_threads),
                min_silence_ms=min_silence_ms,
                min_speech_ms=min_speech_ms,
                speech_pad_ms=preroll_ms / 2,
            )
        self.clock: Callable[[], float] = lambda: self.audio_pos
        self.reset()

    # ------------------------------------------------------------------ estado
    def reset(self) -> None:
        self.events: list[dict] = []
        self.audio_pos = 0.0  # s de audio entregados
        self._pending = np.zeros(0, dtype=np.float32)
        self._frame_idx = 0
        self._preroll: deque[np.ndarray] = deque(maxlen=max(self.preroll_frames, 1))
        self.stream = None
        self._seg = -1
        self._rev = 0
        self._last_text = ""
        self._seg_start = 0.0
        self.t_vad = 0.0  # s de cómputo en el VAD
        self.t_asr = 0.0  # s de cómputo en el reconocedor
        self.t_flush = 0.0  # s de cómputo en vaciados (subconjunto de t_asr)
        self.flush_ms: list[float] = []
        self.gate_frames = 0  # tramas que han entrado al ASR
        self.total_frames = 0
        if self.vad:
            self.vad.reset()
        if self.policy == "native":
            self._open_stream(0.0)

    def _emit(self, typ: str, **kw) -> dict:
        ev = {"type": typ, "seg": self._seg, "rev": self._rev, "emitted_at": self.clock(), "audio_pos": self.audio_pos}
        ev.update(kw)
        self.events.append(ev)
        return ev

    # ------------------------------------------------------------------ ASR
    def _open_stream(self, t_start: float) -> None:
        self.stream = self.rec.create_stream()
        self._seg += 1
        self._rev = 0
        self._last_text = ""
        self._seg_start = t_start

    def _feed(self, samples: np.ndarray) -> None:
        c0 = time.perf_counter()
        self.stream.accept_waveform(SAMPLE_RATE, samples)
        self.t_asr += time.perf_counter() - c0

    def _decode_and_poll(self) -> None:
        if self.stream is None:
            return
        c0 = time.perf_counter()
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)
        text = self.rec.get_result_all(self.stream).text.strip()
        self.t_asr += time.perf_counter() - c0
        if text and text != self._last_text:
            self._rev += 1
            self._last_text = text
            self._emit("partial", text=text, t_start=self._seg_start)

    def _finish_stream(
        self, *, t_end: float | None, decided_at: float | None, forced: bool = False, reason: str = ""
    ) -> None:
        """Vacía el stream (relleno + input_finished), emite ``final`` y ``endpoint``.

        ``decided_at`` es el instante (reloj de audio) en el que se decidió cerrar el tramo
        (fin de turno del VAD, corte forzado o fin del audio); sirve para desglosar la latencia.
        """
        c0 = time.perf_counter()
        if self.tail_pad:
            self.stream.accept_waveform(SAMPLE_RATE, np.zeros(self.tail_pad, dtype=np.float32))
        self.stream.input_finished()
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)
        text = self.rec.get_result_all(self.stream).text.strip()
        dt = time.perf_counter() - c0
        self.t_asr += dt
        self.t_flush += dt
        self.flush_ms.append(dt * 1000)
        self._rev += 1
        if text:
            self._emit(
                "final", text=text, t_start=self._seg_start, t_end=t_end, decided_at=decided_at, forced=forced,
                reason=reason, flush_ms=dt * 1000,
            )
        else:
            self._emit("discard", text="", t_start=self._seg_start, t_end=t_end, reason=reason or "sin texto")
        self._emit("endpoint", text="", t_start=self._seg_start, t_end=t_end, reason=reason)
        self.stream = None

    # ------------------------------------------------------------------ entrada
    def push(self, chunk: np.ndarray) -> None:
        """Acepta un trozo de audio del dispositivo (20-100 ms) y procesa las tramas completas."""
        self.audio_pos += len(chunk) / SAMPLE_RATE
        self._pending = np.concatenate([self._pending, chunk.astype(np.float32, copy=False)])
        while len(self._pending) >= FRAME:
            frame, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            self._frame(frame)
        self._decode_and_poll()
        if self.policy == "native":
            self._check_endpoint()

    def _frame(self, frame: np.ndarray) -> None:
        self.total_frames += 1
        t_frame_start = self._frame_idx * FRAME_S
        self._frame_idx += 1
        if self.policy == "native":
            self._feed(frame)
            self.gate_frames += 1
            return

        c0 = time.perf_counter()
        evs = self.vad.push(frame)
        self.t_vad += time.perf_counter() - c0
        opened = False
        for ev in evs:
            if ev.kind == "start":
                pre = list(self._preroll)
                self._open_stream(t_frame_start - len(pre) * FRAME_S)
                self._emit("speech_start", text="", t_start=self._seg_start, vad_decided_at=ev.decided_at)
                if pre:
                    self._feed(np.concatenate(pre))
                    self.gate_frames += len(pre)
                self._feed(frame)
                self.gate_frames += 1
                opened = True
        if self.stream is not None and not opened:
            self._feed(frame)
            self.gate_frames += 1
        for ev in evs:
            if ev.kind in ("end", "cancel") and self.stream is not None:
                if ev.kind == "end":
                    self._decode_and_poll()
                    self._finish_stream(t_end=ev.speech_end, decided_at=ev.decided_at, reason="vad")
                else:
                    self.stream = None
                    self._emit("discard", text="", t_start=self._seg_start, t_end=ev.speech_end, reason="cancel")
        # Corte forzado por duración (solo si se pide).
        if self.stream is not None and self.max_segment_s and (t_frame_start + FRAME_S - self._seg_start) >= self.max_segment_s:
            self._decode_and_poll()
            t_cut = t_frame_start + FRAME_S
            self._finish_stream(t_end=t_cut, decided_at=t_cut, forced=True, reason="max_segment")
            self._open_stream(t_cut)
        self._preroll.append(frame)

    def _check_endpoint(self) -> None:
        if self.stream is not None and self.rec.is_endpoint(self.stream):
            text = self.rec.get_result_all(self.stream).text.strip()
            t_now = self.audio_pos
            if text:
                self._rev += 1
                self._emit(
                    "final", text=text, t_start=self._seg_start, t_end=None, decided_at=t_now, forced=False,
                    reason="endpoint", flush_ms=0.0,
                )
                self._emit("endpoint", text="", t_start=self._seg_start, t_end=None, reason="endpoint")
            self.rec.reset(self.stream)
            self._seg += 1
            self._rev = 0
            self._last_text = ""
            self._seg_start = t_now

    def flush(self) -> None:
        """Fin del audio: cierra lo que quede abierto."""
        if self._pending.size:
            pad = np.zeros(FRAME - len(self._pending), dtype=np.float32)
            self._frame(np.concatenate([self._pending, pad]))
            self._pending = np.zeros(0, dtype=np.float32)
        if self.policy == "vad":
            for ev in self.vad.flush():
                if ev.kind == "end" and self.stream is not None:
                    self._decode_and_poll()
                    self._finish_stream(t_end=ev.speech_end, decided_at=self.audio_pos, reason="flush")
            if self.stream is not None:
                self._decode_and_poll()
                self._finish_stream(t_end=None, decided_at=self.audio_pos, reason="flush")
        else:
            self._decode_and_poll()
            if self.stream is not None and self.rec.get_result_all(self.stream).text.strip():
                self._finish_stream(t_end=None, decided_at=self.audio_pos, reason="flush")
