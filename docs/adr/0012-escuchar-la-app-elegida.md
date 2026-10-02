# ADR-0012: Escuchar solo la aplicación elegida (captura INCLUDE) y filtro de idioma

- Estado: Propuesta
- Fecha: 2026-10-02
- Decide: humano, a propuesta del orquestador tras el spike S6

## Contexto
La v0.1.0 capta todo el PC salvo su propia voz (EXCLUDE, ADR-0010). En el uso real, las voces en español de Discord se cuelan y «lían» la traducción. Además, la persona usuaria suele ver películas **compartidas por Discord** mientras habla en la llamada: la película y la conversación salen del mismo programa.

El spike S6 (`spikes/captura_app/README.md`) midió en su PC:
- **INCLUDE sobre el proceso raíz de Chrome o Edge** capta el navegador y deja fuera las demás apps. Al reiniciar la app, el audio vuelve a llegar en 32-187 ms.
- **INCLUDE cubre el PID y sus hijos directos.** Una captura admite un solo PID.
- **Con un PID inexistente**, Windows activa la captura sin error y entrega ceros.
- **El medidor de pico de una sesión no es fiable** (con Discord copia la mezcla del dispositivo): para saber si una app suena hay que probar a captarla.
- **Autoexclusión:** los INCLUDE de los antepasados propios, hasta el nivel 3, oyen nuestra voz.
- **El autotest de ADR-0010 sirve sin cambios** si se invierte el cableado.
- **Discord:** la voz de la llamada sale por un `renderer` hijo. Falta medir con la persona usuaria si la emisión (Go Live) sale por otro hijo.

El spike S5 (`spikes/idiomas/README.md`) midió un **filtro de idioma** con Whisper base en CPU: acepta el 97-99 % del idioma elegido y deja pasar un 0,3-0,7 % del español, con 96/131 ms por segmento.

## Decisión
1. **Dos modos de escucha** (FR-006):
   - **«una aplicación»**: INCLUDE sobre el proceso raíz de la app elegida;
   - **«todo el PC»**: EXCLUDE propio, como en ADR-0010.
   - Por defecto, «todo el PC» mientras no se elija ninguna app.
2. **Identidad de la app** = ruta de su ejecutable, guardada en los ajustes. Nunca el PID ni una subcadena del nombre.
3. **Lista para elegir** (FR-007): sesiones de audio de **todos** los dispositivos de salida, agrupadas por ejecutable. Se comprueba con una captura INCLUDE breve qué app suena de verdad. Se ocultan la propia app y **todos sus antepasados**.
4. **Vigilante de la app** por (PID, hora de creación): si muere o aún no existe, estado «esperando a la app», sin captar ninguna otra fuente (FR-010). Reabre con el PID nuevo. `ProcessLoopbackSource` deja de vigilar el PID objetivo en modo INCLUDE: el vigilante es quien cambia de PID.
5. **Aviso de «suena pero llega silencio»**: la captura entrega ceros mientras la app sí suena según la sonda.
6. **Autotest** al arrancar, con el cableado invertido en modo app: la captura de la app no debe oír el tono; una INCLUDE propia sí debe oírlo.
7. **Filtro de idioma** en ambos modos (FR-003): cada unidad reconocida se descarta si su audio no es del idioma elegido. Usa Whisper base ONNX en CPU, con una ventana de hasta 6 s y la decisión entre {elegido, español, inglés}. Es la defensa garantizada para la película y la llamada dentro de Discord.
8. **Discord:** si la medición con la persona usuaria muestra que la emisión y la llamada salen por PID hijos distintos, en modo app se capta solo el hijo de la emisión. Si salen por el mismo PID, se queda solo el filtro de idioma.

## Alternativas consideradas
- **Seguir con EXCLUDE y excluir Discord:** una captura solo excluye un PID, el propio.
- **Varias capturas mezcladas:** posible, pero sin necesidad real; complica la sincronía.
- **Separación de voces o diarización** para quitar la llamada: pesada, poco fiable y con licencias problemáticas; no hace falta si los idiomas difieren.
- **Solo el filtro de idioma, sin INCLUDE:** no quita notificaciones, música de otras apps ni conversaciones en el mismo idioma de la película.

## Consecuencias
- ADR-0010 sigue vigente para el modo «todo el PC». Este ADR añade el modo app y el filtro de idioma.
- **Coste del filtro:** unos 100 ms de CPU por unidad, en paralelo con la traducción, y un componente nuevo en `preparar` (Whisper base ONNX, licencia MIT).
- **No se pueden separar las pestañas** de un navegador. **Una llamada en el mismo idioma que la película**, dentro del mismo programa, no se puede separar.
- **Sin verificar:** contenido con DRM, apps de la Store, Firefox y reproductores locales. La persona usuaria usa Chrome, Edge y Discord, que sí están medidos.
