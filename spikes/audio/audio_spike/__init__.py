"""Utilidades del spike S4 (captura por proceso y reproduccion en Windows 11).

Este paquete solo sirve al spike: no es codigo de producto.
"""

import sys

# COM en modo multihilo (MTA) ANTES de que comtypes/pycaw lo inicialicen. miniaudio
# trabaja en MTA y pycaw exige MTA para sus notificaciones (MMNotificationClient).
# Por eso todo script del spike debe importar `audio_spike` antes que comtypes/pycaw.
if "comtypes" not in sys.modules:
    sys.coinit_flags = 0
