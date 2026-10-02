# Spike S7 · Habla baja, susurrada o alargada y «vosotros»

Spike de investigación de la feature 002 (FR-013, FR-014, FR-015, SC-005, SC-006, SC-007). **No es código de producto**: lo que se entrega son mediciones y una recomendación con valores concretos. Medido el 2026-10-02 en esta máquina (Ryzen 7 8700F, RTX 5070, Windows 11) con el corpus **sintético** y el tratamiento **informal por defecto**, como decidió el humano. Audio, modelos y cachés viven **fuera del repo**, en `%LOCALAPPDATA%\InstantTraductor\spikes\habla_baja\` (`dl\` descargas, `c2\` corpus, `out\` volcados). En el repo solo hay código y `resultados\`.

## Resumen en cifras

**Parte A, habla baja.** Con la cadena actual (AGC, Silero, Nemotron 560 ms y segmentador reales, en modo archivo) sobre 780 clips sintéticos:

- **La cadena no pierde habla por el nivel.** Con 40 enunciados por condición, del habla a −20 a −50 dBFS se traduce el 100 % de las frases (recall de palabras 96,4 % a −20 y 93,5 % a −51). Sin AGC y con VAD perfecto, Nemotron mantiene el 97 a 99 % de las palabras de −15 a −40 dBFS y el 93,5 % a −55 dBFS; cae al 83,7 % a −60 dBFS (curva A2). La hipótesis del informe previo («Nemotron sin normalización es sensible al nivel») **no se confirma** en ese rango.
- **El AGC casi no pierde nada** (−0,1 puntos en el total del embudo) y **tras una explosión** (`after_loud`: voz a −35 dBFS 0,4 s después de un golpe a −12) **se traduce el 100 %**. Hacer la relajación más rápida (1 s a 0,25 s) **empeora** las condiciones duras: 86,1 % → 82,8 % de frases traducidas. Subir el tope a +40 dB no cambia nada.
- **Lo que pierde es la voz baja bajo música** (embudo de las 780 clips: ASR/audio 4,9 puntos, VAD 2,0, AGC −0,1, segmentador 0,0 puntos de palabras). Con la voz por debajo de la música (SNR −2 a −6 dB) se traduce solo el **65 %** (mus_d, whisper_mus y susurro de Qwen3-TTS sobre música); con SNR +2 a 0 dB, el 90 % al 100 %. Ahí pierden el **VAD** (6,7 a 27 puntos de palabras) y el techo del **ASR** (7 a 23).
- **El susurro por sí solo no es el problema.** Susurro por DSP (−30 y −42 dBFS): 98 % traducido. Susurro de Qwen3-TTS: 100 % a −30, 95 % a −42 y 65 % sobre música a SNR −2. Nemotron lee bien el susurro sintético (techo perdido 1,7 a 5,4 puntos).
- **Umbral de Silero:** bajarlo de 0,5/0,35 a **0,30/0,15** sube las frases traducidas en condiciones duras de 86,1 % a 87,8 % (recall 82,5 → 85,1 %), con +0,04 s de retardo del fin de frase (p50 0,54 → 0,58 s). **0,25/0,10**: 88,9 % (+0,06 s). Con el silencio mínimo a 700 ms y 0,30/0,15: 89,4 % pero p50 0,77 s. **Falsas alarmas: 0 frases** en 10 min de música y efectos con cualquier umbral (como mucho 1 tramo de 0,2 s), pero esa prueba es débil (ver límites).
- **Segmentación:** el 14,5 % de las unidades de las frases normales son de 1 a 3 palabras («she said sadly»). Exigir 4 palabras de cola tras un corte de cláusula las baja al **8,2 %** (+0,9 s en el p95 de la latencia por unidad: 1,06 → 1,97 s).

**Parte B, «vosotros»** (Hy-MT2-7B Q4_K_M, corpus B0 de 228 frases nuevas: 167 de «you» plural informal, 24 singulares, 18 formales, 19 de 3.ª persona del plural):

| Configuración | «vosotros» en las 167 plurales (IC 95 %) | «ustedes» | «tú» (número equivocado) | daño: singulares que salen en «vosotros» | coste extra |
|---|---:|---:|---:|---:|---|
| Prompt actual (3 semillas) | **49-50 %** (42-57) | 16-17 % | 28 % | 8 % (2/24, ya en el actual) | 0 |
| + posedición por reglas | 65 % | 1 % | 29 % | 8 % | ~25 µs/frase |
| Nota de plural condicionada a la escena (`state_note`, 3 semillas, con la nota repetida recortada) | 66-69 % | 7-10 % | 17-19 % | 8 % | +~15 tokens |
| `state_note` + reglas | **74 %** (67-80) | 1 % | 18 % | 8 % | ~25 µs/frase |
| Prompt actual + reglas + reintento con nota solo en las marcadas (23 % de las frases) | **81 %** (74-86) | 1 % | 13 % | 8 % | +80 a +174 ms de media por frase (medido con la CPU saturada por otros procesos) |

Control de daño: de las 19 frases de 3.ª persona del plural, **0** pasan a «vosotros» o «ustedes» en todas las configuraciones; la posedición no toca ninguna singular ni ninguna de 3.ª persona. Calidad en el corpus S2 (`quality.py`): sin cambios (0 no-traducciones, 15/16 de léxico de España, 1 a 2 de 10 trampas fallidas, igual que el prompt actual).

## Qué hay en la carpeta

| Fichero | Para qué |
|---|---|
| `pyproject.toml`, `uv.lock` | Proyecto uv propio: `uv sync --directory spikes/habla_baja`. Depende de `instanttraductor` en modo editable (`../..`, solo lectura) más `jiwer`, `whisper-normalizer`, `scipy`, `soundfile`, `filelock`. |
| `common.py`, `dsp_tools.py` | Rutas, utilidades de nivel; susurro por DSP, time-stretch WSOLA, efectos sintéticos. |
| `find_music.py` | Búsqueda y descarga de música CC0 de Wikimedia Commons. |
| `build_c2.py`, `build_c2_extra.py`, `tts_whisper.py`, `build_c2_tts.py` | Construyen el corpus C2 (780 clips y el clip de 10 min de música y efectos). |
| `chain.py`, `evalcore.py` | La cadena real en modo archivo, instrumentada, con cachés deterministas de Silero y del ASR. Métricas. |
| `a0_funnel.py`, `experiments_a.py`, `a_report.py` | A0 (embudo), A1/A3 (VAD, AGC), A2 (curva de nivel), segmentador. |
| `corpus_b0.py`, `detector.py`, `detector_eval.py` | Corpus B0, detector de «vosotros» y su medida. |
| `prompts_b1.py`, `mt_lab.py`, `b1_report.py` | Variantes de prompt (B1), banco de pruebas con `llama-server` bajo `gpu_lock()`. |
| `postedit.py`, `b2_postedit_eval.py`, `b2_retry.py`, `b2_report.py` | Posedición por reglas, reintento y tablas (B2). |
| `resultados/` | Resultados ligeros: `a0_*`, `a1_*`, `a_full_*`, `a2_*`, `seg_*`, `b0_*`, `b1_tabla.md`, `b2_*`. |

Reproducir: `uv run --directory spikes/habla_baja python build_c2.py` (necesita `find_music.py get ...` y LibriSpeech test-clean en `dl\`), luego `a0_funnel.py`, `experiments_a.py vad1|full|curve|seg`, `mt_lab.py run ...`, `b2_retry.py ...`. Todo el uso de GPU va dentro de `gpu_lock()` (`mt_lab.py`, `b2_retry.py` y `tts_whisper.py`).

## Parte A: habla baja

### Corpus C2 (sintético, 780 clips)

- **Voz:** 40 enunciados en inglés: 10 de `tests/fixtures/dialogo_en_2min.wav` (LibriSpeech, CC BY 4.0, separados por sus silencios) y 30 de **LibriSpeech test-clean** (CC BY 4.0, un enunciado por locutor, de 3 a 9 s; descargado de openslr.org/12). Se recorta el silencio de los extremos y se pone el nivel por el **RMS de los tramos activos** (dBFS). Cada clip lleva 1,5 s de margen, ruido de fondo a −70 dBFS y la posición real del habla (`manifest.json`).
- **Condiciones** (40 enunciados cada una, salvo las marcadas con 20): `n20`, `n30`, `n40`, `n50` (nivel); `mus_a` (voz −26, música −34: SNR +8 dB), `mus_b` (+2 dB), `mus_c` (−2 dB, 20 enunciados), `mus_d` (−6 dB, 20); `sfx_a` (SNR 0 dB sobre explosiones, disparos, pasos, viento; 20); `reverb` (RT60 ≈ 0,7 s; 20); `whisper` y `whisper_q` (susurro por DSP a −30 y −42 dBFS); `whisper_mus` (DSP −36 sobre música a −34; 20); `whisper_tts`, `whisper_tts_q` y `whisper_tts_mus` (susurro de **Qwen3-TTS-12Hz-1.7B-VoiceDesign**, 20 enunciados); `stretch` (3 vocales ×2,8 por WSOLA), `stretch4` (4 vocales ×4; 20), `slow` (×1,6 global); `hesitate` (dos pausas de 0,65 s dentro del enunciado; 20); `after_loud` (explosión a −12 dBFS y voz a −35 dBFS 0,4 s después).
- **Susurro:** no hay una voz de referencia susurrada con licencia libre. Hay dos aproximaciones: (a) DSP (`whisperize`: se conserva la envolvente espectral por liftering cepstral y se excita con ruido, sin graves ni tono) y (b) Qwen3-TTS VoiceDesign (Apache-2.0) con la instrucción «a person whispering very softly and breathily, with no voiced pitch…». Ninguna es una persona susurrando.
- **Música (todas CC0, Wikimedia Commons):** Komiku (`Action Time Attack Research`, `Ambiant Anxiety`, `Action Chasing`, `Action Investigation`, `Ambiant Evil`, `Ambiant Nervous Breakdown`, `Ambiant Wait`, `Action Fight`) y Loyalty Freak Music (`A ghost Waltz`, `The Old Witch Place`, `The graveyard`, `A really dark alley`, `The Swamp`, `Hello Regan`, `Monster Parade`), más `Chopin - Piano Concerto no. 1 (string quartet)-2`. Para las mezclas se usaron 5 pistas; para el clip de falsas alarmas, otras 5. Los 10 min sin diálogo son 7 min de música (−26 ± 4 dBFS) y 3 min de efectos sintéticos (−22 dBFS), sin voz.

### A0: embudo por etapa (cadena actual, modo archivo)

Cada clip se mide en cuatro puntos con el recall de palabras (palabras de la referencia que salen bien, texto normalizado): **techo** (ASR con ganancia ideal −20 dBFS y VAD perfecto), **AGC** (tras el AGC real, VAD perfecto), **VAD** (solo lo que deja pasar Silero) y **unidades** (texto del segmentador). La pérdida de cada etapa es la diferencia entre un punto y el anterior (puntos de palabras). «Frase traducida» = las unidades recuperan ≥ 60 % de las palabras (proxy de SC-005: el traductor no está en el bucle).

| Condición | n | ASR/audio pierde | AGC | VAD | Segmentador | Recall final | % frases traducidas |
|---|---:|---:|---:|---:|---:|---:|---:|
| n20 / n30 / n40 | 40 | 3,4 / 3,4 / 3,2 | −0,4 / 0,1 / 1,1 | 0,6 / −0,1 / −0,3 | 0 | 96,4 / 96,6 / 96,0 | 100 |
| n50 (−51 dBFS) | 40 | 4,7 | 0,3 | 1,5 | 0 | 93,5 | 100 |
| mus_a (SNR +8) | 40 | 3,9 | 0,0 | 0,6 | 0 | 95,4 | 100 |
| mus_b (SNR +2) | 40 | 7,9 | −0,9 | 4,1 | 0 | 88,9 | 92 |
| mus_c (SNR −2) | 20 | 7,3 | 0,1 | 9,7 | 0 | 83,0 | 90 |
| mus_d (SNR −6) | 20 | 23,0 | 1,7 | 6,7 | 0 | 68,6 | 65 |
| whisper / whisper_q (DSP) | 40 | 5,4 / 6,5 | −0,3 / −1,8 | 4,7 / 7,7 | 0 | 90,2 / 87,7 | 98 / 98 |
| whisper_tts / _q (Qwen3-TTS) | 20 | 2,7 / 1,7 | −0,7 / 0,2 | 2,6 / 6,9 | 0 | 95,3 / 91,1 | 100 / 95 |
| whisper_mus (DSP, SNR −2) | 20 | 19,0 | 1,8 | 15,9 | 0 | 63,3 | 65 |
| whisper_tts_mus (SNR −2) | 20 | 5,1 | 0,1 | 27,4 | 0 | 67,5 | 65 |
| sfx_a (SNR 0, efectos) | 20 | 3,7 | 0,1 | −0,4 | 0 | 96,7 | 100 |
| reverb | 20 | 5,3 | 0,5 | 3,0 | 0 | 91,2 | 100 |
| stretch / slow / stretch4 | 40 / 40 / 20 | 6,1 / 5,4 / 7,0 | 0,5 / −0,2 / 1,7 | 1,8 / 0,9 / 1,6 | 0 | 91,6 / 93,8 / 89,7 | 98 / 100 / 100 |
| hesitate (2 pausas de 0,65 s) | 20 | 3,5 | 0,0 | 1,7 | 0 | 94,7 | 100 |
| after_loud | 40 | 3,5 | 0,5 | 0,6 | 0 | 95,3 | 100 |

Detalle por clip y por condición (nivel de entrada y tras el AGC, ganancia, probabilidad máxima de Silero, retardo): `resultados/a0_resumen*.md` y `a0_clips*.json`. Lectura:

1. **Etapa que explica la pérdida:** ASR/audio y VAD, en ese orden; el AGC y el segmentador no pierden palabras. En los 440 clips de las 11 condiciones originales el reparto es ASR/audio 4,9, VAD 2,0, AGC −0,1 y segmentador 0,0 puntos de palabras; en las 7 condiciones duras añadidas (140 clips) es 9,8, 5,5, 0,8 y 0,0.
2. **Todo lo que falla tiene música por encima de la voz** (SNR ≤ −2 dB) o susurro sobre música. Sin música, ningún nivel hasta −51 dBFS ni el susurro bajan del 95 %.
3. **El primer segundo tras una escena fuerte no se pierde** (`after_loud`, ganancia al empezar la voz −2 dB, 100 % traducido). La hipótesis de la relajación de 1 s del AGC no se reproduce con este corpus.
4. **Retardo del fin del habla a la unidad lista:** p50 0,54 s y p95 0,56 a 0,70 s sin música; con música p95 1,4 a 1,5 s (el VAD tarda más en cerrar). Es el retardo algorítmico, sin el cómputo del ASR.
5. **Falsas alarmas (10 min de música y efectos):** 0 tramos y 0 frases con la cadena actual (SC-007 ≤ 1: se cumple en este clip).

### A2: curva de nivel (Nemotron sin AGC, VAD perfecto)

Recall medio de 10 frases limpias reescaladas (RMS activo en dBFS): −15: 97,8 %, −20: 98,5, −25: 98,6, −30: 99,0, −35: 97,8, −40: 97,2, −45: 95,7, −50: 93,8, −55: 93,5, **−60: 83,7**. Por encima de −55 dBFS el nivel casi no importa; el AGC solo hace falta bajo ese nivel, que es justo donde su puerta (−60 dBFS) deja de subir la ganancia. Ruido de fondo fijo a −70 dBFS en todos los clips (`resultados/a2_curva_nivel.json`).

### A1 y siguientes: barridos

**Nivel 1, solo VAD** (sin ASR, 780 clips + 10 min sin diálogo; `resultados/a1_vad_nivel1.md`): fracción del habla cubierta por los tramos del VAD y falsas alarmas.

| Config. (umbral/salida) | cubierto, condiciones duras % | clips con ≥ 90 % cubierto % | tramos por clip | FA: tramos en 10 min |
|---|---:|---:|---:|---:|
| 0,5/0,35 (actual) | 91,1 | 72,8 | 1,31 | 0 |
| 0,40/0,25 | 92,2 | 75,8 | 1,26 | 0 |
| 0,30/0,15 | 93,4 | 80,5 | 1,21 | 1 (0 s) |
| 0,25/0,10 | 94,2 | 84,8 | 1,16 | 1 (0 s) |
| 0,5/0,35 con entrada persistente (≥ 0,25 durante 6 tramas) | 92,3 | 76,8 | 1,27 | 0 |
| 0,40/0,25 con media móvil de 3 tramas | 92,1 | 77,0 | 1,23 | 0 |
| 0,40/0,25 con silencio mínimo 300 / 700 / 1000 ms | 91,2 / 93,1 / 93,8 | 70,8 / 79,5 / 81,2 | 1,50 / 1,12 / 1,06 | 0 |

(El «cubierto» no llega al 100 % porque los enunciados tienen pausas internas de más de 0,5 s que el VAD corta con razón.)

**Nivel 2, cadena completa** (20 enunciados × 11 condiciones: `mus_b`, `mus_c`, `mus_d`, `whisper_q`, `whisper_mus`, `after_loud`, `reverb`, `n20`, `hesitate`, `whisper_tts`, `whisper_tts_mus`; 6 de ellas «duras»; ASR real, 10 min de FA; `resultados/a_full_tabla.md`):

| Configuración | % frases traducidas (duras) | recall duras % | % traducidas (fáciles) | retardo del fin p50 / p95 (s) | unidades/clip | FA: frases | FA: s de «habla» |
|---|---:|---:|---:|---:|---:|---:|---:|
| **actual** 0,5/0,35, 500 ms | 86,1 | 82,5 | 100 | 0,54 / 1,30 | 2,36 | 0 | 0 |
| 0,35/0,20 | 87,2 | 84,1 | 100 | 0,56 / 1,50 | 3,28 | 0 | 0,2 |
| **0,30/0,15** | 87,8 | 85,1 | 100 | 0,58 / 1,50 | 3,21 | 0 | 0,2 |
| 0,25/0,10 | 88,9 | 86,7 | 100 | 0,60 / 1,50 | 3,37 | 0 | 0,3 |
| 0,40/0,25 + media móvil de 3 tramas | 85,6 | 82,5 | 100 | 0,60 / 1,49 | 2,80 | 0 | 0 |
| 0,30/0,15 con silencio mínimo 700 ms | 89,4 | 85,8 | 100 | 0,77 / 1,50 | 3,30 | 0 | 0,2 |
| AGC con relajación 0,25 s | 82,8 | 79,1 | 100 | 0,55 / 1,28 | 2,25 | 0 | 0 |
| AGC con relajación 0,25 s y +40 dB | 82,8 | 78,8 | 100 | 0,55 / 1,28 | 2,32 | 0 | 0 |

Por condición (% traducidas, actual → 0,25/0,10): `mus_b` 90 → 95, `whisper_mus` 65 → 70, `whisper_tts_mus` 65 → 80, `mus_c` 90 → 90, `mus_d` 65 → 65; las demás, 100 → 100. Las condiciones donde la voz queda por debajo de la música (`mus_d`, `whisper_mus`) **no mejoran**: ahí el límite es el ASR y la separación, no el umbral.

**Segmentador** (reutiliza el ASR cacheado: sin cómputo nuevo; 440 clips de 11 condiciones; `resultados/seg_segmentador.md`). El recall no cambia (el texto es el mismo); cambia la fragmentación y la latencia por unidad (listo − fin de la unidad):

| Segmentador | unidades/clip | % unidades ≤ 3 palabras | latencia por unidad p50 / p95 (s) |
|---|---:|---:|---:|
| actual (6 palabras, comas y conjunciones) | 2,33 | 14,5 | 0,55 / 1,06 |
| 8 palabras | 2,15 | 13,1 | 0,54 / 1,04 |
| solo comas, 8 palabras | 1,95 | 12,4 | 0,52 / 0,78 |
| cola mínima 3 / **4** / 5 palabras tras el corte | 2,29 / 2,15 / 2,12 | 13,3 / **8,2** / 9,4 | 0,55 / 1,43 · **0,55 / 1,97** · 0,54 / 2,19 |
| 8 palabras + cola mínima 4 | 2,04 | 9,2 | 0,54 / 1,69 |

Las unidades cortas son las colas tras un corte de cláusula («she said sadly», «real or ostensible»). Con dudas de 0,65 s dentro del enunciado (`hesitate`) el VAD parte en 3,4 unidades por clip (el 29 % de ≤ 3 palabras) con el silencio de 500 ms; con 700 ms baja a 1,12 tramos por clip en las condiciones duras (nivel 1).

## Parte B: «vosotros»

### B0: corpus y detector

- **Corpus** (`corpus_b0.py`): 228 frases inglesas nuevas en 38 escenas de 6 líneas, escritas para este spike (ninguna está en el corpus S2). 167 con «you» plural informal (77 imperativos, 25 imperativos negativos, 35 preguntas con «you» sin marca, 30 afirmaciones; 34 con marca explícita como «you guys», «all of you», «everyone»), 24 singulares informales, 18 formales (usted y ustedes, informativos) y 19 de 3.ª persona del plural legítima («they», «the neighbors»; control de daño). Cada frase lleva la etiqueta esperada. El contexto de cada frase son las 4 traducciones anteriores de su escena, como en la sesión.
- **Detector** (`detector.py`, reglas léxicas y morfológicas con ayuda del inglés para los verbos en 3.ª plural). Medido contra **mi etiquetado a mano** de las 228 salidas del 7B con el prompt actual (`detector_eval.py`, `resultados/b0_detector.md`): **vosotros: precisión 97,6 % (81/83), cobertura 100 %**; ustedes: 93,5 % y 96,7 %; tú: 100 % y 91,7 %; usted: 87,5 % y 100 %. Las marcas de «vosotros» no distinguen las frases mixtas («Avísame si necesitáis», 2 de 81).

### B1: prompt (solo Hy-MT2-7B Q4_K_M; `resultados/b1_tabla.md`)

Variantes (una semilla salvo las marcadas), con el 7B en `llama-server` (flags de producción con `-c 8192` por el tamaño de algunas variantes):

| Variante | «vosotros» en plurales | «ustedes» | «tú» | daño en singulares | daño en 3.ª plural | tokens de prompt | ms p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| actual (3 semillas) | 49-50 % | 16-17 | 28 | 8 % | 0/19 | 767 | 151 / 213 |
| (a) estilo en cada turno (plantilla *Style*, sin sistema) | 54 | 1 | 37 | 8 % | 1/19 | 1 484 | 176 / 259 |
| (b) nota de plural **siempre** al final del turno (3 semillas) | 68-71 | 2 | 20-23 | **21-25 %** | 0-1/19 | 1 150 | 161 / 228 |
| **(b') nota solo si la escena indica un grupo** (`state_note`, 3 semillas) | **66-69** | 7-10 | 17-19 | 8 % | 0/19 | 782 | 178 / 440 |
| (c) 36 ejemplos fijos (mini-escenas con plural, singular y formal) | **40** | 15 | 36 | 0 % | 0/19 | 1 836 | 173 / 244 |
| (c+a) 36 ejemplos + estilo en el turno | 59 | 1 | 32 | 8 % | 0/19 | 3 804 | 183 / 269 |
| (c+b) 36 ejemplos + nota siempre | 60 | 4 | 29 | 12 % | 0/19 | 2 845 | 176 / 251 |
| (c+b') 36 ejemplos + nota por escena | 54 | 8 | 28 | 0 % | 0/19 | 1 852 | 192 / 477 |
| (d) 3 ejemplos dinámicos por tipo de frase | 47 | 14 | 32 | 8 % | 0/19 | 901 | 187 / 250 |
| (c+d) 36 fijos + 3 dinámicos | 38 | 17 | 36 | 0 % | 0/19 | 1 970 | 202 / 268 |

- **Más ejemplos empeoran** (40 % frente a 49-50 %): empujan al «tú». El único mecanismo que funciona es una **instrucción explícita de plural informal en el último turno** (estilo en el turno, o la nota). Hacerlo siempre cuesta el 21-25 % de los singulares en «vosotros» (error de número, peor que «ustedes»).
- **Las cuatro primeras variantes (actual, estilo en el turno, nota siempre, 36 ejemplos) se midieron con `-c 4096`; el resto con `-c 8192`** (algunas no caben en 4096, como los 3 804 tokens de (c+a): con el contexto de producción habría que subirlo).
- **La escena decide:** (b') pone la nota solo si en las últimas 5 líneas en inglés hubo una marca de plural (`you guys`, `everyone`, `kids`, `team`, `class`...) y ninguna de singular (`buddy`, `sir`, `honey`...), o si la propia frase lleva marca de plural. Gana 16 puntos frente al actual sin subir el daño en singulares.
- **El modelo a veces repite la nota** traducida tras la traducción («\n\n(Español de España, informal: ...)»): en `state_note` ocurrió en el 6,6 % de las frases y el filtro de longitud de producción las **rechaza** (frase sin pronunciar). Con el recorte de la nota (`clean_output`: quitar desde el salto de línea doble y el paréntesis final) esas frases valen y las cifras de la tabla ya lo incluyen. **Hay que añadir ese recorte a los filtros de `hymt2.py`** si se adopta la nota.
- **Calidad (corpus S2, 65 + 10 frases):** sin cambios con ninguna variante: 0 no-traducciones, léxico de España 15/16, 1 a 2 trampas fallidas (igual que el actual), 0 rechazadas por los filtros (con la nota recortada).
- **Modo CONCISE** (`--concise`): con la plantilla actual solo el 2 % de las plurales sale en «vosotros» (el 53 % sin ninguna marca de persona); con «vosotros» en la cláusula de estilo, 28 %; con la cláusula y 2 ejemplos telegráficos (`concise_vos_ex`), **43 %** (daño en singulares 4 %). Con la posedición por reglas sobre la plantilla actual sube del 2 % al 23 %. No se midió cuánto acorta cada variante.

### B2: posedición por reglas y reintento (`resultados/b2_tabla.md`)

- **Posedición** (`postedit.py`): «ustedes» → «vosotros»; 3.ª plural → 2.ª plural (presente, pretérito, imperfecto, futuro, condicional, subjuntivo); imperativo («tomen» → «tomad», «síganme» → «seguidme», «siéntense» → «sentaos», «no miren» → «no miréis»); «su(s)» → «vuestro(s)/vuestra(s)» y «les» → «os» solo con «your» y sin «they/their». El léxico de formas se genera con reglas de conjugación y ~300 verbos de diálogo (sin dependencias nuevas). **Solo convierte con la señal del inglés** (hay «you/your/guys...» o un imperativo, y no hay «they/them/their»); no toca verbos precedidos de un sustantivo plural.
- **Resultados sobre el prompt actual** (228 salidas): vosotros en plurales **83 → 109 de 167** (el 50 % → 65 %), ustedes 27 → 1; **0 de 24 singulares y 0 de 19 de 3.ª plural cambiadas**; 3 de 18 formales se convierten a «vosotros» (es lo que pide el tratamiento informal por defecto; con `tratamiento: auto` habría que no tocarlas). Las 30 conversiones (27 plurales y 3 formales), **revisadas una por una** (`resultados/b2_conversiones_base_s42.txt`): ninguna es incorrecta ni cambia el sentido. Durante el desarrollo hubo 3 conversiones dañinas, ya corregidas: «Ven conmigo» → «Veis conmigo» (el imperativo de «venir» leído como «ven» de «ver», 2 veces) y «se están cerrando las puertas» → «se estáis cerrando» (pasiva refleja). **Cuidado: las reglas se afinaron mirando estas mismas salidas**, así que 65 % y 0 daños son optimistas; hace falta otro corpus para confirmarlo (límites). Coste: **18 a 32 µs por frase**.
- **Reintento con el 7B** solo para lo marcado: se marca si tras las reglas queda «ustedes», si el inglés lleva marca de plural y no hay «vosotros», o si el estado de escena es «grupo» y no hay ni «vosotros» ni «ustedes». El reintento repite la petición con la nota de plural; se queda con él si sale «vosotros». `logit_bias` de −100 a los tokens de «usted/ustedes» (61395, 28244, 24836, medidos con `llama-tokenize`) no aporta nada medible sobre la nota (77 % frente a 76 %).

| Combinación (semilla 42) | vosotros en plurales (IC 95 %) | marcadas / de 228 | reintentos que acaban en «vosotros» | coste medio por frase (ms)* |
|---|---:|---:|---:|---:|
| actual + reglas | 65 % (57-72) | 54 (solo se miden) | – | ~0 |
| actual + reglas + reintento con nota | **81 %** (74-86) | 52 | 25 de 52 | 174 |
| `state_note` + reglas | 74 % (67-80) | 38 | – | ~0 |
| `state_note` + reglas + reintento con nota | 76 % (69-82) | 38 | 3 de 38 | 112 |
| `state_note` + reglas + reintento con nota y `logit_bias` | 77 % (70-83) | 37 | 4 de 37 | 90 |

\* Medido con la CPU del PC al 100 % por otros procesos: el reintento tardó p50 380 a 450 ms y p95 1,4 a 1,7 s, **por encima** de los 211/347 ms de S2. No es una medida limpia (ver límites).

- **Lo que ni las reglas ni el reintento arreglan:** el 13-18 % de plurales que salen en «tú» cuando nada del inglés ni de la escena indica plural (p. ej. «Open your books to page twelve.» sin vocativo previo). Ahí hace falta saber el destinatario (hablante, pantalla, texto), que el pipeline no tiene.

## Recomendación concreta para el plan de la spec 002

### Habla baja (FR-013, FR-014, SC-005)

1. **Silero:** `threshold` 0,5 → **0,30** y `neg_threshold` 0,35 → **0,15** (salida = entrada − 0,15, la regla de Silero). Ganancia medida: +1,7 puntos de frases traducidas en condiciones duras (86,1 → 87,8 %) y +2,6 de recall, con +0,04 s de retardo del fin. Si se admite más fragmentación, **0,25/0,10**: 88,9 %. **No** subir el silencio mínimo a 700 ms por defecto (+0,19 s de p50 por +1,6 puntos más). **No** usar entrada persistente ni media móvil (no ganan más que bajar el umbral).
2. **AGC: no tocarlo.** Más ganancia (+40 dB) no cambia nada y una relajación más rápida **empeora** (86,1 → 82,8 %). Nemotron es robusto al nivel de −15 a −55 dBFS.
3. **Segmentador:** exigir **al menos 4 palabras de cola** tras un corte de cláusula (`TailAwareSegmenter` en `chain.py`, ~15 líneas): las unidades de ≤ 3 palabras bajan de 14,5 % a 8,2 %, a costa de +0,9 s en el p95 de la latencia por unidad (1,06 → 1,97 s) y sin cambiar el texto. Alternativa sin coste de latencia: cortar solo en comas con 8 palabras mínimas (12,4 % y p95 0,78 s). La decisión depende de cuánto pese traducir mal un fragmento corto frente a retardo; **no medí la calidad de la traducción de los fragmentos**.
4. **Validación pendiente antes de adoptar el umbral bajo (SC-007):** la prueba de falsas alarmas fue 10 min de música instrumental CC0 y efectos sintéticos; con 0,25 y 0,30 dio 1 tramo de 0,2 s y 0 frases. Con música con voz cantada, risas o murmullos reales puede ser muy distinta. Hay que repetirla con el corpus C1 real (o al menos con 10 min de una serie con música y sin diálogo) antes de fijar el valor.
5. **Lo que queda sin resolver:** voz por debajo de la música (SNR ≤ −2 dB): 65 % traducido con cualquier umbral. Es un límite del ASR y de la mezcla, no del VAD ni del AGC: solo lo cambiaría separar el diálogo (ADR-0008), el canal central en 5.1/7.1 o aceptar el límite. FireRedVAD, DeepFilterNet y el análisis de canales **no se han medido** (A4 a A6 del informe).

### «Vosotros» (FR-015, SC-006)

1. **Prompt:** añadir al turno final (después del texto) la nota `(Spanish from Spain, informal: use "vosotros" when you address several people, never "ustedes".)` **solo cuando la escena indica un grupo** (marca de plural en la frase o en las últimas 5 líneas en inglés y ninguna de singular) y **recortar de la salida** todo lo que siga a un salto de línea doble con paréntesis. Medido: 49-50 % → 66-69 % de «vosotros» en plurales (3 semillas), sin dañar más singulares que hoy. **No** añadir ejemplos fijos (empeoran: 40 %) ni dinámicos (no cambian).
2. **Posedición por reglas** sobre la traducción (y sobre las traducciones que se reinyectan como contexto): 66-69 % → **74 %** con la nota; sin la nota, 50 → 65 %. Cuesta ~25 µs por frase, 0 daño en singulares y en 3.ª persona del plural, y deja «ustedes» en el 1 %. Detrás de un ajuste `tratamiento: informal | formal | auto`: con `auto` o `formal` no se aplica.
3. **Reintento con el 7B (opcional, solo si hace falta pasar del 80 %):** con el prompt actual + reglas + reintento con la nota para el 23 % de las frases marcadas se llega al **81 %** (74-86 %); con `state_note` el reintento aporta solo +2 a +3 puntos. Coste medio medido +80 a +174 ms por frase (con la CPU saturada: hay que repetirlo en limpio). Mi propuesta: **`state_note` + reglas** (74 %, sin coste de latencia) como valor por defecto y el reintento solo para las marcadas por «ustedes» residual o por marca explícita de plural (8 de 228 frases, el 3,5 %).
4. **CONCISE:** cambiar la plantilla a la de `concise_vos_ex` (cláusula de estilo con «vosotros» y 2 ejemplos telegráficos): 2 % → 43 %. Hay que medir cuánto acorta (no se midió) antes de adoptarla.
5. **El detector** (`detector.py`) sirve como métrica del criterio SC-006 con precisión 97,6 % en «vosotros», pero lo etiqueté yo con él delante: hace falta que la persona usuaria revise una muestra de 100 frases para fijar su precisión real.

## Límites

- **Corpus sintético.** LibriSpeech es habla de lectura limpia; la música CC0 es instrumental y las explosiones, sintéticas; el susurro es procesado o generado por TTS; la reverberación es una respuesta al impulso sintética. No hay solapes de voces, risas, canto ni habla emocionada. Por eso el embudo apenas muestra pérdidas fuera de «voz bajo música». **No reproduce los fallos de la sesión real** (51 palabras por minuto, 24 de 95 unidades con ≤ 3 palabras), que quedan sin explicar; esto pide el corpus C1 grabado en crudo.
- **El % de frases traducidas es un proxy** (recall de palabras ≥ 60 % de la referencia sobre el texto de las unidades). No pasa por el traductor ni por los filtros de salida; un fragmento de 2 palabras puede contar como «traducido» y salir mal. No se midió SC-005 de extremo a extremo.
- **Falsas alarmas (SC-007)** probadas solo con 10 min de música instrumental y efectos sintéticos: 0 con todos los umbrales; sin voz cantada. No concluyente.
- **Susurro por DSP y por TTS** no es una persona susurrando; el de Qwen3-TTS (20 enunciados) puede ser más inteligible que el real. Resultados con n = 20: IC de ±10 a 20 puntos.
- **Los barridos de nivel 2 usan 20 enunciados** por condición (11 condiciones, 6 duras): las diferencias de 1 a 3 puntos están dentro del ruido (cada clip pesa 0,5 puntos). Una sola ejecución por configuración; el ASR y el VAD son deterministas, pero la muestra es pequeña.
- **Retardo = algorítmico** (reloj de audio): no incluye el cómputo del ASR. El reintento del 7B se midió con la CPU del PC saturada por otros obreros; la latencia de las peticiones del 7B (p50 150 a 180 ms, p95 210 a 450 ms en B1) también varía con la carga.
- **Las reglas de posedición se afinaron sobre las salidas de B0 del prompt actual** (y los 3 fallos corregidos salieron de ahí): las cifras de B2 son optimistas. Los ejemplos del prompt (`prompts_b1.py`) no están en B0, pero tratan los mismos temas (campamento, clase, equipo).
- **B0 es mío:** corpus, etiquetas y detector son obra de un solo autor (yo); las etiquetas del detector las puse a mano sobre las mismas salidas con las que lo afiné. «Tú» frente a «sin marca» no es fiable (el detector no reconoce todos los imperativos de tú). Las frases formales de B0 son informativas.
- **Una semilla** en la mayoría de las variantes de B1 (tres en las tres principales); IC de Wilson de ±7 puntos con n = 167. La diferencia entre 66-69 % (nota por escena) y 74 % (con reglas) está dentro del orden de dos intervalos.
- **El «contexto saneado»** (aplicar la posedición a las traducciones previas) está **incluido** en las ejecuciones de `b2_retry.py` (`postedit_for_context`), pero no se midió su efecto por separado frente a un contexto sin sanear.
- **Qwen3-TTS** se ejecutó en el entorno `engines/tts-qwen3` (`uv sync --frozen`, sin cambiar su `uv.lock`) con el modelo `qwen3-tts-12hz-1.7b-voicedesign` local (Apache-2.0).
- **Licencias:** LibriSpeech CC BY 4.0 (Panayotov et al., ICASSP 2015); música CC0 de Wikimedia Commons (Komiku, Loyalty Freak Music, un fragmento de Chopin en interpretación CC0); Silero VAD MIT; Qwen3-TTS Apache-2.0; `jiwer` y `whisper-normalizer`, de código abierto; el resto del código es de este spike. No se descargó nada con licencia no libre.
- **Sin hacer:** FireRedVAD y TEN VAD (A4), DeepFilterNet y realce (A6), canales 5.1/7.1 (A5), corpus C1 real, `n_cmpl` y segundo paso con LLM (B4), comparación con otros modelos (B5), japonés y chino.
