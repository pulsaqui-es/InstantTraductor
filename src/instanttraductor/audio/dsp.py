"""Procesado de la voz en streaming: remuestreo y time-stretch (T027, research R9).

El servicio de voz entrega PCM mono ``float32`` a 24 kHz y el *sink* quiere 48 kHz. Entre medias, si el
motor no soporta ``speed`` (``Synthesizer.supports_speed = False``, el caso de Qwen3-TTS), el núcleo acelera
la voz con un *time-stretch* sobre el PCM. Ambos trabajan **por trozos** y guardan el estado de un trozo al
siguiente, de modo que partir el audio en trozos de cualquier tamaño da exactamente la misma salida que
procesarlo entero.

- ``StreamResampler(src_rate, dst_rate)``: remuestreo con ``soxr`` (calidad HQ; de 10 a 30 ms de retraso,
  según el tamaño de los trozos).
- ``StreamTimeStretch(speed)``: TDHS (*time-domain harmonic scaling*, biblioteca C ``stretch`` vía
  ``audiostretchy``; familia de Sonic). Cambia la duración sin cambiar el tono, con un factor exacto entre
  1,0 y 1,5, ~4 ms de CPU por segundo de audio y 28-46 ms de retraso algorítmico (research R9).
  Con ``speed == 1.0`` no toca el audio: sin retraso y bit a bit igual.

Uso por unidad (``is_last`` es el del último ``SynthesizedChunk``)::

    stretch = StreamTimeStretch(sample_rate=synth.sample_rate)
    resample = StreamResampler(synth.sample_rate, PLAYBACK_RATE)

    stretch.speed = decision.speed            # entre unidades (o antes del primer trozo de la unidad)
    for chunk in synth.synthesize(request):
        samples = resample.process(stretch.process(chunk.samples))
        if chunk.is_last:                     # la cola que guardan los dos algoritmos
            tail = resample.process(stretch.flush())
            samples = np.concatenate([samples, tail, resample.flush()])
        sink.enqueue(SpeechPiece(chunk.unit_id, samples, chunk.is_last))

``flush()`` devuelve lo que aún guardaba el algoritmo y deja el objeto listo para la unidad siguiente. Si se
descarta una unidad a medias, ``reset()`` tira el estado sin devolver nada.

Ninguno de los dos es seguro entre hilos: un objeto por flujo, usado desde un solo hilo.
"""

from __future__ import annotations

import weakref
from typing import Final

import numpy as np
import numpy.typing as npt
import soxr
from audiostretchy.stretch import TDHSAudioStretch

__all__ = [
    "DEFAULT_SAMPLE_RATE",
    "MAX_SPEED",
    "MIN_SPEED",
    "StreamResampler",
    "StreamTimeStretch",
]

Samples = npt.NDArray[np.float32]

#: Frecuencia de salida de Qwen3-TTS: la que usa ``StreamTimeStretch`` si no se le dice otra.
DEFAULT_SAMPLE_RATE: Final = 24_000
#: Rango de ``StreamTimeStretch.speed`` (el de ``SynthesisRequest.speed`` y de ``Settings.max_speed``).
MIN_SPEED: Final = 1.0
MAX_SPEED: Final = 1.5

#: Calidad de soxr: la más alta con un retraso razonable (10-30 ms a 24 -> 48 kHz).
_RESAMPLE_QUALITY: Final = "HQ"
#: Holgura de las comparaciones de velocidad: un ``1.5000000000000002`` por redondeo no es un error.
_SPEED_TOLERANCE: Final = 1e-9
#: Límites de frecuencia de la voz que busca TDHS (los mismos que ``audiostretchy`` por defecto, spike S1):
#: el periodo más corto es el de 333 Hz y el más largo el de 55 Hz.
_HIGHEST_PITCH_HZ: Final = 333
_LOWEST_PITCH_HZ: Final = 55
#: Muestras que se reservan para lo que ``flush()`` devuelve (la cola del algoritmo es de unos cientos).
_FLUSH_CAPACITY: Final = 1 << 16


