# Research: 001-espina-dorsal

Decisiones de la fase 0 del plan. Formato: **Decisión** · **Motivo** · **Alternativas**. Fuentes:
- informes de `docs/investigacion/` (2026-09-30);
- spikes medidos en el PC del usuario (`spikes/`, 2026-10-01).

## R1. Núcleo en Python 3.12 con uv
- **Decisión:** núcleo en CPython 3.12, gestionado con uv (uv instala la 3.12.x en el ámbito del usuario). Cada motor con dependencias de PyTorch o CUDA va en su propio proyecto uv (ADR-0004).
- **Motivo:** compatibilidad de ruedas en Windows. Los spikes S3 y S4 funcionaron con 3.12.14 sin incidencias.
- **Alternativas:** 3.13 (instalada en el sistema): varias ruedas de ML no la cubren aún o están sin verificar.

## R2. Captura: *process loopback* propio (ctypes/comtypes) — spike S4
- **Decisión:**
  - Captura con `ActivateAudioInterfaceAsync` en modo `PROCESS_LOOPBACK` + `EXCLUDE_TARGET_PROCESS_TREE`, implementada con ctypes/comtypes. La base es `spikes/audio/audio_spike/loopback_ctypes.py`.
  - Formato pedido: 16 kHz, mono, float32, sin remuestrear en el núcleo.
  - **PID objetivo = `os.getpid()` del núcleo, que capta y reproduce en el mismo proceso.**
  - `sys.coinit_flags = 0` (COM en MTA) antes de importar comtypes o pycaw.
- **Motivo (medido):**
  - La subclase de pyminiaudio falla (`MA_INVALID_ARGS`: miniaudio 0.11.25 llama a `GetDevice("VAD\Process_Loopback")`).
  - El plan B en Python activa la captura en 0,2–3 ms, entrega paquetes de 10 ms, usa el 0,8 % de un núcleo y no pierde datos con el GIL ocupado.
  - **Windows solo excluye el PID objetivo y sus hijos directos, no los nietos.** El redirector `python.exe` de un venv deja al intérprete real a dos niveles.
- **Consecuencias para el diseño:**
  - Ningún otro proceso reproduce audio (los motores devuelven PCM).
  - **Vigilante** con cuatro condiciones: sin paquetes durante más de 0,5 s, error de WASAPI, PID objetivo muerto o cambiado (si muere, la captura sigue pero deja de excluir: fallo silencioso, T1c) y reproducción detenida.
  - **Autotest** al arrancar: tono de 0,3 s muy bajo que NO debe aparecer en la captura EXCLUDE y SÍ en una captura INCLUDE temporal (control positivo).
- **Alternativas:**
  - pyminiaudio para captar: no funciona.
  - *Sidecar* NAudio: innecesario. Queda como opción si hiciera falta aislar el audio del GIL.
  - Loopback del dispositivo completo: recaptura nuestra voz. Solo como diagnóstico.
- **Pendiente en la ADR:** la corrección de ADR-0005 se consulta al humano (ADR-0009). Mientras tanto, rige esta decisión técnica.

## R3. Silencio, reloj y niveles — spike S4
- **Decisión:**
  - **Reloj de audio:** recuento de muestras (`n/16000`), con una red de seguridad que rellena con ceros los huecos de más de 100 ms y se resincroniza con la hora de llegada. Los sellos QPC no se usan.
  - **Niveles:** AGC de margen amplio antes del VAD y del ASR. Aviso de «sin audio del origen» si llega silencio digital sostenido (app silenciada o al 0 %).
- **Motivo (medido):**
  - En *process loopback* llegan 100 paquetes/s de ceros aunque no suene nada (300 s, 0 huecos, deriva 0 ppm); los sellos QPC son sintéticos.
  - El volumen de sesión de la app de origen escala el nivel captado de forma lineal (−6,4 dB al 50 %, silenciada = ceros) y el nivel absoluto varía hasta 17 dB entre fuentes.
- **Alternativas:** relleno continuo por reloj (recortaba audio real con *jitter*: descartado en el spike).

