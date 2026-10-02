# S6 — Captura por aplicación (INCLUDE) medida en Windows 11

Spike de investigación de la feature 002-idiomas-y-peliculas. **No es código de producto**: scripts para medir en el PC real lo que
`docs/investigacion/2026-10-02-captura-por-app.md` dejó por medir y para dar al plan una base con cifras (FR-006..FR-012, SC-003,
SC-003b, SC-004). Fecha de las medidas: 2026-10-02. Entorno: Windows 11 Pro 25H2 (26200), Chrome 154, Edge 154, Discord 1.0.9259,
Python 3.12, `comtypes` 1.4.17, `pycaw` 20260927, `psutil` 7.2.2.

## Cómo se ejecuta

Usa el entorno raíz (no hay proyecto uv propio): `uv sync` en la raíz y después
`uv run python spikes/captura_app/<script>.py`. Los scripts importan `ProcessLoopbackSource`, `run_echo_selftest` y `DeviceSink` de
`src/` sin modificarlos. Ruff de la raíz excluye `spikes/`; aquí `ruff.toml` solo vigila errores reales. No hace falta GPU ni modelos.
Sin dependencias nuevas (`ffmpeg` y `ffplay` del PATH solo para `medir_navegador.py`).

| Script | Para qué |
|---|---|
| `listar_apps.py` | **Hito 1.** Lista numerada de apps con sesión de audio de **todos** los endpoints activos (la pantalla de arranque). |
| `capturar_app.py` | **Hito 2.** `AppWatcher`: INCLUDE por nombre, estado «esperando a la app», vigilante `(pid, create_time)`, detección de «suena pero llega silencio». También es un CLI. |
| `medir_navegador.py` | SC-003 y SC-004 con Chrome o Edge reproduciendo un vídeo (perfil temporal propio, audio propio). |
| `medir_reinicio.py` | SC-004 con un emisor controlado (tiempos finos de reanudación y de detección). |
| `medir_latencia.py` | Latencia emisor → captura INCLUDE. |
| `autotest_invertido.py` | **Hito 3.** Autotest con INCLUDE de otra app, con control positivo; escenarios de autoselección. |
| `profundidad.py` | Cuánto cubre INCLUDE en una cadena de procesos y desde los antepasados propios. |
| `discord_sesiones.py` | **Hito 3.** SC-003b: PIDs de Discord con sesión de audio, cada 0,5 s (instrucciones abajo). |
| `diagnostico_nivel.py` | Pico de sesión frente a lo que entrega cada INCLUDE y frente al sistema entero. |
| `common.py`, `emisor.py` | Utilidades (enumeración, resolución del PID raíz) y emisor de tonos (-30 dBFS por defecto). |

Reglas de las pruebas: sonidos propios, bajos (-30 dBFS) y cortos; nada de terceros se guarda ni se reproduce. Con Discord y con el
Chrome de uso real solo se leyeron PID, niveles (pico y RMS) y si INCLUDE entrega audio. El navegador de las pruebas usa un
`--user-data-dir` temporal (instancia aparte, borrada al terminar). Nota de nivel: un tono emitido a -30 dBFS (mono) llega a la
captura unos 6 dB más alto (pico -24 dBFS; probablemente Windows suma los dos canales al pasar de mono a estéreo).

## Resultados

### 1. Lista de apps (`listar_apps.py`)

- Enumeración de las sesiones de los 4 endpoints de render activos: **250 ms** sin nombres de endpoint, 320-340 ms con ellos (domina la
  activación COM de cada endpoint). Agrupar y resolver PID raíz: 170 ms (AUMID y datos del proceso). 14 sesiones → 6 apps.
- Salida real (resumida): `Discord` (objetivo PID 15112 = proceso `main`; sesiones de dos hijos directos: `renderer` activo y
  `utility:audio` inactivo), `Google Chrome` (objetivo 261644 = `browser`; la sesión la tiene el `AudioService`, hijo directo),
  `FACEIT`, `LGHUB Agent`, `Steam` (sesión del propio `steam.exe` en 4 endpoints) y `Steam Client WebHelper`. Las sesiones del mismo
  PID en varios endpoints se agrupan bien. La propia app y su padre quedan ocultos.
