"""Trabajador de tonos del spike S4: reproduce tonos bajo orden.

Se lanza de tres formas (las usan `t1_autoexclusion.py`, `t9_latencia.py` y compañia):
- `--rol hijo` / `--rol nieto`: lee ordenes por stdin (una por linea) y contesta con un JSON
  por linea en stdout. Sirve para probar procesos hijo y nieto del proceso que captura.
- `--rol externo --udp PUERTO`: escucha ordenes UDP en 127.0.0.1 y contesta por UDP. Se lanza
  con `cmd /c start`, fuera del arbol del que captura.
- `--auto "tono F DUR AMP etiqueta" --retardo S`: ejecuta una orden tras un retardo y termina
  (nieto huerfano: su padre ya habra muerto).

Ordenes: ping | abrir | cerrar | tono F DUR AMP [etiqueta] | nieto | nieto_tono F DUR AMP [etiqueta]
         | huerfano F DUR AMP RETARDO [etiqueta] | salir
Todas las marcas de tiempo son `time.perf_counter_ns()` (QPC, comparable entre procesos).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time

import audio_spike  # noqa: F401  (COM en MTA antes de comtypes)
from audio_spike.tonos import ReproductorTonos

CREATE_NO_WINDOW = 0x08000000


class Trabajador:
    def __init__(self, rol: str, log: str) -> None:
        self.rol = rol
        self.log_path = log
        self.rep: ReproductorTonos | None = None  # dispositivo persistente (tras `abrir`)
        self.nieto: subprocess.Popen | None = None

    # -- registro -------------------------------------------------------------------
    def log(self, **datos) -> None:
        if not self.log_path:
            return
        datos.update({"rol": self.rol, "pid": os.getpid(), "ppid": os.getppid(), "t_ns": time.perf_counter_ns()})
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(datos, default=str) + "\n")
        except OSError:
            pass

    # -- ordenes ----------------------------------------------------------------------
    def orden(self, linea: str) -> dict:
        partes = linea.strip().split()
        if not partes:
            return {"ok": False, "error": "vacia"}
        nombre, args = partes[0], partes[1:]
        try:
            if nombre == "ping":
                return {"ok": True, "pid": os.getpid(), "ppid": os.getppid(), "t_ns": time.perf_counter_ns()}
            if nombre == "abrir":
                # abrir [periodo_ms] [periodos] [canales]: dispositivo persistente (con ceros)
                periodo = int(args[0]) if len(args) > 0 else 20
                periodos = int(args[1]) if len(args) > 1 else 3
                canales = int(args[2]) if len(args) > 2 else 2
                if self.rep is None:
                    self.rep = ReproductorTonos(48000, canales, periodo, periodos, al_notificar=self._notificacion)
                    self.rep.abrir()
                self.log(evento="abrir", periodo_ms=periodo, periodos=periodos, canales=canales)
                return {"ok": True, "pid": os.getpid()}
            if nombre == "cerrar":
                if self.rep is not None:
                    self.rep.cerrar()
                    self.rep = None
                return {"ok": True}
            if nombre == "tono":
                return self.tono(float(args[0]), float(args[1]), float(args[2]), args[3] if len(args) > 3 else "")
            if nombre == "nieto":
                return self.lanzar_nieto()
            if nombre == "nieto_tono":
                return self.nieto_tono(" ".join(["tono"] + args))
            if nombre == "huerfano":
                return self.huerfano(float(args[0]), float(args[1]), float(args[2]), float(args[3]),
                                     args[4] if len(args) > 4 else "")
            if nombre == "salir":
                self.cerrar_todo()
                return {"ok": True, "salir": True}
        except Exception as exc:  # devolver el error al que manda la orden
            return {"ok": False, "error": repr(exc)}
        return {"ok": False, "error": f"orden desconocida: {nombre}"}

    def _notificacion(self, t_ns: int, nombre: str) -> None:
        """Notificaciones de miniaudio (started/stopped/rerouted...) al log, para el script de T3."""
        self.log(evento="notificacion", tipo=nombre, t_evento_ns=t_ns)

    def tono(self, f: float, dur: float, amp: float, etiqueta: str) -> dict:
        t_recv = time.perf_counter_ns()
        temporal = self.rep is None
        rep = ReproductorTonos(48000, 2, 20, 3) if temporal else self.rep
        if temporal:
            rep.abrir()  # dispositivo nuevo: la sesion de audio se crea ahora
        info = rep.tono_y_esperar(f, dur, amp, cola_s=0.3)
        if temporal:
            rep.cerrar()
        res = {
            "ok": True, "pid": os.getpid(), "etiqueta": etiqueta, "f": f, "temporal": temporal,
            "t_recv_ns": t_recv,
            "t_primer_bloque_ns": info["t_primer_bloque_ns"],
            "t_ultimo_bloque_ns": info["t_ultimo_bloque_ns"],
        }
        self.log(evento="tono", **res)
        return res

    def lanzar_nieto(self) -> dict:
        if self.nieto is None:
            self.nieto = subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--rol", "nieto", "--log", self.log_path],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
            )
            listo = self.nieto.stdout.readline().strip()
            return {"ok": True, "launcher_pid": self.nieto.pid, "listo": listo}
        return {"ok": True, "launcher_pid": self.nieto.pid, "ya_existia": True}

    def nieto_tono(self, linea: str) -> dict:
        if self.nieto is None:
            return {"ok": False, "error": "no hay nieto"}
        self.nieto.stdin.write(linea + "\n")
        self.nieto.stdin.flush()
        return json.loads(self.nieto.stdout.readline())

    def huerfano(self, f: float, dur: float, amp: float, retardo: float, etiqueta: str) -> dict:
        """Lanza un nieto autonomo que tocara tras `retardo` s; este proceso se ira antes."""
        p = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--rol", "nieto", "--log", self.log_path,
             "--auto", f"tono {f} {dur} {amp} {etiqueta}", "--retardo", str(retardo)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        return {"ok": True, "launcher_pid": p.pid, "padre_pid": os.getpid(), "huerfano": True}

    def cerrar_todo(self) -> None:
        if self.nieto is not None:
            try:
                self.nieto.stdin.write("salir\n")
                self.nieto.stdin.flush()
                self.nieto.wait(timeout=3)
            except Exception:
                self.nieto.kill()
            self.nieto = None
        if self.rep is not None:
            self.rep.cerrar()
            self.rep = None


def emitir(obj: dict) -> None:
    """Escribe una linea JSON en stdout si existe (con pythonw no hay stdout)."""
    if sys.stdout is not None:
        sys.stdout.write(json.dumps(obj, default=str) + "\n")
        sys.stdout.flush()


def servir_stdin(t: Trabajador) -> None:
    emitir({"listo": True, "pid": os.getpid(), "ppid": os.getppid(), "rol": t.rol})
    for linea in sys.stdin:
        resp = t.orden(linea)
        emitir(resp)
        if linea.strip().startswith("huerfano"):
            time.sleep(0.05)
            os._exit(0)  # irse ya: el nieto queda huerfano
        if resp.get("salir"):
            break
    t.cerrar_todo()


def servir_udp(t: Trabajador, puerto: int) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", puerto))
    t.log(evento="listo_udp", puerto=puerto)
    while True:
        datos, origen = s.recvfrom(4096)
        linea = datos.decode("utf-8", "replace")
        resp = t.orden(linea)
        s.sendto(json.dumps(resp, default=str).encode(), origen)
        if resp.get("salir"):
            break


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rol", default="hijo")
    ap.add_argument("--log", default="")
    ap.add_argument("--udp", type=int, default=0)
    ap.add_argument("--auto", default="")
    ap.add_argument("--retardo", type=float, default=0.0)
    a = ap.parse_args()
    t = Trabajador(a.rol, a.log)
    t.log(evento="inicio", argv=sys.argv[1:])
    if a.auto:
        time.sleep(a.retardo)
        t.orden(a.auto)
        t.cerrar_todo()
        return
    if a.udp:
        servir_udp(t, a.udp)
    else:
        servir_stdin(t)


if __name__ == "__main__":
    main()
