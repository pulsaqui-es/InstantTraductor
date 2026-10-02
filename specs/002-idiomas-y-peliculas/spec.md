# Feature Specification: Idiomas elegidos a mano y robustez en películas

**Feature Branch**: `002-idiomas-y-peliculas`

**Created**: 2026-10-02

**Status**: Approved (H1, orquestador por delegación ADR-0009; alcance decidido por el humano, 2026-10-02)

**Input**: User description: "Segunda versión del intérprete, centrada en lo que la persona usuaria encontró al usarlo con películas y series. Incluye:
(1) idioma de origen elegido a mano entre inglés, japonés, chino (mandarín) y coreano, sin detección automática;
(2) escuchar solo la aplicación elegida, para que Discord, llamadas u otras voces no se cuelen;
(3) que se traduzca el habla baja, susurrada o con palabras alargadas;
(4) español de España con «vosotros»;
(5) casi ninguna frase inventada durante música, canciones o efectos;
(6) completar las validaciones pendientes de la 001: 30 min sin eco, 60 min de estabilidad, cambio de dispositivo y sin red.
Objetivos:
- retardo p50 ≤ 3 s y p95 ≤ 5 s en los cuatro idiomas;
- cero frases de Discord traducidas con la app elegida;
- ≥ 80 % del diálogo bajo o susurrado traducido;
- ≥ 95 % de plurales informales con «vosotros».
Fuera de alcance: detección automática del idioma (004), clonación (003), interfaz gráfica (005) y traducir mientras se juega en el mismo PC. Restricciones: 100 % local sin costes, uso personal, Windows 11 y RTX 5070 con la VRAM casi llena."

## Clarifications

### Session 2026-10-02

- Q: ¿Cómo se elige la aplicación que se escucha? → A: Con una lista al arrancar. Si no hay ninguna guardada, o se pide expresamente, la terminal muestra numeradas las aplicaciones que están sonando y se elige con un número. La elección se recuerda. También se puede indicar por nombre al arrancar.
- Q: Si la aplicación elegida no está abierta o no suena al arrancar, ¿qué hace la app? → A: Espera a que suene, avisándolo en la terminal, y empieza a traducir en cuanto suena. Nunca escucha otra cosa mientras tanto.
- Q: ¿Qué tratamiento se usa por defecto al hablar a varias personas sin pista de formalidad? → A: Informal: «vosotros». «Ustedes» solo si el contexto es claramente formal.
- Q: ¿Se ven películas compartidas por Discord (emisión en directo) mientras se habla en la llamada? → A: Sí, es habitual. La película y las voces de la llamada llegan por el mismo programa, así que elegir la aplicación no basta.
- Q: ¿Cómo se construye el corpus de habla baja? → A: Con material sintético (voces bajadas de volumen y susurradas sobre música libre). La persona usuaria no grabará escenas.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Escuchar solo la película (Priority: P1)

La persona usuaria ve una película en el navegador mientras sus amigos hablan en Discord. Al arrancar el modo directo elige la aplicación que reproduce la película; la app le enseña las que están sonando en ese momento. Desde entonces solo se traduce lo que suena en esa aplicación: Discord, las llamadas, las notificaciones y cualquier otro programa quedan fuera. La próxima vez, la app recuerda la elección.

**Why this priority**: es el problema que más estropea la experiencia hoy. Con voces en español de fondo, la traducción se «lía» y deja de ser útil. Arreglarlo hace utilizable la app en el día a día.

**Independent Test**: reproducir una película en inglés en el navegador y, a la vez, una conversación en Discord o un audio de voz en otro programa, durante 10 minutos con el modo directo escuchando solo el navegador. Solo aparecen traducidas frases de la película.

**Acceptance Scenarios**:

1. **Given** varias aplicaciones sonando, **When** la persona usuaria pide elegir la aplicación, **Then** ve la lista de las que están sonando, con un nombre reconocible, y puede elegir una.
2. **Given** una aplicación elegida, **When** suena voz en otra aplicación (Discord, una llamada, un vídeo en otro programa), **Then** esa voz no se traduce.
3. **Given** una aplicación elegida en una sesión anterior, **When** se arranca el modo directo sin indicar ninguna, **Then** se usa la misma aplicación, si está abierta.
4. **Given** el modo directo escuchando una aplicación, **When** esa aplicación se cierra o se reinicia, **Then** la app lo avisa en la terminal y vuelve a escucharla en cuanto reaparece, sin reiniciarse.
5. **Given** una aplicación elegida, **When** suena la voz en español de la propia app, **Then** nunca se capta ni se traduce.
6. **Given** una película compartida por Discord mientras los amigos hablan en español en la llamada, **When** se escucha Discord con el inglés (u otro idioma de origen) elegido, **Then** se traduce la película y ninguna frase de la conversación en español.
7. **Given** que la persona usuaria prefiere el comportamiento anterior, **When** elige escuchar todo el PC, **Then** la app capta todo menos su propia voz, como en la versión 0.1.

