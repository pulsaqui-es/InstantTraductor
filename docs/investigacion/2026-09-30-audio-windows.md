# InstantTraductor · Investigación 01 — Capa de audio en Windows 11

- **Fecha:** 30-sep-2026 · **Equipo objetivo:** Windows 11 Pro 25H2 (build 26200), Ryzen 7 8700F, RTX 5070, auriculares USB Logitech G733, Python 3.13 / .NET SDK 10 / Node 24 instalados.
- **Alcance (actualizado por el coordinador):** el audio original se deja **sin cambios** y se mezcla con la voz en español. La app será **100 % local** y de **uso personal**, y se admiten licencias no comerciales. El ducking, el silenciado y el cable virtual quedan como notas breves (§3.3).
- **Convenciones:** las referencias `[Sn]` remiten a §6. **[sin verificar]** marca inferencias o datos que no he podido comprobar en una fuente primaria ni en el código. Nada se ha instalado. Para leer el código fuente (miniaudio.h, pyminiaudio, wasapi-rs, cpal, LiveDub, Voxis, RTT) descargué los ficheros al *scratchpad*.

---

## 1) Resumen ejecutivo

1. **Captura:** *process loopback* (`ActivateAudioInterfaceAsync` + `VAD\Process_Loopback`) en modo **`EXCLUDE_TARGET_PROCESS_TREE`** sobre el **PID raíz** de la app. Devuelve "todo lo que suena menos nosotros", sin drivers. Requiere build ≥ 20348; el PC tiene la 26200 [S2][S3].
2. **Sin realimentación:** la exclusión se aplica al **árbol de procesos**. Toda la voz en español debe sonar desde un proceso descendiente de ese PID. No vale el navegador del usuario ni un servidor lanzado aparte.
3. Esta API no tiene *mix format*: se elige el formato (p. ej. 16 kHz mono float32) y el motor lo convierte [S6][S24]. Llegan paquetes de unos 10 ms, pero **en silencio no llega nada** y hay que rellenar con ceros [S24][S40].
4. **Reproducción:** endpoint por defecto con **seguimiento automático del dispositivo** (miniaudio, NAudio 3, cpal ≥ 0.18) para que el G733 se pueda conectar y desconectar en caliente. Windows mezcla el original con la voz sin que hagamos nada.
5. **Python basta.** `pyminiaudio` 1.71 (MIT) incluye miniaudio 0.11.25, que ya implementa el *process loopback* con exclusión y el *rerouting* automático. Se activa con una subclase pequeña vía cffi [S21][S22]. Alternativa: ctypes/comtypes propio, como hacen LiveDub y Voxis.
6. **Plan B robusto:** un proceso auxiliar (*sidecar*) en C# con **NAudio 3.1** (MIT, ago–sep 2026), que trae `WithProcessLoopback(..., ExcludeTargetProcessTree)` y un reproductor con `WithDefaultDeviceStreamRouting()` [S23][S24]. .NET 10 ya está instalado.
7. **Latencia:** la capa de audio añade unas decenas de ms, despreciable frente al objetivo de 1,5–3 s.
8. **Riesgos a medir en un *spike* de 1–2 días (§5):** hijos creados después de activar la captura, cambio de dispositivo, DRM, juegos en modo exclusivo y audio espacial, y *glitches* con la GPU cargada.

---

## 2) Tablas comparativas

### 2.1 Mecanismos de captura

| Mecanismo | Requisito Windows | ¿Recaptura nuestra voz? | Formato | Sin audio sonando | Cambio de dispositivo por defecto | Efecto del volumen | Veredicto |
|---|---|---|---|---|---|---|---|
| **Endpoint loopback** (`AUDCLNT_STREAMFLAGS_LOOPBACK` sobre el render endpoint) | Vista+. Modo por eventos desde Win10 1703 [S1] | **Sí**, si la voz sale por el mismo endpoint | *Mix format* del endpoint (normalmente float32 48 kHz). Solo modo compartido [S1][S12] | No entrega paquetes [S12][S24] | Ligado al endpoint: hay que reabrirlo, o usar una librería que redirija sola [S21] | El volumen de sesión de cada app **sí** afecta. El maestro y el mute del endpoint, por defecto **no** (el *tap* es previo al volumen) [S7], aunque algunos drivers se desvían [S14][S17] | Solo como *fallback* |
| **Process loopback EXCLUDE** del árbol propio | Documentado: build 20348. En la práctica, Win10 2004 actualizado [S2][S20][S24] | **No** | Sin *mix format*: se pide el formato y el motor convierte [S6] | Tampoco entrega paquetes [S24][S40] | "No ligado a un endpoint" según Microsoft [S6]. Comportamiento real **[sin verificar]** | Sesión de la app origen: **sí** (25 % → ×0,051; mute → 0). Maestro y mute: **no** [S13] | **Principal** |
| **Process loopback INCLUDE** de una app concreta | Igual | No | Igual | Igual | Igual | Igual | Opción de interfaz: "traducir solo esta app" |
| Cable virtual (VB-CABLE) + enrutado por app | Driver: admin y reinicio [S52] | No | El del cable | — | — | — | Innecesario mientras el original vaya sin cambios |
| "Stereo Mix" de hardware | Depende de la tarjeta [S1] | Sí | — | — | — | — | Descartado |

### 2.2 Librerías (versiones comprobadas hoy en PyPI, NuGet, docs.rs o GitHub)

| Librería | Versión (fecha) | Licencia | Endpoint loopback | **Process loopback** | Reproducción | Sigue al dispositivo por defecto | Madurez y fricción |
|---|---|---|---|---|---|---|---|
| **pyminiaudio** (`miniaudio` en PyPI) | 1.71 (29-abr-2026), wheels cp310–cp314 | MIT. El núcleo miniaudio 0.11.25 es Unlicense/MIT-0 | En C sí; la API Python no lo expone | En C sí (`wasapi.loopbackProcessID/Exclude`). Accesible por cffi con una subclase **no oficial** [S21][S22] | Sí (`PlaybackDevice` con generador) | **Sí**: *rerouting* automático en reproducción y loopback [S21] | **Menor fricción en Python puro.** Depende de *internals* (`_miniaudio`, `_make_context`), así que hay que fijar la versión |
| ctypes/comtypes propio (+ definiciones de pycaw) | comtypes 1.4.17 (21-sep-2026); pycaw 20260927 (26-sep-2026) | MIT | Sí | Sí, en 200–300 líneas (patrón de LiveDub y Voxis) [S39][S40] | — | A mano (`MMNotificationClient` de pycaw) [S30] | Control total. COM a mano (hay que implementar `IAgileObject`) |
| PyAudioWPatch | 0.2.12.8 (14-ene-2026), cp38–cp314 | Apache-2.0 (fork de PyAudio, MIT) [S27] | Sí | No | Sí (PyAudio) | No (lista de dispositivos estática) | Maduro. Lo usan RTT y Speech-Translate |
| SoundCard | 0.4.6 (12-abr-2026) | BSD-3 | Sí (`include_loopback`) | No | Sí | No | Fallos WASAPI conocidos: mono "garbage", `blocksize` ignorado [S28] |
| sounddevice (PortAudio) | 0.5.6 (17-ago-2026) | MIT | No en la API de alto nivel [S29] | No | **Sí, muy madura** (`WasapiSettings(auto_convert=True)`) | No (hay que reiniciar PortAudio) | Buena **solo** para reproducción |
| process-audio-capture | 1.0.0 (3-dic-2025) | MIT | — | Sí (INCLUDE/EXCLUDE) | No | — | Graba a WAV y da el nivel; 1 estrella. **Inmadura** [S32] |
| pycaw | 20260927 | MIT | — | — | — | Notificaciones de dispositivo y sesión [S30] | Control de sesiones y volumen, `IPolicyConfig`, definiciones de `IAudioClient` |
| **NAudio 3.x** (.NET) | 3.1.0 (7-sep-2026); 3.0.0 (15-ago-2026) | MIT | Sí (`WithLoopbackCapture`) | **Sí** (`WithProcessLoopback(pid, Include/Exclude)`) [S24] | Sí (`WasapiPlayer`, *zero-copy*, MMCSS, IAudioClient3) | **Sí** (`WithDefaultDeviceStreamRouting`) | Versión mayor recién salida (riesgo de fallos tempranos). Requiere .NET 9+. Ideal como *sidecar* |
| CSCore (.NET) | 1.2.1.2 (22-oct-2017) | MS-PL | Sí | No | Sí | No | Abandonado → descartar [S60] |
| **wasapi** (Rust) | 0.24.0 (12-ago-2026) | MIT | Sí | Sí (`new_application_loopback_client(pid, include_tree)`) [S25] | Sí | Notificaciones (a mano) | Buena, pero Rust no está instalado |
| cpal (Rust) | 0.18.2 (16-ago-2026) | Apache-2.0 | Sí (flujo de entrada sobre un dispositivo de salida) [S26] | No | Sí | Sí, desde 0.18.0 [S26]. El changelog de 0.18.2 y la sección *Unreleased* se contradicen sobre el evento `DeviceChanged` → verificar | Complemento de `wasapi` para la reproducción |
| ApplicationLoopback (C++, Microsoft) | Ejemplo oficial | MIT [S5] | — | Sí | — | — | Referencia oficial |
| Naseband/ProcessLoopbackCapture (C++) | — | Dominio público (Unlicense) [S33] | — | Sí | — | — | Clase sin WIL/WRL, fácil de envolver en una DLL |

