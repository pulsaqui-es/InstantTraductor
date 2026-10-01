# Feature Specification: Espina dorsal del intérprete simultáneo (inglés → español)

**Feature Branch**: `001-espina-dorsal`

**Created**: 2026-09-30

**Status**: Approved (H1, humano, 2026-10-01)

**Input**: User description: "Espina dorsal del intérprete simultáneo. El usuario arranca InstantTraductor con un comando mientras ve una serie o película en inglés en su PC con Windows 11. La app escucha todo lo que suena en el PC salvo su propia voz, reconoce el habla en inglés, la traduce al español de España y la pronuncia con una voz fija en castellano por los mismos auriculares, mezclada con el audio original, que no se modifica nunca. Objetivo de retardo: p50 ≤ 3 s y p95 ≤ 5 s. Incluye modo en directo, modo archivo, métricas de retardo, control básico del retraso, protección contra realimentación, comando de preparación y elección de voz. Fuera de alcance: clonación (003), japonés/chino y detección de idioma (004), interfaz gráfica (005), robustez con música y comparativa de motores (002)."

## Clarifications

### Session 2026-09-30

- Q: Cuando la voz en español va demasiado retrasada incluso hablando más rápido, ¿qué se prefiere? → A: Resumir. La traducción se acorta a lo esencial para recuperar el ritmo; descartar frases queda solo como último recurso.
- Q: Con frases largas, ¿empezar antes traduciendo por partes o esperar a la frase entera? → A: Por partes. Las frases cortas se traducen enteras; las largas, por fragmentos con sentido en cuanto están listos.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Oír en español lo que suena en el PC (Priority: P1)

La persona usuaria abre una terminal, lanza InstantTraductor en modo directo y pone una serie o película en inglés. A medida que los personajes hablan, oye por los auriculares la traducción al español de España con una voz castellana, superpuesta al audio original, que sigue sonando igual. En la terminal ve si la app está escuchando, traduciendo o hablando, y cuánto retraso lleva. Cuando termina, detiene la app y ve un resumen de la sesión.

**Why this priority**: es el objetivo principal del proyecto. Sin esto no hay producto; todo lo demás lo apoya o lo mide.

**Independent Test**: con la preparación hecha, reproducir un vídeo en inglés con diálogo claro durante 10 minutos con el modo directo activo. Se oye cada frase en español dentro del retardo objetivo, el original no cambia y al detener la app no queda nada en marcha.

**Acceptance Scenarios**:

1. **Given** la app preparada y un vídeo en inglés sonando, **When** la persona usuaria arranca el modo directo, **Then** cada frase dicha en inglés se oye traducida al español, en el mismo orden, sin que el original cambie de volumen ni se corte.
2. **Given** el modo directo en marcha, **When** no suena ninguna voz (silencio, pausa del vídeo o solo ruido de ambiente), **Then** la app no pronuncia nada.
3. **Given** el modo directo en marcha, **When** suena la propia voz en español de la app, **Then** esa voz nunca se vuelve a captar ni a traducir.
4. **Given** el modo directo en marcha, **When** la persona usuaria pide detenerlo, **Then** la app termina en 2 segundos o menos, no deja ningún proceso suyo en marcha y muestra el resumen de la sesión.
5. **Given** el modo directo en marcha, **When** se desconectan los auriculares o cambia el dispositivo de salida predeterminado, **Then** la voz en español pasa a sonar por el nuevo dispositivo sin reiniciar la app.
6. **Given** la voz en español acumula retraso, **When** el retraso supera el primer umbral, **Then** la voz habla más rápido (hasta 1,25×); **When** aun así supera el segundo umbral, **Then** las traducciones siguientes se resumen a lo esencial hasta recuperar el ritmo; y **When** incluso así supera el tercer umbral, **Then** se descartan las frases pendientes más antiguas que aún no han empezado a sonar, avisándolo en la terminal.
7. **Given** el modo directo en marcha, **When** la persona usuaria cambia el volumen de la voz en español, **Then** solo cambia la voz en español y el original sigue igual.

---

### User Story 2 - Traducir un fichero y medir el resultado (Priority: P2)

La persona usuaria (o el propio equipo de desarrollo) pasa a la app un fichero de audio o vídeo en inglés. Obtiene, sin usar altavoces ni auriculares, la pista de voz en español colocada en el tiempo como sonaría en directo, una mezcla del original con esa voz para escucharla, la transcripción y la traducción con sus tiempos, y un informe con las métricas de retardo.

**Why this priority**: permite probar y comparar la calidad y el retardo con contenido repetible, sin depender de dispositivos ni del momento. Es la base de las pruebas automáticas y de la mejora continua (specs 002 y siguientes).

