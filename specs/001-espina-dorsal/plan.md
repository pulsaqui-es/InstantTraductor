# Implementation Plan: Espina dorsal del intérprete simultáneo (inglés → español)

**Branch**: `001-espina-dorsal` | **Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-espina-dorsal/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Construir la tubería completa, de extremo a extremo, del intérprete: capta el audio del sistema excluyendo el de la propia app; detecta la voz; la reconoce en inglés en streaming; la agrupa en unidades de traducción (frases cortas enteras, frases largas por cláusulas y como máximo 6 s de habla sin traducir); la traduce al español de España con contexto; la sintetiza con una voz castellana fija; y la reproduce encima del original sin tocarlo.

El mismo núcleo sirve para tres modos:
- **Directo:** dispositivos reales.
- **Archivo:** fichero de entrada y pistas alineadas de salida, al ritmo real.
- **Preparación:** descarga y verificación de componentes, más elección de voz.

Un planificador controla el retraso (acelerar hasta 1,25×, luego resumir y, como último recurso, descartar) y registra el tiempo de cada etapa por frase para el informe de la sesión.

Enfoque técnico (ADR 0004–0008):
- Núcleo en Python 3.12 con uv.
- Captura con *process loopback* en modo EXCLUDE (pyminiaudio).
- Silero VAD y Nemotron Streaming EN (sherpa-onnx, CPU).
- Hy-MT2-1.8B servido por `llama-server` como proceso hijo.
- Servicio de voz propio (proceso hijo con su entorno) detrás de una API HTTP local.
- Contratos `typing.Protocol` + `@dataclass(frozen=True)` congelados antes de repartir el trabajo.

## Technical Context

**Language/Version**: Python 3.12 (núcleo, gestionado con uv). El servicio de voz usa su propio proyecto uv, con la versión de Python que exija el motor (ver research.md, R8).

**Primary Dependencies** (versiones en research.md):
- Núcleo:
  - captura: `comtypes` + ctypes (*process loopback* propio, R2);
  - reproducción: `miniaudio` 1.71 (pyminiaudio);
  - señal: `numpy`, `soxr`, `audiostretchy` (*time-stretch* TDHS), `pycaw`;
  - reconocimiento: `onnxruntime` (Silero VAD con su `.onnx`), `sherpa-onnx` 1.13.8 + **`sherpa-onnx-core`** (declarado explícitamente);
  - comunicación y modelos: `httpx`, `huggingface_hub`;
  - interfaz y ajustes: `rich`, `tomli-w`.
- Binarios externos:
  - `llama-server` de llama.cpp **b11146** (CUDA 13.4, sm_120);
  - `ffmpeg`.
- Servicio de voz (`engines/tts-qwen3/`):
  - motor: `faster-qwen3-tts` 0.5.3 + Qwen3-TTS-12Hz-0.6B-Base;
  - `torch` 2.11.0+cu130 y `transformers` 5.15.1 (fijado);
  - servidor: FastAPI + uvicorn.
- Desarrollo: `pytest`, `pytest-timeout` y `ruff`.

