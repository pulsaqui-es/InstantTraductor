# 03 · Traducción automática (MT) y voz en español (TTS) — InstantTraductor

*Investigación a 30-sep-2026. Alcance revisado por el coordinador durante la investigación: **app 100 % local, uso personal** (las licencias no comerciales son candidatas válidas); la nube queda como tabla breve de curiosidad (solo cuotas gratuitas permanentes).*

**Leyenda de fiabilidad de las cifras**
- **[F]** dato del fabricante o de la documentación oficial (model card, repositorio, docs).
- **[3]** fuente secundaria (prensa, blogs, comparativas o tablas publicadas por un competidor).
- **[E]** estimación propia (a partir del tamaño del modelo y de los 672 GB/s de la RTX 5070). **Hay que medirla antes de decidir.**
- **(s/v)** sin verificar.

---

## 1) Resumen ejecutivo

1. **MT: Hy-MT2** (Tencent, may-2026, **Apache 2.0**): **1.8B Q8** (~2 GB, ~0,1–0,2 s/frase [E]) por defecto; **7B Q4** (~5 GB) si sobra VRAM.
2. **Descartados Hunyuan-MT-7B y HY-MT1.5** (su licencia **no se aplica en la UE**). Alternativas: Qwen3.5-4B/9B, TranslateGemma-4B, Gemma 4 E4B; **Opus-MT** (CTranslate2) de respaldo en CPU.
3. **TTS principal (validar): Chatterbox Multilingual V3 + *finetune* es-ES** (MIT; único checkpoint abierto de castellano; ~3,5 GB; clonación).
4. **Alternativas TTS:** **XTTS-v2** (no comercial, *streaming* <200 ms, ~2 GB), **Qwen3-TTS-0.6B** (Apache, voz castellana clonada); en CPU: **Piper es_ES**, Kokoro, OneCore.
5. **VRAM:** ASR 2–3 GB + Hy-MT2-1.8B ~2,5 + Chatterbox ~3,5 + Windows ~0,7 ≈ **9–10 GB de 12**.
6. **Simultaneidad:** traducir **cláusulas confirmadas** (puntuación o pausa; tope ~2 s o 12–15 palabras) con LLM + contexto + glosario; **nunca re-traducir audio ya emitido**.
7. **Ritmo:** velocidad nativa ≤1,25× + *time-stretch* Sonic (Apache 2.0) + traducción más concisa y pausas recortadas si hay retraso.
8. **Retardo realista:** **en→es 2–3 s; ja/zh→es 3–5 s** (el japonés obliga a esperar al verbo final).
9. **Riesgos:** Blackwell sm_120 + Windows + Python 3.13 (un entorno por motor); latencia de Chatterbox en PyTorch por medir; modelos de 2026 inmaduros.

---

## 2) Tablas comparativas

### 2.1 Traducción local (en→es prioritario; ja/zh→es después)

Las latencias se refieren a una frase o cláusula de 10–20 palabras en la RTX 5070 con el modelo ya cargado. Como referencia, Llama-3.1-8B Q4_K_M rinde ~80–93 tok/s en esta GPU [3].

| Modelo (fecha) | Tipo | Licencia · ¿uso personal? · ¿comercial? | Pares | Calidad (dato disponible) | Latencia/frase [E] | VRAM aprox. | Contexto / glosario | Runtime en Windows |
|---|---|---|---|---|---|---|---|---|
| **Hy-MT2-1.8B** (21-may-2026) | LLM especializado en MT | **Apache 2.0** · ✔ · ✔ | 33 idiomas (en, ja, zh, es…) | "Supera en conjunto a las API comerciales de Microsoft y Doubao" [F]. Index-Translate-2B dice superarlo en todas sus métricas [3] | **0,1–0,2 s** | Q8_0 1,91 GB · Q4_K_M 1,13 GB [F] (+0,3–0,6 GB de KV y contexto CUDA [E]) | **Sí**: plantillas oficiales de terminología, contexto y estilo [F] | llama.cpp (GGUF oficial), transformers ≥5.6 |
| **Hy-MT2-7B** (21-may-2026) | LLM-MT | **Apache 2.0** · ✔ · ✔ | 33 | 96,9 % de Gemini 2.5 Pro en FLORES-200 [3]. FLORES COMET-22 0,8747 (tabla de Index) [3] | 0,3–0,5 s | Q4_K_M 4,62 GB · Q6_K 6,16 · Q8_0 7,98 [F] | Sí | Igual |
| Hunyuan-MT-7B / HY-MT1.5 (2025) | LLM-MT | Tencent HY Community License: **"no se aplica en la UE, Reino Unido ni Corea del Sur"** [F] · ✘ · ✘ | 33–36 | Campeón de WMT25 [F] | — | — | — | **Descartado por licencia** |
| **TranslateGemma 4B/12B** (15-ene-2026) | LLM-MT (Gemma 3) | Gemma Terms · ✔ · ✔ (con política de uso) | 55 idiomas | 4B: MetricX 5,32 / COMET 81,6 en WMT24++ [F]. El 12B supera a Gemma 3 27B [F]. 12B: FLORES COMET-22 0,8732 [3] | 4B 0,2–0,3 s · 12B 0,5–0,8 s | 4B 3,3 GB · 12B 8,1 GB (Ollama) [F] | Plantilla rígida; entrada de 2K tokens [F] | Ollama, llama.cpp |
| Index-Translate-2B/9B (sep-2026) | LLM-MT (base Qwen3.5) | Apache 2.0 · ✔ · ✔ | 150 | FLORES COMET-22: 2B 0,8655; 9B 0,8789. WMT24++ 2B: 0,8489 [F] | 2B ~0,15 s · 9B 0,4–0,6 s | 2B ~8 GB en BF16 [F] (cuantizado ~1,5–2 GB [E]) · 9B ~24 GB en BF16 [F] | Sí (fuerte en seguir instrucciones) [F] | transformers; GGUF (s/v). **Tiene días de vida** |
| Seed-X-PPO-7B (jul-2025) | LLM-MT (Mistral) | OpenMDW · ✔ · ✔ | 28 | "A la par o por encima de Gemini-2.5/GPT-4" en evaluación humana [F] | 0,3–0,5 s | ~4,5 GB Q4 [E]; AWQ/GPTQ oficiales [F] | Limitado (formato con etiqueta `<es>`) | llama.cpp (GGUF de la comunidad), transformers |
| Tower+ 2B/9B (jun-2025) | LLM-MT (Gemma 2) | CC-BY-NC-SA 4.0 · ✔ · ✘ | 22+ | 9B: XCOMET-XXL 84,38 en WMT24++ (24 pares) [3] | 0,3–0,5 s | 9B ~5,5 GB Q4 [E] | Sí | llama.cpp |
| SalamandraTA-7B v3 (BSC) | LLM-MT | **GPL-3** en los pesos de la v3 [F] · ✔ · ⚠ | 40 (es, ca, gl, eu…) | FLORES+ EN→XX: 37,95 BLEU de media [F] | 0,3–0,5 s | ~4,5 GB Q4 [E] | Sí (nivel documento) [F] | llama.cpp / vLLM |
| EuroLLM-9B-Instruct | LLM de la UE | Apache 2.0 · ✔ · ✔ | 35 | Base del mejor sistema simultáneo de IWSLT 2025 (CUNI) [F] | 0,4–0,6 s | ~5,5 GB Q4 [E] | Sí | llama.cpp, CTranslate2 |
| Qwen3.5-4B / 9B (feb–mar 2026) | LLM generalista | Apache 2.0 · ✔ · ✔ | 201 | 4B: 66,6 XCOMET-XXL de media en WMT24++ (55 idiomas) [F]. 9B: FLORES COMET-22 0,8316 (tabla de Index) [3] | 4B 0,2–0,3 s · 9B 0,4–0,6 s | 4B ~2,7 GB · 9B ~5,5–6 GB en Q4 [E] | Sí (desactivar *thinking*) [F] | llama.cpp / Ollama |
| Gemma 4 E4B (abr-2026) | LLM multimodal | **Apache 2.0** · ✔ · ✔ | 140+ | Sin benchmark de MT publicado. **Acepta audio y devuelve texto traducido** [F] | 0,2–0,4 s | ~3–5 GB Q4 [E] | Sí | llama.cpp / Ollama |
| Ministral 3 8B (dic-2025) | LLM generalista | Apache 2.0 · ✔ · ✔ | ~11 (es, ja, zh) | Sin benchmark de MT [F] | ~0,4 s | ~5 GB Q4 [E] | Sí | llama.cpp |
| **Opus-MT en-es / ja-es** (2020) | NMT Marian (~75M, s/v) | Apache 2.0 · ✔ · ✔ | en→es, ja→es. **No existe zh→es directo**: hay que pasar por inglés | en-es: BLEU 54,9 (Tatoeba) y 35,0 (newstest2013). ja-es: 34,6 (Tatoeba) [F] | **10–30 ms en GPU; 30–100 ms en CPU int8** | 0,2–0,5 GB, o CPU | No | CTranslate2 (MIT) |
| NLLB-200 600M/1.3B/3.3B | NMT | CC-BY-NC 4.0; "no publicado para producción" [F] · ✔ · ✘ | 200 | En la tabla multi-dirección de SalamandraTA (WMT24++) queda por debajo de MADLAD-7B y de los LLM de MT [3] | 50–200 ms | 0,6–3,5 GB int8 [E] | No (solo frases, ≤512 tokens) [F] | CTranslate2 |
| MADLAD-400 3B/7B/10B | NMT (T5) | Apache 2.0 · ✔ · ✔ | 400+ | Bueno para una NMT; inferior a los LLM de MT de 2025–26 [3] | 0,1–0,3 s | 3B ~3 GB int8; 7B ~7 GB [E] | No | CTranslate2 |
| M2M100 418M/1.2B (2020) | NMT | MIT · ✔ · ✔ | 100 | Superado por NLLB y MADLAD [E] | 50–100 ms | 0,5–1,3 GB [E] | No | CTranslate2 |
| SeamlessM4T v2 (texto) | Multitarea, 2,3B | CC-BY-NC 4.0 · ✔ · ✘ | 96 (texto) | ~Nivel NLLB (s/v) | 0,2–0,4 s | ~5–6 GB fp16 [E] | No | PyTorch / transformers |

