"""Identificación del idioma hablado con Whisper multilingüe (tiny/base, ONNX de sherpa-onnx) en CPU.

La API ``SpokenLanguageIdentification`` de sherpa-onnx solo devuelve el idioma de mayor puntuación. Para poder
**restringir** la decisión a un subconjunto de idiomas ({elegido, es}, {elegido, es, en}...) este módulo hace lo
mismo que ``detect_language`` de Whisper con los mismos ONNX: log-mel de 30 s -> codificador -> decodificador con
solo ``<|startoftranscript|>`` -> logits de los tokens de idioma. Se contrasta con el resultado de sherpa-onnx
(``sherpa_top1``).
"""

from __future__ import annotations

import time

import numpy as np
import onnxruntime as ort

from idiomas.paths import models_dir

SR = 16_000
N_FFT = 400
HOP = 160
N_MELS = 80
CHUNK = 30 * SR  # Whisper mira siempre 30 s


def _mel_filters(n_mels: int = N_MELS) -> np.ndarray:
    """Banco de filtros mel «slaney» (el de ``librosa.filters.mel`` que usa Whisper)."""
    f_sp = 200.0 / 3
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0

    def hz_to_mel(f):
        f = np.asarray(f, dtype=np.float64)
        return np.where(f >= min_log_hz, min_log_mel + np.log(np.maximum(f, 1e-9) / min_log_hz) / logstep, f / f_sp)

    def mel_to_hz(m):
        m = np.asarray(m, dtype=np.float64)
        return np.where(m >= min_log_mel, min_log_hz * np.exp(logstep * (m - min_log_mel)), f_sp * m)

    fft_freqs = np.linspace(0, SR / 2, 1 + N_FFT // 2)
    mel_f = mel_to_hz(np.linspace(hz_to_mel(0.0), hz_to_mel(SR / 2), n_mels + 2))
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fft_freqs[None, :]
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    weights = np.maximum(0, np.minimum(lower, upper))
    weights *= (2.0 / (mel_f[2 : n_mels + 2] - mel_f[:n_mels]))[:, None]
    return weights.astype(np.float32)


_MEL = _mel_filters()
_WINDOW = np.hanning(N_FFT + 1)[:-1].astype(np.float32)  # hann periódica (torch.hann_window)


def log_mel(x: np.ndarray) -> np.ndarray:
    """Log-mel de Whisper de ``x`` (relleno de ceros a 30 s): forma (80, 3000)."""
    audio = np.zeros(CHUNK, dtype=np.float32)
    audio[: min(len(x), CHUNK)] = x[:CHUNK]
    padded = np.pad(audio, N_FFT // 2, mode="reflect")
    n_frames = 1 + (len(padded) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    spec = np.fft.rfft(padded[idx] * _WINDOW, axis=1)
    mag = (spec.real**2 + spec.imag**2)[:-1].T  # (201, 3000): se descarta la última trama
    mel = _MEL @ mag.astype(np.float32)
    log_spec = np.log10(np.maximum(mel, 1e-10))
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0).astype(np.float32)


class WhisperLid:
    """Puntuaciones de idioma de Whisper tiny/base (int8) con onnxruntime, en CPU."""

    def __init__(self, size: str = "tiny", threads: int = 1) -> None:
        base = models_dir() / f"sherpa-onnx-whisper-{size}"
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        self.enc = ort.InferenceSession(str(base / f"{size}-encoder.int8.onnx"), opts, providers=["CPUExecutionProvider"])
        self.dec = ort.InferenceSession(str(base / f"{size}-decoder.int8.onnx"), opts, providers=["CPUExecutionProvider"])
        meta = self.enc.get_modelmeta().custom_metadata_map
        self.lang_tokens = np.array([int(t) for t in meta["all_language_tokens"].split(",")])
        self.lang_codes = meta["all_language_codes"].split(",")
        self.sot = int(meta["sot"])
        self.n_layer = int(meta["n_text_layer"])
        self.n_state = int(meta["n_text_state"])
        self.size = size
        self.threads = threads
        self.base = base

    def logits(self, x: np.ndarray) -> np.ndarray:
        mel = log_mel(x)[None]
        cross_k, cross_v = self.enc.run(None, {"mel": mel})
        kv = np.zeros((self.n_layer, 1, 448, self.n_state), dtype=np.float32)
        out = self.dec.run(
            None,
            {
                "tokens": np.array([[self.sot]], dtype=np.int64),
                "in_n_layer_self_k_cache": kv,
                "in_n_layer_self_v_cache": kv,
                "n_layer_cross_k": cross_k,
                "n_layer_cross_v": cross_v,
                "offset": np.array([0], dtype=np.int64),
            },
        )[0]
        return out[0, -1, self.lang_tokens].astype(np.float64)

    def probs(self, x: np.ndarray, subset: tuple[str, ...] | None = None) -> dict[str, float]:
        """Probabilidad por idioma (softmax sobre todos o solo sobre ``subset``)."""
        lg = self.logits(x)
        codes = self.lang_codes
        if subset is not None:
            keep = [codes.index(c) for c in subset]
            lg, codes = lg[keep], [codes[i] for i in keep]
        e = np.exp(lg - lg.max())
        p = e / e.sum()
        return dict(zip(codes, p.tolist(), strict=True))

    def sherpa_top1(self, x: np.ndarray) -> str:
        import sherpa_onnx as so

        if not hasattr(self, "_sl"):
            cfg = so.SpokenLanguageIdentificationConfig(
                whisper=so.SpokenLanguageIdentificationWhisperConfig(
                    encoder=str(self.base / f"{self.size}-encoder.int8.onnx"),
                    decoder=str(self.base / f"{self.size}-decoder.int8.onnx"),
                ),
                num_threads=self.threads,
            )
            self._sl = so.SpokenLanguageIdentification(cfg)
        st = self._sl.create_stream()
        st.accept_waveform(SR, x)
        return self._sl.compute(st)


def timed(fn, *args):
    t0 = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - t0
