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
- **ADR:** aprobada por el humano como ADR-0010 (2026-10-01), que sustituye en parte a ADR-0005.

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
- **Decisión:**
  - **VAD:** Silero VAD 6.2.3 con el `.onnx` ejecutado con `onnxruntime` en CPU. El paquete `silero-vad` no se usa porque arrastra torch. Parámetros iniciales: `threshold` 0,5, salida 0,35, `min_silence_ms` 500 y `speech_pad_ms` 150.
  - **ASR:** NVIDIA Nemotron Speech Streaming EN 0.6B int8 sobre sherpa-onnx 1.13.8, en CPU:
    - trozo de 560 ms, 2 hilos, `blank_penalty` 1;
    - VAD + vaciado + **stream nuevo por tramo**, sin el *endpoint* nativo de sherpa;
    - **`sherpa-onnx-core` declarado explícitamente** en el `pyproject`: uv lo pierde en Windows y entonces carga el `onnxruntime.dll` 1.17 de System32;
    - `onnxruntime` (pip) y el ORT 1.28 de sherpa conviven en el mismo proceso.
  - **Alternativa y referencia de calidad:** faster-whisper 1.2.1 + CTranslate2 4.8.2 con `large-v3-turbo` FP16 en GPU, que funciona en sm_120. Para ja/zh, en la spec 004.
- **Motivo (medido en tiempo real, 594 s de LibriSpeech, en este PC):**
  - **Nemotron 560 ms:** final p50/p95 de 0,67/0,78 s desde el fin del habla, WER 5,05 % (3,86 % en habla continua), RTF 0,15, 0,4 núcleos de CPU, 850 MB de RAM y 0 de VRAM; sin deriva en 10 min.
  - **Parciales:** solo añaden texto (0 retractaciones en 2811 cambios). En el 15–21 % de los casos terminan a mitad de palabra, así que `stable_len` llega hasta la última palabra completa.
  - **faster-whisper:** final 0,71/0,82 s y WER 5,82 % con cortes a 5 s (3,42 % con enunciados enteros), 2,3 GB de VRAM y sin parciales.
- **Alternativas:**
  - Nemotron con trozos de 160 ms: solo gana 0,34 s en el primer parcial, con más CPU y peor WER.
  - *Endpoint* nativo de sherpa: WER 11,3 %.
  - Whisper como principal: sin parciales y con más VRAM.

## R6. Segmentación en unidades de traducción
- **Decisión:**
  - **Fin de frase por pausa:** una unidad se cierra con el `SPEECH_END` del VAD (silencio ≥ 500 ms) y el FINAL del ASR. Nemotron casi nunca pone punto final (1 % de los finales), así que no se usa la puntuación para cerrar frases.
  - **Frases largas:** si el habla sigue, se corta en una coma estable (Nemotron da unas 3,5 comas por cada 100 palabras con `blank_penalty` 1) o en una conjunción (*and, but, because, so, which, when, while, if*), siempre que el fragmento tenga al menos 6 palabras.
  - **Corte forzado:** en la última palabra completa estable si se superan `max_habla_sin_traducir_s` (6 s).
  - Solo se emite texto estable (hasta la última palabra completa); nada se retracta.
  - Sin tiempos por palabra, `t_end` se estima por la proporción de caracteres.
- **Motivo:**
  - Clarificación 2 de la spec.
  - Spike S3: puntuación final poco fiable y parciales que solo añaden texto.
  - El LLM traduce mejor fragmentos con sentido que trozos de N palabras.
- **Alternativas:**
  - *wait-k*: no encaja con un traductor que no se reentrena.
  - Retraducir parciales: lo prohíbe FR-008 (no repetir lo ya pronunciado).

