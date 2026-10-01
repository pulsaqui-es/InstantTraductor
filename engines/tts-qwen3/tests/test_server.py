"""Tests del servicio de voz sin GPU (T025).

Cuatro grupos:

1. El catálogo de voces, el motor (``Qwen3Engine``) con un modelo falso y ``load_engine`` hasta donde llega
   sin GPU.
2. La API de ``contracts/tts-service.md`` con el ``TestClient`` de FastAPI y un motor falso (``FakeEngine``).
3. El servicio entero con ``main()`` en el mismo proceso y un puerto real: línea ``ready``, *streaming* de
   verdad, un fallo a mitad de la respuesta, un cliente que se va y la parada.
4. El servicio como proceso aparte: la línea ``ready`` por una tubería, la parada en <= 2 s y los arranques
   con error.

El modelo real y la GPU se prueban en ``test_engine_gpu.py`` (marcadores ``gpu`` y ``model``).
"""

from __future__ import annotations

import contextlib
import io
import json
import queue
import socket
import subprocess
import sys
import threading
import time
import types
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
import soundfile

with warnings.catch_warnings():
    # Starlette 1.x avisa de que su TestClient prefiere ``httpx2``; el motor solo tiene ``httpx``.
    warnings.filterwarnings("ignore", message=".*starlette.testclient.*")
    from fastapi.testclient import TestClient

from tts_service.engine import (
    CHUNK_SIZE,
    MODEL_DIR_NAME,
    EngineLoadError,
    Qwen3Engine,
    ServiceConfig,
    UnknownVoiceError,
    Voice,
    VoiceCatalogError,
    load_engine,
    load_voices,
)
from tts_service.server import MAX_TEXT_CHARS, EngineHost, create_app, main

#: Margen para esperas que NO miden ningún requisito de tiempo (el arranque de Python varía).
GENEROUS_S = 20.0
MIB = 1024 * 1024
REFERENCE_RATE = 24_000
REF_TEXT = "Expedito, pero doña Francisca, no convencida, continuó chillando."


def wait_until(predicate: Callable[[], bool], timeout_s: float = 5.0, message: str = "") -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail(f"Tiempo agotado ({timeout_s:g} s): {message}")
        time.sleep(0.01)


