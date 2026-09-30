# S4 — Captura por proceso y reproducción de audio en Windows 11

Spike de investigación de la feature 001-espina-dorsal (Ola 0). **No es código de producto**: es un banco de medidas
para validar en el PC real del usuario el ADR-0005 (`docs/adr/0005-captura-y-reproduccion.md`) y la investigación
(`docs/investigacion/2026-09-30-audio-windows.md`). Fecha de las medidas: 2026-10-01.

## Objetivo

Comprobar, con los dispositivos de audio reales, si se sostiene lo que asume el ADR-0005:

1. que una subclase de pyminiaudio 1.71 activa el *process loopback* en modo `EXCLUDE` sobre el PID propio (16 kHz, mono, float32);
2. que el audio del propio proceso y de sus descendientes no reaparece en la captura y el de un proceso externo sí (**T1**);
3. qué llega cuando no suena nada y cómo rellenar por reloj (**T4**);
4. si el volumen de sesión de la app de origen cambia el nivel capturado (**T5**);
5. la latencia desde que un proceso externo suena hasta que la muestra llega a la captura (**T9**);
6. que `PlaybackDevice` sin `device_id` a 48 kHz funciona en el dispositivo por defecto;
7. dejar listo el script manual de **T3** (conexión y desconexión de los auriculares).

## Resumen

| Pregunta | Respuesta medida |
|---|---|
| ¿Funciona la subclase de pyminiaudio? | **No.** `ma_device_init` devuelve `MA_INVALID_ARGS (-2)` con EXCLUDE e INCLUDE. miniaudio 0.11.25 (la rama `master` es idéntica) pide a `IMMDeviceEnumerator::GetDevice` el ID `VAD\Process_Loopback`, que Windows rechaza con `E_INVALIDARG`. El loopback de dispositivo (sin PID) sí funciona. |
| ¿Y el plan B en Python (ctypes/comtypes)? | **Funciona a la primera** con `ActivateAudioInterfaceAsync`. Activa en 0,2–3 ms, acepta 16 kHz mono float32 directamente, entrega paquetes de 160 frames cada 10 ms, usa el 0,8 % de un núcleo y no pierde datos con el GIL ocupado. |
| T1: ¿se excluye al propio proceso y a los descendientes? | **Al propio proceso y a sus hijos directos, sí. A los nietos, no.** Tampoco a un hijo lanzado con `sys.executable` desde un venv de uv (el redirector `python.exe` lo deja a dos niveles). Los procesos externos sí aparecen. **Windows trata como «árbol» solo el PID objetivo y sus hijos directos.** |
| T1c: ¿y si muere el PID objetivo? | La captura sigue viva, sin error, pero **deja de excluir** al proceso nuevo: realimentación silenciosa. |
| T4: ¿llegan paquetes en silencio? | **En process loopback, sí**: 100 paquetes/s de ceros exactos, sin flags. No hace falta relleno. El loopback de dispositivo sí calla (hasta que hay una sesión activa, aunque sea muda). |
| T5: ¿el volumen de sesión cambia el nivel? | **Sí, linealmente** (−6,4 dB al 50 %, −12,4 dB al 25 %, −20,3 dB al 10 %) y silenciar da ceros exactos. |
| T9: latencia | Muestra escrita en la fuente → disponible en la captura: **82 ms** (fuente 10 ms × 2) o **124 ms** (fuente 20 ms × 3). El process loopback añade 27–35 ms al loopback de dispositivo. |
| Reproducción | Abre sin `device_id` a 48 kHz float32 en el G733, en 21–41 ms. 8 de 8 formatos de entrada suenan bien. 20 ms × 3 periodos aguanta un GIL ocupado; 10 ms × 2 no. |
| T3 manual | Script listo: `probar_cambio_dispositivo.py` (no ejecutado). |

## Entorno (versiones exactas)

| Componente | Versión |
|---|---|
| Windows | 11 Pro 25H2, build 26200.9457 |
| Python | 3.12.14 (CPython gestionado por uv 0.12.21) |
| pyminiaudio (`miniaudio` en PyPI) | 1.71, con miniaudio (C) 0.11.25 |
| numpy | 2.5.3 |
| pycaw / comtypes | 20260927 / 1.4.17 |
| psutil / cffi | 7.2.2 / 2.1.1 |
| ffplay (app «externa» de prueba) | 9.0.1-essentials_build-www.gyan.dev |
| Dispositivo por defecto | Altavoces (Logitech G733 Gaming Headset). Mezcla de WASAPI: 48 kHz, **8 canales**, float32 |
| Otros destinos activos | Q27G42ZE y SAMSUNG (NVIDIA High Definition Audio), Realtek Digital Output |
| Volumen maestro | 78 % (solo lectura; no se ha tocado ningún volumen del sistema) |
| Árbol de procesos de las pruebas | `uv.exe` → `python.exe` (redirector del venv) → `python.exe` (intérprete real: el que suena y captura) |

Las versiones quedan fijadas en `pyproject.toml` y `uv.lock` (proyecto uv propio de esta carpeta; en la raíz del repo no hay `pyproject`).

## Método

