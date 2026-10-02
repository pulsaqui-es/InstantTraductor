"""Registro de paquetes de una captura (comun a la subclase de miniaudio y al plan B en ctypes)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator, Optional

import numpy as np


@dataclass
class Paquete:
    """Un paquete entregado por la captura."""

    t_ns: int  # llegada (time.perf_counter_ns) justo despues de leerlo
    muestras: np.ndarray  # float32 mono
    flags: Optional[int] = None  # AUDCLNT_BUFFERFLAGS_* (1=discontinuidad, 2=silencio, 4=error de sello)
    qpc_ns: Optional[int] = None  # sello QPC (ns) del primer frame segun WASAPI, si lo hay
    despertar_ns: Optional[int] = None  # instante en que desperto el hilo de captura


@dataclass
class Registro:
    """Almacen de paquetes y de eventos de una captura."""

    sample_rate: int
    etiqueta: str = ""
    paquetes: list[Paquete] = field(default_factory=list)
    eventos: list[tuple[int, str]] = field(default_factory=list)

    def anadir(self, paquete: Paquete) -> None:
        self.paquetes.append(paquete)  # append es atomico con el GIL

    def evento(self, texto: str) -> None:
        self.eventos.append((time.perf_counter_ns(), texto))

    def consumidor(self) -> Iterator[None]:
        """Generador para `miniaudio.CaptureDevice.start()`: anota cada periodo con su llegada."""
        while True:
            datos = yield
            t_ns = time.perf_counter_ns()
            # `datos` es un bytearray nuevo en cada llamada: se puede usar sin copiar.
            self.anadir(Paquete(t_ns, np.frombuffer(datos, dtype=np.float32)))

    # -- consultas -----------------------------------------------------------------
    @property
    def n_paquetes(self) -> int:
        return len(self.paquetes)

    @property
    def n_muestras(self) -> int:
        return sum(len(p.muestras) for p in list(self.paquetes))

    def ventana(self, t0_ns: int, t1_ns: int) -> tuple[np.ndarray, list[Paquete]]:
        """Muestras de los paquetes cuya llegada cae en [t0_ns, t1_ns] (y los propios paquetes)."""
        sel = [p for p in list(self.paquetes) if t0_ns <= p.t_ns <= t1_ns]
        if not sel:
            return np.zeros(0, dtype=np.float32), []
        return np.concatenate([p.muestras for p in sel]), sel

    def senal_con_tiempos(self, t0_ns: int, t1_ns: int) -> tuple[np.ndarray, np.ndarray]:
        """Muestras y hora (ns) estimada de cada una, para paquetes que llegan en [t0_ns, t1_ns].

        La hora de una muestra se estima suponiendo que el paquete llega justo cuando termina:
        t = llegada - (n - i) / fs. Es la mejor estimacion sin sellos fiables (los sellos QPC del
        process loopback son sinteticos, ver T4).
        """
        sel = [p for p in list(self.paquetes) if t0_ns <= p.t_ns <= t1_ns]
        if not sel:
            return np.zeros(0, dtype=np.float32), np.zeros(0)
        x = np.concatenate([p.muestras for p in sel])
        t = np.concatenate([p.t_ns - (len(p.muestras) - np.arange(len(p.muestras))) / self.sample_rate * 1e9
                            for p in sel])
        return x, t

    def intervalos_ms(self) -> np.ndarray:
        """Intervalos entre llegadas consecutivas, en ms."""
        ts = np.array([p.t_ns for p in list(self.paquetes)], dtype=np.int64)
        return np.diff(ts) / 1e6 if len(ts) > 1 else np.zeros(0)

    def guardar(self, ruta: str) -> None:
        """Vuelca el registro a un .npz (solo para ficheros temporales del spike)."""
        ps = list(self.paquetes)
        np.savez(
            ruta,
            sample_rate=self.sample_rate,
            etiqueta=self.etiqueta,
            t_ns=np.array([p.t_ns for p in ps], dtype=np.int64),
            n=np.array([len(p.muestras) for p in ps], dtype=np.int64),
            flags=np.array([-1 if p.flags is None else p.flags for p in ps], dtype=np.int64),
            qpc_ns=np.array([-1 if p.qpc_ns is None else p.qpc_ns for p in ps], dtype=np.int64),
            despertar_ns=np.array([-1 if p.despertar_ns is None else p.despertar_ns for p in ps], dtype=np.int64),
            muestras=np.concatenate([p.muestras for p in ps]) if ps else np.zeros(0, dtype=np.float32),
            ev_t=np.array([t for t, _ in self.eventos], dtype=np.int64),
            ev_txt=np.array([e for _, e in self.eventos], dtype=object),
        )

    @staticmethod
    def cargar(ruta: str) -> "Registro":
        d = np.load(ruta, allow_pickle=True)
        reg = Registro(int(d["sample_rate"]), str(d["etiqueta"]))
        pos = 0
        for t, n, fl, q, dsp in zip(d["t_ns"], d["n"], d["flags"], d["qpc_ns"], d["despertar_ns"]):
            reg.paquetes.append(
                Paquete(
                    int(t),
                    d["muestras"][pos : pos + int(n)],
                    None if fl < 0 else int(fl),
                    None if q < 0 else int(q),
                    None if dsp < 0 else int(dsp),
                )
            )
            pos += int(n)
        reg.eventos = list(zip((int(t) for t in d["ev_t"]), (str(e) for e in d["ev_txt"])))
        return reg
