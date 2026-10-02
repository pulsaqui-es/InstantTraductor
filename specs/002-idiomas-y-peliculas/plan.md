# Implementation Plan: Idiomas elegidos a mano y robustez en películas

**Branch**: `002-idiomas-y-peliculas` | **Date**: 2026-10-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-idiomas-y-peliculas/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

La 002 amplía la v0.1.0 (spec 001) en cuatro frentes, todos medidos en los spikes S5–S7 y decididos en los ADR 0012 y 0013:

1. **Idioma de origen elegido a mano** (en, ja, zh, ko): un reconocedor por idioma, todos en CPU con sherpa-onnx (Nemotron para en, X-ASR para zh y SenseVoice para ja/ko). El traductor (Hy-MT2-7B) recibe el idioma: el filtro de longitud y el tope de tokens se ajustan por idioma.
2. **Escuchar solo la aplicación elegida** (captura INCLUDE sobre su proceso raíz), con una lista numerada al arrancar, un vigilante que espera y reabre cuando la app reaparece y el autotest con el cableado invertido. El modo «todo el PC» de la 0.1 se mantiene.
3. **Filtro de idioma** (Whisper base ONNX, CPU) sobre el audio de cada unidad antes de traducirla. Es la defensa garantizada para la película compartida por Discord con la llamada en español.
4. **Calidad:**
   - Silero más sensible (0,30/0,15);
   - una cola mínima de unidad para no partir frases en trozos sin sentido;
   - «vosotros» con una nota de escena, posedición por reglas y un reintento solo para el «ustedes» residual.

Además, las validaciones que quedaron pendientes de la 001: 30 min sin eco, 60 min de estabilidad, cambio de dispositivo y sin red.

## Technical Context

**Language/Version**: Python 3.12 (núcleo, uv), como en la 001. El servicio de voz no cambia.

**Primary Dependencies**:
- **Las de la 001**, sin versiones nuevas: sherpa-onnx 1.13.8, onnxruntime, numpy, comtypes, pycaw, miniaudio, soxr, psutil, httpx y rich.
- **Modelos nuevos** (descargados por `preparar`; licencias en research.md, R9):
  - X-ASR-zh-en streaming int8 (Apache-2.0);
  - SenseVoice-Small int8, versión 2024-07-17 con puntuación (FunASR Model License v1.1);
  - Whisper base multilingüe ONNX para la identificación de idioma (MIT).
- **Sin dependencias Python nuevas:** la identificación de idioma reimplementa la decodificación de un paso con onnxruntime (spike S5).

**Storage**:
- ficheros locales;
- ajustes nuevos en `ajustes.toml`: `idioma_origen` y `app_escuchada`.

**Testing**: pytest con los marcadores `gpu`, `model` y `device` (Principio V). Dobles para la lista de apps, el vigilante, el verificador de idioma y los motores nuevos.

**Target Platform**: Windows 11 (build ≥ 20348), RTX 5070 12 GB, Ryzen 7 8700F y 32 GB de RAM.

**Project Type**: aplicación de línea de comandos con dos servicios locales como procesos hijos (traducción y voz), sin cambios.

**Performance Goals**:
- retardo de frase p50 ≤ 3 s y p95 ≤ 5 s en los cuatro idiomas (SC-001);
- reanudación ≤ 5 s tras reiniciar la app (SC-004);
- arranque ≤ 60 s (SC-011);
- filtro de idioma ≤ 150 ms de CPU por unidad.

**Constraints**:
- **cero VRAM nueva**: la GPU sigue con la traducción (5,2 GB) y la voz (3,8 GB);
- 100 % local y sin red después de `preparar`;
- el audio original nunca se toca.

**Scale/Scope**: una persona usuaria y una sesión a la vez, sesiones de hasta 60 minutos.

**Resuelto con los spikes S5–S7** (research.md), sin NEEDS CLARIFICATION pendientes. Queda **una medición de validación con el humano**: si la emisión (Go Live) y la llamada de Discord salen por procesos distintos (research.md, R4). Tiene un plan A y un plan B, y ninguno bloquea el diseño.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Cómo lo cumple este plan | Estado |
|---|---|---|
| I. Local y sin costes | Modelos nuevos gratuitos, en CPU y con licencias válidas en la UE (R9). Sin red tras `preparar` (SC-010) | ✅ |
| II. Latencia medible | Las etapas nuevas (verificación de idioma) entran en `StageTimings` y en el informe. Presupuesto por idioma en R6 | ✅ |
| III. Motores tras contratos | Los motores nuevos implementan `AsrEngine`. El verificador de idioma, un contrato nuevo `LanguageVerifier`. Cambios versionados con el tag `contratos-002-v1` antes de la ola 1 | ✅ |
| IV. Especificación primero | Spec aprobada (H1) con el alcance y las aclaraciones del humano. ADR-0012 y ADR-0013 aprobados por el humano. Plan y tareas por delegación (H2, ADR-0009) | ✅ |
| V. Pruebas sin hardware | Dobles de la lista de apps, del vigilante, de `LanguageVerifier` y de los motores. Tests `device` y `model` marcados | ✅ |
| VI. Paralelismo seguro | Olas de como máximo 3 obreros con ficheros disjuntos (Plan de olas). Ficheros calientes del orquestador | ✅ |
| VII. Simplicidad y Windows primero | Lo de Windows, en `audio/` y `platform/`. Sin detección automática (004) ni UI gráfica (005) | ✅ |

Revisión tras la fase 1: ✅ sin violaciones.

## Project Structure

### Documentation (this feature)