---

## 3) Detalle por opción

### 3.1 Captura del audio del sistema

#### 3.1.1 WASAPI *endpoint loopback* (clásico)
- **Cómo funciona:** se abre un `IAudioClient` de **captura** sobre el *render endpoint* con `AUDCLNT_STREAMFLAGS_LOOPBACK`. Solo admite **modo compartido** [S1]. Devuelve la mezcla *post-mix* de todas las sesiones de ese endpoint, **incluida la nuestra** [S12].
- **Formato:** el *mix format* del endpoint. Un empleado de Microsoft explica que el loopback no hace conversiones de frecuencia "no triviales" [S12]. Hoy las librerías piden otros formatos con `AUTOCONVERTPCM` (NAudio lo admite desde 2.1) [S24].
- **Modo por eventos:** antes de Win10 1703 no llegaban eventos y había que usar un flujo de *render* auxiliar. Desde 1703 está soportado [S1].
- **Silencio:** si no suena nada, **no llegan paquetes**. Lo confirman el blog de Matthew van Eerde (Microsoft), NAudio y el código de RTT ("WASAPI loopback STOPS delivering frames when no app is rendering audio") [S12][S24][S41].
- **Volumen:**
  - Por defecto el *tap* es **anterior** al volumen y al mute del endpoint. Win11 24H2 añade `AUDCLNT_STREAMOPTIONS_POST_VOLUME_LOOPBACK` para pedir el *tap* posterior y obliga a los drivers a declarar `KSPROPERTY_AUDIOLOOPBACK` [S7][S8][S9].
  - En la práctica **depende del driver**: un Sonos silencia el loopback al hacer mute [S14], y en el foro de OBS algunos dispositivos reaccionan al volumen maestro y otros no [S15][S17].
  - El volumen de **sesión** de cada app **sí** se aplica antes del loopback [S16].
- **Otros:** incluye efectos (APO) del driver [S12]. No captura apps en **modo exclusivo** ni ASIO [S12]. Un driver *trusted* no deja capturar contenido **DRM** protegido [S1].
- **Cambio de dispositivo:** el flujo está atado a un endpoint. Si cambia el dispositivo por defecto, hay que escuchar `IMMNotificationClient::OnDefaultDeviceChanged` y reabrir. Hay casos clásicos de captura muerta tras el cambio [S19]. miniaudio lo hace solo para el loopback del dispositivo por defecto [S21].
- **Para InstantTraductor:** recapturaría nuestra propia voz (mismo G733) → **no sirve como vía principal**.

#### 3.1.2 *Process loopback* (Application Loopback API)

**Pasos:**
1. Rellenar `AUDIOCLIENT_ACTIVATION_PARAMS { ActivationType = PROCESS_LOOPBACK, ProcessLoopbackParams = { TargetProcessId, PROCESS_LOOPBACK_MODE_{INCLUDE|EXCLUDE}_TARGET_PROCESS_TREE } }` y meterlo en un `PROPVARIANT` de tipo `VT_BLOB`.
2. Llamar a `ActivateAudioInterfaceAsync(L"VAD\\Process_Loopback", IID_IAudioClient, …)`.
3. `IAudioClient::Initialize(SHARED, LOOPBACK | EVENTCALLBACK | AUTOCONVERTPCM [| SRC_DEFAULT_QUALITY], …, &formatoElegido)`.
4. Obtener `IAudioCaptureClient` y hacer el bucle `GetBuffer` / `ReleaseBuffer` [S4][S5].

**Requisitos de Windows:**
- La documentación dice **Windows 10 build 20348** [S2][S3]. En `ActivateAudioInterfaceAsync` aparece "Build 20438", una errata aparente [S4].
- win-capture-audio y NAudio 3 lo declaran funcional desde **Win10 2004 (19041) actualizado** [S20][S24].
- El PC del usuario (26200) cumple en ambos casos.

**Modos** [S3]:
- `INCLUDE`: solo el proceso objetivo y sus hijos.
- `EXCLUDE`: todo excepto el proceso objetivo y sus hijos.

**Formato:**
- El dispositivo virtual **no tiene *mix format***: `GetMixFormat` e `IsFormatSupported` devuelven `E_NOTIMPL`, porque internamente es `AudioSes!CMixerClient`. Microsoft recomienda fijar el formato a mano [S6].
- Formatos que funcionan en implementaciones públicas:
  - 44,1 kHz PCM16 estéreo (ejemplo de Microsoft) [S5].
  - 44,1 kHz float estéreo (valor por defecto de NAudio) [S24].
  - 48 kHz float estéreo (LiveDub, GoofCord) [S34][S40].
  - **16 kHz mono PCM16 directamente** (Voxis) [S39].
- Conviene **float32**: no recorta si la mezcla supera 0 dBFS, y conserva la precisión si el origen está bajo de volumen [S40].
- miniaudio abre internamente el flujo a 44,1 kHz float estéreo y luego convierte con su propio remuestreador al formato pedido [S21].

**Métodos que no funcionan en este modo** (documentado en wasapi-rs) [S25]:
- `GetMixFormat`, `IsFormatSupported`, `GetDevicePeriod`, `GetCurrentPadding`.
- `GetBufferSize` devuelve valores absurdos.
- No hay `IAudioRenderClient`, `IAudioSessionControl` ni `IAudioClock`.

