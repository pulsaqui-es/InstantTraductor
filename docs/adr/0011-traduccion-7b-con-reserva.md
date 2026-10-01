# ADR-0011: Traducción con Hy-MT2-7B, reserva 1.8B y glosario de España

- Estado: Aceptada (sustituye en parte a ADR-0007)
- Fecha: 2026-10-01
- Decide: humano, a propuesta del orquestador tras el spike S2 y la medición del 7B

## Contexto
El spike S2 y la medición posterior del 7B (`spikes/traduccion/README.md` y `resultados/*_7b.*`) mostraron lo siguiente.

**Hy-MT2-1.8B Q8_0:**
- Muy rápido: p50/p95 de 145/218 ms; VRAM de 2,3 GB.
- Unas 20 % de frases con error de sentido en jerga y modismos.
- **No sabe resumir**, de ninguna de las 13 formas probadas. La spec exige resumir con retraso (FR-013, clarificación del humano).

**Hy-MT2-7B Q4_K_M:**
- Acierta más el sentido. Por ejemplo, «is crashing» lo traduce como «está teniendo una crisis», donde el 1.8B daba «está de paso».
- **Sí resume:** −32 % de palabras, conservando el sentido en 8 de 10 frases.
- Con caché de *prompt*: p50/p95 de 211/347 ms; VRAM de 5,2 GB.

**Comunes a los dos:**
- Sesgo hacia el español de América («jugo», «estacionamiento», «ustedes»).
- La cláusula de estilo no tiene efecto, pero un glosario de léxico de España sube el acierto de 9/16 a 14/16.
- Las plantillas oficiales en inglés no se pueden combinar: el modelo traduce el propio *prompt*.

## Decisión
- **Por defecto:** Hy-MT2-7B Q4_K_M en `llama-server` (llama.cpp b11146, build CUDA 13.4, sm_120 nativo, `--cache-ram 0`).
- **Reserva automática:** Hy-MT2-1.8B Q8_0 si, al arrancar, la VRAM libre no alcanza para el 7B más el servicio de voz con margen. En ese caso no hay modo resumen y el control de retraso pasa a acelerar y descartar. Se avisa en la terminal y queda en el informe.
- **Construcción del *prompt*** (la que funcionó en S2):
  - el contexto va como turnos de chat (4 frases previas);
  - 12 ejemplos previos en castellano, fijos y cacheables;
  - cada turno va envuelto en la instrucción de traducir;
  - el glosario usa la plantilla *Terminology* en chino.
- **Modo resumen** (solo con el 7B): plantilla *Style* «telegraphic… at most N words», con N calculado a partir de la longitud del original y del retraso.
- **Glosario base de España incorporado**, con unos 100–200 pares (zumo, nevera, aparcamiento, ordenador, móvil, coche, vale...). Se aplica filtrado por frase, para no engordar el *prompt*, y se suma al glosario del usuario.
- **La comparativa a fondo de traductores** (COMET, revisión del humano y modelos entrenados con español de España como SalamandraTA o EuroLLM) queda para la spec 002, que ya prevé comparar motores.

## Alternativas consideradas
- **Solo el 1.8B:** más ligero, pero con más errores de sentido y sin poder resumir.
- **Comparar más antes de decidir:** retrasa la spec 001 y gasta cuota. Queda para la 002.
- **Cargar los dos modelos a la vez:** no cabe en la VRAM junto a la voz.

## Consecuencias
- **Presupuesto de VRAM:** base del sistema ~1,6 GB (con apps abiertas, hasta 3,2) + traducción 5,2 + voz 3,3 ≈ 10–11,7 GB de 12. Por eso hace falta la reserva automática y un aviso de VRAM en `diagnostico`.
- **Contención en la GPU:** la traducción y la voz comparten GPU. S1 midió que la carga ajena multiplica el tiempo hasta el primer audio, así que se mide con el *stack* completo en la validación.
- **Licencias:** Hy-MT2-7B y 1.8B, Apache 2.0 (comprobada la del 1.8B; la del 7B, en su model card, con la misma familia y fecha).

## Referencias
- `spikes/traduccion/README.md` y `spikes/traduccion/resultados/` (S2 y la medición del 7B, 2026-10-01)
- ADR-0007