## R7. Traducción — spike S2 y medición del 7B (ADR-0011)
- **Decisión:**
  - **Motor:**
    - Hy-MT2-7B Q4_K_M en `llama-server` (llama.cpp **b11146**, release v0.5.0, zips `llama-b11146-bin-win-cuda-13.4-x64.zip` + `cudart-llama-bin-win-cuda-13.4-x64.zip`, sm_120 nativo), con `--cache-ram 0` y todas las capas en GPU;
    - **reserva automática** a Hy-MT2-1.8B Q8_0 si al arrancar no hay VRAM libre para el 7B y la voz con un margen de 1 GB.
  - **_Prompt_** (el de S2, `spikes/traduccion/prompts.py`):
    - contexto como turnos de chat (4 frases previas);
    - 12 ejemplos previos en castellano, fijos (la caché de *prompt* los reutiliza);
    - cada turno envuelto en la instrucción de traducir;
    - glosario con la plantilla *Terminology* en chino;
    - glosario base de léxico de España incorporado (unos 150 pares), filtrado por frase.
  - **Modo resumen (FR-013, solo con el 7B):** plantilla *Style* «telegraphic Spanish… at most N words», con N = ceil(0,6 × las palabras del original), que es la configuración medida en S2 (−33 %).
  - **Filtros de salida:** traducción vacía, idioma distinto del español, longitud anómala (más de 3 veces el original) y eco del *prompt*. Si saltan, `rejected=True` y la frase no se pronuncia.
- **Motivo (medido):**
  - **7B:** p50/p95 de 211/347 ms con caché (sin caché, 344/497 ms); primer token 43/83 ms; 5,2 GB de VRAM; arranque de 2,1 s; glosario 10/10.
  - **Modo resumen del 7B:** −32 % de palabras, conservando el sentido en 8 de 10 frases y en 246 ms.
  - **1.8B:** 145/218 ms y 2,3 GB, pero no resume y tiene ~20 % de errores de sentido.
  - En ninguno tiene efecto la cláusula de estilo; el glosario sí (léxico de España de 9/16 a 14/16).
  - 0 muletillas en 4075 salidas.
- **Alternativas:**
  - Solo el 1.8B: ver ADR-0011.
  - SalamandraTA, EuroLLM, Qwen3.5 y TranslateGemma: se comparan en la spec 002.
- **Riesgos:**
  - **RAM:** la de `llama-server` creció de 2,3 a 4,2 GB en una medición larga; se vigila en la prueba de estabilidad (SC-005).
  - **Contención** de GPU con la voz.

## R8. Voz — spike S1 y escucha del humano (ADR-0008, resolución)
- **Decisión:**
  - **Motor y versiones:**
    - Qwen3-TTS-12Hz-0.6B-Base + faster-qwen3-tts 0.5.3 en un proyecto uv propio (`engines/tts-qwen3/`);
    - torch 2.11.0+cu130 (con sm_120);
    - **transformers fijado a 5.15.1**, porque la 5.18 rompe qwen-tts.
  - **Ajustes:**
    - `chunk_size` 4;
    - modo ICL con `ref_text` de la referencia (guardado en el JSON de la voz) y `x_vector_only` de rescate;
    - `warmup()` y captura de CUDA graphs al arrancar.
  - **Voces:**
    - por defecto, **una femenina castellana**;
    - la masculina de LibriVox («Trafalgar» de Galdós, lector Tux, dominio público) suena a España según el humano;
    - se buscarán ≥ 2 referencias femeninas castellanas de dominio público (LibriVox) y se validarán como en S1.
- **Motivo (medido):**
  - Primer audio p50/p95 de 179/182 ms (`chunk_size` 4); RTF 0,37; 3,3 GB de VRAM.
  - Carga de 6,1 s + 0,84 s de grafos; en frío, sin calentar, 1,42 s.
  - El humano la eligió al escuchar las muestras.
- **Medición del servicio integrado (2026-10-01, GPU libre):** primer audio p50/p95 de 222/283 ms, RTF 0,45 y VRAM de 3,8 GB con el contexto CUDA (el límite del contrato pasa a 4 GB). Con la GPU compartida (otro proceso al 88 %) el RTF sube a 0,67. Mejora para la spec 002: bajar la VRAM (`max_seq_len`, grafos capturados).
- **Alternativas:**
  - Chatterbox es-ES: primer audio de 748 ms y RTF en *streaming* de 1,12; solo cumpliría con menos pasos CFM y pérdida de calidad.
  - XTTS-v2 o Piper como último recurso.

