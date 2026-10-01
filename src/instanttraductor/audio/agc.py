"""AGC de margen amplio, antes del VAD y del ASR (T016, research R3).

El nivel que llega de la captura depende de la fuente: el volumen de sesión de la app de origen lo escala de
forma lineal (−6 dB al 50 %) y el nivel absoluto varía hasta 17 dB entre fuentes. `AutoGain` lo lleva a un
nivel estable para que el VAD y el ASR vean siempre algo parecido.

Cómo funciona (por chunk de 20 ms):

- **Nivel:** el RMS del chunk en dBFS. La ganancia deseada es `objetivo - nivel`, limitada a
  `[min_gain_db, max_gain_db]` (−20 dB a +30 dB).
- **Ataque y relajación:** la ganancia se acerca a la deseada con constantes de tiempo distintas según el
  sentido. Si hay que **bajarla** (la fuente suena más fuerte), con el ataque de 50 ms; si hay que
  **subirla**, con la relajación de 1 s. Así un golpe de volumen se corrige enseguida y los silencios entre
  palabras no disparan la ganancia. Como sigue antes los picos que los valles de la voz, el RMS medio de la
  salida queda algo por debajo del objetivo.
- **Puerta:** por debajo de `gate_dbfs` (−60 dBFS) el chunk es silencio o ruido de fondo y **la ganancia se
  mantiene**: no se sube para amplificar el silencio. Sin esto, tras unos segundos de ceros la ganancia
  estaría en +30 dB y la primera palabra saldría a todo volumen.
- **Sin saltos:** la ganancia cambia con una rampa lineal dentro del chunk, desde donde terminó el anterior.
- **Sin saturación:** si, aun así, un pico pasara de fondo de escala, se baja ese chunk entero (sin lookahead)
  en lugar de recortarlo: la salida siempre queda en [−1, 1].

`source_silent_for_s` mide cuánto lleva la entrada en **silencio digital** (ceros, o ruido numérico de menos
de −120 dBFS): una app silenciada o con el volumen al 0 % entrega ceros exactos. La sesión avisa de «sin audio
del origen» cuando pasa de `SOURCE_SILENCE_WARNING_S` (10 s).
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import AudioChunk

TARGET_DBFS: Final = -20.0  # nivel RMS al que se lleva la voz
ATTACK_S: Final = 0.05  # constante de tiempo al bajar la ganancia
RELEASE_S: Final = 1.0  # constante de tiempo al subir la ganancia
MAX_GAIN_DB: Final = 30.0  # nunca más de +30 dB
MIN_GAIN_DB: Final = -20.0  # y como mucho -20 dB (fuentes muy fuertes)
GATE_DBFS: Final = -60.0  # por debajo de este RMS la ganancia se mantiene
SILENCE_PEAK: Final = 1e-6  # pico por debajo del cual la entrada es silencio digital (-120 dBFS)
SOURCE_SILENCE_WARNING_S: Final = 10.0  # más de 10 s de silencio digital: «sin audio del origen»

_PEAK_LIMIT: Final = 0.999  # tope de la salida, con un poco de margen sobre el fondo de escala


class AutoGain:
    """Control automático de ganancia con puerta, ataque y relajación (ver el módulo).

    Un `AutoGain` por fuente de audio: tiene estado (la ganancia actual y el tiempo en silencio). No es seguro
    llamar a `process` desde varios hilos a la vez; leer `gain_db` y `source_silent_for_s` desde otro hilo sí.
    """

    def __init__(
        self,
        *,
        target_dbfs: float = TARGET_DBFS,
        attack_s: float = ATTACK_S,
        release_s: float = RELEASE_S,
        max_gain_db: float = MAX_GAIN_DB,
        min_gain_db: float = MIN_GAIN_DB,
        gate_dbfs: float = GATE_DBFS,
    ) -> None:
        if attack_s <= 0 or release_s <= 0:
            raise ValueError("attack_s y release_s deben ser positivos.")
        if min_gain_db > max_gain_db:
            raise ValueError("min_gain_db no puede ser mayor que max_gain_db.")
        self._target_dbfs = target_dbfs
        self._attack_s = attack_s
        self._release_s = release_s
        self._max_gain_db = max_gain_db
        self._min_gain_db = min_gain_db
        self._gate_dbfs = gate_dbfs
        self._gain_db = min(max(0.0, min_gain_db), max_gain_db)
        self._applied = 10 ** (self._gain_db / 20)  # ganancia lineal con la que acabó el último chunk
        self._silent_s = 0.0

    @property
    def gain_db(self) -> float:
        """Ganancia actual en dB (empieza en 0)."""
        return self._gain_db

    @property
    def source_silent_for_s(self) -> float:
        """Segundos seguidos de silencio digital en la entrada (0 si el último chunk tenía señal)."""
        return self._silent_s

    def process(self, chunk: AudioChunk) -> AudioChunk:
        """El chunk con la ganancia aplicada: mismo `t_start` y frecuencia, con audio nuevo en float32."""
        samples = chunk.samples
        count = len(samples)
        if count == 0:
            return chunk
        duration = chunk.duration
        if float(np.max(np.abs(samples))) < SILENCE_PEAK:
            self._silent_s += duration
        else:
            self._silent_s = 0.0

        level_db = _rms_dbfs(samples)
        if level_db >= self._gate_dbfs:
            self._track(level_db, duration)

        gain = 10 ** (self._gain_db / 20)
        ramp = (self._applied + (gain - self._applied) * (np.arange(1, count + 1) / count)).astype(np.float32)
        out = samples * ramp
        peak = float(np.max(np.abs(out)))
        if peak > _PEAK_LIMIT:
            scale = _PEAK_LIMIT / peak
            out *= np.float32(scale)
            gain *= scale
        self._applied = gain
        return AudioChunk(samples=out, sample_rate=chunk.sample_rate, t_start=chunk.t_start)

    def _track(self, level_db: float, duration: float) -> None:
        """Acerca la ganancia a la deseada: con el ataque si hay que bajarla, con la relajación si subirla."""
        desired = min(max(self._target_dbfs - level_db, self._min_gain_db), self._max_gain_db)
        time_constant = self._attack_s if desired < self._gain_db else self._release_s
        self._gain_db += (1.0 - math.exp(-duration / time_constant)) * (desired - self._gain_db)


def _rms_dbfs(samples: npt.NDArray[np.float32]) -> float:
    power = float(np.mean(np.square(samples, dtype=np.float64)))
    return 10.0 * math.log10(power) if power > 0.0 else -math.inf
