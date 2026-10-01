---

description: "Lista de tareas de la feature 001-espina-dorsal"
---

# Tasks: Espina dorsal del intérprete simultáneo (inglés → español)

**Input**: Design documents from `/specs/001-espina-dorsal/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (pipeline.md, cli.md, tts-service.md, informe.md), quickstart.md

**Tests**: TDD, porque lo exige la constitución (Principio V).
- Cada tarea de implementación incluye sus tests unitarios y de contrato **escritos primero y en rojo**, con dobles y sin hardware.
- Los tests que necesitan GPU, modelos o dispositivos reales llevan el marcador `gpu`, `model` o `device`. Solo los ejecuta el orquestador, de uno en uno.

**Organization**: tareas agrupadas por historia (US1 directo, US2 archivo, US3 preparación y voces). El reparto en olas de como máximo 3 obreros con ficheros disjuntos está al final («Plan de olas»).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Núcleo: `src/instanttraductor/` y `tests/` en la raíz.
- Servicio de voz: `engines/tts-qwen3/`, proyecto uv propio.
- Los spikes de `spikes/` son **código de referencia para portar**, no producto. Se citan en cada tarea.
- Rutas de datos: `%LOCALAPPDATA%\InstantTraductor\{models,bin,voices,logs,informes}` y `%APPDATA%\InstantTraductor\ajustes.toml`. Ninguna va dentro del repo.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure. Lo hace el orquestador, en secuencia.

- [ ] T001 Crear `pyproject.toml` del núcleo:
  - proyecto uv, paquete `instanttraductor` con layout `src/`, `requires-python = "==3.12.*"` y `.python-version` con `3.12`;
  - script de consola `instanttraductor = "instanttraductor.cli:main"`;
  - dependencias fijadas según plan.md y research.md: `numpy`, `comtypes`, `miniaudio==1.71`, `pycaw`, `soxr`, `audiostretchy`, `onnxruntime>=1.30`, `sherpa-onnx==1.13.8`, `sherpa-onnx-core==1.13.8` (explícito, R5), `httpx`, `huggingface_hub`, `rich`, `tomli-w` y `psutil`;
  - grupo `dev` con `pytest`, `pytest-timeout` y `ruff`;
  - generar `uv.lock` con `uv lock` y comprobar `uv sync`.
- [ ] T002 Configurar ruff y pytest en `pyproject.toml` (depends on T001):
  - ruff: `line-length = 110`, `target-version = "py312"`, `select = ["E","F","W","I","B","UP","SIM"]`, `exclude = ["spikes", "engines"]`;
  - pytest: `testpaths = ["tests"]`, marcadores `gpu`, `model` y `device` con descripción, `addopts = "-q -m 'not gpu and not model and not device'"` y `timeout = 60`.
- [ ] T003 Crear la estructura de paquetes (depends on T001):
  - `src/instanttraductor/__init__.py` con `__version__ = "0.1.0"`;
  - `src/instanttraductor/__main__.py`, que llama a `cli.main()`;
  - subpaquetes vacíos con `__init__.py`: `contracts`, `platform`, `audio`, `vad`, `asr`, `pipeline`, `mt`, `tts`, `metrics`, `setup` y `ui`;
  - `tests/{fakes,fixtures,contract,unit,integration}/` con `__init__.py` y un `tests/conftest.py` raíz que fije `INSTANTTRADUCTOR_HOME` a un directorio temporal en cada test.
- [ ] T004 Fixtures de audio en `tests/fixtures/` (depends on T003):
  - generador `tests/fixtures/generar_fixtures.py`, que produce:
    - `tono_1k_1s.wav` y `silencio_3s.wav` (16 kHz, mono, float32);
    - `ruido_rosa_5s.wav`;
    - `dialogo_en_2min.wav`: concatenación de enunciados del dataset `hf-internal-testing/librispeech_asr_dummy` (LibriSpeech, CC BY 4.0) con pausas de 0,8 s, y su transcripción en `dialogo_en_2min.txt`;
  - todos los ficheros < 5 MB;
  - `tests/fixtures/ATTRIBUTION.md` con la atribución de LibriSpeech.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: contratos, reloj, ajustes, procesos hijos, manifiesto y dobles. Es todo lo que comparten las historias.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. Esta fase termina con el tag `contratos-001-v1` (T012).

- [ ] T005 Implementar los contratos en `src/instanttraductor/contracts/` (depends on T003):
  - módulos `clock.py`, `errors.py`, `audio.py`, `speech.py`, `units.py`, `translation.py`, `synthesis.py`, `scheduling.py`, `metrics.py` y `__init__.py`, que reexporta todo;
  - **exactamente** como en `specs/001-espina-dorsal/contracts/pipeline.md`: mismos nombres, campos, valores por defecto, `@dataclass(frozen=True, slots=True)`, `StrEnum` y `Protocol`;
  - implementar las propiedades `AudioChunk.duration`, `AudioChunk.t_end` y `StageTimings.sentence_delay` (None si falta `play_started_at`);
  - `EngineError(message, *, engine, recoverable=True)`;
  - tests en `tests/unit/contracts/test_dataclasses.py`: inmutabilidad, propiedades y valores por defecto.
- [ ] T006 [P] Relojes en `src/instanttraductor/pipeline/clock.py` (depends on T005):
  - `SessionClock`: `time.monotonic()` desde la creación, no decreciente;
  - `ManualClock`: `set(t)`, `advance(dt)`, seguro entre hilos y sin permitir retroceder;
  - tests en `tests/unit/pipeline/test_clock.py`.
- [ ] T007 [P] Ajustes y rutas en `src/instanttraductor/config.py` (depends on T003):
  - dataclass `Settings` con las claves, los valores por defecto y los rangos de la tabla «Ajustes» de `data-model.md`:
    - `volumen_voz` 0,0–2,0;
    - `umbral_resumir_s` > `umbral_acelerar_s` y `umbral_descartar_s` > `umbral_resumir_s`;
    - `velocidad_max` 1,0–1,5;
    - `max_habla_sin_traducir_s` 2–15;
    - `frases_de_contexto` 0–8;
  - `load_settings()` y `save_settings()` en TOML (`tomllib` + `tomli-w`) en `%APPDATA%\InstantTraductor\ajustes.toml`. Un valor fuera de rango produce `logging.warning` y se usa el valor por defecto;
  - `AppPaths` con `home` = `%LOCALAPPDATA%\InstantTraductor` (o `INSTANTTRADUCTOR_HOME` si está definida) y las subcarpetas `models`, `bin`, `voices`, `logs` e `informes`, creadas bajo demanda;
  - tests en `tests/unit/test_config.py`.
- [ ] T008 [P] Procesos hijos en `src/instanttraductor/platform/windows.py` (depends on T003):
  - con ctypes: `create_kill_on_close_job()`, que crea un Job Object con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`;
  - `launch_child(args, *, env=None, cwd=None) -> subprocess.Popen`: `CREATE_NO_WINDOW`, stdout y stderr en tubería, y el proceso se asigna al job (singleton del proceso);
  - `windows_build() -> int`;
  - tests en `tests/unit/platform/test_windows.py`: lanzar un `python -c "import time; time.sleep(60)"` hijo, cerrar el handle del job y comprobar que el hijo muere en ≤ 2 s.
