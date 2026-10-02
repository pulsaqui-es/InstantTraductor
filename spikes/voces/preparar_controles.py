"""Prepara dos referencias de CONTROL a partir de las candidatas LibriVox que el humano ya rechazó (T040, 1.ª vuelta).

No son candidatas: sirven para calibrar si el acento de la referencia (con distinción /θ/-/s/ medida: Δ 14,0 y 11,6 dB) pasa a lo que
sintetiza Qwen3-TTS en modo ICL. Lee `%LOCALAPPDATA%\\InstantTraductor\\spikes\\voces-candidatas\\` (fuera del repo) y escribe
`<out>/es-f-ctrl-*_ref.wav|json`.

    uv run --project spikes/voces python spikes/voces/preparar_controles.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402

CONTROLES = {
    "es-f-ctrl-juanina": ("es-f-juanina.wav",
                          "Paquita bajó los ojos, y haciendo un esfuerzo consiguió ponerse colorada como un tomate. La madre arrugó el entrecejo.",
                          "Control: juanina (LibriVox 19250), «La gente cursi», cap. IV"),
    "es-f-ctrl-mongope": ("es-f-mongope.wav",
                          "Helena se posaba en su asiento solemne y fría, henchida de desdén, como una diosa llevada por el destino.",
                          "Control: Mongope (LibriVox 10246), «Abel Sánchez», cap. II"),
}


def main() -> None:
    src = c.vb.data_root() / "spikes" / "voces-candidatas"
    dst = c.out_dir()
    for cid, (wav, texto, nombre) in CONTROLES.items():
        shutil.copyfile(src / wav, dst / f"{cid}_ref.wav")
        c.guardar_json(dst / f"{cid}_ref.json", {
            "voice_id": cid, "name": nombre, "gender": "f",
            "source": "LibriVox (dominio público); ver docs/investigacion/2026-10-01-voces-castellanas.md",
            "license": "Dominio público (declaración general de LibriVox)", "ref_text": texto, "control": True,
        })
        print(cid, "->", dst / f"{cid}_ref.wav")


if __name__ == "__main__":
    main()
