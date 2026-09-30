# 04 · Traducción voz→voz de extremo a extremo, costes y aplicaciones existentes

*InstantTraductor · investigación a 30-sep-2026.*
*Alcance actualizado por el coordinador a mitad de la tarea: la app será **100 % local y de uso personal** (se aceptan licencias no comerciales). Por eso este informe se centra en (1) modelos E2E con pesos abiertos ejecutables en local y (2) aplicaciones y funciones existentes. La nube y los costes se resumen solo como referencia, con los datos ya recogidos.*
*Convenciones: "E2E" = modelo único voz→voz. "LAAL" = retardo medio de la traducción respecto al original. "End offset" = cuánto sigue hablando la traducción tras callar el orador. "(sin verificar)" = dato que no se ha podido confirmar en una fuente primaria.*

---

## 1) Resumen ejecutivo

- A 30-sep-2026 **no existe ningún E2E voz→voz de pesos abiertos** que traduzca en/ja/zh→es con buena calidad, latencia de 1,5–3 s y que funcione tal cual en Windows con la RTX 5070 (sm_120).
- El único candidato real es **Meta Seamless** (CC-BY-NC 4.0, válido para uso personal). Traduce en/ja/zh→es con voz, pero tiene tres pegas:
  - retardo medido de ≈3 s en frases y de 6–7 s en discurso largo;
  - voz genérica, que no se parece a la del orador;
  - SeamlessStreaming depende de fairseq2 0.2, que no funciona en Windows y solo admite PyTorch ≤2.1 y Python ≤3.11, así que no corre en Blackwell sin portarlo.
- **Hibiki y Hibiki-Zero** (Kyutai) son la mejor arquitectura abierta, pero **solo traducen hacia inglés**. **Qwen3-Omni** (Apache 2.0, habla español) necesita unos 79 GB en BF16, así que no cabe en 12 GB. Las novedades de 2026 son solo zh↔en (SimulS2ST-Omni) o no tienen código (SimulU).
- Los E2E buenos de 2026 están en la **nube**: gpt-realtime-translate (2,04 $/h), Gemini 3.5 Live Translate (≈2,2 $/h), Azure Live Interpreter (2,5 $/h) y Qwen3.8-LiveTranslate (≈1,5 $/h). Quedan descartados porque la app será 100 % local; en local el coste es la electricidad (≈0,05 €/h).
- **Recomendación:**
  - motor principal: una **cascada local en streaming**;
  - desde el principio, una **interfaz de motor enchufable** (audio → audio + texto);
  - SeamlessM4T v2 (vía Transformers, nativo en Windows) solo como motor experimental o de referencia, no como opción de producto.
- **Ninguna función integrada** (Subtítulos en directo de Windows, Chrome, YouTube, Teams, Meet, Zoom) da **voz en español de España para cualquier audio del PC** en un equipo sin NPU Copilot+ (el Ryzen 7 8700F tiene 16 TOPS). Las apps abiertas más parecidas son Sokuji (local, AGPL), VoxisLive y My Translator (nube) y LiveCaptions-Translator (solo texto). Son las que hay que superar en calidad, retardo y voz es-ES.

---

## 2) Tabla comparativa

### 2.1 Modelos E2E con pesos abiertos para uso local (foco principal)

| Modelo (fecha) | Idiomas útiles para InstantTraductor | ¿Simultáneo? | Latencia publicada | VRAM / ¿cabe en 12 GB? | Windows + RTX 5070 | Licencia | Veredicto |
|---|---|---|---|---|---|---|---|
| **SeamlessStreaming** (Meta, dic-2023) | Sí: en/ja/zh→es. Habla en 36 idiomas, español incluido. | Sí | Meta dice "unos 2 s". Medido (X→en): LAAL 2,7–3,1 s en frases y 6,2–7,3 s en discurso largo; end offset 2,4–3,2 s. | 2,5B parámetros. La demo oficial usa una T4 de 16 GB. Estimado 6–10 GB (sin verificar): probablemente cabe. | **No, tal cual.** fairseq2 0.2.x no funciona en Windows (hay que usar WSL2) y solo admite PyTorch ≤2.1 y Python ≤3.11. La RTX 5070 necesita PyTorch ≥2.7 con CUDA 12.8. | CC-BY-NC 4.0 (uso personal permitido) | Único E2E simultáneo abierto que da español. Integrarlo es caro y arriesgado. |
| **SeamlessM4T v2 large** (Meta) vía HF Transformers | Sí: en/ja/zh→es (entrada y salida de voz en spa/jpn/cmn). | No: hay que trocear el audio con VAD. | Duración del segmento + inferencia. Estimado 3–6 s en total (sin verificar). | 2,3B. Unos 5 GB en fp16 (estimado): cabe. | Probablemente sí (Transformers + PyTorch moderno), sin verificar en Blackwell. En Transformers v5 desapareció el pipeline de traducción: hay que usar las clases del modelo. | CC-BY-NC 4.0 | **La mejor vía** para un motor E2E experimental enchufable. |
| SeamlessExpressive (Meta) | en, es, fr, de, it, zh. **Sin japonés.** | No | — | — | Mismo problema de fairseq2. | Licencia "Seamless" (no comercial, con solicitud de acceso) | Descartado. |
| Hibiki (Kyutai, feb-2025) | Solo fr→en. | Sí | — | 2,7B; pensado para ejecutarse en el propio dispositivo. | Sin verificar. | CC-BY 4.0 | No sirve: traduce hacia inglés. |
| **Hibiki-Zero** (Kyutai, feb-2026) | fr/es/pt/de→en (italiano añadido en un experimento). | Sí | LAAL 2,8–3,1 s en frases y 5,6–6,3 s en discurso largo; end offset 1,9–2,6 s. | 3B. Según sus autores, "con 8 GB debería funcionar; 12 GB es seguro". | PyTorch; Windows no documentado. | CC BY-NC-SA 4.0 | No sirve (traduce hacia inglés). Útil como referencia de arquitectura. |
| **Qwen3-Omni-30B-A3B** (Alibaba, sep-2025) | Entiende voz en 18 idiomas (en/ja/zh/es…) y habla en 10, español incluido. | No: responde por turnos, cuando acaba la frase. | — | **≥79 GB en BF16.** Incluso en INT4/NVFP4 muy por encima de 12 GB (estimado). | Funciona con Transformers. vLLM no genera audio (según la model card). | Apache 2.0 | No cabe en 12 GB. |
| SimulS2ST-Omni (artículo, jul-2026) | Solo zh↔en. | Sí | LAAL ≈0,5–2,5 s (en→zh). | Basado en Qwen2.5-Omni. | Pesos no confirmados. | Artículo CC BY 4.0 | Investigación. |
| SimulU (artículo, mar-2026) | en→es y otros 7 pares (MuST-C), sobre SeamlessM4T. | Sí (política sin entrenamiento) | Primer audio a los ≈1–2 s. | ~1B | **Sin código publicado.** | — | Vigilar: daría modo simultáneo sobre M4T. |

