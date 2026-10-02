"""Verificador de idioma con Whisper base: `WhisperLanguageVerifier`, que implementa `LanguageVerifier`.

ADR-0012 y 0013, research.md R3. Whisper **base** multilingüe (licencia MIT) exportado a ONNX por
sherpa-onnx (codificador y decodificador int8), con onnxruntime en CPU y un hilo. Se porta de
`spikes/idiomas/idiomas/lid.py` (S5): con 300 recortes de 1-6 s por idioma acepta el 97,3 % (ja), el 99,0 %
(zh) y el 97,7 % (ko) del idioma correcto y deja pasar el 0,3-0,7 % del español, a 96/131 ms (p50/p95).

Cómo decide (lo mismo que `detect_language` de Whisper, con los mismos ONNX):
1. Log-mel de Whisper (80 bandas) del audio, con relleno de ceros **a la derecha** hasta una ventana fija
   de 6 s (600 tramas). Whisper original mira siempre 30 s, pero el codificador de sherpa-onnx admite
   ventanas más cortas: con 6 s es 7 veces más rápido y la precisión no cae (S5).
2. Codificador → claves y valores cruzados.
3. Decodificador con solo `<|startoftranscript|>`: los logits de los tokens de idioma de la primera posición.
4. Softmax **restringido a `VERIFIER_LANGUAGES`** ({en, es, ja, zh, ko}); la API de sherpa solo da el top-1 de
   los 99 idiomas, y por eso se reimplementa. Gana el idioma de mayor probabilidad y `accepted` es True si
   es el idioma elegido.

Entrada: mono, `float32`, a 16 kHz, de 1 a 6 s (contrato). Si dura **menos de 1 s, no se rechaza**: se rellena
con ceros hasta los 6 s igual que cualquier recorte corto (lo normal es que quien llama ya lo haya completado
por la izquierda con audio real, que da mejor resultado, R3). Si dura **más de 6 s**, se usan los últimos 6 s.

Las sesiones de onnxruntime se pueden inyectar (`encoder=` y `decoder=`): vale cualquier objeto con
`run(None, entradas)` y `get_modelmeta().custom_metadata_map` (el codificador). Los tests unitarios usan
dobles. No es seguro entre hilos (el hilo de traducción es el único que lo llama).

Ficheros del modelo que espera `create_sessions` en `component_dir("whisper-base-lid")`: `MODEL_FILES`.
"""

from __future__ import annotations

import functools
import time
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
import numpy.typing as npt

from instanttraductor.config import AppPaths
from instanttraductor.contracts import (
    CAPTURE_RATE,
    VERIFIER_LANGUAGES,
    EngineError,
    LanguageVerdict,
    SourceLanguage,
)

Samples = npt.NDArray[np.float32]

COMPONENT_ID: Final = "whisper-base-lid"
ENGINE_NAME: Final = "whisper-base-lid"
ENCODER_FILE: Final = "base-encoder.int8.onnx"
DECODER_FILE: Final = "base-decoder.int8.onnx"
MODEL_FILES: Final = (ENCODER_FILE, DECODER_FILE)
NUM_THREADS: Final = 1

WINDOW_S: Final = 6.0  # ventana fija de Whisper (en vez de sus 30 s originales)
N_FFT: Final = 400
HOP: Final = 160
N_MELS: Final = 80
KV_LENGTH: Final = 448  # longitud máxima de texto del decodificador de Whisper (caché vacía)


class OrtSession(Protocol):
    """Lo que `WhisperLanguageVerifier` usa de `onnxruntime.InferenceSession`."""

    def run(self, output_names: Any, input_feed: dict[str, Any]) -> list[Any]: ...

    def get_modelmeta(self) -> Any: ...


def default_model_dir() -> Path:
    """Carpeta del componente `whisper-base-lid` (= `AppPaths().models / "whisper-base-lid"`)."""
    return AppPaths().models / COMPONENT_ID


