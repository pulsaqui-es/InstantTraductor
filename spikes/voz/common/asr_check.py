"""Comprobación de inteligibilidad de ida y vuelta: Whisper-small (CPU) transcribe las muestras y se calcula el WER frente al texto.

No es una medida de acento ni de naturalidad (eso lo decide el humano escuchando): solo detecta audio roto, cortado o ininteligible.
Usa la CPU, pero hay que lanzarlo SIN mediciones de GPU en marcha (compite por CPU y falsearía el TTFA).

    cd spikes/voz/qwen3
    uv run python ../common/asr_check.py A_qwen3 [subcarpeta]
    uv run python ../common/asr_check.py B_chatterbox
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asr_whisper as asr  # noqa: E402
import vozbench as vb  # noqa: E402

prefijo = sys.argv[1]
sub = sys.argv[2] if len(sys.argv) > 2 else ""
base = vb.samples_dir() / sub if sub else vb.samples_dir()

filas = []
for i, frase in enumerate(vb.SAMPLE_SENTENCES, start=1):
    p = base / f"{prefijo}_{i:02d}.wav"
    if not p.exists():
        continue
    audio, sr = vb.read_wav_mono(p)
    t0 = time.perf_counter()
    hip = asr.transcribe(audio, sr, words=False)["text"].strip()
    w = asr.wer(frase, hip)
    filas.append({"muestra": p.name, "audio_s": round(len(audio) / sr, 2), "palabras": vb.count_words(frase), "palabras_por_s": round(vb.count_words(frase) / (len(audio) / sr), 2), "wer": round(w, 3), "texto": frase, "asr": hip})
    print(f"{p.name}: {len(audio) / sr:5.1f} s | WER {w * 100:5.1f} % | {hip}", flush=True)

if filas:
    wers = [f["wer"] for f in filas]
    resumen = {"wer_medio": round(sum(wers) / len(wers), 3), "wer_max": max(wers), "muestras": filas}
    nombre = f"asr_{prefijo}{'_' + sub if sub else ''}.json"
    print("WER medio:", resumen["wer_medio"], "->", vb.save_json(nombre, resumen))
else:
    print("no se encontraron muestras", prefijo, "en", base)
