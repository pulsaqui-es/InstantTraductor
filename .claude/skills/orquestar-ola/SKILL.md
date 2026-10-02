---
name: orquestar-ola
description: Protocolo del orquestador de InstantTraductor para implementar tareas de una spec con obreros en paralelo. Cubre la planificación de la ola por propiedad de ficheros, el lanzamiento en worktrees aislados, la integración en secuencia con tests y el cierre con revisión. Úsalo al implementar tasks.md cuando haya 2 o más tareas independientes y la sesión vaya con esfuerzo medio o superior.
argument-hint: "[carpeta de la feature o rango de tareas]"
---

# Orquestar una ola de obreros

Esfuerzo actual: ${CLAUDE_EFFORT}. Si es `low`, no lances obreros: implementa tú en secuencia, o con `/speckit-implement` acotado a un rango de tareas.

## 0. Condiciones previas
Si falta alguna, no lances la ola.
- Spec aprobada (H1) y plan, contratos y tareas aprobados (H2).
- Estás en la rama de la feature (`NNN-nombre`) y `git status` está limpio. Los obreros parten de tu HEAD (`worktree.baseRef: "head"`): lo que no esté commiteado no lo verán.
- Fases Setup y Foundational terminadas, y contratos congelados con el tag `contratos-NNN-vX`.

## 1. Planificar la ola
1. Lee `tasks.md`. Son candidatas las tareas `- [ ]` con las dependencias resueltas: la fase anterior completa y sus `depends on` hechos.
2. Reparte por propiedad de ficheros. Dos tareas pueden ir a obreros distintos solo si sus conjuntos de ficheros son disjuntos, contando los tests y los `__init__.py`. Las tareas que comparten fichero van al mismo obrero, en orden.
3. Tamaño: **como máximo 3 obreros a la vez** (2 si son pruebas pesadas con la GPU), cada uno con 1 a 3 tareas cohesionadas. Cada brief lleva un **alcance mínimo y un tiempo límite** (decisión del humano, 2026-10-01: la cuota del plan se agota con olas grandes).
4. Ficheros calientes (`pyproject.toml`, `uv.lock`, `conftest.py` raíz, `__init__.py` que reexportan, configuración común): son tuyos. Si una tarea los necesita, cámbialos tú antes de la ola y commitea.
5. Tareas que necesitan GPU, modelos o dispositivos reales: el obrero escribe el código y los tests con dobles; los tests marcados `gpu`, `model` o `device` los ejecutas tú al integrar.

## 2. Lanzar
- Escribe un brief por obrero con la plantilla [brief.md](brief.md). Incluye el hash base (`git rev-parse --short HEAD`).
- Lanza todos los obreros de la ola en **un solo mensaje**: herramienta Agent, `subagent_type: "obrero"`, `run_in_background: true`. El modelo es el de la definición (Sonnet). Pasa `model: "opus"` solo para tareas difíciles (concurrencia delicada, algoritmos de latencia) y dilo en el brief.
- Mientras trabajan, no toques sus ficheros. Puedes preparar la ola siguiente o documentar.

## 3. Integrar
Integra según llegan los informes, respetando el orden de dependencias.
1. Según el `ESTADO`:
   - `DONE` / `DONE_WITH_CONCERNS`: integra y lee las NOTAS.
   - `NEEDS_CONTEXT`: contesta al obrero con SendMessage (conserva su contexto) o resuelve tú el hueco (por ejemplo, añadir una dependencia) y reanúdalo.
   - `BLOCKED`: analiza la causa. Si exige cambiar un contrato o la spec, detén la ola, redacta un ADR y consulta al humano.
2. Comprueba la propiedad **antes del merge**: `git diff --name-only $(git merge-base HEAD <rama>)..<rama>` debe estar contenido en los ficheros asignados. Usa siempre el `merge-base`, no la base del brief: el worktree nace del HEAD del momento del lanzamiento, que puede ser posterior. Si no se cumple, no integres y reanuda al obrero con la corrección.
3. Integra con `git merge --no-ff <rama> -m "Ola N: integra T0xx"`. Si hay conflicto en `uv.lock`, regenera con `uv lock` y commitea. Si es en otro fichero, el reparto estaba mal: resuélvelo tú y anótalo en la bitácora.
4. Verifica con `uv run pytest -q` y `uv run ruff check .`. Si sale rojo y el merge aún no está publicado, deshazlo (`git reset --hard ORIG_HEAD`) y devuelve la salida del fallo al obrero con SendMessage: su worktree sigue existiendo.
5. Marca `[X]` en `tasks.md` las tareas integradas (solo tú escribes `tasks.md`) y commitea.
6. Limpia con `git worktree remove <ruta>` y `git branch -d <rama>`.

## 4. Cerrar la ola
- Ejecuta la suite completa y, si la ola los afecta, los tests `gpu`, `model` y `device`, de uno en uno.
- Lanza el agente `revisor` sobre `<base>..HEAD` (Sonnet; Opus en features críticas). Corrige o encarga los hallazgos GRAVE y MEDIO.
- Haz push de la rama de la feature.
- Si la ola cierra una historia de usuario, usa la skill `registrar-hito`.

## Reglas fijas
- Solo el orquestador escribe `tasks.md`, `specs/**`, los contratos, `pyproject.toml`, `uv.lock`, `CLAUDE.md`, `.claude/**` y `docs/**`.
- Nunca dos obreros con el mismo fichero, y nunca una ola con cambios sin commitear.
- Nunca tests de GPU o de dispositivos en paralelo.
- Si un obrero falla dos veces en la misma tarea, hazla tú o replantea la tarea.
