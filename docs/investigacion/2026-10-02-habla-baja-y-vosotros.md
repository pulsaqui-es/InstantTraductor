# Investigación: habla baja o alargada que no se traduce y «vosotros» en la traducción

- Fecha de consulta de todas las fuentes: **2026-10-02**.
- Pedido por el orquestador para la spec 002. Contexto leído: `CLAUDE.md`, `specs/001-espina-dorsal/research.md` y `validacion.md`, `spikes/traduccion/README.md`, `corpus.py`, `quality.py`, `src/instanttraductor/audio/agc.py`, `vad/silero.py` y `mt/hymt2.py`.
- Etiquetas: **[V]** verificado en la fuente primaria o midiendo en este PC; **[A]** afirmación del autor del recurso (no reproducida); **[E]** estimación mía a partir de datos propios; **[SV]** sin verificar.
- No se ha tocado código ni se ha ejecutado ningún experimento de calidad. Solo se hicieron lecturas del PC (formato del dispositivo, metadatos del ONNX, tokenizador, informe de la sesión real).

## 1. Resumen ejecutivo

1. **No hay datos que digan dónde se pierde el habla baja.** Solo hay hipótesis. La primera tarea es un «embudo» por etapa (cue de subtítulo, tramo del VAD, texto del ASR, unidad emitida, traducción aceptada, frase pronunciada) sobre clips grabados en crudo. Sin eso, cualquier ajuste es a ciegas.
2. **Hallazgo propio que cambia el diagnóstico:** el Nemotron exportado a sherpa-onnx tiene `normalize_type: ''` (sin normalización de características) [V, metadatos del `encoder.int8.onnx` local] y la configuración de NeMo lo dice expresamente («no normalization… makes streaming easier») [V]. El nivel absoluto entra directo en el log-mel. El AGC es, por tanto, parte del reconocedor y no un adorno: hay que probarlo con una curva de nivel (WER frente a ganancia).
3. **El AGC no puede mejorar la relación voz/música** y tiene una relajación de 1 s con recuperación lenta (de −10 a +25 dB tarda ~2 s en llegar a +20 dB) [V, cálculo sobre `agc.py`]. Tras una escena fuerte, un susurro pierde su primer segundo. Es una hipótesis fuerte y barata de comprobar.
4. **VAD:** Silero v6.2.3 sigue siendo razonable; la evidencia pública sobre habla susurrada o baja es nula. TEN VAD pierde en los datos de Silero y en los de FireRed (más falsas alarmas). FireRedVAD (Apache-2.0, ONNX de 2,3 MB, con variante que distingue habla, canto y música) es el único candidato que merece un banco de pruebas. Valores a barrer: umbral 0,5 a 0,25 con salida = umbral − 0,15, y una entrada «persistente» a umbral bajo.
5. **Realce previo al ASR:** la evidencia reciente (2025-2026) dice que empeora el WER con ASR modernos (Whisper, Parakeet) [V]. Con Nemotron no está medido. Solo vale la pena probar lo trivial (paso alto, ganancia solo en habla, centro/mid) y, como cota, DeepFilterNet3 con mezcla de la señal original. Esto es coherente con el ADR-0008.
6. **Canales:** el dispositivo por defecto de este PC (Logitech G733) expone **7.1 (máscara 0x63F, 8 canales, 48 kHz float)** [V, medido hoy]. La captura pide 16 kHz mono y es Windows quien mezcla a mono con una matriz que no está documentada [SV]. Hay que medirlo con la captura de 8 canales del spike S4 (`loopback_ctypes.py` ya admite `nchannels`).
7. **«Vosotros»:** hay fallos en tres frentes. El *prompt* actual aprendió «vosotros» con 12 ejemplos y un sistema que el modelo casi no usa (Hy-MT2 no tiene *system prompt* por defecto [V]); el modo CONCISE no lleva ni ejemplos ni mención de «vosotros»; y el contexto reinyecta las traducciones propias del modelo, errores incluidos.
8. **`logit_bias` solo sirve para el pronombre.** En el tokenizador de Hy-MT2, «ustedes» es `usted`+`es`, y «tomen», «síganme» o «vengan» se parten en trozos sin sentido (` to`+`men`). Y en llama.cpp una cadena como clave sesga **cada token** de la cadena (también `es`) [V en el código de master; b11146 sin verificar]. Las gramáticas GBNF no niegan cadenas de varios caracteres [V].
9. **Propuesta de mayor rendimiento para «vosotros»:** (a) corpus propio de ≥ 150 frases y detector medido; (b) prompt (turno de estilo, ejemplos dirigidos, contexto saneado); (c) **posedición por reglas con la señal del inglés** (imperativo sin sujeto o «you» sin «they»), que cuesta < 1 ms [E]; (d) reintento con el 7B solo para lo marcado (+0,2 a 0,35 s en esas frases, ~25–60 ms de media si se marca el 10–25 % [E]). Un segundo modelo pequeño no cabe en la VRAM (7B 5,2 GB + voz 3,8 GB + escritorio).
10. **Dato real de la sesión del humano** (informe `20261002-151737`): 632 palabras en 12,5 min (51 por minuto) y 24 de 95 unidades con ≤ 3 palabras (cortes como «am I», «right», «What's the»). No hay referencia, así que no prueba pérdida, pero es consistente con ella y con la fragmentación.

## 2. Tablas comparativas

### 2.1 Habla baja o alargada: dónde puede perderse y qué probar

| Etapa | Hipótesis | Evidencia | Coste de comprobarla | Prioridad |
|---|---|---|---|---|
| AGC | Relajación de 1 s y objetivo en el RMS de la mezcla: tras una escena fuerte el habla baja entra 13–35 dB por debajo de lo previsto durante ~1 s; la música constante fija la ganancia | Código de `agc.py` [V]; cálculo propio | Muy bajo (offline, sobre captura cruda) | Alta |
| ASR (nivel) | Nemotron sin normalización de características: nivel muy bajo o muy alto desplaza el log-mel; entrenado con habla de lectura y YouTube [V], sin música ni susurro documentados [V] | `normalize_type ''` local [V]; model card | Muy bajo (curva WER frente a ganancia) | Alta |
| VAD | Con habla susurrada (sin tono) o enmascarada por música, la probabilidad queda entre 0,35 y 0,5 y no abre | Sin datos públicos; v6.2 dice mejorar «muted speech» [V] | Bajo (volcar probabilidades y barrer umbrales offline) | Alta |
| ASR (voz) | Habla susurrada: WER mucho mayor (Whisper 18,8 % frente a 9,2 % de un WavLM afinado, en wTIMIT) [V]; sin cifras para Nemotron | arXiv 2407.21211 | Medio (EARS «whisper» y «slow») | Media |
| Segmentación o filtros posteriores | Tramos que el ASR sí transcribió pero que se descartan (vacíos, longitud, idioma, retraso) | Sesión real: 1 descartada, 0 rechazadas [V]; ASR no volcado | Bajo (embudo por etapa) | Alta |
| Mezcla de canales | La mezcla a mono de Windows atenúa el canal central en 5.1/7.1 | Dispositivo 7.1 [V]; matriz sin documentar [SV] | Bajo-medio (tonos por canal) | Media |

### 2.2 Alternativas de VAD (streaming, CPU)

| VAD | Licencia | Tamaño / ejecución | Datos publicados (todos del propio autor) | Notas para nosotros |
|---|---|---|---|---|
| **Silero VAD v6.2.3** (actual) | MIT | ~2 MB, ONNX, tramas de 32 ms | ROC-AUC 0,97 y exactitud 0,92 (v6) frente a 0,93 y 0,87 de TEN; ESC-50 0,87 (v5: 0,61) [V, wiki Quality-Metrics] | 6.2 mejora voces raras y «muted speech» [V]. En FLEURS-VAD-102: F1 95,95, falsas alarmas 9,41 %, pérdidas 3,95 % [V, tabla de FireRed] |
| **TEN VAD** | Apache-2.0 **con condiciones de Agora** (no competir con sus ofertas; solo para tu aplicación y tus usuarios) [V, LICENSE] | 306 KB, hop de 10 o 16 ms; DLL x64 en Windows [A] | FLEURS-VAD-102: F1 95,19, falsas alarmas 15,47 %, pérdidas 2,95 % [V, tabla de FireRed] | Menos pérdidas pero más falsas alarmas; sin dato de habla baja. Valida para uso personal. Poco probable que ayude con música |
| **FireRedVAD** (Stream-VAD y AED) | Apache-2.0 [V] | 0,57–0,59 M parámetros; ONNX de 2,3 MB con caché para streaming; entradas: fbank + CMVN global (`kaldi_native_fbank`) [V, repo]; v0.0.2 (beta), último *push* 2026-05-06 [V] | FLEURS-VAD-102: F1 97,57, falsas alarmas 2,69 %, pérdidas 3,62 % [V] | **La variante AED distingue habla, canto y música**, útil como puerta contra falsos positivos al bajar el umbral. Umbral de ejemplo 0,4, suavizado de 5 tramas, `min_speech_frame=8`. Sin datos de ruido, música ni habla baja |
| WebRTC VAD | BSD | trivial | F1 52,30 (FireRed) [V] | Descartado |

Los datos de FireRed y de Silero son de lectura de FLEURS, no de cine. No sirven para decidir: sirven para elegir qué llevar al banco de pruebas.

### 2.3 Realce o preproceso previo al ASR

| Técnica | Coste en CPU | Evidencia sobre WER | Riesgo | Veredicto provisional |
|---|---|---|---|---|
| Paso alto 80–100 Hz y ecualización de banda de voz | despreciable [E] | Sin evidencia específica | bajo | Probar (barato) |
| AGC solo con tramos de habla (ganancia congelada durante música) | despreciable | Sin evidencia específica | bajo | Probar (primera mejora al AGC) |
| Canal central (7.1/5.1) o mid (L+R) de estéreo | despreciable | Práctica común, **sin cifras de WER publicadas** que haya encontrado [SV] | depende de la mezcla | Probar; pide medir el flujo de canales |
| RNNoise o DeepFilterNet3 (dual MIT/Apache [A], 48 kHz, salto de 10 ms, ~40 ms de latencia algorítmica [A]) | bajo, en tiempo real en CPU [A] | Aplicado a ASR modernos **empeora**: MetricGAN+ con Whisper, Parakeet y otros, en las 40 configuraciones, +1,1 a +46,6 puntos absolutos de WER semántico (arXiv 2512.17562, 2025-12); SAM-Audio con Whisper en inglés 10,53 % a 21,66 % (arXiv 2603.04710, 2026-03) [V] | artefactos (Iwamoto et al. 2022: el componente de artefacto es la causa principal; mezclar parte de la señal original ayuda) [V] | Solo como cota, con mezcla de observación (señal realzada + α × original) |
| Separación pesada (HT-Demucs, Bandit v2, SAM-Audio) | alto (GPU o CPU lenta) | HT-Demucs empeoró a Whisper en canciones (WER 35,5 a 47,9 %) [V, informe previo] | VRAM, idioma | **Fuera de la ruta crítica** (ADR-0008). Solo como oráculo de «techo» offline |

### 2.4 «Vosotros»: técnicas

| Técnica | Cobertura | Coste en latencia | Riesgo | Veredicto provisional |
|---|---|---|---|---|
| Estilo en cada turno (plantilla oficial *Style*) en vez de en el sistema | General | ~0 (tokens del turno) [E] | Cambiar el formato de turno puede romper otras cosas | Probar en el 7B (en el 1,8B no tenía efecto) |
| Más ejemplos dirigidos (24–32), incluidos imperativos, «you» sin marca y negativos | Alta | ~0 al cachearse | Sobreajuste al corpus | Probar |
| Ejemplos dinámicos (2–3 por cue) tras el bloque fijo | Media-alta | +10–30 ms de *prefill* [E] | Rompe la caché solo de esos tokens | Probar |
| Sanear el contexto (aplicar la posedición a las traducciones previas) | Evita el autocebado | ~0 | Ninguno | **Hacer** si la posedición existe |
| Modo CONCISE con «vosotros» | Solo ese modo | ~0 | Cambia la plantilla medida en S2 | Medir: hoy no hay ninguna pista de variante |
| `logit_bias` | Solo el pronombre «usted(es)» (`usted` 61395, `usted` sin espacio 28244 y `sted` 24836); no los verbos | 0 | Sesgar `es` o `U` rompe otras palabras | Solo con tokens ids explícitos y solo como parte del reintento |
| Gramática GBNF | Ninguna práctica | Alto | No existe negación de cadenas [V] | Descartada |
| Posedición por reglas con la señal del inglés | Alta en imperativos y presente; cuidado con «su(s)», «les», «se» | < 1 ms [E] | 3.ª persona legítima del plural | **Núcleo de la propuesta** |
| Reintento con el 7B (mismo servidor) y marca de estilo, `n_cmpl` o sesgo | Solo lo marcado | +0,2 a 0,35 s por frase marcada [E] | Regresiones de sentido | Para el residuo |
| Segundo LLM pequeño | Alta | +0,1 a 0,25 s [E] | **No cabe en 12 GB** con 7B + TTS; en CPU, lento | No recomendado |
| Cambiar de modelo (TranslateGemma con `es-ES`; SalamandraTA-7B) | Depende | Depende | Licencia Gemma; Salamandra es GPL-3.0 (uso personal) [V] | Solo como métrica añadida en la comparativa de la spec 002 |
| LoRA sobre Hy-MT2-7B con datos sintéticos | Alta | 0 | Infraestructura de entrenamiento en 12 GB, Windows [SV] | Último recurso |

## 3. Detalle por opción

### 3.1 Habla baja, susurrada o alargada

#### 3.1.1 Lo que sabemos de la cadena actual
- **AGC** (`agc.py`) [V]:
  - objetivo de −20 dBFS de RMS por chunk de 20 ms, máximo +30 dB y mínimo −20 dB;
  - ataque de 50 ms (bajar) y relajación de 1 s (subir);
  - puerta en −60 dBFS (por debajo, la ganancia se congela);
  - mide el RMS de **la mezcla**, no de la voz.
  - Consecuencia: con música constante a −30 dBFS y un susurro a −38 dBFS, la ganancia queda en +10 dB y la relación voz/música no cambia. Con +30 dB de tope, el AGC solo puede llevar a −20 dBFS el habla que parta de −50 dBFS o más.
  - Recuperación tras una escena fuerte (g0 = −10 dB, deseada = +25 dB, τ = 1 s): g(t) = 25 − 35·e^(−t) da +3,8 dB a 0,5 s, +12,1 dB a 1 s y +20,3 dB a 2 s. El primer susurro tras una explosión llega 13 a 35 dB por debajo de lo que el AGC «quiere».
- **VAD** (`silero.py`) [V]: umbral 0,5 para abrir, 0,35 para cerrar (solo cuentan las tramas por debajo), 500 ms de silencio y 150 ms de relleno. No hay `min_speech_duration`: una sola trama de 32 ms ≥ 0,5 abre el tramo. Por tanto, el VAD solo pierde habla si la probabilidad **nunca** llega a 0,5 en ese tramo.
- **ASR** (modelo local, `encoder.int8.onnx`) [V]: `feat_dim` 128, `chunk_size_ms` 560, `subsampling_factor` 8, `normalize_type` vacío, es decir, sin normalización por frase ni por canal de características. En NeMo, las configuraciones de streaming usan `normalize: "NA"` («no normalization for mel-spectogram makes streaming easier») [V].
- **Datos de entrenamiento** del Nemotron (model card) [V]: 530 000 h (Riva 250 k, YouTube-Commons 109,5 k, YODAS2 102 k, LibriLight 49,5 k y otros); no se menciona habla susurrada ni música de fondo. WER por conjunto con trozos de 0,56 s: media 7,07 %, LibriSpeech clean 2,46 %, Earnings22 12,82 %; con 0,08 s de trozo sube a 8,43 %. La AMI (habla conversacional con solape) es de las peores (11,73 % a 1,12 s y 14,71 % a 0,16 s). No hay cifras con ruido o música.
- **Sesión real** (`informes/20261002-151737`) [V]: 632 palabras en 747,7 s (51 por minuto); 24 de 95 unidades con ≤ 3 palabras y 15 con ≤ 2; mediana de 6 palabras. Ejemplos de las más lentas: «am I», «right», «What's the». Sin `ustedes` (traducía el 1,8B). Para interpretar los 51 por minuto hace falta saber la densidad real de diálogo de esa escena: **no es prueba de pérdida**.

#### 3.1.2 VAD: valores y coste en falsos positivos
- Valores por defecto en las fuentes primarias:
  - Silero (`get_speech_timestamps`): umbral 0,5, `neg_threshold` por defecto = umbral − 0,15, `min_speech_duration_ms` 250, `min_silence_duration_ms` 100, `speech_pad_ms` 30 [V, `utils_vad.py` de `master`]. El proyecto ya usa 0,5/0,35, que coincide con la regla del −0,15.
  - faster-whisper (`VadOptions`): umbral 0,5, `min_silence` 2000 ms y `speech_pad` 400 ms [V].
  - El wiki de Silero dice que «para la mayoría de usos no hace falta ajustar» y recomienda dibujar las probabilidades y elegir `threshold`, `min_speech_duration_ms` y `min_silence_duration_ms` por conjunto de datos [V].
- **Para habla débil**, la bibliografía accesible es de segunda mano: guías de terceros recomiendan 0,3–0,4 [A, simplismart y whisper.rn]. Nadie publica la curva de falsos positivos en cine. La discusión nº 441 de Silero muestra el otro extremo: sonidos no verbales (toser, carraspear) disparan el VAD y usuarios subieron el umbral a 0,97–0,98 [V]. Hay literatura reciente sobre que Silero confunde canto con habla (arXiv 2512.09713, «Robust Speech Activity Detection in the Presence of Singing Voice») [V el título; las cifras de falsas alarmas por condición no pude verificarlas].
- **Coste previsible de bajar el umbral** [E]: más tramos de música y efectos pasan al ASR (inserciones, textos basura, traducciones de ruido) y, con música constante, los silencios no bajan de `neg_threshold`, así que los tramos no se cierran y la frase tarda más. Por eso conviene probar una entrada «persistente»: abrir con 0,5 como hoy y, además, abrir con un umbral bajo (0,3) solo si se mantiene ≥ 4 tramas seguidas (128 ms), con una media móvil de 3 tramas.
- **Silero v6.2** (2025-11-06): reentrenado, «muted voices / muted speech» entre los casos mejorados [V]. Ya se usa la 6.2.3 (2026-09-23). La 6.2.2 añadió un modelo ONNX «secuencia» fuera de línea (solo 16 kHz), que no es de streaming [V].

#### 3.1.3 Alternativas de VAD
Ver tabla 2.2. Resumen:
- **TEN VAD**: ventajas de latencia y tamaño; su licencia tiene condiciones (no competir con Agora, solo para tu propia aplicación). En la tabla de FireRed tiene menos pérdidas que Silero pero 6 puntos más de falsas alarmas; en el wiki de Silero (datos propios) pierde frente a v6 en ROC-AUC y exactitud. Sin datos de habla débil. Prioridad baja.
- **FireRedVAD**: ONNX sin torch (`fireredvad_stream_vad_with_cache.onnx`, 2,3 MB); necesita fbank de Kaldi (`kaldi_native_fbank`) y CMVN, o una implementación propia en NumPy (hay una de Rust como referencia) [V]. El AED de 3 clases (habla, canto, música) es el valor añadido para cine y juegos. Riesgos: v0.0.2 beta; el CMVN global hace que el nivel influya; sin cifras de música ni habla baja; latencia de streaming no documentada [V].
- **Silero con más contexto**: no hay otra palanca nativa. Se puede probar a alimentarlo con una copia con más ganancia que la del ASR (barato) o con la señal antes del AGC.

#### 3.1.4 ASR: susurro y palabras alargadas
- Susurro: en wTIMIT, Whisper tiene 18,8 % de WER frente a 9,22 % de un modelo WavLM afinado (arXiv 2407.21211) [V]; con ASR entrenados solo con voz normal, el WER con susurro puede superar el 100 % (resumen de búsqueda sobre arXiv 2311.05179 y trabajos afines; la cita exacta no se verificó) [SV]. La falta de tono (F0) y de excitación glotal es el factor principal [V]. **No hay cifras para Nemotron.**
- Alargadas: no hay fuente. En un transductor con 80 ms por trama del codificador, una vocal muy larga se emite como pocos tokens o ninguno; la consecuencia más probable es la pérdida de una palabra suelta o una repetición, no de la frase [E]. Hay que **medirlo** estirando con TDHS/WSOLA habla limpia (el proyecto ya usa `audiostretchy`) y con el estilo «slow» de EARS.
- Alternativa de referencia: faster-whisper `large-v3-turbo` en GPU (ya validada en el spike S3, WER 5,82 %, 2,3 GB de VRAM) [V, `research.md`]. Sirve de oráculo para separar «lo pierde el VAD o el ASR» de «el audio ya no tiene la voz».

#### 3.1.5 Realce de diálogo ligero
- La evidencia más reciente **va en contra** del realce previo con ASR modernos:
  - MetricGAN+ con Whisper, Parakeet, Gemini 2.0 Flash y otro: peor WER semántico en las 40 configuraciones (+1,1 a +46,6 puntos) [V, arXiv 2512.17562, 2025-12-19];
  - SAM-Audio con cinco variantes de Whisper: peor en todas las combinaciones modelo-conjunto (Whisper base en inglés 10,53 a 21,66 %; large-v3 en bengalí 65,83 a 77,35 %) [V, arXiv 2603.04710, 2026-03-05, revisado 2026-07-14];
  - Iwamoto et al. (Interspeech 2022): el culpable es el componente de artefacto del realce; mezclar de vuelta parte de la señal observada («observation adding») mejora el WER [V].
- Estos estudios usan ASR no streaming y entrenados con mucho ruido; **Nemotron está entrenado con datos más limpios** (YouTube, LibriLight, etc.) y podría comportarse distinto. Por eso hay que medirlo, no darlo por supuesto.
- Candidatos baratos que no son «separación»: paso alto, ganancia solo durante el habla, `mid`/centro. DeepFilterNet3 (MIT o Apache-2.0 [A], Windows y CPU [A], 48 kHz, salto de 10 ms) queda como cota con mezcla de observación (α ≈ 0,3–0,5).
- La separación pesada (HT-Demucs, Bandit v2) sigue fuera de la ruta crítica por lo que ya recoge el ADR-0008. Solo sirve offline como «techo» (¿cuánto ganaría un diálogo perfectamente limpio?).

#### 3.1.6 Canal central y mezcla en 5.1 o 7.1
- **Medido hoy:** el dispositivo de reproducción por defecto es «Altavoces (Logitech G733 Gaming Headset)», con formato de mezcla de **8 canales, 48 kHz, 32 bits, `WAVE_FORMAT_EXTENSIBLE`, máscara 0x63F** (FL, FR, FC, LFE, BL, BR, SL, SR = 7.1) [V, `GetMixFormat` del 2026-10-02]. En la validación se citó otro dispositivo (Samsung HDMI); no sabemos cuál tenía el humano en la sesión del 2026-10-02 («con auriculares»).
- **Qué pide hoy la captura:** 16 kHz mono float32 con `AUTOCONVERTPCM` (R2, spike S4); el dispositivo virtual de *process loopback* no tiene formato de mezcla, así que el formato lo fija el cliente y Windows convierte [V, `loopback_ctypes.py`]. El módulo ya admite `nchannels` y recae en 2 si falla.
- **Qué no sabemos** [SV]: con qué coeficientes mezcla Windows 7.1 o 5.1 a mono (¿el centro entra a −3 dB, a 0 dB, o se pierde?), si el mono es una media o una suma, y si la app origen entrega multicanal. Microsoft documenta el *process loopback* y sus parámetros (modo incluir o excluir, árbol de procesos, Windows 10 build 20348 o superior) pero no la matriz de conversión [V].
- **Qué dice la práctica**: el diálogo suele ir en el canal central, pero «no siempre» y «rara vez algo es tan limpio» (foros de mezcla) [A, nivel de anécdota]. Muchas apps (navegadores, Netflix en navegador) entregan estéreo aunque el dispositivo sea 7.1 [SV]; los juegos usan la configuración del altavoz.
- **Consecuencia para el experimento:** capturar 8 canales con el spike S4 y comparar los candidatos de mono: la mezcla de Windows, solo FC, FC + 0,7·(FL+FR), y `mid` en estéreo. Cuesta CPU casi nula.

### 3.2 Español de España y «vosotros»

#### 3.2.1 Lo que sabemos (spike S2, 1,8B; producción con el 7B)
- Con el *prompt* final del 1,8B: «vosotros» en 3 de 6 frases plurales, «ustedes» en 1–2 [V, README de S2]. La cláusula de estilo del sistema no movió nada; solo los ejemplos previos (6: 2 de 6; 12: 3 de 6) [V]. Con 7B no hay medición de variante: la medición completa del 7B quedó pendiente en S2 [V]. El humano y el orquestador vieron `ustedes`, `tomen`, `síganme`, `¿Están listos?` con el 7B [V, `validacion.md`].
- **Hy-MT2-7B no tiene *system prompt* por defecto** y sus plantillas oficiales (incluida *Style*) llevan la instrucción en el turno del usuario, antes del texto [V, model card]. Nuestro *prompt* pone el estilo en el mensaje de sistema, fuera de lo que se entrenó [E]. Parámetros recomendados: temperatura 0,7, top-p 0,6, top-k 20, penalización de repetición 1,05; no hay mención de variantes del español [V].
- **Cuatro debilidades del montaje actual** (lectura de `mt/hymt2.py`):
  1. De los 12 ejemplos fijos, ninguno es un «you» **sin marca** (la queja típica, «Are you ready?»); los plurales llevan «you guys», «you two», «all of you».
  2. El contexto (hasta 4 pares) reinyecta las **traducciones propias** del modelo como turnos del asistente: un «ustedes» previo cebará el siguiente.
  3. El modo CONCISE usa un único mensaje con estilo telegráfico, **sin ejemplos y sin «vosotros»** (`CONCISE_TEMPLATE`): sin ninguna pista de variante.
  4. El turno con glosario usa la plantilla china de terminología, distinta de la de los ejemplos: otro formato de turno que el modelo no ha visto con «vosotros».
- Las comprobaciones de `corpus.py` y `quality.py` usan expresiones regulares sobre solo 6 frases plurales, con `\bles\b|\bsus\b` como marca de «ustedes» (falsos positivos: «les» y «sus» valen para tercera persona). **Con n = 6 no se puede detectar una mejora**: hace falta un corpus mayor.

#### 3.2.2 `logit_bias` y gramáticas (llama.cpp)
- `llama-server` acepta `logit_bias` como `[[id, sesgo]]`, `{"id": sesgo}` o con una cadena como clave; `false` prohíbe el token [V, README del servidor y `server-schema.cpp` de `master`, 2026-10-02]. **Con una cadena, tokeniza y aplica el sesgo a cada token resultante**, no a la secuencia [V en el código de `master`; b11146 no se ha comprobado].
- Tokenización real con `llama-tokenize` sobre el GGUF del 7B Q4_K_M (b11146, solo vocabulario) [V, medido hoy]:

  | Texto | Tokens |
  |---|---|
  | ` ustedes` | ` usted`(61395) + `es`(288) |
  | `ustedes` | `usted`(28244) + `es`(288) |
  | `Ustedes` | `U`(52) + `sted`(24836) + `es`(288) |
  | ` Ustedes` | ` U`(549) + `sted`(24836) + `es`(288) |
  | ` tomen` | ` to`(311) + `men`(5794) |
  | ` síganme` | ` sí`(45815) + `gan`(30528) + `me`(2727) |
  | ` vengan` | ` v`(348) + `engan`(18763) |
  | ` miren` | ` m`(296) + `iren`(47435) |
  | ` están` / ` sean` / ` les` / ` sus` | un solo token cada uno |
  | ` vosotros` | ` vos`(26317) + `otros`(48145) |
  | ` estáis` | ` está`(15833) + `is`(285) |

  - Conclusión: se puede prohibir el pronombre con ids explícitos (61395, 28244 y quizá 24836 `sted`), pero **no los verbos** (` to`+`men`), y sesgar `es` rompería casi todo.
  - Un sesgo positivo a «vosotros» o a `os` es demasiado burdo, y ` vos` es también el voseo.
  - Prohibir el pronombre hace que el modelo lo omita («¿Están listos?»), no que cambie a 2.ª persona: **no resuelve** el caso principal.
- **GBNF**: solo admite negación de rangos de caracteres y de **tokens**, no de cadenas de varios caracteres, y avisa de que `!"palabra"` no existe [V, `grammars/README.md`]. Descartada como técnica práctica.
- **Sin cadenas prohibidas ni retroceso** en el servidor (no hay `banned_strings` ni *antislop* en la documentación consultada) [V].

#### 3.2.3 Prompting
- **Instrucción al final / formato del turno:** la plantilla oficial *Style* (`Please translate the following text into Spanish. Note that the translation style must strictly conform to [style]:` + texto) pone la instrucción **delante** del texto, no detrás. «Al final» no está validado por el fabricante; hay que medirlo [SV]. En S2 todas las variantes de estilo se probaron con el 1,8B y sin efecto; con el 7B no.
- **Más ejemplos / ejemplos dirigidos:** única palanca que movió los números en S2 (0/4/2 a 3/1/2). Propuesta: 24–32 ejemplos fijos (cacheables) con las clases del fallo: imperativos afirmativos y negativos, «you» sin marca en preguntas, «let me know», «come on», «guys»; y 2–3 ejemplos dinámicos elegidos por cue (imperativo, pregunta con «you», negativo) justo tras el bloque fijo y antes del contexto.
- **Coste de *prefill* del 7B** [E, de `research.md` R7]: 211/347 ms (p50/p95) con caché y 344/497 sin ella para un *prompt* de ~830 tokens, es decir, ~0,16 ms por token no cacheado. 3 ejemplos dinámicos de ~60 tokens suman ~30 ms.
- **Contexto saneado:** aplicar la posedición (3.2.4) a las traducciones que se reinyectan como contexto. Es gratis y corta el autocebado.
- **Estilo en el modo CONCISE:** añadir «Peninsular Spanish, informal plural = vosotros» a la plantilla telegráfica o 2–3 ejemplos, y medirlo, porque en S2 los ejemplos anulaban la concisión del 7B.

#### 3.2.4 Posedición por reglas
Lo que hay que convertir (español de España, informal):
- **Pronombre y posesivo:** `ustedes` a `vosotros`; `sus` a `vuestros/as` y `les` a `os` **solo si** el referente es el oyente; son ambiguos con 3.ª persona.
- **Imperativo:** el imperativo afirmativo de ustedes (` tomen`) viene de la forma de subjuntivo; el de vosotros se forma con el infinitivo (`tomar` a `tomad`, `comer` a `comed`, `vivir` a `vivid`). Con irregulares: `vayan` a `id`, `sean` a `sed`, `digan` a `decid`, `hagan` a `haced`, `pongan` a `poned`, `vengan` a `venid`, `salgan` a `salid`, `tengan` a `tened`, `vean` a `ved`, `den` a `dad`. Con enclíticos: `síganme` a `seguidme`, `dénselo` a `dádselo`, `siéntense` a `sentaos`, `váyanse` a `idos`. En negativo se usa el subjuntivo: `no tomen` a `no toméis`.
- **Otros tiempos** (3.ª a 2.ª plural): presente (`están` a `estáis`, `tienen` a `tenéis`, `quieren` a `queréis`, `pueden` a `podéis`, `piden` a `pedís`); pretérito (`tomaron` a `tomasteis`, `fueron` a `fuisteis`); imperfecto (`tomaban` a `tomabais`); futuro (`harán` a `haréis`); condicional; subjuntivo.
- Necesita un léxico de formas. Opciones:
  - un volcado de Wiktionary (kaikki.org, CC BY-SA) con etiquetas de persona y tiempo [SV, tamaño y calidad sin comprobar];
  - `mlconjug3` 4.0.1 (MIT; el conjugador es un modelo aprendido, así que hay que comprobar sus irregulares) [V la licencia];
  - spaCy 3.8.16 (MIT) con `es_core_news_*` (**GPL-3.0**, por AnCora) para los rasgos `Person`, `Number`, `Mood`; vale para uso personal pero se anota [V].
- **La ambigüedad real:** un verbo en 3.ª persona del plural no dice si habla del oyente. Señales para decidir:
  - **Señal del inglés**, más fiable que el español: el original en imperativo (frase que empieza por verbo base, «Don't», «Let me»…) con el español empezando por una forma en `-en`/`-an` es siempre el oyente; si el original tiene «you», «your», «guys», «y'all», «everyone» y **no** tiene «they», «them», «their» ni un sujeto plural, el verbo en 3.ª persona del plural es del oyente.
  - **Señal en el español:** `ustedes` explícito, enclíticos de imperativo, `no` + subjuntivo.
  - Los casos dudosos (original con «they» y «you» a la vez) se dejan sin tocar o se reintentan con el LLM.
- Tratamiento singular: los fallos de S2 incluyen «Póngalo», «Apague», «Denme». El singular formal convierte a tú (`póngalo` a `ponlo`, `apague` a `apaga`, con los irregulares `di`, `haz`, `ve`, `pon`, `sal`, `sé`, `ten`, `ven`). Conviene un ajuste de usuario `tratamiento: informal | formal | auto` para no estropear escenas con «usted» legítimo (policía, médico, realeza).
- **Coste:** < 1 ms por frase (diccionario en memoria) [E]. **No hay una fuente publicada** que evalúe este tipo de conversión de LatAm a peninsular que haya encontrado [SV]; la propuesta se apoya en gramática y en medir.

#### 3.2.5 Segundo paso con un LLM
- **Mismo servidor, mismo modelo** (7B): una petición corta («Rewrite for Spain Spanish: informal plural = vosotros, singular = tú»), solo para frases marcadas. Latencia ≈ la de una traducción del 7B: 0,2 a 0,35 s (p50/p95 211/347 ms con caché) [E, R7]. En S2 el 7B hizo bien el *two_step* de acortar (−32 %), a 703 ms en total, pero el 1,8B tradujo al inglés en 6 de 30 salidas [V]: el 7B es viable, el 1,8B no.
- **Regenerar en lugar de reescribir:** repetir la traducción con una marca explícita en el turno, `logit_bias` para `usted(es)`, y, en `master`, `n_cmpl` > 1 (el *prompt* se procesa una vez y los hijos se activan después) con `-np` ≥ n [V en `server-context.cpp` de `master`; b11146 y la VRAM extra de KV: SV]. Elegir la primera que pase el detector. El servidor actual se lanza con `-np 1`.
- **Segundo modelo pequeño (Qwen, Gemma, Hy-MT2-1.8B):** descartado por VRAM: 7B Q4_K_M 5,2 GB + voz 3,8 GB + escritorio ~3,2 GB [V, ADR-0008 y R7/R8] ya deja poco margen, y la reserva automática al 1,8B existe precisamente por esto.

#### 3.2.6 Latencia: balance
| Pieza | Coste por frase | Se aplica a |
|---|---|---|
| Posedición por reglas | < 1 ms [E] | todas |
| Detector (regex) | < 1 ms [E] | todas |
| Ejemplos fijos extra | ~0 (caché) | todas |
| Ejemplos dinámicos | +10–30 ms [E] | todas |
| Reintento con el 7B | +0,2–0,35 s [E] | frases marcadas (fracción f) |
| Media con f = 10 / 25 % | +25 / +60 ms [E] | |

El presupuesto de retardo medido en la sesión real (p50 1,16 s y p95 3,57 s con un objetivo de ≤ 3 s y ≤ 5 s) absorbe el reintento en la cola, pero el reintento compite por la misma GPU que la voz (RTF de 0,45 a 0,67 con la GPU compartida) [V, `validacion.md`].

## 4. Recomendación para InstantTraductor

### 4.1 Habla baja o alargada

**Principal:** diagnosticar antes de cambiar. Cinco experimentos en este orden (A0 a A5). Cambiar la configuración de producción solo con datos.

**Alternativas** (si A0 muestra que el ASR no pierde nada y el problema está aguas abajo): ajustar filtros de salida y segmentación. Si A0 muestra que la pérdida es del audio (voz enmascarada), la mejora es `mid`/centro o aceptar el límite.

**Por qué ese orden:**
- A0 y A1 son offline sobre una captura cruda y casi sin coste de máquina.
- El resultado de A2 (curva de nivel) separa «el ASR no entiende lo bajo» de «el AGC no sube».
- Realce y VAD alternativos solo tienen sentido si A0 localiza la pérdida.

### 4.2 «Vosotros»

**Principal:** corpus y detector (B0), prompt (B1), posedición por reglas con señal del inglés (B3) y reintento con el 7B para el residuo (B2), con el contexto saneado. Aplicar el tratamiento con un ajuste de usuario.

**Alternativas:**
- Si el 7B con los cambios del prompt ya baja el fallo por debajo del 5 %, no hace falta posedición.
- Si la posedición tiene más del 1 % de conversiones dañinas, limitarla a pronombre explícito e imperativo con original imperativo.
- Cambiar de modelo (TranslateGemma `es-ES`, SalamandraTA) como métrica añadida de la comparativa de la spec 002, no como solución de esta spec.

**Por qué:** ninguna técnica de decodificación puede forzar la persona gramatical con este tokenizador. La señal más fiable (el inglés) está disponible en el proceso; el LLM solo se usa en el residuo.

## 5. Propuesta priorizada de experimentos

Todos son **spikes** que no cambian la producción. Ejecución con un obrero por bloque; los que tocan GPU, de uno en uno con el candado `gpu.lock`.

### 5.0 Corpus propio (base de A y B)

**Corpus C1: clips reales grabados en crudo.**
- 30–40 clips de 60–120 s (~1 h) de series, películas y juegos del humano, repartidos en: diálogo normal, susurros, escenas con música alta, efectos, voces alargadas, solapes. Uso personal, fuera del repo (`%LOCALAPPDATA%`).
- Grabación con un modo de volcado de la **captura cruda** (16 kHz mono antes del AGC) y, para el experimento de canales, 8 canales. Con la captura cruda se repite todo offline y de forma determinista.
- Referencia: subtítulos oficiales (SRT) revisados en una muestra de 15 min por una persona; cada cue tiene tiempos (±0,3 s) y texto. Etiquetas por cue: nivel de la voz (RMS de la ventana en dBFS), presencia de música y estilo (normal, baja, susurro, alargada).
- Dependencia: el humano elige los clips (criterio personal) y revisa la muestra.

**Corpus C2: sintético controlado.**
- LibriSpeech test-clean (CC BY 4.0; ya en el proyecto) con ganancias de −10 a −45 dB, y mezcla con música de MUSAN (CC BY 4.0 [V], 11 GB) a SNR +10, +5, 0 y −5 dB; con ruido.
- EARS (CC-NC 4.0 [V]; 107 hablantes, estilos *regular, loud, whisper, high pitch, low pitch, fast, slow*) para susurro y habla lenta.
- Alargadas: estirar sílabas o palabras con TDHS o WSOLA a ×1,5 y ×2,5.
- Nota de licencias: EARS es no comercial (vale para uso personal; se anota). El resultado de C2 es reproducible.

### 5.1 Habla baja

| Id | Qué se mide y cómo | Entrada | Criterio propuesto (a confirmar con A0) | Esfuerzo |
|---|---|---|---|---|
| **A0** Embudo | Por cada cue de C1: ¿hay tramo del VAD que lo solape ≥ 50 %?, ¿texto no vacío del ASR?, ¿unidad emitida?, ¿traducción aceptada?, ¿pronunciada? Más los volcados de probabilidad de Silero y de ganancia del AGC. Informa pérdidas por etapa y por nivel/estilo | C1 crudo | Decidir qué etapa explica ≥ 70 % de las pérdidas | 1–1,5 días |
| **A0b** Oráculo | Mismo C1 con faster-whisper `large-v3-turbo` sin VAD y con el mismo VAD. Si el oráculo recupera lo perdido, el fallo es del VAD o de Nemotron; si no, es del audio | C1 | — | 0,5 día |
| **A2** Curva de nivel | WER del Nemotron (560 ms) en C2 con ganancias de −45 a +10 dB **sin AGC**, y luego con AGC; con y sin música. Resultado: la curva de sensibilidad al nivel y la ganancia del AGC | C2 | Detecta un hueco de ≥ 3 puntos absolutos de WER en el rango de −30 a −45 dB | 0,5 día |
| **A1** Barrido del VAD | Con las probabilidades volcadas una sola vez, calcular offline: umbral {0,5, 0,4, 0,35, 0,3, 0,25}; salida = umbral − 0,15 y − 0,10; silencio 500/700 ms; entrada persistente (0,3 durante ≥ 4 tramas); media móvil de 3 tramas. Métricas: recall por cue, segundos de falso positivo por hora en clips solo de música y efectos, retardo de cierre (p50/p95), nº de unidades por minuto | C1, C2 | Mejora del recall de «baja» ≥ 15 puntos con ≤ 2× los falsos positivos de hoy (propuesta mía) y sin subir el p95 del retardo de cierre más de 0,3 s | 0,5 día |
| **A3** AGC | Variantes sobre captura cruda: relajación 0,3/0,6/1 s; ganancia solo durante habla del VAD; objetivo −16/−20/−23 dBFS; paso alto 80 Hz; ganancia con límite según SNR. Métrica: WER por nivel y recall | C1, C2 | Mejora de WER relativo ≥ 5 % en el intervalo bajo sin empeorar el limpio más de 0,5 puntos absolutos | 1 día |
| **A4** VAD alternativos | TEN VAD y FireRedVAD (Stream-VAD y AED como puerta de música) frente a Silero, a igual falsa alarma: recall, retardo, CPU, y la combinación «Silero a umbral bajo y AED no-música» | C1, C2 | Recall +10 puntos a igual falsos positivos, ≤ 0,05 núcleos extra | 1–1,5 días |
| **A5** Canales | Con el spike S4 (`nchannels` = 8 y 1): (1) tonos por canal en un fichero 7.1 y en uno estéreo (VLC o mpv, y un navegador): qué atenuación sufre cada canal en el mono de Windows; (2) en C1 con contenido 5.1/7.1, comparar WER de: mono de Windows, solo FC, FC + 0,7·(FL+FR), y `mid` en estéreo | C1 (8 canales), tonos | Decide si merece la pena capturar multicanal y hacer la mezcla propia | 1 día |
| **A6** Realce | WER con y sin: DeepFilterNet3, y mezcla de observación (α 0,3 y 0,5), en C1/C2 con **Nemotron**. Cota con Bandit v2 (offline) | C1, C2 | Solo adoptar si el WER relativo mejora ≥ 5 % en el intervalo difícil y no empeora el limpio más de 0,5 puntos | 1 día |
| **A7** Susurro y alargadas | EARS *whisper*, *slow*, *fast*; palabras estiradas. WER y borrados (D/N) frente al habla normal con Nemotron; con `large-v3-turbo` de comparación | C2 | Cuantifica; sin umbral | 0,5 día |

Pruebas de que lo anterior no empeora lo demás (regresión): WER en LibriSpeech (593,8 s ya medidos: 5,05 %), falsos positivos por hora en música sola, retardo p50/p95 y CPU.

### 5.2 «Vosotros»

| Id | Qué se mide y cómo | Entrada | Criterio propuesto | Esfuerzo |
|---|---|---|---|---|
| **B0** Línea base del 7B | Corpus nuevo de ≥ 150 frases en inglés (nuevas, sin tocar las de S2): imperativos (afirmativos y negativos), «you» sin marca en preguntas, «you guys/all/two», singular informal, y 20 formales legítimos (control). Mezclar escenas para llevar contexto. Etiquetar cada salida con un detector (pronombre `ustedes`/`usted`, 3.ª persona del plural dirigida, imperativos 3.ª persona, `vosotros` correcto, tú, neutral) y comprobar con una persona 100 de ellas. Informar tasas con IC de Wilson (±8 puntos con n = 150) en NORMAL y en CONCISE, con contexto crudo y contexto saneado, con 3 semillas | 7B Q4_K_M | Línea base y precisión/recall del detector (≥ 95 % de precisión) | 1 día |
| **B1** Prompt | Variantes, una a una, sobre B0: (a) estilo en cada turno (*Style* oficial) en vez de en el sistema; (b) instrucción al final del turno; (c) 24–32 ejemplos fijos (imperativos, «you» sin marca); (d) 2–3 dinámicos por cue; (e) CONCISE con «vosotros» o con 2–3 ejemplos; (f) contexto saneado. Métrica: tasa de fallo, errores de sentido (revisión a ciegas de 50 frases), latencia p50/p95, tokens | B0 | Fallo < 5 % sin regresiones de sentido | 1–1,5 días |
| **B3** Posedición por reglas | Implementar el conversor sobre un léxico de formas (Wiktionary/kaikki o `mlconjug3`) con la señal del inglés; evaluar sobre B0 y sobre 100 conversiones reales revisadas por una persona: precisión, daño (cambios de sentido), cobertura (qué fracción de fallos se arregla), latencia | B0, salidas de B1 | Precisión ≥ 95 %, daño ≤ 1 %, cobertura ≥ 70 % de lo marcado, < 1 ms | 2 días |
| **B2** Reintento | Sobre los fallos que queden tras B1+B3: regenerar con (i) marca de estilo en el turno, (ii) `logit_bias` de `usted` con ids explícitos, (iii) `n_cmpl` = 3 y elegir con el detector. Latencia p50/p95 añadida, fracción f, regresiones. Comprobar antes con una petición real el comportamiento de `logit_bias` por cadena en b11146 | 7B | Corrige ≥ 80 % del residuo con ≤ +0,35 s | 1 día |
| **B4** Segundo paso con LLM | Petición de reescritura corta al 7B solo para lo marcado: tasa de arreglo, regresiones, latencia. Alternativa a B2 si `n_cmpl` no va con `-np 1` | 7B | Como B2 | 0,5 día |
| **B5** Otros modelos | Añadir la tasa de «vosotros» (corpus B0) a la comparativa de la spec 002: TranslateGemma con `es-ES`, SalamandraTA-7B (GPL-3.0), EuroLLM, Qwen3.5 | corpus B0 | Informativo | incluido |

### 5.3 Orden de ejecución propuesto

1. **Semana 1:** C1 (grabación cruda), A0, A0b, A2, B0.
2. **Semana 2:** A1, A3, B1, B3.
3. **Semana 3:** A4, A5 (canales), B2/B4, A6, A7.
4. Cada experimento acaba con una recomendación para el plan de la spec 002 y, si cambia una decisión de arquitectura (p. ej. captura multicanal), un ADR.

## 6. Riesgos y preguntas abiertas

**Habla baja**
- **Sin datos de pérdida.** Todo lo de §3.1 son hipótesis; solo el AGC, el formato del ASR y el dispositivo son hechos medidos.
- **Sesgo de la referencia.** Los subtítulos no son una transcripción literal (omiten muletillas, resumen), y la cobertura no es del 100 %: la referencia debe revisarse en una muestra.
- **Pregunta al humano:** ¿qué dispositivo de salida usa de ordinario (G733 en 7.1, Samsung HDMI u otro)? ¿qué apps (navegador, reproductor, juegos)? ¿qué ejemplos concretos de «alargada» (interjecciones, voces de personajes) quiere traducir? ¿Cuánto vale una frase de interjección (p. ej., «Nooo») frente a una falsa inserción?
- **Fragmentación.** 25 % de las unidades de la sesión real tienen ≤ 3 palabras: puede deberse tanto al VAD con música como a la segmentación. Es otra causa posible de «no se traduce» (la traducción de un trozo suelto sale mal o se descarta).
- **Licencias:** TEN VAD (Apache-2.0 con condiciones de Agora; uso personal vale), EARS (CC-NC; uso personal), `es_core_news_*` de spaCy (GPL-3.0), SalamandraTA (GPL-3.0), Gemma (licencia propia). Todo ello se anotaría en el ADR si se adopta.
- **Dependencias nuevas** (FireRedVAD: `kaldi_native_fbank`; DeepFilterNet; spaCy) chocan con el principio de pocas dependencias y con las ruedas de Windows/Python 3.12: sin comprobar.
- **Windows 11 y la matriz de mezcla:** no documentada; puede cambiar con actualizaciones o con el software del auricular (G HUB).
- **Contención de GPU:** cualquier reintento del 7B compite con la voz.

**«Vosotros»**
- **Falsos positivos de la posedición:** una 3.ª persona legítima convertida por error es peor que un «ustedes». Por eso se propone medir daño y limitar al subconjunto de alta precisión.
- **Registro formal legítimo** (usted en policía, médicos, realeza, doblajes de época): hace falta el ajuste `tratamiento` y, tal vez, una señal del título («Sir», «Your Honor», «Ma'am»).
- **`logit_bias` en b11146** y **`n_cmpl` con `-np 1`:** sin comprobar; se verificó el comportamiento en el código de `master`.
- **Corpus de S2 sobreajustado:** el *prompt* final se eligió mirando las mismas 65 frases; por eso B0 pide frases nuevas.
- **Voseo rioplatense** («Respondeme») apareció en S2: también conviene detectarlo (formas en `-á/-é/-í` con acento final de 2.ª persona).
- **Japonés y chino:** el *prompt* no se ha probado con esos orígenes; el «tú/vosotros» depende más del contexto en ellos.
- **Pregunta al humano:** ¿el tratamiento por defecto debe ser siempre informal (tú/vosotros) en España? ¿quiere el ajuste por título?

## 7. Fuentes (consultadas el 2026-10-02)

Primarias (repositorios, tarjetas de modelo, documentación, código):
- Silero VAD, repositorio y releases: https://github.com/snakers4/silero-vad (releases por la API de GitHub: v6.0 2025-08-26, v6.1 2025-11-05, v6.2 2025-11-06, v6.2.1 2026-02-24, v6.2.2 2026-09-17, v6.2.3 2026-09-23).
- Silero VAD, `utils_vad.py` (valores por defecto de `get_speech_timestamps`): https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/utils_vad.py
- Silero VAD, wiki de calidad: https://github.com/snakers4/silero-vad/wiki/Quality-Metrics ; FAQ: https://github.com/snakers4/silero-vad/wiki/FAQ ; discusión nº 441: https://github.com/snakers4/silero-vad/discussions/441
- faster-whisper, `VadOptions`: https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/vad.py
- TEN VAD: https://github.com/TEN-framework/ten-vad ; licencia: https://raw.githubusercontent.com/TEN-framework/ten-vad/main/LICENSE ; https://huggingface.co/TEN-framework/ten-vad
- FireRedVAD: https://github.com/FireRedTeam/FireRedVAD (ONNX en `pretrained_models/onnx_models`, `requirements.txt`, `pyproject.toml` v0.0.2) ; https://huggingface.co/FireRedTeam/FireRedVAD
- NVIDIA Nemotron Speech Streaming EN 0.6B: https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b
- NeMo, configuración de streaming (`normalize: "NA"`): https://raw.githubusercontent.com/NVIDIA/NeMo/main/examples/asr/conf/fastconformer/cache_aware_streaming/fastconformer_transducer_bpe_streaming.yaml
- Metadatos del ONNX local: `%LOCALAPPDATA%\InstantTraductor\models\nemotron-en\encoder.int8.onnx` (medido hoy).
- Hy-MT2-7B (tarjeta): https://huggingface.co/tencent/Hy-MT2-7B
- llama.cpp, servidor: https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md ; `server-schema.cpp` (`logit_bias`, `n_cmpl`) y `server-context.cpp`: https://github.com/ggml-org/llama.cpp/tree/master/tools/server ; GBNF: https://raw.githubusercontent.com/ggml-org/llama.cpp/master/grammars/README.md
- Tokenizador de Hy-MT2-7B Q4_K_M medido con `llama-tokenize.exe` de b11146 (local, 2026-10-02).
- TranslateGemma: https://huggingface.co/google/translategemma-4b-it ; SalamandraTA-7B: https://huggingface.co/BSC-LT/salamandraTA-7b-instruct
- Microsoft, loopback y *process loopback*: https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording ; https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params
- PyPI (licencias y versiones): `mlconjug3` 4.0.1 (MIT), `spacy` 3.8.16 (MIT), `verbecc` 2.0.3 (LGPL), `simplemma` 2.0.0 (MIT), `stanza` 1.15.0 (Apache-2.0); metadatos de `es_core_news_md-3.8.0` (GPL-3.0): https://raw.githubusercontent.com/explosion/spacy-models/master/meta/es_core_news_md-3.8.0.json
- EARS: https://github.com/facebookresearch/ears_dataset ; arXiv 2406.06185
- MUSAN: https://www.openslr.org/17/
- AVA-Speech (referencia de corpus de cine): arXiv 1808.00606.

Artículos:
- Whispered ASR: arXiv 2407.21211 (WavLM frente a Whisper, wTIMIT) ; arXiv 2311.05179 (aumentación pseudo-susurro).
- Realce y ASR: arXiv 2512.17562 (2025-12-19) ; arXiv 2603.04710 (2026-03-05, rev. 2026-07-14) ; arXiv 2201.06685 (Iwamoto et al., Interspeech 2022).
- Silero y canto: arXiv 2512.09713 (solo el resumen).
- Silero, tamaño de ventana: arXiv 2601.17270 (solo el resumen).
- DnR (separación en cine): arXiv 2407.07275.

Secundarias (nivel de anécdota; se citan como tales):
- Guías de ajuste de umbrales: https://docs.simplismart.ai/troubleshooting-faq/vad-parameter-tuning ; https://micdrop.dev/docs/client/vad
- Foros de mezcla 5.1 a estéreo (FFmpeg-user 2022-08, VideoHelp, Hydrogenaudio): el diálogo «suele ir al centro pero no siempre».

Documentos del proyecto citados:
- `specs/001-espina-dorsal/research.md`, `specs/001-espina-dorsal/validacion.md`, `spikes/traduccion/README.md`, `spikes/traduccion/corpus.py`, `spikes/traduccion/quality.py`, `src/instanttraductor/audio/agc.py`, `src/instanttraductor/vad/silero.py`, `src/instanttraductor/mt/hymt2.py`, `docs/adr/0008-voz-y-clonacion.md`, `docs/investigacion/2026-09-30-aislamiento-y-clonacion.md`, informe de sesión `%LOCALAPPDATA%\InstantTraductor\informes\20261002-151737`.