- **Tonos de prueba:** senos con fundidos de 5 ms, frecuencias poco comunes (1234, 777, 1111, 1222, 1321, 1357, 1471, 1493, 1579, 1663, 1777, 1888 y 1999 Hz), de 0,25 a 1 s y amplitud 0,15 (−16,5 dBFS; 0,10 en los de 1 s). Ningún script toca el volumen del dispositivo (T5 solo baja el de la sesión de ffplay).
- **Tres capturas simultáneas** en cada prueba de exclusión: `EXCLUDE(PID)` (la que usará la app), `INCLUDE(PID)` (control positivo: oye lo que EXCLUDE no oye) y `ENDPOINT` (loopback clásico del dispositivo por defecto: oye todo). Sin los controles, un «no aparece» no probaría nada, porque el sonido podría no haber salido.
- **Detección por pico espectral relativo** (`audio_spike/analisis.py`), robusta a que el humano oiga otras cosas: amplitud del seno a la frecuencia de la prueba (demodulación con ventana de Hann, ventana deslizante de 0,3 s) frente a la **mediana** de la amplitud en 40 frecuencias de referencia cercanas. Se da por presente con una relación ≥ 15 dB y ≥ 10 dB por encima de la misma medida en un tramo base sin tonos. En la práctica, presente = 118–139 dB y ausente = 0–13 dB (el sistema estaba en silencio digital).
- **Procesos externos:** `cmd /c start "" /min` (ffplay y un trabajador Python con `pythonw`) y `Win32_Process.Create` por WMI. En cada caso se comprueba con psutil que la cadena de PIDs padre no llega al proceso que captura.
- **Reloj común:** `time.perf_counter_ns()` (QPC) es el mismo en todos los procesos (desfase medido 0,06 ms, ida y vuelta 0,3 ms).
- **Limpieza:** todo proceso que lanzan los scripts lleva la carpeta temporal en su línea de comandos y se mata al terminar; los WAV son temporales y no se guardan.

## Resultados

### Subclase de pyminiaudio (plan A): no funciona

`audio_spike/loopback.py` (`CapturaProceso`) es la subclase del boceto de la investigación (§4.1), con dos diferencias:
engancha `notificationCallback` con `ffi.callback` y admite los tres modos. Nota: `CaptureDevice._data_callback` entrega un
`bytearray`, no un `array('f')` como decía el boceto. Resultado exacto (`uv run python diagnostico_subclase.py`):

```text
endpoint  OK: dispositivo creado, backend WASAPI; paquetes: 99; tono de 1234 Hz detectado: SI (125 dB)
exclude   ERROR: MiniaudioError: ('ma_device_init fallo: MA_INVALID_ARGS (-2) [modo=exclude, pid=360764]', -2)
include   ERROR: MiniaudioError: ('ma_device_init fallo: MA_INVALID_ARGS (-2) [modo=include, pid=360764]', -2)
GetDevice('VAD\\Process_Loopback') -> COMError 0x80070057 (El parámetro no es correcto.)
```

**Causa confirmada:** en la ruta «Desktop» de miniaudio, `ma_context_get_IAudioClient__wasapi` sustituye el ID por el dispositivo
virtual `VAD\Process_Loopback` y `ma_context_get_IAudioClient_Desktop__wasapi` llama a `ma_context_get_MMDevice__wasapi`, que ejecuta
`IMMDeviceEnumerator::GetDevice(L"VAD\\Process_Loopback")` antes de `Activate()`. Windows devuelve `E_INVALIDARG` (se comprobó la
llamada por separado con pycaw) y miniaudio lo convierte en `MA_INVALID_ARGS`. El dispositivo virtual solo se puede activar con
`ActivateAudioInterfaceAsync`, que miniaudio usa únicamente en la ruta UWP. El `miniaudio.h` de la rama `master` (0.11.25) es idéntico
al de la etiqueta (`cmp`, 2026-10-01): no hay arreglo aguas arriba ni versión de pyminiaudio que lo incluya. Desde Python no hay forma
de evitar esa ruta (el código C va compilado en el wheel), así que la subclase no es viable. Sí funcionan su modo sin PID
(loopback de dispositivo) y el gancho de notificaciones.

### Plan B en Python (ctypes + comtypes): funciona

`audio_spike/loopback_ctypes.py` (`CapturaProcesoCtypes`, unas 400 líneas con comentarios):

1. rellena `AUDIOCLIENT_ACTIVATION_PARAMS` (EXCLUDE o INCLUDE + PID) en un `PROPVARIANT` de tipo `VT_BLOB`;
2. llama a `ActivateAudioInterfaceAsync(L"VAD\\Process_Loopback", IID_IAudioClient, ...)` con un manejador que implementa
   `IActivateAudioInterfaceCompletionHandler` **e** `IAgileObject`;
3. `IAudioClient::Initialize(SHARED, LOOPBACK | EVENTCALLBACK | AUTOCONVERTPCM | SRC_DEFAULT_QUALITY, ..., 16 kHz mono float32)`;
4. un hilo espera el evento y lee con `IAudioCaptureClient`, con la hora de llegada, los flags y el sello QPC de cada paquete.

