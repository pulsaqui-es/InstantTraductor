# S1: prueba de arranque («hito 0») de la voz en la RTX 5070 con Windows nativo

Spike de investigación de la spec 001 (ADR-0008). No es código de producto: mide y compara los dos candidatos de voz.
Fecha de las mediciones: 2026-10-01.

## Objetivo

Comprobar, en el PC objetivo (RTX 5070 12 GB, Blackwell sm_120, Windows 11 nativo, sin WSL2), si los dos candidatos de ADR-0008
cumplen el criterio «primer audio (TTFA) p95 ≤ 0,6 s»:

- **A**: Qwen3-TTS-12Hz-0.6B-Base con `faster-qwen3-tts` (CUDA graphs), `language="Spanish"`.
- **B**: Chatterbox Multilingual con el finetune es-ES (`ResembleAI/Chatterbox-Multilingual-es-es`).

Se mide TTFA (p50 y p95) en streaming, RTF, VRAM pico y tiempo de carga; se generan las mismas 6 frases con cada uno para que el
humano elija escuchando (¿suena a España?); y se responde a «¿se puede pedir 1,1× y 1,25× de velocidad?».

## Conclusión (resumen)

| | A: Qwen3-TTS 0,6B + faster-qwen3-tts | B: Chatterbox es-ES (PyTorch eager, fp32) |
|---|---|---|
| Funciona en Windows nativo + sm_120 | **Sí** (CUDA graphs capturan y se ejecutan) | **Sí** (con torch 2.11 cu130 en lugar del `torch==2.6.0` fijado) |
| TTFA p50 / p95, configuración principal | **263 / 270 ms** (`chunk_size=8`); 179 / 182 ms (`chunk_size=4`); 117 / 122 ms (`chunk_size=1`) | **730 / 748 ms** (primer chunk de 10 tokens); 609 / 624 ms (5 tokens) |
| ¿Cumple TTFA p95 ≤ 0,6 s? | **Sí, con margen ×2 a ×5** | **No** tal cual (0,62-0,85 s); con 5 pasos CFM baja a 0,43 s (ver «Resultados») |
| RTF (generación / audio) | 0,33 (`chunk_size=8`), 0,41 (4), 0,63 (1): 1,6× a 3× tiempo real | 1,12 en streaming (0,89× tiempo real: **no aguanta tiempo real continuo**); 0,65 por frase completa |
| VRAM pico (NVML − línea base, con contexto CUDA) | 3,3 GiB (`torch` asignado 2,6 GiB) | 3,8 GiB (`torch` asignado 3,4 GiB) |
| Carga del modelo | 6,1 s (+0,8 s de captura de grafos, +0,5 s del prompt de la referencia) | 6,0 s (+1,5 s de la referencia) |
| Arranque en frío (1ª petición, sin calentar) | 1,42 s (incluye la captura perezosa de los grafos) | 1,00 s (total 3,9 s) |
| Inteligibilidad (Whisper-small, 6 muestras) | WER medio 2,0 % | WER medio 3,0 % |

**Recomendación para el plan:** fijar **A (Qwen3-TTS-0,6B + faster-qwen3-tts) como motor por defecto de la spec 001**: cumple el criterio
con mucho margen en Windows nativo, sin WSL2 y con `chunk_size` entre 1 y 8 según el compromiso latencia/continuidad. **B solo entra si el humano
prefiere su acento al escuchar** (la elección final es de oído: no hay benchmark de acento es-ES): en ese caso hay que presupuestar trabajo
de optimización (CUDA graphs en T3 y en el decodificador S3Gen, menos pasos CFM), porque el código actual no da TTFA ≤ 0,6 s p95 ni sostiene tiempo
real en streaming continuo. Detalles, cifras y matices en las secciones siguientes.

PENDIENTE_RESUMEN_EXTRA

## Entorno

| Elemento | Valor |
|---|---|
| Sistema | Windows 11 Pro 10.0.26200 (25H2) |
| CPU / RAM | Ryzen 7 8700F (8 núcleos, 16 hilos), 31,7 GB |
| GPU | NVIDIA GeForce RTX 5070, 12 227 MiB (12 199 MiB visibles para torch), compute capability 12.0 (sm_120), modo WDDM |
| Driver NVIDIA | 616.64 (CUDA UMD 13.4) |
| Python | 3.12.14 (CPython gestionado por uv 0.12.21), un entorno por candidato |
| PyTorch | 2.11.0+cu130 y torchaudio 2.11.0+cu130 (índice `https://download.pytorch.org/whl/cu130`); `sm_120` aparece en `torch.cuda.get_arch_list()` (`sm_75 … sm_100 sm_120`) |

