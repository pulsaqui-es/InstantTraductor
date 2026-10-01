# ADR-0008: Síntesis de voz (TTS), clonación y aislamiento de voz

- Estado: Aceptada (aprobada por el humano el 2026-09-30)
- Fecha: 2026-09-30
- Decide: orquestador (con visto bueno del humano); **la elección final del motor la hace el humano escuchando**

## Contexto
- La voz en español debe sonar a **español de España**, dar el primer audio en ≤0,5–0,6 s y, desde la spec 003, **parecerse a la del hablante original** aunque hable en inglés, japonés o chino.
- El contenido (series, películas y juegos) trae música y efectos que ensucian las referencias de voz.
- No hay benchmarks públicos de acento es-ES para ningún modelo abierto.
- En Windows con Blackwell la latencia depende de optimizaciones (CUDA graphs) que no están comprobadas en sm_120.
- Hay unos 8 GB de VRAM útiles: Windows y las apps ocupan ~3,2 GB.

## Decisión
1. **Candidatos principales (se elige midiendo):**
   - **Qwen3-TTS-0.6B Base + faster-qwen3-tts** (Apache 2.0 + MIT):
     - clonación con 3 s de referencia, *streaming* y caché del *prompt*;
     - primer audio de 156 ms en una 4090 y 413 ms en una 4060 con Windows;
     - riesgo: sin CUDA graphs en Windows/sm_120 se han medido 3–5 s por frase.
   - **Chatterbox Multilingual es-es** (MIT):
     - el único modelo afinado para castellano, con clonación;
     - primer audio estimado en 0,5–0,9 s;
     - fija `torch==2.6.0`, que no soporta sm_120, así que hay que instalar torch ≥ 2.7 a mano.
2. **Prueba de arranque ("hito 0") al principio de la spec 001:**
   - se miden ambos en la 5070 (primer audio p95, RTF, VRAM pico);
   - el humano escucha unas frases de cada uno (¿suena a España?);
   - gana el que cumpla primer audio p95 ≤ 0,6 s con un acento aceptable;
   - si ninguno lo cumple, XTTS-v2 (no comercial, válido para uso personal) o, en último término, Piper es_ES en CPU para la spec 001, y se revisa en la 003.
3. **Spec 001: voz fija** en castellano (una referencia elegida por el humano). La interfaz del motor ya admite una referencia de voz, para que la clonación de la 003 no cambie el contrato.
4. **Spec 003: clonación por hablante:**
   - **Registro de personajes propio:** VAD + *embedding* de hablante (ONNX, CPU) + agrupación en línea + caché de referencia y *prompt* por personaje. La diarización pesada se descarta: Sortformer es solo para Linux y diart está sin mantenimiento.
   - **Referencias limpias fuera de la ruta crítica:**
     - Bandit v2 multilingüe separa el diálogo de la música y los efectos en ventanas de 6–8 s, en segundo plano. Único con datos en ja/zh/es; licencia CC BY-SA, válida para uso personal.
     - Plan B: HT-Demucs (MIT).
     - Referencias de 6–10 s, mono a 24 kHz, normalizadas.
   - Si el acento se desvía, `x_vector_only` (Qwen3) o `cfg_weight=0` (Chatterbox). Si no basta, TTS castellano + conversión de voz.
5. **La separación NO va en la ruta crítica del ASR:** la evidencia indica que empeora el WER y el idioma detectado. El VAD es la defensa principal contra alucinaciones.
6. **Detección de idioma (spec 004):** conjunto cerrado {en, ja, zh} dentro del ASR (Whisper), con histéresis y validación por sistema de escritura.
7. **Control de ritmo:** velocidad nativa del TTS hasta 1,25× y *crossfade* de 20 ms entre cláusulas (de al menos 5–8 palabras, para evitar saltos de prosodia).

## Alternativas consideradas
- **CosyVoice3:** modo *cross-lingual* nativo, pero su aceleración solo funciona en Linux.
- **IndexTTS-2.5:** separa emoción y timbre, pero ~6 GB, >1 s de primer audio y sin *streaming*.
- **TTS castellano + Seed-VC:** acento fijo y poca VRAM, pero pierde emoción, es GPL-3.0 y está archivado.
- **No caben en la VRAM:** Fish S2 Pro, Higgs v3, Voxtral TTS y VoxCPM2.
- **Solo CPU (Kokoro, Piper, MOSS-TTS-Nano):** reservados para un posible perfil de juego con la GPU ocupada.