| Medida | Resultado |
|---|---|
| Activación del dispositivo virtual | 0,2–3 ms (EXCLUDE e INCLUDE) |
| Formato | 16 kHz **mono** float32 aceptado directamente (Windows convierte) |
| Paquetes | siempre 160 frames (10 ms), cada 10,0 ms (p99 ≈ 11 ms) |
| Flags de WASAPI | siempre 0 (nunca SILENT, discontinuidad ni error de sello) |
| CPU de una captura en reposo | 0,8 % de un núcleo |
| Con un hilo Python de cálculo puro ocupando el GIL | intervalo máximo entre paquetes 22–25 ms, 0 discontinuidades y 0 huecos en el tono, con búfer de WASAPI de 100 ms **y** de 30 ms |

La investigación indica que sin `IAgileObject` el sistema falla con `E_ILLEGAL_METHOD_CALL` (no se ha probado aquí: el manejador lo
implementa desde el principio). COM debe estar en MTA (`sys.coinit_flags = 0` antes de importar comtypes o pycaw;
`audio_spike/__init__.py` lo hace).

### T1 — autoexclusión (`t1_autoexclusion.py`, 2 rondas idénticas)

«Niveles» = distancia en la cadena de PIDs entre el proceso que suena y el PID objetivo (0 = el propio). «Según ADR» = lo que
asumen el ADR-0005 y la investigación (todo descendiente queda excluido).

| Escenario | Niveles | EXCLUDE (¿aparece?) | INCLUDE | ENDPOINT | Según ADR |
|---|---:|---|---|---|---|
| `propio_nuevo`: `PlaybackDevice` creado tras iniciar la captura | 0 | no | sí | sí | cumple |
| `propio_previo`: dispositivo abierto (con ceros) antes de la captura | 0 | no | sí | sí | cumple |
| `hijo_directo_previo`: hijo directo creado y con el dispositivo abierto antes de la captura | 1 | no | sí | sí | cumple |
| `hijo_directo_posterior`: hijo directo creado después de iniciar la captura | 1 | no | sí | sí | cumple |
| `ffplay_hijo_directo`: ffplay con `Popen` directo | 1 | no | sí | sí | cumple |
| `hijo_redirector`: hijo lanzado con `sys.executable` (redirector del venv) | 2 | **sí** | no | sí | **no cumple** |
| `nieto_directo`: nieto (hijo directo del hijo directo), sin redirectores | 2 | **sí** | no | sí | **no cumple** |
| `nieto_redirector`: nieto lanzado con `sys.executable` desde un hijo con redirector | 4 | **sí** | no | sí | **no cumple** |
| `ffplay_via_cmd`: `cmd /c ffplay` (cmd.exe vivo de intermedio) | 2 | **sí** | no | sí | **no cumple** |
| `externo_ffplay_cmd`: ffplay con `cmd /c start /min` | externo | sí | no | sí | cumple |
| `externo_python_cmd`: trabajador Python (`pythonw`) con `cmd /c start /min` | externo | sí | no | sí | cumple |
| `externo_ffplay_wmi`: ffplay con `Win32_Process.Create` (padre `WmiPrvSE.exe`) | externo | sí | no | sí | cumple |

- Las dos rondas dan el mismo resultado en las 12 filas (8 de 24 lanzamientos no cumplen, siempre los de profundidad ≥ 2).
- La relación tono/fondo fue de 118–139 dB donde aparece y de 0–13 dB donde no. El ENDPOINT oyó los 12 tonos: todos salieron al dispositivo.
- Cadenas de los externos (ninguna llega al proceso que captura): `ffplay.exe <- <cmd.exe muerto>`, `pythonw.exe <- pythonw.exe <- <muerto>`, `ffplay.exe <- WmiPrvSE.exe <- svchost.exe <- services.exe <- wininit.exe`.
- Una primera pasada de desarrollo (`resultados/t1_primera_ejecucion.json`) incluyó un **nieto huérfano** (su padre muere antes de que suene): aparece en EXCLUDE, como cualquier proceso fuera del alcance.

### T1b — qué entiende Windows por «árbol» (`t1b_arbol.py`)

**Parte A (ascendientes).** El tono del propio proceso se mide con capturas cuyo PID objetivo es cada ascendiente:

| PID objetivo | Distancia de mi proceso | INCLUDE oye mi tono | EXCLUDE oye mi tono |
|---|---:|---|---|
| yo (`python.exe`) | 0 | sí | no |
| redirector del venv (`python.exe`) | 1 | **sí** | no |
| `uv.exe` | 2 | **no** | sí |
| `bash.exe` (y 2 más), `claude.exe`, `Code.exe` (2), `explorer.exe` | 3–9 | no | sí (probado hasta el nivel 3) |

**Parte B (descendientes).** Confirma la tabla de T1: el hijo directo queda incluido por INCLUDE(yo) aunque se cree antes o después de
activar la captura (la evaluación es dinámica) y `INCLUDE(redirector)` oye a su hijo directo, que es el intérprete real.

