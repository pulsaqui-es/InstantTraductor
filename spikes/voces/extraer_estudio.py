"""Camino B: extrae las referencias de estudio (`<id>_ref.wav` + `<id>_ref.json`) de VoxPopuli es (CC0) y de OpenSLR SLR61 (CC BY-SA 4.0).

    uv run --project spikes/voces python spikes/voces/extraer_estudio.py            # todas las de ESTUDIO
    uv run --project spikes/voces python spikes/voces/extraer_estudio.py es-f-est-01

Cada referencia se recorta entre pausas reales, se pasa a 24 kHz mono, RMS -20 dBFS (pico <= -1 dBFS) y fundidos de 30 ms (igual que
`prepare_reference.py` del spike S1). El `ref_text` sale de Whisper large-v3-turbo sobre el propio recorte y se contrasta con el
texto «raw_text» del corpus (VoxPopuli) o con el texto de la línea del TSV (SLR61).
"""

from __future__ import annotations

import difflib
import os
import sys
from math import gcd
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
import elegir_estudio as ee  # noqa: E402
import voxpopuli_explorar as vx  # noqa: E402

VOXPOPULI_LIC = ("CC0 1.0 (datos de VoxPopuli, Meta AI); audio original del Parlamento Europeo (sesiones plenarias), reutilización autorizada citando la fuente: "
                 "© Unión Europea, Parlamento Europeo. Aviso legal: https://www.europarl.europa.eu/legal-notice/es/")
SLR61_LIC = "CC BY-SA 4.0 (OpenSLR SLR61, Google; mensajes meteorológicos en español peninsular). Atribución: Copyright 2018, 2019 Google, Inc.; ver https://openslr.org/61/"

# Elegidas con `elegir_estudio.py cribar/tramos`: tramos de 8-10 s entre pausas reales de hablantes femeninas con distinción /θ/-/s/ (indicio) y buen SNR.
ESTUDIO: list[dict] = [
    {"id": "es-f-est-01", "fuente": "voxpopuli", "speaker_id": "28390", "audio_id": "20170405-0900-PLENARY-14-es_20170405-18:01:16_6",
     "t0": 0.0, "t1": 9.04, "nombre": "Eurodiputada 28390 (VoxPopuli)"},
    {"id": "es-f-est-02", "fuente": "voxpopuli", "speaker_id": "96922", "audio_id": "20110706-0900-PLENARY-6-es_20110706-14:02:19_0",
     "t0": 2.58, "t1": 11.6, "nombre": "Eurodiputada 96922 (VoxPopuli)"},
    {"id": "es-f-est-03", "fuente": "voxpopuli", "speaker_id": "103035", "audio_id": "20100615-0900-PLENARY-14-es_20100615-21:30:17_25",
     "t0": 4.28, "t1": 13.3, "nombre": "Eurodiputada 103035 (VoxPopuli)"},
    {"id": "es-f-est-04", "fuente": "voxpopuli", "speaker_id": "101146", "audio_id": "20100120-0900-PLENARY-10-es_20100120-17:48:45_11",
     "t0": 2.8, "t1": 12.68, "margen_ini": 0.06, "margen_fin": 0.06, "nombre": "Eurodiputada 101146 (VoxPopuli)"},  # márgenes cortos: <= 10 s
    {"id": "es-f-est-05", "fuente": "slr61", "speaker_id": "03397",
     "mensajes": ["esw_03397_01452159553", "esw_03397_00254676062", "esw_03397_01417960131", "esw_03397_00285442820"], "pausa_s": 0.30,
     "nombre": "Locutora 03397 (SLR61, estudio 48 kHz)"},
]


