---

description: "Lista de tareas de la feature 001-espina-dorsal"
---

# Tasks: Espina dorsal del intérprete simultáneo (inglés → español)

**Input**: Design documents from `/specs/001-espina-dorsal/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (pipeline.md, cli.md, tts-service.md, informe.md), quickstart.md

**Tests**: TDD, porque lo exige la constitución (Principio V).
- Cada tarea de implementación incluye sus tests unitarios y de contrato **escritos primero y en rojo**, con dobles y sin hardware.
- Los tests que necesitan GPU, modelos o dispositivos reales llevan el marcador `gpu`, `model` o `device`. Solo los ejecuta el orquestador, de uno en uno.

**Organization**: tareas agrupadas por historia (US1 directo, US2 archivo, US3 preparación y voces). El reparto en olas de como máximo 3 obreros con ficheros disjuntos está al final («Plan de olas»). Es la única fuente de ese reparto.

**Revisión:** incorpora las correcciones de `/speckit-analyze` del 2026-10-01 (C1, C2, H1–H6 y M1–M8).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Núcleo: `src/instanttraductor/` y `tests/` en la raíz.
- Servicio de voz: `engines/tts-qwen3/`, proyecto uv propio. Su `pyproject.toml` y su `uv.lock` son del orquestador.
- Utilidades del orquestador: `scripts/`.
- Los spikes de `spikes/` son **código de referencia para portar**, no producto. Se citan en cada tarea.
- Rutas de datos: `%LOCALAPPDATA%\InstantTraductor\{models,bin,voices,logs,informes}` y `%APPDATA%\InstantTraductor\ajustes.toml`. Ninguna va dentro del repo.
- Identificadores en inglés (CLAUDE.md). Solo las claves del TOML de ajustes, que ve el humano, van en español.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure. Lo hace el orquestador, en secuencia.

- [X] T001 Crear `pyproject.toml` del núcleo:
  - proyecto uv, paquete `instanttraductor` con layout `src/`, `requires-python = "==3.12.*"` y `.python-version` con `3.12`;
  - script de consola `instanttraductor = "instanttraductor.cli:main"`;
  - dependencias fijadas según plan.md y research.md: `numpy`, `comtypes`, `miniaudio==1.71`, `pycaw`, `soxr`, `audiostretchy`, `onnxruntime>=1.30`, `sherpa-onnx==1.13.8`, `sherpa-onnx-core==1.13.8` (explícito, R5), `httpx`, `huggingface_hub`, `rich`, `tomli-w` y `psutil`;
  - grupo `dev` con `pytest`, `pytest-timeout`, `ruff`, `soundfile` y `pyarrow` (estos dos, para generar fixtures);
  - generar `uv.lock` con `uv lock` y comprobar `uv sync`.
- [X] T002 Configurar ruff y pytest en `pyproject.toml` (depends on T001):
  - ruff: `line-length = 110`, `target-version = "py312"`, `select = ["E","F","W","I","B","UP","SIM"]`, `exclude = ["spikes", "engines"]`;
  - pytest: `testpaths = ["tests"]`, marcadores `gpu`, `model` y `device` con descripción, `addopts = "-q -m 'not gpu and not model and not device'"` y `timeout = 60`.
- [X] T003 Crear la estructura de paquetes (depends on T001):
  - `src/instanttraductor/__init__.py` con `__version__ = "0.1.0"`;
  - `src/instanttraductor/__main__.py`, que llama a `cli.main()` (esta tarea es la única dueña del fichero);
  - subpaquetes vacíos con `__init__.py`: `contracts`, `platform`, `audio`, `vad`, `asr`, `pipeline`, `mt`, `tts`, `metrics`, `setup` y `ui`;
  - **todos** los directorios de tests con `__init__.py`: `tests/`, `tests/fakes/`, `tests/fixtures/`, `tests/contract/`, `tests/integration/` y `tests/unit/{contracts,pipeline,audio,vad,asr,mt,tts,metrics,setup,ui,platform}/`;
  - `tests/conftest.py` raíz con un fixture `autouse` que fija `INSTANTTRADUCTOR_HOME` a un directorio temporal **salvo en los tests marcados `gpu`, `model` o `device`**, que usan los componentes reales.
- [X] T004 Fixtures de audio en `tests/fixtures/` (depends on T003):
  - generador `tests/fixtures/generate_fixtures.py`, que produce:
    - `tono_1k_1s.wav`, `silencio_3s.wav` y `ruido_rosa_5s.wav`;
    - `dialogo_en_2min.wav`: concatenación de enunciados de `hf-internal-testing/librispeech_asr_dummy` (LibriSpeech, CC BY 4.0) con pausas de 0,8 s, y su transcripción en `dialogo_en_2min.txt`;
  - todo en **WAV PCM de 16 bits**, 16 kHz y mono (el diálogo ocupa ~3,8 MB; cada fichero < 5 MB);
  - `tests/fixtures/ATTRIBUTION.md` con la atribución de LibriSpeech.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: contratos, reloj, ajustes, procesos hijos, manifiesto, entorno de la voz y dobles. Es todo lo que comparten las historias. Lo hace el orquestador, o un único obrero en secuencia.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. Esta fase termina con el tag `contratos-001-v1` (T014).

- [X] T005 Implementar los contratos en `src/instanttraductor/contracts/` (depends on T003):
  - módulos `clock.py`, `errors.py`, `audio.py`, `speech.py`, `units.py`, `translation.py`, `synthesis.py`, `scheduling.py`, `metrics.py` y `__init__.py`, que reexporta todo;
  - **exactamente** como en `specs/001-espina-dorsal/contracts/pipeline.md`, incluidos `Translator.supports_concise`, `DelayPolicy.allow_concise`, `StageTimings.captured_at` y `Outcome.REJECTED`;
  - implementar las propiedades `AudioChunk.duration`, `AudioChunk.t_end` y `StageTimings.sentence_delay` (None si falta `play_started_at`);
  - tests en `tests/unit/contracts/test_dataclasses.py`.
- [X] T006 [P] Relojes en `src/instanttraductor/pipeline/clock.py` (depends on T005):
  - `SessionClock`: origen al construirse, que la sesión hace **al arrancar la captura** (data-model); `time.monotonic()`, no decreciente;
  - `ManualClock`: `set(t)`, `advance(dt)`, seguro entre hilos y sin permitir retroceder;
  - tests en `tests/unit/pipeline/test_clock.py`.
- [X] T007 [P] Ajustes y rutas en `src/instanttraductor/config.py` (depends on T003):
  - dataclass `Settings` con **atributos en inglés** (`voice`, `voice_volume`, `accelerate_after_s`, `concise_after_s`, `drop_after_s`, `max_speed`, `max_untranslated_s`, `context_utterances`, `glossary`, `show_text`, `save_audio`) y la correspondencia con las claves en español del TOML de `data-model.md`;
  - rangos:
    - `volumen_voz` 0,0–2,0;
    - `umbral_resumir_s` > `umbral_acelerar_s` y `umbral_descartar_s` > `umbral_resumir_s`;
    - `velocidad_max` 1,0–1,5;
    - `max_habla_sin_traducir_s` 2–15;
    - `frases_de_contexto` 0–8;
  - `load_settings()` y `save_settings()` en `%APPDATA%\InstantTraductor\ajustes.toml`. Un valor fuera de rango produce `logging.warning` y se usa el valor por defecto;
  - `AppPaths`: `home` = `%LOCALAPPDATA%\InstantTraductor` o `INSTANTTRADUCTOR_HOME`, con las propiedades `models`, `bin`, `voices`, `logs` y `reports` (carpeta `informes`);
  - `ffmpeg_path()`: `AppPaths.bin/ffmpeg/bin/ffmpeg.exe` si existe; si no, el de PATH; si no, `None`;
  - tests en `tests/unit/test_config.py`.
- [X] T008 [P] Plataforma y procesos hijos (depends on T003):
  - `src/instanttraductor/platform/windows.py` (ctypes y msvcrt):
    - `create_kill_on_close_job()`, con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`;
    - `launch_child(args, *, env=None, cwd=None) -> subprocess.Popen`: `CREATE_NO_WINDOW`, tuberías y asignación al job (singleton);
    - `close_job()`;
    - `windows_build() -> int`;
    - `read_key_nonblocking() -> str | None` (msvcrt; **el único sitio del núcleo que lee teclas**);
  - `src/instanttraductor/platform/children.py`, clase `ManagedChild(args, *, env, ready, health)`:
    - `ready` puede ser «línea JSON en stdout» o «GET /health 200», con un tiempo máximo;
    - comprueba la salud cada 2 s y la notifica por *callback*;
    - `restart_once()`;
    - `stop_all(children, grace_s=1.0)` envía la parada ordenada a todos **en paralelo** y después cierra el job, todo en ≤ 2 s (R10);
  - tests en `tests/unit/platform/test_windows.py` (un `python -c "import time; time.sleep(60)"` hijo muere en ≤ 2 s al cerrar el job) y `tests/unit/platform/test_children.py` (hijos falsos que imprimen `ready` o no responden).
