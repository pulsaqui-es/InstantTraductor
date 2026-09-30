# 06 - Aislamiento de voz y clonación/conversión de voz en tiempo real (InstantTraductor)

Fecha de la investigación: 2026-09-30.
PC objetivo: Windows 11 Pro 25H2, Ryzen 7 8700F (8C/16T), 32 GB RAM, RTX 5070 12 GB (Blackwell, sm_120), Python 3.13.15 + uv 0.12.21.
Lectura local (solo lectura, sin instalar nada): driver NVIDIA 616.64, VRAM total 12 227 MiB y **3 197 MiB ya ocupados por Windows/aplicaciones** en el momento de medir; no hay torch/onnxruntime/faster-whisper instalados.

**Leyenda de fiabilidad** (la uso en todo el informe):
- **[V]** verificado en fuente primaria durante esta sesión (repo, model card, paper, PyPI).
- **[A]** cifra reportada por los autores (casi siempre con GPU de servidor: H20/H100/H200/L20/A10); no es una medida en tu PC.
- **[E]** estimación propia (extrapolación razonada, NO medida).
- **[SV]** sin verificar.

**Nota metodológica.** El presupuesto de WebSearch de la sesión (200/200) se agotó a mitad de la investigación. El resto se hizo con WebFetch sobre fuentes primarias conocidas (repos, model cards, arXiv, PyPI). Los resúmenes de WebFetch los genera un modelo pequeño: contrasté las cifras críticas con una segunda lectura (HTML de arXiv, README crudo) cuando fue posible; donde no, lo indico. No se ejecutó ni instaló ningún modelo: **todas las latencias "en la 5070" son extrapolaciones [E]**.

---

## 1) Resumen ejecutivo

1. **Separación:** no en la ruta crítica del ASR por defecto. Whisper degrada menos que los ASR supervisados con ruido [V]; HT-Demucs *empeoró* a Whisper en canciones (WER 35,5 -> 47,9 %, idioma equivocado) [V]; lo que más ayuda contra alucinaciones es Silero VAD (WER 104,8 -> 8,0 % en su test) [V]; los ASR de 2026 ya se entrenan con BGM [A]. Sin benchmark en series/películas/juegos: medir (plan 4.6).
2. **Dónde sí aislar:** referencias limpias para clonar (fuera de la ruta crítica) + 2ª pasada selectiva de ASR, con **Bandit v2 multilingüe** (Apache-2.0 / pesos CC BY-SA): diálogo 14,9-16,2 dB en ja/zh/es/en; el Bandit solo-inglés cae a 2,2 dB en mandarín [V].
3. **Clonación v1 (principal):** **Qwen3-TTS-0,6B Base** (Apache-2.0; es/ja/zh/en; 3 s de referencia; streaming) con **faster-qwen3-tts** (MIT): TTFA 156 ms en 4090 y 413 ms en 4060 Windows [V]; en la 5070 ~0,2-0,35 s [E] *si* las CUDA graphs funcionan en Windows/sm_120 (hito 0; fallback WSL2); ~3-3,5 GB [E].
4. **Alternativas (a):** Chatterbox es-es (único finetune para España; MIT), CosyVoice3-0,5B (cross-lingual nativo; aceleración solo Linux), IndexTTS-2.5 (emoción/duración; ~6 GB), XTTS-v2 (fallback), Fish S1-mini, OmniVoice (rápido, pero arrastra acento). No caben o licencia: Fish S2 Pro, Higgs v3, Voxtral TTS, VoxCPM2, MOSS v1.5.
5. **(b) TTS neutro + VC** (Seed-VC v1 / OpenVoice): 1-2,5 GB y acento fijado por el TTS base, pero dos etapas, sin emoción original y Seed-VC es GPL-3.0 y está archivado -> plan B.
6. **Español de España:** sin benchmarks públicos -> bake-off con oyente nativo; contra la fuga de acento: `x_vector_only` (Qwen3), `cfg_weight=0` (Chatterbox), modo `cross_lingual` (CosyVoice).
7. **Varios hablantes:** VAD + embedding (ReDimNet/WeSpeaker/CAM++, 15-50 ms) + clustering online + caché por personaje de la referencia limpia y del prompt del TTS; pyannote segmentation-3.0 solo para cambios de turno/solapes; Sortformer (Linux, ≤4) y diart (estancado) secundarios.
8. **LID en/ja/zh:** Whisper con logits restringidos a {en,ja,zh} + histéresis + validación por escritura; respaldo SenseVoice-Small / Qwen3-ASR (98,7 % Fleurs) / ECAPA VoxLingua107; no aislar la voz antes del LID.
9. **VRAM:** ~8 GB útiles (12,2 - 3,2 ya ocupados - margen): Whisper-turbo int8 (1,5-2) + MT 3-4B Q4 (2,5-3) + Qwen3-TTS-0,6B (3-3,5) + separador bajo demanda (1-1,5); con un juego: perfil ligero ≤5 GB.
10. **Riesgos:** latencia real en Windows + sm_120, acento es-ES, pines incompatibles/Python 3.13 (un venv por modelo; WSL2), referencias contaminadas, contención de GPU; licencias NC válidas para uso personal.

---

## 2) Tablas comparativas

### 2.1 Aislamiento de voz y realce (latencias en la 5070 = [E] salvo indicación)

| Modelo | Qué hace | Tamaño | Calidad reportada | Latencia por chunk (GPU fp16, 5070) | VRAM | Licencia | Python / Windows |
|---|---|---|---|---|---|---|---|
| **HT-Demucs v4** (`htdemucs`, `htdemucs_ft`) | 4 stems (vocals=voz cantada/hablada) | n/d [SV]; `_ft` = 4 modelos, 4x más lento [V] | SDR MUSDB 9,0 dB (ft) [V]; 9,20 con datos extra (paper) [V] | 0,1-0,3 s por ~8 s [E]; CPU ~1,5x la duración [V] | "≥3 GB; ~7 GB con args por defecto" [V]; fp16+segmento corto ~1,5-2,5 GB [E] | MIT [V] | Py ≥3.10, torch ≥2.1, PyPI 4.1.0 [V]; doc Windows [V]; el autor "ya no trabaja activamente" [V] |
| **BS-RoFormer / Mel-Band RoFormer** (incl. ckpt comunitarios "Kim", ep_317) | 2 stems vocals/instr., chunk de 8 s | 72-95 M params [V] | SDR vocals 10,8-12,7 dB (MUSDB18HQ, paper) [V]; 10,98-12,98 en tablas de ZFTurbo/audio-separator [V] | 0,3-1,0 s por 8 s [E]; más `num_overlap` = más calidad y tiempo [V] | 2-4 GB [E] | Código MIT [V]; pesos comunitarios sin licencia clara [SV] | `audio-separator` 0.47.0 (MIT; Py ≥3.10, ≠3.14.1; torch ≥2.3; onnxruntime-gpu) [V] |
| **SCNet** small/large | 4 stems | 10,1 M / 41,2 M [V] | vocals 9,89 / 10,86 dB [V] | 0,05-0,2 s [E] | <1 GB [E] | MIT [V] | pesos por Google Drive [V] |
| **MDX-Net / UVR** (Kim_Vocal_2...) | vocals/instr. (ONNX) | n/d | n/d | rápido [E] | ~1 GB [E] | pesos de comunidad [SV] | soportado por audio-separator y sherpa-onnx [V]; usado como preproceso opcional en Faster-Whisper-XXL [V] |
| **Bandit v2 multilingüe** (CASS: diálogo/música/efectos) | 3 stems orientados a cine | ckpt 446,7 MB cada uno [V]; el README de Bandit cita 33-83 M params según variante (el tamaño del ckpt sugiere más parámetros o estado extra) [SV] | SNR diálogo: en 15,3 / ja 14,9 / zh 15,5 / es 16,2 dB (DnR v3) [V] | 0,1-0,2 s por 6 s [E]; 290-390 GFLOPs/chunk y >10 batches/s en RTX 3090 [V] | 1-2 GB [E] | Código Apache-2.0; pesos CC BY-SA 4.0 [V] | PyTorch Lightning, `inference.py` [V]; Zenodo 12701995 [V] |
| **BandIt Plus** (ZFTurbo, DnR v2 en inglés) | voz/música/efectos | n/d | DnR: voz 15,64 / música 9,18 / fx 9,69 [V] | como Bandit [E] | como Bandit [E] | MIT (repo) [V] | riesgo: entrenado en inglés; el paper de Bandit v2 mide 2,2 dB en mandarín con un Bandit solo-inglés [V] |
| **SAM Audio** (Meta, dic-2025) | separación por prompt (texto/visual/span), a 16 kHz | 500M / 1B / 3B [V] | "SOTA" (sin SDR en el resumen) [V] | RTF ≈ 0,7 (Meta, HW n/d) [A]: demasiado lento para continuo | n/d [SV] | SAM License, acceso gated en HF [V] | Py ≥3.11; requiere PE-AV [V] |
| **DeepFilterNet3** | realce (ruido), 48 kHz | n/d [SV] | PESQ 3,17 (VoiceBank) [V] | RTF 0,19 en 1 hilo de i5-8250U; latencia 40 ms [V] | CPU | MIT o Apache-2.0 [V] | `deepfilternet` 0.5.6 (ago-2023); `deepfilterlib` solo ruedas ≤cp310 [V] -> **no instala en Py 3.13** sin compilar Rust |
| **DPDFNet** (Ceva) | realce, 8/16/48 kHz | 2,49-3,54 M params [V] | n/d | 20 ms + 10 ms/bloque [V] | CPU | Apache-2.0 [V] | ONNX/TFLite; soportado en sherpa-onnx [V] |
| **GTCRN** | realce ultraligero, 16 kHz | 48,2 K params, 33 MMACs/s [V] | DNSMOS P.808 3,44 (DNS3) [V] | RTF 0,07 en i5-12400 [V] | CPU | MIT [V] | sherpa-onnx [V] |
| **MossFormer2_SE_48K / FRCRN** (ClearerVoice-Studio) | realce de voz 48/16 kHz | n/d | n/d | n/d [SV] | ~0,5-1 GB [E] | Apache-2.0 [V] | `pip install clearvoice`, API NumPy desde jun-2025 [V] |
| **Resemble Enhance** | denoiser + enhancer generativo, 44,1 kHz | n/d | n/d | offline, pesado [E] | >1 GB [E] | MIT [V] | pip [V] |
| **NVIDIA Maxine AFX SDK / Broadcast** | denoise, dereverb, super-res, AEC | n/d | n/d | frames 10/20 ms [V] | n/d | EULA no indicada en docs [V]; sin mención a Blackwell [V] | API C, Windows 10 + VS2017, GPUs con Tensor Cores [V]; Broadcast: solo micrófono (Noise Removal, Studio Voice) en la página consultada [V] |

