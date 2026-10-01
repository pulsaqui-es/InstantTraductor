"""Espera (hasta N minutos) a que el equipo esté tranquilo antes de una medición en tiempo real.

Uso (desde ``spikes/asr``)::

    uv run python campaign/wait_quiet.py 4 25      # hasta 4 min, CPU global < 25 % dos veces seguidas

Otros procesos (en las mediciones del spike, otros obreros) distorsionan las latencias; si no hay
ventana tranquila, sale igualmente y la medición registra la carga ajena.
"""

import sys
import time

import psutil

max_min = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
thr = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
t_end = time.time() + max_min * 60
ok = 0
last = None
while time.time() < t_end:
    last = psutil.cpu_percent(interval=5)
    ok = ok + 1 if last < thr else 0
    if ok >= 2:
        print(f"[wait_quiet] equipo tranquilo (CPU {last:.0f} % < {thr:.0f} %)", flush=True)
        sys.exit(0)
print(f"[wait_quiet] sin ventana tranquila tras {max_min} min (última CPU {last:.0f} %); se mide igualmente", flush=True)
