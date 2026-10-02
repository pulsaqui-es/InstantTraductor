"""Audio de InstantTraductor: captura, reproducción, AGC, DSP y autotest.

COM debe inicializarse en MTA antes de que se importe comtypes o pycaw (ADR-0010; spike S4). Este
``__init__`` se ejecuta antes que cualquier módulo del paquete, así que el orden de los imports deja de
importar.
"""

import sys

sys.coinit_flags = 0  # type: ignore[attr-defined]