**Independent Test**: ejecutar el modo archivo sobre un clip en inglés de 2 minutos. Aparecen las cinco salidas y el informe muestra, frase a frase, el retardo y el tiempo de cada etapa.

**Acceptance Scenarios**:

1. **Given** un fichero de audio o vídeo con habla en inglés, **When** se ejecuta el modo archivo, **Then** se generan: la pista de voz en español alineada en el tiempo, la mezcla original + español, la transcripción con tiempos, la traducción con tiempos y el informe de métricas.
2. **Given** el mismo fichero procesado dos veces con los mismos ajustes, **When** se comparan las transcripciones y traducciones, **Then** coinciden. Los tiempos pueden variar, pero se mantienen dentro del retardo objetivo.
3. **Given** un fichero sin habla, **When** se ejecuta el modo archivo, **Then** termina sin error, la pista en español queda en silencio y el informe indica que no se detectó habla.
4. **Given** un fichero dañado o en un formato no admitido, **When** se ejecuta el modo archivo, **Then** la app termina con un mensaje claro que dice qué falla y no genera salidas a medias.

---

### User Story 3 - Preparar el equipo y elegir la voz (Priority: P3)

La primera vez, la persona usuaria ejecuta un comando de preparación. Este descarga todo lo necesario sin coste ni cuentas, comprueba que el equipo puede con ello y enseña qué componentes se han instalado y con qué licencia. Después escucha muestras de varias voces castellanas y elige la que prefiere. La app la recuerda para las siguientes sesiones.

**Why this priority**: es imprescindible para usar la app, pero se hace una sola vez. Las historias 1 y 2 pueden probarse con una preparación manual durante el desarrollo.

**Independent Test**: en el PC de la persona usuaria, ejecutar la preparación dos veces seguidas. La primera deja todo listo; la segunda no descarga nada y confirma que todo está correcto. Después, escuchar las muestras y elegir una voz, que se usa en la siguiente sesión.

**Acceptance Scenarios**:

1. **Given** un PC con los requisitos y conexión a internet, **When** se ejecuta la preparación, **Then** queda todo listo en una sola ejecución, sin pasos manuales, cuentas ni pagos, y se muestra la lista de componentes con su licencia.
2. **Given** la preparación ya hecha, **When** se ejecuta otra vez, **Then** no vuelve a descargar nada y verifica que todo sigue correcto.
3. **Given** la preparación hecha, **When** se pide escuchar las voces, **Then** se oye una muestra de cada voz castellana disponible (al menos 3) y la persona usuaria puede elegir una.
4. **Given** falta espacio en disco o el equipo no cumple los requisitos, **When** se ejecuta la preparación, **Then** se detiene antes de descargar y explica qué falta.

---

### Edge Cases

- **Habla continua sin pausas** (monólogos, discusiones): la app no espera al final para traducir. Empieza con lo ya dicho cuando lleva el máximo de habla sin traducir (6 s por defecto).
- **Frases muy cortas o interjecciones** ("Yeah.", "What?", "Run!"): se traducen como el resto; si generan retraso, entra el control de retraso.
- **Varias personas hablando a la vez:** se traduce lo que se reconozca, sin garantía de separar las voces (la clonación y los hablantes llegan en la 003).
- **Música, canciones y efectos fuertes:** lo básico es no inventar frases cuando no hay voz. La robustez específica llega en la 002.
- **Habla en otro idioma que no sea inglés:** no se garantiza la traducción; lo deseable es no producir frases sin sentido. La detección de idioma llega en la 004.
- **Contenido protegido que el sistema no deja capturar:** no se traduce; la terminal indica que no llega audio.
- **Sonidos del sistema y notificaciones:** no son voz y no deben producir traducciones.
- **Falta un modelo o la preparación está incompleta:** la app no arranca y dice que hay que ejecutar la preparación.
- **Un componente interno se cae a mitad de sesión:** la app avisa, intenta recuperarlo una vez y, si no puede, se detiene de forma limpia.
- **El equipo va cargado y todo se ralentiza:** actúa el control de retraso y el informe lo refleja.
- **Se detiene la app mientras habla:** la voz se corta en ese momento y no queda audio pendiente sonando después.

## Requirements *(mandatory)*

### Functional Requirements

**Captura y audio original**

- **FR-001**: La app MUST captar todo lo que suena en el PC excluyendo siempre el sonido que produce ella misma.
- **FR-002**: La app MUST NOT modificar nunca el audio original (volumen, silencio ni efectos).
- **FR-003**: Al arrancar el modo directo, la app MUST comprobar automáticamente que no capta su propia voz. Si la comprobación falla, MUST NOT arrancar y MUST explicar el motivo.

