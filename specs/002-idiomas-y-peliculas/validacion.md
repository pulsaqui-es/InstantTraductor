# Validación de la 002 en el PC

Mismo equipo que en la 001: RTX 5070, Ryzen 7 8700F, Windows 11 26200. Fechas en hora de Madrid.

## §1 Tests sin hardware
`uv run pytest` y `uv run ruff check .` en verde, incluidos estos E2E con dobles:
- filtro de idioma: película en «inglés» y llamada en «español»;
- modo archivo;
- `LiveSession`.

## §2 Preparación (2026-10-02)
- `preparar` instala en 34 s los tres componentes nuevos y los deja verificados por fichero:
  - X-ASR-zh-en, desde su `.tar.bz2` fijado, extraído y verificado: 169 MB;
  - SenseVoice-Small: 240 MB;
  - Whisper base: 160 MB.
- El resto de componentes no se vuelve a descargar.

## §3 Tests marcados
| Qué | Resultado |
|---|---|
| `model`: reconocedores ja/zh/ko y verificador (10 frases FLEURS por idioma) | 17/17 en verde. CER: zh 4,5 %, ja 8,7 % (12,7 % con el corte forzado de 6 s), ko 5,8 % (8,2 % con el corte). Verificador: acepta 19-20/20 del idioma correcto y rechaza 19-20/20 del español, con 74/83 ms (p50/p95) |
| `device`: escuchar una app | 13/13 en verde: lista, INCLUDE de un emisor que no oye a otro, espera con ceros, reinicio del emisor reanudado en < 5 s y autotest invertido |
| `gpu`+`model`: «vosotros» (corpus B0 de S7, 228 frases) | En verde: ≥ 80 % de «vosotros» y ≤ 2 % de «ustedes» (SC-006), con la regla de reintento final |

**Cambio que salió de la validación (T019).** Con la nota de escena en la primera pasada, «vosotros» se quedaba en el 74,3 %. Se pasó a la combinación medida en S7 que da el 81 %:
- primera pasada sin nota;
- reintento con la nota solo en las frases marcadas;
- dos salvaguardas:
  - nunca con un vocativo singular;
  - «ustedes» solo se reintenta si el inglés lleva «you», para no convertir un «they» en «vosotros».

## §4 Idiomas (SC-001)
*Pendiente: en curso.*

## §5 y §6 Escuchar una app y Discord (SC-003, SC-003b, SC-004)
*Pendiente: con el humano.*

## §7 Habla baja, «vosotros» y música (SC-005, SC-006, SC-007)
- **SC-006:** cumplido (§3).
- **SC-005, habla baja:** medido en el spike S7 con las mismas piezas de producción (AGC, Silero, Nemotron y segmentador), corpus sintético C2:
  - de -20 a -51 dBFS se traduce el 100 % de las frases;
  - el susurro (DSP y Qwen3-TTS VoiceDesign) entre el 95 % y el 100 % sin música;
  - con la voz por debajo de la música (SNR ≤ -2 dB) solo el 65 %. Queda fuera del objetivo, según la asunción de la spec («música moderada»);
  - los umbrales nuevos de Silero (0,30/0,15) suben +1,7 puntos en condiciones duras.
- **SC-007, música sin diálogo:** 0 frases en 10 min de música instrumental y efectos en S7, y Silero no abre ningún segmento con orquesta, aria ni coros (S5). Prueba débil: falta material con canciones con letra.

## §8 y §9 Sesiones largas y sin red (SC-008, SC-009, SC-010, SC-011)
*Pendiente: con el humano.*
