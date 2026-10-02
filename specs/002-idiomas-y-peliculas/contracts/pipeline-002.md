# Contratos 002: cambios sobre `contratos-001-v1`

Todos los cambios son **aditivos y con valor por defecto**: el código y los dobles de la 001 siguen siendo válidos. Al terminar la ola 0 se congelan con el tag `contratos-002-v1`.

## Nuevo: `src/instanttraductor/contracts/language.py`
```python
class SourceLanguage(StrEnum):
    EN = "en"; JA = "ja"; ZH = "zh"; KO = "ko"

@dataclass(frozen=True, slots=True)
class LanguageVerdict:
    accepted: bool
    detected: str            # código ISO 639-1 del ganador entre {en, es, ja, zh, ko}
    probability: float       # 0–1
    elapsed_s: float

class LanguageVerifier(Protocol):
    name: str
    def verify(self, samples: npt.NDArray[np.float32], sample_rate: int,
               language: SourceLanguage, *, hint: str | None = None) -> LanguageVerdict:
        """¿Es el audio habla en `language`? `hint`: etiqueta de idioma del ASR, si la da (SenseVoice).
        Lanza `EngineError` si falla. 1 s ≤ duración ≤ 6 s (si es más corto, el que llama lo completa)."""
        ...
    def close(self) -> None: ...
```

## Cambia: `translation.py`
- `TranslationRequest.source_language: SourceLanguage = SourceLanguage.EN`, el último campo.

## Sin cambio de forma: `speech.py` (AsrEvent)
- `AsrEvent.language` ya existe. **Regla nueva:**
  - un motor que detecta el idioma (SenseVoice) pone en el FINAL el idioma **detectado**;
  - los demás ponen el idioma elegido.
- El pipeline pasa `hint=event.language` al verificador.

## Cambia: `metrics.py` (StageTimings)
- `lid_done_at: float | None = None`, el último campo.

## Sin cambios
`AudioSource`, `AudioSink`, `Vad`, `AsrEngine`, `Segmenter`, `Synthesizer`, `DelayController` y `Clock`.

`AppLoopbackSource` implementa `AudioSource` (pasa `AudioSourceContract`, con `finite=False`). Los motores nuevos implementan `AsrEngine`: un motor por segmento declara `capabilities.partials=False` y solo emite el FINAL en `flush()` o en el corte forzado.

## Reglas del pipeline (comportamiento, no código)
1. **Antes de traducir una unidad:**
   - el hilo de traducción pide al verificador la ventana de audio de la unidad (R3), sacada del anillo de audio, del audio captado tras el AGC;
   - si `accepted` es False, o si `hint` no coincide con el idioma elegido: `scheduler.on_rejected(unit_id, "idioma")`.
     - Es un método nuevo del planificador, que no es contrato.
     - La unidad se cierra como `REJECTED` con ese motivo, y no se traduce ni suena.
2. **El verificador falla con `EngineError`:** la unidad se traduce igual (se prefiere no perder habla), con un aviso y un contador en el informe.
3. **La fuente por app** entrega ceros mientras espera. El VAD no abre nada con silencio digital, así que no se traduce nada.
