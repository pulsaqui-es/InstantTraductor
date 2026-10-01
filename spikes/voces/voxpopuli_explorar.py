"""Camino B: explora VoxPopuli es (CC0, Parlamento Europeo) y lista hablantes femeninas con segmentos de 8-10 s.

    uv run --project spikes/voces python spikes/voces/voxpopuli_explorar.py descargar
    uv run --project spikes/voces python spikes/voces/voxpopuli_explorar.py resumen

`descargar` baja los parquet `validation` y `test` de `facebook/voxpopuli` (config `es`, sin cuenta; ~1 GB cada uno) a
`<out>/_trabajo/corpus/voxpopuli/`. `resumen` imprime, por hablante, el sexo declarado, los segmentos y su duración total, y guarda
`resumen_hablantes.json` (sin audio). El audio es WAV de 16 kHz mono.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

REPO = "facebook/voxpopuli"
FICHEROS = ["es/validation-00000-of-00001.parquet", "es/test-00000-of-00001.parquet"]


def carpeta() -> Path:
    return c.work_dir("corpus", "voxpopuli")


def descargar() -> None:
    from huggingface_hub import hf_hub_download

    for f in FICHEROS:
        p = hf_hub_download(REPO, f, repo_type="dataset", local_dir=str(carpeta()))
        print("->", p, round(Path(p).stat().st_size / 1e6), "MB", flush=True)


def resumen() -> None:
    import pyarrow.parquet as pq

    filas = []
    for f in FICHEROS:
        p = carpeta() / f
        pf = pq.ParquetFile(p)
        print(f, pf.metadata.num_rows, "filas", pf.schema_arrow.names)
        for batch in pf.iter_batches(batch_size=64, columns=["audio_id", "raw_text", "normalized_text", "gender", "speaker_id", "is_gold_transcript", "accent", "audio"]):
            d = batch.to_pydict()
            for i in range(len(d["audio_id"])):
                b = d["audio"][i]["bytes"]
                dur = (len(b) - 44) / 32000.0  # WAV PCM16 mono 16 kHz
                filas.append({"split": Path(f).name.split("-")[0], "audio_id": d["audio_id"][i], "gender": d["gender"][i], "speaker_id": d["speaker_id"][i],
                              "gold": d["is_gold_transcript"][i], "accent": d["accent"][i], "dur_s": round(dur, 2), "texto": d["raw_text"][i],
                              "normalizado": d["normalized_text"][i]})
    por: dict = {}
    for r in filas:
        h = por.setdefault(r["speaker_id"], {"gender": r["gender"], "accent": set(), "n": 0, "dur": 0.0, "n_8_10": 0})
        h["n"] += 1
        h["dur"] += r["dur_s"]
        h["accent"].add(str(r["accent"]))
        if 7.5 <= r["dur_s"] <= 10.5:
            h["n_8_10"] += 1
    print(len(filas), "segmentos;", len(por), "hablantes")
    mujeres = {k: v for k, v in por.items() if str(v["gender"]).lower().startswith("f")}
    print("hablantes femeninas:", len(mujeres))
    for k, v in sorted(mujeres.items(), key=lambda kv: -kv[1]["dur"])[:40]:
        print(f"  {k}: {v['n']} segmentos, {v['dur']:.0f} s, {v['n_8_10']} de 7,5-10,5 s, acento={sorted(v['accent'])}")
    c.guardar_json(carpeta() / "segmentos.json", filas)
    c.guardar_json(carpeta() / "resumen_hablantes.json", {k: {**v, "accent": sorted(v["accent"])} for k, v in por.items()})


if __name__ == "__main__":
    {"descargar": descargar, "resumen": resumen}[sys.argv[1]]()
