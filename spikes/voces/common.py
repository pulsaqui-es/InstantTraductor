"""Utilidades del spike T040 (2.ª vuelta): voces femeninas castellanas, diseñadas y de estudio.

Reutiliza (solo lectura) lo del spike S1 de `spikes/voz/common`: candado de GPU, lectura y escritura de WAV, la comprobación
de inteligibilidad (WER) y el indicio de acento (`distincion.py`). Todo lo que se genera va FUERA del repo, en
`%LOCALAPPDATA%\\InstantTraductor\\spikes\\voces-v2\\`.

El indicio de acento es el de `distincion.py`: diferencia en dB entre la fuerza de la /s/ y la de la /θ/ (palabras con ce, ci, z),
ambas relativas a la vocal más fuerte de la palabra. Referencias del spike S1: control peninsular 15,5 dB; seseo argentino 1,8 dB.
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

import numpy as np

COMMON_VOZ = Path(__file__).resolve().parents[1] / "voz" / "common"
sys.path.insert(0, str(COMMON_VOZ))

import asr_whisper as aw  # noqa: E402  (normalize_text y wer; no importa torch hasta pedir el pipeline)
import distincion as dist  # noqa: E402
import vozbench as vb  # noqa: E402

SR = 24000
QWEN3_BASE_DIR = "qwen3-tts-12hz-0.6b-base"
QWEN3_DESIGN_DIR = "qwen3-tts-12hz-1.7b-voicedesign"
WHISPER_TURBO_DIR = "faster-whisper-large-v3-turbo"


def out_dir() -> Path:
    """Carpeta de muestras de esta vuelta (fuera del repo)."""
    p = vb.data_root() / "spikes" / "voces-v2"
    p.mkdir(parents=True, exist_ok=True)
    return p


def work_dir(*parts: str) -> Path:
    """Carpeta de trabajo (candidatas, cachés de ASR, descargas); también fuera del repo."""
    p = out_dir().joinpath("_trabajo", *parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------- frases comunes a TODAS las candidatas

# Las mismas 4 frases para todas. Cada una lleva palabras con /θ/ (ce, ci, z) y con /s/ para que el indicio de acento
# tenga material en lo generado (aprox. 13 palabras con /θ/ y 11 con /s/ entre las cuatro).
FRASES: list[dict] = [
    {"n": 1, "tipo": "diálogo natural",
     "texto": "Pues mira, la verdad es que no tenía ganas de hacer nada, así que me quedé en casa y pedí una pizza para cenar con Sara."},
    {"n": 2, "tipo": "pregunta",
     "texto": "¿Qué te parece si el sábado vamos a cenar al centro y luego nos tomamos una cerveza en la plaza?"},
    {"n": 3, "tipo": "exclamación",
     "texto": "¡Venga, date prisa, que son las doce y cinco y todavía no hemos salido de casa!"},
    {"n": 4, "tipo": "vosotros y léxico de España",
     "texto": "Vale, vosotros decidid: o apagáis ya el ordenador, o cogéis el móvil y llamáis a Sara, que yo cierro a las cinco."},
]


# --------------------------------------------------------------------------- audio


def rms_dbfs(a: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(a))) + 1e-12))


def recortar_silencios(a: np.ndarray, sr: int, margen_s: float = 0.15, umbral_db: float = 35.0) -> np.ndarray:
    """Recorta el silencio de los extremos dejando `margen_s` a cada lado.

    Silencio = tramas de 20 ms cuya energía queda `umbral_db` dB por debajo del percentil 95 de la energía por tramas.
    """
    n = int(0.02 * sr)
    if len(a) < 4 * n:
        return a
    frames = a[: len(a) // n * n].reshape(-1, n)
    e = 10 * np.log10(np.mean(frames**2, axis=1) + 1e-12)
    ref = np.percentile(e, 95)
    activo = np.where(e > ref - umbral_db)[0]
    if activo.size == 0:
        return a
    i0 = max(0, activo[0] * n - int(margen_s * sr))
    i1 = min(len(a), (activo[-1] + 1) * n + int(margen_s * sr))
    return a[i0:i1]


def normalizar(a: np.ndarray, sr: int, rms_obj_db: float = -20.0, pico_max_db: float = -1.0, fade_s: float = 0.03) -> np.ndarray:
    """RMS -20 dBFS con pico <= -1 dBFS y fundidos de 30 ms (igual que `prepare_reference.normalizar` del spike S1)."""
    a = np.asarray(a, dtype=np.float32).copy()
    g_rms = 10 ** ((rms_obj_db - rms_dbfs(a)) / 20)
    pico = float(np.max(np.abs(a))) + 1e-12
    g_pico = 10 ** (pico_max_db / 20) / pico
    a *= min(g_rms, g_pico)
    n = int(fade_s * sr)
    if n > 0 and len(a) > 2 * n:
        rampa = np.linspace(0.0, 1.0, n, dtype=np.float32)
        a[:n] *= rampa
        a[-n:] *= rampa[::-1]
    return a


# --------------------------------------------------------------------------- F0 (expresividad)


def f0_contour(a: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 450.0, frame_s: float = 0.040, hop_s: float = 0.010,
               thr: float = 0.45) -> np.ndarray:
    """F0 por autocorrelación normalizada (estilo Boersma) en tramas de 40 ms cada 10 ms; NaN donde no hay voz."""
    a = np.asarray(a, dtype=np.float64)
    n = int(frame_s * sr)
    hop = int(hop_s * sr)
    lagmin, lagmax = int(sr / fmax), int(sr / fmin)
    win = np.hanning(n)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    rw = np.fft.irfft(np.abs(np.fft.rfft(win, nfft)) ** 2)[: lagmax + 2]
    rw = rw / rw[0]
    gate = 10 ** (-45 / 20)  # silencio: RMS por debajo de -45 dBFS
    gate = max(gate, 0.05 * np.percentile(np.abs(a), 99)) if len(a) else gate
    out = []
    for i in range(0, len(a) - n, hop):
        x = a[i : i + n]
        if np.sqrt(np.mean(x**2)) < gate:
            out.append(np.nan)
            continue
        x = (x - x.mean()) * win
        r = np.fft.irfft(np.abs(np.fft.rfft(x, nfft)) ** 2)[: lagmax + 2]
        r = r / (r[0] + 1e-12) / np.maximum(rw, 1e-6)
        seg = r[lagmin : lagmax + 1]
        k = int(np.argmax(seg))
        pico = float(seg[k])
        if pico < thr:
            out.append(np.nan)
            continue
        lag = lagmin + k
        if 1 <= lag < len(r) - 1:  # interpolación parabólica
            y0, y1, y2 = r[lag - 1], r[lag], r[lag + 1]
            den = y0 - 2 * y1 + y2
            if abs(den) > 1e-12:
                lag = lag + 0.5 * (y0 - y2) / den
        out.append(sr / lag)
    f0 = np.array(out, dtype=np.float64)
    # filtro de mediana de 5 tramas sobre las sonoras para quitar saltos de octava aislados
    if np.isfinite(f0).sum() > 5:
        idx = np.where(np.isfinite(f0))[0]
        v = f0[idx].copy()
        pad = np.pad(v, 2, mode="edge")
        med = np.median(np.stack([pad[j : j + len(v)] for j in range(5)]), axis=0)
        bad = np.abs(np.log2(v / med)) > 0.35  # >4 semitonos de la mediana local: se descarta
        v[bad] = np.nan
        f0[idx] = v
    return f0


def f0_stats(a: np.ndarray, sr: int) -> dict:
    f0 = f0_contour(a, sr)
    v = f0[np.isfinite(f0)]
    if v.size < 20:
        return {"n_sonoras": int(v.size)}
    p10, p50, p90 = (float(np.percentile(v, q)) for q in (10, 50, 90))
    st = 12 * np.log2(v / p50)
    return {
        "n_sonoras": int(v.size),
        "f0_mediana_hz": round(p50, 1),
        "f0_p10_hz": round(p10, 1),
        "f0_p90_hz": round(p90, 1),
        "f0_rango_p10_p90_hz": round(p90 - p10, 1),
        "f0_rango_p10_p90_st": round(float(12 * np.log2(p90 / p10)), 2),
        "f0_desv_st": round(float(np.std(st)), 2),
        "porcentaje_sonoro": round(100 * float(np.isfinite(f0).mean()), 1),
    }


# --------------------------------------------------------------------------- ASR (faster-whisper large-v3-turbo en CPU)

_whisper = None


def get_whisper():
    global _whisper
    if _whisper is None:
        import os

        from faster_whisper import WhisperModel

        hilos = int(os.environ.get("VOCES_ASR_HILOS", "8"))
        _whisper = WhisperModel(str(vb.models_dir() / WHISPER_TURBO_DIR), device="cpu", compute_type="int8", cpu_threads=hilos)
    return _whisper


def transcribir(a: np.ndarray, sr: int, prompt: str | None = None) -> dict:
    """Devuelve {'text', 'chunks': [{'text','timestamp':(t0,t1)}]} (mismo formato que usa `distincion.py`)."""
    a16 = aw.to_16k(a, sr)
    model = get_whisper()
    segs, _ = model.transcribe(a16, language="es", beam_size=5, word_timestamps=True, condition_on_previous_text=False,
                               vad_filter=False, initial_prompt=prompt)
    chunks, texts = [], []
    for s in segs:
        texts.append(s.text)
        for w in s.words or []:
            chunks.append({"text": w.word, "timestamp": (float(w.start), float(w.end))})
    return {"text": " ".join(t.strip() for t in texts).strip(), "chunks": chunks}


def alinear_objetivo(chunks: list[dict], texto: str) -> list[dict]:
    """Pone a cada palabra del TEXTO PEDIDO los tiempos de la palabra que Whisper oyó en su lugar.

    `distincion.py` clasifica las palabras por su grafía (ce, ci, z frente a s). Si Whisper oye /θ/ como /t/ o /d/ («Cecilia» → «Detilia»),
    la palabra desaparece de la clase /θ/ y solo sobreviven las bien pronunciadas, lo que infla el indicio. Alineando con el texto pedido
    (1 a 1 en los tramos que no coinciden) se mide lo que realmente suena en el instante de cada palabra pedida.
    """
    obj = re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", texto)
    obj_n = [dist.norm_word(w) for w in obj]
    asr_n = [dist.norm_word(ch["text"]) for ch in chunks]
    sm = difflib.SequenceMatcher(a=asr_n, b=obj_n, autojunk=False)
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or (tag == "replace" and (i2 - i1) == (j2 - j1)):
            for k in range(i2 - i1):
                out.append({"text": obj[j1 + k], "timestamp": chunks[i1 + k].get("timestamp")})
    return out


def acento_tokens(a: np.ndarray, sr: int, chunks: list[dict], texto: str | None = None) -> dict:
    """Tokens de /θ/ y /s/ medidos por `distincion.py` (para mezclar varios clips antes de resumir).

    Con `texto` se miden las palabras del texto pedido alineadas con las que oyó Whisper (ver `alinear_objetivo`); sin él, las que escribió Whisper.
    """
    return dist.medir_tokens(a, sr, alinear_objetivo(chunks, texto) if texto else chunks)


def acento_resumen(tokens: dict) -> dict:
    """Resumen del indicio de acento: Δ(s−θ) en dB (positivo grande = distingue /θ/ de /s/), n y p de Mann-Whitney."""
    r = dist.resumir(tokens)
    niv = r.get("nivel_rel_db", {})
    t, s = niv.get("theta_mediana"), niv.get("s_mediana")
    return {
        "n_theta": r["n_theta"],
        "n_s": r["n_s"],
        "delta_s_menos_theta_db": None if t is None or s is None else round(float(s - t), 1),
        "p_mann_whitney": niv.get("p_mann_whitney"),
        "palabras_theta": r["palabras_theta"],
    }


def juntar_tokens(lista: list[dict]) -> dict:
    tot = {"theta": [], "s": []}
    for t in lista:
        tot["theta"] += t["theta"]
        tot["s"] += t["s"]
    return tot


_UNIDADES = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce", "trece", "catorce",
             "quince", "dieciseis", "diecisiete", "dieciocho", "diecinueve", "veinte"]
_DECENAS = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}


def num_a_palabras(n: int) -> str:
    """0-99 en palabras sin tildes (para comparar con el texto pedido)."""
    if n <= 20:
        return _UNIDADES[n]
    if n < 30:
        return "veinti" + _UNIDADES[n - 20]
    d, u = divmod(n, 10)
    return _DECENAS[d] + ("" if u == 0 else " y " + _UNIDADES[u])


def normalizar_numeros(texto: str) -> str:
    """Whisper escribe «doce y cinco» como «12 y 5»; se pasan a palabras para que no cuenten como errores del TTS."""
    return re.sub(r"\d{1,2}", lambda m: num_a_palabras(int(m.group())), texto)


def wer(ref: str, hyp: str) -> float:
    return aw.wer(ref, normalizar_numeros(hyp))


def guardar_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=vb._json_default), encoding="utf-8")


def leer_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