- [ ] T009 [P] Manifiesto de componentes en `src/instanttraductor/setup/manifest.py` (depends on T007):
  - dataclass `Component` con los campos de «Componente» de `data-model.md`: `component_id` ASCII único, `name`, `version`, `kind` (`binario|modelo|entorno|voz`), `source_url` + `revision` fijados (sin «latest»), `sha256`, `size_bytes`, `license` obligatoria, `path` bajo `AppPaths.home`;
  - lista `COMPONENTS` con:
    - llama.cpp b11146 (`llama-b11146-bin-win-cuda-13.4-x64.zip` y `cudart-llama-bin-win-cuda-13.4-x64.zip`);
    - `Hy-MT2-7B-Q4_K_M.gguf` y `Hy-MT2-1.8B-Q8_0.gguf`;
    - el modelo Nemotron Speech Streaming EN int8 de sherpa-onnx;
    - `silero_vad.onnx` 6.2.3;
    - Qwen3-TTS-12Hz-0.6B-Base (repo y revisión de HF);
    - ffmpeg essentials (opcional);
  - las URL, los sha256 y los tamaños se copian de `spikes/traduccion/download.py`, `spikes/asr/fetch_assets.py` y `spikes/voz/common/descargar_modelos.py`;
  - función `component_path(component_id)`;
  - tests en `tests/unit/setup/test_manifest.py`: ids únicos, licencia no vacía, rutas bajo `home` y ningún «latest».
- [ ] T010 Dobles de todos los contratos en `tests/fakes/` (depends on T005, T006):
  - `fake_audio.py`:
    - `FakeAudioSource` (desde un array o un WAV, en chunks contiguos de 20 ms, con `exhausted`);
    - `FakeAudioSink` (registra los `SpeechPiece` y emite STARTED/FINISHED/CANCELLED con un `ManualClock`, duración = muestras/48 000);
  - `fake_speech.py`: `FakeVad` (por energía, con umbral) y `FakeAsrEngine` (guion de eventos por tiempo);
  - `fake_translation.py`: `FakeTranslator` (determinista: `"ES: " + texto`; en CONCISE recorta a la mitad de palabras; latencia configurable con el reloj);
  - `fake_synthesis.py`: `FakeSynthesizer` (tono de 50 ms por palabra a 24 kHz, en trozos de 100 ms, con `is_last` al final);
  - `fake_scheduling.py`: `ScriptedDelayController`;
  - `__init__.py`.
- [ ] T011 Suites de contrato reutilizables en `tests/contract/` (depends on T010):
  - `test_audio_contract.py`, `test_speech_contract.py`, `test_units_contract.py`, `test_translation_contract.py`, `test_synthesis_contract.py` y `test_scheduling_contract.py`;
  - cada una define una clase base `XxxContract` con un fixture abstracto `make_impl` y los tests de la sección «Tests de contrato obligatorios» de `contracts/pipeline.md`;
  - una subclase `TestXxxFake` la concreta con el doble de T010;
  - la suite del segmentador queda como clase base: la concreta T018.
- [ ] T012 Cerrar Foundational (depends on T005, T006, T007, T008, T009, T010, T011):
  - `uv run pytest` y `uv run ruff check .` en verde;
  - commit y **tag `contratos-001-v1`**, y push de la rama y del tag.
  - Desde aquí, cambiar `src/instanttraductor/contracts/**` exige un ADR (constitución, Principio III).