- [X] T009 [P] Manifiesto de componentes en `src/instanttraductor/setup/manifest.py` (depends on T007):
  - dataclasses `ComponentFile(rel_path, sha256, size_bytes)` y `Component`:
    - `component_id` ASCII único, `name`, `version`, `kind` (`binario|modelo|entorno|voz`), `license` obligatoria;
    - `source`: URL fijada, o `hf_repo_id` + `hf_revision` (hash de commit) + `allow_patterns`;
    - `files: tuple[ComponentFile, ...]`;
    - `install_dir` bajo `AppPaths.home`;
  - lista `COMPONENTS`:
    - llama.cpp b11146 (`llama-b11146-bin-win-cuda-13.4-x64.zip` y `cudart-llama-bin-win-cuda-13.4-x64.zip`);
    - `Hy-MT2-7B-Q4_K_M.gguf` y `Hy-MT2-1.8B-Q8_0.gguf`;
    - Nemotron Speech Streaming EN int8 (sherpa-onnx);
    - `silero_vad.onnx` 6.2.3;
    - Qwen3-TTS-12Hz-0.6B-Base (HF, varios ficheros);
    - ffmpeg essentials (opcional);
    - las voces (`kind="voz"`, se rellenan en T042);
  - las URL vienen de `spikes/traduccion/download.py`, `spikes/asr/fetch_assets.py` y `spikes/voz/common/descargar_modelos.py`. Los `sha256` y las revisiones que falten los rellena T013;
  - `component_dir(component_id)` y `is_installed(component_id)` (existen todos los ficheros con su tamaño);
  - tests en `tests/unit/setup/test_manifest.py`: ids únicos, licencia no vacía, rutas bajo `home` y ningún «latest».
- [X] T010 [P] Entorno del servicio de voz (C1, del orquestador) (depends on T003):
  - `engines/tts-qwen3/pyproject.toml` y `engines/tts-qwen3/uv.lock`, partiendo de `spikes/voz/qwen3/pyproject.toml` y su `uv.lock`;
  - Python 3.12, `torch==2.11.0+cu130` (índice cu130), `transformers==5.15.1`, `faster-qwen3-tts==0.5.3`, `fastapi`, `uvicorn`, `numpy` y `soundfile`; grupo `dev` con `pytest` y `ruff`; script `tts-service = "tts_service.server:main"`;
  - configuración propia de pytest (marcadores `gpu` y `model`, excluidos por defecto) y de ruff;
  - `engines/tts-qwen3/src/tts_service/__init__.py` y `engines/tts-qwen3/tests/__init__.py` vacíos;
  - comprobar `uv sync --project engines/tts-qwen3`.
