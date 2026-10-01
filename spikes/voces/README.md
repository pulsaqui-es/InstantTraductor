# T040 (2.ª vuelta): voces femeninas castellanas nuevas (diseñadas y de estudio)

Spike de investigación de la feature `001-espina-dorsal`. No es código de producto. Fecha de todas las consultas y mediciones: 2026-10-01.

**Por qué:** el humano escuchó las 4 lectoras de LibriVox de la 1.ª vuelta (`docs/investigacion/2026-10-01-voces-castellanas.md`) y las rechazó:
«tienen una voz terrible, no anima a escucharlas más de 10 segundos». Pide **voz femenina joven, suave, con buena entonación, en español de España**.

> **Estado de este documento: hito 2 (referencias generadas o extraídas).** Las muestras de las 4 frases, las medidas y la recomendación se añaden en el hito 3.

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

Indicio de acento = Δ(s−θ) de `spikes/voz/common/distincion.py` (dB; control peninsular del spike S1 15,5 dB; seseo argentino 1,8 dB).
Se generó 2 veces cada variante con la **misma** voz base y la misma frase, densa en palabras con z/ce/ci (18 palabras con /θ/ y 6 con /s/ por variante):

| Forma de pedir el acento | Δ(s−θ) agrupado |
|---|---|
| sin mencionar acento | −0,2 dB |
| «castellano estándar de Madrid, “th” para z y c» (EN) | 1,3 dB |
| «nacida en España, NO latinoamericana, con distinción… sin seseo» (EN) | 0,1 dB |
| «actriz de doblaje de España, castellano neutro del doblaje» (EN) | 0,2 dB |
| lo mismo, descrito en español: «nacida en España… con distinción, nunca seseo» | 1,7 dB |
| «actriz de doblaje y locutora profesional de España» (ES) | −0,5 dB |
| «ceceo castellano: z/ce/ci suenan como la “th” inglesa» (EN) | 0,8 dB |

Todas quedan en la zona del seseo (≈ 0–2 dB): **las voces diseñadas con una descripción normal hablan sin distinción**, aunque se les pida lo contrario de seis maneras.
Whisper las transcribe sin ningún error (WER 0), así que no están rotas: simplemente pronuncian z/ce/ci como /s/.

**Truco probado: reescribir z/ce/ci con «th» en el texto que se envía a VoiceDesign** (`Hace cinco días` → `Hathe thinco días`): el modelo lee «th» con la /θ/ inglesa y el indicio sube a 9–20 dB
(`base_en_th` 9,1; `fuerte_en_th` 20,1), a costa de que Whisper confunda algunas /θ/ con /t/ o /d/ («Detilia», «dinar»: WER 0,14). El `ref_text` de la referencia sigue siendo el texto normal. Es un
indicio medido, **sin oír**: puede sonar a «th» inglesa y no a /θ/ castellana; lo decide el oído (ver el hito 3 para lo que pasa después en el motor de producción).

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

## 3. Referencias generadas o extraídas (hito 2)

Todas son WAV mono de 24 kHz, de 8 a 10 s, con RMS −20 dBFS (pico ≤ −1 dBFS) y fundidos de 30 ms, en `%LOCALAPPDATA%\InstantTraductor\spikes\voces-v2\<id>_ref.wav`
con su `<id>_ref.json` (campos de `VoiceInfo` del contrato de voz más `ref_text`, duración y origen).

- **Diseñadas (`es-f-dis-NN`, 8 voces):** `Qwen3-TTS-12Hz-1.7B-VoiceDesign` con una descripción en inglés (edad 22–30, timbre distinto en cada una, origen castellano pedido: Madrid, Valladolid, Toledo,
  Salamanca, Burgos, Zaragoza, Segovia) y un texto castellano de 21–23 palabras. De 2 tomas por voz se escribe la que Whisper large-v3-turbo transcribe sin ninguna diferencia (WER 0) y cae en 7,8–10,6 s;
  el `ref_text` es exactamente el texto generado. `es-f-dis-NNth` es la misma voz con la reescritura «th» del apartado 1.2 (solo se conserva una si cumple duración y WER ≤ 0,20; son experimentales y dos pasan de 10 s: `03th` 10,2 s y `04th` 10,6 s).