```text
specs/002-idiomas-y-peliculas/
├── plan.md              # este fichero
├── research.md          # fase 0: decisiones R1–R10 con los datos de S5–S7
├── data-model.md        # fase 1: entidades nuevas y cambios
├── quickstart.md        # fase 1: validación en el PC
├── contracts/
│   ├── pipeline-002.md  # cambios de contratos frente a contratos-001-v1
│   └── cli-002.md       # opciones y subcomandos nuevos
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

Ficheros nuevos (N) y modificados (M) sobre la estructura de la 001:

```text
src/instanttraductor/
├── contracts/
│   ├── language.py              # N: SourceLanguage, LanguageVerifier y LanguageVerdict
│   ├── translation.py           # M: TranslationRequest.source_language (por defecto EN)
│   └── __init__.py              # M: reexporta lo nuevo
├── config.py                    # M: Settings.source_language y capture_app
├── audio/
│   ├── wasapi_capture.py        # M: en INCLUDE no vigila el PID objetivo (lo hace el vigilante)
│   ├── apps.py                  # N: lista de apps que suenan (todos los endpoints + sonda INCLUDE), identidad por ruta
│   ├── app_source.py            # N: AppLoopbackSource (AudioSource): vigilante (pid, create_time), esperando/sonando/silencio
│   └── audio_ring.py            # N: búfer circular del audio captado (≥ 30 s) para el verificador de idioma
├── asr/
│   ├── xasr_zh.py               # N: X-ASR-zh-en en streaming (AsrEngine)
│   ├── sensevoice.py            # N: SenseVoice por segmento (AsrEngine sin parciales, corte forzado a max_habla_sin_traducir_s)
│   └── factory.py               # N: reconocedor y recursos por idioma
├── lid/
│   └── whisper_lid.py           # N: WhisperLanguageVerifier (onnxruntime, CPU)
├── mt/
│   ├── hymt2.py                 # M: idioma de origen en el prompt; longitud y max_tokens por idioma; nota de escena
│   └── vosotros.py              # N: posedición ustedes → vosotros (con la señal del inglés) y detector de «ustedes» residual
├── pipeline/
│   ├── session.py               # M: verificación de idioma antes de traducir; anillo de audio
│   ├── segmenter.py             # M: cola mínima de unidad (palabras o caracteres CJK)
│   ├── engines.py               # M: motores por idioma y verificador
│   ├── live.py                  # M: fuente por app o todo el PC; autotest invertido
│   └── file_session.py          # M: idioma de origen
├── vad/silero.py                # M: umbrales por defecto 0,30 / 0,15
├── setup/manifest.py            # M: componentes x-asr-zh, sensevoice-small y whisper-base-lid
├── ui/terminal.py               # M: muestra la app escuchada, el idioma y el estado «esperando a la app»
└── cli.py                       # M: --idioma, --app, --elegir-app, --todo-el-pc; subcomando apps

tests/
├── contract/test_language_contract.py   # N
├── fakes/fake_language.py, fake_apps.py # N
├── unit/... (uno por módulo nuevo)
└── integration/
    ├── test_app_capture_device.py       # N (device)
    ├── test_asr_multilang_model.py      # N (model)
    └── test_language_filter_fakes.py    # N: E2E con dobles (película + llamada en español)
```

**Structure Decision**: se mantiene la estructura de la 001. Lo nuevo va en módulos nuevos detrás de contratos (`asr/`, `lid/`, `audio/app_source.py`). Los cambios en módulos existentes son pequeños y localizados.

## Plan de olas (paralelismo)

| Ola | Quién | Tareas | Ficheros |
|---|---|---|---|
| 0 | Orquestador | Contratos 002, ajustes, dobles y tests de contrato → tag `contratos-002-v1` | `contracts/**`, `config.py`, `tests/fakes/**`, `tests/contract/**` |
| 1 | Obrero A | Captura de la app elegida: lista, vigilante y cambio en la captura | `audio/apps.py`, `audio/app_source.py`, `audio/wasapi_capture.py` y sus tests |
| 1 | Obrero B | Reconocedores por idioma y verificador de idioma | `asr/xasr_zh.py`, `asr/sensevoice.py`, `asr/factory.py`, `lid/**` y sus tests |
| 1 | Obrero C | Traducción por idioma y «vosotros» | `mt/hymt2.py`, `mt/vosotros.py` y sus tests |
| 2 | Obrero D | Preparación: componentes nuevos | `setup/manifest.py` y `tests/unit/setup/**` |
| 2 | Orquestador | Integración: anillo de audio, verificación, segmentador, VAD, motores, CLI e interfaz | `pipeline/**`, `vad/silero.py`, `cli.py`, `ui/terminal.py`, `audio/audio_ring.py` |
| 3 | Orquestador + humano | Validación: tests `device` y `model`, idiomas, Discord y sesiones largas | `validacion.md` |

GPU: solo la usan los tests `model` de la traducción, y los lanza el orquestador de uno en uno.

## Complexity Tracking

Sin violaciones de la constitución. Hay dos complejidades justificadas:

| Complejidad | Por qué hace falta | Alternativa más simple descartada porque |
|---|---|---|
| Verificador de idioma con su propio modelo | Es la única defensa cuando la película y la llamada salen del mismo programa (Discord) | Confiar en el ASR: un reconocedor de inglés «entiende» el español como inglés inventado |
| Fuente de audio que espera a la app y cambia de PID | Exigido por FR-010: esperar sin escuchar otra cosa y reanudar en ≤ 5 s | Reiniciar la sesión: lo prohíbe la spec |