- [X] T011 Dobles de todos los contratos en `tests/fakes/` (depends on T005, T006):
  - `fake_audio.py`: `FakeAudioSource` (array o WAV, chunks contiguos de 20 ms, `exhausted`) y `FakeAudioSink` (registra los `SpeechPiece` y emite STARTED/FINISHED/CANCELLED con un `ManualClock`, duración = muestras/48 000);
  - `fake_speech.py`: `FakeVad` (por energía) y `FakeAsrEngine` (guion de eventos por tiempo);
  - `fake_translation.py`: `FakeTranslator(supports_concise=True)` (determinista: `"ES: " + texto`; en CONCISE recorta a la mitad de palabras; latencia configurable y `fail_times` para simular fallos);
  - `fake_synthesis.py`: `FakeSynthesizer` (tono de 50 ms por palabra a 24 kHz, en trozos de 100 ms, con `is_last` al final);
  - `fake_scheduling.py`: `ScriptedDelayController`.
- [X] T012 Suites de contrato reutilizables en `tests/contract/` (depends on T011):
  - `test_audio_contract.py`, `test_speech_contract.py`, `test_units_contract.py`, `test_translation_contract.py`, `test_synthesis_contract.py` y `test_scheduling_contract.py`;
  - cada una define una clase base `XxxContract` con un fixture abstracto `make_impl` y los tests de la sección «Tests de contrato obligatorios» de `contracts/pipeline.md`;
  - una subclase `TestXxxFake` la concreta con el doble;
  - la suite del segmentador la concreta T020.
- [X] T013 Preparación manual de desarrollo (H6) en `scripts/dev_place_components.py`, del orquestador (depends on T009):
  - copia o enlaza en `component_dir()` los componentes que los spikes ya descargaron (en `%LOCALAPPDATA%\InstantTraductor\models` y `\bin`, y en la caché de HF): llama.cpp b11146, los GGUF 7B y 1.8B, Nemotron, `silero_vad.onnx` y Qwen3-TTS;
  - **calcula los sha256 y tamaños de todos los ficheros**, y saca la `hf_revision` de la carpeta del *snapshot* de la caché de HF;
  - **escribe esos valores en `manifest.py`**;
  - comprueba el `LICENSE` del 7B;
  - coloca la voz masculina de S1, `%LOCALAPPDATA%\InstantTraductor\spikes\voz\ref\ref_es_es_24k.wav`, como `voices\es-m-tux.wav` + `es-m-tux.json` (`ref_text`, origen LibriVox «Trafalgar», lector Tux, dominio público).
- [X] T014 Cerrar Foundational (depends on T005–T013):
  - `uv run pytest` y `uv run ruff check .` en verde;
  - commit y **tag `contratos-001-v1`**, y push de la rama y del tag.
  - Desde aquí, cambiar `src/instanttraductor/contracts/**` exige un ADR (Principio III).

**Checkpoint**: contratos congelados y componentes en su sitio. Las historias pueden empezar.

---

## Phase 3: User Story 1 - Oír en español lo que suena en el PC (Priority: P1) 🎯 MVP

**Goal**: modo directo. Capta todo el sonido del PC salvo el propio; reconoce, segmenta y traduce al español de España; sintetiza con una voz castellana y la reproduce encima del original. Control de retraso, autotest y monitor de eco, informe al detener.

**Independent Test**: quickstart §5–§8, §10 y §11. Frases en español con un retardo p50 ≤ 3 s y p95 ≤ 5 s, 0 ecos, 20 paradas en ≤ 2 s sin procesos huérfanos y funcionamiento sin red.

### Tests for User Story 1

> Los tests unitarios y de contrato de cada componente van dentro de su tarea (primero en rojo). Aquí están las pruebas de extremo a extremo.

- [ ] T033 [US1] E2E del directo con dobles en `tests/integration/test_pipeline_fakes.py`, sin marcadores (depends on T031):
  - `LiveSession` con `FakeAudioSource` (`dialogo_en_2min.wav`) y los dobles de VAD, ASR, traducción, voz y sink;
  - verifica:
    - orden FIFO, sin repeticiones (FR-008) y nada durante el silencio (FR-009);
    - acelerar, resumir y descartar con latencias inyectadas (FR-012–FR-014);
    - con `FakeTranslator(supports_concise=False)` nunca se pide CONCISE y se pasa a descartar;
    - un autotest que falla → código 4 (FR-003);
    - un motor que falla una vez se reinicia y, si falla dos, la parada es limpia (FR-018);
    - el informe cumple el esquema de `contracts/informe.md`;
    - `stop()` en ≤ 2 s.
- [ ] T034 [US1] Validación en el PC (orquestador; `device`, `gpu` y `model`) (depends on T032, T013):
  - `scripts/stop_test.py` (20 arranques y paradas con Ctrl+Break, midiendo el tiempo y los procesos hijos vivos, SC-006);
  - quickstart §5, §6, §7, §8, §10 (con el humano) y §11 (sin red);
  - resultados con cifras en `specs/001-espina-dorsal/validacion.md`.

### Implementation for User Story 1

