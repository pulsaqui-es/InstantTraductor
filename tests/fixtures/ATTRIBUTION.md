# Atribución de los fixtures de audio

Todos los WAV de esta carpeta son PCM de 16 bits, 16 kHz y mono. Se generan con
[`generate_fixtures.py`](generate_fixtures.py) y se versionan porque son pequeños.

| Fichero | Contenido | Origen |
|---|---|---|
| `tono_1k_1s.wav` | Seno de 1 kHz, 1 s, −6 dBFS de pico | Sintético |
| `silencio_3s.wav` | 3 s de silencio digital | Sintético |
| `ruido_rosa_5s.wav` | 5 s de ruido rosa, RMS −20 dBFS, semilla fija | Sintético |
| `dialogo_en_2min.wav` | 10 enunciados en inglés con una pausa de 0,8 s tras cada uno (117,8 s) | LibriSpeech |
| `dialogo_en_2min.txt` | Su transcripción, una línea por enunciado | LibriSpeech |

Los tres primeros los crea el script y no contienen material de terceros.

## LibriSpeech (`dialogo_en_2min.wav` y `dialogo_en_2min.txt`)

- **Obra:** corpus LibriSpeech ASR, de Vassil Panayotov, Guoguo Chen, Daniel Povey y Sanjeev Khudanpur,
  construido a partir de grabaciones de voluntarios de LibriVox de libros de dominio público.
  <https://www.openslr.org/12>
- **Licencia:** Creative Commons Atribución 4.0 Internacional (**CC BY 4.0**).
  <https://creativecommons.org/licenses/by/4.0/deed.es>
- **Copia usada:** el dataset `hf-internal-testing/librispeech_asr_dummy` de Hugging Face (73 enunciados
  de la partición de validación «clean»), en la revisión `5be91486e11a2d616f4ec5db8d3fd248585ac07a`.
- **Enunciados usados**, en este orden: `1272-128104-0000` a `1272-128104-0009` (locutor 1272, capítulo 128104).
- **Cambios:** se han concatenado esos enunciados, uno tras otro, con 0,8 s de silencio digital después de cada
  uno (también del último), y se han guardado como WAV. El audio de cada enunciado no se ha modificado:
  son las mismas muestras de 16 bits a 16 kHz que las del original, sin pérdida. La transcripción es el texto
  de LibriSpeech tal cual (mayúsculas y sin puntuación), una línea por enunciado.
- **Cita:** V. Panayotov, G. Chen, D. Povey y S. Khudanpur, «Librispeech: an ASR corpus based on public domain
  audio books», *IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP)*, 2015,
  pp. 5206–5210. doi:10.1109/ICASSP.2015.7178964

## Regenerar

Desde la raíz del repositorio (el diálogo necesita red la primera vez, para bajar el dataset a la caché de
Hugging Face del usuario):

```text
uv run python tests/fixtures/generate_fixtures.py
```
