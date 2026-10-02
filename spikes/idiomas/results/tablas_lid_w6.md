Fichero: lid_t1_w6.json; hilos: 1; recortes: 420

Ventana de Whisper: 6.0 s

- Whisper tiny: decisión propia p50/p95 49/90 ms (CPU 47/391 ms)
- Whisper base: decisión propia p50/p95 96/131 ms (CPU 94/298 ms)


#### Sin música

**Whisper tiny**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 92% / 0% / 0% / 2% | 98% / 0% / 0% / 1% | 96% / 0% / 0% / 1% |
| {T,es} | 100% / 0% / 80% / 96% | 100% / 0% / 60% / 86% | 100% / 0% / 70% / 89% |
| {T,es,en} | 98% / 0% / 0% / 30% | 98% / 0% / 0% / 25% | 100% / 0% / 0% / 14% |
| {ja,zh,ko,es,en} | 92% / 0% / 0% / 2% | 98% / 0% / 0% / 2% | 96% / 0% / 0% / 2% |
| p>=0.5 | 98% / 0% / 0% / 27% | 98% / 0% / 0% / 22% | 100% / 0% / 0% / 12% |
| p>=0.8 | 98% / 0% / 0% / 7% | 98% / 0% / 0% / 5% | 96% / 0% / 0% / 4% |
| p>=0.95 | 84% / 0% / 0% / 1% | 92% / 0% / 0% / 2% | 96% / 0% / 0% / 2% |

**Whisper base**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 96% / 0% / 0% / 0% | 98% / 0% / 0% / 1% | 98% / 0% / 0% / 1% |
| {T,es} | 100% / 0% / 73% / 99% | 100% / 0% / 57% / 84% | 100% / 0% / 57% / 90% |
| {T,es,en} | 98% / 0% / 0% / 21% | 98% / 0% / 0% / 21% | 98% / 0% / 0% / 20% |
| {ja,zh,ko,es,en} | 98% / 0% / 0% / 0% | 98% / 0% / 0% / 1% | 98% / 0% / 0% / 1% |
| p>=0.5 | 98% / 0% / 0% / 20% | 98% / 0% / 0% / 19% | 98% / 0% / 0% / 18% |
| p>=0.8 | 94% / 0% / 0% / 7% | 98% / 0% / 0% / 4% | 96% / 0% / 0% / 4% |
| p>=0.95 | 88% / 0% / 0% / 2% | 98% / 0% / 0% / 1% | 92% / 0% / 0% / 1% |


#### Con música a -10 dB

**Whisper tiny**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 88% / 0% / 0% / 1% | 94% / 0% / 0% / 1% | 98% / 0% / 0% / 2% |
| {T,es} | 100% / 0% / 80% / 94% | 100% / 0% / 67% / 81% | 100% / 0% / 80% / 89% |
| {T,es,en} | 94% / 0% / 0% / 25% | 96% / 0% / 0% / 24% | 100% / 0% / 0% / 21% |
| {ja,zh,ko,es,en} | 90% / 0% / 0% / 1% | 96% / 0% / 0% / 1% | 98% / 0% / 0% / 2% |
| p>=0.5 | 94% / 0% / 0% / 25% | 96% / 0% / 0% / 21% | 100% / 0% / 0% / 19% |
| p>=0.8 | 90% / 0% / 0% / 11% | 94% / 0% / 0% / 9% | 94% / 0% / 0% / 7% |
| p>=0.95 | 82% / 0% / 0% / 4% | 90% / 0% / 0% / 3% | 90% / 0% / 0% / 1% |

**Whisper base**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 92% / 0% / 0% / 0% | 96% / 0% / 0% / 0% | 98% / 0% / 0% / 2% |
| {T,es} | 100% / 0% / 67% / 99% | 100% / 0% / 53% / 79% | 98% / 0% / 43% / 88% |
| {T,es,en} | 98% / 0% / 0% / 32% | 98% / 0% / 0% / 16% | 98% / 0% / 0% / 20% |
| {ja,zh,ko,es,en} | 94% / 0% / 0% / 1% | 98% / 0% / 0% / 0% | 98% / 0% / 0% / 2% |
| p>=0.5 | 98% / 0% / 0% / 30% | 98% / 0% / 0% / 15% | 98% / 0% / 0% / 18% |
| p>=0.8 | 92% / 0% / 0% / 8% | 98% / 0% / 0% / 2% | 98% / 0% / 0% / 5% |
| p>=0.95 | 82% / 0% / 0% / 2% | 92% / 0% / 0% / 0% | 94% / 0% / 0% / 1% |


#### Aceptación del idioma correcto por duración del recorte (regla {T,es,en}, sin música)

| Whisper | 1-2 s | 2-4 s | 4-6 s |
|---|---|---|---|
| tiny | 38/39 (97%) | 63/64 (98%) | 47/47 (100%) |
| base | 37/39 (95%) | 63/64 (98%) | 47/47 (100%) |

#### Qué detecta Whisper (idioma de mayor puntuación entre los 99) en los recortes sin música

- tiny, audio ja: ja 46, tr 1, zh 1, ko 1, ml 1
- tiny, audio zh: zh 49, ja 1
- tiny, audio ko: ko 48, vi 1, ja 1
- tiny, audio es: es 29, ta 1
- tiny, audio en: en 29, tr 1
- base, audio ja: ja 48, bn 1, ko 1
- base, audio zh: zh 49, en 1
- base, audio ko: ko 49, zh 1
- base, audio es: es 28, bn 1, tl 1
- base, audio en: en 30
