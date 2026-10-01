"""Utilidades comunes del spike S1 (voz): rutas, candado de GPU, sondeo de VRAM, estadísticas, frases y WAV.

Solo depende de numpy, soundfile, filelock y nvidia-ml-py (las tienen los tres entornos del spike).
Todo lo que escribe va FUERA del repo, en %LOCALAPPDATA%\\InstantTraductor (modelos, WAV, candado),
salvo los JSON de resultados, que son pequeños y se copian también a spikes/voz/resultados/.
"""

from __future__ import annotations

import contextlib
import importlib.metadata as md
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------- rutas


def data_root() -> Path:
    """Carpeta de datos del proyecto (fuera del repo)."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise RuntimeError("LOCALAPPDATA no está definida: este spike es solo para Windows")
    return Path(base) / "InstantTraductor"


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    return _ensure(data_root() / "models")


def spike_dir() -> Path:
    return _ensure(data_root() / "spikes" / "voz")


def samples_dir() -> Path:
    return _ensure(spike_dir() / "muestras")


def ref_dir() -> Path:
    return _ensure(spike_dir() / "ref")


def results_dir() -> Path:
    return _ensure(spike_dir() / "resultados")


def repo_results_dir() -> Path:
    """spikes/voz/resultados/ dentro del repo (JSON pequeños con las cifras)."""
    return _ensure(Path(__file__).resolve().parents[1] / "resultados")


QWEN3_MODEL_DIR = "qwen3-tts-12hz-0.6b-base"
CHATTERBOX_MODEL_DIR = "chatterbox-multilingual-es-es"
REF_WAV = "ref_es_es_24k.wav"
REF_META = "ref_es_es_24k.json"


def save_json(name: str, obj: dict) -> Path:
    """Guarda un resultado en %LOCALAPPDATA% y en spikes/voz/resultados/ (mismo contenido)."""
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default)
    (results_dir() / name).write_text(text, encoding="utf-8")
    out = repo_results_dir() / name
    out.write_text(text, encoding="utf-8")
    return out


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)


# --------------------------------------------------------------------------- candado de GPU


@contextlib.contextmanager
def gpu_lock(timeout_s: float = 1800.0):
    """Candado de fichero compartido con el resto de obreros (%LOCALAPPDATA%\\InstantTraductor\\gpu.lock).

    Toda medición en GPU debe ir dentro de este bloque. Espera hasta 30 min y devuelve los segundos esperados.
    """
    from filelock import FileLock

    path = data_root() / "gpu.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path), timeout=timeout_s)
    t0 = time.perf_counter()
    print(f"[gpu.lock] esperando {path} (máx. {timeout_s / 60:.0f} min)...", flush=True)
    lock.acquire()
    waited = time.perf_counter() - t0
    print(f"[gpu.lock] adquirido tras {waited:.1f} s", flush=True)
    try:
        yield waited
    finally:
        lock.release()
        print("[gpu.lock] liberado", flush=True)


# --------------------------------------------------------------------------- VRAM (nvidia-smi / NVML)


def nvidia_smi_query(fields: str) -> list[str]:
    """Ejecuta nvidia-smi --query-gpu=<fields> y devuelve los valores de la primera GPU."""
    out = subprocess.run(
        ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return [x.strip() for x in out.splitlines()[0].split(",")]


def vram_used_mib_smi() -> float:
    """VRAM usada en total en la GPU según el binario nvidia-smi (MiB)."""
    return float(nvidia_smi_query("memory.used")[0])


class VramSampler:
    """Hilo que sondea la VRAM total usada (NVML, el mismo dato que nvidia-smi) y guarda el pico.

    En Windows (WDDM) NVML no da el uso por proceso, así que se mide el total de la GPU: con el candado
    cogido y el escritorio estable, pico - línea base = VRAM del proceso (incluye el contexto CUDA).
    """

    def __init__(self, interval_s: float = 0.1, index: int = 0):
        import pynvml

        self._nvml = pynvml
        pynvml.nvmlInit()
        self._h = pynvml.nvmlDeviceGetHandleByIndex(index)
        self.interval_s = interval_s
        self.total_mib = pynvml.nvmlDeviceGetMemoryInfo(self._h).total / 2**20
        self.baseline_mib = self.read_mib()
        self.peak_mib = self.baseline_mib
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def read_mib(self) -> float:
        return self._nvml.nvmlDeviceGetMemoryInfo(self._h).used / 2**20

    def _run(self) -> None:
        while not self._stop.is_set():
            v = self.read_mib()
            if v > self.peak_mib:
                self.peak_mib = v
            self._stop.wait(self.interval_s)

    def __enter__(self) -> "VramSampler":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.peak_mib = max(self.peak_mib, self.read_mib())

    def reset_peak(self) -> None:
        self.peak_mib = self.read_mib()


# --------------------------------------------------------------------------- estadísticas


def summarize(values) -> dict:
    a = np.asarray(list(values), dtype=float)
    if a.size == 0:
        return {"n": 0}
    return {
        "n": int(a.size),
        "mean": float(a.mean()),
        "p50": float(np.percentile(a, 50)),
        "p95": float(np.percentile(a, 95)),
        "min": float(a.min()),
        "max": float(a.max()),
    }


# --------------------------------------------------------------------------- WAV


def write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    import soundfile as sf

    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(a))) if a.size else 0.0
    if peak > 0.98:  # los motores pueden superar 1,0 (Chatterbox llega a 1,14): se baja la ganancia en vez de recortar
        a = a * (0.98 / peak)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), a, sr, subtype="PCM_16")


def read_wav_mono(path: Path, target_sr: int | None = None) -> tuple[np.ndarray, int]:
    import soundfile as sf

    a, sr = sf.read(str(path), dtype="float32", always_2d=True)
    a = a.mean(axis=1)
    if target_sr and sr != target_sr:
        from scipy.signal import resample_poly
        from math import gcd

        g = gcd(int(sr), int(target_sr))
        a = resample_poly(a, target_sr // g, sr // g).astype(np.float32)
        sr = target_sr
    return a, sr


# --------------------------------------------------------------------------- entorno


def collect_env_info(packages: list[str]) -> dict:
    info: dict = {
        "python": sys.version.split()[0],
        "plataforma": platform.platform(),
        "paquetes": {},
    }
    for p in packages:
        try:
            info["paquetes"][p] = md.version(p)
        except md.PackageNotFoundError:
            info["paquetes"][p] = None
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda_build"] = torch.version.cuda
        info["arch_list"] = torch.cuda.get_arch_list()
        info["sm_120"] = "sm_120" in torch.cuda.get_arch_list()
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            info["gpu"] = {"nombre": p.name, "vram_total_mib": round(p.total_memory / 2**20), "cc": f"{p.major}.{p.minor}"}
    except Exception as exc:  # noqa: BLE001
        info["torch_error"] = repr(exc)
    try:
        drv, cuda_ver = nvidia_smi_query("driver_version,name")[0], None
        info["driver_nvidia"] = drv
    except Exception as exc:  # noqa: BLE001
        info["driver_error"] = repr(exc)
    return info


# --------------------------------------------------------------------------- frases (español de España)

# 20 frases de medición, de 5 a 25 palabras. Mezclan registro coloquial, noticias, avisos y diálogo de series.
MEASURE_SENTENCES: list[str] = [
    "Vale, nos vemos luego en casa de Laura.",
    "¿Vosotros sabéis dónde he dejado las llaves del coche?",
    "No me lo puedo creer, otra vez se ha roto el ordenador.",
    "Tranquilo, tío, que lo arreglamos mañana por la mañana.",
    "Buenas noches, ¿qué tal todo?",
    "El tren con destino a Barcelona saldrá de la vía cuatro en cinco minutos.",
    "Me ha llamado mi madre al móvil y no he podido cogerlo.",
    "Vamos a tener que darnos prisa si queremos llegar antes de que empiece la película.",
    "Aquí tenéis la cuenta, y gracias por venir a nuestro restaurante.",
    "¡Cuidado! Viene un coche por la derecha y no va a frenar.",
    "Dicen que mañana lloverá en casi toda la península, aunque por la tarde saldrá el sol en el sur.",
    "¿Sabes qué hora es? Llevamos esperando casi una hora en la puerta.",
    "El presidente del gobierno anunció ayer que subirá el salario mínimo a partir del próximo año.",
    "Nunca pensé que fuera a decirte esto, pero creo que has cometido un error enorme.",
    "¿Puedes bajar el volumen, por favor?",
    "Vale, de acuerdo, pero esta vez pagáis vosotros la cena.",
    "En el capítulo anterior descubrimos que el protagonista llevaba años ocultando su verdadera identidad a toda su familia.",
    "Los científicos han descubierto una nueva especie de pez en las profundidades del océano Atlántico, a más de tres mil metros.",
    "Si me das un minuto, te explico con calma todo lo que ha pasado esta mañana en la oficina, porque no ha sido culpa mía.",
    "Atención, pasajeros del vuelo con destino a Sevilla: la puerta de embarque ha cambiado, diríjanse a la puerta doce inmediatamente, por favor.",
]

# 6 frases de muestra, las mismas para los dos candidatos (con «vosotros» y vocabulario de España).
SAMPLE_SENTENCES: list[str] = [
    "Vale, ¿vosotros venís en coche o cogéis el autobús? Yo llego en veinte minutos.",
    "Se me ha estropeado el ordenador y no encuentro el móvil, así que hoy no puedo contestar a nadie.",
    "Tío, ¿has visto el capítulo de anoche? Me ha parecido una pasada, sobre todo el final.",
    "Buenas tardes, señoras y señores. Les habla el capitán: en breve aterrizaremos en el aeropuerto de Madrid.",
    "Después de tres años de negociaciones, el gobierno ha anunciado una reforma que cambiará la vida de millones de personas.",
    "¡Cuidado con la zorra! Vosotros id por la izquierda, que yo cubro el centro y luego nos vemos en el coche.",
]


def count_words(text: str) -> int:
    return len([w for w in text.replace("¿", " ").replace("¡", " ").split() if any(c.isalnum() for c in w)])


def check_sentences() -> None:
    for i, s in enumerate(MEASURE_SENTENCES):
        n = count_words(s)
        assert 5 <= n <= 25, f"frase {i}: {n} palabras fuera de 5-25: {s}"
    print(f"{len(MEASURE_SENTENCES)} frases de medición; palabras:", [count_words(s) for s in MEASURE_SENTENCES])
    print(f"{len(SAMPLE_SENTENCES)} frases de muestra; palabras:", [count_words(s) for s in SAMPLE_SENTENCES])


if __name__ == "__main__":
    check_sentences()