### 2.2 Aplicaciones y funciones existentes

| Producto | ¿Voz traducida? | ¿Traduce a español? ¿Y ja/zh→es? | ¿Cualquier audio del PC? | Requisitos y limitaciones clave |
|---|---|---|---|---|
| **Subtítulos en directo de Windows 11** (Live Captions) | No: solo texto. | **No.** Traduce a inglés desde más de 40 idiomas y a chino simplificado desde 27. | Sí | Traducción solo en **PC Copilot+** con 24H2 o posterior. El Ryzen 7 8700F tiene una NPU de 16 TOPS, así que el PC del usuario no puede traducir; solo transcribe (en/ja/zh/es…), en local y sin conexión. |
| **Chrome** (Subtítulos automáticos + traducción) | No: solo texto. | Sí, a más de 100 idiomas. Entiende 19 idiomas de origen, entre ellos en/ja/zh. | **No**: solo el audio que suena en Chrome. | La transcripción es local; para traducir, en Windows/Mac/Linux los subtítulos se envían a Google. |
| Edge (traducción de vídeo en tiempo real) | Sí (doblaje) | Pocos pares, en→es incluido. | No: solo sitios compatibles. | **Retirada en Edge 152 (ago-2026).** |
| **YouTube** (doblaje automático) | Sí, pregenerado por vídeo. Voz expresiva en 8 idiomas, español incluido. | en→es sí. **ja→es y zh→es no**: el japonés y el chino solo se doblan a inglés. | No: solo vídeos de YouTube que cumplan los requisitos. | Máximo 120 min por vídeo. No se puede editar ni es en directo. |
| **Teams** (agente Interpreter) | Sí (simultáneo) | Sí: 10 idiomas, entre ellos es, ja, zh simplificado y zh tradicional. | No: solo reuniones y llamadas de Teams. | Requiere **licencia Microsoft 365 Copilot**. 20 h por usuario y mes. El modo consecutivo está en pausa desde jul-2026. |
| **Google Meet** (traducción de voz) | Sí, con una voz que imita el tono y el ritmo del orador. | Disponible: en↔es/fr/de/pt/it. En preview privada: más de 70 idiomas con Gemini 3.5. | No: solo reuniones de Meet. | Workspace Business Standard o superior, o Google AI Pro/Ultra. Un solo par de idiomas por reunión y límites de uso. |
| **Zoom** (Voice Translator, jul-2026) | Sí (voz sintética) | Sí: en, zh, es, fr, ja. | No: solo reuniones de Zoom. | Cuenta Pro/Business/Enterprise + complemento. App de escritorio 7.0 o posterior. |
| Google Traductor (móvil) | Sí (con auriculares, o por el auricular del teléfono en Android) | Sí, más de 70 idiomas. | No: móvil y micrófono. | Android/iOS, en la nube. |
| JotMe / Transync AI (comerciales) | Sobre todo subtítulos. JotMe clona la voz del propio usuario para lo que él dice. | Sí | Sí | En la nube y de pago. JotMe: gratis 20 min; 10–15 $/mes con 200–500 min. |
| **VoxisLive** | Sí | Sí: 79 idiomas de destino, 35 con voz. | **Sí**, sin cable virtual: captura el audio del sistema excluyendo su propia salida. | En la nube (Gemini Live con clave propia). 10 min/día gratis. Licencia no libre. Microsoft Store. |
| **My Translator** (MIT) | Sí (Edge TTS, Chirp, ElevenLabs) | Sí | Sí | Motores en la nube (Soniox, OpenAI, Qwen). El modo local solo funciona en Apple Silicon. Retardo declarado: ~2 s con Soniox/OpenAI, ~4 s con Qwen y ~10 s en local. |
| **Sokuji** (AGPL-3.0) | Sí (Piper, Matcha, MMS…: 53 idiomas) | Sí | Sí (versión de escritorio), con micrófono virtual. | Modo 100 % local (WASM/WebGPU): 44 modelos de ASR, Opus-MT y LLMs Qwen/Hunyuan-MT/TranslateGemma para traducir. No publica cifras de calidad ni retardo. |
| **LiveCaptions-Translator** (Apache-2.0) | No: solo texto. | Sí, vía LLM local (Ollama), DeepL o Google. | Sí | Aprovecha el reconocimiento de voz local de Live Captions **sin necesitar un PC Copilot+**. Windows 11 22H2 o posterior. |
| Voxxwire | Sí (Piper, según su web) | Sí, según su web. | Sí | Dice ser local y MIT con retardo "inferior a un segundo". **Sin verificar**: no se localizó el repositorio. |