**Storage**: ficheros locales.
- Ajustes: `%APPDATA%\InstantTraductor\ajustes.toml`.
- Modelos, binarios y voces: `%LOCALAPPDATA%\InstantTraductor\{models,bin,voices}\`.
- Registros e informes: `%LOCALAPPDATA%\InstantTraductor\{logs,informes}\`.
- Nunca se guarda audio captado sin petición expresa (FR-030).

**Testing**: pytest con marcadores `gpu`, `model` y `device`, excluidos por defecto (Principio V).
- Tests unitarios y de contrato con dobles y WAV pequeños en `tests/fixtures/`.
- Tests de integración marcados, que ejecuta el orquestador de uno en uno.

**Target Platform**: Windows 11 (build ≥ 20348 para *process loopback*); PC del usuario con RTX 5070 12 GB (Blackwell sm_120, CUDA ≥ 12.8), 32 GB de RAM y Ryzen 7 8700F.

**Project Type**: aplicación de escritorio de línea de comandos, con dos servicios locales como procesos hijos (traducción y voz).

**Performance Goals** (spec SC-001, SC-006 y SC-010):
- retardo de frase p50 ≤ 3 s y p95 ≤ 5 s;
- parada ≤ 2 s;
- arranque ≤ 60 s.

Presupuesto por etapa: captura + VAD ≤ 0,1 s · ASR ≤ 0,8 s · traducción ≤ 0,3 s · primer audio de voz ≤ 0,6 s · búfer de reproducción ≤ 0,1 s.

**Constraints**:
- 100 % local y sin coste.
- VRAM de la app de unos 8,5 GB (traducción 7B 5,2 GB + voz 3,3 GB). Si al arrancar no cabe, reserva automática con el 1.8B (5,6 GB en total) (ADR-0011).
- Sin internet tras la preparación.
- El audio original nunca se modifica.
- Sin procesos huérfanos, garantizado con un *Job Object* de Windows.

**Scale/Scope**: una persona usuaria y una sesión a la vez. Sesiones de hasta 60 minutos estables (SC-005). Ficheros de hasta ~2 h en el modo archivo.

**Resuelto con los spikes S1–S4** (research.md, R2–R9; ADR-0010, ADR-0011 y la resolución de ADR-0008), sin NEEDS CLARIFICATION pendientes:
- **Captura:** propia con ctypes/comtypes, no con pyminiaudio.
- **ASR:** Nemotron en CPU, final p50 de 0,67 s, segmentando por pausas y comas.
- **Traducción:** 7B con llama.cpp b11146, *prompt* de S2 y modo resumen; p50 de 0,21 s.
- **Voz:** Qwen3-TTS, primer audio p95 de 0,18 s.
- **Velocidad:** *time-stretch* TDHS.

Retardo de frase estimado sin colas: 0,67 + 0,21 + 0,18 + 0,06 ≈ **1,1 s p50**, frente al objetivo de ≤ 3 s.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Cómo lo cumple este plan | Estado |
|---|---|---|
| I. Local y sin costes | Todo se ejecuta en el PC. La red solo se usa en la preparación y sin cuentas. Licencias en research.md (R20) | ✅ |
| II. Latencia medible | Presupuesto por etapa; tiempos por frase y etapa en el reloj de sesión (`StageTimings`); informe p50/p95 (FR-023, FR-024) | ✅ |
| III. Motores tras contratos | Contratos en `src/instanttraductor/contracts/` y `specs/001-espina-dorsal/contracts/`; adaptadores intercambiables; tag `contratos-001-v1` antes de la primera ola | ✅ |
| IV. Especificación primero | Spec aprobada por el humano (H1, 2026-10-01). Los cambios de arquitectura que salieron de los spikes (ADR-0010 y ADR-0011) y la elección de voz los aprobó el humano. El plan y las tareas se aprueban por delegación (H2, ADR-0009) | ✅ |
| V. Pruebas sin hardware | Dobles de todos los contratos, `ManualClock` y WAV de muestra. Tests `gpu`, `model` y `device` marcados | ✅ |
| VI. Paralelismo seguro | Olas con ficheros disjuntos (ver «Plan de olas»). Ficheros calientes del orquestador. Obreros en worktrees | ✅ |
| VII. Simplicidad y Windows primero | Lo específico de Windows, aislado en `audio/wasapi_*.py` y `platform/windows.py`. Sin UI gráfica ni funciones fuera de la spec. El original no se toca | ✅ |

Revisión tras la fase 1: ✅ sin violaciones (ver final de la sección «Complexity Tracking»).

## Project Structure

### Documentation (this feature)

```text
specs/001-espina-dorsal/
├── plan.md              # Este fichero
├── research.md          # Fase 0: decisiones (incluye los resultados de los spikes S1–S4)
├── data-model.md        # Fase 1: entidades, estados y reglas
├── quickstart.md        # Fase 1: guía de validación ejecutable
├── contracts/           # Fase 1: contratos
│   ├── pipeline.md      # Protocolos internos entre etapas (Python)
│   ├── cli.md           # Comandos, opciones, códigos de salida y salidas
│   ├── tts-service.md   # API HTTP local del servicio de voz
│   └── informe.md       # Formato del informe de métricas y de las salidas del modo archivo
└── tasks.md             # Fase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
pyproject.toml                    # proyecto uv del núcleo (del orquestador)
src/instanttraductor/
├── __init__.py
├── __main__.py                   # python -m instanttraductor
├── cli.py                        # subcomandos: directo, archivo, preparar, voces, diagnostico
├── config.py                     # ajustes (TOML) y rutas estándar
├── contracts/                    # CONGELADOS tras la fase Foundational (tag contratos-001-v1)
│   ├── __init__.py
│   ├── clock.py                  # Clock, reloj de sesión
│   ├── audio.py                  # AudioChunk, SpeechClip, AudioSource, AudioSink, PlaybackEvent
│   ├── speech.py                 # VadEvent, Vad, AsrEvent, AsrCapabilities, AsrEngine
│   ├── units.py                  # TranslationUnit, Segmenter
│   ├── translation.py            # TranslationMode, TranslationRequest, TranslationResult, Translator
│   ├── synthesis.py              # VoiceRef, SynthesisRequest, SynthesizedChunk, Synthesizer
│   ├── scheduling.py             # DelayPolicy, DelayDecision, DelayController
│   └── metrics.py                # StageTimings, UtteranceRecord, SessionReport
├── platform/
│   └── windows.py                # Job Object (matar hijos al salir), versión de Windows
├── audio/
│   ├── wasapi_capture.py         # ProcessLoopbackSource: process loopback propio (ctypes/comtypes), EXCLUDE(PID propio)
│   ├── echo_monitor.py           # monitor de eco: correlación voz reproducida / captura (R14)
│   ├── wasapi_playback.py        # DeviceSink (dispositivo por defecto, sigue cambios)
│   ├── file_source.py            # FileSource (ffmpeg → 16 kHz mono, a ritmo real)
│   ├── file_sink.py              # TimelineSink (pista alineada)
│   ├── file_outputs.py           # mezclas (wav/mkv), SRT y JSON, escritura atómica
│   ├── agc.py                    # AGC y aviso de «sin audio del origen»
│   ├── dsp.py                    # remuestreo y time-stretch TDHS
│   └── selftest.py               # comprobación anti-realimentación al arrancar
├── vad/
│   └── silero.py                 # SileroVad (ONNX Runtime, CPU)
├── asr/
│   └── sherpa_streaming.py       # adaptador de Nemotron Streaming EN
├── pipeline/
│   ├── clock.py                  # SessionClock (monotónico) y ManualClock (tests)
│   ├── segmenter.py              # unidades: frases cortas enteras, largas por cláusulas, máx. 6 s
│   ├── delay.py                  # política de retraso: acelerar, resumir, descartar
│   ├── scheduler.py              # cola de frases, orden, estados y descartes
│   └── session.py                # une etapas (hilos y colas), ciclo de vida y parada limpia
├── mt/
│   ├── llama_server.py           # proceso hijo llama-server: arranque, salud y parada
│   ├── selection.py              # elección 7B / 1.8B según la VRAM libre (ADR-0011)
│   ├── hymt2.py                  # HyMt2Translator: prompt de S2 (contexto, ejemplos, glosario), modo resumen y filtros
│   └── glossary_es.toml          # glosario base de léxico de España (datos)
├── tts/
│   ├── service_process.py        # proceso hijo del servicio de voz: arranque, salud y parada
│   └── http_client.py            # HttpSynthesizer (streaming de PCM)
├── metrics/
│   ├── recorder.py               # tiempos por etapa y frase
│   └── report.py                 # resumen p50/p95, JSON y Markdown
├── setup/
│   ├── manifest.py               # componentes fijados: URL, revisión, sha256, tamaño y licencia
│   ├── installer.py              # comprobaciones, descargas idempotentes y verificación
│   └── voices.py                 # catálogo de voces castellanas y muestras
└── ui/
    └── terminal.py               # estado en vivo (rich), avisos y resumen

