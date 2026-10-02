# Quickstart: validación de la 002 en el PC

Se trabaja desde la carpeta del proyecto (`cd C:\InstantTraductor`). Los resultados, con sus cifras, van a `validacion.md`.

## 1. Sin hardware
`uv run pytest` y `uv run ruff check .` en verde.

## 2. Preparación
- `uv run instanttraductor preparar`: descarga X-ASR, SenseVoice y Whisper base, y muestra sus licencias.
- Una segunda ejecución no descarga nada.

## 3. Tests marcados (orquestador, de uno en uno)
- `device`: lista de apps, captura de la app elegida, reapertura y autotest invertido.
- `model`: reconocedores ja/zh/ko con FLEURS y verificador de idioma.
- `gpu`+`model`: traducción ja/zh/ko.

## 4. Idiomas (SC-001, SC-002)
- **Retardo (SC-001):** `uv run instanttraductor archivo <clip_ja>.wav --idioma ja`, y lo mismo con zh y ko. Se usa el corpus FLEURS de S5 concatenado (≥ 10 min por idioma). **Esperado:** retardo de frase p50 ≤ 3 s y p95 ≤ 5 s.
- **Calidad (SC-002):** la persona usuaria revisa `traduccion.srt` frente a la referencia en español de cada frase. **Esperado:** ≥ 85 % buenas por idioma.

## 5. Escuchar la app elegida (SC-003, SC-004)
- `uv run instanttraductor directo --elegir-app`: elegir Chrome con una película en inglés.
- A la vez, poner voz en español en otra app durante 10 min. **Esperado:** ninguna frase de esa app.
- Cerrar y volver a abrir Chrome. **Esperado:** «esperando a Chrome» y la traducción se reanuda ≤ 5 s después de que vuelva a sonar.

## 6. Discord (SC-003b)
1. **Medición de procesos con el humano:** `uv run python spikes/captura_app/discord_sesiones.py`, con los pasos del README de S6. Decide el plan A o el plan B (research.md, R4).
2. **Prueba real:** película compartida por Discord y conversación en español en la llamada, 10 min, con `directo --app discord`. **Esperado:** ninguna frase de la conversación traducida y la película traducida.

## 7. Habla baja, «vosotros» y música (SC-005, SC-006, SC-007)
- **SC-005:** corpus C2 de S7 por `archivo`. **Esperado:** ≥ 80 % de frases traducidas.
- **SC-006:** corpus B0 de S7 (228 frases). **Esperado:** ≥ 80 % de «vosotros» y ≤ 2 % de «ustedes».
- **SC-007:** 10 min de música y efectos sin diálogo, incluidas canciones con letra si hay material libre. **Esperado:** ≤ 1 frase.

## 8. Sesiones largas (SC-008, SC-009, SC-011)
- 30 min sin eco: `echo_events = 0`.
- 60 min estable:
  - `underruns = 0`;
  - racha de retraso por encima del umbral de descarte ≤ 10 s;
  - memoria final ≤ 1,10 × la del minuto 5.
- Arranque ≤ 60 s en cada idioma.
- Cambiar el dispositivo de salida durante la sesión: la voz sigue y la captura continúa.

## 9. Sin red (SC-010)
Con la red desactivada, `directo` y `archivo` en los cuatro idiomas. **Esperado:** funcionan y el registro no muestra ningún intento de descarga.
