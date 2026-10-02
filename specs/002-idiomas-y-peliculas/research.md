# Research: Idiomas elegidos a mano y robustez en películas

**Fuentes:**
- investigaciones: `docs/investigacion/2026-10-02-asr-ja-zh-ko.md`, `-captura-por-app.md` y `-habla-baja-y-vosotros.md`;
- spikes medidos en el PC de la persona usuaria: S5 `spikes/idiomas/README.md`, S6 `spikes/captura_app/README.md` y S7 `spikes/habla_baja/README.md`;
- ADR-0012 y ADR-0013.

## R1. Idioma de origen elegido a mano
- **Decision:** cuatro idiomas (`en`, `ja`, `zh` y `ko`) elegidos en los ajustes o por sesión. No se detecta el idioma.
- **Rationale:** decisión del humano. Supone menos consumo y menos espera, porque solo se carga el reconocedor del idioma elegido.
- **Alternatives considered:** la detección automática con un ASR multilingüe (Whisper en GPU), descartada porque no hay VRAM y añade espera. Queda como opción para la 004.

## R2. Reconocedor por idioma (ADR-0013)
- **Decision:**

  | Idioma | Motor | Tipo | CER S5 (sin / con música) | Final p50/p95 |
  |---|---|---|---|---|
  | en | Nemotron Streaming 0.6B, 560 ms | streaming | (WER 5 %, 001) | 0,67 / 0,78 s |
  | zh | X-ASR-zh-en, 960 ms | streaming, con comas | 4,87 / 5,15 % | 0,58 / 0,61 s |
  | ja | SenseVoice-Small 2024-07-17 | por segmento de VAD, con puntuación | 8,32 % | 0,88 / 1,39 s |
  | ko | SenseVoice-Small 2024-07-17 | por segmento, con espacios | 7,14 / 8,09 % | 0,91 / 1,23 s |

- **Motor por segmento** (`asr/sensevoice.py`):
  - `accept()` acumula el habla y no emite nada;
  - `flush()`, que el pipeline llama al final de la voz, decodifica y devuelve un FINAL;
  - `capabilities.partials=False`.
- **Corte forzado:** para cumplir el máximo de habla sin traducir (FR-005 de la 001), el motor cierra el segmento a los `max_habla_sin_traducir_s` de habla continua, en la trama de menos energía de los últimos 1,5 s, y emite su FINAL.
- **Alternativa del japonés:** Parakeet-tdt_ctc-0.6b-ja (CER 5,31 %; p95 de 2,0 s, y 3,35 s con la CPU cargada). Se cambia a ella si SC-002 no llega en japonés.
- **Rationale:** el mejor CER con latencia ≤ 1,4 s, sin VRAM y con poca CPU (0,07-0,13 núcleos). Un mismo modelo para ja y ko ahorra descarga y memoria.
- **Alternatives considered:**
  - Nemotron 3.5 multilingüe: CER del 12,6 % en ja y del 19,5 % en zh;
  - SenseVoice para zh: peor y más lento que X-ASR;
  - el zipformer coreano y kangkyu: sin espacios;
  - ReazonSpeech: sin puntuación;
  - Whisper turbo: VRAM.

## R3. Filtro de idioma (ADR-0012)
- **Decision:**
  - `WhisperLanguageVerifier`: encoder y decoder de Whisper **base** en ONNX con onnxruntime en CPU, un hilo.
  - Por cada unidad con texto, toma del anillo de audio la ventana `[max(t_start, t_end − 6 s), t_end]`; si dura menos de 1 s, se completa por la izquierda.
  - Calcula las probabilidades de idioma restringidas a {en, es, ja, zh, ko}.
  - **Acepta si gana el idioma elegido.**
  - En ja y ko, si SenseVoice da su etiqueta de idioma, se exige también que coincida (comprobación AND).
  - Va en el hilo de traducción, antes de traducir. Una unidad rechazada se registra como `Outcome.REJECTED` con el motivo «idioma».
- **Datos S5** (300 recortes por idioma):
  - acepta el 97,3 % (ja), el 99,0 % (zh) y el 97,7 % (ko) del idioma correcto;
  - deja pasar el 0,3-0,7 % del español;
  - coste: 96/131 ms (p50/p95).
- **Rationale:** cubre SC-003b, la película por Discord con la llamada en español, sin depender de separar procesos.
- **Alternatives considered:**
  - Whisper tiny: 49 ms, pero 96-99 % de aceptación;
  - restringir a {elegido, es}: deja pasar el inglés;
  - la proporción de escritura: no sirve;
  - la API de sherpa: solo da el top-1.

