# T040 (2.ª vuelta): voces femeninas castellanas nuevas (diseñadas y de estudio)

Spike de investigación de la feature `001-espina-dorsal`. No es código de producto. Fecha de todas las consultas y mediciones: 2026-10-01.

**Por qué:** el humano escuchó las 4 lectoras de LibriVox de la 1.ª vuelta (`docs/investigacion/2026-10-01-voces-castellanas.md`) y las rechazó:
«tienen una voz terrible, no anima a escucharlas más de 10 segundos». Pide **voz femenina joven, suave, con buena entonación, en español de España**.
La app clona la voz de una referencia de 6 a 10 s con Qwen3-TTS-0.6B Base + `faster-qwen3-tts` (modo ICL con `ref_text`), y el acento de la referencia se contagia a todo lo que dice.

**Convenciones.** «**Δ(s−θ)**» es el indicio de acento de `spikes/voz/common/distincion.py`: diferencia en dB entre la fuerza de la /s/ y la de la /θ/ (palabras con «ce, ci, z»), ambas relativas a la vocal
más fuerte de la palabra. Referencias del spike S1: control peninsular 15,5 dB; seseo argentino 1,8 dB. Un Δ grande indica **distinción** (español de España); es un indicio, no una prueba.
«**F0**» es la frecuencia fundamental mediana (autocorrelación, tramas de 40 ms) y «**rango**» es la diferencia entre los percentiles 10 y 90 de la F0 en semitonos (mide cuánto sube y baja la voz: expresividad).
Las voces adultas femeninas suelen estar entre 165 y 255 Hz (referencia general, sin verificar en fuente primaria). **No puedo oír el audio**: timbre, juventud, suavidad, naturalidad y artefactos los decide el oído del humano.
Los tiempos de generación de este spike (RTF, primer audio) se midieron con la CPU ocupada por Whisper y no sirven como cifras de rendimiento; valen las del spike S1.

## Resumen

