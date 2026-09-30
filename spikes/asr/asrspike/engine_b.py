"""Motor B: faster-whisper (CTranslate2) con large-v3-turbo en FP16 (GPU), por segmentos de VAD.

El mismo Silero VAD que usa el motor A cierra los segmentos (``min_silence_ms`` de silencio) y se
fuerza un corte si el habla continúa más de ``max_segment_s`` (cortando en la trama de menor
probabilidad de habla de la última ``cut_search_s``). Cada segmento se transcribe en un hilo
aparte (como haría la tubería real) con los filtros contra alucinaciones del informe (§3.9).
No hay parciales: solo ``final``.
"""

from __future__ import annotations

import os
import queue
import site
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import paths
from .vad import FRAME, FRAME_S, SAMPLE_RATE, SileroOnnx, StreamingVad


def add_cuda_dll_dirs() -> list[str]:
    """CTranslate2 (CUDA 12) busca ``cublas64_12.dll`` por la ruta de DLL del proceso.

    Las DLL llegan con el paquete ``nvidia-cublas-cu12`` (en ``site-packages/nvidia/*/bin``). Hay
    que registrarlas con ``os.add_dll_directory`` Y en ``PATH``, porque CTranslate2 las carga con
    ``LoadLibrary`` (no con las rutas de usuario de Python). Debe llamarse antes de importar
    ``ctranslate2``.
    """
    added = []
    roots = [Path(p) for p in site.getsitepackages()]
    for root in roots:
        for bin_dir in sorted((root / "nvidia").glob("*/bin")):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
            added.append(str(bin_dir))
    return added


def load_model(device: str = "cuda", compute_type: str = "float16"):
    """Carga ``large-v3-turbo`` (CTranslate2, FP16) desde ``models/faster-whisper-large-v3-turbo``."""
    add_cuda_dll_dirs()
    from faster_whisper import WhisperModel

    return WhisperModel(str(paths.whisper_turbo_dir()), device=device, compute_type=compute_type)


