"""Banco de pruebas compartido por los scripts del spike (hijos, externos, capturas, ffplay)."""

from __future__ import annotations

import atexit
import json
import os
import platform
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


from .loopback_ctypes import CapturaProcesoCtypes
from .modos import ModoCaptura
from .procesos import (
    CREATE_NO_WINDOW,
    cadena_padres,
    cadena_texto,
    esperar_fin,
    esperar_proceso,
    lanzar_cmd_start,
    lanzar_wmi,
    matar_por_marca,
    ruta_pythonw,
)
from .registro import Registro
from .tonos import AMPLITUD_POR_DEFECTO, escribir_wav, generar_tono

RAIZ = Path(__file__).resolve().parent.parent  # spikes/audio
TRABAJADOR = str(RAIZ / "tone_worker.py")
RESULTADOS = RAIZ / "resultados"
SR_CAPTURA = 16000


def ahora_ns() -> int:
    return time.perf_counter_ns()


def dormir(segundos: float) -> None:
    time.sleep(segundos)


def directorio_temporal(prefijo: str) -> str:
    """Crea una carpeta temporal unica que se borra sola al terminar el proceso (incluso tras un error)."""
    ruta = tempfile.mkdtemp(prefix=prefijo)
    atexit.register(borrar, ruta)
    return ruta


def borrar(ruta: str) -> None:
    """Borra la carpeta temporal y mata antes cualquier proceso propio que la use (ffplay, trabajadores).

    Un ffplay con un origen infinito (p. ej. lavfi anullsrc) no termina solo y dejaria una sesion
    de audio activa que falsea las pruebas siguientes; por eso todo proceso lanzado por el spike
    lleva en su linea de comandos la ruta de la carpeta temporal.
    """
    matar_por_marca(os.path.basename(ruta.rstrip("\\/")))
    shutil.rmtree(ruta, ignore_errors=True)


def sesiones_activas() -> list[dict]:
    """Sesiones de audio del dispositivo por defecto (pycaw): proceso, estado y volumen de sesion."""
    import audio_spike  # noqa: F401
    from pycaw.utils import AudioUtilities

    estados = {0: "inactiva", 1: "activa", 2: "expirada"}
    res = []
    for s in AudioUtilities.GetAllSessions():
        try:
            nombre = s.Process.name() if s.Process else "(sistema)"
        except Exception:
            nombre = "?"
        res.append({"pid": s.ProcessId, "proceso": nombre, "estado": estados.get(s.State, s.State),
                    "volumen": round(float(s.SimpleAudioVolume.GetMasterVolume()), 2)})
    return res


class CargaGIL(threading.Thread):
    """Hilo Python de calculo puro que retiene el GIL (intervalo de cambio de 5 ms de CPython).

    Simula, sin GPU, un hilo de trabajo (p. ej. preprocesado) que compite con el audio por el GIL.
    """

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.parar = False

    def run(self) -> None:
        x = 0
        while not self.parar:
            for i in range(200000):
                x += i * i % 7