# --------------------------------------------------------------------------------------------------
# Dobles
# --------------------------------------------------------------------------------------------------
def write_voice(directory: Path, stem: str, *, wav: bool = True, **overrides: Any) -> Path:
    """Crea ``<stem>.wav`` (1 s de tono a 24 kHz) y ``<stem>.json`` con los campos del contrato."""
    directory.mkdir(parents=True, exist_ok=True)
    if wav:
        t = np.arange(REFERENCE_RATE) / REFERENCE_RATE
        tone = (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
        soundfile.write(directory / f"{stem}.wav", tone, REFERENCE_RATE, subtype="PCM_16")
    meta: dict[str, Any] = {
        "voice_id": stem,
        "name": f"Voz {stem}",
        "gender": "f",
        "source": "LibriVox, lector de prueba, minuto 1:23",
        "license": "dominio público",
        "ref_text": REF_TEXT,
    }
    meta.update(overrides)
    meta = {key: value for key, value in meta.items() if value is not None}
    path = directory / f"{stem}.json"
    path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return path


class FakeQwenModel:
    """Imita lo que ``Qwen3Engine`` usa de ``FasterQwen3TTS``; guarda todas las llamadas para comprobarlas."""

    sample_rate = REFERENCE_RATE

    def __init__(self, *, fail_icl: bool = False, chunks: int = 3) -> None:
        self.model = self  # ``FasterQwen3TTS.model`` es el ``Qwen3TTSModel`` de qwen-tts
        self.fail_icl = fail_icl
        self.chunks = chunks
        self.prompt_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []
        self.warmups: list[int] = []
        self.order: list[str] = []
        self.closed_streams = 0

    def create_voice_clone_prompt(
        self, ref_audio: Any, ref_text: str | None = None, x_vector_only_mode: bool = False
    ) -> list[Any]:
        self.order.append("prompt")
        self.prompt_calls.append(
            {"ref_audio": ref_audio, "ref_text": ref_text, "x_vector_only_mode": x_vector_only_mode}
        )
        if self.fail_icl and not x_vector_only_mode:
            raise RuntimeError("el modo ICL no está disponible")
        return [("item", len(self.prompt_calls))]

    def warmup(self, prefill_len: int = 100) -> None:
        self.order.append("warmup")
        self.warmups.append(prefill_len)

    def generate_voice_clone_streaming(self, **kwargs: Any) -> Iterator[tuple[Any, int, dict[str, float]]]:
        self.order.append("stream")
        self.stream_calls.append(kwargs)
        return self._stream()

    def _stream(self) -> Iterator[tuple[Any, int, dict[str, float]]]:
        try:
            for index in range(self.chunks):
                yield (
                    np.full(8000, 0.1 * (index + 1), dtype=np.float32),
                    self.sample_rate,
                    {"prefill_ms": 1.0},
                )
        finally:
            self.closed_streams += 1


VOICES = (
    Voice(
        "es-f-fake", "Voz femenina", "f", "doble de pruebas", "sin licencia", Path("es-f-fake.wav"), "SECRETO"
    ),
    Voice("es-m-fake", "Voz masculina", "m", "doble de pruebas", "sin licencia", Path("es-m-fake.wav")),
)


class FakeEngine:
    """``Engine`` falso: trozos de 2 400 muestras constantes (0,1; 0,2; 0,3...) y fallos a demanda."""

    name = "fake-tts"
    model_name = "fake-model-0"
    sample_rate = 24_000
    supports_speed = False

    def __init__(self, *, chunks: int = 3, chunk_samples: int = 2400, step_delay_s: float = 0.0) -> None:
        self.chunks = chunks
        self.chunk_samples = chunk_samples
        self.step_delay_s = step_delay_s
        self.fail_before_audio = False
        self.fail_after_chunks: int | None = None
        self.silent = False
        self.custom: list[Any] | None = None  # trozos exactos que entregar (para audio no válido)
        self.gate: threading.Event | None = None  # tras el primer trozo, espera a que se abra
        self.calls: list[tuple[str, str, float]] = []
        self.produced = 0
        self.closed = False
        self.generator_closed = threading.Event()
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def voices(self) -> tuple[Voice, ...]:
        return VOICES

    def chunk(self, index: int) -> np.ndarray:
        return np.full(self.chunk_samples, 0.1 * (index + 1), dtype=np.float32)

    def expected_pcm(self, chunks: int | None = None) -> bytes:
        return b"".join(
            self.chunk(index).tobytes() for index in range(self.chunks if chunks is None else chunks)
        )

    def synthesize(self, text: str, voice_id: str, speed: float) -> Iterator[np.ndarray]:
        self.calls.append((text, voice_id, speed))
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.generator_closed.clear()
        try:
            if self.fail_before_audio:
                raise RuntimeError("fallo del motor falso")
            if self.silent:
                return
            if self.custom is not None:
                yield from self.custom
                return
            for index in range(self.chunks):
                if index == 1 and self.gate is not None and not self.gate.wait(GENEROUS_S):
                    raise TimeoutError("la compuerta del motor falso no se abrió")
                if self.fail_after_chunks is not None and index == self.fail_after_chunks:
                    raise RuntimeError("fallo del motor falso a mitad")
                if self.step_delay_s:
                    time.sleep(self.step_delay_s)
                self.produced += 1
                yield self.chunk(index)
        finally:
            with self._lock:
                self.active -= 1
            self.generator_closed.set()

    def vram_mb(self) -> int:
        return 1234

    def close(self) -> None:
        self.closed = True


# ==================================================================================================
# 1. Voces, motor y carga
# ==================================================================================================
class TestVoiceCatalog:
    def test_loads_every_voice_with_its_metadata_sorted_by_id(self, tmp_path: Path) -> None:
        write_voice(tmp_path, "es-m-tux", gender="m", name="Tux (LibriVox)")
        write_voice(tmp_path, "es-f-uno", ref_text=None)

        voices = load_voices(tmp_path)

        assert [voice.voice_id for voice in voices] == ["es-f-uno", "es-m-tux"]
        tux = voices[1]
        assert (tux.name, tux.gender, tux.license) == ("Tux (LibriVox)", "m", "dominio público")
        assert tux.wav_path == tmp_path / "es-m-tux.wav"
        assert tux.ref_text == REF_TEXT
        assert voices[0].ref_text == ""  # sin ref_text: el motor usará x_vector_only

    def test_the_public_view_has_only_the_fields_of_voice_info(self, tmp_path: Path) -> None:
        write_voice(tmp_path, "es-f-uno")

        public = load_voices(tmp_path)[0].public()

        assert set(public) == {"voice_id", "name", "gender", "source", "license"}
        assert REF_TEXT not in json.dumps(public, ensure_ascii=False)

    def test_a_json_without_its_wav_is_an_error_that_names_the_file(self, tmp_path: Path) -> None:
        write_voice(tmp_path, "es-f-uno", wav=False)

        with pytest.raises(VoiceCatalogError, match=r"es-f-uno\.json.*es-f-uno\.wav"):
            load_voices(tmp_path)

    def test_every_problem_is_reported_at_once(self, tmp_path: Path) -> None:
        write_voice(tmp_path, "es-f-uno", gender="x")
        write_voice(tmp_path, "es-f-dos", name="  ")
        (tmp_path / "es-f-tres.json").write_text("{esto no es json", encoding="utf-8")
        write_voice(tmp_path, "es-f-cuatro", voice_id="otra-voz")
        write_voice(tmp_path, "es-f-cinco", ref_text=7)
        write_voice(tmp_path, "es-f-seis", source=None)

        with pytest.raises(VoiceCatalogError) as error:
            load_voices(tmp_path)

        message = str(error.value)
        for voice_id in ("uno", "dos", "tres", "cuatro", "cinco", "seis"):
            assert f"es-f-{voice_id}.json" in message
        assert "gender" in message and "JSON no válido" in message and "voice_id" in message

    def test_an_empty_or_missing_folder_asks_to_run_preparar(self, tmp_path: Path) -> None:
        with pytest.raises(VoiceCatalogError, match="preparar"):
            load_voices(tmp_path)  # existe pero no hay voces
        with pytest.raises(VoiceCatalogError, match="preparar"):
            load_voices(tmp_path / "no-existe")

    def test_a_wav_without_json_is_not_a_voice(self, tmp_path: Path) -> None:
        write_voice(tmp_path, "es-f-uno")
        soundfile.write(tmp_path / "suelto.wav", np.zeros(100, dtype=np.float32), REFERENCE_RATE)

        assert [voice.voice_id for voice in load_voices(tmp_path)] == ["es-f-uno"]


class TestQwen3Engine:
    @pytest.fixture
    def voices_dir(self, tmp_path: Path) -> Path:
        write_voice(tmp_path, "es-m-tux", gender="m")
        return tmp_path

    def make(self, voices_dir: Path, model: FakeQwenModel | None = None, **kwargs: Any) -> Qwen3Engine:
        return Qwen3Engine(model or FakeQwenModel(), load_voices(voices_dir), **kwargs)

    def test_identifies_itself_and_does_not_support_speed(self, voices_dir: Path) -> None:
        engine = self.make(voices_dir)

        assert (engine.name, engine.model_name) == ("qwen3-tts", "Qwen3-TTS-12Hz-0.6B-Base")
        assert engine.sample_rate == 24_000
        assert engine.supports_speed is False
        assert [voice.voice_id for voice in engine.voices()] == ["es-m-tux"]

    def test_the_icl_prompt_is_the_reference_plus_half_a_second_of_silence(self, voices_dir: Path) -> None:
        model = FakeQwenModel()

        self.make(voices_dir, model)

        (call,) = model.prompt_calls
        audio, rate = call["ref_audio"]
        assert rate == REFERENCE_RATE
        assert len(audio) == REFERENCE_RATE + REFERENCE_RATE // 2
        assert audio[:REFERENCE_RATE].any()
        assert not audio[REFERENCE_RATE:].any()
        assert audio.dtype == np.float32 and audio.ndim == 1
        assert call["ref_text"] == REF_TEXT
        assert call["x_vector_only_mode"] is False

    def test_a_voice_without_ref_text_falls_back_to_x_vector_only(self, tmp_path: Path) -> None:
        write_voice(tmp_path, "es-f-uno", ref_text=None)
        model = FakeQwenModel()

        engine = Qwen3Engine(model, load_voices(tmp_path))

        (call,) = model.prompt_calls
        assert call["x_vector_only_mode"] is True
        assert call["ref_text"] == ""
        assert call["ref_audio"] == str(tmp_path / "es-f-uno.wav")
        assert list(engine.synthesize("Hola.", "es-f-uno", 1.0))
        assert model.stream_calls[0]["xvec_only"] is True

    def test_x_vector_only_can_be_forced_for_every_voice(self, voices_dir: Path) -> None:
        model = FakeQwenModel()

        engine = self.make(voices_dir, model, x_vector_only=True)

        assert [call["x_vector_only_mode"] for call in model.prompt_calls] == [True]
        list(engine.synthesize("Hola.", "es-m-tux", 1.0))
        assert model.stream_calls[0]["xvec_only"] is True
        assert model.stream_calls[0]["ref_text"] == ""

    def test_a_failing_icl_prompt_is_rescued_with_x_vector_only(
        self, voices_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        model = FakeQwenModel(fail_icl=True)

        engine = self.make(voices_dir, model)

        assert [call["x_vector_only_mode"] for call in model.prompt_calls] == [False, True]
        assert "rescate" in caplog.text
        assert list(engine.synthesize("Hola.", "es-m-tux", 1.0))

    def test_synthesize_streams_float32_chunks_using_the_cached_prompt(self, voices_dir: Path) -> None:
        model = FakeQwenModel()
        engine = self.make(voices_dir, model)

        chunks = list(engine.synthesize("Vale, nos vemos luego.", "es-m-tux", 1.0))

        assert len(chunks) == 3
        assert all(c.dtype == np.float32 and c.ndim == 1 and len(c) == 8000 for c in chunks)
        (call,) = model.stream_calls
        assert call["text"] == "Vale, nos vemos luego."
        assert call["language"] == "Spanish"
        assert call["chunk_size"] == CHUNK_SIZE == 4
        assert call["xvec_only"] is False
        assert call["ref_text"] == REF_TEXT
        assert call["voice_clone_prompt"] == [("item", 1)]  # el que se creó al construir el motor

    def test_the_prompt_is_created_once_and_reused_by_every_request(self, voices_dir: Path) -> None:
        model = FakeQwenModel()
        engine = self.make(voices_dir, model)

        for _ in range(3):
            list(engine.synthesize("Hola.", "es-m-tux", 1.0))

        assert len(model.prompt_calls) == 1
        assert len(model.stream_calls) == 3

    def test_the_chunk_size_is_configurable(self, voices_dir: Path) -> None:
        model = FakeQwenModel()

        list(self.make(voices_dir, model, chunk_size=8).synthesize("Hola.", "es-m-tux", 1.0))

        assert model.stream_calls[0]["chunk_size"] == 8

    def test_speed_is_ignored_because_the_model_has_no_such_parameter(self, voices_dir: Path) -> None:
        model = FakeQwenModel()
        engine = self.make(voices_dir, model)

        list(engine.synthesize("Hola.", "es-m-tux", 1.5))

        assert set(model.stream_calls[0]) == {
            "text",
            "language",
            "ref_text",
            "voice_clone_prompt",
            "chunk_size",
            "xvec_only",
        }

    def test_an_unknown_voice_is_an_error(self, voices_dir: Path) -> None:
        engine = self.make(voices_dir)

        with pytest.raises(UnknownVoiceError):
            next(engine.synthesize("Hola.", "no-existe", 1.0))

    def test_stopping_early_closes_the_model_stream(self, voices_dir: Path) -> None:
        model = FakeQwenModel()
        stream = self.make(voices_dir, model).synthesize("Hola.", "es-m-tux", 1.0)

        next(stream)
        stream.close()

        assert model.closed_streams == 1

    def test_warmup_captures_the_graphs_and_makes_short_syntheses_with_the_first_voice(
        self, voices_dir: Path
    ) -> None:
        write_voice(voices_dir, "es-f-uno")
        model = FakeQwenModel()
        engine = self.make(voices_dir, model)

        engine.warmup()

        assert model.warmups == [100]
        assert model.order == ["prompt", "prompt", "warmup", "stream", "stream"]
        assert all(call["text"] for call in model.stream_calls)
        assert model.stream_calls[0]["ref_text"] == REF_TEXT  # la primera voz (es-f-uno)

    def test_it_needs_at_least_one_voice_and_a_valid_chunk_size(self, voices_dir: Path) -> None:
        with pytest.raises(ValueError, match="voz"):
            Qwen3Engine(FakeQwenModel(), [])
        with pytest.raises(ValueError, match="chunk_size"):
            self.make(voices_dir, chunk_size=0)

    def test_vram_is_the_bigger_of_the_load_delta_and_what_torch_reserves(
        self, voices_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reserved = {"bytes": 2048 * MIB}
        cache_cleared: list[bool] = []
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(
                is_available=lambda: True,
                memory_reserved=lambda: reserved["bytes"],
                empty_cache=lambda: cache_cleared.append(True),
            )
        )
        monkeypatch.setitem(sys.modules, "torch", fake_torch)
        engine = self.make(voices_dir)

        assert engine.vram_mb() == 2048
        engine.load_vram_mib = 3304.0
        assert engine.vram_mb() == 3304
        engine.close()
        engine.close()  # idempotente
        assert cache_cleared == [True, True]


class TestLoadEngine:
    def test_without_voices_it_fails_before_touching_the_model(self, tmp_path: Path) -> None:
        with pytest.raises(VoiceCatalogError):
            load_engine(ServiceConfig(voices_dir=tmp_path / "voces", models_dir=tmp_path / "models"))

    def test_without_the_model_it_asks_to_run_preparar(self, tmp_path: Path) -> None:
        write_voice(tmp_path / "voces", "es-f-uno")

        with pytest.raises(EngineLoadError, match=r"preparar") as error:
            load_engine(ServiceConfig(voices_dir=tmp_path / "voces", models_dir=tmp_path / "models"))

        assert MODEL_DIR_NAME in str(error.value)

    def test_without_cuda_it_says_so(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        write_voice(tmp_path / "voces", "es-f-uno")
        model_dir = tmp_path / "models" / MODEL_DIR_NAME
        model_dir.mkdir(parents=True)
        (model_dir / "config.json").write_text("{}", encoding="utf-8")
        monkeypatch.setitem(
            sys.modules,
            "torch",
            types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False)),
        )

        with pytest.raises(EngineLoadError, match="CUDA"):
            load_engine(ServiceConfig(voices_dir=tmp_path / "voces", models_dir=tmp_path / "models"))


# ==================================================================================================
# 2. La API con TestClient
# ==================================================================================================
def synth_body(text: str = "Hola, ¿qué tal?", voice_id: str = "es-f-fake", **extra: Any) -> dict[str, Any]:
    return {"text": text, "voice_id": voice_id, **extra}


@pytest.fixture
def fake() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def shutdown_calls() -> list[bool]:
    return []


@pytest.fixture
def host(fake: FakeEngine) -> Iterator[EngineHost]:
    engine_host = EngineHost(lambda: fake)
    engine_host.start()
    assert engine_host.loaded.wait(GENEROUS_S)
    yield engine_host
    engine_host.close()


@pytest.fixture
def client(host: EngineHost, shutdown_calls: list[bool]) -> Iterator[TestClient]:
    with TestClient(create_app(host, request_shutdown=lambda: shutdown_calls.append(True))) as test_client:
        yield test_client


def assert_error(response: httpx.Response, status: int) -> str:
    """Un error del contrato: ``application/json`` con ``{"error": str}`` y nada más."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {"error"}
    assert isinstance(body["error"], str) and body["error"]
    return body["error"]


class TestHealth:
    def test_reports_the_engine_and_its_capabilities(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "engine": "fake-tts",
            "model": "fake-model-0",
            "sample_rate": 24_000,
            "supports_speed": False,
            "vram_mb": 1234,
        }

    def test_a_failing_vram_probe_does_not_break_the_health_check(
        self, client: TestClient, fake: FakeEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken() -> int:
            raise RuntimeError("NVML no responde")

        monkeypatch.setattr(fake, "vram_mb", broken)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["vram_mb"] == 0


class TestVoicesEndpoint:
    def test_lists_the_voices_without_ref_text(self, client: TestClient) -> None:
        response = client.get("/voices")

        assert response.status_code == 200
        assert response.json() == [
            {
                "voice_id": "es-f-fake",
                "name": "Voz femenina",
                "gender": "f",
                "source": "doble de pruebas",
                "license": "sin licencia",
            },
            {
                "voice_id": "es-m-fake",
                "name": "Voz masculina",
                "gender": "m",
                "source": "doble de pruebas",
                "license": "sin licencia",
            },
        ]
        assert "SECRETO" not in response.text


class TestSynthesize:
    def test_returns_the_pcm_as_float32_little_endian_with_the_sample_rate(
        self, client: TestClient, fake: FakeEngine
    ) -> None:
        response = client.post("/synthesize", json=synth_body())

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["x-sample-rate"] == "24000"
        assert response.content == fake.expected_pcm()
        assert len(response.content) % 4 == 0
        samples = np.frombuffer(response.content, dtype="<f4")
        assert samples.dtype == np.float32
        assert samples[:2400] == pytest.approx(0.1)
        assert samples[-1] == pytest.approx(0.3)

    def test_the_engine_receives_the_text_stripped_the_voice_and_the_speed(
        self, client: TestClient, fake: FakeEngine
    ) -> None:
        client.post("/synthesize", json=synth_body("  Vale, nos vemos.  \n", "es-m-fake", speed=1.25))

        assert fake.calls == [("Vale, nos vemos.", "es-m-fake", 1.25)]

    def test_speed_is_optional_and_defaults_to_one(self, client: TestClient, fake: FakeEngine) -> None:
        assert client.post("/synthesize", json=synth_body()).status_code == 200

        assert fake.calls[0][2] == 1.0

    @pytest.mark.parametrize("speed", [1.0, 1.25, 1.5])
    def test_accepts_the_speeds_of_the_contract(self, client: TestClient, speed: float) -> None:
        assert client.post("/synthesize", json=synth_body(speed=speed)).status_code == 200

    def test_accepts_a_text_of_exactly_1000_characters(self, client: TestClient, fake: FakeEngine) -> None:
        text = "a" * MAX_TEXT_CHARS

        assert client.post("/synthesize", json=synth_body(text)).status_code == 200

        assert fake.calls[0][0] == text

    def test_chunks_of_any_size_are_sent_whole(self, client: TestClient, fake: FakeEngine) -> None:
        fake.chunk_samples = 1001  # un trozo cuyo tamaño no es múltiplo de nada cómodo
        fake.chunks = 5

        response = client.post("/synthesize", json=synth_body())

        assert response.content == fake.expected_pcm()

    # -- 400 -------------------------------------------------------------------------------------
    def test_an_unknown_voice_is_a_400(self, client: TestClient, fake: FakeEngine) -> None:
        error = assert_error(client.post("/synthesize", json=synth_body(voice_id="no-existe")), 400)

        assert "no-existe" in error
        assert fake.calls == []

    @pytest.mark.parametrize("text", ["", "   ", "\n\t "])
    def test_an_empty_text_is_a_400(self, client: TestClient, fake: FakeEngine, text: str) -> None:
        assert_error(client.post("/synthesize", json=synth_body(text)), 400)

        assert fake.calls == []

    def test_a_text_over_1000_characters_is_a_400(self, client: TestClient, fake: FakeEngine) -> None:
        error = assert_error(client.post("/synthesize", json=synth_body("a" * (MAX_TEXT_CHARS + 1))), 400)

        assert "1000" in error
        assert fake.calls == []

    @pytest.mark.parametrize("speed", [0.99, 0.5, 0, -1.0, 1.51, 2.0, 100.0])
    def test_a_speed_out_of_range_is_a_400(self, client: TestClient, fake: FakeEngine, speed: float) -> None:
        error = assert_error(client.post("/synthesize", json=synth_body(speed=speed)), 400)

        assert "speed" in error
        assert fake.calls == []

    def test_a_speed_that_is_not_a_number_is_a_400(self, client: TestClient) -> None:
        raw = b'{"text": "Hola", "voice_id": "es-f-fake", "speed": NaN}'

        response = client.post("/synthesize", content=raw, headers={"content-type": "application/json"})

        assert_error(response, 400)

    @pytest.mark.parametrize(
        "body",
        [
            {"voice_id": "es-f-fake"},
            {"text": "Hola"},
            {"text": 12, "voice_id": "es-f-fake"},
            {"text": "Hola", "voice_id": None},
            {"text": "Hola", "voice_id": "es-f-fake", "speed": "rápido"},
            [],
            {},
        ],
    )
    def test_a_malformed_body_is_a_400(self, client: TestClient, fake: FakeEngine, body: Any) -> None:
        assert_error(client.post("/synthesize", json=body), 400)

        assert fake.calls == []

    def test_a_body_that_is_not_json_is_a_400(self, client: TestClient) -> None:
        response = client.post(
            "/synthesize", content=b"{esto no es json", headers={"content-type": "application/json"}
        )

        assert "JSON" in assert_error(response, 400)

    # -- 500 -------------------------------------------------------------------------------------
    def test_an_engine_error_before_any_audio_is_a_500(self, client: TestClient, fake: FakeEngine) -> None:
        fake.fail_before_audio = True

        error = assert_error(client.post("/synthesize", json=synth_body()), 500)

        assert "fallo del motor falso" in error

    def test_an_engine_that_produces_no_audio_is_a_500(self, client: TestClient, fake: FakeEngine) -> None:
        fake.silent = True

        assert_error(client.post("/synthesize", json=synth_body()), 500)

    def test_the_service_keeps_working_after_an_engine_error(
        self, client: TestClient, fake: FakeEngine
    ) -> None:
        fake.fail_before_audio = True
        assert_error(client.post("/synthesize", json=synth_body()), 500)
        fake.fail_before_audio = False

        response = client.post("/synthesize", json=synth_body())

        assert response.status_code == 200
        assert response.content == fake.expected_pcm()

    # -- audio no válido ---------------------------------------------------------------------------
    def test_the_audio_is_always_finite_float32_within_full_scale(
        self, client: TestClient, fake: FakeEngine
    ) -> None:
        fake.custom = [
            np.array([np.nan, np.inf, -np.inf, 1.5, -2.0, 0.5], dtype=np.float64),
            np.array([[0.25], [-0.25]], dtype=np.float32),  # con forma (n, 1)
            np.zeros(0, dtype=np.float32),  # un trozo vacío no se envía
        ]

        response = client.post("/synthesize", json=synth_body())

        samples = np.frombuffer(response.content, dtype="<f4")
        assert samples.tolist() == [0.0, 1.0, -1.0, 1.0, -1.0, 0.5, 0.25, -0.25]

    # -- varias peticiones ---------------------------------------------------------------------------
    def test_requests_are_served_one_at_a_time_in_arrival_order(
        self, host: EngineHost, fake: FakeEngine
    ) -> None:
        fake.step_delay_s = 0.05
        results: dict[int, bytes] = {}

        def request(index: int) -> None:
            with TestClient(create_app(host)) as own_client:
                results[index] = own_client.post("/synthesize", json=synth_body(f"Frase {index}")).content

        threads = [threading.Thread(target=request, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(GENEROUS_S)

        assert all(not thread.is_alive() for thread in threads)
        assert fake.max_active == 1
        assert sorted(text for text, _, _ in fake.calls) == [f"Frase {index}" for index in range(4)]
        assert all(content == fake.expected_pcm() for content in results.values()) and len(results) == 4


class TestShutdownEndpoint:
    def test_answers_202_and_asks_the_server_to_stop(
        self, client: TestClient, shutdown_calls: list[bool]
    ) -> None:
        response = client.post("/shutdown")

        assert response.status_code == 202
        assert shutdown_calls == [True]


class TestNotReady:
    def test_everything_answers_503_while_the_model_loads_and_works_afterwards(self) -> None:
        release = threading.Event()
        engine = FakeEngine()

        def slow_factory() -> FakeEngine:
            assert release.wait(GENEROUS_S)
            return engine

        engine_host = EngineHost(slow_factory)
        engine_host.start()
        try:
            with TestClient(create_app(engine_host)) as test_client:
                assert "listo" in assert_error(test_client.get("/health"), 503)
                assert_error(test_client.get("/voices"), 503)
                assert_error(test_client.post("/synthesize", json=synth_body()), 503)
                assert engine.calls == []

                release.set()
                assert engine_host.loaded.wait(GENEROUS_S)

                assert test_client.get("/health").status_code == 200
                assert test_client.post("/synthesize", json=synth_body()).status_code == 200
        finally:
            release.set()
            engine_host.close()

    def test_a_failed_load_keeps_answering_503_with_the_reason(self) -> None:
        def failing_factory() -> FakeEngine:
            raise EngineLoadError("falta el modelo de prueba")

        engine_host = EngineHost(failing_factory)
        engine_host.start()
        try:
            assert engine_host.loaded.wait(GENEROUS_S)
            with TestClient(create_app(engine_host)) as test_client:
                assert "falta el modelo de prueba" in assert_error(test_client.get("/health"), 503)
        finally:
            engine_host.close()

    def test_the_load_runs_in_the_engine_thread_with_stdout_diverted_to_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        threads: list[str] = []

        def noisy_factory() -> FakeEngine:
            threads.append(threading.current_thread().name)
            print("Capturing CUDA graph...")
            return FakeEngine()

        engine_host = EngineHost(noisy_factory)
        engine_host.start()
        try:
            assert engine_host.loaded.wait(GENEROUS_S)
        finally:
            engine_host.close()

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Capturing CUDA graph" in captured.err
        assert threads[0].startswith("tts-engine")


class TestRoutes:
    def test_unknown_routes_and_methods_answer_json_errors(self, client: TestClient) -> None:
        assert_error(client.get("/nada"), 404)
        assert_error(client.get("/synthesize"), 405)
        assert_error(client.post("/health"), 405)
        assert_error(client.get("/shutdown"), 405)

    def test_there_is_no_documentation_endpoint(self, client: TestClient) -> None:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404

    def test_closing_the_host_releases_the_engine_and_refuses_new_work(
        self, host: EngineHost, fake: FakeEngine
    ) -> None:
        host.close()

        assert fake.closed
        assert host.engine is None
        with pytest.raises(RuntimeError):
            host.submit(lambda: None)
        host.close()  # idempotente


# ==================================================================================================
# 3. main() en el mismo proceso, con un puerto real
# ==================================================================================================
class RecordingStream(io.StringIO):
    """Un ``stdout`` o ``stderr`` que se puede leer desde otro hilo."""

    def __init__(self) -> None:
        super().__init__()
        self._guard = threading.Lock()

    def write(self, text: str) -> int:
        with self._guard:
            return super().write(text)

    def lines(self) -> list[str]:
        with self._guard:
            return self.getvalue().splitlines()

    def text(self) -> str:
        with self._guard:
            return self.getvalue()


class RunningService:
    """``main()`` corriendo en un hilo, con su ``stdout`` y su ``stderr`` grabados."""

    def __init__(
        self, thread: threading.Thread, outcome: list[int], stdout: RecordingStream, stderr: RecordingStream
    ):
        self.thread = thread
        self.outcome = outcome
        self.stdout = stdout
        self.stderr = stderr
        self._info: dict[str, Any] | None = None

    def ready(self, timeout_s: float = GENEROUS_S) -> dict[str, Any]:
        """La línea ``ready`` ya parseada; falla si el servicio muere antes de escribirla."""
        deadline = time.monotonic() + timeout_s
        while self._info is None:
            line = next((line for line in self.stdout.lines() if line.startswith("{")), None)
            if line is not None:
                self._info = json.loads(line)
            elif not self.thread.is_alive():
                pytest.fail(
                    f"El servicio terminó sin «ready» (código {self.outcome}). stderr:\n{self.stderr.text()}"
                )
            elif time.monotonic() > deadline:
                pytest.fail(f"No llegó «ready» en {timeout_s:g} s. stderr:\n{self.stderr.text()}")
            else:
                time.sleep(0.01)
        return self._info

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.ready()['port']}"

    def stop(self) -> None:
        if self.thread.is_alive() and self._info is not None:
            with contextlib.suppress(httpx.HTTPError):
                httpx.post(f"{self.base_url}/shutdown", timeout=2.0, trust_env=False)
        self.thread.join(5.0)


@pytest.fixture
def run_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., RunningService]]:
    services: list[RunningService] = []

    def start(engine: Any, *extra_args: str) -> RunningService:
        stdout, stderr = RecordingStream(), RecordingStream()
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(sys, "stderr", stderr)
        argv = [
            "--port",
            "0",
            "--voices-dir",
            str(tmp_path / "voices"),
            "--models-dir",
            str(tmp_path / "models"),
            *extra_args,
        ]
        factory = engine if isinstance(engine, types.FunctionType) else (lambda _config: engine)
        outcome: list[int] = []
        thread = threading.Thread(
            target=lambda: outcome.append(main(argv, engine_factory=factory)),
            name="test-service",
            daemon=True,
        )
        service = RunningService(thread, outcome, stdout, stderr)
        services.append(service)
        thread.start()
        return service

    yield start
    for service in services:
        service.stop()


@pytest.fixture
def http() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=10.0, trust_env=False) as client:
        yield client


class TestServiceInProcess:
    def test_ready_is_one_json_line_with_the_contract_fields(
        self, run_service: Callable[..., RunningService]
    ) -> None:
        service = run_service(FakeEngine())

        info = service.ready()

        assert set(info) == {"event", "port", "sample_rate", "engine", "supports_speed"}
        assert info["event"] == "ready"
        assert isinstance(info["port"], int) and info["port"] > 0
        assert info["sample_rate"] == 24_000
        assert info["engine"] == "fake-tts"
        assert info["supports_speed"] is False
        assert [line for line in service.stdout.lines() if line.strip()] == [json.dumps(info)]

    def test_ready_is_written_only_when_the_engine_is_loaded_and_stdout_stays_clean(
        self, run_service: Callable[..., RunningService]
    ) -> None:
        release = threading.Event()

        def factory(_config: ServiceConfig) -> FakeEngine:
            print("ruido de las bibliotecas al cargar")
            assert release.wait(GENEROUS_S)
            return FakeEngine()

        service = run_service(factory)
        try:
            time.sleep(0.5)
            assert service.stdout.lines() == []
            assert "ruido de las bibliotecas" in service.stderr.text()
        finally:
            release.set()

        service.ready()
        assert len([line for line in service.stdout.lines() if line.strip()]) == 1

    def test_the_server_already_answers_when_ready_is_written(
        self, run_service: Callable[..., RunningService], http: httpx.Client
    ) -> None:
        service = run_service(FakeEngine())

        assert http.get(f"{service.base_url}/health").status_code == 200

    def test_port_zero_picks_a_free_port_and_it_listens_only_on_the_loopback(
        self, run_service: Callable[..., RunningService]
    ) -> None:
        service = run_service(FakeEngine())
        port = service.ready()["port"]

        socket.create_connection(("127.0.0.1", port), timeout=2.0).close()
        try:
            infos = socket.getaddrinfo(socket.gethostname(), port, socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            infos = []
        others = [str(info[4][0]) for info in infos if not str(info[4][0]).startswith("127.")]
        if not others:
            pytest.skip("este equipo no tiene otra dirección IPv4 con la que probar")
        for address in others:
            with pytest.raises(OSError):
                socket.create_connection((address, port), timeout=2.0).close()

    def test_two_services_get_different_ports(self, run_service: Callable[..., RunningService]) -> None:
        # Uno detrás de otro: ``sys.stdout`` es único y cada servicio graba el suyo al arrancar.
        first_port = run_service(FakeEngine()).ready()["port"]
        second_port = run_service(FakeEngine()).ready()["port"]

        assert first_port != second_port

    def test_a_host_other_than_the_loopback_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        argv = ["--host", "0.0.0.0", "--voices-dir", str(tmp_path), "--models-dir", str(tmp_path)]

        with pytest.raises(SystemExit) as exit_:
            main(argv, engine_factory=lambda _config: FakeEngine())

        assert exit_.value.code == 2
        assert "127.0.0.1" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "bad",
        [
            ["--port", "70000"],
            ["--port", "-1"],
            ["--chunk-size", "0"],
            ["--chunk-size", "13"],
            ["--port", "x"],
        ],
    )
    def test_invalid_options_are_refused_with_exit_code_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], bad: list[str]
    ) -> None:
        argv = ["--voices-dir", str(tmp_path), "--models-dir", str(tmp_path), *bad]

        with pytest.raises(SystemExit) as exit_:
            main(argv, engine_factory=lambda _config: FakeEngine())

        assert exit_.value.code == 2
        assert capsys.readouterr().err

    def test_the_voices_and_models_dirs_are_required(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exit_:
            main([], engine_factory=lambda _config: FakeEngine())

        assert exit_.value.code == 2
        assert "--voices-dir" in capsys.readouterr().err

    def test_the_engine_factory_receives_the_command_line_options(
        self, run_service: Callable[..., RunningService], tmp_path: Path
    ) -> None:
        received: list[ServiceConfig] = []

        def factory(config: ServiceConfig) -> FakeEngine:
            received.append(config)
            return FakeEngine()

        run_service(factory, "--chunk-size", "8", "--x-vector-only").ready()

        (config,) = received
        assert config.voices_dir == tmp_path / "voices"
        assert config.models_dir == tmp_path / "models"
        assert config.chunk_size == 8
        assert config.x_vector_only is True

    def test_defaults_are_chunk_size_4_and_icl(self, run_service: Callable[..., RunningService]) -> None:
        received: list[ServiceConfig] = []

        def factory(config: ServiceConfig) -> FakeEngine:
            received.append(config)
            return FakeEngine()

        run_service(factory).ready()

        assert (received[0].chunk_size, received[0].x_vector_only) == (4, False)

    def test_shutdown_stops_the_service_with_code_0_in_two_seconds(
        self, run_service: Callable[..., RunningService], http: httpx.Client
    ) -> None:
        fake = FakeEngine()
        service = run_service(fake)

        response = http.post(f"{service.base_url}/shutdown")
        started = time.monotonic()
        service.thread.join(GENEROUS_S)

        assert response.status_code == 202
        assert not service.thread.is_alive()
        assert time.monotonic() - started <= 2.0
        assert service.outcome == [0]
        assert fake.closed
        with pytest.raises(httpx.TransportError):
            http.get(f"{service.base_url}/health")

    def test_the_audio_streams_as_soon_as_it_is_generated(
        self, run_service: Callable[..., RunningService], http: httpx.Client
    ) -> None:
        fake = FakeEngine()
        fake.gate = threading.Event()  # el motor no da el segundo trozo hasta que se abra
        service = run_service(fake)
        received = bytearray()
        first_chunk_bytes = len(fake.chunk(0).tobytes())

        try:
            with http.stream("POST", f"{service.base_url}/synthesize", json=synth_body()) as response:
                assert response.status_code == 200
                assert response.headers["transfer-encoding"] == "chunked"
                assert response.headers["x-sample-rate"] == "24000"
                stream = response.iter_raw()
                while len(received) < first_chunk_bytes:
                    received.extend(next(stream))
                # El primer trozo ya está aquí y el motor sigue bloqueado: no se esperó al final.
                assert bytes(received) == fake.expected_pcm(1)
                assert fake.produced == 1
                fake.gate.set()
                received.extend(b"".join(stream))
        finally:
            fake.gate.set()

        assert bytes(received) == fake.expected_pcm()

    def test_an_engine_failure_after_the_first_chunk_cuts_the_connection_and_the_service_survives(
        self, run_service: Callable[..., RunningService], http: httpx.Client
    ) -> None:
        fake = FakeEngine()
        fake.fail_after_chunks = 1
        service = run_service(fake)

        # Respuesta incompleta: el cuerpo chunked no termina bien.
        with (
            pytest.raises(httpx.TransportError),
            http.stream("POST", f"{service.base_url}/synthesize", json=synth_body()) as response,
        ):
            assert response.status_code == 200
            b"".join(response.iter_raw())

        fake.fail_after_chunks = None
        again = http.post(f"{service.base_url}/synthesize", json=synth_body())
        assert again.status_code == 200
        assert again.content == fake.expected_pcm()

    def test_a_client_that_disconnects_stops_the_synthesis_and_does_not_block_the_next_request(
        self, run_service: Callable[..., RunningService], http: httpx.Client
    ) -> None:
        fake = FakeEngine(chunks=6)
        fake.gate = threading.Event()
        service = run_service(fake)

        with http.stream("POST", f"{service.base_url}/synthesize", json=synth_body()) as response:
            stream = response.iter_raw()
            next(stream)  # el primer trozo y nos vamos
        time.sleep(0.5)  # lo que tarda el servidor en enterarse de que el cliente se fue
        fake.gate.set()

        assert fake.generator_closed.wait(GENEROUS_S)
        assert fake.produced < fake.chunks  # no siguió generando para nadie
        fake.gate = None
        again = http.post(f"{service.base_url}/synthesize", json=synth_body())
        assert again.status_code == 200
        assert again.content == fake.expected_pcm()

    def test_concurrent_requests_never_run_the_engine_at_the_same_time(
        self, run_service: Callable[..., RunningService]
    ) -> None:
        fake = FakeEngine(step_delay_s=0.05)
        service = run_service(fake)
        base_url = service.base_url
        bodies: queue.Queue[bytes] = queue.Queue()

        def request() -> None:
            with httpx.Client(timeout=GENEROUS_S, trust_env=False) as own:
                bodies.put(own.post(f"{base_url}/synthesize", json=synth_body()).content)

        threads = [threading.Thread(target=request) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(GENEROUS_S)

        assert bodies.qsize() == 4
        assert fake.max_active == 1

    def test_a_failing_engine_load_reports_on_stderr_and_exits_non_zero(
        self, run_service: Callable[..., RunningService]
    ) -> None:
        def factory(_config: ServiceConfig) -> FakeEngine:
            raise EngineLoadError("falta el modelo de prueba")

        service = run_service(factory)
        service.thread.join(GENEROUS_S)

        assert not service.thread.is_alive()
        assert service.outcome == [1]
        assert "error de arranque" in service.stderr.text()
        assert "falta el modelo de prueba" in service.stderr.text()
        assert service.stdout.lines() == []  # sin «ready»

    def test_an_unexpected_load_error_also_prints_its_traceback(
        self, run_service: Callable[..., RunningService]
    ) -> None:
        def factory(_config: ServiceConfig) -> FakeEngine:
            raise ZeroDivisionError("división inesperada")

        service = run_service(factory)
        service.thread.join(GENEROUS_S)

        assert service.outcome == [1]
        assert "Traceback" in service.stderr.text()
        assert "ZeroDivisionError" in service.stderr.text()

    def test_a_port_that_is_already_taken_fails_with_a_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            argv = ["--port", str(port), "--voices-dir", str(tmp_path), "--models-dir", str(tmp_path)]

            code = main(argv, engine_factory=lambda _config: FakeEngine())

        assert code == 1
        assert "error de arranque" in capsys.readouterr().err


# ==================================================================================================
# 4. El servicio como proceso aparte
# ==================================================================================================
FAKE_SERVICE_SCRIPT = r'''
"""Lanza el servicio con un motor falso: lo mismo que ``tts-service``, pero sin GPU ni modelo."""
import sys
import time
from pathlib import Path

import numpy as np

from tts_service.engine import Voice
from tts_service.server import main


class Engine:
    name = "fake-tts"
    model_name = "fake"
    sample_rate = 24000
    supports_speed = False

    def voices(self):
        return (Voice("es-f-fake", "Voz", "f", "origen", "licencia", Path("x.wav"), "texto"),)

    def synthesize(self, text, voice_id, speed):
        for index in range(3):
            time.sleep(0.02)
            yield np.full(2400, 0.1 * (index + 1), dtype=np.float32)

    def vram_mb(self):
        return 7

    def close(self):
        pass


def factory(config):
    print("Capturing CUDA graph... (ruido de la biblioteca de CUDA)")
    return Engine()


raise SystemExit(main(sys.argv[1:], engine_factory=factory))
'''


class TestServiceAsAProcess:
    def start(self, tmp_path: Path) -> tuple[subprocess.Popen[str], queue.Queue[str], list[str]]:
        script = tmp_path / "fake_service.py"
        script.write_text(FAKE_SERVICE_SCRIPT, encoding="utf-8")
        process = subprocess.Popen(
            [
                sys.executable,
                str(script),
                "--port",
                "0",
                "--voices-dir",
                str(tmp_path / "voices"),
                "--models-dir",
                str(tmp_path / "models"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        stdout_lines: queue.Queue[str] = queue.Queue()
        stderr_lines: list[str] = []
        assert process.stdout is not None and process.stderr is not None
        threading.Thread(
            target=lambda out=process.stdout: [stdout_lines.put(x) for x in out], daemon=True
        ).start()
        threading.Thread(
            target=lambda err=process.stderr: [stderr_lines.append(x) for x in err], daemon=True
        ).start()
        return process, stdout_lines, stderr_lines

    def test_ready_comes_through_the_pipe_as_the_only_line_and_shutdown_exits_quickly(
        self, tmp_path: Path
    ) -> None:
        process, stdout_lines, stderr_lines = self.start(tmp_path)
        try:
            info = json.loads(stdout_lines.get(timeout=60))
            base_url = f"http://127.0.0.1:{info['port']}"
            with httpx.Client(timeout=10.0, trust_env=False) as client:
                health = client.get(f"{base_url}/health").json()
                with client.stream("POST", f"{base_url}/synthesize", json=synth_body()) as response:
                    pcm = b"".join(response.iter_raw())
                started = time.monotonic()
                shutdown = client.post(f"{base_url}/shutdown")
            code = process.wait(timeout=10)
            elapsed = time.monotonic() - started
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)

        assert info == {
            "event": "ready",
            "port": info["port"],
            "sample_rate": 24000,
            "engine": "fake-tts",
            "supports_speed": False,
        }
        assert health["status"] == "ok" and health["model"] == "fake"
        assert len(pcm) == 3 * 2400 * 4
        assert shutdown.status_code == 202
        assert code == 0
        assert elapsed <= 2.0
        assert stdout_lines.empty()  # solo hubo una línea en stdout: el ruido de CUDA fue a stderr
        wait_until(
            lambda: any("ruido de la biblioteca" in line for line in stderr_lines), 5.0, "el ruido en stderr"
        )

    def test_the_real_entry_point_fails_fast_when_there_are_no_voices(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tts_service",
                "--port",
                "0",
                "--voices-dir",
                str(tmp_path / "voces"),
                "--models-dir",
                str(tmp_path / "models"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )

        assert result.returncode == 1
        assert "error de arranque" in result.stderr
        assert "voces" in result.stderr
        assert result.stdout.strip() == ""

    def test_the_real_entry_point_asks_to_run_preparar_when_the_model_is_missing(
        self, tmp_path: Path
    ) -> None:
        write_voice(tmp_path / "voces", "es-f-uno")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tts_service",
                "--port",
                "0",
                "--voices-dir",
                str(tmp_path / "voces"),
                "--models-dir",
                str(tmp_path / "models"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )

        assert result.returncode == 1
        assert "preparar" in result.stderr and MODEL_DIR_NAME in result.stderr
        assert result.stdout.strip() == ""

    def test_the_real_entry_point_rejects_a_non_loopback_host(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tts_service",
                "--host",
                "0.0.0.0",
                "--voices-dir",
                str(tmp_path),
                "--models-dir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )

        assert result.returncode == 2
        assert "127.0.0.1" in result.stderr