**`IAgileObject`:** el *completion handler* debe implementar `IActivateAudioInterfaceCompletionHandler` **e** `IAgileObject`. La documentación lo exige en versiones anteriores a Win10 [S4], y Voxis cuenta que sin él obtuvo `E_ILLEGAL_METHOD_CALL` sin más explicación [S39]. miniaudio ya lo resuelve internamente [S21].

**Temporización:**
- Funcionan tanto el modo por eventos (ejemplo de Microsoft) como el *polling* cada 4–10 ms (Voxis, LiveDub) [S5][S39][S40].
- Los paquetes son de unos **10 ms** (480 *frames* a 48 kHz) [S34].
- **Cuando no suena nada puede no llegar ningún paquete:** "no buffers are delivered while the target renders no audio" [S24]; "Windows sends nothing while all other apps are silent" [S40].
- La documentación del ejemplo dice "receives silence" [S5]. Hay que tratar los dos casos: `AUDCLNT_BUFFERFLAGS_SILENT` → ceros, y huecos → rellenar con ceros según el reloj.

**Volumen** (medido en A2DP-Windows-Bridge) [S13]:
- "The app's Volume Mixer slider scales the capture (25% → 0.051). Mute gives 0. Master volume and mute have no effect."
- Es decir, la captura es **posterior** al volumen y al mute de sesión y **anterior** al volumen maestro. Coincide con lo observado en OBS para la captura por aplicación [S16].
- En OBS se ha visto un caso raro de niveles (Spotify capturado a −20 dB) [S18]. **Conviene normalizar antes del ASR.**

**Endpoint:** "process-based loopback capture … is actually not tied to a specific audio endpoint" (Microsoft) [S6]. No hace falta un `IAudioClient` por endpoint, y en principio sobrevive a los cambios de dispositivo por defecto **[sin verificar en la práctica]**. Tampoco está claro si `EXCLUDE` mezcla streams que van a **otros** endpoints (p. ej. una app enrutada a los altavoces):
- Microsoft dice que no está ligado a un endpoint [S6].
- GoofCord lo describe como "full default-endpoint audio mix except…" [S34].
- → **Probar en el *spike*.**

**Fallos en mitad de la sesión:** Voxis los atribuye a desconectar el endpoint, a que otra app tome el dispositivo en exclusivo o a suspender y reanudar [S39]. Hace falta un *watchdog* que vuelva a activar la captura.

**No se captura:**
- Streams en modo exclusivo y ASIO (no pasan por el motor).
- Contenido DRM protegido: ProcessAudioCapture lo documenta como imposible [S32]; el efecto real con Netflix o Prime en Edge está **[sin verificar]**.
- Streams de audio espacial (`ISpatialAudioClient`): **[sin verificar]**.

**Soporte en la comunidad:**
- OBS trae la fuente *Application Audio Capture* [S16][S18]; antes existía el plugin win-capture-audio [S20].
- GStreamer tiene `wasapi2src` con los modos include/exclude-process-tree [S58].
- Hay addons de Node [S34][S35], proyectos en Rust [S37][S38] y en Python [S39][S40].

#### 3.1.3 Latencia típica
- **Captura:** el mínimo es un periodo del motor (normalmente **10 ms**, según un empleado de Microsoft en el blog de van Eerde) [S12]. En *process loopback* los paquetes también son de 10 ms [S34].
- Un búfer WASAPI de 100–200 ms **no añade latencia** si se vacía a menudo; así lo configuran Voxis y LiveDub (200 ms más *polling*) [S39][S40].
- El modo de baja latencia `IAudioClient3` **no se aplica al loopback** [S24].
- **Reproducción:** periodo del motor (unos 10 ms) más nuestro búfer (40–100 ms recomendados).
- **Total estimado de la capa de audio:** 30–150 ms **[estimación]**. Es irrelevante frente a 1,5–3 s, donde dominan el ASR, la traducción y el TTS.

#### 3.1.4 Cambio de dispositivo por defecto y conexión en caliente
- **Reproducción:** desde Win10 1607, al activar con `DEVINTERFACE_AUDIO_RENDER` vía `ActivateAudioInterfaceAsync`, WASAPI traslada el flujo al nuevo dispositivo por defecto sin código adicional (*automatic stream routing*) [S10].
  - NAudio 3 lo expone como `WithDefaultDeviceStreamRouting()` [S24].
  - miniaudio lo emula para los dispositivos por defecto: escucha `IMMNotificationClient`, para, reinicializa y reanuda [S21].
  - cpal lo hace desde 0.18.0 [S26].
  - PortAudio (sounddevice) y PyAudio(WPatch) **no**: la lista de dispositivos se fija al inicializar.
- **Captura (*process loopback*):** no debería necesitar reapertura [S6]. miniaudio la reinicializa igualmente al cambiar el dispositivo por defecto (breve hueco) [S21].
- **G733:** es un receptor USB LIGHTSPEED. No he verificado si el endpoint desaparece al apagar los auriculares, ni si G HUB expone un endpoint 7.1 **[sin verificar]**. El diseño no depende de ello (se pide el formato propio y la reproducción convierte).

### 3.2 Realimentación y aplicación multiproceso

**Mecanismo:** `EXCLUDE_TARGET_PROCESS_TREE` excluye los *render streams* del PID indicado **y de sus hijos** [S2][S3].

**Evidencia en apps multiproceso:**
- En Electron y Chromium el audio lo reproduce un proceso hijo ("Audio Service"). Excluir el PID del proceso principal de Electron lo cubre: "EXCLUDE_TARGET_PROCESS_TREE covers the whole tree, including the separate 'Audio Service' utility child" [S34].
- videorc hace lo mismo, con la exclusión "rooted at the Electron main PID" [S37].
- voice-cat usa `EXCLUDE` sobre su propio PID para eliminar su eco, e indica que el modo es **dinámico**: las apps lanzadas después sí se capturan [S36].

**Reglas de diseño para InstantTraductor:**
1. **Un único proceso raíz** (orquestador o lanzador) vivo durante toda la sesión. El resto (E/S de audio, ASR, traducción, *workers* TTS, interfaz) son **descendientes**. `multiprocessing` en Windows usa *spawn* y `subprocess.Popen` crea hijos reales, así que quedan en el árbol.
2. **El `TargetProcessId` es el PID raíz**, no necesariamente el del proceso que captura. Un proceso de captura puede excluir a su padre, y como es su hijo queda excluido también.
3. **Solo un proceso reproduce audio** (el de E/S). Los motores TTS devuelven PCM y nunca reproducen. RealtimeTTS lo permite con `muted=True` u `on_audio_chunk` [S44].
4. **Prohibido reproducir desde fuera del árbol:**
   - el navegador del usuario (interfaz Gradio o Streamlit);
   - servidores TTS arrancados a mano o como servicio;
   - servidores COM *out-of-proc* lanzados por DCOM/svchost.
   
   Si la interfaz usa WebView2 (pywebview), sus procesos cuelgan de la app, así que **deberían** estar en el árbol **[sin verificar]**.
5. **Lanzadores:**
   - El `python.exe` de un venv en Windows es un redirector que lanza el intérprete base (desde 3.7.2) [S57].
   - Los ejecutables *onefile* de PyInstaller tienen un proceso *bootloader* padre **[sin verificar en esta sesión]**.
   
   Ninguno de los dos reproduce audio, así que basta con usar el PID del intérprete que orquesta. Si el orquestador es otro ejecutable, se usa el suyo.