# -- trabajadores hijo (stdin/stdout) ---------------------------------------------------------
class Hijo:
    """Proceso hijo `tone_worker.py` controlado por stdin/stdout (JSON por linea)."""

    def __init__(self, rol: str, log: str, directo: bool = False) -> None:
        """`directo=True` lanza el interprete base (sin el redirector `python.exe` del venv).

        Con el venv de uv, `sys.executable` es un redirector que crea el interprete real como
        hijo: el que suena queda a dos niveles. Con `directo=True` el que suena es hijo
        directo de este proceso (se le da el `site-packages` del venv por PYTHONPATH).
        """
        self.rol = rol
        self.directo = directo
        ejecutable, env = sys.executable, None
        if directo:
            ejecutable = getattr(sys, "_base_executable", sys.executable)
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(
                [str(Path(sys.prefix) / "Lib" / "site-packages"), env.get("PYTHONPATH", "")]
            )
        self.proc = subprocess.Popen(
            [ejecutable, TRABAJADOR, "--rol", rol, "--log", log],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        listo = json.loads(self.proc.stdout.readline())
        self.pid_real: int = listo["pid"]  # PID del interprete real (no del lanzador del venv)
        self.launcher_pid: int = self.proc.pid

    def orden(self, linea: str) -> dict:
        self.proc.stdin.write(linea + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def cerrar(self) -> None:
        try:
            self.orden("salir")
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


# -- trabajador externo por UDP ------------------------------------------------------------------
def puerto_libre() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class ExternoUDP:
    """`tone_worker.py --rol externo` lanzado con `cmd /c start` (fuera del arbol) y mandado por UDP."""

    def __init__(self, log: str, metodo: str = "cmd", timeout_arranque_s: float = 20.0) -> None:
        self.puerto = puerto_libre()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(1.0)
        argv = [ruta_pythonw(), TRABAJADOR, "--rol", "externo", "--udp", str(self.puerto), "--log", log]
        if metodo == "cmd":
            lanzar_cmd_start(argv)
        elif metodo == "wmi":
            lanzar_wmi(argv)
        else:
            raise ValueError(metodo)
        self.metodo = metodo
        fin = time.monotonic() + timeout_arranque_s
        self.pid_real = 0
        while time.monotonic() < fin:
            try:
                r = self.orden("ping", espera_s=0.5)
            except (socket.timeout, OSError):
                continue
            if r.get("ok"):
                self.pid_real = r["pid"]
                self.ppid = r["ppid"]
                break
        if not self.pid_real:
            raise RuntimeError("el trabajador externo no respondio por UDP")

    def orden(self, linea: str, espera_s: float = 10.0) -> dict:
        self.sock.settimeout(espera_s)
        self.sock.sendto(linea.encode(), ("127.0.0.1", self.puerto))
        datos, _ = self.sock.recvfrom(65535)
        return json.loads(datos.decode())

    def cerrar(self) -> None:
        try:
            self.orden("salir", espera_s=3.0)
        except Exception:
            pass
        esperar_fin(self.pid_real, 5.0)
        self.sock.close()


# -- ffplay externo ----------------------------------------------------------------------------------
def ruta_ffplay() -> str:
    return shutil.which("ffplay") or "ffplay"


@dataclass
class EjecucionFfplay:
    wav: str
    metodo: str
    t_lanzamiento_ns: int
    pid: int = 0
    cadena: list = field(default_factory=list)
    t_fin_ns: int = 0
    terminado: bool = False


def lanzar_ffplay(wav: str, metodo: str = "cmd", volumen: int = 100) -> EjecucionFfplay:
    """Lanza `ffplay -nodisp -autoexit wav` fuera del arbol del proceso actual y espera a que aparezca."""
    marca = os.path.basename(wav)
    argv = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", str(volumen), wav]
    t0 = ahora_ns()
    if metodo == "cmd":  # cmd /c start: huerfano (su cmd.exe muere)
        lanzar_cmd_start(argv)  # espera a que cmd.exe termine y suelta su handle
    elif metodo == "wmi":  # padre = WmiPrvSE
        argv[0] = ruta_ffplay()
        lanzar_wmi(argv)
    elif metodo == "popen":  # hijo DIRECTO de este proceso
        argv[0] = ruta_ffplay()
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    elif metodo == "cmd_hijo":  # este proceso -> cmd.exe (vivo) -> ffplay: nieto con padre vivo
        subprocess.Popen(["cmd", "/c"] + argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    else:
        raise ValueError(metodo)
    ej = EjecucionFfplay(wav, metodo, t0)
    p = esperar_proceso(marca, "ffplay.exe", 15.0)
    if p is not None:
        ej.pid = p.pid
        # Con `cmd /c start` el cmd.exe intermedio tarda unos ms en morir: se mira la cadena
        # cuando ya se ha ido (ffplay sigue vivo: el WAV lleva silencio al final).
        time.sleep(0.4)
        ej.cadena = cadena_padres(p.pid)
    return ej


def esperar_ffplay(ej: EjecucionFfplay, timeout_s: float = 10.0) -> None:
    if ej.pid:
        ej.terminado = esperar_fin(ej.pid, timeout_s)
    ej.t_fin_ns = ahora_ns()


def wav_tono(directorio: str, nombre: str, frecuencia: float, duracion_s: float = 0.6,
             amplitud: float = AMPLITUD_POR_DEFECTO, retardo_s: float = 0.0, cola_s: float = 1.5) -> str:
    """Crea un WAV mono de 48 kHz con un tono, con `retardo_s` de silencio delante y `cola_s` detras.

    El silencio final mantiene vivo el proceso de ffplay el tiempo suficiente para anotar su
    cadena de padres (el humano solo oye el tono).
    """
    import numpy as np

    tono = generar_tono(frecuencia, duracion_s, amplitud, 48000)
    if retardo_s > 0:
        tono = np.concatenate([np.zeros(int(retardo_s * 48000), dtype=np.float32), tono])
    if cola_s > 0:
        tono = np.concatenate([tono, np.zeros(int(cola_s * 48000), dtype=np.float32)])
    ruta = os.path.join(directorio, nombre)
    escribir_wav(ruta, tono, 48000)
    return ruta


# -- capturas simultaneas ---------------------------------------------------------------------------------
class Capturas:
    """Las tres capturas de control: EXCLUDE(pid), INCLUDE(pid) y ENDPOINT (plan B en ctypes)."""

    def __init__(self, pid: int, modos=(ModoCaptura.EXCLUDE, ModoCaptura.INCLUDE, ModoCaptura.ENDPOINT),
                 buffer_ms: int = 100) -> None:
        self.pid = pid
        self.dispositivos: dict[ModoCaptura, CapturaProcesoCtypes] = {}
        self.registros: dict[ModoCaptura, Registro] = {}
        for m in modos:
            self.dispositivos[m] = CapturaProcesoCtypes(pid=pid, modo=m, sample_rate=SR_CAPTURA, buffer_ms=buffer_ms)
            self.registros[m] = Registro(SR_CAPTURA, m.value)

    def iniciar(self) -> None:
        for m, d in self.dispositivos.items():
            d.iniciar(self.registros[m])

    def cerrar(self) -> None:
        for d in self.dispositivos.values():
            d.cerrar()


# -- informacion del entorno -----------------------------------------------------------------------------------
def info_entorno() -> dict:
    """Versiones y dispositivo por defecto (para el README y los JSON de resultados)."""
    import importlib.metadata as md

    import audio_spike  # noqa: F401
    from pycaw.utils import AudioUtilities

    def version(paquete: str) -> str:
        try:
            return md.version(paquete)
        except md.PackageNotFoundError:
            return "?"

    w = sys.getwindowsversion()
    ubr = ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
            ubr = f"{winreg.QueryValueEx(k, 'DisplayVersion')[0]} UBR {winreg.QueryValueEx(k, 'UBR')[0]}"
    except OSError:
        pass
    altavoces = AudioUtilities.GetSpeakers()
    activos = [
        {"nombre": d.FriendlyName, "id": d.id}
        for d in AudioUtilities.GetAllDevices(data_flow=0, device_state=1)  # eRender, DEVICE_STATE_ACTIVE
    ]
    mezcla = {}
    try:
        from .loopback_ctypes import activar_cliente_endpoint

        f = activar_cliente_endpoint().GetMixFormat().contents
        mezcla = {"frecuencia": f.nSamplesPerSec, "canales": f.nChannels, "bits": f.wBitsPerSample,
                  "formato": f.wFormatTag}
    except Exception as exc:  # solo informativo
        mezcla = {"error": repr(exc)}
    return {
        "formato_mezcla_dispositivo": mezcla,
        "volumen_maestro_pct": round(float(altavoces.volume_percent), 0),
        "windows": f"{platform.platform()} build {w.build} ({ubr})",
        "python": platform.python_version(),
        "miniaudio": version("miniaudio"),
        "numpy": version("numpy"),
        "pycaw": version("pycaw"),
        "comtypes": version("comtypes"),
        "psutil": version("psutil"),
        "cffi": version("cffi"),
        "dispositivo_por_defecto": {"nombre": altavoces.FriendlyName, "id": altavoces.id},
        "dispositivos_activos": activos,
        "pid": os.getpid(),
        "cadena_propia": cadena_texto(cadena_padres(os.getpid())),
    }


def guardar_json(nombre: str, datos: dict) -> Path:
    RESULTADOS.mkdir(exist_ok=True)
    ruta = RESULTADOS / nombre
    ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False, default=_serializar), encoding="utf-8", newline="\n")
    return ruta


def _serializar(o):
    import numpy as np

    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def aleatorio(a: float, b: float) -> float:
    return random.uniform(a, b)
