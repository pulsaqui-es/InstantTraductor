# ADR-0005: Captura y reproducción de audio

- Estado: Aceptada (aprobada por el humano el 2026-09-30)
- Fecha: 2026-09-30
- Decide: orquestador (con visto bueno del humano)

## Contexto
Hay que capturar todo lo que suena en el PC y reproducir la voz en español por los mismos auriculares (Logitech G733, USB) sin volver a capturarla. El audio original no se toca (ADR-0003). El PC tiene Windows 11 build 26200.

## Decisión
- **Captura:** *process loopback* de WASAPI en modo `EXCLUDE_TARGET_PROCESS_TREE` sobre el PID del núcleo, es decir, «todo el sistema salvo InstantTraductor». Requiere la build 20348 o posterior.
  - Implementación: **pyminiaudio 1.71** (MIT), con una subclase que activa el modo por proceso. Depende de detalles internos, así que la versión queda fijada y hay tests que la vigilan.
  - Se piden 16 kHz, mono y float32; la conversión la hace Windows o miniaudio.
  - En silencio no llegan paquetes, así que se **rellena con ceros según el reloj** para que el VAD y los tiempos no se desajusten.
  - El volumen de la app de origen afecta al nivel capturado, así que hay **normalización o AGC** antes del ASR.
  - Un *watchdog* reactiva la captura tras suspender el equipo o si se pierde el dispositivo.
- **Reproducción:** `pyminiaudio.PlaybackDevice` en el **dispositivo por defecto**, siguiendo sus cambios (por ejemplo, al desconectar el G733), a 48 kHz float32 con periodos de 20–30 ms. Windows mezcla nuestra voz con el original.
- **Plan B:** si aparecen cortes (GIL, GPU al 100 %) o la subclase falla, se usa un *sidecar* en .NET 10 con **NAudio 3.1** (captura por proceso y reproducción que sigue al dispositivo), lanzado como hijo del núcleo y con la misma interfaz `AudioSource`/`AudioSink`.
- **Prueba temprana (spike)** en el PC del usuario, al principio de la spec 001:
  - autoexclusión, incluidos hijos y nietos;
  - conexión y desconexión del dispositivo;
  - comportamiento en silencio y niveles;
  - contenido con DRM (Netflix y similares);
  - audio espacial y juegos en modo exclusivo;
  - cortes con la GPU cargada;
  - latencia;
  - suspensión y reanudación.

## Alternativas consideradas
- **Loopback del dispositivo completo:** vuelve a capturar nuestra voz. Solo como diagnóstico.
- **Cable de audio virtual:** innecesario con el original sin cambios.
- **CSCore:** abandonado.
- **sounddevice para capturar:** no ofrece loopback.
- **Rust (`wasapi` + `cpal`) o C++:** exigen instalar herramientas que no hay y no aportan frente al plan B.

## Consecuencias
- Positivas: no hace falta instalar drivers ni compilar, y la capa añade decenas de milisegundos, despreciables en el presupuesto.
- Riesgos:
  - contenido no capturable (DRM, modo exclusivo, ASIO): la interfaz avisará de que no llega audio del origen;
  - audio de la app reproducido fuera del árbol: queda prohibido por diseño y se comprueba al arrancar con un tono de prueba;
  - dependencia de detalles internos de pyminiaudio.

## Referencias
- `docs/investigacion/2026-09-30-audio-windows.md`
