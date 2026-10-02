# A0: embudo por etapa (cadena actual, corpus C2)

Pérdida = puntos porcentuales de palabras de la referencia (recall medio). Columnas en orden de la cadena.

| Condición | n | Techo ASR perdido | AGC pierde | VAD pierde | Segmentador pierde | Recall final | % frases traducidas (≥ 0,6) | % completas (≥ 0,9) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mus_c | 20 | 7.3 | 0.1 | 9.7 | 0.0 | 83.0 | 90 | 55 |
| mus_d | 20 | 23.0 | 1.7 | 6.7 | 0.0 | 68.6 | 65 | 45 |
| sfx_a | 20 | 3.7 | 0.1 | -0.4 | 0.0 | 96.7 | 100 | 90 |
| reverb | 20 | 5.3 | 0.5 | 3.0 | 0.0 | 91.2 | 100 | 60 |
| whisper_mus | 20 | 19.0 | 1.8 | 15.9 | 0.0 | 63.3 | 65 | 20 |
| hesitate | 20 | 3.5 | 0.0 | 1.7 | 0.0 | 94.7 | 100 | 85 |
| stretch4 | 20 | 7.0 | 1.7 | 1.6 | 0.0 | 89.7 | 100 | 50 |
| TODO | 140 | 9.8 | 0.8 | 5.5 | 0.0 | 83.9 | 89 | 58 |

| Condición | Nivel de entrada (dBFS) | Tras el AGC (dBFS) | Ganancia al empezar (dB) | P(Silero) máx. | % tramas ≥ 0,5 | Habla cubierta por VAD | Retardo del fin p50 / p95 (s) | Unidades/clip | % unidades ≤ 3 pal. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mus_c | -28 | -22 | 8 | 0.99 | 78 | 86 % | 0.55 / 1.03 | 2.2 | 16 |
| mus_d | -29 | -22 | 8 | 0.94 | 68 | 78 % | 0.50 / 1.50 | 2.1 | 21 |
| sfx_a | -25 | -22 | 5 | 1.00 | 89 | 97 % | 0.56 / 1.14 | 2.4 | 12 |
| reverb | -30 | -23 | 0 | 1.00 | 82 | 88 % | 0.04 / 0.14 | 2.4 | 13 |
| whisper_mus | -32 | -22 | 11 | 0.97 | 66 | 80 % | 0.60 / 1.49 | 2.1 | 21 |
| hesitate | -26 | -22 | 0 | 1.00 | 73 | 80 % | 0.54 / 0.58 | 3.4 | 29 |
| stretch4 | -30 | -23 | 0 | 1.00 | 89 | 97 % | 0.54 / 0.58 | 2.5 | 14 |

Falsas alarmas (10 min de música y efectos sin diálogo): - frases emitidas, - tramos de VAD (0 s).

Resumen por condición (retardo, fragmentación):

```json
{
 "mus_c": {
  "n": 20,
  "pct_translated": 90.0,
  "pct_complete": 55.00000000000001,
  "mean_recall": 83.00098733119654,
  "pct_emitted": 100.0,
  "delay_p50": 0.5450000000000004,
  "delay_p95": 1.0250000000000004,
  "units_per_clip": 2.25,
  "pct_units_le3": 15.555555555555555
 },
 "TODO": {
  "n": 140,
  "pct_translated": 88.57142857142857,
  "pct_complete": 57.85714285714286,
  "mean_recall": 83.89116466524743,
  "pct_emitted": 99.28571428571429,
  "delay_p50": 0.5399999999999991,
  "delay_p95": 1.166999999999998,
  "units_per_clip": 2.45,
  "pct_units_le3": 18.658892128279884
 },
 "mus_d": {
  "n": 20,
  "pct_translated": 65.0,
  "pct_complete": 45.0,
  "mean_recall": 68.6147567892079,
  "pct_emitted": 95.0,
  "delay_p50": 0.5,
  "delay_p95": 1.5,
  "units_per_clip": 2.1,
  "pct_units_le3": 21.428571428571427
 },
 "sfx_a": {
  "n": 20,
  "pct_translated": 100.0,
  "pct_complete": 90.0,
  "mean_recall": 96.68101199791342,
  "pct_emitted": 100.0,
  "delay_p50": 0.5599999999999992,
  "delay_p95": 1.1409999999999996,
  "units_per_clip": 2.4,
  "pct_units_le3": 12.5
 },
 "reverb": {
  "n": 20,
  "pct_translated": 100.0,
  "pct_complete": 60.0,
  "mean_recall": 91.20361868044657,
  "pct_emitted": 100.0,
  "delay_p50": 0.03999999999999915,
  "delay_p95": 0.1409999999999997,
  "units_per_clip": 2.35,
  "pct_units_le3": 12.76595744680851
 },
 "whisper_mus": {
  "n": 20,
  "pct_translated": 65.0,
  "pct_complete": 20.0,
  "mean_recall": 63.324682568223544,
  "pct_emitted": 100.0,
  "delay_p50": 0.6049999999999993,
  "delay_p95": 1.4904999999999986,
  "units_per_clip": 2.15,
  "pct_units_le3": 20.930232558139537
 },
 "hesitate": {
  "n": 20,
  "pct_translated": 100.0,
  "pct_complete": 85.0,
  "mean_recall": 94.71299870424768,
  "pct_emitted": 100.0,
  "delay_p50": 0.5399999999999991,
  "delay_p95": 0.5799999999999992,
  "units_per_clip": 3.4,
  "pct_units_le3": 29.411764705882355
 },
 "stretch4": {
  "n": 20,
  "pct_translated": 100.0,
  "pct_complete": 50.0,
  "mean_recall": 89.70009658549645,
  "pct_emitted": 100.0,
  "delay_p50": 0.5449999999999999,
  "delay_p95": 0.5800000000000001,
  "units_per_clip": 2.5,
  "pct_units_le3": 14.000000000000002
 }
}
```