**Ola 1, obrero A: captura, AGC e interfaz**
- [X] T015 [P] [US1] Captura en `src/instanttraductor/audio/wasapi_capture.py`: `ProcessLoopbackSource`, que implementa `AudioSource`. Se porta `spikes/audio/audio_spike/loopback_ctypes.py`, `relleno.py` y `vigilante.py` (depends on T014).
  - Modo PROCESS_LOOPBACK con `include=False` (EXCLUDE, por defecto) o `include=True` (control positivo del autotest), sobre `target_pid=os.getpid()`.
  - Formato: 16 kHz, mono, float32. `sys.coinit_flags = 0` antes de importar comtypes.
  - Chunks contiguos, con `captured_at` (hora de llegada en el reloj de sesión) disponible para las métricas.
  - Relleno solo de huecos de más de 100 ms, resincronizando con la hora de llegada.
  - Vigilante que reabre (como máximo una vez cada 10 s) y notifica con un *callback* `on_reopen` (la sesión repite el autotest), si:
    - pasan más de 0,5 s sin paquetes;
    - hay un error de WASAPI;
    - el PID objetivo ya no es el del proceso.
  - Tests: `tests/unit/audio/test_wasapi_capture.py` (relleno y vigilante simulados) y `tests/integration/test_capture_device.py` (marcador `device`: `AudioSourceContract` y un tono propio que no aparece).
- [X] T016 [P] [US1] AGC en `src/instanttraductor/audio/agc.py` (depends on T014):
  - `AutoGain.process(chunk) -> AudioChunk`;
  - objetivo de −20 dBFS RMS en voz, ataque de 50 ms y relajación de 1 s, máximo +30 dB;
  - nunca amplifica el silencio digital;
  - `source_silent_for_s` para el aviso de «sin audio del origen» (> 10 s de ceros);
  - tests en `tests/unit/audio/test_agc.py`.
- [X] T017 [P] [US1] Interfaz en `src/instanttraductor/ui/terminal.py` (C2) (depends on T014):
  - `StatusSnapshot` (dataclass: `state` `listening|translating|speaking|stopped`, `lag_s`, `speed`, `mode`, `warnings`, `last_source`, `last_translation`);
  - `TerminalUI(key_reader: Callable[[], str | None])`. **No importa msvcrt**: recibe `platform.windows.read_key_nonblocking`;
  - `rich.live.Live` con `update(snapshot)` y `show_summary(report)`;
  - las teclas `+` y `-` (±10 % de volumen), `t` (texto) y `q` (salir) se procesan por *callbacks*;
  - **todos los textos de la interfaz, en español**;
  - tests en `tests/unit/ui/test_terminal.py` (renderizado a texto y un lector de teclas falso).

**Ola 1, obrero B: escucha**
- [X] T018 [P] [US1] VAD en `src/instanttraductor/vad/silero.py`: `SileroVad`, que implementa `Vad`. Se porta `spikes/asr/asrspike/vad.py` (depends on T014).
  - `.onnx` de `component_dir("silero-vad")`, ejecutado con `onnxruntime` en CPU;
  - `threshold` 0,5, salida 0,35, `min_silence_ms` 500 y `speech_pad_ms` 150;
  - probabilidad inyectable para los tests;
  - tests en `tests/unit/vad/test_silero.py` y `tests/integration/test_silero_model.py` (marcador `model`, `VadContract`).
- [X] T019 [P] [US1] ASR en `src/instanttraductor/asr/sherpa_streaming.py`: `NemotronStreamingAsr`, que implementa `AsrEngine`. Se porta `spikes/asr/asrspike/engine_a.py` (depends on T014).
  - `OnlineRecognizer` con el modelo de `component_dir("nemotron-en")`, trozo de 560 ms, 2 hilos y `blank_penalty=1.0`;
  - un stream nuevo por tramo; `flush()` emite FINAL si había texto;
  - PARTIAL con `revision` creciente y `stable_len` hasta la última palabra completa; tiempos en el reloj de audio; `emitted_at` del `Clock`;
  - `AsrCapabilities(native_streaming=True, partials=True, punctuation=True, word_timestamps=False, languages={"en"}, device="cpu", est_vram_mb=0)`;
  - tests en `tests/unit/asr/test_sherpa_streaming.py` (*recognizer* falso) y `tests/integration/test_nemotron_model.py` (marcador `model`: `AsrEngineContract` y WER < 10 % en `dialogo_en_2min.wav`).
- [X] T020 [P] [US1] Segmentador en `src/instanttraductor/pipeline/segmenter.py`: `PauseClauseSegmenter`, que implementa `Segmenter` según research.md R6 (depends on T014).
  - Cierra la unidad con `SPEECH_END` + FINAL.
  - Con habla larga, corta en una coma o conjunción estable si el fragmento tiene ≥ 6 palabras.
  - Corte forzado a los 6 s en la última palabra completa estable.
  - Solo texto estable, sin solapes ni repeticiones. `t_end` por proporción de caracteres.
  - Tests en `tests/unit/pipeline/test_segmenter.py` y subclase de `SegmenterContract`.

**Ola 1, obrero C: traducción**
- [X] T021 [P] [US1] Servidor de traducción y elección de modelo (depends on T014):
  - `src/instanttraductor/mt/llama_server.py`: `LlamaServerProcess(model_path)` sobre `platform.children.ManagedChild`, que lanza `llama-server.exe` de `component_dir("llama-cpp")`. Puerto libre en 127.0.0.1; `-m`, `-ngl 99`, `--cache-ram 0`, `-c 4096`; listo con `GET /health` (≤ 30 s). Se porta `spikes/traduccion/llama_server.py`;
  - `src/instanttraductor/mt/selection.py`:
    - `free_vram_mb()` con nvidia-smi;
    - `choose_mt_model(free_mb)`: el 7B si la VRAM libre tras cargar la voz es ≥ 5 200 + 1 024 MiB; si no, el 1.8B si es ≥ 2 300 + 1 024 MiB; si no, `EngineError(recoverable=False)` (ADR-0011);
  - tests en `tests/unit/mt/test_llama_server.py` y `tests/unit/mt/test_selection.py`.