6. **Solo se puede excluir un árbol por flujo.** "Sistema menos dos árboles independientes" no es posible con un solo *process loopback*. Hay que organizar todo bajo una raíz.
7. **Hijos creados después de activar la captura:** lo esperable es que el motor evalúe el árbol de forma dinámica (voice-cat lo observa para otras apps [S36]), pero para nuestros propios hijos está **[sin verificar]** → prueba T1 del §5.
8. Si el proceso raíz muere o se reinicia, **reactivar** la captura, porque el PID cambia.

**Alternativas peores:**
- **Loopback del endpoint + "puerta" que pausa el ASR mientras habla el TTS:** se pierde el habla original durante ese tiempo.
- **AEC con referencia:** complejo, e inexacto por el remuestreo y las APO.
- **Voz por otro endpoint:** el usuario solo tiene el G733.

Ejemplos reales:
- RTT captura el loopback del endpoint **sin excluirse**: su propio doblaje vuelve a entrar [S41].
- LiveDub pasa automáticamente al modo "todo menos el doblaje" cuando el origen y la salida son el mismo dispositivo [S40].

**Tip de UX:** ofrecer dos modos. "Todo el sistema (excepto InstantTraductor)" usa `EXCLUDE` sobre la raíz. "Solo esta app" usa `INCLUDE` sobre el proceso raíz de la app elegida: en Chrome o Edge, el proceso *browser* principal cubre al hijo que reproduce el audio [S34]. `EXCLUDE` también traduce notificaciones, Discord, etc.

### 3.3 Modos del audio original (prioridad baja: notas para el futuro)
- **(c) Sin cambios (el elegido):** no hay que hacer nada, Windows mezcla el original con la voz.
  - Si el usuario baja la app de origen en el mezclador, **también baja lo capturado** (el volumen de sesión se aplica antes del loopback) [S13]. Por eso conviene un **AGC/normalización antes del ASR**.
  - El volumen maestro no afecta a la captura.
  - Conviene dar nombre e icono a nuestra sesión (`IAudioSessionControl::SetDisplayName`) para que el usuario equilibre la voz frente al original.
- **(a) Atenuar el original (ducking):**
  - Se hace con `ISimpleAudioVolume` (pycaw) sobre las **otras** sesiones. Así lo hacen RTT y Voxis [S39][S41].
  - Como la atenuación afecta a lo capturado, hay que **compensar la ganancia en float32**. LiveDub baja las otras apps a ~1 % y re-amplifica la captura [S40].
  - No hay que abrir nuestra voz como stream de **comunicaciones**: Windows atenúa por defecto un 80 % los demás streams (pestaña *Communications*) [S11].
- **(b) Silenciar el original y seguir capturando:**
  - El mute de sesión da 0 en la captura [S13]. Hace falta **enrutar la app a otro endpoint**:
    - VB-CABLE: *donationware*, instalación como admin y reinicio; el uso comercial y la redistribución requieren licencia [S52].
    - Una salida física sin uso.
  - El cambio por app se hace a mano (Configuración → Mezclador) o con la API **no documentada** `IAudioPolicyConfigFactory::SetPersistedDefaultAudioEndpoint(pid, flow, role, deviceId)`. La usan EarTrumpet (MIT, con "Excluded Entities") y SoundSwitch (GPL-3.0) [S53][S54].

### 3.4 Librerías: madurez, mantenimiento y fricción

**Python**
- **pyminiaudio 1.71** (MIT, cp310–cp314, incluye miniaudio 0.11.25) [S22]:
  - La API alta (`CaptureDevice`) usa siempre `ma_device_type_capture`.
  - La definición cffi **sí** expone `ma_device_type_loopback` y, dentro de `ma_device_config.wasapi`, `loopbackProcessID` y `loopbackProcessExclude`. Lo comprobé en `build_ffi_module.py` [S22].
  - El núcleo C implementa el *process loopback* (`VAD\Process_Loopback`), el `IAgileObject` y el *rerouting* automático de reproducción y loopback (`noAutoStreamRouting = false` por defecto) [S21].
  - Detalles: el process loopback **requiere `pDeviceID = NULL`** [S21]. El *callback* corre en el hilo de audio de miniaudio **con el GIL**. `PlaybackDevice` acepta un generador que recibe el nº de *frames* y devuelve bytes, `array` o numpy [S22].
  - **Riesgo:** depende de detalles internos → fijar la versión y aislarlo tras una interfaz propia.
- **ctypes/comtypes + pycaw (implementación propia):**
  - LiveDub usa **ctypes puro** con vtables COM, `EXCLUDE os.getpid()`, 48 kHz float estéreo y `AUTOCONVERTPCM | SRC_DEFAULT_QUALITY`, *polling* cada 10 ms y relleno de huecos con ceros [S40].
  - Voxis usa **comtypes + pycaw** (definiciones de `IAudioClient`), 16 kHz mono PCM16, una `deque(maxlen)` que descarta lo más antiguo y un hilo de captura mínimo [S39].
  - Esas son **ideas**. El código de LiveDub (sin licencia) y el de Voxis ("all rights reserved") **no se pueden copiar**.
  - La implementación propia cuesta unas 250 líneas y da control total.
- **PyAudioWPatch 0.2.12.8** (Apache-2.0): loopback de endpoint maduro, sin *process loopback* [S27].
- **SoundCard 0.4.6** (BSD-3): loopback de endpoint con problemas conocidos en WASAPI [S28].
- **sounddevice 0.5.6** (MIT): la mejor opción clásica para **reproducir** (PortAudio, `WasapiSettings(auto_convert=True)`) [S29]. No sigue al dispositivo por defecto; hay que reiniciar PortAudio (con la API privada `sd._terminate()`/`sd._initialize()`) **[workaround comunitario, sin verificar en esta sesión]**.
- **pycaw 20260927** (MIT, Python ≥ 3.10) [S30]:
  - `AudioUtilities` para sesiones y volúmenes (`ISimpleAudioVolume`, `IAudioEndpointVolume`);
  - `callbacks.MMNotificationClient` (`OnDefaultDeviceChanged`, `OnDeviceAdded/Removed/StateChanged`) y `AudioSessionEvents`;
  - `IPolicyConfig` (no documentada);
  - definiciones de `IAudioClient`.
- **process-audio-capture 1.0.0** (MIT): *process loopback* INCLUDE/EXCLUDE, pero pensado para grabar WAV con un *callback* de nivel. Muy nuevo, 1 estrella [S32].
- **Nota sobre la versión de Python:** RealtimeSTT solo prueba con 3.11/3.12 ("Python 3.13 and newer are not release targets") [S43], y buzz-captions exige 3.12 [S46]. Las librerías de audio recomendadas funcionan con 3.13 y 3.14 (pyminiaudio y PyAudioWPatch tienen wheels cp313/cp314; sounddevice es py3).

**.NET**
- **NAudio 3.0.0** (15-ago-2026) / **3.1.0** (7-sep-2026), MIT, requiere net9.0+ [S23]. Novedades:
  - `WasapiRecorder` y `WasapiPlayer` con *builders*;
  - "per-process loopback capture", "automatic stream routing that follows the default endpoint", IAudioClient3, MMCSS, búferes *zero-copy*;
  - compatibilidad Native AOT en NAudio.Wasapi.
