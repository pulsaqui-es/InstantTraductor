"""Prepara la voz de referencia castellana (6-10 s) a partir de una grabación humana de LibriVox (dominio público).

Se ejecuta en el entorno ligero (sin torch):

    cd spikes/voz
    uv run python prepare_reference.py referencia      # la referencia definitiva: lee referencia.json, descarga y recorta
    uv run python prepare_reference.py bajar --ia <item_de_Internet_Archive> --fichero <mp3>
    uv run python prepare_reference.py extracto --raw <mp3> --inicio 60 --fin 150 --out <wav>   # tramos para explorar

Todo se escribe fuera del repo, en %LOCALAPPDATA%\\InstantTraductor\\spikes\\voz\\ref\\.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parent / "common"))
import vozbench as vb  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (compatible; InstantTraductorSpike/1.0)"}
TARGET_SR = 24000


def bajar(ia_id: str, fichero: str) -> Path:
    """Descarga un fichero de un item de Internet Archive a ref/raw/."""
    raw_dir = vb.ref_dir() / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dst = raw_dir / fichero
    if dst.exists() and dst.stat().st_size > 0:
        print("ya existe:", dst)
        return dst
    url = f"https://archive.org/download/{ia_id}/{fichero}"
    print("descargando", url)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(dst, "wb") as fh:
        fh.write(r.read())
    print("guardado:", dst, f"{dst.stat().st_size / 1e6:.1f} MB")
    return dst


def cargar_tramo(raw: Path, inicio: float, fin: float) -> np.ndarray:
    """Decodifica el MP3 con soundfile (libsndfile 1.2, mpg123), pasa a mono y a 24 kHz y recorta [inicio, fin] s."""
    a, sr = sf.read(str(raw), dtype="float32", always_2d=True)
    a = a.mean(axis=1)
    g = gcd(int(sr), TARGET_SR)
    a = resample_poly(a, TARGET_SR // g, int(sr) // g).astype(np.float32)
    i0, i1 = int(inicio * TARGET_SR), int(fin * TARGET_SR)
    return a[i0:i1]


def normalizar(a: np.ndarray, rms_dbfs: float = -20.0, pico_dbfs: float = -1.0) -> np.ndarray:
    """Ganancia para RMS objetivo, limitada para que el pico no pase de pico_dbfs."""
    rms = float(np.sqrt(np.mean(a**2)) + 1e-12)
    gain = 10 ** (rms_dbfs / 20) / rms
    peak = float(np.max(np.abs(a)) + 1e-12)
    gain = min(gain, 10 ** (pico_dbfs / 20) / peak)
    return (a * gain).astype(np.float32)


def fundidos(a: np.ndarray, ms: float = 30.0) -> np.ndarray:
    n = int(TARGET_SR * ms / 1000)
    w = np.linspace(0.0, 1.0, n, dtype=np.float32)
    a = a.copy()
    a[:n] *= w
    a[-n:] *= w[::-1]
    return a


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("bajar")
    p.add_argument("--ia", required=True)
    p.add_argument("--fichero", required=True)

    p = sub.add_parser("extracto")
    p.add_argument("--raw", required=True)
    p.add_argument("--inicio", type=float, required=True)
    p.add_argument("--fin", type=float, required=True)
    p.add_argument("--out", required=True)

    p = sub.add_parser("referencia")
    p.add_argument("--config", default=str(Path(__file__).with_name("referencia.json")), help="JSON con ia_id, fichero, inicio_s, fin_s y los datos de origen/licencia/texto")

    args = ap.parse_args()
    if args.cmd == "bajar":
        bajar(args.ia, args.fichero)
    elif args.cmd == "extracto":
        a = normalizar(cargar_tramo(Path(args.raw), args.inicio, args.fin))
        vb.write_wav(Path(args.out), a, TARGET_SR)
        print("extracto:", args.out, f"{len(a) / TARGET_SR:.1f} s")
    elif args.cmd == "referencia":
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        raw = bajar(cfg["ia_id"], cfg["fichero"])
        a = fundidos(normalizar(cargar_tramo(raw, cfg["inicio_s"], cfg["fin_s"])))
        out = vb.ref_dir() / vb.REF_WAV
        vb.write_wav(out, a, TARGET_SR)
        meta = dict(cfg)
        meta.update(
            {
                "duracion_s": round(len(a) / TARGET_SR, 3),
                "formato": f"WAV PCM16 mono {TARGET_SR} Hz, RMS -20 dBFS, fundidos de 30 ms",
                "sha256_wav": hashlib.sha256(out.read_bytes()).hexdigest(),
            }
        )
        (vb.ref_dir() / vb.REF_META).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print("referencia:", out, f"{meta['duracion_s']} s | sha256 {meta['sha256_wav'][:16]}...")


if __name__ == "__main__":
    main()