## R4. Escuchar la aplicación elegida (ADR-0012, S6)
- **Decision:**
  - **Lista** (`audio/apps.py`):
    - sesiones de audio de todos los dispositivos de salida activos (250-340 ms);
    - objetivo = la sesión, o su padre directo si tiene la misma imagen;
    - agrupadas por ruta del ejecutable, con el nombre visible del `FileDescription`;
    - una **sonda INCLUDE de 0,6 s** por app decide «suena» (≥ -60 dBFS RMS): el medidor de pico de la sesión engaña con Discord;
    - se ocultan la propia app y todos sus antepasados.
  - **Identidad:** la ruta del ejecutable, guardada en `app_escuchada`.
  - **Fuente** (`audio/app_source.py`, `AppLoopbackSource`):
    - vigilante cada 0,25 s por (PID, hora de creación);
    - estados `esperando`, `sonando` y `silencio`;
    - mientras espera, entrega chunks de ceros a ritmo de reloj, para que el pipeline siga y no se capte nada más;
    - al encontrar la app, abre INCLUDE sobre el PID nuevo;
    - reanudación medida: audio a los 32-187 ms y detección de la muerte a los 46-533 ms.
  - **`ProcessLoopbackSource` en modo INCLUDE** deja de vigilar el PID objetivo (S6, hallazgo 2).
  - **Aviso de «suena pero llega silencio»** a los ~4 s, solo si la sonda dice que la app suena (fallo silencioso de un PID muerto o de contenido con DRM).
  - **Discord (SC-003b):**
    - Plan A, si la emisión y la llamada salen por hijos distintos: capturar solo el hijo de la emisión.
    - Plan B, si salen por el mismo proceso: solo el filtro de idioma (R3).
    - Se mide con el humano (`spikes/captura_app/discord_sesiones.py`) en la validación. El diseño funciona en los dos casos.
- **Rationale:** medido con Chrome 154, Edge 154 y Discord en el PC del humano. Otra app sonando no entra (SC-003 cumplido en el spike).
- **Alternatives considered:** sustituir la app por su nombre de proceso (`DiscordSystemHelper.exe` ≠ `Discord.exe`); varias capturas mezcladas, sin necesidad.

## R5. Autotest con la escucha de una app
- **Decision:** `run_echo_selftest` sin cambios, con el cableado invertido:
  - `make_source(False)` = INCLUDE de la app;
  - `make_source(True)` = INCLUDE propia.
- **Rationale:** S6 lo verificó: falla, como debe, con el PID propio, el padre y los antepasados de nivel 2-3; pasa con la app.
- **Limitación conocida:** con una app que no suena, el autotest solo garantiza que la voz propia no entra. Que llegue audio lo vigila el aviso de silencio (R4).

## R6. Presupuesto de latencia por idioma
- **Decision:**

  | Etapa | en | zh | ja / ko |
  |---|---|---|---|
  | Final del ASR (p95) | 0,8 s | 0,6 s | 1,2-1,4 s |
  | Filtro de idioma (p95) | 0,13 s | 0,13 s | 0,13 s |
  | Traducción (p95, S5) | 0,35 s | 0,66-0,87 s | 0,66-0,87 s |
  | Primer audio de la voz (p95) | 0,3 s | 0,3 s | 0,3 s |

  Con la cola, p95 ≈ 3-3,5 s < 5 s (SC-001).
- **Rationale:** sobra margen, pero se valida con contenido real; el corpus FLEURS es habla leída.

## R7. Habla baja y unidades partidas (S7)
- **Decision:**
  - **Silero:** umbral 0,30 y negativo 0,15 por defecto (antes 0,5/0,35): +1,7 puntos de frases traducidas en condiciones duras, +0,04 s.
  - **AGC sin cambios:** la relajación rápida empeora.
  - **Silencio mínimo:** 500 ms.
  - **Segmentador, cola mínima de unidad:** no cerrar por coma ni por pausa una unidad de menos de 4 palabras (en, ko) o de menos de 8 caracteres (ja, zh); se une a la siguiente. En inglés baja las unidades de ≤ 3 palabras del 14,5 % al 8,2 %, con +0,9 s en el p95 por unidad. El tope de `max_habla_sin_traducir_s` sigue mandando.
