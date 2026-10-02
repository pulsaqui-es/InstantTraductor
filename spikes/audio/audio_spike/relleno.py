"""Propuesta de relleno por reloj para la captura (ADR-0005, punto "en silencio no llegan paquetes").

Convierte los paquetes de la captura, que pueden llegar con huecos, en un flujo CONTINUO de
muestras alineado con el reloj de pared, para que el VAD y las marcas de tiempo no se desajusten.

Politica (aprendida en T4):
- El audio real NUNCA se recorta ni se duplica por jitter: un paquete que llega 25 ms tarde
  sigue siendo continuo con el anterior (en process loopback los paquetes se generan contando
  frames, no hay huecos). Solo se rellena con ceros un HUECO REAL: mas de `umbral_hueco_ms`
  (100 ms por defecto) sin paquetes.
- `tick(ahora_ns)` (cada 10-20 ms desde el consumidor) detecta el hueco y emite ceros hasta
  `ahora - margen`; el margen (40 ms) evita inventar ceros justo antes de que llegue un paquete.
- Al volver los paquetes tras un hueco, se alinea exactamente con el reloj: se anaden los ceros
  que falten o, si el relleno se adelanto, se recorta el principio del paquete (<= margen).
- Fuera de un hueco, la deriva entre el reloj de audio y el de pared se corrige moviendo
  suavemente la referencia (`_fin_ns`), sin tocar las muestras.

En process loopback (Windows 11 build 26200) llegan paquetes de ceros cada 10 ms aunque no suene
nada (ver T4), asi que aqui el relleno no entra en juego; se conserva como red de seguridad
(suspension, perdida del dispositivo) y para el fallback al loopback de dispositivo completo, que
SI deja huecos en silencio.
"""

from __future__ import annotations

import threading
from collections import deque

import numpy as np


class RellenoPorReloj:
    def __init__(self, sample_rate: int = 16000, margen_ms: float = 40.0, umbral_hueco_ms: float = 100.0,
                 reanclaje: float = 0.02) -> None:
        self.sr = sample_rate
        self.margen_ns = int(margen_ms * 1e6)
        self.umbral_ns = int(umbral_hueco_ms * 1e6)
        self.reanclaje = reanclaje
        self._fin_ns: int | None = None  # instante hasta el que la salida ya cubre segun el reloj
        self._en_hueco = False
        self._salida: deque[np.ndarray] = deque()
        self._lock = threading.Lock()
        # contadores (muestras o eventos)
        self.reales = 0
        self.rellenadas = 0
        self.recortadas = 0
        self.huecos = 0

    def _ceros(self, dur_ns: float) -> None:
        n = int(round(dur_ns * 1e-9 * self.sr))
        if n > 0:
            self._salida.append(np.zeros(n, dtype=np.float32))
            self.rellenadas += n
            self._fin_ns += int(n / self.sr * 1e9)

    def push(self, t_ns: int, muestras: np.ndarray) -> None:
        with self._lock:
            dur_ns = int(len(muestras) / self.sr * 1e9)
            inicio_ns = t_ns - dur_ns
            if self._fin_ns is None:
                self._fin_ns = inicio_ns
            desfase = inicio_ns - self._fin_ns
            if self._en_hueco:
                # fin de un hueco: alinear exactamente con el reloj
                if desfase > 0:
                    self._ceros(desfase)
                elif desfase < 0:
                    n = min(int(-desfase * 1e-9 * self.sr), len(muestras))
                    muestras = muestras[n:]
                    self.recortadas += n
                self._en_hueco = False
            elif desfase > self.umbral_ns:
                # hueco que `tick` aun no habia visto (p. ej. no se llamo a tick)
                self.huecos += 1
                self._ceros(desfase)
            else:
                # jitter y deriva: no se toca el audio; la referencia se mueve despacio
                self._fin_ns += int(desfase * self.reanclaje)
            if len(muestras):
                self._salida.append(muestras)
                self.reales += len(muestras)
                self._fin_ns += int(len(muestras) / self.sr * 1e9)

    def tick(self, ahora_ns: int) -> None:
        """Llamar cada 10-20 ms desde el consumidor: si hay un hueco, rellena con ceros."""
        with self._lock:
            if self._fin_ns is None:
                return
            limite_ns = ahora_ns - self.margen_ns
            if not self._en_hueco and limite_ns - self._fin_ns > self.umbral_ns:
                self._en_hueco = True
                self.huecos += 1
            if self._en_hueco and limite_ns > self._fin_ns:
                self._ceros(limite_ns - self._fin_ns)

    def recoger(self) -> np.ndarray:
        with self._lock:
            if not self._salida:
                return np.zeros(0, dtype=np.float32)
            datos = np.concatenate(list(self._salida))
            self._salida.clear()
            return datos

    @property
    def cubierto_hasta_ns(self) -> int | None:
        return self._fin_ns


