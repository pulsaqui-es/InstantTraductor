"""Cliente del servicio de voz: ``HttpSynthesizer`` (T026, ``contracts/tts-service.md``).

``HttpSynthesizer`` implementa ``Synthesizer`` hablando con el servicio de voz local (lo lanza
``tts/service_process.py``). ``synthesize`` hace ``POST /synthesize`` y lee la respuesta en *streaming*:
cada bloque que llega se convierte en un ``SynthesizedChunk`` sin esperar al siguiente, así que el primer
audio sale en cuanto el motor lo tiene (p95 de 0,18 s con Qwen3-TTS).

- El cuerpo es PCM ``float32`` little-endian mono y los bloques de la red no tienen por qué ser múltiplos de
  4 bytes: lo que sobra de un bloque se guarda para el siguiente.
- La frecuencia sale de la cabecera ``X-Sample-Rate`` y debe ser la ``sample_rate`` declarada (la de la línea
  ``ready``). El audio se sanea: sin NaN ni infinitos y dentro de [-1, 1].
- **El último trozo (``is_last=True``) va vacío.** El fin del cuerpo es lo único que marca el fin del audio, y
  no se retiene ningún bloque esperando saber si es el último: eso retrasaría el primer audio un bloque
  entero (333 ms con ``chunk_size`` 4). Los demás trozos llevan audio.
- Un 4xx o 5xx del servicio y cualquier fallo de red o de protocolo (incluido un cuerpo cortado a mitad) se
  lanzan como ``EngineError``. ``recoverable`` es ``False`` para un 4xx (reintentar no cambia nada) y
  ``True`` para un 5xx o un fallo de red.
- ``supports_speed`` vale ``False`` por defecto: Qwen3-TTS no tiene parámetro de velocidad y el núcleo
  acelera con *time-stretch* (research R9). ``speed`` se envía igualmente; el servicio lo valida y lo ignora.

La URL puede ser un ``str`` o una función que la devuelve en cada petición: con ``--port 0`` un reinicio del
servicio cambia el puerto, y ``TtsServiceProcess.synthesizer()`` pasa una función que lee el puerto vigente.

Los trozos son arrays nuevos (``float32``, mono) que nadie más usa. Un ``HttpSynthesizer`` se puede usar desde
varios hilos; cada ``synthesize`` es un generador independiente.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from typing import Any, Final

import httpx
import numpy as np
import numpy.typing as npt

from instanttraductor.contracts import EngineError, SynthesisRequest, SynthesizedChunk, VoiceInfo

__all__ = [
    "CONNECT_TIMEOUT_S",
    "DEFAULT_NAME",
    "DEFAULT_SAMPLE_RATE",
    "READ_TIMEOUT_S",
    "HttpSynthesizer",
]

#: Nombre del motor si no se dice otro (la línea ``ready`` trae el verdadero: ``qwen3-tts``).
DEFAULT_NAME: Final = "tts-service"
#: Frecuencia de Qwen3-TTS.
DEFAULT_SAMPLE_RATE: Final = 24_000
CONNECT_TIMEOUT_S: Final = 2.0
#: Tiempo máximo sin recibir nada del servicio (también entre dos bloques de audio).
READ_TIMEOUT_S: Final = 10.0

_SAMPLE_BYTES: Final = 4  # float32
_ERROR_TEXT_CHARS: Final = 200

Samples = npt.NDArray[np.float32]


def _decode(data: bytes) -> Samples:
    """PCM ``float32`` little-endian a un array nuevo, finito y dentro de [-1, 1]."""
    samples = np.frombuffer(data, dtype="<f4").astype(np.float32)
    if not np.isfinite(samples).all():
        samples = np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)
    np.clip(samples, -1.0, 1.0, out=samples)
    return samples


class HttpSynthesizer:
    """``Synthesizer`` que habla con el servicio de voz local por HTTP.

    - ``base_url``: ``http://127.0.0.1:<puerto>``, o una función sin argumentos que lo devuelve (se llama en
      cada petición).
    - ``name``, ``sample_rate`` y ``supports_speed``: lo que dice el servicio en su línea ``ready``.
    - ``timeout_s``: tiempo máximo sin recibir datos. ``transport``: solo en los tests (``MockTransport``).
    """

    def __init__(
        self,
        base_url: str | Callable[[], str],
        *,
        name: str = DEFAULT_NAME,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        supports_speed: bool = False,
        timeout_s: float = READ_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ValueError(f"sample_rate debe ser un entero positivo en Hz (recibido {sample_rate!r}).")
        self.name = name
        self.sample_rate = sample_rate
        self.supports_speed = supports_speed
        self._base_url = base_url
        if transport is None:
            # TCP_NODELAY: sin él, el algoritmo de Nagle retiene el cuerpo de la petición hasta el ACK de las
            # cabeceras y suma decenas de ms al primer audio.
            transport = httpx.HTTPTransport(socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)])
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=min(timeout_s, CONNECT_TIMEOUT_S)),
            transport=transport,
            trust_env=False,  # solo se habla con 127.0.0.1: nada de proxys del entorno
        )
        self._closed = False

    def __repr__(self) -> str:
        url = self._base_url if isinstance(self._base_url, str) else "<función>"
        return f"HttpSynthesizer(name={self.name!r}, url={url!r}, sample_rate={self.sample_rate})"

    # -- Synthesizer -----------------------------------------------------------------------------------
    def synthesize(self, request: SynthesisRequest) -> Iterator[SynthesizedChunk]:
        """Síntesis en streaming. Lanza ``EngineError`` si el servicio falla (también a mitad del audio)."""
        self._check_open()
        url = self._url("/synthesize")
        payload = {"text": request.text, "voice_id": request.voice.voice_id, "speed": request.speed}
        try:
            with self._client.stream("POST", url, json=payload) as response:
                if response.status_code != 200:
                    response.read()
                    raise self._status_error(response, "la síntesis")
                rate = self._response_rate(response)
                pending = b""
                produced = False
                for block in response.iter_bytes():
                    data = pending + block if pending else block
                    usable = len(data) - len(data) % _SAMPLE_BYTES
                    pending = data[usable:]
                    if usable:
                        produced = True
                        yield SynthesizedChunk(request.unit_id, _decode(data[:usable]), rate, is_last=False)
                if pending:
                    raise EngineError(
                        f"El audio del servicio acabó a mitad de una muestra ({len(pending)} bytes de más).",
                        engine=self.name,
                        recoverable=True,
                    )
                if not produced:
                    raise EngineError(
                        "El servicio de voz no devolvió audio.", engine=self.name, recoverable=True
                    )
                yield SynthesizedChunk(request.unit_id, np.zeros(0, dtype=np.float32), rate, is_last=True)
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise self._network_error(error, "la síntesis") from error

    def list_voices(self) -> tuple[VoiceInfo, ...]:
        """Las voces del servicio (``GET /voices``). ``EngineError`` si falla o responde algo no válido."""
        self._check_open()
        try:
            response = self._client.get(self._url("/voices"))
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise self._network_error(error, "la lista de voces") from error
        if response.status_code != 200:
            raise self._status_error(response, "la lista de voces")
        try:
            items = response.json()
        except ValueError as error:
            raise self._invalid("La lista de voces no es un JSON válido.") from error
        if not isinstance(items, list):
            raise self._invalid("La lista de voces debe ser un array JSON.")
        return tuple(self._voice_info(item) for item in items)

    def close(self) -> None:
        """Cierra las conexiones. Es idempotente."""
        if self._closed:
            return
        self._closed = True
        self._client.close()

    # -- internos --------------------------------------------------------------------------------------
    def _check_open(self) -> None:
        if self._closed:
            raise EngineError(
                "El cliente del servicio de voz está cerrado.", engine=self.name, recoverable=False
            )

    def _url(self, path: str) -> str:
        base = self._base_url() if callable(self._base_url) else self._base_url
        return base.rstrip("/") + path

    def _invalid(self, message: str) -> EngineError:
        return EngineError(message, engine=self.name, recoverable=False)

    def _network_error(self, error: Exception, what: str) -> EngineError:
        # Una URL mal formada no se arregla reintentando; un fallo de red o de protocolo, a lo mejor sí.
        return EngineError(
            f"No se pudo hablar con el servicio de voz ({what}): {error}",
            engine=self.name,
            recoverable=not isinstance(error, httpx.InvalidURL),
        )

    def _status_error(self, response: httpx.Response, what: str) -> EngineError:
        status = response.status_code
        return EngineError(
            f"El servicio de voz respondió {status} a {what}: {self._error_text(response)}",
            engine=self.name,
            recoverable=status >= 500 or status in (408, 429),
        )

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        """El ``{"error": str}`` del servicio o, si no es JSON, el principio del cuerpo."""
        try:
            body: Any = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and isinstance(body.get("error"), str) and body["error"].strip():
            return body["error"].strip()
        text = response.text.strip()
        return text[:_ERROR_TEXT_CHARS] if text else (response.reason_phrase or "sin detalle")

    def _response_rate(self, response: httpx.Response) -> int:
        raw = response.headers.get("x-sample-rate")
        try:
            rate = int(raw)  # type: ignore[arg-type]  # None -> TypeError
        except (TypeError, ValueError):
            rate = 0
        if rate <= 0:
            raise self._invalid(
                f"Falta la cabecera X-Sample-Rate o no es una frecuencia válida (recibida {raw!r})."
            )
        if rate != self.sample_rate:
            raise self._invalid(f"El servicio responde a {rate} Hz y se esperaban {self.sample_rate} Hz.")
        return rate

    def _voice_info(self, item: Any) -> VoiceInfo:
        if not isinstance(item, dict):
            raise self._invalid(f"Una voz de la lista no es un objeto JSON: {item!r}.")
        fields: dict[str, str] = {}
        for key in ("voice_id", "name", "source", "license"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise self._invalid(f"Una voz de la lista no tiene «{key}» o no es un texto: {item!r}.")
            fields[key] = value
        gender = item.get("gender")
        if gender not in ("f", "m"):
            raise self._invalid(
                f"El «gender» de la voz {fields['voice_id']!r} debe ser «f» o «m» (recibido {gender!r})."
            )
        return VoiceInfo(
            voice_id=fields["voice_id"],
            name=fields["name"],
            gender=gender,
            source=fields["source"],
            license=fields["license"],
        )
