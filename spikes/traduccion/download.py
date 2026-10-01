"""Descarga y verifica llama.cpp (Windows, CUDA 13.4) y el GGUF oficial de Hy-MT2-1.8B.

Todo se guarda FUERA del repositorio, en ``%LOCALAPPDATA%\\InstantTraductor``:

- binarios: ``bin\\llama.cpp\\b11146\\`` (los zips) y ``...\\cuda-13.4-x64\\`` (extraídos);
- modelo: ``models\\Hy-MT2-1.8B-Q8_0.gguf``.

Las versiones están FIJADAS con su tamaño y SHA-256 (comprobados el 2026-09-30):

- llama.cpp ``v0.5.0``: release estable oficial de ggml-org (2026-09-23). Sus binarios
  cuelgan del build ``b11146`` (commit ``7fe450e19``): la release ``v0.5.0`` solo trae un
  fichero ``nightly-tag.txt`` que apunta a ese build.
- Se usa la build CUDA 13.4 (incluye sm_120 = Blackwell) más el zip de las DLL de CUDA
  (cudart, cuBLAS), porque el equipo no tiene el toolkit de CUDA instalado.
- Modelo: ``tencent/Hy-MT2-1.8B-GGUF`` (Apache 2.0, sin acceso restringido).

No requiere cuentas ni permisos de administrador.

Uso::

    uv run python download.py            # descarga lo que falte y extrae
    uv run python download.py --check    # solo verifica lo que ya está
    uv run python download.py --with-7b  # añade Hy-MT2-7B Q4_K_M (opcional, para comparar)
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from llama_server import APP_DIR, DEFAULT_MODEL, DEFAULT_SERVER_DIR, LLAMA_BUILD

LLAMA_RELEASE = "v0.5.0"
_GH = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}"


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    sha256: str


LLAMA_ASSETS: tuple[Asset, ...] = (
    Asset(
        f"llama-{LLAMA_BUILD}-bin-win-cuda-13.4-x64.zip",
        f"{_GH}/llama-{LLAMA_BUILD}-bin-win-cuda-13.4-x64.zip",
        149_758_833,
        "b1866c0ce76bc7bfb0c24b33e9a37e9669f1be18539b12c74ce361f81c41f047",
    ),
    Asset(
        "cudart-llama-bin-win-cuda-13.4-x64.zip",
        f"{_GH}/cudart-llama-bin-win-cuda-13.4-x64.zip",
        423_535_356,
        "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668",
    ),
)
MODEL = Asset(
    "Hy-MT2-1.8B-Q8_0.gguf",
    "https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/main/Hy-MT2-1.8B-Q8_0.gguf",
    1_908_528_192,
    "5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4",
)

#: Modelo mayor, solo para la comparación opcional (``--with-7b``): ``tencent/Hy-MT2-7B-GGUF``.
MODEL_7B = Asset(
    "Hy-MT2-7B-Q4_K_M.gguf",
    "https://huggingface.co/tencent/Hy-MT2-7B-GGUF/resolve/main/Hy-MT2-7B-Q4_K_M.gguf",
    4_624_648_896,
    "9f96256500f3fc1ab4d64336b58f52a949a95ad7516b0c229476eef782f9f77b",
)

ZIP_DIR = APP_DIR / "bin" / "llama.cpp" / LLAMA_BUILD


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def is_valid(asset: Asset, path: Path) -> bool:
    """¿Existe el fichero con el tamaño y el SHA-256 esperados?"""
    return path.exists() and path.stat().st_size == asset.size and sha256_of(path) == asset.sha256


def download(asset: Asset, dest: Path) -> None:
    """Descarga ``asset`` a ``dest`` (vía fichero ``.part``) y verifica su SHA-256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    print(f"[download] {asset.name} ({asset.size / 1e6:.0f} MB) ...", flush=True)
    h = hashlib.sha256()
    done = 0
    next_report = 0.1
    with httpx.stream("GET", asset.url, follow_redirects=True, timeout=60.0) as resp:
        resp.raise_for_status()
        with open(part, "wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if done / asset.size >= next_report:
                    print(f"[download]   {done / asset.size:4.0%}", flush=True)
                    next_report += 0.1
    if h.hexdigest() != asset.sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 incorrecto para {asset.name}: {h.hexdigest()}")
    part.replace(dest)


def ensure(asset: Asset, dest: Path, check_only: bool = False) -> bool:
    if is_valid(asset, dest):
        print(f"[download] OK (tamaño y SHA-256 correctos): {dest}")
        return True
    if check_only:
        print(f"[download] FALTA o es incorrecto: {dest}")
        return False
    download(asset, dest)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="solo verificar, sin descargar")
    ap.add_argument("--with-7b", action="store_true", help="incluir también Hy-MT2-7B Q4_K_M (4,6 GB, opcional)")
    args = ap.parse_args()

    ok = True
    for asset in LLAMA_ASSETS:
        ok &= ensure(asset, ZIP_DIR / asset.name, args.check)
    if ok and not (DEFAULT_SERVER_DIR / "llama-server.exe").exists() and not args.check:
        DEFAULT_SERVER_DIR.mkdir(parents=True, exist_ok=True)
        for asset in LLAMA_ASSETS:
            with zipfile.ZipFile(ZIP_DIR / asset.name) as zf:
                zf.extractall(DEFAULT_SERVER_DIR)
        print(f"[download] extraído en {DEFAULT_SERVER_DIR}")
    elif (DEFAULT_SERVER_DIR / "llama-server.exe").exists():
        print(f"[download] llama-server.exe presente en {DEFAULT_SERVER_DIR}")
    ok &= ensure(MODEL, DEFAULT_MODEL, args.check)
    if args.with_7b:
        ok &= ensure(MODEL_7B, DEFAULT_MODEL.with_name(MODEL_7B.name), args.check)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
