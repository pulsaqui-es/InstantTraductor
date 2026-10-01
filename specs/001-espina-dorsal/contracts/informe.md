# Contrato: informe de métricas y salidas del modo archivo

## `informe.json` (directo y archivo)
Codificación UTF-8, `schema_version: 1`. Los tiempos van en segundos, con 3 decimales.

```json
{
  "schema_version": 1,
  "session_id": "20261001-213000",
  "mode": "directo",
  "input_file": null,
  "started_at": "2026-10-01T21:30:00+02:00",
  "duration_s": 1800.0,
  "settings": { "voz": "es-f-01", "volumen_voz": 1.0, "umbral_acelerar_s": 3.0, "umbral_resumir_s": 5.0,
                "umbral_descartar_s": 8.0, "velocidad_max": 1.25, "max_habla_sin_traducir_s": 6.0 },
  "components": [ { "component_id": "hy-mt2-1.8b-q8", "version": "…", "license": "Apache-2.0" } ],
  "summary": {
    "utterances": 412, "spoken": 403, "concise": 12, "accelerated": 30, "dropped": 7, "rejected": 2, "failed": 0,
    "sentence_delay_s": { "p50": 2.41, "p95": 4.62, "max": 7.9 },
    "stages_s": {
      "capture":   { "p50": 0.09, "p95": 0.12 },
      "asr":       { "p50": 0.62, "p95": 0.95 },
      "mt":        { "p50": 0.18, "p95": 0.31 },
      "tts_first": { "p50": 0.33, "p95": 0.52 },
      "playback":  { "p50": 0.40, "p95": 2.10 }
    }
  },
  "diagnostics": { "startup_s": 34.2, "rss_mb_min5": 812, "rss_mb_end": 830,
                   "rss_children_mb_min5": 7900, "rss_children_mb_end": 8050,
                   "max_lag_s": 7.4, "lag_over_drop_max_streak_s": 0.0,
                   "echo_events": 0, "component_restarts": 0, "underruns": 0, "mt_model": "hy-mt2-7b-q4" },
  "utterances": [
    { "unit_id": 1, "source_text": "Where were you last night?", "translated_text": "¿Dónde estuviste anoche?",
      "mode": "normal", "speed": 1.0, "outcome": "pronunciada", "reason": null,
      "timings": { "t_start_audio": 3.120, "t_end_audio": 4.480, "unit_ready_at": 5.050, "captured_at": 4.570, "asr_final_at": 5.010,
                   "mt_started_at": 5.051, "mt_finished_at": 5.230, "tts_started_at": 5.231,
                   "tts_first_audio_at": 5.560, "tts_finished_at": 6.100,
                   "play_started_at": 5.590, "play_finished_at": 7.020 },
      "sentence_delay_s": 1.110 }
  ]
}
```

Reglas:
- Los percentiles se calculan solo sobre frases `pronunciada`.
- Etapas (FR-023):
  - `capture` = `captured_at − t_end_audio`
  - `asr` = `asr_final_at − t_end_audio`
  - `mt` = `mt_finished_at − mt_started_at`
  - `tts_first` = `tts_first_audio_at − tts_started_at`
  - `playback` = `play_started_at − tts_first_audio_at`
- `echo_events` cuenta las veces que el monitor de eco detecta la voz propia en la captura. En SC-002 debe ser 0.
- Memoria (SC-005):
  - `rss_mb_min5` y `rss_mb_end`: la del proceso núcleo;
  - `rss_children_mb_*`: la suma de `llama-server` y el servicio de voz.
- Retraso (SC-005):
  - se muestrea cada 0,5 s;
  - `max_lag_s` es el máximo;
  - `lag_over_drop_max_streak_s` es la racha continua más larga con el retraso por encima de `umbral_descartar_s`, que debe ser ≤ 10 s.
- `mt_model` indica qué modelo de traducción se usó (7B o la reserva 1.8B).
- `rejected` cuenta las traducciones que no pasaron los filtros de salida y no se pronunciaron.

## `informe.md`
Resumen legible del JSON:
- tabla de percentiles;
- recuentos;
- las 10 frases más lentas;
- avisos (reinicios, descartes, eco).

## Salidas del modo archivo
| Fichero | Formato |
|---|---|
| `voz_es.wav` | 48 kHz, mono, float32. Misma duración que la entrada. Cada frase empieza en su `play_started_at` |
| `mezcla.wav` | 48 kHz, estéreo, 16 bits. Original + voz en español al volumen de los ajustes, con limitador para evitar saturación |
| `mezcla.mkv` | Solo si la entrada tiene vídeo: vídeo copiado sin recodificar, pista 1 = mezcla y pista 2 = original |
| `transcripcion.srt` / `.json` | Una entrada por unidad: `t_start_audio → t_end_audio`, texto original |
| `traduccion.srt` / `.json` | Una entrada por unidad pronunciada: `play_started_at → play_finished_at`, texto en español (resumida marcada) |
| `informe.json` / `.md` | Como arriba, con `mode: "archivo"` e `input_file` |
