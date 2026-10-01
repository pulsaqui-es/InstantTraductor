"""Errores del contrato entre etapas."""


class EngineError(RuntimeError):
    """Fallo de un motor (ASR, traducción, voz, audio). `recoverable` indica si vale la pena reintentar."""

    def __init__(self, message: str, *, engine: str, recoverable: bool = True) -> None:
        super().__init__(message)
        self.engine = engine
        self.recoverable = recoverable
