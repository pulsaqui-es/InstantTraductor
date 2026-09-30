# Guía de validación: 001-espina-dorsal

Escenarios ejecutables que demuestran que la feature cumple la spec. Los comandos se lanzan desde la raíz del repositorio. Contratos: [cli.md](contracts/cli.md) e [informe.md](contracts/informe.md).

## 0. Requisitos previos
- Windows 11 (build ≥ 20348), GPU NVIDIA RTX 5070, `uv` y conexión a internet solo para la preparación.
- `uv sync`: crea el entorno del núcleo.

## 1. Pruebas sin hardware (siempre, también los obreros)
```text
uv run pytest -q                      # unitarios y de contrato; excluye gpu, model y device
uv run ruff check . && uv run ruff format --check .
```
**Esperado:** todo en verde, sin tocar la GPU ni los dispositivos de audio.

## 2. Preparación (US3, SC-008)
```text
uv run instanttraductor preparar       # 1.ª vez: descarga, verifica y lista los componentes con su licencia
uv run instanttraductor preparar       # 2.ª vez: no descarga nada
uv run instanttraductor diagnostico
```
**Esperado:**
- una tabla con todos los componentes en estado «verificado», con versión y licencia;
- la segunda ejecución no descarga nada;
- `diagnostico` muestra la GPU y la VRAM libre.

## 3. Elegir voz (US3, SC-009)
```text
uv run instanttraductor voces --escuchar
uv run instanttraductor voces --elegir <id>
```
**Esperado:** se oyen al menos 3 voces castellanas (con los dos géneros) y la elegida queda guardada.

## 4. Modo archivo (US2, SC-007)
```text
uv run instanttraductor archivo tests/fixtures/dialogo_en_2min.wav --salida %TEMP%\it-prueba
uv run instanttraductor archivo <un clip de vídeo MKV/MP4 en inglés de 10 min>
```
**Esperado:**
- las salidas de [informe.md](contracts/informe.md), sin abrir ningún dispositivo de audio;
- `informe.md` con el retardo p50/p95;
- con un fichero sin habla, la pista queda en silencio y el informe lo dice;
- con un fichero dañado, sale con el código 5 y sin salidas a medias.

## 5. Modo directo (US1, SC-001, SC-006, SC-010)
1. Poner en reproducción un vídeo en inglés con diálogo (≥ 10 min).
2. `uv run instanttraductor directo --mostrar-texto`
3. **Esperado:**
   - tono de «listo» en ≤ 60 s;
   - las frases se oyen en español por encima del original, que no cambia;
   - la terminal muestra el estado y el retraso.
4. Pulsar `+` y `-`: solo cambia la voz en español.
5. Ctrl+C. **Esperado:** para en ≤ 2 s y en el informe aparece p50 ≤ 3 s y p95 ≤ 5 s. `tasklist | findstr /i "llama tts-service"` no devuelve nada.

## 6. Silencio (SC-003)
`directo` durante 10 min sin reproducir nada con voz, solo ruido o nada. **Esperado:** 0 frases en el informe.

## 7. Eco propio (SC-002)
`directo` durante 30 min con un vídeo. **Esperado:** `diagnostics.echo_events = 0` y ninguna frase en español reconocida como si fuera inglés.

## 8. Estabilidad (SC-005)
`directo` durante 60 min. **Esperado:**
- sin cortes;
- el retraso no pasa de 8 s más de 10 s seguidos;
- `rss_mb_end ≤ 1,10 × rss_mb_min5`.

## 9. Calidad (SC-004)
`archivo` sobre el conjunto de 50 frases de prueba y revisión humana de `traduccion.srt`. **Esperado:** ≥ 85 % de frases dadas por buenas.

## 10. Cambio de dispositivo (FR-017)
Con `directo` en marcha, apagar o desenchufar el G733 y volver a conectarlo. **Esperado:** la voz sigue por el dispositivo predeterminado de cada momento y la captura no se detiene.
