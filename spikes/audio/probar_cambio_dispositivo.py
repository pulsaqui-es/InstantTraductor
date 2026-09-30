"""T3 (PRUEBA MANUAL) - Conexion y desconexion del dispositivo de audio con el humano delante.

NO se ejecuta de forma automatica: hay que desconectar y volver a conectar los auriculares (G733)
mientras corre. Imprime, segundo a segundo, que pasa con la captura y con la reproduccion, y al
final un resumen con la linea temporal de eventos y los tiempos de recuperacion de un vigilante.

Que se ejecuta:
- Reproduccion propia: `PlaybackDevice` de miniaudio SIN device_id (dispositivo por defecto, con
  el seguimiento automatico de miniaudio), 48 kHz float32, 20 ms x 3. Un pitido muy bajo de 777 Hz
  cada 3 s. Se vigilan sus notificaciones (started/stopped/rerouted) y sus peticiones de datos.
- Emisor externo: un trabajador Python lanzado con `cmd /c start` (fuera del arbol de este proceso),
  con su propio PlaybackDevice por defecto, que emite un pitido de 1999 Hz cada 3 s (desfasado 1,5 s).
- Tres capturas a 16 kHz mono float32 (todas con vigilante que las reabre si fallan):
    EXCLUDE(este PID)  process loopback: la que usara la app; debe seguir oyendo el externo (1999 Hz).
    INCLUDE(este PID)  process loopback: debe oir la reproduccion propia (777 Hz).
    ENDPOINT           loopback clasico del dispositivo por defecto: atado al dispositivo, de contraste.
- Eventos de Windows (pycaw MMNotificationClient): dispositivo anadido/quitado, cambio de estado y
  cambio del dispositivo por defecto.

Guion sugerido (los tiempos se pueden cambiar con las opciones):
  0-20 s     no toques nada (referencia)
  20 s       DESCONECTA los auriculares (apaga el G733 o quita el receptor USB)
  50 s       CONECTALOS de nuevo y espera a que Windows los reconozca
  80 s       (opcional) cambia a mano el dispositivo por defecto a otra salida (Win+Ctrl+V) y luego vuelve
  hasta el final: deja correr para ver si todo se recupera.

Volumen: pitidos de 0,12 s con amplitud 0,08 (-22 dBFS). No se toca ningun volumen del sistema.

Uso:  uv run python probar_cambio_dispositivo.py [--duracion 120] [--sin-pausa] [--sin-externo]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime

import audio_spike  # noqa: F401  (COM en MTA antes de comtypes)
from audio_spike import banco
from audio_spike.analisis import maximo_tono
from audio_spike.modos import ModoCaptura
from audio_spike.vigilante import CapturaGestionada, ReproductorGestionado

SR = banco.SR_CAPTURA
F_PROPIO = 777.0
F_EXTERNO = 1999.0
BIP_S = 0.12
UMBRAL_DB = 15.0

_bloqueo = threading.Lock()
_t0_ns = banco.ahora_ns()
linea_temporal: list[dict] = []


def rel_s(t_ns: int | None = None) -> float:
    return ((t_ns if t_ns is not None else banco.ahora_ns()) - _t0_ns) / 1e9


def evento(origen: str, texto: str, t_ns: int | None = None) -> None:
    """Imprime un evento con su tiempo relativo y lo anota en la linea temporal."""
    t = rel_s(t_ns)
    with _bloqueo:
        linea_temporal.append({"t_s": round(t, 3), "origen": origen, "texto": texto})
        print(f"[{t:7.2f}s] {origen:10} {texto}", flush=True)


def nombre_dispositivo_por_defecto() -> str:
    try:
        from pycaw.utils import AudioUtilities

        return AudioUtilities.GetSpeakers().FriendlyName
    except Exception as exc:
        return f"(sin dispositivo por defecto: {type(exc).__name__})"


def nombres_de_dispositivos() -> dict[str, str]:
    try:
        from pycaw.utils import AudioUtilities

        return {d.id: d.FriendlyName for d in AudioUtilities.GetAllDevices()}
    except Exception:
        return {}


def crear_monitor_de_dispositivos():
    """Registra un IMMNotificationClient de pycaw que imprime cada evento de Windows."""
    from pycaw.callbacks import MMNotificationClient
    from pycaw.utils import AudioUtilities

    cache = nombres_de_dispositivos()

    def nombre(dev_id: str) -> str:
        if dev_id not in cache:
            cache.update(nombres_de_dispositivos())
        return cache.get(dev_id, dev_id)

    class Monitor(MMNotificationClient):
        def on_default_device_changed(self, flow, flow_id, role, role_id, default_device_id):
            if flow == "eRender":
                evento("windows", f"dispositivo de reproduccion POR DEFECTO ({role}) -> {nombre(default_device_id)}")

        def on_device_added(self, added_device_id):
            evento("windows", f"dispositivo ANADIDO: {nombre(added_device_id)}")

        def on_device_removed(self, removed_device_id):
            evento("windows", f"dispositivo QUITADO: {nombre(removed_device_id)}")

        def on_device_state_changed(self, device_id, new_state, new_state_id):
            evento("windows", f"estado de {nombre(device_id)}: {new_state}")

    enumerador = AudioUtilities.GetDeviceEnumerator()
    monitor = Monitor()
    enumerador.RegisterEndpointNotificationCallback(monitor)
    return enumerador, monitor


def seguir_log_del_externo(ruta: str, parar: threading.Event) -> None:
    """Imprime las notificaciones de miniaudio que anota el emisor externo en su log."""
    pos = 0
    while not parar.is_set():
        try:
            with open(ruta, encoding="utf-8") as f:
                f.seek(pos)
                for linea in f:
                    try:
                        d = json.loads(linea)
                    except ValueError:
                        continue
                    if d.get("evento") == "notificacion":
                        evento("externo", f"PlaybackDevice del emisor externo (miniaudio): {d.get('tipo')}", d.get("t_evento_ns"))
                pos = f.tell()
        except OSError:
            pass
        time.sleep(0.25)


def tono_reciente(reg, frecuencia: float, ventana_s: float) -> bool:
    ahora = banco.ahora_ns()
    x, _ = reg.ventana(ahora - int(ventana_s * 1e9), ahora)
    if len(x) < int(0.3 * SR):
        return False
    return maximo_tono(x, SR, frecuencia, ventana_s=0.1)["ratio_db"] >= UMBRAL_DB


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duracion", type=float, default=120.0, help="duracion total (s)")
    ap.add_argument("--t-desconectar", type=float, default=20.0, help="instante del aviso 'DESCONECTA'")
    ap.add_argument("--t-conectar", type=float, default=50.0, help="instante del aviso 'CONECTA'")
    ap.add_argument("--t-cambiar", type=float, default=80.0, help="instante del aviso de cambio manual del dispositivo por defecto")
    ap.add_argument("--periodo-bip", type=float, default=3.0, help="segundos entre pitidos de cada emisor")
    ap.add_argument("--amplitud", type=float, default=0.08, help="amplitud de los pitidos (0-1)")
    ap.add_argument("--sin-externo", action="store_true", help="no lanza el emisor externo")
    ap.add_argument("--sin-pausa", action="store_true", help="no espera a Intro antes de empezar")
    ap.add_argument("--nombre", default="", help="sufijo del JSON de resultados")
    args = ap.parse_args()

    global _t0_ns
    entorno = banco.info_entorno()
    print(__doc__.split("Que se ejecuta:")[0].strip())
    print()
    print("Windows:", entorno["windows"])
    print("Dispositivo de reproduccion por defecto:", entorno["dispositivo_por_defecto"]["nombre"])
    print("Dispositivos activos:", [d["nombre"] for d in entorno["dispositivos_activos"]])
    print(f"Se oiran pitidos muy bajos cada {args.periodo_bip:.0f} s (777 Hz propio y 1999 Hz externo).")
    if not args.sin_pausa:
        input("\nPulsa Intro para empezar (luego sigue los avisos en pantalla)... ")

    pid = os.getpid()
    tmp = banco.directorio_temporal("s4_t3_")
    log = os.path.join(tmp, "trabajadores.jsonl")
    parar_log = threading.Event()
    _t0_ns = banco.ahora_ns()
    enumerador = monitor = None
    capturas: dict[str, CapturaGestionada] = {}
    repro = None
    ext = None
    estado_por_segundo: list[dict] = []
    try:
        enumerador, monitor = crear_monitor_de_dispositivos()
        evento("inicio", f"PID {pid}; dispositivo por defecto: {nombre_dispositivo_por_defecto()}")
        for nombre, modo in (("EXCLUDE", ModoCaptura.EXCLUDE), ("INCLUDE", ModoCaptura.INCLUDE), ("ENDPOINT", ModoCaptura.ENDPOINT)):
            capturas[nombre] = CapturaGestionada(nombre, pid, modo, SR, al_evento=lambda t, n=nombre: evento("vigilante", t))
        repro = ReproductorGestionado(al_evento=lambda t: evento("reproduccion", t))
        if not args.sin_externo:
            ext = banco.ExternoUDP(log, metodo="cmd")
            ext.orden("abrir 20 3 2")
            evento("externo", f"emisor externo listo (pid {ext.pid_real}); fuera del arbol de este proceso")
            threading.Thread(target=seguir_log_del_externo, args=(log, parar_log), daemon=True).start()

        def emisor_externo() -> None:
            time.sleep(args.periodo_bip / 2)
            while not parar_log.is_set():
                try:
                    ext.orden(f"tono {F_EXTERNO} {BIP_S} {args.amplitud} t3", espera_s=3.0)
                except Exception as exc:
                    evento("externo", f"el emisor externo no responde: {type(exc).__name__}")
                parar_log.wait(args.periodo_bip)

        if ext is not None:
            threading.Thread(target=emisor_externo, daemon=True).start()

        avisos = sorted([(args.t_desconectar, ">>> AHORA: DESCONECTA los auriculares (apaga el G733 o quita el receptor USB)"),
                         (args.t_conectar, ">>> AHORA: CONECTA los auriculares de nuevo y espera a que Windows los reconozca"),
                         (args.t_cambiar, ">>> (opcional) cambia a mano el dispositivo de salida por defecto (Win+Ctrl+V) y luego vuelve al original")])
        siguiente_aviso = 0
        proximo_bip = 0.0
        proximo_estado = 1.0
        ultimo_defecto = ""
        ultimo_defecto_t = -10.0
        evento("inicio", "referencia: no toques nada hasta el primer aviso")
        while rel_s() < args.duracion:
            t = rel_s()
            for c in capturas.values():
                c.vigilar()
            repro.vigilar()
            if siguiente_aviso < len(avisos) and t >= avisos[siguiente_aviso][0]:
                evento("AVISO", avisos[siguiente_aviso][1])
                siguiente_aviso += 1
            if t >= proximo_bip:
                repro.tono(F_PROPIO, BIP_S, args.amplitud)
                proximo_bip += args.periodo_bip
            if t >= proximo_estado:
                proximo_estado += 1.0
                if t - ultimo_defecto_t >= 3.0:
                    ultimo_defecto, ultimo_defecto_t = nombre_dispositivo_por_defecto(), t
                fila: dict = {"t_s": round(t, 1), "defecto": ultimo_defecto}
                partes = []
                ahora = banco.ahora_ns()
                ventana_bip = args.periodo_bip + 0.5
                for nombre, c in capturas.items():
                    paq = sum(1 for p in c.registro.paquetes[-150:] if ahora - p.t_ns <= 1e9)
                    if nombre == "EXCLUDE":
                        oye = "ext:" + ("SI" if tono_reciente(c.registro, F_EXTERNO, ventana_bip) else "no")
                    elif nombre == "INCLUDE":
                        oye = "propio:" + ("SI" if tono_reciente(c.registro, F_PROPIO, ventana_bip) else "no")
                    else:
                        oye = ("ext:" + ("SI" if tono_reciente(c.registro, F_EXTERNO, ventana_bip) else "no") + " propio:" +
                               ("SI" if tono_reciente(c.registro, F_PROPIO, ventana_bip) else "no"))
                    fila[nombre] = {"paquetes_s": paq, "tono": oye}
                    partes.append(f"{nombre} {paq:3d}p/s {oye}")
                cb = repro.callbacks_por_s()
                fila["reproduccion_callbacks_s"] = cb
                estado_por_segundo.append(fila)
                with _bloqueo:
                    print(f"[{t:7.2f}s] " + " | ".join(partes) + f" | REPROD {cb:3.0f}cb/s | defecto: {ultimo_defecto[:38]}", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        evento("fin", "interrumpido por el usuario")
    finally:
        parar_log.set()
        for c in capturas.values():
            c.cerrar()
        if repro is not None:
            repro.cerrar()
        if ext is not None:
            try:
                ext.cerrar()
            except Exception:
                pass
        if enumerador is not None and monitor is not None:
            try:
                enumerador.UnregisterEndpointNotificationCallback(monitor)
            except Exception:
                pass

    # ---- resumen -----------------------------------------------------------------------------------------
    print("\n==== RESUMEN ====")
    print("Linea temporal de eventos (sin las lineas por segundo):")
    for e in sorted(linea_temporal, key=lambda e: e["t_s"]):
        print(f"  [{e['t_s']:7.2f}s] {e['origen']:10} {e['texto']}")
    print("\nRecuperaciones del vigilante:")
    historial = {n: c.historial for n, c in capturas.items()}
    for n, h in historial.items():
        for r in h:
            print(f"  captura {n}: fallo -> {r['causa']} | recuperacion {r['recuperacion_ms']:.0f} ms | intentos {r['intentos']}")
        if not h:
            print(f"  captura {n}: sin fallos")
    if repro is not None:
        for r in repro.historial:
            print(f"  reproduccion: {r['causa']} | intentos {r['intentos']} | recreada tras "
                  f"{(r['t_reabierto_ns'] - r['t_fallo_ns']) / 1e6:.0f} ms")
        if not repro.historial:
            print("  reproduccion: sin fallos (nunca dejaron de pedirle datos)")
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = banco.guardar_json(f"t3_manual_{sello}{('_' + args.nombre) if args.nombre else ''}.json", {
        "entorno": entorno, "linea_temporal": linea_temporal, "estado_por_segundo": estado_por_segundo,
        "historial_capturas": historial,
        "historial_reproduccion": repro.historial if repro is not None else [],
        "notificaciones_reproduccion_propia": [(rel_s(t), n) for t, n in (repro.eventos_dispositivo if repro else [])],
    })
    print("\nResultados guardados en", ruta)
    banco.borrar(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
