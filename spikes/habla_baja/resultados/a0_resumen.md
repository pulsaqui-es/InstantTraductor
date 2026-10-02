# A0: embudo por etapa (cadena actual, corpus C2)

Pérdida = puntos porcentuales de palabras de la referencia (recall medio). Columnas en orden de la cadena.

| Condición | n | Techo ASR perdido | AGC pierde | VAD pierde | Segmentador pierde | Recall final | % frases traducidas (≥ 0,6) | % completas (≥ 0,9) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| n20 | 40 | 3.4 | -0.4 | 0.6 | 0.0 | 96.4 | 100 | 88 |
| n30 | 40 | 3.4 | 0.1 | -0.1 | 0.0 | 96.6 | 100 | 88 |
| n40 | 40 | 3.2 | 1.1 | -0.3 | 0.0 | 96.0 | 100 | 85 |
| n50 | 40 | 4.7 | 0.3 | 1.5 | 0.0 | 93.5 | 100 | 72 |
| mus_a | 40 | 3.9 | 0.0 | 0.6 | 0.0 | 95.4 | 100 | 80 |
| mus_b | 40 | 7.9 | -0.9 | 4.1 | 0.0 | 88.9 | 92 | 62 |
| whisper | 40 | 5.4 | -0.3 | 4.7 | 0.0 | 90.2 | 98 | 62 |
| whisper_q | 40 | 6.5 | -1.8 | 7.7 | 0.0 | 87.7 | 98 | 52 |
| stretch | 40 | 6.1 | 0.5 | 1.8 | 0.0 | 91.6 | 98 | 70 |
| slow | 40 | 5.4 | -0.2 | 0.9 | 0.0 | 93.8 | 100 | 82 |
| after_loud | 40 | 3.5 | 0.5 | 0.6 | 0.0 | 95.3 | 100 | 82 |
| TODO | 440 | 4.9 | -0.1 | 2.0 | 0.0 | 93.2 | 99 | 75 |

| Condición | Nivel de entrada (dBFS) | Tras el AGC (dBFS) | Ganancia al empezar (dB) | P(Silero) máx. | % tramas ≥ 0,5 | Habla cubierta por VAD | Retardo del fin p50 / p95 (s) | Unidades/clip | % unidades ≤ 3 pal. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| n20 | -20 | -22 | 0 | 1.00 | 89 | 96 % | 0.54 / 0.56 | 2.3 | 13 |
| n30 | -30 | -23 | 0 | 1.00 | 89 | 95 % | 0.54 / 0.58 | 2.4 | 15 |
| n40 | -40 | -24 | 0 | 1.00 | 89 | 96 % | 0.55 / 0.60 | 2.3 | 14 |
| n50 | -51 | -28 | 0 | 1.00 | 88 | 95 % | 0.55 / 0.70 | 2.2 | 13 |
| mus_a | -26 | -22 | 12 | 1.00 | 88 | 96 % | 0.60 / 1.36 | 2.3 | 13 |
| mus_b | -28 | -22 | 9 | 1.00 | 86 | 94 % | 0.59 / 1.50 | 2.2 | 17 |
| whisper | -30 | -23 | 0 | 1.00 | 86 | 95 % | 0.54 / 0.60 | 2.3 | 12 |
| whisper_q | -42 | -25 | 0 | 1.00 | 84 | 93 % | 0.55 / 0.62 | 2.2 | 12 |
| stretch | -30 | -23 | 0 | 1.00 | 90 | 96 % | 0.55 / 0.58 | 2.4 | 14 |
| slow | -30 | -23 | 0 | 1.00 | 87 | 92 % | 0.49 / 0.56 | 2.9 | 19 |
| after_loud | -35 | -24 | -2 | 1.00 | 89 | 96 % | 0.55 / 0.62 | 2.3 | 15 |

Falsas alarmas (10 min de música y efectos sin diálogo): 0 frases emitidas, 0 tramos de VAD (0 s).

Resumen por condición (retardo, fragmentación):

