"""Tests de ``tts/http_client.py``: ``HttpSynthesizer`` sobre ``httpx.MockTransport`` (T026).

``FakeTtsService`` hace de servicio de voz según ``contracts/tts-service.md``: ``GET /voices``,
``GET /health`` y ``POST /synthesize`` con PCM ``float32`` little-endian en bloques del tamaño que se pida
(también de tamaños que parten una muestra por la mitad). ``SynthesizerContract`` se concreta cuatro veces:
con bloques alineados, con bloques que no son múltiplo de 4 bytes, con bloques de un solo byte y con todo el
audio en un solo bloque.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import httpx
import numpy as np
import pytest

from instanttraductor.contracts import EngineError, SynthesisRequest, Synthesizer, VoiceInfo, VoiceRef
from instanttraductor.tts.http_client import DEFAULT_NAME, DEFAULT_SAMPLE_RATE, HttpSynthesizer
from tests.contract.helpers import assert_implements
from tests.contract.test_synthesis_contract import SynthesizerContract

BASE_URL = "http://127.0.0.1:51234"
RATE = 24_000
WORD_S = 0.05  # 50 ms de tono por palabra

VOICES: list[dict[str, str]] = [
    {
        "voice_id": "es-f-uno",
        "name": "Voz uno",
        "gender": "f",
        "source": "LibriVox, lector A",
        "license": "PD",
    },
    {"voice_id": "es-m-tux", "name": "Tux", "gender": "m", "source": "LibriVox, lector Tux", "license": "PD"},
    {
        "voice_id": "es-f-dos",
        "name": "Voz dos",
        "gender": "f",
        "source": "LibriVox, lectora B",
        "license": "PD",
    },
]


def tone(words: int) -> np.ndarray:
    n = round(max(1, words) * WORD_S * RATE)
    return (0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / RATE)).astype(np.float32)


class TrackedStream(httpx.SyncByteStream):
    """Cuerpo de respuesta por bloques que anota cuántos se han leído, si se cerró y si falla a mitad."""

    def __init__(self, blocks: Sequence[bytes], *, fail_after: int | None = None) -> None:
        self.blocks = list(blocks)
        self.fail_after = fail_after
        self.consumed = 0
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        for index, block in enumerate(self.blocks):
            if self.fail_after is not None and index == self.fail_after:
                raise httpx.RemoteProtocolError(
                    "peer closed connection without sending complete message body"
                )
            self.consumed += 1
            yield block

    def close(self) -> None:
        self.closed = True


def split(data: bytes, size: int) -> list[bytes]:
    return [data[start : start + size] for start in range(0, len(data), size)]


class FakeTtsService:
    """El servicio de voz de ``contracts/tts-service.md`` como manejador de ``httpx.MockTransport``."""

    def __init__(self, *, block_bytes: int = 4096, voices: list[dict[str, str]] | None = None) -> None:
        self.block_bytes = block_bytes
        self.voices = VOICES if voices is None else voices
        self.requests: list[httpx.Request] = []
        self.streams: list[TrackedStream] = []
        self.sample_rate_header: str | None = str(RATE)
        self.pcm: bytes | None = None  # si se da, es lo que se devuelve en vez del tono
        self.status = 200
        self.error_body: Any = {"error": "fallo del servicio de prueba"}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path == "/voices":
            return httpx.Response(self.status, json=self.voices if self.status == 200 else self.error_body)
        if request.method == "GET" and path == "/health":
            return httpx.Response(200, json={"status": "ok", "sample_rate": RATE})
        if request.method == "POST" and path == "/synthesize":
            return self.synthesize(json.loads(request.content))
        return httpx.Response(404, json={"error": "Not Found"})

    def synthesize(self, body: dict[str, Any]) -> httpx.Response:
        if self.status != 200:
            if isinstance(self.error_body, str):
                return httpx.Response(self.status, content=self.error_body.encode())
            return httpx.Response(self.status, json=self.error_body)
        pcm = (
            self.pcm if self.pcm is not None else tone(len(str(body["text"]).split())).astype("<f4").tobytes()
        )
        stream = TrackedStream(split(pcm, self.block_bytes))
        self.streams.append(stream)
        headers = {"Content-Type": "application/octet-stream"}
        if self.sample_rate_header is not None:
            headers["X-Sample-Rate"] = self.sample_rate_header
        return httpx.Response(200, headers=headers, stream=stream)


def make_synth(
    service: FakeTtsService | Callable[[httpx.Request], httpx.Response], **kwargs: Any
) -> HttpSynthesizer:
    return HttpSynthesizer(BASE_URL, transport=httpx.MockTransport(service), **kwargs)


def request(
    text: str = "Hola, ¿qué tal?", voice: str = "es-f-uno", *, unit_id: int = 7, speed: float = 1.0
) -> SynthesisRequest:
    return SynthesisRequest(unit_id=unit_id, text=text, voice=VoiceRef(voice), speed=speed)


def collect(synth: Synthesizer, req: SynthesisRequest | None = None) -> list[Any]:
    return list(synth.synthesize(req or request()))


def audio_of(chunks: list[Any]) -> np.ndarray:
    return np.concatenate([chunk.samples for chunk in chunks])


# --------------------------------------------------------------------------------------------------
# La suite de contrato
# --------------------------------------------------------------------------------------------------
class TestHttpSynthesizerContract(SynthesizerContract):
    block_bytes = 4096

    @pytest.fixture
    def make_impl(self) -> Callable[[], Synthesizer]:
        return lambda: make_synth(FakeTtsService(block_bytes=self.block_bytes))


class TestHttpSynthesizerContractWithMisalignedBlocks(TestHttpSynthesizerContract):
    block_bytes = 3201  # no es múltiplo de 4: una muestra queda partida entre dos bloques


class TestHttpSynthesizerContractWithOneByteBlocks(TestHttpSynthesizerContract):
    block_bytes = 1


class TestHttpSynthesizerContractWithBigBlocks(TestHttpSynthesizerContract):
    block_bytes = 1 << 20  # todo el audio en un solo bloque


# --------------------------------------------------------------------------------------------------
# synthesize
# --------------------------------------------------------------------------------------------------
class TestSynthesize:
    def test_declares_what_the_qwen3_service_is_by_default(self) -> None:
        synth = make_synth(FakeTtsService())

        assert synth.name == DEFAULT_NAME
        assert synth.sample_rate == DEFAULT_SAMPLE_RATE == RATE
        assert synth.supports_speed is False
        assert_implements(synth, Synthesizer)

    def test_the_declared_name_rate_and_speed_support_are_configurable(self) -> None:
        synth = make_synth(FakeTtsService(), name="otro-motor", sample_rate=22_050, supports_speed=True)

        assert (synth.name, synth.sample_rate, synth.supports_speed) == ("otro-motor", 22_050, True)

    def test_posts_the_request_as_json_to_the_synthesize_endpoint(self) -> None:
        service = FakeTtsService()

        collect(make_synth(service), request("Vale, nos vemos.", "es-m-tux", speed=1.25))

        (sent,) = service.requests
        assert (sent.method, sent.url) == ("POST", httpx.URL(f"{BASE_URL}/synthesize"))
        assert sent.headers["content-type"] == "application/json"
        assert json.loads(sent.content) == {"text": "Vale, nos vemos.", "voice_id": "es-m-tux", "speed": 1.25}

    def test_the_text_travels_with_its_non_ascii_characters_intact(self) -> None:
        service = FakeTtsService()
        text = "¿Vosotros sabéis dónde está la señora Núñez? ¡Qué pasada!"

        collect(make_synth(service), request(text))

        assert json.loads(service.requests[0].content)["text"] == text

    def test_every_chunk_carries_the_unit_id_the_rate_and_float32_mono_audio(self) -> None:
        chunks = collect(make_synth(FakeTtsService(block_bytes=1000)), request(unit_id=42))

        assert len(chunks) > 2
        assert {chunk.unit_id for chunk in chunks} == {42}
        assert {chunk.sample_rate for chunk in chunks} == {RATE}
        assert all(chunk.samples.dtype == np.float32 and chunk.samples.ndim == 1 for chunk in chunks)

    def test_the_audio_is_exactly_what_the_service_sent(self) -> None:
        service = FakeTtsService(block_bytes=1000)
        text = "Vamos a salir antes de que anochezca"

        chunks = collect(make_synth(service), request(text))

        assert np.array_equal(audio_of(chunks), tone(len(text.split())))

    @pytest.mark.parametrize("block_bytes", [1, 2, 3, 5, 7, 4093, 4096])
    def test_a_sample_split_across_blocks_is_rebuilt_and_no_audio_is_lost(self, block_bytes: int) -> None:
        text = "Hola, ¿qué tal todo?"
        chunks = collect(make_synth(FakeTtsService(block_bytes=block_bytes)), request(text))

        assert np.array_equal(audio_of(chunks), tone(len(text.split())))

    def test_the_last_chunk_is_empty_and_alone_marks_the_end(self) -> None:
        """No se retiene ningún bloque esperando al siguiente: el primer audio sale en cuanto llega."""
        chunks = collect(make_synth(FakeTtsService(block_bytes=2000)))

        assert [chunk.is_last for chunk in chunks] == [False] * (len(chunks) - 1) + [True]
        assert chunks[-1].samples.size == 0
        assert all(chunk.samples.size > 0 for chunk in chunks[:-1])

    def test_the_first_chunk_is_yielded_before_the_rest_of_the_body_is_read(self) -> None:
        service = FakeTtsService(block_bytes=2000)
        generator = make_synth(service).synthesize(request("uno dos tres cuatro cinco seis"))

        first = next(generator)

        assert first.samples.size > 0 and not first.is_last
        assert service.streams[0].consumed == 1
        assert len(service.streams[0].blocks) > 3
        generator.close()

    def test_closing_the_generator_early_closes_the_response(self) -> None:
        service = FakeTtsService(block_bytes=2000)
        generator = make_synth(service).synthesize(request("uno dos tres cuatro cinco seis"))
        next(generator)

        generator.close()

        assert service.streams[0].closed

    def test_a_complete_read_closes_the_response_too(self) -> None:
        service = FakeTtsService()

        collect(make_synth(service))

        assert service.streams[0].closed

    def test_non_finite_and_out_of_range_samples_are_sanitized(self) -> None:
        service = FakeTtsService()
        dirty = np.array([np.nan, np.inf, -np.inf, 1.5, -2.0, 0.5], dtype="<f4")
        service.pcm = dirty.tobytes()

        samples = audio_of(collect(make_synth(service)))

        assert samples.tolist() == [0.0, 1.0, -1.0, 1.0, -1.0, 0.5]

    def test_the_chunks_do_not_share_memory_with_each_other_and_can_be_kept(self) -> None:
        chunks = collect(make_synth(FakeTtsService(block_bytes=1000)))
        before = [chunk.samples.copy() for chunk in chunks]

        chunks[0].samples[:] = 0.0  # tocar uno no estropea a los demás

        assert all(np.array_equal(a.samples, b) for a, b in zip(chunks[1:], before[1:], strict=True))

    def test_the_url_can_be_a_callable_evaluated_on_every_request(self) -> None:
        """Tras un reinicio del servicio (``--port 0``) el puerto cambia: el cliente sigue al nuevo."""
        service = FakeTtsService()
        urls = iter(["http://127.0.0.1:1111", "http://127.0.0.1:2222"])
        synth = HttpSynthesizer(lambda: next(urls), transport=httpx.MockTransport(service))

        collect(synth)
        collect(synth)

        assert [str(sent.url) for sent in service.requests] == [
            "http://127.0.0.1:1111/synthesize",
            "http://127.0.0.1:2222/synthesize",
        ]

    def test_a_trailing_slash_in_the_url_is_fine(self) -> None:
        service = FakeTtsService()

        collect(HttpSynthesizer(BASE_URL + "/", transport=httpx.MockTransport(service)))

        assert str(service.requests[0].url) == f"{BASE_URL}/synthesize"


# --------------------------------------------------------------------------------------------------
# Errores
# --------------------------------------------------------------------------------------------------
class TestErrors:
    @pytest.mark.parametrize(
        ("status", "recoverable"),
        [(400, False), (404, False), (422, False), (500, True), (502, True), (503, True)],
    )
    def test_an_http_error_status_is_an_engine_error_with_the_service_message(
        self, status: int, recoverable: bool
    ) -> None:
        service = FakeTtsService()
        service.status = status
        service.error_body = {"error": "voice_id desconocido: 'x'."}
        synth = make_synth(service, name="qwen3-tts")

        with pytest.raises(EngineError) as error:
            collect(synth)

        assert error.value.engine == "qwen3-tts"
        assert error.value.recoverable is recoverable
        assert "voice_id desconocido" in str(error.value)
        assert str(status) in str(error.value)

    def test_an_error_that_is_not_json_still_reports_the_status_and_the_text(self) -> None:
        service = FakeTtsService()
        service.status = 500
        service.error_body = "Internal Server Error"

        with pytest.raises(EngineError, match=r"500.*Internal Server Error"):
            collect(make_synth(service))

    def test_an_empty_error_body_reports_the_status(self) -> None:
        service = FakeTtsService()
        service.status = 503
        service.error_body = ""

        with pytest.raises(EngineError, match="503"):
            collect(make_synth(service))

    def test_the_error_response_is_closed(self) -> None:
        closed: list[bool] = []

        class Body(httpx.SyncByteStream):
            def __iter__(self) -> Iterator[bytes]:
                yield b'{"error": "boom"}'

            def close(self) -> None:
                closed.append(True)

        synth = make_synth(lambda _request: httpx.Response(500, stream=Body()))

        with pytest.raises(EngineError):
            collect(synth)

        assert closed == [True]

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.ConnectError("conexión rechazada"),
            httpx.ConnectTimeout("sin respuesta"),
            httpx.ReadTimeout("el servicio no contesta"),
            httpx.RemoteProtocolError("el servicio cortó la conexión"),
        ],
    )
    def test_a_network_failure_is_a_recoverable_engine_error(self, failure: httpx.HTTPError) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise failure

        with pytest.raises(EngineError) as error:
            collect(make_synth(handler, name="qwen3-tts"))

        assert error.value.recoverable is True
        assert error.value.engine == "qwen3-tts"
        assert error.value.__cause__ is failure

    def test_a_response_cut_in_the_middle_delivers_what_arrived_and_then_fails(self) -> None:
        stream = TrackedStream([b"\x00\x00\x80\x3e" * 100, b"\x00\x00\x80\x3e" * 100, b"x"], fail_after=2)
        synth = make_synth(
            lambda _request: httpx.Response(200, headers={"X-Sample-Rate": str(RATE)}, stream=stream)
        )
        received: list[Any] = []

        with pytest.raises(EngineError) as error:
            for chunk in synth.synthesize(request()):
                received.append(chunk)

        assert [chunk.samples.size for chunk in received] == [100, 100]
        assert error.value.recoverable is True
        assert stream.closed

    def test_a_missing_sample_rate_header_is_an_error(self) -> None:
        service = FakeTtsService()
        service.sample_rate_header = None

        with pytest.raises(EngineError, match="X-Sample-Rate"):
            collect(make_synth(service))

    @pytest.mark.parametrize("value", ["", "rapido", "24000.5", "0", "-24000"])
    def test_an_invalid_sample_rate_header_is_an_error(self, value: str) -> None:
        service = FakeTtsService()
        service.sample_rate_header = value

        with pytest.raises(EngineError, match="X-Sample-Rate"):
            collect(make_synth(service))

    def test_a_sample_rate_different_from_the_declared_one_is_a_non_recoverable_error(self) -> None:
        service = FakeTtsService()
        service.sample_rate_header = "48000"

        with pytest.raises(EngineError, match="48000") as error:
            collect(make_synth(service))

        assert error.value.recoverable is False

    def test_a_body_without_audio_is_an_error(self) -> None:
        service = FakeTtsService()
        service.pcm = b""

        with pytest.raises(EngineError, match="audio"):
            collect(make_synth(service))

    def test_a_body_that_ends_in_the_middle_of_a_sample_is_an_error(self) -> None:
        service = FakeTtsService()
        service.pcm = tone(2).astype("<f4").tobytes() + b"\x01\x02"

        with pytest.raises(EngineError, match="muestra"):
            collect(make_synth(service))

    def test_a_body_with_less_than_one_sample_is_an_error(self) -> None:
        service = FakeTtsService()
        service.pcm = b"\x01\x02\x03"

        with pytest.raises(EngineError):
            collect(make_synth(service))

    def test_the_synthesizer_keeps_working_after_an_error(self) -> None:
        service = FakeTtsService()
        synth = make_synth(service)
        service.status = 500
        with pytest.raises(EngineError):
            collect(synth)
        service.status = 200

        assert audio_of(collect(synth)).size > 0


# --------------------------------------------------------------------------------------------------
# list_voices
# --------------------------------------------------------------------------------------------------
class TestListVoices:
    def test_returns_the_voices_as_voice_info_in_the_service_order(self) -> None:
        voices = make_synth(FakeTtsService()).list_voices()

        assert isinstance(voices, tuple)
        assert voices[0] == VoiceInfo("es-f-uno", "Voz uno", "f", "LibriVox, lector A", "PD")
        assert [voice.voice_id for voice in voices] == ["es-f-uno", "es-m-tux", "es-f-dos"]
        assert [voice.gender for voice in voices] == ["f", "m", "f"]

    def test_gets_the_voices_endpoint(self) -> None:
        service = FakeTtsService()

        make_synth(service).list_voices()

        (sent,) = service.requests
        assert (sent.method, str(sent.url)) == ("GET", f"{BASE_URL}/voices")

    def test_unknown_fields_of_the_service_are_ignored(self) -> None:
        service = FakeTtsService(voices=[{**VOICES[0], "ref_text": "algo", "extra": "1"}])

        (voice,) = make_synth(service).list_voices()

        assert voice == VoiceInfo("es-f-uno", "Voz uno", "f", "LibriVox, lector A", "PD")

    @pytest.mark.parametrize(
        "voices",
        [
            {"voices": []},
            "no es una lista",
            [{"voice_id": "es-f-uno"}],
            [{**VOICES[0], "gender": "x"}],
            [{**VOICES[0], "voice_id": ""}],
            [{**VOICES[0], "name": 7}],
            [["es-f-uno"]],
            [None],
        ],
    )
    def test_a_malformed_voice_list_is_a_non_recoverable_engine_error(self, voices: Any) -> None:
        service = FakeTtsService(voices=voices)

        with pytest.raises(EngineError) as error:
            make_synth(service).list_voices()

        assert error.value.recoverable is False

    def test_a_body_that_is_not_json_is_an_engine_error(self) -> None:
        synth = make_synth(lambda _request: httpx.Response(200, content=b"<html>"))

        with pytest.raises(EngineError):
            synth.list_voices()

    @pytest.mark.parametrize(("status", "recoverable"), [(503, True), (404, False)])
    def test_an_http_error_is_an_engine_error(self, status: int, recoverable: bool) -> None:
        service = FakeTtsService()
        service.status = status
        service.error_body = {"error": "El modelo aún no está listo."}

        with pytest.raises(EngineError, match="aún no está listo") as error:
            make_synth(service).list_voices()

        assert error.value.recoverable is recoverable

    def test_a_network_failure_is_a_recoverable_engine_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("conexión rechazada")

        with pytest.raises(EngineError) as error:
            make_synth(handler).list_voices()

        assert error.value.recoverable is True


# --------------------------------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------------------------------
class TestLifecycle:
    def test_close_is_idempotent(self) -> None:
        synth = make_synth(FakeTtsService())

        synth.close()
        synth.close()

    def test_nothing_works_after_close(self) -> None:
        synth = make_synth(FakeTtsService())
        synth.close()

        with pytest.raises(EngineError, match="cerrado") as synth_error:
            collect(synth)
        with pytest.raises(EngineError, match="cerrado"):
            synth.list_voices()

        assert synth_error.value.recoverable is False

    def test_closing_the_transport_releases_the_client(self) -> None:
        closed: list[bool] = []

        class Transport(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, json=VOICES)

            def close(self) -> None:
                closed.append(True)

        synth = HttpSynthesizer(BASE_URL, transport=Transport())
        synth.list_voices()

        synth.close()

        assert closed == [True]

    def test_the_repr_names_the_engine_and_the_service(self) -> None:
        text = repr(make_synth(FakeTtsService(), name="qwen3-tts"))

        assert "qwen3-tts" in text
        assert BASE_URL in text
