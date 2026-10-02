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
Corpus FLEURS de S5 (lectura continua, de 11 a 12 min por idioma, con música a -10 dB) en modo archivo:

| Idioma | Frases pronunciadas | Retardo de frase p50 / p95 | Cumple |
|---|---|---|---|
| zh | 62/62 | 0,9 / 3,9 s | sí |
| ko | 103 (25 rechazos por idioma, que eran ruido) | 2,1 / 5,7 s | p95 no |
| ja | 105 (24 rechazos por idioma, que eran ruido) | 2,1 / 6,1 s | p95 no |
| en (001, sesión real del humano) | 94/95 | 1,16 / 3,57 s | sí |

**Las rechazadas por idioma no son habla perdida.** Son trocitos de una sílaba que SenseVoice «reconoce» en la música («そ。», «あ。», «The.»), y el filtro de idioma las descarta.

**Fallo de diseño encontrado y corregido** (venía de la 0.1):
- El planificador decidía acelerar o resumir al traducir cada frase, nada más reconocerla, con un retraso que no contaba el audio ya encolado en el sink.
- Con habla seguida, nunca resumía: en ja, 0 resumidas y 2 aceleradas, con un retraso de hasta 8,2 s.
- Ahora:
  - la traducción espera a que la frase anterior empiece a sonar;
  - el modo y la velocidad se deciden con el retraso previsto (lo que ya espera la frase + el audio pendiente en el sink).
- Efecto en ja: 6 resumidas y 33 aceleradas, p95 de 6,5 → 6,1 s.

**Lo que queda es estructural de este corpus:** frases leídas de 8 a 25 s, una tras otra. Una frase corta que sigue a una larga espera a que suene la traducción de la larga.
*Pendiente:* medirlo con diálogo real (anime, serie coreana) con el humano, antes de decidir si hace falta más (umbrales o resumen más agresivo para ja/ko).

## SC-002 Calidad ja/zh/ko
- Hojas de revisión: `%LOCALAPPDATA%\InstantTraductor\calidadevision_{ja,zh,ko}.txt`. Cada frase con su referencia (es_419 de FLEURS) y lo que dijo la app.
- Primera lectura del orquestador: en ja hay varias frases con el sentido cambiado (errores del reconocedor y cortes forzados a 6 s). Si no llega al 85 %, la alternativa prevista es Parakeet-ja (R2).
- *Pendiente: juicio del humano.*

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