- Documentación del *process loopback*: `WithProcessLoopback((uint)pid, ProcessLoopbackMode.ExcludeTargetProcessTree)`, se construye con `BuildAsync()`, formato por defecto 44,1 kHz float estéreo (`WithFormat` para cambiarlo) y "no buffers are delivered while the target renders no audio" [S24].
- `WasapiPlayer` en modo compartido convierte al *mix format* ("any reasonable WaveFormat will play") y admite `WithDefaultDeviceStreamRouting()` [S24].
- **Riesgo:** versión mayor recién publicada, con 3.1.1-preview en curso.
- CSCore: sin versiones desde 2017, MS-PL → descartar [S60].

**Rust**
- **wasapi 0.24.0** (MIT): `AudioClient::new_application_loopback_client(process_id, include_tree)`, con el ejemplo `record_application` [S25]. **Ojo:** el comentario del código dice que `false` = "solo el proceso", pero el código lo traduce a `PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE` (verificado en `api.rs`).
- **cpal 0.18.2** (Apache-2.0): loopback de endpoint (flujo de entrada sobre un dispositivo *eRender*) y *rerouting* de flujos por defecto desde 0.18.0. **No** tiene *process loopback* [S26]. El changelog tiene idas y vueltas: en 0.18.2 dejó de emitir `DeviceChanged`, y en *Unreleased* se revierte por "misinformed" → verificar el comportamiento real si se elige Rust.
- Rust no está instalado en el PC del usuario.

**C/C++**
- Ejemplo oficial **ApplicationLoopback** (MIT) [S5].
- **Naseband/ProcessLoopbackCapture** (dominio público) [S33].
- **miniaudio** (C, *single-header*, Unlicense/MIT-0) [S21].
- Cualquiera se puede compilar como DLL y llamarse con ctypes, pero hace falta MSVC, que no está confirmado.

**¿Qué da menos fricción para "process loopback + control de sesiones + reproducción en streaming"?**
- **Todo en Python:** `pyminiaudio` (captura EXCLUDE y reproducción con *rerouting*) + `pycaw` (sesiones y notificaciones). Tres paquetes con wheels, sin compilar nada.
- **Nativo:** **NAudio 3** cubre las tres cosas en una sola librería, y .NET 10 ya está instalado.

### 3.5 Reproducción de la voz
- **Streaming:**
  - Reproductor de tipo *pull* por *callback* que lee de un *ring buffer* float32 y rellena con ceros si falta audio (miniaudio ya pre-silencia la salida [S21]).
  - Búfer de salida de 40–100 ms (p. ej. `buffersize_msec = 20–30` × 3 periodos en pyminiaudio [S22]).
  - La E/S de audio debe ir **en un proceso separado del ML**: el *callback* Python necesita el GIL, y un hilo Python ocupado provoca cortes.
- **Remuestreo:**
  - Recomendación: flujo de salida **fijo a 48 kHz float32**, y remuestrear cada segmento TTS (Piper 22,05 kHz; Kokoro/XTTS 24 kHz) con **soxr** (LGPL-2.1+; 1.1.0, may-2026) o **samplerate** (MIT; 0.2.4, mar-2026) [S56]. Así cambiar de motor TTS no obliga a reabrir el dispositivo.
  - Alternativa: abrir a la frecuencia del TTS y dejar que convierta WASAPI (`AUTOCONVERTPCM | SRC_DEFAULT_QUALITY`) o miniaudio. Al usar una frecuencia distinta de la nativa, miniaudio desactiva el modo de baja latencia salvo con `noAutoConvertSRC` [S21]; aquí no importa.
- **Cola:**
  - Cada segmento lleva metadatos (instante del habla original, idioma, duración).
  - Se mide el **retraso** = ahora − instante original.
  - Por encima de un umbral (p. ej. 2,5 s), acelerar los segmentos siguientes. Por encima de un límite duro (p. ej. 5 s), descartar o condensar los pendientes.
  - Fundidos de 5–10 ms entre segmentos y nunca dos segmentos solapados.
  - Normalizar la sonoridad (pyloudnorm, MIT) para que la voz se entienda sobre el original.
- **Acelerar sin cambiar el tono:**
  1. **Primero, la velocidad nativa del TTS:** Piper `length_scale = 1/velocidad`. RTT usa `velocidad = base + 0,15·(segmentos pendientes)`, con tope 1,45 [S41]. Kokoro y XTTS exponen un parámetro `speed` **[sin verificar en esta sesión]**.
  2. **Estiramiento temporal por segmento:**
     - `pedalboard.time_stretch` (Rubber Band; pedalboard 0.9.25, **GPL-3**, wheels cp310–cp315) [S55];
     - `pylibrb` (GPL-2, 2023);
     - `pyrubberband` (envoltorio ISC que llama a la CLI de Rubber Band, GPL o comercial);
     - WSOLA con `audiotsm` (MIT, sin mantenimiento desde 2017);
     - `audiostretchy` (BSD-3, TDHS, 2023);
     - `pytsmod` (GPL-3, requiere Python < 3.13) [S56].
     
     Al ser uso personal, la GPL no es problema.
  3. Límite de inteligibilidad orientativo: 1,3–1,5×. Por encima, es mejor resumir o descartar **[criterio]**.
- **Conexión en caliente y cambio de dispositivo por defecto:**
  - Seguimiento automático (miniaudio, NAudio `WithDefaultDeviceStreamRouting`, cpal 0.18).
  - `MMNotificationClient` de pycaw para avisar en la interfaz y registrar el evento.
  - Con sounddevice o PyAudio habría que reinicializar a mano.
- **Categoría del stream:** normal (Media/Other). Evitar el rol o la categoría de comunicaciones, que dispara la atenuación automática de Windows [S11].

### 3.6 Proyectos open source parecidos