**Cómo leer las cifras de calidad.** Los valores de FLORES y WMT24++ son **medias sobre muchos idiomas**. No he encontrado ningún benchmark público específico de en→**es-ES** para estos modelos. Para un par de muchos recursos como en→es, las diferencias entre los LLM de MT modernos son pequeñas. En la práctica pesan más cuatro cosas:
- seguir instrucciones (variante peninsular, glosario, contexto);
- no añadir explicaciones;
- la robustez ante los errores del ASR;
- la latencia.

En la misma tabla de terceros (Index-Translate), los modelos de MT locales quedan al nivel de los modelos en la nube de 2026. Por ejemplo: Hy-MT2-7B 0,8747 frente a Gemini 3.5 Flash-Lite 0,8750 y GPT-5.6-Sol 0,8650 [3].

### 2.2 Síntesis de voz local en español

| Motor (fecha) | Licencia (código / pesos) | Español de España | Naturalidad [juicio] | Primer audio / RTF | *Streaming* | Control de velocidad | VRAM | Clonación | Notas |
|---|---|---|---|---|---|---|---|---|---|
| **Chatterbox Multilingual V3 + *finetune* `es-es`** (Resemble; HF jun-2026) | MIT / MIT [F] | **Sí: checkpoint dedicado a castellano**, con "control de calidad es-ES más estricto" [F] | Alta (validar de oído) | ~0,56 s de media en CLI con CUDA (implementación ggml de NVIDIA; no se indica el modelo); con carga gráfica 3D, ~1–1,3 s [F]. Turbo va ~2× más rápido pero solo en inglés [F] | Por fragmentos, no token a token [F] | `cfg_weight` (0,3–0,5 más lento; 1–3 más rápido) [F], más *time-stretch* | **~3,5 GB** [F] | Sí (~10 s de referencia) [F] | Marca de agua Perth. Python 3.11. Blackwell: torch 2.9+cu128 [F] |
| **XTTS-v2** (Coqui, 2023; fork de Idiap) | MPL-2.0 / **CPML, no comercial** [F] | Sí, clonando una referencia castellana | Media-alta | **<200 ms** [F] | **Sí** (`inference_stream`) | `speed` (produce artefactos lejos de 1,0) [F] | ~2 GB [3] | Sí (6 s) [F] | coqui-tts funciona con Python 3.10–3.14 [F] |
| **Qwen3-TTS 0.6B/1.7B** (22-ene-2026) | Apache 2.0 / Apache 2.0 [F] | Español sí; castellano solo clonando (las 9 voces preset no son hispanas) | Alta. WER en español: 1,13–1,49 [F] | 97 ms al primer paquete (*paper*) [F]. **El código oficial de *streaming* no se publicó**; hay un *fork* comunitario (~6× más rápido) [3] | Mediante el *fork* | Por instrucciones (CustomVoice/VoiceDesign) [F] | ~4 GB (0.6B) / ~6 GB (1.7B) [3] | Sí (3 s) [F] | El *fork* documenta Windows con torch cu130 y flash-attn |
| **Fun-CosyVoice3 0.5B** (dic-2025) | Apache 2.0 / Apache 2.0 [F] | Español sí; castellano clonando | Alta (CER zh 0,81 %, WER en 1,68 % con RL) [F] | ~150 ms (*bi-streaming*) [F] | **Sí** (entra texto y sale audio en *streaming*) | Instrucción de velocidad [F] | 3–4 GB [E] | Sí | Python 3.10 con conda; orientado a Linux |
| **IndexTTS-2.5** (10-ago-2026) | Licencia de uso de bilibili (para uso comercial hay que contactar) [F] | Español sí (versión nueva) | Alta (s/v en español) | RTF 0,21 en RTX 4090 [F] | No documentado | **`duration_factor` de 0,5 a 2,0×** [F] | 4–6 GB [E] | Sí | Requiere CUDA ≥12.8 y uv; DeepSpeed da problemas en Windows [F] |
| F5-TTS + **F5-Spanish** | MIT / base CC-BY-NC; el *finetune* declara CC0 [F] | Incluye español peninsular (218 h mezcladas con variedades americanas) [F] | Media-alta | RTF 0,04 y 253 ms en una L20 [F] | No (por trozos o socket) | `speed` | 2–3 GB [E] | Sí | Necesita audio de referencia limpio |
| OmniVoice 0.6B (abr-2026) | Apache / **CC-BY-NC** [F] | Diseño de voz con atributo de "dialecto/acento" [F] | ? | RTF 0,025 [F] | No | ? | 2–3 GB [E] | Sí | Muy nuevo |
| OpenAudio S1-mini 0.5B | — / CC-BY-NC-SA 4.0 [F] | Español sí | Alta (medida en inglés) | ? | Servidor Fish | No | 2–4 GB [E] | Sí | 13 idiomas |
| **Kokoro-82M** | Apache 2.0 [F] | 3 voces (ef_dora, em_alex, em_santa) **sin nota de calidad**; fonemas con espeak-ng `es` [F] | Media-baja en español; se reporta acento extranjero [3] | Muy rápido (~100× tiempo real en GPU) [3] | Sí (generador por fragmentos) [F] | `speed` [F] | <1 GB de pesos. 2,4–4 GB con Kokoro-FastAPI [F]. O CPU | No | Requiere instalar espeak-ng (MSI) en Windows [F] |
| **Piper** (piper1-gpl) | GPL-3.0 / voces CC0, dominio público o CC-BY [F] | **Castellano nativo**: davefx (medium), sharvard (medium, 2 voces), carlfm (x_low), mls_9972 y mls_10246 (low) [F] | Media-baja (VITS, algo robótica) | Muy rápido en CPU [E] | Sí (fragmentos por frase) [F] | `length_scale` [F] | 0 (CPU); CUDA opcional [F] | No | `pip install piper-tts` |
| Supertonic 2 / 3 | MIT / OpenRAIL-M [F] | Español sí (acento s/v) | Media (s/v) | RTF 0,012–0,015 en CPU (M4 Pro) [F] | No | ? | 0 (CPU, ONNX) | No | 66M / 99M parámetros |
| MeloTTS | MIT [F] | ES (acento s/v) | Media-baja | Tiempo real en CPU [F] | No | `speed` [F] | 0 | No | Mantenimiento escaso |
| Voces OneCore de Windows (Helena, Laura, Pablo) | Del sistema operativo | Castellano nativo | Baja-media | Inmediato | Sí | `SpeakingRate` 0,5–6,0 y SSML [F] | 0 | No | API WinRT; las voces "naturales" no tienen API oficial |
| *Voxtral TTS 4B* (mar-2026) | CC-BY-NC [F] | Español sí; 20 voces | Alta | 70 ms, RTF 0,103 [F] | Sí | ? | **≥16 GB** [F] | Sí | **No cabe**; necesita vLLM-Omni (Linux) |
| *VoxCPM2 2B* | Apache 2.0 [F] | 30 idiomas | Alta (s/v) | RTF ~0,3 en 4090 [F] | Sí | Por estilo | **~8 GB** [F] | Sí | No cabe junto al ASR y la MT |
| *Fish S2 Pro (5B)* / *Higgs TTS 3 (4B)* | Licencias de investigación / no comerciales [F] | Español (tier 2 / WER <5 %) | Alta | ~100 ms (H200) / <1 s | Sí | — | >10 GB [E] | Sí | No caben |
| *Orpheus 3B es_it* (abr-2025) | Apache (según la card), sobre Llama 3.2 [F] | s/v | s/v | ~200 ms [F] | Sí | No | ~6–7 GB fp16 [E] | Sí | *Research preview*; acceso restringido (*gated*) |
| *Magpie TTS Multilingual 357M* (jul-2026) | NVIDIA Open Model License (uso comercial) [F] | es (variante no indicada) | s/v | ~120 ms [3] | s/v | s/v | s/v | No (5 voces) | Usa NeMo (Linux) |
| *VibeVoice-Realtime 0.5B* | MIT, uso de investigación [F] | Español "experimental" [F] | — | ~300 ms [F] | Sí | — | — | — | Solo es fiable en inglés |

### 2.3 Combinaciones que caben en 12 GB (con el ASR)

Cada proceso con CUDA propio suma ~0,3–0,5 GB de contexto [E]. Windows, el escritorio y el navegador se llevan ~0,5–1 GB.

| Perfil | ASR | MT | TTS | VRAM total aprox. | Comentario |
|---|---|---|---|---|---|
| **A · Principal ("voz de calidad")** | 2–3 GB | **Hy-MT2-1.8B Q8_0** (~2,5 GB con KV y contexto) | **Chatterbox es-ES** (~3,5 GB) | **~9–10 GB** | Todo con licencias permisivas (Apache/MIT). Margen de 2–3 GB |
| B · "Traducción de más calidad" | 2–3 | **Hy-MT2-7B Q4_K_M** (~5,3 GB) | Piper o Kokoro en CPU (0), o Kokoro en GPU (~1) | ~8,5–10 GB | Con XTTS (2 GB) queda al límite (~11–12 GB) |
| C · "Latencia mínima" | 2–3 | Hy-MT2-1.8B Q4 (~1,6) u Opus-MT CT2 (~0,4) | XTTS-v2 (~2,3) o Kokoro (~1) | ~5–7 GB | Buena opción si la GPU se comparte |
| D · "Ligero / jugando" | ASR pequeño (1–2) | Opus-MT en CPU (0) | Piper en CPU (0) | ~1–2 GB | Calidad justa pero muy estable |
| No caben | — | TranslateGemma-12B, Index-Translate-9B BF16, EuroLLM-22B | Voxtral, VoxCPM2, Fish S2 Pro, Higgs 3 | — | — |