- [ ] T013 Preparación manual de desarrollo (depends on T009): `scripts/dev_colocar_componentes.py`, solo para el orquestador.
  - Copia o enlaza en las rutas de `component_path()` los componentes que los spikes ya descargaron en `%LOCALAPPDATA%\InstantTraductor\` y en la caché de HF: llama.cpp b11146, los GGUF 7B y 1.8B, Nemotron, `silero_vad.onnx` y Qwen3-TTS.
  - Coloca la voz masculina de referencia de S1 (`spikes\voz\ref\ref_es_es_24k.wav` + JSON con `ref_text` y origen LibriVox) en `voices\es-m-tux.*`.
  - Verifica los sha256.

**Checkpoint**: contratos congelados (`contratos-001-v1`) y componentes en su sitio. Las historias pueden empezar en paralelo.

---

## Phase 3: User Story 1 - Oír en español lo que suena en el PC (Priority: P1) 🎯 MVP

**Goal**: modo directo. Capta todo el sonido del PC salvo el propio; reconoce, segmenta y traduce al español de España; sintetiza con una voz castellana y la reproduce encima del original. Control de retraso (acelerar, resumir, descartar), autotest y monitor de eco, informe al detener.

**Independent Test**: quickstart §5–§8 y §10. Con un vídeo en inglés: frases en español con un retardo p50 ≤ 3 s y p95 ≤ 5 s, 0 ecos, parada en ≤ 2 s sin procesos huérfanos.

### Tests for User Story 1

> Los tests unitarios y de contrato de cada componente van dentro de su tarea (primero en rojo). Aquí están las pruebas de extremo a extremo.

- [ ] T032 [US1] E2E del directo con dobles en `tests/integration/test_pipeline_fakes.py`, sin marcadores (depends on T029):
  - `LiveSession` con `FakeAudioSource` (fixture `dialogo_en_2min.wav`), `FakeVad`, `FakeAsrEngine` con guion, `FakeTranslator`, `FakeSynthesizer` y `FakeAudioSink`;
  - verifica:
    - orden FIFO de `unit_id` y ninguna frase repetida (FR-008);
    - nada pronunciado durante el silencio (FR-009);
    - activación de acelerar, resumir y descartar con latencias inyectadas (FR-012–FR-014);
    - informe generado con el esquema de `contracts/informe.md`;
    - `stop()` en ≤ 2 s.
- [ ] T033 [US1] Validación en el PC (orquestador; `device`, `gpu` y `model`) (depends on T031, T013):
  - quickstart §5 (directo + Ctrl+C + `tasklist`), §6 (10 min de silencio), §7 (30 min, `echo_events = 0`), §8 (60 min de estabilidad) y §10 (cambio de dispositivo con el humano);
  - resultados con cifras en `specs/001-espina-dorsal/validacion.md`.

### Implementation for User Story 1

**Ola 1, obrero A: captura**
- [ ] T014 [P] [US1] Captura en `src/instanttraductor/audio/wasapi_capture.py`: `ProcessLoopbackSource`, que implementa `AudioSource`. Se porta `spikes/audio/audio_spike/loopback_ctypes.py`, `relleno.py` y `vigilante.py` (depends on T012).
  - `ActivateAudioInterfaceAsync` en modo PROCESS_LOOPBACK, con `include=False` (EXCLUDE, por defecto) o `include=True` (para el control positivo del autotest), sobre `target_pid=os.getpid()`.
  - Formato: 16 kHz, mono, float32. `sys.coinit_flags = 0` antes de importar comtypes.
  - Chunks contiguos (`t_start` encadenado).
  - Relleno con ceros **solo** de huecos de más de 100 ms, resincronizando con la hora de llegada.
  - Vigilante que reabre (como máximo una vez cada 10 s y avisa) si:
    - pasan más de 0,5 s sin paquetes;
    - hay un error de WASAPI;
    - el PID objetivo ya no es el del proceso.
  - Primero los tests: `tests/unit/audio/test_wasapi_capture.py` (relleno y vigilante con llegadas simuladas, sin dispositivo) y `tests/integration/test_capture_device.py` (marcador `device`: suite `AudioSourceContract` y un tono propio que no aparece).
- [ ] T015 [P] [US1] AGC en `src/instanttraductor/audio/agc.py` (depends on T012):
  - `AutoGain.process(chunk) -> AudioChunk`;
  - objetivo de −20 dBFS RMS en tramos con voz, ataque de 50 ms y relajación de 1 s, ganancia máxima de +30 dB;
  - nunca amplifica el silencio digital;
  - `source_silent_for_s` para el aviso de «sin audio del origen» (> 10 s de ceros);
  - tests en `tests/unit/audio/test_agc.py`.

**Ola 1, obrero B: escucha**
- [ ] T016 [P] [US1] VAD en `src/instanttraductor/vad/silero.py`: `SileroVad`, que implementa `Vad`. Se porta `spikes/asr/asrspike/vad.py` (depends on T012).
  - `.onnx` desde `component_path("silero-vad")`, ejecutado con `onnxruntime` en CPU (sin el paquete `silero-vad`);
  - `threshold` 0,5, salida 0,35, `min_silence_ms` 500 y `speech_pad_ms` 150;
  - función de probabilidad inyectable para los tests;
  - tests de la máquina de estados en `tests/unit/vad/test_silero.py` con probabilidades inyectadas;
  - `tests/integration/test_silero_model.py` (marcador `model`): suite `VadContract` con fixtures reales.
- [ ] T017 [P] [US1] ASR en `src/instanttraductor/asr/sherpa_streaming.py`: `NemotronStreamingAsr`, que implementa `AsrEngine`. Se porta `spikes/asr/asrspike/engine_a.py` (depends on T012).
  - sherpa-onnx `OnlineRecognizer`, con el modelo de `component_path("nemotron-en")`, trozo de 560 ms, 2 hilos y `blank_penalty=1.0`;
  - **un stream nuevo por tramo**; `flush()` cierra el tramo y emite FINAL si había texto;
  - PARTIAL con `revision` creciente y `stable_len` hasta la última palabra completa; tiempos en el reloj de audio; `emitted_at` del `Clock`;
  - `AsrCapabilities(native_streaming=True, partials=True, punctuation=True, word_timestamps=False, languages={"en"}, device="cpu", est_vram_mb=0)`;
  - tests en `tests/unit/asr/test_sherpa_streaming.py` con un *recognizer* falso;
  - `tests/integration/test_nemotron_model.py` (marcador `model`): suite `AsrEngineContract` y WER < 10 % sobre `dialogo_en_2min.wav`.
- [ ] T018 [P] [US1] Segmentador en `src/instanttraductor/pipeline/segmenter.py`: `PauseClauseSegmenter`, que implementa `Segmenter` según research.md R6 (depends on T012).
  - Cierra la unidad con `SPEECH_END` + FINAL.
  - Con habla larga, corta en una coma estable o en una conjunción (*and, but, because, so, which, when, while, if*) si el fragmento tiene ≥ 6 palabras.
  - Corte forzado al superar `max_untranslated_s` (6 s) en la última palabra completa estable.
  - Solo texto estable, sin solapes ni repeticiones. `t_end` por proporción de caracteres si no hay `words`.
  - Tests en `tests/unit/pipeline/test_segmenter.py` y subclase concreta de `SegmenterContract`.

**Ola 1, obrero C: traducción**
- [ ] T019 [P] [US1] Servidor de traducción en `src/instanttraductor/mt/llama_server.py` (depends on T012). Se porta `spikes/traduccion/llama_server.py` y `gpu_info.py`.
  - `LlamaServerProcess(model_path)` con `platform.windows.launch_child`, puerto libre en 127.0.0.1 y los argumentos `-m`, `-ngl 99`, `--cache-ram 0`, `-c 4096`;
  - espera a `/health` hasta 30 s; `health()`, `stop()` y como máximo un reinicio;
  - en `src/instanttraductor/mt/selection.py`:
    - `free_vram_mb()` (nvidia-smi);
    - `choose_mt_model(free_mb)`: el 7B si la VRAM libre tras cargar la voz es ≥ 5 200 + 1 024 MiB; si no, el 1.8B si es ≥ 2 300 + 1 024 MiB; si no, `EngineError(recoverable=False)` (ADR-0011);
  - tests en `tests/unit/mt/test_llama_server.py` (proceso falso) y `tests/unit/mt/test_selection.py`.
- [ ] T020 [P] [US1] Traductor en `src/instanttraductor/mt/hymt2.py`: `HyMt2Translator`, que implementa `Translator`. Se porta `spikes/traduccion/prompts.py` y `client.py` (depends on T012).
  - ***Prompt*:**
    - contexto como turnos de chat (las N previas de `request.context`);
    - los 12 ejemplos fijos en castellano de S2;
    - cada turno envuelto en la instrucción de traducir;
    - glosario (el del usuario + el base filtrado por las palabras de la frase) con la plantilla *Terminology* en chino;
    - `cache_prompt: true`.
  - **Modo CONCISE:** plantilla *Style* «telegraphic Spanish… at most N words», con N = ceil(0,7 × las palabras de la traducción esperada, estimada como 1,15 × las palabras del original).
  - **Filtros:** vacía, sin caracteres latinos, longitud > 3× la del original o eco del *prompt* → `rejected=True`.
  - **Glosario base** `src/instanttraductor/mt/glossary_es.toml`, con ≥ 150 pares inglés → español de España: juice→zumo, fridge→nevera, parking lot→aparcamiento, computer→ordenador, cell phone→móvil, car→coche, popcorn→palomitas, okay→vale…
  - **Tests:**
    - `tests/unit/mt/test_hymt2.py` con `httpx.MockTransport`, más la subclase de `TranslatorContract`;
    - `tests/integration/test_hymt2_model.py` (marcadores `gpu` y `model`): el corpus de 65 frases de `spikes/traduccion/corpus.py` da 0 salidas que no son traducción y, con el 7B, el modo CONCISE reduce las palabras ≥ 20 %.

**Ola 2, obrero D: reproducción, autotest y eco**
- [ ] T021 [P] [US1] Reproducción en `src/instanttraductor/audio/wasapi_playback.py`: `DeviceSink`, que implementa `AudioSink`. Se porta `spikes/audio/reproduccion.py` y el gancho de `notificationCallback` (depends on T012).
  - `miniaudio.PlaybackDevice` sin `device_id`, 48 kHz, float32, estéreo (la voz mono se duplica), periodos de 20 ms × 3;
  - sigue los cambios de dispositivo (`rerouted`) y avisa de `stopped`;
  - unidades en FIFO; STARTED y FINISHED con el `Clock`; `set_volume` 0,0–2,0 solo sobre nuestra voz; `pending_seconds`; `stop()` corta en seco y emite CANCELLED;
  - tests en `tests/unit/audio/test_wasapi_playback.py` con un *backend* falso;
  - `tests/integration/test_playback_device.py` (marcador `device`): suite `AudioSinkContract`.
- [ ] T022 [US1] Autotest y monitor de eco (depends on T014, T021):
  - `src/instanttraductor/audio/selftest.py`: `run_echo_selftest(sink, make_source)`. Tono de 0,3 s a 1234 Hz y −30 dBFS por el `DeviceSink`. Debe NO aparecer en una captura EXCLUDE y SÍ en una INCLUDE temporal. La detección se porta de `spikes/audio/audio_spike/analisis.py`. Devuelve `SelftestResult(ok, motivo, umbral_correlacion)`;
  - `src/instanttraductor/audio/echo_monitor.py`: `EchoMonitor` (research.md R14). Correlación cruzada de envolventes (50 Hz) entre lo reproducido y lo captado, en una ventana de 2 s, con el umbral de la calibración del autotest; contador `echo_events` y aviso;
  - tests en `tests/unit/audio/test_echo_monitor.py` (señales sintéticas con y sin eco);
  - `tests/integration/test_selftest_device.py` (marcador `device`).

**Ola 2, obrero E: voz**
- [ ] T023 [P] [US1] Servicio de voz en `engines/tts-qwen3/` (depends on T012). Se porta `spikes/voz/qwen3/bench_qwen3.py` y `spikes/voz/common/vozbench.py`.
  - **`pyproject.toml`:**
    - Python 3.12, `torch==2.11.0+cu130` (índice de PyTorch cu130), `transformers==5.15.1`, `faster-qwen3-tts==0.5.3`, `fastapi`, `uvicorn`, `numpy`, `soundfile`;
    - script de consola `tts-service = "tts_service.server:main"`.
  - **`src/tts_service/engine.py`:**
    - carga Qwen3-TTS-12Hz-0.6B-Base, `warmup()` y captura de CUDA graphs;
    - voces de `--voices-dir` (`<id>.wav` + `<id>.json` con `ref_text`), con el *prompt* ICL en caché y `x_vector_only` de rescate;
    - `chunk_size=4`; *streaming* de PCM float32 a 24 kHz.
  - **`src/tts_service/server.py`:** API **exacta** de `specs/001-espina-dorsal/contracts/tts-service.md` (línea `ready` en stdout, `/health`, `/voices`, `/synthesize` en *streaming*, `/shutdown`, solo 127.0.0.1).
  - **Tests:**
    - `engines/tts-qwen3/tests/test_server.py` con un motor falso, sin GPU;
    - `engines/tts-qwen3/tests/test_engine_gpu.py` (marcadores `gpu` y `model`): primer audio p95 ≤ 0,6 s y VRAM ≤ 3,5 GB.
- [ ] T024 [P] [US1] Cliente del servicio de voz en `src/instanttraductor/tts/` (depends on T012):
  - `service_process.py`: `TtsServiceProcess`. Lanza con `launch_child` `uv run --project engines/tts-qwen3 tts-service --host 127.0.0.1 --port 0 --voices-dir <AppPaths.voices> --models-dir <AppPaths.models>`. Lee la línea `ready` (hasta 120 s), `health()`, `stop()` (`POST /shutdown` y `terminate` a los 2 s) y como máximo un reinicio;
  - `http_client.py`: `HttpSynthesizer`, que implementa `Synthesizer`. *Streaming* con httpx; conserva el resto cuando un bloque no es múltiplo de 4 bytes; lee `X-Sample-Rate`; 4xx/5xx → `EngineError`; `supports_speed=False`; `list_voices()` desde `/voices`;
  - tests en `tests/unit/tts/test_http_client.py` (`httpx.MockTransport` + suite `SynthesizerContract`) y `tests/unit/tts/test_service_process.py` (proceso falso que imprime `ready`).
- [ ] T025 [P] [US1] DSP en `src/instanttraductor/audio/dsp.py` (depends on T012):
  - `StreamResampler(src_rate, dst_rate)` con soxr y estado entre trozos;
  - `StreamTimeStretch(speed)` con TDHS (`audiostretchy`), factor exacto entre 1,0 y 1,5, cambiable entre unidades. Se porta `spikes/voz/velocidad_postproceso.py`;
  - tests en `tests/unit/audio/test_dsp.py`: relación de duración dentro del 2 %, sin NaN y continuidad entre trozos.

**Ola 2, obrero F: planificador, retraso y métricas**
- [ ] T026 [P] [US1] Política de retraso en `src/instanttraductor/pipeline/delay.py`: `ThresholdDelayController`, que implementa `DelayController` (depends on T012).
  - `speed` sube de forma lineal de 1,0 (con lag = `accelerate_after_s`) a `max_speed` (con lag = `concise_after_s`);
  - `mode=CONCISE` cuando lag > `concise_after_s` a velocidad máxima, y se mantiene (histéresis) hasta que lag < `accelerate_after_s`;
  - `drop_oldest_pending=True` solo si lag > `drop_after_s`;
  - tests en `tests/unit/pipeline/test_delay.py` y subclase de `DelayControllerContract`.
- [ ] T027 [US1] Planificador en `src/instanttraductor/pipeline/scheduler.py`: `Scheduler` (depends on T026).
  - Implementa los estados de «Frase» de `data-model.md` (PENDIENTE → TRADUCIENDO → SINTETIZANDO → EN_COLA → SONANDO → PRONUNCIADA, DESCARTADA o FALLIDA) en orden FIFO.
  - `lag = clock.now() − t_end` de la frase más antigua no terminada.
  - Construye las peticiones:
    - `TranslationRequest`: contexto de las últimas `frases_de_contexto` frases **pronunciadas**, glosario y `mode` de la `DelayDecision`;
    - `SynthesisRequest`: `speed`.
  - Aplica los descartes con `sink.cancel_pending()`.
  - Actualiza `StageTimings` con los `PlaybackEvent`.
  - Produce `UtteranceRecord` al cerrar cada frase.
  - Tests en `tests/unit/pipeline/test_scheduler.py` con dobles y `ManualClock`.
- [ ] T028 [P] [US1] Métricas e informe en `src/instanttraductor/metrics/` (depends on T012):
  - `recorder.py`: `MetricsRecorder`, que acumula `UtteranceRecord` y `diagnostics`: `startup_s`, `rss_mb_min5` y `rss_mb_end` (psutil), `echo_events`, `component_restarts` y `underruns`;
  - `report.py`: `build_report()`, `write_json()` y `write_markdown()`, con el esquema exacto de `contracts/informe.md` (`schema_version: 1`, percentiles p50 y p95 solo sobre las pronunciadas, 3 decimales) y el Markdown con la tabla, los recuentos, las 10 más lentas y los avisos;
  - tests en `tests/unit/metrics/test_report.py`, con un JSON de referencia de una sesión sintética.

**Ola 3, obrero I: interfaz de terminal**
- [ ] T030 [P] [US1] Interfaz en `src/instanttraductor/ui/terminal.py` (depends on T012):
  - `StatusSnapshot` (dataclass definida aquí: estado `escuchando|traduciendo|hablando|parado`, `lag_s`, `velocidad`, `modo`, `avisos`, `ultima_original`, `ultima_traduccion`);
  - `TerminalUI` con `rich.live.Live`: `update(snapshot)`, `show_summary(report)` y teclas por `msvcrt`, sin bloquear (`+` y `-` = ±10 % de volumen, `t` = mostrar u ocultar el texto, `q` = salir) mediante *callbacks*;
  - tests en `tests/unit/ui/test_terminal.py`, con el renderizado a texto.

**Integración (orquestador)**
- [ ] T029 [US1] Sesión en directo en `src/instanttraductor/pipeline/session.py`: `LiveSession` (depends on T014–T028).
  - **Arranque, ≤ 60 s:** servicio de voz → elección del modelo de traducción por VRAM (T019) → `llama-server` → calentamiento → autotest de eco (si falla, código 4).
  - **Hilos y colas acotadas:** captura → AGC → VAD/ASR → segmentador → planificador → traducción → voz → *time-stretch* y remuestreo a 48 kHz → sink. En paralelo, el monitor de eco.
  - **Fallos:** reinicio de un componente que falla, una sola vez; si no se recupera, parada limpia.
  - **Parada en ≤ 2 s:** `sink.stop()`, `/shutdown` y cierre del job.
  - Al terminar, el informe en `AppPaths.informes`.
- [ ] T031 [US1] Línea de comandos (depends on T029, T030):
  - `src/instanttraductor/cli.py` con `main()` (argparse);
  - subcomando `directo` con las opciones `--voz`, `--volumen`, `--mostrar-texto` e `--informe`, y los códigos de salida de `contracts/cli.md`;
  - `logging` a fichero rotativo en `AppPaths.logs` (sin audio, FR-030);
  - `src/instanttraductor/__main__.py`.

**Checkpoint**: el modo directo funciona por sí solo y con datos medidos (T033).

---

## Phase 4: User Story 2 - Traducir un fichero y medir el resultado (Priority: P2)

**Goal**: modo archivo. A partir de un fichero en inglés, y sin dispositivos, genera la pista en español alineada, la mezcla, la transcripción, la traducción y el informe.

**Independent Test**: quickstart §4. Un clip de 2 min produce las salidas de `contracts/informe.md`; un fichero dañado sale con código 5 y sin salidas a medias; un fichero sin habla deja la pista en silencio.

### Tests for User Story 2

- [ ] T037 [US2] E2E del modo archivo con dobles en `tests/integration/test_file_mode_fakes.py`, sin marcadores (depends on T036):
  - `dialogo_en_2min.wav` produce `voz_es.wav` (misma duración), `mezcla.wav`, `transcripcion.srt/.json`, `traduccion.srt/.json` e `informe.json/.md` válidos;
  - un fichero dañado sale con el código 5 y no deja la carpeta de salida;
  - `silencio_3s.wav` deja la pista en silencio y el informe dice «no se detectó habla».
- [ ] T038 [US2] Validación de quickstart §4 con los motores reales (orquestador; `gpu` y `model`) (depends on T036, T013): resultados en `specs/001-espina-dorsal/validacion.md`.

### Implementation for User Story 2

**Ola 3, obrero G: modo archivo**
- [ ] T034 [P] [US2] Fuente de fichero en `src/instanttraductor/audio/file_source.py`: `FileSource`, que implementa `AudioSource` (depends on T012).
  - `ffmpeg -i <entrada> -ac 1 -ar 16000 -f f32le -` por tubería, a **ritmo real** (espera hasta `t_start` en el `Clock`);
  - chunks contiguos de 20 ms y `exhausted` al terminar;
  - fichero inexistente, dañado o sin audio → `InputFileError` (código 5);
  - tests en `tests/unit/audio/test_file_source.py` con los fixtures y la suite `AudioSourceContract`.
- [ ] T035 [P] [US2] Salidas del modo archivo (depends on T012):
  - `src/instanttraductor/audio/file_sink.py`: `TimelineSink`, que implementa `AudioSink`. Coloca cada unidad en el instante del `Clock` en que «empieza a sonar», respetando FIFO y sin solapes (si llega tarde, va tras la anterior), y emite los eventos;
  - `src/instanttraductor/audio/file_outputs.py`. Escribe en una carpeta temporal y la mueve de forma atómica al final:
    - `voz_es.wav`: 48 kHz, mono, float32, con la duración de la entrada;
    - `mezcla.wav`: 48 kHz, estéreo, 16 bits, con ffmpeg `amix` + limitador;
    - `mezcla.mkv`: solo si la entrada tiene vídeo. Vídeo copiado; pista 1 = mezcla, pista 2 = original;
    - `transcripcion.srt/.json` y `traduccion.srt/.json`, con el formato de `contracts/informe.md`;
  - tests en `tests/unit/audio/test_file_sink.py` y `tests/unit/audio/test_file_outputs.py`.

**Integración (orquestador)**
- [ ] T036 [US2] Sesión de fichero (depends on T029, T031, T034, T035):
  - `FileSession` en `src/instanttraductor/pipeline/session.py`, que reutiliza el *pipeline* con `FileSource` + `TimelineSink`, sin autotest ni monitor de eco;
  - subcomando `archivo ENTRADA [--salida DIR] [--voz ID]` en `src/instanttraductor/cli.py`, con salida por defecto `<carpeta de ENTRADA>\<nombre>_es\` y código 5 para la entrada no válida.

**Checkpoint**: las historias 1 y 2 funcionan cada una por su lado.

---

## Phase 5: User Story 3 - Preparar el equipo y elegir la voz (Priority: P3)

**Goal**: `preparar` deja todo listo en una sola ejecución, sin cuentas ni pagos, y muestra las licencias; `voces` permite escuchar al menos 3 voces castellanas (femeninas y masculinas) y elegir una.

**Independent Test**: quickstart §2 y §3. Una segunda ejecución de `preparar` no descarga nada; el humano escucha las voces y elige.

### Tests for User Story 3

- [ ] T042 [US3] Validación de quickstart §2 y §3 en el PC (orquestador; red y `device`) (depends on T041): el humano escucha las voces y elige (SC-009). Resultados en `specs/001-espina-dorsal/validacion.md`.

### Implementation for User Story 3

**Ola 3, obrero H: preparación y voces**
- [ ] T039 [P] [US3] Instalador en `src/instanttraductor/setup/installer.py` (depends on T012).
  - **Comprobaciones previas** (si falla alguna, código 6): build ≥ 20348 (`windows_build()`), GPU NVIDIA y driver (nvidia-smi), espacio libre ≥ lo que falta + 2 GB y ffmpeg (si falta, descarga gyan.dev *essentials* a `AppPaths.bin`).
  - **Descargas idempotentes:**
    - `huggingface_hub.hf_hub_download(revision=fija)` para los modelos de HF;
    - httpx en *streaming* + descompresión para los zip de GitHub;
    - verificación sha256. Estados: `ausente` → `descargado` → `verificado` | `corrupto` (un corrupto se vuelve a descargar).
  - **Entorno de la voz:** `uv sync --project engines/tts-qwen3`.
  - **Tabla `rich`:** nombre, versión, licencia, tamaño y estado.
  - **`--comprobar`:** solo verifica.
  - **Tests:** `tests/unit/setup/test_installer.py`, con un descargador falso y `home` temporal: la segunda ejecución no descarga nada.
- [ ] T040 [P] [US3] Voces castellanas en `src/instanttraductor/setup/voices.py` (depends on T009).
  - **Catálogo de ≥ 3 voces:**
    - `es-m-tux`: la de S1, LibriVox «Trafalgar», lector Tux;
    - **al menos 2 femeninas castellanas de dominio público**. Hay que buscar en LibriVox lectoras de España con grabación limpia y anotar la URL del MP3, la lectora y el minuto exacto (de 6 a 10 s de habla continua).
  - **`ref_text`:** el texto exacto, verificado contra la fuente (Gutenberg o similar).
  - **Preparación:** descarga desde archive.org, recorte con ffmpeg, mono a 24 kHz, normalización a −23 LUFS. Escribe `<AppPaths.voices>/<id>.wav` + `<id>.json` (campos de `VoiceInfo` + `ref_text` + `source` + `license: dominio público`).
  - **Indicio de acento:** se guarda en el JSON con el método de `spikes/voz/common/distincion.py` (fricativa de ce/ci/z más débil que la de /s/).
  - **Voz por defecto:** la primera femenina.
  - **Tests:** `tests/unit/setup/test_voices.py`, que comprueba el catálogo (ids ASCII únicos, al menos 1 de cada género, licencia).

**Integración (orquestador)**
- [ ] T041 [US3] Subcomandos en `src/instanttraductor/cli.py` (depends on T031, T039, T040):
  - `preparar [--comprobar]`, que además genera las muestras de las voces con el servicio de voz;
  - `voces [--escuchar [ID]] [--elegir ID]`: escucha con `DeviceSink`; la elección se guarda en los ajustes;
  - `diagnostico`: versiones, GPU y VRAM libre, dispositivos, rutas y estado de la preparación.

**Checkpoint**: las tres historias funcionan por su cuenta.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: calidad, documentación y cierre de la feature.

- [ ] T043 [P] Actualizar `README.md` con la instalación y el uso en español (`preparar`, `voces`, `directo`, `archivo`), los requisitos y la nota de licencias (depends on T041).
- [ ] T044 Conjunto de calidad para SC-004 (depends on T038):
  - `tests/fixtures/calidad/generar_calidad.py` sintetiza en inglés 50 de las 65 frases de `spikes/traduccion/corpus.py` con Qwen3-TTS y una referencia inglesa de LibriVox de dominio público, con pausas;
  - se pasa `archivo` y el humano revisa `traduccion.srt` (objetivo: ≥ 85 % buenas);
  - resultados en `specs/001-espina-dorsal/validacion.md`.
- [ ] T045 Convergencia y revisión (depends on T033, T038, T042, T044):
  - `/speckit-converge` hasta «Converged»;
  - agente `revisor` sobre `main..001-espina-dorsal` (Opus por ser la feature base);
  - corregir los hallazgos GRAVE y MEDIO.
- [ ] T046 Cerrar la feature (depends on T045):
  - skill `registrar-hito` (bitácora, CHANGELOG `0.1.0` y hoja de ruta con la 001 hecha);
  - PR y merge a main;
  - tag `v0.1.0`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 → T002, T003 → T004.
- **Foundational (Phase 2)**: depende de Setup y bloquea todas las historias. Termina con T012 (tag `contratos-001-v1`); T013 prepara los componentes para los tests con modelo.
- **US1 (Phase 3)**: tras T012. Las olas 1 y 2 en paralelo dentro de cada ola; integración en T029 → T031 → T032 y T033.
- **US2 (Phase 4)**: T034 y T035 tras T012 (en paralelo con US1); la integración (T036) necesita T029 y T031.
- **US3 (Phase 5)**: T039 y T040 tras T012/T009; la integración (T041) necesita T031.
- **Polish (Phase 6)**: tras las validaciones T033, T038 y T042.

### User Story Dependencies

- **US1 (P1)**: solo depende de Foundational. Es el MVP.
- **US2 (P2)**: sus componentes (T034, T035) son independientes. Para la sesión reutiliza el *pipeline* de US1 (T029).
- **US3 (P3)**: independiente. US1 y US2 pueden probarse con la preparación manual (T013).

### Within Each User Story

- En cada tarea, los tests se escriben primero y deben FALLAR antes de implementar.
- Componentes (olas) → integración (orquestador) → validación en el PC.
- Commits por hito (ver `.claude/agents/obrero.md`).

### Parallel Opportunities

- Foundational: T006, T007, T008 y T009 en paralelo una vez hecho T005 (T009 tras T007).
- US1: las tareas [P] de cada ola tocan ficheros disjuntos.
- US2 y US3: sus componentes (T034, T035, T039 y T040) no dependen de US1 y caben en la ola 3.

---

## Parallel Example: User Story 1

```text
# Ola 1 (tras el tag contratos-001-v1), tres obreros en paralelo:
Task: "Obrero A — T014 + T015: captura (wasapi_capture.py) y AGC (agc.py)"
Task: "Obrero B — T016 + T017 + T018: VAD (silero.py), ASR (sherpa_streaming.py) y segmentador (segmenter.py)"
Task: "Obrero C — T019 + T020: llama_server.py + selection.py y hymt2.py + glossary_es.toml"

