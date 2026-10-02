# Spike S5: ASR en japonés, chino y coreano, filtro de idioma y traducción a español

> Spike de investigación para la spec 002 (`specs/002-idiomas-y-peliculas`), **no es código de producto**. Medido el 2026-10-02 en este PC.
> Modelos, audio y cachés viven fuera del repo (`%LOCALAPPDATA%\InstantTraductor\spikes\idiomas\`). Sigue el plan de
> `docs/investigacion/2026-10-02-asr-ja-zh-ko.md` y copia el estilo de `spikes/asr/README.md` (S3).

## Resumen

Todo se midió en CPU con sherpa-onnx 1.13.8 (la traducción, en GPU), con las mismas 50 frases paralelas de FLEURS en ja, zh y ko (habla leída y limpia, 11-13 s por frase; ver «Límites»).

- **ASR, por idioma (CER sin / con música a -10 dB; final p50 / p95 desde el fin real del habla):**
  - **Chino: X-ASR-zh-en 960 ms** (streaming, con comas): **4,87 % / 5,15 %**, final **0,58 / 0,61 s**, 0,13 núcleos, 294 MB de RAM. Alternativa: SenseVoice-Small, 5,55 % / 6,06 %, 0,87 / 1,31 s.
  - **Japonés: Parakeet-tdt_ctc-0.6b-ja (CTC)**: **5,31 % / 6,17 %**, final **1,24 / 2,02 s** (con la CPU cargada, 1,57 / 3,35 s), 0,12 núcleos, 753 MB. Es el más preciso con diferencia; el streaming (Nemotron 3.5) queda en 12,6-13,4 %. Alternativas: ReazonSpeech (8,44 %, 0,74 / 0,98 s, sin puntuación) y SenseVoice (8,32 %, 0,88 / 1,39 s, con puntuación).
  - **Coreano: SenseVoice-Small**: **7,14 % / 8,09 %**, final **0,91 / 1,23 s**, 0,07 núcleos, 357 MB, y **es el único que escribe los espacios entre palabras** (Nemotron 3.5 y `kangkyu` los omiten). Alternativas: Nemotron 3.5 (8,43 %, parciales, pero 0,46 núcleos y p95 de 4,6 s con la CPU cargada) y `kangkyu` chunk 64 (8,47 %, 0,58 / 0,62 s, 0,11 núcleos).
  - **SenseVoice-Small sirve para los tres idiomas con un solo modelo de 163 MB** (CER 5,6-8,3 %, 0,06-0,07 núcleos) y emite la etiqueta de idioma.
- **La música sin diálogo la frena el VAD, no el ASR.** Con 10 min de orquesta, Silero no abre ningún segmento (p máx. 0,06; con aria y coros, 0,14), así que ningún candidato inventa frases. **Sin VAD, Parakeet, ReazonSpeech y SenseVoice sacan texto en 150 de 150 trozos de 4 s de música** (1-3 caracteres: «うん。», «なるほど»); los transductores en streaming no (Nemotron, X-ASR y `kangkyu`, 0 de 150). Las canciones con letra en el idioma elegido no se probaron.
- **Filtro de idioma: Whisper base (ONNX de sherpa-onnx, CPU) restringido a {idioma elegido, es, en}, con una ventana de 6 s.** Con 300 recortes de 1-6 s por idioma acepta **97,3 % (ja), 99,0 % (zh) y 97,7 % (ko)** del idioma correcto y **0,3-0,7 % del español** (1-2 de 300), 0,3 % del inglés; **96 / 131 ms (p50 / p95) por segmento con un hilo** (tiny: 49 / 90 ms, 96-99 %). Con música: 97 / 98 / 98 %. **No llega a «0 % de español»**: queda un 0,3-0,7 % por segmento. Solo con los 30 s originales de Whisper es 7 veces más lento (base 723 ms). El filtro «restringido a {T, es}» **deja pasar el inglés (54-86 %)**. La etiqueta de idioma de SenseVoice (gratis, es el propio ASR) acepta el 100 % del idioma correcto, pero deja pasar el español en ja (20 %); como segunda comprobación de las dos (AND) no pierde ningún recorte correcto.
- **Traducción Hy-MT2-7B Q4 con el prompt de producción: p50 0,41-0,46 s, p95 0,66-0,87 s, máx. 1,24 s** (chrF contra es_419: 46-48; variantes de ejemplos sin diferencia). **El prompt no necesita cambios, pero los filtros y topes de `hymt2.py` están pensados para el inglés y fallan con CJK:** el filtro de longitud (3× el original en caracteres) **rechaza 48 de 50 traducciones del chino, 15-17 del japonés y 3 del coreano**, y el tope de tokens (64, porque `count_words` cuenta una tira de ideogramas como una palabra) **trunca 3-4 de 50** en ja y zh. Las traducciones de las 50 frases están en `traducciones_{ja,zh,ko}.md` para que el humano las juzgue (SC-002).
- **Retardo (SC-001):** sin carga, el ASR aporta 0,56-1,24 s de p50 y 0,60-2,02 s de p95 y la traducción 0,4 / 0,7 s (p50 / p95), muy por debajo de p50 ≤ 3 s y p95 ≤ 5 s antes de contar la voz. Con 12 de los 16 hilos ocupados, los candidatos principales siguen en p95 ≤ 3,4 s de ASR; solo Nemotron 3.5 en coreano llega a 4,6 s.

## Objetivo

Medir en este PC (Ryzen 7 8700F, RTX 5070, Windows 11) lo que el plan de la spec 002 necesita decidir:

1. **ASR por idioma** (ja, zh, ko) en sherpa-onnx 1.13.8, CPU: CER, latencia del final desde el fin real del habla (p50/p95) con Silero VAD delante, RTF, núcleos, RAM, puntuación y CER con música a -10 dB.
2. **Filtro de idioma** (FR-003, SC-003b): rechazar los segmentos que no están en el idioma elegido, sobre todo en español.
3. **Traducción ja/zh/ko→es** con Hy-MT2-7B Q4_K_M y el prompt de producción: latencia, calidad (para que el humano la juzgue en SC-002) y si el prompt necesita cambios.
4. **Recomendación** por idioma, con los datos.

## Entorno

Mismo PC que S3. Las mediciones de ASR se hicieron con la máquina libre salvo otros obreros puntuales (ver «Límites»).

| Componente | Versión / dato |
|---|---|
| Sistema | Windows 11 Pro 10.0.26200 |
| CPU / RAM | AMD Ryzen 7 8700F (8 núcleos, 16 hilos), 31,7 GB |
| GPU | NVIDIA GeForce RTX 5070 12 GB (solo traducción y la referencia de Whisper; el ASR va en CPU) |
| Python y gestor | Python 3.12 (uv 0.12.21), proyecto uv propio (`pyproject.toml`, `uv.lock`) |
| **sherpa-onnx** | **1.13.8** + `sherpa-onnx-core` 1.13.8 (declarado explícito, ver S3 problema 1) |
| onnxruntime (Silero y Whisper-LID propio) | 1.30.0 |
| Silero VAD | 6.2.3 (el de S3: `models/silero-vad-6.2.3`) |
| Métricas y utilidades | `jiwer` 4.0.0, `sacrebleu` 2.6.0, `numpy` 2.5.3, `soundfile` 0.14.0, `psutil` 7.2.2, `pyarrow` 25.0.1 |
| Traducción | Hy-MT2-7B Q4_K_M y llama.cpp b11146 (CUDA 13.4) de la app (`component_dir("hy-mt2-7b-q4")`, `component_dir("llama-cpp")`) |
| Prompt | importado de `src/instanttraductor/mt/hymt2.py` (sin modificarlo); `gpu_lock.py` y `llama_server.py` de `spikes/traduccion` |

Modelos (carpeta `models/` del spike): `sherpa-onnx-x-asr-{480,960}ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05`, `sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30`,
`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17`, `sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11`,
`sherpa-onnx-nemo-parakeet-tdt_ctc-0.6b-ja-35000-int8`, `sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01`, `kangkyu/icefall-asr-ko-streaming-zipformer-174m` (HF; int8 chunk 32 y 64),
`sherpa-onnx-whisper-{tiny,base}` (identificación de idioma).
## Método

### Corpus
- **FLEURS** (`google/fleurs`, partición `test`, **CC BY 4.0**; <https://huggingface.co/datasets/google/fleurs>), en ja_jp, cmn_hans_cn y ko_kr. FLEURS es paralelo: la misma frase (mismo `id`) está leída en todos los idiomas.
  **50 frases elegidas al azar (semilla 20261002) entre las 247 que están a la vez en ja, zh, ko, es y en**, así que son las mismas 50 frases en los tres idiomas. Referencia: `raw_transcription` (con puntuación) del idioma.
  Referencia en español: la frase paralela de **es_419** (existe y es paralela; es español latinoamericano: sin «vosotros» ni léxico peninsular, así que sirve de referencia de sentido, no de estilo). Se guarda también la frase en inglés (en_us).
  Duración de las frases: ja 7,1-24,5 s (media 13,1), zh 4,7-22,0 s (11,5), ko 4,7-24,1 s (12,4). Es **habla leída de textos de Wikipedia/Wikinoticias, registro formal y limpio**; no es diálogo de cine (ver «Límites»).
- Nivel: cada grabación se normaliza a -22 dBFS de RMS de habla (las originales varían de -18 a -40 dBFS).
- **Flujos**: las 50 frases separadas por huecos de 1,2-2,2 s de ruido blanco a -66 dBFS, como el flujo `gapped` de S3: ja 742 s, zh 659 s, ko 708 s.
- **Música a -10 dB**: el mismo flujo con música mezclada durante todo el flujo (también en los huecos), con el RMS de la música 10 dB por debajo del RMS del habla. Música: 4 pistas de la colección **Musopen** en Wikimedia Commons (**dominio público o CC0**): Borodin, *En las estepas del Asia central*; Dvořák, *Nuevo Mundo* (II y IV); Albinoni, concierto para oboe op. 9 n.º 2. Procedencia y licencia de cada una en `music_licenses.json`. No se usó MUSAN (11 GB en un solo fichero y licencias mezcladas).
- **Filtro de idioma**: recortes de **1-6 s** (longitud al azar, dentro del habla) de FLEURS: 50 de cada idioma asiático (los de las 50 frases), 30 de es_419 y 30 de en_us; más una versión con música a -10 dB. Una segunda campaña con **300 recortes por idioma** (`run_lid_big.py`) acota los porcentajes.
- Manifiesto con referencias, tiempos y procedencia: `corpus_manifest.json` (sin audio).

### Tubería de ASR
Igual que S3: **Silero VAD 6.2.3** (umbral 0,5/0,35, **500 ms de silencio** para cerrar, tramos de menos de 250 ms descartados, relleno de 150 ms) delante de cada candidato, con 2 hilos de sherpa-onnx.
- **Streaming** (X-ASR, zipformer-zh, Nemotron 3.5, `kangkyu`): stream nuevo por tramo, parciales por trama, al cerrar se rellena con un trozo de ceros, `input_finished()` y se decodifica.
- **Por segmentos** (SenseVoice, Parakeet-ja CTC, ReazonSpeech): se acumula el tramo (desde el relleno previo hasta 150 ms tras el último habla) y se decodifica entero al cerrarlo. Sin parciales. Sin corte forzado (las frases de FLEURS son de ≤ 24,5 s).
- Nemotron 3.5: `stream.set_option("language", <ja|ko>)` por flujo; se midió con `blank_penalty` 0 y 1 (el de S3).
- SenseVoice: idioma fijado (`language="ja"|"zh"|"ko"`), `use_itn=True`.

### Reloj virtual (desviación respecto a S3)
En vez de esperar el reloj de pared (10-12 min por ejecución), el audio se entrega en tramas de 32 ms con un **reloj virtual**: cada llamada a `push` cuesta su tiempo real de cómputo y, si el procesador va retrasado, las tramas siguientes esperan en cola; los eventos se sellan con el reloj virtual. Es equivalente a la alimentación en tiempo real de S3 salvo la contención de CPU entre procesos, que aquí es la real de la máquina (se ejecutaron tres colas en paralelo; ver «Límites»). **Contraste:** X-ASR 960 ms (zh, sin música) en tiempo real de verdad (`--paced`, 11 min): final p50 / p95 **0,572 / 0,604 s** frente a 0,58 / 0,61 s con el reloj virtual; mismo CER (4,87 %) y 67 segmentos.

### Habla «real» para las latencias
El oráculo por energía de S3 **falla en FLEURS** (en japonés marcó el fin de la frase más de 0,3 s antes en 20 de 50 frases, hasta 10 s, por grabaciones con ruido). Se usa la **probabilidad de Silero 6.2.3 sobre el clip limpio sin mezclar**: inicio = primera trama con p ≥ 0,5; fin = última trama con p ≥ 0,5. Es independiente de la tubería (que tiene histéresis y 500 ms de silencio), pero comparte modelo con ella. Con la música se usa el mismo fin real.

### Métricas
| Métrica | Definición |
|---|---|
| CER | CER de corpus (errores de carácter / caracteres de referencia, `jiwer`). Normalización igual para referencia e hipótesis: NFKC (unifica anchos), minúsculas, fuera puntuación, símbolos y espacios; en ja y zh, los numerales de ideogramas pasan a cifras (`二〇一一` = `2011`). El texto de una frase es la concatenación de los finales cuyo tramo cae dentro de ella |
| Final | instante del `final` (reloj virtual) menos el fin real del habla de la frase; si la frase se partió en varios tramos, el del último |
| 1.er parcial | primer parcial con texto menos el inicio real del habla (solo streaming) |
| RTF | cómputo (VAD + ASR) / segundos de audio |
| Núcleos | CPU del proceso (usuario + sistema, todos los hilos) / segundos de audio = núcleos medios con el flujo emitido en tiempo real |
| RAM | RSS tras cargar el modelo y pico del proceso (dos condiciones y el calentamiento) |
| Puntuación | signos por 100 caracteres reconocidos y frases cuyo texto acaba en `。.!?？！…` |
| Espurias | finales con texto cuyo tramo cae fuera de cualquier frase (huecos y música) |

## Resultados

Cifras de `results/*.json` (`uv run python report_asr.py`, `report_lid.py`, `report_translate.py`; tablas completas en `results/tablas_*.md`). 50 frases por idioma, 2 hilos, Silero VAD delante.
Latencias en segundos, p50 / p95, desde el fin real del habla hasta el `final`. «Núcleos» = CPU media con el flujo en tiempo real; «RAM» = tras cargar / pico.

### Tabla 1: ASR (sin música y con música a -10 dB, reloj virtual)

| Idioma | Candidato | CER | CER con música | Final | Final con música | 1.er parcial p50 | RTF | Núcleos | RAM (MB) | Puntuación: signos/100 car.; frases con cierre |
|---|---|---|---|---|---|---|---|---|---|---|
| **ja** | **Parakeet-tdt_ctc-0.6b-ja** (CTC, int8, por segmentos) | **5,31 %** | 6,17 % | 1,24 / 2,02 | 1,37 / 2,28 | - | 0,069 | 0,12 | 753 / 1046 | 0,6; 8/50 |
| ja | SenseVoice-Small 2024 (int8, ITN, por segmentos) | 8,32 % | 10,20 % | 0,88 / 1,39 | 0,95 / 1,52 | - | 0,038 | 0,06 | 357 / 530 | 4,9; 50/50 |
| ja | ReazonSpeech zipformer k2 v2 (int8, por segmentos) | 8,44 % | 9,57 % | 0,74 / 0,98 | 0,78 / 1,10 | - | 0,026 | 0,05 | 286 / 642 | 0,2; 0/50 |
| ja | Nemotron 3.5 560 ms, `blank_penalty` 1 (streaming) | 12,58 % | 14,96 % | 0,69 / 0,84 | 0,74 / 1,02 | 1,07 | 0,190 | 0,44 | 793 / 960 | 3,5; 28/50 |
| ja | Nemotron 3.5 560 ms, `blank_penalty` 0 | 13,40 % | 17,03 % | 0,71 / 0,91 | 0,74 / 1,04 | 1,08 | 0,205 | 0,45 | 793 / 960 | 1,9; 4/50 |
| **zh** | **X-ASR-zh-en 960 ms** (punct, int8, streaming) | **4,87 %** | 5,15 % | 0,58 / 0,61 | 0,60 / 0,74 | 0,84 | 0,043 | 0,13 | 294 / 421 | 3,7; 0/50 |
| zh | SenseVoice-Small 2024 | 5,55 % | 6,06 % | 0,87 / 1,31 | 0,88 / 1,44 | - | 0,043 | 0,07 | 357 / 520 | 7,7; 50/50 |
| zh | X-ASR-zh-en 480 ms | 5,77 % | 6,28 % | 0,57 / 0,59 | 0,58 / 0,72 | 0,84 | 0,060 | 0,20 | 294 / 417 | 3,6; 0/50 |
| zh | zipformer-zh streaming 2025-06-30 (int8, sin puntuación) | 8,66 % | 9,90 % | 0,57 / 0,60 | 0,58 / 0,72 | 0,51 | 0,088 | 0,28 | 293 / 408 | 0,0; 0/50 |
| **ko** | **SenseVoice-Small 2024** (con espacios) | **7,14 %** | 8,09 % | 0,91 / 1,23 | 0,97 / 1,54 | - | 0,042 | 0,07 | 357 / 525 | 2,2; 50/50 |
| ko | Nemotron 3.5 560 ms, `blank_penalty` 1 (sin espacios) | 8,43 % | 9,81 % | 0,71 / 0,83 | 0,78 / 1,18 | 1,04 | 0,197 | 0,46 | 793 / 955 | 2,5; 49/50 |
| ko | `kangkyu` zipformer 174M, chunk 64 (1280 ms; sin espacios ni puntuación) | 8,47 % | 9,68 % | 0,58 / 0,62 | 0,61 / 1,10 | 1,17 | 0,039 | 0,11 | 285 / 425 | 0,0; 0/50 |
| ko | Nemotron 3.5 560 ms, `blank_penalty` 0 | 8,73 % | 9,72 % | 0,72 / 0,83 | 0,77 / 1,18 | 1,07 | 0,205 | 0,45 | 793 / 956 | 2,3; 47/50 |
| ko | `kangkyu` chunk 32 (640 ms) | 8,90 % | 9,59 % | 0,56 / 0,61 | 0,60 / 1,10 | 1,15 | 0,055 | 0,16 | 286 / 412 | 0,0; 0/50 |

- **Segmentos:** el VAD con 500 ms de silencio saca 64 tramos de las 50 frases en ja, 67 en zh y 61 en ko (en FLEURS hay pausas largas dentro de la frase): **un 22-34 % de las frases llega al traductor partida en 2 o más tramos** (FR-014). Ningún candidato dio frases en los huecos ni con música (0 espurias).
- **Errores (limpio):** Parakeet 74 sustituciones / 31 borrados / 31 inserciones; ReazonSpeech borra mucho (127 de 216 errores); SenseVoice ja 132 / 52 / 29. Frases sin texto: 0 en todos. CER mediano por frase 3,0-6,4 %, p90 12,5-24,6 % (candidatos principales y alternativas de la tabla, sin Nemotron en ja).
- **Puntuación:** SenseVoice puntúa todas las frases (también con cierre `。`); X-ASR da comas pero nunca punto final; Nemotron con `blank_penalty` 1 da más cierres que con 0 (ja 28/50 frente a 4/50, ko 49/50 frente a 47/50) y el CER sale igual o algo mejor en ja y ko (12,58 frente a 13,40; 8,43 frente a 8,73). Parakeet puntúa poco (8/50 con cierre).
- **Espacios en coreano:** Nemotron 3.5 y `kangkyu` escriben las sílabas **sin espacios** (0,5-0,8 espacios por 100 caracteres frente a 22,2 de la referencia); SenseVoice, 23,3. Afecta a la traducción (tabla 5).
- **Coste de decodificar un segmento (modelos por segmentos, 2 hilos, p50 / p95):** Parakeet 658 / 1277 ms, SenseVoice 311-369 / 691-727 ms, ReazonSpeech 200 / 415 ms, para segmentos de ~6 s de media: **~0,1 s por segundo de audio en Parakeet**. Crece con la longitud del tramo; las frases de FLEURS son de ≤ 24 s y no hubo corte forzado.

### Tabla 2: con la CPU cargada (12 procesos ocupados de 16 hilos; resto igual)

| Idioma | Candidato | CER | Final | Final con música | RTF | Núcleos | Decodificación por segmento p50 / p95 (ms) |
|---|---|---|---|---|---|---|---|
| ja | Parakeet-ja | 5,31 % | 1,57 / 3,35 (sin carga 1,24 / 2,02) | 1,74 / 3,46 | 0,127 | 0,14 | 1043 / 2949 (sin carga 658 / 1277) |
| ja | ReazonSpeech | 8,44 % | 0,97 / 2,02 (0,74 / 0,98) | 1,15 / 2,17 | 0,069 | 0,06 | 411 / 1393 |
| zh | X-ASR 960 ms | 4,87 % | 0,63 / 0,90 (0,58 / 0,61) | 0,64 / 0,90 | 0,128 | 0,18 | 91 / 294 |
| zh | SenseVoice | 5,55 % | 1,23 / 2,17 (0,87 / 1,31) | 1,01 / 2,19 | 0,096 | 0,09 | 626 / 1614 |
| ko | SenseVoice | 7,14 % | 1,28 / 2,28 (0,91 / 1,23) | 1,49 / 2,16 | 0,086 | 0,08 | 683 / 1637 |
| ko | Nemotron 3.5 (bp 1) | 8,43 % | 1,28 / **4,59** (0,71 / 0,83) | 1,55 / 4,23 | **0,536** | **0,65** | 381 / 1097 (con carga el ASR sigue el audio con RTF 0,54) |
| ko | `kangkyu` chunk 64 | 8,47 % | 0,58 / 0,62 (0,58 / 0,62) | 0,61 / 1,11 | 0,038 | 0,11 | 53 / 65 |

La carga no cambia el CER. Los modelos ligeros (X-ASR, `kangkyu`, ReazonSpeech) apenas notan la carga; Nemotron 3.5 (0,6B) la nota mucho (RTF de 0,20 a 0,54), como el inglés de S3 con varios hilos. El reloj virtual incluye la espera en cola.

### Tabla 3: música sin diálogo (10 min, mismas 4 pistas de orquesta a -22 y -32 dBFS; y 3 pistas con voz cantada, solo en ja)

| Candidato | Tubería con Silero: segmentos abiertos | Sin VAD: trozos de 4 s con texto (de 150) | Ejemplos sin VAD |
|---|---|---|---|
| Parakeet-ja | 0 (orquesta); 0 (aria y coros) | **150** (427-439 caracteres en total) | «うん。», «。» |
| ReazonSpeech | 0 | **150** (298-302) | «なるほど», «頑張れ», «ああ» |
| SenseVoice (ja, zh, ko) | 0 | **150 en los tres idiomas** (220-281) | «.», «。», «春花在家。», «그.» |
| Nemotron 3.5 (ja, ko) | 0 | 0 | |
| X-ASR 960 ms (zh) | 0 | 0 | |
| zipformer-zh | 0 | 3 (con la música fuerte: «爹», «我») | |
| `kangkyu` chunk 64 (ko) | 0 | 0 | |

Silero 6.2.3 da como mucho p = 0,03-0,06 con la orquesta y 0,14 con aria y coros (umbral 0,5): el VAD cierra el paso. **Los modelos por segmentos alucinan 1-3 caracteres en cualquier trozo de música que les llegue**, así que dependen por completo de la puerta de VAD (y de descartar textos de 1-2 caracteres).
Las **canciones con letra en el idioma elegido** (que sí activarían el VAD) y los efectos de sonido no se probaron: no hay corpus libre a mano.

### Tabla 4: filtro de idioma

Aceptado (%) del idioma correcto (T), del español, del inglés y de los otros dos idiomas asiáticos. Recortes de 1-6 s, sin música; entre paréntesis, con música a -10 dB.
**Whisper base, ventana de 6 s, 300 recortes por idioma** (`results/lid_big_w6.json`; `results/tablas_lid_big_w6.md` trae tiny, otras reglas y umbrales):

| Regla | T = ja: ja / es / en / zh+ko | T = zh: zh / es / en / ja+ko | T = ko: ko / es / en / ja+zh |
|---|---|---|---|
| idioma de mayor puntuación entre los 99 | 95 % / 0,3 % / 0,3 % / 1 % (93 / 0,3 / 0,3 / 2) | 98 % / 0,3 % / 0 / 1 % (97 / 0,3 / 0 / 2) | 96 % / 0 / 0 / 0 (93 / 0 / 0 / 0) |
| **mayor puntuación en {T, es, en}** | **97,3 % / 0,7 % / 0,3 % / 23 %** (97 / 0,3 / 0,3 / 26) | **99,0 % / 0,3 % / 0,3 % / 18 %** (98 / 0,3 / 0 / 20) | **97,7 % / 0,3 % / 0 / 13 %** (98 / 0,3 / 0 / 13) |
| mayor puntuación en {T, es} | 99 % / 1 % / **79 %** / 96 % | 100 % / 0 / **63 %** / 82 % | 100 % / 0 / **62 %** / 84 % |
| p(T) ≥ 0,8 en {T, es, en} | 94 % / 0 / 0 / 4 % | 97 % / 0 / 0 / 4 % | 97 % / 0 / 0 / 1 % |

- **Whisper tiny** (misma regla, 300 recortes): 96,0 % (ja), 98,3 % (zh), 99,3 % (ko) del idioma correcto, español 0-0,3 %; con música 95 / 98 / 98 %.
- **Por duración (regla {T, es, en}):** 1-2 s: 93 % (205 recortes), 2-4 s: 99 % (383), 4-6 s: 100 % (312). Los segmentos cortos son el punto débil.
- **Con 50 recortes, `base` y `tiny` con la ventana de 30 s** (la de Whisper, y la de la API `SpokenLanguageIdentification` de sherpa-onnx): ja 88 % con el idioma completo (ver `results/tablas_lid_busy.md`); la ventana de 6 s **no empeora (ver arriba, con 300 recortes) y es unas 7 veces más rápida** (mismos ONNX; el codificador acepta mezclas más cortas).
- **Coste por segmento, un hilo, máquina libre** (`results/lid_t1_w6.json`, `lid_t1_w30.json`; incluye el log-mel en numpy): **tiny 49 / 90 ms, base 96 / 131 ms con 6 s**; con 30 s tiny 354 / 484 ms y base 723 / 951 ms. La API de sherpa-onnx, medida con la máquina ocupada, 157 / 226 ms (tiny) y 279 / 386 ms (base) con 30 s; coincide con la implementación propia en el 95 % de los recortes.
- **Alternativas baratas (SenseVoice, 50 recortes por idioma, tabla de `tablas_lid_busy.md`):**

| Regla | ja | zh | ko |
|---|---|---|---|
| etiqueta de idioma de SenseVoice (idioma automático): T / es / en / otros | 100 / **20** / 0 / 0 % | 100 / 0 / 0 / 0 % | 100 / 3 / 0 / 0 % |
| texto de SenseVoice con el idioma fijado: ≥ 90 % de letras de la escritura de T | 100 / **63** / 3 / 51 % | 96 / 27 / 0 / 9 % | 100 / 50 / 7 / 8 % |
| Whisper base {T, es, en} **Y** etiqueta de SenseVoice | 96 / 0 / 0 / - % | 98 / 0 / 0 / - % | 100 / 0 / 0 / - % |

La proporción de escritura correcta **no sirve**: un ASR en japonés que oye español escribe kana igualmente. La etiqueta de SenseVoice es gratis cuando ese es el ASR y rechaza bien el chino y el coreano ajenos, pero deja pasar el español en ja (20 %) y confunde con el español poco hablado.
En el conjunto de 50 recortes la combinación (Whisper Y etiqueta) acepta 48/50, 49/50 y 50/50 del idioma correcto y 0/30 del español en los tres; con tamaño tan pequeño solo acota el español por debajo del 10 %.
El motor del ASR por idioma (Nemotron, Parakeet, X-ASR...) no expone confianza por token en esta API de sherpa-onnx 1.13.8 (`ys_log_probs` vacío en CTC y SenseVoice), así que no se midió una puerta por confianza.

### Tabla 5: traducción ja/zh/ko → es con Hy-MT2-7B Q4_K_M (prompt de producción, 50 frases por idioma)

Contra la referencia es_419, con chrF (sacrebleu; **orientativo**: la referencia es latinoamericana y la salida usa el léxico de España; la medida buena es el juicio humano de `traducciones_*.md`).
Entrada «referencia» = texto original de FLEURS con puntuación; «sin puntuación» = el mismo sin puntuación ni símbolos; «ASR» = lo que reconoció el candidato (sin música).

| Idioma | Variante de ejemplos | Entrada | chrF | Latencia p50 / p95 / máx. (ms) | Rechazadas por los filtros de producción | Truncadas |
|---|---|---|---|---|---|---|
| ja | producción (12 ejemplos en inglés) | referencia | 46,4 | 434 / 711 / 724 | **17** / 50 | 4 |
| ja | ejemplos en japonés | referencia | 46,4 | 460 / 725 / 771 | 16 | 4 |
| ja | sin ejemplos | referencia | 46,0 | 433 / 671 / 687 | 20 | 4 |
| ja | producción, tope de tokens libre (256) | referencia | 47,3 | 463 / 865 / 1236 | 15 | 0 |
| ja | producción | sin puntuación | 46,4 | 445 / 765 / 900 | 22 | 3 |
| ja | producción | ASR Parakeet / SenseVoice / ReazonSpeech | 45,0 / 43,6 / 43,8 | 405 / 662 | 18 / 21 / 22 | 3-4 |
| zh | producción | referencia | 47,4 | 413 / 684 / 751 | **48** / 50 | 3 |
| zh | ejemplos en chino / sin ejemplos | referencia | 47,4 / 46,9 | 398 / 664; 404 / 679 | 48; 47 | 3 |
| zh | producción, tope libre | referencia | 48,6 | 424 / 806 / 1150 | 48 | 0 |
| zh | producción | sin puntuación | 47,2 | 412 / 715 / 879 | 47 | 3 |
| zh | producción | ASR X-ASR 960 / SenseVoice | 46,7 / 46,0 | 379 / 656 | 48 / 48 | 4 |
| ko | producción | referencia | 47,1 | 438 / 706 / 973 | 3 / 50 | 0 |
| ko | ejemplos en coreano / sin ejemplos | referencia | 46,9 / 46,9 | 415 / 686; 407 / 660 | 4; 1 | 0 |
| ko | producción | sin puntuación | 46,2 | 421 / 697 / 953 | 4 | 0 |
| ko | producción | ASR SenseVoice / `kangkyu` 64 / Nemotron 3.5 | 45,1 / 44,3 / **42,8** | 404 / 628; 381 / 641; 381 / 645 | 3 / **35** / **31** | 0 / 2 / 2 |

- **Los ejemplos del prompt no importan:** las tres variantes (ejemplos en inglés, en el idioma de origen o ninguno) quedan dentro de 1,4 puntos de chrF, sin orden claro; los ejemplos en inglés de producción valen para ja/zh/ko. La plantilla en chino de Hy-MT2 para zh no se probó.
- **Filtros de producción y CJK:** la traducción al español ocupa **2,8 (ja), 3,9 (zh) y 2,4 (ko) veces** los caracteres del original (p50; p95 3,6 / 4,6 / 3,0; máx. 4,4 / 5,0 / 3,3), así que el filtro `longitud` de `rejection_reason` (3×) tira el 96 % de las del chino y el 30-34 % de las del japonés (con tope 6 no cae ninguna). El tope de tokens `max_tokens_for` (mínimo 64) se queda corto en ja/zh porque `count_words` cuenta una tira de ideogramas como una palabra: salen 72 tokens de p95 y 102 de máximo y se truncan 3-4 frases de 50.
- **ASR → traducción:** pasar del texto original al reconocido cuesta 0,7-1,4 puntos de chrF con el mejor candidato de cada idioma (ja Parakeet 46,4 → 45,0; zh X-ASR 47,4 → 46,7; ko SenseVoice 47,1 → 45,1) y la música otros 0,1-0,6. Quitar la puntuación cuesta 0-0,9. **El coreano sin espacios pierde 2,3 puntos frente a SenseVoice y dispara el filtro de longitud** (la entrada es más corta).
- La latencia por frase (p50 0,37-0,46 s, p95 0,63-0,87 s, máx. 1,24 s) es la del 7B con `llama-server` en la 5070 (arranque 3 s), con el prefijo del prompt en caché y un hueco; el tiempo de espera del candado de GPU fue de 0-43 s.

## Recomendación para el plan

| Idioma | Principal | Alternativa | Motivo |
|---|---|---|---|
| **Chino** | **X-ASR-zh-en 960 ms** (streaming, `punct` int8, 294 MB), CER 4,87 % (5,15 % con música), final 0,58 / 0,61 s | **SenseVoice-Small** por segmentos (5,55 %, 0,87 / 1,31 s, puntúa del todo) | el mejor CER, parciales (0,84 s), 0,13 núcleos y apenas sufre la carga (p95 0,90 s). El de 480 ms pierde un punto de CER (5,77 %) sin ganar latencia (el final lo manda el silencio del VAD). El zipformer-zh 2025 (8,66 %) no compensa |
| **Japonés** | **Parakeet-tdt_ctc-0.6b-ja** (CTC, por segmentos), CER 5,31 % (6,17 %), final 1,24 / 2,02 s, 753 MB | **SenseVoice-Small** (8,32 %, 0,88 / 1,39 s, 357 MB, puntúa) o **ReazonSpeech** (8,44 %, 0,74 / 0,98 s, sin puntuación, la más ligera) | Parakeet es el más preciso con mucha diferencia (3 puntos), a cambio de ~0,1 s de cómputo por segundo de segmento y p95 3,35 s con la CPU cargada. Si el retardo o la RAM mandan, SenseVoice. Nemotron 3.5 (12,6-13,4 %) no es una opción en ja |
| **Coreano** | **SenseVoice-Small** (7,14 %, 8,09 % con música, final 0,91 / 1,23 s, 0,07 núcleos) | **Nemotron 3.5 560 ms** `blank_penalty` 1 (8,43 %, parciales, mismo motor que el inglés) y `kangkyu` chunk 64 (8,47 %, 0,11 núcleos, 0,58 / 0,62 s) | SenseVoice gana en CER, escribe espacios y cuesta poco; los dos streaming omiten los espacios (la traducción pierde 0,8-2,3 chrF y salta el filtro de longitud) y Nemotron triplica el RTF con la CPU cargada (p95 4,6 s). **Esto contradice la elección provisional del informe de investigación (Nemotron principal)** |
| **Filtro de idioma** | **Whisper base ONNX, ventana de 6 s, decisión entre {idioma elegido, es, en}**, un hilo (96 / 131 ms): 97,3-99 % del idioma correcto, 0,3-0,7 % del español | Whisper tiny (49 / 90 ms, 96-99 %); etiqueta de idioma de SenseVoice como segunda comprobación | no llega a «0 % de español»; con SenseVoice como ASR conviene añadir su etiqueta (AND) |

Notas para el plan:

- **Un solo modelo para los tres idiomas es posible:** SenseVoice-Small (163 MB, 0,06-0,07 núcleos, RAM 357 MB) con `language=` fijado y su etiqueta de idioma; Parakeet (ja) y X-ASR (zh) mejoran el CER 3 y 0,7 puntos a cambio de más recursos.
- **Dos perfiles de motor:** streaming (X-ASR; Nemotron, `kangkyu` si se quieren parciales) y por segmentos (Parakeet, SenseVoice, ReazonSpeech). Los segmentos solo emiten `final`, a ≥ 0,5 s del fin del habla más la decodificación.
- **Descartar los textos de 1-2 caracteres** de los modelos por segmentos y no darles nunca audio sin puerta de VAD (alucinan en toda la música: 150 de 150 trozos).
- **Segmentación:** el 22-34 % de las frases queda partido en 2 o más tramos con 500 ms de silencio (FR-014): conviene medir otras políticas (silencio mayor en ja/ko, agrupar tramos antes de traducir).
- **Filtro de idioma:** aplicarlo por segmento (con los primeros 6 s) antes del ASR; los segmentos de menos de 2 s son los más inseguros (93 %). No se puede distinguir japonés de chino de coreano ajeno con Whisper restringido (13-26 % del otro asiático pasa); la etiqueta de SenseVoice sí.
- **Traducción:** mantener el prompt de producción tal cual para ja/zh/ko; **cambiar en `hymt2.py` el filtro de longitud (3× caracteres: 6× cubre todo el corpus con p95 de 3-4,6) y `max_tokens_for` (usar caracteres o un mínimo de ~150 con CJK)**. Con el idioma de origen CJK el tope de tokens y la proporción de caracteres deben depender del idioma. La plantilla oficial china para zh no se probó.
- El **glosario base** de `hymt2.py` (`select_glossary`) busca términos en inglés: no hace nada con texto CJK; habría que glosarios por idioma de origen (no medido).

## Problemas y soluciones

1. **El oráculo de «fin real del habla» por energía de S3 falla en FLEURS** (grabaciones con ruido: en ja marca el fin más de 0,3 s antes en 20 de 50 frases, hasta 10 s). Se sustituyó por la probabilidad de Silero sobre el clip limpio (frames con p ≥ 0,5). Ver «Habla real».
2. **La API de identificación de idioma de sherpa-onnx solo devuelve el idioma de mayor puntuación** (no se puede restringir a {T, es, en}). Se reimplementó con los mismos ONNX de Whisper y `onnxruntime` (log-mel de 30 s en numpy, codificador, decodificador con solo `<|startoftranscript|>`, logits de los tokens de idioma): coincide con sherpa-onnx en el 95 % de 420 recortes, y los ONNX aceptan ventanas más cortas (6 s).
3. **El codificador de Whisper de sherpa-onnx admite entradas de menos de 30 s**: con 6 s es 7 veces más rápido y la precisión no cae.
4. **Los modelos por segmentos alucinan en música** (tabla 3); el VAD de Silero (probado con orquesta, aria y coros) los protege.
5. **Los filtros y topes de `hymt2.py` están calibrados para el inglés** (ver tabla 5).
6. **Los transductores coreanos en streaming no escriben espacios** (Nemotron 3.5 con idioma `ko`, `kangkyu`): afecta a la traducción y al filtro de longitud.
7. **FLEURS en Hugging Face** ya no se carga con `datasets` (script del repositorio); se leen los ficheros `parquet-data/<idioma>/test-*.parquet` con `huggingface_hub` y `pyarrow`.
8. **La API de GitHub sin autenticar da 403 por límite de peticiones**: la lista de modelos de la release `asr-models` se sacó de la página `expanded_assets`; los modelos se descargan con `urllib`.
9. **`uv add` durante una campaña** (para `sacrebleu`, `tomli-w`) no estropeó las ejecuciones en marcha (`uv run` solo sincroniza paquetes nuevos), pero conviene no hacerlo con medidas de latencia.
10. **Para importar `hymt2.py` hace falta `tomli-w`** (lo importa `instanttraductor.config`); está solo en el entorno de este spike.

## Límites y pendientes

- **El corpus no es cine.** Son frases de Wikipedia leídas por una persona en un registro formal, de 5 a 25 s, con la voz normalizada y sin efectos; los números absolutos (CER 5-9 %, traducción) son **optimistas** frente a diálogo de series y películas (habla espontánea, susurros, varios hablantes, efectos, canciones). Las referencias de S3 también eran lectura limpia. El CER de ASR de cine y el corpus de habla baja de la spec 002 siguen pendientes. Estimaciones de los autores de los modelos (JSUT, ReazonSpeech test) no son comparables con estas.
- **La música es suave:** 4 pistas orquestales a 10 dB por debajo del habla (más 3 con voz cantada solo en el VAD de ja); pop, rock, efectos de explosión o canciones con letra en el idioma elegido **no se probaron**. El CER con música solo sube 0,3-1,9 puntos; es una cota inferior del daño real.
- **50 frases por idioma:** una frase son ~2 puntos porcentuales en las tasas de «aceptado» del filtro (con 50 recortes) y ~0,6 con 300; las latencias son p50 / p95 de 61-68 tramos por ejecución. El «0,3-0,7 % de español» del filtro se basa en 1-2 recortes de 300. Cada configuración se midió una sola vez.
- **Reloj virtual:** equivalente al tiempo real en la única ejecución contrastada (X-ASR zh); las colas de ja, zh y ko corrieron en paralelo (3 procesos con 2 hilos de ASR cada uno, más otros obreros puntuales), así que la contención de CPU entre ellas está dentro de las cifras de la tabla 1 (el ASR más pesado, Nemotron, la sufrió más). Con la CPU «cargada» se usaron 12 procesos de punto fijo (75 % de los hilos): no es un juego real. La carga no se midió con la GPU compartida con un juego.
- **Latencias del filtro de idioma** medidas con un hilo en el equipo libre solo para Whisper propio; la API de sherpa-onnx y SenseVoice se midieron con otros procesos en marcha. El log-mel en numpy es parte del coste (se puede optimizar).
- **No medido:** Whisper large-v3-turbo FP16 en GPU como referencia (el brief lo dejaba «si da tiempo»; no dio), Qwen3-ASR y Fun-ASR-Nano (alternativas del informe), COMET o juicio humano de la traducción (SC-002 lo hace la persona usuaria con `traducciones_*.md`), `num_threads` distintos de 2 (S3 vio que más hilos gastan más CPU), la plantilla china oficial de Hy-MT2 para zh, el Hy-MT2 1.8B, textos con errores de ASR de otros candidatos, VRAM del traductor en esta tanda.
- **Normalización del CER:** los numerales de ideogramas se unifican con cifras en ja y zh, pero el coreano no (`십오` frente a `15`) ni los números escritos en hiragana; la referencia en coreano de FLEURS usa cifras, y SenseVoice usa ITN, Nemotron y `kangkyu` no: puede perjudicar a estos dos.
- **Referencia de traducción es_419:** no usa «vosotros» ni léxico de España; el chrF solo vale para comparar variantes entre sí. Hy-MT2 tradujo con el «tú» en los ejemplos revisados («puede que quieras…»); el «vosotros» de la spec no se midió con CJK.
- **Licencias de modelos** tomadas del informe de investigación y de las tarjetas, no releídas aquí. Las dos grandes dudas siguen siendo la tarjeta sin licencia del zipformer-zh 2025 y los datos de AI Hub de `kangkyu`.

## Cómo reproducir

Todo con `uv run` desde `spikes/idiomas` (en la raíz del repo no hay `pyproject.toml`). Nada de audio ni de modelos va al repo.

```powershell
cd spikes/idiomas
uv sync
uv run python fetch_music.py            # música de Musopen (Commons) -> WAV 16 kHz; --vocal para aria y coros
uv run python fetch_models.py           # modelos de sherpa-onnx y el zipformer coreano (fuera del repo)
uv run python build_corpus.py           # FLEURS -> clips, flujos con y sin música, recortes para el filtro, corpus_manifest.json
bash campaign/asr_campaign.sh           # tres colas (ja, zh, ko) de ASR en paralelo -> results/asr_*.json
bash campaign/load_runs.sh              # los candidatos principales con la CPU cargada (12 procesos ocupados)
uv run python run_asr.py --model xasr960 --lang zh --paced --conds clean --tag _paced   # tiempo real de verdad
uv run python run_music_only.py --model parakeet_ja sensevoice --lang ja [--vocal]
uv run python run_lid.py --threads 1 --tag _busy                     # Whisper (API de sherpa y propio) y SenseVoice
uv run python run_lid.py --threads 1 --whisper-only --window 6 --tag _w6
uv run python run_lid_big.py --n 300 --window 6
uv run python translate.py --all-variants --md --jobs prod,ja,ref,free prod,zh,ref,free prod,ko,ref,free prod,ja,nopunct prod,zh,nopunct prod,ko,nopunct --out translate_main
uv run python translate.py --out translate_asr --jobs prod,ja,asr:asr_parakeet_ja_ja_t2.json@clean ...
uv run python report_asr.py | report_lid.py <fichero> | report_translate.py   # tablas
```

## Contenido de la carpeta

| Fichero | Para qué sirve |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | proyecto uv propio (Python 3.12) |
| `idiomas/asr.py` | candidatos, tuberías (streaming y por segmentos) y simuladores (reloj virtual y tiempo real) |
| `idiomas/vad.py`, `audio.py`, `text.py` | Silero VAD (copia de S3), utilidades de audio y mezcla, normalización y CER |
| `idiomas/lid.py` | Whisper tiny/base ONNX para el idioma hablado (propio, con subconjuntos y ventana corta) |
| `fetch_models.py`, `fetch_music.py`, `build_corpus.py` | descargas y montaje del corpus |
| `run_asr.py`, `run_music_only.py`, `run_lid.py`, `run_lid_big.py`, `translate.py` | mediciones |
| `report_asr.py`, `report_lid.py`, `report_translate.py` | tablas Markdown a partir de `results/` |
| `campaign/` | `asr_campaign.sh`, `load_runs.sh`, `cpu_hog.py` |
| `results/` | JSON de cada medición (con el texto de cada frase) y `tablas_*.md` |
| `traducciones_{ja,zh,ko}.md` | las 50 frases: original, referencia es_419, referencia en inglés y traducción, para que el humano las juzgue (SC-002) |
| `corpus_manifest.json`, `music_licenses*.json` | referencias, tiempos y procedencia del corpus |

## Licencias

- **Datos:** FLEURS **CC BY 4.0** (Google); música de **Musopen** vía Wikimedia Commons (**dominio público / CC0**, `music_licenses*.json`).
- **Modelos:** sherpa-onnx Apache-2.0; Silero VAD MIT; **X-ASR-zh-en Apache-2.0**; zipformer-zh 2025 (icefall, la tarjeta no declara licencia; datos multi_zh-hans); **Nemotron 3.5 streaming OpenMDW-1.1**; **Parakeet-tdt_ctc-0.6b-ja CC-BY-4.0** (atribución a NVIDIA);
  **ReazonSpeech zipformer k2 v2 Apache-2.0**; **SenseVoice-Small FunASR Model License v1.1** (atribución y conservar el nombre del modelo; el paquete de sherpa solo enlaza el texto); `kangkyu` zipformer coreano Apache-2.0 según la tarjeta (datos de AI Hub);
  Whisper (tiny, base, large-v3-turbo) MIT; **Hy-MT2 Apache-2.0** (verificado en `docs/investigacion/2026-10-02-asr-ja-zh-ko.md`). Las licencias de modelo no se han releído aquí: se toman de ese informe y de las tarjetas.
- **Librerías:** `jiwer` Apache-2.0, `sacrebleu` Apache-2.0, `numpy` BSD, `onnxruntime` MIT.
