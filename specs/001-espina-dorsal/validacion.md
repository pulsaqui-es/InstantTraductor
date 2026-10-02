# Validación de la 001 en el PC

Equipo:
- Windows 11 Pro (build 26200);
- RTX 5070 de 12 GB (driver 616.64, CUDA 13.4), Ryzen 7 8700F y 32 GB de RAM;
- salida de audio predeterminada: SAMSUNG (NVIDIA High Definition Audio).

Fechas en hora de Madrid.

## Tests automáticos
| Qué | Resultado (2026-10-01) |
|---|---|
| Suite sin hardware (`uv run pytest`) | En verde, incluidos los E2E con dobles del directo y del archivo |
| `device`: captura, reproducción y autotest | En verde. El test del eco con la exclusión rota se salta si suena audio en el PC (ver T024) |
| `gpu`+`model`: servicio de voz | Primer audio p95 de 283 ms, RTF 0,45, VRAM 3,8 GB |
| `model`: Silero, Nemotron y Hy-MT2 | En verde |

## §2 Preparación (SC-008)
- `preparar` verifica los 6 componentes obligatorios y las 5 voces, comprueba el entorno de voz y genera las 5 muestras en 34 s.
- Una segunda ejecución no descarga nada ni regenera las muestras. **Cumple.**

## §4 Modo archivo (SC-007)
- **MP4 de 40 s** (diálogo LibriSpeech sobre imagen de prueba):
  - genera las 9 salidas, incluido `mezcla.mkv` con vídeo h264 copiado, pista 1 «Mezcla (original y español)» y pista 2 «Original»;
  - 9 de 9 frases pronunciadas, sin descartes;
  - retardo de frase p50 de 1,4 s y p95 de 2,9 s; arranque en 16 s.
- **Fichero inexistente:** código 5 y sin carpeta de salida.
- **Fichero dañado y silencio:** cubiertos en el E2E con dobles (`test_file_mode_fakes.py`).
- **MKV de 10 min (SC-007, 2026-10-01 23:22)**, con el diálogo en bucle sobre imagen de prueba: **cumple.**
  - genera las 9 salidas, sin abrir ningún dispositivo;
  - 139 de 139 frases pronunciadas, 0 descartadas, 4 resumidas y 3 aceleradas;
  - retardo de frase p50 de 1,5 s, p95 de 4,3 s y máximo de 5,4 s; retraso máximo de 5,1 s.

## §9 Calidad (SC-004)
- `tests/fixtures/calidad/generate_quality_set.py` sintetiza en inglés 50 frases del corpus de S2: 4,3 min, voz clonada de LibriSpeech.
- Pasadas por `archivo`, salen 64 unidades (las frases largas, por partes), todas pronunciadas, con retardo p50 de 1,2 s y p95 de 3,7 s.
- Salidas en `%LOCALAPPDATA%\InstantTraductor\calidad\frases_en_es\`.
- **Primera lectura del orquestador** (no sustituye al juicio humano):
  - la mayoría son correctas y naturales;
  - fallo recurrente: el plural de cortesía latinoamericano («¿A ustedes…?», «tomen», «síganme», «¿Están listos?») aunque el prompt pide «vosotros»;
  - fallos sueltos: «Take five» → «Tómenselo con calma», «ship» → «barco», «Helm» sin traducir y un tiempo verbal roto al partir una frase («Y pon el cartón…»).
- **Revisión del humano (2026-10-02): «correcto para esta versión». SC-004 se da por cumplido.** La mejora del «vosotros» queda para una spec posterior.

## §5 Modo directo (SC-001, SC-006, SC-010)
**Prueba de humo (2026-10-01 22:20).** El diálogo en inglés de 2 min sonaba con `ffplay` en otro proceso, mientras en el PC sonaba también música a unos -20 dBFS.
- Arranque en 18,1 s (SC-010: ≤ 60 s) y parada en 1,4 s.
- 21 de 21 frases pronunciadas, sin descartes.
- Retardo de frase p50 de 1,70 s y p95 de 2,94 s (objetivo: ≤ 3 s y ≤ 5 s).
- Etapas (p50): ASR 1,25 s, traducción 0,13 s y primer audio 0,22 s.
- **Observación:** con la música de fondo, el reconocedor parte algunas frases en trozos muy cortos («make it», «furnished»). En el modo archivo, con audio limpio, no pasa.

**Sesión real del humano (2026-10-02 15:17, informe `20261002-151737`):** película o serie en inglés con auriculares, 12,5 min.
- 95 frases: 94 pronunciadas y 1 descartada por retraso.
- **Retardo de frase p50 de 1,16 s y p95 de 3,57 s: SC-001 se cumple con contenido real.**
- Ecos: 0. Cortes de audio (`underruns`): 0. Racha de retraso por encima del umbral de descarte: 0 s.
- Memoria: núcleo de 841 a 843 MB; hijos de 4922 a 4924 MB. Estable.
- Arranque en 42 s, en frío tras reiniciar el PC (SC-010: ≤ 60 s).
- **Problemas que encontró el humano** (pasan a la spec 002):
  1. Las voces en español de Discord de fondo se cuelan y lían la traducción. **Decisión del humano:** capturar solo la app elegida.
  2. El habla muy baja o alargada no llega a traducirse.

## Pendiente (pasa a la spec 002)
- SC-002 completo (30 min sin eco): de momento hay 12,5 min con 0 ecos.
- SC-005 completo (60 min): de momento hay 12,5 min estables.
- §10, cambio de dispositivo.
- §11, sin red.

**SC-006, 20 paradas con Ctrl+Break** (`scripts/stop_test.py --veces 20`, 2026-10-01 22:55): **20 de 20 correctas.**
- Parada: mediana de 1,51 s y máximo de 1,68 s.
- Todas salieron con código 0 y el informe guardado.
- Ningún proceso hijo quedó vivo.
- El arranque, de unos 16 s por vuelta, también cumple SC-010.
- Además, al cortar el script a mitad de una vuelta no quedó ningún proceso huérfano: el Job Object funciona.

## Incidencias encontradas y corregidas durante la validación
- **Autotest con audio de fondo:** con música en el PC, el detector daba falsos positivos de realimentación (18-20 dB). Ahora solo mira el tramo en que sonó el tono, alineado con la captura de control. Resultado: 16 de 16 autotests correctos con música sonando.
- **Autotest repetido en el mismo sink:** la segunda pasada salía muda. Ahora cada pasada usa una unidad nueva.
- **Diagnóstico:** los drivers recientes escriben «CUDA UMD Version»; ahora se lee.
- **Ctrl+Break:** mataba el proceso sin informe. Ahora para igual que Ctrl+C.