def simular(llegadas: list[tuple[int, int]], sample_rate: int = 16000, paso_tick_ms: float = 20.0,
            margen_ms: float = 40.0, umbral_hueco_ms: float = 100.0, cola_s: float = 0.0) -> dict:
    """Reproduce una serie de llegadas (t_ns, n_muestras) con `tick` cada `paso_tick_ms`.

    `cola_s`: tiempo extra simulado tras la ultima llegada (para ver como se rellena un silencio final).
    Devuelve metricas de continuidad. `retraso` = ahora - hasta donde cubre la salida.
    """
    r = RellenoPorReloj(sample_rate, margen_ms, umbral_hueco_ms)
    if not llegadas:
        return {}
    llegadas = sorted(llegadas)
    t_ini = llegadas[0][0]
    t_fin = llegadas[-1][0] + int(cola_s * 1e9)
    paso = int(paso_tick_ms * 1e6)
    i = 0
    retrasos = []
    total = 0
    t = t_ini
    while t <= t_fin:
        while i < len(llegadas) and llegadas[i][0] <= t:
            r.push(llegadas[i][0], np.zeros(llegadas[i][1], dtype=np.float32))
            i += 1
        r.tick(t)
        total += len(r.recoger())
        if r.cubierto_hasta_ns is not None:
            retrasos.append((t - r.cubierto_hasta_ns) / 1e6)
        t += paso
    e = np.array(retrasos)
    return {
        "muestras_emitidas": total,
        "duracion_s": (t_fin - t_ini) / 1e9,
        "paquetes_reales_s": r.reales / sample_rate,
        "rellenadas_s": r.rellenadas / sample_rate,
        "recortadas_ms": r.recortadas / sample_rate * 1e3,
        "huecos": r.huecos,
        "retraso_medio_ms": float(e.mean()) if len(e) else 0.0,
        "retraso_max_ms": float(e.max()) if len(e) else 0.0,
    }


def autoprueba() -> None:
    """Comprobacion sintetica: jitter, deriva, paradas cortas (sin huecos) y dos huecos reales de 2 s."""
    rng = np.random.default_rng(1)
    sr = 16000
    llegadas: list[tuple[int, int]] = []
    base = 0
    for rafaga in range(3):  # tres rafagas de 2 s separadas por 2 s sin paquetes
        for k in range(200):
            t = base + int(k * 10_000_500 + rng.normal(0, 1.0e6))  # reloj de audio 50 ppm lento + jitter 1 ms
            if rafaga == 0 and 100 <= k < 104:
                t += 40_000_000  # parada de 40 ms: los paquetes se retrasan y luego llegan seguidos
            llegadas.append((t, 160))
        base += 200 * 10_000_500 + 2_000_000_000
    # los paquetes retrasados llegan en orden, sin huecos de audio
    llegadas.sort()
    m = simular(llegadas, sr, cola_s=0.0)
    # 1) solo se detectan los dos huecos reales; la parada de 40 ms no cuenta
    assert m["huecos"] == 2, m
    # 2) no se recorta audio real
    assert m["recortadas_ms"] < 15.0, m
    # 3) se rellenan ~2 s por cada hueco real (menos el margen y la deteccion) y nada mas
    assert abs(m["rellenadas_s"] - 4.0) < 0.25, m
    # 4) el retraso de la salida respecto del reloj queda acotado (margen + detecciones)
    assert m["retraso_max_ms"] < 260.0, m
    print("autoprueba OK:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()})


if __name__ == "__main__":
    autoprueba()
