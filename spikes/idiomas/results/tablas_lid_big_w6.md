Fichero: lid_big_w6.json; hilos: 1; recortes: 3000

Ventana de Whisper: 6.0 s



#### Sin música

**Whisper tiny**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 93% / 0% / 0% / 1% | 96% / 0% / 0% / 2% | 96% / 0% / 0% / 1% |
| {T,es} | 99% / 1% / 86% / 96% | 100% / 1% / 54% / 88% | 100% / 0% / 64% / 89% |
| {T,es,en} | 96% / 0% / 0% / 24% | 98% / 0% / 0% / 24% | 99% / 0% / 0% / 17% |
| {ja,zh,ko,es,en} | 93% / 0% / 0% / 1% | 98% / 0% / 0% / 2% | 96% / 0% / 0% / 1% |
| p>=0.5 | 96% / 0% / 0% / 23% | 98% / 0% / 0% / 22% | 99% / 0% / 0% / 16% |
| p>=0.8 | 94% / 0% / 0% / 8% | 97% / 0% / 0% / 9% | 97% / 0% / 0% / 2% |
| p>=0.95 | 85% / 0% / 0% / 2% | 94% / 0% / 0% / 2% | 93% / 0% / 0% / 0% |

**Whisper base**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 95% / 0% / 0% / 1% | 98% / 0% / 0% / 1% | 96% / 0% / 0% / 0% |
| {T,es} | 99% / 1% / 79% / 96% | 100% / 0% / 63% / 82% | 100% / 0% / 62% / 84% |
| {T,es,en} | 97% / 1% / 0% / 23% | 99% / 0% / 0% / 18% | 98% / 0% / 0% / 13% |
| {ja,zh,ko,es,en} | 96% / 1% / 0% / 1% | 99% / 0% / 0% / 1% | 96% / 0% / 0% / 0% |
| p>=0.5 | 97% / 0% / 0% / 22% | 99% / 0% / 0% / 17% | 98% / 0% / 0% / 12% |
| p>=0.8 | 94% / 0% / 0% / 4% | 97% / 0% / 0% / 4% | 97% / 0% / 0% / 1% |
| p>=0.95 | 87% / 0% / 0% / 2% | 96% / 0% / 0% / 1% | 91% / 0% / 0% / 0% |


#### Con música a -10 dB

**Whisper tiny**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 92% / 0% / 0% / 2% | 96% / 0% / 0% / 3% | 93% / 0% / 0% / 0% |
| {T,es} | 98% / 1% / 86% / 96% | 100% / 0% / 67% / 86% | 100% / 0% / 74% / 88% |
| {T,es,en} | 95% / 0% / 0% / 26% | 98% / 0% / 0% / 28% | 98% / 0% / 0% / 23% |
| {ja,zh,ko,es,en} | 93% / 0% / 0% / 2% | 97% / 0% / 0% / 3% | 93% / 0% / 0% / 0% |
| p>=0.5 | 95% / 0% / 0% / 26% | 98% / 0% / 0% / 27% | 98% / 0% / 0% / 22% |
| p>=0.8 | 92% / 0% / 0% / 10% | 96% / 0% / 0% / 11% | 96% / 0% / 0% / 5% |
| p>=0.95 | 81% / 0% / 0% / 3% | 94% / 0% / 0% / 4% | 91% / 0% / 0% / 0% |

**Whisper base**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 93% / 0% / 0% / 2% | 97% / 0% / 0% / 2% | 93% / 0% / 0% / 0% |
| {T,es} | 100% / 1% / 78% / 96% | 100% / 1% / 58% / 82% | 100% / 1% / 62% / 85% |
| {T,es,en} | 97% / 0% / 0% / 26% | 98% / 0% / 0% / 20% | 98% / 0% / 0% / 13% |
| {ja,zh,ko,es,en} | 95% / 0% / 0% / 2% | 98% / 0% / 0% / 2% | 94% / 0% / 0% / 0% |
| p>=0.5 | 97% / 0% / 0% / 24% | 98% / 0% / 0% / 18% | 98% / 0% / 0% / 10% |
| p>=0.8 | 91% / 0% / 0% / 6% | 97% / 0% / 0% / 6% | 96% / 0% / 0% / 3% |
| p>=0.95 | 84% / 0% / 0% / 1% | 95% / 0% / 0% / 1% | 90% / 0% / 0% / 0% |


#### Aceptación del idioma correcto por duración del recorte (regla {T,es,en}, sin música)

| Whisper | 1-2 s | 2-4 s | 4-6 s |
|---|---|---|---|
| tiny | 190/205 (93%) | 379/383 (99%) | 312/312 (100%) |
| base | 191/205 (93%) | 379/383 (99%) | 312/312 (100%) |

#### Qué detecta Whisper (idioma de mayor puntuación entre los 99) en los recortes sin música

- tiny, audio ja: ja 278, zh 7, en 5, ko 3, es 3
- tiny, audio zh: zh 289, en 2, ko 2, th 2, fr 2
- tiny, audio ko: ko 287, ja 6, zh 3, th 1, fr 1
- tiny, audio es: es 288, en 5, it 3, ml 1, hi 1
- tiny, audio en: en 299, fr 1
- base, audio ja: ja 284, zh 4, en 3, ta 1, ko 1
- base, audio zh: zh 294, en 3, my 2, vi 1
- base, audio ko: ko 288, ja 5, zh 3, th 2, en 1
- base, audio es: es 292, en 2, ja 1, ms 1, ro 1
- base, audio en: en 299, ja 1