### 2.4 Nube: solo como curiosidad (cuotas gratuitas permanentes)

| Servicio | Tipo | Cuota gratuita permanente | Observaciones |
|---|---|---|---|
| Azure Translator (F0) | MT | 2 M caracteres/mes [F] | El plan S1 cuesta 10 $/M [3] |
| Google Cloud Translation (NMT) | MT | 500 k caracteres/mes (crédito de 10 $) [3] | Después, 20 $/M |
| DeepL API ("Developer") | MT | En 2026 las fuentes describen **1 M de caracteres no renovable**; antes, el API Free daba 500 k/mes [3] | Contradictorio: la página oficial no se pudo leer (s/v) |
| Gemini API (Flash / Flash-Lite, Flash TTS) | MT (LLM) y TTS | Capa gratuita con límites de uso [F] | **Los datos se usan para mejorar productos** [F] |
| Azure Speech (F0) | TTS | 0,5 M caracteres/mes con voces neuronales [3] | Tiene voces neuronales es-ES |
| Google Cloud TTS | TTS | 4 M/mes en Standard y WaveNet; 1 M/mes en Neural2, Studio y Chirp 3 HD [3] | — |
| ElevenLabs Free | TTS | 10 k créditos/mes [3] | Sin uso comercial; exige atribución |
| edge-tts (no oficial) | TTS | Gratis y sin cuenta | Usa el "Leer en voz alta" de Edge. GPL-3 [F]. **No es local**; puede romperse y su encaje en los términos de servicio es dudoso |
| Amazon Translate / Polly | MT / TTS | Solo 12 meses (no es permanente) [3] | — |

---

## 3) Detalle por opción

### 3.1 Traducción con NMT clásica

**Opus-MT / MarianMT (Helsinki-NLP) con CTranslate2**
- **Qué es.** Modelos Marian pequeños por par de idiomas: `opus-mt-en-es` (Apache 2.0, 2020) y `opus-mt-ja-es` (Apache 2.0) [F].
  - **No hay `opus-mt-zh-es`** (el repositorio no existe o no es accesible). Para zh→es hay que pivotar zh→en→es (`opus-mt-zh-en` sí existe) o usar un LLM.
- **Calidad.** en-es: BLEU 54,9 en Tatoeba y 35,0 en newstest2013. ja-es: BLEU 34,6 en Tatoeba [F].
  - Tatoeba contiene frases cortas y limpias; con habla espontánea y errores de ASR rinde bastante peor.
  - Mezcla variantes del español (no hay forma de forzar la peninsular).
  - No usa contexto ni glosario.
- **Rendimiento.** CTranslate2 (MIT) con int8/fp16: ~7.500–9.300 tokens/s en lote sobre una A10G, con ~1 GB de VRAM; en CPU con 4 hilos, ~700 tokens/s [F]. En la práctica, **10–30 ms por frase en GPU y 30–100 ms en CPU** [E].
  - Conversión: `ct2-transformers-converter --model Helsinki-NLP/opus-mt-en-es --quantization int8`.
- **Papel en InstantTraductor.** Red de seguridad instantánea en CPU (perfil D y *failover* si el LLM se atasca) y línea base para las pruebas A/B.

**NLLB-200 (Meta)**
- **Licencia.** CC-BY-NC 4.0; Meta advierte que "no se publicó para producción" y que solo traduce frases de ≤512 tokens [F]. Para uso personal vale.
- **Tamaños y cobertura.** Destilados de 600M y 1.3B, más el de 3.3B. Cubre 200 idiomas, entre ellos ja y zh.
- **Calidad.** Sólida pero por detrás de MADLAD-7B y de los LLM de MT en comparativas recientes [3]. Sin contexto.
- **Veredicto.** Útil solo si hiciera falta un idioma raro; para en/ja/zh→es no aporta frente a Hy-MT2.

**MADLAD-400 (Google)**
- **Licencia y formato.** Apache 2.0; tamaños 3B, 7.2B y 10.7B; se indica el idioma con el prefijo `<2es>` [F]. CTranslate2 lo soporta [F].
- **Encaje.** El 3B en int8 (~3 GB) cabe; el 7B, no, junto a lo demás.
- **Calidad.** Buena para una NMT, pero sin contexto ni instrucciones. Google lo define como "modelo de investigación" [F].

**M2M100 (Meta, 2020)**
- MIT, 418M y 1.2B, 100 idiomas [F]. Superado por NLLB y MADLAD; solo tendría sentido como opción MIT muy ligera.

**SeamlessM4T v2 (texto)**
- CC-BY-NC 4.0 y 2,3B parámetros. Hace T2TT en 96 idiomas y también S2ST directo [F].
- Es pesado porque carga los módulos de voz, no admite contexto y su voz de salida (S2ST) es de 2023. **No recomendado.**

### 3.2 Traducción con LLM especializados en MT

**Hy-MT2 (Tencent Hunyuan): recomendado**
- **Qué es.** Publicado el 21-may-2026 en tres tamaños: 1.8B, 7B y 30B-A3B (MoE). Traduce entre 33 idiomas [F].
- **Licencia.** **Apache 2.0**, verificada en el `LICENSE.txt` del repositorio. **No hereda la exclusión de la UE** de las versiones anteriores.
- **Calidad.**
  - Los modelos de 7B y 30B "superan a DeepSeek-V4-Pro y Kimi K2.6 en modo *fast-thinking*"; el de 1.8B "supera en conjunto a las API de Microsoft y Doubao" [F].
  - En FLORES-200, el 7B y el 30B alcanzan el 96,9 % y el 98,1 % de Gemini 2.5 Pro [3].
  - En la tabla de un competidor (Index-Translate), el 7B saca 0,8747 de COMET-22 en FLORES, frente a 0,8732 de TranslateGemma-12B y 0,8316 de Qwen3.5-9B [3].
- **Plantillas y parámetros.**
  - Hay plantillas oficiales para: traducción normal, **terminología** (se dan traducciones de referencia antes del texto), **contexto** (información de fondo), **estilo** y datos estructurados [F]. Encajan muy bien con la interpretación simultánea: contexto de lo ya dicho, glosario y "español de España, tuteo".
  - Parámetros recomendados: temperatura 0,7, top_p 0,6, top_k 20, penalización de repetición 1,05 [F]. En simultánea conviene probar también una temperatura baja (0–0,3) para ganar estabilidad [E].
- **GGUF oficiales.**
  - 7B: Q4_K_M 4,62 GB, Q6_K 6,16 GB y Q8_0 7,98 GB.
  - 1.8B: Q4_K_M 1,13 GB, Q6_K 1,47 GB y Q8_0 1,91 GB [F].
  - La card cita la PR #22836 de llama.cpp. Esa PR solo añade la cuantización ternaria STQ1_0 (1,25 bits, **solo ARM**, todavía abierta) y **no afecta a Q4_K_M ni a Q8_0** [F]. Que la arquitectura esté soportada en llama.cpp estándar es muy probable, porque ya había GGUF de HY-MT1.5 (s/v; comprobar).
- **Riesgo.** El modelo tiene cuatro meses; conviene medir a qué español tiende por defecto (peninsular o neutro) y fijarlo por instrucción.

**Hunyuan-MT-7B / Hunyuan-MT-Chimera / HY-MT1.5 (1.8B y 7B, dic-2025): descartados**
- Usan la "Tencent HY Community License Agreement": *"THIS LICENSE AGREEMENT DOES NOT APPLY IN THE EUROPEAN UNION, UNITED KINGDOM AND SOUTH KOREA"*. Su "Territory" excluye la UE [F].
- Sin licencia válida en España no se pueden usar, ni siquiera para uso personal. Su sucesor Apache (Hy-MT2) resuelve el problema.

**TranslateGemma (Google, 15-ene-2026)**
- **Qué es.** Tamaños 4B, 12B y 27B sobre Gemma 3, afinados con SFT más RL (recompensas MetricX-QE y AutoMQM). Cubre 55 idiomas y se entrenó con ~500 pares adicionales [F].
- **Calidad.** El 12B supera a Gemma 3 27B y el 4B "rivaliza" con el 12B base [F]. El 4B saca MetricX 5,32 y COMET 81,6 en WMT24++ [F].
- **Licencia.** Gemma Terms [F]: permite uso comercial con política de uso prohibido.
- **Limitaciones.** Plantilla de *prompt* rígida (códigos de idioma de origen y destino más el texto) y **2K tokens de entrada** [F], así que el contexto y el glosario no se pueden inyectar con libertad. Admite códigos regionales como `de-DE`, por lo que `es-ES` debería funcionar (s/v).
- **Disponibilidad.** En Ollama: 4b 3,3 GB, 12b 8,1 GB y 27b 17 GB [F].
- **Veredicto.** Buena alternativa "sin configurar nada" (4B); menos flexible que Hy-MT2 para el modo simultáneo.

