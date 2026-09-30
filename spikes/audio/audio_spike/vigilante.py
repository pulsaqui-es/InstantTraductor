"""Prototipo de vigilante (watchdog) de captura y reproduccion (ADR-0005).

`CapturaGestionada` reabre la captura si el hilo de lectura muere (error de WASAPI, p. ej.
AUDCLNT_E_DEVICE_INVALIDATED), si dejan de llegar paquetes o si no se puede crear (no hay
dispositivo). `ReproductorGestionado` hace lo mismo con el PlaybackDevice si dejan de llegar
peticiones de datos. Ambos guardan un historial con los tiempos de recuperacion.

Es un prototipo para el spike T3 (conexion y desconexion de dispositivos): no es codigo de producto.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from .loopback_ctypes import CapturaProcesoCtypes
from .modos import ModoCaptura
from .registro import Registro
from .tonos import ReproductorTonos


class CapturaGestionada:
    def __init__(self, nombre: str, pid: int, modo: ModoCaptura, sample_rate: int = 16000,
                 silencio_max_s: float = 0.5, reintento_s: float = 1.0,
                 al_evento: Optional[Callable[[str], None]] = None,
                 vigilar_silencio: Optional[bool] = None) -> None:
        """`vigilar_silencio`: reabrir si dejan de llegar paquetes. Por defecto solo en process loopback
        (EXCLUDE/INCLUDE), que entrega paquetes siempre; el loopback de dispositivo (ENDPOINT) calla
        cuando no hay ninguna sesion activa y en ese caso solo se reabre ante un error de lectura."""
        self.nombre = nombre
        self.pid = pid
        self.modo = modo
        self.sample_rate = sample_rate
        self.vigilar_silencio = (modo is not ModoCaptura.ENDPOINT) if vigilar_silencio is None else vigilar_silencio
        self.silencio_max_s = silencio_max_s
        self.reintento_s = reintento_s
        self.al_evento = al_evento or (lambda _t: None)
        self.registro = Registro(sample_rate, nombre)  # un unico registro a lo largo de los reinicios
        self.captura: Optional[CapturaProcesoCtypes] = None
        self.historial: list[dict] = []
        self._pendiente: Optional[dict] = None  # recuperacion en curso
        self._proximo_intento_ns = 0
        self._t_abierta_ns = 0
        self.abrir()

    # -- apertura ---------------------------------------------------------------------------
    def abrir(self) -> bool:
        try:
            cap = CapturaProcesoCtypes(pid=self.pid, modo=self.modo, sample_rate=self.sample_rate)
            cap.iniciar(self.registro)
        except Exception as exc:  # sin dispositivo, servicio de audio parado, etc.
            self.captura = None
            self.registro.evento(f"no se pudo abrir: {exc}")
            self._proximo_intento_ns = time.perf_counter_ns() + int(self.reintento_s * 1e9)
            return False
        self.captura = cap
        self._t_abierta_ns = time.perf_counter_ns()
        return True

    def _cerrar_actual(self) -> None:
        if self.captura is not None:
            try:
                self.captura.cerrar()
            except Exception:
                pass
            self.captura = None

    # -- vigilancia -----------------------------------------------------------------------------
    def _ultimo_paquete_ns(self) -> int:
        ps = self.registro.paquetes
        return ps[-1].t_ns if ps else 0

    def vigilar(self) -> Optional[str]:
        """Llamar cada ~100 ms. Devuelve un texto si ha habido un cambio de estado (para imprimirlo)."""
        ahora = time.perf_counter_ns()
        aviso = None
        if self.captura is not None:
            causa = None
            if self.captura.error:
                causa = f"error de lectura: {self.captura.error}"
            elif self.vigilar_silencio:
                ref = max(self._ultimo_paquete_ns(), self._t_abierta_ns)
                if (ahora - ref) / 1e9 > self.silencio_max_s:
                    causa = f"sin paquetes desde hace {(ahora - ref) / 1e9:.2f} s"
            if causa and self._pendiente is None:
                self._pendiente = {"captura": self.nombre, "t_fallo_ns": ahora, "causa": causa, "intentos": 0}
                aviso = f"{self.nombre}: FALLO ({causa}); se reabrira"
                self._cerrar_actual()
                self._proximo_intento_ns = ahora
        if self.captura is None and ahora >= self._proximo_intento_ns:
            if self._pendiente is not None:
                self._pendiente["intentos"] += 1
            if self.abrir():
                if self._pendiente is not None:
                    self._pendiente["t_reabierta_ns"] = time.perf_counter_ns()
                    aviso = (f"{self.nombre}: reabierta tras {(self._pendiente['t_reabierta_ns'] - self._pendiente['t_fallo_ns']) / 1e6:.0f} ms "
                             f"(intentos: {self._pendiente['intentos']})")
        # primer paquete tras la reapertura: fin de la recuperacion
        if self._pendiente is not None and "t_reabierta_ns" in self._pendiente:
            if self._ultimo_paquete_ns() > self._pendiente["t_reabierta_ns"]:
                self._pendiente["t_primer_paquete_ns"] = self._ultimo_paquete_ns()
                self._pendiente["recuperacion_ms"] = round(
                    (self._pendiente["t_primer_paquete_ns"] - self._pendiente["t_fallo_ns"]) / 1e6, 1)
                self.historial.append(self._pendiente)
                aviso = (aviso + " | " if aviso else "") + (
                    f"{self.nombre}: datos de nuevo {self._pendiente['recuperacion_ms']:.0f} ms despues del fallo")
                self._pendiente = None
        if aviso:
            self.al_evento(aviso)
        return aviso

    def cerrar(self) -> None:
        self._cerrar_actual()


class ReproductorGestionado:
    """PlaybackDevice por defecto con vigilante: si dejan de pedirle datos, lo recrea."""

    def __init__(self, sample_rate: int = 48000, nchannels: int = 2, periodo_ms: int = 20, periodos: int = 3,
                 sin_callbacks_max_s: float = 1.0, reintento_s: float = 1.0,
                 al_evento: Optional[Callable[[str], None]] = None) -> None:
        self.cfg = (sample_rate, nchannels, periodo_ms, periodos)
        self.sin_callbacks_max_s = sin_callbacks_max_s
        self.reintento_s = reintento_s
        self.al_evento = al_evento or (lambda _t: None)
        self.rep: Optional[ReproductorTonos] = None
        self.historial: list[dict] = []
        self.eventos_dispositivo: list[tuple[int, str]] = []  # notificaciones de miniaudio
        self._pendiente: Optional[dict] = None
        self._proximo_intento_ns = 0
        self._t_abierto_ns = 0
        self.abrir()

    def _notificacion(self, t_ns: int, nombre: str) -> None:
        self.eventos_dispositivo.append((t_ns, nombre))
        self.al_evento(f"reproductor (miniaudio): {nombre}")

    def abrir(self) -> bool:
        try:
            rep = ReproductorTonos(*self.cfg, al_notificar=self._notificacion)
            rep.abrir()
        except Exception as exc:
            self.rep = None
            self._proximo_intento_ns = time.perf_counter_ns() + int(self.reintento_s * 1e9)
            self.al_evento(f"reproductor: no se pudo abrir: {exc}")
            return False
        self.rep = rep
        self._t_abierto_ns = time.perf_counter_ns()
        return True

    def tono(self, *args, **kwargs):
        if self.rep is not None:
            return self.rep.tono(*args, **kwargs)
        return None

    def callbacks_por_s(self, ventana_s: float = 1.0) -> float:
        if self.rep is None:
            return 0.0
        ahora = time.perf_counter_ns()
        ts = self.rep.t_callbacks[-200:]
        return sum(1 for t in ts if ahora - t <= ventana_s * 1e9) / ventana_s

    def vigilar(self) -> Optional[str]:
        ahora = time.perf_counter_ns()
        aviso = None
        if self.rep is not None:
            ref = max(self.rep.t_callbacks[-1] if self.rep.t_callbacks else 0, self._t_abierto_ns)
            if (ahora - ref) / 1e9 > self.sin_callbacks_max_s and self._pendiente is None:
                self._pendiente = {"t_fallo_ns": ahora, "causa": f"sin peticiones de datos desde hace {(ahora - ref) / 1e9:.2f} s",
                                   "intentos": 0}
                aviso = f"reproductor: FALLO ({self._pendiente['causa']}); se recreara"
                try:
                    self.rep.cerrar()
                except Exception:
                    pass
                self.rep = None
                self._proximo_intento_ns = ahora
        if self.rep is None and ahora >= self._proximo_intento_ns:
            if self._pendiente is not None:
                self._pendiente["intentos"] += 1
            if self.abrir() and self._pendiente is not None:
                self._pendiente["t_reabierto_ns"] = time.perf_counter_ns()
                aviso = (f"reproductor: recreado tras {(self._pendiente['t_reabierto_ns'] - self._pendiente['t_fallo_ns']) / 1e6:.0f} ms "
                         f"(intentos: {self._pendiente['intentos']})")
                self.historial.append(self._pendiente)
                self._pendiente = None
        if aviso:
            self.al_evento(aviso)
        return aviso

    def cerrar(self) -> None:
        if self.rep is not None:
            self.rep.cerrar()
            self.rep = None
