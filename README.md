# InstantTraductor

Traductor simultáneo para Windows: lo que suena en el PC (una serie, una película, un vídeo) se oye casi en tiempo real hablado en **español de España**, por encima del audio original, que no se toca.

- Idioma de origen: **inglés**. Japonés y chino llegarán más adelante ([hoja de ruta](docs/hoja-de-ruta.md)).
- **100 % local**: reconocimiento de voz, traducción y voz se ejecutan en tu PC. No hay cuentas, servicios de pago ni envío de audio a internet.
- Uso personal.

**Estado:** versión 0.1 (spec `001-espina-dorsal`). Con habla en inglés, la frase traducida suele oírse unos 1,5–3 s después del original.

## Requisitos
- Windows 11 (o Windows 10 build ≥ 20348).
- GPU NVIDIA con unos 9 GB de VRAM libres y un driver compatible con CUDA 13. Desarrollado y probado con una RTX 5070 de 12 GB.
- Unos 15 GB de disco para los modelos y el entorno de la voz.
- [uv](https://docs.astral.sh/uv/) y [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) en el `PATH`. ffmpeg solo hace falta para el modo archivo.

## Instalación
```powershell
git clone https://github.com/pulsaqui-es/InstantTraductor.git
cd InstantTraductor
uv sync
uv run instanttraductor preparar
```
`preparar` comprueba el equipo, descarga y verifica (sha256) los modelos en `%LOCALAPPDATA%\InstantTraductor`, prepara el entorno del servicio de voz y genera las muestras de las voces. Si lo repites, no descarga nada de nuevo. Con `--comprobar` solo verifica.

## Uso
### En directo
```powershell
uv run instanttraductor directo --mostrar-texto
```
1. Arranca en menos de un minuto. Antes de escuchar comprueba que no se capta a sí misma, con un pitido corto.
2. Pon el vídeo en inglés: oirás la traducción por la salida de audio predeterminada.
3. Teclas:
   - `+` y `-`: volumen de la voz en español, en pasos del 10 %;
   - `t`: muestra u oculta el texto;
   - `q` o Ctrl+C: para.
4. Al parar se muestra un resumen y el informe se guarda en `%LOCALAPPDATA%\InstantTraductor\informes\`.

Si el retraso se acumula, la voz acelera hasta 1,25×. Si no basta, resume la frase y, como último recurso, descarta las pendientes más antiguas y lo avisa.

### Un fichero
```powershell
uv run instanttraductor archivo pelicula.mkv
```
Procesa a ritmo real, igual que en directo, y deja en `pelicula_es\` (o en `--salida DIR`):
- `voz_es.wav`: la voz en español alineada con el original;
- `mezcla.wav`: el original más la voz en español; si la entrada es un vídeo, también `mezcla.mkv`, con el vídeo copiado y dos pistas de audio (la mezcla y el original);
- `transcripcion.srt` y `.json`, y `traduccion.srt` y `.json`;
- `informe.json` e `informe.md`, con los retardos por frase y por etapa.

### Voces
```powershell
uv run instanttraductor voces                    # lista y marca la elegida
uv run instanttraductor voces --escuchar         # muestras de todas (o --escuchar ID)
uv run instanttraductor voces --elegir es-f-dvx-08
```
Las voces vienen incluidas: Lucía (por defecto), Clara, dos voces humanas grabadas y Tux. `--voz ID` cambia la voz solo para una sesión.

### Si algo falla
`uv run instanttraductor diagnostico` muestra las versiones, la GPU y la VRAM libre, la salida de audio, las rutas y el estado de la preparación. El registro está en `%LOCALAPPDATA%\InstantTraductor\logs\`.

| Código de salida | Significado |
|---|---|
| 0 | Correcto (también al parar con Ctrl+C) |
| 2 | Opciones incorrectas |
| 3 | Falta ejecutar `preparar` |
| 4 | La app se oye a sí misma (falla la comprobación del arranque) |
| 5 | Fichero de entrada no válido |
| 6 | El equipo no cumple los requisitos |

## Cómo funciona
Captura del audio del PC, excepto el de la propia app (*process loopback* de WASAPI) → detección de voz (Silero) → reconocimiento en streaming (Nemotron, en CPU) → traducción (Hy-MT2 7B con `llama-server`, con glosario de España y el modelo 1.8B de reserva si falta VRAM) → voz (Qwen3-TTS) → reproducción.

Detalles en [docs/arquitectura.md](docs/arquitectura.md) y en las decisiones de [docs/adr/](docs/adr/).

## Licencias de los componentes
`preparar` las muestra también en su tabla.

| Componente | Licencia |
|---|---|
| llama.cpp (`llama-server`) | MIT |
| Hy-MT2-7B y 1.8B (traducción) | Apache-2.0 |
| Nemotron Speech Streaming EN 0.6B (reconocimiento) | NVIDIA Open Model License |
| Silero VAD | MIT |
| Qwen3-TTS-12Hz-0.6B-Base (voz) | Apache-2.0 |
| Voces Lucía y Clara | Apache-2.0 (diseñadas con VoxCPM2; audio sintético) |
| Voz humana 1 y 2 | CC0 1.0 (VoxPopuli; © Unión Europea, Parlamento Europeo) |
| Voz Tux | Dominio público (LibriVox) |
| ffmpeg | GPL (se usa como programa externo) |

## Desarrollo
- Desarrollo guiado por especificaciones con [Spec Kit](https://github.com/github/spec-kit): las specs están en [`specs/`](specs/) y el proceso en [`CLAUDE.md`](CLAUDE.md) y en la [constitución](.specify/memory/constitution.md).
- Tests: `uv run pytest`. Por defecto excluye los marcadores `gpu`, `model` y `device`, que necesitan la GPU, los modelos o los dispositivos de audio.
- Lint: `uv run ruff check .` y `uv run ruff format .`.
- Historial: [docs/bitacora.md](docs/bitacora.md).