| Proyecto | Stack | Licencia | Captura en Windows | Anti-realimentación | Qué aprovechar | Notas |
|---|---|---|---|---|---|---|
| **Real-Time-Translator** (HaiHoang-AI) [S41] | Python 3.11, PySide6, Moonshine/faster-whisper, NLLB/Ollama/Gemini, Piper | MIT. Piper es GPL-3; los pesos de NLLB son CC-BY-NC | PyAudioWPatch (loopback del endpoint por defecto) + PyAV a 16 kHz | **Ninguna**: su doblaje vuelve a entrar | Recuperación del retraso con `length_scale`, *ducking* con pycaw excluyendo su PID, *overlay* | Muy parecido a InstantTraductor. Creado en jul-2026, 5★ |
| **LiveDub** (yusufkaanklc) [S40] | Python, PySide6, sounddevice + soundcard + soxr. Motores en la nube (Gemini/OpenAI Realtime) | **Sin licencia** (todos los derechos reservados) | *Process loopback* EXCLUDE (ctypes puro, 48 kHz float), loopback con soundcard o VB-CABLE | EXCLUDE `os.getpid()`, detección de riesgo de realimentación, *ducking* a ~1 % con compensación | Solo ideas | Creado el 29-sep-2026 |
| **VoxisLive** (DavutAkca) [S39] | Python, comtypes, pycaw, Silero VAD. Gemini | "All rights reserved", extracto de solo lectura. El artículo de DEV.to hablaba de PolyForm NC; manda el LICENSE | *Process loopback* EXCLUDE a 16 kHz mono PCM16 | EXCLUDE del propio PID y *ducking* de sesión | Solo ideas (lo de `IAgileObject`, la cola con descarte) | — |
| **LiveCaptions-Translator** [S42] | C# / .NET 8 (WPF) | Apache-2.0 | No captura: lee Live Captions de Win11 22H2+ | N/A (sin TTS) | Idea de un ASR alternativo en inglés | 3,8k★, activo (ago-2026) |
| **RealtimeSTT** [S43] | Python | MIT | Micrófono o `use_microphone=False` + audio externo (PCM16 mono 16 kHz) | N/A | Motor ASR que se alimenta con nuestra captura | 10k★. Solo 3.11/3.12 |
| **RealtimeTTS** [S44] | Python | MIT (cada motor con su licencia) | Reproduce con PyAudio. `muted=True` / `on_audio_chunk` | Reproducir desde nuestro árbol | Motores TTS en streaming (Kokoro, Piper, XTTS…) | Activo (27-sep-2026) |
| WhisperLive [S45] | Python cliente/servidor | MIT | Cliente: micrófono con PyAudio | — | Servidor ASR en streaming | — |
| Buzz [S46] | Python / Qt | MIT | Micrófono y archivos | — | Poco relevante | Requiere Python 3.12 |
| Speech-Translate [S47] | Python | MIT | "Speaker input" en Win8+ (loopback) | — | Flujo e interfaz | Sin TTS |
| OBS LocalVocal [S48] | C++ (plugin de OBS), whisper.cpp | GPL-2.0 | Fuentes de OBS (incluida *Application Audio Capture*) | — | Referencia de whisper.cpp en streaming | — |
| win-capture-audio [S20] | C++ (plugin de OBS) | GPL-2.0 | *Process loopback* INCLUDE | — | Requisitos y fallos típicos | Integrado después en OBS |
| Sokuji [S49] | Escritorio (Electron) y extensiones | AGPL-3.0 | Micrófono y audio del sistema | Cancelación de eco (Web Audio) | Ideas de interfaz | Sobre todo en la nube |
| Meetily [S50] | Tauri / Rust | MIT | Micrófono y sistema a la vez, con *ducking* y prevención de *clipping* | — | Código Rust de captura | — |
| my-translator [S51] | Tauri 2 / Rust | MIT | WASAPI (audio del sistema) | Desactiva el TTS en modo bidireccional | — | En la nube |
| GoofCord wasapi-loopback [S34] / application-loopback [S35] | Addons de Node (MIT) | MIT | *Process loopback* EXCLUDE (raíz = main de Electron) / INCLUDE | EXCLUDE del árbol | Prueba de que funciona en apps multiproceso | — |

**Qué reutilizar de verdad:**
- **Código:** RealtimeSTT y RealtimeTTS (MIT), como motores detrás de nuestra capa de audio.
- **Patrones:**
  - de RTT (MIT): recuperación del retraso con `length_scale` y *ducking* con pycaw;
  - de LiveDub y Voxis (solo ideas): relleno de huecos, float32 más compensación y cola con descarte de lo más antiguo.
- **Referencias:** el ejemplo de Microsoft y ProcessLoopbackCapture (dominio público).

---

## 4) Recomendación para InstantTraductor

### 4.1 Principal: E/S de audio en Python, dentro del árbol de la app

```
[Proceso raíz / orquestador  (PID R)]  ← vive toda la sesión; su PID se pasa al proceso de audio
   ├─ [audio_io]  (único proceso que toca WASAPI)
   │     ├─ CAPTURA: process loopback EXCLUDE árbol(R) → 16 kHz mono float32 → AGC → ring buffer → ASR
   │     └─ SALIDA : cola de segmentos TTS → remuestreo a 48 kHz f32 → PlaybackDevice(dispositivo por defecto, rerouting auto)
   ├─ [asr]  (GPU)   ← recibe PCM por memoria compartida/cola
   ├─ [mt]
   └─ [tts]  (GPU)   → devuelve PCM al audio_io; NUNCA reproduce
```
- **Captura:**
  - `pyminiaudio` con una subclase (boceto abajo), en float32. Pedir 16 kHz mono (lo convierte miniaudio) o 48 kHz y convertir con soxr.
  - Relleno de huecos por reloj.
  - *Watchdog*: sin datos y con error, o tras suspender el equipo → reactivar.
  - Cola acotada que descarta lo más antiguo.
- **Salida:**
  - `pyminiaudio.PlaybackDevice` sin `device_id`, para que miniaudio siga al dispositivo por defecto.
  - 48 kHz float32, periodo de 20–30 ms.
  - La política de cola y aceleración del §3.5.
- **Eventos:** `pycaw.callbacks.MMNotificationClient` para la interfaz y los registros. pycaw también sirve para nombrar nuestra sesión en el mezclador.
- **Interfaz de captura:** "Todo el sistema (excepto InstantTraductor)" (EXCLUDE) o "Solo esta app" (INCLUDE).
- **Plan B dentro de Python:** si la subclase de pyminiaudio da problemas, se sustituye la captura por una implementación ctypes/comtypes propia, con el patrón de LiveDub y Voxis (unas 250 líneas), manteniendo la misma interfaz `AudioSource`/`AudioSink`.

Boceto (**no probado**; usa *internals* de pyminiaudio 1.71, así que hay que fijar la versión):

```python
import miniaudio
from _miniaudio import ffi, lib

class ExcludeTreeLoopback(miniaudio.CaptureDevice):
    """Todo el audio del sistema salvo el árbol de procesos root_pid (process loopback)."""
    def __init__(self, root_pid: int, sample_rate=16000, nchannels=1, period_ms=20):
        miniaudio.AbstractDevice.__init__(self)
        self.format = miniaudio.SampleFormat.FLOAT32
        self.sample_width = miniaudio.width_from_format(self.format)
        self.nchannels, self.sample_rate, self.buffersize_msec = nchannels, sample_rate, period_ms
        self._ffi_handle = ffi.new_handle(self)
        cfg = lib.ma_device_config_init(lib.ma_device_type_loopback)
        cfg.sampleRate = sample_rate
        cfg.capture.format = self.format.value
        cfg.capture.channels = nchannels
        cfg.capture.pDeviceID = ffi.NULL            # obligatorio para process loopback
        cfg.wasapi.loopbackProcessID = root_pid
        cfg.wasapi.loopbackProcessExclude = True    # -> EXCLUDE_TARGET_PROCESS_TREE
        cfg.periodSizeInMilliseconds = period_ms
        cfg.pUserData = self._ffi_handle
        cfg.dataCallback = lib._internal_data_callback
        cfg.stopCallback = lib._internal_stop_callback
        self._devconfig = cfg
        self.callback_generator = None
        self._context = self._make_context([miniaudio.Backend.WASAPI])
        if lib.ma_device_init(self._context, ffi.addressof(self._devconfig), self._device) != lib.MA_SUCCESS:
            raise miniaudio.MiniaudioError("process loopback no disponible")
# Uso: gen = consumidor(); next(gen); ExcludeTreeLoopback(ROOT_PID).start(gen)
# (el generador recibe array('f'); debe copiar a un ring buffer sin bloquear)
```

**Motivos:**
- Un solo lenguaje con el resto del *pipeline*.
- Sin drivers ni compilación.
- Las tres piezas críticas (exclusión por árbol, conversión de formato y seguimiento del dispositivo) las resuelve **código C maduro** (miniaudio) y no Python.
- La latencia de la capa (decenas de ms) cabe de sobra en el presupuesto.

### 4.2 Alternativa A (la más robusta): *sidecar* C# con NAudio 3.1
- Un `audio-sidecar.exe` (.NET 10, opcionalmente Native AOT), **lanzado como hijo** del orquestador, hace la captura y la reproducción.
- IPC con Python por stdin/stdout con tramas binarias o *named pipes*. El PCM a 16 kHz mono float32 son unos 64 KB/s.
- Se elige si aparecen cortes con la GPU al 100 % o por el GIL, o si se quiere MMCSS y un COM tipado sin trucos.