Lectura: los realzadores (DFN3, DPDFNet, GTCRN, MossFormer2, Maxine, Broadcast) están pensados para **ruido de voz en llamadas**, no para quitar la música de una mezcla de cine; para "voz vs música/efectos" los candidatos son los separadores, y de ellos solo Bandit v2 está entrenado para diálogo multilingüe.

### 2.2 ¿Mejora de verdad la separación al ASR? Evidencia

| Fuente | Condición | Resultado | Lectura |
|---|---|---|---|
| Whisper (arXiv 2212.04356) [V] | ruido aditivo (pub noise, LibriSpeech) | "todos los modelos degradan rápido al aumentar el ruido", y los supervisados quedan peor que Whisper con SNR <10 dB | Whisper es más robusto que los supervisados, pero también degrada con ruido intenso |
| Whisper-AT (2307.03183) [V] | sonidos de fondo reales | "Whisper es muy robusto a sonidos de fondo reales (p. ej. música)", pero sus representaciones dependen del tipo de ruido | lectura: Whisper tolera bien la música de fondo típica (sin cifras de WER por tipo de ruido en el paper) |
| **Jam-ALT** (2311.13987) [V] | letras de canciones, con HT-Demucs vs mezcla | la separación "en general empeoró": v2 35,7 -> 44,0 %; v3 35,5 -> 47,9 %; solo mejora v2 en inglés (43,8 -> 32,3 %) | mecanismo: con voz separada Whisper "a menudo transcribe en el idioma equivocado" -> **riesgo directo para el LID** |
| LyricWhiz (2306.17103) [V] | MUSDB18: stems reales vs mezcla | 26,3 % vs 50,9 % WER | techo teórico si la separación fuera perfecta (canto, SNR mucho peor que un diálogo) |
| Iwamoto et al. (2201.06685) [V] | realce como front-end de ASR | los **artefactos** son la causa principal de la degradación; "observation adding" (sumar una versión escalada de la señal original) mejora | si separas para el ASR, mezcla de vuelta 10-30 % del original [E para el factor] |
| Barański et al. ICASSP 2025 (2501.11378) [V] | Whisper large-v3; voz combinada con audio no-voz (AudioSet, MUSAN, UrbanSound8K, FSD50K; sin solape / con solape) | WER 104,8 / 112,0 % sin tratar; **Silero VAD 8,0 / 10,8 %**; deloop+BoH 17,1 / 21,1 %; ambos 6,5 / 9,4 % | el problema dominante es la no-voz (alucinaciones), y lo resuelve el VAD, no la separación (no probada) |
| Qwen3-ASR (ene-2026) [A] | canciones con BGM; LID | EntireSongs-en 14,60 / -zh 13,91 WER; M4Singer 5,98 vs 13,58 (Whisper-large-v3); LID 98,7 % vs 94,6 % (Fleurs, 30 idiomas) | los ASR nuevos absorben la música en el propio modelo |
| Fun-ASR-Nano (dic-2025) [A] | música de fondo | "mayor rendimiento con interferencia musical" (sin cifra en README) | idem |
| stable-ts `denoiser`; Faster-Whisper-XXL (MDX23 Kim_vocal_v2) [V] | preproceso opcional | las herramientas lo ofrecen como opción, sin evidencia cuantitativa | uso práctico, no prueba |
| DnR v3 / Bandit v2 (2407.07275) [V] | diálogo no inglés | Bandit solo-inglés "a menudo falla con diálogo no inglés, confundiendo fonemas no vistos y tonos lingüísticos con música/efectos": ja 9,0 dB, zh 2,2 dB, es 8,9 dB vs 14,9 / 15,5 / 16,2 dB del multilingüe | para ja/zh usar separadores entrenados en multilingüe |

**Conclusión:** no hay evidencia de que separar mejore el ASR en general; sí evidencia de que puede empeorarlo (artefactos, idioma equivocado). Puede ayudar solo con música dominante (SNR por debajo de ~5-10 dB [E]), como 2ª pasada y con mezcla de vuelta. Para la **clonación** la justificación es otra y más sólida: las referencias deben ser limpias (OpenVoice QA: "sin ruido de fondo"; F5-Spanish: "elimina el ruido de fondo de la referencia"; OmniVoice entrena una tarea de *prompt denoising*) [V].

### 2.3 (a) TTS zero-shot con clonación (en la 5070 = [E] salvo indicación)