def _check_rate(name: str, value: int) -> int:
    """Una frecuencia de muestreo: entero positivo en Hz."""
    if isinstance(value, bool) or not isinstance(value, int | np.integer) or value <= 0:
        raise ValueError(f"{name}: la frecuencia debe ser un entero positivo en Hz (recibido {value!r}).")
    return int(value)


def _as_mono_float32(samples: npt.ArrayLike) -> Samples:
    """``float32`` contiguo y 1-D, con los NaN a 0 y los infinitos a ±1 (un NaN contaminaría el filtro)."""
    x = np.ascontiguousarray(samples, dtype=np.float32)
    if x.ndim != 1:
        raise ValueError(f"El audio debe ser mono (1-D); recibido con forma {x.shape}.")
    if x.size and not np.isfinite(x).all():
        x = np.nan_to_num(x, nan=0.0, posinf=1.0, neginf=-1.0)
    return x


def _empty() -> Samples:
    return np.zeros(0, dtype=np.float32)


class StreamResampler:
    """Remuestreo en streaming (soxr, calidad HQ) de audio mono ``float32``.

    El filtro guarda audio de un trozo al siguiente, así que no hay saltos en las uniones; a cambio, el
    primer trozo sale entre 10 y 30 ms más corto (con un trozo de menos de ~30 ms puede no salir nada) y
    ``flush()`` entrega el resto. Con ``src_rate == dst_rate`` el audio pasa sin cambios. La salida se
    recorta a [-1, 1]: el filtro puede sobrepasar 1,0 con audio de plena escala.
    """

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        self._src_rate = _check_rate("src_rate", src_rate)
        self._dst_rate = _check_rate("dst_rate", dst_rate)
        self._stream: soxr.ResampleStream | None = (
            None
            if self._src_rate == self._dst_rate
            else soxr.ResampleStream(
                self._src_rate, self._dst_rate, 1, dtype="float32", quality=_RESAMPLE_QUALITY
            )
        )

    def __repr__(self) -> str:
        return f"StreamResampler({self._src_rate} -> {self._dst_rate} Hz)"

    @property
    def src_rate(self) -> int:
        return self._src_rate

    @property
    def dst_rate(self) -> int:
        return self._dst_rate

    def process(self, samples: npt.ArrayLike) -> Samples:
        """Remuestrea un trozo y devuelve el audio nuevo (un array nuevo, nunca el de entrada)."""
        x = _as_mono_float32(samples)
        if self._stream is None:
            return x.copy()
        if x.size == 0:
            return _empty()
        return self._clipped(self._stream.resample_chunk(x, last=False))

    def flush(self) -> Samples:
        """Entrega lo que el filtro aún guardaba y lo deja listo para la unidad siguiente."""
        if self._stream is None:
            return _empty()
        out = self._stream.resample_chunk(_empty(), last=True)
        self._stream.clear()
        return self._clipped(out)

    def reset(self) -> None:
        """Tira el estado (una unidad descartada a medias): lo que guardaba el filtro se pierde."""
        if self._stream is not None:
            self._stream.clear()

    @staticmethod
    def _clipped(out: Samples) -> Samples:
        out = np.ascontiguousarray(out, dtype=np.float32)
        np.clip(out, -1.0, 1.0, out=out)
        return out


def _check_speed(value: float) -> float:
    """La velocidad como ``float`` dentro de [1,0 , 1,5] (con una holgura de redondeo, que se recorta)."""
    try:
        speed = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"La velocidad debe ser un número entre {MIN_SPEED:g} y {MAX_SPEED:g} (recibida {value!r})."
        ) from None
    if not MIN_SPEED - _SPEED_TOLERANCE <= speed <= MAX_SPEED + _SPEED_TOLERANCE:  # falso también para NaN
        raise ValueError(f"La velocidad debe estar entre {MIN_SPEED:g} y {MAX_SPEED:g} (recibida {value!r}).")
    return min(MAX_SPEED, max(MIN_SPEED, speed))


def _to_int16(x: Samples) -> npt.NDArray[np.int16]:
    return np.clip(np.rint(x * np.float32(32768.0)), -32768.0, 32767.0).astype(np.int16)


