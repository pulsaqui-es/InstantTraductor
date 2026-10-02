"""Carga sintética de GPU para medir el TTFA con contención (proceso aparte; lo lanzan los bench con --fase contencion).

Multiplica matrices fp16 de 4096x4096 en bucle durante `duracion` s con un ciclo de trabajo dado (p. ej. 50 = ocupada la mitad
de cada periodo de 20 ms). Imita, de forma tosca, a los otros motores que compartirán la GPU en producción (ASR, traducción).

    uv run python ../common/carga_gpu.py <ciclo_%> <duracion_s>
"""

from __future__ import annotations

import sys
import time

import torch

duty = float(sys.argv[1]) / 100.0
dur = float(sys.argv[2])
a = torch.randn(4096, 4096, device="cuda", dtype=torch.float16)
b = torch.randn(4096, 4096, device="cuda", dtype=torch.float16)
torch.cuda.synchronize()
print("listo", flush=True)
periodo = 0.020
fin = time.perf_counter() + dur
while time.perf_counter() < fin:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < duty * periodo:
        for _ in range(2):
            a @ b
        torch.cuda.synchronize()
    resto = periodo - (time.perf_counter() - t0)
    if resto > 0:
        time.sleep(resto)
