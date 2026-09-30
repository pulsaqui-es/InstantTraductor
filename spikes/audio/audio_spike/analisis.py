"""Deteccion de tonos por pico espectral relativo (robusta al ruido de fondo).

Como el humano puede estar oyendo otras cosas durante las pruebas, no se mira el nivel
absoluto: se mide la amplitud del seno a la frecuencia de la prueba (demodulacion compleja
con ventana de Hann) y se compara con la MEDIANA de la amplitud a otras 40 frecuencias de
referencia de la misma zona del espectro (sin la banda del tono). Un tono puro destaca
decenas de dB sobre esa mediana; la musica y el ruido no.
"""

from __future__ import annotations

import numpy as np

EPS = 1e-9


def dbfs(amplitud: float) -> float:
    return 20.0 * np.log10(max(float(amplitud), EPS))


def rms_dbfs(x: np.ndarray) -> float:
    if len(x) == 0:
        return float("-inf")
    return dbfs(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def _demod(x: np.ndarray, sr: int, frecuencias: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Amplitud (pico) del seno a cada frecuencia, con la ventana `w` ya calculada."""
    n = np.arange(len(x))
    fase = np.exp(-2j * np.pi * np.outer(frecuencias, n) / sr)
    z = fase @ (x.astype(np.float64) * w)
    return 2.0 * np.abs(z) / np.sum(w)


def frecuencias_referencia(f0: float, n_ref: int = 40, excluir_rel: float = 0.08,
                           banda_rel: tuple[float, float] = (0.55, 1.8), sr: int = 16000) -> np.ndarray:
    f = np.linspace(banda_rel[0] * f0, min(banda_rel[1] * f0, 0.45 * sr), n_ref)
    return f[np.abs(f - f0) > excluir_rel * f0]


def nivel_tono(x: np.ndarray, sr: int, f0: float) -> tuple[float, float, float]:
    """(amplitud del tono, amplitud de fondo = mediana, relacion en dB) para la señal `x`."""
    if len(x) < int(0.05 * sr):
        return 0.0, 0.0, 0.0
    w = np.hanning(len(x))
    a0 = _demod(x, sr, np.array([f0]), w)[0]
    ref = _demod(x, sr, frecuencias_referencia(f0, sr=sr), w)
    fondo = float(np.median(ref))
    a0 = max(a0, EPS)
    fondo = max(fondo, EPS)
    return float(a0), fondo, 20.0 * np.log10(a0 / fondo)


def barrido_tono(x: np.ndarray, sr: int, f0: float, ventana_s: float = 0.3, paso_s: float = 0.05):
    """Devuelve (centros_s, amplitudes, relaciones_db) con una ventana deslizante."""
    n_v = int(ventana_s * sr)
    n_p = max(1, int(paso_s * sr))
    centros, amps, ratios = [], [], []
    if len(x) < n_v:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    for ini in range(0, len(x) - n_v + 1, n_p):
        a0, _fondo, r = nivel_tono(x[ini : ini + n_v], sr, f0)
        centros.append((ini + n_v / 2) / sr)
        amps.append(a0)
        ratios.append(r)
    return np.array(centros), np.array(amps), np.array(ratios)


def maximo_tono(x: np.ndarray, sr: int, f0: float, ventana_s: float = 0.3) -> dict:
    """Resumen de una ventana: maximo de la relacion tono/fondo y maximo de la amplitud del tono.

    `ratio_db` decide si hay tono; `amp_dbfs` es el mayor nivel medido en cualquier ventana (no el de la
    ventana de mayor relacion, que puede caer en un tramo donde el nivel cambia poco pero es menor).
    """
    c, a, r = barrido_tono(x, sr, f0, ventana_s=ventana_s)
    if len(r) == 0:
        return {"ratio_db": 0.0, "amp_dbfs": dbfs(0.0), "t_s": None, "muestras": int(len(x))}
    i = int(np.argmax(r))
    return {"ratio_db": float(r[i]), "amp_dbfs": dbfs(float(np.max(a))), "t_s": float(c[i]), "muestras": int(len(x))}


# -- inicio del tono (latencia) ----------------------------------------------------------
def _envolvente(x: np.ndarray, sr: int, f0: float, largo: int) -> np.ndarray:
    """Envolvente causal (ventana rectangular de `largo` muestras) del seno a f0."""
    n = np.arange(len(x))
    z = x.astype(np.float64) * np.exp(-2j * np.pi * f0 * n / sr)
    c = np.cumsum(z)
    c = np.concatenate([np.zeros(largo, dtype=complex), c])
    return 2.0 * np.abs(c[largo:] - c[:-largo]) / largo


def inicio_tono(x: np.ndarray, sr: int, f0: float, largo_ms: float = 8.0, fraccion: float = 0.5) -> int | None:
    """Indice de muestra (aprox.) donde empieza el tono, o None si no hay.

    Se busca el primer cruce de `fraccion` de la meseta de la envolvente (causal, de
    `largo_ms`) y se corrige con el sesgo medido sobre un tono sintetico con el mismo
    fundido de entrada (`sesgo_inicio`).
    """
    largo = max(8, int(largo_ms * 1e-3 * sr))
    if len(x) < 2 * largo:
        return None
    env = _envolvente(x, sr, f0, largo)
    meseta = float(np.percentile(env, 99))
    if meseta < 1e-4:
        return None
    idx = np.nonzero(env >= fraccion * meseta)[0]
    if len(idx) == 0:
        return None
    return int(idx[0]) - sesgo_inicio(sr, f0, largo_ms, fraccion)


_SESGOS: dict = {}


def sesgo_inicio(sr: int, f0: float, largo_ms: float = 8.0, fraccion: float = 0.5) -> int:
    """Sesgo (en muestras) del detector de inicio: indice detectado menos indice real (0)."""
    clave = (sr, round(f0, 3), largo_ms, fraccion)
    if clave not in _SESGOS:
        from .tonos import generar_tono

        largo = max(8, int(largo_ms * 1e-3 * sr))
        relleno = np.zeros(int(0.05 * sr), dtype=np.float32)
        tono = generar_tono(f0, 0.3, 0.15, sr)
        x = np.concatenate([relleno, tono, relleno])
        env = _envolvente(x, sr, f0, largo)
        meseta = float(np.percentile(env, 99))
        idx = np.nonzero(env >= fraccion * meseta)[0]
        _SESGOS[clave] = int(idx[0]) - len(relleno)
    return _SESGOS[clave]
