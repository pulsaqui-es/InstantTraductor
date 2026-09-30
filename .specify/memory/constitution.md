# InstantTraductor Constitution

> Estado: **propuesta**, pendiente de aprobación del humano. Esta línea se quita al aprobarla.

## Core Principles

### I. Local y sin costes (NO NEGOCIABLE)
- Todo el procesamiento (captura, reconocimiento, traducción y síntesis) DEBE ejecutarse en el PC del usuario.
- Ninguna función PUEDE depender de APIs de pago ni de internet en tiempo de ejecución. La red solo se usa para descargar modelos y dependencias.
- El uso es personal: se PUEDEN usar modelos y librerías con licencia no comercial, pero la licencia de cada uno DEBE quedar anotada en un ADR o en `docs/investigacion/`.
- NO se PUEDEN usar componentes cuya licencia excluya la Unión Europea.

Motivo: decisión del humano (ADR-0003); privacidad y coste cero.

### II. La latencia es un requisito medible
- Cada spec que toque el pipeline DEBE declarar su presupuesto de retardo por etapa y un criterio de éxito medible.
- Los tiempos DEBEN medirse en el reloj de audio de la sesión y registrarse por unidad de traducción y etapa.
- Objetivo inicial de EVS (desde que se dice algo hasta que se oye en español) del inglés al español: p50 ≤ 3 s y p95 ≤ 5 s. Todo cambio que lo empeore DEBE justificarse con datos.

Motivo: un intérprete que llega tarde no sirve.

### III. Motores intercambiables tras contratos
- Las etapas (captura, VAD, ASR, traducción, voz y reproducción) DEBEN comunicarse solo mediante contratos: `typing.Protocol` y `@dataclass(frozen=True)` en `src/instanttraductor/contracts/`.
- Cada motor DEBE ser un adaptador que cumple un contrato y declara sus capacidades. Cambiar de motor NO DEBE obligar a tocar otras etapas.
- Los contratos DEBEN congelarse con un tag (`contratos-NNN-vX`) antes de repartir trabajo en paralelo. Cambiar un contrato congelado exige un ADR y la aprobación del humano.

Motivo: los modelos cambian cada pocos meses; los contratos son la frontera estable.

### IV. Especificación primero
- NO DEBE escribirse código de producto sin una spec aprobada por el humano (H1) ni sin plan, contratos y tareas aprobados (H2).
- Toda decisión de arquitectura o tecnología DEBE quedar en un ADR. Los ADR no se borran: se sustituyen.
- La spec describe el qué y el porqué; el plan, el cómo.

Motivo: metodología SDD elegida por el humano (ADR-0001).

### V. Pruebas sin hardware
- Toda la lógica DEBE poder probarse sin GPU, sin modelos descargados y sin dispositivos de audio, con WAV de ejemplo y dobles de los contratos.
- Los tests que necesitan GPU, modelos o dispositivos reales DEBEN llevar los marcadores `gpu`, `model` o `device`. Por defecto no se ejecutan, y solo el orquestador los lanza, de uno en uno.
- Cada contrato DEBE tener tests de contrato que cualquier adaptador supere.

Motivo: los obreros trabajan en paralelo y no pueden competir por la GPU ni por los auriculares.

### VI. Paralelismo seguro
- Los obreros DEBEN trabajar en worktrees aislados, con ficheros asignados en exclusiva por el orquestador.
- Solo el orquestador PUEDE escribir `tasks.md`, las specs, los contratos, `pyproject.toml`, `uv.lock`, `CLAUDE.md`, `.claude/**` y `docs/**`.
- La integración DEBE hacerse en secuencia y solo con los tests en verde. Se rechaza lo que un obrero toque fuera de sus ficheros.

Motivo: velocidad sin conflictos (ADR-0002).

### VII. Simplicidad y Windows primero
- Windows 11 es la plataforma objetivo. El código específico de Windows DEBE quedar aislado en la capa de audio y plataforma.
- El audio original NO DEBE modificarse nunca: la voz en español se mezcla encima.
- YAGNI: no se añade nada que no pida una spec aprobada.

Motivo: foco en el objetivo principal, y puerta abierta a portar a otros sistemas sin pagarlo por adelantado.

## Restricciones técnicas

- **Stack:** el núcleo va en Python 3.12 gestionado con uv. Los motores pesados son procesos hijos del núcleo con su propio entorno (ADR-0004).
- **Audio:** solo el núcleo toca dispositivos de audio; los motores devuelven PCM (ADR-0005).
- **GPU:** NVIDIA RTX 5070 12 GB (Blackwell, CUDA ≥ 12.8). Todo el pipeline DEBE caber en 12 GB de VRAM junto al uso normal del PC.
- **Modelos:** se guardan fuera del repositorio (`%LOCALAPPDATA%\InstantTraductor\models`), con la versión fijada y la licencia anotada.
- **Idioma:** documentación, specs, interfaz, comentarios y commits en español; identificadores de código en inglés; los tokens de Spec Kit no se traducen.

## Flujo de trabajo y calidad

- **Ciclo de una feature:** `/speckit-specify` → `/speckit-clarify` → H1 → `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze` → H2 → implementación por olas (skill `orquestar-ola`) → `/speckit-converge` → revisión → merge a main.
- **Cierre de cada ola:** suite de tests en verde, `ruff` sin errores y revisión del agente `revisor`. Los hallazgos graves se corrigen antes de seguir.
- **Línea temporal:** se mantiene con fechas absolutas (bitácora, CHANGELOG, ADR y hoja de ruta) mediante la skill `registrar-hito`. Versionado SemVer y tags `vX.Y.Z`.

## Governance

- Esta constitución prevalece sobre cualquier otra práctica. `CLAUDE.md` es la guía operativa y NO DEBE contradecirla.
- **Enmiendas:** se proponen con un ADR, las aprueba el humano y se aplican con `/speckit-constitution`, que sube la versión.
- **Versionado:**
  - MAJOR si se elimina o redefine un principio.
  - MINOR si se añade un principio o una sección, o se amplía de forma sustancial.
  - PATCH para aclaraciones.
- **Cumplimiento:** cada plan pasa el «Constitution Check». El revisor y el orquestador comprueban la constitución al integrar. Toda excepción se justifica por escrito en el plan de la feature.

**Version**: 1.0.0 | **Ratified**: 2026-09-30 | **Last Amended**: 2026-09-30