### 2.3 Servicios E2E en la nube (solo referencia: descartados por la decisión 100 % local)

| Servicio (estado) | ¿Salida es? ¿Entrada ja/zh? | Latencia (según la fuente) | Precio oficial | Notas |
|---|---|---|---|---|
| **OpenAI gpt-realtime-translate** (disponible desde may-2026) | Sí. 13 idiomas de salida: es, pt, fr, ja, ru, zh, de, ko, hi, id, vi, it, en. Más de 70 de entrada. | Traduce en continuo y devuelve audio en trozos de 200 ms. Sin cifra oficial; ~2 s según una app de terceros. | **0,034 $/min (2,04 $/h)** | Conexión por WebRTC o WebSocket. No permite elegir voz, dar instrucciones ni usar glosario. |
| **Google Gemini 3.5 Live Translate** (preview desde jun-2026) | Sí; más de 70 idiomas. | "Unos segundos por detrás". | Entrada 0,0053 $/min + salida 0,0315 $/min: **≈2,2 $/h** | Nivel gratuito disponible. Imita la entonación del orador (de forma irregular). Conexión por WebSocket. |
| **Azure Live Interpreter** (disponible desde nov-2025) | Sí: 9 idiomas de salida (es, ja, zh-Hans…) y 76 de entrada. | "Casi a la par de un intérprete humano" (sin cifras). | Entrada 1 $/h + salida estándar 1,5 $/h: **2,5 $/h**. Salida "custom" 2 $/h; texto 10 $/1M caracteres. | Regiones en la UE (West/North Europe, France Central…). Puede usar la voz del orador (con consentimiento). |
| **Qwen3.8-LiveTranslate** (Alibaba, sep-2026) | Sí: habla 29 idiomas y entiende 60. | **LAAL 2,3 s** (según el fabricante) | 7,5 $/1M tokens de audio de entrada y 30 $/1M de salida; **≈1,5 $/h** según la prensa. | Regiones Singapur y Pekín. Pesos cerrados. |
| **DeepL Voice** (API voz→voz en acceso anticipado desde abr-2026) | Más de 40 idiomas, incluidos los 24 de la UE. ja/zh sin verificar. | "Una o dos frases" de retraso. | No publicado. | Internamente es una cascada con una voz sintética fija. |
| **Palabra.ai** | Sí; más de 60 idiomas. | "Menos de 1 s" (dato de marketing). | **0,04 $/min (2,4 $/h)** | Clonación de voz. Opción autoalojada por contrato. |
| **Soniox** (cascada gestionada) | Sí; más de 60 idiomas. | Streaming token a token. | Reconocimiento 0,12 $/h (traducción incluida, ≈0,18 $/h) + voz ≈0,70 $/h: **≈0,82–0,88 $/h** | Voz TTS v2 en más de 60 idiomas. |
| Speechmatics | Solo en→es y solo en texto. | — | Reconocimiento en tiempo real 0,24–0,43 $/h | Su TTS solo habla inglés: no sirve para voz en español. |
| ElevenLabs | No tiene producto de traducción voz→voz en directo. | Su TTS v4 Turbo tarda ~100 ms. | Scribe v2 en tiempo real 0,39 $/h; voz 0,04 $ por 1.000 caracteres (≈2,2 $/h) | Solo ofrece piezas sueltas para una cascada. |
| Seed LiveInterpret 2.0 (ByteDance) | No: solo zh↔en. | 2–3 s | — | Cerrado. |
| Modelos conversacionales genéricos (gpt-realtime-2, Gemini 3.8 Live) | Sí | — | gpt-realtime-2 ≈1,15 $/h de entrada + 4,61 $/h de salida. Gemini 3.8 Live 0,005 $/min de entrada + 0,018 $/min de salida. | No están pensados para interpretar audio continuo y cobran de nuevo el contexto acumulado. |

### 2.4 Coste por hora (breve)

Supuestos: 1 h de audio original (~9.000 palabras), ~55.000 caracteres de español generados y, como máximo, 1 h de audio de salida. Precios oficiales recogidos en esta sesión.