---

### User Story 2 - Series en japonés, chino y coreano (Priority: P2)

La persona usuaria va a ver un anime en japonés, un drama coreano o una película china. Elige el idioma de origen al arrancar, o lo deja guardado, y oye la traducción al español de España igual que con el inglés. Con un idioma elegido, el habla en otros idiomas se ignora: no se intenta entender como si fuera el idioma elegido.

**Why this priority**: amplía el producto a los otros idiomas que la persona usuaria ve. Elegirlo a mano es más rápido y gasta menos recursos que detectarlo.

**Independent Test**: con el idioma correspondiente elegido, reproducir 10 minutos de diálogo en japonés, en chino y en coreano. Cada frase se oye en español dentro del retardo objetivo y con sentido fiel.

**Acceptance Scenarios**:

1. **Given** el japonés, el chino o el coreano elegido, **When** suena diálogo en ese idioma, **Then** se oye traducido al español de España, en orden y dentro del retardo objetivo.
2. **Given** un idioma elegido, **When** se arranca una sesión indicando otro idioma solo para esa sesión, **Then** se usa el indicado y el ajuste guardado no cambia.
3. **Given** el inglés elegido, **When** suena una conversación en español u otro idioma, **Then** no se pronuncia ninguna traducción inventada a partir de ella.
4. **Given** el modo archivo, **When** se indica el idioma de origen del fichero, **Then** se traduce desde ese idioma con las mismas salidas que en la versión 0.1.
5. **Given** el modo directo en marcha, **When** la persona usuaria mira la terminal, **Then** ve el idioma de origen activo y la aplicación que se escucha.

---

### User Story 3 - No perderse nada y oír español de España (Priority: P3)

En las películas hay diálogos susurrados, frases dichas muy bajo o con palabras alargadas, y tramos largos de música o efectos. La persona usuaria espera que lo hablado bajo también se traduzca, que la música y los efectos no produzcan frases inventadas y que el español sea de España: «¿Estáis listos?» y no «¿Están listos?».

**Why this priority**: mejora la calidad percibida de todo lo anterior. No bloquea el uso, pero es lo que distingue una traducción buena de una que cansa.

**Independent Test**: pasar por el modo archivo dos corpus de prueba. El de diálogo bajo, susurrado o alargado debe traducirse en al menos el 80 % de sus frases. El de plurales informales debe dar «vosotros» en al menos el 95 %. Además, 10 minutos de música y efectos sin diálogo apenas deben producir frases.

**Acceptance Scenarios**:

1. **Given** una frase dicha en voz baja o susurrada, **When** suena en la película, **Then** se traduce como cualquier otra.
2. **Given** una frase con palabras alargadas o pausas dentro de la palabra, **When** termina, **Then** se traduce entera, sin perderse ni partirse en trozos sin sentido.
3. **Given** un diálogo dirigido a varias personas en tono informal, **When** se traduce, **Then** usa «vosotros» y sus formas verbales, salvo que el contexto sea claramente formal.
4. **Given** un tramo de música, canción o efectos sin diálogo, **When** suena, **Then** la app no pronuncia frases inventadas.

---

### User Story 4 - Sesiones largas sin sorpresas (Priority: P4)

La persona usuaria ve una película entera. La app aguanta la sesión completa sin cortes ni bloqueos, sin oírse a sí misma, sigue funcionando si cambia los auriculares por los altavoces y no necesita internet.

**Why this priority**: completa la validación de la versión 0.1, que quedó pendiente por falta de tiempo de prueba. Son comprobaciones, no funciones nuevas.

**Independent Test**: una sesión de 60 minutos con contenido real en la que también se cambia el dispositivo de salida, y otra arrancada sin conexión de red.

**Acceptance Scenarios**:

1. **Given** una sesión de 60 minutos, **When** termina, **Then** no ha habido cortes ni bloqueos, la propia voz no se ha captado ni una vez y el consumo de memoria es estable.
2. **Given** el modo directo en marcha, **When** se desconectan los auriculares o cambia el dispositivo de salida predeterminado, **Then** la voz en español sigue por el nuevo dispositivo y la captura continúa.
3. **Given** la preparación hecha y el PC sin red, **When** se usa el modo directo o el de archivo, **Then** funcionan igual.

---

### Edge Cases

