# Spike S3: reconocimiento de voz en inglés en streaming

> Spike de investigación (ADR-0006), **no es código de producto**. Cerrado el 2026-10-01 con lo imprescindible; lo que queda
> pendiente está en «Límites y pendientes». Modelos y audio viven fuera del repo.

## Resumen

- **Funciona en esta máquina.** Nemotron Speech Streaming EN 0.6B (int8) sobre sherpa-onnx 1.13.8, en CPU y con Silero VAD 6.2.3 delante,
  hace streaming real en Windows 11 con Python 3.12. faster-whisper 1.2.1 + CTranslate2 4.8.2 con `large-v3-turbo` FP16 también funciona
  en la RTX 5070 (sm_120) **sin errores** de CTranslate2.
- **Motor A recomendado: exportación de 560 ms.** WER 5,05 % en las frases sueltas y 3,86 % en habla continua, RTF 0,15-0,18, **0,4-0,5 núcleos**
  (2,5-3 % del equipo), ~850 MB de RAM, 0 de VRAM. El de 160 ms sale un 17 % peor en WER en las frases sueltas (5,90 %) y gasta unas 3 veces más CPU (2,7-3,1), a cambio de un
  primer parcial 0,34 s antes (0,73 s frente a 1,07 s).
- **Latencia del texto final desde el fin real del habla: p50 0,67 s y p95 0,78 s** (A 560 ms), dominada por los 0,5 s de silencio del VAD (0,57 s hasta
  decidir) más ~0,1 s de vaciado. El texto ya está completo ~0,3 s tras el fin del habla. Con 300 ms de silencio, p50 0,49 s y p95 0,59 s, a cambio de +0,5 puntos de WER.
- **La puntuación de Nemotron no sirve para cortar frases.** Mayúsculas sí (los finales empiezan en mayúscula y salen los nombres propios). Comas solo con
  `blank_penalty` ≥ 1 (3,5 por 100 palabras). **Punto final casi nunca** (1 % de los finales). Subir `blank_penalty` lo mejora, pero cuesta WER (+0,6 a +3,5 puntos).
- **Motor B (Whisper turbo FP16):** 2,3 GB de VRAM (pico 2,4 GB), 139 ms por segmento (p95 303 ms), CPU casi nula, puntuación buena (63-67 % de finales con `. ? !`),
  pero **sin parciales**: el primer texto llega al cerrar el segmento (p50 4,8 s). **Es más preciso que A sobre el enunciado entero (WER 3,42 % frente a 5,05 %)**, pero los
  **cortes forzados a 5 s de la ADR le suben el WER a 5,82 % (frases sueltas) y 6,14 % (habla continua)**. A no pierde nada por el VAD ni por la puerta (5,05 % y 5,90 % con y sin tubería).
- **Dos correcciones para el plan:** declarar `sherpa-onnx-core` explícitamente en el `pyproject.toml` (uv lo pierde) y **no usar el endpoint nativo** de sherpa-onnx
  (WER 11,3 %, final 1,0 s).

## Objetivo

Comprobar con medidas, en esta máquina (Ryzen 7 8700F, RTX 5070 Blackwell, Windows 11), que el ASR principal de la ADR-0006 funciona en streaming real y cuánto cuesta, y compararlo con el
alternativo:

- **Motor A:** sherpa-onnx ≥ 1.13.8 en CPU con NVIDIA Nemotron Speech Streaming EN 0.6B (int8), con Silero VAD 6.2.x (ONNX, CPU) como puerta y detector de fin de frase.
- **Motor B:** faster-whisper con `large-v3-turbo` FP16 en GPU, por segmentos de VAD (con el candado de GPU).
- **Medidas:** latencia del primer parcial y del texto final desde el fin real del habla (p50/p95), RTF, % de CPU, WER normalizado, si da puntuación y mayúsculas; del motor B, WER, latencia por
  segmento y VRAM.

## Entorno

Mediciones del 2026-10-01 (de las 00:20 a las 02:40; las líneas base sin VAD, hacia las 10:00), con otros obreros trabajando a la vez en la misma máquina (ver «Carga ajena»).