## Consecuencias
- El humano participa en la elección escuchando: no hay benchmarks públicos de acento es-ES.
- Cada TTS va en su propio proceso y `.venv` (ADR-0004), porque sus versiones de torch y transformers son incompatibles entre sí.
- Riesgos:
  - fuga de acento en la clonación entre idiomas;
  - referencias contaminadas por la música;
  - saltos de prosodia entre cláusulas;
  - latencia real en sm_120 sin comprobar.
- Licencias anotadas: Qwen3-TTS Apache 2.0, faster-qwen3-tts MIT, Chatterbox MIT (añade una marca de agua PerTh), Bandit v2 CC BY-SA, HT-Demucs MIT y XTTS-v2 CPML (no comercial). El audio clonado es solo para consumo privado: no se distribuye.

## Resolución del hito 0 (2026-10-01)
Spike S1 (`spikes/voz/README.md`), medido en la RTX 5070 con Windows nativo.

**Qwen3-TTS-0.6B Base + faster-qwen3-tts 0.5.3:**
- Las CUDA graphs funcionan en sm_120.
- Primer audio p95 de 182 ms con `chunk_size` 4 (de 122 a 270 ms según el *chunk*).
- RTF de 0,37.
- VRAM de 3,3 GB.

**Chatterbox es-ES:**
- Primer audio p95 de 748 ms.
- RTF en *streaming* de 1,12: no aguanta el tiempo real sin optimizarlo.

**Ninguno tiene parámetro de velocidad**, así que se acelera con *time-stretch* del PCM: factor exacto, 3–4 ms de CPU por segundo de audio.

**Decisión del humano tras escuchar las muestras:**
- motor **Qwen3-TTS-0.6B** (modo ICL con `ref_text`; `x_vector_only` de rescate);
- **voz por defecto femenina** y castellana;
- la referencia masculina de LibriVox («Trafalgar», lector Tux, dominio público) suena a España y queda como una de las voces;
- se buscarán al menos dos referencias femeninas castellanas de dominio público.

**Riesgo abierto:** la contención con la traducción en la misma GPU. Con carga ajena al 100 %, el p95 del primer audio sube a ~2 s.

## Catálogo de voces de la v1 (2026-10-01, decisión del humano)
- **Primera vuelta:** las referencias de LibriVox se rechazaron de oído («voz terrible»). Las grabaciones de aficionados suenan planas.
- **Segunda vuelta** (`spikes/voces/README.md`):
  - el diseño de voz de **Qwen3-TTS-1.7B-VoiceDesign** sesea siempre, así que no sirve para el castellano;
  - **VoxCPM2** (Apache-2.0) con la descripción **en español** sí da acento peninsular;
  - grabaciones **VoxPopuli** (CC0) de calidad de estudio.
- **El humano acepta las 4 finalistas y elige Lucía por defecto.** Catálogo:

  | Voz | Origen | Licencia |
  |---|---|---|
  | **Lucía** `es-f-dvx-01` (por defecto) | diseñada con VoxCPM2, sin persona real detrás | Apache-2.0 |
  | Clara `es-f-dvx-08` | diseñada con VoxCPM2, sin persona real detrás | Apache-2.0 |
  | Voz humana 1 y 2 `es-f-est-04/01` | VoxPopuli, Parlamento Europeo | CC0, «© Unión Europea, Parlamento Europeo» |
  | Tux `es-m-tux` | LibriVox | dominio público |

- **Las voces van empaquetadas en la app** (`src/instanttraductor/setup/voices/`): no se descargan.
- **VoxCPM2 es solo una herramienta de autoría** para crear voces nuevas. No forma parte de la app en ejecución: su `transformers` choca con el del servicio de voz.
- **Línea futura** (propuesta del humano): un catálogo con voces de distintas edades, femeninas y masculinas, diseñadas igual. Va a la spec 003 (hoja de ruta).

## Referencias
- `docs/investigacion/2026-09-30-aislamiento-y-clonacion.md`
- `spikes/voz/README.md` (S1, 2026-10-01)
- `spikes/voces/README.md` (voces nuevas, 2026-10-01)
- `docs/investigacion/2026-09-30-traduccion-y-voz.md`
