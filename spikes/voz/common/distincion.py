"""Indicio acústico de «distinción» /θ/-/s/ (castellano peninsular) en un tramo de habla transcrito con tiempos por palabra.

Por qué: en Chatterbox es-es y en Qwen3-TTS el acento de la referencia importa, y no puedo escucharla. En castellano peninsular
«z, ce, ci» suena /θ/ (fricativa débil y difusa) distinta de /s/; en el español de América y en el andaluz con seseo son
iguales. Se mira la fricativa inicial de las palabras que empiezan por «ce/ci/z» y por «s+vocal»: si el hablante distingue,
la fricativa de las primeras es bastante más débil (relativa a la vocal siguiente) que la de las segundas.

Es un indicio, no una prueba de que el lector sea de España (hay hablantes peninsulares sin distinción y al revés). Uso:

    cd spikes/voz/qwen3
    uv run python ../common/distincion.py <tramo.wav> <tramo.json>      # el JSON sale de transcribir_ref.py / transcribir_varios.py
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
from scipy.signal import stft
from scipy.stats import mannwhitneyu

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vozbench as vb  # noqa: E402

NFFT = 512  # 21 ms a 24 kHz
HOP = 120  # 5 ms


def norm_word(w: str) -> str:
    w = unicodedata.normalize("NFKD", w.strip().lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return re.sub(r"[^a-zñ]", "", w)


def clase(w: str) -> str | None:
    """theta: palabras cuya única fricativa es /θ/ (ce, ci, z); s: solo /s/ intervocálica o inicial (sin otras fricativas)."""
    otras = re.search(r"(f|j|ge|gi|x|ch)", w)
    if otras:
        return None
    tiene_theta = re.search(r"(ce|ci|z)", w) is not None
    tiene_s = "s" in w
    if tiene_theta and not tiene_s:
        return "theta"
    if tiene_s and not tiene_theta and re.search(r"((^|[aeiou])s[aeiou])", w):
        return "s"
    return None


def medir_tokens(wav: np.ndarray, sr: int, chunks: list[dict]) -> dict:
    f, t, Z = stft(wav, fs=sr, nperseg=NFFT, noverlap=NFFT - HOP, window="hann", boundary=None, padded=False)
    P = np.abs(Z) ** 2  # (freq, frames)
    band_hf = (f >= 4000) & (f <= 11500)
    band_all = (f >= 100) & (f <= 11500)
    band_lf = (f >= 100) & (f <= 1000)
    band_cen = (f >= 2000) & (f <= 11500)
    total = P[band_all].sum(axis=0)
    hf = P[band_hf].sum(axis=0)
    lf = P[band_lf].sum(axis=0)
    ratio = hf / (total + 1e-12)
    floor = np.percentile(total, 10)
    fric = (ratio > 0.55) & (total > 4 * floor)

    res = {"theta": [], "s": []}
    palabras = {"theta": [], "s": []}
    for ch in chunks:
        ts = ch.get("timestamp")
        if not ts or ts[0] is None or ts[1] is None:
            continue
        w = norm_word(ch["text"])
        c = clase(w)
        if c is None or len(w) < 3:
            continue
        t0, t1 = ts
        i0 = int(np.searchsorted(t, t0 - 0.06))
        i1 = min(int(np.searchsorted(t, t1 + 0.04)), len(t))
        if i1 - i0 < 6:
            continue
        # racha de fricación dentro de la palabra: umbral relativo al máximo de la palabra (las grabaciones MP3 de LibriVox
        # tienen poca energía por encima de 4 kHz, así que un umbral absoluto dejaría casi todo fuera)
        thr = max(0.1, 0.5 * float(ratio[i0:i1].max()))
        ok = (ratio >= thr) & (total > 4 * floor)
        runs, cur = [], None
        for i in range(i0, i1):
            if ok[i]:
                cur = [i, i] if cur is None else [cur[0], i]
            elif cur:
                runs.append(cur)
                cur = None
        if cur:
            runs.append(cur)
        runs = [r for r in runs if r[1] - r[0] + 1 >= 4]  # al menos 20 ms
        if not runs:
            continue
        a, b = max(runs, key=lambda r: hf[r[0] : r[1] + 1].sum())
        spec = P[:, a : b + 1].mean(axis=1)
        cen = float((f[band_cen] * spec[band_cen]).sum() / (spec[band_cen].sum() + 1e-12))
        peak = float(f[band_cen][np.argmax(spec[band_cen])])
        vow = lf[i0:i1].max()  # vocal más fuerte de la palabra
        level = float(10 * np.log10(hf[a : b + 1].mean() + 1e-12) - 10 * np.log10(vow + 1e-12))
        res[c].append({"palabra": w, "t0": round(float(t0), 2), "dur_ms": (b - a + 1) * HOP / sr * 1000, "centroide_hz": cen, "pico_hz": peak, "nivel_rel_db": level})
        palabras[c].append(w)

    return res


def resumir(res: dict) -> dict:
    out: dict = {"n_theta": len(res["theta"]), "n_s": len(res["s"]), "palabras_theta": sorted({x["palabra"] for x in res["theta"]})}
    for clave in ("nivel_rel_db", "centroide_hz", "dur_ms", "pico_hz"):
        a = [x[clave] for x in res["theta"]]
        b = [x[clave] for x in res["s"]]
        out[clave] = {"theta_mediana": float(np.median(a)) if a else None, "s_mediana": float(np.median(b)) if b else None}
        if len(a) >= 3 and len(b) >= 3:
            out[clave]["p_mann_whitney"] = float(mannwhitneyu(a, b).pvalue)
    return out


def analizar(wav: np.ndarray, sr: int, chunks: list[dict]) -> dict:
    return resumir(medir_tokens(wav, sr, chunks))


if __name__ == "__main__":
    # Un tramo:  distincion.py <tramo.wav> <tramo.json>
    # Un lote:   distincion.py --lote <carpeta con .wav y .json por clip> [<carpeta2> ...]   (mezcla los tokens de todos los clips)
    if sys.argv[1] == "--lote":
        for carpeta in sys.argv[2:]:
            total = {"theta": [], "s": []}
            for wavp in sorted(Path(carpeta).glob("*.wav")):
                jp = wavp.with_suffix(".json")
                if not jp.exists():
                    continue
                wav, sr = vb.read_wav_mono(wavp)
                r = medir_tokens(wav, sr, json.loads(jp.read_text(encoding="utf-8"))["chunks"])
                total["theta"] += r["theta"]
                total["s"] += r["s"]
            print("==", carpeta)
            print(json.dumps(resumir(total), ensure_ascii=False, indent=1))
    else:
        wav, sr = vb.read_wav_mono(Path(sys.argv[1]))
        chunks = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["chunks"]
        print(json.dumps(analizar(wav, sr, chunks), ensure_ascii=False, indent=1))
