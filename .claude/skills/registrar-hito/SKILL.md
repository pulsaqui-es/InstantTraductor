---
name: registrar-hito
description: Mantiene la línea temporal de InstantTraductor con fechas absolutas (bitácora, CHANGELOG, ADR, hoja de ruta y tags de versión). Úsalo al cerrar una sesión de trabajo, una historia de usuario o una feature, al tomar o cambiar una decisión de arquitectura o de tecnología, y al publicar una versión.
argument-hint: "[sesion | decision | feature NNN | version X.Y.Z]"
---

# Registrar un hito

Usa siempre fechas absolutas en formato `AAAA-MM-DD` (la de hoy la da `date +%F`). Nunca escribas «ayer» ni «la semana pasada».

## Qué actualizar según el evento

| Evento | Qué actualizar |
|---|---|
| Fin de una sesión de trabajo | `docs/bitacora.md`: entrada nueva arriba del todo |
| Decisión de arquitectura o tecnología | `docs/adr/NNNN-titulo-ascii.md` (plantilla en `docs/adr/README.md`) + índice de ADR + entrada en la bitácora |
| Cambio de una decisión anterior | ADR nuevo que «Sustituye a ADR-NNNN»; en el antiguo, `Estado: Sustituida por ADR-MMMM`. Los ADR nunca se borran |
| Historia de usuario o feature integrada en main | `CHANGELOG.md` (sección «Sin publicar»), `docs/hoja-de-ruta.md` (estado) y bitácora |
| Publicar una versión | `CHANGELOG.md`: «Sin publicar» pasa a `[X.Y.Z] - AAAA-MM-DD`; tag anotado `vX.Y.Z` y push del tag |
| Cambio de principios | `/speckit-constitution` (sube la versión de la constitución) + ADR |

## Formatos

Bitácora:

```markdown
## AAAA-MM-DD — <título corto>
- Hecho: <qué se ha terminado, con enlaces a specs, PR o commits>
- Decidido: <decisión> (ADR-NNNN)
- Siguiente: <próximo paso concreto>
```

CHANGELOG: formato Keep a Changelog en español (Añadido, Cambiado, Corregido, Eliminado) y versionado SemVer (`0.y.z` hasta la primera versión estable).

## Reglas
- Cada dato vive en un solo sitio: el detalle técnico, en `specs/` y en los ADR; la bitácora y el CHANGELOG enlazan, no copian.
- Commit propio para cada registro: `docs: registra <hito>`.
- Para reconstruir fechas pasadas usa `git log --format='%ad %h %s' --date=short`.