def create_sessions(
    model_dir: str | Path | None = None, *, threads: int = NUM_THREADS
) -> tuple[OrtSession, OrtSession]:
    """Sesiones de onnxruntime (codificador, decodificador) en CPU y con `threads` hilos.

    Un `EngineError` no recuperable avisa de que faltan ficheros del modelo (`instanttraductor preparar`) o de
    que onnxruntime no puede cargarlos.
    """
    base = Path(model_dir) if model_dir is not None else default_model_dir()
    missing = [name for name in MODEL_FILES if not (base / name).is_file()]
    if missing:
        raise EngineError(
            f"Faltan ficheros del modelo Whisper en {base}: {', '.join(missing)}. "
            "Ejecuta «instanttraductor preparar».",
            engine=ENGINE_NAME,
            recoverable=False,
        )
    try:
        import onnxruntime  # perezoso

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        providers = ["CPUExecutionProvider"]
        encoder = onnxruntime.InferenceSession(str(base / ENCODER_FILE), options, providers=providers)
        decoder = onnxruntime.InferenceSession(str(base / DECODER_FILE), options, providers=providers)
    except Exception as exc:
        raise EngineError(
            f"No se pudo cargar el modelo Whisper de {base}: {exc}", engine=ENGINE_NAME, recoverable=False
        ) from exc
    return encoder, decoder