Boceto con los nombres de la documentación de NAudio 3 [S24] (no probado):

```csharp
await using var rec = await new WasapiRecorderBuilder()
    .WithProcessLoopback((uint)rootPid, ProcessLoopbackMode.ExcludeTargetProcessTree)
    .WithFormat(WaveFormat.CreateIeeeFloatWaveFormat(16000, 1))
    .BuildAsync();
rec.DataAvailable += (buffer, flags, devicePos, qpcPos) => stdout.Write(buffer);  // copiar: el span solo vale en el callback
rec.StartRecording();

await using var player = await new WasapiPlayerBuilder()
    .WithDefaultDeviceStreamRouting()   // sigue al dispositivo por defecto (Win10 1607+)
    .WithLatency(60)
    .BuildAsync();
player.Init(bufferedTtsProvider);       // p. ej. BufferedWaveProvider alimentado desde Python
player.Play();
```

### 4.3 Otras alternativas
- **Rust** (`wasapi` 0.24 para la captura EXCLUDE + `cpal` 0.18 para la reproducción con *rerouting*): binario pequeño y sin runtime, pero exige instalar Rust.
- **C++:** DLL basada en el ejemplo de Microsoft o en ProcessLoopbackCapture (dominio público), llamada con ctypes. Máximo control, más código y exige MSVC.
- **GStreamer `wasapi2src`** (LGPL), con los modos include/exclude-process-tree [S58]. Pesado de desplegar en Windows con Python.

### 4.4 Descartes
- **Loopback del endpoint como vía principal:** recaptura nuestra voz. Queda solo como diagnóstico o *fallback*.
- **Cable virtual:** innecesario con el original sin cambios.
- **CSCore:** abandonado.
- **process-audio-capture:** inmaduro y orientado a WAV.
- **sounddevice para capturar:** no ofrece loopback en su API. Sí vale para reproducir si se prefiere a miniaudio, aunque entonces hay que implementar a mano el seguimiento del dispositivo.

---

## 5) Riesgos y preguntas abiertas

**Riesgos:**
1. **Exclusión incompleta:** audio reproducido fuera del árbol (navegador, servicio, servidor COM) → realimentación. Mitigación: reglas del §3.2 y prueba automática al arrancar (tono desde `audio_io` y comprobación de que la captura no lo contiene).
2. **Sin paquetes en silencio:** confunde al VAD y a los *timestamps*. Mitigación: relleno por reloj. Hay que comprobar si los `qpcPosition` de `GetBuffer` son fiables en *process loopback* (IAudioClock no está disponible [S25]) **[sin verificar]**.
3. **Nivel de captura atado al volumen de sesión de la app de origen** [S13] → AGC y aviso en la interfaz.
4. **Contenido no capturable:** DRM, juegos en modo exclusivo o ASIO, y quizá audio espacial → mensaje en la interfaz de "sin audio del origen".
5. **Fallos tras suspender, desconectar el dispositivo o que otra app lo tome en exclusivo** [S39] → *watchdog* y reactivación.
6. **GIL y carga de GPU:** cortes en el *callback* de reproducción → proceso de audio aislado, búfer de 60–100 ms o *sidecar* nativo.
7. **Dependencia de detalles internos de pyminiaudio** → fijar la versión, pruebas y fallback a ctypes.
8. **NAudio 3 muy reciente** (ago/sep-2026) → fijar la versión si se elige el *sidecar*.
9. **Versiones de Python:** RealtimeSTT y Buzz no soportan 3.13 → decisión global de la app (probablemente 3.12).

**Spike propuesto (1–2 días, en el PC del usuario):**
- **T1** Autoexclusión: tono desde `audio_io`, desde un hijo creado **antes** y otro **después** de activar la captura, y desde un nieto. Esperado: nada en la captura.
- **T2** Otros endpoints: con `EXCLUDE` activo, enrutar una app a otro dispositivo (salida HDMI/DP de la RTX o un Realtek) y ver si se captura.
- **T3** Hot-plug: apagar y encender el G733, desenchufar el receptor, cambiar el dispositivo por defecto. Medir la continuidad de la captura y de la reproducción.
- **T4** Silencio: ¿llegan paquetes `SILENT` o no llega nada? Validar el relleno.
- **T5** Niveles: repetir en este PC la medición de volumen de sesión y maestro frente a la captura [S13]. Calibrar el AGC.
- **T6** DRM: Netflix, Prime y Disney+ en Edge y Chrome, y la app de Netflix.
- **T7** Audio espacial (Windows Sonic / DTS de G HUB) y un juego en modo exclusivo.
- **T8** Carga: ASR y TTS en la GPU al 100 % durante 30 min. Contar *underruns* y *glitches*.
- **T9** Latencia: clic en el origen → marca en la captura; y segmento TTS → salida (grabando con un micrófono externo).
- **T10** Suspender y reanudar, y reiniciar el servicio `Audiosrv`.

**Preguntas abiertas:**
- ¿Qué tecnología de interfaz? Una WebView2 propia quedaría dentro del árbol; una web en el navegador del usuario **no**.
- ¿Se ofrece "solo esta app" (INCLUDE) desde la v1?
- ¿`EXCLUDE` incluye notificaciones del sistema que no conviene traducir? Si molestan, se usa INCLUDE o se filtra por VAD o idioma.

---

## 6) Fuentes

