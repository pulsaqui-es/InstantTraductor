# ASR para japonés, chino (mandarín) y coreano, con el idioma elegido a mano

- Fecha de consulta: **2026-10-02**. Autor: investigador (spec 002).
- Contexto: `CLAUDE.md`, `docs/adr/0006-reconocimiento-de-voz.md`, `specs/001-espina-dorsal/research.md` (R5, R6) y `docs/investigacion/2026-09-30-asr.md`.
- Marcas de evidencia: **[A]** dato del autor del modelo (model card, paper o repo oficial); **[T]** medido por terceros; **[V]** comprobado directamente en esta pasada (fichero, API de Hugging Face o GitHub); **[E]** estimación mía; **sin verificar** = no confirmado.
- Los CER de distintas fuentes **no son comparables entre sí** (conjuntos y normalización distintos). Solo se comparan dentro de una misma tabla o fuente.

## 1. Resumen ejecutivo

1. **Todo el trabajo puede hacerse con sherpa-onnx 1.13.8 en CPU** (la misma pila que el inglés, sin GPU). Los binarios y los modelos ONNX int8 ya están publicados en la release `asr-models` [V]. No hace falta ningún modelo solo para Linux.
2. **Chino, principal: X-ASR-zh-en** (junio de 2026, Apache-2.0, 160M, streaming de 160 a 1920 ms, con puntuación y mayúsculas). Hay 134 MB en int8 y CER de WenetSpeech de 7,38 (net) y 9,31 (meeting) con trozos de 480 ms [A]. Alternativa robusta y muy rápida: **SenseVoice-Small** (offline, etiqueta BGM). Alternativa de máxima precisión: Fun-ASR-Nano o Qwen3-ASR 0.6B (offline, CPU).
3. **Coreano, principal: Nemotron 3.5 ASR Streaming 0.6B**, el mismo motor y la misma familia que el inglés actual. Va por sherpa-onnx en CPU, con el idioma fijado por flujo (`set_option("language","ko")`). CER de FLEURS de 7,18 con 560 ms [A], con puntuación. Alternativa: zipformer coreano comunitario de 155M (KsponSpeech 7,5, streaming, Apache-2.0) o SenseVoice.
4. **Japonés: no existe un streaming bueno.** El único streaming razonable por sherpa es Nemotron 3.5 (CER de FLEURS de 11,9 [A]), flojo. Principal propuesto: **Parakeet-tdt_ctc-0.6b-ja int8** (offline por segmentos de VAD, CPU, con puntuación; JSUT 6,5, CV8 7,2, TEDxJP 9,1 [A]). Alternativas: ReazonSpeech zipformer k2 v2, Nemotron 3.5 (si hacen falta parciales) y Whisper large-v3-turbo en GPU (FLEURS 4,8 [T]; 2,3 GB de VRAM medidos en el spike S3).
5. **Nemotron 3.5 para chino se descarta** (CER de FLEURS de 19,5 [A]).
6. **Latencia:** un modelo offline con VAD de 500 ms cierra el final en unos 0,5 s más la decodificación. SenseVoice, por ejemplo, decodifica un trozo de 5 s en 0,1–0,3 s [E], así que el objetivo de ≤ 1 s (p95) es alcanzable. Lo que se pierde sin streaming son los **parciales** y la capacidad de traducir a mitad de frase.
7. **Hy-MT2 cumple:** licencia **Apache-2.0 sin cláusula territorial** [V] (el `LICENSE.txt` de `tencent/Hy-MT2-7B` es Apache 2.0 estándar, sin mención de la UE). Cubre ja, zh, ko y es entre sus 33 idiomas. No hay cifras publicadas por par (ja/zh/ko→es), así que el spike las mide.
8. **Cambio sugerido a ADR-0006:** su línea «ja/zh = faster-whisper con idioma detectado» queda desfasada (el idioma ahora se elige a mano y hay opciones en CPU mejores). Whisper pasa a ser alternativa o referencia en GPU. La decisión es del orquestador y del humano.
9. **Riesgos principales:** la robustez a música y efectos de los modelos streaming zh y ko **no tiene datos públicos** (spike); el zipformer coreano oficial tiene una incidencia abierta de salida vacía con audio acústico (#2886); el japonés tiene el verbo al final, así que traducir a mitad de frase rinde poco.

## 2. Tabla comparativa

Leyenda de motor: **S** = streaming nativo; **O** = offline (por segmentos de VAD); CPU = sherpa-onnx int8 salvo que se indique. Tamaño = del `.tar.bz2` de la release `asr-models` (modelo + ficheros de prueba) [V].

### 2.1 Chino (mandarín)

| Modelo | Motor | Licencia | Tamaño | Dónde corre | CER (fuente) | Puntuación | Música / ruido | Listo en sherpa-onnx |
|---|---|---|---|---|---|---|---|---|
| **X-ASR-zh-en** (2026-06) | S (160/480/960/1920 ms) y offline | Apache-2.0 [V] | 160M; 134 MB (160 y 480 ms, `punct` int8) | CPU | WenetSpeech net/meeting en streaming: 480 ms 7,38/9,31; 960 ms 6,96/8,84; 160 ms 9,45/12,04; offline 5,96/7,20 [A]. LibriSpeech clean 3,14 (480 ms) [A] | **Sí** (variantes `punct`) y mayúsculas del inglés | Sin datos; entrenado con 1 M horas [A]. Incidencia abierta: «se traga caracteres repetidos» (#14) | Sí (`sherpa-onnx-x-asr-*`, 2026-06-05) |
| zipformer-zh streaming «large» (2025-06-30) | S | sin licencia en la tarjeta (icefall Apache-2.0; datos multi-zh-hans) | 160M; 133 MB int8 | CPU | AISHELL-1 test 1,91; AISHELL-2 4,12; WenetSpeech net 8,54, meeting 7,91 (transductor greedy en streaming) [A, icefall RESULTS] | No | Sin datos | Sí |
| zipformer-zh streaming «xlarge» | S | ídem | ~700M; 598 MB int8 | CPU (más lento) | offline: WenetSpeech net 6,89, meeting 5,85 [A] | No | Sin datos | Sí |
| Paraformer-bilingual zh-en streaming (2024) | S | tarjeta HF: Apache-2.0; origen ModelScope bajo licencia FunASR | 1047 MB (fp32 + int8) | CPU | sin verificar (modelo antiguo) | No | Sin datos | Sí |
| **SenseVoice-Small** (234M) | O | FunASR Model License v1.1 (atribución; sin territorio) [V] | 163 MB (int8) | CPU o GPU | AISHELL-1 2,96; AISHELL-2 3,80; WenetSpeech net 7,84, meeting 7,44; Common Voice zh 10,78 [A, paper] | Solo el modelo 2024-07-17 con `use_itn`; el de 2025-09 **no** puntúa [A] | **Etiqueta BGM, aplausos, risa** [A] | Sí (2024-07-17 y 2025-09-09) |
| **Fun-ASR-Nano-2512** (800M, LLM) | O | Apache-2.0 [V] | 842 MB int8 | CPU (lento) o GPU | AIShell1 1,80; WenetSpeech meeting 6,60, net 6,01; «fondo complejo» 14,59 frente a 32,57 de Whisper-large-v3; letras de canciones 30,85 [A] | Sí | **Entrenado con música de fondo y ruido lejano** [A] | Sí (`funasr-nano`, 2025-12-30) |
| **Qwen3-ASR 0.6B / 1.7B** | O (streaming solo con vLLM) | Apache-2.0 [V] | 879 MB (0.6B int8) | CPU (0.6B) o GPU | FLEURS zh 2,88 / 2,41; Common Voice zh 6,89 / 5,35 [A] | Sí | Canciones con música: zh 13,91 (1.7B) [A] | Solo 0.6B int8 offline (2026-03-25). Streaming en sherpa: solicitud abierta (#3865) |
| FireRedASR2-AED (1B+) | O | Apache-2.0 [V] | 839 MB int8 | CPU (pesado) o GPU | AISHELL-1 0,57; media de 4 benchmarks de mandarín 3,05 [A] | Sí (módulo aparte FireRedPunc) | Declara soporte de canto [A] | Sí (`fire-red-asr2-zh_en-int8`). Solo zh/en |
| Whisper large-v3-turbo | O | MIT [V] | 809M; ~2,3 GB VRAM FP16 (medido en S3) | GPU (CPU: 0,8× tiempo real en un portátil [T]) | FLEURS zh 8,50 [T]; WenetSpeech meeting ~18–19, net ~10–12 (large-v3) [A] | Sí | Alucina en música sin VAD | CT2/faster-whisper nativo; también sherpa |
| Nemotron 3.5 streaming | S | OpenMDW-1.1 [V] | 475 MB (560 ms) | CPU | FLEURS zh **19,5** (560 ms) [A] | Sí | Sin datos | Sí |

### 2.2 Japonés

| Modelo | Motor | Licencia | Tamaño | Dónde corre | CER (fuente) | Puntuación | Música / ruido | Listo en sherpa-onnx |
|---|---|---|---|---|---|---|---|---|
| **Parakeet-tdt_ctc-0.6b-ja** | O (CTC en sherpa) | CC-BY-4.0 [V] | 0,6B; 489 MB int8 | CPU o GPU | **CTC**: JSUT 6,5; CV8 7,2; CV16 test 13,3; TEDxJP 9,1. TDT: 6,4/7,1/13,2/9,0 [A] | **Sí** | Sin datos; entrenado con 35 000 h de TV (ReazonSpeech) | Sí (`nemo-parakeet-tdt_ctc-0.6b-ja-35000-int8`, solo la cabeza CTC) |
| ReazonSpeech zipformer k2 v2 | O (clips de hasta ~30 s) | Apache-2.0 [V] | 159M; 713 MB | CPU | JSUT 8,07; CV8 7,42; ReazonSpeech test 8,68 [T, tabla de kotoba-whisper] | No | Sin datos | Sí (`zipformer-ja-reazonspeech-2024-08-01`) |
| Nemotron 3.5 streaming | S | OpenMDW-1.1 [V] | 475 MB | CPU | FLEURS ja **11,91** (560 ms), 11,48 (1,12 s) [A]; 13,52 [T, otra normalización] | Sí | Sin datos | Sí |
| zipformer multilingüe streaming (PengChengStarling, 2025-02) | S | Apache-2.0 [V] | 259 MB | CPU | ReazonSpeech test **13,34** (Whisper-large-v3: 16,3) [A] | No | Sin datos | Sí |
| **SenseVoice-Small** | O | FunASR v1.1 | 163 MB | CPU o GPU | Common Voice ja 11,96 [A]; FLEURS ja 7,63 [T] | Solo el modelo 2024 | Etiqueta BGM | Sí |
| **Whisper large-v3-turbo** (idioma `ja` fijado) | O | MIT | ~2,3 GB VRAM | GPU | FLEURS ja **4,82** (large-v3 4,81) [T]; CV8 de large-v3 8,5 y ReazonSpeech test 16,3 [A] | Sí | Alucina en música/silencio | faster-whisper nativo |
| Kotoba-Whisper v2.0 / v2.1 / v2.2 | O | Apache-2.0 en HF; pesos CT2 `-faster` en MIT [V] | destilado (2 capas de decoder); ~1,5–2 GB VRAM [E] | GPU | CV8 9,2; JSUT 8,4; ReazonSpeech test 11,6 [A]: **no mejora a large-v3** fuera de dominio; es 6,3× más rápido [A] | v2.1/v2.2 con puntuación (pipeline de transformers) | Como Whisper | faster-whisper (CT2) |
| Fun-ASR-Nano / MLT-Nano | O | Apache-2.0 [V] | 842 MB | CPU lento o GPU | FLEURS ja: Nano 8,50; MLT-Nano 2,32 [T]; la diferencia sugiere un problema de normalización: sin verificar | Sí | Entrenado con fondo musical [A] | Sí (solo Nano en sherpa) |
| Qwen3-ASR 0.6B / 1.7B | O | Apache-2.0 | 879 MB (0.6B) | CPU/GPU | FLEURS ja 8,33 / 5,20; CV ja 14,96 / 11,64 [A] | Sí | Música: bueno [A] | 0.6B offline |
| kodama-ja-streaming-small (2026-08) | S | Apache-2.0 | 324 MB | CPU (ORT) | no comparable; el propio autor avisa: **débil con ruido** (+0,10 CER a SNR 10 dB) y alucina el 10–12 % en varios conjuntos [A] | No | **Mala** | No (grafos ORT propios) |
| Moonshine base-ja | O | «other» (Community License no comercial, sin verificar el texto) | 104 MB | CPU | FLEURS 11,11 [T] | Sí | Sin datos | Sí |

### 2.3 Coreano

| Modelo | Motor | Licencia | Tamaño | Dónde corre | CER (fuente) | Puntuación | Música / ruido | Listo en sherpa-onnx |
|---|---|---|---|---|---|---|---|---|
| **Nemotron 3.5 streaming** | S (80 ms a 1,12 s) | OpenMDW-1.1 | 475 MB | CPU | FLEURS ko **7,18** (560 ms), 7,12 (1,12 s) [A]; 8,89 [T, otra normalización] | **Sí** | Sin datos; entrenado con un conjunto enorme y sintético, multilingüe [A] | Sí |
| zipformer coreano comunitario `kangkyu/icefall-asr-ko-streaming-zipformer-174m` (2026-05) | S (chunk 16/32/64 = 320/640/1280 ms) | Apache-2.0 en la tarjeta [V] | 155,7M; int8 | CPU (RTF 0,05–0,07 con 1 hilo [A]) | KsponSpeech: chunk 64 **7,53**; 32 7,82; 16 8,26 [A]. En el mismo conjunto: Qwen3-ASR-1.7B 9,99 y Whisper-large-v2 13,17 [A] | No | Entrenado con 6 500 h y MUSAN + RIR [A]; sin medidas de robustez independientes | Sí en formato sherpa (ficheros int8 incluidos), pero **no está en la release oficial**; un solo autor; 0 descargas [V] |
| zipformer coreano oficial 2024-06-16 | S | sin licencia en la tarjeta; el autor lo trata como Apache-2.0 [V] | 79M; 418 MB | CPU | KsponSpeech 10,0–11,1 (320–640 ms) [A] | No | **Incidencia abierta #2886:** salida vacía con audio altavoz→micrófono (entrenado solo con audio limpio) [V] | Sí (`streaming-zipformer-korean-2024-06-16`) |
| **SenseVoice-Small** | O | FunASR v1.1 | 163 MB | CPU o GPU | Common Voice ko 8,28 [A]; FLEURS ko 8,27 [T] | Solo el modelo 2024 | Etiqueta BGM | Sí |
| Qwen3-ASR 0.6B / 1.7B | O | Apache-2.0 | 879 MB (0.6B) | CPU/GPU | FLEURS ko 3,72 / 2,57 [A]; 5,82 / 4,60 [T] | Sí | Bueno [A] | 0.6B offline |
| **Whisper large-v3-turbo** (idioma `ko` fijado) | O | MIT | ~2,3 GB VRAM | GPU | FLEURS ko **5,24** (large-v3 4,89) [T]; Common Voice ko de large-v3 5,59 [A] | Sí | Alucina sin VAD | faster-whisper nativo |
| Fun-ASR-MLT-Nano | O | FunASR v1.1 / Apache-2.0 (la tarjeta dice Apache-2.0; la fuente de terceros dice FunASR: sin verificar) | 0,8B | GPU o CPU lento | FLEURS ko 5,20 [T] | Sí | Entrenado con fondo musical [A] | **No** (en sherpa solo hay el Nano zh/en/ja) |
| Moonshine base-ko / tiny-ko | O | «other» (sin verificar) | 70 MB / 30 MB | CPU | FLEURS 8,12 / 9,00 [T] | Sí | Sin datos | Sí (tiny-ko; base-ko por transcribe.cpp) |

### 2.4 Velocidad en CPU de terceros

Fuente: `models.handy.computer`, FLEURS test, cuantización Q8_0, en un **Ryzen 4750U** (portátil de 8 núcleos, bastante más lento que el 8700F) y con `transcribe.cpp`, no con sherpa. El número es «veces tiempo real» [T]:

| Modelo | CPU (× tiempo real) |
|---|---|
| SenseVoice-Small | 15,5 |
| Nemotron 3.5 (en bloque, no en streaming) | 7,5 |
| Fun-ASR-MLT-Nano | 4,5 |
| Qwen3-ASR-0.6B | 4,3 |
| Cohere Transcribe | 3,0 |
| Qwen3-ASR-1.7B | 2,0 |
| Whisper large-v3-turbo | 0,8 |

Para el 8700F (Zen 4, de sobremesa) espero más, pero **sin medir** [E]. En sherpa, SenseVoice 2024-07-17 hace un RTF de 0,099 con un solo hilo en un Cortex-A76 [A].

## 3. Detalle por opción

### 3.1 Streaming con sherpa-onnx (CPU)

**X-ASR-zh-en** (SJTU, SII, Fudan, HUST; 2026-06)
- Transductor zipformer de 160M entrenado con ~1 M horas (open source y propias), unificado para offline y streaming. Streaming verdadero con trozos de 160/480/960/1920 ms [A].
- Hay variantes `punct` (puntuación y mayúsculas) y no `punct`, en fp32 e int8, con 134 MB en int8. Licencia Apache-2.0 en la tarjeta de HF y en el repo [V].
- Cifras en streaming con 480 ms: WenetSpeech net 7,38 y meeting 9,31 [A], frente a 8,54 y 7,91 del zipformer-zh «large» de 2025 [A]. Es mejor en `net` y peor en `meeting`, pero con puntuación incluida y soporte de inglés dentro del chino (code-switching).
- Sin AISHELL publicado y sin informe técnico («coming soon»). Es un repo joven (186 estrellas, 4 incidencias abiertas). Entre ellas, «se traga caracteres repetidos» (#14) [V].
- Sherpa-onnx lo soporta desde la 1.13.3 (PR #3662) [V]. Hay una app de escritorio de los autores con una versión de Windows «preview».

**Zipformer-zh streaming «large» y «xlarge»** (icefall `multi_zh-hans`, 2025-06-30)
- Referencia fiable en chino streaming sin puntuación. AISHELL-1 test 1,91; WenetSpeech net 8,54 y meeting 7,91 [A]. El «xlarge» (~700M) es más preciso pero se mide solo offline en la tabla de icefall.
- No tiene puntuación. Habría que añadir CT-Punc (sherpa tiene `punct-ct-transformer-zh-en`, 65 MB int8 [V]) o pasar sin ella.

**Paraformer streaming bilingüe zh-en** (2024)
- Modelo antiguo de ModelScope convertido; no hay cifras actuales en las fuentes consultadas. Superado por los zipformer anteriores en tamaño y calidad. Solo sirve como respaldo.

**Nemotron 3.5 ASR Streaming 0.6B** (NVIDIA, 2026-06-04; sherpa-onnx desde 1.13.3)
- FastConformer-RNNT con caché, 40 locales, **prompt de idioma** y puntuación/mayúsculas nativas. Tamaños de trozo: 80, 160, 320, 560 y 1120 ms [A].
- **Encaje con nuestra pila:** el idioma se fija por flujo con `stream.set_option("language", "ko")` (Python, test oficial del PR #3671). Sin valor o con `auto`, detecta el idioma. Los tokens de etiqueta de idioma se filtran en el runtime. La misma API que el inglés actual [V].
- Paquetes `sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-{80,160,320,560,1120}ms-int8-2026-06-11` en la release [V]; 475 MB el de 560 ms.
- CER FLEURS (con idioma dado) para 80/160/320/560/1120 ms [A]:

  | Idioma | 80 ms | 160 ms | 320 ms | 560 ms | 1120 ms |
  |---|---|---|---|---|---|
  | ko | 7,59 | 7,70 | 7,27 | 7,18 | 7,12 |
  | ja | 13,87 | 12,90 | 12,22 | 11,91 | 11,48 |
  | zh | 20,56 | 20,22 | 20,03 | 19,51 | 19,28 |

  La tarjeta avisa de que la normalización no es perfecta y que el error real puede ser algo menor.
- Licencia OpenMDW-1.1: concede derechos amplios (uso, modificación, redistribución) sin restricción territorial ni de campo; solo mantiene los avisos y tiene una cláusula de terminación por litigio de patentes [V, texto leído]. Válida para uso personal en la UE.
- Esperable en CPU: el mismo coste que el Nemotron EN actual (0,6B int8; RTF 0,15 y 0,4 núcleos medidos en S3), **sin medir para 3.5** [E].
- Para chino queda descartado; para japonés es el único streaming razonable por sherpa, pero con un CER ~2× el de los modelos offline especializados.

**Zipformer coreano comunitario de 155,7M** (`kangkyu`, 2026-05)
- Transductor causal con vocabulario de sílabas (2 460 tokens). Entrenado con KsponSpeech (964 h) + mezcla de AI Hub (~5 500 h), con MUSAN y RIR [A]. Hay ficheros int8 de sherpa para trozos de 16, 32 y 64 fotogramas.
- KsponSpeech (eval_clean + eval_other, 6 000 frases): 7,53 con chunk 64 (latencia 1,28 s), 7,82 con 32 (640 ms), 8,26 con 16 (320 ms) [A]. RTF 0,05–0,07 con un hilo en CPU [A]. En su misma tabla, Qwen3-ASR-1.7B saca 9,99 y Whisper-large-v2 13,17 (propio, sin verificar de forma independiente).
- Los datos de AI Hub traen sus propios términos. La discusión #3926 de sherpa confirma que el ONNX tiene los mismos derechos de redistribución que el checkpoint original (Apache-2.0) [V]. Para uso personal no es un problema.
- Riesgo: un solo autor, 0 descargas, sin informe independiente.

**Zipformer coreano oficial 2024-06-16** (k2-fsa; 79M)
- Entrenado solo con KsponSpeech (audio limpio): 10,0–11,1 de CER. **Incidencia abierta #2886** (2025-12): da texto vacío con audio reproducido por altavoz y grabado por micrófono, mientras SenseVoice acierta ~90 % [V]. No sirve para contenido con música o ruido.

**Zipformer multilingüe PengChengStarling** (ar, en, id, ja, ru, th, vi, zh; 2025-02)
- Streaming con ~2 000 h por idioma; ReazonSpeech test 13,34 en japonés y WenetSpeech meeting 22,67 en chino [A]. Inferior a las opciones específicas.

### 3.2 Offline por segmentos de VAD con sherpa-onnx (CPU)

**Parakeet-tdt_ctc-0.6b-ja** (NVIDIA NeMo)
- FastConformer híbrido TDT-CTC de 0,6B entrenado con ReazonSpeech v2.0 (35 000 h de TV japonesa), con puntuación en la salida [A].
- La release de sherpa trae **solo la cabeza CTC** (`model.int8.onnx`, 489 MB). Su CER es casi igual que el de TDT: JSUT 6,5/6,4, CV8 7,2/7,1, TEDxJP 9,1/9,0 [A].
- Licencia CC-BY-4.0 (atribución) [V]. `nemo-toolkit` no funciona en Windows, pero sherpa-onnx no lo necesita.
- Sin datos de latencia en CPU. Por tamaño debe estar por debajo del Nemotron 0.6B streaming; **a medir**.
- Riesgo: el corpus es habla de televisión (noticias, programas). El habla expresiva de anime o doblaje y la música quedan fuera de dominio. Sin datos.

**ReazonSpeech zipformer k2 v2**
- RNN-T de 159M por caracteres, hecho para clips de hasta ~30 s [A]. Licencia Apache-2.0 [V]. JSUT 8,07, CV8 7,42 y ReazonSpeech test 8,68 según la tabla de kotoba-whisper [T]. Sin puntuación. Es una alternativa 100 % CPU y de licencia más sencilla, pero con CER algo peor que Parakeet-ja.
- Existe también `zipformer-ja-en-reazonspeech-2025-01-17` (438 MB) con inglés mezclado, sin cifras consultadas.

**SenseVoice-Small** (Alibaba, 234M; no autorregresivo)
- zh, yue, en, ja, ko en un solo modelo, con idioma fijable (`language="ja"`). Emite además etiquetas de **evento** (`<|BGM|>`, aplausos, risa, tos...) y de emoción [A]. Útil para detectar música y no traducirla.
- La versión 2024-07-17 puntúa con `use_itn`; la de 2025-09-09 (afinada con más cantonés) **no puntúa** [A]. Usaríamos la de 2024.
- Calidad: muy buena en chino (AISHELL-1 2,96); en japonés y coreano queda por detrás de Whisper en Common Voice (ja 11,96 frente a 10,34; ko 8,28 frente a 5,59) [A, paper].
- Velocidad: 70 ms por cada 10 s en una GPU A800 [A]; 15,5× tiempo real en el 4750U con transcribe.cpp [T].
- Licencia: FunASR Model Open Source License v1.1 [V, texto leído]: uso, copia, modificación y reparto libres con atribución y conservación del nombre del modelo. Sin cláusula territorial. Hay un punto raro (la cláusula 4.2 retira la licencia a quien denigre el modelo) y un «[Country/Region]» sin rellenar en la ley aplicable. Para uso personal es aceptable; se anota.

**Fun-ASR-Nano-2512** (Alibaba, 800M, encoder SenseVoice + decoder Qwen3-0.6B)
- zh, en, ja. Entrenado para fondo musical, campo lejano y ruido (en su tabla de industria, «fondo complejo» 14,59 de WER frente a 32,57 de Whisper-large-v3 [A]).
- Sherpa-onnx lo ejecuta en offline (842 MB int8). Autorregresivo, así que más lento en CPU que SenseVoice (4,5× tiempo real en el 4750U para el MLT [T]).
- Licencia Apache-2.0 en la tarjeta [V].

**Qwen3-ASR 0.6B / 1.7B** (Alibaba, 2026-01)
- Muy buena calidad: FLEURS zh 2,41, ja 5,20 y ko 2,57 con el 1.7B [A]; en la tabla de terceros, ko 4,60 y 5,82 (1.7B y 0.6B).
- En sherpa solo está el 0.6B int8 offline (879 MB). Una incidencia abierta mide RTF ≈ 0,30 en un móvil [V]. El streaming nativo requiere vLLM (WSL2) y su soporte en sherpa solo está pedido (#3865).
- Apache-2.0. El 1.7B en GPU necesita ~4–5 GB [E], que no caben.

**FireRedASR2-AED**
- Solo mandarín e inglés (más dialectos), con canto. AISHELL-1 0,57 [A]. Apache-2.0. Sherpa int8 de 839 MB, ~1B de parámetros: probablemente pesado para tiempo real en CPU [E]. Sin ventaja de coste frente a SenseVoice o Fun-ASR-Nano para nuestro objetivo; se deja como referencia de calidad en chino.

**Cohere Transcribe 03-2026** (2B, Apache-2.0)
- Incluye ja, ko y zh. FLEURS ja 5,13 y ko 6,57 [T]. Release sherpa int8 de 1,7 GB. Demasiado grande para CPU en tiempo real y para la GPU disponible; descartado.

### 3.3 Whisper en GPU (referencia y alternativa)

**faster-whisper + large-v3-turbo FP16** (CTranslate2 4.8.x; MIT)
- Con el idioma fijado (`language="ja"|"zh"|"ko"`) desaparece el riesgo de detectar mal el idioma. En S3 funcionó en sm_120, con **2,3 GB de VRAM**, final p50/p95 de 0,71/0,82 s con cortes a 5 s y sin parciales.
- FLEURS [T]: ja 4,82; ko 5,24; zh 8,50. En chino, WenetSpeech meeting 18–19 CER (large-v3) [A]: flojo con habla espontánea; SenseVoice y los zipformer lo superan con holgura.
- Con ~9 GB ya ocupados (traducción 5,2 + voz 3,8) y Windows (~0,7 GB), quedan **~2,3 GB**: el turbo cabe **justo**. Con el LLM 1.8B en lugar del 7B sobra espacio.
- Riesgos conocidos: alucinaciones en música y silencio (el VAD ayuda) y cortes forzados de 5 s (WER 5,82 frente a 3,42 con frases enteras en el S3 de inglés).

**Kotoba-Whisper v2.0 / v2.1 / v2.2** (japonés)
- Destilado de large-v3 con 2 capas de decoder, entrenado con ReazonSpeech. **No mejora a large-v3 fuera de dominio**: CV8 9,2 frente a 8,5; JSUT 8,4 [A]. Su ventaja es la velocidad (6,3×) y que rinde mejor en el dominio de ReazonSpeech (11,6 frente a 16,3 de large-v3, según PengChengStarling).
- Pesos CT2 para faster-whisper (`kotoba-whisper-v2.0-faster`, MIT). La v2.2 (diarización y puntuación) solo va por `transformers`.
- Sin ventaja clara sobre el turbo con idioma fijado, salvo menos VRAM.

### 3.4 Otras opciones revisadas

- **Moonshine ja/ko/zh** (offline, CPU, 30–104 MB): FLEURS ja 11,11 y ko 8,12 [T]. Licencia «other» en los modelos de otros idiomas (Community License no comercial, válida para uso personal; el texto exacto sin verificar). Sin ventaja frente a las demás opciones.
- **kodama-ja-streaming-small** (2026-08, un autor): streaming real en CPU para japonés, pero el propio autor documenta debilidad con ruido y alucinaciones. Solo para vigilar.
- **Voxtral Realtime** (≥ 16 GB), **Granite Speech 4.1**, **Nemotron 3.5 en GPU**: no encajan por VRAM; Granite no cubre coreano ni chino en ASR.
- No he encontrado un streaming japonés de 2026 que supere a Nemotron 3.5 en sherpa-onnx.

### 3.5 Hy-MT2 (traducción ja/zh/ko → es)

- **Licencia verificada [V, 2026-10-02]:** los repos `tencent/Hy-MT2-7B`, `Hy-MT2-1.8B` y sus GGUF (`-GGUF`) llevan `license: apache-2.0` en la API de Hugging Face. El `LICENSE.txt` de `Hy-MT2-7B` empieza con «Hy-MT2-7B is licensed under the Apache License, Version 2.0» y contiene el texto estándar de Apache 2.0; **no hay mención de la UE, el Reino Unido, Corea del Sur ni ningún territorio** (búsqueda de «European», «territory», «Korea» y «United Kingdom» sin resultados). Hy-MT2-30B-A3B no se ha consultado.
- **Contraste con la generación anterior:** Hunyuan-MT-7B y HY-MT1.5 llevaban la Tencent HY Community License con exclusión territorial (según `2026-09-30-traduccion-y-voz.md`). Hy-MT2 (21-may-2026) cambió a Apache-2.0. No hay que mezclar repos de generaciones distintas.
- **Idiomas:** 33 en total, entre ellos zh, zh-Hant, yue, ja, ko, es, en [V, tabla del README]. El paper (arXiv 2605.22064) dice que FLORES-200 cubre 1 056 direcciones entre 33 idiomas; Hy-MT2-7B saca 86,89 de media (XCOMET-XXL) [V]. **No publica cifras por par** (ja→es, zh→es, ko→es), y no detalla datos de subtítulos o transcripciones de ASR.
- **Conclusión:** soportado y con licencia válida; la calidad concreta de ja/zh/ko→es y con **texto de ASR sin puntuación o con errores** queda como pregunta del spike.

## 4. Recomendación para InstantTraductor

### 4.1 Por idioma

| Idioma | Principal | Alternativas (por orden) |
|---|---|---|
| **Chino** | **X-ASR-zh-en streaming, 480 ms, int8 `punct`**, sherpa-onnx, CPU. Motivos: streaming con parciales, puntuación, 134 MB, Apache-2.0, mejor `net` que el zipformer anterior | 1) **SenseVoice-Small 2024-07-17** por segmentos de VAD (muy rápido, robusto, con BGM, puntúa); 2) zipformer-zh «large» streaming 2025-06-30 (el más contrastado); 3) Fun-ASR-Nano o Qwen3-ASR 0.6B offline en CPU para máxima precisión con música; 4) Whisper turbo FP16 en GPU como referencia (peor en habla espontánea) |
| **Japonés** | **Parakeet-tdt_ctc-0.6b-ja int8 (CTC), offline por segmentos de VAD**, sherpa-onnx, CPU. Motivos: mejor CER publicado entre los modelos CPU (JSUT 6,5; CV8 7,2), con puntuación, 35 000 h de TV | 1) **Nemotron 3.5 streaming** con `language=ja` (único streaming razonable; CER ~2× peor, pero con parciales y el mismo motor que el inglés); 2) ReazonSpeech zipformer k2 v2 (Apache-2.0, sin puntuación); 3) **Whisper large-v3-turbo FP16** con `language=ja` (mejor CER de FLEURS, 2,3 GB de VRAM, sin parciales); 4) SenseVoice-Small si hace falta ligereza |
| **Coreano** | **Nemotron 3.5 streaming, 560 ms, int8**, sherpa-onnx, CPU, `language=ko`. Motivos: mismo motor y API que el inglés actual (integración mínima), CER 7,18, puntuación, streaming | 1) zipformer coreano comunitario `kangkyu` (chunk 32 o 64; si resulta robusto con música); 2) **SenseVoice-Small** por segmentos; 3) Whisper turbo FP16 con `language=ko` (FLEURS 5,24) o Qwen3-ASR 0.6B offline en CPU |