> **Regla medida:** el process loopback cubre el **PID objetivo y sus hijos directos**, no el árbol entero, tanto en INCLUDE como en EXCLUDE.

### T1c — el proceso objetivo muere (`t1c_pid_objetivo_muere.py`)

Un hijo A suena y se excluye con EXCLUDE(A): no aparece, y INCLUDE(A) sí lo oye. Se mata A:

- las dos capturas **siguen entregando 100 paquetes/s, sin ningún error**;
- un hijo nuevo B (otro PID) suena a continuación y **aparece en EXCLUDE(A)**: la captura antigua ya no excluye nada.

Si el proceso que suena se reinicia, hay que reactivar la captura con el PID nuevo; nada avisa del fallo, y el resultado sería realimentación.

### T4 — silencio (`t4_silencio.py`)

Sistema en silencio real (sin sesiones activas ajenas). Paquetes por segundo, contenido y flags, por fase:

| Fase | EXCLUDE | INCLUDE | ENDPOINT |
|---|---|---|---|
| Ambiente: nada suena y no hay ninguna sesión activa | 100 paq/s, **ceros exactos** (−180 dBFS) | 100 paq/s, ceros exactos | **0 paq/s** |
| `PlaybackDevice` propio abierto, alimentado con ceros | 100 paq/s, ceros exactos | 100 paq/s (−135 dBFS de ruido numérico) | 100 paq/s (−135 dBFS) |
| 3 tonos de 0,3 s con el dispositivo abierto | 100 paq/s, no ve el tono (excluido) | 100 paq/s, ve el tono | 100 paq/s, ve el tono |
| Dispositivo propio cerrado | 100 paq/s | 100 paq/s | **0 paq/s** otra vez |
| Sesión externa activa reproduciendo ceros (ffplay con WAV mudo) | 99,7 paq/s (−134 dBFS) | 100 paq/s | 99,7 paq/s, con paquetes **marcados SILENT** (flags 0 y 2) |
| 300 s en reposo | 100,0 paq/s = 16000,0 frames/s; máximo intervalo 27 ms | igual (24 ms) | 0 paq/s |

- **Paquetes y flags:** en process loopback llegan siempre paquetes de 160 frames cada 10,0 ms (p99 ≈ 11 ms) y **nunca** llevan flags. El loopback de dispositivo (ENDPOINT) calla por completo mientras no haya ninguna sesión activa, que es lo que describía la investigación; basta una sesión abierta, aunque sea muda, para que entregue paquetes.
- **Sellos QPC:** el 99,99 % de los pasos entre sellos son exactamente 10,000 ms: los sellos de `GetBuffer` son **sintéticos** (cuenta de frames), no medidos. En 300 s de reposo la tasa por hora de llegada es 16000,0 Hz (deriva 0 ppm). Hay un salto puntual de 8–17 ms en el sello **cada vez que empieza o termina una sesión dentro del conjunto capturado** (2 por captura y ejecución: mi reproductor abriéndose y cerrándose para INCLUDE, el ffplay externo arrancando y terminando para EXCLUDE); por eso una ejecución completa aparenta una deriva de −50 a −80 ppm (y una corta, de −470 a −550 ppm) que no es tal (`resultados/t4_saltos.json` localiza los saltos por fase).
- **Hora de llegada frente al sello:** la diferencia es constante para cada instancia de captura (9,3–10,6 ms, p99 ≤ 11,9 ms), coherente con sellos sintéticos: **no informa de la latencia real**; la latencia se mide en T9.
- **Relleno por reloj** (`audio_spike/relleno.py`, simulado sobre las llegadas reales de toda la ejecución): EXCLUDE e INCLUDE, 333 s reales, **0 s rellenados, 0 huecos, 0 ms recortados**. ENDPOINT, que sí deja huecos: 20,3 s reales y 4,58 s de ceros para cubrir el silencio, con un hueco detectado.

**Propuesta de relleno por reloj** (`RellenoPorReloj`, con autoprueba sintética: `uv run python -m audio_spike.relleno`):

- el audio real **nunca se recorta ni se duplica por jitter**: una parada de 25–40 ms sigue siendo continua con el paquete anterior (mi primera versión rellenaba y recortaba 10 ms de audio real tras una parada de 25 ms; se descartó);
- solo se rellena con ceros un **hueco real**: más de 100 ms sin paquetes; `tick(ahora)` cada 10–20 ms emite ceros hasta `ahora − 40 ms`;
- al volver los paquetes se alinea exactamente con el reloj (se añaden los ceros que falten o se recorta como máximo el margen);
- fuera de un hueco, la deriva se absorbe moviendo despacio la referencia, sin tocar las muestras;
- las marcas de tiempo deben salir de la **hora de llegada**, no de contar muestras ni de los sellos QPC.

### T5 — niveles (`t5_niveles.py`, 2 pasadas idénticas)

ffplay (externo) reproduce 6 pitidos de 0,4 s a 1493 Hz. Entre pitido y pitido se cambia el volumen de **su sesión** con pycaw
(`ISimpleAudioVolume`). Solo se baja el volumen, nunca se sube por encima de 1,0, y se deja en 1,0 al terminar.