- **De estudio (`es-f-est-NN`, 5 voces):** 4 hablantes de VoxPopuli `es` (CC0) y la hablante peninsular de SLR61. De VoxPopuli se cribaron las 14 hablantes con más material (4 segmentos de 12–28 s por hablante,
  Whisper large-v3-turbo con tiempos por palabra, `distincion.py`, F0 y suelo de ruido). Δ(s−θ) entre 9,7 y 20,4 dB en 11 de las 14 (las otras tres: 0,7; −3,0 y 6,5 dB, descartadas). De ellas se eligieron 4 con
  distinción medida (p < 0,05), SNR de 29 a 37 dB y F0 de 202 a 262 Hz, y de cada una un tramo de 9–10 s entre pausas reales; el `ref_text` es la transcripción de Whisper del propio recorte, que coincide con el
  `raw_text` del corpus (96–100 % de las palabras alineadas). `es-f-est-05` une 4 mensajes del tiempo de la locutora 03397 de SLR61 (texto del TSV del corpus).
- **Controles (`es-f-ctrl-*`):** las dos LibriVox de la 1.ª vuelta con mejor distinción medida (juanina y Mongope), **no son candidatas** (el humano ya las rechazó): sirven para comprobar si el acento de la
  referencia pasa a lo que sintetiza el motor.