# Ola 2, tres obreros en paralelo:
Task: "Obrero D — T021 + T022: wasapi_playback.py, selftest.py y echo_monitor.py"
Task: "Obrero E — T023 + T024 + T025: engines/tts-qwen3, tts/ y dsp.py"
Task: "Obrero F — T026 + T027 + T028: delay.py, scheduler.py y metrics/"

# Ola 3, tres obreros + orquestador:
Task: "Obrero G — T034 + T035: file_source.py, file_sink.py y file_outputs.py (US2)"
Task: "Obrero H — T039 + T040: installer.py y voices.py, con las voces femeninas castellanas (US3)"
Task: "Obrero I — T030: ui/terminal.py"
Orquestador: T029 → T031 → T032 (y T036 y T041 cuando lleguen G y H)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Setup (T001–T004) y Foundational (T005–T013), con el tag `contratos-001-v1`.
2. Olas 1 y 2 → integración T029–T032 → **validación T033 en el PC**.
3. **STOP and VALIDATE:** se oye en español con las métricas de la spec.

### Incremental Delivery

1. Cimientos → US1 (MVP, en directo) → US2 (modo archivo y conjunto de calidad) → US3 (preparación y voces) → cierre (T043–T046, `v0.1.0`).
2. Cada historia se valida por separado (T033, T038, T042) antes de dar la feature por cerrada.