| Volumen de la sesión de ffplay | Amplitud en EXCLUDE | Relativa al 100 % | Esperada (20·log₁₀ v) | Diferencia |
|---|---:|---:|---:|---:|
| 100 % | −27,5 dBFS | 0,0 dB | 0,0 dB | — |
| 50 % | −33,8 dBFS | −6,4 dB | −6,0 dB | −0,4 dB |
| 25 % | −39,9 dBFS | −12,4 dB | −12,0 dB | −0,4 dB |
| 10 % | −47,8 dBFS | −20,3 dB | −20,0 dB | −0,3 dB |
| Silenciada (mute) | −180 dBFS (ceros exactos) | — | — | — |
| 100 % otra vez | −27,8 dBFS | −0,3 dB | 0,0 dB | −0,3 dB |

- **Sí:** el nivel capturado escala con el volumen de sesión de la app de origen, de forma lineal en amplitud, con ±0,4 dB. El ENDPOINT da lo mismo con ±0,1 dB: ambos toman el audio después del volumen de sesión.
- **No se midió el volumen maestro** del dispositivo: cambiarlo habría roto lo que el humano estuviera oyendo. La literatura (A2DP-Windows-Bridge) dice que no afecta al process loopback; sigue sin verificar aquí.
- **El nivel absoluto depende de la fuente:** el mismo nivel de entrada (−16,5 dBFS) llega a −13,0 dBFS desde un `PlaybackDevice` estéreo, a −10,2 dBFS desde uno mono y a −27,5 dBFS desde ffplay (WAV mono); la causa no se ha investigado (el dispositivo mezcla en 7.1 y puede tener efectos propios). Hace falta un AGC con margen amplio (≥ 40 dB) y un aviso cuando llegue silencio digital sostenido (app silenciada o al 0 %).

### T9 — latencia (`t9_latencia.py`)

Un trabajador Python externo (cadena `pythonw.exe <- pythonw.exe <- <muerto>`, fuera del árbol) tiene un `PlaybackDevice` abierto y,
al recibir una orden UDP, escribe un tono de 0,25 s. Anota con QPC el instante en que entrega el primer bloque con tono. Aquí se detecta
el inicio del tono en la captura (la hora de cada muestra se estima como la llegada de su paquete menos el tiempo que queda hasta el
final de ese paquete) y se resta. 10 pruebas por configuración, en instantes aleatorios respecto a los paquetes de 10 ms.

| Búfer de la fuente (periodo × periodos) | Fuente → EXCLUDE (process loopback) | Fuente → ENDPOINT (loopback de dispositivo) | EXCLUDE − ENDPOINT |
|---|---|---|---|
| 10 ms × 2 | **81,8 ms** (80,5–83,6; σ 0,8) | 49,4 ms (48,7–50,0) | +32,3 ms |
| 20 ms × 3 (ADR) | **124,0 ms** (122,2–125,7; σ 0,9) | 89,7 ms (89,2–90,0) | +34,4 ms |

- Es una latencia de extremo a extremo de la capa de audio: incluye el búfer de reproducción de la **fuente**, la mezcla de Windows y el paquete de captura de 10 ms. No incluye el dispositivo físico (el loopback toma el audio antes de él).
- Dentro de una ejecución es muy estable (σ < 1 ms) pero **entre ejecuciones varía unos milisegundos** en la parte del process loopback: una ejecución anterior de desarrollo dio 84,0 y 117,4 ms (+34,1 y +27,5 ms sobre el ENDPOINT). Conviene dar 27–35 ms como coste del process loopback sobre el loopback de dispositivo.
- La cifra de la investigación («30–150 ms») se confirma para la capa de audio: **82–124 ms**, despreciable frente al objetivo de 1,5–3 s.

### Reproducción (`reproduccion.py`)

| Comprobación | Resultado |
|---|---|
| `PlaybackDevice` sin `device_id`, 48 kHz float32, estéreo, 20 ms × 3 | Abre en 21–41 ms, backend WASAPI, en el dispositivo por defecto (Altavoces G733). La captura ENDPOINT oye el tono a −13,0 dBFS |
| Formatos de entrada (48000, 44100, 24000 y 22050 Hz × mono y estéreo) | Los 8 abren y suenan a 1234 Hz: Windows/miniaudio convierten bien, así que **no hace falta remuestrear en Python** el PCM de un TTS a 22,05 o 24 kHz (la investigación proponía hacerlo con soxr para no reabrir el dispositivo al cambiar de motor; sigue siendo opción) |
| Cadencia de peticiones de datos en reposo | 20 × 3: 20,0 ms (p99 20,6; máx. 20,7). 10 × 2: 10,0 ms (p99 11,1). 30 × 3: 30,0 ms (p99 30,7) |
| Cadencia con un hilo Python de cálculo puro ocupando el GIL | 20 × 3: p99 37,7 ms, máx. 44,0 ms, ninguno por encima de los 60 ms del búfer. 10 × 2: máx. 30,9 ms, 14 por encima de los 20 ms del búfer. 30 × 3: máx. 48,8 ms |
| **Cortes reales** (3 tonos de 1 s, huecos en el tono capturado) | 10 × 2 con el GIL libre: 0. **10 × 2 con el GIL ocupado: 30 huecos (324 ms de audio perdido).** 20 × 3 con el GIL libre: 0. 20 × 3 con el GIL ocupado: 3 microhuecos (1 ms en total, inaudibles) |
| Notificaciones de dispositivo | `notificationCallback` (started, stopped, rerouted, interruption) se engancha con `ffi.callback`; pyminiaudio 1.71 no lo hace (`PlaybackDeviceConNotificaciones` en `audio_spike/tonos.py`) |

