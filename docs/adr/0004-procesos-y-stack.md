# ADR-0004: Arquitectura de procesos y stack base

- Estado: Propuesta
- Fecha: 2026-09-30
- Decide: orquestador (con visto bueno del humano)

## Contexto
- Los motores de IA tienen dependencias incompatibles entre sí en Windows con una GPU Blackwell: PyTorch cu128/cu130 (CUDA 12.8+/13), CTranslate2 (solo CUDA 12), llama.cpp con sus propias DLL, y versiones de Python distintas (3.10–3.13).
- La captura *process loopback* de Windows excluye **un único árbol de procesos**, así que todo lo que la app ejecute tiene que colgar de un mismo proceso raíz.
- Hay que poder cambiar de motor sin rehacer el resto y repartir el trabajo entre obreros con fronteras claras.

## Decisión
1. **Núcleo en Python 3.12**, gestionado con uv (paquete `instanttraductor`, en `src/`). Se encarga de:
   - la captura y la reproducción de audio;
   - el VAD y la segmentación;
   - el planificador del pipeline (control de retraso);
   - las métricas, la configuración y la interfaz.

   **El núcleo no importa PyTorch.**
2. **Los motores pesados son procesos hijos del núcleo**: están en el mismo árbol, así que la captura los excluye. Cada uno tiene su entorno aislado:
   - **Traducción:** `llama-server` (binario de llama.cpp con CUDA) con API HTTP compatible con OpenAI.
   - **Voz:** servicio Python propio en `engines/<motor>/`, con su `pyproject.toml` y su `.venv`. Expone una API HTTP local que devuelve PCM.
   - **ASR:** dentro del proceso del núcleo mientras corra en CPU (sherpa-onnx). Si pasa a GPU con otra pila CUDA, se saca a un proceso hijo con el mismo contrato.
3. **Solo el núcleo toca dispositivos de audio.** Los motores devuelven PCM y nunca reproducen.
4. **Comunicación local:** HTTP en `127.0.0.1` con un puerto libre elegido al arrancar. JSON para el control y PCM float32 en binario para el audio.
5. **Contratos:** entre etapas hay contratos (`typing.Protocol` + `@dataclass(frozen=True)`) en `src/instanttraductor/contracts/`. Cada motor es un adaptador. Todos los tiempos van en el reloj de audio de la sesión, nunca en el del sistema.
6. **Modelos fuera del repo**, en `%LOCALAPPDATA%\InstantTraductor\models`, descargados por un comando de preparación y con su licencia anotada.

## Alternativas consideradas
- **Todo en un proceso:** choques de DLL CUDA, contención del GIL con la reproducción, y un fallo de un motor tumba la app.
- **App en C#/.NET:** el ecosistema de IA local es mucho más pobre. .NET queda como plan B solo para la capa de audio (ADR-0005).
- **Rust/Tauri:** Rust no está instalado y los motores seguirían en Python.
- **WSL2 para los motores:** complica el audio, el arranque y el despliegue. Solo se usará si un motor imprescindible no funciona en Windows.

## Consecuencias
- Positivas: dependencias y fallos aislados, motores intercambiables y fronteras naturales para los obreros (un paquete por motor).
- Negativas:
  - cada proceso con CUDA gasta ~0,3–0,5 GB de VRAM de contexto;
  - el arranque es más lento;
  - hay que gestionar el ciclo de vida de los hijos (arranque, comprobación de salud, reinicio y cierre al salir).

## Referencias
- `docs/investigacion/2026-09-30-audio-windows.md` (§3.2, §4.1)
- `docs/investigacion/2026-09-30-asr.md` (§4.4)
- `docs/investigacion/2026-09-30-traduccion-y-voz.md` (§5, riesgo 2)