- [X] T022 [P] [US1] Traductor en `src/instanttraductor/mt/hymt2.py`: `HyMt2Translator(base_url, model_kind)`, que implementa `Translator`. `supports_concise` vale `True` solo con el 7B. Se porta `spikes/traduccion/prompts.py` y `client.py` (depends on T014).
  - ***Prompt*:**
    - contexto como turnos de chat;
    - los 12 ejemplos fijos en castellano de S2;
    - cada turno envuelto en la instrucción de traducir;
    - glosario (el del usuario + el base filtrado por la frase) con la plantilla *Terminology* en chino;
    - `cache_prompt: true`.
  - **CONCISE:** plantilla *Style* «telegraphic Spanish… at most N words», con N = ceil(0,6 × las palabras del original) (lo medido en S2).
  - **Filtros:** vacía, sin caracteres latinos, longitud > 3× la del original o eco del *prompt* → `rejected=True`.
  - **Glosario base** `src/instanttraductor/mt/glossary_es.toml`, con ≥ 150 pares inglés → español de España: juice→zumo, fridge→nevera, parking lot→aparcamiento, computer→ordenador, cell phone→móvil, car→coche, popcorn→palomitas, okay→vale…
  - **Tests:**
    - `tests/unit/mt/test_hymt2.py` (`httpx.MockTransport` + `TranslatorContract`);
    - `tests/integration/test_hymt2_model.py` (marcadores `gpu` y `model`): con el corpus de `spikes/traduccion/corpus.py`, 0 salidas que no son traducción y CONCISE del 7B con ≥ 20 % menos palabras.

**Ola 2, obrero D: reproducción, autotest y eco**
- [ ] T023 [P] [US1] Reproducción en `src/instanttraductor/audio/wasapi_playback.py`: `DeviceSink`, que implementa `AudioSink`. Se porta `spikes/audio/reproduccion.py` y el gancho de `notificationCallback` (depends on T014).
  - `miniaudio.PlaybackDevice` sin `device_id`, 48 kHz, float32, estéreo, periodos de 20 ms × 3;
  - sigue `rerouted`; cuenta los `underruns`;
  - FIFO; eventos con el `Clock`; `set_volume` 0,0–2,0 solo sobre nuestra voz; `pending_seconds`; `stop()` corta en seco;
  - tests en `tests/unit/audio/test_wasapi_playback.py` (*backend* falso) y `tests/integration/test_playback_device.py` (marcador `device`, `AudioSinkContract`).
- [ ] T024 [US1] Autotest y monitor de eco (depends on T015, T023):
  - `src/instanttraductor/audio/selftest.py`: `run_echo_selftest(sink, make_source) -> SelftestResult(ok, reason, correlation_threshold)`. Tono de 0,3 s a 1234 Hz y −30 dBFS: NO debe aparecer en EXCLUDE y SÍ en INCLUDE (detección de `spikes/audio/audio_spike/analisis.py`);
  - `src/instanttraductor/audio/echo_monitor.py`: `EchoMonitor` (R14). Correlación de envolventes (50 Hz) entre lo reproducido y lo captado, en una ventana de 2 s, con el umbral calibrado; contador `echo_events` y aviso;
  - tests en `tests/unit/audio/test_echo_monitor.py` y `tests/integration/test_selftest_device.py` (marcador `device`).

**Ola 2, obrero E: voz**
- [ ] T025 [P] [US1] Servicio de voz: código en `engines/tts-qwen3/src/tts_service/`. **No toca el `pyproject.toml` ni el `uv.lock` del motor (T010).** Se porta `spikes/voz/qwen3/bench_qwen3.py` y `spikes/voz/common/vozbench.py` (depends on T014).
  - **`engine.py`:**
    - carga Qwen3-TTS-12Hz-0.6B-Base, `warmup()` y CUDA graphs;
    - voces de `--voices-dir` (`<id>.wav` + `<id>.json` con `ref_text`), con el *prompt* ICL en caché y `x_vector_only` de rescate;
    - `chunk_size=4`; *streaming* de PCM float32 a 24 kHz.
  - **`server.py`:** la API **exacta** de `contracts/tts-service.md` (línea `ready`, `/health`, `/voices`, `/synthesize` en *streaming*, `/shutdown`, solo 127.0.0.1).
  - **Tests:**
    - `engines/tts-qwen3/tests/test_server.py` con un motor falso, sin GPU;
    - `engines/tts-qwen3/tests/test_engine_gpu.py` (marcadores `gpu` y `model`): primer audio p95 ≤ 0,6 s y VRAM ≤ 3,5 GB.
- [ ] T026 [P] [US1] Cliente del servicio de voz en `src/instanttraductor/tts/` (depends on T014):
  - `service_process.py`: `TtsServiceProcess` sobre `ManagedChild`:
    - lanza `uv run --frozen --offline --project engines/tts-qwen3 tts-service --host 127.0.0.1 --port 0 --voices-dir <AppPaths.voices> --models-dir <AppPaths.models>` con `HF_HUB_OFFLINE=1` y `TRANSFORMERS_OFFLINE=1` (FR-027);
    - está listo con la línea `ready` (≤ 120 s);
    - se para con `POST /shutdown`;
  - `http_client.py`: `HttpSynthesizer`, que implementa `Synthesizer`:
    - *streaming* con httpx, conservando el resto si un bloque no es múltiplo de 4 bytes;
    - lee `X-Sample-Rate`;
    - 4xx/5xx → `EngineError`;
    - `supports_speed=False`;
    - `list_voices()`;
  - tests en `tests/unit/tts/test_http_client.py` (`httpx.MockTransport` + `SynthesizerContract`) y `tests/unit/tts/test_service_process.py`.
