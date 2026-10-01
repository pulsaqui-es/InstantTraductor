"""Comprobación rápida del entorno: versiones, CUDA y arquitectura sm_120 (no mide nada, sin candado)."""
import importlib.metadata as md
import platform
import sys

import torch

print("python      :", sys.version.split()[0], platform.platform())
print("torch       :", torch.__version__, "| CUDA (build):", torch.version.cuda)
print("cuda avail  :", torch.cuda.is_available())
arch = torch.cuda.get_arch_list()
print("arch list   :", arch)
print("sm_120 en arch list:", "sm_120" in arch)
for name in ["transformers", "faster-qwen3-tts", "qwen-tts-hf", "chatterbox-tts", "accelerate", "numpy", "soundfile", "librosa", "huggingface-hub"]:
    try:
        print(f"{name:18s}:", md.version(name))
    except md.PackageNotFoundError:
        pass
if torch.cuda.is_available():
    # Solo consulta de propiedades: no reserva memoria ni lanza kernels.
    p = torch.cuda.get_device_properties(0)
    print("GPU         :", p.name, f"| {p.total_memory / 2**20:.0f} MiB | cc {p.major}.{p.minor}")