```json
{
 "n20": {
  "n": 40,
  "pct_translated": 100.0,
  "pct_complete": 87.5,
  "mean_recall": 96.38634223085839,
  "pct_emitted": 100.0,
  "delay_p50": 0.5399999999999996,
  "delay_p95": 0.5609999999999996,
  "units_per_clip": 2.275,
  "pct_units_le3": 13.186813186813188
 },
 "TODO": {
  "n": 440,
  "pct_translated": 98.63636363636363,
  "pct_complete": 75.0,
  "mean_recall": 93.23218620726206,
  "pct_emitted": 100.0,
  "delay_p50": 0.5470000000000002,
  "delay_p95": 0.8402499999999987,
  "units_per_clip": 2.3295454545454546,
  "pct_units_le3": 14.536585365853657
 },
 "n30": {
  "n": 40,
  "pct_translated": 100.0,
  "pct_complete": 87.5,
  "mean_recall": 96.62675185687716,
  "pct_emitted": 100.0,
  "delay_p50": 0.5400000000000005,
  "delay_p95": 0.581,
  "units_per_clip": 2.35,
  "pct_units_le3": 14.893617021276595
 },
 "n40": {
  "n": 40,
  "pct_translated": 100.0,
  "pct_complete": 85.0,
  "mean_recall": 96.02229265759557,
  "pct_emitted": 100.0,
  "delay_p50": 0.5500000000000007,
  "delay_p95": 0.6009999999999996,
  "units_per_clip": 2.275,
  "pct_units_le3": 14.285714285714285
 },
 "n50": {
  "n": 40,
  "pct_translated": 100.0,
  "pct_complete": 72.5,
  "mean_recall": 93.52711676043631,
  "pct_emitted": 100.0,
  "delay_p50": 0.5500000000000007,
  "delay_p95": 0.7010000000000001,
  "units_per_clip": 2.225,
  "pct_units_le3": 13.48314606741573
 },
 "mus_a": {
  "n": 40,
  "pct_translated": 100.0,
  "pct_complete": 80.0,
  "mean_recall": 95.44438861719152,
  "pct_emitted": 100.0,
  "delay_p50": 0.5999999999999992,
  "delay_p95": 1.3569999999999993,
  "units_per_clip": 2.275,
  "pct_units_le3": 13.186813186813188
 },
 "mus_b": {
  "n": 40,
  "pct_translated": 92.5,
  "pct_complete": 62.5,
  "mean_recall": 88.86662630904425,
  "pct_emitted": 100.0,
  "delay_p50": 0.5899999999999999,
  "delay_p95": 1.4999999999999991,
  "units_per_clip": 2.175,
  "pct_units_le3": 17.24137931034483
 },
 "whisper": {
  "n": 40,
  "pct_translated": 97.5,
  "pct_complete": 62.5,
  "mean_recall": 90.19884827965929,
  "pct_emitted": 100.0,
  "delay_p50": 0.5449999999999999,
  "delay_p95": 0.5999999999999996,
  "units_per_clip": 2.3,
  "pct_units_le3": 11.956521739130435
 },
 "whisper_q": {
  "n": 40,
  "pct_translated": 97.5,
  "pct_complete": 52.5,
  "mean_recall": 87.72440770979924,
  "pct_emitted": 100.0,
  "delay_p50": 0.5549999999999997,
  "delay_p95": 0.621,
  "units_per_clip": 2.225,
  "pct_units_le3": 12.359550561797752
 },
 "stretch": {
  "n": 40,
  "pct_translated": 97.5,
  "pct_complete": 70.0,
  "mean_recall": 91.59056357441526,
  "pct_emitted": 100.0,
  "delay_p50": 0.5459999999999994,
  "delay_p95": 0.5764000000000004,
  "units_per_clip": 2.375,
  "pct_units_le3": 13.684210526315791
 },
 "slow": {
  "n": 40,
  "pct_translated": 100.0,
  "pct_complete": 82.5,
  "mean_recall": 93.81848153601162,
  "pct_emitted": 100.0,
  "delay_p50": 0.4919999999999991,
  "delay_p95": 0.5600000000000005,
  "units_per_clip": 2.85,
  "pct_units_le3": 19.298245614035086
 },
 "after_loud": {
  "n": 40,
  "pct_translated": 100.0,
  "pct_complete": 82.5,
  "mean_recall": 95.34822874799417,
  "pct_emitted": 100.0,
  "delay_p50": 0.5500000000000007,
  "delay_p95": 0.622,
  "units_per_clip": 2.3,
  "pct_units_le3": 15.217391304347828
 }
}
```