- [ ] T027 [P] [US1] DSP en `src/instanttraductor/audio/dsp.py` (depends on T014):
  - `StreamResampler(src_rate, dst_rate)` con soxr y estado entre trozos;
  - `StreamTimeStretch(speed)` con TDHS (`audiostretchy`), entre 1,0 y 1,5, cambiable entre unidades. Se porta `spikes/voz/velocidad_postproceso.py`;
  - tests en `tests/unit/audio/test_dsp.py`: duración dentro del 2 %, sin NaN y continuidad entre trozos.

**Ola 2, obrero F: planificador, retraso y métricas**
- [X] T028 [P] [US1] Política de retraso en `src/instanttraductor/pipeline/delay.py`: `ThresholdDelayController`, que implementa `DelayController` (depends on T014).
  - `speed` lineal de 1,0 (con lag = `accelerate_after_s`) a `max_speed` (con lag = `concise_after_s`);
  - CONCISE cuando lag > `concise_after_s` a velocidad máxima, con histéresis hasta lag < `accelerate_after_s`, **solo si `allow_concise`**;
  - `drop_oldest_pending` si lag > `drop_after_s`;
  - tests en `tests/unit/pipeline/test_delay.py` (incluido `allow_concise=False`) y `DelayControllerContract`.
- [X] T029 [US1] Planificador en `src/instanttraductor/pipeline/scheduler.py`: `Scheduler` (depends on T028).
  - Estados de «Frase» de `data-model.md` en FIFO.
  - **`lag` = `clock.now() − t_end` de la frase pendiente más antigua que aún no ha empezado a sonar (0 si no hay)**. Se muestrea cada 0,5 s para las métricas.
  - **Peticiones:**
    - `TranslationRequest`: contexto de las últimas pronunciadas, glosario y `mode` de la decisión;
    - `SynthesisRequest`: `speed`.
  - **Resultados:** una traducción `rejected` pasa a `Outcome.REJECTED`; los descartes, con `sink.cancel_pending()`.
  - **Tiempos:** `StageTimings`, incluido `captured_at`, con los eventos.
  - Tests en `tests/unit/pipeline/test_scheduler.py` con dobles y `ManualClock`.
- [X] T030 [P] [US1] Métricas e informe en `src/instanttraductor/metrics/` (depends on T014):
  - `recorder.py`: `MetricsRecorder`, que guarda los `UtteranceRecord`, la serie de `lag` y los `diagnostics` de `contracts/informe.md`:
    - `startup_s`;
    - `rss_mb_min5` y `rss_mb_end`, y `rss_children_mb_*` (psutil, de los PID hijos);
    - `max_lag_s` y `lag_over_drop_max_streak_s`;
    - `echo_events`, `component_restarts`, `underruns` y `mt_model`;
  - `report.py`: JSON con el esquema exacto (`schema_version: 1`, etapas `capture`, `asr`, `mt`, `tts_first` y `playback`, percentiles solo sobre las pronunciadas, recuento de `rejected`) y Markdown;
  - tests en `tests/unit/metrics/test_report.py`, con un JSON de referencia.

**Integración (orquestador)**
- [ ] T031 [US1] Sesión en directo en `src/instanttraductor/pipeline/session.py`: `LiveSession` (depends on T015–T030).
  - **Arranque, ≤ 60 s:**
    1. servicio de voz;
    2. `choose_mt_model` y `llama-server`;
    3. `DelayPolicy(allow_concise=translator.supports_concise)` y calentamiento;
    4. **`SessionClock` al arrancar la captura**;
    5. autotest (si falla, código 4).
  - **Hilos y colas acotadas:** captura → AGC → VAD/ASR → segmentador → planificador → traducción → voz → *time-stretch* y remuestreo → sink. En paralelo, el monitor de eco y el `StatusSnapshot` hacia la interfaz.
  - **Reapertura de la captura:** se repite el autotest (ADR-0010).
  - **Fallos:** un componente que falla se reinicia una vez; si vuelve a fallar, parada limpia.
  - **Parada en ≤ 2 s:** `sink.stop()` y `stop_all()`.
  - **Al terminar:** si `save_audio`, el audio captado en `AppPaths.reports`; el informe, con `mt_model`.
- [ ] T032 [US1] Línea de comandos en `src/instanttraductor/cli.py` (depends on T031, T017, T009):
  - `main()` con argparse; subcomando `directo` (`--voz`, `--volumen`, `--mostrar-texto`, `--informe`);
  - código 3 si `is_installed()` falla para algún componente obligatorio;
  - el resto de códigos de `contracts/cli.md`;
  - `logging` a fichero rotativo en `AppPaths.logs` (sin audio).

**Checkpoint**: el modo directo funciona por sí solo, con datos medidos (T034).

---

## Phase 4: User Story 2 - Traducir un fichero y medir el resultado (Priority: P2)

**Goal**: modo archivo, sin dispositivos: pista en español alineada, mezcla, transcripción, traducción e informe.

**Independent Test**: quickstart §4 y §11.

### Tests for User Story 2

- [ ] T038 [US2] E2E del modo archivo con dobles en `tests/integration/test_file_mode_fakes.py`, sin marcadores (depends on T037):
  - salidas válidas a partir de `dialogo_en_2min.wav`;
  - un fichero dañado → código 5 y sin carpeta de salida;
  - `silencio_3s.wav` → pista en silencio e informe «no se detectó habla».
- [ ] T039 [US2] Validación de quickstart §4 con los motores reales (orquestador; `gpu` y `model`) (depends on T037, T013). Resultados en `validacion.md`.