**Entorno A** (`spikes/voz/qwen3/`): `faster-qwen3-tts` 0.5.3 (MIT), `qwen-tts-hf` 0.1.1.post1 (recompilación de `qwen-tts` para Transformers 5),
`transformers` 5.15.1, `accelerate` 1.12.0, `numpy` 2.5.3, `soundfile` 0.14.0, `huggingface-hub` 1.33.0. Modelo `Qwen/Qwen3-TTS-12Hz-0.6B-Base`
(Apache-2.0, 2,5 GB), bf16, atención SDPA, `max_seq_len=2048`.

**Entorno B** (`spikes/voz/chatterbox/`): `chatterbox-tts` 0.1.7 (MIT; solo se usan sus módulos), `transformers` 5.2.0, `numpy` 1.26.4, `librosa` 0.11.0,
`safetensors` 0.5.3, `resemble-perth` 1.0.1, `s3tokenizer` 0.3.0, `diffusers` 0.29.0. Pesos: `ResembleAI/Chatterbox-Multilingual-es-es`
(`t3_es_es.safetensors` 2,14 GB, `s3gen_v3.safetensors` 1,06 GB, `grapheme_mtl_merged_expanded_v1.json`; MIT) más `ResembleAI/chatterbox`
(`ve.pt` y `conds.pt`; MIT). fp32, PyTorch eager.

**Herramientas** (`spikes/voz/`, sin torch): `audiostretchy` 1.3.5 y `audiotsm` 0.1.2 (time-stretch), `scipy`, `soundfile`, `filelock`, `nvidia-ml-py`.
**Auxiliar:** `openai/whisper-small` (MIT, en CPU) solo para transcribir la referencia y comprobar la inteligibilidad de las muestras.