**Index-Translate (IndexTeam/bilibili, sep-2026)**
- **Qué es.** Tamaños 2B, 9B y 35B-A3B sobre Qwen3.5, con licencia Apache 2.0 y 150 idiomas [F].
- **Resultados.** FLORES COMET-22: 0,8655 (2B) y 0,8789 (9B). IFscore de seguimiento de instrucciones: 0,7569 (2B) frente a 0,6079 de Hy-MT2-7B, según su propia tabla [F].
- **Pegas.** Se publicó hace días; los pesos están en BF16 (2B ~8 GB y 9B ~24 GB según la card) y el *prompt* va en chino.
- **Veredicto.** Vigilar y probar el 2B cuantizado cuando haya GGUF. En la misma organización salió **Index-Echo-S2ST-9B/2B** (27-sep-2026): voz a voz zh↔en/es/ja, Apache 2.0, **sin *streaming*** y ≥24 GB para el 9B [F]. Solo como referencia.

**Seed-X-PPO-7B (ByteDance, jul-2025)**
- Arquitectura Mistral y licencia OpenMDW (permisiva). Cubre 28 idiomas y el *prompt* termina con la etiqueta de destino `<es>` [F].
- Hay versiones AWQ y GPTQ oficiales. Se presenta a la par de Gemini-2.5 y GPT-4 en evaluación humana [F].
- Solo traduce (no sigue instrucciones de estilo ni glosario). Alternativa a Hy-MT2-7B.

**Tower+ (Unbabel, jun-2025)**
- Tamaños 2B, 9B y 72B sobre Gemma 2, con licencia CC-BY-NC-SA 4.0 [3] (vale para uso personal).
- El 9B saca 84,38 de XCOMET-XXL en WMT24++ [3]. Ha quedado superado por Hy-MT2 y TranslateGemma.

**SalamandraTA (BSC)**
- Tamaños 2B y 7B; cubre 40 idiomas, con foco ibérico (es, ca, gl, eu) y traducción a nivel de documento [F].
- **La v3 lleva pesos con licencia GPL-3** (por datos GPL) [F]; versiones anteriores eran Apache [3]. Media FLORES+ EN→XX: 37,95 BLEU [F].
- Interesante para el matiz peninsular (s/v); sin GGUF oficial confirmado.

### 3.3 Traducción con LLM generalistas

- **Qwen3.5**
  - Versiones pequeñas de 0.8B, 2B, 4B y 9B (feb–mar 2026) con Apache 2.0, 201 idiomas y 262K de contexto [F].
  - Traen **modo *thinking* activado por defecto**: desactivarlo (`enable_thinking: false`) es imprescindible para la latencia [F].
  - El 4B saca 66,6 XCOMET-XXL de media en WMT24++ [F].
  - Son muy flexibles con instrucciones (glosario, registro, concisión) y fuertes en zh y ja. Qwen3 (2025) también es Apache.
- **Gemma 4**
  - Publicado el 2-abr-2026 **con Apache 2.0** (Google abandonó sus términos propios) [3]. Tamaños E2B, E4B, 26B-A4B y 31B.
  - El E4B tiene 4,5B efectivos (8B totales), 128K de contexto y más de 140 idiomas, y **admite audio de entrada, incluida la voz a texto traducido** [F]. A futuro podría fusionar ASR y MT; su calidad y latencia en *streaming* no están evaluadas.
  - Gemma 3 12B (Gemma Terms) fue la base de BeaverTalk en IWSLT 2025 [F], pero con 12B no cabe junto a lo demás.
- **Ministral 3 8B** (dic-2025): Apache 2.0, ~11 idiomas incluidos es, ja y zh, 256K de contexto [F]. Sin métricas de MT.
- **EuroLLM-9B-Instruct**: Apache 2.0 y 35 idiomas. Es la MT del sistema de CUNI, el mejor de la tarea simultánea de IWSLT 2025 [F]. EuroLLM-22B (feb-2026, Apache) no cabe.
- **Llama 3.x**: licencia comunitaria de Meta (s/v en esta sesión); sin ventaja para MT frente a los anteriores.

### 3.4 Runtimes y compatibilidad en Windows 11 con la RTX 5070 (Blackwell, sm_120)

- **llama.cpp / Ollama**
  - Hay compilaciones oficiales de Windows con CUDA 12.x y 13.x [3]. No he verificado cuál incluye sm_120 de forma nativa; si ninguna lo hace, se compila con CUDA ≥12.8. El driver 616.64 del usuario es suficiente para CUDA 13.
  - También hay wheels de la comunidad de `llama-cpp-python` específicas para Blackwell (sm_120, CUDA 13.0) [3].
  - `llama-server` expone una API **compatible con OpenAI** (`/v1/chat/completions` con *streaming*).
  - Sirve para Hy-MT2 (GGUF oficiales), Qwen3.5, Gemma 4, TranslateGemma (también en la biblioteca de Ollama [F]), EuroLLM y Seed-X (GGUF de la comunidad).
- **CTranslate2** (MIT)
  - La 4.6.3 (6-ene-2026) añadió CUDA 12.8, la necesaria para Blackwell [F]. Python 3.13 está soportado desde la 4.6.0 y 3.14 desde la 4.6.1; la serie 4.8.x es de 2026 [F].
  - Soporta Marian, NLLB, M2M100, MADLAD-400 y T5Gemma, además de LLM (Llama, Mistral, Gemma, Qwen2…) [F].
- **PyTorch**: para sm_120 hacen falta builds cu128 o posteriores (torch ≥2.7); con CUDA ≤12.6 no funciona [3].
  - Chatterbox-TTS-Server indica torch 2.9.0+cu128 para Blackwell [F].
  - El *fork* de *streaming* de Qwen3-TTS usa torch cu130, una wheel de flash-attn para Windows y triton-windows [F].
- **vLLM, vLLM-Omni y SGLang**: pensados para Linux (en Windows, vía WSL2). Voxtral TTS y el servidor de Fish S2 dependen de ellos, y Qwen3-TTS los usa para servir. **Conviene evitarlos en el camino principal.**
- **ExLlamaV2/V3 + TabbyAPI**: rápidos en NVIDIA y con soporte para Windows (s/v en esta sesión). No aportan frente a llama.cpp con modelos de ≤7B.
- **Rendimiento esperado.** 8B Q4 ≈ 80–93 tok/s [3], lo que da unos 7B Q4 ≈ 95–110 tok/s, 4B Q4 ≈ 150 tok/s y 1.8B Q8 ≈ 200–250 tok/s [E].
  - Una cláusula de ~20–25 tokens de salida tarda 0,1–0,3 s, más 30–100 ms de *prefill* con ~300 tokens de contexto [E].

### 3.5 Traducción simultánea: estrategias para texto que llega en fragmentos

**Opciones y cómo encajan con la salida hablada**

| Estrategia | Idea | Pros | Contras para voz |
|---|---|---|---|
| Esperar a la oración completa | Traducir solo cuando el ASR cierra la frase | Máxima calidad y coherencia | Con frases largas el retardo supera los 3–5 s |
| Re-traducción (Arivazhagan et al., 2020) | Re-traducir el prefijo completo cada vez que llega texto | Iguala o supera al *streaming* dedicado cuando se permiten correcciones [F] | **El audio ya hablado no se puede borrar.** Solo sirve para subtítulos |
| wait-k / prefijo a prefijo (STACL) | Emitir la traducción siempre k palabras por detrás de la fuente [F] | Latencia controlable | Requiere modelos entrenados para ello. Con LLM genéricos provoca anticipaciones erróneas, irreversibles en voz |
| LocalAgreement (Whisper-Streaming, SimulStreaming) | Confirmar solo el prefijo común de dos hipótesis consecutivas [F] | Estabiliza el texto de entrada o salida sin reentrenar | Añade el retardo de una actualización |
| **LLM por cláusulas confirmadas, con contexto y glosario** | Traducir unidades cortas y estables, dando al modelo lo ya dicho | Buen equilibrio; es lo que usan los mejores sistemas de IWSLT 2025 | Hace falta un buen segmentador |

**Evidencia reciente**
- **CUNI (SimulStreaming, mejor sistema de IWSLT 2025)**: Whisper con la política AlignAtt, más EuroLLM-9B con **LocalAgreement** y *buffers* de contexto fuente-destino.
  - Dio +13–22 BLEU sobre la línea base en en→de/zh/ja.
  - Operó en régimen de alta latencia: StreamLAAL de ~3,7–4,7 s (con ~1,3–1,5 s de ellos atribuibles al ASR). La baja latencia no fue viable por el coste de EuroLLM [F].
  - Recortar el contexto por **segmentos** en lugar de por oraciones evitó alucinaciones en zh y ja [F].
- **BeaverTalk (Oregon State, IWSLT 2025)**: segmentador VAD, Whisper large-v2 y **Gemma 3 12B con LoRA**, con memoria de la frase anterior.
  - en→de: 24,64 BLEU a ~1,84 s y 27,83 BLEU a ~3,34 s (StreamLAAL) [F].
  - Pasar de ~1,8 a ~3,3 s de latencia aporta unos 3 BLEU: **2–3 s es el punto dulce**.
- **Seed LiveInterpret 2.0 (ByteDance)**: voz a voz de extremo a extremo zh↔en con 2,53 s y clonación de voz. **Propietario** [F]. Marca el techo actual: unos 2,5–3 s con calidad cercana a la humana.
- **Hibiki-Zero (Kyutai, 2026)**: voz a voz simultánea solo de fr/es/pt/de **hacia inglés**, CC-BY-NC-SA [F]. No sirve para en→es.
- **Longitud de la traducción**: el trabajo sobre *prompting* para MT isométrica (IWSLT 2025, incluye en-es) concluye que los LLM acortan su salida sobre todo cuando se les dan ejemplos extremos, y que **generar varias candidatas y elegir** mejora el compromiso entre longitud y calidad [F]. Seed LiveInterpret cita la "inflación del habla traducida" como problema clave [F].