### Vigilante (prototipo para T3)

`audio_spike/vigilante.py` reabre la captura si el hilo de lectura muere, si no se puede crear o, **solo en process loopback**, si
dejan de llegar paquetes (umbral 0,5 s; el loopback de dispositivo calla sin sesiones activas, así que allí solo se reabre ante un
error de lectura), y recrea el `PlaybackDevice` si dejan de pedirle datos (1,0 s). Probado con fallos simulados (sin cambiar de
dispositivo): la captura se reabrió en 1–7 ms y recuperó datos a los 42–51 ms del fallo detectado; el reproductor se recreó en
43–60 ms. Un hueco de datos de 0,5 s (el umbral) es lo que habría que cubrir con ceros.

## Problemas y soluciones

| Problema | Causa | Solución |
|---|---|---|
| La subclase de pyminiaudio falla con `MA_INVALID_ARGS (-2)` | miniaudio 0.11.25 llama a `GetDevice("VAD\Process_Loopback")` | Plan B con `ActivateAudioInterfaceAsync` (`loopback_ctypes.py`) |
| Un hijo no quedaba excluido | Windows solo cubre el PID objetivo y sus hijos directos; con el venv de uv, `sys.executable` es un redirector que crea el intérprete real como hijo (dos niveles) | Excluir el PID de quien suena (`os.getpid()`); en las pruebas, `Popen` del intérprete base (`sys._base_executable`) para tener un hijo directo |
| Una pasada de T4 dio paquetes continuos en el ENDPOINT «en silencio» | Quedaron vivos tres `ffplay` de mis pruebas de humo: `-t N` con `lavfi anullsrc` no los termina y mantenían una sesión activa | WAV mudo finito, limpieza por marca de todo proceso propio y listado de sesiones activas al empezar T4 |
| El ffplay «externo» parecía colgar de este proceso | `cmd /c start /b` mantiene vivo `cmd.exe`; además mi `Popen` retenía el handle del `cmd.exe` ya muerto y psutil lo veía como padre | `start /min` y esperar a que `cmd.exe` termine antes de mirar la cadena |
| No se encontraba el PID de ffplay | Con `process_iter` leyendo la línea de comandos de todos los procesos el escaneo tarda más que la vida útil de ffplay | Filtrar primero por nombre y leer la línea de comandos solo de los candidatos; WAV con silencio final |
| El relleno por reloj recortaba audio real tras una parada de 25 ms | Trataba el jitter como hueco y luego como solape | Política nueva: solo huecos de más de 100 ms; el audio real no se toca |
| Niveles absolutos inconsistentes entre escenarios | Formato, canales y mezcla 7.1 del dispositivo | Comparar siempre niveles relativos (T5) y medir la máxima amplitud, no la de la ventana de mayor relación |
| pyminiaudio no avisa de `rerouted` ni `stopped` | No engancha `notificationCallback` | `ffi.callback` y una copia de `PlaybackDevice.__init__` con el gancho |
| Posible choque de modo COM entre miniaudio, comtypes y pycaw (no llegó a observarse) | comtypes inicializa COM en STA por defecto; miniaudio y los callbacks de pycaw trabajan en MTA | Prevención: `sys.coinit_flags = 0` (MTA) antes de importar comtypes o pycaw (`audio_spike/__init__.py`) |

## Conclusión y recomendación para el plan

