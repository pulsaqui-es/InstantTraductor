# InstantTraductor

Traductor simultáneo para Windows: captura lo que suena en el PC y lo reproduce hablado en español de España casi en tiempo real. Idioma de origen: inglés primero; japonés y chino después.

## Restricciones que mandan
- 100 % local (RTX 5070 12 GB, Blackwell sm_120): nada de APIs de pago en tiempo de ejecución.
- Uso personal: se permiten licencias no comerciales, pero la licencia de cada modelo o librería queda anotada (ADR o `docs/investigacion/`).
- El audio original suena sin cambios y la voz en español va encima. Contenido principal: series, películas y juegos.
- Windows 11 primero. Lo específico de Windows queda aislado en la capa de audio y plataforma.
- Principios completos en `.specify/memory/constitution.md`. Decisiones en `docs/adr/`.

## Roles
- **Humano:** decide lo importante. Aprueba specs, planes, ADR y cambios de principios o contratos.
- **Orquestador** (sesión principal, Opus): arquitecto. Escribe specs, planes y ADR; reparte, integra y revisa.
- **Obreros** (`.claude/agents/obrero.md`, Sonnet): implementan briefs en worktrees aislados. De apoyo: `revisor` e `investigador`.
- Autonomía concedida: instalar herramientas de desarrollo, ramas, commits, push, PR y merge a main. Se consulta antes cualquier acción destructiva o irreversible y cualquier cambio en el proceso de trabajo.

## Idioma
- En español: documentación, specs, ADR, interfaz, comentarios, docstrings y mensajes de commit.
- En inglés: identificadores de código (módulos, clases, funciones, variables).
- Spec Kit: no se traducen los encabezados de plantilla ni los tokens de máquina (`T001`, `[P]`, `[US1]`, `FR-001`, `SC-001`, `CHK001`, `[NEEDS CLARIFICATION]`, `P1`, casillas `- [ ]`).
- Nombres de feature y de rama en ASCII: `001-nombre-corto`.

## Flujo SDD (Spec Kit 1.0.13, versión fijada)
1. Rama `NNN-nombre-corto` desde main → `/speckit-specify` → `/speckit-clarify` → **H1: el humano aprueba la spec**.
2. `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze` → **H2: el humano aprueba plan, contratos, tareas y ADR nuevos**.
3. Setup y Foundational en secuencia → contratos congelados (tag `contratos-NNN-vX`) → historias por olas con la skill `orquestar-ola`.
4. `/speckit-converge` hasta «Converged» → revisión → merge a main → skill `registrar-hito`.
- Solo el orquestador ejecuta `/speckit-*` (la numeración de features no es atómica) y escribe `tasks.md`.

## Trabajo en paralelo
- Con esfuerzo medio o superior y tareas modulables: obreros en paralelo con la skill `orquestar-ola` (de 2 a 4 por ola).
- Solo el orquestador escribe `specs/**`, `.specify/**`, los contratos, `pyproject.toml`, `uv.lock`, `CLAUDE.md`, `.claude/**` y `docs/**`.
- Los obreros parten del HEAD del orquestador (`worktree.baseRef: "head"`): hay que commitear antes de cada ola.
- Cualquier mejora del proceso se propone al humano antes de aplicarla.

## Entorno y comandos
- Python gestionado con uv. Cada worktree tiene su propio `.venv` (`uv sync`).
- Tests: `uv run pytest` (por defecto excluye `gpu`, `device` y `model`). Lint: `uv run ruff check .`. Formato: `uv run ruff format .`.
- Marcadores: `gpu` (necesita CUDA), `device` (dispositivos de audio reales), `model` (modelos descargados). Solo el orquestador los ejecuta, de uno en uno.
- Modelos y cachés, siempre fuera del repo (`%LOCALAPPDATA%\InstantTraductor\models` y la caché de Hugging Face del usuario).
- Shell: la herramienta Bash (Git Bash) para git y uv. PowerShell 5.1 solo para lo específico de Windows (no admite `&&`).
- Si `gh` o `specify` no están en PATH: `"/c/Program Files/GitHub CLI/gh.exe"` y `~/.local/bin/specify.exe`.

## Git
- Commits en español con prefijo (`feat`, `fix`, `docs`, `chore`, `test`, `refactor`). Commits de tareas: `T011: ...`.
- Nunca force-push a main ni reescribir historia publicada.

## Línea temporal
- Fechas absolutas (`AAAA-MM-DD`). Bitácora en `docs/bitacora.md`, `CHANGELOG.md`, ADR en `docs/adr/` y hoja de ruta en `docs/hoja-de-ruta.md`. Se mantienen con la skill `registrar-hito`.