- Resolución del PID raíz con la regla «el padre directo si es la misma imagen y anterior; si no, el PID de la sesión»: acierta en
  Chrome, Discord y Steam (profundidad 1) y, en las pruebas de navegador, en la raíz del Chrome/Edge temporal. Nombre visible = `FileDescription` del `.exe` (como el Administrador de tareas).
  Ojo: `DiscordSystemHelper.exe` es otra imagen: la identidad debe ser la **ruta de la imagen**, no una subcadena del nombre.
- **Hallazgo: el medidor de pico de una sesión de Discord copia la mezcla del endpoint.** Mientras Chrome sonaba y Discord no entregaba
  nada, el pico de la sesión de Discord era idéntico al de Chrome (-11,4 dBFS ambos; con un emisor propio encendido, el de Discord
  subía por encima de los dos) y `INCLUDE(Discord)` daba -78 dBFS de RMS (silencio práctico). Así que «pico de sesión > 0» **no basta**
  para decir que una app suena. `listar_apps.py` hace un sondeo INCLUDE de 0,6 s por app con pico (en paralelo) y etiqueta `SUENA`
  (RMS ≥ -60 dBFS), `muy bajo` (≥ -80), `¿medidor?` (el medidor marca pero la captura no) o nada.
- Coste de resolver procesos con `psutil`: `process_iter(["pid","name"])` ~50 ms con 390 procesos; **pedir `create_time` de todos
  tarda 7,7 s la primera vez** y `cmdline` 40 ms cada uno. El vigilante filtra por nombre y solo pide `exe`/`create_time` de los
  candidatos: **18 ms por consulta con la caché caliente** (200-450 ms en frío, con Discord o con 27 procesos de Chrome).

### 2. INCLUDE por nombre con vigilante (`capturar_app.py`, `medir_reinicio.py`, `medir_navegador.py`)

**SC-003 (otra app no entra)**, Chrome 154 con un vídeo de 1234 Hz a -30 dBFS y una voz en español (SAPI) por `ffplay` a -30 dBFS, con
una segunda captura INCLUDE(`ffplay`) de control positivo (audio propio, solo métricas):

| Fase | Captura INCLUDE(Chrome) | Control INCLUDE(ffplay) |
|---|---|---|
| A: navegador mudo + voz de `ffplay` (14 s) | RMS **-138 dBFS** (ceros digitales) | RMS -50 dBFS (la voz suena) |
| B: vídeo + voz a la vez (**44 s**) | tono 1234 Hz a 126 dB sobre el fondo; lo demás **-71 dBFS** | RMS -50 dBFS (la voz sigue sonando) |
| C: solo el vídeo (línea base) | tono 123 dB; lo demás -60 dBFS | — |

La voz **no entra** (en A hay silencio digital y en B lo que no es el tono es igual o menor que la línea base). Mismo resultado con
**Edge 154** (A -138 dBFS; B 13,7 s con tono a 125 dB y resto -69 dBFS). El navegador de las pruebas no era el Chrome de uso real, y
este último no entró en ninguna medida. No se hizo la prueba de 10 minutos del SC-003 (sí 44 s por navegador); el mecanismo es
determinista (Windows filtra por proceso) y la prueba larga es trivial de repetir: `--fase-b 600`.

**SC-004 (reanudación ≤ 5 s)**, sondeo del vigilante de 0,25 s:

| Qué se reinicia | Detectar la muerte | Abrir INCLUDE tras el lanzamiento | Audio captado tras volver a sonar |
|---|---|---|---|
| Emisor controlado (5 reinicios + 1 arranque en frío) | 46-162 ms (mediana 149) | 104-373 ms (mediana 228) | **44-166 ms** (mediana 45; frío 38) |
| Chrome 154 (6 reinicios, todos sus procesos) | 257-530 ms | 186-1063 ms | **32-187 ms** desde el evento `playing` del vídeo |
| Edge 154 (3 reinicios) | 353-533 ms | 553-957 ms | **133-167 ms** |

El vídeo tarda 1,1-1,4 s en sonar tras lanzar el navegador, así que la captura casi siempre está abierta antes. Peor caso medido desde que
vuelve a sonar hasta el primer audio captado: **187 ms**, 25 veces por debajo del límite de 5 s (el arranque propio de la app no
cuenta; la cota teórica es un sondeo más la apertura, ≈ 1 s). Detalles útiles para el plan:

- **Procesos lanzadores efímeros**: en 1 de 6 reinicios de Chrome (y en 1 de 5 en una pasada anterior, donde se midió) la primera raíz encontrada murió a los 0,27 s (el lanzador de Chrome,
  que luego crea el `browser` real). El vigilante lo trató como un reinicio: MUERTA → esperando → INCLUDE sobre la raíz nueva a los 0,8 s.
  La raíz se resuelve **por nombre**, no por el PID del `Popen`.