class WhisperPipeline:
    """Segmentación por VAD + faster-whisper. Acumula eventos en ``self.events``."""

    def __init__(
        self,
        model,
        *,
        beam_size: int = 1,
        max_segment_s: float | None = 5.0,
        min_silence_ms: float = 500.0,
        min_speech_ms: float = 250.0,
        preroll_ms: float = 300.0,
        end_pad_ms: float = 150.0,
        cut_search_s: float = 1.0,
        min_segment_s: float = 0.3,
        language: str = "en",
        vad_threads: int = 1,
    ) -> None:
        self.model = model
        self.beam_size = beam_size
        self.max_segment_s = max_segment_s
        self.preroll_frames = int(round(preroll_ms / 1000 / FRAME_S))
        self.end_pad_frames = int(round(end_pad_ms / 1000 / FRAME_S))
        self.cut_search_frames = int(round(cut_search_s / FRAME_S))
        self.min_segment_s = min_segment_s
        self.language = language
        self.config = {
            "engine": "faster-whisper large-v3-turbo FP16 (CTranslate2)",
            "beam_size": beam_size,
            "max_segment_s": max_segment_s,
            "min_silence_ms": min_silence_ms,
            "min_speech_ms": min_speech_ms,
            "preroll_ms": preroll_ms,
            "end_pad_ms": end_pad_ms,
            "cut_search_s": cut_search_s,
            "language": language,
            "anti_hallucination": {
                "condition_on_previous_text": False,
                "temperature": 0.0,
                "no_speech_threshold": 0.6,
                "log_prob_threshold": -1.0,
                "compression_ratio_threshold": 2.4,
            },
        }
        self.vad = StreamingVad(
            SileroOnnx(paths.silero_model_path(), num_threads=vad_threads),
            min_silence_ms=min_silence_ms,
            min_speech_ms=min_speech_ms,
            speech_pad_ms=preroll_ms / 2,
        )
        self.clock: Callable[[], float] = lambda: self.audio_pos
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._stop = False
        self.reset()
        self._worker.start()

    # ------------------------------------------------------------------ estado
    def reset(self) -> None:
        self._queue.join()
        with self._lock:
            self.events: list[dict] = []
        self.audio_pos = 0.0
        self._pending = np.zeros(0, dtype=np.float32)
        self._frame_idx = 0
        self._preroll: deque[np.ndarray] = deque(maxlen=max(self.preroll_frames, 1))
        self._frames: list[np.ndarray] = []  # tramas del segmento abierto
        self._probs: list[float] = []
        self._open = False
        self._seg_start = 0.0  # inicio (reloj de audio) de la primera trama del segmento abierto
        self._seg = -1
        self.t_vad = 0.0
        self.infer_ms: list[float] = []
        self.queue_ms: list[float] = []
        self.audio_infer_s = 0.0
        self.vad.reset()

    def close(self) -> None:
        self._queue.join()
        self._stop = True
        self._queue.put(None)
        self._worker.join(timeout=10)

    def _emit(self, typ: str, **kw) -> None:
        ev = {"type": typ, "rev": 0, "emitted_at": self.clock(), "audio_pos": self.audio_pos}
        ev.update(kw)
        with self._lock:
            self.events.append(ev)

    # ------------------------------------------------------------------ entrada
    def push(self, chunk: np.ndarray) -> None:
        self.audio_pos += len(chunk) / SAMPLE_RATE
        self._pending = np.concatenate([self._pending, chunk.astype(np.float32, copy=False)])
        while len(self._pending) >= FRAME:
            frame, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            self._frame(frame)

    def _frame(self, frame: np.ndarray) -> None:
        t_frame_start = self._frame_idx * FRAME_S
        self._frame_idx += 1
        c0 = time.perf_counter()
        evs = self.vad.push(frame)
        self.t_vad += time.perf_counter() - c0
        prob = self.vad.probs[-1]
        opened = False
        for ev in evs:
            if ev.kind == "start":
                pre = list(self._preroll)
                self._frames = pre + [frame]
                self._probs = [0.0] * len(pre) + [prob]
                self._seg_start = t_frame_start - len(pre) * FRAME_S
                self._open = True
                opened = True
                self._emit("speech_start", seg=self._seg + 1, text="", t_start=self._seg_start)
        if self._open and not opened:
            self._frames.append(frame)
            self._probs.append(prob)
        for ev in evs:
            if ev.kind == "end" and self._open:
                self._close_segment(speech_end=ev.speech_end, reason="vad")
            elif ev.kind == "cancel" and self._open:
                self._open = False
                self._frames, self._probs = [], []
                self._emit("discard", seg=self._seg + 1, text="", reason="cancel")
        if self._open and self.max_segment_s and len(self._frames) * FRAME_S >= self.max_segment_s:
            self._force_cut()
        self._preroll.append(frame)

    def _force_cut(self) -> None:
        """Corte forzado en la trama de menor probabilidad de habla de la última ventana."""
        n = len(self._frames)
        lo = max(int(self.min_segment_s / FRAME_S), n - self.cut_search_frames)
        cut = lo + int(np.argmin(self._probs[lo:n]))
        head, tail = self._frames[: cut + 1], self._frames[cut + 1 :]
        tail_probs = self._probs[cut + 1 :]
        t_cut = self._seg_start + len(head) * FRAME_S
        self._submit(np.concatenate(head), t_start=self._seg_start, t_end=t_cut, forced=True, reason="max_segment")
        self._frames, self._probs = tail, tail_probs
        self._seg_start = t_cut

    def _close_segment(self, *, speech_end: float | None, reason: str) -> None:
        """Cierra el segmento abierto: recorta el silencio final (queda un relleno corto)."""
        end_t = (speech_end if speech_end is not None else self._seg_start + len(self._frames) * FRAME_S)
        keep = int(np.ceil((end_t - self._seg_start) / FRAME_S)) + self.end_pad_frames
        keep = max(1, min(keep, len(self._frames)))
        audio = np.concatenate(self._frames[:keep])
        self._open = False
        self._frames, self._probs = [], []
        self._submit(audio, t_start=self._seg_start, t_end=end_t, forced=False, reason=reason)

    def _submit(self, audio: np.ndarray, *, t_start: float, t_end: float, forced: bool, reason: str) -> None:
        self._seg += 1
        self._queue.put(
            {
                "seg": self._seg,
                "audio": audio,
                "t_start": t_start,
                "t_end": t_end,
                "forced": forced,
                "reason": reason,
                "queued_at": time.perf_counter(),
            }
        )

    def flush(self) -> None:
        if self._pending.size:
            pad = np.zeros(FRAME - len(self._pending), dtype=np.float32)
            self._frame(np.concatenate([self._pending, pad]))
            self._pending = np.zeros(0, dtype=np.float32)
        for ev in self.vad.flush():
            if ev.kind == "end" and self._open:
                self._close_segment(speech_end=ev.speech_end, reason="flush")
        if self._open:
            self._close_segment(speech_end=None, reason="flush")
        self._queue.join()

    # ------------------------------------------------------------------ hilo de inferencia
    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            try:
                t0 = time.perf_counter()
                queue_ms = (t0 - item["queued_at"]) * 1000
                segments, _info = self.model.transcribe(
                    item["audio"],
                    language=self.language,
                    task="transcribe",
                    beam_size=self.beam_size,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    no_speech_threshold=0.6,
                    log_prob_threshold=-1.0,
                    compression_ratio_threshold=2.4,
                    without_timestamps=True,
                    vad_filter=False,
                    word_timestamps=False,
                )
                text = " ".join(s.text.strip() for s in segments).strip()
                infer_ms = (time.perf_counter() - t0) * 1000
                self.infer_ms.append(infer_ms)
                self.queue_ms.append(queue_ms)
                self.audio_infer_s += len(item["audio"]) / SAMPLE_RATE
                typ = "final" if text else "discard"
                self._emit(
                    typ,
                    seg=item["seg"],
                    text=text,
                    t_start=item["t_start"],
                    t_end=item["t_end"],
                    forced=item["forced"],
                    reason=item["reason"],
                    infer_ms=infer_ms,
                    queue_ms=queue_ms,
                    audio_s=len(item["audio"]) / SAMPLE_RATE,
                )
            finally:
                self._queue.task_done()