1. **Hay muestras para escuchar** en `%LOCALAPPDATA%\InstantTraductor\spikes\voces-v2\`: 5 voces de estudio (`es-f-est-01` a `05`), 8 voces diseñadas con Qwen3-TTS-VoiceDesign (`es-f-dis-01` a `08`; de la `05` solo hay versión `th`), 6 diseñadas con VoxCPM2 (`es-f-dvx-NN`: `01`, `02`, `04`, `05`, `06`, `08`)
   y 2 controles. Para cada una, la referencia (`<id>_ref.wav`, con su `ref_text` en `<id>_ref.json`) y las mismas 4 frases sintetizadas por el motor de producción (`<id>_frase1.wav` a `<id>_frase4.wav`):
   diálogo natural, pregunta, exclamación y una frase con «vosotros», «ordenador», «móvil» y «vale». Ninguna frase salió rota (WER por candidata de 0,00 a 0,10).
2. **El acento lo decide la referencia, y el motor de producción lo conserva.** Con referencias de estudio, el acento de España pasa a lo generado: Δ de 10,5 a 17,1 dB en las 5 de estudio y de 12,4 a 16,5 dB en los 2 controles
   (las LibriVox que el humano rechazó por la voz, no por el acento). También pasa en modo x-vector (`es-f-est-02-xv`: 16,4 dB).
3. **Camino A (voces diseñadas): viable, y solo VoxCPM2 da distinción.** `Qwen3-TTS-VoiceDesign` 1.7B (Apache-2.0, español, 4,5-4,6 GiB de VRAM de torch) funciona con el entorno del spike S1 y da timbres muy distintos con WER ≈ 0, pero
   las 7 voces con referencia normal dan Δ de -4,0 a 2,2 dB (seseo, como el control argentino) con 7 formulaciones de la descripción (§1.2). `VoxCPM2` (Apache-2.0, 5,5 GiB de pico), con la descripción entera en español,
   **sí da distinción**: las 6 voces `es-f-dvx-NN` dan Δ de 11,7 a 18,6 dB con el motor de producción (§1.3, §5.3), aunque en más de la mitad de las tomas sale con voz de hombre. Reescribir z/ce/ci con «th» en Qwen3 (§5.2) es un truco experimental.
4. **Camino B (grabaciones humanas): VoxPopuli `es` (CC0)** da hablantes femeninas con distinción medida y micrófono de sala parlamentaria; OpenSLR SLR61 solo trae 90 mensajes del tiempo peninsulares (una mujer, a 48 kHz). Common Voice, MediaSpeech, TEDx y los de LibriVox quedan descartados (§2).
5. **Orden recomendado** (preselección con medidas; manda el oído; §6): 1) `es-f-dvx-08` y 2) `es-f-dvx-01` (diseñadas con VoxCPM2, con distinción medida y sin voz humana), 3) `es-f-est-04` y 4) `es-f-est-01` (voces humanas de VoxPopuli, CC0).
6. **Límites:** nada está escuchado; «joven», «suave» y «buena entonación» son aquí F0, rango de F0 y ritmo; las 4 frases dan de 6 a 13 palabras con /θ/ medibles por candidata (§7).

## 1. Camino A: voces diseñadas a partir de una descripción

### 1.1 Qué modelos permiten diseñar una voz

| Modelo | Licencia | Idiomas | Diseñar voz | Tamaño / VRAM medida | ¿Funciona en el entorno del spike S1? |
|---|---|---|---|---|---|
| `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` | Apache-2.0 (sin cuenta, `gated=False`) | 10, entre ellos **español** (sin dialectos del español documentados) | **Sí**: `generate_voice_design(text, language, instruct)` | 4,52 GB en disco; **torch asignado 4 562–4 665 MiB** (reservado 5 042–5 186; NVML +5,4 GB con el contexto CUDA); RTF 0,50–0,58 con CUDA graphs | **Sí**, tal cual: `faster-qwen3-tts` 0.5.3 trae `generate_voice_design`; entorno de `spikes/voz/qwen3` sin tocar su `pyproject`. `engines/tts-qwen3` fija exactamente las mismas versiones (`faster-qwen3-tts==0.5.3`, `transformers==5.15.1`, `torch==2.11.0`), así que valdría igual |
| `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` y `0.6B-CustomVoice` | Apache-2.0 | 10 (incluye español) | **No**: 9 timbres prefabricados (Vivian, Serena, Uncle_Fu, Dylan, Eric, Ryan, Aiden, Ono_Anna, Sohee); solo se controla el estilo con `instruct` (en la 1.7B) | 0,6B: del orden del Base | No se probó: ninguno de los 9 es hablante nativo de español (chino, inglés, japonés, coreano), así que cabe esperar acento extranjero |
| `Qwen/Qwen3-TTS-12Hz-0.6B-VoiceDesign` | No existe | | | | La familia publicada es: 1.7B-VoiceDesign, 1.7B-CustomVoice, 1.7B-Base, 0.6B-CustomVoice y 0.6B-Base (README de `QwenLM/Qwen3-TTS`) |
| `openbmb/VoxCPM2` (otro modelo abierto) | Apache-2.0 | 30, entre ellos español (sin acentos regionales documentados) | **Sí**: la descripción va entre paréntesis delante del texto, «(A young woman, gentle and sweet voice)...» | 2B parámetros, ~8 GB de VRAM según su ficha; salida a 48 kHz | Entorno propio (pide `Python < 3.13`, `torch >= 2.5`, `funasr`, `gradio`, `modelscope`...); la ficha no dice nada de Windows |

El flujo oficial del README de Qwen3-TTS («Voice Design then Clone») es el que se usa aquí: VoiceDesign genera una **referencia corta** con la voz descrita y esa
referencia, con su texto exacto (`ref_text`), es la que clona después el motor de producción (Qwen3-TTS-0.6B Base + `faster-qwen3-tts`, ICL).
VoiceDesign solo hace falta **al crear la voz** (herramienta de autoría, ~5 GB de VRAM puntuales); el servicio de voz en producción no lo carga.

### 1.2 Resultado clave: VoiceDesign no distingue /θ/ de /s/ por mucho que se le pida

Se generó 2 veces cada variante con la **misma** voz base y la misma frase, densa en palabras con z/ce/ci (9 con /θ/ y 3 con /s/ por toma), y se midió Δ(s−θ). La columna «Whisper» cuenta solo las palabras
que Whisper escribió bien (las que se escriben con ce/ci/z): si Whisper oye una /θ/ como /t/ o /d/, la palabra desaparece de esa cuenta.

| Forma de pedir el acento (instrucción de VoiceDesign) | Δ(s−θ) sobre el texto pedido | Δ(s−θ) solo con lo que Whisper escribió bien |
|---|---|---|
| sin mencionar acento | -0,2 dB (n 18/6) | -0,2 dB (n 18) |
| «castellano estándar de Madrid, “th” para z y c» (EN) | 1,3 dB (n 18/6) | 1,3 dB (n 18) |
| «nacida en España, NO latinoamericana, con distinción… sin seseo» (EN) | 0,1 dB (n 18/6) | 0,1 dB (n 18) |
| «actriz de doblaje de España, castellano neutro del doblaje» (EN) | 0,2 dB (n 18/6) | 0,2 dB (n 18) |
| lo mismo que «fuerte», descrito en español | 1,7 dB (n 18/6) | 1,7 dB (n 18) |
| «actriz de doblaje y locutora profesional de España» (ES) | -0,5 dB (n 18/6) | -0,5 dB (n 18) |
| «ceceo castellano: z/ce/ci suenan como la “th” inglesa» (EN) | 0,8 dB (n 18/6) | 0,8 dB (n 18) |
| descripción «base» + texto con z/ce/ci reescritos con «th» | 9,1 dB (n 14/6) | 9,1 dB (n 8) |
| descripción «fuerte» + texto con «th» | 19,1 dB (n 11/6) | 20,1 dB (n 9) |
| descripción «base» + texto con el símbolo «θ» | 13,2 dB (n 9/6) | 13,2 dB (n 11) |

Las 7 primeras filas quedan en la zona del seseo (≈ 0-2 dB, el control argentino da 1,8): **las voces diseñadas con una descripción hablan sin distinción**, aunque se les pida lo contrario de seis maneras. Whisper las transcribe sin ningún
error (WER 0), así que no están rotas: simplemente pronuncian z/ce/ci como /s/. Con las 7 voces diseñadas con referencia normal (apartado 3; 4 frases con 13 palabras con /θ/ cada una) el resultado es el mismo: Δ de -4,0 a 2,2 dB.

**Truco probado: reescribir z/ce/ci con «th» en el texto que se envía** (`Hace cinco días` → `Hathe thinco días`): el modelo lee «th» con la /θ/ inglesa y el indicio sube. Es un indicio medido **sin oír**: puede sonar a «th» inglesa y
no a /θ/ castellana, y Whisper confunde parte de ellas con /t/ o /d/ («Detilia», «dinar»; WER de 0,14 a 0,45). El símbolo «θ» da más errores de transcripción (WER de 0,23 a 0,45: a veces el modelo lo dice como «zeta» o se lo come). Cómo se comporta cuando esa reescritura se aplica a la referencia
o a las frases del motor de producción está en el apartado 5.

### 1.3 Camino A2: VoxCPM2 sí da distinción, pero a ratos con voz de hombre

`openbmb/VoxCPM2` (Apache-2.0, 30 idiomas con español, descripción de voz entre paréntesis delante del texto) es un segundo modelo abierto de diseño de voz. Entorno propio (`spikes/voces/voxcpm`: `torch` 2.11.0+cu130 del mismo índice,
`transformers` 4.57.6, y `override-dependencies` para no instalar `gradio`, `funasr`, `modelscope`, `datasets`, `spaces`, `matplotlib` ni `torchcodec`, que solo hacen falta para su interfaz y su ASR chino); modelo en `models\voxcpm2`.
Carga en 19-27 s, **VRAM de torch 4,9 GiB en reposo y 5,5 GiB de pico** (5 064 y 5 586 MiB; NVML +6,2 GB), salida a 48 kHz (se baja a 24 kHz); es lento (RTF ≈ 2,7 sin `torch.compile` y con la CPU ocupada), pero solo es herramienta de autoría.
`generate()` de la 2.0.3 publicada en PyPI no admite `seed=` (se fija con `torch.manual_seed`).

- **Sonda de acento** (misma frase y misma voz base que §1.2; 2 tomas por variante): descripción en inglés, Δ de 0,8 a 1,6 dB (seseo, igual que Qwen3); **descripción entera en español** con «pronuncia la z y ce/ci con la zeta interdental /θ/, distinta de la s, sin seseo»: **12,0 dB** (n 14/6, WER 0).
- **8 voces × 3 tomas** con esa descripción en español (los mismos 8 timbres de `disenos.py`, traducidos): muchas tomas dan Δ de 12 a 22 dB, pero **17 de las 24 salieron con F0 por debajo de 170 Hz (108-160 Hz, rango de voz de hombre)** aunque la descripción decía «Mujer de N años» (un segundo estimador, YIN, da lo mismo o hasta un 15 % más, así que son graves de verdad y no un error de octava: `comprobar_f0.py`);
  las voces «grave y aterciopelada» (`03`) y «ligera, aireada y sonriente» (`07`) no dieron ninguna toma femenina. Una 2.ª pasada (otros 24 takes, textos de 28-29 palabras para llegar a 8-10 s, y la cláusula «voz femenina aguda de mujer joven, no de hombre») subió las tomas con F0 ≥ 170 Hz de 7 a 13 de 24.
- Se eligió por voz la toma con F0 ≥ 170 Hz, WER ≤ 0,05, 6-10,6 s y mayor Δ: salen 6 referencias `es-f-dvx-NN` (`03` y `07` sin ninguna toma femenina). Su Δ en lo generado por el motor de producción: `01` 18,6 dB (17,5 con la sonda), `02` 11,9 dB (11,0 con la sonda), `04` 11,7 dB (18,6 con la sonda), `05` 13,5 dB (14,4 con la sonda), `06` 14,3 dB (13,0 con la sonda), `08` 17,5 dB (16,2 con la sonda).
  Dos de ellas son cortas (`02`: 6,2 s; `08`: 7,8 s, por encima del mínimo de 6 s del contrato).


## 2. Camino B: grabaciones humanas de estudio con licencia abierta

| Corpus | Licencia | Veredicto |
|---|---|---|
| **OpenSLR SLR61** (`openslr.org/61`) | CC BY-SA 4.0 (Google) | Es sobre todo un corpus de **español argentino** (5 739 grabaciones de voluntarios en Buenos Aires); lo peninsular son solo **90 mensajes del tiempo** («Hay diecisiete grados y está nublado») de 3 hablantes, **una mujer** (03397, F0 229 Hz, grabada a 48 kHz) y dos hombres (122 y 129 Hz). Sirve como control de estudio, pero con una prosodia de locutor de avisos y un texto repetitivo |
| **VoxPopuli `es`** (`facebook/voxpopuli`, sesiones plenarias del Parlamento Europeo) | CC0 para los datos (ficha de Hugging Face y README de Meta); audio original del Parlamento Europeo, reutilización citando la fuente | **Elegido.** Sin cuenta (`gated=False`), con id de hablante y sexo: 115 hablantes en validación y test, 40 mujeres. Micrófono de sala parlamentaria (SNR 27–37 dB), 16 kHz |
| Mozilla Common Voice `es` | CC0 | Descartado: ya no se descarga sin cuenta (el repositorio `mozilla-foundation/common_voice_17_0` de Hugging Face solo tiene 2 ficheros) y la calidad es de micrófonos de usuario |
| MediaSpeech `es` (`ymoslem/MediaSpeech`) | CC BY-4.0 | Descartado: 10 h de vídeos de noticias de YouTube **sin id de hablante ni sexo** y de procedencia no indicada; no permite elegir una voz concreta |
| TEDx Spanish (SLR67) | CC BY-NC-ND 4.0 | Descartado: «NC» y «ND» impiden reutilizarlo |
| M-AILABS, CSS10, MLS, CML-TTS | (LibriVox) | Descartados por el brief: son los lectores aficionados que se quiere evitar |
| AhoSyn female ES (Aholab) | sin verificar | Descartado: voz de estudio a 48 kHz de la UPV/EHU, pero no he podido comprobar que sea de descarga libre con licencia CC |
| Vasco, catalán y gallego (SLR76, SLR69, SLR77) | CC BY-SA 4.0 | Descartados: son grabaciones en esas lenguas, no en español |

Los scripts de esta vuelta están en esta carpeta (ver «Estructura» al final); el audio está fuera del repo en `%LOCALAPPDATA%\InstantTraductor\spikes\voces-v2\`.

## 3. Referencias generadas o extraídas

Todas son WAV mono de 24 kHz con RMS −20 dBFS (pico ≤ −1 dBFS) y fundidos de 30 ms, en `%LOCALAPPDATA%\InstantTraductor\spikes\voces-v2\<id>_ref.wav`, con su `<id>_ref.json`
(campos de `VoiceInfo` del contrato de voz más `ref_text`, duración, origen y métricas). `exportar_voz.py` deja una candidata lista para instalar (solo los campos del contrato) en `...\voces-v2\listas\`.

- **Diseñadas con Qwen3 (`es-f-dis-NN`, 8 voces):** `Qwen3-TTS-12Hz-1.7B-VoiceDesign` con una descripción en inglés (edad 22-30, un timbre distinto en cada una, origen castellano pedido: Madrid, Valladolid, Toledo,
  Salamanca, Burgos, Zaragoza, Segovia) y un texto castellano de 21-23 palabras. De 2 tomas por voz se escribe la que Whisper large-v3-turbo transcribe sin ninguna diferencia (WER 0) y cae en 7,8-10,6 s; el `ref_text`
  es exactamente el texto generado. `es-f-dis-NNth` es la misma voz con la reescritura «th» del apartado 1.2 (solo se conserva una toma si cumple duración y WER ≤ 0,20; son experimentales y dos pasan de 10 s: `03th` 10,2 s y `04th` 10,6 s).
  `es-f-dis-05` no tiene versión normal porque ninguna de sus 2 tomas pasó el filtro de duración y WER.
- **Diseñadas con VoxCPM2 (`es-f-dvx-NN`, 6 voces):** los mismos 8 timbres de `disenos.py` descritos en español, con «hablante nativa de castellano de <ciudad>, España, … zeta interdental /θ/ … sin seseo» y, en la 2.ª pasada,
  «voz femenina aguda de mujer joven, no de hombre». De 48 tomas (2 pasadas × 8 voces × 3) se elige por voz la de F0 ≥ 170 Hz, WER ≤ 0,05, de 6 a 10,6 s y mayor Δ; `03` y `07` no dieron ninguna toma de mujer y no tienen referencia.
  El `ref_text` es el texto, sin la descripción. Duran de 6,2 a 9,4 s (`02`: 6,2 s y `08`: 7,8 s; el contrato pide de 6 a 10 s).
- **De estudio (`es-f-est-NN`, 5 voces):** 4 hablantes de VoxPopuli `es` (CC0) y la hablante peninsular de SLR61. De VoxPopuli se cribaron las 14 hablantes con más material (4 segmentos de 12-28 s por hablante,
  Whisper large-v3-turbo con tiempos por palabra, `distincion.py`, F0 y suelo de ruido): 11 de las 14 distinguen /θ/ de /s/ (Δ de 9,7 a 20,4 dB) y las otras tres no (0,7; −3,0 y 6,5 dB, descartadas). De las 11 se eligieron 4 con
  distinción medida (p < 0,05), SNR de 29 a 37 dB y F0 de 202 a 262 Hz, y de cada una un tramo de 9-10 s entre pausas reales; el `ref_text` es la transcripción de Whisper del propio recorte, que coincide con el
  `raw_text` del corpus (96-100 % de las palabras alineadas). `es-f-est-05` une 4 mensajes del tiempo de la locutora 03397 de SLR61 (texto del TSV del corpus, que escribe «dieciseis» sin tilde).
- **Controles (`es-f-ctrl-*`):** las dos LibriVox de la 1.ª vuelta con mejor distinción medida (juanina y Mongope). **No son candidatas** (el humano ya las rechazó): sirven para comprobar si el acento de la referencia
  pasa a lo que sintetiza el motor.

| id | duración | F0 mediana | ref_text (exacto) | origen |
|---|---|---|---|---|
| `es-f-ctrl-juanina` | - s | - Hz | «Paquita bajó los ojos, y haciendo un esfuerzo consiguió ponerse colorada como un tomate. La madre arrugó el entrecejo.» | LibriVox (dominio público); ver docs/investigacion/2026-10-01-voces-castellanas.md |
| `es-f-ctrl-mongope` | - s | - Hz | «Helena se posaba en su asiento solemne y fría, henchida de desdén, como una diosa llevada por el destino.» | LibriVox (dominio público); ver docs/investigacion/2026-10-01-voces-castellanas.md |
| `es-f-dis-01` | 9,9 s | 238 Hz | «Cuando llegué a la estación, el tren ya se había marchado. Entonces me senté, respiré hondo y decidí esperar con calma al siguiente.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-01_en_normal_t1.wav`, semilla 3130 |
| `es-f-dis-01th` | 9,4 s | 219 Hz | «Cuando llegué a la estación, el tren ya se había marchado. Entonces me senté, respiré hondo y decidí esperar con calma al siguiente.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-01_en_th_t2.wav`, semilla 2127 |
| `es-f-dis-02` | 8,0 s | 386 Hz | «¡Qué maravilla de día! Hace un sol precioso y el cielo está despejado. ¿Por qué no salimos a dar un paseo?» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-02_en_normal_t2.wav`, semilla 3231 |
| `es-f-dis-03` | 8,8 s | 215 Hz | «A veces pienso que lo mejor de la vida son las cosas sencillas: un café caliente, una conversación tranquila y nada de prisa.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-03_en_normal_t2.wav`, semilla 3331 |
| `es-f-dis-03th` | 10,2 s | 188 Hz | «A veces pienso que lo mejor de la vida son las cosas sencillas: un café caliente, una conversación tranquila y nada de prisa.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-03_en_th_t1.wav`, semilla 2326 |
| `es-f-dis-04` | 8,5 s | 306 Hz | «Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-04_en_normal_t2.wav`, semilla 3431 |
| `es-f-dis-04th` | 10,6 s | 182 Hz | «Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-04_en_th_t1.wav`, semilla 2426 |
| `es-f-dis-05th` | 8,4 s | 236 Hz | «Cuando llegué a la estación, el tren ya se había marchado. Entonces me senté, respiré hondo y decidí esperar con calma al siguiente.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-05_en_th_t1.wav`, semilla 2526 |
| `es-f-dis-06` | 8,0 s | 212 Hz | «¡Qué maravilla de día! Hace un sol precioso y el cielo está despejado. ¿Por qué no salimos a dar un paseo?» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-06_en_normal_t2.wav`, semilla 3631 |
| `es-f-dis-06th` | 9,0 s | 305 Hz | «¡Qué maravilla de día! Hace un sol precioso y el cielo está despejado. ¿Por qué no salimos a dar un paseo?» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-06_en_th_t2.wav`, semilla 2627 |
| `es-f-dis-07` | 9,3 s | 282 Hz | «A veces pienso que lo mejor de la vida son las cosas sencillas: un café caliente, una conversación tranquila y nada de prisa.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-07_en_normal_t2.wav`, semilla 3731 |
| `es-f-dis-07th` | 9,1 s | 265 Hz | «A veces pienso que lo mejor de la vida son las cosas sencillas: un café caliente, una conversación tranquila y nada de prisa.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-07_en_th_t2.wav`, semilla 2727 |
| `es-f-dis-08` | 8,1 s | 271 Hz | «Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-08_en_normal_t2.wav`, semilla 3831 |
| `es-f-dis-08th` | 8,5 s | 198 Hz | «Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-08_en_th_t2.wav`, semilla 2827 |
| `es-f-dvx-01` | 9,4 s | 233 Hz | «Cuando llegué a la estación, el tren ya se había marchado. Entonces me senté, respiré hondo y decidí esperar con calma al siguiente, mirando cómo caía la lluvia.» | Diseñada con VoxCPM2 (openbmb/VoxCPM2) (Apache-2.0); descripción: (Mujer de 25 años, voz suave y cálida de tono medio, amable y cercana, entonación natural y expresiva con una melodía marcada, dicción clara, ritmo pausado y natural; voz femenina aguda de mujer joven, no de hombre; hablante nativa de castellano de Madrid, España, con acento peninsular: pronuncia la z y ce/ci con la zeta interdental /θ/, distinta de la s, sin seseo) |
| `es-f-dvx-02` | 6,2 s | 208 Hz | «¡Qué maravilla de día! Hace un sol precioso y el cielo está despejado. ¿Por qué no salimos a dar un paseo?» | Diseñada con VoxCPM2 (openbmb/VoxCPM2) (Apache-2.0); descripción: (Mujer de 22 años, voz algo más aguda, brillante y dulce, juvenil y alegre con un tono sonriente, entonación viva y expresiva, dicción nítida; hablante nativa de castellano de Valladolid, España, con acento peninsular: pronuncia la z y ce/ci con la zeta interdental /θ/, distinta de la s, sin seseo) |
| `es-f-dvx-04` | 9,3 s | 204 Hz | «Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida y con tanta seguridad.» | Diseñada con VoxCPM2 (openbmb/VoxCPM2) (Apache-2.0); descripción: (Mujer de 24 años, voz suave, aireada y delicada, tierna, algo baja de volumen pero perfectamente clara, entonación natural y expresiva, ritmo relajado; voz femenina aguda de mujer joven, no de hombre; hablante nativa de castellano de Salamanca, España, con acento peninsular: pronuncia la z y ce/ci con la zeta interdental /θ/, distinta de la s, sin seseo) |
| `es-f-dvx-05` | 9,1 s | 198 Hz | «Cuando llegué a la estación, el tren ya se había marchado. Entonces me senté, respiré hondo y decidí esperar con calma al siguiente, mirando cómo caía la lluvia.» | Diseñada con VoxCPM2 (openbmb/VoxCPM2) (Apache-2.0); descripción: (Mujer de 27 años, voz clara, articulada y cálida de tono medio, como una locutora de radio cercana, segura y atractiva, entonación expresiva con variación natural del tono, dicción muy clara; voz femenina aguda de mujer joven, no de hombre; hablante nativa de castellano de Burgos, España, con acento peninsular: pronuncia la z y ce/ci con la zeta interdental /θ/, distinta de la s, sin seseo) |
| `es-f-dvx-06` | 8,8 s | 171 Hz | «¡Qué maravilla de día! Hace un sol precioso y el cielo está despejado. ¿Por qué no salimos a dar un paseo antes de que empiece a hacer demasiado calor?» | Diseñada con VoxCPM2 (openbmb/VoxCPM2) (Apache-2.0); descripción: (Mujer de 26 años, voz cálida y algo ronca con un toque ahumado, tono conversacional relajado y amistoso, tono medio-grave, entonación natural y expresiva, dicción clara; voz femenina aguda de mujer joven, no de hombre; hablante nativa de castellano de Madrid, España, con acento peninsular: pronuncia la z y ce/ci con la zeta interdental /θ/, distinta de la s, sin seseo) |
| `es-f-dvx-08` | 7,8 s | 211 Hz | «Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida y con tanta seguridad.» | Diseñada con VoxCPM2 (openbmb/VoxCPM2) (Apache-2.0); descripción: (Mujer de 30 años, voz serena, tranquilizadora y cálida de tono medio, ritmo constante y sin prisa, tono suave y amable, entonación natural y expresiva, dicción muy clara; voz femenina aguda de mujer joven, no de hombre; hablante nativa de castellano de Segovia, España, con acento peninsular: pronuncia la z y ce/ci con la zeta interdental /θ/, distinta de la s, sin seseo) |
| `es-f-est-01` | 9,2 s | 201 Hz | «Fue este Parlamento el que lo aprobó y lo negoció con el Consejo, con una gran colaboración con la Comisión.» | voxpopuli: 20170405-0900-PLENARY-14-es_20170405-18:01:16_6 0.0-9.04 s; hablante 28390 |
| `es-f-est-02` | 9,2 s | 222 Hz | «Gracias, presidenta. He apoyado este informe porque va a mejorar la calidad de los productos alimenticios y también va a contribuir al consumo informado y responsable.» | voxpopuli: 20110706-0900-PLENARY-6-es_20110706-14:02:19_0 2.58-11.6 s; hablante 96922 |
| `es-f-est-03` | 9,2 s | 231 Hz | «una directiva que viene a reconocer nuevos derechos a aquellas mujeres que ejercen una actividad autónoma y a los cónyuges o parejas, de hecho, colaboradores.» | voxpopuli: 20100615-0900-PLENARY-14-es_20100615-21:30:17_25 4.28-13.3 s; hablante 103035 |
| `es-f-est-04` | 10,0 s | 216 Hz | «Tengan ustedes la tranquilidad, que podemos decir alto y claro que en Copenhague la Unión Europea no ha sido el problema.» | voxpopuli: 20100120-0900-PLENARY-10-es_20100120-17:48:45_11 2.8-12.68 s; hablante 101146 |
| `es-f-est-05` | 9,6 s | 236 Hz | «Hay dieciocho grados con sol. Hay once grados y llueve. Hay diecinueve grados y está nublado. Hay dieciseis grados y está nublado.» | slr61: mensajes esw_03397_01452159553, esw_03397_00254676062, esw_03397_01417960131, esw_0; hablante 03397 |

**Criba de hablantes femeninas de VoxPopuli** (4 segmentos de 12-28 s por hablante; Δ con pocas palabras con /θ/ es un cribado, no una prueba):

| hablante | material criba | F0 mediana | rango F0 p10–p90 | suelo de ruido / SNR | palabras/s | Δ(s−θ) (n θ / n s, p) | elegida |
|---|---|---|---|---|---|---|---|
| 111496 | 53 s | 204 Hz | 5,5 st | -48 dB / 30 dB | 2,44 | 20,4 dB (n 1 / 10) |  |
| 28390 | 46 s | 202 Hz | 6,8 st | -57 dB / 37 dB | 2,23 | 16,1 dB (n 6 / 8, p < 0,001) | sí |
| 135491 | 54 s | 222 Hz | 8,1 st | -50 dB / 27 dB | 2,58 | 15,7 dB (n 1 / 10) |  |
| 111019 | 46 s | 195 Hz | 6,8 st | -45 dB / 27 dB | 2,89 | 14,8 dB (n 3 / 16, p = 0,002) |  |
| 96922 | 48 s | 222 Hz | 7,5 st | -47 dB / 31 dB | 2,70 | 14,7 dB (n 4 / 8, p = 0,004) | sí |
| 22418 | 52 s | 191 Hz | 5,1 st | -50 dB / 32 dB | 2,86 | 13,9 dB (n 5 / 10, p < 0,001) |  |
| 101146 | 53 s | 228 Hz | 8,4 st | -43 dB / 29 dB | 2,23 | 12,9 dB (n 4 / 6, p = 0,010) | sí |
| 101417 | 51 s | 201 Hz | 6,5 st | -58 dB / 31 dB | 2,51 | 12,5 dB (n 3 / 8, p = 0,085) |  |
| 103035 | 53 s | 262 Hz | 6,9 st | -43 dB / 30 dB | 2,75 | 11,9 dB (n 5 / 12, p < 0,001) | sí |
| 97024 | 53 s | 227 Hz | 4,4 st | -55 dB / 31 dB | 2,70 | 10,0 dB (n 3 / 8, p = 0,012) |  |
| 111017 | 54 s | 228 Hz | 5,9 st | -52 dB / 32 dB | 2,26 | 9,7 dB (n 2 / 15) |  |
| 28326 | 45 s | 241 Hz | 5,5 st | -43 dB / 28 dB | 2,82 | 6,5 dB (n 2 / 9) |  |
| 124708 | 50 s | 224 Hz | 6,9 st | -59 dB / 37 dB | 1,79 | 0,7 dB (n 5 / 8, p = 0,524) |  |
| 101148 | 55 s | 246 Hz | 6,8 st | -46 dB / 30 dB | 2,42 | -3,0 dB (n 4 / 5, p = 0,413) |  |

Atribución de las de estudio: VoxPopuli (Wang et al., ACL 2021, https://aclanthology.org/2021.acl-long.80), datos CC0; el audio es de las sesiones plenarias del Parlamento Europeo
(reutilización citando la fuente, aviso legal https://www.europarl.europa.eu/legal-notice/es/); SLR61: «Copyright 2018, 2019 Google, Inc.», CC BY-SA 4.0, https://openslr.org/61/ (Guevara-Rukoz et al., LREC 2020).
**Una voz clonada es la voz de una persona real**: las de estudio son eurodiputadas identificables por el id de la sesión; no he valorado jurídicamente el uso (valoración mía, sin verificar).

## 4. Muestras y medidas

Todo en `%LOCALAPPDATA%\InstantTraductor\spikes\voces-v2\` (WAV PCM16 mono de 24 kHz, sin reproducir por los altavoces): `<id>_ref.wav` (la referencia que se clona), `<id>_frase1.wav` a `<id>_frase4.wav`
(las 4 frases) y `<id>_sonda.wav` (una frase extra, densa en z/ce/ci y s, solo para tener más palabras en el indicio de acento). Las 4 frases son las mismas para todas y llevan 13 palabras con /θ/ (con la alineación de Whisper cuentan de 6 a 13 por candidata):

1. **diálogo natural:** «Pues mira, la verdad es que no tenía ganas de hacer nada, así que me quedé en casa y pedí una pizza para cenar con Sara.»
2. **pregunta:** «¿Qué te parece si el sábado vamos a cenar al centro y luego nos tomamos una cerveza en la plaza?»
3. **exclamación:** «¡Venga, date prisa, que son las doce y cinco y todavía no hemos salido de casa!»
4. **«vosotros» y léxico de España:** «Vale, vosotros decidid: o apagáis ya el ordenador, o cogéis el móvil y llamáis a Sara, que yo cierro a las cinco.»

Generadas con el motor de producción: Qwen3-TTS-12Hz-0.6B-Base + `faster-qwen3-tts` 0.5.3, modo ICL con el `ref_text` de la referencia, `language="Spanish"`, `chunk_size=4`, 0,5 s de silencio al final de la referencia contra el
«phoneme bleeding» y una semilla fija por frase (4243 a 4246), con las funciones `preparar_prompt` y `una_peticion` del spike S1 (el servicio de T025 todavía no está en la rama; las porta). Medidas con Whisper large-v3-turbo en CPU:
**WER** de lo generado contra el texto pedido, **F0** mediana y rango p10-p90 en semitonos (medias de las 4 frases) y **Δ(s−θ)** con las palabras de las 4 frases juntas (entre paréntesis, n de palabras con /θ/ y con /s/ y p de Mann-Whitney);
«con la frase de sonda» suma la frase extra (n mayor). Ninguna frase salió rota (criterio: WER > 0,25, duración fuera de 0,45x-2x de lo esperado o recortes); los niveles quedan entre −24 y −18 dBFS de RMS (solo `es-f-dis-02` es 4 dB más baja).

| id | camino | descripción | licencia | indicio de acento Δ(s−θ) | F0 mediana / rango p10–p90 | duración 4 frases | observaciones |
|---|---|---|---|---|---|---|---|
| `es-f-ctrl-juanina` | control (LibriVox) | Control: juanina (LibriVox 19250), «La gente cursi», cap. IV | Dominio público (declaración general de LibriVox) | **12,4** dB (n 13/10, p < 0,001)<br>con la frase de sonda: 12,7 dB (n 20/13, p < 0,001) | 187 Hz / 9,8 st | 28 s | WER medio 0,00 |
| `es-f-ctrl-mongope` | control (LibriVox) | Control: Mongope (LibriVox 10246), «Abel Sánchez», cap. II | Dominio público (declaración general de LibriVox) | **16,5** dB (n 11/10, p < 0,001)<br>con la frase de sonda: 17,0 dB (n 20/13, p < 0,001) | 178 Hz / 7,2 st | 29 s | WER medio 0,00 |
| `es-f-dis-01` | A (diseñada, Qwen3) | Lucía: tono medio, suave y cálida; origen pedido: Madrid | Apache-2.0 (modelo); sin voz humana | **0,9** dB (n 13/10, p = 0,687)<br>con la frase de sonda: 2,0 dB (n 22/13, p = 0,213) | 244 Hz / 11,2 st | 26 s | WER medio 0,00 |
| `es-f-dis-02` | A (diseñada, Qwen3) | Paula: algo aguda, brillante y dulce, alegre; origen pedido: Valladolid | Apache-2.0 (modelo); sin voz humana | **-4,0** dB (n 13/10, p = 0,204)<br>con la frase de sonda: -3,9 dB (n 22/13, p = 0,028) | 340 Hz / 9,3 st | 25 s | WER medio 0,00 |
| `es-f-dis-03` | A (diseñada, Qwen3) | Marta: grave, aterciopelada, serena; origen pedido: Toledo | Apache-2.0 (modelo); sin voz humana | **2,2** dB (n 13/10, p = 0,145)<br>con la frase de sonda: 4,2 dB (n 22/13, p = 0,010) | 211 Hz / 9,4 st | 28 s | WER medio 0,00 |
| `es-f-dis-04` | A (diseñada, Qwen3) | Elena: susurrante, tierna y delicada; origen pedido: Salamanca | Apache-2.0 (modelo); sin voz humana | **0,0** dB (n 13/10, p = 0,780)<br>con la frase de sonda: 0,3 dB (n 22/13, p = 0,597) | 294 Hz / 7,8 st | 28 s | WER medio 0,00 |
| `es-f-dis-06` | A (diseñada, Qwen3) | Irene: cálida, algo ronca, conversacional; origen pedido: Madrid | Apache-2.0 (modelo); sin voz humana | **0,9** dB (n 13/10, p = 0,114)<br>con la frase de sonda: 1,8 dB (n 22/13, p = 0,025) | 202 Hz / 8,0 st | 24 s | WER medio 0,00 |
| `es-f-dis-07` | A (diseñada, Qwen3) | Sofía: ligera, aireada, sonriente; origen pedido: Zaragoza | Apache-2.0 (modelo); sin voz humana | **0,8** dB (n 13/10, p = 0,642)<br>con la frase de sonda: 0,3 dB (n 22/13, p = 0,597) | 289 Hz / 9,2 st | 27 s | WER medio 0,00 |
| `es-f-dis-08` | A (diseñada, Qwen3) | Clara: serena, tranquilizadora, ritmo constante; origen pedido: Segovia | Apache-2.0 (modelo); sin voz humana | **0,8** dB (n 13/10, p = 0,780)<br>con la frase de sonda: 1,1 dB (n 22/13, p = 0,366) | 267 Hz / 9,9 st | 26 s | WER medio 0,00 |
| `es-f-dvx-01` | A2 (diseñada, VoxCPM2) | Lucía: tono medio, suave y cálida; origen pedido: Madrid (descripción en español, VoxCPM2) | Apache-2.0 (modelo); sin voz humana | **18,6** dB (n 6/10, p < 0,001)<br>con la frase de sonda: 17,5 dB (n 14/13, p < 0,001) | 239 Hz / 12,7 st | 22 s | WER medio 0,00 |
| `es-f-dvx-02` | A2 (diseñada, VoxCPM2) | Paula: algo aguda, brillante y dulce, alegre; origen pedido: Valladolid (descripción en español, VoxCPM2) | Apache-2.0 (modelo); sin voz humana | **11,9** dB (n 7/10, p = 0,003)<br>con la frase de sonda: 11,0 dB (n 11/13, p = 0,005) | 214 Hz / 7,8 st | 21 s | WER medio 0,00 |
| `es-f-dvx-04` | A2 (diseñada, VoxCPM2) | Elena: susurrante, tierna y delicada; origen pedido: Salamanca (descripción en español, VoxCPM2) | Apache-2.0 (modelo); sin voz humana | **11,7** dB (n 6/10, p = 0,011)<br>con la frase de sonda: 18,6 dB (n 15/13, p < 0,001) | 199 Hz / 14,3 st | 25 s | WER medio 0,00 |
| `es-f-dvx-05` | A2 (diseñada, VoxCPM2) | Carmen: clara y articulada, tipo locutora cercana; origen pedido: Burgos (descripción en español, VoxCPM2) | Apache-2.0 (modelo); sin voz humana | **13,5** dB (n 9/10, p = 0,002)<br>con la frase de sonda: 14,4 dB (n 18/13, p < 0,001) | 214 Hz / 14,6 st | 22 s | WER medio 0,00 |
| `es-f-dvx-06` | A2 (diseñada, VoxCPM2) | Irene: cálida, algo ronca, conversacional; origen pedido: Madrid (descripción en español, VoxCPM2) | Apache-2.0 (modelo); sin voz humana | **14,3** dB (n 8/10, p = 0,001)<br>con la frase de sonda: 13,0 dB (n 17/13, p < 0,001) | 160 Hz / 10,8 st | 23 s | WER medio 0,00 |
| `es-f-dvx-08` | A2 (diseñada, VoxCPM2) | Clara: serena, tranquilizadora, ritmo constante; origen pedido: Segovia (descripción en español, VoxCPM2) | Apache-2.0 (modelo); sin voz humana | **17,5** dB (n 13/10, p < 0,001)<br>con la frase de sonda: 16,2 dB (n 22/13, p < 0,001) | 214 Hz / 9,9 st | 24 s | WER medio 0,00 |
| `es-f-est-01` | B (estudio) | Eurodiputada 28390 (VoxPopuli) | CC0 (VoxPopuli); audio © Parlamento Europeo, cita la fuente | **17,1** dB (n 7/10, p < 0,001)<br>con la frase de sonda: 16,4 dB (n 14/13, p < 0,001) | 222 Hz / 6,0 st | 26 s | WER medio 0,00 |
| `es-f-est-02` | B (estudio) | Eurodiputada 96922 (VoxPopuli) | CC0 (VoxPopuli); audio © Parlamento Europeo, cita la fuente | **11,3** dB (n 6/10, p < 0,001)<br>con la frase de sonda: 13,6 dB (n 12/13, p < 0,001) | 231 Hz / 7,7 st | 23 s | WER medio 0,00 |
| `es-f-est-03` | B (estudio) | Eurodiputada 103035 (VoxPopuli) | CC0 (VoxPopuli); audio © Parlamento Europeo, cita la fuente | **10,5** dB (n 6/9, p = 0,026)<br>con la frase de sonda: 9,1 dB (n 11/12, p = 0,003) | 232 Hz / 6,7 st | 25 s | WER medio 0,01 |
| `es-f-est-04` | B (estudio) | Eurodiputada 101146 (VoxPopuli) | CC0 (VoxPopuli); audio © Parlamento Europeo, cita la fuente | **13,1** dB (n 12/10, p < 0,001)<br>con la frase de sonda: 12,3 dB (n 20/13, p < 0,001) | 235 Hz / 9,2 st | 30 s | WER medio 0,00 |
| `es-f-est-05` | B (estudio) | Locutora 03397 (SLR61, estudio 48 kHz) | CC BY-SA 4.0 (OpenSLR SLR61, © Google) | **11,9** dB (n 9/10, p = 0,005)<br>con la frase de sonda: 14,3 dB (n 18/13, p < 0,001) | 244 Hz / 7,9 st | 25 s | WER medio 0,00 |

Notas por candidata (lectura de las medidas; **no he oído nada**):

- `es-f-est-01`: VoxPopuli, hablante 28390. La grabación más limpia (SNR 37 dB, suelo −57 dB) y la distinción más marcada de las de estudio; ritmo pausado en la criba (2,2 palabras/s) y la entonación más plana (rango 6,0 st).
- `es-f-est-02`: VoxPopuli, hablante 96922. La referencia arranca con «Gracias, presidenta»; Δ y rango de F0 medios.
- `es-f-est-03`: VoxPopuli, hablante 103035. La voz más aguda de la criba (F0 262 Hz en los segmentos; 232 Hz generada), suelo de ruido −43 dB, la referencia empieza a media frase y es la de Δ más bajo de las de estudio.
- `es-f-est-04`: VoxPopuli, hablante 101146. La más expresiva de las de estudio (rango 9,2 st), suelo de ruido −43 dB, referencia de exactamente 10,0 s empezando a media frase.
- `es-f-est-05`: OpenSLR SLR61, locutora peninsular 03397. La única con micrófono de estudio a 48 kHz; la referencia son 4 mensajes del tiempo («Hay dieciocho grados con sol…»), con prosodia de aviso: comprobar de oído que su entonación en frases libres es natural.
- `es-f-dvx-01`: VoxCPM2, «Lucía» (tono medio, suave y cálida, 25 años, Madrid). Muy expresiva (rango 12,7 st), F0 239 Hz; habla deprisa (3,9 palabras/s). Con la frase de sonda, n de /θ/ = 14.
- `es-f-dvx-02`: VoxCPM2, «Paula» (algo aguda, brillante y dulce, 22 años, Valladolid). Referencia corta (6,2 s) y habla muy deprisa (4,0 palabras/s).
- `es-f-dvx-04`: VoxCPM2, «Elena» (susurrante, tierna y delicada, 24 años, Salamanca). Rango de F0 muy amplio (14,3 st); Δ de las 4 frases 11,7 dB, con la sonda sube a 18,6.
- `es-f-dvx-05`: VoxCPM2, «Carmen» (clara y articulada, tipo locutora cercana, 27 años, Burgos). El rango de F0 más amplio (14,6 st) y habla deprisa (3,8 palabras/s).
- `es-f-dvx-06`: VoxCPM2, «Irene» (cálida, algo ronca, 26 años, Madrid). F0 160 Hz: la más grave de las candidatas, en el límite de una voz femenina; puede sonar a voz grave o ambigua.
- `es-f-dvx-08`: VoxCPM2, «Clara» (serena y tranquilizadora, ritmo constante, 30 años, Segovia). La distinción mejor respaldada de las diseñadas (Δ 17,5 dB con 13 palabras con /θ/, p < 0,001; 16,2 con 22) y de las más lentas de las VoxCPM2 (3,5 palabras/s).
- `es-f-dis-01 a 08 (Qwen3)`: Timbres muy distintos y WER 0, pero **sin distinción** (Δ de -4,0 a 2,2 dB): `01` (tono medio, cálida) la más expresiva de las de Qwen3 (rango 11,2 st); `02` demasiado aguda (F0 340 Hz, 4 dB más baja de volumen); `03` grave aterciopelada (F0 211 Hz); `04` susurrante (294 Hz); `06` cálida algo ronca (202 Hz); `07` ligera y sonriente (289 Hz); `08` serena (267 Hz). `05` no tiene versión normal.
- `es-f-ctrl-*`: controles (LibriVox ya rechazadas): no son candidatas.

## 5. ¿Pasa el acento de la referencia a lo que sintetiza el motor? Experimentos

**5.1 Sí, y el motor no lo corrige.** Con las dos LibriVox de control (referencias con distinción medida, Δ 14,0 y 11,6 dB en la 1.ª vuelta) lo generado da 12,4 y 16,5 dB; con las 5 de estudio, de
10,5 a 17,1 dB. En **modo x-vector** (`xvec_only=True`, el rescate del ADR-0008: solo el embedding del hablante, sin `ref_text`) también pasa: `es-f-ctrl-juanina-xv` 13,0 dB y `es-f-est-02-xv` 16,4 dB
(en ICL, `es-f-est-02`: 11,3). Y al revés: las voces diseñadas se quedan en el seseo también en x-vector (`es-f-dis-01-xv` 2,3 dB, `es-f-dis-04-xv` 2,9 dB;
en ICL 0,9 y 0,0). Es decir, **el acento va en la referencia y en el embedding del hablante, no en el motor**: para tener castellano con distinción hace falta una referencia que lo tenga.

**5.2 Variantes con «th» sobre las voces diseñadas con Qwen3** (experimentales; se dejan fuera de la tabla del apartado 4). `NNth` = la referencia se diseñó con el texto reescrito; `-rth` = la referencia es la normal y se reescriben
las frases que se piden al motor de producción; `-xv` = modo x-vector:

| id | camino | descripción | licencia | indicio de acento Δ(s−θ) | F0 mediana / rango p10–p90 | duración 4 frases | observaciones |
|---|---|---|---|---|---|---|---|
| `es-f-ctrl-juanina-xv` | control (LibriVox) | Control: juanina (LibriVox 19250), «La gente cursi», cap. IV | Dominio público (declaración general de LibriVox) | **13,0** dB (n 11/10, p = 0,002) | 185 Hz / 8,2 st | 26 s | WER medio 0,01 |
| `es-f-dis-01-rth` | A (diseñada, Qwen3) | Lucía: tono medio, suave y cálida; origen pedido: Madrid | Apache-2.0 (modelo); sin voz humana | **5,9** dB (n 5/10, p < 0,001) | 229 Hz / 10,1 st | 27 s | WER medio 0,04 |
| `es-f-dis-01-xv` | A (diseñada, Qwen3) | Lucía: tono medio, suave y cálida; origen pedido: Madrid | Apache-2.0 (modelo); sin voz humana | **2,3** dB (n 13/10, p = 0,028) | 212 Hz / 9,2 st | 27 s | WER medio 0,00 |
| `es-f-dis-01th` | A (diseñada, Qwen3) | Lucía: tono medio, suave y cálida; origen pedido: Madrid + «th» en el texto de la referencia | Apache-2.0 (modelo); sin voz humana | **-0,0** dB (n 13/10, p = 0,733) | 191 Hz / 7,8 st | 27 s | WER medio 0,00 |
| `es-f-dis-02-rth` | A (diseñada, Qwen3) | Paula: algo aguda, brillante y dulce, alegre; origen pedido: Valladolid | Apache-2.0 (modelo); sin voz humana | **9,6** dB (n 6/10, p = 0,147) | 352 Hz / 8,9 st | 25 s | WER medio 0,05 |
| `es-f-dis-03-rth` | A (diseñada, Qwen3) | Marta: grave, aterciopelada, serena; origen pedido: Toledo | Apache-2.0 (modelo); sin voz humana | **15,8** dB (n 7/10, p = 0,019) | 208 Hz / 9,9 st | 29 s | WER medio 0,10 |
| `es-f-dis-03th` | A (diseñada, Qwen3) | Marta: grave, aterciopelada, serena; origen pedido: Toledo + «th» en el texto de la referencia | Apache-2.0 (modelo); sin voz humana | **2,9** dB (n 12/10, p = 0,016) | 175 Hz / 6,2 st | 31 s | WER medio 0,00 |
| `es-f-dis-04-rth` | A (diseñada, Qwen3) | Elena: susurrante, tierna y delicada; origen pedido: Salamanca | Apache-2.0 (modelo); sin voz humana | **10,5** dB (n 8/10, p = 0,004) | 281 Hz / 8,0 st | 27 s | WER medio 0,06 |
| `es-f-dis-04-xv` | A (diseñada, Qwen3) | Elena: susurrante, tierna y delicada; origen pedido: Salamanca | Apache-2.0 (modelo); sin voz humana | **2,9** dB (n 13/10, p = 0,010) | 277 Hz / 7,8 st | 25 s | WER medio 0,00 |
| `es-f-dis-04th` | A (diseñada, Qwen3) | Elena: susurrante, tierna y delicada; origen pedido: Salamanca + «th» en el texto de la referencia | Apache-2.0 (modelo); sin voz humana | **3,0** dB (n 10/10, p = 0,045) | 193 Hz / 7,3 st | 25 s | WER medio 0,00 |
| `es-f-dis-05th` | A (diseñada, Qwen3) | Carmen: clara y articulada, tipo locutora cercana; origen pedido: Burgos + «th» en el texto de la referencia | Apache-2.0 (modelo); sin voz humana | **8,5** dB (n 9/10, p = 0,004) | 235 Hz / 10,1 st | 25 s | WER medio 0,00 |
| `es-f-dis-06-rth` | A (diseñada, Qwen3) | Irene: cálida, algo ronca, conversacional; origen pedido: Madrid | Apache-2.0 (modelo); sin voz humana | **16,3** dB (n 9/10, p = 0,001) | 189 Hz / 7,6 st | 24 s | WER medio 0,05 |
| `es-f-dis-06th` | A (diseñada, Qwen3) | Irene: cálida, algo ronca, conversacional; origen pedido: Madrid + «th» en el texto de la referencia | Apache-2.0 (modelo); sin voz humana | **2,0** dB (n 13/10, p = 0,077) | 283 Hz / 10,2 st | 29 s | WER medio 0,00 |
| `es-f-dis-07th` | A (diseñada, Qwen3) | Sofía: ligera, aireada, sonriente; origen pedido: Zaragoza + «th» en el texto de la referencia | Apache-2.0 (modelo); sin voz humana | **0,1** dB (n 12/10, p = 0,717) | 277 Hz / 9,9 st | 27 s | WER medio 0,00 |
| `es-f-dis-08-rth` | A (diseñada, Qwen3) | Clara: serena, tranquilizadora, ritmo constante; origen pedido: Segovia | Apache-2.0 (modelo); sin voz humana | **12,0** dB (n 9/10, p = 0,005) | 237 Hz / 9,9 st | 26 s | WER medio 0,07 |
| `es-f-dis-08th` | A (diseñada, Qwen3) | Clara: serena, tranquilizadora, ritmo constante; origen pedido: Segovia + «th» en el texto de la referencia | Apache-2.0 (modelo); sin voz humana | **1,7** dB (n 13/10, p = 0,306) | 199 Hz / 6,4 st | 27 s | WER medio 0,00 |
| `es-f-est-02-xv` | B (estudio) | Eurodiputada 96922 (VoxPopuli) | CC0 (VoxPopuli); audio © Parlamento Europeo, cita la fuente | **16,4** dB (n 13/10, p = 0,002) | 225 Hz / 7,7 st | 26 s | WER medio 0,01 |

- **Reescribir la referencia (`NNth`) casi no cambia lo que dice el motor** (Δ de −0,0 a 3,0 dB; solo `05th` llega a 8,5): con 1-3 palabras de ejemplo en la referencia, el motor de 0,6B no generaliza la /θ/ a las demás.
- **Reescribir las frases (`-rth`) sí mueve el indicio**: Δ de 5,9 a 16,3 dB
  (`es-f-dis-06-rth` 16,3, `03-rth` 15,8, `08-rth` 12,0, `04-rth` 10,5; las voces `01-rth` y `02-rth`, 6 y 10 dB). Pero solo se pudieron alinear de 5 a 9 de las 13 palabras con /θ/ (a Whisper le salen
  partidas o cambiadas) y el WER sube de 0,00 a entre 0,04 y 0,10 (de 3 a 8 palabras mal de unas 80). **Es un truco de texto** (normalizar z/ce/ci → «th» antes del TTS, solo para voces diseñadas) con la /θ/ inglesa; podría sonar a «th» y no a castellano.
  Solo el oído lo decide. Si sonara bien, permitiría timbres diseñados con acento castellano a costa de un normalizador de texto en el servicio de voz; si no, las diseñadas con Qwen3 quedan sin acento de España.

**5.3 Las voces diseñadas con VoxCPM2 conservan la distinción en el motor de producción.** Con una referencia de VoxCPM2 en español de España, el motor de 0,6B también la mantiene: Δ de 11,7 a 18,6 dB en las 6 (`es-f-dvx-NN`),
frente a -4,0 a 2,2 dB de las diseñadas con Qwen3. Es decir, **sí hay una vía para tener voces diseñadas con distinción** (el acento de la referencia pasa, §5.1), pero con dos costes: VoxCPM2 desobedece «mujer» en la mitad o más de las tomas (§1.3) y
sus voces hablan deprisa (de 3,4 a 4,0 palabras/s frente a 2,8-3,7 de las de estudio; de 21 a 25 s para las 4 frases frente a 23-30 s), lo que reduce el retraso acumulado del traductor, pero puede cansar o perder claridad.

## 6. Recomendación (orden de preferencia)

Preselección con las medidas del apartado 4 (acento de España en lo generado, WER, F0 de voz femenina, rango de F0, limpieza de la fuente y derechos); **el desempate real es el oído del humano**:

1. **`es-f-dvx-08`: «Clara», diseñada con VoxCPM2** (serena, tranquilizadora, 30 años). Es la diseñada mejor respaldada: Δ 17,5 dB con 13 palabras con /θ/ (p < 0,001; 16,2 con 22), F0 214 Hz, rango de F0 9,9 st (moderadamente expresiva), WER 0, de las más lentas de las VoxCPM2
   y **sin voz humana detrás** (sin cuestión de derechos sobre la voz de una persona). Contras: referencia de 7,8 s, voz generada por un modelo que no distingue bien el sexo (comprobar que suena a mujer), ritmo todavía rápido (3,5 palabras/s).
2. **`es-f-dvx-01`: «Lucía», diseñada con VoxCPM2** (tono medio, suave y cálida, 25 años). La distinción más marcada de las diseñadas (Δ 18,6 dB; 17,5 con la sonda), F0 239 Hz y una entonación muy viva (rango 12,7 st; las de rango más amplio son `05` y `04`, con 14,6 y 14,3 st).
   Contras: habla deprisa (3,9 palabras/s) y la entonación podría resultar exagerada.
3. **`es-f-est-04`: VoxPopuli, hablante 101146 (CC0)**, la voz humana más segura en acento: Δ 13,1 dB con 12 palabras con /θ/ (p < 0,001; 12,3 con la sonda), la más expresiva de las de estudio (rango 9,2 st), F0 235 Hz y WER 0.
   Contras: oratoria de sala parlamentaria (suelo de ruido −43 dB), 16 kHz, y es una eurodiputada identificable.
4. **`es-f-est-01`: VoxPopuli, hablante 28390 (CC0).** La grabación más limpia (SNR 37 dB), la distinción más marcada de las humanas (Δ 17,1 dB; 16,4 con la sonda) y ritmo pausado: la mejor candidata a «suave»; contra: la entonación más plana (rango 6,0 st).

**Alternativas:** `es-f-dvx-05` («Carmen», clara tipo locutora; Δ 13,5 dB), `es-f-dvx-04` («Elena», susurrante; 11,7 dB, 18,6 con la sonda), `es-f-est-05` (SLR61, micrófono de estudio a 48 kHz, F0 244 Hz, pero con referencia de avisos del tiempo)
y `es-f-est-02`. **Descartadas por el criterio de acento:** las 7 `es-f-dis-NN` de Qwen3 (seseo) y `es-f-dvx-06` (F0 160 Hz, límite de voz femenina); `es-f-dvx-02` tiene la referencia más corta (6,2 s).

**Cómo decidir:** que el humano escuche primero las 4 frases de las 4 principales (y la referencia de cada una), elija por timbre y naturalidad, y compare con `es-f-ctrl-*` si quiere calibrar. Antes de instalar la elegida: `exportar_voz.py <id>` deja `<id>.wav` y `<id>.json`
(campos del contrato de voz) en `...\voces-v2\listas\`; la instalación en la carpeta de voces de la app y el ADR de la voz (con la licencia y la atribución de §3) los hace quien decida. Si elige una diseñada (`dvx`), anotar en el ADR que el acento es un indicio medido, no oído, y que VoxCPM2 solo es herramienta de autoría (5,5 GiB de VRAM, fuera del servicio).

## 7. Límites, riesgos y preguntas para el humano

- **Nada de esto está escuchado.** «Joven», «suave», «buena entonación», «timbre agradable» y «de España» son aquí F0, rango de F0, ritmo y el indicio Δ(s−θ), medidas indirectas. La F0 no da la edad; la suavidad no se midió.
  **El humano debe escuchar `<id>_frase1..4.wav` de las candidatas del apartado 6** antes de decidir.
- **Pocas palabras para el indicio:** las 4 frases llevan 13 palabras con /θ/, pero las alineables con lo que oyó Whisper son de 6 a 13 por candidata (de 11 a 22 con la frase de sonda). Un Δ de 10-17 dB frente a ≈ 0-4 dB separa bien «con distinción» de «seseo», pero entre dos voces de estudio la diferencia
  de unos dB no es concluyente. Hay hablantes peninsulares sin distinción y al revés (lo advierte el propio `distincion.py`); sobre todo, no prueba que el hablante sea de España.
- **VoxPopuli:** audio de 16 kHz (la referencia pasa a 24 kHz sin contenido por encima de 8 kHz) y de sala parlamentaria (suelo de ruido de −43 a −57 dB); es oratoria preparada, no conversación; las hablantes son eurodiputadas identificables.
  La licencia (CC0 para los datos, reutilización del Parlamento Europeo citando la fuente) no resuelve derechos sobre la voz de una persona real si el uso cambiara; para uso personal local el riesgo es bajo (valoración mía, **sin verificar jurídicamente**).
- **SLR61 (`es-f-est-05`):** solo hay una mujer peninsular y sus 30 mensajes son la misma frase con cifras distintas; la referencia son 4 mensajes unidos. Mide cómo clona una voz de estudio, no cómo suena en conversación.
- **Voces diseñadas:** la descripción está en inglés (el idioma de los ejemplos del modelo); no se probó otra redacción de timbre. Las tomas son aleatorias (semilla en el JSON) y 2 por voz; con más tomas saldrían otras. Qwen3-VoiceDesign no distingue /θ/ de /s/ (§1.2),
  así que su `ref_text` normal y su audio coinciden (WER 0), pero el acento es el de un español sin distinción.
- **Motor de producción:** el servicio de T025 todavía no está en la rama. Se usaron las mismas funciones del spike S1 que T025 porta (`preparar_prompt`, `una_peticion`; ICL, `chunk_size=4`), así que lo medido vale para esa configuración.
  Las cifras de rendimiento (RTF, primer audio) de las ejecuciones de este spike no son válidas (CPU ocupada por Whisper y GPU compartida): valen las del spike S1.
- **Whisper large-v3-turbo** (CPU, int8) hace de oído para el WER y para los tiempos por palabra del indicio. Confunde algunas /θ/ forzadas («th») con /t/ o /d/; por eso en el apartado 5 se da el Δ sobre las palabras pedidas alineadas y sobre las que escribió bien.
- **No se probó:** `Qwen3-TTS-CustomVoice` (ninguno de sus 9 timbres es nativo de español), Parler-TTS ni otros modelos de diseño de voz, el modo `instruct` sobre una referencia, ni sesiones largas.
- **Preguntas para el humano:** ¿le importa más el timbre de una voz diseñada o el acento de España? (hoy son excluyentes); ¿timbre más grave (`es-f-est-01`, 222 Hz) o más agudo (`es-f-est-05`, 244 Hz)?; ¿le suena natural la reescritura «th» de los apartados 5.2 y 5.3?

## 8. Cómo reproducir

Requisitos: Windows 11, `uv`, GPU NVIDIA (RTX 5070 aquí). Nada a nivel de sistema, sin cuentas ni pagos. Todo uso de GPU va bajo el candado `%LOCALAPPDATA%\InstantTraductor\gpu.lock`
(`filelock`, espera hasta 30 min). Desde la raíz del repo; tres entornos, ninguno toca los `pyproject.toml` de `spikes/voz/` ni de `engines/`:

```powershell
# 0. Entornos: herramientas CPU (Whisper, F0, acento), el de Qwen3 del spike S1 (sin modificar) y el de VoxCPM2
uv sync --project spikes/voces
uv sync --project spikes/voz/qwen3
uv sync --project spikes/voces/voxcpm

