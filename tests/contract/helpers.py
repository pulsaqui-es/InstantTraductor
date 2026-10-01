"""Utilidades compartidas por las suites de contrato y por los tests de los dobles.

- `assert_implements`: comprueba que un objeto cumple un `Protocol` del contrato (miembros y firmas).
- Generadores de audio sintético a 16 kHz: `silence`, `tone` y `voiced`.
- `to_chunks`: trocea un array en `AudioChunk` contiguos.
"""

from __future__ import annotations

import inspect

import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import CAPTURE_RATE, AudioChunk

Samples = npt.NDArray[np.float32]


def protocol_members(protocol: type) -> frozenset[str]:
    """Nombres de los miembros (métodos, propiedades y atributos) que declara un Protocol."""
    return frozenset(protocol.__protocol_attrs__)  # type: ignore[attr-defined]


def _parameters(function: object) -> list[inspect.Parameter]:
    return [p for p in inspect.signature(function).parameters.values() if p.name != "self"]  # type: ignore[arg-type]


def assert_implements(obj: object, protocol: type) -> None:
    """Comprueba que `obj` cumple `protocol`.

    - Tiene todos los miembros del Protocol.
    - Los métodos son invocables y sus parámetros empiezan por los mismos nombres y en el mismo orden;
      los parámetros que añada la implementación deben ser opcionales.

    Los Protocols del contrato no son `runtime_checkable`, y `isinstance` no comprobaría las firmas.
    """
    cls_name = type(obj).__name__
    members = sorted(protocol_members(protocol))
    missing = [name for name in members if not hasattr(obj, name)]
    assert not missing, f"{cls_name} no cumple {protocol.__name__}: faltan {missing}"

    for name in members:
        declared = inspect.getattr_static(protocol, name, None)
        if not inspect.isfunction(declared):
            continue  # propiedad o atributo de datos: basta con que exista
        implementation = getattr(obj, name)
        assert callable(implementation), f"{cls_name}.{name} debería ser un método"
        expected = [p.name for p in _parameters(declared)]
        actual = _parameters(implementation)
        assert [p.name for p in actual[: len(expected)]] == expected, (
            f"{cls_name}.{name}{inspect.signature(implementation)} no coincide con "
            f"{protocol.__name__}.{name}({', '.join(expected)})"
        )
        extra_required = [
            p.name
            for p in actual[len(expected) :]
            if p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert not extra_required, (
            f"{cls_name}.{name} exige parámetros que el contrato no tiene: {extra_required}"
        )


def silence(duration_s: float, rate: int = CAPTURE_RATE) -> Samples:
    """Silencio digital (ceros)."""
    return np.zeros(round(duration_s * rate), dtype=np.float32)


def tone(
    duration_s: float, freq_hz: float = 440.0, *, rate: int = CAPTURE_RATE, amplitude: float = 0.3
) -> Samples:
    """Tono senoidal."""
    t = np.arange(round(duration_s * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def voiced(duration_s: float, rate: int = CAPTURE_RATE) -> Samples:
    """Señal sonora que imita un tramo de habla: un tono con la amplitud modulada a unos 4 Hz.

    Nunca baja de la mitad de su amplitud, así que un detector por energía la ve siempre como voz.
    Un VAD o un ASR reales no la reconocen como habla: ellos usan audio de verdad.
    """
    t = np.arange(round(duration_s * rate)) / rate
    envelope = 0.6 + 0.4 * np.sin(2 * np.pi * 4.0 * t)
    return (0.3 * envelope * np.sin(2 * np.pi * 150.0 * t)).astype(np.float32)


def to_chunks(
    samples: Samples, *, t0: float = 0.0, chunk_s: float = 0.02, rate: int = CAPTURE_RATE
) -> list[AudioChunk]:
    """Trocea `samples` en chunks contiguos de `chunk_s` segundos, el primero en `t0` (reloj de audio).

    El último chunk puede ser más corto.
    """
    size = max(1, round(chunk_s * rate))
    return [
        AudioChunk(samples=samples[pos : pos + size].copy(), sample_rate=rate, t_start=t0 + pos / rate)
        for pos in range(0, len(samples), size)
    ]
