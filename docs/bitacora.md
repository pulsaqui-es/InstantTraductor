# Bitácora

Registro cronológico del proyecto, con lo más reciente arriba. El formato y las reglas están en la skill `registrar-hito`.

## 2026-09-30 — Aprobación de los cimientos y arranque de la spec 001
- **Hecho:** los obreros heredan el modo de permisos de la sesión del humano (antes `acceptEdits`).
- **Decidido:**
  - El humano aprueba sin cambios la constitución 1.0.0, los ADR 0004–0008 y la hoja de ruta.
  - Consigna: todo sin costes (100 % local, sin servicios de pago).
- **Siguiente:**
  - Rama `001-espina-dorsal` con `/speckit-specify` y `/speckit-clarify` → H1.
  - En paralelo, cuatro pruebas técnicas (spikes) de voz, traducción, ASR y captura de audio, para basar el plan en mediciones reales.

## 2026-09-30 — Arranque del proyecto
- **Hecho:**
  - Repositorio inicializado y enlazado con GitHub.
  - Herramientas instaladas: uv 0.12, ffmpeg, GitHub CLI 2.102 y Spec Kit 1.0.13.
  - Infraestructura de orquestación: agentes `obrero`, `revisor` e `investigador`, y skills `orquestar-ola` y `registrar-hito`.
  - Seis investigaciones en paralelo, guardadas en `docs/investigacion/`.
- **Decidido:**
  - SDD con Spec Kit (ADR-0001).
  - Orquestador y obreros en Sonnet (ADR-0002).
  - App 100 % local y de uso personal, con el audio original sin cambios. Contenido principal: series, películas y juegos. La v1 incluye clonación de voz y detección de idioma (ADR-0003).
- **Propuesto:** ADR-0004 a 0008, la constitución 1.0.0 y la hoja de ruta.
- **Decidido también:** en la v1 no se traduce mientras se juega (solo el perfil de calidad) y se arranca con un comando hasta la spec 005 (ADR-0003).
- **Siguiente:** el humano revisa la propuesta y aprueba o pide cambios; después, la spec `001-espina-dorsal`.