# 1. Modelos extra a %LOCALAPPDATA%\InstantTraductor\models\ (el motor Base y Whisper ya los dejó el spike S1)
uv run --project spikes/voces python spikes/voces/descargar_modelos.py voicedesign voxcpm2

# 2. Camino A: sonda de acento, diseño de las 8 voces y elección de la mejor toma
uv run --project spikes/voz/qwen3 python spikes/voces/sondear_acento.py --takes 2
uv run --project spikes/voces python spikes/voces/evaluar_sonda.py
uv run --project spikes/voz/qwen3 python spikes/voces/disenar.py --takes 2 --ortografia normal --semilla-base 3030
uv run --project spikes/voz/qwen3 python spikes/voces/disenar.py --takes 2 --ortografia th
uv run --project spikes/voces python spikes/voces/evaluar_disenos.py --auto
#    A2: VoxCPM2
uv run --project spikes/voces/voxcpm python spikes/voces/voxcpm/sondear_voxcpm.py --takes 2
uv run --project spikes/voces/voxcpm python spikes/voces/voxcpm/disenar_voxcpm.py --takes 3 --acento distincion_es
uv run --project spikes/voces python spikes/voces/evaluar_disenos.py --motor voxcpm --auto

# 3. Camino B: VoxPopuli es (CC0) y SLR61 (el spike S1 lo dejó en spikes\voz\ref\raw\es_weather_messages: https://openslr.trmal.net/resources/61/es_weather_messages.zip)
uv run --project spikes/voces python spikes/voces/voxpopuli_explorar.py descargar
uv run --project spikes/voces python spikes/voces/voxpopuli_explorar.py resumen
uv run --project spikes/voces python spikes/voces/elegir_estudio.py cribar --max-hablantes 14
uv run --project spikes/voces python spikes/voces/elegir_estudio.py tramos --hablante 101146        # ventanas de 8-10 s entre pausas
uv run --project spikes/voces python spikes/voces/extraer_estudio.py                               # las 5 referencias de estudio
uv run --project spikes/voces python spikes/voces/preparar_controles.py                            # 2 controles LibriVox

