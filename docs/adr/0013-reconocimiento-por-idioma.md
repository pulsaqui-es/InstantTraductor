# ADR-0013: Reconocimiento de voz por idioma elegido (en, ja, zh, ko)

- Estado: Propuesta
- Fecha: 2026-10-02
- Decide: humano, a propuesta del orquestador tras el spike S5

## Contexto
La persona usuaria decidió elegir a mano el idioma de origen (inglés, japonés, chino y coreano) en lugar de detectarlo: menos consumo, menos espera y menos errores. ADR-0006 preveía faster-whisper en GPU para ja/zh con detección de idioma, pero la GPU está casi llena (traducción 5,2 GB y voz 3,8 GB).

El spike S5 (`spikes/idiomas/README.md`, FLEURS, 50 frases por idioma, sherpa-onnx 1.13.8 en CPU) midió:

| Idioma | Modelo | CER sin / con música | Final p50/p95 | CPU | RAM |
|---|---|---|---|---|---|
| zh | X-ASR-zh-en (streaming, 960 ms) | 4,87 / 5,15 % | 0,58 / 0,61 s | 0,13 núcleos | 294 MB |
| ja | SenseVoice-Small (por segmento de VAD) | 8,32 % | 0,88 / 1,39 s | 0,07 | 163 MB* |
| ja | Parakeet-tdt_ctc-0.6b-ja (alternativa) | 5,31 / 6,17 % | 1,24 / 2,02 s (3,35 s con la CPU cargada) | 0,12 | 753 MB |
| ko | SenseVoice-Small | 7,14 / 8,09 % | 0,91 / 1,23 s | 0,07 | 163 MB* |

\* El mismo modelo SenseVoice sirve para ja y ko.

- **Traducción:** Hy-MT2-7B traduce ja/zh/ko → es con el prompt actual en 0,41-0,46 s de p50. Hay que adaptar al chino, japonés y coreano el filtro de longitud y el tope de tokens.
- **Música sin diálogo:** el VAD Silero no abre ningún segmento.

## Decisión
1. **Un reconocedor por idioma**, todos en CPU con sherpa-onnx:
   - en: Nemotron Streaming (sin cambios);
   - zh: X-ASR-zh-en en streaming;
   - ja y ko: SenseVoice-Small por segmento de VAD.
   - Solo se carga el del idioma elegido.
2. **Parakeet-ja** queda como alternativa de mayor precisión para el japonés, a revisar con el juicio humano de SC-002. Si SenseVoice no llega al 85 %, se cambia a Parakeet, aunque su latencia es mayor.
3. **El contrato `AsrEngine` no cambia.** Un motor por segmento entrega solo el FINAL (sin parciales), lo que el contrato ya admite (`capabilities.partials=False`).
4. **El traductor** recibe el idioma de origen; el filtro de longitud y `max_tokens` se calculan por idioma (en CJK, por caracteres).
5. **`preparar`** descarga los cuatro idiomas: unos 460 MB más, más el filtro de idioma (ADR-0012; tamaño a confirmar en el plan).

## Alternativas consideradas
- **Whisper large-v3-turbo en GPU:** 2,3 GB de VRAM que no hay.
- **Nemotron 3.5 multilingüe para todo:** CER del 12,6-13,4 % en japonés y del 19,5 % en chino.
- **SenseVoice para los tres:** en chino es peor y más lento que X-ASR (5,55 % y 0,87/1,31 s).
- **Detección automática:** queda como opción para la 004.

## Consecuencias
- Sustituye en parte a ADR-0006: la línea de ja/zh con faster-whisper y detección de idioma.
- Sin VRAM extra y con poca CPU.
- ja y ko no tienen parciales: el texto llega al cerrar el segmento. Cabe en el presupuesto de ≤ 3 s de p50, pero hay que validarlo con contenido real (SC-001).
- **Riesgos:**
  - el corpus FLEURS es habla leída y limpia: el cine será peor;
  - el coreano de Nemotron y kangkyu no escribe espacios (por eso se elige SenseVoice);
  - las licencias de los modelos nuevos se revisan en el plan.
