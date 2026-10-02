# Captura por aplicación (INCLUDE sobre un proceso) en Windows 11

- Fecha de consulta y de las medidas: 2026-10-02.
- Contexto: spec 002. El humano decide capturar **solo la app elegida** (modo `PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE`) para que las voces de Discord no se cuelen. Parte de ADR-0005, ADR-0010 y el spike S4 (`spikes/audio/README.md`).
- Entorno de las medidas de hoy: Windows 11 Pro 25H2 build 26200, Chrome 154.0.8037.58, Edge 154.0.4258.53, Discord 1.0.9259, pycaw 20260927 (MIT), comtypes 1.4.17 (MIT), psutil 7.2.2 (BSD-3-Clause). Se usó la captura `loopback_ctypes.py` del spike, copiada a una carpeta temporal fuera del repo (no se tocó código del proyecto).
- Leyenda de evidencia: **[M]** medido hoy en este PC; **[S4]** medido en el spike S4; **[D]** documentación de Microsoft; **[T]** fuente de terceros (código o issues públicos); **[SV]** sin verificar.

## 1. Resumen ejecutivo

1. **INCLUDE cubre el PID objetivo y sus hijos directos, no el árbol entero [S4][M]**. La documentación de Microsoft dice solo «child processes» [D]. Los procesos hijos creados después de abrir la captura entran (evaluación dinámica) [S4]. Los nietos no [S4].
2. **Chrome, Edge y Discord (Electron) funcionan con INCLUDE sobre el proceso raíz [M]**. El servicio de audio (`--type=utility`, `audio.mojom.AudioService`) y los renderers son hijos **directos** del proceso `browser`; INCLUDE(raíz) oyó el tono y los renderers/GPU por separado no. Si se mata el servicio de audio, Chrome y Edge lo recrean con otro PID y INCLUDE(raíz) sigue oyendo sin reabrir [M]. En Discord la voz sale por un **renderer**, no por el servicio de audio [M].
3. **Varios perfiles o ventanas del mismo navegador = un solo proceso raíz = una sola captura que mezcla todas las pestañas [M]**. No se puede separar por pestaña. Dos instancias con `--user-data-dir` distinto sí tienen raíces distintas.
4. **La lista de apps se saca de las sesiones de audio** (`IAudioSessionManager2`) de **todos** los endpoints de render, no solo del predeterminado. El PID de la sesión suele ser un hijo (servicio de audio o renderer). Hay que subir a la raíz con la regla medida: el objetivo es el PID de la sesión **o su padre directo**, nunca un antepasado más lejano [M][S4].
5. **Una captura = un PID [D]** (la estructura tiene un único `TargetProcessId`). Varias capturas se pueden abrir y sumar: dos capturas simultáneas de la misma fuente salieron idénticas muestra a muestra (desfase 0) [M]. Hay que evitar capturar un padre y su hijo a la vez (doble recuento).
6. **Fallos silenciosos medidos hoy [M]**: activar INCLUDE con un PID inexistente (999999, 4 o 0xFFFFFFF0) funciona y entrega ceros sin error. Con S4/T1c: si el PID objetivo muere, la captura sigue viva y muda. Hace falta vigilar el proceso y reabrir con el PID nuevo.
7. **DRM: sin verificar.** No hay fuente primaria que diga qué pasa con Netflix, Prime o Disney+ por proceso. Hay un caso real de una app (Teams de escritorio) cuyo audio llega mudo por proceso pero sí por endpoint [T]. Hace falta una prueba asistida por el humano (spike).
8. **Autoexclusión**: con INCLUDE de otra app nuestra voz queda fuera por diseño. Casos que fallan: elegir nuestro propio PID, su padre directo (el redirector del venv, un lanzador o `explorer.exe`) o una app que re-renderiza nuestra salida (cable virtual). Se evita filtrando la lista y con un autotest invertido.
9. Lo medido hoy apoya el diseño; lo que queda por medir (Firefox, Store/UWP, reproductores, DRM, elevación) está en §4.4.

## 2. Tabla comparativa

Qué proceso emite el audio y a qué PID hay que apuntar, por tipo de app.

