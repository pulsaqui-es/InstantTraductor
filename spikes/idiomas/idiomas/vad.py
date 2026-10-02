"""Silero VAD 6.2.x (ONNX, CPU) en streaming, con histéresis y detección de fin de turno.

El modelo se ejecuta con onnxruntime (un hilo, CPU) sobre tramas de 512 muestras a 16 kHz
(32 ms), con 64 muestras de contexto y un estado recurrente ``[2, 1, 128]``. Es la misma
interfaz que usa ``OnnxWrapper`` del paquete oficial ``silero-vad``, pero sin torch.

La lógica de disparo copia la de ``VADIterator`` (umbral de entrada ``threshold`` y de salida
``threshold - 0.15``) con dos diferencias pensadas para el segmentador de la tubería:
- el silencio se cuenta desde el INICIO de la primera trama silenciosa;
- los eventos llevan dos tiempos: cuándo se decide (reloj de audio, fin de la trama) y a qué
  instante del audio corresponde la frontera de habla.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16_000
FRAME = 512  # muestras por trama (32 ms)
CONTEXT = 64  # muestras de contexto que Silero exige delante de cada trama
FRAME_S = FRAME / SAMPLE_RATE


class SileroOnnx:
    """Modelo Silero VAD (ONNX) en CPU, con estado entre tramas."""

    def __init__(self, model_path: str, num_threads: int = 1) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = num_threads
        self.session = ort.InferenceSession(str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT), dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        """Probabilidad de habla de una trama de exactamente 512 muestras float32."""
        x = np.concatenate([self._context, frame.reshape(1, FRAME)], axis=1)
        out, self._state = self.session.run(None, {"input": x, "state": self._state, "sr": self._sr})
        self._context = x[:, -CONTEXT:]
        return float(out[0, 0])


@dataclass(frozen=True)
class VadEvent:
    """Evento del detector. Todos los tiempos están en segundos del reloj de audio."""

    kind: str  # "start" | "end" | "cancel"
    decided_at: float  # instante en el que se toma la decisión (fin de la trama que la provoca)
    boundary: float  # frontera de habla: inicio (con relleno previo) o fin (con relleno posterior)
    speech_start: float | None = None  # solo en "end"/"cancel": inicio del tramo
    speech_end: float | None = None  # solo en "end"/"cancel": último instante con habla (sin relleno)


class StreamingVad:
    """Puerta de voz y detector de fin de turno sobre tramas de 32 ms.

    Parámetros por defecto (§3.10 del informe): umbral 0,5 con salida en 0,35, relleno de
    100-200 ms y 300-500 ms de silencio para confirmar el fin.
    """

    def __init__(
        self,
        model: SileroOnnx,
        threshold: float = 0.5,
        neg_threshold: float | None = None,
        min_silence_ms: float = 500.0,
        min_speech_ms: float = 250.0,
        speech_pad_ms: float = 150.0,
    ) -> None:
        self.model = model
        self.threshold = threshold
        self.neg_threshold = max(threshold - 0.15, 0.01) if neg_threshold is None else neg_threshold
        self.min_silence_s = min_silence_ms / 1000.0
        self.min_speech_s = min_speech_ms / 1000.0
        self.speech_pad_s = speech_pad_ms / 1000.0
        self._buf = np.zeros(0, dtype=np.float32)
        self.reset()

    def reset(self) -> None:
        self.model.reset()
        self._buf = np.zeros(0, dtype=np.float32)
        self.frame_index = 0  # tramas ya procesadas
        self.triggered = False
        self._speech_start = 0.0
        self._silence_start: float | None = None
        self._last_speech_end = 0.0
        self.probs: list[float] = []  # probabilidades por trama (diagnóstico)

    @property
    def in_speech(self) -> bool:
        return self.triggered

    def push(self, chunk: np.ndarray) -> list[VadEvent]:
        """Acepta audio de cualquier tamaño y devuelve los eventos de las tramas completadas."""
        self._buf = np.concatenate([self._buf, chunk.astype(np.float32, copy=False)])
        events: list[VadEvent] = []
        while len(self._buf) >= FRAME:
            frame, self._buf = self._buf[:FRAME], self._buf[FRAME:]
            ev = self._step(self.model.prob(frame))
            if ev is not None:
                events.append(ev)
        return events

    def flush(self) -> list[VadEvent]:
        """Cierra un tramo abierto al terminar el audio (no hay más silencio que esperar)."""
        if not self.triggered:
            return []
        end_t = self.frame_index * FRAME_S
        return [self._close(end_t, self._silence_start if self._silence_start is not None else end_t)]

    def _step(self, p: float) -> VadEvent | None:
        t_start = self.frame_index * FRAME_S
        t_end = t_start + FRAME_S
        self.frame_index += 1
        self.probs.append(p)

        if p >= self.threshold:
            self._silence_start = None
            self._last_speech_end = t_end
            if not self.triggered:
                self.triggered = True
                self._speech_start = t_start
                return VadEvent("start", decided_at=t_end, boundary=max(0.0, t_start - self.speech_pad_s))
            return None

        if self.triggered and p < self.neg_threshold:
            if self._silence_start is None:
                self._silence_start = t_start
            if t_end - self._silence_start >= self.min_silence_s:
                return self._close(t_end, self._silence_start)
        return None

    def _close(self, decided_at: float, silence_start: float) -> VadEvent:
        self.triggered = False
        self._silence_start = None
        speech_end = min(silence_start, self._last_speech_end) if self._last_speech_end else silence_start
        kind = "end" if speech_end - self._speech_start >= self.min_speech_s else "cancel"
        return VadEvent(
            kind,
            decided_at=decided_at,
            boundary=speech_end + self.speech_pad_s,
            speech_start=self._speech_start,
            speech_end=speech_end,
        )