## R4. Reproducción — spike S4
- **Decisión:**
  - `miniaudio.PlaybackDevice` sin `device_id` (sigue al dispositivo por defecto), 48 kHz, float32, estéreo (la voz mono se duplica).
  - **Periodo mínimo de 20 ms × 3** (60 ms de búfer).
  - Gancho de `notificationCallback` (copia adaptada de `PlaybackDevice.__init__`) para enterarse de `rerouted` y `stopped`.
- **Motivo:**
  - Abre en 21–41 ms en el G733.
  - Con 10 ms × 2 se pierde audio en cuanto el GIL se ocupa; con 20 ms × 3 sale limpio.
  - Windows convierte frecuencias y canales sin problema.
- **Riesgo:** no se ha medido con la carga real de ML. Si aparecen cortes, la E/S de audio pasa a un proceso hijo dedicado, que capta y reproduce, con PID objetivo = él mismo. El informe cuenta los *underruns*.

## R5. VAD y ASR — spike S3
- **Decisión:** _pendiente del cierre de S3_. Hipótesis de partida (ADR-0006):
  - Silero VAD 6.2 en CPU;
  - Nemotron Speech Streaming EN 0.6B en sherpa-onnx, CPU int8;
  - faster-whisper turbo FP16 como alternativa.
- **Motivo:** _por completar con las cifras de S3_.
- **Alternativas:** _por completar_.

## R6. Segmentación en unidades de traducción
- **Decisión:**
  - **Frases cortas:** una unidad por oración, cuando el texto estable termina en `. ? !`.
  - **Frases largas:** se corta en el límite de cláusula estable (`, ; :` y conjunciones *and, but, because, so, which, when, while, if*) cuando el fragmento tiene al menos 6 palabras.
  - **Corte forzado:** en el último límite de palabra estable si se superan `max_habla_sin_traducir_s` (6 s).
  - Solo se emite texto estable (`stable_len`); nada se retracta.
  - Sin tiempos por palabra, `t_end` se estima por la proporción de caracteres.
- **Motivo:** clarificación 2 de la spec, y equilibrio entre retardo y naturalidad. El LLM traduce mejor fragmentos con sentido que trozos de N palabras.
- **Alternativas:**
  - *wait-k*: no encaja con un traductor que no se reentrena.
  - Retraducir parciales: lo prohíbe FR-008 (no repetir lo ya pronunciado).

## R7. Traducción — spike S2
- **Decisión:** _pendiente del cierre de S2_. Hipótesis de partida (ADR-0007):
  - Hy-MT2-1.8B Q8_0 con `llama-server`;
  - plantillas de contexto, glosario y estilo;
  - modo resumen para FR-013.
- **Motivo:** _por completar con las cifras de S2_ (latencia, versión de llama.cpp y *prompt* final).
- **Alternativas:** _por completar_.

## R8. Voz — spike S1 y escucha del humano
- **Decisión:** _pendiente del cierre de S1 y de la elección del humano_ entre Qwen3-TTS-0.6B y Chatterbox es-es (ADR-0008).
- **Motivo:** _por completar_.
- **Alternativas:** XTTS-v2, o Piper es_ES en CPU como último recurso.

## R9. Velocidad de habla (acelerar hasta 1,25×)
- **Decisión:** si el motor elegido acepta la velocidad de forma nativa con buena calidad, se le pasa en `SynthesisRequest.speed`. Si no, el núcleo aplica *time-stretch* (WSOLA) por unidad antes de encolarla. _Se confirma con S1._
- **Motivo:** la aceleración solo se usa cuando hay retraso; entonces importa más recuperar el ritmo que el primer audio.
- **Alternativas:** Rubber Band (GPL, binario externo): más calidad, pero más dependencias.

## R10. Procesos hijos y ciclo de vida
- **Decisión:**
  - `llama-server` y el servicio de voz se lanzan con `subprocess.Popen`, sin consola.
  - Se asignan a un *Job Object* con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (ctypes, `platform/windows.py`).
  - Arranque: se espera `/health` o la línea `ready`.
  - Salud: cada 2 s; un reinicio como máximo por sesión.
  - Parada: `POST /shutdown` y, a los 2 s, `terminate`.
