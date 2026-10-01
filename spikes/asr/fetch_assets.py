"""Descarga los modelos y el audio de prueba del spike S3 (siempre fuera del repo).

Uso (desde ``spikes/asr``)::

    uv run python fetch_assets.py                 # Nemotron 160 y 560 ms + Silero + Whisper turbo + dataset
    uv run python fetch_assets.py --chunks 80 160 560 1120 --no-whisper

Todo es público y no pide cuenta ni aceptar términos:

- Nemotron Speech Streaming EN 0.6B (int8, exportación de sherpa-onnx, 2026-04-25):
  https://huggingface.co/csukuangfj2 (un repositorio por tamaño de trozo).
- Silero VAD 6.2.3 (MIT): se extrae ``silero_vad.onnx`` del wheel oficial de PyPI,
  sin instalar el paquete (que arrastra torch).
- faster-whisper large-v3-turbo (CTranslate2, FP16, MIT).
- LibriSpeech dummy (``hf-internal-testing/librispeech_asr_dummy``; LibriSpeech es CC BY 4.0).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import urllib.request
import zipfile

from asrspike import paths

NEMOTRON_REPO = "csukuangfj2/sherpa-onnx-nemotron-speech-streaming-en-0.6b-{chunk}ms-int8-2026-04-25"
WHISPER_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
DATASET_REPO = "hf-internal-testing/librispeech_asr_dummy"
SILERO_VERSION = "6.2.3"


def fetch_nemotron(chunk_ms: int) -> None:
    from huggingface_hub import snapshot_download

    dest = paths.nemotron_dir(chunk_ms)
    if (dest / "encoder.int8.onnx").is_file():
        print(f"[nemotron {chunk_ms} ms] ya existe: {dest}")
        return
    print(f"[nemotron {chunk_ms} ms] descargando a {dest} ...")
    snapshot_download(repo_id=NEMOTRON_REPO.format(chunk=chunk_ms), local_dir=str(dest))


def fetch_silero() -> None:
    dest = paths.silero_model_path()
    if dest.is_file():
        print(f"[silero] ya existe: {dest}")
        return
    meta = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/silero-vad/{SILERO_VERSION}/json", timeout=60))
    wheel = next(f for f in meta["urls"] if f["filename"].endswith(".whl"))
    print(f"[silero] descargando {wheel['filename']} ({wheel['size'] / 1e6:.1f} MB)")
    data = urllib.request.urlopen(wheel["url"], timeout=300).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != wheel["digests"]["sha256"]:
        raise RuntimeError(f"SHA-256 del wheel de silero-vad no coincide: {digest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        dest.write_bytes(zf.read("silero_vad/data/silero_vad.onnx"))
        # La licencia MIT se guarda junto al modelo.
        (dest.parent / "LICENSE").write_bytes(zf.read(f"silero_vad-{SILERO_VERSION}.dist-info/licenses/LICENSE"))
    print(f"[silero] guardado en {dest}")


def fetch_whisper() -> None:
    from huggingface_hub import snapshot_download

    dest = paths.whisper_turbo_dir()
    if (dest / "model.bin").is_file():
        print(f"[whisper] ya existe: {dest}")
        return
    print(f"[whisper] descargando large-v3-turbo (CTranslate2, ~1,6 GB) a {dest} ...")
    snapshot_download(repo_id=WHISPER_REPO, local_dir=str(dest))


PUNCT_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/sherpa-onnx-online-punct-en-2024-08-06.tar.bz2"


def fetch_punct() -> None:
    """Modelo de restauración de puntuación y mayúsculas en inglés de sherpa-onnx (extra opcional)."""
    import tarfile

    dest = paths.punct_dir()
    if (dest / "model.onnx").is_file() or (dest / "model.int8.onnx").is_file():
        print(f"[puntuación] ya existe: {dest}")
        return
    print(f"[puntuación] descargando {PUNCT_URL} (~30 MB)")
    data = urllib.request.urlopen(PUNCT_URL, timeout=600).read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2") as tf:
        tf.extractall(dest.parent)
    print(f"[puntuación] guardado en {dest}")


def fetch_dataset() -> None:
    from huggingface_hub import snapshot_download

    path = snapshot_download(repo_id=DATASET_REPO, repo_type="dataset")
    print(f"[dataset] en la caché de Hugging Face: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chunks", type=int, nargs="*", default=[160, 560], help="trozos de Nemotron (ms)")
    parser.add_argument("--no-whisper", action="store_true", help="no descargar faster-whisper large-v3-turbo")
    parser.add_argument("--punct", action="store_true", help="descargar también el modelo de puntuación (extra)")
    args = parser.parse_args()

    fetch_silero()
    fetch_dataset()
    for chunk in args.chunks:
        fetch_nemotron(chunk)
    if not args.no_whisper:
        fetch_whisper()
    if args.punct:
        fetch_punct()
    print("Listo.")


if __name__ == "__main__":
    main()
