# T040 · Voces femeninas castellanas de dominio público (LibriVox) para clonar con Qwen3-TTS

Fecha de la investigación y de todas las consultas: 2026-10-01 · Feature `001-espina-dorsal` · Alcance mínimo, 60 min.

**Convenciones**
- «**Δ(s−θ)**» es el indicio acústico de `spikes/voz/common/distincion.py`: diferencia, en dB, entre la fuerza de la /s/ y la de la /θ/ (palabras con «ce, ci, z»), ambas relativas a la vocal más fuerte de la palabra. Referencias del propio spike (`spikes/voz/README.md`): control peninsular 15,5 dB; seseo argentino 1,8 dB (no significativo); Tux (la voz masculina actual) 5,8 dB. Un Δ grande indica **distinción** /θ/-/s/ (español de España); es un indicio, no una prueba.
- «**F0**» es la frecuencia fundamental mediana (autocorrelación, 40 ms). Es lo único que tengo para decir «voz femenina»: voces adultas femeninas suelen ir de 165 a 255 Hz y masculinas de 85 a 155 Hz (referencia general, **sin verificar** en fuente primaria). Tux da 124 Hz con el mismo método.
- «**Suelo de ruido**» = percentil 10 de la energía por tramas de 20 ms (dB respecto a plena escala); «**SNR aprox.**» = percentil 90 menos percentil 10 de esa energía. Un suelo de −95 dB es silencio digital.
- **No puedo oír el audio.** Acento real, timbre, naturalidad y artefactos los decide el oído del humano. «sin verificar» = no confirmado.

---

## 1) Resumen ejecutivo

