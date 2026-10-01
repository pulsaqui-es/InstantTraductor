"""Descarga los modelos extra de este spike a `%LOCALAPPDATA%\\InstantTraductor\\models\\` (nunca dentro del repo; sin cuenta ni token: `gated=False`).

    uv run --project spikes/voces python spikes/voces/descargar_modelos.py voicedesign   # Qwen3-TTS-12Hz-1.7B-VoiceDesign (Apache-2.0, 4,52 GB)
    uv run --project spikes/voces python spikes/voces/descargar_modelos.py voxcpm2       # VoxCPM2 (Apache-2.0)

Con `local_dir` (sin caché de Hugging Face ni enlaces simbólicos, que en Windows duplicarían el disco). El motor de producción
(Qwen3-TTS-12Hz-0.6B-Base), faster-whisper-large-v3-turbo y whisper-small ya los bajó el spike S1 (`spikes/voz/common/descargar_modelos.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

MODELOS = {
    "voicedesign": ("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", c.QWEN3_DESIGN_DIR),
    "voxcpm2": ("openbmb/VoxCPM2", "voxcpm2"),
}


def main() -> None:
    from huggingface_hub import snapshot_download

    for nombre in sys.argv[1:] or list(MODELOS):
        repo, carpeta = MODELOS[nombre]
        destino = c.vb.models_dir() / carpeta
        p = snapshot_download(repo_id=repo, local_dir=str(destino))
        print(f"{repo} -> {p}")


if __name__ == "__main__":
    main()
