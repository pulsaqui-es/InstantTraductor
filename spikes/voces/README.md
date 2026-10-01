# T040 (2.ª vuelta): voces femeninas castellanas nuevas (diseñadas y de estudio)

Spike de investigación de la feature `001-espina-dorsal`. No es código de producto. Fecha de todas las consultas y mediciones: 2026-10-01.

**Por qué:** el humano escuchó las 4 lectoras de LibriVox de la 1.ª vuelta (`docs/investigacion/2026-10-01-voces-castellanas.md`) y las rechazó:
«tienen una voz terrible, no anima a escucharlas más de 10 segundos». Pide **voz femenina joven, suave, con buena entonación, en español de España**.

> **Estado de este documento: hito 1 (viabilidad).** Las muestras, las medidas y la recomendación se añaden en los hitos 2 y 3.

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
