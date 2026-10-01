# Arquitectura de InstantTraductor

> Estado: **aprobada** (2026-09-30). Los motivos de cada pieza están en los ADR 0004–0008.

## Vista general

```text
Núcleo: proceso raíz, Python 3.12 + uv. Capta Y reproduce, y es el PID excluido de la captura (ADR-0010)
 ├─ Captura (hilo) ── process loopback EXCLUDE(PID del núcleo), código propio con ctypes/comtypes
 │                     → 16 kHz mono float32 → AGC → búfer (vigilante + autotest de eco)
 ├─ VAD y segmentación (hilo) ── Silero VAD → voz / fin de turno
 ├─ ASR (hilo, en el proceso) ── Nemotron Streaming EN 560 ms (sherpa-onnx, CPU) → eventos parcial/final
 ├─ Planificador ── unidades de traducción (pausas del VAD, comas, máx. 6 s) + control del retraso
 ├─ Cliente MT ──── HTTP local ──► [hijo] llama-server + Hy-MT2-7B Q4 (GPU; reserva 1.8B si falta VRAM)
 ├─ Cliente TTS ─── HTTP local ──► [hijo] servicio de voz Qwen3-TTS-0.6B, entorno propio (GPU) → PCM
 ├─ Registro de hablantes (spec 003) ── embedding (CPU) + referencias limpias (separador en 2.º plano)
 └─ Reproducción (hilo) ── cola de PCM → 48 kHz → dispositivo por defecto
                           (Windows lo mezcla con el original, que suena sin cambios)
```

## Recorrido de una frase
1. El original suena en los auriculares; no se toca.
2. La captura lo recibe sin nuestra propia voz (modo EXCLUDE).
3. El VAD y el ASR producen texto con tiempos del reloj de audio.
4. Cuando una cláusula u oración queda confirmada, se crea una unidad de traducción con su contexto y el glosario.
5. La traducción devuelve español en *streaming*.
6. La voz sintetiza el PCM; desde la spec 003, con la voz de referencia del hablante.
7. La reproducción respeta el orden. Si se acumula retraso, primero acelera (hasta 1,25×) y después condensa.

## Contratos
Las etapas se comunican mediante contratos (`typing.Protocol` + `@dataclass(frozen=True)`) en `src/instanttraductor/contracts/`. Todos los tiempos van en el reloj de audio de la sesión. Cada motor es un adaptador intercambiable, dentro del proceso o como proceso hijo con API HTTP local. Los contratos se congelan (con un tag) antes de repartir trabajo entre obreros.

## Presupuesto de retardo (del inglés al español, objetivo inicial)

| Etapa | Objetivo |
|---|---|
| Captura y VAD | ≤ 0,1 s |
| ASR (texto final tras cerrarse la cláusula) | ≤ 0,8 s |
| Traducción | ≤ 0,3 s |
| Voz (primer audio) | ≤ 0,6 s |
| Búfer de reproducción | ≤ 0,1 s |

**EVS** (desde que se dice algo hasta que se oye en español): p50 ≤ 3 s y p95 ≤ 5 s. Se mide en cada spec y se ajusta con datos. Desde japonés o chino se esperan de 3 a 5 s, por el orden de las palabras.

## VRAM (12 GB; medido el 2026-10-01)
Windows y las apps ocupan entre 1,6 y 3,2 GB según lo que haya abierto. Presupuesto de la app:
- ASR en CPU: 0 GB.
- Hy-MT2-7B Q4_K_M: 5,2 GB (reserva 1.8B Q8: 2,3 GB).
- Qwen3-TTS-0.6B: 3,3 GB.
- Separador de diálogo bajo demanda (spec 003): ~0,5–1 GB.

En total, unos 8,5 GB, o 5,6 con la reserva. Al arrancar se comprueba la VRAM libre: si no hay margen para el 7B, se usa el 1.8B (ADR-0011). La v1 no contempla traducir mientras se juega en el mismo PC (ADR-0003).

## Estructura prevista del repositorio

```text
src/instanttraductor/   núcleo: contracts/ audio/ vad/ asr/ mt/ tts/ pipeline/ metrics/ config/ cli.py
engines/<motor>/        motores con entorno propio (pyproject.toml y .venv separados)
tests/                  unit/ contract/ integration/ fakes/ fixtures/
specs/                  specs de Spec Kit (una carpeta por feature)
docs/                   arquitectura, ADR, investigación, hoja de ruta, bitácora
```
