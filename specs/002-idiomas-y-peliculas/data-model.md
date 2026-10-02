# Data Model: Idiomas elegidos a mano y robustez en películas

Parte del modelo de la 001 (`specs/001-espina-dorsal/data-model.md`). Aquí solo está lo nuevo o lo que cambia.

## SourceLanguage (nuevo, contrato)
- **Valores:** `en`, `ja`, `zh` y `ko` (StrEnum).
- **Por defecto:** `en`.
- **Origen:**
  - el ajuste `idioma_origen` y la opción `--idioma`, que lo sobrescribe en esa sesión;
  - también en el modo archivo.
- **Determina:** el reconocedor (R2), el filtro de longitud y `max_tokens` de la traducción (R10), la cola mínima del segmentador (R7) y el idioma que acepta el verificador (R3).

## Settings (cambia)
| Atributo | Clave TOML | Tipo | Por defecto | Validación |
|---|---|---|---|---|
| `source_language` | `idioma_origen` | `SourceLanguage` | `en` | Uno de los cuatro |
| `capture_app` | `app_escuchada` | `str` | `""` (todo el PC) | Vacío o ruta absoluta de un `.exe` |

El resto de los ajustes no cambia. Un ajuste no válido lanza `ValueError` con la clave en español, como en la 001.

## AppIdentity (nuevo, `audio/apps.py`)
- **Campos:**
  - `exe_path`, la identidad que se guarda;
  - `display_name`, el `FileDescription` del ejecutable o el nombre del proceso;
  - `root_pid` y `create_time`, que solo valen en la sesión.
- **Regla del objetivo:** el PID de la sesión de audio, o su padre directo si tiene la misma imagen.
- **Exclusión:** nunca la propia app ni ninguno de sus antepasados.

## AudioApp (nuevo, una fila de la lista)
- **Campos:**
  - `identity: AppIdentity`;
  - `sounding: bool`, de la sonda INCLUDE de 0,6 s (≥ -60 dBFS RMS);
  - `level_dbfs: float`;
  - `endpoints: tuple[str, ...]`.
- **Orden:** primero las que suenan, por nivel.

## AppCaptureState (nuevo, estado de `AppLoopbackSource`)
```
esperando ──(aparece la app: abre INCLUDE)──▶ sonando
sonando ──(muere o cambia el PID)──▶ esperando
sonando ──(la sonda dice que suena y llegan ceros ≥ 4 s)──▶ silencio (aviso)
silencio ──(llega audio)──▶ sonando
```
- Mientras está en `esperando`, la fuente entrega chunks de ceros a ritmo de reloj: no capta nada más (FR-010).
- La interfaz muestra el estado («esperando a Chrome…»).

## LanguageVerdict (nuevo, contrato)
- **Campos:**
  - `accepted: bool`;
  - `detected: SourceLanguage | Literal["es"]`, el ganador entre {en, es, ja, zh, ko};
  - `probability: float`;
  - `elapsed_s: float`.
- **Regla:** se acepta si `detected` es el idioma elegido y, además, si `AsrEvent.language` del FINAL coincide con el idioma elegido. SenseVoice pone ahí el idioma detectado; los demás motores, el elegido.

## UtteranceRecord (cambia)
- `outcome = REJECTED` con `reason = "idioma"` cuando el verificador rechaza la unidad.
- **Nuevo campo de tiempos:** `StageTimings.lid_done_at: float | None`. Se añade al final con valor por defecto, así que el contrato no se rompe.
- **Informe:**
  - la etapa `lid` en `stages_s`;
  - el resumen cuenta las frases rechazadas por idioma;
  - campos nuevos: `source_language` y `capture` («todo el PC» o el nombre de la app).

## TranslationRequest (cambia)
- `source_language: SourceLanguage = SourceLanguage.EN`, añadido al final con valor por defecto.