| Escenario | Componentes | Coste/h aprox. |
|---|---|---|
| **100 % local (decisión actual)** | RTX 5070 (consumo máximo 250 W) más el resto del equipo: ≈0,25–0,35 kWh por hora, a 0,15–0,20 €/kWh (supuesto de tarifa). | **≈0,04–0,07 €/h** (solo electricidad; estimación) |
| (a) Cascada barata en la nube | Soniox para reconocer y traducir (0,18 $/h) + Soniox para la voz (≈0,70 $/h). Alternativa: voz neuronal de Azure (55.000 × 15 $/1M = 0,83 $/h). | ≈0,9–1,0 $/h |
| (b) E2E en la nube | Qwen3.8-LT ≈1,5; gpt-realtime-translate 2,04; Gemini 3.5 LT ≈2,2; Palabra 2,4; Azure Live Interpreter 2,5. | 1,5–2,5 $/h |
| (c1) Híbrido: reconocimiento y voz en local, traducción en la nube | Un LLM barato, p. ej. Gemini 2.5 Flash-Lite a 0,10 $ (entrada) y 0,40 $ (salida) por millón de tokens. Con contexto: ~40.000 tokens de entrada y ~15.000 de salida. | < 0,02 $/h |
| (c2) Híbrido: todo local salvo la voz | Azure Neural 0,83 $/h. Gemini 3.8 Flash-Lite TTS: 6 $/1M tokens de audio hasta el 31-dic-2026 y 12 $ desde 2027; suponiendo 25 tokens/s, ≈0,54 $/h y ≈1,08 $/h. ElevenLabs Flash ≈2,2 $/h. | 0,5–2,2 $/h |

---

## 3) Detalle por opción

### 3.1 Modelos abiertos para uso local

**SeamlessStreaming (Meta).**
- **Qué es:** traductor simultáneo (Dec-2023, 2,5B parámetros). Entiende voz en unos 100 idiomas, genera texto en 96 y habla en 36. El español está entre las salidas de voz y el inglés, el japonés y el chino entre las entradas, según la tabla de idiomas de SeamlessM4T v2, en la que se basa.
- **Retardo:**
  - Meta anuncia "unos 2 s".
  - En la medición independiente del artículo de Hibiki-Zero (pares X→en), el retardo medio (LAAL) es de 2,7–3,1 s en frases cortas y de 6,2–7,3 s en discurso largo, con 2,4–3,2 s de end offset.
  - Para en→es no hay cifras publicadas; se usan las X→en como aproximación.
- **Calidad:**
  - Precisión de la traducción en discurso largo: ASR-BLEU 27,8–29,9, frente a 29,1–33,2 de Hibiki-Zero.
  - El parecido de la voz con la del orador es muy bajo: 11–16 sobre 100 en evaluación humana, frente a 50–74 de Hibiki-Zero. La voz es genérica.
- **Integración (el problema principal):**
  - `seamless_communication` fija `fairseq2==0.2.*`.
  - fairseq2 0.2.1 solo admite PyTorch 2.0 o 2.1 y Python 3.8–3.11, y "no tiene soporte nativo para Windows ni planes de tenerlo" (hay que usar WSL2).
  - La RTX 5070 necesita PyTorch 2.7 o posterior compilado con CUDA 12.8.
  - Por tanto, habría que usar WSL2 **y además** recompilar fairseq2 para un PyTorch moderno, o portar el agente de streaming. Hay usuarios que dedicaron unas 50 h a pelearse con dependencias incluso en Linux.
  - El proyecto no se actualiza desde finales de 2023.
- **VRAM:** la demo oficial se ejecuta en una T4 de 16 GB. Estimación de 6–10 GB (sin verificar), así que probablemente cabe en 12 GB. En CPU no se recomienda.
- **Licencia:** CC-BY-NC 4.0. Vale para uso personal, pero bloquea un uso comercial futuro.

**SeamlessM4T v2 large vía Hugging Face Transformers.**
- Mismo tipo de traductor (2,3B, CC-BY-NC 4.0) y **disponible en Transformers** (`SeamlessM4Tv2Model`), así que no depende de fairseq2 y debería funcionar en Windows con PyTorch moderno (sin verificar en Blackwell).
- Español, japonés y chino tienen entrada y salida de voz.
- No traduce de forma simultánea: habría que trocear el audio con un detector de voz y traducir cada trozo. El retardo sería lo que dura el trozo más la inferencia (estimado 3–6 s; sin verificar).
- En Transformers v5 desapareció el pipeline de traducción, así que hay que usar directamente las clases del modelo.
- Un artículo de mar-2026, SimulU, demuestra un modo simultáneo sin reentrenar sobre SeamlessM4T (evaluado en en→es; primer audio a ≈1–2 s), pero no ha publicado código.
- **Encaje:** motor E2E experimental o de referencia, barato de probar. La voz no será natural ni tendrá acento de España garantizado.

**SeamlessExpressive (Meta).** Conserva la prosodia y el estilo de voz del orador en inglés, español, alemán, francés, italiano y chino. **No incluye japonés**, usa una licencia propia no comercial con solicitud de acceso y la misma pila fairseq2. Descartado.

**Hibiki (feb-2025) y Hibiki-Zero (feb-2026), de Kyutai.**
- Son la referencia técnica del sector: modelos de 2,7–3B parámetros que traducen de forma simultánea y conservan la voz. Hibiki-Zero se entrenó sin datos alineados palabra a palabra.
- Hibiki-Zero cumple su propia recomendación de VRAM ("8 GB debería funcionar, 12 GB es seguro") y mejora a Seamless en calidad y en parecido de la voz.
- **Pero solo traducen hacia inglés:** Hibiki desde francés; Hibiki-Zero desde francés, español, portugués y alemán, con un experimento que añade italiano con menos de 1.000 h de datos. Ese mecanismo añade **idiomas de origen**, no de destino.
- Licencias: Hibiki CC-BY 4.0; Hibiki-Zero CC BY-NC-SA 4.0.
- El blog de Kyutai no anuncia (hasta sep-2026) ningún modelo que traduzca hacia el español. Su TTS ligero *Pocket TTS* sí habla español desde may-2026 (útil para una cascada; licencia sin verificar).