1. **Captura: process loopback con ctypes/comtypes, no con pyminiaudio.** `audio_spike/loopback_ctypes.py` es la base de la implementación de producción (unas 400 líneas). Va detrás de `AudioSource`. El sidecar de NAudio deja de ser necesario para la captura: la captura en Python es robusta (0,8 % de CPU, sin pérdidas con el GIL ocupado); queda solo como opción si se quiere aislar más el audio del GIL.
2. **`TargetProcessId` = PID del proceso que reproduce, y ese proceso captura y reproduce a la vez.** Windows no excluye «el árbol»: solo el PID y sus hijos directos. Con `audio_io` reproduciendo y capturando en el mismo proceso, basta `EXCLUDE(os.getpid())`, que se comprobó con la sesión creada antes y después de iniciar la captura. Los demás procesos (ASR, traducción, TTS) **nunca reproducen**, tal como ya decía la arquitectura. Un proceso auxiliar que suene quedaría fuera de la exclusión y realimentaría (por ejemplo, un hijo lanzado con `multiprocessing` y `spawn`, que usa `sys.executable` y en un venv pasa por el redirector: no se ha probado, pero quedaría a dos niveles). Si captura y reproducción estuvieran en procesos distintos, el objetivo sigue siendo el PID del que reproduce (o el de su padre directo).
3. **Autotest al arrancar y tras cada reinicio de `audio_io`:** emitir un tono de 0,3 s muy bajo de una frecuencia poco común, comprobar que **no** está en la captura EXCLUDE y que **sí** está en una captura INCLUDE temporal del mismo PID (control positivo); ambas detecciones son las de `analisis.py`. Si el tono reaparece, avisar de realimentación.
4. **Vigilante con cuatro condiciones:** sin paquetes durante más de 0,5 s (solo en process loopback, que entrega paquetes siempre), error de lectura de WASAPI, **PID objetivo muerto o cambiado** (T1c: es un fallo silencioso) y notificación `stopped` de la reproducción. Reabrir cuesta 1–7 ms en la captura y 43–60 ms en la reproducción.
5. **Silencio:** en process loopback **no hace falta relleno por reloj**. Se conserva `RellenoPorReloj` como red de seguridad para huecos de más de 100 ms (suspensión, pérdida del dispositivo) y para el fallback al loopback de dispositivo, que sí deja huecos. No usar el conteo de muestras ni los sellos QPC para las marcas de tiempo: usar la hora de llegada.
6. **Niveles:** AGC de margen amplio (la ganancia efectiva cambia hasta 17 dB según la fuente y el volumen de sesión escala linealmente) y aviso de «sin audio del origen» si llega silencio digital sostenido (app silenciada o al 0 %).
7. **Latencia:** 82–124 ms de la fuente a la captura, más el búfer de salida; despreciable frente a 1,5–3 s. El process loopback añade 27–35 ms al loopback de dispositivo.
8. **Reproducción:** `PlaybackDevice` sin `device_id`, 48 kHz float32, estéreo, **mínimo 20 ms × 3 periodos (60 ms)**; 10 ms × 2 pierde audio en cuanto el GIL se ocupa. Seguir aislando el audio en su propio proceso: con 60 ms de búfer se aguantó un hilo de cálculo puro, pero no se midió carga real de ML ni de GPU. Windows convierte las frecuencias de 22,05 a 48 kHz y mono/estéreo sin problema.
9. **Pendiente** (no medido en este spike): T2 (otros destinos de audio), **T3 (manual, script listo)**, T6 (DRM), T7 (audio espacial y modo exclusivo), T8 (carga real de GPU), T10 (suspensión), el volumen maestro, y la latencia de la reproducción de extremo a extremo con un micrófono externo.

### Correcciones propuestas al ADR-0005 y a la investigación

(El spike no edita `docs/**`; se proponen para que las aplique el orquestador.)

| Texto actual | Corrección propuesta |
|---|---|
| ADR-0005, Decisión: «Implementación: **pyminiaudio 1.71** (MIT), con una subclase que activa el modo por proceso» | La subclase no funciona (`MA_INVALID_ARGS`). Captura con ctypes/comtypes sobre `ActivateAudioInterfaceAsync`; pyminiaudio queda para la reproducción (y el loopback de dispositivo) |
| ADR-0005: «*process loopback* … sobre el PID del núcleo, es decir, “todo el sistema salvo InstantTraductor”» | El objetivo es el PID del proceso que reproduce (`audio_io`), que también captura. Windows solo cubre ese PID y sus hijos **directos** |
| ADR-0005: «En silencio no llegan paquetes, así que se rellena con ceros según el reloj» | En process loopback llegan 100 paquetes/s de ceros; el relleno es una red de seguridad para huecos de más de 100 ms |
| ADR-0005, Riesgos: «audio … fuera del árbol: queda prohibido» | Precisar: «fuera del proceso que captura o de sus hijos directos» (los nietos y el redirector del venv cuentan como fuera) |
| Investigación §3.2 reglas 1, 2, 4 y 7 (un único proceso raíz, hijos y nietos dentro del árbol, hijos dinámicos) | Solo PID objetivo + hijos directos; la evaluación sí es dinámica para los hijos directos |
| Investigación §3.1.2 y §5 riesgo 2 («puede no llegar ningún paquete»; fiabilidad de `qpcPosition`) | Siempre llegan paquetes; los sellos QPC son sintéticos |
| Investigación §4.1, boceto de la subclase | No funciona; sustituir por el plan B de este spike |
| Riesgo nuevo para la lista | Si muere o se reinicia el PID objetivo, la captura sigue viva y deja de excluir (T1c) |

## Cómo reproducir

Desde `spikes/audio/` (o con `uv run --directory spikes/audio ...` desde la raíz). El humano oirá pitidos cortos y bajos; no se
toca ningún volumen del sistema. Conviene que no suene otra cosa en ese momento, aunque la detección tolera ruido de fondo.