Modelos y audio viven fuera del repo: `%LOCALAPPDATA%\InstantTraductor\models\` (descargados con `local_dir`, sin caché de Hugging Face ni enlaces simbólicos) y
`%LOCALAPPDATA%\InstantTraductor\spikes\voz\`. Ningún repositorio exigió cuenta ni aceptar términos (`gated=False`).
Todas las mediciones con GPU fueron bajo el candado `%LOCALAPPDATA%\InstantTraductor\gpu.lock` (`filelock`; a veces hubo que esperar a otros obreros: 0 s a 318 s).

## Método

- **Frases:** 20 de medición (5 a 25 palabras, español de España: «vosotros», «vale», «ordenador», «móvil», «coche», avisos, noticias, diálogo de series) y 6 de muestra
  (las mismas para ambos). Están en `common/vozbench.py`.
- **Referencia de voz:** la misma para ambos (6,86 s, mono 24 kHz), ver «Voz de referencia».
- **TTFA:** segundos desde que se llama al generador de streaming hasta que el primer chunk de audio está en memoria del llamante. Incluye tokenización del texto,
  prefill, generación de los primeros tokens y decodificación del códec/vocoder. Excluye carga del modelo, captura de grafos y construcción del prompt de la referencia
  (cacheado, como haría el producto por personaje). Con la referencia ya cacheada y tras calentamiento.
- **RTF:** tiempo total de generación / duración del audio generado (sin reproducir: los chunks se consumen sin esperar). `xRT` = su inverso.
- **Repeticiones:** 20 frases × 3 repeticiones = 60 peticiones por fila de A (semillas fijas); 20 × 2 = 40 en la fila principal de B y 20 × 3 = 60 (solo hasta el primer chunk) en el barrido de B.
  p95 = percentil 95 con interpolación lineal de NumPy.
- **VRAM:** `torch.cuda.max_memory_allocated/reserved` más el total de la GPU según NVML (el mismo dato que `nvidia-smi`; en WDDM no hay uso por proceso), sondeado a 10 Hz. Con el
  candado cogido y el escritorio estable, «pico − línea base» es la VRAM del proceso, contexto CUDA incluido. Línea base del escritorio: ~1,8 GiB.
- **Carga:** desde el inicio de `from_pretrained` hasta tener el modelo en GPU, con los ficheros ya en la caché de disco del sistema operativo.
- **Arranque en frío:** proceso nuevo sin calentamiento explícito; la 1ª petición lo paga todo (captura de grafos en A, inicialización de kernels en B).
- **CPU:** libre durante las mediciones (la transcripción con Whisper se hizo aparte).

## Resultados

Cifras en bruto (incluida cada petición) en `resultados/*.json`; las tablas salen de `common/informe_tablas.py`.

### A: Qwen3-TTS-0,6B Base + faster-qwen3-tts (modo ICL, referencia cacheada, calentado)

`resultados/qwen3_completa_icl.json`. 60 peticiones por fila (20 frases × 3 repeticiones, semillas fijas).

| `chunk_size` | audio por chunk | TTFA p50 (ms) | **TTFA p95 (ms)** | TTFA máx (ms) | RTF p50 | RTF p95 | × tiempo real (p50) |
|---|---|---|---|---|---|---|---|
| 1 | 83 ms | 117 | **122** | 139 | 0,627 | 0,737 | 1,60 |
| 2 | 167 ms | 138 | **143** | 146 | 0,454 | 0,521 | 2,20 |
| 4 | 333 ms | 179 | **182** | 185 | 0,372 | 0,414 | 2,69 |
| 8 | 667 ms | 263 | **270** | 279 | 0,330 | 0,360 | 3,03 |

- **Desglose:** TTFA ≈ 95 ms + 20,9 ms × `chunk_size` (prefill 45 ms + `chunk_size` pasos de 20,9 ms con CUDA graphs + ~50 ms de tokenización y decodificación del códec, que incluye los códigos de la referencia del modo ICL).
  No depende de la longitud de la frase (correlación palabras-TTFA de −0,07 a −0,18; 5 a 25 palabras), así que el p95 casi coincide con el p50.
- **Repetible:** otra ejecución independiente con `chunk_size=8` (`qwen3_muestras_ajuste.json`) dio 264 / 268 ms.
- **Velocidad de generación:** 20,9 ms por paso de códec (83 ms de audio) = 4× en el bucle de decodificación; el RTF total es 0,33 por la decodificación del códec y la copia a CPU por chunk. Con `chunk_size=1` el coste por chunk sube (RTF 0,63) pero sigue por debajo de 1.
- **Carga y arranque:** carga del modelo 6,1 s; `warmup()` (captura de los grafos del predictor y del talker) 0,84 s; creación del prompt de la referencia (espectro, tokens del códec, embedding del hablante) 0,47 s por referencia, que es lo que el producto cachearía por personaje.
  **Arranque en frío** (sin `warmup()`): la 1ª petición tarda TTFA 1,42 s (total 2,43 s) porque captura los grafos; la 2ª ya da 0,26 s. En producción basta con llamar a `warmup()` al arrancar el proceso.
- **VRAM:** `torch` asignado pico 2 679 MiB (reservado 3 076 MiB); NVML pico total 5 096 MiB con una línea base de escritorio de 1 792 MiB → **3 304 MiB de delta** (contexto CUDA incluido). Tras cargar, 2 070 MiB asignados.
- **Modo x-vector** (`xvec_only=True`: solo el embedding del hablante, sin `ref_text`; `resultados/qwen3_completa_xvec.json`): TTFA p50 / p95 de 98 / 105 ms (`chunk_size=1`), 119 / 125 (2), 165 / 170 (4) y 248 / 258 ms (8); RTF p50 de 0,49 a 0,31;
  VRAM pico 2 449 MiB asignados y 2 767 MiB de delta. Gana 15-20 ms al modo ICL porque el prefill es más corto (~10 tokens frente a ~80+) y no decodifica los códigos de la referencia. Es el modo de rescate del ADR-0008 (acento, arranque en frío) a costa de parecido de voz;
  sus muestras están en `extra\A_qwen3_xvec_NN.wav`.
- **`chunk_size=1` por oído:** `extra\A_qwen3_cs1_NN.wav` son las mismas 6 frases con chunks de 83 ms, para comprobar que no se pierde calidad con el chunk más pequeño.

### B: Chatterbox Multilingual es-ES (PyTorch eager, fp32; envoltorio `cb_es.py`)

`resultados/chatterbox_completa.json`. Streaming por chunks (envoltorio propio: el paquete oficial solo genera la frase completa). El primer chunk sale cuando hay «N + 3» tokens de voz (1 token = 40 ms de audio; los 3 últimos son la mirada adelante del flujo).

| Configuración | 1er chunk | TTFA p50 (ms) | **TTFA p95 (ms)** | máx (ms) |
|---|---|---|---|---|
| `p5` (5+3 tokens, chunks siguientes de 15) | 0,2 s de audio | 609 | **624** | 639 |
| `p10` (10+3, siguientes de 25) — **principal** | 0,4 s | 726 | **748** | 750 |
| `p15` (15+3, siguientes de 25) | 0,6 s | 831 | **852** | 860 |

- **RTF en streaming `p10`: p50 1,117, p95 1,321 (0,89× tiempo real)**: el bucle T3 + S3Gen no aguanta tiempo real continuo. Por frase completa (ruta oficial): tiempo hasta el audio completo p50 2,46 s, p95 4,29 s; RTF p50 0,648 (0,20 s por palabra).
- **Desglose del primer chunk (`p10`, mediana de 10 frases):** prefill 27 ms + 13 pasos de T3 × 20,4 ms (265 ms) + decodificación S3Gen del primer chunk 433 ms (flujo CFM de 10 pasos con guía y vocoder HiFT) = **719 ms**.
  Dominan T3 (37 %) y, sobre todo, el decodificador S3Gen (60 %); parecen costes de lanzamiento de kernels desde Python (el tamaño de la referencia no influye, ver más abajo), que es justo lo que los CUDA graphs aceleran en A.
- `cfg_weight=0` (una sola secuencia en vez de dos, sin guía): TTFA p50 729 ms, p95 782 ms; RTF 1,12. No ayuda (el coste es de lanzamiento de kernels, no de cómputo).
- **Marca de agua PerTh** (solo en la ruta de frase completa; omitida en streaming): 8 ms para 2,1 s de audio en CPU (la primera llamada, 0,11 s).
- **Arranque en frío:** 1ª petición TTFA 1,00 s (total 3,88 s); la 2ª, 0,70 s. Carga del modelo 6,0 s; preparar la referencia (espectro, tokens, embeddings) 1,5 s.
- **VRAM:** `torch` asignado pico 3 521 MiB (reservado 3 686 MiB); NVML pico total 5 682 MiB con línea base de 1 777 MiB → **3 904 MiB de delta**. Tras cargar, 3 075 MiB asignados (T3 2,14 GB y S3Gen 1,06 GB en fp32).

**Optimizaciones baratas (sin tocar el modelo)** — `resultados/chatterbox_optim.json` y `chatterbox_optim_p10.json` (TTFA con 20 frases × 3 repeticiones; RTF con 8 frases):

| Variante | TF32 | pasos CFM | referencia del decodificador | TTFA p50 (ms) | **TTFA p95 (ms)** | RTF p50 |
|---|---|---|---|---|---|---|
| `p5` base | no | 10 | completa (6,9 s) | 588 | 617 | 1,43 |
| `p5` + TF32 | sí | 10 | completa | 613 | 632 | 1,53 |
| `p5` + TF32 + 5 pasos | sí | 5 | completa | 410 | **432** | 1,07 |
| `p5` + TF32 + 5 pasos + referencia 3 s | sí | 5 | 3 s | 409 | **424** | 1,03 |
| `p5` + TF32 + 3 pasos + referencia 3 s | sí | 3 | 3 s | 334 | **354** | 0,88 |
| `p10` + TF32 + 5 pasos | sí | 5 | completa | 564 | 603 | 0,97 |
| `p10` + TF32 + 3 pasos | sí | 3 | completa | 467 | 484 | 0,81 |

TF32 no aporta nada; **los pasos del flujo CFM son la palanca** (≈ 45 ms cada uno). Acortar la referencia del decodificador a 3 s tampoco cambia el TTFA. Con 5 pasos y primer chunk de 5 tokens, B baja a p95 0,43 s (cumple), pero el RTF sigue en ~1,0
(sin CUDA graphs en T3 no se sostiene tiempo real continuo) y **puede costar calidad**: las muestras `extra\B_chatterbox_p5_tf32_cfm5_NN.wav` (5 pasos), `…_cfm5_ref3s_NN.wav` y `…_cfm3_ref3s_NN.wav` permiten juzgarlo de oído.
Estimación (no medida): con CUDA graphs en el paso de T3 (20 ms → ~6-8 ms) y en el flujo, más 5 pasos CFM, el TTFA de B bajaría a ~0,25-0,3 s y el RTF a ~0,4: trabajo de ingeniería, no de configuración.

### Velocidad de habla: ¿se puede pedir 1,1× y 1,25×?

**Ninguno de los dos tiene un parámetro de velocidad.** `generate_voice_clone_streaming` de `faster-qwen3-tts` no tiene `speed`/`duration`; `ChatterboxMultilingualTTS.generate` tampoco. Lo único «nativo» es indirecto y no sirve para pedir un factor exacto:

| Vía | Efecto medido (10 frases × 2 semillas, mismas semillas en cada variante) | TTFA |
|---|---|---|
| **A: argumento `instruct`** («Habla más rápido de lo normal», «Habla un 25 % más rápido», «Speak 25% faster than normal», «Habla muy deprisa…») | velocidad efectiva **mediana 0,99-1,05×**, con dispersión enorme (mín 0,89×, máx 1,76×: algunas salidas salen mucho más cortas, posibles palabras comidas). Sin efecto fiable; en Base es «experimental» según la propia biblioteca. | sin cambio (263 → 264-265 ms) |
| PENDIENTE_VEL_B | | |
| **Post-proceso: time-stretch del PCM en streaming** (TDHS de la biblioteca C «stretch», la familia de Sonic, o WSOLA) | **factor exacto**: 1,099-1,103× y 1,248-1,249× (TDHS); 1,104-1,105× y 1,257-1,260× (WSOLA) | ver abajo |

**Recomendación: control de velocidad por post-proceso**, en un `RateController` que trabaje sobre el PCM que sale de cualquiera de los motores (coincide con la política de ritmo del informe de traducción y voz, §3.8). Medido con
chunks de 83, 200, 333 y 667 ms (los tamaños que emiten A y B), sobre 4 muestras reales (`resultados/velocidad_postproceso.json`, WAV estirados en `muestras\velocidad\`):

- **Coste:** 3,0-4,2 ms de CPU por cada segundo de audio; cómputo del primer chunk entre 0,13 y 2,7 ms.
- **Efecto en el TTFA:** prácticamente nulo en cómputo (**+0,1 a +2,7 ms**) más un **retraso algorítmico de 28-46 ms** de audio (el algoritmo guarda un trozo de señal: el primer chunk produce 10-40 ms menos de audio del esperado y ese desfase se mantiene).
  En la práctica el primer audio sale inmediatamente con el factor aplicado y todo el audio posterior llega ~30-45 ms más tarde de lo que llegaría sin estirar; a cambio cada segundo de voz dura 0,91 s (1,1×) o 0,8 s (1,25×), así que el retraso acumulado baja.
- TDHS y WSOLA dan el mismo factor y coste; cuál suena mejor a 1,25× lo decide el oído con `muestras\velocidad\`. El informe de traducción y voz ya sitúa 1,0-1,25× como casi imperceptible y >1,4× como notable.

PENDIENTE_VEL_NOTA

PENDIENTE_CONTENCION

## Voz de referencia y origen/licencia

Una sola referencia para los dos candidatos, preparada con `uv run python prepare_reference.py referencia` (lee `referencia.json`; el resultado es reproducible bit a bit,
sha256 `f3cbcbf48452b455…`).

| Campo | Valor |
|---|---|
| Fuente | LibriVox (dominio público), «Trafalgar», de Benito Pérez Galdós, sección 02 |
| Lector | **Tux** (voluntario de LibriVox), voz masculina (F0 mediana ~122 Hz), relación señal/ruido aproximada 22 dB |
| URL | https://archive.org/details/trafalgar_0909_librivox (audio: https://archive.org/download/trafalgar_0909_librivox/trafalgar_02_perezgaldos.mp3) |
| Minuto | de 02:39,72 a 02:46,58 del fichero `trafalgar_02_perezgaldos.mp3` (6,86 s) |
| Licencia | Dominio público (grabación de LibriVox; Internet Archive la marca como dominio público) y texto de 1873 |
| Texto (`ref_text` de Qwen3 ICL) | «expedito, pero doña Francisca, no convencida con tan endeble argumento, continuó chillando en estos términos.» (Project Gutenberg #16961, contrastado palabra por palabra con Whisper-small sobre el propio recorte) |
| Formato | WAV PCM16 mono 24 kHz, RMS −20 dBFS, fundidos de 30 ms; en `%LOCALAPPDATA%\InstantTraductor\spikes\voz\ref\ref_es_es_24k.wav` (no está en el repo) |

**Advertencia sobre el acento: no puedo oír el audio.** `librivox.org` no respondía durante la sesión (errores 522 de Cloudflare), así que no pude comprobar de dónde es Tux. En lugar de
asumirlo, medí un indicio acústico: en castellano peninsular «ce, ci, z» suena /θ/, una fricativa mucho más débil que /s/; con seseo (español de América, parte del andaluz) son la misma /s/.
`common/distincion_informe.py` mide la fuerza de la fricativa relativa a la vocal más fuerte de cada palabra (dB), en palabras cuya única fricativa es /θ/ frente a palabras con solo /s/,
con tiempos por palabra de Whisper-small:

| Grupo | n (/θ/) | n (/s/) | nivel /θ/ (dB) | nivel /s/ (dB) | Δ (s − θ) | p (Mann-Whitney) |
|---|---|---|---|---|---|---|
| Tux, «Trafalgar» (5 min) | 29 | 58 | −20,9 | −15,2 | **5,8** | 1,9e-7 |
| Mongope, «Abel Sánchez» (5 min) | 26 | 50 | −23,9 | −11,5 | **12,4** | 1,3e-8 |
| Control peninsular (OpenSLR SLR61, mensajes del tiempo en español peninsular, CC BY-SA 4.0) | 5 | 29 | −31,3 | −15,9 | **15,5** | 7,2e-6 |
| Control argentino (SLR61, seseo; solo la palabra «hace») | 86 | 44 | −15,8 | −14,1 | **1,8** | 0,052 (no significativo) |

Lectura: Tux se comporta como el control peninsular (la /θ/ es claramente más débil que la /s/) y no como el control con seseo. Es un **indicio**, no una prueba de que sea de España
(el control argentino solo tiene una palabra /θ/; los lectores son prosa libre transcrita con un ASR pequeño). **El humano debe escuchar `ref_es_es_24k.wav` antes de juzgar el acento de las
muestras**: si la referencia no suena a España, el acento de A (que imita la referencia) saldrá sesgado; `referencia.json` se cambia en una línea y las muestras se regeneran con un comando.

## Muestras para escuchar

En `%LOCALAPPDATA%\InstantTraductor\spikes\voz\muestras\` (WAV PCM16 mono 24 kHz, sin reproducir por los altavoces; fuera del repo). Las mismas 6 frases con cada candidato
(pico normalizado a −0,2 dBFS si el motor lo superaba: Chatterbox llegaba a 1,14):

| Frase | A (Qwen3) | B (Chatterbox) |
|---|---|---|
| 1. «Vale, ¿vosotros venís en coche o cogéis el autobús? Yo llego en veinte minutos.» | `A_qwen3_01.wav` | `B_chatterbox_01.wav` |
| 2. «Se me ha estropeado el ordenador y no encuentro el móvil, así que hoy no puedo contestar a nadie.» | `A_qwen3_02.wav` | `B_chatterbox_02.wav` |
| 3. «Tío, ¿has visto el capítulo de anoche? Me ha parecido una pasada, sobre todo el final.» | `A_qwen3_03.wav` | `B_chatterbox_03.wav` |
| 4. «Buenas tardes, señoras y señores. Les habla el capitán: en breve aterrizaremos en el aeropuerto de Madrid.» | `A_qwen3_04.wav` | `B_chatterbox_04.wav` |
| 5. «Después de tres años de negociaciones, el gobierno ha anunciado una reforma que cambiará la vida de millones de personas.» | `A_qwen3_05.wav` | `B_chatterbox_05.wav` |
| 6. «¡Cuidado con la zorra! Vosotros id por la izquierda, que yo cubro el centro y luego nos vemos en el coche.» | `A_qwen3_06.wav` | `B_chatterbox_06.wav` |

- A se generó por la ruta de streaming (`chunk_size=8`, ICL con la referencia, semilla fija por frase). B, por la ruta oficial de frase completa (`generate`-equivalente, con marca de agua PerTh), que es la calidad
  de referencia del modelo; la ruta de streaming de B (con empalmes entre chunks) está en `extra\B_chatterbox_stream_NN.wav` para comprobar que no se oyen costuras.
- `muestras\extra\` tiene variantes para decidir con el oído: B con menos pasos CFM / referencia corta del decodificador (`B_chatterbox_p5_tf32_cfm5_NN`, `…_cfm5_ref3s_NN`, `…_cfm3_ref3s_NN`: muestran si la optimización de
  latencia cuesta calidad), las dos normalizaciones de texto de B (`B_chatterbox_space_NN` / `B_chatterbox_pip_NN`) y A en modo x-vector (`A_qwen3_xvec_NN`, si se genera).
- `muestras\velocidad\` tiene muestras estiradas a 1,10× y 1,25× (TDHS y WSOLA) para juzgar cuánto se nota.
- Whisper-small transcribe las 12 muestras principales con WER medio 2,0 % (A) y 3,0 % (B): son inteligibles. Eso **no** dice nada del acento ni de la naturalidad.

## Problemas y soluciones

1. **`faster-qwen3-tts` 0.5.3 + `transformers` 5.18.0 fallan al cargar** con `AttributeError: 'MimiConfig' object has no attribute 'rope_theta'`
   (`qwen_tts/_transformers_compat.py`). La capa de compatibilidad de `qwen-tts-hf` 0.1.1.post1 asume un `rope_theta` que `transformers` 5.18 ya no tiene.
   **Solución:** fijar `transformers==5.15.1` (el mínimo que pide `faster-qwen3-tts`) en `qwen3/pyproject.toml`. Hay un aviso inocuo de «SoX could not be found».
2. **`torchaudio` solo existe hasta la 2.11 en el índice cu130 para Windows** y exige el `torch` idéntico, así que no se pudo usar el `torch` 2.14.1+cu130 más nuevo: se usa `torch==2.11.0+cu130` (también con `sm_120`).
3. **El riesgo nº 2 del informe de clonación no se cumple:** el issue #92 de `faster-qwen3-tts` (RTX 5090, Windows nativo, 3-5 s por frase, «los CUDA graphs requieren Linux») no se reproduce. Con
   `faster-qwen3-tts` 0.5.3 y PyTorch 2.11+cu130 los grafos del predictor y del talker se capturan («CUDA graph captured!») y cada paso de decodificación tarda 20,9 ms. No hace falta WSL2.
4. **`chatterbox-tts` 0.1.7 fija `torch==2.6.0` (sin `sm_120`) y trae `gradio` como dependencia dura.** Solución: `override-dependencies` de uv (`torch`/`torchaudio` 2.11 cu130 y `gradio ; sys_platform == 'never'`).
   `spacy-pkuseg` y `resemble-perth` instalan con ruedas (no hay compilador de C en la máquina); `perth` avisa de que `pkg_resources` está obsoleto (inocuo con `setuptools` 81).
5. **El paquete `chatterbox-tts` 0.1.7 no sirve tal cual para el finetune es-ES**: su `ChatterboxMultilingualTTS` carga `s3gen.pt` y `t3_mtl23ls_v2`, obliga a usar el `AlignmentStreamAnalyzer` (atenciones en modo eager, más lento)
   y no tiene streaming. La demo oficial del finetune (Space `ResembleAI/Chatterbox-Multilingual-TTS-es-es`) vendoriza su propio código. Solución: `chatterbox/cb_es.py`, que monta los módulos de la rueda con los pesos es-es
   (T3 `t3_es_es`, S3Gen `s3gen_v3`; al cargar `s3gen_v3` solo faltan `tokenizer._mel_filters` y `tokenizer.window`, que no son pesos), sin analizador, con el muestreo oficial (`temperature` 0,8, `repetition_penalty` 1,2,
   `min_p` 0,05, `cfg_weight` 0,5, `exaggeration` 0,5) y con un bucle de T3 que suelta tokens por tandas.
6. **`CausalMaskedDiffWithXvec.inference(finalize=False)` de la rueda falla** (`expanded size of the tensor (420) must match the existing size (426)`): recorta la salida del codificador pero calcula la máscara con la longitud
   sin recortar. Solución: `cb_es.py::_mels` replica la función con la máscara correcta (todo unos con batch 1). Hace falta para el streaming (con `finalize=True` no ocurre).
7. **El `MTLTokenizer` de la rueda descarga el mapa Cangjie y carga `pkuseg` (chino) al construirse.** Solución: tokenización propia para español con el `tokenizers` del JSON (`[es]` + texto con `[SPACE]`). Se compararon las dos
   normalizaciones posibles (A/B con Whisper sobre las 6 muestras): la de la demo del finetune (sin minúsculas ni NFKD) WER medio 3,0 %; la del paquete (minúsculas + NFKD) 5,6 %. Es ruido con 6 frases; se usó la de la demo.
8. **Clipping de B:** el audio de Chatterbox llega a 1,14 de pico. Se baja la ganancia en `vozbench.write_wav` en vez de recortar (las muestras de A y B pasan por la misma normalización).
9. **Hugging Face con caché en Windows** duplica el disco si no hay enlaces simbólicos: los modelos se descargan con `local_dir` a `%LOCALAPPDATA%\InstantTraductor\models\`.
10. **LibriVox caído (Cloudflare 522)** durante la sesión: el audio se bajó de Internet Archive (que aloja las mismas grabaciones); el origen geográfico del lector no se pudo consultar (ver «Voz de referencia»).
11. **Transcripción de la referencia:** Qwen3 en modo ICL necesita `ref_text`. La única herramienta extra es Whisper-small en CPU (MIT, 0,97 GB), que no entra en el brief pero hace falta para esto y para detectar audio roto; su texto se contrastó con el
    texto del libro (Gutenberg) y se eligió el tramo cuyas 16 palabras coinciden exactamente.

### Limitaciones del spike (qué no se ha medido)

- **Acento y naturalidad:** no puedo oír el audio. Las muestras están listas para que las escuche el humano; los WER de Whisper-small solo dicen que son inteligibles.
- **Sistema ocioso:** las cifras principales son con la GPU y la CPU para el TTS solo (más la prueba sintética de contención de abajo). El TTFA real dependerá de lo que corra a la vez (ASR, traducción, el propio juego o vídeo).
- **Muestra pequeña:** 60 peticiones por fila (el p95 son las 3 más lentas); se repitió una configuración de A y dio lo mismo (263/270 y 264/268 ms). Son cifras de una máquina, un driver y una referencia.
- **B con streaming propio:** el paquete oficial no lo trae; `cb_es.py` sigue el enfoque de los forks de la comunidad (contexto a la izquierda de 10 tokens y fundido de 10 ms). Sus empalmes no se han evaluado de oído (hay muestras en `extra\`); el TTFA sí es el de ese código.
- **Sin sesiones largas ni frases de 1-3 palabras:** no se ha buscado fugas de VRAM en horas de uso, ni el comportamiento con cláusulas muy cortas (issue #96 de `faster-qwen3-tts`: saltos de prosodia entre chunks).
- **Carga:** medida con los ficheros en la caché de disco del sistema operativo (un arranque realmente frío leerá ~2,5 GB de A o ~3,3 GB de B del SSD).

## Cómo reproducir

Requisitos: Windows 11, uv, GPU NVIDIA con driver ≥ 570 (el probado es el 616.64). Nada a nivel de sistema (ni winget, ni instaladores, ni WSL2): uv descarga Python 3.12 por su cuenta.
Todos los comandos se ejecutan desde la carpeta indicada (en la raíz del repo no hay `pyproject.toml`). Las rutas `%LOCALAPPDATA%` se crean solas.

```powershell
# 1. Entornos (uno por candidato + uno ligero)
cd spikes/voz;            uv sync
cd spikes/voz/qwen3;      uv sync
cd spikes/voz/chatterbox; uv sync
cd spikes/voz/qwen3;      uv run python ../common/check_cuda.py        # versiones, CUDA y sm_120 (no mide nada)

# 2. Modelos, fuera del repo (no hace falta el candado de GPU)
cd spikes/voz/qwen3;      uv run python ../common/descargar_modelos.py qwen3 whisper
cd spikes/voz/chatterbox; uv run python ../common/descargar_modelos.py chatterbox

# 3. Voz de referencia (descarga el MP3 de Internet Archive y recorta; datos en referencia.json)
cd spikes/voz;            uv run python prepare_reference.py referencia

# 4. Mediciones A (Qwen3-TTS); todo con GPU va bajo el candado gpu.lock
cd spikes/voz/qwen3
uv run python bench_qwen3.py --fase fria                   # carga + 1ª petición sin calentar
uv run python bench_qwen3.py --fase completa               # calentamiento, barrido de chunk_size 1/2/4/8 y las 6 muestras
uv run python bench_qwen3.py --fase completa --modo xvec --sin-muestras --salida qwen3_completa_xvec.json
uv run python bench_qwen3.py --fase velocidad              # efecto de «instruct» en la velocidad
uv run python bench_qwen3.py --fase contencion             # TTFA con otra carga en la GPU

# 5. Mediciones B (Chatterbox es-ES)
cd spikes/voz/chatterbox
uv run python bench_chatterbox.py --fase fria
uv run python bench_chatterbox.py --fase completa --muestras-stream    # streaming, frase completa, cfg_weight=0, marca de agua, desglose, muestras
uv run python bench_chatterbox.py --fase completa --ab-texto           # dos normalizaciones de texto (muestras en extra\)
uv run python bench_chatterbox.py --fase optim                         # TF32 / pasos CFM / referencia corta
uv run python bench_chatterbox.py --fase velocidad                     # cfg_weight y exaggeration frente a la velocidad
uv run python bench_chatterbox.py --fase contencion

# 6. Comprobaciones en CPU (sin mediciones de GPU en marcha: compiten por CPU)
cd spikes/voz/qwen3;      uv run python ../common/asr_check.py A_qwen3
cd spikes/voz/qwen3;      uv run python ../common/asr_check.py B_chatterbox
cd spikes/voz;            uv run python velocidad_postproceso.py A_qwen3_01.wav B_chatterbox_01.wav   # time-stretch 1,10x y 1,25x
cd spikes/voz;            uv run python common/informe_tablas.py                                       # tablas de este README desde los JSON

# 7. (Opcional, ~25 min de CPU) evidencia de acento de la referencia: datos y transcripciones con Whisper-small
cd spikes/voz
uv run python prepare_reference.py bajar --ia trafalgar_0909_librivox --fichero trafalgar_02_perezgaldos_64kb.mp3
uv run python prepare_reference.py extracto --raw <ref>\raw\trafalgar_02_perezgaldos_64kb.mp3 --inicio 30 --fin 330 --out <ref>\exploracion\tux_trafalgar02_30_330.wav
uv run python prepare_reference.py bajar --ia abelsanchez_1904_librivox --fichero abelsanchez_03_unamuno_128kb.mp3
uv run python prepare_reference.py extracto --raw <ref>\raw\abelsanchez_03_unamuno_128kb.mp3 --inicio 30 --fin 330 --out <ref>\exploracion\mongope_abel03_30_330.wav
#   mensajes del tiempo de OpenSLR SLR61 (CC BY-SA 4.0): https://openslr.trmal.net/resources/61/es_weather_messages.zip -> descomprimir en <ref>\raw\es_weather_messages\ (carpetas es-es y es-ar)
cd qwen3
uv run python ../common/transcribir_varios.py <ref>\exploracion\tux_trafalgar02_30_330.wav <ref>\exploracion\mongope_abel03_30_330.wav
uv run python ../common/transcribir_lote.py <ref>\raw\es_weather_messages\es-es <ref>\raw\es_weather_messages\es-ar
cd ..; uv run python common/distincion_informe.py
# <ref> = %LOCALAPPDATA%\InstantTraductor\spikes\voz\ref
```

Para cambiar la voz de referencia: editar `referencia.json` (`ia_id`, `fichero`, `inicio_s`, `fin_s`, `texto`), repetir el paso 3 y regenerar las muestras (`bench_qwen3.py --fase completa`, `bench_chatterbox.py --fase completa --solo-muestras`).
Los resultados en bruto están en `resultados/*.json` (con cada petición individual); no se versionan modelos ni WAV.

## Estructura

```
spikes/voz/
  README.md, referencia.json, pyproject.toml/uv.lock   herramientas ligeras (sin torch)
  prepare_reference.py        descarga y recorta la referencia
  velocidad_postproceso.py    time-stretch en streaming (TDHS y WSOLA) a 1,1x y 1,25x
  common/                     vozbench.py (candado de GPU, VRAM, frases, WAV), descargar_modelos.py, asr_*.py, distincion*.py, carga_gpu.py, informe_tablas.py
  qwen3/                      entorno A + bench_qwen3.py
  chatterbox/                 entorno B + cb_es.py (envoltorio del finetune es-ES con streaming) + bench_chatterbox.py + prueba_cpu.py
  resultados/                 JSON con todas las cifras (pequeños)
```
