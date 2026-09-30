# Contrato: línea de comandos

Ejecutable: `instanttraductor` (script de consola del paquete) o `python -m instanttraductor`. Los subcomandos y las opciones van en español. Toda la salida para personas va en español; los ficheros de datos van en UTF-8.

## `instanttraductor directo`
Traduce en directo lo que suena en el PC (US1).

| Opción | Efecto |
|---|---|
| `--voz ID` | Usa esta voz en la sesión (sin cambiar el ajuste guardado) |
| `--volumen N` | Volumen de la voz en español, 0–200 (%) |
| `--mostrar-texto` | Muestra el original y la traducción de cada frase |
| `--informe DIR` | Carpeta del informe (por defecto `%LOCALAPPDATA%\InstantTraductor\informes\`) |

Comportamiento:
1. Comprueba que la preparación está completa (si no, sale con código 3).
2. Arranca los servicios y hace la comprobación contra la realimentación: un tono breve de «listo» que no debe aparecer en la captura (FR-003). Si falla, sale con código 4.
3. Muestra el estado en vivo: escuchando, traduciendo o hablando; retraso actual; avisos.
4. Con **Ctrl+C**, para en ≤ 2 s, muestra el resumen, guarda el informe y sale con código 0.
5. Teclas durante la sesión: `+` y `-` cambian el volumen de la voz en pasos del 10 %; `t` muestra u oculta el texto; `q` detiene la sesión (igual que Ctrl+C).

## `instanttraductor archivo ENTRADA`
Traduce un fichero (US2). Formatos: los que admita ffmpeg; como mínimo WAV, MP3, MP4 y MKV.

| Opción | Efecto |
|---|---|
| `--salida DIR` | Carpeta de salida (por defecto `<carpeta de ENTRADA>\<nombre>_es\`) |
| `--voz ID` | Voz de esta ejecución |

Procesa a ritmo real, igual que en directo (FR-021), y escribe en la carpeta de salida (formatos en [informe.md](informe.md)):
- `voz_es.wav`: la pista en español alineada con el original.
- `mezcla.wav`: el original más la voz en español. Si la entrada es un vídeo, además `mezcla.mkv` con el vídeo copiado y el audio mezclado.
- `transcripcion.srt` y `transcripcion.json`.
- `traduccion.srt` y `traduccion.json`.
- `informe.json` e `informe.md`.

Todo se escribe primero en una carpeta temporal y se mueve al terminar: si hay un error, no quedan salidas a medias (FR-022).

## `instanttraductor preparar`
Deja el equipo listo (US3).

| Opción | Efecto |
|---|---|
| `--comprobar` | Solo verifica (no descarga) y lista el estado |

Comportamiento:
1. Comprueba los requisitos: Windows build ≥ 20348, GPU NVIDIA con driver compatible con CUDA ≥ 12.8, espacio libre ≥ lo necesario + 2 GB, y ffmpeg (si falta, lo instala en local).
2. Descarga lo que falte o esté corrupto (verificación sha256), con progreso.
3. Prepara el entorno del servicio de voz.
4. Genera las muestras de las voces.
5. Muestra la tabla de componentes: nombre, versión, licencia, tamaño y estado.

Una segunda ejecución no descarga nada (SC-008).

## `instanttraductor voces`
Gestiona las voces castellanas (FR-028).

| Opción | Efecto |
|---|---|
| (sin opciones) | Lista las voces (id, nombre, género y licencia) y marca la elegida |
| `--escuchar [ID]` | Reproduce la muestra de una voz o de todas |
| `--elegir ID` | Guarda la voz en los ajustes |

## `instanttraductor diagnostico`
Muestra versiones, GPU y VRAM libre, dispositivos de audio, rutas y el estado de la preparación. Sirve para informar de problemas.

## Códigos de salida
| Código | Significado |
|---|---|
| 0 | Correcto (incluida la parada con Ctrl+C) |
| 1 | Error inesperado (detalle en el registro) |
| 2 | Uso incorrecto (opciones) |
| 3 | Preparación incompleta: hay que ejecutar `preparar` |
| 4 | Falla la comprobación contra la realimentación |
| 5 | Fichero de entrada no válido o no admitido |
| 6 | El equipo no cumple los requisitos |

## Garantías de proceso
- Todos los procesos hijos (`llama-server` y el servicio de voz) se asocian a un *Job Object* de Windows con `KILL_ON_JOB_CLOSE`. Si el núcleo muere, mueren ellos: no hay procesos huérfanos (FR-015, FR-018).
- El núcleo es el único proceso que abre dispositivos de audio.
