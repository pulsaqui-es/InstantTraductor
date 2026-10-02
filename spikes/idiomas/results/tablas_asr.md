
### ja

| Candidato | CER limpio | CER con música | Final p50 / p95 (s) | Con música p50 / p95 (s) | 1.er parcial p50 (s) | RTF | Núcleos | RAM cargado / pico (MB) | Puntuación (signos/100 car.; frases con cierre) | Segmentos (esp.) |
|---|---|---|---|---|---|---|---|---|---|---|
| Parakeet-tdt_ctc-0.6b-ja (cabeza CTC, int8) (2 h) | 5.31 % | 6.17 % | 1.24 / 2.02 | 1.37 / 2.28 | - | 0.069 | 0.12 | 753 / 1046 | 0.6; 8/50 | 64 (0/0) |
| SenseVoice-Small 2024-07-17 (int8, ITN) (2 h) | 8.32 % | 10.20 % | 0.88 / 1.39 | 0.95 / 1.52 | - | 0.038 | 0.06 | 357 / 530 | 4.9; 50/50 | 64 (0/0) |
| ReazonSpeech zipformer k2 v2 (int8) (2 h) | 8.44 % | 9.57 % | 0.74 / 0.98 | 0.78 / 1.10 | - | 0.026 | 0.05 | 286 / 642 | 0.2; 0/50 | 64 (0/0) |
| Nemotron 3.5 560 ms, blank_penalty 1 (2 h) | 12.58 % | 14.96 % | 0.69 / 0.84 | 0.74 / 1.02 | 1.07 | 0.190 | 0.44 | 793 / 960 | 3.5; 28/50 | 64 (0/0) |
| Nemotron 3.5 streaming 560 ms (int8) (2 h) | 13.40 % | 17.03 % | 0.71 / 0.91 | 0.74 / 1.04 | 1.08 | 0.205 | 0.45 | 793 / 960 | 1.9; 4/50 | 64 (0/0) |

Detalle: CER con partición de errores (sustituciones/borrados/inserciones), mediana y p90 por frase, frases sin texto.

| Candidato | S / D / I (limpio) | CER mediano por frase | CER p90 por frase | Frases sin texto (limpio / música) | Decodificación por segmento p50 / p95 (ms) |
|---|---|---|---|---|---|
| Parakeet-tdt_ctc-0.6b-ja (cabeza CTC, int8) | 74 / 31 / 31 | 3.9 % | 13.5 % | 0 / 0 | 658 / 1277 |
| SenseVoice-Small 2024-07-17 (int8, ITN) | 132 / 52 / 29 | 5.8 % | 18.8 % | 0 / 0 | 330 / 727 |
| ReazonSpeech zipformer k2 v2 (int8) | 69 / 127 / 20 | 4.9 % | 22.3 % | 0 / 0 | 200 / 415 |
| Nemotron 3.5 560 ms, blank_penalty 1 | 223 / 63 / 36 | 11.8 % | 25.7 % | 0 / 0 | 152 / 178 |
| Nemotron 3.5 streaming 560 ms (int8) | 208 / 111 / 24 | 12.9 % | 25.5 % | 0 / 0 | 169 / 225 |

### zh

| Candidato | CER limpio | CER con música | Final p50 / p95 (s) | Con música p50 / p95 (s) | 1.er parcial p50 (s) | RTF | Núcleos | RAM cargado / pico (MB) | Puntuación (signos/100 car.; frases con cierre) | Segmentos (esp.) |
|---|---|---|---|---|---|---|---|---|---|---|
| X-ASR-zh-en 960 ms (punct, int8) (2 h) | 4.87 % | 5.15 % | 0.58 / 0.61 | 0.60 / 0.74 | 0.84 | 0.043 | 0.13 | 294 / 421 | 3.7; 0/50 | 67 (0/0) |
| SenseVoice-Small 2024-07-17 (int8, ITN) (2 h) | 5.55 % | 6.06 % | 0.87 / 1.31 | 0.88 / 1.44 | - | 0.043 | 0.07 | 357 / 520 | 7.7; 50/50 | 67 (0/0) |
| X-ASR-zh-en 480 ms (punct, int8) (2 h) | 5.77 % | 6.28 % | 0.57 / 0.59 | 0.58 / 0.72 | 0.84 | 0.060 | 0.20 | 294 / 417 | 3.6; 0/50 | 67 (0/0) |
| zipformer-zh streaming 2025-06-30 (int8) (2 h) | 8.66 % | 9.90 % | 0.57 / 0.60 | 0.58 / 0.72 | 0.51 | 0.088 | 0.28 | 293 / 408 | 0.0; 0/50 | 67 (0/0) |

Detalle: CER con partición de errores (sustituciones/borrados/inserciones), mediana y p90 por frase, frases sin texto.

