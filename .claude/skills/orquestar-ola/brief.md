# Plantilla de brief para un obrero

Copia el bloque, rellena todos los campos y pásalo como `prompt` al agente `obrero`. Un brief incompleto produce trabajo inútil: si no sabes rellenar un campo, la tarea no está lista para delegarse.

```text
BRIEF · Feature <NNN-nombre> · Ola <N> · Obrero <A|B|C|D>
Base: <hash corto> (debe ser ancestro de tu HEAD)

Tareas, en orden:
- T0xx — <título tal cual aparece en tasks.md>
- T0yy — <...>

Contexto que DEBES leer:
- specs/<NNN-nombre>/spec.md → <secciones o requisitos FR-xxx concretos>
- specs/<NNN-nombre>/plan.md → <secciones>
- specs/<NNN-nombre>/contracts/<fichero> y <ruta del contrato en código>
- <otros: data-model.md, tests de contrato, fakes existentes>

Ficheros que POSEES (crear o modificar): <rutas o globs exactos, incluidos los tests>
Solo lectura: todo lo demás (en especial los contratos y specs/**)

Criterios de aceptación:
- T0xx: <comportamiento verificable, extraído de la spec o de la tarea>
- T0yy: <...>

Definición de hecho:
- uv run pytest <rutas de tus tests> -q → todo en verde
- uv run ruff check <tus rutas> → sin errores
- uv run ruff format --check <tus rutas> → sin cambios pendientes

Restricciones: sin GPU, sin dispositivos de audio y sin descargar modelos <salvo: ...>
Modelo: sonnet | opus (<motivo>)

Alcance mínimo: <lo imprescindible para dar la tarea por hecha; lo demás es opcional>
Tiempo límite: <p. ej. 60 min>. Si se alcanza, commitea lo que tengas y termina con DONE_WITH_CONCERNS explicando qué falta.
Hitos (un commit por cada uno): <p. ej. 1) tests en rojo, 2) implementación en verde, 3) lint limpio>

Devuelve el informe final con el formato de tu definición de agente.
```