**Recomendación concreta para InstantTraductor**

1. **Entrada**: solo palabras **confirmadas** por el ASR (LocalAgreement-2 o equivalente), con marcas de tiempo y puntuación. Los parciales no confirmados solo se usan para subtítulos, si los hay.
2. **Segmentador**: la unidad de traducción se cierra cuando se cumple lo primero de lo siguiente:
   - fin de oración (`. ? !`);
   - pausa de ≥300–400 ms y ≥4 palabras;
   - límite de cláusula (coma, *and/but/because/which/so*…) y ≥8 palabras;
   - **tope** de ≥12–15 palabras o ≥2,0 s desde la primera palabra; en ese caso se corta en el mejor límite disponible.
   - Para ja/zh se priorizan las pausas y el fin de oración, con topes mayores (en japonés el verbo va al final: esperar a la partícula o forma verbal final).
   - En→es es mayoritariamente monótono (SVO), así que el corte por cláusulas apenas daña la calidad; los reordenamientos son locales, como adjetivo y sustantivo.
3. **Prompt**. Adaptarlo a las plantillas oficiales de Hy-MT2 (contexto, terminología y estilo). Esquema:
   ```text
   [Estilo] Español de España (peninsular), natural y conciso, tuteo; sin explicaciones.
   [Terminología] "patch" → "parche"; "Steam Deck" → "Steam Deck"; nombres propios sin traducir…
   [Contexto: lo ya interpretado, últimos 3–5 pares, ≤300 tokens]
   EN: … | ES: …
   [Traduce SOLO este fragmento; si está incompleto, que la traducción pueda continuarse]
   EN: "…"
   ```
4. **Decodificación**: temperatura baja, `max_tokens` ≈ 2× la longitud de la fuente y parada en salto de línea [E]. Hay que **filtrar** las salidas que no sean traducción: explicaciones, comillas, cambio de idioma o una proporción de longitud anómala.
5. ***Streaming* hacia el TTS**: leer los tokens del LLM y enviar al TTS en cuanto aparezca una coma o un punto, sin esperar a la cláusula entera.
6. **Contexto** = lo que *realmente se dijo* en español, aunque tuviera errores. Nunca se re-traduce el audio ya emitido; si un error cambia el sentido, la frase siguiente puede corregirlo ("perdón: …"), como hace un intérprete.
7. **Pipeline ja/zh→es**: traducir directamente con el mismo LLM (Hy-MT2 y Qwen son fuertes en zh y ja). Pivotar vía el "translate" de Whisper al inglés es una opción de respaldo, pero se pierden matices.

**Presupuesto de latencia orientativo en en→es**

| Etapa | Perfil A (Hy-MT2-1.8B + Chatterbox) | Perfil C (Hy-MT2-1.8B/Opus-MT + XTTS/Kokoro) |
|---|---|---|
| ASR: confirmar palabras (ver informe de ASR) | 0,5–1,0 s | 0,5–1,0 s |
| Segmentador (espera de pausa o límite) | 0–0,4 s | 0–0,4 s |
| MT (primer token más la cláusula) | 0,1–0,25 s [E] | 0,02–0,2 s [E] |
| TTS: primer audio | 0,5–0,8 s [F/E] | 0,1–0,3 s [F/E] |
| **Desde el final de la cláusula hasta la voz** | **~1,1–2,5 s** | **~0,6–1,9 s** |
| **Retardo medio oído–voz (EVS)** | **~2–3,5 s** | **~1,5–2,5 s** |

### 3.6 Síntesis de voz local: detalle por motor

**Chatterbox Multilingual V3 y *finetune* `Chatterbox-Multilingual-es-es` (Resemble AI)**
- **Modelos.** El multilingüe tiene 500M parámetros y cubre 23 idiomas, incluido el español. Resemble publicó seis *finetunes* monolingües; uno es **`es-es`** (castellano), de 2,14 GB en fp32, que ofrece "un control de calidad es-ES más estricto que el multilingüe" [F].
  - Chatterbox-Turbo (350M), Nano (110M) y Flash (bloques de difusión, 103 ms al primer paquete) son **solo inglés** [F].
- **Licencia.** MIT en código y pesos. Todo el audio lleva la marca de agua Perth [F].
- **Rendimiento.**
  - Con la implementación ggml de NVIDIA (ACE): el multilingüe necesita **≥3,5 GB** y el Turbo ≥2 GB. Latencia media en CLI: ~564 ms con CUDA, ~626 ms con Vulkan y ~1,5 s con D3D12; con carga gráfica 3D, el primer audio sube a ~1,0–1,2 s. La documentación no aclara si se midió con Turbo o con el multilingüe. El Turbo es ~2× más rápido que el multilingüe [F].
  - En PyTorch no hay *streaming* token a token. El servidor de la comunidad (Chatterbox-TTS-Server, MIT) trocea por frases, ofrece `stream: true` por fragmentos, un endpoint `/v1/audio/speech` compatible con OpenAI y notas para Blackwell (torch 2.9.0+cu128) [F].
- **Controles.**
  - `cfg_weight`: además del acento, controla el ritmo (0,3–0,5 más lento y natural; 1–3 más rápido) [F].
  - `exaggeration`: más expresividad y habla algo más rápida [F].
  - Clonación con ~10 s de referencia [F].
- **Pros.** Es el único modelo abierto con checkpoint dedicado a español de España, con licencia permisiva y clonación. Además, se puede **clonar el timbre del hablante original** entre idiomas.
- **Contras.** Latencia más alta que XTTS, Kokoro o Piper; Python 3.11; poca documentación de su rendimiento en la 5070 (medir).

**XTTS-v2 (Coqui; mantenido por Idiap como `coqui-tts`)**
- 17 idiomas, incluido el español. Clona con 6 s de referencia y genera a 24 kHz [F].
- ***Streaming* real** con <200 ms [F]. Tiene parámetro `speed`, aunque "puede producir artefactos lejos de 1,0" [F]. Ocupa ~2 GB en fp16 [3].
- **Licencia.** Código MPL-2.0 y pesos **CPML (no comercial)**. Coqui cerró en ene-2024, así que **ya no se puede comprar una licencia comercial** [3]. Para uso personal vale.
- **Instalación.** coqui-tts 0.27.x requiere Python ≥3.10 y <3.15 (encaja con el 3.13 del usuario) y trae wheels para Windows [F].
- **Acento.** El castellano depende de la referencia: usar una voz peninsular limpia. Es un modelo de 2023: a veces alucina en textos muy cortos y conviene unir fragmentos de ≥4–5 palabras [E].

**Qwen3-TTS (Alibaba Qwen, 22-ene-2026)**
- Tamaños 0.6B (CustomVoice y Base) y 1.7B (CustomVoice, VoiceDesign y Base). Cubre 10 idiomas, incluido el español [F].
- **Voces preset**: 9 (Vivian, Serena, Uncle_Fu, Dylan, Eric, Ryan, Aiden, Ono_Anna y Sohee), **ninguna hispana**. Para castellano hay que usar el modelo **Base con clonación** de 3 s de una voz peninsular [F].
- **Calidad.** WER en español: 1,126 (CustomVoice 1.7B) y 1,491 (Base 1.7B); similitud de hablante 0,814 [F].
- ***Streaming*.** El *paper* anuncia 97 ms al primer paquete con el tokenizador de 12 Hz [F]. Sin embargo, **el código oficial de *streaming* no se publicó**; el *fork* `Qwen3-TTS-streaming` lo añade (`stream_generate_pcm` y `stream_generate_voice_clone`), va ~6× más rápido y documenta la instalación en Windows con torch cu130; se probó en una RTX 5090, que también es Blackwell [3].
- **Resto.** La velocidad se controla por instrucción [F]. VRAM de ~4 GB (0.6B) y ~6 GB (1.7B) [3]. Apache 2.0.

**Fun-CosyVoice3 0.5B (Alibaba FunAudioLLM, dic-2025)**
- 9 idiomas, incluido el español, más 18 dialectos chinos. Licencia Apache 2.0 [F].
- ***Bi-streaming***: entra texto y sale audio de forma incremental, **~150 ms** [F]. Ideal para encadenarlo con un LLM que emite tokens.
- Admite instrucciones de velocidad y emoción [F]. Aceleración con vLLM ≥0.11 o TensorRT-LLM [F].
- Contras: entorno Python 3.10 con conda, orientado a Linux; en Windows cabe esperar fricción con dependencias (s/v).

**IndexTTS-2.5 (bilibili, 10-ago-2026)**
- 0,8B parámetros; idiomas zh, en, ja, **es** y ar. RTF 0,21 en una RTX 4090 [F].
- **`duration_factor` de 0,5 a 2,0×** [F]: el mejor control explícito de duración de la lista. También controla la emoción.
- **Licencia.** Contrato de uso de modelos de bilibili; para uso comercial hay que contactar [F].
- **Instalación.** CUDA ≥12.8 y uv; DeepSpeed complica Windows [F].
- Sin *streaming* documentado. Muy reciente: validar su calidad en español.

**F5-TTS con F5-Spanish**
- Arquitectura no autorregresiva. El código es MIT; los pesos base son **CC-BY-NC** (por el dataset Emilia) [F].
- F5-Spanish (jpgallegoar): 218 h de datos de VoxPopuli, TEDx y *crowdsourcing*, con español peninsular y de varios países americanos. Su card declara CC0 [F], pero hereda la base NC: tratarlo como no comercial.
- Rendimiento: RTF 0,04 y 253 ms en una L20 con Triton y TensorRT-LLM [F]. Genera por trozos (máximo 30 s) y tiene un servidor de socket [F]. Admite `speed`.