| id | duración | F0 mediana | ref_text (exacto) | origen |
|---|---|---|---|---|
| `es-f-ctrl-juanina` |  s |  Hz | «Paquita bajó los ojos, y haciendo un esfuerzo consiguió ponerse colorada como un tomate. La madre arrugó el entrecejo.» | LibriVox (dominio público); ver docs/investigacion/2026-10-01-voces-castellanas.md |
| `es-f-ctrl-mongope` |  s |  Hz | «Helena se posaba en su asiento solemne y fría, henchida de desdén, como una diosa llevada por el destino.» | LibriVox (dominio público); ver docs/investigacion/2026-10-01-voces-castellanas.md |
| `es-f-dis-01` | 9.92 s | 238.1 Hz | «Cuando llegué a la estación, el tren ya se había marchado. Entonces me senté, respiré hondo y decidí esperar con calma al siguiente.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-01_en_normal_t1.wav`, semilla 3130 |
| `es-f-dis-01th` | 9.43 s | 218.6 Hz | «Cuando llegué a la estación, el tren ya se había marchado. Entonces me senté, respiré hondo y decidí esperar con calma al siguiente.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-01_en_th_t2.wav`, semilla 2127 |
| `es-f-dis-02` | 7.95 s | 386.1 Hz | «¡Qué maravilla de día! Hace un sol precioso y el cielo está despejado. ¿Por qué no salimos a dar un paseo?» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-02_en_normal_t2.wav`, semilla 3231 |
| `es-f-dis-03` | 8.79 s | 215.4 Hz | «A veces pienso que lo mejor de la vida son las cosas sencillas: un café caliente, una conversación tranquila y nada de prisa.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-03_en_normal_t2.wav`, semilla 3331 |
| `es-f-dis-03th` | 10.19 s | 187.8 Hz | «A veces pienso que lo mejor de la vida son las cosas sencillas: un café caliente, una conversación tranquila y nada de prisa.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-03_en_th_t1.wav`, semilla 2326 |
| `es-f-dis-04` | 8.53 s | 305.9 Hz | «Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-04_en_normal_t2.wav`, semilla 3431 |
| `es-f-dis-04th` | 10.55 s | 182.0 Hz | «Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-04_en_th_t1.wav`, semilla 2426 |
| `es-f-dis-05th` | 8.4 s | 235.9 Hz | «Cuando llegué a la estación, el tren ya se había marchado. Entonces me senté, respiré hondo y decidí esperar con calma al siguiente.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-05_en_th_t1.wav`, semilla 2526 |
| `es-f-dis-06` | 8.03 s | 212.2 Hz | «¡Qué maravilla de día! Hace un sol precioso y el cielo está despejado. ¿Por qué no salimos a dar un paseo?» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-06_en_normal_t2.wav`, semilla 3631 |
| `es-f-dis-06th` | 9.04 s | 305.2 Hz | «¡Qué maravilla de día! Hace un sol precioso y el cielo está despejado. ¿Por qué no salimos a dar un paseo?» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-06_en_th_t2.wav`, semilla 2627 |
| `es-f-dis-07` | 9.28 s | 281.7 Hz | «A veces pienso que lo mejor de la vida son las cosas sencillas: un café caliente, una conversación tranquila y nada de prisa.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-07_en_normal_t2.wav`, semilla 3731 |
| `es-f-dis-07th` | 9.05 s | 265.0 Hz | «A veces pienso que lo mejor de la vida son las cosas sencillas: un café caliente, una conversación tranquila y nada de prisa.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-07_en_th_t2.wav`, semilla 2727 |
| `es-f-dis-08` | 8.08 s | 270.8 Hz | «Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-08_en_normal_t2.wav`, semilla 3831 |
| `es-f-dis-08th` | 8.49 s | 197.9 Hz | «Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida.» | Qwen3-TTS-1.7B-VoiceDesign, toma `es-f-dis-08_en_th_t2.wav`, semilla 2827 |
| `es-f-est-01` | 9.16 s | 201.0 Hz | «Fue este Parlamento el que lo aprobó y lo negoció con el Consejo, con una gran colaboración con la Comisión.» | voxpopuli: 20170405-0900-PLENARY-14-es_20170405-18:01:16_6 0.0-9.04 s; hablante 28390 |
| `es-f-est-02` | 9.24 s | 221.7 Hz | «Gracias, presidenta. He apoyado este informe porque va a mejorar la calidad de los productos alimenticios y también va a contribuir al consumo informado y responsable.» | voxpopuli: 20110706-0900-PLENARY-6-es_20110706-14:02:19_0 2.58-11.6 s; hablante 96922 |
| `es-f-est-03` | 9.24 s | 230.6 Hz | «una directiva que viene a reconocer nuevos derechos a aquellas mujeres que ejercen una actividad autónoma y a los cónyuges o parejas, de hecho, colaboradores.» | voxpopuli: 20100615-0900-PLENARY-14-es_20100615-21:30:17_25 4.28-13.3 s; hablante 103035 |
| `es-f-est-04` | 10.0 s | 216.5 Hz | «Tengan ustedes la tranquilidad, que podemos decir alto y claro que en Copenhague la Unión Europea no ha sido el problema.» | voxpopuli: 20100120-0900-PLENARY-10-es_20100120-17:48:45_11 2.8-12.68 s; hablante 101146 |
| `es-f-est-05` | 9.6 s | 236.2 Hz | «Hay dieciocho grados con sol. Hay once grados y llueve. Hay diecinueve grados y está nublado. Hay dieciseis grados y está nublado.» | slr61: mensajes esw_03397_01452159553, esw_03397_00254676062, esw_03397_01417960131, esw_0; hablante 03397 |

Atribución de las de estudio: VoxPopuli (Wang et al., ACL 2021, https://aclanthology.org/2021.acl-long.80), datos CC0; el audio es de las sesiones plenarias del Parlamento Europeo
(reutilización citando la fuente, aviso legal https://www.europarl.europa.eu/legal-notice/es/); SLR61: «Copyright 2018, 2019 Google, Inc.», CC BY-SA 4.0, https://openslr.org/61/ (Guevara-Rukoz et al., LREC 2020).
**Una voz clonada es la voz de una persona real**: las de estudio son eurodiputadas identificables por el id de la sesión; no he valorado jurídicamente el uso (valoración mía, sin verificar).
