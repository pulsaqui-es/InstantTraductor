"""T5 - Niveles: cambia el nivel capturado el volumen de sesion de la app externa? (spike S4, ADR-0005).

Una app externa (ffplay, lanzada con `cmd /c start`, fuera del arbol) reproduce 6 pitidos de 0,4 s a
1493 Hz (amplitud 0,15, cada 2 s). Entre pitido y pitido este script cambia el volumen de la SESION de
ffplay con pycaw (ISimpleAudioVolume): 100 %, 50 %, 25 %, 10 %, silenciada y otra vez 100 %. Se mide
la amplitud del tono en la captura EXCLUDE y en la ENDPOINT (control) y se compara con lo esperado
(20*log10(volumen de sesion)).

Seguridad:
- Solo se BAJA el volumen de la sesion de ffplay (nunca se sube por encima de 1,0).
- No se toca el volumen maestro del dispositivo (el humano puede estar oyendo otras cosas); solo se lee.
- Windows recuerda el volumen por aplicacion: al terminar (y en `finally`) la sesion de ffplay se deja a
  1,0 y sin silenciar.

Uso:  uv run python t5_niveles.py
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np

import audio_spike  # noqa: F401  (COM en MTA antes de comtypes)
from audio_spike import banco
from audio_spike.analisis import dbfs, inicio_tono, nivel_tono
from audio_spike.modos import ModoCaptura
from audio_spike.tonos import escribir_wav, generar_tono

FRECUENCIA = 1493.0
AMPLITUD = 0.15
PITIDO_S = 0.4
PERIODO_S = 2.0
N_PITIDOS = 6
INICIO_S = 1.0
# (etiqueta, volumen de sesion, silenciada)
PASOS = [("100 %", 1.0, False), ("50 %", 0.5, False), ("25 %", 0.25, False), ("10 %", 0.10, False),
         ("silenciada", 1.0, True), ("100 % otra vez", 1.0, False)]


def crear_wav(ruta: str) -> None:
    sr = 48000
    total = int((INICIO_S + PERIODO_S * N_PITIDOS + 1.0) * sr)
    x = np.zeros(total, dtype=np.float32)
    pitido = generar_tono(FRECUENCIA, PITIDO_S, AMPLITUD, sr)
    for k in range(N_PITIDOS):
        i = int((INICIO_S + PERIODO_S * k) * sr)
        x[i : i + len(pitido)] = pitido
    escribir_wav(ruta, x, sr)


def sesion_de(pid: int):
    from pycaw.utils import AudioUtilities

    for s in AudioUtilities.GetAllSessions():
        if s.ProcessId == pid:
            return s
    return None


def amplitud_reciente(reg, ventana_s: float = 0.25) -> tuple[float, float]:
    """(amplitud del tono, relacion tono/fondo en dB) en los ultimos `ventana_s` s de la captura."""
    ahora = banco.ahora_ns()
    x, _ = reg.ventana(ahora - int(ventana_s * 1e9) - int(0.05e9), ahora)
    if len(x) < int(0.15 * banco.SR_CAPTURA):
        return 0.0, 0.0
    a, _f, r = nivel_tono(x[-int(ventana_s * banco.SR_CAPTURA):], banco.SR_CAPTURA, FRECUENCIA)
    return a, r


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nombre", default="t5_niveles", help="nombre del JSON de resultados")
    args = ap.parse_args()
    pid = os.getpid()
    tmp = banco.directorio_temporal("s4_t5_")
    entorno = banco.info_entorno()
    print("== T5 niveles ==")
    print("Dispositivo:", entorno["dispositivo_por_defecto"]["nombre"], "| volumen maestro (solo lectura):",
          entorno["volumen_maestro_pct"], "%")
    wav = os.path.join(tmp, f"s4_t5_niveles_{int(FRECUENCIA)}.wav")
    crear_wav(wav)

    capt = banco.Capturas(pid, modos=(ModoCaptura.EXCLUDE, ModoCaptura.ENDPOINT))
    capt.iniciar()
    reg_ex = capt.registros[ModoCaptura.EXCLUDE]
    time.sleep(1.0)
    t_base0 = banco.ahora_ns() - int(0.9e9)
    t_base1 = banco.ahora_ns()
    sesion = None
    ej = None
    cambios = []
    try:
        ej = banco.lanzar_ffplay(wav, "cmd")
        print("ffplay externo: pid", ej.pid, "| cadena:", [c["nombre"] for c in ej.cadena])
        # esperar a que aparezca su sesion de audio
        fin = time.monotonic() + 8.0
        while time.monotonic() < fin and sesion is None:
            sesion = sesion_de(ej.pid)
            time.sleep(0.02)
        if sesion is None:
            print("ERROR: no aparecio la sesion de audio de ffplay")
            return 2
        vol = sesion.SimpleAudioVolume
        estado_inicial = {"volumen": round(float(vol.GetMasterVolume()), 3), "mute": int(vol.GetMute())}
        print("Estado inicial de la sesion de ffplay (Windows recuerda el ultimo):", estado_inicial)
        vol.SetMasterVolume(1.0, None)
        vol.SetMute(0, None)
        # esperar el primer pitido en la captura para sincronizar el calendario
        t_primer = None
        fin = time.monotonic() + 8.0
        while time.monotonic() < fin:
            a, r = amplitud_reciente(reg_ex)
            if r > 20.0 and a > 1e-3:
                t_primer = banco.ahora_ns()  # el pitido lleva ya unos 0,1-0,25 s sonando
                break
            time.sleep(0.03)
        if t_primer is None:
            print("ERROR: no se detecto el primer pitido en la captura EXCLUDE")
            return 2
        # calendario: el pitido k empieza ~PERIODO_S*k despues del primero; se cambia el volumen
        # a mitad del hueco anterior (0,8 s antes de cada pitido)
        t_ref = t_primer - int(0.2e9)  # instante aproximado del inicio del primer pitido
        for k in range(1, N_PITIDOS):
            objetivo = t_ref + int((PERIODO_S * k - 0.8) * 1e9)
            while banco.ahora_ns() < objetivo:
                time.sleep(0.005)
            _etq, v, m = PASOS[k]
            vol.SetMasterVolume(float(v), None)
            vol.SetMute(1 if m else 0, None)
            cambios.append({"pitido": k, "volumen": v, "mute": m, "t_ns": banco.ahora_ns(),
                            "leido": {"volumen": round(float(vol.GetMasterVolume()), 3), "mute": int(vol.GetMute())}})
        banco.esperar_ffplay(ej, 10.0)
    finally:
        # dejar la sesion como estaba: 1,0 y sin silenciar
        try:
            if sesion is not None and ej is not None and not ej.terminado:
                sesion.SimpleAudioVolume.SetMasterVolume(1.0, None)
                sesion.SimpleAudioVolume.SetMute(0, None)
        except Exception as exc:
            print("aviso: no se pudo restaurar la sesion:", exc)
        time.sleep(0.4)
        capt.cerrar()

    # ---- analisis --------------------------------------------------------------------------------
    # Inicio real del primer pitido en la captura EXCLUDE; los demas llevan PERIODO_S de separacion exacta.
    x0, tt0 = reg_ex.senal_con_tiempos(t_ref - int(0.6e9), t_ref + int(0.6e9))
    i0 = inicio_tono(x0, banco.SR_CAPTURA, FRECUENCIA)
    t_ref_ns = int(tt0[i0]) if i0 is not None and i0 >= 0 else t_ref
    print(f"Inicio del primer pitido en la captura: {(t_ref_ns - t_ref) / 1e6:+.0f} ms respecto a la estimacion en vivo")
    filas = []
    base_a = {}
    for modo, reg in capt.registros.items():
        xb, _ = reg.ventana(t_base0, t_base1)
        base_a[modo.value] = nivel_tono(xb, banco.SR_CAPTURA, FRECUENCIA)[1] if len(xb) else 0.0
    referencia = {}
    print()
    print(f"{'pitido':6} {'volumen de sesion':20} | {'EXCLUDE dBFS':>13} {'rel. dB':>8} {'esperado':>9} {'dif':>6} | {'ENDPOINT dBFS':>14} {'rel. dB':>8} {'dif':>6}")
    for k, (etq, v, m) in enumerate(PASOS):
        centro = t_ref_ns + int((PERIODO_S * k + PITIDO_S / 2) * 1e9)
        fila = {"pitido": k, "etiqueta": etq, "volumen": v, "mute": m}
        for modo, reg in capt.registros.items():
            x, t = reg.senal_con_tiempos(centro - int(0.6e9), centro + int(0.6e9))
            sel = (t >= centro - 0.12e9) & (t <= centro + 0.12e9)
            xs = x[sel]
            a, fondo, ratio = nivel_tono(xs, banco.SR_CAPTURA, FRECUENCIA) if len(xs) > 800 else (0.0, 0.0, 0.0)
            fila[modo.value] = {"amp_dbfs": round(dbfs(a), 1), "ratio_db": round(ratio, 1)}
            if k == 0:
                referencia[modo.value] = dbfs(a)
            fila[modo.value]["rel_db"] = round(dbfs(a) - referencia[modo.value], 1)
        esperado = None if m else round(20 * np.log10(v), 1)
        fila["esperado_db"] = esperado
        ex, ep = fila["exclude"], fila["endpoint"]
        dif_ex = None if esperado is None else round(ex["rel_db"] - esperado, 1)
        dif_ep = None if esperado is None else round(ep["rel_db"] - esperado, 1)
        fila["dif_exclude_db"], fila["dif_endpoint_db"] = dif_ex, dif_ep
        filas.append(fila)
        print(f"{k:6d} {etq:20} | {ex['amp_dbfs']:13.1f} {ex['rel_db']:8.1f} {str(esperado):>9} {str(dif_ex):>6} | "
              f"{ep['amp_dbfs']:14.1f} {ep['rel_db']:8.1f} {str(dif_ep):>6}")
    print()
    print("(rel. dB = frente al pitido a 100 %; esperado = 20*log10(volumen); 'silenciada' debe dar el suelo de ruido)")
    print("Cambios aplicados:", [{k: v for k, v in c.items() if k != 't_ns'} for c in cambios])
    ruta = banco.guardar_json(f"{args.nombre}.json", {
        "entorno": entorno, "frecuencia": FRECUENCIA, "amplitud_fuente": AMPLITUD,
        "amplitud_fuente_dbfs": round(dbfs(AMPLITUD), 1), "estado_inicial_sesion": estado_inicial,
        "filas": filas, "cambios": cambios,
    })
    print("Resultados guardados en", ruta)
    banco.borrar(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
