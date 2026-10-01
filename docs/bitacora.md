# Bitácora

Registro cronológico del proyecto, con lo más reciente arriba. El formato y las reglas están en la skill `registrar-hito`.

## 2026-10-01 — Spikes cerrados: voz, traducción y ASR decididos
- **Hecho:** spikes S1, S2 y S3 integrados en `001-espina-dorsal`; medición del 7B por el orquestador.
  - **Voz:** Qwen3-TTS, primer audio p95 de 0,18 s, RTF 0,37, 3,3 GB. Chatterbox: 0,75 s y no aguanta el tiempo real.
  - **Traducción:**
    - 7B: p50/p95 de 211/347 ms con caché, 5,2 GB y sí resume.
    - 1.8B: 145/218 ms y 2,3 GB, pero no resume y tiene ~20 % de errores de sentido.
  - **ASR:** Nemotron en CPU, final p50/p95 de 0,67/0,78 s y WER del 5 %, sin VRAM. Casi no pone puntos: la segmentación irá por pausas y comas.
- **Decidido (humano):**
  - voz Qwen3-TTS con voz femenina castellana por defecto (ADR-0008, resolución);
  - traducción con el 7B y la reserva 1.8B, más un glosario de España (ADR-0011);
  - corrección de la captura (ADR-0010).
- **Siguiente:** completar research.md y plan, aprobar H2 (delegado) y `/speckit-tasks`.

## 2026-10-01 — Spikes: captura resuelta; cuota agotada y medidas de eficiencia
- **Hecho:**
  - Spike S4 (captura y reproducción) integrado en `001-espina-dorsal`. La subclase de pyminiaudio no sirve, pero la captura propia con ctypes/comtypes sí funciona.
  - Windows solo excluye el PID objetivo y sus hijos directos.
  - En silencio llegan paquetes.
  - Latencia de captura: 82–124 ms.
- **Incidente:** S1, S2 y S3 se cortaron por el límite de 5 horas del plan; se reanudaron a las 09:47 con la orden de cerrar rápido.
- **Decidido (humano):**
  - como máximo 3 obreros a la vez (2 en pruebas pesadas con GPU);
  - briefs con alcance mínimo y tiempo límite;
  - commits por hito (ADR-0002, actualización).
- **Siguiente:**
  - cerrar S1–S3 y completar `research.md`;
  - consultar al humano la corrección del ADR-0005 (captura) y la elección de voz.

## 2026-10-01 — Spec 001 aprobada y aprobaciones delegadas
- **Hecho:**
  - Spec `001-espina-dorsal` escrita y clarificada con dos preguntas de producto:
    - con retraso excesivo, primero se acelera, luego se resume y como último recurso se descarta;
    - las frases largas se traducen por partes.
  - Cuatro spikes en marcha (voz, traducción, ASR y captura de audio).
- **Decidido:**
  - El humano aprueba la spec 001 (H1).
  - A partir de ahora, el orquestador aprueba specs y planes que sigan la hoja de ruta y consulta solo lo importante (ADR-0009, constitución 1.1.0).
- **Siguiente:** `/speckit-plan` de la 001 con los resultados de los spikes.

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
