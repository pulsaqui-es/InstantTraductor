# Herramientas SDD para Claude Code en modo «orquestador + obreros en paralelo» — InstantTraductor

> Informe de investigación · 30-sep-2026 · Tema 05.
> Método: fuentes primarias (repos, releases, docs oficiales, issues vía API de GitHub) y lectura directa del código y las plantillas (clones superficiales en `scratchpad/research/raw/`, solo lectura). No se instaló nada ni se tocó `C:\InstantTraductor`. Lo que no se pudo comprobar se marca **(sin verificar)**.

---

## 1. Resumen ejecutivo

- **GitHub Spec Kit v1.0.13** (29-sep-2026, MIT, 139,6k★) es la opción más madura y la que mejor encaja: se integra de forma nativa con Claude Code como *skills* (`/speckit-plan`…), trae scripts PowerShell para Windows y genera un `tasks.md` (IDs `T001`, marca `[P]`, etiqueta `[US1]`, fases) que sirve directamente como cola de trabajo.
- En 2026 ha cambiado mucho: `--ai` se eliminó en la 0.10.0 → `specify init --here --integration claude --script ps`; los comandos son ahora skills en `.claude/skills/speckit-*/SKILL.md`; git pasó a ser una extensión opcional; hay un comando nuevo, `/speckit-converge`; y se actualiza con `specify self upgrade` + `specify integration upgrade claude`.
- Por diseño, Spec Kit **no orquesta obreros en paralelo** (lo deja a extensiones). El patrón que funciona: congelar los contratos en la Fase 2, lanzar olas de tareas `[P]` con ficheros disjuntos a subagentes con `isolation: worktree` y `worktree.baseRef: "head"`, y que el orquestador sea el único que escribe `tasks.md` e integra.
- **Español:** Spec Kit no tiene opción de idioma (se pidió en el #1239 y se cerró como *not planned*). Se resuelve con reglas en `CLAUDE.md` y en la constitución, conservando los tokens de máquina y usando nombres de carpeta ASCII. OpenSpec y cc-sdd sí tienen idioma nativo, español incluido.
- **Alternativas:** OpenSpec (ligero, pensado para código existente) es la segunda opción. BMAD es demasiado pesado para un solo decisor. Kiro no funciona sobre Claude Code. Agent OS v3 solo gestiona estándares. Superpowers es complementario, no sustituto.
- **Recomendación:** Spec Kit 1.0.13 fijado + protocolo propio de orquestación (agentes `implementador` y `revisor`, olas, worktrees, puertas humanas). Primero hay que actualizar Claude Code: el `claude.exe` instalado es el 2.1.201 y la última es la 2.1.286, con correcciones de worktrees en Windows.

---

## 2. Tabla comparativa

Estrellas (★) consultadas en la API de GitHub el 30-sep-2026.

| Opción | Versión (fecha) | Licencia | ★ | Soporte Claude Code | Español | Peso del proceso | Paralelismo | Windows | Madurez |
|---|---|---|---|---|---|---|---|---|---|
| **GitHub Spec Kit** | v1.0.13 (29-sep-2026) | MIT | 139,6k | Nativo: skills `.claude/skills/speckit-*`, `/speckit-<cmd>` | No nativo (instrucciones o preset propio; ya existe un preset zh-cn de modelo) | Medio-alto: 5 pasos mínimos, 9 con puertas; hay preset `lean` | `[P]` + fases + historias; delegación a subagentes documentada; extensiones de terceros (schedule, worktrees) | Sí: scripts `ps`/`py`/`sh`; en 2026 hubo varios bugs de PS 5.1, ya corregidos | Muy alta; 2-3 releases por semana; 1.0 desde el 21-ago-2026 |
| **OpenSpec** (Fission-AI) | v1.13.2 (23-sep-2026) | MIT | 70,8k | Nativo: `.claude/skills/openspec-*` + `/opsx:*` | **Nativo**: `openspec init --language`, con ejemplo en español | Bajo (propose → apply → archive) | Varios cambios en paralelo (una carpeta por cambio); tareas sin marca de paralelismo ni dependencias | Sí (Node ≥ 20.19); correcciones CRLF/EPERM | Alta |
| **BMAD Method** | v6.12.0 (3-sep-2026) | MIT + marca registrada | 53,7k | Plugin de marketplace o `npx skills add` | **Nativo** (`document_output_language`, `communication_language`) | Alto (roles PM/arquitecto/dev/QA, PRD, épicas) | Solo entre épicas, con una capa de coordinación externa; módulo aparte BMad Loop | Sí (hay correcciones de Windows); necesita Node + uv + Python ≥ 3.11 | Alta, pero con cambios incompatibles frecuentes en 6.x |
| **cc-sdd** (especificaciones estilo Kiro) | v3.1.0 (23-sep-2026) | MIT | 3,7k | Skills de Claude Code (estable) + subagentes | **Nativo** (`--lang es`) | Medio (requisitos EARS → diseño → tareas) | Marcas `(P)`, `_Boundary:_`, `_Depends:_`; `/kiro-impl` hace una tarea por iteración; `/kiro-spec-batch` crea especificaciones en paralelo | (sin verificar) | Media |
| **Kiro** (AWS) | IDE/CLI (docs del 27-ago-2026) | Propietario | — | No (es otro agente); Spec Kit tiene integración `kiro-cli` | (sin verificar) | Medio | Nativo: olas de tareas concurrentes | Sí (IDE) | Producto comercial |
| **Agent OS** | v3.0 (20-ene-2026) | MIT | 5,5k | Diseñado para Claude Code (comandos) | No | Bajo (estándares + `shape-spec`; delega en el modo plan) | Retirado en v3 (lo delega en el agente) | Scripts bash (Git Bash) (sin verificar) | Media; poca actividad |
| **Superpowers** (obra) | v6.4.2 (25-sep-2026) | MIT | 293k | Plugin del marketplace oficial | No | Medio (lluvia de ideas → plan → subagente por tarea + revisión) | Subagente nuevo por tarea (secuencial) + worktrees; despacho paralelo solo para problemas independientes | Sí | Alta |
| **CCPM** | Sin releases (último push 18-mar-2026) | MIT | 8,4k | Skill | No | Medio | Un worktree por épica + flujos paralelos; usa GitHub Issues | Requiere `gh` | Poca actividad |
| **Tessl** | Framework en beta cerrada; Registry en beta abierta | Comercial | — | Vía MCP | (sin verificar) | Alto (la especificación es la fuente del código) | — | — | Baja (según reseñas de terceros) |
| **GSD** (get-shit-done) | v1.42.3; **archivado** el 26-jun-2026 | MIT | 64k | Era para Claude Code | — | — | — | — | Discontinuado; sigue en `open-gsd/gsd-core` |
| **Claude Code sin framework** (modo plan + subagentes + worktrees) | Claude Code 2.1.286 (30-sep-2026) | Propietario | — | — | Sí, con instrucciones | Mínimo | Subagentes con `isolation: worktree`, `/batch`, flujos dinámicos, agent teams (experimental) | Sí | Alta |

---

## 3. Detalle por opción

### 3.1 GitHub Spec Kit (`github/spec-kit`)

#### Estado y versión
- **Versión actual: v1.0.13**, publicada el 29-sep-2026 en PyPI como `specify-cli`. Requiere Python ≥ 3.11 y es oficial (mantenedor `github-spec-kit`). La v1.0.0 salió el 21-ago-2026 y en septiembre se publicaron de la 1.0.4 a la 1.0.13. `main` ya está en `1.0.14.dev0`.
- **Tracción:** 139,6k★, más de 270 contribuidores, último commit el 30-sep-2026. **Licencia MIT** (Copyright GitHub, Inc.).
- **Alcance actual:** ya no es solo SDD. Incluye tres procesos: SDD en el núcleo, más *bug fixing* (`specify extension add bug`) e *idea assessment* (`specify extension add assess`) como extensiones incluidas. A eso se suman extensiones, presets, workflows y bundles. El catálogo comunitario tiene unas 176 extensiones y unos 40 presets.
- **Integraciones:** más de 40 agentes. Claude Code usa la clave `claude` y se instala como skills («multi-install safe»).

**Cambios clave respecto a los tutoriales de 2025** (según el CHANGELOG):

| Antes | Ahora (1.0.x) |
|---|---|
| `specify init --here --ai claude --script ps` | `--ai`, `--ai-commands-dir` y `--ai-skills` **se eliminaron en la 0.10.0** (9-jun-2026). Ahora se usa `--integration claude`. |
| `.claude/commands/speckit.plan.md` y `/speckit.plan` | `.claude/skills/speckit-plan/SKILL.md` y `/speckit-plan`. La integración nativa por skills llegó en la 0.4.5 (abr-2026); en el #2031 se había reportado que `.claude/commands/` dejaba de reconocerse. |
| Siempre se creaba una rama git `001-feature`; existía `--no-git` | Git es ahora la **extensión opcional** `git`, y `--no-git` se eliminó en la 0.10.0. La feature activa se guarda en `.specify/feature.json`, no en la rama. |
| `update-agent-context.ps1` editaba `CLAUDE.md` | Spec Kit ya no toca `CLAUDE.md`. Si se quiere, está la extensión opcional `agent-context`. |
| — | Nuevo **`/speckit-converge`** (0.11.2, 18-jun-2026). |
| Se actualizaba re-ejecutando `init --force` | `specify self upgrade`, `specify integration upgrade claude` y `specify extension update`, con manifiestos y hash SHA-256 de cada fichero. |

#### Instalación en Windows (PowerShell)

```powershell
# 0) uv. En esta máquina ya aparece uv 0.12.21 en PATH (WinGet). Si faltara:
winget install --id=astral-sh.uv -e
#   o: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 1) CLI persistente FIJADA a una versión (recomendado)
uv tool install specify-cli==1.0.13
#   alternativa desde el tag de git:
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git@v1.0.13

# 2) Comprobaciones
specify version           # versión de la CLI, Python, plataforma
specify self check        # ¿hay una versión más nueva? (solo lectura)
specify check             # detecta las CLIs de los agentes (aquí: claude.exe de WinGet)

# 3) Inicializar en el repo existente (primero commit de una base revisable)
cd C:\InstantTraductor
specify init --here --force --integration claude --script ps
#   --ignore-agent-tools   si no encuentra la CLI "claude" (p. ej. si solo se usa la extensión de VS Code)
#   --non-interactive      para scripts; ¡ojo! sin --integration, en modo no interactivo elige copilot

# 4) Opcionales
specify extension add git     # ramas numeradas 001-... y auto-commit configurable
specify preset add lean       # flujo mínimo (menos ceremonia)

# Uso puntual sin instalar (uvx):
uvx --from git+https://github.com/github/spec-kit.git@v1.0.13 specify init --here --integration claude --script ps
```

- **Opciones de `specify init` en la 1.0.13** (leídas del código): `--integration <clave>`, `--integration-options`, `--script sh|ps|py`, `--here`, `--force`, `--non-interactive`, `--ignore-agent-tools`, `--preset <id>`, `--extension <id>` (repetible), `--offline`, `--skip-tls`, `--debug`, `--github-token`, `--trust-extension-urls`.
- **Variables de entorno útiles:**
  - `SPECKIT_INTEGRATION_DEFAULT=claude`
  - `SPECIFY_FEATURE_DIRECTORY` (fija la feature)
  - `SPECIFY_FEATURE_NO_PERSIST=1` (1.0.11): evita escribir `feature.json`; pensada para varios agentes concurrentes en el mismo checkout
  - `SPECIFY_INIT_DIR` (monorepos)
- **Diagnóstico:** `specify integration status [--json]`, `specify version --features --json`.

#### Estructura que genera

Con `--integration claude --script ps` (nombres leídos de docs, código y tests; `claude.manifest.json` se infiere por analogía con `copilot.manifest.json`):

```text
C:/InstantTraductor/
├── .claude/
│   └── skills/
│       ├── speckit-constitution/SKILL.md
│       ├── speckit-specify/SKILL.md
│       ├── speckit-clarify/SKILL.md
│       ├── speckit-plan/SKILL.md
│       ├── speckit-checklist/SKILL.md
│       ├── speckit-tasks/SKILL.md
│       ├── speckit-analyze/SKILL.md
│       ├── speckit-implement/SKILL.md
│       ├── speckit-converge/SKILL.md
│       └── speckit-taskstoissues/SKILL.md
├── .specify/
│   ├── .gitignore                 # gestionado: ignora feature.json y extensions/*/local-config.yml
│   ├── feature.json               # puntero a la feature activa (estado local, NO se versiona)
│   ├── init-options.json          # opciones de init (tipo de script, numeración...)
│   ├── integration.json           # integraciones instaladas / por defecto
│   ├── integrations/              # manifiestos con hash de ficheros gestionados
│   │   ├── claude.manifest.json
│   │   └── speckit.manifest.json
│   ├── memory/
│   │   └── constitution.md        # constitución del proyecto (nunca la pisa un upgrade)
│   ├── scripts/powershell/        # con --script ps (con py: scripts/python/*.py)
│   │   ├── common.ps1
│   │   ├── check-prerequisites.ps1
│   │   ├── create-new-feature.ps1
│   │   ├── resolve-template.ps1
│   │   ├── setup-plan.ps1
│   │   └── setup-tasks.ps1
│   ├── templates/
│   │   ├── spec-template.md
│   │   ├── plan-template.md
│   │   ├── tasks-template.md
│   │   ├── checklist-template.md
│   │   ├── constitution-template.md
│   │   └── overrides/             # (lo crea el usuario) overrides locales, máxima precedencia
│   ├── workflows/speckit/workflow.yml   # workflow "Full SDD Cycle" (+ workflow-registry.json)
│   ├── presets/<id>/              # si se instalan presets
│   ├── extensions/<id>/           # si se instalan extensiones (git, agent-context...)
│   └── extensions.yml             # hooks de extensiones (before_/after_<comando>)
└── specs/
    └── 001-captura-audio/         # una carpeta por feature: NNN-nombre-corto
        ├── spec.md                # /speckit-specify (+ /speckit-clarify)
        ├── checklists/
        │   └── requirements.md    # checklist de calidad del spec (lo mantiene specify/clarify)
        ├── plan.md                # /speckit-plan
        ├── research.md            # /speckit-plan, fase 0 (decisión / motivo / alternativas)
        ├── data-model.md          # /speckit-plan, fase 1
        ├── quickstart.md          # /speckit-plan, fase 1 (escenarios de validación ejecutables)
        ├── contracts/             # /speckit-plan, fase 1 (interfaces: API de librería, CLI, UI...)
        └── tasks.md               # /speckit-tasks
```

#### Comandos para Claude Code: qué son y dónde se instalan

Son **skills** en `.claude/skills/speckit-<cmd>/SKILL.md`. Llevan `user-invocable: true` y `disable-model-invocation: false`, así que el orquestador también puede invocarlas con la herramienta Skill. En Claude Code se escriben con guion (`/speckit-plan`); la documentación usa el nombre canónico con punto (`/speckit.plan`).

| Skill | Qué hace / qué produce | ¿Obligatorio? |
|---|---|---|
| `/speckit-constitution <principios>` | Crea o actualiza `.specify/memory/constitution.md` | Una vez por proyecto |
| `/speckit-specify <descripción>` | Crea `specs/NNN-x/spec.md` + `checklists/requirements.md` y guarda `feature.json`; como mucho 3 marcas `[NEEDS CLARIFICATION]` | Sí |
| `/speckit-clarify [foco]` | Hasta 5 preguntas; escribe las respuestas en `spec.md` | Puerta opcional |
| `/speckit-plan <stack/arquitectura>` | `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md` + «Constitution Check» | Sí |
| `/speckit-checklist [foco]` | Checklists de calidad de requisitos («tests unitarios de los requisitos»); los marca el revisor humano | Opcional |
| `/speckit-tasks` | `tasks.md` por fases e historias | Sí |
| `/speckit-analyze` | Informe de consistencia spec/plan/tasks. **Solo lectura** | Opcional (recomendado) |
| `/speckit-implement [alcance]` | Ejecuta las tareas y las marca `[X]`. Se detiene a preguntar si hay checklists sin marcar | Sí |
| `/speckit-converge` | Compara código y artefactos. **Solo añade** tareas en una sección «Convergence»; se repite hasta «Converged» | Sí (desde 1.0) |
| `/speckit-taskstoissues` | Convierte tareas en GitHub Issues (requiere remoto GitHub + MCP de GitHub); pasando a la extensión `github` | Opcional |

- **Flujo mínimo:** `constitution` (una vez) → `specify` → `plan` → `tasks` → `implement` → `converge`, repitiendo implement/converge hasta «Converged».
- **Flujo completo:** `constitution` → `specify` → `clarify` → `plan` → `checklist` → `tasks` → `analyze` → `implement` → `converge`.
- **Extensiones:** añaden skills como `/speckit-bug-assess`, `/speckit-git-commit`, etc.
- **Features grandes:** la documentación recomienda acotar cada ejecución (`/speckit-implement only execute tasks T001-T010...`) o delegar las tareas `[P]` en subagentes; ver §3.7.

#### Formato de `tasks.md` (plantilla y reglas del comando, leídas del repo)

Cada tarea es una línea:

```
- [ ] [TaskID] [P?] [Story?] Descripción con ruta de fichero
```

- La casilla es obligatoria.
- **ID** secuencial `T001, T002…` en orden de ejecución.
- **`[P]`**: solo si la tarea es paralelizable, es decir, toca ficheros distintos y no depende de tareas incompletas.
- **`[USn]`**: obligatoria en las fases de historia y prohibida en Setup, Foundational y Polish.
- La descripción debe incluir la **ruta exacta** del fichero.

Ejemplos que da la regla:
- ✅ `- [ ] T012 [P] [US1] Create User model in src/models/user.py`
- ❌ `- [ ] T001 [US1] Create model` (falta la ruta)

**Fases:**
1. **Setup**.
2. **Foundational**: «⚠️ CRITICAL: No user story work can begin until this phase is complete», con un *Checkpoint* al final.
3. **3+**: una fase por historia, en orden P1, P2, P3 (la P1 va marcada «🎯 MVP»). Cada una lleva *Goal*, *Independent Test* y *Checkpoint*. Los tests son opcionales y solo se generan si se piden (TDD): «write these tests FIRST, ensure they FAIL».
4. **Última: Polish**.

Dentro de una historia el orden es: tests → modelos → servicios → endpoints → integración.

**Secciones finales:**
- *Dependencies & Execution Order*.
- *Parallel Example*: bloques `Task: "..."` para lanzar juntos.
- *Implementation Strategy*: *MVP first*, entrega incremental y *Parallel Team Strategy* (tras Foundational, un desarrollador por historia).

**Dependencias:** el núcleo **no tiene sintaxis formal**. Solo cuentan el orden, las fases y texto libre como «(depends on T012, T013)» en el ejemplo. La propuesta de `(depends on T###)` en el núcleo se cerró sin implementar (#1934, 25-sep-2026). El preset comunitario **`explicit-task-dependencies`** sí la añade, junto con un «Execution Wave DAG».

**Cómo lo ejecuta `/speckit-implement`:**
- Fase a fase.
- Las `[P]` pueden ir juntas, pero «las tareas que afectan a los mismos ficheros deben ir en secuencia».
- Se para si falla una tarea no paralela. Si falla una `[P]`, sigue y lo reporta.
- Marca `[X]`.

**`/speckit-converge`:** añade tareas nuevas bajo «Convergence», con IDs que continúan la numeración.

#### Scripts PowerShell en Windows
- **Con `--script ps`**, cada skill ejecuta, por ejemplo, `.specify/scripts/powershell/setup-plan.ps1 -Json` y lee el JSON resultante (`FEATURE_DIR`, `IMPL_PLAN`…). Las asignaciones son:

  | Skill | Script |
  |---|---|
  | plan | `setup-plan.ps1 -Json` |
  | tasks | `setup-tasks.ps1 -Json` |
  | implement, analyze, converge | `check-prerequisites.ps1 -Json -RequireTasks -IncludeTasks` |
  | clarify | `check-prerequisites.ps1 -Json -PathsOnly` |
  | constitution | `resolve-template.ps1 constitution-template -Json` |

  `/speckit-specify` ya no usa script: el agente crea la carpeta y `feature.json`.
- **Alternativa `--script py`** (añadida en la 0.12.4, 2-jul-2026; empaquetado corregido en la 0.14.0):
  - Scripts Python equivalentes, de biblioteca estándar y UTF-8 explícito.
  - Busca el intérprete en este orden: `.venv\Scripts\python.exe` del proyecto → `python3` → `python`. Descarta el alias de Microsoft Store (#3304/#3383), que en esta máquina existe: `python3` apunta a `WindowsApps`.
  - Se puede cambiar después con `specify integration upgrade claude --script py`.
- **Riesgo PS 5.1:** en esta máquina solo hay Windows PowerShell 5.1. La CI de Spec Kit prueba en `windows-latest` con Python 3.13/3.14, pero sus tests de PowerShell usan **`pwsh` (7)** si existe. Por eso las regresiones propias de 5.1 aparecen como issues:
  - #2680 (may)
  - #2927 (jun)
  - #3749 (jul)
  - #4333 (ago)

  Todas están corregidas; la de codificación de `feature.json` en la **1.0.2**.
- **Política de ejecución:** dentro de las sesiones de Claude Code la política es `Bypass` a nivel de proceso (observado). Fuera, LocalMachine está *Undefined* (efectivo *Restricted*), así que ejecutar los `.ps1` a mano puede requerir `powershell -ExecutionPolicy Bypass -File ...`.

#### Personalizar plantillas y usarlas en español
- **Orden de resolución de plantillas:**
  1. `.specify/templates/overrides/` (override local, «para ajustes puntuales»)
  2. presets instalados (`.specify/presets/<id>/`, por prioridad)
  3. extensiones
  4. núcleo `.specify/templates/`

  Para ver cuál gana: `specify preset resolve tasks-template` o `specify artifact info template:tasks-template --json`.
- **Comandos:** se «materializan» en `.claude/skills/`. No conviene editarlos a mano: el upgrade detecta el cambio por hash y se bloquea. Para cambiar su comportamiento se crea un **preset** con estrategia `replace`, `prepend`, `append` o `wrap` (`{CORE_TEMPLATE}`) y se prueba con `specify preset add --dev ./mi-preset`.
- **Presets útiles:**
  - Oficiales: `lean` (flujo mínimo: cada comando produce un único fichero sin secciones de plantilla) y `constitution-sync`.
  - Comunitarios:
    - `claude-ask-questions`: `/speckit-clarify` y `/speckit-checklist` con el selector nativo `AskUserQuestion`; cómodo para un único decisor.
    - `explicit-task-dependencies`.
    - `test-first-governance`.
- **Español.** El estado actual:
  - No hay opción de idioma. El #1239 («project-level language configuration that all /speckit.* commands consistently enforce») se cerró como *not planned* el 3-jul-2026. En él se contaba que, aunque la constitución lo exija, el modelo vuelve al inglés en plan/tasks/implement.
  - README solo en inglés, japonés y chino; la documentación, solo en inglés.

  **Práctica recomendada:**
  - Escribir los prompts de `/speckit-*` en español.
  - Poner la regla de idioma en `CLAUDE.md`, que se carga en cada sesión **y en cada subagente**, y también en la constitución: «artefactos en español; se conservan los encabezados de plantilla y los tokens de máquina `T001`, `[P]`, `[US1]`, `FR-001`, `SC-001`, `CHK001`, `[NEEDS CLARIFICATION]`, `P1/P2/P3` y las casillas `- [ ]`».
  - Traducir los encabezados es arriesgado: los comandos buscan secciones por su nombre en inglés («User Scenarios & Testing», «Functional Requirements», «Success Criteria», «Technical Context», «Constitution Check»).
  - Si más adelante se quieren plantillas en español, lo sensato es un **preset propio con estrategia `wrap`**, copiando el enfoque del preset comunitario `zh-cn`:
    - «traducir descripciones, no protocolos»
    - conserva `FR-001`, `SC-001`, `US1`, `T001`, `CHK001`, `[P]`
    - requiere Spec Kit ≥ 1.0.5
    - la demo *pirate-speak* demuestra que un preset puede cambiar toda la terminología
  - En el catálogo no hay preset en español a 30-sep-2026; fuera del catálogo, (sin verificar).
- **Nombres de carpeta y rama:** los helpers solo conservan `[a-z0-9]`, así que «traducción» queda en `traducci` y una descripción sin caracteres ASCII produce `001-` (#4574, abierto). Hay que pedir siempre un nombre corto ASCII (`001-captura-audio`) o pasar `-ShortName`.

#### Actualizar Spec Kit en un proyecto existente sin perder cambios
1. Hacer `git commit` de todo, como base revisable.
2. **CLI:** `specify self upgrade`, o `specify self upgrade --tag v1.0.14` para fijar versión. Detecta si se instaló con uv o pipx. Después, comprobar con `specify self check`.
3. `specify integration status`: lista los ficheros gestionados que se han modificado o faltan.
4. `specify integration upgrade claude`: regenera skills, scripts y plantillas gestionadas. **Se detiene** si hay ediciones locales en ficheros gestionados. `--force` solo tras revisarlas.
5. `specify extension update` (y `specify preset update <id>` para los presets).
6. Revisar el `git diff`.

**Nunca se tocan:** `specs/`, `.specify/memory/constitution.md` y el código.

Las plantillas y scripts compartidos solo se refrescan si siguen idénticos a la copia gestionada. Por eso las personalizaciones deben vivir en `overrides/` o en un preset. Como vía de recuperación queda `specify init --here --force --integration claude`, que conserva la constitución.

Tras actualizar Claude Code, a veces hay que reiniciar el IDE para que aparezcan las skills.

#### Licencia
MIT, tanto el repo como el paquete de PyPI. Las extensiones y presets comunitarios tienen licencias y mantenedores propios; hay que revisar su código antes de instalarlos (lo pide la propia documentación).

#### Problemas conocidos en Windows (issues de GitHub)

| Issue | Estado | Resumen | Relevancia aquí |
|---|---|---|---|
| #4333 | Cerrado (28-ago; corregido en 1.0.2) | PS 5.1 leía `feature.json` UTF-8 como ANSI y creaba una segunda carpeta `specs/` con mojibake | Alta si hay nombres con tildes; hoy corregido |
| #3749 | Cerrado (jul) | `common.ps1` usaba una API solo de .NET Core, lo que rompía `SPECIFY_INIT_DIR` en PS 5.1 | Baja |
| #2927 | Cerrado (17-jun) | `specify init` se colgaba en Windows (PS 5.1) | Corregido desde la 0.10.x |
| #2680 | Cerrado (may) | ¿PS 7 como requisito no documentado? Problema de codificación | Histórico |
| #3304 / #3383 | Cerrados (jul) | El alias `python3` de Microsoft Store rompía los scripts `sh`/`py` | Esta máquina tiene ese alias; hoy se detecta |
| #4574 | **Abierto** | Descripciones sin caracteres ASCII → carpeta `001-` sin nombre | Usar nombres cortos ASCII |
| #4270 | **Abierto** | La numeración de features no es atómica: invocaciones concurrentes pueden pisar el mismo `spec.md` | Crear features solo desde el orquestador, de una en una |
| #1923 | Abierto (antiguo, v0.2.1) | Ruta base de `specs/` en `common.ps1` | Probablemente obsoleto (sin verificar) |
| #4443 | Cerrado (sep) | La composición de presets fallaba si el `python3` del sistema no tenía PyYAML | Solo si se usan presets con scripts |
| #2031 | Cerrado (abr) | `.claude/commands/` no reconocido → migración a skills | Explica el formato actual |

#### Extensiones y presets comunitarios relevantes para trabajar en paralelo

Todos son de terceros; el código no se ha auditado. Versiones tomadas del catálogo comunitario del 30-sep-2026.

| Componente | Qué hace | Notas |
|---|---|---|
| `schedule` (jfranc38/spec-kit-schedule) v0.7.4 | Convierte `tasks.md` en **rondas óptimas para subagentes** (CP-SAT), teniendo en cuenta la ruta crítica y la exclusión mutua por fichero. `/speckit-schedule-run` y `/speckit-schedule-implement` | Sin worktrees: todos en el mismo checkout, protegidos por el mutex de ficheros. **El orquestador es el único que escribe `tasks.md`.** Pide Python 3.10–3.12 + uv (entorno propio) |
| `worktrees` (dango85/spec-kit-worktree-parallel) | Un worktree por feature (`.worktrees/NNN-x` o carpeta hermana) mediante un hook `after_specify` | Aísla features en paralelo, no tareas. Sin guía para Windows |
| `worktree` (Quratulain-bilal) | Worktrees aislados por feature | — |
| `orchestrator` (Quratulain-bilal) | Estado entre features y detección de conflictos entre especificaciones paralelas | Solo lectura |
| `orchestration-task-context-management` | «Unidades de trabajo» para subagentes en `tasks.md` | v0.0.0 |
| `agent-assign` (xymelon) | Asigna agentes especializados de Claude Code a cada tarea | — |
| `maqa` v0.3.1 | Coordinador → feature → QA, con GitHub Issues como fuente de verdad; despacho paralelo o secuencial | Requiere GitHub |
| `fleet` v1.1.0 | Orquesta el ciclo completo con puertas humanas | — |
| `speckit-superpowers-bridge`, `superb`, `superspec` | Puentes con Superpowers (TDD, revisión, subagentes) | Uno de ellos declara «verified for Claude Code» |
| **cc-spex** (rhuss; plugin de Claude Code, Apache-2.0) | Rasgos sobre Spec Kit: puertas de calidad, worktree en `.claude/worktrees/<rama>` tras specify, implementación paralela con Agent Teams | La 5.9.x es la estable; la 6.0 está en desarrollo |
| Preset `explicit-task-dependencies` v1.0.0 | `(depends on T###)` + «Execution Wave DAG» | Útil para planificar olas |
| Preset `parallel-autonomous-run-governance` | Gobierno de campañas autónomas en paralelo | Pesado |

### 3.2 OpenSpec (`Fission-AI/OpenSpec`)
- **Versión y tracción:** v1.13.2 (23-sep-2026), MIT, 70,8k★. Se instala con `npm install -g @fission-ai/openspec@latest` (Node ≥ 20.19.0) y luego `openspec init --tools claude`.
- **Filosofía:** «fluid not rigid, iterative not waterfall, built for brownfield».
- **Artefactos:**
  - Especificaciones vivas en `openspec/specs/<capacidad>/spec.md`.
  - Cada cambio va en `openspec/changes/<cambio>/` con `proposal.md`, `design.md`, `tasks.md` y `specs/` (deltas `ADDED`/`MODIFIED`/`REMOVED` con requisitos `SHALL` y escenarios WHEN/THEN).
  - Al archivar, se mueve a `openspec/changes/archive/AAAA-MM-DD-<cambio>/` y los deltas se fusionan en las especificaciones vivas.
- **Claude Code:** skills `.claude/skills/openspec-*/SKILL.md` y comandos `.claude/commands/opsx/<id>.md`, que se invocan como `/opsx:propose`, `/opsx:explore`, `/opsx:apply`, `/opsx:update`, `/opsx:sync` y `/opsx:archive`. En el perfil ampliado hay además `/opsx:new`, `/opsx:continue`, `/opsx:ff`, `/opsx:verify`, `/opsx:bulk-archive` y `/opsx:onboard`.
- **Español nativo:** `openspec init --language "Spanish"`, o en `openspec/config.yaml`:

  ```yaml
  context: |
    Idioma: Español
    Todos los artefactos deben escribirse en español.
  ```

  Las palabras `SHALL`/`MUST` y los encabezados estructurales siguen en inglés porque la validación depende de ellos. La 1.13.2 corrigió un falso positivo de `validate --strict` con textos en español que empiezan por «Todo el…».
- **Paralelismo:**
  - Cambios paralelos sin conflicto (cada uno en su carpeta) y «one change, one owner».
  - Los conflictos solo aparecen al archivar dos cambios que tocan el mismo requisito. Ya hay validación que lo detecta y el archivado es seguro.
  - `tasks.md` es una lista numerada (`- [ ] 1.1 …`) **sin marca de paralelismo ni dependencias**, así que sirve peor como cola de trabajo para varios obreros.
- **Windows:** correcciones recientes de CRLF, `EPERM` al archivar y un *lock* residual.
- **Encaje:** muy bueno para mantener un proyecto vivo con cambios pequeños. Para descomponer una aplicación nueva en módulos paralelos, Spec Kit da más estructura (fases, historias, `[P]`, contratos).

### 3.3 BMAD Method (`bmad-code-org/BMAD-METHOD`)
- **Versión:** v6.12.0 (3-sep-2026). Licencia MIT; «BMad» es marca registrada de BMad Code, LLC. 53,7k★.
- **Instalación:** `npx skills add bmad-code-org/BMAD-METHOD` o el marketplace de Claude Code (`/plugin marketplace add bmad-code-org/bmad-plugins`), y después `bmad setup`. Requiere **uv + Python ≥ 3.11** para las skills renderizadas, además de Node/npm.
- **Proceso:** aclarar → planificar → construir y verificar → aprender, con skills y personas (`bmad-agent-analyst`, `-pm`, `-architect`, `-ux-designer`, `-dev`), `bmad-prd`, `bmad-architecture`, `bmad-build`, `bmad-code-review` y `bmad-party-mode`. Se ajusta al tamaño del cambio.
- **Configuración:** TOML por capas en `_bmad/`. Los breaking changes son frecuentes; la 6.12 y la versión sin publicar migran las rutas de salida.
- **Idioma:** `document_output_language` y `communication_language`, que se aplican al escribir ficheros.
- **Paralelismo:** solo entre épicas independientes y «con una capa de coordinación superior». El módulo aparte «BMad Loop» construye épicas sin supervisión.
- **Encaje:** demasiada ceremonia y demasiados roles para un solo decisor. Útil si se quiere un PRD o una arquitectura muy trabajados, pero duplica lo que el orquestador ya hace.

### 3.4 Especificaciones estilo Kiro: Kiro (AWS) y cc-sdd
- **Kiro** (IDE y CLI propietarios):
  - Formato `.kiro/specs/<nombre>/requirements.md` (historias + criterios EARS, «WHEN … THE SYSTEM SHALL …»), o `bugfix.md` para correcciones.
  - Además, `design.md` y `tasks.md`.
  - Tiene *steering files* y **ejecución paralela nativa por olas**: agrupa las tareas independientes y las lanza a la vez. Según una fuente secundaria, en tandas de 3 (sin verificar).
  - No funciona sobre Claude Code. Spec Kit tiene integración `kiro-cli` (alias `kiro`).
- **cc-sdd** (`gotalab/cc-sdd`), v3.1.0 (23-sep-2026), MIT, 3,7k★. Reproduce el flujo de Kiro con skills de Claude Code.
  - **Instalación:** `npx cc-sdd@latest --lang es` (por defecto instala skills de Claude Code; 14 idiomas, **español incluido**).
  - **Skills:** `kiro-discovery`, `kiro-spec-init`, `-requirements`, `-design`, `-tasks`, `kiro-impl`, `kiro-spec-batch`, `kiro-validate-gap` y `kiro-steering`.
  - `design.md` incluye un «File Structure Plan» del que salen los límites de las tareas.
  - **Tareas:** `- [ ] 2.1 (P) …` con `_Boundary:_` y `_Depends:_`; la regla exige `_Boundary:_` en toda tarea `(P)`.
  - `/kiro-impl` hace **una tarea por iteración** con un implementador nuevo (TDD detrás de un *feature flag*), un revisor independiente y un paso de depuración automático.
  - `/kiro-spec-batch` crea varias especificaciones en paralelo por olas de dependencia.
  - Es la alternativa más próxima a Spec Kit si se prefiere EARS + español nativo, pero su comunidad es 40 veces menor.

### 3.5 Agent OS v3 (`buildermethods/agent-os`)
- **Versión:** v3.0 (20-ene-2026), MIT, 5,5k★. Último push: 29-ago-2026.
- **Cambio de enfoque en v3:** se centra en **estándares** (`/discover-standards`, `/inject-standards`, `/index-standards`), `/plan-product` y `/shape-spec`.
- **Qué deja al agente:** la especificación la delega en el *plan mode* del agente, y la descomposición en tareas y la orquestación de la implementación «se retiran porque los modelos frontera ya lo hacen» (CHANGELOG).
- **Instalación:** scripts bash (`project-install.sh`); en Windows haría falta Git Bash (sin verificar).
- **Encaje:** útil como fuente de ideas para documentar estándares de código. No aporta cola de tareas ni paralelismo.

### 3.6 Otras opciones relevantes en 2026
- **Superpowers** (obra, v6.4.2, 293k★, MIT). Metodología en skills: `brainstorming`, `writing-plans`, `subagent-driven-development`, `dispatching-parallel-agents`, `using-git-worktrees`, `test-driven-development`, `requesting-code-review`, `finishing-a-development-branch`.
  - Su «subagent-driven development» es **secuencial**: subagente nuevo por tarea, revisión de spec y de calidad, y revisión final.
  - Registra decisiones en un *ledger* («Ruling: … — why — cost if wrong»).
  - Complementa a Spec Kit (hay tres puentes en el catálogo). Puede chocar con las puertas humanas porque está diseñado para no pausar.
- **CCPM** (automazeio). PRD → épica → tareas → GitHub Issues → agentes paralelos en **un worktree por épica**, con metadatos `depends_on` / `conflicts_with` / `parallel`. Requiere `gh` autenticado y un repo en GitHub. Sin actividad desde marzo de 2026.
- **Tessl**. Filosofía «spec-as-source» (el código se regenera desde la especificación). Framework en beta cerrada y Spec Registry en beta abierta, vía MCP. Inmaduro para este caso, según reseñas de terceros.
- **GSD (get-shit-done)**. Archivado el 26-jun-2026; continúa como `open-gsd/gsd-core`.
- **Task Master AI**. Última release 0.43.1 (31-mar-2026), licencia no estándar (NOASSERTION).
- **spec-workflow-mcp**. GPL-3.0.
- **Claude Code sin framework.** Entrevista con `AskUserQuestion` → `SPEC.md` → modo plan → subagentes. Es la línea base mínima que recomienda la propia guía de buenas prácticas de Claude Code: especificaciones autocontenidas que nombren ficheros e interfaces, digan qué queda fuera de alcance y terminen con una verificación extremo a extremo.
- **Opinión externa.** Thoughtworks Technology Radar mantiene SDD en **«Assess»**. Advierte de flujos «elaborate and opinionated», especificaciones largas y difíciles de revisar, y del riesgo de «relearning a bitter lesson». Motivo para usar el flujo con mesura (preset `lean` y puertas solo donde aportan).

### 3.7 Encaje con la orquestación paralela (orquestador + obreros)

#### a) Primitivas disponibles en Claude Code (docs oficiales, sep-2026)

| Primitiva | Qué aporta | Límites y notas |
|---|---|---|
| **Subagentes** (`.claude/agents/*.md`) | Contexto propio. Frontmatter: `name`, `description`, `tools`, `disallowedTools`, `model`, `permissionMode`, `maxTurns`, `skills`, `hooks`, `memory`, `background`, `effort`, **`isolation: worktree`** | Paralelos y en segundo plano por defecto. Máximo 20 concurrentes (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`). Anidamiento hasta 3 niveles. **No pueden usar `AskUserQuestion`**, así que no preguntan al humano. |
| **`isolation: worktree`** | Worktree temporal por subagente. Bloquea ediciones y comandos git fuera del worktree | Se borra solo si no hubo cambios; si los hubo, queda en disco hasta el barrido. **Por defecto parte de la rama por defecto del remoto (`"fresh"`), no del HEAD actual**: hay que poner `"worktree": {"baseRef": "head"}` para que los obreros vean los contratos y tareas del orquestador (sin remoto, cae a HEAD local). |
| **`.worktreeinclude`** | Copia en cada worktree nuevo los ficheros ignorados por git (`.env`, etc.) | Solo ficheros que estén en `.gitignore` |
| **`claude --worktree <nombre>`** | Sesión manual en `.claude/worktrees/<nombre>/`, rama `worktree-<nombre>` | Añadir `.claude/worktrees/` a `.gitignore`. El repo necesita al menos un commit. |
| **Agent teams** | Líder + compañeros, lista de tareas compartida con bloqueo, mensajería | **Experimental** (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). **No aísla con worktrees**: hay que repartir ficheros. El modo de paneles no funciona en Windows Terminal ni en el terminal de VS Code. Se recomiendan 3-5 compañeros con 5-6 tareas cada uno. |
| **Flujos dinámicos (workflows)** | Script JS con `agent()`, `parallel()` y `pipeline()`; reanudable; se guarda en `.claude/workflows/` | Hasta 16 agentes concurrentes. **Sin entrada del usuario a mitad de ejecución**, así que hay que hacer un flujo por ola y dejar la puerta humana entre olas. |
| **`/batch <instrucción>`** | Divide un cambio grande en 5-30 unidades, cada una en su worktree | Pensado para migraciones mecánicas, no para features con contratos |
| **Hooks** (`PreToolUse` y otros) | Deterministas; por ejemplo, bloquear escrituras en `contratos/` | Los hooks del frontmatter del subagente se ignoran en subagentes que vienen de plugins |

**Específico de Windows:**
- Las aprobaciones de permisos concedidas dentro de un worktree **se quedan en ese worktree**, así que hay que preconfigurarlas en `.claude/settings.json`, que está versionado.
- Antes de la **v2.1.205**, borrar un worktree que contuviera un *junction* podía borrar la carpeta a la que apuntaba. Aquí `claude.exe` es la **2.1.201**: hay que actualizar.

#### b) Qué ofrece Spec Kit para trabajar en paralelo
- La marca `[P]`, las fases con *checkpoint* y las historias independientes. La plantilla advierte: «Avoid: same file conflicts, cross-story dependencies».
- La guía oficial *Handling Complex Features*:
  1. acotar `/speckit-implement` a N tareas o a una fase;
  2. «`/speckit.implement delegate each parallel [P] task to a sub-agent`»;
  3. combinar ambas;
  4. «spec of specs» (hoja de ruta de sub-features; «para construir porciones independientes en paralelo, usa worktrees distintos»).
- `SPECIFY_FEATURE_NO_PERSIST=1` (1.0.11), para varios agentes concurrentes en el mismo checkout (#4128).
- La guía *Contract-Driven Development*: «Agree on the contract before dependent implementation», «One side owns the authoritative contract». Los contratos se versionan y no se editan en copias.
- Postura de los mantenedores (discusión #2762, jun-2026): el núcleo sigue siendo agnóstico del agente y la orquestación multiagente va en extensiones o presets. De esa discusión sale un vocabulario útil de estados para obreros: `DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED`, y la regla «no se marca hecha una tarea sin evidencia registrada».

#### c) Trampas concretas al combinar Spec Kit con obreros en worktrees
1. **`.specify/feature.json` está en `.gitignore`**, así que no existe en los worktrees y cualquier `/speckit-*` lanzado allí no sabrá qué feature es la activa. Solución: que los obreros **no ejecuten skills de Spec Kit**. Si hiciera falta, `SPECIFY_FEATURE_DIRECTORY` o `.worktreeinclude` con `.specify/feature.json`.
2. **La numeración de features no es atómica** (#4270, abierto). `/speckit-specify` solo lo ejecuta el orquestador, y de uno en uno.
3. **Varios escritores de `tasks.md`** provocan conflictos de merge en líneas contiguas. Regla: **el orquestador es el único que escribe `tasks.md`**, como hace spec-kit-schedule.
4. **Ficheros «calientes»:** `pyproject.toml`, `uv.lock`, `__init__.py` que reexportan, `CLAUDE.md`, configuración común. Los posee el orquestador y se crean en la Fase 1-2. Los obreros no añaden dependencias: las piden con `NEEDS_CONTEXT`.
5. **Python:** cada worktree necesita su propio `.venv` (`uv sync`, barato gracias a la caché de uv). Si se reutiliza un venv con instalación editable del checkout principal, **los tests prueban el código equivocado**. Además, con `--script py`, si existía `.venv` al hacer `init` las skills llevan fijado `.venv/Scripts/python.exe`.
6. **La base del worktree:** hay que fijar `baseRef: "head"` y **hacer commit de spec, plan, contratos y tareas antes de lanzar cada ola**.
7. **Tests con hardware de audio** (WASAPI, dispositivos) en paralelo son inestables. En los obreros se usan fakes/mocks; los tests con dispositivo se marcan (`@pytest.mark.hw`) y solo los ejecuta el orquestador al integrar.
8. **Coste:** los agentes paralelos consumen entre 3 y 6 veces más tokens (Böttger), lo que cuenta contra los límites de la suscripción.

#### d) Experiencias y prácticas documentadas
- **Dominic Böttger, «speckit.team-implement» (6-feb-2026):** Spec Kit + Agent Teams de Claude Code.
  - Reparte las tareas en *streams* por **análisis de conflicto de rutas**: dos tareas chocan si comparten fichero o prefijo de dos segmentos, y los componentes conexos van al mismo stream.
  - Usa 2-4 agentes especialistas + un agente QA/seguridad obligatorio que «verifica y no implementa».
  - Hace **un commit por tarea**.
  - Resultado: 34 tareas → 3 streams, 38 commits, puertas de calidad superadas.
  - Lecciones: la calidad de la especificación se amplifica con el paralelismo; las rutas de fichero son mejores que las palabras clave; la **propiedad de ficheros no es negociable**; el tamaño óptimo es de 2-4 agentes; el estado de las tareas se retrasa (limitación de teams); el coste es de 3-6 veces más tokens.
- **spec-kit-schedule:** reparte las tareas en carriles con exclusión mutua por fichero, calcula rondas que respetan barreras de fase, escribe un *brief* autocontenido por carril y deja al orquestador como único escritor de `tasks.md`. Si un carril falla, la ronda no avanza.
- **Claude Code (docs):** «Two teammates editing the same file leads to overwrites. Break the work so each teammate owns a different set of files». También el patrón escritor/revisor (el revisor en un contexto nuevo) y la recomendación de dar siempre una verificación ejecutable (tests) y pedir evidencia, no afirmaciones.
- **OpenSpec:** «One change, one owner». **BMAD:** los streams paralelos solo tienen sentido «when dependencies and integration boundaries are explicit».

---

## 4. Recomendación para InstantTraductor

### 4.1 Decisión
Usar **GitHub Spec Kit 1.0.13** (fijado) como columna vertebral del SDD, con integración `claude` y scripts `ps`, más un **protocolo de orquestación propio**: agentes `implementador` y `revisor` de Claude Code con worktrees, olas y puertas humanas. OpenSpec queda como plan B, o para la fase de mantenimiento si el flujo de Spec Kit resulta pesado.

**Motivos:**
1. **Madurez y comunidad** muy superiores: 139,6k★, releases semanales, respaldo de GitHub y documentación extensa. Menos riesgo de abandono (GSD se archivó y CCPM está parado).
2. **Encaja con la paralelización:** fases con *checkpoint*, Foundational bloqueante (el lugar natural para **congelar contratos**), `contracts/` en el plan, `[P]` con semántica de «ficheros distintos», historias independientes y rutas exactas por tarea. Es justo lo que necesita un orquestador para calcular olas y propiedad de ficheros.
3. **Windows de primera clase:** scripts PowerShell (o `py`) y CI en `windows-latest`. Los bugs de PS 5.1 de 2026 están corregidos.
4. **Un solo humano decide:** las puertas son explícitas y opcionales (clarify, checklist, analyze). El preset `lean` permite aligerar las features pequeñas y `claude-ask-questions` da preguntas con selector. Las skills son invocables por el propio orquestador.
5. **Extensible sin bifurcar:** overrides y presets sobreviven a los upgrades. Si el protocolo propio madura, se puede empaquetar como preset o extensión, o evaluar `schedule` o `explicit-task-dependencies`.
6. **Riesgo asumible con el idioma:** el contenido en español funciona con instrucciones. La carencia de idioma nativo es la principal desventaja frente a OpenSpec o cc-sdd.

**Tipo de script:** `ps`, porque es el predeterminado en Windows y el más usado. Si aparecen fallos de PS 5.1, se pasa a `py` con `specify integration upgrade claude --script py`: usa el Python 3.13 instalado, es independiente de la versión de PowerShell y está probado en la CI de Windows.

### 4.2 Preparación única

Pasos propuestos para el humano o el orquestador; no los ha ejecutado este informe.

1. **Actualizar Claude Code** a ≥ 2.1.286 (`claude update` o `winget upgrade`). La 2.1.201 instalada es anterior a varias correcciones de worktrees, entre ellas la de *junctions* en Windows (v2.1.205).
2. **Preparar git:**
   - `git init` + primer commit (los worktrees lo necesitan).
   - `git config core.longpaths true` (se reprodujo un fallo de MAX_PATH al clonar en rutas largas).
   - `.gitattributes` con `* text=auto` y `*.md`/`*.py` con `eol=lf`, para evitar diffs de fichero completo por CRLF entre worktrees.
   - `.gitignore` con `.claude/worktrees/`, `.venv/` y `__pycache__/`.
3. **Instalar e inicializar Spec Kit:** `uv tool install specify-cli==1.0.13` y `specify init --here --force --integration claude --script ps`. Opcional: `specify extension add git` con `auto_commit` desactivado (así el orquestador decide los commits).
4. **Constitución** (`/speckit-constitution`, en español). Principios sugeridos:
   - Windows 11 primero, Python 3.13.
   - Presupuesto de latencia de extremo a extremo.
   - Privacidad y funcionamiento local.
   - Tests con fakes para dispositivos de audio.
   - **Contratos primero y congelados antes de paralelizar.**
   - Propiedad de ficheros.
   - Idioma: documentos en español, identificadores de código a decidir.
5. **`CLAUDE.md`** breve:
   - regla de idioma y tokens de máquina;
   - comandos: `uv run pytest`, `uv run ruff check`;
   - «los obreros no tocan `tasks.md`, `contratos/`, `pyproject.toml` ni `uv.lock`»;
   - nombres de feature en ASCII.
6. **`.claude/settings.json`** (versionado; sintaxis a validar con la versión instalada):
   ```json
   {
     "worktree": { "baseRef": "head" },
     "permissions": { "allow": ["Bash(uv run pytest *)", "Bash(uv run ruff *)", "Bash(uv sync *)", "Bash(git add *)", "Bash(git commit *)"] }
   }
   ```
7. **Agentes** en `.claude/agents/`:
   - **`implementador.md`**: `isolation: worktree`, `permissionMode: acceptEdits`, `tools` limitadas (Read, Grep, Glob, Edit, Write, Bash o PowerShell), `model` a decidir. Lleva un hook `PreToolUse` que **bloquea con código 2** las escrituras en `src/instanttraductor/contratos/**`, `specs/**/contracts/**`, `specs/**/tasks.md`, `pyproject.toml` y `uv.lock`; la sintaxis YAML del hook en el frontmatter está (sin verificar).
   - **`revisor.md`**: solo lectura, contexto nuevo, compara el diff con spec, plan, contratos y tareas, y señala solo huecos de corrección o de requisitos.

### 4.3 Ciclo por feature con puertas humanas (H)
1. `/speckit-specify <descripción en español>` pidiendo un nombre corto ASCII → `/speckit-clarify` (responde el humano). **H1: especificación aprobada.**
2. `/speckit-plan <stack y arquitectura>` → `research.md`, `data-model.md`, **`contracts/`**, `quickstart.md`. Para una app de escritorio, los contratos son las interfaces entre las etapas del pipeline (captura → reconocimiento de voz → traducción → síntesis de voz → reproducción → UI): tipos de mensaje, errores, modelo de hilos/colas, esquema de configuración y presupuesto de latencia por etapa.
3. `/speckit-tasks` con instrucciones como: «rutas exactas en todas las tareas; `[P]` solo si los ficheros son disjuntos; anota `(depends on T###)`; en la Fase 2, implementa los contratos en código (`typing.Protocol` + `@dataclass(frozen=True)`), sus tests de contrato y los fakes». Después, `/speckit-analyze` y corregir en origen. **H2: plan, contratos y tareas aprobados.**
4. **Fases 1-2** (Setup + Foundational): las hace el orquestador o un único obrero, en secuencia. Commit y **tag `contratos-NNN-v1`**. **H3: contratos congelados.**
5. **Olas de historias:**
   - El orquestador calcula las olas: tareas pendientes sin dependencias abiertas, agrupadas por conjuntos de ficheros disjuntos. Elige 2-4 obreros.
   - Lanza los obreros en paralelo (subagente `implementador`, en segundo plano), cada uno con su *brief* (§4.4).
6. **Integración, en secuencia y por orden de dependencia:**
   - Por cada obrero: `git merge --no-ff <rama-del-worktree>` en la rama de la feature. El nombre exacto de esa rama está (sin verificar); se obtiene con `git worktree list`.
   - Después: `uv run pytest` + `ruff` + los tests de contrato.
   - Si sale rojo, se revierte (`git revert -m 1`) y se devuelve al obrero con la salida del fallo.
   - Si hay conflicto en ficheros de un obrero, el mapa de propiedad estaba mal y se corrige. Si es en `uv.lock`, se regenera con `uv lock` en vez de resolverlo a mano.
   - Al final de la ola: marcar `[X]` en `tasks.md` (único escritor), lanzar el `revisor` sobre el diff de la ola y pasar a la siguiente. Las siguientes olas parten del HEAD actualizado.
7. `/speckit-converge` hasta «Converged». Los tests con hardware los ejecuta el orquestador. **H4: revisión final** y merge a `main`.

Si hay que cambiar un contrato a mitad de camino: se para la ola, el orquestador propone el cambio al humano (breve ADR en `research.md`), se crea el tag `-v2`, se relanzan los tests de contrato y se vuelven a despachar las tareas afectadas.

### 4.4 Plantilla de *brief* para un obrero, e informe de vuelta
```text
BRIEF · Feature 001-captura-audio · Ola 2 · Obrero B
Tareas (en orden): T011, T016
Ficheros que POSEES (crear/modificar): src/instanttraductor/asr/**, tests/unit/asr/**
Solo lectura: src/instanttraductor/contratos/** (tag contratos-001-v1), specs/001-captura-audio/{spec,plan,data-model}.md, specs/001-captura-audio/contracts/**
Prohibido: specs/**/tasks.md, pyproject.toml, uv.lock, CLAUDE.md, cualquier otro fichero fuera de tu propiedad
Entorno: ejecuta "uv sync" en tu worktree antes de los tests; usa los fakes de tests/fakes/ (nada de dispositivos reales)
Hecho = uv run pytest tests/unit/asr tests/contract -q en verde + uv run ruff check src/instanttraductor/asr sin errores
Commits: uno por tarea, mensaje "T011: <resumen>"
Devuelve: ESTADO (DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED), commits, ficheros tocados, salida de tests, dudas o decisiones
```

### 4.5 Ejemplo de `tasks.md` (tokens en inglés, texto en español)
```markdown
## Phase 2: Foundational (Blocking Prerequisites)
- [ ] T004 Definir contratos del pipeline en src/instanttraductor/contratos/pipeline.py (Protocols FuenteAudio, Reconocedor, Traductor, Sintetizador, SalidaAudio; dataclasses BloqueAudio, SegmentoTexto)
- [ ] T005 [P] Fakes de contrato en tests/fakes/pipeline_fakes.py (depends on T004)
- [ ] T006 [P] Tests de contrato en tests/contract/test_pipeline.py (depends on T004)
**Checkpoint**: contratos congelados (tag contratos-001-v1)

## Phase 3: User Story 1 - Oír en español el audio del sistema (Priority: P1) 🎯 MVP
- [ ] T010 [P] [US1] Captura en bucle (loopback) WASAPI en src/instanttraductor/captura/wasapi.py
- [ ] T011 [P] [US1] Motor de reconocimiento de voz en src/instanttraductor/asr/motor.py
- [ ] T012 [P] [US1] Motor de traducción en src/instanttraductor/traduccion/motor.py
- [ ] T013 [P] [US1] Motor de síntesis de voz en src/instanttraductor/tts/motor.py
- [ ] T014 [US1] Orquestación del pipeline en src/instanttraductor/pipeline.py (depends on T010, T011, T012, T013)
```
Las tareas T010-T013 forman una ola de 4 obreros con ficheros disjuntos. La T014 va en la ola siguiente.

### 4.6 Qué dejar para más adelante
- Agent Teams: son experimentales, no aíslan con worktrees y el modo de paneles no funciona en Windows Terminal. Úsense, si acaso, para revisión o investigación.
- Extensiones comunitarias de paralelismo (`schedule`, `worktrees`, cc-spex): evaluarlas en una feature piloto antes de adoptarlas.
- Codificar las olas como flujo dinámico guardado (`.claude/workflows/`), cuando el protocolo manual esté estable.
- Preset en español con estrategia `wrap`.
- `taskstoissues`/GitHub: solo si se crea el remoto y se instala `gh`.

---

## 5. Riesgos y preguntas abiertas

### 5.1 Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Spec Kit cambia muy rápido: ha habido cambios incompatibles (`--ai`, git opcional, paso a skills) | Medio | Fijar la versión (`==1.0.13`), actualizar a propósito con el flujo de §3.1 y personalizar solo con overrides o presets |
| Regresiones propias de PS 5.1 (la CI prueba sobre todo con pwsh 7) | Bajo-medio | Nombres ASCII; si falla, `--script py` |
| El modelo vuelve al inglés en plan/tasks (#1239) | Bajo | Regla en `CLAUDE.md`, recordatorio en cada prompt, revisión en las puertas |
| Conflictos de integración o pérdida de trabajo por escrituras concurrentes | Alto | Worktrees + propiedad de ficheros + hook que bloquea + único escritor de `tasks.md` + integración secuencial con tests |
| Contratos mal definidos → los obreros divergen | Alto | Puerta H2/H3, tests de contrato, tag inmutable, cambios solo vía orquestador y humano |
| Worktrees basados en la rama equivocada (por defecto `"fresh"`) | Alto | `worktree.baseRef: "head"` y commit antes de cada ola |
| Borrado de *junctions* en Windows con Claude Code < 2.1.205 | Alto (pérdida de datos) | Actualizar Claude Code antes de usar worktrees |
| Tests de audio inestables o bloqueos de dispositivos en paralelo | Medio | Fakes en los obreros; tests con hardware solo al integrar |
| Coste de tokens 3-6 veces mayor; límites de la suscripción | Medio | 2-4 obreros, olas pequeñas, modelos más baratos para los obreros si la calidad lo permite |
| Extensiones de terceros (seguridad y mantenimiento) | Medio | Revisar el código, fijar versión, piloto aislado |
| Sobreespecificación (Thoughtworks: «Assess»; especificaciones largas) | Medio | Preset `lean` o saltar puertas en features pequeñas; mantener las especificaciones cortas |

### 5.2 Hallazgos del entorno (comprobaciones de solo lectura)
- **`uv` 0.12.21 ya está en PATH** (`...\WinGet\Links\uv.exe`), en contra de lo que decía el contexto. Hay que confirmar si lo instaló alguien.
- **`claude.exe` 2.1.201** (WinGet, del 3-jul-2026); la última es la 2.1.286 (30-sep-2026). Parece que se usa la extensión de VS Code, que puede traer su propia versión (sin verificar).
- `python3` apunta al alias de Microsoft Store (`WindowsApps`) y `python` es el 3.13 real. Spec Kit ya gestiona ese caso.
- Solo hay Windows PowerShell 5.1 (sin `pwsh`), y no hay `gh` ni `specify`.
- Política de ejecución: `Process = Bypass` dentro de Claude Code; `LocalMachine = Undefined` (efectivo *Restricted*) fuera.

### 5.3 Preguntas abiertas para el decisor
1. ¿Identificadores de código en inglés (recomendado por compatibilidad con librerías) o en español sin tildes? Los documentos van en español en cualquier caso.
2. ¿Flujo completo (9 pasos) o `lean` más clarify y analyze? ¿Qué puertas H1-H4 son obligatorias?
3. ¿Scripts `ps` (predeterminado) o `py`? ¿Instalar PowerShell 7? Está (sin verificar) si la herramienta PowerShell de Claude Code lo usaría.
4. ¿Cuántos obreros por ola (propuesta: 2-4) y con qué modelo (Opus en todos o más barato en los obreros)?
5. ¿Habrá remoto en GitHub? Afecta a la base de los worktrees, a `taskstoissues` y a instalar `gh`.
6. ¿Se adopta la extensión `git` (ramas `NNN-`) o gestiona las ramas el orquestador?
7. ¿Se evaluará `spec-kit-schedule` o `explicit-task-dependencies` en una feature piloto?
8. ¿Se crea un preset de plantillas en español ahora o se espera a validar el flujo?

---

## 6. Fuentes

**Spec Kit (primarias)**
- https://github.com/github/spec-kit (README, LICENSE, CHANGELOG.md, pyproject.toml)
- https://github.com/github/spec-kit/releases (v1.0.13, 29-sep-2026)
- https://pypi.org/project/specify-cli/
- https://github.github.com/spec-kit/installation.html
- https://github.github.com/spec-kit/upgrade.html
- https://github.github.com/spec-kit/quickstart.html
- https://github.github.com/spec-kit/reference/integrations.html
- https://github.com/github/spec-kit/blob/main/docs/reference/agentic-sdd.md
- https://github.com/github/spec-kit/blob/main/docs/reference/core.md
- https://github.com/github/spec-kit/blob/main/docs/reference/presets.md
- https://github.com/github/spec-kit/blob/main/docs/reference/artifacts.md
- https://github.com/github/spec-kit/blob/main/docs/guides/customization.md
- https://github.com/github/spec-kit/blob/main/docs/guides/existing-projects.md
- https://github.com/github/spec-kit/blob/main/docs/guides/contract-driven-development.md
- https://github.com/github/spec-kit/blob/main/docs/concepts/complex-features.md
- https://github.com/github/spec-kit/blob/main/docs/concepts/spec-of-specs.md
- https://github.com/github/spec-kit/blob/main/docs/concepts/spec-persistence.md
- https://github.com/github/spec-kit/blob/main/templates/tasks-template.md
- https://github.com/github/spec-kit/blob/main/templates/commands/tasks.md
- https://github.com/github/spec-kit/blob/main/templates/commands/implement.md
- https://github.com/github/spec-kit/blob/main/templates/commands/specify.md
- https://github.com/github/spec-kit/blob/main/scripts/powershell/create-new-feature.ps1
- https://github.com/github/spec-kit/blob/main/src/specify_cli/integrations/claude/__init__.py
- https://github.com/github/spec-kit/blob/main/extensions/git/README.md
- https://github.com/github/spec-kit/blob/main/extensions/agent-context/README.md
- https://github.com/github/spec-kit/blob/main/presets/lean/README.md
- https://github.com/github/spec-kit/blob/main/extensions/catalog.community.json
- https://github.com/github/spec-kit/blob/main/presets/catalog.community.json
- https://github.com/github/spec-kit/blob/main/.github/workflows/test.yml

**Spec Kit: issues, discusiones y PR**
- https://github.com/github/spec-kit/issues/4333
- https://github.com/github/spec-kit/issues/3749
- https://github.com/github/spec-kit/issues/2927
- https://github.com/github/spec-kit/issues/2680
- https://github.com/github/spec-kit/issues/3304
- https://github.com/github/spec-kit/issues/3383
- https://github.com/github/spec-kit/issues/4574
- https://github.com/github/spec-kit/issues/4270
- https://github.com/github/spec-kit/issues/1923
- https://github.com/github/spec-kit/issues/4443
- https://github.com/github/spec-kit/issues/2031
- https://github.com/github/spec-kit/issues/1239
- https://github.com/github/spec-kit/issues/1934
- https://github.com/github/spec-kit/issues/4128
- https://github.com/github/spec-kit/issues/1476
- https://github.com/github/spec-kit/issues/4418
- https://github.com/github/spec-kit/discussions/2762
- https://github.com/github/spec-kit/pull/4437

**Extensiones y presets de Spec Kit, y experiencias**
- https://github.com/lin52025iq/spec-kit-preset-zh-cn
- https://github.com/jfranc38/spec-kit-schedule
- https://github.com/dango85/spec-kit-worktree-parallel
- https://github.com/Quratulain-bilal/spec-kit-preset-explicit-task-dependencies
- https://github.com/rhuss/cc-spex
- https://github.com/mnriem/spec-kit-pirate-speak-preset-demo
- https://dominic-boettger.com/blog/speckit-team-implement-parallel-ai-agent-teams/

**Alternativas**
- https://github.com/Fission-AI/OpenSpec
  - docs/multi-language.md
  - docs/commands.md
  - docs/supported-tools.md
  - docs/team-workflow.md
  - docs/workflows.md
  - CHANGELOG.md
  - openspec-parallel-merge-plan.md
- https://github.com/bmad-code-org/BMAD-METHOD
  - README.md
  - CHANGELOG.md
  - docs/customize/adopt-bmad-across-a-team.md
  - docs/build/autonomous-development-loops.md
- https://github.com/gotalab/cc-sdd (README.md, CHANGELOG.md, .kiro/settings/rules/tasks-generation.md)
- https://kiro.dev/docs/specs/
- https://kiro.dev/changelog/ide/0-12/
- https://github.com/buildermethods/agent-os (CHANGELOG.md)
- https://buildermethods.com/agent-os
- https://github.com/obra/superpowers (README.md, skills/subagent-driven-development, skills/dispatching-parallel-agents)
- https://github.com/automazeio/ccpm
- https://github.com/gsd-build/get-shit-done
- https://github.com/open-gsd/gsd-core
- https://tessl.io/blog/tessl-launches-spec-driven-framework-and-registry
- https://codemyspec.com/blog/tessl-review
- https://www.thoughtworks.com/en-cl/radar/techniques/spec-driven-development
- https://www.martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html

**Claude Code (docs oficiales)**
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/worktrees
- https://code.claude.com/docs/en/agent-teams
- https://code.claude.com/docs/en/agents
- https://code.claude.com/docs/en/workflows
- https://code.claude.com/docs/en/commands
- https://code.claude.com/docs/en/best-practices
- https://code.claude.com/docs/en/common-workflows
- https://registry.npmjs.org/@anthropic-ai/claude-code (versión 2.1.286, 30-sep-2026)
