"""Informe del indicio de «distinción» /θ/-/s/: dos lectores de LibriVox frente a un control peninsular y otro argentino.

Datos (todo fuera del repo, en %LOCALAPPDATA%\\InstantTraductor\\spikes\\voz\\ref\\):
  - tux_trafalgar02_30_330      : LibriVox, Tux, «Trafalgar» sección 02, segundos 30-330 (MP3 de 64 kbps)
  - mongope_abel03_30_330       : LibriVox, Mongope, «Abel Sánchez» capítulo 3, segundos 30-330 (MP3 de 128 kbps)
  - es-es (90 clips)            : OpenSLR SLR61, mensajes meteorológicos en español peninsular (Google, CC BY-SA 4.0)
  - es-ar (90 clips)            : OpenSLR SLR61, mensajes meteorológicos en español argentino (seseo)
Cada clip/tramo se transcribe con Whisper-small (CPU) con tiempos por palabra (transcribir_varios.py / transcribir_lote.py).

    cd spikes/voz
    uv run python common/distincion_informe.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import distincion as d  # noqa: E402
import vozbench as vb  # noqa: E402

expl = vb.ref_dir() / "exploracion"
raw = vb.ref_dir() / "raw" / "es_weather_messages"

grupos: dict = {}

# Tramos largos (un WAV + su JSON)
for nombre in ["tux_trafalgar02_30_330", "mongope_abel03_30_330"]:
    wav, sr = vb.read_wav_mono(expl / f"{nombre}.wav")
    chunks = json.loads((expl / f"{nombre}.json").read_text(encoding="utf-8"))["chunks"]
    grupos[nombre] = d.resumir(d.medir_tokens(wav, sr, chunks))

# Lotes de clips cortos
for nombre, carpeta in [("es-ES_peninsular_SLR61", raw / "es-es"), ("es-AR_argentino_SLR61", raw / "es-ar")]:
    total = {"theta": [], "s": []}
    for wavp in sorted(carpeta.glob("*.wav")):
        jp = wavp.with_suffix(".json")
        if not jp.exists():
            continue
        wav, sr = vb.read_wav_mono(wavp)
        r = d.medir_tokens(wav, sr, json.loads(jp.read_text(encoding="utf-8"))["chunks"])
        total["theta"] += r["theta"]
        total["s"] += r["s"]
    grupos[nombre] = d.resumir(total)

print(f"{'grupo':28s} {'n θ':>4} {'n s':>4} {'nivel θ dB':>11} {'nivel s dB':>11} {'Δ (s-θ) dB':>11} {'p (U)':>10}")
for nombre, r in grupos.items():
    n = r["nivel_rel_db"]
    delta = n["s_mediana"] - n["theta_mediana"]
    print(f"{nombre:28s} {r['n_theta']:>4} {r['n_s']:>4} {n['theta_mediana']:>11.1f} {n['s_mediana']:>11.1f} {delta:>11.1f} {n.get('p_mann_whitney', float('nan')):>10.1e}")

informe = {
    "que_se_mide": "Nivel de la fricativa inicial/intervocálica relativo a la vocal más fuerte de la palabra (dB). Palabras «theta»: solo /θ/ (ce, ci, z, sin s); palabras «s»: solo /s/ intervocálica o inicial.",
    "interpretacion": "Con distinción (castellano peninsular) la fricativa de las palabras «theta» es mucho más débil que la de las «s» (Δ grande y significativo). Con seseo (español de América, andaluz) son la misma /s/ (Δ ~ 0).",
    "limites": "Es un indicio acústico, no una prueba del país del lector. El control argentino solo tiene la palabra «hace» como ejemplo de «theta»; los datos de los lectores de LibriVox son prosa libre transcrita con Whisper-small.",
    "grupos": grupos,
}
print("->", vb.save_json("distincion.json", informe))