- **`ProcessLoopbackSource` con `target_pid` explícito no sirve como vigilante**: cuando el PID muere, su vigilante interno avisa «Reabriendo
  la captura: el proceso objetivo ya no es el de la captura», reabre **con el mismo PID muerto** (según el código; se activa sin error, y con un PID inexistente se vio un aviso cada 10 s) y llama a
  `on_reopen`, que en producción lanzaría un autotest para nada. El spike lo evita cerrando él la captura antes. El plan necesita una
  de dos cosas: que en INCLUDE esa fuente no vigile el PID objetivo (lo hace el vigilante de la app) o un método para cambiar de PID.
- Una captura abierta sobre una app que **aún no existe** no se puede: se activa con PID inválido y da ceros sin error (4-6 ms, medido
  con 999999). Por eso el estado «esperando» no abre nada hasta que haya un proceso.

**Sesión con pico pero captura en silencio.** Demo (`capturar_app.py --app python --cmdline-contains emisor.py --forzar-pid 999999`):
la captura de un PID inexistente se activa sin error en 4,3 ms y da ceros; el emisor real, con su sesión a -22 dBFS, hace que el
vigilante pase a «suena pero llega silencio» a los **3,9 s** (umbral de 3 s sostenidos, comprobación cada 1 s). Ajuste necesario por el
hallazgo de Discord: si el pico de la sesión iguala o supera al de la sesión más alta de otra app, no se concluye nada (evento
`MEDIDOR`); con Discord solo en esa situación no hubo falsas alarmas. DRM real (Netflix, etc.) **no se pudo provocar**: sigue sin
verificar y requiere a la persona (ver «Pendiente»).

**Latencia de captura** (`medir_latencia.py`, INCLUDE sobre el lanzador del emisor, 20 ráfagas por búfer):
**65 ms** (búfer del emisor 10 ms; mín. 64, máx. 66) y **101 ms** (búfer 20 ms; 101-103). Es la del S4 (82-124 ms medidos con otro
método): no depende de elegir la app. No se midió EXCLUDE a la vez porque el PC tenía otros sonidos.

### 3. Autotest invertido (`autotest_invertido.py`)

`run_echo_selftest(sink, make_source)` **sirve tal cual**, interpretando `make_source(False)` como la captura de la app (INCLUDE(T)) y
`make_source(True)` como el control positivo (INCLUDE sobre el PID propio): una línea de código distinta en el *wiring* de
`WasapiDevices.selftest`. Mismo tono (1234 Hz, -30 dBFS, 0,3 s), misma duración (1,5-1,6 s) y umbral del monitor de eco 0,78-0,80 con
la app sonando, muda o inexistente (no cambia el calibrado). Resultados (3 repeticiones cada uno, siempre iguales):

| T (app elegida) | Resultado | Tono propio en INCLUDE(T) | Control positivo |
|---|---|---|---|
| Emisor ajeno que suena (777 Hz) | **OK** | -5 a 2 dB | 105-119 dB |
| Proceso ajeno sin audio | **OK** | 0 dB | 105-120 dB |
| Nuestro PID | **FALLA** (correcto) | 94 dB | 105-117 dB |
| Padre directo (lanzador del venv) | **FALLA** (correcto) | 94 dB | 105-116 dB |
| Antepasados de nivel 2 y 3 (`bash`) | **FALLA** | 87-95 dB | 105-119 dB |
| Antepasados de nivel 4, 5, 6 (`bash`, `claude`, `Code`) | OK | 0 dB | 105-117 dB |
| PID inexistente (999999) | **OK** (falso consuelo) | 0 dB | 105-119 dB |

Lo que hay que anotar:

- **Cobertura de antepasados distinta a la de S4.** Con `profundidad.py`: para el audio de **otro** proceso, INCLUDE cubre solo el PID y sus
  hijos directos (cadenas de 3-5 niveles, también a través de `cmd /c` y con el lanzador del venv; el abuelo del emisor no lo oye), como
  decía el informe. Pero el audio del **propio proceso que captura** lo oyen los INCLUDE de sus antepasados hasta el nivel 3 (1234 Hz a
  134 dB en los tres; el tono de un emisor hijo, a 2 dB, no). No se ha podido explicar el porqué (parece un tratamiento especial del
  proceso solicitante). Consecuencia: **hay que ocultar de la lista todos los antepasados propios, no solo el padre**, y el autotest
  invertido cubre el resto. En la práctica un terminal o un shell no tienen sesión de audio y no saldrían en la lista.
