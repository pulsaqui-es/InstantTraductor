# ADR-0001: Desarrollo guiado por especificaciones con GitHub Spec Kit

- Estado: Aceptada
- Fecha: 2026-09-30
- Decide: humano (la metodología SDD) y orquestador (la herramienta)

## Contexto
El humano ha elegido el desarrollo guiado por especificaciones (SDD): la especificación se escribe y se aprueba antes que el código. Hay un solo decisor humano, y la implementación la hacen agentes de Claude Code, a menudo varios en paralelo. Hace falta una herramienta que dé estructura a las specs y que produzca una lista de tareas que se pueda repartir.

## Decisión
Usar **GitHub Spec Kit 1.0.13**, con la versión fijada, integración `claude` (skills `/speckit-*`) y scripts PowerShell (`--script ps`).
- Artefactos por feature en `specs/NNN-nombre/`: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md` y `tasks.md`.
- Constitución en `.specify/memory/constitution.md`.
- Dos puertas humanas obligatorias: H1 (aprobar la spec) y H2 (aprobar plan, contratos y tareas).
- Contenido en español mediante reglas en `CLAUDE.md` y en la constitución. Se conservan los encabezados de plantilla y los tokens de máquina en inglés.
- Solo el orquestador ejecuta `/speckit-*` y escribe `tasks.md`.

## Alternativas consideradas
- **OpenSpec:** ligero y con español nativo, pero sus tareas no marcan paralelismo ni dependencias, así que sirve peor como cola de trabajo para los obreros. Queda como plan B para la fase de mantenimiento.
- **BMAD Method:** demasiados roles y ceremonia para un solo decisor.
- **cc-sdd (estilo Kiro):** buen encaje y español nativo, pero su comunidad es unas 40 veces menor.
- **Sin framework** (modo plan + subagentes): mínimo, pero sin una estructura común de artefactos ni reglas de paralelismo.

## Consecuencias
- Positivas:
  - `tasks.md` trae IDs, fases, historias y la marca `[P]` (ficheros disjuntos), la base para repartir olas.
  - La fase Foundational es el sitio natural para congelar contratos.
  - Tiene soporte de primera clase en Windows.
- Negativas:
  - No tiene opción de idioma: puede volver al inglés y hay que vigilarlo en las puertas.
  - Evoluciona muy rápido: se actualiza a propósito con `specify self upgrade` y `specify integration upgrade claude`, revisando el diff.
  - Los nombres de feature deben ser ASCII: con caracteres no ASCII la carpeta sale sin nombre (issue #4574).
  - La numeración no es atómica (#4270): las features se crean de una en una.
- Los ficheros gestionados por Spec Kit se versionan sin conversión de fin de línea (`.gitattributes`), para que sus manifiestos de hashes sigan siendo válidos.

## Referencias
- `docs/investigacion/2026-09-30-sdd-herramientas.md`
- https://github.com/github/spec-kit (v1.0.13, 29-sep-2026)