**OmniVoice (k2-fsa, abr-2026)**
- 0,6B parámetros, más de 600 idiomas y **RTF 0,025**. Diseño de voz por atributos, incluido "dialecto/acento" [F].
- Código Apache y **pesos CC-BY-NC** [F]. Sin *streaming* documentado. Prometedor para lograr acento castellano por diseño; muy nuevo.

**Fish Audio (OpenAudio S1-mini y S2 Pro)**
- S1-mini: 0,5B, CC-BY-NC-SA, 13 idiomas incluido el español, con marcas de emoción [F].
- S2 Pro: 4B + 0,4B, licencia de investigación no comercial, español en tier 2, RTF 0,195 y ~100 ms en una H200 con SGLang [F]. **No cabe.**

**Kokoro-82M**
- Apache 2.0 y 24 kHz. Parámetro `speed`; el generador entrega el audio por fragmentos [F].
- **Español**: 3 voces (ef_dora, em_alex y em_santa) **sin nota de calidad en VOICES.md**, que avisa de que "el soporte no inglés puede ser escaso por un G2P débil o falta de datos" [F]. Algunos usuarios reportan acento extranjero [3]. Los fonemas de espeak-ng `es` son de castellano (distinguen /θ/).
- Muy rápido y ligero; también corre en CPU. Kokoro-FastAPI ofrece un endpoint compatible con OpenAI, ~300 ms al primer audio en GPU con fragmentos de 400 y 2,4–4 GB de VRAM con PyTorch [F].
- **Papel**: modo rápido o de emergencia; validar su español de oído.

**Piper (OHF-Voice/piper1-gpl)**
- El repositorio original `rhasspy/piper` (MIT) se archivó el 6-oct-2025. El proyecto vivo es **GPL-3.0** (enlaza con espeak-ng, también GPL-3) [3/F].
- **Voces es_ES nativas**:

  | Voz | Calidad | Datos | Licencia |
  |---|---|---|---|
  | davefx | medium | — | CC0 |
  | sharvard | medium, 2 hablantes | — | CC-BY 3.0 |
  | carlfm | x_low | — | Dominio público |
  | mls_10246 / mls_9972 | low | MLS | CC-BY 4.0 |

- API en Python: `synthesize()` devuelve fragmentos, así que admite *streaming*. `SynthesisConfig` expone `length_scale` (velocidad), `noise_scale` y `noise_w_scale`. CUDA es opcional (`use_cuda=True` con onnxruntime-gpu) [F].
- **Papel**: respaldo instantáneo en CPU con acento castellano auténtico; suena algo robótico.

**Supertonic 2/3, MeloTTS, Orpheus, Magpie y VibeVoice**
- **Supertonic 2**: 66M, 5 idiomas incluido el español. **Supertonic 3**: 99M, 31 idiomas. Pesos OpenRAIL-M y ONNX en CPU con RTF ~0,01 [F]. Candidatos de CPU ultraligeros; acento sin verificar.
- **MeloTTS** (MIT, ES, tiempo real en CPU, `speed`) [F]: calidad discreta y mantenimiento escaso.
- **Orpheus 3B es_it**: *research preview* de abr-2025 sobre Llama 3.2, con acceso restringido [F]. Pesado y sin datos de acento.
- **Magpie 357M** (NVIDIA, 12 idiomas incluido el español, licencia abierta de NVIDIA) [F]: depende de NeMo y Linux.
- **VibeVoice-Realtime**: el español es "experimental" [F].
- Ninguno de ellos es prioritario.

### 3.7 Voces de Windows y edge-tts

- **OneCore (Helena, Laura y Pablo, es-ES)** [3]
  - Se usan con `Windows.Media.SpeechSynthesis` (WinRT, accesible desde .NET, C++ o Python con las proyecciones winrt).
  - `SpeakingRate` va de 0,5 a 6,0 y se combina con SSML `<prosody>`. Por defecto se añaden **~750 ms de silencio** tras cada enunciado y signo de puntuación, configurables con `AppendedSilence` y `PunctuationSilence` [F]. **Recortarlos es clave para la latencia.**
  - Por SAPI5 solo aparecen algunas voces; las OneCore se exponen con un truco de registro (`HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices`) [3].
  - Calidad antigua, pero con latencia y VRAM nulas: el último recurso "siempre disponible".
- **Voces "naturales" de Windows 11 (Narrador)**
  - Son neuronales y funcionan en el dispositivo. En la build 26220.7262 (Dev/Beta) se añadieron voces HD en en-US para Narrador [3]. No he verificado qué voces es-ES hay.
  - **Microsoft no permite a apps de terceros usarlas oficialmente** [3].
  - El adaptador no oficial *NaturalVoiceSAPIAdapter* las expone vía SAPI5 "usando claves extraídas de archivos del sistema; es más un *hack*". Puede romperse con una actualización, las últimas voces de Narrador son incompatibles y requiere privilegios de administrador [F]. Solo para experimentar.
- **edge-tts**: usa el servicio online de Edge, no es local; GPL-3.0. Admite `--rate`, pero Microsoft bloquea el SSML propio [F]. Queda fuera del requisito 100 % local.

### 3.8 Control de ritmo cuando la voz se retrasa

El español suele salir ~15–25 % más largo que el inglés (regla empírica de localización, s/v). Hay que prever la inflación.

| Motor | Mecanismo | Rango útil [E] | Naturalidad |
|---|---|---|---|
| Piper | `length_scale` (duraciones predichas) | 0,75–1,0 (1,33–1× más rápido) | Buena |
| Kokoro | `speed` | 1,0–1,3 | Buena |
| F5-TTS | `speed` (duración total) | 1,0–1,3 | Buena |
| IndexTTS-2.5 | `duration_factor` | 0,5–2,0× de duración [F] | Buena (pensado para ello) |
| XTTS-v2 | `speed` | 1,0–1,25 | Media (artefactos) [F] |
| CosyVoice3 | Instrucción o parámetro de velocidad | ~1,0–1,3 | Buena (s/v) |
| Qwen3-TTS | Instrucción ("habla un poco más rápido") | Cualitativo | Variable |
| Chatterbox | `cfg_weight` (1–3 más rápido), `exaggeration` | Cualitativo | Variable: mejor *time-stretch* |
| Windows OneCore | `SpeakingRate`, `<prosody rate>`, silencios | 1,0–1,5 | Aceptable |
| **Cualquiera (postproceso)** | *Time-stretch* sin cambiar el tono: **Sonic** (C, Apache 2.0, optimizado para habla y aceleraciones >2×) [3], WSOLA (audiotsm, MIT, s/v), SoundTouch (LGPL-2.1+) [3], Rubber Band (GPL o comercial, s/v) | 1,0–1,25 casi imperceptible; >1,4 se nota | Buena si ≤1,25× |

**Política recomendada** (retraso = audio pendiente en cola más la antigüedad del segmento más viejo sin hablar):
1. **<1 s**: velocidad 1,0.
2. **1–2,5 s**: 1,1–1,2×. Usar la velocidad nativa si existe; si no, Sonic. Recortar los silencios entre fragmentos a 50–100 ms.
3. **2,5–4 s**: 1,25–1,3×, más una instrucción al LLM de "traducción concisa". Eliminar muletillas y repeticiones del ASR.
4. **>4–5 s**: condensar. Fusionar los segmentos pendientes y pedir un resumen de ≤N palabras, o descartar lo de poco valor. Avisar en la interfaz.
5. **No cambiar de voz** para ponerse al día (desorienta al oyente). El *failover* a Piper o Kokoro se reserva para cuando el TTS principal falle o la GPU esté saturada.

### 3.9 Interfaces comunes para poder cambiar de motor

**Recomendación de arquitectura.** Cada motor corre en **su propio proceso y entorno** (Python 3.10, 3.11 o 3.12 según el motor; el sistema tiene 3.13 y no tiene uv). Los procesos exponen una **API HTTP local compatible con OpenAI**, y el orquestador (Python o .NET 10) solo habla con esa API. Ventajas:
- aísla dependencias de CUDA y PyTorch;
- permite descargar un motor para liberar VRAM;
- varios servidores ya la implementan (llama-server, Ollama, Kokoro-FastAPI, Chatterbox-TTS-Server).

| Contrato | Endpoint | Implementaciones existentes | Envoltorio a escribir |
|---|---|---|---|
| MT | `POST /v1/chat/completions` (`stream: true`) | llama-server, Ollama, LM Studio, TabbyAPI | Envoltorio pequeño para CTranslate2 (Opus-MT o NLLB) con el mismo contrato |
| TTS | `POST /v1/audio/speech` (`input`, `voice`, `speed`, `response_format: "pcm"`, *streaming*) | Kokoro-FastAPI, Chatterbox-TTS-Server, vLLM-Omni (Linux) | Envoltorios para Piper, XTTS, Qwen3-TTS (*fork*) y WinRT |
| Control | `GET /health`, `GET /capabilities`, `POST /load`, `POST /unload` | — | En todos (gestión de VRAM) |

Interfaz interna (esquema):
```python
class Translator(Protocol):
    caps: TranslatorCaps   # langs, supports_context, supports_glossary, streaming, max_ctx_tokens, device, vram_mb
    async def translate(self, seg: SourceSegment, ctx: TranslationContext) -> AsyncIterator[str]: ...
    # ctx: pares previos (fuente, lo_realmente_hablado), glosario, estilo="es-ES", concision: 0..2

class TtsEngine(Protocol):
    caps: TtsCaps          # sample_rate, streaming, rate_range, native_rate: bool, voices, cloning, device, vram_mb
    async def synthesize(self, text: str, voice: VoiceRef, rate: float = 1.0) -> AsyncIterator[PcmChunk]: ...
    # si native_rate es False, el RateController aplica Sonic al PCM recibido
```