| Tipo de app | Proceso que tiene la sesión de audio | Objetivo INCLUDE recomendado | Estado |
|---|---|---|---|
| Chrome 154 | `chrome.exe --type=utility --utility-sub-type=audio.mojom.AudioService`, hijo directo del `browser` | PID del proceso `browser` (raíz) | **[M]** INCLUDE(raíz) y INCLUDE(servicio) oyen; renderers y GPU no; el servicio se recrea con otro PID y la captura de la raíz sigue |
| Edge 154 | Igual que Chrome (`msedge.exe`) | PID del `browser` | **[M]** igual que Chrome |
| Chrome/Edge con varios perfiles o ventanas (mismo `user-data-dir`) | El mismo servicio de audio | El mismo `browser` | **[M]** un solo proceso raíz; INCLUDE oyó los tonos de ambos perfiles |
| Chrome/Edge con `user-data-dir` distinto | Un servicio de audio por instancia | Una raíz por instancia | Medido por otros [T] (sokuji PR 394); por construcción también aquí |
| Electron (Discord) | **Renderer** (voz y sonidos) y también el servicio de audio (inactivo), ambos hijos directos del `main` | PID del `main` (`browser/main`) | **[M]** INCLUDE(main) = INCLUDE(renderer), mismo nivel; INCLUDE(servicio) = silencio |
| Steam (`steam.exe` → `steamwebhelper` → `steamwebhelper`) | `steamwebhelper` a **dos** niveles de `steam.exe` | El padre directo del que emite (`steamwebhelper` intermedio), no `steam.exe` | Estructura **[M]**; captura sin probar (la sesión estaba inactiva) |
| Firefox | Sin verificar: proceso de contenido, utility o el principal. El lanzador (`firefox.exe`) termina tras crear el proceso `browser` [T] | PID del proceso `browser` (todo hijo lo lanza el padre [D-Mozilla]) | **[SV]** no instalado aquí |
| VLC, mpv, MPC-HC, PotPlayer | Un proceso por reproductor. mpv puede tener un envoltorio `mpv.com` | El PID del que suena | **[SV]** ninguno instalado aquí. Si usan salida WASAPI en **modo exclusivo** no pasan por el motor: no se captura |
| Netflix, Disney+, Prime (Microsoft Store: UWP, WinUI o contenedor) | Proceso propio del paquete (no `ApplicationFrameHost`) | PID de la sesión | **[SV]** no instalados aquí |
| Teams de escritorio (`ms-teams.exe`) | Una sola sesión de render duplicada, PID de `ms-teams.exe` | — | **[T]** process loopback entrega **silencio**; el loopback de endpoint sí lo captura (microsoft/Windows-classic-samples #414, abierto) |
| Contenido DRM (Widevine, PlayReady) | El del navegador o app | El del navegador o app | **[SV]** ver §3.3 |

## 3. Detalle por opción (una por pregunta)

### 3.1 Semántica de INCLUDE_TARGET_PROCESS_TREE (pregunta 1)

- **Documentación** [D]: `TargetProcessId` es «el ID del proceso cuyos flujos de render, y los de sus procesos hijos, se incluirán o excluirán». El enum dice «el proceso especificado y sus procesos hijos». No define «árbol» ni habla de nietos. El ejemplo `ApplicationLoopback` repite «un proceso y cualquiera de sus procesos hijos» [D]. Si el árbol no tiene flujos de render, el capturador recibe silencio [D] (confirmado: ceros, 100 paquetes/s [S4]).
- **Medido en el spike S4** [S4] (2 rondas, 12 escenarios, control positivo y control de endpoint):
  - propio PID y hijo directo (creado antes o después de abrir la captura): **incluido**;
  - nieto (hijo de un hijo directo), también con `cmd /c` de por medio o con el redirector de uv: **no incluido**;
  - ascendientes: INCLUDE(padre directo) oye al hijo; INCLUDE(abuelo) no.
- **Conclusión**: la regla efectiva es **«PID objetivo + hijos directos»**, evaluada de forma dinámica para los hijos. Lo confirma lo de hoy: en Chrome, Edge y Discord el emisor es siempre hijo directo del proceso raíz [M], así que el comportamiento «árbol» de los terceros parece cierto solo por esa forma de los procesos.
- **Advertencia**: no se debe copiar la heurística de otros proyectos de «subir hasta el antepasado más alto con el mismo ejecutable» (sokuji PR 394, polyrec PR 84 [T]). Con árboles de profundidad ≥ 2 el antepasado alto **no cubre** a los nietos según S4. Aquí se usa «la sesión o su padre directo» y, si hace falta, varias capturas (§3.5).
- Matiz de versión: Microsoft documenta build mínima 20348 [D]; OBS y otros dicen Windows 10 2004 [T]. Irrelevante en Windows 11.
- Pendiente de comprobar (spike M2): que la regla de profundidad 1 se mantenga con procesos reales de profundidad ≥ 2 (Steam).

### 3.2 Navegadores (pregunta 2)

**Chrome y Edge [M]** (perfil temporal propio, tono de 1234 Hz a 0,03 de amplitud con WebAudio, procesos y carpeta temporal eliminados al terminar):
- El árbol de un `browser` con una pestaña: ~10–16 hijos directos (renderers, `gpu-process`, `crashpad-handler`, `utility/network`, `utility/storage`, `utility/audio.mojom.AudioService`). **Todos tienen como padre el proceso `browser`**.
- Sesión de audio: solo la tiene el PID del `AudioService`.
- INCLUDE(PID del browser): rms 0,0152 (Chrome) y 0,0153 (Edge). INCLUDE(AudioService): 0,0152 y 0,0153. INCLUDE(renderers, GPU): **0**.
- Se mató el servicio de audio con INCLUDE(raíz) abierta: el nivel cayó a 0 durante ~2 s y volvió con un `AudioService` nuevo (PID distinto), **sin reabrir la captura**. (La página pedía un flujo nuevo cada 2 s, así que el hueco medido es un máximo por esa cadencia, no el tiempo real de recreación.)
- En el Chrome y el Edge de uso real también vi la misma forma (servicio de audio hijo directo del `browser`) [M]. En el Chrome real el servicio estaba inactivo y listado (sesión estado 0), lo que muestra que las sesiones inactivas siguen apareciendo.
- El PID con el que se lanza `chrome.exe` no es la raíz: en una prueba Chrome relanzó un proceso y el `browser` real tenía como padre uno ya muerto. La raíz real se obtiene de la sesión, no del `Popen`.
- Confirmado por terceros [T]: sokuji PR 394 midió lo mismo (el PID que lista la sesión es el `utility` reciclable; apuntar a él da `target_gone` si se recicla; apuntar al browser sobrevive).

**Varios perfiles y ventanas [M]**: con el mismo `--user-data-dir` y dos perfiles (`Default` y `Profile 2`, tonos de 1234 y 777 Hz) hubo **un solo proceso `browser`** y INCLUDE(raíz) oyó **ambos** tonos (0,0186 y 0,0134; ruido de referencia 0,00002). Es decir, no hay forma de elegir un perfil, ventana ni pestaña. Con `user-data-dir` distinto hay otra raíz y otro servicio de audio [T].

**Firefox [SV]**: no está instalado en este PC. Lo que sí se sabe:
- el proceso padre lanza y gestiona todos los hijos [D-Mozilla, process model];
- en Windows existe un **proceso lanzador** que crea el proceso `browser` y se termina [T, Mozilla]; el `browser` real queda como raíz, no hay que apuntar al lanzador;
- el audio se remota por AudioIPC con un servidor en el proceso padre o de servidor [T, mozilla/audioipc]; qué proceso aparece como dueño de la sesión WASAPI en las versiones actuales no se ha podido verificar. En cualquier caso todos son hijos directos del `browser`, así que INCLUDE(browser) debería funcionar.
- Un hilo del foro de OBS dice que con la captura de aplicación de OBS Chrome y Firefox abiertos **antes** que OBS «no capturan» y abiertos después sí [T]; sin causa explicada. Hoy no se reprodujo: Discord, abierto horas antes, se capturó bien con INCLUDE [M]. Queda como pregunta abierta para Firefox.

### 3.3 Apps de streaming, reproductores y DRM (pregunta 3)

**Reproductores (VLC, mpv, MPC-HC, PotPlayer) [SV]**: ninguno instalado. Se espera un proceso único por reproductor (el PID de la sesión), salvo envoltorios de consola como `mpv.com`. El riesgo real es la **salida en modo exclusivo** de WASAPI: Microsoft dice que un flujo exclusivo no se puede capturar por loopback [D]; para process loopback no está medido (T7 del spike S4 sigue pendiente). Dos instancias de VLC aparecen como dos PID distintos con una sesión cada una [T, issue 414].

**Apps de la Microsoft Store (Netflix, Disney+, Prime) [SV]**: no hay ninguna instalada (solo `Microsoft.ZuneMusic`, que sirve de sujeto de prueba para UWP). Qué hay que medir: PID de la sesión, si su padre es el proceso del paquete, AUMID/`GetApplicationUserModelId` para el nombre y la clave estable.

**DRM [SV, con pistas]**:
- Microsoft: «un driver de audio de confianza no permite que un dispositivo de loopback capture flujos digitales con contenido protegido» [D, texto de la época de Vista, página actualizada en 2025-04].
- `process-audio-capture` (PyPI) lista «contenido protegido por DRM: no se puede capturar» como limitación [T].
- Sin fuente primaria sobre Netflix, Disney+ o Prime en Edge, Chrome o la app de la Store. Los resultados de búsqueda sobre «Netflix y loopback» eran SEO sin valor y se descartaron. El foro de OBS sobre Netflix habla de **vídeo** en negro, no del audio [T].
- Caso real que prueba que «por proceso» y «por endpoint» pueden diferir: Teams de escritorio [T]: process loopback da ceros y el loopback de endpoint sí captura. Causa no explicada; podría ser un tipo de flujo marcado por la app. Hoy, en cambio, Discord con voz en renderer se capturó bien por proceso [M].
- Conclusión: hay que medir, por servicio y por modo (INCLUDE vs endpoint), y añadir al diagnóstico el **medidor de pico de la sesión** (`IAudioMeterInformation`, que funciona: dio 0,81 para el renderer de Discord [M]). Si la sesión marca pico pero la captura es silencio digital, se avisa de «la app suena pero Windows no entrega su audio (protección)».

### 3.4 Cómo listar apps que suenan (pregunta 4)

- **API** [D][M]: `IMMDeviceEnumerator.EnumAudioEndpoints(eRender, ACTIVE)` → `IMMDevice.Activate(IAudioSessionManager2)` → `GetSessionEnumerator()` → por sesión `IAudioSessionControl2`: `GetProcessId()`, `GetState()` (0 inactiva, 1 activa, 2 expirada), `IsSystemSoundsSession()`, `GetSessionIdentifier()`, `GetDisplayName()` y `IAudioMeterInformation.GetPeakValue()`.
- **El enumerador es por dispositivo** [D]. `pycaw.AudioUtilities.GetAllSessions()` solo mira el dispositivo de reproducción **predeterminado** (código leído, pycaw 20260927). Hoy había 4 endpoints de render activos y las sesiones estaban repartidas (8 en el predeterminado y solo `steam.exe` + sonidos del sistema en los otros tres) [M]. La captura por proceso no depende del endpoint [D, README del ejemplo], así que la lista debe unir **todos** los endpoints activos. Con pycaw 20260927 se hace con `GetDeviceEnumerator()`/`IMMDeviceEnumerator` a mano (probado: funciona [M]).
- **El PID de la sesión no es el objetivo** [M]: en Chrome es el `AudioService` (hijo), en Discord el `renderer`, en Steam un `steamwebhelper` a dos niveles de `steam.exe`. `GetProcessId` puede devolver `AUDCLNT_S_NO_SINGLE_PROCESS` con el PID del creador cuando la sesión abarca varios procesos [D].
- **De PID de sesión a objetivo y nombre**:
  1. Imagen y hora de creación con psutil (`exe()`, `create_time()`); el par `(pid, create_time)` evita reutilización de PID.
  2. Objetivo `T`: el padre directo si está vivo, `create_time(padre) ≤ create_time(sesión)` y tiene **la misma imagen** que el emisor; si no, el propio PID. Chrome: `T`=browser. Discord: `T`=main. Steam: `T`=el `steamwebhelper` intermedio.
  3. Agrupar las sesiones que comparten imagen y comprobar la cobertura: un `T` cubre a `P` si `P == T` o `ppid(P) == T`. Si un solo `T` no cubre a todos los emisores del grupo, se abren varias capturas (§3.5) o se avisa.
  4. Nombre visible: `FileDescription` del `.exe` (lo que enseña el Administrador de tareas), con el PID añadido si hay varias instancias, y títulos de ventana (`EnumWindows` + `GetWindowThreadProcessId`) solo como pista. En paquetes de la Store, `GetApplicationUserModelId` da la clave estable [SV: no medido].
  5. Clave estable para recordar: ruta de la imagen normalizada (y AUMID si es un paquete). El `SessionIdentifier` de Windows contiene la ruta del exe y termina en `%b{GUID}`; sirve de apoyo, no es único entre instancias [D].
- **Cuándo refrescar**: sondear cada 1–2 s (coste sin medir, §4.4). `RegisterSessionNotification` existe [D] pero obliga a un `IAudioSessionNotification` propio con comtypes; solo merece la pena si el sondeo molesta.
- **Si la app se reinicia** [S4][T]: el PID nuevo no entra en una captura abierta con el PID antiguo (la captura sigue viva y muda). Hay que vigilar el proceso objetivo (`OpenProcess(SYNCHRONIZE)` y `WaitForSingleObject`, o psutil en cada pasada del vigilante), cerrar la captura, esperar a que reaparezca un proceso con la misma clave y reabrir. Mientras una raíz vive, los hijos nuevos (nuevo `AudioService`) entran solos [M].

### 3.5 Varios PID y mezcla (pregunta 5)

- **Una captura admite un solo PID** [D]: `AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS` tiene un único `DWORD TargetProcessId`.
- **Varias capturas a la vez** [M]: dos INCLUDE sobre la misma fuente (raíz y renderer de Discord) dieron muestras **idénticas** (correlación máxima con desfase 0 muestras, diferencia máxima 0), con un desfase de arranque de 1,97 ms entre los primeros paquetes. Cada captura es un `IAudioClient` independiente con paquetes de 10 ms [S4]; el coste de CPU es de ~0,8 % de un núcleo por captura [S4]; el spike S4 ya probó 3 capturas simultáneas.
- **Mezcla**: sumar muestra a muestra tras alinear por hora de llegada de paquetes (los sellos QPC son sintéticos [S4]). Latencia: la de cada captura (82–124 ms de la fuente a la captura [S4]); no se suma.
- **Doble recuento**: capturar un padre y su hijo directo a la vez (que es lo que ocurre con INCLUDE(raíz) + INCLUDE(renderer)) duplica la amplitud de lo común. El diseño debe deduplicar: una captura por `T` y que ningún `T` sea hijo directo de otro `T`.
- **Cuándo usarlas**: solo si el emisor no cabe en un único `T` (árboles de profundidad ≥ 2 con emisores en ramas distintas) o si el humano quiere dos apps a la vez. Para una app normal, una captura.

### 3.6 Autoexclusión con INCLUDE (pregunta 6)

Por diseño nuestra voz sale del núcleo (PID propio), que no es el PID elegido ni su hijo directo, así que no entra. Casos en que **sí** entraría:

| Caso | Por qué | Defensa |
|---|---|---|
| El usuario elige nuestra propia app (el núcleo) | INCLUDE(PID propio) oye nuestro audio [S4] | Quitar de la lista el PID propio y los emisores de nuestra imagen |
| Elige el padre directo del núcleo (redirector del venv, `uv.exe` si es padre directo, un lanzador, `cmd`/terminal o `explorer.exe` desde donde nos lanzaron) | El núcleo es hijo directo de ese `T`; INCLUDE(redirector) oye a su hijo directo [S4 T1b] | Rechazar `T == ppid(propio)` y `T == pid(propio)`; avisar si `T` es un shell o lanzador |
| Elige una app a la que nosotros lanzamos o que lanzó otro proceso de la app que reproduce | Cualquier hijo directo que suene queda dentro | La regla de ADR-0010: solo el núcleo reproduce |
| Cable virtual o mezclador que re-renderiza nuestra salida (VB-Cable, Voicemeeter, «Escuchar este dispositivo») y se elige esa herramienta | El audio pasa a ser emitido por otro proceso | Autotest invertido (abajo) y quitar de la lista las apps de esa clase conocidas [SV] |
| La interfaz de InstantTraductor corre en el navegador del usuario y emite audio (por ejemplo, previsualizar la voz) | Estaría dentro del árbol del navegador elegido | No emitir audio desde la interfaz; ya lo prohíbe la regla de ADR-0010 |
| Servicios compartidos | No hay un «host de audio compartido» que emita por cuenta de varias apps: `audiodg.exe` es el motor, no un cliente. Las sesiones del sistema (PID 0 y `ShellExperienceHost`, notificaciones) no son nuestro caso [M: aparecen en la lista] | Ocultar `IsSystemSoundsSession` en la lista |

**Autotest invertido** (sustituye al de ADR-0010 en modo INCLUDE): con la captura INCLUDE(objetivo) abierta, emitir un tono corto y bajo desde el núcleo y comprobar que **no** aparece; control positivo con INCLUDE(PID propio) temporal (que sí debe oírlo). Mismo método de detección que `analisis.py` [S4].

## 4. Recomendación para InstantTraductor

### 4.1 Decisión técnica (principal)

- **Captura**: INCLUDE sobre el `T` calculado (§3.4), una sola captura por defecto; varias solo si no hay un `T` que cubra todo.
- **Selección**: lista interactiva de apps (agrupadas por imagen) construida con las sesiones de **todos** los endpoints activos, con nombre amigable, estado (suena ahora / en silencio) y medidor de nivel. Orden: primero las que suenan. Si solo una app suena, preseleccionarla.
- **Recordar la elección**: guardar la clave de app (ruta de la imagen normalizada; AUMID para paquetes), el nombre visible y la fecha; nunca el PID. Al arrancar: buscar un proceso con esa clave; si existe, abrir INCLUDE(`T`) aunque no suene todavía (los flujos nuevos entran solos [M][S4]); si no, estado «esperando a la app» y sondeo cada 1–2 s.
- **Por nombre (CLI o ajuste)**: `--app chrome.exe` o coincidencia por subcadena del nombre amigable. Si hay varias instancias con la misma imagen, no adivinar: listar con PID y título de ventana y exigir una; si exactamente una suena ahora, ofrecerla.
- **Vigilante** (ampliación de ADR-0010): además de las cuatro condiciones, vigilar que el proceso objetivo siga vivo con `(pid, create_time)` y que el PID siga existiendo antes de abrir (un PID inválido se activa sin error y da ceros [M]); al morir, cerrar y pasar a «esperando». Distinguir tres estados en la interfaz: app no encontrada, app sin sonido y app que suena pero llega silencio (medidor de pico > 0 con captura a ceros: DRM o protección).
- **Filtros de la lista**: quitar el PID propio, los emisores de nuestra imagen, `T == ppid(propio)`, sesiones del sistema y apps que no tengan sesión de render.
- **Autotest** invertido en §3.6, al arrancar y tras cada reapertura.
- **Fuera de alcance de la captura por proceso**: separar pestañas o ventanas de un mismo navegador; recomendar al usuario usar un navegador o perfil con `--user-data-dir` distinto para lo que vaya a traducirse. Documentar «un navegador = todas sus pestañas».
- **Efecto en ADR**: la decisión de ADR-0010 «EXCLUDE sobre el PID del núcleo» queda sustituida por INCLUDE sobre la app elegida; el humano ya lo decidió, falta el ADR (lo escribe el orquestador). Se mantienen el vigilante, el formato 16 kHz mono float32, MTA y el reloj por recuento. El volumen de sesión de la app escala el nivel capturado y silenciarla da ceros [S4 T5]: avisarlo en la interfaz.

### 4.2 Alternativas

- **A. Todo el sistema menos nosotros (EXCLUDE)**: la situación actual; mezcla Discord. Mantenerlo como modo opcional «todo el sistema» (el humano ha decidido INCLUDE como principal).
- **B. Elegir por ventana (estilo OBS)**: OBS elige por clase, título y ejecutable de ventana y toma el PID de la ventana [T]. Rechazada: el PID de una ventana UWP es `ApplicationFrameHost` (no medido), y el de un navegador no cubre varias ventanas de otra forma; las sesiones de audio dan el dato correcto y funcionan sin ventana.
- **C. Elegir por nombre de ejecutable solo, sin lista**: sirve como atajo (CLI) pero no resuelve instancias múltiples ni apps de la Store.
- **D. Antepasado más alto con la misma imagen (sokuji)**: funciona en Chrome, Edge y Discord (profundidad 1) pero según S4 falla con árboles de profundidad ≥ 2; descartada como regla general.
- **E. Cable virtual por app**: ya descartado en ADR-0005 (componentes de terceros).

### 4.3 Casos límite (resumen para la spec)

- La app no está abierta al arrancar: esperar; no capturar nada.
- La app se cierra y se reabre: reabrir con el PID nuevo; mostrar el estado.
- Varias instancias de la misma app: pedir elección; no agrupar apps con `user-data-dir` distinto.
- Navegador con varias pestañas sonando: se captura todo lo que suene en ese navegador; avisar.
- Elegir una app cuyo audio no llega (DRM, modo exclusivo, Teams): mensaje de «la app suena pero no llega audio».
- La app cambia de dispositivo de salida: la captura por proceso no depende del endpoint [D]; sin medir (T3/spike).
- App elevada (como administrador) o proceso protegido: **[SV]**, medir.
- PID reutilizado: usar siempre `(pid, create_time)`.

### 4.4 Qué medir en un spike con ctypes/comtypes

Reutilizar `loopback_ctypes.py` y el banco de S4 (tres capturas INCLUDE/EXCLUDE/ENDPOINT, detección de tono). Propuesta de mediciones, en orden de valor:

| ID | Medida | Salida esperada |
|---|---|---|
| M1 | **Navegadores con tono controlado**: Chrome, Edge y Firefox con `user-data-dir` temporal. INCLUDE(raíz), INCLUDE(servicio), INCLUDE(renderer); matar el servicio de audio; segunda instancia con otro `user-data-dir`; dos perfiles del mismo | Confirmar [M] de hoy para Chrome/Edge y rellenar Firefox (qué PID tiene la sesión, lanzador) |
| M2 | **Profundidad**: árbol sintético de tres niveles con el emisor en el nivel 2 y en el 3, más Steam real (`steam.exe` → `steamwebhelper` → `steamwebhelper`): INCLUDE en cada nivel | Confirmar «PID + hijos directos» con apps reales y validar la regla de §3.4 |
| M3 | **Reproductores**: VLC, mpv (con `mpv.com`), MPC-HC, PotPlayer (instalar con winget); PID de sesión, padre, captura INCLUDE; con y sin salida WASAPI exclusiva | Tabla de qué PID suena y qué casos se pierden |
| M4 | **Apps de la Store**: `Microsoft.ZuneMusic` aquí; Netflix, Disney+ y Prime con ayuda del humano. PID de sesión, `GetApplicationUserModelId`, relación con `ApplicationFrameHost`, nombre y clave estable | Cómo nombrar y recordar apps empaquetadas |
| M5 | **DRM (T6)**: para cada servicio y cada ruta (Edge, Chrome, app de la Store), nivel capturado por INCLUDE(`T`) frente a ENDPOINT frente al medidor de pico de la sesión | Si el audio llega mudo por proceso, por endpoint o por ninguno; si el medidor de pico sirve de diagnóstico |
| M6 | **Enumeración**: tiempo de enumerar todos los endpoints con pycaw/comtypes, cada cuánto refrescar, cuánto tarda una sesión en desaparecer o pasar a «expirada» al cerrar la app, sesiones del mismo PID en varios endpoints | Coste del sondeo y política de refresco |
| M7 | **Reinicio**: cerrar y relanzar la app objetivo; tiempo hasta detectarlo y reabrir; reutilización de PID | Tiempo de recuperación; qué se oye de menos |
| M8 | **Mezcla**: dos INCLUDE de apps distintas con tonos distintos; alineación, deriva en 5 min, CPU, comprobación del doble recuento al incluir padre e hijo | Viabilidad de «dos apps a la vez» |
| M9 | **Autoselección**: INCLUDE(PID propio), INCLUDE(padre directo), INCLUDE(redirector uv): confirmar que se oye el tono propio; autotest invertido con control positivo | Validar los filtros de §3.6 |
| M10 | **Dispositivo de salida**: app en un endpoint distinto del predeterminado; cambio de dispositivo con la captura abierta (relacionado con T3) | Confirmar que INCLUDE no depende del endpoint |
| M11 | **Elevación y PID inválidos**: INCLUDE sobre un proceso elevado o protegido (con anticheat), PID de otra sesión; error o silencio | Qué avisar al usuario |
| M12 | **Latencia INCLUDE vs EXCLUDE** (repetir T9): debería ser la misma | Confirmar 82–124 ms |

Ya medido hoy y no hace falta repetir: INCLUDE con PID inexistente activa y da ceros; dos capturas de la misma fuente quedan alineadas (desfase 0); enumeración de sesiones en todos los endpoints funciona; INCLUDE(raíz) captura Chrome, Edge y Discord.

## 5. Riesgos y preguntas abiertas

1. **Fallo silencioso con PID inválido o muerto** [M][S4]: sin error. Mitigación: validar y vigilar el proceso (§4.1).
2. **DRM sin verificar** [SV]: puede dejar mudos Netflix, Disney+ o Prime en alguna ruta. Es el riesgo de producto principal (contenido principal: series y películas). Medir en M5 antes de fijar la spec.
3. **Teams y apps parecidas** [T]: process loopback mudo pero endpoint loopback con audio. No sabemos si otras apps (juegos con voz, apps de comunicación) comparten el comportamiento. Una vía de salida sería un modo de respaldo por endpoint, pero eso vuelve a mezclar apps; decisión del humano.
4. **Navegador = todas las pestañas** [M]: no se puede aislar una pestaña. Puede sorprender al usuario.
5. **Regla de profundidad 1** [S4]: medida en la build 26200.9457; Microsoft no la documenta («árbol» en la doc). Una actualización de Windows podría cambiarla. Mitigación: autotest en el arranque, no basarse en la doc.
6. **Firefox, reproductores, apps de la Store y modo exclusivo** [SV]: no están instalados aquí.
7. **Rotación de PID en el servicio de audio del navegador** [M]: cubierto por INCLUDE(raíz); apuntar al servicio sería un error (sokuji PR 394 [T]).
8. **Elevación y anticheat** [SV]: si el proceso elegido es de mayor integridad, no sabemos si Windows deja capturarlo.
9. **Privacidad**: hoy, para probar, se abrió una captura pasiva sobre Discord (solo se calcularon rms y correlación; nada se guardó). En producción, el usuario debe saber que la captura toma el audio de la app elegida.
10. **Latencia y volumen de sesión** [S4]: silenciar la app o bajarle el volumen en el mezclador baja o anula lo capturado; la lista de la interfaz debe avisar.
11. Pregunta abierta para el humano: ¿mantener un modo «todo el sistema salvo nosotros» como alternativa explícita, o retirarlo? La investigación recomienda conservarlo (alternativa A).

## 6. Fuentes (consultadas el 2026-10-02)

Documentación de Microsoft:
- AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS: https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params
- PROCESS_LOOPBACK_MODE: https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ne-audioclientactivationparams-process_loopback_mode
- AUDIOCLIENT_ACTIVATION_PARAMS: https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_activation_params
- Application Loopback sample (README): https://github.com/microsoft/Windows-classic-samples/tree/main/Samples/ApplicationLoopback
- IAudioSessionManager2: https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nn-audiopolicy-iaudiosessionmanager2
- IAudioSessionControl2::GetProcessId: https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nf-audiopolicy-iaudiosessioncontrol2-getprocessid
- IAudioSessionControl2::GetSessionIdentifier: https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nf-audiopolicy-iaudiosessioncontrol2-getsessionidentifier
- Loopback Recording (DRM, modo exclusivo): https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording

Issues y código públicos (evidencia de terceros):
- microsoft/Windows-classic-samples #414, Teams mudo por proceso: https://github.com/microsoft/Windows-classic-samples/issues/414
- microsoft/Windows-classic-samples #319, latencia: https://github.com/microsoft/Windows-classic-samples/issues/319
- kizuna-ai-lab/sokuji PR 394 (servicio de audio del navegador, dos ventanas = una sesión): https://github.com/kizuna-ai-lab/sokuji/pull/394
- kizuna-ai-lab/sokuji PR 380 y issue 335: https://github.com/kizuna-ai-lab/sokuji/pull/380 · https://github.com/kizuna-ai-lab/sokuji/issues/335
- yusukensanta/polyrec PR 84 (antepasado con la misma imagen): https://github.com/yusukensanta/polyrec/pull/84
- thientran01/palette PR 81 (Discord se colaba; unión AUMID a PID): https://github.com/thientran01/palette/pull/81
- OBS, `win-wasapi.cpp` (elige por ventana; usa INCLUDE_TARGET_PROCESS_TREE): https://github.com/obsproject/obs-studio/blob/master/plugins/win-wasapi/win-wasapi.cpp
- OBS, guía de captura de audio de aplicación: https://obsproject.com/kb/application-audio-capture-guide
- OBS foro, Chrome abierto antes que OBS: https://obsproject.com/forum/threads/possible-issue-with-chrome-browser-being-used-as-an-application-audio-source.193082/
- OBS foro, Edge: https://obsproject.com/forum/threads/application-audio-capture-beta-is-buggy-with-edge-browser-why-obs-studio-28-1.161414/
- OBS foro, Netflix bloquea vídeo: https://obsproject.com/forum/threads/netflix-blocking-obs-studio-from-recording-video-and-sound-in-firefox-edge-and-chrome.150847
- process-audio-capture (DRM como limitación): https://github.com/tsubome/ProcessAudioCapture
- GStreamer wasapi2src (propiedades de process loopback): https://gstreamer.freedesktop.org/documentation/wasapi2/wasapi2src.html
- Chromium audio service: https://chromium.googlesource.com/chromium/src/+/main/services/audio/README.md
- Firefox, modelo de procesos: https://firefox-source-docs.mozilla.org/dom/ipc/process_model.html
- Mozilla audioipc: https://github.com/mozilla/audioipc
- Firefox, proceso lanzador (resumen de búsqueda; blog de Aaron Klotz): https://dblohm7.ca/blog/2021/01/04/2018-roundup-q2-part2/

Medidas propias de hoy (2026-10-02, scripts en la carpeta temporal de la sesión, no en el repo): enumeración de sesiones y árboles de procesos; captura pasiva INCLUDE sobre Discord (raíz, renderer, servicio de audio), Chrome (raíz y servicio de audio); Chrome y Edge con perfil temporal y tono WebAudio (INCLUDE raíz, servicio, renderers, GPU; muerte del servicio de audio); dos perfiles de Chrome en un mismo `user-data-dir`; activación con PID inexistente; alineación de dos capturas de la misma fuente. Procesos y carpetas temporales eliminados.

Internas: `spikes/audio/README.md` (S4, 2026-10-01), `docs/adr/0005-captura-y-reproduccion.md`, `docs/adr/0010-captura-propia-y-exclusion.md`, `docs/investigacion/2026-09-30-audio-windows.md`.

Notas sobre la calidad de las fuentes: los resúmenes de búsqueda web sobre DRM y sobre Firefox eran genéricos y no se usaron como evidencia; las afirmaciones sobre sokuji, polyrec y palette vienen de descripciones de PR (escritas en parte con asistentes de IA) y se trataron como secundarias.