- **La aplicación elegida no está sonando al arrancar.** La app espera a que suene y lo indica en la terminal, sin fallar y sin escuchar mientras tanto ninguna otra fuente.
- **Varias ventanas o pestañas del mismo navegador.** Se escucha todo el audio de esa aplicación: no se distingue por pestaña.
- **La persona usuaria elige la propia app de traducción** (o algo que no se puede escuchar). Se rechaza con un mensaje claro.
- **Contenido protegido que llega en silencio a la captura.** Se avisa de que no llega audio de la aplicación, como en la versión 0.1.
- **Diálogo en un idioma distinto del elegido.** Se ignora. Si eso es lo único que suena, la app no pronuncia nada.
- **Mezcla de idiomas en una misma frase** (por ejemplo, palabras inglesas sueltas en un anime). Se traduce lo que se reconoce en el idioma elegido.
- **Canciones con letra en el idioma elegido.** No se exige traducirlas; lo importante es no inventar frases cuando no hay letra.
- **Susurros bajo música alta.** Se intenta, pero la medición de habla baja se hace con música a un nivel moderado.
- **Idioma elegido cuyos componentes no están preparados.** La app pide ejecutar la preparación (código de «preparación incompleta»).

## Requirements *(mandatory)*

### Functional Requirements

**Idioma de origen**

- **FR-001**: La persona usuaria MUST poder elegir el idioma de origen entre inglés, japonés, chino (mandarín) y coreano.
- **FR-002**: El idioma elegido MUST recordarse entre sesiones, y MUST poder cambiarse solo para una sesión sin tocar el ajuste guardado.
- **FR-003**: Con un idioma elegido, la app MUST reconocer y traducir solo el habla en ese idioma, y MUST NOT pronunciar traducciones obtenidas de habla en otros idiomas. Esto vale también cuando ambas hablas llegan por la misma aplicación, como una película compartida por Discord con la llamada en español.
- **FR-004**: Los modos directo y archivo MUST admitir los cuatro idiomas con las mismas funciones que la versión 0.1: orden, control del retraso, métricas y salidas.
- **FR-005**: La app MUST NOT detectar el idioma automáticamente en esta versión: siempre usa el elegido.

**Aplicación que se escucha**

- **FR-006**: La persona usuaria MUST poder elegir escuchar una sola aplicación o todo el PC. En el segundo caso se mantiene el comportamiento de la versión 0.1.
- **FR-007**: La app MUST mostrar las aplicaciones que están sonando, numeradas y con un nombre reconocible, para elegir una con un número al arrancar. Esto ocurre cuando no hay ninguna guardada o cuando la persona usuaria lo pide. También MUST poder indicarse la aplicación por su nombre al arrancar.
- **FR-008**: La aplicación elegida MUST recordarse entre sesiones (por su nombre, no por un identificador temporal), y MUST poder cambiarse solo para una sesión.
- **FR-009**: Escuchando una aplicación, el sonido de cualquier otra MUST NOT llegar a la traducción. Si la aplicación separa la emisión de la llamada (por ejemplo, Discord), la app SHOULD escuchar solo la emisión.
- **FR-010**: Si la aplicación elegida se cierra, se reinicia o aún no está sonando (también al arrancar), la app MUST avisarlo en la terminal, MUST esperar sin escuchar ninguna otra fuente y MUST volver a escucharla en cuanto suene, sin reiniciarse ni detener la sesión.
- **FR-011**: La app MUST seguir sin captar nunca su propia voz, en cualquiera de los dos modos de escucha, y MUST comprobarlo al arrancar como en la versión 0.1.
- **FR-012**: La terminal MUST mostrar qué se está escuchando (la aplicación o todo el PC) y el idioma de origen activo.

**Calidad de lo que se traduce**

- **FR-013**: La app MUST traducir el habla en voz baja, susurrada o con palabras alargadas presente en películas y series, en lugar de perderla.
- **FR-014**: Una frase con palabras alargadas o con pausas cortas dentro MUST traducirse como una unidad con sentido, no como fragmentos sueltos sin sentido.
- **FR-015**: La traducción MUST usar «vosotros» y sus formas verbales para la segunda persona del plural informal, y «ustedes» solo cuando el tratamiento sea claramente formal.
- **FR-016**: Durante música, canciones sin letra en el idioma elegido, efectos o ruido sin diálogo, la app MUST NOT pronunciar frases inventadas.

**Validación pendiente de la versión 0.1**

- **FR-017**: La app MUST mantener todos los requisitos de la versión 0.1 (spec 001) en los cuatro idiomas y en los dos modos de escucha: parada en ≤ 2 s, sin procesos huérfanos, original intacto, voz propia nunca captada, funcionamiento sin red y cambio de dispositivo sin reiniciar.

