# ADR-0002: Orquestador y obreros en paralelo con worktrees

- Estado: Aceptada
- Fecha: 2026-09-30
- Decide: humano (trabajar en paralelo, obreros en Sonnet) y orquestador (el protocolo)

## Contexto
El humano quiere que, con esfuerzo medio o superior y tareas modulables, la sesión principal reparta el trabajo entre varios agentes en paralelo y actúe como máquina principal. Hay que evitar que los agentes se pisen y que la cuota del plan Claude Max x5 se agote.

## Decisión
- **Orquestador:** la sesión principal (Opus). Planifica, escribe specs, planes, contratos y ADR, reparte, integra y revisa.
- **Obreros:** subagente `obrero` (`.claude/agents/obrero.md`) con `model: sonnet` e `isolation: worktree`, sin poder lanzar otros agentes. Heredan el modo de permisos de la sesión del humano (decidido por el humano el 2026-09-30). Cada uno recibe un brief (plantilla en la skill `orquestar-ola`) y devuelve un informe con `ESTADO: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED`.
- **Apoyo:** `revisor` (solo lectura, revisa rangos de commits contra la spec) e `investigador` (informes con fuentes en `docs/investigacion/`).
- **Protocolo** (skill `orquestar-ola`):
  - olas de 2 a 4 obreros con ficheros disjuntos;
  - contratos congelados antes de la primera ola;
  - `worktree.baseRef: "head"` y commit antes de lanzar;
  - integración en secuencia con `merge --no-ff`, comprobando que cada obrero solo tocó sus ficheros y que los tests pasan;
  - el orquestador es el único que escribe `tasks.md`, specs, contratos, dependencias y documentación.
- Los tests con GPU, modelos o dispositivos reales solo los ejecuta el orquestador, de uno en uno.
- Opus para un obrero solo en tareas difíciles, justificándolo en el brief.

## Alternativas consideradas
- **Agent teams:** experimentales, sin aislamiento por worktree y con el modo de paneles sin soporte en el terminal de VS Code.
- **Workflows con script:** no admiten intervención humana a mitad de ejecución. Se podrán usar más adelante para codificar olas ya estables.
- **`/batch`:** pensado para migraciones mecánicas, no para features con contratos.
- **Un solo agente en secuencia:** más lento; se sigue usando cuando el esfuerzo es bajo o las tareas no se pueden separar.

## Consecuencias
- Positivas: paralelismo real sin conflictos de ficheros; cada obrero trabaja con contexto limpio; errores acotados a su rama.
- Negativas: los agentes paralelos consumen de 3 a 6 veces más tokens, y cada worktree necesita su propio `.venv` (barato gracias a la caché de uv).
- Obliga a escribir contratos y briefs muy precisos: la calidad de la spec se amplifica, para bien y para mal.
- Los permisos que necesitan los obreros van preconfigurados en `.claude/settings.json`, porque en Windows las aprobaciones dadas dentro de un worktree no se comparten.

## Actualización 2026-10-01 (decisión del humano)
Con cuatro obreros en paralelo haciendo pruebas largas se agotó el límite de 5 horas del plan Max x5 en unas 1,5 h. Tres obreros se cortaron con trabajo sin commitear. Medidas:
- como máximo 3 obreros a la vez (2 en pruebas pesadas con GPU);
- cada brief con alcance mínimo y tiempo límite;
- commits en cada hito.

## Referencias
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/worktrees
- `docs/investigacion/2026-09-30-sdd-herramientas.md` (§3.7)