1. Hay **4 candidatas** en LibriVox (grabaciones que LibriVox declara de dominio público) con un tramo de 6,7 a 8,9 s de habla limpia cuya transcripción coincide **palabra por palabra** con Project Gutenberg: **juanina**, **Mongope**, **Lu** y **Marian Martin**.
2. Cada tramo se recortó del MP3 original de archive.org con ffmpeg y se re-transcribió con faster-whisper large-v3-turbo: **0 diferencias** con el texto del libro en las 4 principales y en 3 alternativas.
3. Acento: las 4 **distinguen /θ/ de /s/** (Δ de 11 a 14 dB con 4 min de lectura; Tux 5,8). Ninguna ficha de lectora en LibriVox indica procedencia (sin biografía ni ciudad), así que «de España» queda como **indicio acústico**.
4. «Femenina» se apoya solo en la F0 (174 a 200 Hz en los tramos). Hace falta confirmarlo de oído.
5. **Orden recomendado:** 1) juanina, 2) Mongope, 3) Lu, 4) Marian Martin (motivos en §4). Mongope es la mejor alternativa si el humano prefiere su timbre: es la más consistente entre libros y la de más material en LibriVox.
6. Descartadas por seseo (Δ ≈ 0): Karen Savage, Claudia Caldi, mariemdover, Joyfull, Consuelo Aponte; Maritza Mateo y KendalRigans (Δ ≈ 2,5). Meribau distingue (Δ 25 dB) pero su F0 (150 Hz) apunta a voz masculina.
7. **Muestras para escuchar:** `%LOCALAPPDATA%\InstantTraductor\spikes\voces-candidatas\es-f-<id>.wav` (WAV PCM16 mono 24 kHz). MP3 originales y sus sha256 en `...\voces-candidatas\raw\`.
8. Pendiente: el oído del humano; probar cada WAV como referencia de Qwen3 (modo ICL) y medir con `distincion.py` si el acento pasa a las frases generadas.

---

## 2) Tabla comparativa

### 2.1 Candidatas (tramo principal de cada una)

| Orden | Id de la muestra | Lectora (LibriVox) | Libro (autor) | Tramo en el MP3 original | Dur. | Δ(s−θ), 4 min | F0 mediana | Suelo de ruido (SNR aprox.) | Palabras con /θ/ en el tramo | Material de la lectora en LibriVox |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `es-f-juanina` | juanina (lectora 19250) | «La gente cursi» (Ramón Ortega y Frías), cap. IV | 03:52,37 – 04:01,25 | 8,88 s | **14,0 dB** (n_θ = 23, p = 9e-11) | 186 Hz | −69 dB (46 dB) | 3 (haciendo, esfuerzo, entrecejo) | 21 proyectos, 163 secciones |
| 2 | `es-f-mongope` | Mongope (lectora 10246) | «Abel Sánchez» (Miguel de Unamuno), cap. II | 02:14,28 – 02:21,93 | 7,65 s | **11,6 dB** (n_θ = 21, p = 3e-5) | 177 Hz | −95 dB (puerta de ruido: silencio digital) | 0 | 70 proyectos, 1 593 secciones |
| 3 | `es-f-lu` | Lu (lectora 18022, foro «LUbook») | «El tesoro de Gastón» (Emilia Pardo Bazán), sección 02 | 03:51,83 – 03:59,95 | 8,12 s | **12,8 dB** (n_θ = 13, p = 4e-8) | 185 Hz | −60 dB (37 dB) | 2 (precedió, alzó) | 48 proyectos, 492 secciones |
| 4 | `es-f-martin` | Marian Martin (lectora 3290) | «Relatos y cuentos Vol. 001»: «Los buques suicidantes» (Horacio Quiroga) | 01:57,61 – 02:05,71 | 8,10 s | **11,1 dB** (n_θ = 10, p = 1e-6) | 200 Hz | −60 dB (41 dB) | 0 | 27 proyectos, 95 secciones |

Alternativas ya recortadas y verificadas (misma lectora y mismo MP3): `es-f-mongope-b` (02:47,01 – 02:54,88; 7,87 s), `es-f-lu-b` (02:46,61 – 02:55,05; 8,44 s), `es-f-martin-b` (02:36,43 – 02:43,09; 6,66 s). Ver §3.

### 2.2 Evidencia de acento: todas las mediciones (Δ(s−θ) en dB; entre paréntesis, n de palabras con /θ/)

| Lectora | Medidas | Lectura |
|---|---|---|
| juanina | «La gente cursi» cap. IV: 14,0 (23) con 4 min y 15,0 (5) con 75 s; cap. IX: 15,2 (5); cap. X: 10,9 (7); cap. XII: 15,3 (3); cap. XIV: 12,9 (2) | Distinción en 5 capítulos, uniforme (11 a 15 dB). |
| Mongope | «Abel Sánchez» cap. II: 12,6 (10) con 150 s y 11,6 (21) con 4 min; «Cañas y barro»: 10,7 (16); spike S1, «Abel Sánchez» cap. III: 12,4 (26) | Distinción muy consistente entre 3 libros y 2 mediciones independientes. |
| Lu | «Tiempos difíciles»: 10,2 (10); «El tesoro de Gastón»: 15,7 (5) con 150 s y 12,8 (13) con 4 min; «Entre naranjos»: 4,0 (7); «Doña Berta»: 6,8 (11) | Positivo y significativo (p < 0,02) en las 5 lecturas, pero con magnitud variable (4 a 16 dB). |
| Marian Martin | «Los buques suicidantes»: 11,3 (5) con 150 s y 11,1 (10) con 4 min; «Adiós, Cordera»: 11,8 (2) con 48 s; «El don Juan»: 18,5 (4) con 48 s | Distinción en 3 relatos; los tramos de 48 s tienen muy pocas palabras. |

Las mediciones de 75 s o menos tienen pocas palabras con /θ/ (2 a 7): sirven de cribado, no de prueba.

### 2.3 Lectoras evaluadas y descartadas

| Lectora (libro medido) | F0 | Δ(s−θ) (n_θ) | Motivo |
|---|---|---|---|
| Karen Savage («Novelas cortas», Alarcón) | 219 Hz | −0,1 (14) | Sin distinción (seseo) |
| Claudia Caldi («La frailocracia filipina») | 163 Hz | −0,1 (15) | Sin distinción |
| mariemdover («La Cautiva», Echeverría) | 170 Hz | −0,2 (13) | Sin distinción |
| Joyfull (Biblia Reina-Valera, «Job») | 188 Hz | 0,5 (11) | Sin distinción |
| Consuelo Aponte («En la diestra de Dios Padre», Carrasquilla) | 167 Hz | 1,4 (11) | Sin distinción |
| Maritza Mateo («El Peregrino») | 198 Hz | 2,5 (13; p = 0,03) | Distinción débil o nula |
| KendalRigans («Rimas de dentro», Unamuno) | 200-225 Hz | 2,4 (15; p = 0,04) | Distinción débil o nula |
| Meribau («Doña Perfecta», Galdós) | 150 Hz (p10 129) | **25,1** (8) | Distingue, pero la F0 apunta a voz masculina (sin verificar); descartada por el criterio de género |
| Epachuko, Víctor Villarraza, Alexelmagno, Carlos Lombardi, mpinedag, Mario Pineda, FiccionNarrada, Ditirambo | 103-137 Hz | no medido | Voces de registro masculino |

Pista sin cerrar: en «Cuentos festivos para niños menores de 50 años» (Juan Pérez Zúñiga, LibriVox, lectores varios) las secciones 04 y 05 tienen F0 de 222 y 228 Hz y Δ de 18,2 (n_θ = 9) y 11,3 (n_θ = 7). No se pudo identificar a la lectora (la ficha del proyecto en LibriVox devolvió error 525) y tampoco encontré su texto en Project Gutenberg (la búsqueda por título y autor no lo devuelve), así que no se siguió.

---

## 3) Detalle por opción

Comunes a todas: MP3 original de archive.org (VBR, 44,1 kHz, 105-128 kb/s medios, estéreo o mono según el item) descargado el 2026-10-01 (el tamaño coincide con el declarado por la API de metadatos de archive.org). La decodificación con ffmpeg y con libsndfile (la de `prepare_reference.py`) da el mismo instante (desfase medido 0,000 s), así que los tiempos valen para ambas rutas. Cada recorte incluye de 0,15 a 0,3 s de silencio a cada lado (centrado en la pausa), con ganancia a RMS −20 dBFS (pico ≤ −1 dBFS) y fundidos de 30 ms, igual que `prepare_reference.normalizar`. Comprobado en los 7 WAV: la energía de los primeros y últimos 80 ms queda al menos 37 dB por debajo de la del habla (0,19 a 0,37 s de silencio antes y después), así que no hay restos de palabras en los extremos.

### 3.1 `es-f-juanina` · juanina · «La gente cursi», cap. IV «Turbaciones»

- **Libro:** «La gente cursi: novela de costumbres ridículas», de Ramón Ortega y Frías. LibriVox: https://librivox.org/la-gente-cursi-novela-de-costumbres-ridiculas-by-ramon-ortega-y-frias/ (22 secciones, varios lectores; el cap. IV, 19:43, es de juanina).
- **Lectora:** juanina, https://librivox.org/reader/19250 (nombre en el foro «juanina»; 21 proyectos, 163 secciones). **Procedencia: no consta** (ficha sin biografía ni ubicación).
- **Item de Internet Archive:** https://archive.org/details/lagentecursinoveladecostumbresridiculas_2403_librivox (publicado 2024-03-08; sin `licenseurl`: se apoya en la declaración general de LibriVox, §6).
- **MP3:** https://archive.org/download/lagentecursinoveladecostumbresridiculas_2403_librivox/gentecursi_04_ortegayfrias.mp3 · 17 026 668 bytes · sha256 `dd3b2f6072e0477f1884c2c9b9f1a57681cd5253fbd27e0698e05ad9f1ff81f7` · VBR 115 kb/s, 19:43.
- **Tramo:** 03:52,37 – 04:01,25 (8,88 s). Dos oraciones narrativas, pausa interna de 0,85 s entre ellas (es el cambio de párrafo del libro); pausas de 1,12 s antes y 0,82 s después.
- **Transcripción exacta (para `ref_text`):** «Paquita bajó los ojos, y haciendo un esfuerzo consiguió ponerse colorada como un tomate. La madre arrugó el entrecejo.»
- **Fuente del texto:** Project Gutenberg #47768, líneas 1714-1717 (ortografía actual en este pasaje). Verificación: re-transcripción del recorte final (faster-whisper large-v3-turbo, beam 5) idéntica al texto, sin diferencias en palabras (se compara sin tildes ni puntuación).
- **Acento:** Δ(s−θ) = 14,0 dB con 4 min (n_θ = 23, n_s = 40, p = 9e-11) y 10,9 a 15,3 dB en otros 4 capítulos (§2.2). La más uniforme y la de mayor n.
- **Voz y audio:** F0 mediana 186 Hz (p10 152, p90 276 en el tramo). En otras secciones del libro la F0 baja a 155-168 Hz al leer personajes masculinos; el tramo elegido es solo narración. Suelo de ruido −69 dB, pico −7,2 dBFS antes de normalizar (la ganancia quedó limitada por el pico: RMS final −21,8 dBFS). Sin música.
- **Muestra:** `C:\Users\Usuario\AppData\Local\InstantTraductor\spikes\voces-candidatas\es-f-juanina.wav` · 426 560 bytes · sha256 `a97b1a95ca838b59ea8ca93f362cdf6197184b633c7d327c089fbd3d3bce9512`.
- **Contras:** las 5 mediciones de acento son del mismo libro; el tramo une dos oraciones con una pausa larga de 0,85 s.

### 3.2 `es-f-mongope` · Mongope · «Abel Sánchez», cap. II

- **Libro:** «Abel Sánchez», de Miguel de Unamuno (1917). LibriVox: https://librivox.org/abel-sanchez-by-miguel-de-unamuno/ (38 capítulos, todos de Mongope, 3:45:00; fuente de texto de LibriVox: Biblioteca Digital Hispánica, https://bdh-rd.bne.es/viewer.vm?id=0000200724&page=1).
- **Lectora:** Mongope, https://librivox.org/reader/10246 (foro «mongope»; 70 proyectos, 1 593 secciones). **Procedencia: no consta.** Su catálogo mezcla literatura española (Unamuno, Valle-Inclán, Pardo Bazán, Galdós, Blasco Ibáñez) y traducciones de clásicos; no es prueba de origen.
- **Item de Internet Archive:** https://archive.org/details/abelsanchez_1904_librivox (publicado 2019-04-29; licencia declarada en el item: Public Domain Mark 1.0).
- **MP3:** https://archive.org/download/abelsanchez_1904_librivox/abelsanchez_02_unamuno.mp3 · 5 670 242 bytes · sha256 `0a470cf55df8cf3e7ab14122a9dd59796a14732996496db537527a16731a8658` · VBR 105 kb/s, 07:09.
- **Tramo:** 02:14,28 – 02:21,93 (7,65 s). Una oración narrativa con una pausa interna de 0,55 s; pausas de 0,70 s antes y 1,16 s después.
- **Transcripción exacta:** «Helena se posaba en su asiento solemne y fría, henchida de desdén, como una diosa llevada por el destino.»
- **Fuente del texto:** Project Gutenberg #44512, líneas 371-373. Verificación: re-transcripción idéntica (el ASR de la pasada larga escribía «Elena»; es la misma pronunciación y el tramo final sí sale «Helena»).
- **Acento:** Δ(s−θ) = 11,6 dB con 4 min (n_θ = 21, p = 3e-5); 12,6 (cap. II, 150 s), 10,7 («Cañas y barro») y 12,4 (spike S1, cap. III, 26 palabras). Es la más consistente entre libros.
- **Voz y audio:** F0 mediana 177 Hz (p10 158, p90 240). **Suelo de ruido −95 dB:** las pausas son silencio digital (puerta de ruido); pico −10 dBFS. Lectura pausada: pausas de 0,5 a 1,6 s entre oraciones, aunque la articulación es la más rápida de las cuatro (3,3 palabras/s de habla activa; Lu 2,8, juanina 2,8, Marian Martin 2,5). El tramo no contiene palabras con /θ/.
- **Muestra:** `...\voces-candidatas\es-f-mongope.wav` · 367 440 bytes · sha256 `2c2b1928fa9e26b25356fae06de43efeed48c8f5f420ded46162343c8ab46824`.
- **Alternativa `es-f-mongope-b`:** 02:47,01 – 02:54,88 (7,87 s): «Ellos no lo sabían. Porque uno y otro no hacían sino devorarla con los ojos; la veían, no la oían hablar.» (Gutenberg #44512, líneas 377-379; 1 palabra con /θ/: «hacían»; sha256 `2650141b366e158d7980a0717f52f631532a58efb22688d28e9d6c8d91be7a30`). Verificada sin diferencias.
- **Contras:** el silencio digital y las pausas largas podrían contagiarse a la voz clonada (ritmo lento, huecos); sin /θ/ en el tramo principal.

### 3.3 `es-f-lu` · Lu · «El tesoro de Gastón», sección 02

- **Libro:** «El tesoro de Gastón», de Emilia Pardo Bazán (novela corta, 4:12:37). LibriVox: https://librivox.org/el-tesoro-de-gaston-by-emilia-pardo-bazan/ (fuente de texto de LibriVox: Project Gutenberg #54791).
- **Lectora:** Lu, https://librivox.org/reader/18022 (foro «LUbook»; 48 proyectos, 492 secciones). **Procedencia: no consta.** Nota: la descripción del item en Internet Archive dice «lu88»; la ficha del catálogo de LibriVox atribuye las secciones a «Lu» (18022). Se toma la de LibriVox.
- **Item de Internet Archive:** https://archive.org/details/eltesorodegaston_2303_librivox (publicado 2023-03-31; sin `licenseurl`: se apoya en la declaración general de LibriVox, §6).
- **MP3:** https://archive.org/download/eltesorodegaston_2303_librivox/tesorodegaston_02_pardobazan.mp3 · 14 730 727 bytes · sha256 `0c3bd81184b555dba3370c33d26112250021203c10a0cc6c3c6cd2e51e6773e5` · VBR 112 kb/s, 17:27.
- **Tramo:** 03:51,83 – 03:59,95 (8,12 s). Empieza tras la coma de «Lentamente, deslizándose como una sombra,» (media oración); pausa interna máxima 0,44 s.
- **Transcripción exacta (libro):** «precedió á Gastón por dos ó tres pasillos y antesalas, hasta llegar á una carcomida puerta cuyo picaporte alzó.» El libro usa la ortografía de 1897 («á», «ó» con tilde). **Para `ref_text`, ortografía actual** (se pronuncia igual): «precedió a Gastón por dos o tres pasillos y antesalas, hasta llegar a una carcomida puerta cuyo picaporte alzó.»
- **Fuente del texto:** Project Gutenberg #54791, líneas 455-457. Verificación: re-transcripción idéntica («precedió a Gastón por dos o tres pasillos y antesalas hasta llegar a una carcomida puerta cuyo picaporte alzó»).
- **Acento:** Δ(s−θ) = 12,8 dB con 4 min (n_θ = 13, p = 4e-8) y 15,7 con 150 s; en «Entre naranjos» 4,0 y en «Doña Berta» 6,8 (positivas, p < 0,02). Dos palabras con /θ/ en el tramo (precedió, alzó).
- **Voz y audio:** F0 mediana 185 Hz (p10 157, p90 227). Suelo de ruido −60 dB (ruido de sala normal), pico −10,9 dBFS. Sin música.
- **Muestra:** `...\voces-candidatas\es-f-lu.wav` · 390 016 bytes · sha256 `b25a3a1b74548b41670ae74b187944a5dc50897afd00968cb57e6aaa88a1f6fd`.
- **Alternativa `es-f-lu-b`:** 02:46,61 – 02:55,05 (8,44 s): «abrióse la puerta lateral, gruesa hoja de encina, y apareció en el hueco, inmóvil y muda, la Comendadora,» (Gutenberg #54791, líneas 438-440; 2 palabras con /θ/; empieza y acaba a media oración; sha256 `d511c9a9dc14b5b500e09383410eb5276650d2bf4495ceccc923bb5b2f2c92f1`). Verificada sin diferencias.
- **Contras:** magnitud de la distinción variable entre libros; el tramo principal empieza a media oración.

### 3.4 `es-f-martin` · Marian Martin · «Los buques suicidantes» (Quiroga)

- **Libro:** «Relatos y cuentos Vol. 001» (10 relatos, 2:30:38), lectora única. El relato 02, «Los buques suicidantes», es de Horacio Quiroga. LibriVox: https://librivox.org/relatos-y-cuentos-vol-001/ (fuente de texto de LibriVox para este relato: http://lieber.com.ar/quiroga/losbuquessuicidantes.html).
- **Lectora:** Marian Martin, https://librivox.org/reader/3290 (27 proyectos, 95 secciones). **Procedencia: no consta.** El propio audio dice «Leído por Marian Martín».
- **Item de Internet Archive:** https://archive.org/details/relatosycuentos_1003_librivox (publicado 2010-03-24; `licenseurl`: http://creativecommons.org/licenses/publicdomain/).
- **MP3:** https://archive.org/download/relatosycuentos_1003_librivox/ryc01_02_losbuques_quiroga.mp3 · 8 509 568 bytes · sha256 `263771cbd075de09e27e53c6d76c33ce7521853332bcb6062c1ae573875c5cbf` · MP3 mono 128 kb/s, 08:51.
- **Tramo:** 01:57,61 – 02:05,71 (8,10 s). Una oración narrativa completa; pausas de 0,91 s antes y 0,92 s después; pausa interna máxima 0,39 s.
- **Transcripción exacta:** «Cuatro horas más tarde, un paquete, no teniendo respuesta, desprendió una chalupa que abordó al María Margarita.» (en el libro el nombre del buque va en cursiva: `_María Margarita_`).
- **Fuente del texto:** Project Gutenberg #13507 («Cuentos de amor de locura y de muerte», Quiroga), líneas 2635-2637. Verificación: re-transcripción idéntica.
- **Acento:** Δ(s−θ) = 11,1 dB con 4 min (n_θ = 10, p = 1e-6); 11,3 con 150 s; y 11,8 y 18,5 en dos relatos más de 48 s (2 y 4 palabras). El origen de la lectora sigue sin constar (el autor de este relato es uruguayo; el resto del volumen es sobre todo español).
- **Voz y audio:** F0 mediana 200 Hz (p10 178, p90 238), la más aguda de las 4. Suelo de ruido −60 dB, pico −7,0 dBFS. Grabación de 2010. El tramo no contiene palabras con /θ/.
- **Muestra:** `...\voces-candidatas\es-f-martin.wav` · 389 002 bytes · sha256 `1058b3c80b43bd6bafe2a3205a0ca11fac75afd7482ff74eca1606f5df26b2d4`.
- **Alternativa `es-f-martin-b`:** 02:36,43 – 02:43,09 (6,66 s, en el límite inferior): «Ibamos a Europa, y el capitán nos contaba su historia marina, perfectamente cierta, por otro lado.» (Gutenberg #13507, líneas 2643-2645; 1 palabra con /θ/: «cierta»; el libro imprime «Ibamos» sin tilde; sha256 `7639c710ba44fe5989024f5e2c85db19935b8b9de4433b22c714868e992bdc32`). Verificada sin diferencias.
- **Contras:** grabación más antigua, el menor volumen de material, tramo sin /θ/.

### 3.5 Entrada lista para `spikes/voz/referencia.json` (mismo formato que la referencia actual)

Solo se rellenaría con la elegida; las demás se regeneran con `uv run python prepare_reference.py referencia` cambiando estos campos. Ejemplo con la primera:

```json
{
  "ia_id": "lagentecursinoveladecostumbresridiculas_2403_librivox",
  "fichero": "gentecursi_04_ortegayfrias.mp3",
  "inicio_s": 232.37,
  "fin_s": 241.25,
  "origen": "LibriVox (dominio público): «La gente cursi», de Ramón Ortega y Frías, capítulo IV, leído por juanina",
  "url_item": "https://archive.org/details/lagentecursinoveladecostumbresridiculas_2403_librivox",
  "url_audio": "https://archive.org/download/lagentecursinoveladecostumbresridiculas_2403_librivox/gentecursi_04_ortegayfrias.mp3",
  "lector": "juanina (voluntaria de LibriVox, lectora 19250; sexo y procedencia sin verificar)",
  "minuto": "03:52,37 a 04:01,25 del fichero gentecursi_04_ortegayfrias.mp3",
  "licencia": "Dominio público (declaración general de LibriVox; texto de la edición de Madrid, 1872, en Project Gutenberg)",
  "texto": "Paquita bajó los ojos, y haciendo un esfuerzo consiguió ponerse colorada como un tomate. La madre arrugó el entrecejo.",
  "fuente_texto": "Project Gutenberg #47768, líneas 1714-1717, contrastado con la re-transcripción del propio recorte"
}
```

Los otros tres: `ia_id`/`fichero`/`inicio_s`/`fin_s` = `abelsanchez_1904_librivox` / `abelsanchez_02_unamuno.mp3` / 134.28 / 141.93; `eltesorodegaston_2303_librivox` / `tesorodegaston_02_pardobazan.mp3` / 231.83 / 239.95; `relatosycuentos_1003_librivox` / `ryc01_02_losbuques_quiroga.mp3` / 117.61 / 125.71 (textos en 3.2 a 3.4).

---

## 4) Recomendación para InstantTraductor

**Orden de preferencia** (criterios medibles; el desempate real es el oído del humano):

1. **`es-f-juanina` (principal).** Es la que más pesa en lo que importa a la spec: distinción /θ/-/s/ medida en 5 capítulos (11 a 15 dB, el mayor n de todas), audio con ruido de sala normal (−69 dB, sin puerta de ruido), un tramo de 8,9 s con 3 palabras con /θ/ (útil porque el acento de la referencia se contagia a todo lo que dice el clon) y texto actual sin arcaísmos. Contras: una pausa interna de 0,85 s y procedencia desconocida.
2. **`es-f-mongope` (alternativa fuerte).** La evidencia de acento más consistente entre libros y entre mediciones independientes (la del spike incluida), y la lectora con más material (1 593 secciones) si luego se quiere otra referencia o más duración. Contras: puerta de ruido (silencio digital) y ritmo pausado; el tramo principal no tiene /θ/ (la alternativa `-b` tiene 1).
3. **`es-f-lu`.** Audio y tramo buenos (2 palabras con /θ/), pero la magnitud de su distinción varía de 4 a 16 dB según el libro, y el tramo empieza a media oración con ortografía de 1897 que hay que modernizar en el `ref_text`.
4. **`es-f-martin`.** Distinción clara, pero grabación de 2010, menos material y tramo sin /θ/; queda como cuarta opción por si al oído es la preferida (es la voz más aguda).

**Cómo decidir:** que el humano escuche los 4 WAV principales (y los `-b`), elija por timbre y naturalidad y, si hace falta, se prueba cada uno como referencia en modo ICL y x-vector de Qwen3 midiendo el acento de las muestras generadas con `distincion.py` (comprobación que aquí no se hizo).

---

## 5) Riesgos y preguntas abiertas

- **Nada de esto está escuchado.** «Femenina» (F0), «de España» (Δ /θ/-/s/), «limpio» (suelo de ruido y SNR) y «natural» (pausas y ritmo) son medidas indirectas.
- **Procedencia sin documentar.** Ninguna ficha de lectora de LibriVox (10246, 18022, 3290, 19250) tiene biografía ni ubicación. Como dice el propio `distincion.py`, hay hablantes peninsulares sin distinción y al revés; es un indicio.
- **Voz humana sin verificar.** Según mi conocimiento (sin verificar en esta sesión), LibriVox no admite voz sintética, pero no lo he podido comprobar de oído; Lu y Mongope tienen catálogos muy grandes. Mongope tiene silencio digital entre frases (típico de una puerta de ruido, también de audio procesado).
- **Verificación del texto.** Es una re-transcripción con faster-whisper large-v3-turbo (int8, CPU) contra Gutenberg, comparando sin tildes ni puntuación: confirma las palabras, pero no distingue homófonos ni signos. Los Δ del informe se midieron con ese ASR y no con Whisper-small (el del spike): no son estrictamente comparables, aunque el de Mongope coincide (11,6 a 12,6 frente a 12,4).
- **Muestras pequeñas** en el cribado (2 a 7 palabras con /θ/ por clip de 48 a 75 s). Solo las 4 principales tienen 4 min (n_θ de 10 a 23). Los tramos se buscaron solo en los primeros 4 min de una sección por lectora: hay mucho más material por explorar.
- **Una voz clonada es una voz de una persona real.** LibriVox declara públicas las grabaciones (cita en §6), pero eso no resuelve cuestiones de derechos sobre la voz si el uso cambiara; para uso personal local el riesgo es bajo (valoración mía, **sin verificar jurídicamente**). Conviene anotar la lectora en el ADR de la voz.
- **Disponibilidad:** librivox.org dio errores intermitentes (522 y 525) durante la sesión; los datos de sus fichas salen de `WebFetch` y los audios, de archive.org (estable).
- **Preguntas para el humano:** ¿timbre grave o agudo? ¿le molesta el ritmo pausado de Mongope? ¿hace falta que el tramo incluya /θ/ (en `-b`) o prefiere el tramo más natural?
- **Pendiente técnico:** (a) comprobar de oído; (b) medir con `distincion.py` las frases generadas con cada referencia; (c) revisar si Lu o juanina tienen libros con locución más continua si hace falta una referencia más larga; (d) cerrar la pista de «Cuentos festivos» (F0 222-228 Hz, Δ 11-18 dB) si el humano quiere una voz más aguda.

---

## 6) Fuentes (consultadas el 2026-10-01)

**LibriVox (fichas, `WebFetch`)**
- https://librivox.org/abel-sanchez-by-miguel-de-unamuno/ — lectora Mongope (ID 10246), 38 capítulos, 03:45:00, fuente de texto BNE.
- https://librivox.org/reader/10246 — Mongope: 70 proyectos, 1 593 secciones; sin biografía ni procedencia.
- https://librivox.org/el-tesoro-de-gaston-by-emilia-pardo-bazan/ — lectora Lu (ID 18022); fuente de texto: https://www.gutenberg.org/ebooks/54791.
- https://librivox.org/reader/18022 — Lu (foro «LUbook»): 48 proyectos, 492 secciones; sin biografía.
- https://librivox.org/entre-naranjos-by-vicente-blasco-ibanez/ — Lu (ID 18022).
- https://librivox.org/la-gente-cursi-novela-de-costumbres-ridiculas-by-ramon-ortega-y-frias/ — secciones y lectores (cap. IV: juanina, ID 19250).
- https://librivox.org/reader/19250 — juanina: 21 proyectos, 163 secciones; sin biografía.
- https://librivox.org/relatos-y-cuentos-vol-001/ — lectora Marian Martin (ID 3290), 10 relatos y sus fuentes de texto.
- https://librivox.org/reader/3290 — Marian Martin: 27 proyectos, 95 secciones; sin biografía.
- https://librivox.org/pages/public-domain/ — «all our recordings are public domain (definitely in the USA, and maybe in your country as well)» y «LibriVox records only texts that are in the public domain (in the USA)».

**Internet Archive (API de metadatos y descargas)**
- https://archive.org/advancedsearch.php (colección `librivoxaudio`, idioma español: 560 items en la consulta del 2026-10-01).
- https://archive.org/metadata/abelsanchez_1904_librivox · …/eltesorodegaston_2303_librivox · …/relatosycuentos_1003_librivox · …/lagentecursinoveladecostumbresridiculas_2403_librivox (tamaños, formatos, licencia, fechas).
- MP3 descargados: ver las URL de §3.1 a §3.4 (sha256 calculados al descargar).

**Project Gutenberg**
- #44512 «Abel Sánchez» (https://www.gutenberg.org/ebooks/44512), #54791 «El tesoro de Gastón» (…/54791), #13507 «Cuentos de amor de locura y de muerte» (…/13507), #47768 «La gente cursi» (…/47768). Texto plano: `https://www.gutenberg.org/cache/epub/<id>/pg<id>.txt`.

**Interno**
- `spikes/voz/README.md` (referencia actual: Tux, «Trafalgar», controles de /θ/-/s/), `spikes/voz/common/distincion.py`, `spikes/voz/prepare_reference.py`, `spikes/voz/referencia.json`.
- Modelo usado para transcribir y verificar: `faster-whisper-large-v3-turbo` (CTranslate2, MIT; ya en `%LOCALAPPDATA%\InstantTraductor\models`), con faster-whisper 1.2.1 y ctranslate2 4.8.2, en CPU.

---

## Anexo: método y reproducción

1. **Catálogo:** consulta a la API de búsqueda de archive.org (colección `librivoxaudio`, español): 560 items. El campo «Read by» de la descripción da el lector principal de cada item. Se cribaron unos 35 items (una sección de cada uno) y 56 secciones de 4 proyectos con varios lectores.
2. **Cribado de género (F0):** para cada lectora, ~1 MB del MP3 de 64 kb/s (petición `Range`), decodificado con ffmpeg y F0 mediana por autocorrelación. Tux da 124 Hz con este método (el spike midió ~122 Hz con otro).
3. **Cribado de acento:** 75 a 150 s de lectura transcritos con tiempos por palabra (faster-whisper large-v3-turbo, int8, CPU; mismo formato JSON que `transcribir_varios.py`) y `distincion.py` (entorno uv creado con `uv sync --frozen` del proyecto `spikes/voz` en una carpeta fuera del repo, para no tocarlo). Finalistas: 4 min (de 5 s a 245 s del MP3 original).
4. **Elección del tramo:** alineación de las palabras del ASR con el texto de Gutenberg (`difflib`, con localización por 4-gramas y h muda ignorada) y búsqueda de ventanas de 6,5 a 9,8 s limitadas por pausas reales (≥ 0,12 s de energía baja medida en el audio, no con los tiempos del ASR, que estiran las palabras sobre el silencio), con todas las palabras emparejadas de forma contigua, sin diálogos con raya y con puntuación al final; se prefirieron ventanas sin pausas internas largas y con palabras con /θ/.
5. **Corte y verificación:** ffmpeg (`-ss`, `-t`, mono, 24 kHz, `volume` y `afade`); re-transcripción del WAV final (beam 5) y comparación palabra a palabra con el libro; F0, niveles y pausas del propio tramo.
6. Los scripts de trabajo están en una carpeta temporal fuera del repo y **no** se han añadido al proyecto. Si el orquestador quiere conservar la herramienta de selección de tramos, puede convertirse en `spikes/voz/common/elegir_tramo.py`.