| Modelo (fecha) | Params / VRAM | Idiomas clave | Referencia | Streaming / TTFA | Licencia | Windows / Py / Blackwell | Notas (acento, robustez) |
|---|---|---|---|---|---|---|---|
| **Qwen3-TTS-12Hz Base 0,6B / 1,7B** (22-ene-2026) | pesos ≈2,5 / 4,5 GB (bf16) [V]; uso ~3-3,5 / 5-6 GB [E] | 10: zh,en,ja,ko,de,fr,ru,pt,**es**,it [V] | 3 s; ICL pide `ref_text`; `x_vector_only_mode` sin texto [V] | sí. Paper: 97/101 ms, RTF 0,288/0,313 (vLLM+CUDA graphs, c=1) [A]. **faster-qwen3-tts**: 4090 156/174 ms (4,78x/4,22x tiempo real); **RTX 4060 Windows 413/460 ms** (2,26x/1,83x); base HF 800 ms y 0,82x en 4090 [V] | Apache-2.0 [V] | `pip qwen-tts` 0.1.1 (Py 3.9-3.13; `transformers==4.57.3`) [V]; faster-qwen3-tts MIT con `setup_windows.bat` [V]; su tabla incluye un DGX Spark (GB10, Blackwell): TTFA 567 -> 280 ms [V] = indicio de que corre en Blackwell; sm_120 de la 5070 sin verificar | SIM es 0,812/0,814, WER es 1,49/1,13 (set propio, misma lengua) [A]; zh->es SS 68,02, WER 5,15 (medido por el equipo IndexTTS) [A]; acento es-ES [SV]; issue #341 "eco de la cola de la referencia"; sin concurrencia (#350) [V] |
| **Fun-CosyVoice3-0,5B-2512** (dic-2025) | LM 0,5B + CFM DiT 300M [V]; ~3-4 GB [E] | 9: zh,en,ja,ko,de,**es**,fr,it,ru + 18 dialectos zh [V] | corto; modos `zero_shot` (texto+audio) y `cross_lingual` (solo audio) [V]; `add_zero_shot_spk` cachea por personaje [V] | bi-streaming "150 ms" [A]; con TRT-LLM en L20: primer chunk ~750 ms con 4 peticiones; RTF 0,109 offline [V]; sin cifras en Windows [SV] | Apache-2.0 [V] | conda Py 3.10; vLLM/TRT-LLM (Linux) [V] | es WER 4,25 % (0,5B), ja CER 10,4 % (0,5B) en CV3-Eval [V]; zh->es SS 64,04, WER 4,58 [A]; parámetro `speed` [V] |
| **Chatterbox Multilingual V3 (500M) + pack es-es** (jun-2026 según fechas de HF) | es-es: T3 2,14 GB + S3Gen 1,06 GB (fp32) [V]; ~3-4 GB [E] | 23 incl. es/ja/zh/en; **es-es = finetune para España** [V] | ~10 s (ejemplos) [V]; condicionamiento cacheable [V] | fork streaming en 4090: 0,472 s al 1er chunk, RTF 0,499 [A]; base sin optimizar en 4090: 6,5 s de audio en 3,1 s (issue #552, propuesta de CUDA graphs: 2,0 s) [V]; Flash/Turbo solo inglés [V] | MIT; watermark PerTh [V] | `chatterbox-tts` 0.1.7 fija `torch==2.6.0` (sin sm_120) -> forzar torch ≥2.7 cu128 (el server comunitario usa 2.9.0) [V]; ese server exige Py 3.10 [V] | "con referencia de otro idioma pon `cfg_weight=0` para no transferir acento" [V]; la card de es-es no da benchmarks ni menciona cross-lingual [V] |
| **OmniVoice** (k2-fsa; abr-2026) | 0,6B, pesos 2,45 GB [V]; ~3 GB [E] | 600+ idiomas; es WER 1,03 / SIM-o 0,804; ja 4,03 / 0,828; zh 1,01 / 0,821; en 1,56 / 0,884 (misma lengua) [V] | 3-10 s; `ref_text` opcional (Whisper); `duration` y `speed` explícitos [V] | NAR: RTF 0,0319 (16 pasos, H20) [V]; sin streaming, frase completa 0,2-0,5 s [E] | código Apache-2.0; **pesos CC-BY-NC** [V] | pip/uv, PyTorch 2.8 [V] | **"el clonado cross-lingual conserva el acento del idioma de la referencia"** [V] -> malo para en/ja -> es; entrenado con *prompt denoising* `<|denoise|>` [V] |
| **VoxCPM2** (OpenBMB; abr-2026) | 2B; **~8 GB** [V] | 30 (es,ja,zh,en...) [V] | corto; "ultimate cloning" con transcripción [V] | RTF 0,30 (4090) / 0,13 (Nano-vLLM); `generate_streaming` [V] | Apache-2.0 [V] | Py ≥3.10 <3.13 [V] | 48 kHz; demasiado VRAM para tu presupuesto |
| **IndexTTS-2.5** (paper ene-2026; pesos 10-ago-2026) | 0,8B; **~6 GB** [V] | zh,en,ja,**es**,ar [V]; datos es: Common Voice, dataset argentino, TEDx [V] | 1 clip; emoción por audio/vector/texto; `duration_factor` 0,5-2,0 [V] | RTF 0,2065 (4090, BF16) vs 0,3257 IndexTTS2 [V]; sin streaming [SV] | Licencia Bilibili: uso personal sin contactar; prohíbe usarlo para mejorar otros modelos de IA salvo no comerciales [V] | uv, CUDA ≥12.8, DeepSpeed opcional [V] | zh->es SS 64,5-65,5, WER 4,9-5,2 [A]; mejor control expresivo para drama |
| **XTTS-v2** (fork Idiap 0.27.5, ene-2026) | ~2-3 GB [E] | 17 (es,ja,zh-cn,en...) [V] | 6 s [V]; `get_conditioning_latents` cacheable [V] | `inference_stream`; "<200 ms" [V] | CPML (no comercial) [V]; fork MPL-2.0 | Py ≥3.10 <3.15; ruedas Windows [V] | calidad inferior a 2026 [E]; fallback estable |
| **F5-TTS + F5-Spanish** | ~1-2 GB [E] | F5-Spanish: 218 h (Voxpopuli peninsular + 6 acentos LatAm) [V] | necesita `ref_text` | RTF 0,04-0,15 (L20) [V] | código MIT; pesos CC-BY-NC [V] | n/d | pensado para misma lengua, no cross-lingual [E] |
| **MOSS-TTS** (Nano 0,1B / Realtime 1,7B / v1.5 4-8B; abr-jun 2026) | Nano: CPU 4 núcleos [V] | 20-31 idiomas incl. es/ja/zh [V] | zero-shot | Realtime: 180 ms TTFB [A] | Apache-2.0 [V] | torch/FFmpeg [V] | Nano es candidato "sin VRAM"; calidad [SV] |
| **Fish OpenAudio S1-mini** (0,5B destilado) y Fish-Speech 1.5 | 0,5B [V]; VRAM y latencia local [SV] | 13 idiomas incl. es (~20 000 h en la 1.5), ja, zh, en [V] | 10-30 s (guía de Fish) [V] | sin cifras locales [SV] | CC-BY-NC-SA-4.0 [V] | n/d | etiquetas de emoción `(angry)`, `(whispering)`...; S1-mini WER 0,011 y distancia de locutor 0,380 en inglés (menor es mejor; S1 4B: 0,008/0,332) [A]; **candidato a incluir en el bake-off** |
| Fish Audio S2 Pro / Higgs Audio v3 / Voxtral TTS | 5B / 4B / 4B (≥16 GB) [V] | 80+ / 100+ / 9 (sin ja/zh) [V] | 10-30 s / n/d / n/d | ~100 ms (H200) / n/d / 70 ms (H200) [A] | investigación-no comercial / no comercial / CC BY-NC [V] | - | **no caben** en 12 GB junto a ASR+MT; zh->es de Fish S2 Pro: WER 4,46 pero SS 55,57 [A] |
| MaskGCT, Spark-TTS | - | 6 idiomas **sin es**; solo zh/en [V] | - | - | CC-BY-NC / Apache | - | descartados |
| Sin clonación: Kokoro, Piper, MeloTTS, Magpie v2607, VibeVoice-Realtime, Kyutai TTS | - | - | - | - | - | - | Magpie *eliminó* el zero-shot; VibeVoice-TTS-1.5B deshabilitado; Kyutai solo en/fr [V]. Sirven como TTS base para (b) |

Nota sobre métricas: SIM/SS/WER de tablas distintas **no son comparables** (verificadores y test sets distintos) y los sistemas de verificación de locutor tienen sesgo de idioma (TidyVoice 2026) [V]; úsalas solo para orden de magnitud.

**Robustez con referencias ruidosas (lo que realmente se sabe).** Ningún modelo publica una evaluación con referencias ruidosas reales (música/efectos); hay que asumir que **todos necesitan prompt limpio**:
- OmniVoice: único con entrenamiento explícito de *prompt denoising* (`<|denoise|>`); su ablación es sobre prompts limpios (UTMOS 4,23 -> 4,32; SIM-o 0,697 -> 0,668) [V].
- Qwen3-TTS: sin cifras; el paper menciona filtrado de calidad de datos para reducir alucinaciones [V]; en uso real aparece "eco de la cola de la referencia" (issue #341) y el wrapper añade 0,5 s de silencio; `x_vector_only` depende menos del contenido del audio pero pierde parecido [V].
- CosyVoice3: entrenado "in-the-wild" (título del paper) pero sin evaluación de prompts ruidosos [V].
- Chatterbox, XTTS-v2: sin documentación; las guías recomiendan una referencia limpia de ~6-10 s [V/SV].
- OpenVoice: "audio limpio, sin ruido de fondo, un solo hablante, sin huecos" [V]; F5-Spanish: "elimina el ruido y equilibra niveles de la referencia" [V].
- Seed-VC (entrenado con Emilia, en condiciones reales): tolerancia sin medir [SV].

### 2.3 bis Matriz cualitativa de candidatos (++ mejor / - peor; juicio propio [E])

| Criterio | Qwen3-TTS 0,6B | Chatterbox es-es | CosyVoice3 | OmniVoice | IndexTTS-2.5 | XTTS-v2 | (b) TTS base + Seed-VC |
|---|---|---|---|---|---|---|---|
| TTFA en la 5070 | ++ (0,2-0,35 s) | + (0,5-0,9 s) | + (sin acelerar: sin datos) | ++ (frase completa 0,2-0,5 s) | - (>1 s) | + | ++ (0,35-0,65 s) |
| VRAM | + (3-3,5 GB) | + (3-4) | + (3-4) | + (~3) | - (~6) | ++ (2-3) | ++ (1-2,5) |
| Similitud cross-lingual | ++ (mayor en zh->es [A]) | 0 (sin datos) | + | + | + | 0 | + (SECS alto en misma lengua) |
| Acento es-ES / fuga de acento | 0 (sin datos) | + (finetune es-ES, `cfg_weight=0`) | 0 (modo cross_lingual) | - (arrastra acento) | 0/- (datos argentinos/CV/TEDx) | 0 | ++ (lo fija el TTS base) |
| Windows + Blackwell | + (script Windows; sm_120 sin verificar) | 0 (pines torch; Py 3.10) | - (Linux-first, Py 3.10) | 0 | 0 (uv, CUDA 12.8) | ++ | 0 (GPL; archivado) |
| Licencia (uso personal) | ++ (Apache-2.0) | ++ (MIT) | ++ (Apache-2.0) | + (pesos NC) | + (Bilibili) | + (CPML NC) | + (GPL-3.0) |
| Emoción / duración | 0 | 0 | + (instrucciones, `speed`) | + (`duration`) | ++ (emoción aparte, `duration_factor`) | - | - |
| Streaming | ++ | + (por chunks) | ++ (Linux) | - | - | + | + |

### 2.4 (b) TTS neutro + conversión de voz

| Opción | Referencia | Latencia | VRAM | Similitud / calidad | Licencia | Notas |
|---|---|---|---|---|---|---|
| **Seed-VC v1 real-time** (25M) / offline (98M) / v2 (157M) | 1-30 s [V] | 430 ms totales en RTX 3060 laptop (bloque 0,18 s, 150 ms/chunk a 10 pasos) [V] | 1-1,5 GB [E] | SECS 0,8676, WER 11,99 % (LibriTTS, misma lengua) vs OpenVoice 0,7547/15,46 vs CosyVoice-VC 0,8440/18,98 [V] | **GPL-3.0; repo archivado 21-nov-2025** [V] | v2 hace "voice/accent VC": puede traspasar el acento de la referencia (en/ja) [E] -> usar v1 (timbre) |
| **OpenVoice V2** (TCC + MeloTTS es/en/zh/ja/ko/fr) | limpia, sin ruido [V] | 12x tiempo real en A10G (85 ms por s de habla) [V] | <1 GB [E] | "solo clona el timbre, no el acento ni la emoción" [V]; SECS 0,7547 [V] | MIT [V] | el más ligero; menor similitud |
| **Chatterbox VC** (mismo S3Gen) | clip | n/d | comparte modelo | n/d | MIT [V] | aprovecha el mismo runtime si usas Chatterbox |
| **CosyVoice `inference_vc`** | clip | n/d | ~3 GB | SECS 0,844, WER 18,98 % [V] | Apache-2.0 | peor WER |
| **MeanVC** (ASLP) | audio limpio del objetivo | streaming por chunks, 1-2 pasos [V] | n/d | sin cifras en el README [V] | Apache-2.0 [V] | sin evidencia cross-lingual |
| kNN-VC | ~5 min de referencia [V] | n/d | WavLM-Large | - | LICENSE sin verificar | inviable (referencia corta) |
| RVC | **entrenar** con ≥10 min limpios; 170 ms (90 con ASIO) [V] | - | - | no zero-shot | MIT [V] | solo para protagonistas (offline) |
| Vevo | - | - | componentes 740M+480M+330M+250M [V] | entrenado sin español [V] | CC-BY-NC [V] | descartado |

TTS base con castellano: Piper `es_ES` (carlfm, davefx, mls_10246, mls_9972, sharvard; piper1-gpl, GPL-3.0; CPU/ONNX) [V]; MeloTTS "ES" (MIT; CPU en tiempo real; acento no documentado) [V]; Kokoro-82M (Apache-2.0; voces ef_dora, em_alex, em_santa; dialecto no documentado) [V]; Chatterbox es-es sin referencia.

### 2.5 Varios hablantes: diarización y embeddings

| Opción | Qué aporta | Latencia / VRAM | Límites | Licencia | Windows / Py |
|---|---|---|---|---|---|
| **Silero VAD** | segmentación de voz | <1 ms por chunk de 30 ms, 1 hilo CPU; modelo ~2 MB [V] | no distingue voz de música cantada [SV] | MIT [V] | PyTorch/ONNX [V] |
| **pyannote segmentation-3.0** | cambio de turno y solapes (powerset: ≤3 hablantes/chunk, ≤2/frame), ventana 10 s | 8 ms GPU / 11 ms CPU por chunk de 5 s (RTX 4060 Max-Q) [V] | gated; entrenado con AISHELL, AliMeeting, AMI, **AVA-AVD (cine)**, DIHARD, Ego4D, MSDWild, **REPERE (TV)**, VoxConverse [V] | MIT [V] | pyannote.audio 4.0.7 (torch ≥2.8) [V] |
| pyannote community-1 (pipeline) | mejor conteo/asignación, "exclusive diarization" | offline; RTF n/d [V] | gated (token HF) | CC-BY-4.0 [V] | - |
| **diart** | diarización incremental, paso de 500 ms (0,5-5 s) | seg 8-12 ms + emb 12-29 ms por paso (GPU) [V] | último commit 12-feb-2025; Py 3.10-3.12; `numpy<2`; "Beta" [V] | MIT [V] | WhisperLiveKit: solo Py 3.11-3.12 [V] |
| **Streaming Sortformer v2 / v2.1** (NVIDIA) | diarización end-to-end en streaming | 117 M params; latencias 0,32/1,04/10/30,4 s; ~0,5-1 GB [E] | ≤4 hablantes; DER DIHARD III 13,24 % (1-4 hab.), 15,09 % @1,04 s (v2.1), 41,42 % con 5-9 hab.; "degrada en no-inglés y ruido" [V] | CC-BY-4.0 (v2) / NVIDIA Open Model License (v2.1) [V] | **NeMo solo Linux** (sin guía Windows/WSL) [V] |
| Embeddings: **WeSpeaker ResNet34-LM** | ID de personaje | 15 ms GPU / 48 ms CPU por 5 s [V] | - | CC-BY-4.0 [V] | pyannote |
| **CAM++ / ERes2NetV2** (3D-Speaker) | ID de personaje | CAM++ 7,2 M params, EER 0,65 % (Vox1-O); ERes2NetV2 17,8 M, 0,61 % [V] | sesgo a zh/en [V] | Apache-2.0 [V] | ModelScope |
| **ReDimNet b0-b6** | ID de personaje | 1-15 M params, 0,5-20 GMACs, emb. 192-d [V] | - | MIT [V] | `torch.hub` |

### 2.6 Detección de idioma (en/ja/zh)

| Método | Cobertura | Fiabilidad | Coste | Licencia | Notas |
|---|---|---|---|---|---|
| **Whisper (token de idioma)** | 99 idiomas | Fleurs: 64,5 % (102 idiomas) / 80,3 % (82 con datos) [V, large-v2]; 94,6 % en 30 idiomas (v3, tabla de Qwen) [A] | un paso de encoder (ya lo pagas al transcribir) + 1 de decoder | MIT | faster-whisper: `detect_language(language_detection_segments=1, language_detection_threshold=0,5)`, `multilingual=True` por segmento [V]; WhisperX solo mira los primeros 30 s [V]; **falla con voz separada** (Jam-ALT) [V] |
| **Qwen3-ASR 0,6B/1,7B** (ene-2026) | 52 idiomas y dialectos | **98,7 %** Fleurs (30 idiomas) [A] | ASR completo; streaming solo vía vLLM [V] | Apache-2.0 | entrenado con canciones y BGM [A] |
| **SenseVoice-Small** | zh, yue, en, ja, ko | sin cifras de LID ni en el README ni en el paper (2407.04051) [V] | 234M params; 70 ms por 10 s de audio (RTF 0,007) y 15x más rápido que Whisper-Large [A]; ONNX/GGUF/sherpa-onnx [V] | MIT + licencia FunASR | además emoción (7) y eventos (BGM, risa, aplausos...) en una pasada [V] |
| **SpeechBrain VoxLingua107-ECAPA** | 107 idiomas | 6,7 % de error en dev; peor con acentos extranjeros y voces femeninas [V] | trivial (CPU) | Apache-2.0 | emb. 256-d; la duración mínima fiable no está documentada [V] |
| **MMS-LID-126** | 126 idiomas | n/d | 1B params (wav2vec2) | **CC-BY-NC** [V] | descartado |
| Validación por escritura (kana/han/latino) sobre el texto del ASR | en/ja/zh | [E] alta en texto ≥3-4 caracteres | nula | - | kana => ja; han sin kana => zh; latino => en |

### 2.7 Presupuesto de VRAM (componentes, inferencia)

| Componente | VRAM aprox. | Etiqueta |
|---|---|---|
| ASR: faster-whisper large-v3 fp16 / int8 | 4,5 GB / 2,9 GB (RTX 3070 Ti, beam 5) | [V] |
| ASR: Whisper large-v3-turbo fp16 / int8 | ~2-2,5 / ~1,3-1,6 GB | [E] |
| ASR: SenseVoice-Small / Qwen3-ASR-0,6B / 1,7B | <1 / ~2 / ~4 GB | [E] |
| MT (dato del encargo) | 2-6 GB | - |
| Separador bajo demanda: Bandit v2 / HT-Demucs fp16 / RoFormer | 1-2 / 1,5-2,5 / 2-4 GB | [E] |
| Realce DFN3 / DPDFNet / GTCRN / VAD / LID ECAPA / embeddings | CPU (0 GB) | [V/E] |
| TTS: Qwen3-TTS 0,6B / 1,7B | 3-3,5 / 5-6 GB | [E] |
| TTS: Chatterbox es-es / CosyVoice3 / OmniVoice / XTTS-v2 | 3-4 / 3-4 / ~3 / 2-3 GB | [E] |
| TTS: IndexTTS-2.5 / VoxCPM2 | ~6 / ~8 GB | [V] |
| VC: Seed-VC real-time + vocoder | 1-1,5 GB | [E] |
| Sobrecarga por contexto CUDA (cada proceso) | 0,3-0,5 GB | [E] |
| **Ya ocupado por Windows/apps (medido hoy)** | **3,2 GB** | [V] |

Combinaciones (suma de picos; 12,2 GB totales; margen mínimo recomendado 1 GB):

| Perfil | Composición | Total aprox. | Veredicto |
|---|---|---|---|
| **Ligero / juego** | SenseVoice-Small o Whisper-turbo int8 (0,5-1,5) + MT 1-2B Q4 o NLLB-600M int8 (1-1,5) + TTS en CPU (Piper/Kokoro/MOSS-Nano) o XTTS-v2 (2-3) + Seed-VC rt (1-1,5) opcional | 3-6 GB | viable junto a un juego que use <5 GB [E] |
| **Equilibrado (recomendado)** | Whisper-turbo int8 (1,5-2) + MT 3-4B Q4 (2,5-3) + **Qwen3-TTS-0,6B** (3-3,5) + separador Bandit v2 bajo demanda (1-1,5) | 8-10 GB pico, ~7-8 GB sin separador | cabe si el resto de la GPU usa ≤3 GB; descargar el separador cuando VRAM libre <1,5 GB |
| **Calidad** | Whisper-turbo fp16 (2,5) + MT 4B Q4 (3) + Qwen3-TTS-1,7B (5-6) | ~11 GB | casi sin margen; solo sin juego ni navegador pesado |
| **Expresivo** | ASR (2) + MT (3) + IndexTTS-2.5 (6) | ~11 GB | TTFA >1 s y sin margen: solo para pruebas |

---

## 3) Detalle por opción

### 3.1 Aislamiento y realce de voz

**Cómo se usa cada familia en segmentos de 1-8 s.** Los separadores trabajan con chunks nativos (RoFormer 8 s [V], Bandit 6 s [V], Demucs ~7,8 s [SV]) a 44,1 kHz estéreo; hay que rellenar/solapar (overlap-add) y con menos de ~3 s de contexto la calidad baja [E]. En modo "ventana deslizante" (p. ej. 6 s con salto de 1 s) el coste se multiplica por ventana/salto: con Bandit v2 (~0,12 s por ventana [E]) serían ~12 % de GPU; con un RoFormer (~0,5 s [E]) ~50 %, inviable en continuo junto a ASR+TTS. Por eso el separador debe ir **fuera de la ruta crítica** y a baja prioridad.

**Bandit v2 multilingüe (recomendado para aislar diálogo).** Reimplementación del modelo Bandit entrenada con DnR v3 (32 idiomas) [V]. Checkpoints por idioma y uno `multi` en Zenodo (446,7 MB cada uno) [V]. Resultados de SNR de diálogo: inglés 15,3 (monolingüe 15,6), japonés 14,9 (Bandit solo-inglés: 9,0), mandarín 15,5 (2,2), español 16,2 (8,9) [V]. Es el único candidato con evidencia cuantitativa en ja/zh. Contras: código de investigación (PyTorch Lightning/Hydra), el repo unificado "banda" es AGPL/investigación [V], pesos CC BY-SA 4.0 (sin problema para uso personal). Entrada/salida 44,1 kHz.

**HT-Demucs v4.** Sólido, MIT, fácil (`demucs.api`/CLI), pero "vocals" es canto+habla de un modelo de música y **no hay evidencia publicada en diálogo ja/zh** [SV]. Útil como plan B sencillo. El autor avisa de que ya no lo mantiene activamente [V].

**BS-/Mel-Band RoFormer.** Mejor SDR en música (12,7-13 dB) pero 72-95 M params, atención sobre tiempo y bandas; `python-audio-separator` los expone bien (MIT, pip, Py ≥3.10). Sin evidencia de ventaja en diálogo; coste alto. Reservar para construir referencias de alta calidad de personajes principales (offline/lazy).

**SAM Audio (Meta, 16-dic-2025).** Separación por prompt de texto ("a man speaking"), 0,5B/1B/3B, RTF ≈0,7 según Meta [A] (hardware no indicado), licencia SAM y acceso gated; 16 kHz. Demasiado pesado para tiempo real; interesante para extraer *un* hablante concreto en offline.

**Realce (DFN3, DPDFNet, GTCRN, MossFormer2, Maxine, Broadcast).** Quitan ruido, no música; la música es estructurada y los realzadores tienden a dejarla pasar o a dañar la voz [SV]. Útiles como pulido ligero de una referencia ya aislada. Ojo: DeepFilterNet3 por pip solo tiene ruedas hasta Python 3.10 [V]; alternativa: DPDFNet/GTCRN vía sherpa-onnx (hay rueda `cp313-win_amd64` de sherpa-onnx 1.13.8 [V]). NVIDIA Maxine AFX es API C propietaria, sin mención a Blackwell y pensada para voz de llamada; NVIDIA Broadcast (página consultada) solo habla del micrófono [V]: descartados.

**Trucos baratos (no verificados en tu contenido):**
- *Mid/side:* el diálogo suele ir al centro; `M=(L+R)/2` realza el diálogo respecto a música/efectos anchos. Si el dispositivo de salida está configurado como 5.1, WASAPI loopback devuelve el formato de mezcla del endpoint (podrías leer el canal central) [SV]. Con auriculares en estéreo o audio espacial, no aplica.
- *Observation adding:* mezclar de vuelta 10-30 % del original a la voz separada antes del ASR [E sobre el factor; idea verificada en 2201.06685].
- *Gating de música:* SenseVoice etiqueta `BGM`; Whisper-AT da etiquetas de eventos; umbrales de Whisper (`compression_ratio_threshold` 2,4, `logprob_threshold` -1,0, `no_speech_threshold` 0,6 por defecto [E, conocimiento del código]) para activar la 2ª pasada.

### 3.2 (a) TTS zero-shot: notas por modelo

**Qwen3-TTS (principal).**
- Arquitectura: LM dual-track (texto y tokens acústicos concatenados por canal) + módulo MTP que decodifica desde el primer frame de códec; tokenizer 12 Hz multi-codebook con decodificador ConvNet (sin difusión) [V]. Entrenado con >5 M horas en 10 idiomas [V].
- Clonación: `create_voice_clone_prompt(ref_audio, ref_text)` se construye una vez y se reutiliza (`voice_clone_prompt`) -> caché por personaje [V]. Modo ICL (audio+transcripción; más similitud; puede producir artefacto inicial/eco de la cola de la referencia) vs `x_vector_only` (solo embedding; no pide texto; "cambio de idioma más limpio") [V]. El wrapper faster-qwen3-tts añade 0,5 s de silencio al final de la referencia contra el "phoneme bleeding" [V].
- Latencia en consumo: base HF en 4090: 800 ms y 0,82x tiempo real; con CUDA graphs: 156 ms y 4,78x (0,6B); RTX 4060 (Windows): 413 ms y 2,26x; 1,7B: 174 ms/4,22x (4090) y 460 ms/1,83x (4060). `chunk_size` bajo reduce TTFA (p. ej. Jetson Orin: chunk 1 = 240 ms, chunk 8 = 556 ms) [V]. Extrapolación a la 5070: 3-4x tiempo real y TTFA 0,2-0,35 s [E] (la 4090 no escala linealmente con la 4060: el decode es sensible a latencia de kernels y CPU; tu 8700F ayuda).
- Calidad: SIM es 0,81 (0,6B y 1,7B), WER es 1,1-1,5 % (set propio) [A]; en la comparativa de IndexTTS (zh->es) tiene la mayor similitud (68,02) con WER 5,15 [A]; el paper dice mayor similitud que MiniMax y ElevenLabs en 10 idiomas y reduce ~66 % el error en zh->ko frente a CosyVoice3 [A].
- Estado del motor rápido: faster-qwen3-tts está activo (release 0.5.3 el 29-sep-2026) y su README dice "RTX 50xx / Blackwell necesitan ruedas de PyTorch con CUDA 12.8" y ofrece instalación nativa en Windows (`setup_windows.bat`) con benchmark en RTX 4060 (Windows) [V]. Pero el issue #92 (28-mar-2026) de un usuario con RTX 5090 en Windows nativo reporta 3-5 s por frase con el paquete base y afirma que la captura de CUDA graphs "requiere Linux"; sin respuesta de los mantenedores [V]. Hay que comprobarlo en la 5070 (hito 0 del plan 4.6); fallback: WSL2.
- Otros problemas abiertos: prosodia/tono inconsistentes entre chunks cuando se sintetiza por trozos (issue #96, 1,7B CustomVoice), excepciones con ejecución concurrente (#85), `--instruct` no combina con clonación (#126) [V].
- Contras: sin control explícito de acento/dialecto hispano; `transformers` fijado a 4.57.3; vLLM-Omni solo offline; sin concurrencia; FlashAttention 2 opcional (en Windows usar SDPA) [V/SV].

**CosyVoice3-0,5B.** 9 idiomas, cross-lingual y zero-shot, `stream=True`, `speed`, instrucciones en lenguaje natural (emoción, dialecto, velocidad), normalización de texto sin frontend externo [V]. Caché: `add_zero_shot_spk(prompt_text, prompt_wav, id)` y `save_spkinfo()` [V]. Las cifras de latencia "150 ms" requieren vLLM/TRT-LLM (Linux); en TRT-LLM L20 con 4 concurrentes el primer chunk fue ~750 ms [V]. Instalación oficial: conda Python 3.10 [V]. Buen candidato si se usa WSL2.

**Chatterbox Multilingual V3 / es-es.** El pack "Single Language Pack" incluye `Chatterbox-Multilingual-es-es` (finetune "optimizado para español tal como se habla en España", T3 2,14 GB + S3Gen 1,06 GB) [V]. MIT, con watermark PerTh incrustado [V]. Streaming real solo por chunks en forks (4090: 0,47 s al primer chunk, RTF 0,499) [A]; el vLLM-fork solo Linux/WSL2 [V]. Pin `torch==2.6.0` en PyPI incompatible con sm_120: hay que instalar torch ≥2.7 (cu128) por encima (server comunitario: 2.9.0, driver ≥570) [V]. Consejo oficial: con referencia en otro idioma, `cfg_weight=0` [V]. No hay benchmarks públicos para es-es [V].

**OmniVoice.** NAR (diffusion-LM) con 600+ idiomas, `duration`/`speed` exactos y 0,6B; RTF 0,03 en H20 [V]. Bueno para isocronía y latencia de frase completa, pero su README avisa de que el clonado cross-lingual "lleva acento del idioma de la referencia" [V] y los pesos son CC-BY-NC [V]. Entrenamiento con *prompt denoising* (`<|denoise|>`): ablación en LibriSpeech-PC limpio: UTMOS 4,23 -> 4,32 con SIM-o 0,697 -> 0,668 [V] (no mide referencias ruidosas reales).

**IndexTTS-2.5.** Única opción con desacople de emoción y locutor (referencia de emoción distinta de la de timbre) y `duration_factor` [V]: ideal para "voz del personaje limpia + emoción del clip original". Cuesta ~6 GB, RTF 0,21 en 4090 y no hay streaming documentado. Licencia Bilibili (personal sin trámite) [V]. Datos de español mayormente argentinos/Common Voice/TEDx [V].

**VoxCPM2, Fish S2 Pro, Higgs v3, Voxtral TTS, MOSS v1.5:** buena calidad pero 4-8B params -> 8-16 GB de VRAM [V]; no caben con ASR+MT en 12 GB (y los tres últimos tienen licencia no comercial/investigación, aceptable para uso personal). **MOSS-TTS-Nano (0,1B)** corre en 4 núcleos de CPU con streaming [V]: candidato para el perfil "juego", calidad [SV].

**XTTS-v2.** El plan B "aburrido": 6 s de referencia, streaming (<200 ms según el fork de Idiap), 17 idiomas, Python 3.13 soportado, ruedas Windows [V]. Licencia CPML (no comercial). Calidad y expresividad inferiores a 2026 [E].

**Qwen-Audio-3.0-TTS (jul-2026):** la variante "Plus" es **solo API** ("weights closed") [V]; no sirve para un proyecto 100 % local.

### 3.3 (a) frente a (b)

| Criterio | (a) TTS zero-shot | (b) TTS neutro + VC |
|---|---|---|
| Modelos / VRAM | 1 modelo, 3-6 GB | 2 modelos, 1-2,5 GB (TTS en CPU posible) |
| Tiempo a 1er audio | Qwen3 0,2-0,35 s [E] | TTS base 0,05-0,2 s + VC 0,3-0,45 s (430 ms de Seed-VC en una 3060 laptop [V]) = 0,35-0,65 s [E] |
| Parecido de voz | alto en misma lengua; cross-lingual ~0,64-0,68 (verificador IndexTTS) [A] | SECS 0,87 (Seed-VC, misma lengua) [V]; en cross-lingual sin datos [SV] |
| Acento es-ES | depende del modelo y fuga de acento de la referencia | lo fija el TTS base castellano (Piper es_ES/MeloTTS ES/Chatterbox es-es); Seed-VC v1 cambia solo timbre |
| Emoción / prosodia | parcialmente copiada del prompt (ICL); IndexTTS la controla aparte | la del TTS base (neutra); se pierde el drama |
| Referencias ruidosas | todos piden limpias; solo OmniVoice entrena denoising | Seed-VC entrenado en Emilia (in-the-wild), tolerancia [SV] |
| Mantenimiento / licencia | Apache/MIT (Qwen3, CosyVoice3, Chatterbox) | Seed-VC GPL-3.0 y archivado; OpenVoice MIT pero menos similitud |
| Complejidad | baja | media-alta (dos etapas, sincronía de chunks) |

### 3.4 Varios hablantes: cómo elegir la referencia por frase

1. **Usar el propio segmento como referencia** solo funciona si ya es limpio y ≥3-5 s; los segmentos de diálogo real suelen ser cortos (1-3 s [E]), con música y solapes -> mala referencia (eco de cola, música en la voz, timbre inestable).
2. **Registro por personaje** (recomendado): por cada segmento de voz, embedding (ReDimNet-b2 / WeSpeaker ResNet34 / CAM++; 15-50 ms en CPU o GPU [V]) y asignación al personaje más cercano por coseno con umbral calibrado (no hay umbral universal [E]) y centroide con media móvil. Cada personaje guarda: `centroid`, `f0` mediano (género), 1-3 clips limpios de 5-10 s en total, su `ref_text` (la transcripción del ASR, que ya tienes gratis), puntuación de calidad (SNR del stem de diálogo frente a la mezcla, DNSMOS/UTMOS) y el **prompt del TTS ya calculado** (`voice_clone_prompt` en Qwen3-TTS; `add_zero_shot_spk` en CosyVoice; `get_conditioning_latents` en XTTS; condicionamientos en Chatterbox).
3. **Cambio de hablante dentro del segmento y solapes:** pyannote segmentation-3.0 (8-11 ms por chunk de 5 s [V]) da cambios de turno y solape; si hay solape, **no actualizar** el registro y usar la última voz conocida o la voz por defecto.
4. **Arranque en frío** (primera frase de un personaje nuevo): (i) aislar ese segmento en la ruta crítica con Bandit v2 (~0,1-0,3 s [E]) o (ii) TTS con `x_vector_only`/voz neutra del mismo género y refinar después. Congelar la referencia cuando la puntuación supere un umbral: cambiar de referencia a mitad de episodio cambia la voz percibida.
5. **Streaming diarization:** diart (MIT) es el más simple de usar pero estancado; Sortformer es el más preciso en streaming (DER 13-19 % con 1-4 hablantes) pero solo NeMo/Linux, ≤4 hablantes y "degrada en no-inglés y ruido" [V]; pyannote community-1 es offline (usable por ventanas de 10-30 s como "re-etiquetado" diferido). Para el objetivo (registro de personajes) es suficiente el enfoque DIY de arriba; la diarización solo aporta cambios de turno.
6. **Fuera de alcance v1:** personajes solapados, coros, voz filtrada (radio/robot en juegos) -> usar voz por defecto.

### 3.5 Detección de idioma en streaming (en/ja/zh)

- **Con el propio Whisper** (recomendado): una sola pasada de encoder ya pagada; restringe los logits de los tokens de idioma a {en, ja, zh} y renormaliza (conjunto cerrado -> mucho más fiable que los 99 idiomas) [E]. En faster-whisper: `detect_language(...)` devuelve `all_language_probs`; con `multilingual=True` detecta por segmento [V].
- **Histéresis de sesión:** prior fuerte al idioma de la sesión; cambiar solo tras 2 segmentos consecutivos con p>0,8 o ≥3-4 s de voz acumulada en contra; no actualizar con segmentos de música/no-voz (etiqueta BGM de SenseVoice o bajo `no_speech_prob`). Acumular voz de 3-6 s antes de decidir al inicio.
- **No hay cifras fiables para segmentos cortos** (<2 s): VoxLingua107 (6,7 % en dev) y los 64,5/80,3 % de Whisper en Fleurs son 102/82 idiomas, no 3. SimulStreaming (MIT) advierte de que "los segmentos cortos pueden dar problemas de identificación de idioma" y WhisperStreaming detecta el idioma una sola vez en el primer chunk [V]. Medirlo en tus clips (plan 4.6).
- **Validación por escritura:** si el ASR escribe kana -> ja; han sin kana -> zh; latino -> en. Coste cero y corrige los fallos típicos ja/zh.
- **Modelos dedicados:** ECAPA VoxLingua107 (Apache-2.0, CPU, 256-d) como voto independiente barato; SenseVoice-Small si quieres LID+BGM+emoción en una pasada ultrarrápida (ASR para zh/yue/en/ja/ko); Qwen3-ASR (98,7 % Fleurs [A]) si usas su ASR. MMS-LID: 1B y CC-BY-NC, sin ventaja clara.
- **No aislar la voz antes del LID:** Jam-ALT observó idioma equivocado con voz separada [V].

### 3.6 Presupuesto conjunto de VRAM

Ver 2.7. Puntos clave:
- Medí 3,2 GB ocupados **antes** de arrancar nada; si el contenido es un juego, el juego puede usar 4-10 GB y el 100 % de la GPU. Se necesita un **perfil por escenario** y un monitor de VRAM libre (NVML) que degrade el stack (descargar separador, cambiar a TTS ligero, pasar ASR a int8).
- Cada modelo en su propio proceso suma ~0,3-0,5 GB de contexto CUDA [E]; un proceso "GPU worker" único por venv reduce la sobrecarga.
- CPU (Ryzen 7 8700F, 8C/16T) absorbe: Silero VAD, embeddings de hablante, LID ECAPA, DFN/DPDFNet/GTCRN, DNSMOS, Piper/Kokoro/MOSS-Nano y (opcional) SenseVoice int8.
- Compilación: TensorRT-LLM no está soportado en Windows de forma general y vLLM solo en Linux [SV]: para eso, WSL2 (GPU passthrough) o quedarse con PyTorch + CUDA graphs (como faster-qwen3-tts).

---

## 4) Recomendación para InstantTraductor (v1)

### 4.1 Principal

```
WASAPI loopback (48 kHz, estéreo)
   |
   +--> A0 [CPU] mono/mid (opcional) -> 16 kHz -> Silero VAD -> segmentos de voz (+ marca "música dominante")
   |        |
   |        +--> ASR + LID [GPU: Whisper-turbo int8 / Qwen3-ASR / SenseVoice]   <-- sobre la MEZCLA (sin separador por defecto)
   |        |        LID cerrado {en,ja,zh} + histéresis + validación por escritura
   |        |        -> MT -> texto ES -> TTS clonado [GPU] -> mezcla (fuera de alcance aquí)
   |        |
   |        +--> B  [CPU/ONNX] embedding de hablante -> registro de personajes (caché de referencia + prompt del TTS)
   |
   +--> A1 [GPU, baja prioridad, FUERA de la ruta crítica]
            Bandit v2 multilingüe sobre ventanas 6-8 s (solape 50 %) -> stem de diálogo
            -> puntuación de calidad -> actualiza la referencia limpia del personaje (3-10 s, +0,5 s de silencio al final)
            -> (opcional) 2ª pasada de ASR si hay baja confianza / alucinación / música dominante (con mezcla de vuelta 10-30 %)
```

**Decisiones y motivos**
1. **Separador fuera de la ruta crítica del ASR** por la evidencia de 2.2 (artefactos, idioma equivocado) y porque Whisper/Qwen3-ASR/Fun-ASR ya toleran música (los dos últimos según sus autores [A]). El VAD es la defensa principal contra alucinaciones [V].
2. **Bandit v2 multilingüe** como separador de referencia: único con datos en ja/zh/es, ligero (0,1-0,2 s por ventana [E]), licencias compatibles con uso personal. Plan B: HT-Demucs (MIT, trivial de usar).
3. **TTS principal: Qwen3-TTS-0,6B Base + faster-qwen3-tts**: licencia Apache/MIT, 3 s de referencia, caché del prompt, streaming, mejor evidencia de TTFA en GPU de consumo con Windows (413 ms en una 4060, 156 ms en una 4090) y la mayor similitud cross-lingual entre los sistemas de la comparativa zh->es de IndexTTS [A]. Usar `language="Spanish"`; ICL con `ref_text` de la ASR y `x_vector_only` como modo de rescate (cold start, acento).
4. **Registro de personajes DIY** (VAD + embedding + clustering online) en vez de diarización pesada: menos VRAM, portátil a Windows, y la salida que necesitamos es "qué referencia uso".
5. **LID dentro del ASR** con conjunto cerrado y histéresis; ECAPA o SenseVoice solo como votos adicionales.
6. **Proceso aislado por familia de modelos** (venv con `uv`: TTS, ASR, separador) comunicados por IPC; evita los conflictos de pines (chatterbox: `torch==2.6.0`, `transformers==5.2.0`; qwen-tts: `transformers==4.57.3`; VoxCPM Py<3.13; DeepFilterNet ≤cp310) y permite cambiar de TTS sin tocar el resto.

**Parámetros iniciales sugeridos [E]:** referencia por personaje 6-10 s (mínimo 3 s), mono 24 kHz, sin silencios largos, normalizada (~-23 LUFS), sin música (stem de diálogo con SNR estimada >10 dB); ≥2 clips del mismo personaje concatenados; `chunk_size` de streaming 4-8 tokens (compromiso TTFA/prosodia); TTS por cláusulas de 3-10 palabras; control de velocidad 1,0-1,25 (el español suele salir 15-30 % más largo que el inglés [E]); `x_vector_only` si el acento sale mal.

**Criterios de aceptación propuestos:** TTFA p95 ≤0,5 s en la 5070; WER del ASR sobre el audio TTS ≤8 %; similitud de locutor (ECAPA/ReDimNet) ≥ umbral calibrado frente a la referencia; ABX con oyente nativo de España (acento aceptable en ≥80 % de frases); pico de VRAM ≤8 GB.

### 4.2 Alternativas (con cuándo activarlas)

| Alternativa | Activar si... | Motivos | Coste |
|---|---|---|---|
| **A. Chatterbox es-es** como TTS principal | el acento de Qwen3-TTS no suena a España en el bake-off | único finetune explícito es-ES; MIT; `cfg_weight=0` contra fuga de acento | TTFA ~0,5-0,9 s [E]; torch ≥2.7 manual; Py 3.10; sin CUDA graphs |
| **B. CosyVoice3-0,5B** (cross_lingual) | quieres instrucciones de emoción/velocidad y aceptas WSL2/Linux | modo cross-lingual nativo; Apache-2.0; caché `add_zero_shot_spk` | aceleración solo Linux; Py 3.10 |
| **C. (b) TTS castellano + Seed-VC v1** | el acento o la similitud de (a) no convencen, o VRAM muy justa | acento fijo por el TTS base; ~1-2,5 GB | pierde emoción; GPL-3.0; proyecto archivado |
| **D. IndexTTS-2.5** ("modo calidad" en series sin juego) | quieres emoción del clip original + timbre limpio | desacople emoción/locutor, `duration_factor` | ~6 GB, TTFA >1 s, sin streaming |
| **E. XTTS-v2** | todo lo demás falla o necesitas algo estable hoy | Python 3.13, ruedas Windows, bajo VRAM | calidad inferior, licencia NC |
| **F. MOSS-TTS-Nano / Kokoro / Piper en CPU** | perfil "juego" con VRAM mínima | 0 GB de VRAM | calidad y clonación limitadas |

**Extensiones v2:** modo doblaje (atenuar solo el stem de diálogo original con el mismo Bandit, dejando música/efectos), LoRA por personaje principal (VoxCPM2/Qwen3-TTS tienen fine-tuning oficial; 5-10 min de audio [V]), segunda etapa de pulido con VC.

### 4.3 Accent / es-ES: qué hacer si no suena a España
1. Probar `x_vector_only` (Qwen3) / `cfg_weight=0` (Chatterbox) / `cross_lingual` (CosyVoice).
2. Cambiar a Chatterbox es-es o a la ruta (b) con TTS base castellano.
3. Ajustar el MT a castellano peninsular (vosotros, vocabulario) - tarea del MT.
4. Último recurso: fine-tuning con datos peninsulares (Common Voice es, MLS, Voxpopuli) sobre Qwen3-TTS-0,6B (scripts oficiales) o accent conversion con VC (riesgo de artefactos).

### 4.4 Interfaz sugerida de la etapa
`SpeakerRegistry.assign(segment_audio, ts) -> speaker_id`; `ReferenceBuilder.submit(speaker_id, audio_mix, ts)` (asíncrono, usa Bandit v2) ; `Cloner.synthesize(speaker_id, text_es, lang="es", speed, stream=True) -> iterator[pcm24k]`; `Cloner` debe ser intercambiable (Qwen3 / Chatterbox / CosyVoice / XTTS / VC) detrás de la misma interfaz.

### 4.5 Latencia de esta etapa (objetivo del proyecto: 1,5-3 s totales)
Ruta crítica propia: embedding 15-50 ms [V], asignación <5 ms, TTFA del TTS 0,2-0,5 s [E]; el separador no suma (fuera de ruta) salvo arranque en frío (+0,1-0,3 s [E]). Queda ≥1,5 s para VAD + ASR + MT [E].

### 4.6 Plan de validación (1-2 días, antes de fijar el stack)
0. **Hito 0 (go/no-go de latencia, 2-3 horas):** en un venv `uv` con PyTorch cu128/cu130, ejecutar faster-qwen3-tts (0,6B) en la 5070 con Windows nativo y, si no captura CUDA graphs o el TTFA >0,6 s, repetir en WSL2. Medir TTFA con `chunk_size` 1/4/8, RTF y VRAM pico con el prompt ya cacheado. Si ninguna ruta baja de ~0,6 s, pasar a la alternativa A (Chatterbox es-es) o C (TTS ligero + VC).
1. **Dataset:** ~50 clips de 3-10 s de tu contenido real (series y películas en en/ja/zh, juegos) con subtítulos de referencia y tres condiciones: mezcla, mezcla+mid, dialogue-stem (Bandit v2) y mezcla de vuelta 20 %.
2. **ASR/LID:** WER/CER, nº de alucinaciones, acierto de LID por duración (0,5/1/2/3/5 s) y SNR (0/5/10 dB) con Whisper-turbo vs Qwen3-ASR vs SenseVoice; umbrales de histéresis.
3. **Bake-off de TTS** (Qwen3-0,6B ICL y x-vector, Qwen3-1,7B, Chatterbox es-es, CosyVoice3 cross-lingual, XTTS-v2; opcionales OmniVoice e IndexTTS-2.5) con referencias crudas vs aisladas: WER de Whisper-large-v3 sobre el audio generado, similitud de locutor (ECAPA/ReDimNet), TTFA/RTF/VRAM pico **medidos en la 5070**, y ABX por oyente nativo (acento España).
4. **Registro de personajes:** pureza de clusters en 3 episodios; tasa de fusiones/divisiones.
5. **Contención:** medir latencia del stack mientras corre un juego típico.

---

## 5) Riesgos y preguntas abiertas

**Riesgos**
1. **Acento es-ES sin verificar** en todos los modelos salvo Chatterbox es-es (que tampoco publica benchmark). Fuga de acento cross-lingual documentada (OmniVoice) o mitigable (Chatterbox/Qwen/CosyVoice).
2. **Cifras de latencia de servidor:** 97 ms (Qwen3), 150 ms (CosyVoice3), 100 ms (Fish), 70 ms (Voxtral) son de H20/H100/H200/L20; en GPU de consumo el mismo Qwen3-TTS pasa a 156 ms (4090) y 413 ms (4060) [V]; CosyVoice3 en TRT-LLM L20 dio ~750 ms con 4 concurrentes [V]. Sin CUDA graphs, Qwen3-TTS en una RTX 4060 (Windows) tardó 2 697 ms en el primer audio y un usuario con RTX 5090 en Windows nativo midió 3-5 s por frase (issue #92 de faster-qwen3-tts, mar-2026) [V]: **el TTFA depende críticamente de que la optimización funcione en tu combinación Windows + sm_120**. Hay que medir en la 5070 (hito 0).
2b. **Prosodia entre cláusulas:** sintetizar por trozos pequeños puede dar saltos de tono/estilo entre chunks (issue #96, Qwen3-TTS 1,7B) [V]; mitigar con cláusulas de ≥5-8 palabras, crossfade de 20 ms (práctica del server de Chatterbox [V]), fijar la misma referencia/semilla y, si es posible, acondicionar con el audio del trozo anterior [E].
3. **Referencias contaminadas:** música/efectos en el prompt producen artefactos y eco de cola (issue #341 de Qwen3-TTS); la separación también introduce artefactos; hay que medir si el realce posterior baja la similitud.
4. **Separadores y ja/zh:** los entrenados en inglés/canto fallan (2,2 dB en mandarín); Bandit v2 es investigación, repo unificado "banda" con licencia AGPL/no comercial [V].
5. **Empaquetado Windows + Blackwell + Python 3.13:** pines incompatibles (chatterbox `torch==2.6.0` sin sm_120; `transformers` 5.2.0 vs 4.57.3), VoxCPM <3.13, DeepFilterNet ≤cp310, NeMo solo Linux, vLLM/TRT-LLM solo Linux, `faster-whisper` con ctranslate2 (ruedas cp313 sin verificar). Mitigación: un venv y proceso por modelo con `uv`, PyTorch ≥2.7 cu128/cu130 (PyPI ofrece 2.14.x con Py 3.13), comprobar `sm_120` en `torch.cuda.get_arch_list()`, WSL2 opcional.
6. **Contención de GPU/VRAM con juegos y navegador:** 3,2 GB ya ocupados hoy; un juego puede agotar la VRAM o subir la latencia de kernels.
7. **Diarización en cine/TV/ja/zh:** Sortformer "degrada en no-inglés y ruido"; diart sin mantenimiento; los solapes arruinan referencias.
8. **Licencias:** varios pesos son no comerciales (OmniVoice CC-BY-NC, XTTS CPML, F5 CC-BY-NC, Voxtral CC BY-NC, Fish/Higgs investigación, Vevo CC-BY-NC); Bandit v2 CC BY-SA; IndexTTS prohíbe usar el modelo para mejorar otros modelos de IA salvo no comerciales; Seed-VC GPL-3.0 (solo afecta a distribución). Todo válido para **uso personal**; no redistribuir audio ni modelos modificados sin revisar. Varios repos prohíben suplantación/fraude (OmniVoice, VoxCPM2) y Chatterbox incrusta watermark PerTh: clonar a personajes para consumo privado parece compatible, pero conviene leer las cláusulas de uso aceptable antes de publicar nada [SV, no es asesoría legal].
9. **Métricas poco comparables:** WER/SIM de tablas de distintos autores; los verificadores de locutor tienen sesgo de idioma (TidyVoice 2026) [V].
10. **Ritmo del ecosistema:** en 2026 aparecen modelos cada mes (Qwen3-TTS en ene, IndexTTS-2.5 en ago...) y algunos se retiran (VibeVoice-TTS deshabilitado, Magpie sin zero-shot, Seed-VC archivado): mantener una interfaz intercambiable.
11. **No cubierto por agotamiento de WebSearch:** alternativas no descubiertas de finales de 2026 fuera de las organizaciones que sí consulté (Qwen, FunAudioLLM, OpenBMB, k2-fsa, IndexTeam, ResembleAI, Fish, Mistral, NVIDIA, Kyutai, Microsoft); soporte real de sm_120 en faster-qwen3-tts/CosyVoice/ctranslate2-cp313; estudios ASR+separación específicos de cine/juegos; estudios de LID por duración de segmento.

**Preguntas abiertas**
- ¿Qué TTS da el mejor castellano de España con referencias en inglés/japonés/chino? (bake-off 4.6)
- ¿Mejora o empeora la separación el ASR/LID en *tu* contenido? ¿A partir de qué SNR compensa?
- ¿Qué TTFA/RTF reales da Qwen3-TTS (CUDA graphs) en la 5070 con Windows y PyTorch cu128/cu130?
- ¿`x_vector_only` reduce la fuga de acento sin perder demasiado parecido?
- ¿Es estable el registro de personajes con segmentos de 1-3 s y música? ¿Qué umbral de coseno usar con el embedding elegido?
- ¿Se prefiere el modo doblaje (atenuar el diálogo original con el stem)? Condiciona la elección del separador.
- ¿Cuánta VRAM deja libre un juego típico del usuario? Define el perfil por defecto.

---

## 6) Fuentes (URL)

**Separación / realce**
- Demucs: https://github.com/adefossez/demucs · https://pypi.org/pypi/demucs/json · https://arxiv.org/abs/2211.08553
- Music-Source-Separation-Training: https://github.com/ZFTurbo/Music-Source-Separation-Training · https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/main/docs/pretrained_models.md · https://github.com/ZFTurbo/Music-Source-Separation-Training/releases
- audio-separator: https://github.com/nomadkaraoke/python-audio-separator · https://pypi.org/pypi/audio-separator/json
- BS-RoFormer / Mel-RoFormer: https://arxiv.org/html/2309.02612 · https://arxiv.org/html/2310.01809 · https://github.com/KimberleyJensen/Mel-Band-Roformer-Vocal-Model
- SCNet: https://github.com/starrytong/SCNet · https://arxiv.org/html/2401.13276
- Bandit / DnR: https://github.com/kwatcharasupat/bandit · https://github.com/kwatcharasupat/bandit-v2 · https://zenodo.org/records/12701995 · https://arxiv.org/html/2407.07275 · https://arxiv.org/html/2110.09958 · https://github.com/kwatcharasupat/source-separation-landing · https://github.com/kwatcharasupat/banda
- SAM Audio: https://github.com/facebookresearch/sam-audio · https://huggingface.co/facebook/sam-audio-small · https://ai.meta.com/blog/sam-audio/ · https://arxiv.org/abs/2512.18099
- demucs.cpp: https://github.com/sevagh/demucs.cpp
- DeepFilterNet: https://github.com/Rikorose/DeepFilterNet · https://arxiv.org/html/2305.08227 · https://pypi.org/pypi/deepfilternet/json · https://pypi.org/pypi/deepfilterlib/json
- DPDFNet / GTCRN: https://github.com/ceva-ip/DPDFNet · https://github.com/Xiaobin-Rong/gtcrn
- ClearerVoice-Studio: https://github.com/modelscope/ClearerVoice-Studio · https://huggingface.co/alibabasglab/MossFormer2_SE_48K
- Resemble Enhance: https://github.com/resemble-ai/resemble-enhance
- NVIDIA: https://docs.nvidia.com/deeplearning/maxine/audio-effects-sdk/index.html · https://www.nvidia.com/en-us/geforce/broadcasting/broadcast-app/
- sherpa-onnx: https://github.com/k2-fsa/sherpa-onnx · https://k2-fsa.github.io/sherpa/onnx/source-separation/index.html · https://pypi.org/pypi/sherpa-onnx/json

**Evidencia ASR**
- Whisper: https://arxiv.org/abs/2212.04356 · https://ar5iv.labs.arxiv.org/html/2212.04356
- Whisper-AT: https://arxiv.org/abs/2307.03183 · https://ar5iv.labs.arxiv.org/html/2307.03183
- Alucinaciones por no-voz: https://arxiv.org/abs/2501.11378 · https://arxiv.org/html/2501.11378
- Artefactos de realce: https://arxiv.org/abs/2201.06685
- Jam-ALT: https://arxiv.org/html/2311.13987 · LyricWhiz: https://arxiv.org/html/2306.17103
- stable-ts: https://github.com/jianfch/stable-ts · Faster-Whisper-XXL: https://github.com/Purfview/whisper-standalone-win · WhisperX: https://github.com/m-bain/whisperX
- Qwen3-ASR: https://github.com/QwenLM/Qwen3-ASR · https://huggingface.co/Qwen/Qwen3-ASR-1.7B · https://arxiv.org/abs/2601.21337
- Fun-ASR: https://github.com/FunAudioLLM/Fun-ASR · SenseVoice: https://github.com/FunAudioLLM/SenseVoice · https://arxiv.org/html/2407.04051
- faster-whisper: https://github.com/SYSTRAN/faster-whisper · https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/transcribe.py · https://pypi.org/pypi/faster-whisper/json · https://huggingface.co/openai/whisper-large-v3-turbo

**TTS con clonación**
- Qwen3-TTS: https://github.com/QwenLM/Qwen3-TTS · https://raw.githubusercontent.com/QwenLM/Qwen3-TTS/main/README.md · https://arxiv.org/html/2601.15621 · https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base · https://pypi.org/pypi/qwen-tts/json · https://github.com/QwenLM/Qwen3-TTS/issues · https://github.com/QwenLM/Qwen3-TTS/discussions/358
- faster-qwen3-tts: https://github.com/andimarafioti/faster-qwen3-tts · https://raw.githubusercontent.com/andimarafioti/faster-qwen3-tts/main/README.md · https://github.com/andimarafioti/faster-qwen3-tts/issues · https://github.com/andimarafioti/faster-qwen3-tts/issues/92 · https://github.com/andimarafioti/faster-qwen3-tts/issues/96 · https://github.com/andimarafioti/faster-qwen3-tts/commits/main · https://github.com/nari-labs/nari-qwen3-tts · https://github.com/QwenLM/Qwen3-TTS/issues?q=is%3Aissue+spanish
- CosyVoice: https://github.com/FunAudioLLM/CosyVoice · https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/README.md · https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/cosyvoice/cli/cosyvoice.py · https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/runtime/triton_trtllm/README.Cosyvoice3.md · https://github.com/FunAudioLLM/CosyVoice/issues · https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512 · https://arxiv.org/html/2505.17589
- Chatterbox: https://github.com/resemble-ai/chatterbox · https://huggingface.co/ResembleAI/chatterbox · https://huggingface.co/ResembleAI/Chatterbox-Multilingual-es-es · https://huggingface.co/ResembleAI/Chatterbox-Multilingual-es-es/tree/main · https://huggingface.co/ResembleAI · https://pypi.org/pypi/chatterbox-tts/json · https://github.com/devnen/Chatterbox-TTS-Server · https://github.com/davidbrowne17/chatterbox-streaming · https://github.com/randombk/chatterbox-vllm · https://github.com/resemble-ai/chatterbox/issues · https://github.com/resemble-ai/chatterbox/issues/551 · https://github.com/resemble-ai/chatterbox/issues/552
- OmniVoice: https://github.com/k2-fsa/OmniVoice · https://huggingface.co/k2-fsa/OmniVoice · https://arxiv.org/html/2604.00688
- VoxCPM2: https://github.com/OpenBMB/VoxCPM · https://huggingface.co/openbmb/VoxCPM2 · https://pypi.org/pypi/voxcpm/json · https://arxiv.org/pdf/2606.06928
- IndexTTS: https://github.com/index-tts/index-tts · https://github.com/index-tts/index-tts/blob/main/LICENSE · https://huggingface.co/IndexTeam/IndexTTS-2.5 · https://arxiv.org/html/2601.03888 · https://index-tts.github.io/index-tts2-5.github.io/
- XTTS-v2: https://huggingface.co/coqui/XTTS-v2 · https://github.com/idiap/coqui-ai-TTS · https://pypi.org/pypi/coqui-tts/json · https://raw.githubusercontent.com/idiap/coqui-ai-TTS/dev/TTS/tts/models/xtts.py
- F5-TTS: https://github.com/SWivid/F5-TTS · https://huggingface.co/jpgallegoar/F5-Spanish · https://github.com/jpgallegoar/Spanish-F5
- MOSS-TTS: https://github.com/OpenMOSS/MOSS-TTS · https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano · https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5
- Fish Audio: https://github.com/fishaudio/fish-speech · https://raw.githubusercontent.com/fishaudio/fish-speech/main/README.md · https://speech.fish.audio/ · https://huggingface.co/fishaudio/s2-pro · https://huggingface.co/fishaudio/s1-mini · https://huggingface.co/fishaudio/fish-speech-1.5 · Higgs: https://github.com/boson-ai/higgs-audio · Voxtral TTS: https://huggingface.co/mistralai/Voxtral-4B-TTS-2603
- Qwen-Audio-3.0-TTS (solo API): https://arxiv.org/pdf/2607.23938 · https://llmlearner.com/models/qwen-audio-3-0-tts-plus
- Descartados: https://github.com/SparkAudio/Spark-TTS · https://huggingface.co/amphion/MaskGCT · https://huggingface.co/nvidia/magpie_tts_multilingual_357m · https://github.com/microsoft/VibeVoice · https://huggingface.co/kyutai/tts-1.6b-en_fr · https://github.com/kyutai-labs/hibiki-zero · https://github.com/kyutai-labs/hibiki
- TTS base castellano: https://huggingface.co/hexgrad/Kokoro-82M · https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md · https://github.com/OHF-Voice/piper1-gpl · https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_ES · https://github.com/myshell-ai/MeloTTS · https://huggingface.co/myshell-ai/MeloTTS-Spanish
- Wrappers: https://github.com/rsxdalv/TTS-WebUI
- Orgs HF consultadas: https://huggingface.co/Qwen · https://huggingface.co/IndexTeam · https://huggingface.co/k2-fsa · https://huggingface.co/openbmb · https://huggingface.co/myshell-ai · https://huggingface.co/fishaudio · https://huggingface.co/FunAudioLLM · https://huggingface.co/mistralai

**Conversión de voz**
- Seed-VC: https://github.com/Plachtaa/seed-vc · https://github.com/Plachtaa/seed-vc/blob/main/EVAL.md · https://arxiv.org/html/2411.09943
- OpenVoice: https://github.com/myshell-ai/OpenVoice · https://github.com/myshell-ai/OpenVoice/blob/main/docs/QA.md · https://arxiv.org/html/2312.01479
- kNN-VC: https://github.com/bshall/knn-vc · RVC: https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI
- Vevo: https://github.com/open-mmlab/Amphion/tree/main/models/vc/vevo · https://huggingface.co/amphion/Vevo · https://github.com/open-mmlab/Amphion/blob/main/LICENSE
- MeanVC: https://github.com/ASLP-lab/MeanVC · https://arxiv.org/abs/2510.08392

**Hablantes y LID**
- pyannote: https://huggingface.co/pyannote/speaker-diarization-community-1 · https://huggingface.co/pyannote/segmentation-3.0 · https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM · https://pypi.org/pypi/pyannote.audio/json
- diart: https://github.com/juanmc2005/diart · https://raw.githubusercontent.com/juanmc2005/diart/main/README.md · https://pypi.org/pypi/diart/json · https://github.com/juanmc2005/diart/commits/main
- Sortformer: https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2 · https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1 · https://arxiv.org/abs/2507.18446 · NeMo: https://github.com/NVIDIA-NeMo/NeMo
- WhisperLiveKit: https://github.com/QuentinFuxa/WhisperLiveKit · SimulStreaming: https://github.com/ufal/SimulStreaming · WhisperStreaming: https://github.com/ufal/whisper_streaming
- Embeddings: https://github.com/modelscope/3D-Speaker · https://github.com/IDRnD/ReDimNet · sesgo de idioma: https://arxiv.org/abs/2603.08092
- LID: https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa · https://arxiv.org/abs/2011.12998 · https://huggingface.co/facebook/mms-lid-126
- VAD / calidad: https://github.com/snakers4/silero-vad · https://github.com/microsoft/DNS-Challenge/tree/master/DNSMOS

**Entorno**
- https://pypi.org/pypi/torch/json · https://pypi.org/pypi/onnxruntime-gpu/json · https://pypi.org/pypi/ctranslate2/json · https://github.com/OpenNMT/CTranslate2/releases
- Medición local: `nvidia-smi` (driver 616.64, 12 227 MiB, 3 197 MiB en uso, cc 12.0), Python 3.13.15, uv 0.12.21.