**Qwen3-Omni-30B-A3B (Alibaba, Apache 2.0).**
- Entiende voz en 18 idiomas y **habla en 10, español incluido**, y puede traducir voz si se le pide.
- Funciona **por turnos** (espera a que acabe la frase), no de forma simultánea.
- Necesita **unos 79 GB de VRAM en BF16**. Hay versiones cuantizadas en 4 bits, pero siguen muy por encima de 12 GB (estimado).
- Su sucesor Qwen3.5-Omni (mar-2026) **no ha publicado sus pesos**.
- No es viable en la RTX 5070.

**Investigación de 2026 sin producto utilizable:**
- **SimulS2ST-Omni** (jul-2026, basado en Qwen2.5-Omni): solo zh↔en y pesos no confirmados.
- **SimulU** (mar-2026): sin código.
- **Seed LiveInterpret 2.0** (ByteDance): cerrado y solo zh↔en.
- **Benchmark COMPASS** (jun-2026): concluye que entre sistemas en cascada y E2E la calidad de traducción apenas difiere; las grandes diferencias (más del 30 %) están en naturalidad y en la conservación de la voz del orador.

**Piezas abiertas para una cascada de dos etapas** (voz → texto traducido, y luego voz). Solo como pista para los informes de reconocimiento, traducción y voz:
- NVIDIA **Canary-1B-v2** (CC-BY-4.0): traduce directamente de voz inglesa a texto español, pero no admite japonés ni chino.
- Kyutai **Pocket TTS**: habla español y funciona en CPU.
- Mistral **Voxtral TTS**: habla español; unos 16 GB de VRAM con vLLM-Omni según terceros (sin verificar).

### 3.2 Servicios en la nube (resumen, descartados por ahora)

- **OpenAI gpt-realtime-translate:**
  - Modelo dedicado, lanzado el 7-may-2026.
  - Idiomas: más de 70 de entrada; 13 de salida, entre ellos español, japonés y chino.
  - Precio: **0,034 $/min** (2,04 $/h), con límites de uso por nivel de cuenta.
  - Funcionamiento: sesión continua sin turnos. Recibe audio PCM16 a 24 kHz por WebRTC o WebSocket y devuelve audio en trozos de 200 ms, además de las transcripciones de origen y destino.
  - Limitaciones: no permite elegir voz ni dar instrucciones (tampoco glosario) y puede no traducir lo que ya está en el idioma de destino.
  - No hay cifra oficial de retardo.
- **Google Gemini 3.5 Live Translate:**
  - En preview pública desde el 9-jun-2026; más de 70 idiomas, español de España incluido.
  - Recibe PCM a 16 kHz y devuelve 24 kHz, en trozos de 100 ms.
  - Imita la entonación del orador, aunque de forma irregular.
  - Precio: ≈2,2 $/h; hay nivel gratuito, en el que Google indica que los datos pueden usarse para mejorar sus productos.
  - Es la misma tecnología que Meet y Google Traductor.
- **Azure Live Interpreter:**
  - En preview desde sep-2025 y disponible desde Ignite (nov-2025).
  - Idiomas: detecta automáticamente 76 idiomas de entrada; 9 de salida, español incluido (sin verificar si la voz es de España).
  - Precio: 2,5 $/h con voz estándar; tiene regiones en la UE.
- **DeepL Voice:** la API de voz a texto salió en feb-2026 y la de voz a voz está en acceso anticipado desde abr-2026. Internamente es una cascada con voz fija y un retraso de "una o dos frases".
- **Palabra.ai:** 0,04 $/min, más de 60 idiomas, clonación de voz y retardo anunciado inferior a 1 s.
- **Soniox:**
  - Cascada gestionada: reconocimiento y traducción en la misma llamada (0,12 $/h) y voz TTS v2 (≈0,70 $/h); en total ≈0,82 $/h.
  - Sin datos de retardo en su comparativa.
- **Qwen3.8-LiveTranslate:** 19-sep-2026, LAAL 2,3 s, habla 29 idiomas, cerrado.
- **Speechmatics** (voz solo en inglés) y **ElevenLabs** (sin producto voz→voz en directo): no aportan un E2E con salida en español.

### 3.3 Aplicaciones y funciones existentes

- **Subtítulos en directo de Windows 11:**
  - Transcriben en local cualquier audio del sistema, en inglés, japonés, chino y español, entre otros.
  - Solo traducen en PCs Copilot+, que requieren una NPU de 40 TOPS o más.
  - Solo traducen **hacia inglés** (desde más de 40 idiomas) o **hacia chino simplificado** (desde 27), y nunca con voz.
  - El 8700F del usuario tiene una NPU de 16 TOPS, así que no cumple el requisito.
  - Interesante: **LiveCaptions-Translator** lee el texto de Live Captions (sin necesitar Copilot+) y lo traduce con un LLM local. Demuestra que el reconocimiento local de Windows es reutilizable, aunque de forma frágil (lectura de la ventana con UI Automation).