Piezas transversales:
- `Segmenter` (política configurable por idioma de origen) y `RateController` (política de §3.8).
- Formato de audio común: **PCM s16le, mono, 24 kHz**. Piper produce 22,05 kHz y se remuestrea en el mezclador.
- Perfiles de configuración A, B, C y D (§2.3) en JSON o YAML.
- Un **arnés de evaluación** que mida la latencia de cada etapa (p50/p95), la VRAM (con `nvidia-smi`), la calidad de la MT (COMET-22 o MetricX sobre un conjunto propio) y el WER de ida y vuelta del TTS (ASR sobre el audio generado).

---

## 4) Recomendación para InstantTraductor

### 4.1 Principal: perfil A, "voz de calidad", todo permisivo

**Componentes**
- **MT: Hy-MT2-1.8B en GGUF Q8_0**, servido con `llama-server` (CUDA 12.8+/13) y *streaming* hacia el TTS. Usa plantillas de contexto (últimos 3–5 pares), terminología (glosario del usuario) y estilo ("español de España, tuteo, conciso").
- **TTS: Chatterbox-Multilingual-es-es**, servido por un servidor compatible con OpenAI (p. ej. Chatterbox-TTS-Server con torch cu128). Genera por cláusulas con doble búfer (produce la siguiente mientras suena la actual) y controla el ritmo con `cfg_weight` y Sonic.
- **Respaldo automático**: Opus-MT en-es con CTranslate2 en CPU si el LLM falla o supera 1 s, y Piper es_ES (davefx o sharvard) en CPU si el TTS principal falla.

**Motivos**
1. **Licencias válidas en España** (Apache y MIT). Sirven hoy y también si algún día el uso pasa a ser comercial.
2. **Hy-MT2** es un modelo especializado en MT: en tablas de terceros supera a generalistas de su tamaño (Qwen3.5-9B: 0,8316 frente a Hy-MT2-7B: 0,8747 en FLORES COMET-22) [3]. Con 1,9 GB rinde a nivel de API comercial según Tencent [F], trae plantillas de contexto y terminología pensadas para este uso y cubre ja/zh sin cambiar de modelo. Si sobra VRAM, se sube al 7B con el mismo *prompt*.
3. **Chatterbox es-ES** es la única voz abierta **afinada específicamente para castellano**. Suena moderna, permite clonación (incluido el timbre del hablante original) y cabe con margen (~3,5 GB).
4. **Total: ~9–10 GB** de 12, con margen para picos.

**Condición de salida.** Si en las pruebas Chatterbox da un **p95 de primer audio >0,6–0,7 s por cláusula** o un **RTF >0,5** en la 5070 con el ASR y la MT cargados, se pasa al TTS de la alternativa 1.

### 4.2 Alternativas

1. **Latencia (perfil C)**: Hy-MT2-1.8B con **XTTS-v2** (clonando una referencia castellana). Tiene *streaming* real (<200 ms), `speed` nativo y ~2 GB; su licencia no comercial vale para uso personal.
2. **TTS moderno con Apache**: **Qwen3-TTS-0.6B-Base** clonando una voz castellana, con el *fork* de *streaming* (probado en Blackwell y documentado en Windows). Si el entorno de Linux o WSL2 es aceptable, también **CosyVoice3** (*bi-streaming* de 150 ms, instrucción de velocidad).
3. **Traducción de más calidad (perfil B)**: **Hy-MT2-7B Q4_K_M** con Kokoro o Piper en CPU. Alternativas de MT: **Qwen3.5-4B/9B** sin *thinking* (máxima flexibilidad de instrucciones), **TranslateGemma-4B** (especializado, plantilla rígida) o Seed-X-PPO-7B.
4. **Ligero o jugando (perfil D)**: Opus-MT con CTranslate2 y Piper es_ES, todo en CPU (~0–2 GB de VRAM).
5. **A vigilar (sep-2026)**:
   - **Index-Translate-2B** (Apache, métricas muy buenas, días de vida).
   - **IndexTTS-2.5** (control de duración de 0,5 a 2,0×).
   - **OmniVoice** (acento por diseño, no comercial).
   - **Gemma 4 E4B** (voz a texto traducido en un solo modelo).
   - **Supertonic 3** (TTS de CPU ultraligero en 31 idiomas).

### 4.3 Plan de validación (1–2 semanas, antes de fijar motores)

1. **Conjunto de prueba propio.** 150–200 frases en inglés de contenido real (vídeos, *podcasts*, juegos), incluyendo transcripciones con errores del ASR. Para ja/zh, 50 frases cada uno más adelante.
2. **MT.** Comparar Hy-MT2-1.8B y 7B, Qwen3.5-4B, TranslateGemma-4B y Opus-MT.
   - Medir COMET-22 o MetricX, más una revisión humana de "¿suena a España?".
   - Medir la tasa de salidas que no son traducción y la latencia p50/p95 con el ASR cargado.
   - Regla: elegir **el modelo más pequeño que quede a ≤1 punto de COMET del mejor**.
3. **TTS.** 50 frases es-ES con Chatterbox es-ES, XTTS-v2 (referencia castellana), Qwen3-TTS-0.6B (referencia castellana), Kokoro y Piper.
   - Medir el primer audio y el RTF en la 5070 y la VRAM real.
   - MOS informal (1–5) con 2–3 oyentes y WER de ida y vuelta (objetivo ≤5 %).
4. **Pipeline completo.** 10 minutos de audio real.
   - Medir el EVS (objetivo: p50 ≤2,5 s en en→es), la frecuencia de aceleraciones y condensaciones, y la estabilidad durante 1 hora (VRAM y memoria).

---

## 5) Riesgos y preguntas abiertas

**Riesgos**
1. **Licencias.** Para uso personal todo lo listado vale, salvo **Hunyuan-MT-7B y HY-MT1.5, que no son válidos en la UE en ningún caso**. Si el uso pasa a ser comercial:
   - habría que sustituir XTTS-v2, F5, NLLB, SeamlessM4T, Tower+, Fish, OmniVoice y Voxtral;
   - revisar los Gemma Terms (TranslateGemma) y la licencia de bilibili (IndexTTS);
   - tener en cuenta que Piper, espeak-ng y SalamandraTA-v3 son **GPL-3**: distribuirlos obliga a cumplir la GPL.
2. **Blackwell, Windows y Python.** sm_120 exige CUDA ≥12.8 (torch cu128+, CTranslate2 ≥4.6.3, llama.cpp reciente). Cada motor pide su versión de Python (3.10, 3.11 o 3.12) frente al 3.13 instalado, y no hay uv. flash-attn, DeepSpeed y vLLM dan problemas en Windows. **Mitigación**: un entorno por motor, procesos separados e instalación reproducible.
3. **Latencia de Chatterbox en PyTorch** en la 5070 sin medir (solo hay datos de la implementación ggml de NVIDIA). **El *streaming* oficial de Qwen3-TTS no existe** (depende de un *fork*).
4. **Calidad del castellano**:
   - la de Kokoro, Supertonic y MeloTTS está sin verificar;
   - los modelos con clonación pueden derivar a acento neutro o americano si la referencia no es buena;
   - los LLM pueden mezclar variantes (ustedes/vosotros, "computadora"/"ordenador") si no se fija el estilo.
5. **Novedad de los modelos.** Hy-MT2 tiene 4 meses, IndexTTS-2.5 semanas e Index-Translate días: cabe esperar errores y un soporte irregular en llama.cpp.
6. **VRAM compartida** con juegos o el navegador y ~0,3–0,5 GB de contexto CUDA por proceso. Hace falta carga y descarga dinámica y el perfil D en CPU.
7. **Errores del ASR y disfluencias.** Provocan alucinaciones o explicaciones del LLM; hacen falta filtros (identificación de idioma, proporción de longitud, lista negra de "Aquí tienes la traducción…").
8. **Inflación del español.** Acumula retraso en discursos rápidos; habrá que condensar o perder algo de contenido.
9. **Realimentación de audio (transversal).** La voz generada sale por los mismos auriculares que se capturan en *loopback*: hay que **excluir el audio del propio proceso** (captura *loopback* por proceso en modo exclusión). Lo cubre el informe de captura, pero condiciona el TTS.
10. **Clonación de voces de terceros.** Aunque sea para uso personal, no distribuir el audio clonado. Chatterbox marca todo con Perth.
11. **Datos de nube** (DeepL y otros) contradictorios o de fuentes secundarias; es irrelevante mientras el requisito siga siendo 100 % local.

**Preguntas abiertas para el usuario o el equipo**
- ¿Registro por defecto: tú o usted? ¿Vosotros? ¿Voz masculina o femenina, o **clonar el timbre del hablante original**?
- ¿Salida superpuesta al audio original o bajando su volumen (*ducking*)? ¿Subtítulos en pantalla (permitirían re-traducción visual)?
- ¿Tipo de contenido principal (juegos, YouTube, reuniones, anime)? Afecta al glosario, a la segmentación y al retardo aceptable en ja.
- Cuando haya retraso, ¿se prefiere acelerar o resumir y perder contenido?
- ¿Se usará mientras se juega (VRAM ocupada)? En ese caso el perfil D o C sería el predeterminado.
- ¿Puede haber uso comercial en el futuro? Condiciona si se invierte en XTTS o F5 (no comerciales) o en Chatterbox y Qwen3-TTS (permisivos).

---

## 6) Fuentes (URL)

