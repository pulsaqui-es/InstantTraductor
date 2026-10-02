"""Descarga los modelos del spike S5 (fuera del repo, en %LOCALAPPDATA%\\InstantTraductor\\spikes\\idiomas\\models).

Uso: ``uv run python fetch_models.py [nombre ...]`` (sin argumentos, todos).
Los paquetes de sherpa-onnx salen de la release ``asr-models``; el zipformer coreano comunitario, de Hugging Face.
"""

from __future__ import annotations

import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from idiomas.paths import models_dir

REL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"

#: nombre corto -> (carpeta extraída, fichero de la release)
SHERPA = {
    "xasr480": "sherpa-onnx-x-asr-480ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05",
    "xasr960": "sherpa-onnx-x-asr-960ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05",
    "zipformer_zh": "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30",
    "sensevoice": "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17",
    "nemotron35_560": "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11",
    "parakeet_ja": "sherpa-onnx-nemo-parakeet-tdt_ctc-0.6b-ja-35000-int8",
    "reazon_ja": "sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01",
    "whisper_tiny": "sherpa-onnx-whisper-tiny",
    "whisper_base": "sherpa-onnx-whisper-base",
}
HF = {
    "kangkyu_ko": ("kangkyu/icefall-asr-ko-streaming-zipformer-174m", "kangkyu-ko-zipformer-174m"),
}


def fetch_sherpa(key: str) -> Path:
    folder = SHERPA[key]
    dest = models_dir() / folder
    if dest.is_dir() and any(dest.iterdir()):
        print(f"[{key}] ya está: {dest}")
        return dest
    url = f"{REL}{folder}.tar.bz2"
    archive = models_dir() / f"{folder}.tar.bz2"
    print(f"[{key}] descargando {url}", flush=True)
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "instanttraductor-spike"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(archive, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    print(f"[{key}] {archive.stat().st_size / 1e6:.0f} MB en {time.time() - t0:.0f} s; extrayendo", flush=True)
    with tarfile.open(archive, "r:bz2") as tar:
        tar.extractall(models_dir())
    archive.unlink()
    return dest


def fetch_hf(key: str) -> Path:
    from huggingface_hub import snapshot_download

    repo, folder = HF[key]
    dest = models_dir() / folder
    path = snapshot_download(repo_id=repo, local_dir=str(dest))
    print(f"[{key}] {repo} -> {path}")
    return Path(path)


def main(argv: list[str]) -> None:
    keys = argv or [*SHERPA, *HF]
    for key in keys:
        if key in SHERPA:
            fetch_sherpa(key)
        elif key in HF:
            fetch_hf(key)
        else:
            raise SystemExit(f"modelo desconocido: {key}")


if __name__ == "__main__":
    main(sys.argv[1:])