def _from_int16(pcm: npt.NDArray[np.int16]) -> Samples:
    return pcm.astype(np.float32) * np.float32(1.0 / 32768.0)


class StreamTimeStretch:
    """*Time-stretch* TDHS en streaming: la voz ``speed`` veces más rápida, sin cambiar el tono.

    - ``speed``: de 1,0 a 1,5. Es el factor de aceleración: la salida dura ``1 / speed`` de la entrada.
      El error es de unos milisegundos por unidad (como mucho ~15 ms, un periodo de tono y la cola), así
      que en unidades de 1,5 s o más queda por debajo del 1 %.
    - ``sample_rate``: la del audio que se procesa (por defecto 24 kHz, la de Qwen3-TTS). Fija el rango de
      tonos que busca el algoritmo (55-333 Hz).

    ``speed`` se puede cambiar cuando se quiera, normalmente entre unidades: vale para el audio que se
    procese a partir de entonces. Con ``speed == 1.0`` (y sin audio pendiente) el audio pasa sin tocarse.

    El algoritmo guarda un trozo de señal entre llamadas (28-46 ms de retraso algorítmico): ``flush()``
    devuelve lo que quedaba al final de la unidad y deja el estirador listo para la siguiente. La
    biblioteca C se cuelga si sigue recibiendo audio tras un ``flush`` sin reiniciarse, así que este
    objeto crea un contexto nuevo para cada unidad.
    """

    def __init__(self, speed: float = MIN_SPEED, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self._sample_rate = _check_rate("sample_rate", sample_rate)
        self._speed = _check_speed(speed)
        self._stretch: TDHSAudioStretch | None = None
        self._release: weakref.finalize | None = None  # libera el contexto C aunque no se llame a flush()

    def __repr__(self) -> str:
        return f"StreamTimeStretch(speed={self._speed:g}, sample_rate={self._sample_rate})"

    @property
    def speed(self) -> float:
        return self._speed

    @speed.setter
    def speed(self, value: float) -> None:
        self._speed = _check_speed(value)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def process(self, samples: npt.ArrayLike) -> Samples:
        """Estira un trozo y devuelve el audio nuevo (un array nuevo, nunca el de entrada).

        Con ``speed > 1`` el primer trozo sale más corto de lo esperado (el retraso algorítmico) y, si el
        trozo es más corto que un periodo de tono, no sale nada hasta el siguiente o hasta ``flush()``.
        """
        x = _as_mono_float32(samples)
        if x.size == 0:
            return _empty()
        if self._stretch is None and self._speed == MIN_SPEED:
            return x.copy()  # nada pendiente y sin acelerar: ni retraso ni cuantización a 16 bits
        stretch = self._context()
        pcm = _to_int16(x)
        out = np.empty(stretch.output_capacity(pcm.size, 1.0), dtype=np.int16)
        written = stretch.process_samples(pcm, pcm.size, out, 1.0 / self._speed)
        return _from_int16(out[:written])

    def flush(self) -> Samples:
        """Entrega lo que el algoritmo aún guardaba (a velocidad normal) y empieza una unidad nueva."""
        stretch = self._stretch
        if stretch is None:
            return _empty()
        try:
            out = np.empty(_FLUSH_CAPACITY, dtype=np.int16)
            written = stretch.flush(out)
            return _from_int16(out[:written])
        finally:
            self._dispose()

    def reset(self) -> None:
        """Tira el estado (una unidad descartada a medias): lo que guardaba el algoritmo se pierde."""
        self._dispose()

    # -- contexto de la biblioteca C -------------------------------------------------------------------
    def _context(self) -> TDHSAudioStretch:
        if self._stretch is None:
            rate = self._sample_rate
            stretch = TDHSAudioStretch(
                max(1, rate // _HIGHEST_PITCH_HZ), max(2, rate // _LOWEST_PITCH_HZ), 1, 0
            )
            self._stretch = stretch
            self._release = weakref.finalize(self, stretch.deinit)
        return self._stretch

    def _dispose(self) -> None:
        release, self._release = self._release, None
        self._stretch = None
        if release is not None:
            release()  # ``deinit`` una sola vez