- El autotest **no detecta un PID inexistente o un PID de un proceso que no suena**: da OK porque no entra nada. Su garantía es
  «mi voz no entra», no «la captura funciona». Por eso la captura de la app necesita su propio comprobador (vigilante, «suena pero llega
  silencio»). El control positivo seguirá siendo INCLUDE(PID propio) y valida el camino de reproducción.
- Si la app elegida suena a la vez que el autotest, no molesta: el tono se detecta frente a la mediana de 40 frecuencias vecinas.

### 4. Discord (SC-003b)

Medido hoy, **sin llamada con emisión simultánea** (lo único que hay en el PC es la sesión normal del humano):

- Discord tiene **dos hijos directos con sesión de audio** del proceso `main` (PID 15112): un `renderer` (PID 692572, la voz y los
  sonidos de la app; sesión activa todo el rato) y un `utility:audio` (el `AudioService` de Chromium, PID 706344, sesión inactiva).
- `INCLUDE(main)` e `INCLUDE(renderer)` entregan **el mismo nivel** (misma señal, como en el informe); `INCLUDE(utility:audio)` da
  silencio mientras no suene nada por ahí. Los niveles del renderer eran muy bajos (RMS -57 a -134 dBFS, ráfagas): no había nadie
  hablando con volumen, así que no se pudo comprobar el audio de la llamada con contenido.
- **Lo que no se sabe y decide SC-003b**: si al ver una emisión (Go Live) su audio sale por el `utility:audio` (el reproductor `<video>`
  de Chromium usaría el `AudioService`) o por el mismo `renderer` que la voz de la llamada. `discord_sesiones.py` mide justo eso.

Cómo ejecutarlo con la persona (la herramienta solo escribe PID y niveles; no guarda audio):

1. Con Discord abierto, sin llamada: `uv run python spikes/captura_app/discord_sesiones.py --duracion 15` (referencia en reposo).
2. Que entre en una llamada de voz con alguien que hable en español y lanzar
   `... discord_sesiones.py --duracion 25 --probar --log sesiones_llamada.jsonl` (el fichero solo tiene PID, estado, pico y RMS).
3. Con la llamada activa, que otra persona (o una segunda cuenta) empiece una **emisión (Go Live)** de una película con diálogo en inglés y
   que ella la vea en su Discord: `... --duracion 40 --probar --log sesiones_ambas.jsonl` hablando ambos a ratos.
4. Variantes cortas (20 s cada una, una película sin diálogo sonando y la llamada en silencio, y al revés: la llamada hablando con la
   emisión en pausa) para atribuir cada intervalo a un PID.
5. Leer el resumen final: lista cada PID con los intervalos en que su INCLUDE entregó audio. **Si la emisión y la llamada salen por PID
   distintos**, el diseño del plan funciona: INCLUDE sobre ese PID hijo (no sobre `main`). **Si salen por el mismo PID** (solo uno
   entrega audio en las tres fases), por proceso no se pueden separar y hace falta el plan B (abajo).

## Recomendación de diseño para el plan

**Identificar y recordar la app.**
- Identidad = **ruta de la imagen normalizada** (la clave del informe: AUMID para paquetes de Store, medido sin paquetes aquí). El
  nombre visible (`FileDescription`) y la fecha se guardan solo para mostrar. El nombre introducido a mano se resuelve por
  coincidencia con el nombre visible o el de la imagen; con varias coincidencias se lista y se pide elegir (no se adivina). No se
  guarda nunca un PID. `DiscordSystemHelper.exe` ≠ `Discord.exe`: comparar la ruta, no una subcadena.
- El proceso que se captura (T) se recalcula siempre: sesión o su padre directo si es la misma imagen y anterior; varias raíces (varias
  instancias o `--user-data-dir` distintos) → no agrupar, elegir; que ninguna T sea hija directa de otra.
- La lista se construye con **todos** los endpoints, ocultando la propia app y **todos sus antepasados**, las sesiones del sistema y
  las apps sin sesión. Para marcar «suena» no basta el medidor: sondeo INCLUDE de ~0,6 s por app con pico, en paralelo. Orden: primero
  las que suenan; si solo una suena, preseleccionarla.