**Reconocimiento, traducción y voz**

- **FR-004**: La app MUST reconocer el habla en inglés y dividirla en unidades de traducción. Las frases cortas se traducen enteras; las largas, por fragmentos con sentido propio (cláusulas) en cuanto cada fragmento está completo.
- **FR-005**: La app MUST empezar a traducir sin esperar más del máximo configurado de habla continua sin traducir (6 s por defecto), aunque el fragmento no haya terminado.
- **FR-006**: La app MUST traducir al español de España (vocabulario y formas peninsulares, incluido "vosotros"), teniendo en cuenta las frases anteriores para mantener la coherencia (nombres, género, tratamiento).
- **FR-007**: La app MUST pronunciar cada traducción con la voz castellana elegida, por el dispositivo de salida predeterminado y mezclada con el original.
- **FR-008**: La app MUST pronunciar las traducciones en el mismo orden en que se dijeron los originales, y MUST NOT repetir ni volver a traducir una frase que ya ha sonado.
- **FR-009**: La app MUST NOT pronunciar nada cuando no se detecta voz en el audio captado.
- **FR-010**: La persona usuaria MUST poder ajustar el volumen de la voz en español sin que cambie el original.

**Control del retraso**

- **FR-011**: La app MUST medir continuamente el retraso de la voz en español respecto al original.
- **FR-012**: Si el retraso supera el primer umbral (3 s por defecto), la app MUST acelerar la voz de forma gradual hasta un máximo de 1,25×.
- **FR-013**: Si con la velocidad máxima el retraso supera el segundo umbral (5 s por defecto), la app MUST resumir las traducciones siguientes a su sentido esencial (más cortas y sin perder la información clave) hasta que el retraso vuelva por debajo del primer umbral. Cada frase resumida MUST contarse en el resumen de la sesión.
- **FR-014**: Solo si, aun resumiendo, el retraso supera el tercer umbral (8 s por defecto), la app MUST descartar las frases pendientes más antiguas que aún no han empezado a sonar, MUST avisarlo en la terminal y MUST contarlo en el resumen de la sesión.

**Modo directo**

- **FR-015**: La persona usuaria MUST poder arrancar el modo directo con un comando y detenerlo con una orden de teclado. La app MUST terminar en ≤ 2 s sin dejar procesos suyos en marcha.
- **FR-016**: Durante el modo directo, la app MUST mostrar en la terminal su estado (escuchando, traduciendo, hablando), el retraso actual y los avisos. Opcionalmente MAY mostrar el texto original y la traducción de cada frase.
- **FR-017**: Si cambia el dispositivo de salida predeterminado, la app MUST seguir hablando por el nuevo dispositivo sin reiniciarse, y la captura MUST continuar.
- **FR-018**: Si un componente interno falla, la app MUST avisar, intentar recuperarlo una vez y, si no lo consigue, detenerse de forma limpia sin procesos huérfanos.

**Modo archivo**

- **FR-019**: La app MUST aceptar ficheros de audio o vídeo habituales (al menos WAV, MP3, MP4 y MKV) con habla en inglés.
- **FR-020**: El modo archivo MUST generar cinco salidas:
  - la pista de voz en español alineada en el tiempo como sonaría en directo;
  - la mezcla del original con esa voz;
  - la transcripción con tiempos;
  - la traducción con tiempos;
  - el informe de métricas.
- **FR-021**: El modo archivo MUST NOT usar dispositivos de audio y MUST reproducir el comportamiento temporal del modo directo, para que sus métricas sean comparables.
- **FR-022**: Ante un fichero dañado o no admitido, la app MUST terminar con un mensaje claro y MUST NOT dejar salidas a medias.

**Métricas**

- **FR-023**: Para cada frase, la app MUST registrar el tiempo de cada etapa (captación, reconocimiento, traducción, síntesis de voz, reproducción) y el retardo de frase.
- **FR-024**: Al terminar cada sesión (directo o archivo), la app MUST mostrar y guardar un resumen con:
  - el número de frases;
  - el retardo de frase (p50 y p95);
  - el tiempo por etapa (p50 y p95);
  - las aceleraciones aplicadas;
  - las frases resumidas;
  - las frases descartadas.

**Preparación, voces y ajustes**

