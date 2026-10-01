# ADR-0010: Captura por proceso con implementación propia y reglas de exclusión

- Estado: Aceptada (sustituye en parte a ADR-0005)
- Fecha: 2026-10-01
- Decide: humano, a propuesta del orquestador tras el spike S4

## Contexto
El spike S4 (`spikes/audio/README.md`), medido en el PC del usuario, contradijo tres supuestos de ADR-0005:
1. La subclase de pyminiaudio para *process loopback* no funciona: miniaudio 0.11.25 llama a `GetDevice("VAD\Process_Loopback")` y Windows devuelve `E_INVALIDARG`, de modo que se obtiene `MA_INVALID_ARGS`.
2. Windows no excluye «el árbol» de procesos: excluye solo el PID objetivo y sus **hijos directos**. Además, el redirector `python.exe` de un venv deja al intérprete real a dos niveles.
3. En *process loopback* sí llegan paquetes cuando no suena nada: 100 por segundo, de ceros.

Hay también un riesgo nuevo: si muere el PID objetivo, la captura sigue viva pero deja de excluir, y no da ningún error.

## Decisión
- **Captura** con `ActivateAudioInterfaceAsync` en modo `PROCESS_LOOPBACK` + `EXCLUDE_TARGET_PROCESS_TREE`, implementada en Python con ctypes/comtypes (base: `spikes/audio/audio_spike/loopback_ctypes.py`).
- Formato: 16 kHz, mono, float32. COM en MTA (`sys.coinit_flags = 0` antes de importar comtypes o pycaw).
- **PID objetivo = el del proceso núcleo, que capta y reproduce a la vez.** Ningún otro proceso de la app reproduce audio.
- **Reloj de audio** por recuento de muestras. Hay una red de seguridad que rellena con ceros los huecos de más de 100 ms y se resincroniza con la hora de llegada. Los sellos QPC no se usan.
- **Vigilante** con cuatro condiciones:
  - más de 0,5 s sin paquetes;
  - error de WASAPI;
  - **PID objetivo muerto o cambiado**;
  - reproducción detenida.
- **Autotest** al arrancar y tras cada reapertura: un tono de 0,3 s que NO debe aparecer en la captura EXCLUDE y SÍ en una INCLUDE temporal (control positivo).
- **Reproducción**: sigue con pyminiaudio (`PlaybackDevice` sin `device_id`, 48 kHz, estéreo, periodos mínimos de 20 ms × 3).
- **Plan B**: si aparecen cortes con la carga real, la E/S de audio pasa a un proceso hijo dedicado que capta y reproduce, con PID objetivo = él mismo.

ADR-0005 sigue vigente en lo demás: el audio original no se toca, la reproducción va por el dispositivo por defecto y los motores devuelven PCM.

## Alternativas consideradas
- **Sidecar de NAudio (.NET):** innecesario. La captura en Python es robusta: 0,8 % de un núcleo y sin pérdidas con el GIL ocupado.
- **Arreglar miniaudio:** fuera de nuestro alcance; el fallo está en su ruta de Windows de escritorio.

## Consecuencias
- Unas 400 líneas propias de código COM, con tests de contrato (sin dispositivos) y tests `device`.
- La regla «solo el núcleo suena» pasa de recomendación a requisito, comprobado por el autotest y por el monitor de eco.

## Referencias
- `spikes/audio/README.md` (S4, 2026-10-01)
- ADR-0005