**Estado «esperando a la app».**
- Se entra cuando no hay proceso con esa imagen, cuando la raíz muere o cuando el vigilante no consigue abrir. En ese estado **no se abre
  ninguna captura** (ni una global): lo que no es la app no puede entrar (FR-010). Aviso en terminal: «Esperando a <app>…».
- Vigilar `(pid, create_time)` cada 0,25 s con `psutil` (≈ 0 ms con la caché caliente) para la muerte y cada 0,5-1 s para buscar el
  proceso mientras se espera (18 ms por sondeo con la caché caliente; calentar la caché al arrancar, el primer sondeo cuesta 0,2-0,5 s). No
  pedir `create_time` de todos los procesos (7,7 s en frío).
- Al aparecer un proceso, abrir INCLUDE sobre la raíz **aunque aún no suene** (los flujos nuevos entran solos): medido, la reanudación
  tras reinicio es < 0,5 s de punta a punta. Tratar un lanzador efímero como un reinicio más.
- `ProcessLoopbackSource` necesita una pequeña modificación (en INCLUDE, que el PID objetivo no sea vigilado por ella, o poder cambiar
  de PID): hoy reabre en bucle sobre el PID muerto sin error.

**Avisos (en terminal, en español).**
- «Esperando a <app>» (con la razón: no abierta, se cerró). «Escuchando <app>» al abrir (FR-012). «Se reinició <app>: se vuelve a
  escuchar» (≤ 1 s).
- «<app> suena pero Windows no entrega su audio (protección o salida exclusiva)»: pico de sesión > 0,003 y captura a ceros durante 3 s,
  **solo si** el pico de la sesión no coincide con el de otra app (el medidor de Discord copia la mezcla). Medido a los 3,9 s.
- «Es un navegador: se escucha todo lo que suene en él» (varias pestañas); «el volumen de la app en el mezclador baja o anula lo que se
  escucha» (S4 T5).
- Rechazar o avisar al elegir un antepasado propio; avisar si T es un shell o un lanzador.

**Autotest.** Reutilizar `run_echo_selftest` con la captura de la app como `make_source(False)` y el control positivo como
`make_source(True)` (INCLUDE sobre el PID propio): arranque, y tras cada reapertura. Cuesta lo mismo (1,5 s). Añadir el comprobador de que
la captura de la app **entrega** audio cuando la app suena (el autotest no lo cubre; un PID mal elegido pasa el autotest). Mantener el
modo «todo el PC» (EXCLUDE propio) con el autotest actual; FR-011 en ambos.

**Discord según lo medido.**
- Hoy: Discord se captura bien por proceso (INCLUDE(`main`) o del `renderer`); la voz de la llamada y todo lo que Discord emite salen
  por el `renderer`; el `utility:audio` está inactivo en una llamada normal.
- **Si Go Live sale por un PID distinto al de la llamada** (`utility:audio` o un segundo renderer): el plan captura con INCLUDE sobre
  ese **hijo concreto** y no sobre `main`, y la lista de apps debe poder ofrecer los hijos de Discord con una etiqueta («Discord:
  emisión»), apoyándose en el rol (`--type`, `--utility-sub-type`) y no en un PID. Esa decisión se fija con la medida de arriba.
- **Si salen por el mismo PID**: SC-003b no se puede cumplir separando por proceso. Plan B, para decidir con la persona: (a) silenciar
  en Discord a los participantes de la llamada y dejar solo el volumen de la emisión; (b) escuchar una app auxiliar que reproduzca la
  película en vez de Discord; (c) aceptar la mezcla y filtrar por voz (fuera de alcance). Hasta medirlo, el plan no debería
  prometer SC-003b.

## Pendiente (no resuelto aquí)

- **Discord con llamada y emisión a la vez** (SC-003b): script listo, falta la sesión con la persona.
- **DRM** (Netflix, Prime, Disney+ por navegador y por app de la Store) y **modo exclusivo** de reproductores: no se pudo provocar sin
  contenido de pago; `capturar_app.py` y `diagnostico_nivel.py` están preparados para medirlo.
- **Firefox**, apps de la Store/UWP (AUMID), reproductores (VLC, mpv...), apps elevadas o con anticheat: no instalados o no probados.
- **El porqué de la cobertura de antepasados** del proceso que captura (nivel 1-3) frente al comportamiento con otros procesos (nivel 1).
- Prueba larga de SC-003 (10 minutos) y cambio de dispositivo de salida con la captura abierta (M10).
