# ADR-0006: Reconocimiento de voz (ASR) y segmentación

- Estado: Aceptada (aprobada por el humano el 2026-09-30)
- Fecha: 2026-09-30
- Decide: orquestador (con visto bueno del humano)

## Contexto
El ASR debe dar texto con la menor latencia posible y con puntuación para cortar en frases, soportar contenido con música y efectos (películas y juegos), funcionar en Windows con Blackwell y dejar VRAM para la traducción y la voz.

## Decisión
- **VAD:** Silero VAD 6.2.x (ONNX, CPU, MIT) como puerta y detector de fin de turno. El segmentador va fuera del motor ASR.
- **ASR principal (inglés):** **NVIDIA Nemotron Speech Streaming EN 0.6B** sobre **sherpa-onnx ≥ 1.13.8**, en **CPU int8**.
  - Streaming nativo, con trozos de 160–560 ms.
  - Puntuación propia.
  - WER de ~7–8 %.
  - No gasta VRAM.
- **ASR alternativo y de referencia:** **faster-whisper 1.2.1 + CTranslate2 4.8.x** con `large-v3-turbo` en FP16 (GPU), por segmentos de VAD con corte forzado a los 4–6 s y filtros contra alucinaciones. En Blackwell se usa FP16 porque INT8 dio problemas.
- **Elección final midiendo:** corpus propio (películas, juegos, YouTube, pódcast) con WER, latencia (p50/p95), estabilidad de parciales y frases inventadas en tramos de solo música.
- **Contrato de eventos ASR:**
  - tipos `speech_start`, `partial`, `final`, `endpoint` y `error`;
  - `segment_id` + `revision` y `stable_len` (caracteres que ya no cambiarán);
  - tiempos en el reloj de audio, idioma y capacidades declaradas por motor.
- **Separación de voz y música para el ASR:** no por defecto. Hay evidencia de 2025-2026 de que el realce de voz empeora el WER. Se revisará con datos (y en ADR-0008, para la clonación).
- **Japonés y chino** (spec 004): faster-whisper `large-v3-turbo`/`large-v3` con el idioma detectado. Se evaluarán Qwen3-ASR, SenseVoice y kotoba-whisper con el mismo arnés.

## Alternativas consideradas
- **Whisper en streaming (LocalAgreement / SimulStreaming):** entre 1,5 y 3,3 s de latencia; se come el presupuesto.
- **Parakeet TDT:** excelente, pero por segmentos. Encaja mejor en subtítulos.
- **Moonshine v2 medium:** alternativa en CPU para jugar con la GPU ocupada.
- **Voxtral Realtime:** necesita más de 16 GB de VRAM.
- **Qwen3-ASR en streaming:** requiere vLLM en WSL2.
- **NeMo nativo:** no funciona en Windows.

## Consecuencias
- El ASR en CPU deja libre la GPU para la traducción y la voz.
- Sin datos públicos de Nemotron con música de fondo: la spec 002 lo medirá y, si pierde, pasa al alternativo.
- Licencias: Silero MIT, faster-whisper MIT, Whisper MIT y Nemotron con licencia abierta de NVIDIA (condiciones propias, anotadas).

## Resolución con el spike S3 (2026-10-01)
La decisión se mantiene. Medido en este PC (`spikes/asr/README.md`):

**Nemotron 560 ms, en CPU** (int8, 2 hilos, `blank_penalty` 1):
- texto final p50/p95 de 0,67/0,78 s desde el fin del habla;
- WER del 5,05 %;
- RTF de 0,15, 0,4 núcleos de CPU y 0 de VRAM;
- los parciales solo añaden texto (0 retractaciones).

**faster-whisper turbo FP16:**
- funciona en sm_120;
- texto final de 0,71/0,82 s y WER del 5,82 % con cortes a 5 s;
- 2,3 GB de VRAM y sin parciales.

**Matices para la implementación:**
- Nemotron casi nunca pone punto final, así que la segmentación va por las pausas del VAD y las comas (research.md R6 de la spec 001).
- El *endpoint* nativo de sherpa se descarta (WER del 11 %). Se usa VAD + vaciado + un stream nuevo por tramo.
- En el `pyproject` hay que declarar `sherpa-onnx-core`.
- El paquete `silero-vad` arrastra torch, así que se usa su `.onnx` directamente con onnxruntime.

## Referencias
- `docs/investigacion/2026-09-30-asr.md`
- `spikes/asr/README.md` (S3, 2026-10-01)
