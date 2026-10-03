"""Silero VAD 6.2.x en streaming: `SileroVad`, que implementa `Vad` (research.md R5).

El modelo es el `silero_vad.onnx` de `component_dir("silero-vad")`, ejecutado con `onnxruntime` en CPU.
**No se usa el paquete `silero-vad`**, porque arrastra torch. Se porta `spikes/asr/asrspike/vad.py`.

`SileroOnnx` es el envoltorio del modelo: tramas de 512 muestras a 16 kHz (32 ms), con 64 muestras de contexto
delante y un estado recurrente `[2, 1, 128]`; es la misma interfaz que `OnnxWrapper` del paquete oficial.
`SileroVad` pone encima la lógica de disparo del `VADIterator` oficial:

- entra en habla con una trama de probabilidad ≥ `threshold` (0,30) y la deja con `min_silence_ms` (500 ms)
  seguidos sin habla; en ese silencio solo cuentan las tramas con probabilidad < `neg_threshold` (0,15): las
  intermedias ni abren ni cierran, y solo una trama ≥ `threshold` reinicia la cuenta. Los umbrales bajaron de
  0,5/0,35 en la spec 002 para no perder habla baja (research.md de la 002, R7: +1,7 puntos y +0,04 s);
- `speech_pad_ms` (150 ms) es el relleno previo: `SPEECH_START` se adelanta ese tiempo, sin pasar del primer
  audio recibido, para que quien alimente al ASR incluya el arranque de la primera palabra.
- **Reinicio del estado fuera del habla** (`state_reset_s`, 3 s): el estado recurrente de Silero se adapta al
  fondo, y con música o ambiente constantes deja de ver la voz al cabo de unos segundos (anime real en la
  validación de la 002: una escena de 80 s de diálogo con probabilidad ≈ 0). Tras 3 s seguidos fuera del habla
  se reinicia el modelo (estado y contexto); dentro del habla nunca. Medido en esa grabación: la escena pasa
  de 1 s a 46 s de habla detectada; en 10 min de música y efectos salen tramos cortos (≈ 0,4 s), pero ninguno
  llega a frase traducida tras el ASR y el filtro de idioma.

La probabilidad de habla es inyectable (`SileroVad(model=...)`): vale cualquier objeto con `prob(frame)` y
`reset()`. Así los tests unitarios no necesitan el modelo.

Tiempos de los eventos (reloj de audio, los `t_start` de los chunks):
- `SPEECH_START.t`: inicio de la primera trama con voz menos el relleno previo.
- `SPEECH_END.t`: final de la última trama con voz, **sin relleno**: es el final real del habla, la base del
  retardo de frase. El evento llega 500 ms después, cuando se confirma el silencio.

El VAD recibe chunks contiguos a `CAPTURE_RATE` (contrato de `AudioSource`) y toma el reloj del primer chunk
tras construirlo o tras `reset()`. No es seguro entre hilos: lo usa un único hilo (VAD/ASR).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final, Protocol

import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import (
    CAPTURE_RATE,
    AudioChunk,
    EngineError,
    VadEvent,
    VadEventKind,
)
from instanttraductor.setup.manifest import component_dir

Samples = npt.NDArray[np.float32]

ENGINE_NAME: Final = "silero-vad"
MODEL_FILE_NAME: Final = "silero_vad.onnx"
FRAME_SAMPLES: Final = 512  # muestras por trama: 32 ms a 16 kHz
CONTEXT_SAMPLES: Final = 64  # muestras de contexto que Silero exige delante de cada trama
FRAME_S: Final = FRAME_SAMPLES / CAPTURE_RATE


def default_model_path() -> Path:
    """El `.onnx` de Silero en la carpeta del componente `silero-vad` (lee el entorno al llamar)."""
    return component_dir("silero-vad") / MODEL_FILE_NAME


class SpeechProbabilityModel(Protocol):
    """Lo que `SileroVad` necesita de un modelo: la probabilidad de habla de una trama y volver a empezar."""

    def prob(self, frame: Samples) -> float:
        """Probabilidad de habla (0 a 1) de una trama de exactamente `FRAME_SAMPLES` muestras float32."""
        ...

    def reset(self) -> None:
        """Olvida el estado recurrente y el contexto."""
        ...


class SileroOnnx:
    """Modelo Silero VAD (ONNX) en CPU, con el contexto y el estado recurrente entre tramas."""

    def __init__(self, model_path: str | Path, *, num_threads: int = 1) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise EngineError(
                f"No se encuentra el modelo de Silero VAD: {path}. Ejecuta «instanttraductor preparar».",
                engine=ENGINE_NAME,
                recoverable=False,
            )
        import onnxruntime as ort  # perezoso: carga el motor nativo, que los tests con modelo falso no usan

        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = num_threads
        try:
            self._session = ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        except Exception as exc:  # ONNX Runtime lanza varios tipos (modelo corrupto, versión, memoria...)
            raise EngineError(
                f"No se pudo cargar Silero VAD desde {path}: {exc}", engine=ENGINE_NAME, recoverable=False
            ) from exc
        self._sample_rate = np.array(CAPTURE_RATE, dtype=np.int64)
        self._state: npt.NDArray[np.float32]
        self._context: npt.NDArray[np.float32]
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)

    def prob(self, frame: Samples) -> float:
        """Probabilidad de habla de una trama de exactamente `FRAME_SAMPLES` muestras float32."""
        x = np.concatenate([self._context, frame.reshape(1, FRAME_SAMPLES)], axis=1)
        try:
            out, state = self._session.run(None, {"input": x, "state": self._state, "sr": self._sample_rate})
        except Exception as exc:
            raise EngineError(
                f"Silero VAD falló al procesar una trama: {exc}", engine=ENGINE_NAME, recoverable=True
            ) from exc
        self._state = state
        self._context = x[:, -CONTEXT_SAMPLES:]
        return float(out[0, 0])


#: Umbrales por defecto (spec 002, research.md R7: habla baja sin subir las falsas alarmas medidas).
DEFAULT_THRESHOLD = 0.30
DEFAULT_NEG_THRESHOLD = 0.15
#: Segundos seguidos fuera del habla tras los que se reinicia el estado del modelo (validación de la 002).
DEFAULT_STATE_RESET_S = 3.0


class SileroVad:
    """VAD en streaming sobre tramas de 32 ms: `SPEECH_START` al entrar en habla y `SPEECH_END` al salir.

    Parámetros: `threshold` 0,30 y `neg_threshold` 0,15 (spec 002, R7; en la 001, 0,5 y 0,35),
    `min_silence_ms` 500, `speech_pad_ms` 150 y `state_reset_s` 3 (None: sin reinicios). `model` es la
    probabilidad inyectable; sin él se carga el modelo ONNX de `default_model_path()` (`EngineError` no
    recuperable si falta: lo instala `instanttraductor preparar`).

    Los eventos alternan START y END, y `in_speech` es True si y solo si el último fue START. Un tramo de
    habla muy corto (un chasquido) también produce su pareja START/END: descartarlo es cosa del ASR, que no
    reconocerá texto, y del segmentador, que no emite unidades sin texto.
    """

    def __init__(
        self,
        model: SpeechProbabilityModel | None = None,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        neg_threshold: float = DEFAULT_NEG_THRESHOLD,
        min_silence_ms: float = 500.0,
        speech_pad_ms: float = 150.0,
        state_reset_s: float | None = DEFAULT_STATE_RESET_S,
    ) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError(f"threshold debe estar en (0, 1]; recibido: {threshold}.")
        if not 0.0 < neg_threshold <= threshold:
            raise ValueError(f"neg_threshold debe estar en (0, threshold]; recibido: {neg_threshold}.")
        if min_silence_ms < 0.0 or speech_pad_ms < 0.0:
            raise ValueError("min_silence_ms y speech_pad_ms no pueden ser negativos.")
        if state_reset_s is not None and state_reset_s <= 0.0:
            raise ValueError(f"state_reset_s debe ser positivo o None; recibido: {state_reset_s}.")
        self.threshold = threshold
        self.neg_threshold = neg_threshold
        self.min_silence_ms = min_silence_ms
        self.speech_pad_ms = speech_pad_ms
        # Con muestras enteras no hay errores de redondeo al comparar tiempos.
        self._min_silence_samples = round(min_silence_ms * CAPTURE_RATE / 1000)
        self._pad_s = speech_pad_ms / 1000
        self.state_reset_s = state_reset_s
        self._reset_frames = None if state_reset_s is None else max(1, round(state_reset_s / FRAME_S))
        self._model: SpeechProbabilityModel = model if model is not None else SileroOnnx(default_model_path())
        self._pending: Samples
        self._origin: float | None
        self._frames: int
        self._triggered: bool
        self._silence_from: int | None
        self._last_speech_end: int
        self._quiet_frames: int
        self.reset()

    @property
    def in_speech(self) -> bool:
        return self._triggered

    def reset(self) -> None:
        """Vuelve al estado inicial: fuera del habla, sin audio pendiente y con el modelo reiniciado."""
        self._model.reset()
        self._pending = np.zeros(0, dtype=np.float32)  # muestras que aún no completan una trama
        self._origin = None  # reloj de audio de la muestra 0: el `t_start` del primer chunk
        self._frames = 0  # tramas procesadas desde el origen
        self._triggered = False
        self._silence_from = None  # muestra (desde el origen) en que empezó el silencio en curso
        self._last_speech_end = 0  # muestra en que terminó la última trama con voz
        self._quiet_frames = 0  # tramas seguidas fuera del habla desde el último reinicio del modelo

    def accept(self, chunk: AudioChunk) -> list[VadEvent]:
        if chunk.sample_rate != CAPTURE_RATE:
            raise ValueError(
                f"SileroVad trabaja a {CAPTURE_RATE} Hz y el chunk llega a {chunk.sample_rate} Hz."
            )
        if len(chunk.samples) == 0:
            return []
        if self._origin is None:
            self._origin = chunk.t_start
        samples = np.asarray(chunk.samples, dtype=np.float32)
        if len(self._pending):
            samples = np.concatenate([self._pending, samples])
        whole = len(samples) // FRAME_SAMPLES
        events: list[VadEvent] = []
        for index in range(whole):
            frame = samples[index * FRAME_SAMPLES : (index + 1) * FRAME_SAMPLES]
            self._maybe_reset_model()
            event = self._step(self._model.prob(frame))
            if event is not None:
                events.append(event)
        self._pending = samples[whole * FRAME_SAMPLES :].copy()
        return events

    def _maybe_reset_model(self) -> None:
        """Reinicia el modelo tras `state_reset_s` seguidos fuera del habla (ver el docstring del módulo)."""
        if self._triggered or self._reset_frames is None:
            self._quiet_frames = 0
            return
        if self._quiet_frames >= self._reset_frames:
            self._model.reset()
            self._quiet_frames = 0
        self._quiet_frames += 1

    def _at(self, sample: int) -> float:
        """Reloj de audio de una muestra contada desde el origen."""
        assert self._origin is not None
        return self._origin + sample / CAPTURE_RATE

    def _step(self, probability: float) -> VadEvent | None:
        start = self._frames * FRAME_SAMPLES
        end = start + FRAME_SAMPLES
        self._frames += 1

        if probability >= self.threshold:
            self._silence_from = None
            self._last_speech_end = end
            if self._triggered:
                return None
            self._triggered = True
            assert self._origin is not None
            return VadEvent(VadEventKind.SPEECH_START, max(self._origin, self._at(start) - self._pad_s))

        if self._triggered and probability < self.neg_threshold:
            if self._silence_from is None:
                self._silence_from = start
            if end - self._silence_from >= self._min_silence_samples:
                self._triggered = False
                self._silence_from = None
                return VadEvent(VadEventKind.SPEECH_END, self._at(self._last_speech_end))
        return None