| Componente | Versión / dato |
|---|---|
| Sistema | Windows 11 Pro 10.0.26200, plan de energía «Equilibrado» |
| CPU / RAM | AMD Ryzen 7 8700F (8 núcleos, 16 hilos), 31,7 GB |
| GPU | NVIDIA GeForce RTX 5070 12 GB (Blackwell, sm_120), driver 616.64 (CUDA 13.4 de usuario); en el entorno solo hay cuBLAS de CUDA 12.9 |
| Python y gestor | Python 3.12.14 (gestionado por uv), uv 0.12.21 |
| **sherpa-onnx** | **1.13.8** + `sherpa-onnx-core` 1.13.8 (trae su propio ONNX Runtime **1.28.2**) |
| **onnxruntime** (para Silero) | **1.30.0** (CPU; motor enlazado dentro de su `.pyd`, convive con el de sherpa-onnx) |
| **Silero VAD** | **6.2.3** (`silero_vad.onnx`, extraído del wheel oficial; SHA-256 `1a153a22…88e3`) |
| **faster-whisper** | **1.2.1** |
| **CTranslate2** | **4.8.2** (wheel `cp312` para Windows, trae `cudnn64_9.dll`) |
| cuBLAS | `nvidia-cublas-cu12` 12.9.2.10 (`cublas64_12.dll`) |
| Métricas y utilidades | `jiwer` 4.0.0, `whisper-normalizer` 0.1.15, `numpy` 2.5.3, `huggingface-hub` 1.33.0, `psutil` 7.2.2, `filelock` 4.0.7 |
| Modelo A | `nvidia/nemotron-speech-streaming-en-0.6b` (rev `ebe59e5a`), exportación int8 de sherpa-onnx `csukuangfj2/sherpa-onnx-nemotron-speech-streaming-en-0.6b-{160,560}ms-int8-2026-04-25` (revs `237e551a` y `52056fdc`): `encoder.int8.onnx` 652,9 MB + `decoder.int8.onnx` 7,3 MB + `joiner.int8.onnx` 1,7 MB, `feat_dim=128`. Cada exportación fija su trozo en los metadatos (`chunk_size_ms` 160 o 560) |
| Modelo B | `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (hoy redirige a `dropbox-dash/…`, rev `0a363e91`), CTranslate2 FP16, 1,62 GB |
| Extra (puntuación) | `sherpa-onnx-online-punct-en-2024-08-06` (CNN-BiLSTM, Apache-2.0) |
| Audio | `hf-internal-testing/librispeech_asr_dummy` (rev `5be91486`), recorte de LibriSpeech dev-clean, CC BY 4.0 |

Versiones exactas de todo el entorno: `uv.lock`. Modelos y audio, **siempre fuera del repo**: `%LOCALAPPDATA%\InstantTraductor\models\` (modelos), `%LOCALAPPDATA%\InstantTraductor\spikes\asr\corpus\`
(WAV montados) y la caché de Hugging Face del usuario (dataset).

## Método

### Audio de prueba
- **Fuente:** `hf-internal-testing/librispeech_asr_dummy` (partición `clean/validation`), un recorte de **LibriSpeech dev-clean** (CC BY 4.0 de LibriSpeech; el repositorio de Hugging Face no declara licencia
  propia). No pide cuenta. 73 enunciados de un único hablante (1272), de 1,6 a 29,4 s: **481,0 s de habla y 1 150 palabras** de referencia (1 169 tras normalizar), en MAYÚSCULAS y sin puntuación.
- **Flujo `gapped` (frases sueltas, 593,7 s):** los 73 enunciados separados por huecos de 1,2-1,8 s de ruido blanco muy bajo (-66 dBFS; un loopback real nunca es silencio digital). Sirve para medir latencias por enunciado.
- **Flujo `continuous` (habla continua, 185,9 s):** los 19 primeros enunciados pegados sin hueco añadido (435 palabras); los silencios son los naturales de la lectura. Sirve para medir estabilidad y tramos largos.

### Habla «real» para las latencias
Las latencias se miden contra el inicio y el fin reales de la habla, calculados por **energía** (tramas de 25 ms cada 10 ms; umbral = máx(suelo de ruido + 15 dB, percentil 95 - 28 dB); se unen huecos de menos
de 250 ms y se descartan tramos de menos de 150 ms). Es independiente de Silero. Contraste con Silero 6.2.3 sobre los 73 enunciados: Silero marca el inicio de media 32 ms después (p95 69 ms) y el fin 67 ms después
(p95 167 ms). La incertidumbre del oráculo es de unas decenas de ms.

### Alimentación en tiempo real
El audio llega en **trozos de 32 ms** (una trama de Silero; también se probaron 20 y 100 ms). El trozo que termina en la muestra `n` se entrega cuando han pasado `n/16000` s de reloj de pared desde el inicio, como haría una
captura. Si el procesamiento se retrasa, los siguientes se entregan de golpe hasta ponerse al día (queda registrado como «retraso del alimentador»). Los tiempos de los eventos están en **segundos del reloj de audio**
(= reloj de pared desde el inicio). Antes de cada medición hay un calentamiento de 8-10 s de audio que no cuenta, y la campaña (`campaign/paced_runs.sh`) espera hasta 4 min a que la CPU global baje
del 25 % (`campaign/wait_quiet.py`). El modo `fast` (sin esperar) da cómputo, RTF y WER, y latencias «algorítmicas» sin tiempo de cómputo; solo se usó para el barrido de `blank_penalty`
(`campaign/bp_sweep.sh`).

### Tubería del motor A
1. **Silero VAD 6.2.3** (`silero_vad.onnx`, onnxruntime en CPU, 1 hilo), tramas de 32 ms: umbral de entrada 0,5 y de salida 0,35, **fin de turno tras 500 ms de silencio**, tramos de menos de 250 ms se descartan, relleno previo de 300 ms.
2. **Puerta:** solo entra al reconocedor el audio con habla (más el relleno previo), con un stream nuevo por tramo.
3. **Nemotron Speech Streaming EN 0.6B int8** en sherpa-onnx (`OnlineRecognizer.from_transducer`, `feature_dim=128`, `greedy_search`, **`blank_penalty=1.0`**, 2 hilos salvo que se indique), exportaciones de **160 ms** y **560 ms**.
4. **Parciales:** tras cada trozo de entrada se decodifica lo que esté listo y, si el texto cambia, se emite `partial`.
5. **Final:** al decidir el VAD el fin de turno se rellena con ceros (un trozo del modelo), `input_finished()`, se decodifica el resto y se emite `final` + `endpoint`.
6. **Variante `native`:** sin VAD, todo el audio a un único stream y el `final` lo marca el detector de endpoint de sherpa-onnx (0,8 s de silencio decodificado).

### Tubería del motor B
Mismo Silero VAD y parámetros. faster-whisper con `large-v3-turbo` en **FP16**, haz 1, `language="en"`, `condition_on_previous_text=False`, `temperature=0`, `no_speech_threshold=0.6`, `log_prob_threshold=-1.0`,
`compression_ratio_threshold=2.4`, sin timestamps ni VAD propio. Segmento cerrado por el VAD o **cortado a los 5 s** en la trama de menor probabilidad de habla de la última ventana de 1 s. Cada segmento se transcribe en un
**hilo aparte** (como haría la tubería real). Sin parciales. Toda la medición en GPU, bajo el candado `gpu.lock`.

### Métricas
| Métrica | Definición |
|---|---|
| Primer parcial / primer texto | primer parcial con texto menos el inicio real de la habla del segmento (en B, que no da parciales, «primer texto» es el del final del segmento) |
| Final | instante de emisión del `final` menos el fin real de la habla |
| Texto completo | primer parcial cuyo texto normalizado ya coincide con el final, menos el fin real (cuándo estaba el texto, aunque el evento `final` llegue después) |
| Desglose del final | decisión de cerrar (fin real → decisión del VAD) + después de decidir (vaciado, cola e inferencia → emisión) |
| WER | WER de corpus (errores / palabras de referencia) sobre la concatenación de los finales, tras el normalizador inglés de Whisper (`whisper-normalizer`) aplicado a referencia e hipótesis; `jiwer` |
| RTF | tiempo de cómputo de la tubería (sin las esperas) dividido por los segundos de audio |
| CPU | tiempo de CPU del proceso (usuario + sistema, todos los hilos) dividido por el tiempo de pared: «núcleos de media» y % de los 16 hilos del equipo |
| Estabilidad de parciales | caracteres del parcial anterior que el siguiente cambia o borra; parciales que acaban a mitad de palabra; segmentos cuyo final es idéntico al último parcial |
| Puntuación | comas y marcas finales (`. ? !`) por 100 palabras, % de finales que acaban en `. ? !` y % que empiezan en mayúscula |
| Carga ajena | tiempo de CPU consumido por los demás procesos durante la ejecución y CPU global media y máxima |

## Resultados

Todas las cifras salen de `results/*.json` (`uv run python report.py ...`). Las latencias son p50 / p95 en segundos y solo valen en las ejecuciones en tiempo real.

### Tabla 1: A frente a B con frases sueltas (73 enunciados, 594 s, tiempo real)

| Métrica | **A: Nemotron 560 ms** | A: Nemotron 160 ms | **B: Whisper turbo FP16** | A 160 ms con endpoint nativo (sin VAD) |
|---|---|---|---|---|
| WER normalizado | **5,05 %** | 5,90 % | 5,82 % (con corte forzado a 5 s; 3,42 % con el enunciado entero, tabla 6) | 11,29 % |
| Errores sustituciones / borrados / inserciones (de 1 169) | 46 / 8 / 5 | 56 / 10 / 3 | 36 / 11 / 21 | 55 / 72 / 5 |
| Primer parcial (en B: primer texto del segmento) | 1,07 / 1,12 | **0,73 / 1,06** | 4,84 / 8,27 | 0,81 / 4,02 |
| Final desde el fin real del habla | **0,67 / 0,78** | 0,69 / 0,75 | 0,71 / 0,82 | 1,01 / 1,46 |
| …solo finales que cierran un enunciado | 0,69 / 0,78 | 0,70 / 0,79 | 0,72 / 0,84 | 1,03 / 1,52 |
| …desglose p50: decisión del cierre + después | 0,57 + 0,09 | 0,58 + 0,11 | 0,57 + 0,13 | 0,94 + 0,07 |
| Texto completo (parcial = final) | 0,31 / 0,61 | 0,21 / 0,53 | no hay parciales | 0,22 / 0,66 |
| RTF (cómputo / audio) | 0,152 | 0,385 | 0,012 (VAD) + 0,038 (GPU ocupada) | 0,452 |
| CPU propia: núcleos de media (% de los 16 hilos) | **0,40 (2,5 %)** | 1,08 (6,7 %) | 0,06 (0,4 %) | 1,28 (8,0 %) |
| CPU ajena durante la ejecución: núcleos (CPU global media %) | 0,69 (15,6) | 0,54 (31,4) | 0,57 (5,3) | 1,43 (24,7) |
| RAM del proceso | 850 MB | 856 MB | pico 1 760 MB | 827 MB |
| **VRAM del proceso** | 0 | 0 | **2 300 MB tras cargar, pico 2 396 MB** | 0 |
| Segmentos (finales a mitad de habla o por corte forzado) | 93 (0) | 92 (0) | 138 (45) | 109 (34) |
| Comas / marcas finales por 100 palabras | 3,5 / 0,2 | 3,3 / 0,2 | 4,2 / 9,2 | 3,0 / 0,2 |
| Finales que acaban en `. ? !` / empiezan en mayúscula | 1 % / 100 % | 1 % / 99 % | 67 % / 67 % | 0 % / 99 % |

Notas de B: inferencia por segmento p50 139 ms, p95 303 ms (máx. 326 ms), con segmentos de 3,8 s de mediana y 5,0 s como máximo (RTF de inferencia 0,051), sin cola
(p95 0,1 ms); la GPU estuvo ocupada de media el 3,2 %. Latencia por segmento (cola + inferencia desde que se cierra): p50 139 ms, p95 303 ms. Un corte forzado a los 5 s
tarda en dar texto p50 0,41 s y p95 1,10 s. Carga de la GPU: 1 490 MB usados antes de cargar el modelo y 3 790 MB después (+2 300 MB). Modelo cargado en 3,1 s y
primera transcripción en 1,1 s con la caché de cómputo caliente.

### Tabla 2: habla continua (19 enunciados, 186 s, tiempo real)

| Métrica | **A: Nemotron 560 ms** | A: Nemotron 160 ms | **B: Whisper turbo FP16** |
|---|---|---|---|
| WER normalizado | 3,86 % | **3,64 %** | 6,14 % |
| Errores S / D / I (de 440) | 13 / 1 / 3 | 13 / 2 / 1 | 11 / 4 / 12 |
| Primer parcial (en B: primer texto del segmento) | 1,05 / 1,10 | **0,68 / 1,02** | 4,91 / 9,43 |
| Final desde el fin real del habla | **0,65 / 0,75** | 0,69 / 0,81 | 0,69 / 0,79 |
| Texto completo | 0,27 / 0,57 | 0,20 / 0,52 | no hay parciales |
| RTF | 0,182 | 0,539 | 0,013 (VAD) + 0,038 (GPU) |
| CPU propia: núcleos (% del equipo) | **0,48 (3,0 %)** | 1,46 (9,1 %) | 0,06 (0,4 %) |
| CPU ajena: núcleos (CPU global media / máx. %) | 0,67 (16,0 / 33,8) | 3,0 (42,0 / 60,6) | 1,08 (8,6 / 39,8) |
| Segmentos (a mitad de habla o forzados) | 28 (0) | 28 (0) | 51 (23) |
| Comas / marcas finales por 100 palabras | 2,5 / 0,2 | 3,0 / 0,0 | 4,3 / 9,7 |

**Estabilidad (3 min de habla continua y ~10 min con huecos):** sin deriva. RTF por tercios de la ejecución: A 560 ms `0,179 / 0,182 / 0,184`; A 160 ms `0,617 / 0,510 / 0,491` (el primer tercio coincidió
con 3 núcleos de carga ajena). El retraso del alimentador es de unos 5-25 ms de media por tercio y no se acumula (máximo puntual 0,17-0,23 s). RAM constante (~830 MB).

### Estabilidad de los parciales de Nemotron (4 ejecuciones con VAD)
- **Solo se añade texto: 0 caracteres retractados en 2 811 transiciones de parciales** (más 1 338 en la variante `native`). Con `greedy_search` el parcial nunca se corrige.
- Aun así, **el 15-21 % de los parciales acaban a mitad de palabra** (`squal` → `squalid`): la última palabra no es fiable (A 160 ms: 21 %; A 560 ms: 15 %).
- El `final` es idéntico al último parcial en el 82-93 % de los segmentos (87 % y 82 % con 560 ms; 93 % y 86 % con 160 ms); en el resto, el vaciado añade algún token.
- Parciales por segmento: p50 6 con 560 ms; el parcial llega cada ~160 o ~560 ms de audio.
- El VAD parte algunos enunciados por pausas de más de 0,5 s (93 y 92 segmentos para 73 enunciados). El único segmento descartado (A 160 ms) fue la última palabra de un enunciado (`quickly`) separada
  por una pausa de ~1 s: A 160 ms no devolvió texto y A 560 ms devolvió `Out`. Los segmentos cortos tras una pausa larga son el punto débil de la puerta.

### Tabla 3: hilos de sherpa-onnx (habla continua, tiempo real, peor caso de CPU)

| Trozo (ms) | Hilos | RTF | CPU propia (núcleos) | % del equipo | `push()` p95 / máx. (ms) | Retraso del alimentador p95 / máx. (ms) | Final p50 / p95 (s) | 1.er parcial p50 / p95 (s) | WER % | CPU ajena (núcleos) |
|---|---|---|---|---|---|---|---|---|---|---|
| 160 | 1 | 0,773 | 0,768 | 4,8 | 126 / 255 | 97 / 306 | 0,78 / 0,83 | 0,74 / 1,08 | 3,64 | 0,82 |
| 160 | 2 | 0,539 | 1,458 | 9,1 | 93 / 246 | 67 / 219 | 0,69 / 0,81 | 0,68 / 1,02 | 3,64 | 3,0 |
| 160 | 4 | 0,328 | 2,537 | 15,9 | 54 / 115 | 22 / 100 | 0,65 / 0,69 | 0,64 / 0,98 | 3,64 | 0,62 |
| 560 | 1 | 0,299 | 0,298 | 1,9 | 157 / 320 | 126 / 289 | 0,73 / 0,88 | 1,12 / 1,16 | 3,86 | 1,47 |
| 560 | 2 | 0,182 | 0,477 | 3,0 | 91 / 199 | 59 / 168 | 0,65 / 0,75 | 1,05 / 1,10 | 3,86 | 0,67 |
| 560 | 4 | 0,182 | 1,142 | 7,1 | 86 / 184 | 55 / 153 | 0,65 / 0,76 | 1,05 / 1,10 | 3,86 | 2,93 |

Más hilos **no ahorran CPU total, la gastan**: con 1 hilo la CPU propia coincide con el RTF (0,77 y 0,30 núcleos); con 2 y 4 sube a 1,5-2,5 núcleos (160 ms) y a 0,5-1,1 (560 ms) por el mismo trabajo (probable espera
activa de los hilos de ONNX Runtime). Con 560 ms, 4 hilos no mejoran nada respecto a 2. El WER no cambia con los hilos. La CPU ajena varió de 0,6 a 3,0 núcleos entre ejecuciones, así que las diferencias pequeñas no son concluyentes.

### Tabla 4: `blank_penalty` (modo rápido, flujo con huecos completo, 594 s)

| Trozo (ms) | `blank_penalty` | WER % | S / D / I | Comas / 100 pal. | Marcas finales / 100 pal. | Finales con `. ? !` | Segmentos |
|---|---|---|---|---|---|---|---|
| 160 | 0 | 6,42 | 60 / 12 / 3 | 2,5 | 0,2 | 0 % | 92 |
| 160 | **1** | **5,90** | 56 / 10 / 3 | 3,3 | 0,2 | 1 % | 92 |
| 160 | 2 | 7,01 | 62 / 10 / 10 | 4,3 | 1,0 | 8 % | 93 |
| 160 | 3 | 9,41 | 73 / 12 / 25 | 4,7 | 2,0 | 18 % | 93 |
| 560 | 0 | 5,13 | 48 / 8 / 4 | 2,4 | 0,3 | 0 % | 92 |
| 560 | **1** | **5,05** | 46 / 8 / 5 | 3,5 | 0,2 | 1 % | 93 |
| 560 | 2 | 5,65 | 52 / 6 / 8 | 4,3 | 1,6 | 14 % | 93 |
| 560 | 3 | 6,42 | 56 / 7 / 12 | 4,7 | 2,9 | 28 % | 93 |

Con `blank_penalty=0` (el valor por defecto) hay mayúsculas pero ninguna coma ni punto. `blank_penalty=1` da el mejor WER con los dos trozos y comas; los puntos finales solo aparecen de forma
apreciable con 2-3, pagando 0,6-3,5 puntos de WER (más inserciones).

### Tabla 5: silencio que cierra el turno y tamaño del trozo de entrada (A 560 ms, tiempo real)

| Silencio (flujo con huecos) | WER % | Segmentos | Final p50 / p95 (s) | Final por enunciado p50 / p95 (s) | Texto completo p50 / p95 (s) |
|---|---|---|---|---|---|
| 500 ms (por defecto) | 5,05 | 93 | 0,67 / 0,78 | 0,69 / 0,78 | 0,31 / 0,61 |
| 300 ms | 5,56 | 116 | **0,49 / 0,59** | 0,50 / 0,60 | 0,24 / 0,47 |

| Trozo de entrada (25 primeros enunciados) | 1.er parcial p50 / p95 (s) | Final p50 / p95 (s) | RTF | WER % |
|---|---|---|---|---|
| 20 ms | 0,86 / 1,10 | 0,68 / 0,77 | 0,161 | 4,13 |
| 32 ms (por defecto) | 0,88 / 1,11 | 0,69 / 0,79 | 0,177 | 4,13 |
| 100 ms | 0,86 / 1,16 | 0,72 / 0,81 | 0,150 | 4,13 |

El tamaño del trozo de entrada (20-100 ms) casi no cambia nada: el final se retrasa unos 0,03 s con 100 ms.

### Tabla 6: WER sin segmentar ni VAD (cada enunciado entero, 73 enunciados)

Separa lo que da cada modelo de lo que cuesta la tubería (`baseline_offline.py`; sin pacing ni VAD; A con 4 hilos).

| Motor | WER % | S / D / I | Comas / 100 pal. | Marcas finales / 100 pal. | Textos con `. ? !` | RTF (sin pacing) |
|---|---|---|---|---|---|---|
| A: Nemotron 560 ms, `blank_penalty` 1 | **5,05** | 45 / 10 / 4 | 4,1 | 0,9 | 1 % | 0,167 |
| A: Nemotron 160 ms, `blank_penalty` 1 | 5,90 | 49 / 14 / 6 | 4,5 | 0,8 | 1 % | 0,445 |
| B: Whisper turbo FP16, haz 1 | **3,42** | 32 / 5 / 3 | 4,2 | 5,0 | 70 % | 0,023 |
| B: Whisper turbo FP16, haz 5 | **3,42** | 32 / 5 / 3 | 3,0 | 4,4 | 64 % | 0,025 |

- **La tubería de A no añade errores:** el WER con VAD, puerta y vaciado (tablas 1 y 4) es el mismo que con el enunciado entero (5,05 % y 5,90 %).
- **Whisper turbo es más preciso en este audio** (3,42 %, un 32 % menos de errores que A 560 ms; haz 1 y haz 5 empatan), pero **los cortes forzados a 5 s le cuestan 2,4 puntos** (5,82 % en la tubería, con 21 inserciones por palabras repetidas en los cortes).
- B sin cortes forzados dentro de la tubería (VAD solo) no se midió: ver «Límites y pendientes».

### Tabla 7: ¿da puntuación y mayúsculas?

| Texto | Comas / 100 pal. | Marcas finales / 100 pal. | Finales con `. ? !` | Palabras en mayúscula / 100 pal. | Finales que empiezan en mayúscula |
|---|---|---|---|---|---|
| A 560 ms, `blank_penalty=0` | 2,4 | 0,3 | 0 % | 13,4 | 100 % |
| A 560 ms, `blank_penalty=1` (elegido) | 3,5 | 0,2 | 1 % | 13,2 | 100 % |
| A 560 ms, `blank_penalty=1` + modelo de puntuación aparte (extra) | 4,8 | 2,3 | 19 % | 14,0 | 100 % |
| B Whisper turbo (cortes a 5 s) | 4,2 | 9,2 | 67 % | 12,6 | 67 % |

- **Mayúsculas: sí.** Inicio de frase y nombres propios (`Mister Quilter`, `Hester Prynne`); cuando un tramo continúa una frase empieza en minúscula (`makes a customary appeal…`).
- **Puntuación: parcial.** Comas con `blank_penalty ≥ 1`; punto final casi nunca. El modelo de puntuación de sherpa-onnx (CNN-BiLSTM, 11 ms por llamada en CPU, `results/punct_extra.json`) sube los puntos finales
  al 19 % de los finales: insuficiente para cortar por oraciones. Whisper puntúa mucho más (63-67 % de finales con `. ? !`).
- Los 73 enunciados de LibriSpeech no llevan puntuación de referencia, así que solo se miden densidades, no aciertos.

### Carga ajena durante las ejecuciones principales
Había otros obreros trabajando (otros spikes de Python, `llama-server.exe` con la traducción, `ffplay.exe` de audio) además de Defender (`MsMpEng`), FireStorm, VS Code y los lanzadores de juegos. Las
ejecuciones esperaron hasta 4 min a una ventana con la CPU global por debajo del 25 %. El listado completo está en `uv run python report.py --section load`.

| Ejecución | CPU propia (núcleos) | CPU ajena (núcleos) | CPU global media / máx. (%) | Procesos ajenos con más CPU (núcleos de media) |
|---|---|---|---|---|
| A 160 ms, frases sueltas | 1,08 | 0,54 | 31,4 / 50,1 | System 0,1, FireStorm 0,06, Code 0,04, llama-server 0,04 |
| A 560 ms, frases sueltas | 0,40 | 0,69 | 15,6 / 50,9 | python 0,12, System 0,1, MsMpEng 0,08, Code 0,07 |
| B, frases sueltas | 0,06 | 0,57 | 5,3 / 23,6 | System 0,09, MsMpEng 0,07, FireStorm 0,07, Code 0,04 |
| A 160 ms, endpoint nativo | 1,28 | 1,43 | 24,7 / 47,4 | python 0,9, System 0,1, MsMpEng 0,06, FireStorm 0,06 |
| A 160 ms, habla continua | 1,46 | **3,0** | 42,0 / 60,6 | python 2,21, svchost 0,19, System 0,15, MsMpEng 0,1 |
| A 560 ms, habla continua | 0,48 | 0,67 | 16,0 / 33,8 | System 0,12, python 0,08, MsMpEng 0,07, FireStorm 0,06 |
| B, habla continua | 0,06 | 1,08 | 8,6 / 39,8 | python 0,51, System 0,09, MsMpEng 0,07, FireStorm 0,07 |

El motor B esperó 263,7 s al candado de GPU (otro obrero medía en ese momento). La GPU antes de cargar el modelo tenía 1 490 MB en uso y una utilización del 0 %.

## Problemas y soluciones

1. **`sherpa-onnx` falla al importarse en Windows con uv: «The requested API version [28] is not available, only API versions [1, 17] are supported in this build. Current ORT Version is: 1.17.1».**
   El wheel `sherpa_onnx-1.13.8-…-win_amd64.whl` pesa 2,3 MB porque ya no lleva las DLL nativas: declara `Requires-Dist: sherpa-onnx-core==1.13.8`, pero los metadatos difieren entre plataformas y la resolución universal
   de uv (`uv lock`) los pierde (el paquete queda sin dependencias en `uv.lock`). Sin `sherpa-onnx-core`, el `.pyd` no encuentra sus DLL y acaba cargando el `onnxruntime.dll` 1.17.x que el propio Windows 11 trae en
   `C:\Windows\System32`. **Solución:** declarar `sherpa-onnx-core>=1.13.8` explícitamente en el `pyproject.toml`. Con él, sherpa-onnx usa su ONNX Runtime 1.28.2 (en `site-packages\sherpa_onnx\lib`).
   **Hay que repetirlo en el `pyproject.toml` del producto.**
2. **`onnxruntime` de pip y el de sherpa-onnx en el mismo proceso.** Convivieron sin problema cargando sherpa-onnx y después onnxruntime (como hace la tubería): el de pip (1.30.0) lleva su motor dentro del `.pyd` y el
   de sherpa-onnx usa su propia `onnxruntime.dll` 1.28.2. Silero (onnxruntime) y el ASR (sherpa-onnx) pueden ir en el mismo proceso, como prevé la arquitectura. No se probó el orden de importación inverso.
3. **El paquete `silero-vad` de PyPI exige `torch`** (dependencia dura). Se evita extrayendo `silero_vad.onnx` del wheel oficial de 6.2.3 (SHA-256 verificado contra PyPI) y ejecutándolo con onnxruntime. El envoltorio
   propio (`asrspike/vad.py`: contexto de 64 muestras, estado `[2, 1, 128]`, histéresis de `VADIterator`) cabe en ~150 líneas con comentarios.
4. **Nemotron con la configuración por defecto (`blank_penalty=0`) no puntúa:** sale texto con mayúsculas pero sin comas ni puntos (probablemente el decodificador voraz prefiere el símbolo en blanco a los signos,
   que tienen poca probabilidad). Subir `blank_penalty` (parámetro de `OnlineRecognizer.from_transducer`) los destapa a cambio de WER (tabla 4). `blank_penalty=1.0` fue el mejor en WER con los dos trozos. El punto final de
   frase sigue casi sin aparecer.
5. **El endpoint nativo de sherpa-onnx pierde palabras.** Tras el endpoint hay que hacer `reset()`, que descarta lo que aún no se había emitido, y a veces dispara a mitad de frase (34 de 109 finales). WER 11,3 % frente
   a 5,9 % con el VAD delante y final a 1,0 s en lugar de 0,7 s. Por eso la tubería corta con Silero, vacía el reconocedor (relleno de ceros + `input_finished()`) y crea un stream nuevo por tramo.
6. **ONNX Runtime gasta CPU de más con varios hilos** (tabla 3): con 160 ms y habla continua, 2 hilos consumen 1,5 núcleos y 4 hilos 2,5, frente a 0,77 con 1 hilo. sherpa-onnx no expone
   `session.intra_op.allow_spinning`; la palanca es el número de hilos y el trozo.
7. **CTranslate2 en Blackwell (sm_120): sin errores.** CTranslate2 4.8.2 con CUDA 12 funcionó a la primera con FP16 y declara también `int8`, `int8_float16`, `bfloat16` y `float32` como compatibles con la GPU
   (solo se midió FP16). Hace falta `cublas64_12.dll`: se instala `nvidia-cublas-cu12` y se registra su carpeta con `os.add_dll_directory` **y** en `PATH` (CTranslate2 la carga con `LoadLibrary`). El wheel
   de Windows ya trae `cudnn64_9.dll`. **Primer arranque en frío:** la primera transcripción tardó 17,7 s en una prueba previa (no guardada; probable compilación JIT de núcleos PTX para sm_120, que queda en la caché de
   cómputo de NVIDIA); en las ejecuciones medidas, con la caché ya caliente, 1,1 s. Hay que precalentar el motor B en el primer arranque de la app.
8. **Memoria de GPU por proceso en Windows.** `nvidia-smi` devuelve «N/A» por proceso con WDDM. Se usó el contador `\GPU Process Memory(pid_<pid>_*)\Dedicated Usage` (PowerShell persistente). Para el proceso propio coincide con
   el aumento de `memory.used` (2 300 MB = 3 790 - 1 490), pero para otros procesos (p. ej. `dwm.exe`) da cifras mayores que el total usado, así que solo es fiable para el proceso propio.
9. **Repositorio de Whisper renombrado.** `mobiuslabsgmbh/faster-whisper-large-v3-turbo` redirige ahora a `dropbox-dash/…`; `huggingface_hub` sigue la redirección.
10. **Máquina compartida.** Otros obreros ejecutaban a la vez `llama-server`, `ffplay`, otros spikes de Python, etc. (sección «Carga ajena»). Las ejecuciones en tiempo real esperan hasta 4 min a una ventana con la CPU global
    por debajo del 25 % y registran la carga ajena. En el motor B, el candado de GPU hizo esperar 4,4 min.
11. **La sesión se interrumpió por el límite de uso del plan** con la campaña en marcha; la campaña terminó sola y todos sus resultados estaban guardados. Antes de la interrupción se repitió entera la campaña en tiempo real
    con el análisis final (las primeras ejecuciones se descartaron), así que las tablas 1-3 y 5 usan las mismas definiciones. El barrido de `blank_penalty` (tabla 4) se hizo antes, en modo rápido, con una versión anterior del
    análisis (mismos WER y puntuación que las ejecuciones en tiempo real; sus latencias «algorítmicas» no se usan).

## Conclusión y recomendación para el plan

**La ADR-0006 se sostiene.** El ASR principal funciona en CPU, en streaming real y con un coste muy bajo; el alternativo funciona en la 5070 sin problemas de CTranslate2. Cambios y matices que conviene llevar al plan:

1. **Usar la exportación de 560 ms por defecto** (`num_threads=2`, `blank_penalty=1.0`, Silero con 500 ms de silencio): WER 5,05 % (3,9 % en habla continua), final p50 0,67 s / p95 0,78 s desde el fin real del habla, 0,4-0,5 núcleos,
   ~850 MB de RAM, sin VRAM, sin deriva en 10 min. Encaja en el presupuesto de ASR de `docs/arquitectura.md` (≤ 0,8 s), pero con poco margen en p95 (0,78 s) y bajo carga ajena. La de 160 ms solo compensa si hacen falta parciales más
   ágiles (primer parcial 0,73 s en lugar de 1,07 s) y cuesta unas 3 veces más CPU (2,7-3,1) y +0,85 puntos de WER. Con 1 hilo, 560 ms sigue yendo holgado (RTF 0,30, 0,3 núcleos) con +0,08 s de final: es la opción si la CPU escasea.
2. **El silencio del VAD manda en la latencia del final** (0,57 s de 0,67 s). Con 300 ms: final p50 0,49 s / p95 0,59 s, a cambio de 23 segmentos más (116 frente a 93, más cortes a mitad de frase) y +0,5 puntos de WER.
   El texto está completo ~0,3 s después del fin real del habla, así que el planificador puede adelantar la confirmación (texto estable + silencio del VAD) sin esperar al `final`.
3. **No contar con la puntuación de Nemotron para cortar en oraciones.** Hay mayúsculas y comas (con `blank_penalty ≥ 1`), pero casi ningún punto final (1 % de los finales; 14-28 % con `blank_penalty` 2-3 a costa de +0,6 a +1,4 puntos de WER con
   560 ms). El planificador debe cortar por `endpoint` (silencio) y por `T_max`, y usar `. ? !` solo como pista. Un modelo de puntuación aparte sube los puntos finales al 19 % (11 ms por llamada): no lo resuelve. Whisper sí puntúa (67 %).
4. **Contrato de eventos ASR (§4.4):** los parciales de Nemotron solo añaden texto (0 retractaciones en 2 811 transiciones), por lo que `stable_len` puede ser `len(text)` hasta el último espacio: la última palabra puede estar incompleta
   (15-21 % de los parciales). El `final` coincide con el último parcial en 82-93 % de los segmentos. Eventos observados: `speech_start`, `partial` (cada 160 o 560 ms de audio), `final` y `endpoint`.
5. **Dependencias y arranque:** `sherpa-onnx-core` explícito (problema 1); onnxruntime de pip (Silero) y sherpa-onnx pueden compartir proceso; **no usar el endpoint nativo** (WER 11,3 %, final 1,0 s) sino VAD + vaciado + stream nuevo por tramo;
   que no haga falta CUDA para el ASR principal.
6. **Motor B como respaldo y referencia de calidad, no como vía de baja latencia.** FP16 en sm_120 funciona; 2,3 GB de VRAM (2,4 GB de pico, a sumar al presupuesto de `docs/arquitectura.md`), 139 ms de mediana por segmento (p95 303 ms) y CPU casi nula. Sin parciales:
   el primer texto de un segmento llega p50 4,8 s / p95 8,3 s tras empezar a hablar (el final, p50 0,71 s tras el fin real, igual que A). **El corte forzado a 5 s de la ADR cuesta 2,4 puntos de WER** (3,42 % con el enunciado entero, 5,82 % en la tubería; 6,14 % en habla continua):
   con segmentos así B no gana a A 560 ms (5,05 %). Cortes más largos o por frontera de cláusula, o un solapamiento entre segmentos, mejorarían el WER a costa de latencia: no medido. Precalentarlo al arrancar (17,7 s en frío). Sirve para ja/zh (spec 004) y para puntuar frases ya cerradas.
7. **Calidad A frente a B:** sobre enunciados enteros, B es claramente mejor en este audio (3,42 % frente a 5,05 %); en streaming, A conserva su WER y B pierde con los cortes. Este audio es lectura limpia de un solo hablante, de un dominio (audiolibros de LibriVox)
   muy cercano al de entrenamiento (la ficha de Nemotron cita LibriLight), así que las cifras absolutas son optimistas. Con música, efectos, acentos y otros hablantes, la medición con corpus propio es la de la spec 002, como dice la ADR.

## Límites y pendientes

- **Pendiente (el script ya está):** WER de B **dentro de la tubería sin corte forzado** y con otros largos de corte (3, 8 y 15 s) y haz 5 (`run_engine_b.py --variant etiqueta:gapped:fast:1:0`, `…:1:8`, `…:5:5`), para cuantificar cuánto WER recupera B a costa de latencia.
  `report.py --section b` genera su tabla. También quedan sin ejecutar los barridos «de relleno»: relleno de ceros del vaciado y silencio de cierre en modo rápido (`report.py --section a-misc`).
- No medido: música y efectos, otros hablantes y acentos, GPU para Nemotron (rueda `+cuda12.cudnn9` de sherpa-onnx), INT8 de CTranslate2, ejecuciones de más de 10 min, Python 3.13.
- Las latencias son p50/p95 de 28-93 segmentos por ejecución y cada medición se hizo una sola vez, con carga ajena variable: las diferencias de pocas centésimas de segundo no son concluyentes.
- El oráculo de «habla real» (energía) tiene una incertidumbre de unas decenas de ms (contraste con Silero arriba).
- El WER de los nombres propios inventados del texto (`Kaliko`, `Brion`, `Linnell`…) es la mayor parte de los errores; no se corrigió.

## Cómo reproducir

Todo se ejecuta con `uv run` desde `spikes/asr` (en la raíz del repo no hay `pyproject.toml`). Nada de audio ni de modelos se guarda en el repo.

```powershell
cd spikes/asr
uv sync                                    # crea .venv con Python 3.12 y las versiones de uv.lock
uv run python fetch_assets.py              # modelos (Nemotron 160 y 560 ms, Silero, Whisper turbo) y audio de prueba
uv run python build_corpus.py              # monta los flujos `gapped` (594 s) y `continuous` (186 s)

# Prueba de humo (~1 min): primeros 6 enunciados, sin esperas
uv run python run_engine_a.py --stream gapped --chunk-ms 560 --mode fast --limit 6 --no-save

# Motor A en tiempo real (la etiqueta da nombre a results/<etiqueta>.json)
uv run python run_engine_a.py --stream gapped     --chunk-ms 560 --mode paced --threads 2 --blank-penalty 1 --save-events --label a560_vad_gapped_paced
uv run python run_engine_a.py --stream continuous --chunk-ms 160 --mode paced --threads 2 --blank-penalty 1 --save-events --label a160_vad_continuous_paced
uv run python run_engine_a.py --stream gapped     --chunk-ms 160 --policy native --mode paced --save-events --label a160_native_gapped_paced

# Motor B (toma el candado de GPU %LOCALAPPDATA%\InstantTraductor\gpu.lock una sola vez para todas las variantes)
uv run python run_engine_b.py --save-events --variant b_gapped_paced:gapped:paced:1:5 --variant b_continuous_paced:continuous:paced:1:5
uv run python run_engine_b.py --variant b_gapped_fast_beam5_nocut:gapped:fast:5:0   # etiqueta:flujo:modo:haz:corte_forzado_s (0 = sin corte)

# Línea base sin VAD, extra de puntuación, reanálisis y tablas
uv run python baseline_offline.py --engine a --chunk-ms 560 --blank-penalty 1
uv run python baseline_offline.py --engine b --beam 5 1
uv run python punct_extra.py sweep_a560_bp0_gapped_fast sweep_a560_bp1_gapped_fast --save punct_extra.json   # antes: fetch_assets.py --punct
uv run python reanalyze.py --all                                                                              # repite el análisis desde results/events
uv run python report.py --compare a160_vad_gapped_paced a560_vad_gapped_paced b_gapped_paced
uv run python report.py --section bp          # bp | threads | b | baselines | a-misc | load
```

La campaña completa en tiempo real es `BP=1 bash campaign/paced_runs.sh > paced.log 2>&1` (~1 h 40 min) y el barrido de `blank_penalty`, `bash campaign/bp_sweep.sh` (~35 min), ambos desde Git Bash.

Notas:
- Para medir latencias, que el equipo esté lo más libre posible: otros procesos (aquí, otros obreros) las distorsionan; `results/*.json` guarda la CPU ajena de cada ejecución.
- `--mode fast` no espera al reloj: sirve para WER y RTF; sus latencias son «algorítmicas» (sin tiempo de cómputo).
- El candado de GPU espera hasta 30 min (`--lock-timeout-min`). Toda ejecución del motor B, incluidas las de prueba, lo toma.
- Los eventos crudos (`results/events/*.events.json.gz`) permiten repetir el análisis sin volver a medir en tiempo real.

## Contenido de la carpeta

| Fichero | Para qué sirve |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | proyecto uv propio (Python 3.12), versiones exactas |
| `asrspike/vad.py` | Silero VAD 6.2.x en ONNX (CPU) con histéresis y fin de turno, en streaming |
| `asrspike/engine_a.py` | tubería del motor A: puerta de VAD + Nemotron en sherpa-onnx; eventos `speech_start`, `partial`, `final`, `endpoint` |
| `asrspike/engine_b.py` | tubería del motor B: segmentos de VAD (con corte forzado) + faster-whisper en un hilo |
| `asrspike/realtime.py` | alimentador a ritmo de tiempo real (y modo rápido) |
| `asrspike/data.py` | LibriSpeech dummy, montaje de los flujos y habla «real» por energía |
| `asrspike/analysis.py`, `metrics.py`, `events_io.py` | latencias, WER normalizado, estabilidad de parciales, puntuación; guardado de eventos |
| `asrspike/sysinfo.py`, `gpumem.py` | sistema, carga ajena (CPU/GPU) y VRAM del proceso |
| `fetch_assets.py`, `build_corpus.py` | descargan modelos y audio; montan los flujos (fuera del repo) |
| `run_engine_a.py`, `run_engine_b.py` | medición de cada motor |
| `baseline_offline.py`, `punct_extra.py`, `reanalyze.py`, `report.py` | WER sin VAD con enunciados enteros, extra de puntuación, reanálisis y tablas |
| `campaign/` | `paced_runs.sh` y `bp_sweep.sh` (las campañas que produjeron `results/`) y `wait_quiet.py` (espera a que el equipo esté tranquilo) |
| `results/` | JSON de cada ejecución, `punct_extra.json` y `events/` con los eventos crudos de las ejecuciones en tiempo real |

## Licencias

Silero VAD MIT; sherpa-onnx Apache-2.0; ONNX Runtime MIT; faster-whisper y CTranslate2 MIT; Whisper large-v3-turbo MIT; **Nemotron Speech Streaming: NVIDIA Open Model License** (condiciones propias, ver ADR-0006; la exportación
de sherpa-onnx de terceros no declara licencia y hereda la de NVIDIA); LibriSpeech CC BY 4.0; modelo de puntuación de sherpa-onnx (Edge-Punct-Casing) Apache-2.0; `jiwer` Apache-2.0; `whisper-normalizer` MIT.
