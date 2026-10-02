"""Deja una candidata lista para instalar como voz de la app: `<id>.wav` + `<id>.json` con solo los campos del contrato de voz.

El contrato (`specs/001-espina-dorsal/contracts/tts-service.md`) pide `<voices-dir>/<voice_id>.wav` (mono, 24 kHz, 6-10 s) y un `<voice_id>.json` con los
campos de `VoiceInfo` (`voice_id`, `name`, `gender`, `source`, `license`) más `ref_text`. Los `<id>_ref.json` del spike llevan además métricas; aquí se quitan.
No copia nada a la carpeta de voces de la app (eso lo decide quien elija la voz): escribe en `<out>/listas/`.

    uv run --project spikes/voces python spikes/voces/exportar_voz.py es-f-est-04 es-f-dis-06
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

CAMPOS = ("voice_id", "name", "gender", "source", "license", "ref_text")


def main() -> None:
    destino = c.out_dir() / "listas"
    destino.mkdir(exist_ok=True)
    for cid in sys.argv[1:]:
        meta = c.leer_json(c.out_dir() / f"{cid}_ref.json")
        c.guardar_json(destino / f"{cid}.json", {k: meta[k] for k in CAMPOS})
        shutil.copyfile(c.out_dir() / f"{cid}_ref.wav", destino / f"{cid}.wav")
        a, sr = c.vb.read_wav_mono(destino / f"{cid}.wav")
        print(f"{cid}: {len(a) / sr:.2f} s a {sr} Hz -> {destino}")


if __name__ == "__main__":
    main()