## R9. Velocidad de habla (acelerar hasta 1,25×) — spike S1
- **Decisión:** *time-stretch* en el núcleo sobre el PCM en *streaming*, con **TDHS** (biblioteca C `stretch` vía `audiostretchy`, familia de Sonic). Se aplica por trozo antes de remuestrear a 48 kHz. `Synthesizer.supports_speed = False` para Qwen3-TTS.
- **Motivo:**
  - Ningún motor tiene parámetro de velocidad: el `instruct` de Qwen3 da entre 0,89× y 1,76×, sin control.
  - El *time-stretch* da un factor exacto con 3–4 ms de CPU por segundo de audio y 28–46 ms de retardo algorítmico.
  - No cambia el tiempo hasta el primer audio.
- **Alternativas:**
  - WSOLA (audiotsm, NumPy): válido, algo más de CPU.
  - Rubber Band: GPL y binario externo.

## R10. Procesos hijos y ciclo de vida
- **Decisión:**
  - `llama-server` y el servicio de voz se lanzan con `subprocess.Popen`, sin consola.
  - Se asignan a un *Job Object* con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (ctypes, `platform/windows.py`).
  - Una clase común, `ManagedChild` (`platform/children.py`), se encarga de:
    - esperar a que esté listo: `/health` o la línea `ready`;
    - comprobar la salud cada 2 s;
    - reiniciarlo como máximo una vez por sesión.
  - **Parada en ≤ 2 s en total:**
    - `POST /shutdown` a todos los hijos **en paralelo**, con 1 s de gracia;
    - después se cierra el *Job Object*, que mata lo que quede de inmediato.
  - **Sin red tras la preparación (FR-027):**
    - el servicio de voz se lanza con `uv run --frozen --offline --project engines/tts-qwen3`;
    - se le pasan `HF_HUB_OFFLINE=1` y `TRANSFORMERS_OFFLINE=1`.
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
  - Manifiesto con URL, revisión fijada, licencia y **lista de ficheros** (ruta, sha256 y tamaño) de cada componente.
  - **Hugging Face:** `snapshot_download(repo_id, revision=<hash de commit>, allow_patterns=…)` para los repos con varios ficheros (Qwen3-TTS).
  - **GitHub:** `httpx` para las releases (llama.cpp, sherpa-onnx), con comprobación de espacio previa.
  - Los hashes y las revisiones se calculan una vez a partir de las descargas verificadas de los spikes (T013).
  - **Las voces van empaquetadas en la app** (`src/instanttraductor/setup/voices/`: diseñadas con VoxCPM2, Apache-2.0; VoxPopuli, CC0; LibriVox, dominio público), así que no se descargan y funcionan sin red.
  - ffmpeg portable (gyan.dev *essentials*, GPL) si falta.
  - El entorno del servicio de voz se crea con `uv sync --project engines/tts-<motor>`.
- **Motivo:** FR-025 a FR-027 y SC-008.
- **Alternativas:** instaladores del sistema (winget): necesitan permisos y no son reproducibles.

## R13. Interfaz de terminal, ajustes y registro
- **Decisión:**
  - **Interfaz:** `rich` (Live) para el estado. Las teclas `+ - t q` se leen con `msvcrt` en `platform/windows.py` (`read_key_nonblocking()`) y se inyectan en la interfaz, para mantener el código de Windows aislado (Principio VII).
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
| Voces de referencia (LibriVox) | Dominio público | Lector y minuto anotados en el JSON de la voz |
| audiostretchy / stretch (TDHS) | BSD-3 (por verificar al fijar la versión) | |
| Hy-MT2-7B | Apache-2.0 | `LICENSE.txt` estándar, verificado el 2026-10-01 (T013) |
