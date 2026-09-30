# Contrato: servicio local de voz (HTTP)

El servicio de voz es un proceso hijo del núcleo con su propio entorno (`engines/tts-<motor>/`, ADR-0004). Lo usa `HttpSynthesizer` (`src/instanttraductor/tts/http_client.py`), que implementa `Synthesizer` ([pipeline.md](pipeline.md)). Cambiar de motor no cambia este contrato.

## Arranque
```text
uv run --project engines/tts-<motor> tts-service --host 127.0.0.1 --port 0 --voices-dir <ruta> --models-dir <ruta>
```
- Escucha solo en `127.0.0.1`. Con `--port 0`, el sistema elige un puerto libre.
- Cuando está listo (modelo cargado y voces precargadas), escribe **una línea JSON** en stdout y la vacía (flush):
  `{"event": "ready", "port": 51234, "sample_rate": 24000, "engine": "<motor>", "supports_speed": true}`
- Los errores de arranque salen por stderr con un código de salida distinto de 0.
- El núcleo espera la línea `ready` hasta 120 s. Si no llega, trata el arranque como fallido (FR-018).

## Endpoints

### `GET /health`
`200` → `{"status": "ok", "engine": str, "model": str, "sample_rate": int, "supports_speed": bool, "vram_mb": int}`

### `GET /voices`
`200` → `[{"voice_id": str, "name": str, "gender": "f"|"m", "source": str, "license": str}]`

### `POST /synthesize`
Petición (JSON): `{"text": str, "voice_id": str, "speed": float}`
- `text`: de 1 a 1000 caracteres.
- `speed`: de 1.0 a 1.5 (si `supports_speed` es falso, se ignora y el núcleo aplica *time-stretch*).

Respuesta `200`:
- `Content-Type: application/octet-stream`
- Cabecera `X-Sample-Rate: <int>`
- Cuerpo en *streaming* (chunked): PCM **float32 little-endian mono** a medida que se genera. El primer bloque se envía en cuanto hay audio.
- El cliente debe tolerar bloques cuyo tamaño no sea múltiplo de 4, guardando el resto para el siguiente bloque.
- El fin del cuerpo marca el fin del audio.

Errores (`application/json`, con `{"error": str}`):
| Código | Cuándo |
|---|---|
| `400` | `voice_id` desconocido, texto vacío o `speed` fuera de rango |
| `503` | El modelo aún no está listo |
| `500` | Error del motor (el cliente lanza `EngineError`) |

### `POST /shutdown`
`202`. Cierra el servidor de forma ordenada en ≤ 2 s. Si no lo hace, el núcleo termina el proceso; el *Job Object* lo garantiza.

## Requisitos de rendimiento (con el modelo caliente, en la RTX 5070)
- Primer bloque de audio: p95 ≤ 0,6 s desde que se recibe la petición (ADR-0008).
- RTF < 0,5.
- VRAM del proceso ≤ 3,5 GB.

## Voces
Cada voz es un fichero de referencia `<voices-dir>/<voice_id>.wav` (mono, 24 kHz, de 6 a 10 s) con sus metadatos en `<voices-dir>/<voice_id>.json` (campos de `VoiceInfo` más `ref_text` si el motor lo necesita). El servicio las precarga y deja en caché su *prompt* al arrancar.
