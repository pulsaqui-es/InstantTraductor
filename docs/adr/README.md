# Registro de decisiones de arquitectura (ADR)

Cada decisión relevante de arquitectura o tecnología queda en un fichero `NNNN-titulo-ascii.md`, numerado y fechado. Los ADR no se borran nunca: si una decisión cambia, se escribe otro que la sustituye y el antiguo se marca como «Sustituida».

## Índice

| ADR | Título | Estado | Fecha |
|---|---|---|---|
| [0001](0001-sdd-con-spec-kit.md) | Desarrollo guiado por especificaciones con GitHub Spec Kit | Aceptada | 2026-09-30 |
| [0002](0002-orquestador-y-obreros.md) | Orquestador y obreros en paralelo con worktrees | Aceptada | 2026-09-30 |
| [0003](0003-restricciones-de-producto.md) | Restricciones de producto: local, gratis y de uso personal | Aceptada | 2026-09-30 |
| [0004](0004-procesos-y-stack.md) | Arquitectura de procesos y stack base | Propuesta | 2026-09-30 |
| [0005](0005-captura-y-reproduccion.md) | Captura y reproducción de audio | Propuesta | 2026-09-30 |
| [0006](0006-reconocimiento-de-voz.md) | Reconocimiento de voz (ASR) y segmentación | Propuesta | 2026-09-30 |
| [0007](0007-traduccion.md) | Traducción automática (MT) | Propuesta | 2026-09-30 |
| [0008](0008-voz-y-clonacion.md) | Síntesis de voz (TTS), clonación y aislamiento de voz | Propuesta | 2026-09-30 |

## Plantilla

```markdown
# ADR-NNNN: <título>

- Estado: Propuesta | Aceptada | Sustituida por ADR-MMMM | Rechazada
- Fecha: AAAA-MM-DD
- Decide: humano | orquestador (con visto bueno del humano)

## Contexto
<qué problema hay y qué fuerzas influyen>

## Decisión
<qué se decide, en una o dos frases, y los detalles necesarios>

## Alternativas consideradas
<opción: por qué no>

## Consecuencias
<qué se gana, qué se pierde y qué obliga a hacer>

## Referencias
<informes de docs/investigacion/, specs, enlaces>
```