Las elecciones de japonés y coreano son **provisionales hasta el spike** (sección 5): las cifras de Nemotron 3.5 y Parakeet-ja vienen de los autores y de FLEURS/JSUT, no de contenido con música.

### 4.2 Arquitectura sugerida (sin tocar código)

- **Un solo runtime para todo:** sherpa-onnx 1.13.8 en CPU (ya fijado, con `sherpa-onnx-core` declarado). Dos perfiles de motor detrás del contrato de eventos ASR del ADR-0006:
  - **Streaming** (zh X-ASR, ko Nemotron 3.5): emite `partial` con `stable_len`, como Nemotron EN.
  - **Por segmento** (ja Parakeet, y SenseVoice como respaldo): sin parciales; solo `final` al cerrar el VAD o al corte forzado. El contrato ya prevé «capacidades declaradas por motor».
- **Idioma fijado por sesión** (`set_option("language", ...)` en Nemotron 3.5, `language=` en SenseVoice y Whisper). Se elimina la detección de idioma del camino crítico.
- **Segmentación (research R6):** el contrato actual ya no depende de la puntuación para cerrar frases, así que los modelos sin puntuación (zipformer-zh, ReazonSpeech) siguen siendo viables. Hay que **adaptar los conectores de corte** (coma estable, conjunciones) a cada idioma: no sirven las listas inglesas. Para ja y ko el verbo va al final, así que cortar a mitad de frase hace perder contexto a la traducción; conviene preferir cortar en pausa, `、`/`,` y partículas de cierre de cláusula (a decidir en la spec).
- **Orden de preferencia de la GPU:** libre para traducción (7B o 1.8B) y voz; el ASR de ja/zh/ko se queda en CPU. Whisper turbo FP16 solo como respaldo o referencia en sesiones donde sobre VRAM (~2,3 GB).
- **Competencia con juegos por la CPU:** el 8700F tiene 8 núcleos y 16 hilos; Nemotron EN usa 0,4 núcleos. Hay que medir los tres idiomas con la CPU cargada.
- **Licencias a anotar (ADR o este informe):**

  | Componente | Licencia | Nota |
  |---|---|---|
  | sherpa-onnx | Apache-2.0 | ya anotada |
  | X-ASR-zh-en | Apache-2.0 | |
  | Nemotron 3.5 | OpenMDW-1.1 | permisiva; mantener avisos; sin territorio |
  | Parakeet-tdt_ctc-0.6b-ja | CC-BY-4.0 | atribución |
  | ReazonSpeech zipformer k2 | Apache-2.0 | |
  | SenseVoice-Small | FunASR Model License v1.1 | atribución y nombre del modelo; sin territorio |
  | Fun-ASR-Nano | Apache-2.0 (tarjeta) | |
  | Qwen3-ASR | Apache-2.0 | |
  | zipformer coreano `kangkyu` | Apache-2.0 (tarjeta) | datos de AI Hub |
  | Whisper / faster-whisper | MIT | |
  | **Hy-MT2** | **Apache-2.0** | **verificado, sin territorio** |