- **Motivo:** FR-015 y FR-018 (sin procesos huérfanos aunque el núcleo muera).
- **Alternativas:** `atexit` y señales: no cubren que el proceso muera de golpe.

## R11. Modo archivo
- **Decisión:**
  - Decodificar con `ffmpeg` (CLI) a PCM float32 a 16 kHz mono por tubería, a ritmo real.
  - `TimelineSink` coloca cada frase en su `play_started_at` sobre una pista de la duración del original.
  - Mezcla y `mezcla.mkv` con `ffmpeg` (vídeo copiado sin recodificar).
  - Escritura en una carpeta temporal y movimiento atómico al final.
- **Motivo:** FR-019 a FR-022. ffmpeg admite todos los formatos. A ritmo real, las métricas son comparables con el directo.
- **Alternativas:** PyAV (ruedas grandes y empaquetado más frágil); reloj simulado acelerado (no garantiza métricas comparables; podrá añadirse después).

## R12. Preparación
- **Decisión:**
  - Manifiesto con URL, revisión fijada, sha256, tamaño y licencia de cada componente.
  - Descargas con `huggingface_hub` (revisión fijada) o `httpx` (releases de GitHub), con comprobación de espacio previa.
  - ffmpeg portable (gyan.dev *essentials*, GPL) si falta.
  - El entorno del servicio de voz se crea con `uv sync --project engines/tts-<motor>`.
- **Motivo:** FR-025 a FR-027 y SC-008.
- **Alternativas:** instaladores del sistema (winget): necesitan permisos y no son reproducibles.

## R13. Interfaz de terminal, ajustes y registro
- **Decisión:**
  - **Interfaz:** `rich` (Live) para el estado, y `msvcrt` para las teclas `+ - t q`.
  - **Ajustes:** TOML (`tomllib` + `tomli-w`).
  - **Registro:** `logging` a fichero rotativo en `%LOCALAPPDATA%\InstantTraductor\logs\`, sin audio.
- **Motivo:** dependencias mínimas y Windows nativo.
- **Alternativas:** Typer y Textual: más dependencias y nada imprescindible.

## R14. Monitor de eco (SC-002)
- **Decisión:** correlación cruzada continua entre la envolvente de la voz reproducida y la de la captura, con una ventana de 2 s y el umbral calibrado en el autotest. Cada detección suma 1 a `diagnostics.echo_events` y lanza un aviso.
- **Motivo:** hace medible «0 ecos en 30 min» y detecta en tiempo real el fallo silencioso T1c.
- **Alternativas:** confiar solo en el autotest de arranque (no cubre los cambios a mitad de sesión).

## R15. Pruebas
- **Decisión:**
  - pytest con los marcadores `gpu`, `model` y `device` excluidos por defecto (`addopts`).
  - Dobles de todos los contratos en `tests/fakes/`.
  - `ManualClock` para la lógica temporal.
  - Fixtures WAV pequeños: tonos, silencio y habla de LibriSpeech (CC BY 4.0, con atribución).
- **Motivo:** constitución, Principio V.

## R20. Licencias de los componentes (uso personal)
| Componente | Licencia | Notas |
|---|---|---|
| Captura propia (ctypes/comtypes) | — / MIT (comtypes) | |
| pyminiaudio | MIT | |
| pycaw | MIT | |
| numpy | BSD-3 | |
| soxr | LGPL-2.1 | |
| onnxruntime | MIT | |
| Silero VAD | MIT | |
| sherpa-onnx | Apache-2.0 | |
| Nemotron Speech Streaming EN | NVIDIA Open Model License | Condiciones propias; anotada |
| faster-whisper | MIT | |
| Whisper | MIT | |
| llama.cpp | MIT | |
| Hy-MT2-1.8B | Apache-2.0 | Verificado 2026-09-30 |
| Qwen3-TTS | Apache-2.0 | |
| faster-qwen3-tts | MIT | |
| Chatterbox | MIT | Marca de agua PerTh |
| ffmpeg essentials | GPL | Binario aparte; uso personal |
| rich | MIT | |
| httpx | BSD-3 | |
| huggingface_hub | Apache-2.0 | |
| tomli-w | MIT | |
| Voces de referencia | _según R8_ | |
