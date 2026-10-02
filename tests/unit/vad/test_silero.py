"""Tests de `SileroVad` (T018) sin modelo: la probabilidad de habla se inyecta.

- `ScriptedModel` y `EnergyModel` hacen de modelo de Silero: devuelven la probabilidad de cada trama de
  512 muestras. Así se prueba la lógica de disparo (umbrales, silencio mínimo, relleno y tiempos).
- `SileroOnnx` se prueba con un `InferenceSession` falso: entradas, estado recurrente y contexto.
- `VadContract` (la suite de contrato) se concreta aquí con el modelo por energía; con el modelo real la
  concreta `tests/integration/test_silero_model.py` (marcador `model`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from instanttraductor.contracts import CAPTURE_RATE, AudioChunk, EngineError, Vad, VadEvent, VadEventKind
from instanttraductor.setup.manifest import component_dir
from instanttraductor.vad.silero import (
    CONTEXT_SAMPLES,
    FRAME_S,
    FRAME_SAMPLES,
    SileroOnnx,
    SileroVad,
    default_model_path,
)
from tests.contract.helpers import to_chunks
from tests.contract.test_speech_contract import VadContract
from tests.fakes.fake_speech import rms

Samples = npt.NDArray[np.float32]

START = VadEventKind.SPEECH_START
END = VadEventKind.SPEECH_END


class ScriptedModel:
    """Modelo falso: la trama número `i` tiene la probabilidad `script[i]` (`default` si se acaba el guion).

    El guion corre con las tramas, no con los reinicios: `reset()` solo se cuenta.
    """

    def __init__(self, script: Sequence[float], *, default: float = 0.0) -> None:
        self._script = list(script)
        self._default = default
        self._index = 0
        self.frames: list[Samples] = []
        self.resets = 0

    def prob(self, frame: Samples) -> float:
        self.frames.append(frame.copy())
        p = self._script[self._index] if self._index < len(self._script) else self._default
        self._index += 1
        return p

    def reset(self) -> None:
        self.resets += 1


class EnergyModel:
    """Modelo falso por energía: una trama con RMS ≥ 0,01 es habla (0,9) y el resto, silencio (0,0)."""

    def prob(self, frame: Samples) -> float:
        return 0.9 if rms(frame) >= 0.01 else 0.0

    def reset(self) -> None:
        pass


def frame_chunks(n_frames: int, *, t0: float = 0.0) -> list[AudioChunk]:
    """`n_frames` chunks de exactamente una trama (512 muestras): cada `accept` procesa una trama."""
    return [
        AudioChunk(
            samples=np.zeros(FRAME_SAMPLES, dtype=np.float32),
            sample_rate=CAPTURE_RATE,
            t_start=t0 + i * FRAME_S,
        )
        for i in range(n_frames)
    ]


def run_frames(vad: SileroVad, n_frames: int, *, t0: float = 0.0) -> list[tuple[int, VadEvent]]:
    """Entrega `n_frames` tramas de una en una y devuelve (índice de la trama que lo provoca, evento)."""
    found: list[tuple[int, VadEvent]] = []
    for index, chunk in enumerate(frame_chunks(n_frames, t0=t0)):
        found.extend((index, event) for event in vad.accept(chunk))
    return found


def burst(speech_frames: int, silence_frames: int = 0) -> list[float]:
    """Guion de probabilidades: `speech_frames` tramas de habla seguidas de `silence_frames` de silencio."""
    return [0.9] * speech_frames + [0.0] * silence_frames


# --------------------------------------------------------------------------------------------------
# Suite de contrato con el modelo por energía
# --------------------------------------------------------------------------------------------------


class TestSileroVadContract(VadContract):
    """Con el modelo por energía, la lógica de disparo cumple la suite de contrato con audio sintético."""

    @pytest.fixture
    def make_impl(self) -> Callable[[], Vad]:
        return lambda: SileroVad(EnergyModel())


# --------------------------------------------------------------------------------------------------
# Lógica de disparo
# --------------------------------------------------------------------------------------------------


class TestTrigger:
    def test_no_events_while_the_probability_stays_low(self) -> None:
        vad = SileroVad(ScriptedModel([0.0] * 50))
        assert run_frames(vad, 50) == []
        assert vad.in_speech is False

    def test_speech_start_is_reported_one_pad_before_the_first_speech_frame(self) -> None:
        vad = SileroVad(ScriptedModel([0.0] * 10 + burst(5, 40)))
        found = run_frames(vad, 55)
        (index, start), _end = found
        assert index == 10, "el inicio se decide en la trama que cruza el umbral"
        assert start.kind is START
        # La trama 10 empieza en 10 · 32 ms = 0,32 s; el relleno de 150 ms lo adelanta.
        assert start.t == pytest.approx(0.32 - 0.15)

    def test_speech_start_never_goes_before_the_first_audio_received(self) -> None:
        vad = SileroVad(ScriptedModel(burst(5, 40)))
        (_, start), _end = run_frames(vad, 45, t0=5.0)
        assert start.t == 5.0

    def test_speech_pad_is_configurable(self) -> None:
        vad = SileroVad(ScriptedModel([0.0] * 20 + burst(5, 40)), speech_pad_ms=0.0)
        (_, start), _end = run_frames(vad, 65)
        assert start.t == pytest.approx(20 * FRAME_S)

    def test_speech_end_waits_for_min_silence_and_reports_the_last_speech_frame(self) -> None:
        vad = SileroVad(ScriptedModel(burst(10, 40)))
        (_, _start), (index, end) = run_frames(vad, 50)
        assert end.kind is END
        # Habla en las tramas 0-9 (hasta 0,32 s). El silencio empieza en la 10 y hace falta que el audio
        # sin voz llegue a 500 ms: la trama 25 termina en 26 · 32 − 10 · 32 = 512 ms; la 24, en 480 ms.
        assert index == 25
        assert end.t == pytest.approx(10 * FRAME_S), "SPEECH_END es el final real del habla, sin relleno"
        assert vad.in_speech is False

    def test_min_silence_is_configurable(self) -> None:
        vad = SileroVad(ScriptedModel(burst(10, 40)), min_silence_ms=200.0)
        (_, _start), (index, _end) = run_frames(vad, 50)
        assert index == 10 + 7 - 1, "200 ms son 7 tramas de silencio: 7 · 32 = 224 ms"

    def test_a_pause_shorter_than_min_silence_keeps_the_utterance_open(self) -> None:
        vad = SileroVad(ScriptedModel(burst(10, 10) + burst(10, 40)))
        found = run_frames(vad, 70)
        assert [event.kind for _, event in found] == [START, END], (
            "una sola intervención, sin cortar en 320 ms"
        )
        assert found[1][1].t == pytest.approx(30 * FRAME_S)

    def test_a_pause_of_min_silence_or_more_splits_the_speech(self) -> None:
        vad = SileroVad(ScriptedModel(burst(10, 20) + burst(10, 40)))
        found = run_frames(vad, 80)
        assert [event.kind for _, event in found] == [START, END, START, END]
        times = [event.t for _, event in found]
        assert times == sorted(times)

    def test_threshold_is_inclusive_and_the_exit_threshold_is_exclusive(self) -> None:
        # p = 0,30 ya es habla; p = 0,15 todavía no cuenta como silencio.
        vad = SileroVad(ScriptedModel([0.30] * 3 + [0.15] * 60))
        found = run_frames(vad, 63)
        assert [event.kind for _, event in found] == [START]
        assert vad.in_speech is True

    def test_probabilities_between_the_thresholds_do_not_open_the_speech(self) -> None:
        vad = SileroVad(ScriptedModel([0.2] * 20))
        assert run_frames(vad, 20) == []
        assert vad.in_speech is False

    def test_probabilities_between_the_thresholds_do_not_close_the_speech(self) -> None:
        vad = SileroVad(ScriptedModel(burst(3) + [0.2] * 60))
        found = run_frames(vad, 63)
        assert [event.kind for _, event in found] == [START]
        assert vad.in_speech is True

    def test_only_a_speech_frame_resets_the_silence_timer(self) -> None:
        """Como el `VADIterator` oficial: las tramas intermedias (0,15-0,30) no reinician el silencio."""
        vad = SileroVad(ScriptedModel(burst(5, 5) + [0.2] * 5 + [0.0] * 10))
        found = run_frames(vad, 25)
        # El silencio empieza en la trama 5 (0,16 s). Con las tramas 10-14 intermedias, sigue corriendo
        # y llega a 500 ms en la 20, que sí es silencio.
        (_, _start), (index, end) = found
        assert index == 20
        assert end.t == pytest.approx(5 * FRAME_S)

    def test_a_speech_frame_in_the_middle_of_the_silence_restarts_the_timer(self) -> None:
        vad = SileroVad(ScriptedModel(burst(5, 14) + burst(1, 40)))
        found = run_frames(vad, 60)
        assert [event.kind for _, event in found] == [START, END]
        assert found[1][1].t == pytest.approx(20 * FRAME_S), "el final es el de la última trama con voz"

    def test_a_single_loud_frame_makes_a_start_and_an_end(self) -> None:
        vad = SileroVad(ScriptedModel(burst(1, 40)))
        assert [event.kind for _, event in run_frames(vad, 41)] == [START, END]


# --------------------------------------------------------------------------------------------------
# Audio de cualquier tamaño, tiempos y reinicio
# --------------------------------------------------------------------------------------------------


class TestStreaming:
    SCRIPT = burst(12, 20) + burst(6, 30) + [0.0] * 10

    @pytest.mark.parametrize("chunk_samples", [1, 160, 320, 511, 512, 700, 1024, 5000])
    def test_events_do_not_depend_on_the_chunk_size(self, chunk_samples: int) -> None:
        total = len(self.SCRIPT) * FRAME_SAMPLES
        audio = np.zeros(total, dtype=np.float32)

        def events_with(size: int) -> list[VadEvent]:
            vad = SileroVad(ScriptedModel(self.SCRIPT))
            found: list[VadEvent] = []
            for chunk in to_chunks(audio, chunk_s=size / CAPTURE_RATE):
                found.extend(vad.accept(chunk))
            return found

        expected = events_with(FRAME_SAMPLES)
        assert [e.kind for e in expected] == [START, END, START, END]
        assert events_with(chunk_samples) == expected

    def test_the_model_receives_whole_frames_of_the_original_audio(self) -> None:
        rng = np.random.default_rng(7)
        audio = rng.uniform(-0.5, 0.5, 20 * FRAME_SAMPLES + 123).astype(np.float32)
        model = ScriptedModel([])
        vad = SileroVad(model)
        for chunk in to_chunks(audio, chunk_s=333 / CAPTURE_RATE):
            vad.accept(chunk)
        assert len(model.frames) == 20, "las 123 muestras de más esperan a completar una trama"
        assert all(f.shape == (FRAME_SAMPLES,) and f.dtype == np.float32 for f in model.frames)
        np.testing.assert_array_equal(np.concatenate(model.frames), audio[: 20 * FRAME_SAMPLES])

    def test_event_times_follow_the_chunk_timestamps(self) -> None:
        vad = SileroVad(ScriptedModel([0.0] * 30 + burst(10, 40)))
        found = run_frames(vad, 80, t0=100.0)
        (_, start), (_, end) = found
        assert start.t == pytest.approx(100.0 + 30 * FRAME_S - 0.15)
        assert end.t == pytest.approx(100.0 + 40 * FRAME_S)

    def test_a_chunk_that_is_not_a_whole_number_of_frames_keeps_the_remainder(self) -> None:
        vad = SileroVad(ScriptedModel(burst(10, 40)))
        chunk = AudioChunk(np.zeros(FRAME_SAMPLES * 10 + 100, dtype=np.float32), CAPTURE_RATE, 0.0)
        (start,) = vad.accept(chunk)  # diez tramas completas y 100 muestras que esperan
        assert start.kind is START
        rest = AudioChunk(np.zeros(FRAME_SAMPLES * 40 - 100, dtype=np.float32), CAPTURE_RATE, chunk.t_end)
        (end,) = vad.accept(rest)  # las 100 muestras guardadas completan la trama 10
        assert end.kind is END

    def test_empty_chunks_are_ignored(self) -> None:
        vad = SileroVad(ScriptedModel([]))
        assert vad.accept(AudioChunk(np.zeros(0, dtype=np.float32), CAPTURE_RATE, 0.0)) == []

    def test_a_chunk_that_is_not_16_khz_is_rejected(self) -> None:
        vad = SileroVad(ScriptedModel([]))
        with pytest.raises(ValueError, match="16000"):
            vad.accept(AudioChunk(np.zeros(480, dtype=np.float32), 48_000, 0.0))


class TestReset:
    def test_reset_leaves_the_vad_out_of_speech_without_a_stale_end(self) -> None:
        vad = SileroVad(ScriptedModel(burst(5, 100)))  # tras 5 tramas de habla, solo silencio
        assert [event.kind for _, event in run_frames(vad, 5)] == [START]
        assert vad.in_speech is True
        vad.reset()
        assert vad.in_speech is False
        # Sin el reinicio, 500 ms de silencio cerrarían el habla anterior con un SPEECH_END huérfano.
        assert run_frames(vad, 60, t0=1.0) == []

    def test_reset_resets_the_model_state(self) -> None:
        model = ScriptedModel([])
        vad = SileroVad(model)
        resets = model.resets
        vad.reset()
        assert model.resets == resets + 1

    def test_reset_discards_the_partial_frame(self) -> None:
        model = ScriptedModel([])
        vad = SileroVad(model)
        vad.accept(AudioChunk(np.zeros(300, dtype=np.float32), CAPTURE_RATE, 0.0))
        vad.reset()
        vad.accept(AudioChunk(np.zeros(300, dtype=np.float32), CAPTURE_RATE, 9.0))
        assert model.frames == [], (
            "300 + 300 muestras habrían dado una trama si no se hubiera descartado el resto"
        )

    def test_after_a_reset_the_clock_follows_the_next_chunk(self) -> None:
        vad = SileroVad(ScriptedModel(burst(5, 40) * 2))
        run_frames(vad, 45, t0=0.0)
        vad.reset()
        (_, start), _end = run_frames(vad, 45, t0=50.0)
        assert start.t == 50.0, (
            "tras `reset()` el relleno no puede llevar el inicio antes del primer chunk nuevo"
        )


# --------------------------------------------------------------------------------------------------
# Parámetros
# --------------------------------------------------------------------------------------------------


class TestParameters:
    def test_defaults_are_the_ones_of_the_002_research_r7(self) -> None:
        vad = SileroVad(ScriptedModel([]))
        assert vad.threshold == 0.30
        assert vad.neg_threshold == 0.15
        assert vad.min_silence_ms == 500.0
        assert vad.speech_pad_ms == 150.0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"threshold": 0.0},
            {"threshold": 1.5},
            {"neg_threshold": 0.0},
            {"neg_threshold": 0.6},
            {"min_silence_ms": -1.0},
            {"speech_pad_ms": -1.0},
        ],
    )
    def test_invalid_parameters_are_rejected(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValueError):
            SileroVad(ScriptedModel([]), **kwargs)


# --------------------------------------------------------------------------------------------------
# SileroOnnx con un InferenceSession falso
# --------------------------------------------------------------------------------------------------


class FakeSession:
    """`onnxruntime.InferenceSession` falso: registra las llamadas y devuelve una probabilidad y un estado."""

    instances: list[FakeSession] = []

    def __init__(self, path: str, sess_options: Any = None, providers: Sequence[str] | None = None) -> None:
        self.path = path
        self.options = sess_options
        self.providers = list(providers or [])
        self.calls: list[dict[str, np.ndarray]] = []
        self.probability = 0.75
        self.fail_with: Exception | None = None
        FakeSession.instances.append(self)

    def run(self, output_names: Any, input_feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        if self.fail_with is not None:
            raise self.fail_with
        # ONNX Runtime devuelve arrays nuevos; los de entrada se copian porque el modelo no los muta.
        self.calls.append({name: np.array(value, copy=True) for name, value in input_feed.items()})
        state = np.full((2, 1, 128), len(self.calls), dtype=np.float32)
        return [np.array([[self.probability]], dtype=np.float32), state]


@pytest.fixture
def fake_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Callable[[], tuple[SileroOnnx, FakeSession]]:
    import onnxruntime as ort

    FakeSession.instances = []
    monkeypatch.setattr(ort, "InferenceSession", FakeSession)
    model_file = tmp_path / "silero_vad.onnx"
    model_file.write_bytes(b"no es un modelo de verdad")

    def build() -> tuple[SileroOnnx, FakeSession]:
        model = SileroOnnx(model_file)
        return model, FakeSession.instances[-1]

    return build


class TestSileroOnnx:
    def test_the_session_runs_on_the_cpu_with_one_thread(
        self, fake_session: Callable[[], tuple[SileroOnnx, FakeSession]]
    ) -> None:
        _model, session = fake_session()
        assert session.providers == ["CPUExecutionProvider"]
        assert session.options.intra_op_num_threads == 1
        assert session.options.inter_op_num_threads == 1
        assert session.path.endswith("silero_vad.onnx")

    def test_prob_feeds_the_input_state_and_sample_rate_the_model_expects(
        self, fake_session: Callable[[], tuple[SileroOnnx, FakeSession]]
    ) -> None:
        model, session = fake_session()
        frame = np.linspace(-0.5, 0.5, FRAME_SAMPLES, dtype=np.float32)
        assert model.prob(frame) == pytest.approx(0.75)
        (call,) = session.calls
        assert call["input"].shape == (1, CONTEXT_SAMPLES + FRAME_SAMPLES)
        assert call["input"].dtype == np.float32
        np.testing.assert_array_equal(call["input"][0, :CONTEXT_SAMPLES], np.zeros(CONTEXT_SAMPLES))
        np.testing.assert_array_equal(call["input"][0, CONTEXT_SAMPLES:], frame)
        assert call["state"].shape == (2, 1, 128)
        assert call["state"].dtype == np.float32
        assert call["sr"].dtype == np.int64
        assert int(call["sr"]) == 16_000

    def test_the_context_and_the_recurrent_state_carry_over_between_frames(
        self, fake_session: Callable[[], tuple[SileroOnnx, FakeSession]]
    ) -> None:
        model, session = fake_session()
        first = np.arange(FRAME_SAMPLES, dtype=np.float32) / FRAME_SAMPLES
        second = first[::-1].copy()
        model.prob(first)
        model.prob(second)
        call1, call2 = session.calls
        np.testing.assert_array_equal(call2["input"][0, :CONTEXT_SAMPLES], first[-CONTEXT_SAMPLES:])
        np.testing.assert_array_equal(call2["state"], np.full((2, 1, 128), 1.0, dtype=np.float32))
        assert not call1["state"].any()

    def test_reset_clears_the_context_and_the_state(
        self, fake_session: Callable[[], tuple[SileroOnnx, FakeSession]]
    ) -> None:
        model, session = fake_session()
        model.prob(np.ones(FRAME_SAMPLES, dtype=np.float32))
        model.reset()
        model.prob(np.ones(FRAME_SAMPLES, dtype=np.float32))
        after_reset = session.calls[-1]
        assert not after_reset["state"].any()
        assert not after_reset["input"][0, :CONTEXT_SAMPLES].any()

    def test_a_vad_built_on_the_onnx_model_detects_speech(
        self, fake_session: Callable[[], tuple[SileroOnnx, FakeSession]]
    ) -> None:
        model, session = fake_session()
        session.probability = 0.9
        vad = SileroVad(model)
        (event,) = vad.accept(frame_chunks(1)[0])
        assert event.kind is START

    def test_a_missing_model_file_is_a_non_recoverable_engine_error(self, tmp_path: Path) -> None:
        with pytest.raises(EngineError) as info:
            SileroOnnx(tmp_path / "no_existe.onnx")
        assert info.value.recoverable is False
        assert info.value.engine == "silero-vad"
        assert "no_existe.onnx" in str(info.value)

    def test_a_model_that_onnx_runtime_cannot_load_is_a_non_recoverable_engine_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import onnxruntime as ort

        def broken(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("protobuf corrupto")

        monkeypatch.setattr(ort, "InferenceSession", broken)
        model_file = tmp_path / "silero_vad.onnx"
        model_file.write_bytes(b"x")
        with pytest.raises(EngineError, match="protobuf corrupto") as info:
            SileroOnnx(model_file)
        assert info.value.recoverable is False

    def test_a_failure_while_running_is_a_recoverable_engine_error(
        self, fake_session: Callable[[], tuple[SileroOnnx, FakeSession]]
    ) -> None:
        model, session = fake_session()
        session.fail_with = RuntimeError("fallo de ORT")
        with pytest.raises(EngineError, match="fallo de ORT") as info:
            model.prob(np.zeros(FRAME_SAMPLES, dtype=np.float32))
        assert info.value.recoverable is True
        assert info.value.engine == "silero-vad"


class TestDefaultModel:
    def test_the_default_model_is_the_onnx_of_the_silero_component(self) -> None:
        assert default_model_path() == component_dir("silero-vad") / "silero_vad.onnx"

    def test_without_the_component_installed_it_asks_to_run_prepare(self) -> None:
        # La carpeta de datos de los tests es temporal y está vacía: no hay modelo.
        with pytest.raises(EngineError) as info:
            SileroVad()
        assert info.value.recoverable is False
        assert str(default_model_path()) in str(info.value)
        assert "preparar" in str(info.value)
