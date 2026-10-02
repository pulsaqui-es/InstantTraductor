"""Descarga los modelos del spike S1 a %LOCALAPPDATA%\\InstantTraductor\\models (nunca dentro del repo).

Uso (desde el entorno que corresponda, no necesita candado de GPU):
    cd spikes/voz/qwen3       && uv run python ../common/descargar_modelos.py qwen3
    cd spikes/voz/chatterbox  && uv run python ../common/descargar_modelos.py chatterbox
    cd spikes/voz/qwen3       && uv run python ../common/descargar_modelos.py whisper   # solo para transcribir la referencia y la comprobación ASR

Se descarga con local_dir (sin caché de Hugging Face, sin enlaces simbólicos: en Windows duplicarían el disco).
Ninguno de estos repositorios exige cuenta ni aceptar términos (gated=False, licencias Apache-2.0 / MIT).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vozbench as vb  # noqa: E402

from huggingface_hub import hf_hub_download, snapshot_download  # noqa: E402


def qwen3() -> None:
    dst = vb.models_dir() / vb.QWEN3_MODEL_DIR
    p = snapshot_download(repo_id="Qwen/Qwen3-TTS-12Hz-0.6B-Base", local_dir=str(dst))
    print("Qwen3-TTS-0.6B-Base ->", p)


def chatterbox() -> None:
    dst = vb.models_dir() / vb.CHATTERBOX_MODEL_DIR
    dst.mkdir(parents=True, exist_ok=True)
    # Finetune es-ES (T3 + decodificador S3Gen v3 + tokenizador)
    for fname in ["t3_es_es.safetensors", "s3gen_v3.safetensors", "grapheme_mtl_merged_expanded_v1.json", "README.md"]:
        hf_hub_download(repo_id="ResembleAI/Chatterbox-Multilingual-es-es", filename=fname, local_dir=str(dst))
    # Piezas compartidas del modelo base multilingüe (codificador de voz, voz por defecto, mapa Cangjie)
    for fname in ["ve.pt", "conds.pt", "Cangjie5_TC.json"]:
        hf_hub_download(repo_id="ResembleAI/chatterbox", filename=fname, local_dir=str(dst))
    print("Chatterbox es-es ->", dst)


def whisper() -> None:
    dst = vb.models_dir() / "whisper-small"
    p = snapshot_download(
        repo_id="openai/whisper-small",
        local_dir=str(dst),
        allow_patterns=["*.json", "*.txt", "model.safetensors"],
    )
    print("whisper-small ->", p)


if __name__ == "__main__":
    what = sys.argv[1:] or ["qwen3", "chatterbox"]
    for w in what:
        {"qwen3": qwen3, "chatterbox": chatterbox, "whisper": whisper}[w]()
