# ADR-0007: Traducción automática (MT)

- Estado: Aceptada (aprobada por el humano el 2026-09-30); sustituida en parte por ADR-0011 (2026-10-01)
- Fecha: 2026-09-30
- Decide: orquestador (con visto bueno del humano)

## Contexto
La traducción tiene que ser rápida (≤0,3 s por frase), sonar a español de España, mantener la coherencia entre frases (contexto, nombres de personajes) y servir también para japonés y chino. Debe caber en unos 2–3 GB de VRAM y tener una licencia válida en España.

## Decisión
- **Motor:** **Hy-MT2-1.8B** (Tencent, 21-may-2026) en **GGUF Q8_0** (~2 GB), servido por **`llama-server`** (llama.cpp con CUDA ≥ 12.8) como proceso hijo del núcleo.
  - **Licencia:** Apache 2.0 estándar, sin restricciones territoriales (comprobado en `LICENSE.txt` el 2026-09-30).
  - Cubre en, ja, zh y es entre 36 idiomas.
- **Uso:**
  - Se traducen **cláusulas u oraciones ya confirmadas** por el ASR. Lo que ya ha sonado en español nunca se vuelve a traducir.
  - El *prompt* usa las plantillas oficiales de Hy-MT2: contexto (los últimos 3–5 pares), terminología (glosario del usuario: nombres de personajes, lugares...) y estilo («español de España, natural y conciso; vosotros»).
  - La traducción se transmite en *streaming* hacia la voz.
  - Filtros de seguridad: idioma de salida, proporción de longitud y lista negra de muletillas del tipo «Aquí tienes la traducción».
- **Mejora opcional:** Hy-MT2-7B Q4_K_M (~5 GB), si las mediciones lo justifican y sobra VRAM.
- **Respaldo en CPU:** Opus-MT en→es con CTranslate2, si el LLM falla o tarda más de 1 s.

## Alternativas consideradas
- **Hunyuan-MT-7B y HY-MT1.5:** su licencia excluye la UE. No se pueden usar en España.
- **Qwen3.5-4B/9B:** muy flexible con las instrucciones, pero peor en MT que Hy-MT2 a igual tamaño.
- **TranslateGemma-4B:** plantilla rígida y 2K tokens de entrada.
- **NLLB y SeamlessM4T:** no comerciales y sin control de estilo ni de contexto.
- **Opus-MT como principal:** rápido, pero sin contexto ni glosario, y sin modelo directo de chino a español.

## Consecuencias
- Modelo muy reciente (mayo de 2026): pueden aparecer errores o un soporte irregular en llama.cpp. Se fija la versión de llama.cpp y del GGUF.
- Hay que medir la calidad con un conjunto propio (COMET y revisión de «¿suena a España?») antes de cerrar la elección.

## Referencias
- `docs/investigacion/2026-09-30-traduccion-y-voz.md`
- https://huggingface.co/tencent/Hy-MT2-1.8B