| Candidato | S / D / I (limpio) | CER mediano por frase | CER p90 por frase | Frases sin texto (limpio / música) | Decodificación por segmento p50 / p95 (ms) |
|---|---|---|---|---|---|
| X-ASR-zh-en 960 ms (punct, int8) | 39 / 35 / 12 | 3.0 % | 12.5 % | 0 / 0 | 46 / 69 |
| SenseVoice-Small 2024-07-17 (int8, ITN) | 46 / 38 / 14 | 3.3 % | 13.1 % | 0 / 0 | 311 / 723 |
| X-ASR-zh-en 480 ms (punct, int8) | 50 / 41 / 11 | 3.6 % | 13.0 % | 0 / 0 | 34 / 54 |
| zipformer-zh streaming 2025-06-30 (int8) | 85 / 57 / 11 | 6.4 % | 21.3 % | 0 / 0 | 35 / 55 |

### ko

| Candidato | CER limpio | CER con música | Final p50 / p95 (s) | Con música p50 / p95 (s) | 1.er parcial p50 (s) | RTF | Núcleos | RAM cargado / pico (MB) | Puntuación (signos/100 car.; frases con cierre) | Segmentos (esp.) |
|---|---|---|---|---|---|---|---|---|---|---|
| SenseVoice-Small 2024-07-17 (int8, ITN) (2 h) | 7.14 % | 8.09 % | 0.91 / 1.23 | 0.97 / 1.54 | - | 0.042 | 0.07 | 357 / 525 | 2.2; 50/50 | 61 (0/0) |
| Nemotron 3.5 560 ms, blank_penalty 1 (2 h) | 8.43 % | 9.81 % | 0.71 / 0.83 | 0.78 / 1.18 | 1.04 | 0.197 | 0.46 | 793 / 955 | 2.5; 49/50 | 61 (0/0) |
| zipformer coreano kangkyu 174M, chunk 64 (1280 ms) (2 h) | 8.47 % | 9.68 % | 0.58 / 0.62 | 0.61 / 1.10 | 1.17 | 0.039 | 0.11 | 285 / 425 | 0.0; 0/50 | 61 (0/0) |
| Nemotron 3.5 streaming 560 ms (int8) (2 h) | 8.73 % | 9.72 % | 0.72 / 0.83 | 0.77 / 1.18 | 1.07 | 0.205 | 0.45 | 793 / 956 | 2.3; 47/50 | 61 (0/0) |
| zipformer coreano kangkyu 174M, chunk 32 (640 ms) (2 h) | 8.90 % | 9.59 % | 0.56 / 0.61 | 0.60 / 1.10 | 1.15 | 0.055 | 0.16 | 286 / 412 | 0.0; 0/50 | 61 (0/0) |

Detalle: CER con partición de errores (sustituciones/borrados/inserciones), mediana y p90 por frase, frases sin texto.

| Candidato | S / D / I (limpio) | CER mediano por frase | CER p90 por frase | Frases sin texto (limpio / música) | Decodificación por segmento p50 / p95 (ms) |
|---|---|---|---|---|---|
| SenseVoice-Small 2024-07-17 (int8, ITN) | 66 / 82 / 18 | 3.9 % | 20.1 % | 0 / 0 | 369 / 691 |
| Nemotron 3.5 560 ms, blank_penalty 1 | 123 / 59 / 14 | 5.4 % | 20.4 % | 0 / 0 | 153 / 291 |
| zipformer coreano kangkyu 174M, chunk 64 (1280 ms) | 118 / 68 / 11 | 3.7 % | 24.6 % | 0 / 0 | 53 / 74 |
| Nemotron 3.5 streaming 560 ms (int8) | 127 / 62 / 14 | 5.2 % | 20.4 % | 0 / 0 | 157 / 306 |
| zipformer coreano kangkyu 174M, chunk 32 (640 ms) | 125 / 69 / 13 | 5.1 % | 23.9 % | 0 / 0 | 40 / 65 |

(variante `_carga`)

### ja

| Candidato | CER limpio | CER con música | Final p50 / p95 (s) | Con música p50 / p95 (s) | 1.er parcial p50 (s) | RTF | Núcleos | RAM cargado / pico (MB) | Puntuación (signos/100 car.; frases con cierre) | Segmentos (esp.) |
|---|---|---|---|---|---|---|---|---|---|---|
| Parakeet-tdt_ctc-0.6b-ja (cabeza CTC, int8) (2 h) | 5.31 % | 6.17 % | 1.57 / 3.35 | 1.74 / 3.46 | - | 0.127 | 0.14 | 752 / 1048 | 0.6; 8/50 | 64 (0/0) |
| ReazonSpeech zipformer k2 v2 (int8) (2 h) | 8.44 % | 9.57 % | 0.97 / 2.02 | 1.15 / 2.17 | - | 0.069 | 0.06 | 286 / 643 | 0.2; 0/50 | 64 (0/0) |

Detalle: CER con partición de errores (sustituciones/borrados/inserciones), mediana y p90 por frase, frases sin texto.

| Candidato | S / D / I (limpio) | CER mediano por frase | CER p90 por frase | Frases sin texto (limpio / música) | Decodificación por segmento p50 / p95 (ms) |
|---|---|---|---|---|---|
| Parakeet-tdt_ctc-0.6b-ja (cabeza CTC, int8) | 74 / 31 / 31 | 3.9 % | 13.5 % | 0 / 0 | 1043 / 2949 |
| ReazonSpeech zipformer k2 v2 (int8) | 69 / 127 / 20 | 4.9 % | 22.3 % | 0 / 0 | 411 / 1393 |