@functools.cache
def _mel_filters() -> npt.NDArray[np.float32]:
    """Banco de filtros mel «slaney» (el de `librosa.filters.mel` que usa Whisper): forma (80, 201)."""
    sample_rate = CAPTURE_RATE
    f_sp = 200.0 / 3
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0

    def hz_to_mel(f: Any) -> Any:
        f = np.asarray(f, dtype=np.float64)
        log_part = min_log_mel + np.log(np.maximum(f, 1e-9) / min_log_hz) / logstep
        return np.where(f >= min_log_hz, log_part, f / f_sp)

    def mel_to_hz(m: Any) -> Any:
        m = np.asarray(m, dtype=np.float64)
        return np.where(m >= min_log_mel, min_log_hz * np.exp(logstep * (m - min_log_mel)), f_sp * m)

    fft_freqs = np.linspace(0, sample_rate / 2, 1 + N_FFT // 2)
    mel_f = mel_to_hz(np.linspace(hz_to_mel(0.0), hz_to_mel(sample_rate / 2), N_MELS + 2))
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fft_freqs[None, :]
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    weights = np.maximum(0, np.minimum(lower, upper))
    weights *= (2.0 / (mel_f[2 : N_MELS + 2] - mel_f[:N_MELS]))[:, None]
    return weights.astype(np.float32)


@functools.cache
def _window() -> npt.NDArray[np.float32]:
    return np.hanning(N_FFT + 1)[:-1].astype(np.float32)  # hann periódica (torch.hann_window)


def log_mel(samples: Samples, window_s: float = WINDOW_S) -> npt.NDArray[np.float32]:
    """Log-mel de Whisper de `samples`, con ceros a la derecha hasta `window_s`: (80, 100 · window_s).

    Lo que sobre de `window_s` se corta por la derecha (quien llama ya se queda con los últimos segundos).
    """
    n = round(window_s * CAPTURE_RATE)
    audio = np.zeros(n, dtype=np.float32)
    audio[: min(len(samples), n)] = samples[:n]
    padded = np.pad(audio, N_FFT // 2, mode="reflect")
    n_frames = 1 + (len(padded) - N_FFT) // HOP
    index = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    spectrum = np.fft.rfft(padded[index] * _window(), axis=1)
    magnitudes = (spectrum.real**2 + spectrum.imag**2)[:-1].T  # (201, tramas): se descarta la última trama
    mel = _mel_filters() @ magnitudes.astype(np.float32)
    log_spec = np.log10(np.maximum(mel, 1e-10))
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0).astype(np.float32)


class WhisperLanguageVerifier:
    """`LanguageVerifier` con Whisper base ONNX: ¿gana el idioma elegido entre {en, es, ja, zh, ko}?"""

    name = ENGINE_NAME

    def __init__(
        self,
        *,
        encoder: OrtSession | None = None,
        decoder: OrtSession | None = None,
        model_dir: str | Path | None = None,
        threads: int = NUM_THREADS,
    ) -> None:
        if (encoder is None) != (decoder is None):
            raise ValueError("Hay que inyectar el codificador y el decodificador a la vez, o ninguno.")
        if encoder is None or decoder is None:
            encoder, decoder = create_sessions(model_dir, threads=threads)
        self._encoder: OrtSession | None = encoder
        self._decoder: OrtSession | None = decoder
        try:
            meta = encoder.get_modelmeta().custom_metadata_map
            tokens = [int(token) for token in meta["all_language_tokens"].split(",")]
            codes = meta["all_language_codes"].split(",")
            self._sot = int(meta["sot"])
            self._n_layer = int(meta["n_text_layer"])
            self._n_state = int(meta["n_text_state"])
            # Posiciones, dentro de la lista de idiomas de Whisper, de los idiomas que decide el verificador.
            keep = [codes.index(code) for code in VERIFIER_LANGUAGES]
        except Exception as exc:
            raise EngineError(
                f"El modelo Whisper no trae los metadatos de idioma que se esperan: {exc!r}",
                engine=ENGINE_NAME,
                recoverable=False,
            ) from exc
        self._lang_tokens = np.array([tokens[i] for i in keep], dtype=np.int64)

    def verify(self, samples: Samples, sample_rate: int, language: SourceLanguage) -> LanguageVerdict:
        """¿Es `samples` habla en `language`? Ver el docstring del módulo para la longitud admitida."""
        encoder, decoder = self._encoder, self._decoder
        if encoder is None or decoder is None:
            raise EngineError("El verificador de idioma está cerrado.", engine=ENGINE_NAME, recoverable=False)
        if sample_rate != CAPTURE_RATE:
            raise ValueError(
                f"{ENGINE_NAME} trabaja a {CAPTURE_RATE} Hz y el audio llega a {sample_rate} Hz."
            )
        started = time.perf_counter()
        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        audio = audio[-round(WINDOW_S * CAPTURE_RATE) :]  # más de 6 s: los más recientes
        try:
            mel = log_mel(audio)[None]  # (1, 80, 600)
            cross_k, cross_v = encoder.run(None, {"mel": mel})
            cache = np.zeros((self._n_layer, 1, KV_LENGTH, self._n_state), dtype=np.float32)
            logits = decoder.run(
                None,
                {
                    "tokens": np.array([[self._sot]], dtype=np.int64),
                    "in_n_layer_self_k_cache": cache,
                    "in_n_layer_self_v_cache": cache,
                    "n_layer_cross_k": cross_k,
                    "n_layer_cross_v": cross_v,
                    "offset": np.array([0], dtype=np.int64),
                },
            )[0]
            scores = np.asarray(logits)[0, -1, self._lang_tokens].astype(np.float64)
        except Exception as exc:
            raise EngineError(
                f"El verificador de idioma falló: {exc}", engine=ENGINE_NAME, recoverable=True
            ) from exc
        exp = np.exp(scores - scores.max())
        probabilities = exp / exp.sum()
        winner = int(np.argmax(probabilities))
        detected = VERIFIER_LANGUAGES[winner]
        return LanguageVerdict(
            accepted=detected == str(language),
            detected=detected,
            probability=float(probabilities[winner]),
            elapsed_s=time.perf_counter() - started,
        )

    def close(self) -> None:
        """Suelta las sesiones. Idempotente; después, `verify` lanza `EngineError`."""
        self._encoder = None
        self._decoder = None
