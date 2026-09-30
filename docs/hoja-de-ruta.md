# Hoja de ruta

> Estado: **propuesta** (2026-09-30), pendiente de aprobación del humano.

Cada fila es una spec de Spec Kit que deja algo funcionando y comprobable. El orden prioriza oír español cuanto antes y después ir resolviendo lo difícil.

## Versión 1.0: intérprete local, del inglés (y luego japonés y chino) al español, con la voz del hablante

| Orden | Spec | Objetivo | Resultado comprobable | Estado |
|---|---|---|---|---|
| 0 | Cimientos | SDD, orquestación, constitución, arquitectura (ADR 0001–0008) | Documentos aprobados | En curso |
| 1 | `001-espina-dorsal` | Tubería completa del inglés al español con **voz fija**: captura (excluyendo la app) → VAD → ASR → traducción → voz → auriculares. Modo archivo (WAV de entrada → WAV en español + métricas) para pruebas. Arranque desde la línea de comandos | Un vídeo en inglés se oye en español con un retardo p50 ≤ 3 s | Pendiente |
| 2 | `002-peliculas-y-juegos` | Robustez con música y efectos: filtros contra frases inventadas, detección de música y canciones, control de ritmo (acelerar y condensar), comparativa de motores ASR con un corpus propio | Casi ninguna frase inventada en tramos de solo música; sin retraso acumulado en 30 minutos | Pendiente |
| 3 | `003-voz-del-hablante` | Clonación: la voz en español se parece a la de quien habla, y cambia cuando cambia el hablante | Parecido de voz verificable con un embedding de hablante; retardo dentro del presupuesto | Pendiente |
| 4 | `004-japones-y-chino` | Detección automática del idioma de origen y soporte de japonés y chino | Clips en ja/zh traducidos al español con un retardo p50 ≤ 5 s | Pendiente |
| 5 | `005-app-de-escritorio` | Icono en la bandeja del sistema, ajustes, arranque sencillo y descarga guiada de modelos | Se usa sin abrir un terminal | Pendiente |

## Después de la versión 1.0 (ideas, sin compromiso)
- Subtítulos en pantalla.
- Modo ligero (CPU) para jugar con la GPU ocupada.
- Atenuar o silenciar el original como opción.
- Traducir el micrófono (conversación en ambos sentidos).
- Mac y Linux.
