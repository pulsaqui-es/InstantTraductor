# Registro de decisiones de arquitectura (ADR)

Cada decisión relevante de arquitectura o tecnología queda en un fichero `NNNN-titulo-ascii.md`, numerado y fechado. Los ADR no se borran nunca: si una decisión cambia, se escribe otro que la sustituye y el antiguo se marca como «Sustituida».

## Índice

| ADR | Título | Estado | Fecha |
|---|---|---|---|
| [0001](0001-sdd-con-spec-kit.md) | Desarrollo guiado por especificaciones con GitHub Spec Kit | Aceptada | 2026-09-30 |
| [0002](0002-orquestador-y-obreros.md) | Orquestador y obreros en paralelo con worktrees | Aceptada | 2026-09-30 |
| [0003](0003-restricciones-de-producto.md) | Restricciones de producto: local, gratis y de uso personal | Aceptada | 2026-09-30 |
| [0004](0004-procesos-y-stack.md) | Arquitectura de procesos y stack base | Aceptada | 2026-09-30 |
| [0005](0005-captura-y-reproduccion.md) | Captura y reproducción de audio | Aceptada (en parte sustituida por 0010) | 2026-09-30 |
| [0006](0006-reconocimiento-de-voz.md) | Reconocimiento de voz (ASR) y segmentación | Aceptada | 2026-09-30 |
| [0007](0007-traduccion.md) | Traducción automática (MT) | Aceptada (en parte sustituida por 0011) | 2026-09-30 |
| [0008](0008-voz-y-clonacion.md) | Síntesis de voz (TTS), clonación y aislamiento de voz | Aceptada | 2026-09-30 |
| [0009](0009-aprobaciones-delegadas.md) | Aprobaciones delegadas en el orquestador | Aceptada | 2026-10-01 |
| [0010](0010-captura-propia-y-exclusion.md) | Captura por proceso con implementación propia y reglas de exclusión | Aceptada | 2026-10-01 |
| [0011](0011-traduccion-7b-con-reserva.md) | Traducción con Hy-MT2-7B, reserva 1.8B y glosario de España | Aceptada | 2026-10-01 |
| [0012](0012-escuchar-la-app-elegida.md) | Escuchar solo la aplicación elegida (captura INCLUDE) y filtro de idioma | Propuesta | 2026-10-02 |
| [0013](0013-reconocimiento-por-idioma.md) | Reconocimiento de voz por idioma elegido (en, ja, zh, ko) | Propuesta | 2026-10-02 |

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