## 5. Riesgos y preguntas abiertas

**Lo que hay que medir en un spike** (arnés del S3, `spikes/asr`, en este PC; un solo modelo a la vez por la GPU y la CPU compartidas):

1. **Corpus.** Por idioma:
   - 10–15 min de contenido real (series, películas, juegos, YouTube) con música y efectos, con transcripción de referencia hecha a mano o revisada a partir de subtítulos. La referencia es de **oído humano**: la decide el humano, no el modelo.
   - Conjuntos públicos de línea base: AISHELL-1 y WenetSpeech (`net`, `meeting`) para zh; JSUT, Common Voice y ReazonSpeech test para ja; FLEURS ko y Zeroth-Korean (CC-BY) para ko. KsponSpeech exige cuenta de AI Hub: sin verificar si es accesible.
   - 5 min solo de música/efectos/silencio, y voz sobre música a SNR de 0, 5 y 10 dB.
2. **Calidad:** CER normalizado (NFKC, sin puntuación, números unificados, mismo script) por candidato y por idioma. Inserciones por minuto en tramos de solo música (alucinación). Efecto de los cortes forzados a 4–6 s en los modelos offline.
3. **Latencia:** tiempo hasta el final desde el fin del habla, p50/p95, medido con el mismo método que S3 (VAD con `min_silence_ms` 500). Para los streaming: primer parcial, estabilidad (retractaciones, `stable_len`) y trozos de 480 frente a 960 ms (X-ASR) y de 560 frente a 1120 ms (Nemotron 3.5). Para los offline: coste de decodificar un segmento de 3, 6 y 12 s.
4. **Recursos:** RTF, núcleos, RAM y VRAM con `num_threads` de 1, 2 y 4. Repetir con la CPU cargada por un juego. Confirmar que cada paquete carga con sherpa-onnx 1.13.8 + onnxruntime 1.28 en Windows 11 y Python 3.13 (sobre todo X-ASR, Nemotron 3.5 y Parakeet-ja CTC).
5. **Decisiones concretas:**
   - zh: X-ASR frente a SenseVoice y zipformer-zh «large»; ¿entiende X-ASR inglés intercalado y traga caracteres repetidos (#14)?
   - ja: Parakeet-ja CTC frente a Nemotron 3.5 y Whisper turbo; ¿compensa la falta de parciales?
   - ko: Nemotron 3.5 frente a `kangkyu` y SenseVoice; ¿aguanta música el `kangkyu`?
   - Puntuación: ¿mejora la traducción con modelos que puntúan, frente a SenseVoice 2024 con ITN o a texto sin puntuar?
6. **Traducción (Hy-MT2 7B Q4 y 1.8B Q8):** ja/zh/ko→es sobre las salidas reales del ASR y sobre referencia limpia. Métrica COMET o chrF más revisión humana de una muestra. Comprobar el trato de texto sin puntuación, de nombres propios y del registro de España. Medir latencia por frase.

**Riesgos conocidos:**

- **Robustez con música sin datos** para los candidatos streaming (X-ASR, Nemotron 3.5, `kangkyu`) y para Parakeet-ja. Los modelos de Alibaba (Fun-ASR, SenseVoice, Qwen3) sí declaran entrenamiento con fondo musical; son el plan B natural si el spike falla. El zipformer coreano oficial ya muestra fallo con audio no limpio.
- **Modelos jóvenes y de un solo autor:** X-ASR (informe técnico pendiente), `kangkyu` (0 descargas), kodama. Se fija la revisión (hash) del modelo que se elija y se guarda una copia local fuera del repo.
- **Cifras no comparables:** FLEURS, Common Voice, JSUT, KsponSpeech y WenetSpeech no se pueden mezclar; la normalización de Nemotron 3.5 cambia el resultado (7,18 en su tarjeta frente a 8,89 de un tercero para coreano).
- **Japonés y coreano con el verbo al final:** los parciales aportan menos a la traducción simultánea que en inglés; puede ser mejor esperar a cierre de cláusula aunque el motor sea streaming.
- **Parakeet-ja en sherpa es solo la cabeza CTC:** casi igual de buena que TDT en los números del autor, pero sin latencia medida en CPU.
- **Sin puntuación en varios candidatos** (zipformer-zh, ReazonSpeech, `kangkyu`, SenseVoice 2025): CT-Punc existe solo para zh/en en sherpa; para ja y ko no hay puntuador listo en sherpa [V, lista de `punctuation-models`].
- **Licencias menores sin verificar al detalle:** Fun-ASR-MLT-Nano (Apache-2.0 en la tarjeta, FunASR v1.1 según un tercero), Moonshine ja/ko («other»), zipformer-zh de `yuekai` (sin licencia declarada, acceso restringido en HF), datos de AI Hub del `kangkyu`. Ninguno es candidato único.
- **Alucinación en silencio:** sherpa 1.13.8 corrige alucinaciones con audio silencioso en varios ASR offline (Moonshine v2, FunASR-Nano, Cohere) [V, notas de la release]; hay que confirmarlo para Parakeet-ja y SenseVoice.
- **ADR-0006:** su línea de «japonés y chino con faster-whisper y el idioma detectado» queda superada; hace falta actualizarla (decisión del orquestador, y del humano si se entiende como cambio de arquitectura).

## 6. Fuentes (consultadas el 2026-10-02)

Sherpa-onnx y runtime:
- Release `asr-models` (lista de 499 de 500 ficheros, con tamaños): https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models
- Release v1.13.8 (2026-09-10): https://github.com/k2-fsa/sherpa-onnx/releases/tag/v1.13.8
- PR #3671, soporte de Nemotron 3.5 (API `language` por flujo, tests de Python): https://github.com/k2-fsa/sherpa-onnx/pull/3671
- Issue #2886, zipformer coreano con salida vacía: https://github.com/k2-fsa/sherpa-onnx/issues/2886
- Issue #3926, redistribución del zipformer coreano: https://github.com/k2-fsa/sherpa-onnx/issues/3926
- Issue #3865, streaming de Qwen3-ASR (RTF 0,30 en móvil): https://github.com/k2-fsa/sherpa-onnx/issues/3865
- Modelos de transductor en streaming (documentación): https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/index.html
- SenseVoice en sherpa-onnx: https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html
- Release `punctuation-models`: https://github.com/k2-fsa/sherpa-onnx/releases/tag/punctuation-models

Chino:
- X-ASR-zh-en (HF): https://huggingface.co/GilgameshWind/X-ASR-zh-en · repo: https://github.com/Gilgamesh-J/X-ASR
- icefall `multi_zh-hans` RESULTS: https://github.com/k2-fsa/icefall/blob/master/egs/multi_zh-hans/ASR/RESULTS.md
- Fun-ASR-Nano-2512: https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512 · MLT-Nano: https://huggingface.co/FunAudioLLM/Fun-ASR-MLT-Nano-2512
- FireRedASR2-AED: https://huggingface.co/FireRedTeam/FireRedASR2-AED · paper: https://arxiv.org/abs/2603.10420
- SenseVoice (repo y licencia): https://github.com/FunAudioLLM/SenseVoice · https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE · paper: https://arxiv.org/html/2407.04051

Japonés:
- Parakeet-tdt_ctc-0.6b-ja: https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja
- ReazonSpeech k2 v2: https://huggingface.co/reazon-research/reazonspeech-k2-v2
- Kotoba-Whisper v2.0: https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0 · v2.2: https://huggingface.co/kotoba-tech/kotoba-whisper-v2.2 · CT2: https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0-faster
- PengChengStarling: https://huggingface.co/stdo/PengChengStarling · https://github.com/yangb05/PengChengStarling
- kodama-ja-streaming-small: https://huggingface.co/ayousanz/kodama-ja-streaming-small

Coreano:
- zipformer comunitario: https://huggingface.co/kangkyu/icefall-asr-ko-streaming-zipformer-174m
- zipformer oficial (origen): https://huggingface.co/johnBamma/icefall-asr-ksponspeech-pruned-transducer-stateless7-streaming-2024-06-12 · RESULTS: https://github.com/k2-fsa/icefall/blob/master/egs/ksponspeech/ASR/RESULTS.md

Multilingües:
- Nemotron 3.5 ASR Streaming: https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b · licencia OpenMDW-1.1: https://openmdw.ai/license/1-1/
- Qwen3-ASR (informe técnico): https://arxiv.org/abs/2601.21337 · https://huggingface.co/Qwen/Qwen3-ASR-1.7B
- Whisper large-v3-turbo: https://huggingface.co/openai/whisper-large-v3-turbo
- Cohere Transcribe: https://huggingface.co/CohereLabs/cohere-transcribe-03-2026
- Moonshine: https://github.com/moonshine-ai/moonshine

Comparativas de terceros:
- Clasificación por idioma (FLEURS, Q8_0, Ryzen 4750U): https://models.handy.computer/languages/ko · https://models.handy.computer/languages/ja · https://models.handy.computer/languages/zh · metodología: https://models.handy.computer/
- Qwen3-ASR frente a Whisper en FLEURS (blog de terceros): https://whispernotes.app/blog/qwen3-asr-vs-whisper

Hy-MT2:
- `tencent/Hy-MT2-7B` (tarjeta y `LICENSE.txt`): https://huggingface.co/tencent/Hy-MT2-7B · https://huggingface.co/tencent/Hy-MT2-7B/resolve/main/LICENSE.txt
- 1.8B y GGUF: https://huggingface.co/tencent/Hy-MT2-1.8B · https://huggingface.co/tencent/Hy-MT2-7B-GGUF · https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF
- Paper: https://arxiv.org/abs/2605.22064 (HTML: https://arxiv.org/html/2605.22064)

Internos:
- `docs/adr/0006-reconocimiento-de-voz.md`, `specs/001-espina-dorsal/research.md` (R5, R6), `docs/investigacion/2026-09-30-asr.md`, `docs/investigacion/2026-09-30-traduccion-y-voz.md`.