engines/tts-qwen3/                # servicio de voz Qwen3-TTS: proyecto uv propio (R8)
├── pyproject.toml
└── src/tts_service/
    ├── server.py                 # API HTTP de contracts/tts-service.md
    └── engine.py                 # envoltorio del motor (carga, caché de voces, streaming)

tests/
├── fakes/                        # dobles de todos los contratos
├── fixtures/                     # WAV pequeños (tonos, silencio, habla de LibriSpeech CC BY 4.0)
├── contract/                     # suites que cualquier adaptador debe superar
├── unit/                         # por módulo
└── integration/                  # marcados gpu, model o device (solo el orquestador)

spikes/                           # pruebas de arranque S1–S4 (referencia; no es producto)
```

**Structure Decision**:
- Un único paquete de núcleo (`src/instanttraductor`) organizado por etapas, más un paquete independiente por motor pesado con entorno propio (`engines/`), como exige ADR-0004.
- Los contratos viven en un subpaquete propio, para poder congelarlos y dar a cada obrero ficheros disjuntos: un módulo por etapa y sus tests con el mismo reparto.
- `llama-server` no necesita paquete porque es un binario externo; su gestor está en `mt/llama_server.py`.

## Plan de olas (paralelismo)

Tras `/speckit-tasks`, el reparto previsto es este:
- **Fase 1: Setup** (orquestador, en secuencia): `pyproject.toml`, `uv.lock`, configuración de ruff y pytest, estructura de carpetas y `tests/fakes` vacíos.
- **Fase 2: Foundational** (orquestador, o un obrero en secuencia): `contracts/**` + tests de contrato + dobles + `pipeline/clock.py` + `config.py`. **Tag `contratos-001-v1`.**
Como máximo 3 obreros a la vez (ADR-0002, actualización del 2026-10-01). Los tests `gpu`, `model` y `device` los ejecuta el orquestador al integrar.
- **Ola 1** (3 obreros, ficheros disjuntos):
  1. audio: `audio/wasapi_capture.py`, `audio/wasapi_playback.py`, `audio/selftest.py`, `audio/echo_monitor.py` y `platform/`;
  2. escucha: `vad/`, `asr/` y `pipeline/segmenter.py`;
  3. traducción: `mt/`.
- **Ola 2** (3 obreros):
  1. voz: `engines/tts-qwen3/`, `tts/` y `audio/dsp.py`;
  2. planificador, retraso y métricas: `pipeline/delay.py`, `pipeline/scheduler.py` y `metrics/`;
  3. modo archivo: `audio/file_source.py` y `audio/file_sink.py`.
- **Ola 3** (1 obrero + orquestador):
  - preparación y voces (`setup/`, incluidas las referencias femeninas castellanas);
  - en paralelo, el orquestador integra `pipeline/session.py`, `cli.py` y `ui/terminal.py`.
- **Cierre:** tests de integración marcados y validación de `quickstart.md`, a cargo del orquestador.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No hay violaciones. Los tres procesos (núcleo, `llama-server` y servicio de voz) no son una complejidad añadida por este plan: los exige y justifica ADR-0004 (DLL de CUDA incompatibles, aislamiento de fallos y motores intercambiables).
