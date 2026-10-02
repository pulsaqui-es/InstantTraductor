# Tasks: Idiomas elegidos a mano y robustez en películas

**Input**: Design documents from `/specs/002-idiomas-y-peliculas/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: TDD, como en la 001. Cada módulo nuevo lleva sus tests con dobles. Los tests `gpu`, `model` y `device` van marcados y los ejecuta el orquestador, de uno en uno.

**Organization**: por historias, repartidas en olas de como máximo 3 obreros con ficheros disjuntos (ver «Plan de olas»).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: se puede hacer en paralelo (ficheros distintos, sin dependencias pendientes).
- **[Story]**: historia a la que pertenece (US1–US4).

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Comprobar que el entorno del núcleo trae lo necesario para los motores nuevos (sherpa-onnx 1.13.8 con SenseVoice y los transductores en streaming; onnxruntime para Whisper) con `uv run python -c "import sherpa_onnx, onnxruntime"`. Si falta algo, añadirlo a `pyproject.toml` y a `uv.lock` (orquestador; ficheros calientes).

---

## Phase 2: Foundational (Blocking Prerequisites) — ola 0, orquestador

**Purpose**: contratos 002 aditivos (`contracts/pipeline-002.md`), ajustes nuevos y dobles. Termina con el tag `contratos-002-v1`.

- [ ] T002 Crear `src/instanttraductor/contracts/language.py` exactamente como `contracts/pipeline-002.md`:
  - `SourceLanguage` (StrEnum `en|ja|zh|ko`);
  - `LanguageVerdict` (frozen: `accepted`, `detected`, `probability`, `elapsed_s`);
  - `LanguageVerifier` (Protocol: `name`, `verify(samples, sample_rate, language)`, `close()`);
  - reexportarlos en `src/instanttraductor/contracts/__init__.py`.
- [ ] T003 Añadir al final, con valor por defecto, `TranslationRequest.source_language: SourceLanguage = SourceLanguage.EN` en `src/instanttraductor/contracts/translation.py` y `StageTimings.lid_done_at: float | None = None` en `src/instanttraductor/contracts/metrics.py`. Los tests de la 001 deben seguir en verde.
- [ ] T004 Ajustes nuevos en `src/instanttraductor/config.py`:
  - `source_language` (clave `idioma_origen`, uno de `en|ja|zh|ko`, por defecto `en`);
  - `capture_app` (clave `app_escuchada`, «vacío o ruta absoluta de un `.exe`», por defecto `""`);
  - validación con `ValueError` y la clave en español;
  - tests en `tests/unit/test_config.py`.
- [ ] T005 [P] Dobles en `tests/fakes/fake_language.py`:
  - `FakeLanguageVerifier`, con veredicto por guion o por energía y un idioma fijo;
  - en `tests/fakes/fake_apps.py`: `FakeAppEnumerator` (lista de `AudioApp` de guion) y `FakeProcessTable` (procesos que aparecen y mueren por reloj).
- [ ] T006 Tests de contrato en `tests/contract/test_language_contract.py`:
  - clase `LanguageVerifierContract`, reutilizable por las implementaciones reales, sobre el doble: tipos, `elapsed_s ≥ 0`, `detected` en {en, es, ja, zh, ko} y `close()` idempotente;
  - comprobar que `AudioSourceContract` (`tests/contract/test_audio_contract.py`) admite fuentes `finite=False` que entregan ceros.
- [ ] T007 Commit y tag `contratos-002-v1` (orquestador). Suite completa en verde.

**Checkpoint**: contratos congelados; pueden empezar las olas.

---

## Phase 3: User Story 1 - Escuchar solo la película (Priority: P1) 🎯 MVP

**Goal**: escuchar solo la app elegida, con lista, espera y reanudación (FR-006..FR-012).

**Independent Test**: Chrome con una película en inglés y voz en otra app durante 10 min, con `directo --app chrome`. Solo se traduce la película (SC-003). Al reiniciar Chrome, se reanuda en ≤ 5 s (SC-004).

### Implementation — ola 1, obrero A (captura de la app)

- [X] T008 [P] [US1] Lista de apps en `src/instanttraductor/audio/apps.py`. Portar `spikes/captura_app/listar_apps.py` y `common.py` (research.md, R4).
  - `list_audio_apps(*, probe_s=0.6) -> list[AudioApp]`: sesiones de todos los endpoints de render activos; objetivo = la sesión o su padre directo si tiene la misma imagen; agrupar por `exe_path`; `display_name` del `FileDescription`.
  - Sonda INCLUDE de `probe_s`: `sounding` = RMS ≥ -60 dBFS.
  - **Ocultar la propia app y todos sus antepasados.**
  - `find_app(name_or_path) -> list[AppIdentity]` (sin distinguir mayúsculas, por nombre visible o por nombre del exe) y `resolve_root(exe_path) -> AppIdentity | None` (PID y `create_time` actuales).
  - Inyectable para tests (enumerador y tabla de procesos).
  - Tests en `tests/unit/audio/test_apps.py` con los dobles de T005.
- [X] T009 [P] [US1] Captura sin vigilancia del PID en INCLUDE, en `src/instanttraductor/audio/wasapi_capture.py`. Con `include=True` y `target_pid`, `ProcessLoopbackSource` no reabre ni llama a `on_reopen` porque muera el PID objetivo (S6, hallazgo 2). En EXCLUDE no cambia nada. Tests en `tests/unit/audio/test_wasapi_capture.py`.
- [X] T010 [US1] `AppLoopbackSource` en `src/instanttraductor/audio/app_source.py`, que implementa `AudioSource` (depends on T008, T009). Portar el vigilante de `spikes/captura_app/capturar_app.py`.
  - **Vigilante** cada 0,25 s por (PID, `create_time`).
  - **Estados** `esperando`, `sonando` y `silencio` (data-model.md, AppCaptureState), con callback `on_state(estado, nombre)`.
  - **Mientras espera**, chunks de ceros de 20 ms a ritmo del `Clock`, contiguos.
  - **Al aparecer o cambiar el PID**, abre `ProcessLoopbackSource(include=True, target_pid=nuevo)`, sin cortar la continuidad de los chunks.
  - **Aviso «suena pero llega silencio»** tras ~4 s, solo si la sonda dice que suena.
  - Expone `arrival_time` y `current_pid`.
  - **Tests:**
    - `tests/unit/audio/test_app_source.py`, con dobles de proceso y de captura: espera, aparición, muerte y reinicio, y reanudación ≤ 5 s con reloj manual;
    - `AudioSourceContract` con `finite=False`.
- [X] T011 [US1] Tests `device` en `tests/integration/test_app_capture_device.py` (depends on T010):
  - lista con un emisor propio (ffplay de un tono a -30 dBFS);
  - INCLUDE del emisor: oye su tono y no el de un segundo emisor;
  - matar y relanzar el emisor: reanuda en ≤ 5 s;
  - autotest invertido con `run_echo_selftest`: `make_source(False)` = INCLUDE del emisor y `make_source(True)` = INCLUDE propia → ok.

**Checkpoint**: la captura de la app funciona sola (la integración en la CLI está en T024).

---

## Phase 4: User Story 2 - Series en japonés, chino y coreano (Priority: P2)

**Goal**: idioma elegido a mano y filtro de idioma (FR-001..FR-005, FR-003, SC-001..SC-003b).

**Independent Test**: `archivo` con 10 min de FLEURS en ja, zh y ko: p50 ≤ 3 s y p95 ≤ 5 s. Con una conversación en español mezclada, no se traduce nada de ella.

### Implementation — ola 1, obrero B (reconocedores y filtro de idioma)

- [X] T012 [P] [US2] `XAsrZhStreaming` en `src/instanttraductor/asr/xasr_zh.py`, que implementa `AsrEngine`.
  - X-ASR-zh-en int8 de 960 ms con puntuación, en sherpa-onnx `OnlineRecognizer` y CPU.
  - Portar de `spikes/idiomas/idiomas/asr.py`.
  - Mismo patrón que `asr/sherpa_streaming.py`: parciales y FINAL en `flush()`.
  - `language="zh"`.
  - Tests unitarios con un `recognizer` falso en `tests/unit/asr/test_xasr_zh.py`.
- [X] T013 [P] [US2] `SenseVoiceSegmentAsr` en `src/instanttraductor/asr/sensevoice.py`, que implementa `AsrEngine` con `capabilities.partials=False`.
  - **Funcionamiento:** acumula en `accept()`; en `flush()` decodifica con `OfflineRecognizer` (SenseVoice 2024-07-17, `use_itn=True` y el idioma fijado: `ja` o `ko`) y devuelve un FINAL.
  - **Corte forzado (R2):** con `max_segment_s` (el de `max_habla_sin_traducir_s`) de habla continua, emite un FINAL cortando en la trama de menos energía de los últimos 1,5 s y sigue con el resto.
  - **Tests** con un decodificador falso en `tests/unit/asr/test_sensevoice.py`: FINAL al hacer `flush`, corte forzado y `reset`.
- [X] T014 [US2] Fábrica por idioma en `src/instanttraductor/asr/factory.py` (depends on T012, T013):
  - `create_asr(language, clock, *, models_dir, max_segment_s) -> AsrEngine`, más una carga previa `load_recognizer(language)` para el hilo de arranque;
  - en → Nemotron (existente), zh → X-ASR, ja y ko → SenseVoice;
  - tests en `tests/unit/asr/test_factory.py`.
- [X] T015 [P] [US2] `WhisperLanguageVerifier` en `src/instanttraductor/lid/whisper_lid.py`, que implementa `LanguageVerifier` (research.md, R3).
  - Whisper base ONNX (encoder y decoder de sherpa-onnx) con onnxruntime en CPU y un hilo.
  - Portar `spikes/idiomas/idiomas/lid.py`.
  - Probabilidades restringidas a {en, es, ja, zh, ko}; `accepted` si gana el idioma elegido.
  - Entrada de 1-6 s a 16 kHz.
  - Tests unitarios con sesiones ONNX falsas en `tests/unit/lid/test_whisper_lid.py` y `LanguageVerifierContract`.
- [X] T016 [US2] Tests `model` en `tests/integration/test_asr_multilang_model.py` (depends on T014, T015). Con 10 frases FLEURS por idioma del corpus de S5 (`%LOCALAPPDATA%\InstantTraductor\spikes\idiomas\`; se saltan si no existe):
  - CER ≤ 1,5 × el de S5;
  - el verificador acepta ≥ 9/10 del idioma correcto y rechaza ≥ 9/10 de español.

### Implementation — ola 1, obrero C (traducción por idioma y «vosotros»)

- [X] T017 [P] [US2] Traducción por idioma en `src/instanttraductor/mt/hymt2.py` (research.md, R10):
  - el prompt nombra el idioma de origen de `request.source_language`;
  - filtro de longitud en caracteres: en ≤ 3×, ko ≤ 4×, ja ≤ 6× y zh ≤ 7×;
  - `max_tokens` por caracteres en ja y zh;
  - el glosario base de España solo con origen `en`;
  - tests en `tests/unit/mt/test_hymt2.py` (las 50 frases zh de S5 ya no se rechazan: usar 5 de ellas como fixture de texto).
- [X] T018 [US3] «Vosotros» en `src/instanttraductor/mt/vosotros.py` y `src/instanttraductor/mt/hymt2.py` (depends on T017; research.md, R8):
  - **(a) nota de escena** solo con origen en inglés: marca de plural en las últimas 5 líneas en inglés y ninguna de singular → nota de estilo en el turno. Recortar la salida desde `"\n\n("`;
  - **(b) `postedit_vosotros(source_en, text) -> str`**, portado de `spikes/habla_baja/postedit.py`: solo con señal de plural informal en el inglés;
  - **(c) reintento** con el 7B solo si queda «ustedes» y hay señal;
  - **(d) cláusula de estilo** en el modo CONCISE;
  - **tests** en `tests/unit/mt/test_vosotros.py` con frases de `spikes/habla_baja` (corpus B0): sin daños en singulares ni en la 3.ª persona del plural.
- [X] T019 [US3] Tests `gpu`+`model` en `tests/integration/test_vosotros_model.py` (depends on T018): con el corpus B0 de S7, ≥ 80 % de «vosotros» y ≤ 2 % de «ustedes» (SC-006).

---

## Phase 5: User Story 3 - No perderse nada y oír español de España (Priority: P3)

**Goal**: habla baja y unidades con sentido (FR-013, FR-014, FR-016). El «vosotros» está en T018 y T019.

- [X] T020 [US3] VAD más sensible en `src/instanttraductor/vad/silero.py`: valores por defecto `threshold=0.30` y `neg_threshold=0.15` (research.md, R7). Actualizar sus tests (orquestador, ola 2).
- [X] T021 [US3] Cola mínima de unidad en `src/instanttraductor/pipeline/segmenter.py` (orquestador, ola 2):
  - no cortar por cláusula si detrás quedarían < 4 palabras (la regla medida en S7); en ja y zh no hay espacios ni cortes de cláusula: la unidad es el segmento del VAD o el corte forzado;
  - el tope `max_untranslated_s` sigue mandando;
  - recibe el idioma;
  - tests en `tests/unit/pipeline/test_segmenter.py`.

---

## Phase 6: Integración (ola 2) — orquestador y obrero D

- [X] T022 [P] Componentes nuevos en `src/instanttraductor/setup/manifest.py` (obrero D, research.md, R9):
  - `x-asr-zh`, `sensevoice-small` (2024-07-17 int8) y `whisper-base-lid`;
  - URL o revisión fijadas, verificando que existen, y sha256 y tamaños de **cada fichero** calculados descargándolos a una carpeta temporal fuera del repo;
  - licencias: Apache-2.0, «FunASR Model License v1.1» y MIT;
  - adaptar `tests/unit/setup/test_manifest.py` y `tests/unit/setup/test_installer.py` si hace falta. El instalador de la 001 debe soportarlos sin cambios de diseño.
- [X] T023 Pipeline en `src/instanttraductor/pipeline/session.py`, más `src/instanttraductor/audio/audio_ring.py` y `src/instanttraductor/pipeline/scheduler.py` (depends on T002–T007, T015):
  - **anillo de audio** (≥ 30 s, tras el AGC);
  - el hilo de traducción **verifica el idioma** antes de traducir (contracts/pipeline-002.md, reglas):
    - si se rechaza: `Scheduler.on_rejected(unit_id, "idioma")`, un método nuevo que cierra como `REJECTED`;
    - si el verificador falla, se traduce igual y se avisa;
    - `StageTimings.lid_done_at`;
  - `TranslationRequest.source_language`;
  - E2E con dobles en `tests/integration/test_language_filter_fakes.py`: película en «inglés» y conversación en «español» (FakeLanguageVerifier), solo se pronuncia la primera.
- [X] T024 [US1] Integración de la escucha y los idiomas en `src/instanttraductor/pipeline/engines.py`, `pipeline/live.py` y `pipeline/file_session.py` (depends on T010, T014, T023):
  - motores por idioma con `create_asr`, y el verificador;
  - `WasapiDevices`: fuente `AppLoopbackSource` o `ProcessLoopbackSource` según el modo, y **autotest invertido** en modo app;
  - el estado de la app va a los avisos o a la interfaz;
  - `file_session` con el idioma.
- [X] T025 [US1] CLI e interfaz en `src/instanttraductor/cli.py` y `src/instanttraductor/ui/terminal.py` (depends on T024; contracts/cli-002.md):
  - `--idioma`, `--app`, `--elegir-app` (lista numerada, se elige con un número y se guarda) y `--todo-el-pc`;
  - `archivo --idioma`;
  - subcomandos `apps` e `idioma`;
  - línea de estado con el idioma y lo que se escucha;
  - tests en `tests/unit/test_cli.py`.
- [X] T026 Informe en `src/instanttraductor/metrics/report.py` y `metrics/recorder.py`: la etapa `lid` en `stages_s`, el recuento de rechazadas por idioma y los campos `source_language` y `capture` (data-model.md); tests.

---

## Phase 7: User Story 4 - Sesiones largas sin sorpresas (Priority: P4) y validación

- [ ] T027 [US4] Validación en el PC según `quickstart.md` §2–§5 (orquestador): tests `device`, `model` y `gpu`; preparación; idiomas con FLEURS (SC-001); app elegida (SC-003, SC-004). Resultados en `specs/002-idiomas-y-peliculas/validacion.md`.
- [ ] T028 [US2] Calidad ja/zh/ko (SC-002) con el humano: `traduccion.srt` frente a la referencia en español, ≥ 85 % por idioma. Si el japonés no llega, cambiar a Parakeet-ja (research.md, R2).
- [ ] T029 [US1] Discord con el humano (quickstart §6):
  - medición de procesos con `spikes/captura_app/discord_sesiones.py` → plan A o B (R4);
  - si es el plan A, capturar solo el hijo de la emisión (tarea de seguimiento en la convergencia);
  - prueba real de 10 min (SC-003b).
- [ ] T030 [US3] SC-005, SC-006 y SC-007 con los corpus de S7 (quickstart §7).
- [ ] T031 [US4] Sesiones largas y cambio de dispositivo (SC-008, SC-009, SC-011) y sin red (SC-010) (quickstart §8–§9), con el humano.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T032 README: idiomas, `--app` y `--elegir-app`, Discord y los nuevos componentes con sus licencias.
- [ ] T033 `/speckit-converge`, revisión con el agente `revisor` (Opus), registrar el hito, merge a main y tag `v0.2.0`.

---

## Dependencies & Execution Order

- **Setup (T001)** → **Foundational (T002–T007, tag)** → olas.
- **Ola 1** (3 obreros, ficheros disjuntos):
  - A: T008, T009 → T010 → T011 (tests device los ejecuta el orquestador);
  - B: T012, T013 → T014; T015 → T016 (tests model los ejecuta el orquestador);
  - C: T017 → T018 → T019 (tests gpu los ejecuta el orquestador).
- **Ola 2:** D: T022 en paralelo con el orquestador: T020, T021, T023 → T024 → T025, T026.
- **Validación (T027–T031)** tras la ola 2. **Polish (T032, T033)** al final.

### Plan de olas (única fuente)

| Ola | Quién | Tareas | Ficheros |
|---|---|---|---|
| 0 | orquestador | T001–T007 | `contracts/**`, `config.py`, `tests/fakes/**`, `tests/contract/**`, `pyproject.toml` |
| 1 | A | T008–T011 | `audio/apps.py`, `audio/app_source.py`, `audio/wasapi_capture.py`, `tests/unit/audio/test_apps.py`, `test_app_source.py`, `test_wasapi_capture.py`, `tests/integration/test_app_capture_device.py` |
| 1 | B | T012–T016 | `asr/xasr_zh.py`, `asr/sensevoice.py`, `asr/factory.py`, `lid/**`, `tests/unit/asr/test_xasr_zh.py`, `test_sensevoice.py`, `test_factory.py`, `tests/unit/lid/**`, `tests/integration/test_asr_multilang_model.py` |
| 1 | C | T017–T019 | `mt/hymt2.py`, `mt/vosotros.py`, `tests/unit/mt/test_hymt2.py`, `test_vosotros.py`, `tests/integration/test_vosotros_model.py` |
| 2 | D | T022 | `setup/manifest.py`, `tests/unit/setup/**` |
| 2 | orquestador | T020, T021, T023–T026 | `vad/silero.py`, `pipeline/**`, `audio/audio_ring.py`, `cli.py`, `ui/terminal.py`, `metrics/**` |
| 3 | orquestador + humano | T027–T031 | `validacion.md` |

## Implementation Strategy

### MVP First

US1 (escuchar la app elegida) resuelve el problema principal de la persona usuaria y puede integrarse sola tras la ola 1. Los idiomas (US2) llegan en la misma ola, pero se validan aparte.

### Incremental Delivery

Ola 0 → ola 1 (A, B y C) → ola 2 (integración y D) → validación con el humano → `v0.2.0`.