```bash
uv sync                                          # crea .venv (Python 3.12) con las versiones de uv.lock
uv run python diagnostico_subclase.py            # error exacto de la subclase + causa + plan B (1 pitido)
uv run python t1_autoexclusion.py --rondas 2     # T1: 12 escenarios x 2 rondas (24 pitidos de 0,6 s)
uv run python t1b_arbol.py                       # T1b: ascendientes y descendientes (6 pitidos)
uv run python t1c_pid_objetivo_muere.py          # T1c: muere el PID objetivo (2 pitidos)
uv run python t4_silencio.py --deriva-s 300      # T4: silencio, sellos, deriva (3 pitidos, unos 6 min)
uv run python t5_niveles.py                      # T5: niveles (6 pitidos de 0,4 s)
uv run python t9_latencia.py --n 10              # T9: latencia (20 pitidos de 0,25 s)
uv run python reproduccion.py                    # reproducción, formatos, GIL (unos 20 pitidos, 12 de ellos de 1 s)
uv run python captura_bajo_gil.py                # captura con el GIL ocupado y CPU (12 pitidos de 1 s)
uv run python -m audio_spike.relleno             # autoprueba sintética del relleno por reloj (sin audio)
```

Cada script imprime sus tablas y guarda un JSON pequeño en `resultados/`. Los scripts de T1 a T9 terminan con código 0, salvo T1
que devuelve 1 si algún escenario no cumple lo que asume el ADR (cosa que hoy ocurre). Todo lo temporal (WAV, registros) va a una
carpeta temporal que se borra al terminar.

## Prueba manual T3: conexión y desconexión de los auriculares

`probar_cambio_dispositivo.py` **no se ha ejecutado** en este spike: necesita al humano delante.

```bash
uv run python probar_cambio_dispositivo.py                # 120 s; pide Intro para empezar
uv run python probar_cambio_dispositivo.py --duracion 150 --t-desconectar 20 --t-conectar 55 --t-cambiar 90
```

Qué hace: abre un `PlaybackDevice` por defecto (pitido de 777 Hz cada 3 s), lanza un emisor externo (pitido de 1999 Hz, desfasado
1,5 s), tres capturas con vigilante (EXCLUDE, INCLUDE y ENDPOINT) y un cliente de notificaciones de Windows (pycaw). Imprime un
evento por línea (dispositivo añadido o quitado, cambio del dispositivo por defecto, `started`/`stopped`/`rerouted` de miniaudio,
fallos y reaperturas del vigilante) y cada segundo una línea de estado:

```text
[  23.00s] EXCLUDE 100p/s ext:SI | INCLUDE 100p/s propio:SI | ENDPOINT 100p/s ext:SI propio:SI | REPROD  50cb/s | defecto: Altavoces (Logitech G733 ...
```

Guion (los avisos salen en pantalla): 0–20 s no tocar nada; **20 s: desconectar** los auriculares (apagar el G733 o quitar el
receptor USB); **50 s: conectarlos** de nuevo; **80 s (opcional): cambiar a mano el dispositivo de salida por defecto** (Win+Ctrl+V)
y volver al original; dejar correr hasta el final. Se puede repetir con otra forma de desconectar.

Hipótesis a verificar (no medidas): la reproducción de miniaudio sigue al nuevo dispositivo por defecto (`rerouted`) o se detiene
(`stopped`) si no queda ninguno; la captura por proceso no está atada al dispositivo (debería seguir oyendo al emisor externo); el
ENDPOINT muere con `AUDCLNT_E_DEVICE_INVALIDATED` y el vigilante lo reabre. Al terminar imprime un resumen con la línea temporal y los
tiempos de recuperación y guarda `resultados/t3_manual_<fecha>.json`: basta con pegar el resumen en la conversación.

## Ficheros

| Fichero | Para qué |
|---|---|
| `pyproject.toml`, `uv.lock`, `ruff.toml` | Proyecto uv del spike (Python 3.12, versiones fijadas) y lint mínimo (pyflakes) |
| `audio_spike/loopback.py` | Plan A: subclase de pyminiaudio (falla con PID; funciona sin PID) |
| `audio_spike/loopback_ctypes.py` | **Plan B: process loopback con ctypes/comtypes** (la pieza reutilizable) |
| `audio_spike/relleno.py` | Propuesta de relleno por reloj y su simulador/autoprueba |
| `audio_spike/vigilante.py` | Prototipo de vigilante de captura y reproducción |
| `audio_spike/analisis.py` | Detección de tonos por pico espectral relativo (base del autotest) |
| `audio_spike/tonos.py` | Generación de tonos y `ReproductorTonos` (`PlaybackDevice` por defecto con notificaciones) |
| `audio_spike/procesos.py`, `banco.py`, `registro.py`, `modos.py` | Banco de pruebas: cadenas de padres, procesos externos, capturas simultáneas, registro de paquetes |
| `tone_worker.py` | Trabajador de tonos (hijo, nieto o externo por UDP) |
| `diagnostico_subclase.py`, `t1_autoexclusion.py`, `t1b_arbol.py`, `t1c_pid_objetivo_muere.py`, `t4_silencio.py`, `t5_niveles.py`, `t9_latencia.py`, `reproduccion.py`, `captura_bajo_gil.py` | Pruebas (ver «Cómo reproducir») |
| `probar_cambio_dispositivo.py` | T3, **manual** |
| `resultados/*.json` | Resultados de las ejecuciones citadas aquí (unos 160 KB en total, sin audio) |
