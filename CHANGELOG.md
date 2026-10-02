# Changelog

Todos los cambios relevantes de InstantTraductor se registran aquí.
Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Versionado: [SemVer](https://semver.org/lang/es/).

## [Sin publicar]

## [0.1.0] - 2026-10-02

Primera versión que funciona: lo que suena en el PC en inglés se oye en español de España, con todo en local ([spec 001](specs/001-espina-dorsal/spec.md), [validación](specs/001-espina-dorsal/validacion.md)).

### Añadido
- `instanttraductor directo`, el modo en directo:
  - captura de todo el audio del PC salvo la propia voz, con autotest contra la realimentación y monitor de eco;
  - voz en español por la salida predeterminada;
  - control del retraso: acelerar, resumir y descartar;
  - estado en la terminal y teclas `+`, `-`, `t` y `q`;
  - informe al terminar.
- `instanttraductor archivo`: traduce un fichero de audio o vídeo a ritmo real. Genera la voz alineada, la mezcla (y un MKV con dos pistas), la transcripción y la traducción en SRT y JSON, y el informe.
- `instanttraductor preparar`: comprueba el equipo, descarga y verifica los modelos con sha256, prepara el entorno de la voz y genera las muestras de las voces.
- `instanttraductor voces` y `instanttraductor diagnostico`.
- Catálogo de 5 voces castellanas incluido en la app, con Lucía por defecto (ADR-0008).
- Motores: Silero VAD; Nemotron Streaming en CPU; Hy-MT2 7B con `llama-server`, con reserva 1.8B y glosario de España; Qwen3-TTS 0.6B como servicio propio (ADR-0004 a 0011).

### Corregido
- El autotest daba falsas alarmas de eco si sonaba música en el PC.
- La parada no cerraba el sink ni la captura si un hilo del pipeline había muerto.
- Un fichero dañado a mitad podía dejar salidas incompletas.
- Ctrl+Break mataba la app sin guardar el informe.

## Anteriores a 0.1.0

### Cambiado
- Constitución 1.1.0: el orquestador aprueba las specs y los planes que siguen la hoja de ruta y consulta al humano solo lo importante (ADR-0009).

### Añadido
- Estructura de desarrollo guiado por especificaciones con GitHub Spec Kit 1.0.13 (ADR-0001).
- Infraestructura de trabajo en paralelo: agentes `obrero`, `revisor` e `investigador` y skills `orquestar-ola` y `registrar-hito` (ADR-0002).
- Restricciones de producto: 100 % local, uso personal y audio original sin cambios (ADR-0003).
- Investigación inicial (6 informes en `docs/investigacion/`), arquitectura (ADR 0004–0008), constitución 1.0.0 y hoja de ruta, aprobadas el 2026-09-30.
