# Hoja de ruta

> Estado: **aprobada** (2026-09-30).

Cada fila es una spec de Spec Kit que deja algo funcionando y comprobable. El orden prioriza oír español cuanto antes y después ir resolviendo lo difícil.

## Versión 1.0: intérprete local, del inglés (y luego japonés y chino) al español, con la voz del hablante

| Orden | Spec | Objetivo | Resultado comprobable | Estado |
|---|---|---|---|---|
| 0 | Cimientos | SDD, orquestación, constitución, arquitectura (ADR 0001–0008) | Documentos aprobados | Hecho (2026-09-30) |
| 1 | `001-espina-dorsal` | Tubería completa del inglés al español con **voz fija**: captura (excluyendo la app) → VAD → ASR → traducción → voz → auriculares. Modo archivo (WAV de entrada → WAV en español + métricas) para pruebas. Arranque desde la línea de comandos | Un vídeo en inglés se oye en español con un retardo p50 ≤ 3 s | Hecho (2026-10-02, v0.1.0: p50 1,16 s y p95 3,57 s) |
| 2 | `002-idiomas-y-peliculas` | **Decidido por el humano (2026-10-02):** (a) **idioma de origen elegido a mano**: inglés, japonés, chino y coreano, con un reconocedor ligero por idioma; (b) **capturar solo la app elegida**, sin Discord ni otras voces; (c) habla baja o alargada; (d) «vosotros». Después, robustez con música y efectos: filtros contra frases inventadas, detección de música y canciones, y comparativa de motores ASR con un corpus propio. Validaciones pendientes de la 001: 30 y 60 min, cambio de dispositivo y sin red | Clips en ja/zh/ko y en inglés traducidos con retardo p50 ≤ 3 s; Discord no se cuela; casi ninguna frase inventada en tramos de solo música | En curso |
| 3 | `003-voz-del-hablante` | Clonación: la voz en español se parece a la de quien habla, y cambia cuando cambia el hablante. Incluye un **catálogo de voces de distintas edades** (jóvenes, adultas y mayores; femeninas y masculinas), diseñadas con VoxCPM2: cuando no se pueda clonar, se usa la del catálogo más parecida en edad y género | Parecido de voz verificable con un embedding de hablante; retardo dentro del presupuesto | Pendiente |
| 4 | `004-deteccion-de-idioma` | Detección automática del idioma de origen como **opción** (el idioma elegido a mano llega en la 002) | Cambia de idioma solo, sin empeorar el retardo del idioma elegido a mano | Pendiente (opcional) |
| 5 | `005-app-de-escritorio` | Icono en la bandeja del sistema, ajustes, arranque sencillo y descarga guiada de modelos | Se usa sin abrir un terminal | Pendiente |

## Después de la versión 1.0 (ideas, sin compromiso)
- Subtítulos en pantalla.
- Modo ligero (CPU) para jugar con la GPU ocupada.
- Atenuar o silenciar el original como opción.
- Traducir el micrófono (conversación en ambos sentidos).
- Mac y Linux.