- **Rationale (datos S7):**
  - el nivel no es el problema: de -20 a -51 dBFS se traduce el 100 %;
  - lo que falla es la voz por debajo de la música (SNR ≤ -2 dB: 65 %), y eso queda fuera de esta versión, salvo los umbrales;
  - en la sesión real, un 25 % de las unidades tenía ≤ 3 palabras.
- **Alternatives considered:**
  - silencio de 700 ms: +0,19 s de p50 por 1,6 puntos;
  - realce de voz (DeepFilterNet): empeora el WER en la bibliografía; no se probó;
  - FireRedVAD: queda pendiente.
- **Riesgo:** las falsas alarmas con música (SC-007) solo se probaron con música instrumental: 0 frases. Se validan con material real en la ola 3.

## R8. «Vosotros» (S7, objetivo revisado SC-006: ≥ 80 % y «ustedes» ≤ 2 %)
- **Decision:**
  1. **Nota de escena**, solo con origen en inglés: si las últimas 5 líneas en inglés tienen marca de plural y ninguna de singular, se añade al turno una nota de estilo para el plural informal.
     - 66-69 % de «vosotros», sin dañar los singulares.
     - Hay que **recortar la salida desde «\n\n("**: el 7B repite la nota en ~6,6 % de las frases y el filtro de longitud las rechazaría.
  2. **Posedición por reglas** (`mt/vosotros.py`, 18-32 µs por frase):
     - convierte «ustedes» y la morfología verbal a «vosotros» solo con la señal del inglés: «you» plural, «you guys», «everyone» o «all of you»;
     - sube a 74 % y deja «ustedes» en 1 %, con 0 daños en singulares y en la 3.ª persona del plural.
  3. **Reintento con el 7B** solo si queda «ustedes» con la señal de plural informal (≈ 3,5 % de las frases): medido hasta 81 %, con +80-174 ms de media.
  4. **Modo CONCISE:** una cláusula de estilo y 2 ejemplos (del 2 % al 43 % de «vosotros»).
- **Origen ja/zh/ko:** no hay señal del inglés. Solo se aplica la nota de estilo general del prompt. SC-006 se mide con origen inglés.
- **Alternatives considered:**
  - más ejemplos fijos: empeora (40 %);
  - `logit_bias`: no aporta, porque «ustedes» se parte en tokens;
  - un segundo LLM: no cabe en VRAM.

## R9. Componentes nuevos y licencias
- **Decision:** `preparar` añade al manifiesto:

  | Componente | Licencia | Tamaño aprox. |
  |---|---|---|
  | x-asr-zh (X-ASR-zh-en streaming int8, con puntuación) | Apache-2.0 | 134 MB |
  | sensevoice-small (2024-07-17 int8) | FunASR Model License v1.1: atribución y conservar el nombre; sin territorio | 163 MB |
  | whisper-base-lid (encoder y decoder ONNX) | MIT | a confirmar al fijar los hashes (~150 MB) |

  Las URL, las revisiones y los sha256 se fijan en la tarea del manifiesto, como en la 001 (T013).
- **Rationale:** todas son gratuitas y válidas para uso personal en la UE, según el informe de investigación, con [V] = texto leído. La FunASR License tiene una cláusula rara (la 4.2, retirada por denigrar el modelo), aceptable para uso personal; queda anotada.

## R10. Traducción por idioma (S5)
- **Decision:**
  - `TranslationRequest.source_language`; el prompt nombra el idioma de origen.
  - **Filtro de longitud por idioma** (relación de caracteres salida/entrada): en ≤ 3×, ko ≤ 4×, ja ≤ 6× y zh ≤ 7×. En S5 la relación tiene p50 de 2,8 (zh), 3,9 (ja) y 2,4 (ko), y máximo 5,0.
  - **`max_tokens`** por caracteres en CJK, porque `count_words` cuenta una tira de ideogramas como una sola palabra.
  - El **glosario base de España** solo actúa con origen inglés.
- **Rationale:** con el código de la 001, el filtro rechazaba 48 de 50 frases en chino y `max_tokens` truncaba 3-4 de 50 en ja y zh. Con 6× no cae ninguna.
- **Calidad:** chrF de 46-48 frente a la referencia es_419. Juicio humano en SC-002 con `spikes/idiomas/traducciones_*.md` como base.

## Validación pendiente de la 001 (se hace en la ola 3)
- **SC-008:** 30 min sin eco.
- **SC-009:** 60 min estables.
- **Cambio de dispositivo:** §10 de la 001.
- **Sin red (SC-010):** con los motores nuevos incluidos.
