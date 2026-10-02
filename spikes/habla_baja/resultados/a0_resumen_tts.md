# A0: embudo por etapa (cadena actual, corpus C2)

Pérdida = puntos porcentuales de palabras de la referencia (recall medio). Columnas en orden de la cadena.

| Condición | n | Techo ASR perdido | AGC pierde | VAD pierde | Segmentador pierde | Recall final | % frases traducidas (≥ 0,6) | % completas (≥ 0,9) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| whisper_tts | 20 | 2.7 | -0.7 | 2.6 | 0.0 | 95.3 | 100 | 75 |
| whisper_tts_q | 20 | 1.7 | 0.2 | 6.9 | 0.0 | 91.1 | 95 | 80 |
| whisper_tts_mus | 20 | 5.1 | 0.1 | 27.4 | 0.0 | 67.5 | 65 | 40 |
| TODO | 60 | 3.2 | -0.1 | 12.3 | 0.0 | 84.6 | 87 | 65 |

| Condición | Nivel de entrada (dBFS) | Tras el AGC (dBFS) | Ganancia al empezar (dB) | P(Silero) máx. | % tramas ≥ 0,5 | Habla cubierta por VAD | Retardo del fin p50 / p95 (s) | Unidades/clip | % unidades ≤ 3 pal. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| whisper_tts | -30 | -23 | 0 | 1.00 | 83 | 94 % | 0.53 / 0.57 | 2.4 | 10 |
| whisper_tts_q | -42 | -25 | 0 | 0.97 | 81 | 91 % | 0.53 / 0.62 | 2.2 | 9 |
| whisper_tts_mus | -32 | -22 | 12 | 0.93 | 58 | 69 % | 0.54 / 1.29 | 2.0 | 15 |

Falsas alarmas (10 min de música y efectos sin diálogo): - frases emitidas, - tramos de VAD (0 s).

Resumen por condición (retardo, fragmentación):

```json
{
 "whisper_tts": {
  "n": 20,
  "pct_translated": 100.0,
  "pct_complete": 75.0,
  "mean_recall": 95.34579128249604,
  "pct_emitted": 100.0,
  "delay_p50": 0.5299999999999994,
  "delay_p95": 0.5720000000000003,
  "units_per_clip": 2.4,
  "pct_units_le3": 10.416666666666668
 },
 "TODO": {
  "n": 60,
  "pct_translated": 86.66666666666667,
  "pct_complete": 65.0,
  "mean_recall": 84.62232245242856,
  "pct_emitted": 96.66666666666667,
  "delay_p50": 0.5299999999999994,
  "delay_p95": 0.8029999999999996,
  "units_per_clip": 2.2,
  "pct_units_le3": 11.363636363636363
 },
 "whisper_tts_q": {
  "n": 20,
  "pct_translated": 95.0,
  "pct_complete": 80.0,
  "mean_recall": 91.06616423963615,
  "pct_emitted": 95.0,
  "delay_p50": 0.5299999999999994,
  "delay_p95": 0.6199999999999992,
  "units_per_clip": 2.2,
  "pct_units_le3": 9.090909090909092
 },
 "whisper_tts_mus": {
  "n": 20,
  "pct_translated": 65.0,
  "pct_complete": 40.0,
  "mean_recall": 67.45501183515351,
  "pct_emitted": 95.0,
  "delay_p50": 0.54,
  "delay_p95": 1.2919999999999991,
  "units_per_clip": 2.0,
  "pct_units_le3": 15.0
 }
}
```