### Implementation for User Story 2

**Ola 3, obrero G: modo archivo**
- [ ] T035 [P] [US2] Fuente de fichero en `src/instanttraductor/audio/file_source.py`: `FileSource`, que implementa `AudioSource` (depends on T014).
  - `ffmpeg` (`config.ffmpeg_path()`) con `-i <entrada> -ac 1 -ar 16000 -f f32le -` por tubería, **a ritmo real** con el `Clock`;
  - chunks contiguos de 20 ms y `exhausted`;
  - error → `InputFileError` (código 5);
  - tests en `tests/unit/audio/test_file_source.py` + `AudioSourceContract`.
- [ ] T036 [P] [US2] Salidas del modo archivo (depends on T014):
  - `src/instanttraductor/audio/file_sink.py`: `TimelineSink`, que implementa `AudioSink`. Coloca cada unidad en su instante del `Clock`, en FIFO y sin solapes;
  - `src/instanttraductor/audio/file_outputs.py`, con escritura atómica en una carpeta temporal:
    - `voz_es.wav`: 48 kHz, mono, float32, con la duración de la entrada;
    - `mezcla.wav`: 48 kHz, estéreo, 16 bits, con ffmpeg `amix=normalize=0` + limitador;
    - `mezcla.mkv`: si hay vídeo; vídeo copiado, pista 1 = mezcla, pista 2 = original;
    - `transcripcion.srt/.json` y `traduccion.srt/.json` (`contracts/informe.md`);
  - tests en `tests/unit/audio/test_file_sink.py` y `tests/unit/audio/test_file_outputs.py`.

**Integración (orquestador)**
- [ ] T037 [US2] Sesión de fichero (depends on T031, T032, T035, T036):
  - `FileSession` en `src/instanttraductor/pipeline/session.py`: `FileSource` + `TimelineSink`, sin autotest ni monitor de eco;
  - subcomando `archivo ENTRADA [--salida DIR] [--voz ID]` en `src/instanttraductor/cli.py` (código 5 si la entrada no es válida).

**Checkpoint**: las historias 1 y 2 funcionan cada una por su lado.

---

## Phase 5: User Story 3 - Preparar el equipo y elegir la voz (Priority: P3)

**Goal**: `preparar` en una sola ejecución, sin cuentas ni pagos, con las licencias a la vista; ≥ 3 voces castellanas (femeninas y masculinas) que se pueden escuchar y elegir.

**Independent Test**: quickstart §2 y §3.

### Tests for User Story 3

- [ ] T044 [US3] Validación de quickstart §2 y §3 en el PC (orquestador y humano) (depends on T043): el humano escucha las voces y elige (SC-009). Resultados en `validacion.md`.

### Implementation for User Story 3

- [X] T040 [P] [US3] Voces femeninas castellanas (2026-10-01):
  - primera vuelta, LibriVox: el humano rechazó las 4 lectoras («voz terrible»);
  - segunda vuelta (`spikes/voces/README.md`): voces diseñadas con VoxCPM2 (descripción en español, acento peninsular) y grabaciones CC0 de VoxPopuli;
  - el humano acepta las 4 finalistas y elige **Lucía** (`es-f-dvx-01`) por defecto;
  - las 5 voces del catálogo (Lucía, Clara, Voz humana 1, Voz humana 2 y Tux) están empaquetadas en `src/instanttraductor/setup/voices/`.

**Ola 3, obrero H: preparación y voces**
- [ ] T041 [P] [US3] Instalador en `src/instanttraductor/setup/installer.py` (depends on T014).
  - **Comprobaciones** (si falla alguna, código 6): `windows_build()` ≥ 20348, GPU NVIDIA y driver (nvidia-smi), espacio libre ≥ lo que falta + 2 GB y `ffmpeg_path()` (si falta, gyan.dev *essentials* a `AppPaths.bin`).
  - **Descargas idempotentes por componente:**
    - `snapshot_download(repo_id, revision, allow_patterns)` para HF;
    - httpx en *streaming* + descompresión para GitHub y archive.org;
    - sha256 de **cada fichero**.
  - **Estados:** `ausente` → `descargado` → `verificado` | `corrupto` (se vuelve a descargar).
  - **Entorno de la voz:** `uv sync --frozen --project engines/tts-qwen3`.
  - **Salida:** tabla `rich` con nombre, versión, licencia, tamaño y estado. `--comprobar` solo verifica.
  - **Tests:** `tests/unit/setup/test_installer.py` (descargador falso; la 2.ª ejecución no descarga nada).
- [ ] T042 [US3] Voces en `src/instanttraductor/setup/voices.py` (depends on T041).
  - **Catálogo:** las voces **empaquetadas** en `src/instanttraductor/setup/voices/` (WAV + JSON con `voice_id`, `name`, `gender`, `source`, `license` y `ref_text`), leídas con `importlib.resources`. Sin descargas.
  - **Instalación:** `install_voices()` las copia a `AppPaths.voices` de forma idempotente, verificando el sha256.
  - **Manifiesto:** entradas `kind="voz"` en `src/instanttraductor/setup/manifest.py` con una fuente de tipo paquete (amplía `Component` para recursos empaquetados sin URL).
  - **Voz por defecto:** `es-f-dvx-01` (Lucía, `config.DEFAULT_VOICE`).
  - **Tests:** `tests/unit/setup/test_voices.py` (ids ASCII únicos, al menos 1 de cada género, licencia, `ref_text` no vacío, instalación idempotente con `home` temporal).

**Integración (orquestador)**
- [ ] T043 [US3] Subcomandos en `src/instanttraductor/cli.py` (depends on T037, T041, T042):
  - `preparar [--comprobar]`, que además genera las muestras de las voces;
  - `voces [--escuchar [ID]] [--elegir ID]`, con `DeviceSink`;
  - `diagnostico`.