(variante `_carga`)

### zh

| Candidato | CER limpio | CER con música | Final p50 / p95 (s) | Con música p50 / p95 (s) | 1.er parcial p50 (s) | RTF | Núcleos | RAM cargado / pico (MB) | Puntuación (signos/100 car.; frases con cierre) | Segmentos (esp.) |
|---|---|---|---|---|---|---|---|---|---|---|
| X-ASR-zh-en 960 ms (punct, int8) (2 h) | 4.87 % | 5.15 % | 0.63 / 0.90 | 0.64 / 0.90 | 0.89 | 0.128 | 0.18 | 293 / 420 | 3.7; 0/50 | 67 (0/0) |
| SenseVoice-Small 2024-07-17 (int8, ITN) (2 h) | 5.55 % | 6.06 % | 1.23 / 2.17 | 1.01 / 2.19 | - | 0.096 | 0.09 | 356 / 520 | 7.7; 50/50 | 67 (0/0) |

Detalle: CER con partición de errores (sustituciones/borrados/inserciones), mediana y p90 por frase, frases sin texto.

| Candidato | S / D / I (limpio) | CER mediano por frase | CER p90 por frase | Frases sin texto (limpio / música) | Decodificación por segmento p50 / p95 (ms) |
|---|---|---|---|---|---|
| X-ASR-zh-en 960 ms (punct, int8) | 39 / 35 / 12 | 3.0 % | 12.5 % | 0 / 0 | 91 / 294 |
| SenseVoice-Small 2024-07-17 (int8, ITN) | 46 / 38 / 14 | 3.3 % | 13.1 % | 0 / 0 | 626 / 1614 |

(variante `_carga`)

### ko

| Candidato | CER limpio | CER con música | Final p50 / p95 (s) | Con música p50 / p95 (s) | 1.er parcial p50 (s) | RTF | Núcleos | RAM cargado / pico (MB) | Puntuación (signos/100 car.; frases con cierre) | Segmentos (esp.) |
|---|---|---|---|---|---|---|---|---|---|---|
| SenseVoice-Small 2024-07-17 (int8, ITN) (2 h) | 7.14 % | 8.09 % | 1.28 / 2.28 | 1.49 / 2.16 | - | 0.086 | 0.08 | 357 / 525 | 2.2; 50/50 | 61 (0/0) |
| Nemotron 3.5 560 ms, blank_penalty 1 (2 h) | 8.43 % | 9.81 % | 1.28 / 4.59 | 1.55 / 4.23 | 1.15 | 0.536 | 0.65 | 793 / 957 | 2.5; 49/50 | 61 (0/0) |
| zipformer coreano kangkyu 174M, chunk 64 (1280 ms) (2 h) | 8.47 % | 9.68 % | 0.58 / 0.62 | 0.61 / 1.11 | 1.16 | 0.038 | 0.11 | 285 / 425 | 0.0; 0/50 | 61 (0/0) |

Detalle: CER con partición de errores (sustituciones/borrados/inserciones), mediana y p90 por frase, frases sin texto.

| Candidato | S / D / I (limpio) | CER mediano por frase | CER p90 por frase | Frases sin texto (limpio / música) | Decodificación por segmento p50 / p95 (ms) |
|---|---|---|---|---|---|
| SenseVoice-Small 2024-07-17 (int8, ITN) | 66 / 82 / 18 | 3.9 % | 20.1 % | 0 / 0 | 683 / 1637 |
| Nemotron 3.5 560 ms, blank_penalty 1 | 123 / 59 / 14 | 5.4 % | 20.4 % | 0 / 0 | 381 / 1097 |
| zipformer coreano kangkyu 174M, chunk 64 (1280 ms) | 118 / 68 / 11 | 3.7 % | 24.6 % | 0 / 0 | 53 / 65 |

(variante `_paced`)

(variante `_paced`)

### zh

| Candidato | CER limpio | CER con música | Final p50 / p95 (s) | Con música p50 / p95 (s) | 1.er parcial p50 (s) | RTF | Núcleos | RAM cargado / pico (MB) | Puntuación (signos/100 car.; frases con cierre) | Segmentos (esp.) |
|---|---|---|---|---|---|---|---|---|---|---|
| X-ASR-zh-en 960 ms (punct, int8) (2 h) | 4.87 % | - | 0.57 / 0.60 | - | 0.84 | 0.048 | 0.14 | 294 / 392 | 3.7; 0/50 | 67 (0) |

Detalle: CER con partición de errores (sustituciones/borrados/inserciones), mediana y p90 por frase, frases sin texto.

| Candidato | S / D / I (limpio) | CER mediano por frase | CER p90 por frase | Frases sin texto (limpio / música) | Decodificación por segmento p50 / p95 (ms) |
|---|---|---|---|---|---|
| X-ASR-zh-en 960 ms (punct, int8) | 39 / 35 / 12 | 3.0 % | 12.5 % | 0 / - | 43 / 50 |

(variante `_paced`)