- **FR-025**: Un comando de preparación MUST descargar e instalar en local todo lo necesario, sin coste ni cuentas, y MUST comprobar antes los requisitos (espacio en disco, tarjeta gráfica). Repetirlo MUST NOT volver a descargar lo que ya está.
- **FR-026**: La preparación MUST mostrar cada componente instalado con su versión y su licencia.
- **FR-027**: Tras la preparación, la app MUST funcionar sin conexión a internet.
- **FR-028**: La app MUST ofrecer al menos 3 voces castellanas, masculinas y femeninas. La persona usuaria MUST poder escuchar una muestra de cada una y elegir. La elección MUST recordarse entre sesiones.
- **FR-029**: Los ajustes (voz, volumen de la voz, umbrales de retraso, velocidad máxima y máximo de habla sin traducir) MUST persistir entre sesiones y MUST tener valores por defecto sensatos.
- **FR-030**: La app MUST NOT guardar el audio captado salvo que la persona usuaria lo pida expresamente. MUST guardar un registro de diagnóstico de la sesión sin audio.

### Key Entities

- **Sesión**: una ejecución en modo directo o archivo. Tiene inicio y fin, los ajustes usados y el resumen de métricas.
- **Frase**: la unidad que se traduce, sea una frase corta entera o un fragmento con sentido de una frase larga. Guarda el texto original, su inicio y fin en el audio, la traducción (y si se resumió), su estado (pendiente, sonando, pronunciada o descartada), la velocidad aplicada y los tiempos de cada etapa.
- **Voz**: una voz castellana disponible, con nombre, muestra de escucha, origen y licencia.
- **Componente**: cada pieza descargada en la preparación, con nombre, versión, licencia y estado de verificación.
- **Informe de métricas**: el resumen de una sesión más el detalle por frase.

## Success Criteria *(mandatory)*

Definiciones usadas en esta spec:
- **Retardo de frase:** el tiempo que pasa desde que termina de decirse en el original una frase (o un fragmento, si es una frase larga) hasta que empieza a oírse su traducción.
- **p50:** la mediana; la mitad de las frases va igual o más rápida.
- **p95:** el valor que cumple el 95 % de las frases.

### Measurable Outcomes

- **SC-001**: En al menos 10 minutos de diálogo en inglés de series o películas (con música de fondo moderada), el retardo de frase tiene p50 ≤ 3 s y p95 ≤ 5 s.
- **SC-002**: En una sesión en directo de 30 minutos, la app no capta ni traduce su propia voz ni una sola vez.
- **SC-003**: En 10 minutos sin habla (silencio o ruido de ambiente), la app no pronuncia ninguna frase.
- **SC-004**: En un conjunto de 50 frases de prueba, la persona usuaria da por buena (sentido fiel y español de España natural) al menos el 85 % de las traducciones que oye.
- **SC-005**: En una sesión en directo de 60 minutos no hay cortes ni bloqueos, el retraso nunca pasa de 8 s más de 10 s seguidos y el uso de memoria al final no supera en más de un 10 % al del minuto 5.
- **SC-006**: En 20 paradas seguidas, la app termina en ≤ 2 s y nunca deja procesos suyos en marcha.
- **SC-007**: El modo archivo procesa un fichero de 10 minutos y genera las cinco salidas y el informe sin usar ningún dispositivo de audio.
- **SC-008**: La preparación deja todo listo en una sola ejecución, sin pasos manuales, cuentas ni pagos, y una segunda ejecución no descarga nada.
- **SC-009**: La persona usuaria elige, tras escuchar las muestras, una voz que considera castellana y natural.
- **SC-010**: Con la preparación hecha, pasan ≤ 60 s desde que se lanza el modo directo hasta que la app está escuchando.

## Assumptions

- El equipo es el de la persona usuaria: Windows 11, NVIDIA RTX 5070 de 12 GB, 32 GB de RAM y al menos 15 GB libres en disco para los componentes.
- Todo funciona en local y sin costes (ADR-0003). Solo la preparación necesita internet.
- Uso personal: se aceptan licencias no comerciales. El audio generado no se distribuye.
- El idioma de origen es el inglés. Otros idiomas y la detección automática llegan en la spec 004.
- La voz en español es fija (una de las voces castellanas elegibles). La voz parecida a la del hablante llega en la spec 003.
- El contenido de referencia es diálogo con música de fondo moderada. La música fuerte, las canciones y los efectos intensos se tratan en la spec 002.
- No se traduce mientras se juega en el mismo PC (ADR-0003).
- La interfaz de esta spec es la terminal. La app de escritorio llega en la spec 005.
- Se usan auriculares. Con altavoces también funciona, porque se capta el sonido del sistema y no el de un micrófono.
- Los umbrales por defecto (3 s para acelerar, 5 s para resumir, 8 s para descartar, 1,25× de velocidad máxima y 6 s de habla sin traducir) son un punto de partida que se ajustará con las métricas.