- **Chrome:** subtitula el audio de las pestañas en 19 idiomas y traduce los subtítulos a más de 100 (en Windows, enviándolos a Google). Solo texto y solo dentro del navegador.
- **Edge:** tuvo doblaje en directo de vídeos, retirado en Edge 152 (ago-2026).
- **YouTube:**
  - Doblaje automático abierto a todos los creadores (4-feb-2026, 27 idiomas; voz expresiva en 8, español incluido).
  - Pares: el inglés se dobla a 20 idiomas, pero el japonés y el chino **solo a inglés**, así que no cubre ja/zh→es.
  - Son pistas pregeneradas por vídeo, con condiciones de elegibilidad.
- **Teams, Meet y Zoom:**
  - Ya ofrecen **voz traducida**, pero solo dentro de sus reuniones y con licencias empresariales de pago.
  - Teams exige Microsoft 365 Copilot (20 h al mes).
  - Meet exige Workspace Business Standard o superior, o Google AI Pro/Ultra. Tiene en↔es disponible y 70+ idiomas en preview.
  - Zoom Voice Translator (22-jul-2026) cubre en, zh, es, fr y ja y requiere un complemento.
- **Apps de escritorio:**
  - **VoxisLive** hace exactamente la función central de InstantTraductor: captura el audio de otras apps con la API de Windows *ApplicationLoopback*, excluye su propia salida y lee la traducción en voz alta. Pero usa Gemini Live en la nube y su licencia no es libre.
  - **My Translator** (MIT) es igual, pero depende de la nube en Windows.
  - **Sokuji** (AGPL) es el rival local más directo: reconocimiento, traducción y voz 100 % locales con modelos pequeños en WASM/WebGPU, captura del audio del sistema y micrófono virtual. No publica cifras de calidad ni de retardo.
  - **JotMe** y **Transync** son servicios de pago en la nube, sobre todo de subtítulos.

### 3.4 ¿Qué aporta InstantTraductor frente a todo lo anterior?

1. **Voz en español de España para cualquier audio del PC**: vídeos, streams, juegos, cursos y llamadas en cualquier app, sin depender de una plataforma concreta (Teams, Meet, Zoom o YouTube).
2. **Japonés y chino → español hablado**: YouTube no lo dobla, Live Captions no traduce a español y Chrome solo da texto.
3. **100 % local y sin conexión**: privacidad, sin suscripción ni límites de minutos (Teams 20 h al mes; JotMe 200–500 min), sin claves de API ni envío de audio a terceros.
4. **Funciona en PCs sin NPU Copilot+**, aprovechando la GPU NVIDIA con modelos más grandes que los de WASM/WebGPU que usa Sokuji.
5. **Control total**: elección de una voz es-ES, bajar el volumen del original, subtítulos bilingües, glosario, equilibrio entre retardo y calidad, y captura por aplicación sin cable virtual.

**Riesgo competitivo:** Sokuji (local) y VoxisLive (nube) ya existen. La diferencia tiene que venir de una **calidad y naturalidad claramente superiores en español de España** con 1,5–3 s de retardo en la RTX 5070. Conviene compararse con Sokuji en modo local desde el principio.

---

## 4) Recomendación para InstantTraductor

**Principal: cascada local en streaming** (reconocimiento en streaming → traducción incremental → voz es-ES en streaming) como motor por defecto. Motivos:
1. No hay ningún E2E abierto que cubra ja/zh→es con calidad y voz natural y que funcione en Windows con la RTX 5070.
2. El único E2E abierto con español (Seamless) mide ≈3 s en frases y 6–7 s en discurso largo, por encima del objetivo de 1,5–3 s, y con voz genérica.
3. La pila de SeamlessStreaming es incompatible con Windows nativo y con Blackwell.
4. La cascada permite elegir la mejor pieza para cada idioma, usar glosarios y subtítulos, escoger la voz es-ES y repartir los 12 GB de VRAM.
5. El benchmark COMPASS indica que la calidad de traducción apenas cambia entre cascada y E2E; lo que marca la diferencia es la naturalidad de la voz, y eso se controla mejor con un buen TTS.

**¿Un motor E2E enchufable además de la cascada? Sí a la interfaz; no a invertir en él ahora.**
- Definir un contrato de motor común: entrada de audio PCM (con marcas de tiempo) y, como salida, eventos de texto de origen y destino (parcial y final), trozos de audio traducido y métricas de retardo.
- Así se podrán enchufar después un E2E o un servicio en la nube sin tocar la captura ni la reproducción.
- **Alternativa 1 (experimental, prioridad baja):** SeamlessM4T v2 large vía Transformers, troceando el audio.
  - Es el **único E2E local viable** para en/ja/zh→es en Windows con la RTX 5070 y su licencia CC-BY-NC vale para uso personal.
  - Sirve como punto de comparación y como plan B para idiomas exóticos.
- **Alternativa 2 (no recomendada):** SeamlessStreaming en WSL2. Solo si se acepta WSL2 y el trabajo de portar fairseq2 a PyTorch 2.7 o posterior.
- **Vigilar:**
  - la familia Hibiki, si Kyutai publica un modelo que traduzca hacia el español u otros idiomas;
  - el código de SimulU (modo simultáneo sobre M4T, evaluado en en→es);
  - los pesos de SimulS2ST-Omni;
  - cualquier variante abierta y pequeña de Qwen-Omni.