**Preparación y ajustes**

- **FR-018**: La preparación MUST descargar y verificar los componentes de los cuatro idiomas, mostrando su versión y su licencia. Repetirla MUST NOT volver a descargar nada.
- **FR-019**: Los nuevos ajustes (idioma de origen y aplicación que se escucha) MUST persistir entre sesiones, con valores por defecto sensatos: inglés y todo el PC mientras no se elija una aplicación.

### Key Entities

- **Idioma de origen**: uno de inglés, japonés, chino (mandarín) o coreano. Determina qué componentes de reconocimiento se usan. Se guarda en los ajustes y puede sobrescribirse por sesión.
- **Fuente de escucha**: «todo el PC» o «una aplicación», identificada por un nombre estable (por ejemplo, el nombre del programa). Se guarda en los ajustes y tiene un estado durante la sesión: sonando, en espera o desaparecida.
- **Corpus de prueba**: conjuntos de clips para medir cada objetivo: diálogo en cada idioma, diálogo bajo o susurrado, plurales informales y música o efectos sin diálogo.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: En 10 minutos de diálogo de cada idioma (inglés, japonés, chino y coreano), el retardo de frase tiene p50 ≤ 3 s y p95 ≤ 5 s.
- **SC-002**: En un corpus de 50 frases por idioma (japonés, chino y coreano), cada una con su traducción de referencia al español, la persona usuaria da por buenas (mismo sentido que la referencia y español de España natural) al menos el 85 %. No hace falta que entienda el idioma original.
- **SC-003**: Escuchando una aplicación, durante 10 minutos con voz en español sonando a la vez en otra aplicación, ninguna frase de esa otra aplicación se traduce.
- **SC-003b**: Con una película compartida por Discord y una conversación en español en la llamada a la vez, durante 10 minutos, ninguna frase de la conversación se traduce, y las de la película se traducen como en SC-001.
- **SC-004**: Si la aplicación elegida se reinicia, la traducción se reanuda en ≤ 5 s desde que vuelve a sonar.
- **SC-005**: En un corpus de diálogo bajo, susurrado o con palabras alargadas, al menos el 80 % de las frases se traducen y se oyen.
- **SC-006**: En un corpus de frases con plural informal, al menos el 95 % de las traducciones usan «vosotros» y sus formas verbales.
- **SC-007**: En 10 minutos de música, canciones y efectos sin diálogo, la app pronuncia como mucho 1 frase.
- **SC-008**: En una sesión en directo de 30 minutos, la app no capta ni traduce su propia voz ni una vez.
- **SC-009**: En una sesión de 60 minutos no hay cortes ni bloqueos, el retraso nunca pasa de 8 s más de 10 s seguidos y la memoria al final no supera en más de un 10 % la del minuto 5.
- **SC-010**: Con la preparación hecha y sin red, los modos directo y archivo funcionan en los cuatro idiomas.
- **SC-011**: Con la preparación hecha, el modo directo está escuchando en ≤ 60 s en cualquier idioma.

## Assumptions

- **Versión de partida:** la 0.1.0 (spec 001), validada en el PC. Se reutilizan su pipeline, la voz castellana y el control del retraso.
- **Idioma de destino:** siempre el español de España. El traductor de la versión 0.1 admite el japonés, el chino y el coreano; se confirmará en la investigación.
- **Recursos:** los reconocedores de los nuevos idiomas deben caber en el equipo sin desplazar a la traducción ni a la voz: la tarjeta gráfica está casi llena. Se prefiere el procesador.
- **Chino:** se entiende el mandarín. El cantonés queda fuera.
- **Escucha de una aplicación:** se hace por programa, no por pestaña ni por ventana.
- **Película y llamada en el mismo programa** (Discord, o Discord en el navegador): la defensa garantizada es ignorar el habla que no es del idioma elegido. Se asume que la conversación de la llamada es en español y la película en otro idioma. Si en la llamada se habla el mismo idioma que en la película, no se puede separar; queda documentado.
- **Preparación:** descarga los cuatro idiomas. Se estima un tamaño total moderado (unos cientos de MB por idioma), sin contar el inglés, que ya está.
- **Corpus de prueba:** se crean con material libre o sintético (como el conjunto de calidad de la versión 0.1) y con clips grabados por la persona usuaria con la opción de guardar el audio, que solo se usan en su PC.
- **Habla baja:** se mide con música de fondo a un nivel moderado. El diálogo totalmente tapado por la música no entra en el objetivo.
- **Fuera de alcance:** detección automática del idioma (spec 004), clonación de la voz del hablante (003), interfaz gráfica (005), traducir mientras se juega en el mismo PC, separar pestañas de un mismo programa y cantonés.