### Plan de olas (máximo 3 obreros a la vez)

| Ola | Obreros | Tareas | Tests que ejecuta luego el orquestador |
|---|---|---|---|
| 1 | A, B, C | T014–T015 · T016–T018 · T019–T020 | `device` (T014), `model` (T016, T017), `gpu`+`model` (T020) |
| 2 | D, E, F | T021–T022 · T023–T025 · T026–T028 | `device` (T021, T022), `gpu`+`model` (T023) |
| 3 | G, H, I | T034–T035 · T039–T040 · T030 | — |
| Integración | orquestador | T029, T031, T032, T036, T037, T041 | E2E con dobles |
| Validación | orquestador + humano | T033, T038, T042, T044 | en el PC |

---

## Notes

- [P] tasks = different files, no dependencies.
- Cada brief de obrero lleva alcance mínimo, tiempo límite e hitos con commit (ADR-0002, actualización).
- Solo el orquestador toca `pyproject.toml`, `uv.lock`, `src/instanttraductor/contracts/**`, `pipeline/session.py`, `cli.py`, `specs/**` y `docs/**`. Si un obrero necesita una dependencia nueva, termina con `NEEDS_CONTEXT`.
- Los obreros no ejecutan tests `gpu`, `model` ni `device`, ni descargan modelos: el orquestador lo hace al integrar.