- **Si algún día se acepta la nube**, sobre la misma interfaz:
  - gpt-realtime-translate: el más sencillo; es/ja/zh; 2,04 $/h;
  - Gemini 3.5 Live Translate: tiene nivel gratuito, con cesión de datos;
  - Soniox: la cascada más barata, ≈0,85 $/h.

**Lecciones de la competencia para la cascada:**
- Capturar el audio de otras apps con la API *ApplicationLoopback* excluyendo el propio proceso, como hace VoxisLive, para evitar ecos sin cable virtual.
- Usar un LLM para traducir frases incompletas (lo recomienda LiveCaptions-Translator).
- Medir el retardo real de extremo a extremo: My Translator declara ~10 s en su modo local frente a ~2 s en la nube, así que un pipeline local mal diseñado queda muy lejos del objetivo.

---

## 5) Riesgos y preguntas abiertas

**Riesgos**
- **Retardo:** los E2E abiertos acumulan retardo en discurso largo (LAAL de 6–7 s). La cascada tendrá el mismo riesgo porque el español ocupa ~20–25 % más que el inglés. Habrá que acelerar la voz o condensar la traducción.
- **Compatibilidad:**
  - fairseq2 0.2 solo admite PyTorch ≤2.1 y no funciona en Windows, frente al sm_120 de la RTX 5070 (PyTorch ≥2.7 con CUDA 12.8).
  - SeamlessM4T en Transformers v5 no está probado en Blackwell (sin verificar).
- **Licencias:** Seamless (CC-BY-NC), Hibiki-Zero (CC BY-NC-SA) y el código de Sokuji (AGPL) valen para uso personal, pero impedirían una futura versión comercial si se integran.
- **Eco:** reproducir la voz mientras se captura el audio del sistema requiere excluir el proceso propio o usar otro dispositivo de salida.
- **Mercado cambiante:**
  - Meet pasa a más de 70 idiomas.
  - Windows podría añadir el español como destino de Live Captions.
  - Es posible que Chrome o YouTube amplíen el doblaje (sin verificar; no se pudo buscar más porque se agotó el presupuesto de búsquedas web).
- **Clonación de voz:** si algún día se imita la voz del orador, hay consentimiento y términos de uso que respetar (Hibiki-Zero prohíbe la suplantación).

**Datos sin verificar:**
- la VRAM exacta de SeamlessStreaming;
- el retardo real de Seamless en en→es y en la RTX 5070;
- las cifras oficiales de retardo de OpenAI y Azure;
- si la voz española de Azure es de España o de México;
- si DeepL Voice cubre ja/zh;
- lo que afirma Voxxwire;
- el rendimiento real de Sokuji en modo local.

**Preguntas para el usuario**
1. ¿Son aceptables ~3 s de retardo, o el objetivo real es ≤2 s?
2. ¿Voz fija es-ES o imitar la voz del orador?
3. ¿Subtítulos además de voz?
4. ¿Bajar el volumen del audio original o silenciarlo?
5. ¿Qué fuentes son prioritarias (YouTube/Twitch, juegos, reuniones, clases)?
6. ¿Se acepta WSL2 como dependencia opcional para motores experimentales?
7. ¿Se contempla en el futuro un modo en la nube opcional, por ejemplo el nivel gratuito de Gemini con aviso de privacidad, o queda descartado del todo?

**Siguiente paso sugerido:** una batería de pruebas en la RTX 5070 que mida retardo (primer audio, LAAL y end offset), calidad (COMET o ASR-BLEU frente a una referencia) y naturalidad (escucha subjetiva) de cada motor. Comparar SeamlessM4T v2 por trozos, la cascada candidata y Sokuji en modo local.

---

## 6) Fuentes (URL)

**OpenAI**
- https://developers.openai.com/api/docs/models/gpt-realtime-translate
- https://developers.openai.com/api/docs/guides/realtime-translation
- https://developers.openai.com/cookbook/examples/voice_solutions/realtime_translation_guide
- https://community.openai.com/t/new-realtime-voice-models-in-the-api/1380471
- https://openai.com/index/advancing-voice-intelligence-with-new-models-in-the-api/ (403 al acceder; datos confirmados vía docs y foro)
- https://www.marktechpost.com/2026/05/08/openai-releases-three-realtime-audio-models-gpt-realtime-2-gpt-realtime-translate-and-gpt-realtime-whisper-in-the-realtime-api/ (secundaria)
- https://www.latent.space/p/ainews-gpt-realtime-2-translate-and (secundaria)

**Google**
- https://ai.google.dev/gemini-api/docs/live-api/live-translate
- https://ai.google.dev/gemini-api/docs/pricing
- https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-live-3-5-translate/
- https://blog.google/innovation-and-ai/technology/developers-tools/build-real-time-voice-applications-gemini-audio/
- https://9to5google.com/2026/06/09/gemini-3-5-live-translate-meet/ (secundaria)

**Microsoft / Azure**
- https://prices.azure.com/api/retail/prices (consultas: medidores "Live Interpreter" y "Azure Speech" S1 en westeurope)
- https://azure.microsoft.com/en-us/pricing/details/speech/
- https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/announcing-live-interpreter-api---now-in-public-preview/4453649
- https://argonsys.com/microsoft-cloud/library/advancing-speech-innovation-with-azure-speech-in-microsoft-foundry/ (réplica del blog de Microsoft)

