"""Coloca en las rutas del manifiesto los componentes que ya descargaron los spikes (T013).

Solo para el orquestador durante el desarrollo:
- crea enlaces duros desde las rutas de los spikes, para no duplicar espacio;
- deja la voz masculina de referencia de S1 como ``voices/es-m-tux``;
- imprime en JSON el sha256 y el tamaño de cada fichero, y la revisión de Hugging Face, para
  completar ``src/instanttraductor/setup/manifest.py``.

Uso: ``uv run python scripts/dev_place_components.py``
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

HOME = Path(os.environ["LOCALAPPDATA"]) / "InstantTraductor"
NEMOTRON_SPIKE = "sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25"

# Revisiones (hash de commit) leídas de .cache/huggingface/download/*.metadata de cada descarga.
HF_REVISIONS = {
    "qwen3-tts": "5d83992436eae1d760afd27aff78a71d676296fc",
    "nemotron-en": "52056fdc070914a48dcd68b31b44d6a6f5b85902",
}


def link(src: Path, dst: Path) -> None:
    """Enlace duro de ``src`` en ``dst`` (copia si no se puede enlazar). Idempotente."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if dst.stat().st_size == src.stat().st_size:
            return
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def describe(base: Path, rel_paths: list[str]) -> list[list[object]]:
    return [[rel, sha256(base / rel), (base / rel).stat().st_size] for rel in rel_paths]


def main() -> None:
    result: dict[str, dict[str, object]] = {}

    # llama.cpp: los zips (lo que verifica el manifiesto) y su contenido extraído junto a ellos.
    llama_src = HOME / "bin" / "llama.cpp" / "b11146"
    llama_dst = HOME / "bin" / "llama-cpp"
    for zip_file in llama_src.glob("*.zip"):
        link(zip_file, llama_dst / zip_file.name)
    for item in (llama_src / "cuda-13.4-x64").iterdir():
        if item.is_file():
            link(item, llama_dst / item.name)

    # Hy-MT2: un GGUF por componente.
    for component_id, name in (
        ("hy-mt2-7b-q4", "Hy-MT2-7B-Q4_K_M.gguf"),
        ("hy-mt2-1.8b-q8", "Hy-MT2-1.8B-Q8_0.gguf"),
    ):
        link(HOME / "models" / name, HOME / "models" / component_id / name)

    # Nemotron: los cuatro ficheros que usa sherpa-onnx.
    nemotron_files = ["tokens.txt", "encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx"]
    for rel in nemotron_files:
        link(HOME / "models" / NEMOTRON_SPIKE / rel, HOME / "models" / "nemotron-en" / rel)
    result["nemotron-en"] = {
        "hf_revision": HF_REVISIONS["nemotron-en"],
        "files": describe(HOME / "models" / "nemotron-en", nemotron_files),
    }

    # Silero VAD: el .onnx y su LICENSE, extraídos del wheel por el spike S3.
    silero_files = ["silero_vad.onnx", "LICENSE"]
    for rel in silero_files:
        link(HOME / "models" / "silero-vad-6.2.3" / rel, HOME / "models" / "silero-vad" / rel)
    result["silero-vad"] = {"files": describe(HOME / "models" / "silero-vad", silero_files)}

    # Qwen3-TTS: ya está en su sitio (models/qwen3-tts-12hz-0.6b-base). Todo el repo salvo la caché.
    qwen_dir = HOME / "models" / "qwen3-tts-12hz-0.6b-base"
    qwen_files = sorted(
        p.relative_to(qwen_dir).as_posix()
        for p in qwen_dir.rglob("*")
        if p.is_file() and ".cache" not in p.relative_to(qwen_dir).parts
    )
    result["qwen3-tts"] = {
        "hf_revision": HF_REVISIONS["qwen3-tts"],
        "files": describe(qwen_dir, qwen_files),
    }

    # Voz masculina de referencia del spike S1.
    ref_dir = HOME / "spikes" / "voz" / "ref"
    voices = HOME / "voices"
    link(ref_dir / "ref_es_es_24k.wav", voices / "es-m-tux.wav")
    meta = json.loads(
        (Path(__file__).resolve().parents[1] / "spikes" / "voz" / "referencia.json").read_text("utf-8")
    )
    voice_info = {
        "voice_id": "es-m-tux",
        "name": "Tux (LibriVox)",
        "gender": "m",
        "source": f"{meta['origen']}; {meta['minuto']}; {meta['url_audio']}",
        "license": "Dominio público",
        "ref_text": meta["texto"],
    }
    (voices / "es-m-tux.json").write_text(json.dumps(voice_info, ensure_ascii=False, indent=2), "utf-8")
    result["voz es-m-tux"] = {"files": describe(voices, ["es-m-tux.wav"])}

    # Comprobación de los GGUF y zips ya fijados en el manifiesto.
    result["comprobacion"] = {
        "hy-mt2-7b-q4": sha256(HOME / "models" / "hy-mt2-7b-q4" / "Hy-MT2-7B-Q4_K_M.gguf"),
        "hy-mt2-1.8b-q8": sha256(HOME / "models" / "hy-mt2-1.8b-q8" / "Hy-MT2-1.8B-Q8_0.gguf"),
        "llama-server.exe": (llama_dst / "llama-server.exe").exists(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