def a_24k(a: np.ndarray, sr: int) -> np.ndarray:
    if sr == c.SR:
        return a.astype(np.float32)
    from scipy.signal import resample_poly

    g = gcd(int(sr), c.SR)
    return resample_poly(a, c.SR // g, int(sr) // g).astype(np.float32)


def coincidencia(texto: str, referencia: str) -> float:
    """Fracción de palabras del texto (normalizado) que aparecen alineadas en la referencia."""
    a, b = c.aw.normalize_text(texto), c.aw.normalize_text(referencia)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    ok = sum(m.size for m in sm.get_matching_blocks())
    return ok / max(1, len(a))


def voxpopuli(e: dict) -> tuple[np.ndarray, str, dict]:
    segs = {s["audio_id"]: s for s in c.leer_json(vx.carpeta() / "segmentos.json")}
    seg = segs[e["audio_id"]]
    audio, sr = ee.cargar_audio({e["audio_id"]})[e["audio_id"]]
    # Recorta con un margen de silencio a cada lado (la pausa vecina es >= 0,15 s: se usa como máximo la mitad).
    i0 = max(0, int((e["t0"] - e.get("margen_ini", 0.10)) * sr))
    i1 = min(len(audio), int((e["t1"] + e.get("margen_fin", 0.12)) * sr))
    corte = audio[i0:i1]
    meta = {"fuente_texto": seg["texto"], "audio_id": e["audio_id"], "tramo_s": [e["t0"], e["t1"]], "speaker_id": e["speaker_id"],
            "gender_corpus": seg["gender"], "licencia": VOXPOPULI_LIC, "sr_origen": sr}
    return a_24k(corte, sr), seg["texto"], meta


def slr61(e: dict) -> tuple[np.ndarray, str, dict]:
    base = Path(os.environ["LOCALAPPDATA"]) / "InstantTraductor" / "spikes" / "voz" / "ref" / "raw"
    tsv = dict(line.split("\t") for line in (base / "es_es_line_index_weather.tsv").read_text(encoding="utf-8").splitlines())
    carpeta = base / "es_weather_messages" / "es-es"
    piezas, textos = [], []
    for m in e["mensajes"]:
        a, sr = c.vb.read_wav_mono(carpeta / f"{m}.wav")
        a = c.recortar_silencios(a, sr, margen_s=0.08)
        piezas.append(a_24k(a, sr))
        textos.append(tsv[m].strip().rstrip(".") + ".")
        piezas.append(np.zeros(int(e["pausa_s"] * c.SR), dtype=np.float32))
    audio = np.concatenate(piezas[:-1])
    texto = " ".join(textos)
    meta = {"fuente_texto": texto, "mensajes": e["mensajes"], "speaker_id": e["speaker_id"], "licencia": SLR61_LIC, "sr_origen": 48000}
    return audio, texto, meta


def main() -> None:
    quiero = set(sys.argv[1:])
    dst = c.out_dir()
    for e in ESTUDIO:
        if quiero and e["id"] not in quiero:
            continue
        audio, texto_corpus, meta = voxpopuli(e) if e["fuente"] == "voxpopuli" else slr61(e)
        audio = c.normalizar(audio, c.SR)
        asr = c.transcribir(audio, c.SR)
        coin = coincidencia(asr["text"], texto_corpus)
        st = c.f0_stats(audio, c.SR)
        c.vb.write_wav(dst / f"{e['id']}_ref.wav", audio, c.SR)
        info = {"voice_id": e["id"], "name": e["nombre"], "gender": "f",
                "source": f"{e['fuente']}: " + (f"{e['audio_id']} {e['t0']}-{e['t1']} s" if e["fuente"] == "voxpopuli" else "mensajes " + ", ".join(e["mensajes"])),
                "license": meta["licencia"], "ref_text": asr["text"] if e["fuente"] == "voxpopuli" else texto_corpus, "asr_texto": asr["text"], "duracion_s": round(len(audio) / c.SR, 2),
                "asr_vs_corpus_coincidencia": round(coin, 3), "texto_corpus": texto_corpus, **meta, **{k: v for k, v in st.items()}}
        c.guardar_json(dst / f"{e['id']}_ref.json", info)
        print(f"{e['id']}: {info['duracion_s']} s | F0 {st.get('f0_mediana_hz')} Hz | coincidencia con el corpus {coin:.2f}\n   ref_text: {asr['text']}")


if __name__ == "__main__":
    main()
