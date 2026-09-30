# Modelo de datos: 001-espina-dorsal

Entidades de la spec (Key Entities), con campos, reglas y estados. Los tipos exactos en Python están en [contracts/pipeline.md](contracts/pipeline.md).

## Relojes y tiempos

- **Reloj de sesión** (`Clock.now()`): segundos desde que empieza la sesión, monotónico. Mide cuándo ocurre cada cosa: evento emitido, audio que empieza a sonar.
- **Reloj de audio:** segundos del audio captado desde el inicio de la sesión, contados por muestras (`n / 16000`) y con los silencios rellenados. Sitúa el habla original (`t_start`, `t_end`).
- Los dos relojes comparten origen: el inicio de la sesión. La captura añade decenas de milisegundos, que se desprecian. Por eso:
  - **retardo de frase** = `play_started_at − t_end`;
  - **retraso actual** (`lag`) = `now − t_end` de la frase más antigua que aún no ha terminado de sonar.

## Sesión
| Campo | Tipo | Regla |
|---|---|---|
| `session_id` | texto | Único: `AAAAMMDD-HHMMSS` |
| `mode` | `directo` \| `archivo` | |
| `started_at` | fecha y hora local | |
| `duration_s` | número | ≥ 0 |
| `settings` | Ajustes (copia) | Los ajustes con los que corrió |
| `input_file` | ruta \| nulo | Solo en modo archivo |
| `utterances` | lista de Frase | En orden de `unit_id` |
| `diagnostics` | objeto | `startup_s`, `rss_mb_min5`, `rss_mb_end`, `echo_events`, `component_restarts` |

## Frase (unidad de traducción y su recorrido)
Es una frase corta entera o un fragmento con sentido de una frase larga (spec, clarificación 2).

| Campo | Tipo | Regla |
|---|---|---|
| `unit_id` | entero | Estrictamente creciente en la sesión |
| `source_text` | texto | No vacío; texto estable del ASR (no se retracta) |
| `t_start`, `t_end` | segundos (reloj de audio) | `t_start < t_end`; no se solapan con la unidad anterior |
| `is_sentence_end` | booleano | `False` si es un fragmento de una frase larga |
| `translated_text` | texto \| nulo | Nulo hasta traducir |
| `mode` | `normal` \| `conciso` | `conciso` = resumida (FR-013) |
| `speed` | número | 1,0 ≤ `speed` ≤ `max_speed` |
| `state` | ver diagrama | |
| `timings` | StageTimings | Ver abajo |
| `outcome` | `pronunciada` \| `descartada` \| `fallida` | Al cerrarse |

### Estados de una frase

```text
PENDIENTE ──► TRADUCIENDO ──► SINTETIZANDO ──► EN_COLA ──► SONANDO ──► PRONUNCIADA
    │              │                │              │
    └──────────────┴────────────────┴──────────────┴──► DESCARTADA   (política de retraso, FR-014)
 cualquier estado anterior a PRONUNCIADA ─────────────► FALLIDA      (error de un motor tras reintento, FR-018)
```

- **Orden:** las frases pasan a SONANDO en orden estricto de `unit_id` (FR-008). Una frase nunca vuelve a un estado anterior ni se traduce dos veces.
- **Descartes:** solo se descartan frases que no han empezado a sonar, empezando por la más antigua (FR-014).
- **Parada:** al detener la sesión, lo que está SONANDO se corta y lo pendiente queda DESCARTADA con el motivo «parada».

### StageTimings (reloj de sesión salvo indicación)
| Campo | Significado |
|---|---|
| `t_start_audio`, `t_end_audio` | Inicio y fin en el original (reloj de audio) |
| `asr_final_at` | Texto estable disponible |
| `unit_ready_at` | Unidad cerrada por el segmentador |
| `mt_started_at`, `mt_finished_at` | Traducción |
| `tts_started_at`, `tts_first_audio_at`, `tts_finished_at` | Síntesis de voz |
| `play_started_at`, `play_finished_at` | Reproducción real (eventos del sink) |
| **Derivados** | `sentence_delay = play_started_at − t_end_audio`; `asr_s = asr_final_at − t_end_audio`; `mt_s`; `tts_first_s = tts_first_audio_at − tts_started_at`; `queue_s = play_started_at − tts_first_audio_at` |

## Ajustes (persisten en `ajustes.toml`, FR-029)
| Clave | Por defecto | Rango |
|---|---|---|
| `voz` | la elegida en `voces` (hay una por defecto) | id del catálogo |
| `volumen_voz` | 1,0 | 0,0–2,0 (solo la voz en español) |
| `umbral_acelerar_s` | 3,0 | > 0 |
| `umbral_resumir_s` | 5,0 | > `umbral_acelerar_s` |
| `umbral_descartar_s` | 8,0 | > `umbral_resumir_s` |
| `velocidad_max` | 1,25 | 1,0–1,5 |
| `max_habla_sin_traducir_s` | 6,0 | 2–15 |
| `frases_de_contexto` | 4 | 0–8 |
| `glosario` | vacío | pares inglés → español |
| `mostrar_texto` | falso | |
| `guardar_audio` | falso | (FR-030) |

Un valor fuera de rango al cargar no se ignora en silencio: se avisa y se usa el valor por defecto.

## Voz (catálogo, FR-028)
| Campo | Regla |
|---|---|
| `voice_id` | ASCII, único |
| `name` | Nombre visible |
| `gender` | `f` \| `m` |
| `source` | Origen de la referencia (URL, lector, minuto) |
| `license` | Licencia de la referencia (p. ej. dominio público) |
| `sample_text` | Frase de muestra para escucharla |

Hay al menos 3 voces castellanas y al menos una de cada género.

## Componente (preparación, FR-025 y FR-026)
| Campo | Regla |
|---|---|
| `component_id` | ASCII, único |
| `name`, `version` | |
| `kind` | `binario` \| `modelo` \| `entorno` \| `voz` |
| `source_url` + `revision` | Fijados (sin «latest») |
| `sha256`, `size_bytes` | Para verificar y comprobar el espacio antes de descargar |
| `license` | Obligatoria |
| `path` | Bajo `%LOCALAPPDATA%\InstantTraductor\` |
| `status` | `ausente` → `descargado` → `verificado` \| `corrupto` (un corrupto se vuelve a descargar) |

## Informe de métricas
Resumen de la sesión y detalle por frase. El formato exacto está en [contracts/informe.md](contracts/informe.md). Percentiles p50 y p95 de `sentence_delay` y de cada etapa; recuentos de frases pronunciadas, resumidas, aceleradas, descartadas y fallidas; `diagnostics`.
