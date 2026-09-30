# ADR-0003: Restricciones de producto: local, gratis y de uso personal

- Estado: Aceptada
- Fecha: 2026-09-30
- Decide: humano

## Contexto
Al arrancar el proyecto hacía falta fijar qué se puede pagar, qué licencias valen y cómo debe comportarse el audio. El humano dispone de una RTX 5070 (12 GB), 32 GB de RAM, un Ryzen 7 8700F y auriculares USB Logitech G733, además de suscripciones a Claude Max x5 y ChatGPT. Esas suscripciones no dan acceso por API a la app y solo sirven para desarrollar.

## Decisión
1. **Sin costes de servicio:** la app funciona 100 % en local. No se usan APIs de pago como motor, ni siquiera opcionales.
2. **Uso personal/interno:** se permiten modelos y librerías con licencia no comercial (CC-BY-NC, CPML...). La licencia de cada uno se anota siempre. Se excluyen las licencias que prohíben el uso en la UE (por ejemplo, Hunyuan-MT-7B y HY-MT1.5).
3. **Audio original sin cambios:** la voz en español se mezcla encima, sin atenuar ni silenciar el original. Atenuar o silenciar puede añadirse después como opción.
4. **Contenido principal:** series, películas y juegos (música, efectos, varios personajes).
5. **La versión 1 incluye** voz parecida a la del hablante (clonación) y detección automática del idioma de origen. No incluye subtítulos.
6. **Plataforma:** Windows 11 primero, sin cerrar la puerta a Mac y Linux.

## Alternativas consideradas
Motores en la nube: gpt-realtime-translate (~2 $/h), Gemini Live Translate (~2,2 $/h), Azure Live Interpreter (2,5 $/h) y cascadas del tipo Soniox (~0,85 $/h). Mejor calidad y retardo, sobre todo en japonés y chino, pero con coste por hora. Descartados por la decisión 1.

## Consecuencias
- Todo el pipeline debe caber en 12 GB de VRAM y cumplir el retardo en esta GPU (Blackwell: CUDA ≥ 12.8).
- Retardo esperable: de 2 a 3 s en inglés→español y de 3 a 5 s desde japonés o chino.
- Coste de uso: solo la electricidad (unos 0,04–0,07 €/h, estimado).
- Si algún día se publica o comercializa, habrá que revisar las licencias no comerciales.

## Referencias
- `docs/investigacion/2026-09-30-voz-a-voz-y-costes.md`
- `docs/investigacion/2026-09-30-traduccion-y-voz.md`