**Traducción: modelos**
- Hy-MT2 (tarjetas, licencia, GGUF, repositorio, informe):
  - https://huggingface.co/tencent/Hy-MT2-7B
  - https://huggingface.co/tencent/Hy-MT2-7B/blob/main/LICENSE.txt
  - https://huggingface.co/tencent/Hy-MT2-1.8B
  - https://huggingface.co/tencent/Hy-MT2-7B-GGUF
  - https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF
  - https://github.com/Tencent-Hunyuan/Hy-MT2
  - https://arxiv.org/abs/2605.22064
- PR de llama.cpp citada por los GGUF (STQ1_0): https://github.com/ggml-org/llama.cpp/pull/22836
- Hy-MT2 en prensa (96,9 % / 98,1 % de Gemini 2.5 Pro): https://www.qbitai.com/2026/05/422068.html
- Licencias de HY-MT1.5 y Hunyuan-MT (exclusión de la UE):
  - https://huggingface.co/tencent/HY-MT1.5-7B/blob/main/License.txt
  - https://huggingface.co/tencent/HY-MT1.5-1.8B/blob/main/License.txt
  - https://arxiv.org/html/2512.24092v1
- TranslateGemma:
  - https://huggingface.co/google/translategemma-4b-it
  - https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/
  - https://arxiv.org/abs/2601.09012
  - https://ollama.com/library/translategemma
- Index-Translate e Index-Echo:
  - https://huggingface.co/IndexTeam/Index-Translate-9B
  - https://huggingface.co/IndexTeam/Index-Translate-2B
  - https://huggingface.co/IndexTeam/Index-Echo-S2ST-9B
- Seed-X: https://huggingface.co/ByteDance-Seed/Seed-X-PPO-7B
- Tower+: https://slator.com/from-ai-translation-to-ai-localization-with-unbabels-open-weight-tower/ · https://featherless.ai/models/Unbabel/Tower-Plus-9B
- SalamandraTA: https://huggingface.co/BSC-LT/salamandraTA-7b-instruct · https://arxiv.org/html/2508.12774v1
- EuroLLM: https://huggingface.co/utter-project/EuroLLM-9B-Instruct · https://arxiv.org/abs/2602.05879v1
- Qwen3.5: https://huggingface.co/Qwen/Qwen3.5-4B
- Gemma 4: https://huggingface.co/google/gemma-4-E4B-it · https://datanorth.ai/news/google-releases-gemma-4-open-models
- Ministral 3: https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512
- Opus-MT: https://huggingface.co/Helsinki-NLP/opus-mt-en-es · https://huggingface.co/Helsinki-NLP/opus-mt-ja-es
- NLLB-200: https://huggingface.co/facebook/nllb-200-distilled-600M
- MADLAD-400: https://huggingface.co/google/madlad400-3b-mt
- M2M100: https://huggingface.co/facebook/m2m100_1.2B
- SeamlessM4T v2: https://huggingface.co/facebook/seamless-m4t-v2-large

**Traducción: runtimes y rendimiento**
- CTranslate2: https://github.com/OpenNMT/CTranslate2 · https://github.com/OpenNMT/CTranslate2/releases · https://github.com/OpenNMT/CTranslate2/releases/tag/v4.6.3
- Rendimiento de la RTX 5070 con un 8B Q4_K_M: https://willitrunai.com/can-run/llama-3.1-8b-on-rtx-5070-12gb
- Blackwell y PyTorch: https://discuss.pytorch.org/t/pytorch-support-for-sm120/216099
- Wheels de `llama-cpp-python` para Blackwell (comunidad): https://github.com/dougeeai/llama-cpp-python-wheels/

**Traducción simultánea**
- SimulStreaming (CUNI): https://github.com/ufal/SimulStreaming · https://arxiv.org/html/2506.17077v1
- BeaverTalk: https://arxiv.org/abs/2505.24016
- Re-traducción frente a *streaming*: https://arxiv.org/abs/2004.03643
- STACL / wait-k: https://arxiv.org/abs/1810.08398
- Whisper-Streaming / LocalAgreement: https://arxiv.org/abs/2307.14743
- Seed LiveInterpret 2.0:
  - https://arxiv.org/html/2507.17527v2
  - https://seed.bytedance.com/blog/seed-liveinterpret-2-0-released-an-end-to-end-simultaneous-interpretation-model-featuring-ultra-high-accuracy-close-to-human-interpreters-low-latency-of-3-seconds-and-real-time-voice-cloning
- Hibiki-Zero: https://huggingface.co/kyutai/hibiki-zero-3b-pytorch-bf16 · https://arxiv.org/abs/2602.11072
- MT isométrica con LLM: https://arxiv.org/abs/2506.04855
- SimulS2S-LLM: https://arxiv.org/abs/2504.15509

**TTS local**
- Chatterbox:
  - https://github.com/resemble-ai/chatterbox
  - https://resemble.ai/chatterbox
  - https://huggingface.co/ResembleAI
  - https://huggingface.co/ResembleAI/Chatterbox-Multilingual-es-es
  - https://huggingface.co/ResembleAI/chatterbox-flash
  - https://huggingface.co/ResembleAI/chatterbox-nano
  - https://docs.nvidia.com/ace-for-games/chatterbox-tts/nvigi-chatterbox-model-card.html
  - https://docs.nvidia.com/ace-for-games/chatterbox-tts/programming-guide-tts-chatterbox.html
  - https://github.com/devnen/Chatterbox-TTS-Server
- XTTS-v2:
  - https://huggingface.co/coqui/XTTS-v2
  - https://coqui-tts.readthedocs.io/en/latest/models/xtts.html
  - https://github.com/idiap/coqui-ai-TTS
  - https://www.promptquorum.com/power-local-llm/coqui-tts-review
- Qwen3-TTS:
  - https://github.com/QwenLM/Qwen3-TTS
  - https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base
  - https://arxiv.org/abs/2601.15621
  - https://github.com/dffdeeq/Qwen3-TTS-streaming
- CosyVoice: https://github.com/FunAudioLLM/CosyVoice · https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512
- IndexTTS: https://github.com/index-tts/index-tts · https://huggingface.co/IndexTeam
- F5-TTS: https://github.com/SWivid/F5-TTS · https://github.com/SWivid/F5-TTS/blob/main/src/f5_tts/infer/README.md · https://huggingface.co/jpgallegoar/F5-Spanish
- OmniVoice: https://huggingface.co/k2-fsa/OmniVoice
- Fish Audio: https://github.com/fishaudio/fish-speech · https://huggingface.co/fishaudio/openaudio-s1-mini · https://huggingface.co/fishaudio/s2-pro
- Kokoro:
  - https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
  - https://github.com/hexgrad/kokoro
  - https://github.com/remsky/Kokoro-FastAPI
  - https://itch.io/post/15431112
  - https://tts.ai/voices/kokoro/?lang=ja
- Piper:
  - https://github.com/OHF-Voice/piper1-gpl
  - https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md
  - https://github.com/OHF-Voice/piper1-gpl/releases
  - https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_ES
  - https://www.promptquorum.com/power-local-llm/piper-tts-review
- MeloTTS: https://github.com/myshell-ai/MeloTTS
- Orpheus: https://huggingface.co/canopylabs/3b-es_it-ft-research_release · https://huggingface.co/collections/canopylabs/orpheus-multilingual-research-release
- Supertonic: https://huggingface.co/Supertone/supertonic-2 · https://huggingface.co/Supertone/supertonic-3
- Voxtral TTS: https://huggingface.co/mistralai/Voxtral-4B-TTS-2603
- VoxCPM2: https://huggingface.co/openbmb/VoxCPM2
- Higgs TTS 3: https://huggingface.co/bosonai/higgs-tts-3-4b
- Magpie TTS: https://huggingface.co/nvidia/magpie_tts_multilingual_357m
- VibeVoice-Realtime: https://huggingface.co/microsoft/VibeVoice-Realtime-0.5B
- Listado de TTS en español en Hugging Face: https://huggingface.co/models?pipeline_tag=text-to-speech&language=es&sort=trending

**Voces de Windows, edge-tts y control de ritmo**
- `SpeakingRate`: https://learn.microsoft.com/en-us/uwp/api/windows.media.speechsynthesis.speechsynthesizeroptions.speakingrate
- NaturalVoiceSAPIAdapter: https://github.com/gexgd0419/NaturalVoiceSAPIAdapter/blob/master/README.md
- Voces OneCore vía SAPI (truco de registro): https://winaero.com/unlock-extra-voices-windows-10/
- Voces naturales del Narrador en Windows 11: https://www.elevenforum.com/t/add-natural-voices-to-narrator-and-magnifier-in-windows-11.16560/latest
- edge-tts: https://github.com/rany2/edge-tts
- Sonic (Apache 2.0): https://android.googlesource.com/platform/external/sonic/+/refs/heads/main/README
- SoundTouch (LGPL): https://metadata.ftp-master.debian.org/changelogs/main/s/soundtouch/stable_copyright

**Nube (curiosidad)**
- Azure Translator: https://azure.microsoft.com/en-us/pricing/details/cognitive-services/translator/
- DeepL (planes 2026, secundaria): https://www.eesel.ai/es/blog/precios-deepl
- DeepL (documentación): https://developers.deepl.com/docs/translate/understanding-model-types.md · https://developers.deepl.com/docs/voice/overview.md
- Comparativa de costes 2026: https://simplelocalize.io/blog/posts/ai-machine-translation-cost-comparison/
- Gemini API: https://ai.google.dev/gemini-api/docs/pricing
- Azure Speech: https://azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/
- Google Cloud TTS (secundaria): https://costbench.com/software/ai-voice-tools/google-cloud-text-to-speech/
- ElevenLabs Free (secundaria): https://costbench.com/software/ai-voice-tools/elevenlabs/free-plan
- Amazon Translate: https://aws.amazon.com/translate/pricing/
