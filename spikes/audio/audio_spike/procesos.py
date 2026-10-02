"""Ayudantes de procesos: cadena de padres, lanzamiento de procesos externos al arbol y espera."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import psutil

CREATE_NO_WINDOW = 0x08000000


def cadena_padres(pid: int) -> list[dict]:
    """Cadena de padres de `pid` hacia arriba, segun el PPID registrado por Windows.

    Se corta al llegar a un padre que ya no existe o cuyo PID fue reutilizado (psutil lo
    comprueba comparando las horas de creacion). El ultimo elemento, si el padre esta muerto,
    lleva `vivo=False`: es justo lo que pasa con `cmd /c start`, cuyo cmd.exe termina.
    """
    cadena: list[dict] = []
    try:
        p = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return cadena
    vistos = set()
    while p is not None and p.pid not in vistos:
        vistos.add(p.pid)
        try:
            ppid = p.ppid()
            cadena.append({"pid": p.pid, "nombre": p.name(), "ppid": ppid, "vivo": True})
            padre = p.parent()
        except psutil.NoSuchProcess:
            break
        if padre is None:
            if ppid:
                cadena.append({"pid": ppid, "nombre": "<muerto o PID reutilizado>", "ppid": None, "vivo": False})
            break
        p = padre
    return cadena


def cadena_texto(cadena: list[dict]) -> str:
    return " <- ".join(f"{c['nombre']}({c['pid']})" for c in cadena)


def alcanza(cadena: list[dict], pid_raiz: int) -> bool:
    """True si `pid_raiz` aparece en la cadena de padres (el proceso cuelga de ese PID)."""
    return any(c["pid"] == pid_raiz and c["vivo"] for c in cadena)


def buscar_por_marca(marca: str, nombre: Optional[str] = None) -> list[psutil.Process]:
    """Procesos cuya linea de comandos contiene `marca` (y opcionalmente con ese nombre).

    Si se da `nombre` se filtra primero por nombre (barato) y solo despues se lee la linea de
    comandos, que en Windows es lento: asi se pueden encontrar procesos de vida corta.
    """
    res = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if nombre is not None and (p.info["name"] or "").lower() != nombre.lower():
                continue
            cmd = " ".join(p.cmdline() or [])
            if marca in cmd:
                p.info["cmdline"] = p.cmdline()
                res.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return res


def esperar_proceso(marca: str, nombre: Optional[str], timeout_s: float = 10.0) -> Optional[psutil.Process]:
    """Espera a que aparezca un proceso con esa marca; devuelve el primero."""
    fin = time.monotonic() + timeout_s
    while time.monotonic() < fin:
        ps = buscar_por_marca(marca, nombre)
        if ps:
            return ps[0]
        time.sleep(0.005)
    return None


def matar_por_marca(marca: str, nombres: tuple[str, ...] = ("ffplay.exe", "python.exe", "pythonw.exe")) -> int:
    """Mata los procesos propios del spike que sigan vivos (marca = carpeta temporal unica)."""
    n = 0
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if (p.info["name"] or "").lower() in nombres and marca in " ".join(p.cmdline() or []):
                p.kill()
                n += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return n


def esperar_fin(pid: int, timeout_s: float = 10.0) -> bool:
    """Espera a que el proceso termine; True si termino."""
    try:
        p = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return True
    try:
        p.wait(timeout=timeout_s)
        return True
    except psutil.TimeoutExpired:
        return False


def ruta_pythonw() -> str:
    """`pythonw.exe` del entorno (sin consola) o, si no existe, `python.exe`."""
    cand = Path(sys.executable).with_name("pythonw.exe")
    return str(cand if cand.exists() else sys.executable)


def lanzar_cmd_start(argv: list[str], segundo_plano: bool = False) -> subprocess.Popen:
    """`cmd /c start "" /min argv...`: el proceso nuevo queda huerfano (su cmd.exe termina).

    Es la forma de lanzar una 'app externa' que sugiere el brief. Comprobar despues con
    `cadena_padres` que la cadena no llega al proceso que captura. OJO: con `/b` (sin ventana
    nueva) el cmd.exe NO termina mientras viva el proceso y la cadena SI llega a quien lo lanzo;
    por eso el modo por defecto es `/min` (consola nueva minimizada).
    """
    orden = ["cmd", "/c", "start", "", "/b" if segundo_plano else "/min"]
    orden += argv
    p = subprocess.Popen(
        orden,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    if not segundo_plano:
        # Con `/min` cmd.exe termina enseguida. Hay que esperarlo: mientras este Popen tenga el
        # handle abierto, Windows conserva el objeto del proceso ya muerto y psutil lo sigue
        # viendo como padre del proceso nuevo (falso "cuelga de nosotros").
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    return p


def lanzar_wmi(argv: list[str]) -> Optional[int]:
    """Crea el proceso con `Win32_Process.Create` (su padre es WmiPrvSE, no nosotros). Devuelve el PID."""
    linea = subprocess.list2cmdline(argv).replace("'", "''")
    ps = (
        "(Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        f"-Arguments @{{CommandLine='{linea}'}}).ProcessId"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=CREATE_NO_WINDOW,
    )
    try:
        return int(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def mi_cadena() -> str:
    return cadena_texto(cadena_padres(os.getpid()))