- [S1] Loopback Recording (Microsoft Learn): https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
- [S2] AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS: https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params
- [S3] PROCESS_LOOPBACK_MODE: https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ne-audioclientactivationparams-process_loopback_mode
- [S4] ActivateAudioInterfaceAsync: https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-activateaudiointerfaceasync
- [S5] ApplicationLoopback sample: https://github.com/microsoft/Windows-classic-samples/tree/main/Samples/ApplicationLoopback · código: https://raw.githubusercontent.com/microsoft/Windows-classic-samples/main/Samples/ApplicationLoopback/cpp/LoopbackCapture.cpp · ficha: https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/ · licencia MIT: https://github.com/microsoft/Windows-classic-samples/blob/main/LICENSE
- [S6] Microsoft Q&A, GetMixFormat E_NOTIMPL en process loopback: https://learn.microsoft.com/en-us/answers/questions/1125409/loopbackcapture-(-activateaudiointerfaceasync-with (también https://learn.microsoft.com/en-us/answers/a/1183153)
- [S7] AUDCLNT_STREAMOPTIONS (POST_VOLUME_LOOPBACK): https://learn.microsoft.com/en-us/windows/win32/api/audioclient/ne-audioclient-audclnt_streamoptions
- [S8] KSPROPERTY_AUDIOLOOPBACK: https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/ksproperty-audioloopback
- [S9] AUDIOLOOPBACK_TAPPOINT_TYPE: https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ksmedia/ne-ksmedia-audioloopback_tappoint_type
- [S10] Automatic Stream Routing: https://learn.microsoft.com/en-us/windows/win32/coreaudio/automatic-stream-routing
- [S11] Default Ducking Experience: https://learn.microsoft.com/en-us/windows/win32/coreaudio/stream-attenuation
- [S12] Matthew van Eerde, "WASAPI loopback capture" (archivo, con comentarios de Microsoft): https://learn.microsoft.com/en-us/archive/blogs/matthew_van_eerde/sample-wasapi-loopback-capture-record-what-you-hear
- [S13] A2DP-Windows-Bridge PR #26 (medición de volumen en process loopback): https://github.com/SeiyaFunaokaJP/A2DP-Windows-Bridge/pull/26
- [S14] RoomRelay issue #27 (el mute de un driver silencia el loopback): https://github.com/guicn555/RoomRelay/issues/27
- [S15] CSCore issue #86 (el loopback depende del volumen del sistema según el equipo): https://github.com/filoe/cscore/issues/86
- [S16] Foro de OBS, el volumen por app afecta a la captura: https://obsproject.com/forum/threads/windows-and-obs-audio-capture.111756/
- [S17] Foro de OBS, dependencia del dispositivo: https://obsproject.com/forum/threads/obs-desktop-audio-capturing-audio-at-full-volume-when-using-certain-device-even-when-muted-from-windows.191042
- [S18] Foro de OBS, Spotify a −20 dB con Application Audio Capture: https://obsproject.com/forum/threads/spotify-maxes-at-20db.163053
- [S19] Foro de OBS, la captura se detiene al cambiar el dispositivo por defecto: https://obsproject.com/forum/threads/stops-recording-audio-when-os-default-audio-device-changes.107230
- [S20] win-capture-audio (README y licencia GPL-2.0): https://github.com/bozbez/win-capture-audio
- [S21] miniaudio (miniaudio.h 0.11.25, licencia): https://github.com/mackron/miniaudio · https://raw.githubusercontent.com/mackron/miniaudio/master/miniaudio.h
- [S22] pyminiaudio: https://pypi.org/project/miniaudio/ · https://github.com/irmen/pyminiaudio (miniaudio.py, build_ffi_module.py)
- [S23] NAudio en NuGet: https://www.nuget.org/packages/NAudio · releases: https://github.com/naudio/NAudio/releases · v3.0.0: https://github.com/naudio/NAudio/releases/tag/v3.0.0 · issue #878: https://github.com/naudio/NAudio/issues/878
- [S24] Documentación de NAudio 3: https://raw.githubusercontent.com/naudio/NAudio/HEAD/Docs/WasapiRecorder.md · https://raw.githubusercontent.com/naudio/NAudio/HEAD/Docs/WasapiPlayer.md · https://github.com/naudio/NAudio/blob/master/Docs/WasapiLoopbackCapture.md
- [S25] wasapi-rs: https://docs.rs/wasapi/latest/wasapi/ · https://docs.rs/wasapi/latest/wasapi/struct.AudioClient.html · https://github.com/HEnquist/wasapi-rs (src/api.rs)
- [S26] cpal: https://docs.rs/cpal/latest/cpal/ · CHANGELOG: https://github.com/RustAudio/cpal/blob/master/CHANGELOG.md · PR #754: https://github.com/RustAudio/cpal/pull/754 · src/host/wasapi/device.rs
- [S27] PyAudioWPatch: https://github.com/s0d3s/PyAudioWPatch · https://pypi.org/project/PyAudioWPatch/
- [S28] SoundCard: https://github.com/bastibe/SoundCard · https://pypi.org/project/SoundCard/
- [S29] python-sounddevice: https://python-sounddevice.readthedocs.io/en/latest/api/platform-specific-settings.html · https://python-sounddevice.readthedocs.io/en/latest/version-history.html · https://github.com/spatialaudio/python-sounddevice/issues/281
- [S30] pycaw: https://github.com/AndreMiras/pycaw · https://pypi.org/project/pycaw/
- [S31] comtypes: https://pypi.org/project/comtypes/
- [S32] ProcessAudioCapture / process-audio-capture: https://github.com/tsubome/ProcessAudioCapture · https://pypi.org/project/process-audio-capture/
- [S33] Naseband/ProcessLoopbackCapture: https://github.com/Naseband/ProcessLoopbackCapture
- [S34] thomas-quant/wasapi-loopback (GoofCord): https://github.com/thomas-quant/wasapi-loopback
- [S35] WerdoxDev/application-loopback: https://github.com/WerdoxDev/application-loopback
- [S36] voice-cat, commit "real native exclude + self-echo removal": https://code.iamtalon.me/Talon/voice-cat/commit/5e18dfa1c9d50c33c3123427591de4d688f3141d?files=docs
- [S37] videorc PR #478: https://github.com/TheOrcDev/videorc/pull/478
- [S38] HornScribe PR #135: https://github.com/ka0923s-a11y/HornScribe/pull/135
- [S39] VoxisLive: artículo https://dev.to/davutakca/translating-windows-system-audio-in-real-time-driverless-with-no-virtual-cable-2842 · repositorio y LICENSE: https://github.com/DavutAkca/voxislive
- [S40] LiveDub: https://github.com/yusufkaanklc/livedub (livedub/audio/process_loopback.py, requirements.txt)
- [S41] Real-Time-Translator: https://github.com/HaiHoang-AI/Real-Time-Translator (rtt/audio.py, rtt/dub.py, rtt/app.py)
- [S42] LiveCaptions-Translator: https://github.com/SakiRinn/LiveCaptions-Translator
- [S43] RealtimeSTT: https://github.com/KoljaB/RealtimeSTT · https://pypi.org/project/RealtimeSTT/
- [S44] RealtimeTTS: https://github.com/KoljaB/RealtimeTTS · https://pypi.org/project/RealtimeTTS/
- [S45] WhisperLive: https://github.com/collabora/WhisperLive
- [S46] Buzz: https://github.com/chidiwilliams/buzz · https://pypi.org/project/buzz-captions/
- [S47] Speech-Translate: https://github.com/Dadangdut33/Speech-Translate
- [S48] OBS LocalVocal: https://github.com/locaal-ai/obs-localvocal
- [S49] Sokuji: https://github.com/kizuna-ai-lab/sokuji
- [S50] Meetily: https://github.com/Zackriya-Solutions/meeting-minutes
- [S51] my-translator: https://github.com/phuc-nt/my-translator
- [S52] VB-CABLE: https://vb-audio.com/Cable/
- [S53] EarTrumpet (IAudioPolicyConfigFactory.cs, LICENSE): https://github.com/File-New-Project/EarTrumpet
- [S54] SoundSwitch (GPL-3.0): https://github.com/Belphemur/SoundSwitch
- [S55] pedalboard.time_stretch: https://spotify.github.io/pedalboard/reference/pedalboard.html · https://pypi.org/project/pedalboard/
- [S56] PyPI (versiones y licencias comprobadas el 30-sep-2026): https://pypi.org/project/soxr/ · https://pypi.org/project/samplerate/ · https://pypi.org/project/audiotsm/ · https://pypi.org/project/pyrubberband/ · https://pypi.org/project/pylibrb/ · https://pypi.org/project/audiostretchy/ · https://pypi.org/project/pytsmod/ · https://pypi.org/project/piper-tts/ · https://pypi.org/project/kokoro/ · https://pypi.org/project/pyloudnorm/ · https://pypi.org/project/resampy/
- [S57] Python venv (redirector en Windows): https://docs.python.org/3/library/venv.html
- [S58] GStreamer wasapi2src (process loopback; no revisado en detalle): https://gstreamer.freedesktop.org/documentation/wasapi2/wasapi2src.html · https://gitlab.freedesktop.org/gstreamer/gstreamer/-/issues/1278
- [S59] Microsoft ApplicationLoopback, ficha de Microsoft Samples: https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/
- [S60] CSCore en NuGet: https://www.nuget.org/packages/CSCore · licencia MS-PL: https://github.com/filoe/cscore/blob/master/license.md