**DeepL, Palabra, Soniox, Speechmatics, ElevenLabs**
- https://developers.deepl.com/api-reference/voice
- https://thenextweb.com/news/deepl-voice-to-voice-real-time-spoken-translation
- https://multilingual.com/deepl-launches-voice-api-real-time-speech-transcription-multilingual-communication/
- https://www.palabra.ai/pricing
- https://www.palabra.ai/voice-translation-api
- https://soniox.com/pricing
- https://soniox.com/speech-translation
- https://soniox.com/compare-translation
- https://soniox.com/text-to-speech
- https://www.usagepricing.com/blueprint/activity/speechmatics-2026-07-06-realtime-stt-price-cut (secundaria)
- https://docs.speechmatics.com/introduction/supported-languages
- https://www.speechmatics.com/text-to-speech
- https://elevenlabs.io/pricing/api
- https://elevenlabs.io/v4
- https://releasebot.io/updates/eleven-labs (secundaria)

**Alibaba / ByteDance**
- https://www.alibabacloud.com/help/en/model-studio/qwen3-8-livetranslate-flash-realtime
- https://www.qwencloud.com/models/qwen3.8-livetranslate-flash-realtime
- https://www.marktechpost.com/2026/09/19/alibaba-qwen-team-releases-qwen3-8-livetranslate/ (secundaria)
- https://seed.bytedance.com/en/blog/seed-liveinterpret-2-0-released-an-end-to-end-simultaneous-interpretation-model-featuring-ultra-high-accuracy-close-to-human-interpreters-low-latency-of-3-seconds-and-real-time-voice-cloning

**Meta Seamless y compatibilidad**
- https://huggingface.co/facebook/seamless-streaming
- https://huggingface.co/facebook/seamless-m4t-v2-large
- https://huggingface.co/spaces/facebook/seamless-streaming/blob/main/README.md
- https://huggingface.co/facebook/seamless-streaming/discussions/22
- https://github.com/facebookresearch/seamless_communication
- https://raw.githubusercontent.com/facebookresearch/seamless_communication/main/setup.py
- https://github.com/facebookresearch/fairseq2/blob/v0.2.1/README.md
- https://ai.meta.com/research/seamless-communication/
- https://arxiv.org/abs/2312.05187
- https://discuss.pytorch.org/t/nvidia-geforce-rtx-5070-ti-with-cuda-capability-sm-120/221509 (sm_120 requiere PyTorch ≥2.7 + CUDA 12.8)
- https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5070-family/ (TGP 250 W, 12 GB)

**Kyutai, Qwen-Omni y otros modelos abiertos**
- https://github.com/kyutai-labs/hibiki-zero
- https://huggingface.co/kyutai/hibiki-zero-3b-pytorch-bf16
- https://arxiv.org/html/2602.11072v2 (tablas de latencia Seamless vs Hibiki-Zero)
- https://huggingface.co/kyutai/hibiki-2b-pytorch-bf16
- https://kyutai.org/blog/
- https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct
- https://nvidia.github.io/TensorRT-Edge-LLM/latest/user_guide/examples/omni.html
- https://www.datalearner.com/en/ai-models/pretrained-models/qwen3-5-omni-flash (secundaria: Qwen3.5-Omni sin pesos abiertos)
- https://arxiv.org/html/2607.19810 (SimulS2ST-Omni)
- https://arxiv.org/html/2603.16924 (SimulU)
- https://arxiv.org/abs/2606.03241 (COMPASS)
- https://huggingface.co/nvidia/canary-1b-v2

**Aplicaciones y funciones existentes**
- https://support.microsoft.com/en-us/accessibility/windows/use-live-captions-to-better-understand-audio
- https://www.guru3d.com/story/these-are-the-details-of-the-amd-ryzen-7-8700f-and-ryzen-5-8400f-desktop-processors/ (secundaria: NPU de 16 TOPS del 8700F; la ficha de AMD no respondió)
- https://support.google.com/chrome/answer/10538231?hl=en
- https://thewincentral.com/microsoft-edge-real-time-video-translation-retired/ (secundaria)
- https://blog.youtube/news-and-events/youtube-auto-dubbing-expressive-speech/
- https://support.google.com/youtube/answer/15569972?hl=en
- https://blog-en.topedia.com/2026/05/interpreter-agent-in-teams-now-supports-a-new-consecutive-interpretation-mode/ (secundaria)
- https://blog-en.topedia.com/2026/01/interpreter-agent-is-now-available-in-teams-calls/ (secundaria)
- https://workspaceupdates.googleblog.com/2026/02/speech-translation-meet-ga.html
- https://www.zoom.com/en/blog/voice-translation-zoom/
- https://www.jotme.io/blog/windows-live-translator
- https://dev.to/davutakca/translating-windows-system-audio-in-real-time-driverless-with-no-virtual-cable-2842
- https://github.com/DavutAkca/voxislive
- https://github.com/phuc-nt/my-translator
- https://github.com/kizuna-ai-lab/sokuji
- https://github.com/SakiRinn/LiveCaptions-Translator
- https://voxxwire.com/articles/best-free-offline-translation-tools-windows.html (afirmaciones sin verificar)
