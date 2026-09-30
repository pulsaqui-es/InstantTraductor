# ADR-0009: Aprobaciones delegadas en el orquestador

- Estado: Aceptada
- Fecha: 2026-10-01
- Decide: humano

## Contexto
La constitución 1.0.0 exigía que el humano aprobase cada spec (H1) y cada plan (H2). Tras aprobar los cimientos y la spec 001, el humano pidió que el orquestador «haga todo» y le consulte solo lo importante: quiere avanzar sin revisar cada documento.

## Decisión
- El orquestador aprueba H1 y H2 cuando la spec o el plan siguen la hoja de ruta y los ADR vigentes. Deja un resumen de cada aprobación en la bitácora y avisa al humano en el chat.
- El orquestador sigue consultando al humano antes de aprobar si:
  - cambia el alcance de la hoja de ruta;
  - hay que crear o sustituir un ADR de arquitectura;
  - se tocan los principios de la constitución;
  - aparece cualquier coste;
  - hace falta el criterio personal del humano (por ejemplo, elegir la voz escuchando muestras).
- Cambiar un contrato congelado sigue exigiendo un ADR, pero solo necesita al humano si afecta a la arquitectura aprobada.
- Se aplica con la constitución 1.1.0 (Principio IV).

## Alternativas consideradas
- **Mantener H1 y H2 siempre en manos del humano:** más control, pero frena el ritmo y el humano ha dicho que no quiere revisar cada paso.
- **Autonomía total, sin consultas:** rápida, pero sacaría del humano decisiones que le corresponden (alcance, costes, gusto personal).

## Consecuencias
- Positivas: menos interrupciones y features que avanzan de principio a fin sin esperas.
- Negativas: el humano ve menos detalle antes de implementar. Para compensarlo:
  - resumen en la bitácora y en el chat;
  - revisión independiente (`revisor`) al cerrar cada ola;
  - el humano puede revisar a posteriori cualquier spec o plan en el repo.

## Referencias
- `.specify/memory/constitution.md` (v1.1.0, Principio IV)
- `docs/bitacora.md` (2026-10-01)
