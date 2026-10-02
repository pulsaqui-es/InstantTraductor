Fichero: lid_t1_busy.json; hilos: 1; recortes: 420

Ventana de Whisper: 30.0 s

- Whisper tiny: decisión propia p50/p95 326/412 ms (CPU 328/578 ms); acuerdo con la API de sherpa-onnx 95.0%; API de sherpa p50/p95 157/226 ms
- Whisper base: decisión propia p50/p95 662/809 ms (CPU 656/906 ms); acuerdo con la API de sherpa-onnx 94.5%; API de sherpa p50/p95 279/386 ms
- SenseVoice (idioma automático, ya hace el ASR): p50/p95 267/445 ms (CPU 250/406 ms)


#### Sin música

**Whisper tiny**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 88% / 0% / 0% / 1% | 94% / 0% / 0% / 1% | 98% / 0% / 0% / 4% |
| {T,es} | 100% / 0% / 60% / 99% | 100% / 0% / 47% / 79% | 100% / 0% / 70% / 90% |
| {T,es,en} | 94% / 0% / 0% / 35% | 100% / 0% / 0% / 19% | 100% / 0% / 0% / 36% |
| {ja,zh,ko,es,en} | 88% / 0% / 0% / 1% | 96% / 0% / 0% / 1% | 98% / 0% / 0% / 4% |
| p>=0.5 | 94% / 0% / 0% / 35% | 100% / 0% / 0% / 19% | 100% / 0% / 0% / 36% |
| p>=0.8 | 86% / 0% / 0% / 7% | 94% / 0% / 0% / 7% | 98% / 0% / 0% / 9% |
| p>=0.95 | 76% / 0% / 0% / 1% | 90% / 0% / 0% / 1% | 98% / 0% / 0% / 2% |

**Whisper base**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 88% / 0% / 0% / 0% | 98% / 0% / 0% / 0% | 98% / 0% / 0% / 3% |
| {T,es} | 100% / 0% / 60% / 97% | 100% / 0% / 40% / 87% | 100% / 0% / 60% / 91% |
| {T,es,en} | 96% / 0% / 0% / 19% | 98% / 0% / 0% / 18% | 100% / 0% / 0% / 27% |
| {ja,zh,ko,es,en} | 90% / 0% / 0% / 0% | 98% / 0% / 0% / 0% | 100% / 0% / 0% / 3% |
| p>=0.5 | 96% / 0% / 0% / 15% | 98% / 0% / 0% / 15% | 100% / 0% / 0% / 26% |
| p>=0.8 | 92% / 0% / 0% / 1% | 96% / 0% / 0% / 1% | 100% / 0% / 0% / 5% |
| p>=0.95 | 82% / 0% / 0% / 1% | 96% / 0% / 0% / 0% | 92% / 0% / 0% / 1% |

**Alternativas baratas (SenseVoice)**

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| sv-etiqueta | 100% / 20% / 0% / 0% | 100% / 0% / 0% / 0% | 100% / 3% / 0% / 0% |
| sv-escritura | 100% / 63% / 3% / 51% | 96% / 27% / 0% / 9% | 100% / 50% / 7% / 8% |


#### Con música a -10 dB

**Whisper tiny**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 88% / 0% / 0% / 0% | 92% / 0% / 0% / 1% | 98% / 0% / 0% / 3% |
| {T,es} | 100% / 0% / 63% / 97% | 100% / 0% / 47% / 79% | 100% / 0% / 70% / 95% |
| {T,es,en} | 90% / 0% / 0% / 45% | 96% / 0% / 0% / 24% | 100% / 0% / 0% / 54% |
| {ja,zh,ko,es,en} | 88% / 0% / 0% / 0% | 94% / 0% / 0% / 1% | 98% / 0% / 0% / 3% |
| p>=0.5 | 88% / 0% / 0% / 44% | 96% / 0% / 0% / 20% | 100% / 0% / 0% / 53% |
| p>=0.8 | 84% / 0% / 0% / 16% | 92% / 0% / 0% / 8% | 98% / 0% / 0% / 17% |
| p>=0.95 | 78% / 0% / 0% / 3% | 88% / 0% / 0% / 2% | 92% / 0% / 0% / 3% |

**Whisper base**: aceptado (%) de cada grupo; objetivo: T >= 97 %, es ~0 %

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| completo | 86% / 0% / 0% / 0% | 96% / 0% / 0% / 0% | 100% / 0% / 0% / 4% |
| {T,es} | 100% / 0% / 57% / 100% | 100% / 0% / 43% / 87% | 100% / 0% / 50% / 92% |
| {T,es,en} | 94% / 0% / 0% / 27% | 98% / 0% / 0% / 13% | 100% / 0% / 0% / 28% |
| {ja,zh,ko,es,en} | 86% / 0% / 0% / 0% | 98% / 0% / 0% / 0% | 100% / 0% / 0% / 4% |
| p>=0.5 | 94% / 0% / 0% / 22% | 98% / 0% / 0% / 12% | 100% / 0% / 0% / 25% |
| p>=0.8 | 88% / 0% / 0% / 3% | 98% / 0% / 0% / 1% | 96% / 0% / 0% / 6% |
| p>=0.95 | 84% / 0% / 0% / 2% | 94% / 0% / 0% / 0% | 96% / 0% / 0% / 1% |

**Alternativas baratas (SenseVoice)**

| Regla | T=ja: ja / es / en / zh+ko | T=zh: zh / es / en / ja+ko | T=ko: ko / es / en / ja+zh |
|---|---|---|---|
| sv-etiqueta | 100% / 13% / 0% / 0% | 100% / 0% / 0% / 0% | 100% / 7% / 0% / 0% |
| sv-escritura | 100% / 77% / 7% / 58% | 96% / 33% / 0% / 12% | 100% / 77% / 3% / 15% |


#### Aceptación del idioma correcto por duración del recorte (regla {T,es,en}, sin música)

| Whisper | 1-2 s | 2-4 s | 4-6 s |
|---|---|---|---|
| tiny | 36/39 (92%) | 64/64 (100%) | 47/47 (100%) |
| base | 37/39 (95%) | 63/64 (98%) | 47/47 (100%) |

#### Qué detecta Whisper (idioma de mayor puntuación entre los 99) en los recortes sin música

- tiny, audio ja: ja 44, ko 3, en 3
- tiny, audio zh: zh 47, fr 1, ko 1, ja 1
- tiny, audio ko: ko 49, zh 1
- tiny, audio es: es 29, ta 1
- tiny, audio en: en 30
- base, audio ja: ja 44, ko 3, en 2, tr 1
- base, audio zh: zh 49, en 1
- base, audio ko: ko 49, th 1
- base, audio es: es 28, en 1, hi 1
- base, audio en: en 30