**Checkpoint**: las tres historias funcionan por su cuenta.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: calidad, documentación y cierre.

- [ ] T045 [P] Actualizar `README.md` con la instalación y el uso en español, los requisitos y las licencias (depends on T043).
- [ ] T046 Conjunto de calidad para SC-004 (depends on T039):
  - `tests/fixtures/calidad/generate_quality_set.py` sintetiza en inglés 50 frases del corpus de S2 con Qwen3-TTS y una referencia inglesa de LibriVox de dominio público;
  - se pasa `archivo` y el humano revisa `traduccion.srt` (objetivo: ≥ 85 % buenas);
  - resultados en `validacion.md`.
- [ ] T047 Convergencia y revisión (depends on T034, T039, T044, T046):
  - `/speckit-converge` hasta «Converged»;
  - agente `revisor` (Opus) sobre `main..001-espina-dorsal`;
  - corregir los hallazgos GRAVE y MEDIO.
- [ ] T048 Cerrar la feature (depends on T047):
  - skill `registrar-hito` (bitácora, CHANGELOG `0.1.0`, hoja de ruta y resolución de ADR-0006 con los datos de S3);
  - PR y merge a main;
  - tag `v0.1.0`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 → T002, T003 → T004.
- **Foundational (Phase 2)**: tras Setup. T005 → T006 y T011; T007 → T009 → T013; T008 y T010 en paralelo; T011 → T012; todo → T014 (tag). Bloquea las historias.
- **US1 (Phase 3)**: tras T014. Olas 1 y 2 → T031 → T032 → T033 y T034.
- **US2 (Phase 4)**: T035 y T036 tras T014; T037 tras T031 y T032.
- **US3 (Phase 5)**: T040 ya en marcha; T041 tras T014; T042 tras T040 y T041; T043 tras T037.
- **Polish (Phase 6)**: tras T034, T039, T044 y T046.

### User Story Dependencies

- **US1 (P1)**: solo depende de Foundational. Es el MVP.
- **US2 (P2)**: componentes independientes; la sesión reutiliza el *pipeline* de US1 (T031).
- **US3 (P3)**: independiente; US1 y US2 se prueban con la preparación manual (T013).

### Within Each User Story

- Tests primero y en rojo en cada tarea → componentes por olas → integración (orquestador) → validación en el PC.
- Commits en cada hito (`.claude/agents/obrero.md`).

### Parallel Opportunities

- Foundational: T006, T007, T008 y T010 en paralelo tras T005/T003.
- US1, US2 y US3: las tareas [P] de cada ola tocan ficheros disjuntos; ningún par [P] comparte fichero de código ni de test (los directorios de tests los crea T003).

---

## Parallel Example: User Story 1

```text
# Ola 1 (tras contratos-001-v1):
Task: "Obrero A — T015 + T016 + T017: wasapi_capture.py, agc.py y ui/terminal.py"
Task: "Obrero B — T018 + T019 + T020: silero.py, sherpa_streaming.py y segmenter.py"
Task: "Obrero C — T021 + T022: llama_server.py, selection.py, hymt2.py y glossary_es.toml"

# Ola 2:
Task: "Obrero D — T023 + T024: wasapi_playback.py, selftest.py y echo_monitor.py"
Task: "Obrero E — T025 + T026 + T027: engines/tts-qwen3/src, tts/ y dsp.py"
Task: "Obrero F — T028 + T029 + T030: delay.py, scheduler.py y metrics/"

# Ola 3:
Task: "Obrero G — T035 + T036: file_source.py, file_sink.py y file_outputs.py (US2)"
Task: "Obrero H — T041 + T042: installer.py y voices.py (US3; T042 tras la preselección de voces del humano)"
Orquestador: T031 → T032 → T033 (y T037 y T043 cuando lleguen G y H)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Setup (T001–T004) y Foundational (T005–T014), con el tag `contratos-001-v1`.
2. Olas 1 y 2 → T031–T033 → **validación T034 en el PC**.
3. **STOP and VALIDATE.**

### Incremental Delivery

US1 (MVP) → US2 (archivo y conjunto de calidad) → US3 (preparación y voces) → cierre (T045–T048, `v0.1.0`).

### Plan de olas (máximo 3 obreros a la vez; única fuente)

| Ola | Obreros | Tareas | Tests que ejecuta luego el orquestador |
|---|---|---|---|
| 1 | A, B, C | T015–T017 · T018–T020 · T021–T022 | `device` (T015), `model` (T018, T019), `gpu`+`model` (T022) |
| 2 | D, E, F | T023–T024 · T025–T027 · T028–T030 | `device` (T023, T024), `gpu`+`model` (T025) |
| 3 | G, H | T035–T036 · T041–T042 | — |
| Integración | orquestador | T031, T032, T033, T037, T038, T043 | E2E con dobles |
| Validación | orquestador + humano | T034, T039, T044, T046 | en el PC |

---

## Notes

- [P] tasks = different files, no dependencies.
- Cada brief de obrero lleva alcance mínimo, tiempo límite e hitos con commit (ADR-0002, actualización).
- Solo el orquestador toca:
  - `pyproject.toml` y `uv.lock`, los del núcleo y los de `engines/tts-qwen3`;
  - `src/instanttraductor/contracts/**`, `pipeline/session.py` y `cli.py`;
  - `scripts/**`, `specs/**` y `docs/**`.
- Si un obrero necesita una dependencia nueva, termina con `NEEDS_CONTEXT`.
- Los obreros no ejecutan tests `gpu`, `model` ni `device`, ni descargan modelos.