# 4. Las 4 frases con el motor de producción (Qwen3-TTS-0.6B Base + faster-qwen3-tts, ICL, chunk_size 4) y las medidas en CPU
uv run --project spikes/voz/qwen3 python spikes/voces/sintetizar_frases.py                         # todas las <id>_ref.wav
uv run --project spikes/voz/qwen3 python spikes/voces/sintetizar_frases.py --modo xvec --ids es-f-dis-01,es-f-est-02
uv run --project spikes/voz/qwen3 python spikes/voces/sintetizar_frases.py --respell-th --ids es-f-dis-06,es-f-dis-08
uv run --project spikes/voces python spikes/voces/evaluar_muestras.py                              # escribe medidas.json
uv run --project spikes/voces python spikes/voces/tabla_readme.py                                  # tabla del apartado 4

# 5. Dejar una candidata lista para instalar (<id>.wav + <id>.json con los campos del contrato) en <out>\listas\
uv run --project spikes/voces python spikes/voces/exportar_voz.py es-f-est-04
```

Las medidas en bruto están en `resultados/medidas.json` (por frase: transcripción de Whisper, WER, duración, F0).

Espacio fuera del repo (todo en `%LOCALAPPDATA%\InstantTraductor\`): modelos `voxcpm2` (4,7 GB) y `qwen3-tts-12hz-1.7b-voicedesign` (4,3 GB) en `models\`; las muestras y referencias (WAV de 24 kHz) en `spikes\voces-v2\`, y
unos 2 GB de parquet de VoxPopuli en `spikes\voces-v2\_trabajo\corpus\` (solo hacen falta para repetir la criba; se pueden borrar).

## 9. Estructura

```text
spikes/voces/
  README.md                  este documento
  pyproject.toml, uv.lock    entorno CPU (faster-whisper, scipy, pyarrow); sin torch
  common.py                  rutas, 4 frases comunes, F0, ASR, indicio de acento alineado al texto pedido (reutiliza spikes/voz/common)
  descargar_modelos.py       VoiceDesign 1.7B y VoxCPM2 a %LOCALAPPDATA%\InstantTraductor\models\
  disenos.py, disenar.py     camino A: las 8 descripciones, los textos de referencia y la generación con VoiceDesign
  sondear_acento.py          camino A: sonda de 10 formas de pedir el acento (+ evaluar_sonda.py)
  evaluar_disenos.py         elige la mejor toma de cada voz diseñada y escribe <id>_ref.wav/.json
  voxcpm/                    camino A2: entorno propio de VoxCPM2 (pyproject.toml, uv.lock), sondear_voxcpm.py, disenar_voxcpm.py
  voxpopuli_explorar.py      camino B: descarga y resumen de hablantes de VoxPopuli es
  elegir_estudio.py          camino B: criba de hablantes femeninas y ventanas de 8-10 s
  extraer_estudio.py         camino B: recorta y normaliza las 5 referencias de estudio
  preparar_controles.py      dos controles LibriVox para calibrar la transferencia del acento
  sintetizar_frases.py       las 4 frases con el motor de producción (modos icl, xvec y la reescritura «th»)
  evaluar_muestras.py        ASR, WER, F0, duración y acento de lo generado
  tabla_readme.py            tablas Markdown de este README a partir de medidas.json
  exportar_voz.py            deja una candidata lista para instalar según el contrato de voz
  comprobar_f0.py            contrasta la F0 con un segundo estimador (YIN) para descartar errores de octava
  resultados/medidas.json    cifras de todas las candidatas
```
