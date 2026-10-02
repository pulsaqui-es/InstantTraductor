"""El servicio de voz con Qwen3-TTS real en la GPU (T025): primer audio, tiempo real y VRAM.

Marcadores ``gpu`` y ``model``: no se ejecutan por defecto. Los lanza el orquestador, de uno en uno (con la
GPU para sí: otro proceso en la GPU sube el primer audio a ~2 s, spike S1)::

    uv run --project engines/tts-qwen3 pytest engines/tts-qwen3/tests/test_engine_gpu.py -m "gpu and model" -s

Necesita la RTX 5070 con CUDA, el modelo en ``<home>\\models\\qwen3-tts-12hz-0.6b-base`` y al menos una
voz en ``<home>\\voices`` (``<home>`` es ``INSTANTTRADUCTOR_HOME`` o
``%LOCALAPPDATA%\\InstantTraductor``). Si falta algo, los tests se saltan.

Se prueba el servicio entero, como lo usa el núcleo: ``main()`` con la carga real en el hilo del motor y las
peticiones por HTTP. Los requisitos son los de ``contracts/tts-service.md``:

- primer bloque de audio: p95 <= 0,6 s desde que se recibe la petición (ADR-0008; spike S1: 182 ms);
- RTF < 0,5 (spike S1: 0,37-0,41);
- VRAM del proceso <= 4 GB (spike S1: 3 304 MiB; con el servicio entero, 3 805 MiB; con el contexto CUDA).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import statistics
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

pytestmark = [pytest.mark.gpu, pytest.mark.model]

FIRST_BLOCK_P95_S = 0.6
MAX_RTF = 0.5
MAX_VRAM_MIB = 4.0 * 1024  # medido 3,8 GB con contexto CUDA (2026-10-01); ver research.md R8
READY_TIMEOUT_S = 180.0
WARMUP_REQUESTS = 3
REPETITIONS = 2
#: Frases de medición del spike S1 (``spikes/voz/common/vozbench.py``): de 5 a 25 palabras, español de España.
SENTENCES = (
    "Vale, nos vemos luego en casa de Laura.",
    "¿Vosotros sabéis dónde he dejado las llaves del coche?",
    "No me lo puedo creer, otra vez se ha roto el ordenador.",
    "Tranquilo, tío, que lo arreglamos mañana por la mañana.",
    "Buenas noches, ¿qué tal todo?",
    "El tren con destino a Barcelona saldrá de la vía cuatro en cinco minutos.",
    "Me ha llamado mi madre al móvil y no he podido cogerlo.",
    "Vamos a tener que darnos prisa si queremos llegar antes de que empiece la película.",
    "Aquí tenéis la cuenta, y gracias por venir a nuestro restaurante.",
    "¡Cuidado! Viene un coche por la derecha y no va a frenar.",
    "Dicen que mañana lloverá en casi toda la península, aunque por la tarde saldrá el sol en el sur.",
    "¿Sabes qué hora es? Llevamos esperando casi una hora en la puerta.",
)


def _home() -> Path:
    override = os.environ.get("INSTANTTRADUCTOR_HOME")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        pytest.skip("LOCALAPPDATA no está definida")
    return Path(local) / "InstantTraductor"


def _gpu_used_mib() -> float:
    """VRAM usada en total en la GPU 0 (NVML, lo mismo que ``nvidia-smi``)."""
    import pynvml

    pynvml.nvmlInit()
    try:
        return pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0)).used / 2**20
    finally:
        pynvml.nvmlShutdown()


class VramPeak:
    """Sondea el uso total de la GPU y guarda el pico (como el ``VramSampler`` del spike S1)."""

    def __init__(self, interval_s: float = 0.1) -> None:
        self.interval_s = interval_s
        self.peak_mib = _gpu_used_mib()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="vram-peak", daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.peak_mib = max(self.peak_mib, _gpu_used_mib())

    def __enter__(self) -> VramPeak:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(2.0)
        self.peak_mib = max(self.peak_mib, _gpu_used_mib())


class _Stream(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self._guard = threading.Lock()

    def write(self, text: str) -> int:
        with self._guard:
            return super().write(text)

    def text(self) -> str:
        with self._guard:
            return self.getvalue()


class RealService:
    """El servicio con la carga real de Qwen3-TTS, corriendo en un hilo de este proceso."""

    def __init__(self, base_url: str, vram_baseline_mib: float, stderr: _Stream) -> None:
        self.base_url = base_url
        self.vram_baseline_mib = vram_baseline_mib
        self.stderr = stderr
        self.client = httpx.Client(base_url=base_url, timeout=60.0, trust_env=False)

    def synthesize(self, text: str, voice_id: str) -> tuple[float, float, bytes, int]:
        """Una petición: (segundos hasta el primer bloque, segundos totales, PCM, frecuencia)."""
        started = time.perf_counter()
        with self.client.stream("POST", "/synthesize", json={"text": text, "voice_id": voice_id}) as response:
            assert response.status_code == 200, response.read()
            rate = int(response.headers["x-sample-rate"])
            blocks = response.iter_raw()
            first = next(blocks)
            first_block_s = time.perf_counter() - started
            pcm = first + b"".join(blocks)
        return first_block_s, time.perf_counter() - started, pcm, rate


@pytest.fixture(scope="module")
def service() -> Iterator[RealService]:
    pytest.importorskip("torch")
    import torch

    if not torch.cuda.is_available():
        pytest.skip("CUDA no está disponible")
    from tts_service.engine import MODEL_DIR_NAME, load_engine
    from tts_service.server import main

    models, voices = _home() / "models", _home() / "voices"
    if not (models / MODEL_DIR_NAME / "config.json").is_file():
        pytest.skip(f"Falta el modelo en {models / MODEL_DIR_NAME}")
    if not any(voices.glob("*.json")):
        pytest.skip(f"Faltan las voces en {voices}")

    baseline_mib = _gpu_used_mib()
    stdout, stderr = _Stream(), _Stream()
    outcome: list[int] = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sys, "stdout", stdout)
        patch.setattr(sys, "stderr", stderr)
        argv = ["--port", "0", "--voices-dir", str(voices), "--models-dir", str(models)]
        thread = threading.Thread(
            target=lambda: outcome.append(main(argv, engine_factory=load_engine)),
            name="gpu-service",
            daemon=True,
        )
        thread.start()
        deadline = time.monotonic() + READY_TIMEOUT_S
        info: dict[str, Any] | None = None
        while info is None:
            line = next((x for x in stdout.text().splitlines() if x.startswith("{")), None)
            if line is not None:
                info = json.loads(line)
            elif not thread.is_alive():
                pytest.fail(f"El servicio terminó sin «ready» (código {outcome}):\n{stderr.text()}")
            elif time.monotonic() > deadline:
                pytest.fail(f"El servicio no quedó listo en {READY_TIMEOUT_S:g} s:\n{stderr.text()}")
            else:
                time.sleep(0.05)
        patch.undo()  # ya está listo: los ``print`` de los tests vuelven a verse con ``-s``
    running = RealService(f"http://127.0.0.1:{info['port']}", baseline_mib, stderr)
    try:
        yield running
    finally:
        running.client.close()
        with contextlib.suppress(httpx.HTTPError):
            httpx.post(f"{running.base_url}/shutdown", timeout=5.0, trust_env=False)
        thread.join(30.0)


@pytest.fixture(scope="module")
def voice_ids(service: RealService) -> list[str]:
    voices = service.client.get("/voices").json()
    assert voices
    return [voice["voice_id"] for voice in voices]


@pytest.fixture(scope="module")
def warm(service: RealService, voice_ids: list[str]) -> None:
    """Las peticiones de calentamiento que no se miden (el spike S1 hacía lo mismo)."""
    for text in SENTENCES[:WARMUP_REQUESTS]:
        service.synthesize(text, voice_ids[0])


class TestRealEngine:
    def test_the_health_check_describes_the_real_engine(self, service: RealService) -> None:
        health = service.client.get("/health").json()

        assert health["status"] == "ok"
        assert health["engine"] == "qwen3-tts"
        assert health["model"] == "Qwen3-TTS-12Hz-0.6B-Base"
        assert health["sample_rate"] == 24_000
        assert health["supports_speed"] is False
        assert 0 < health["vram_mb"] <= MAX_VRAM_MIB

    def test_the_first_audio_block_arrives_in_under_0_6_s_at_p95(
        self, service: RealService, voice_ids: list[str], warm: None
    ) -> None:
        first_block = [
            service.synthesize(text, voice_ids[0])[0] for _ in range(REPETITIONS) for text in SENTENCES
        ]

        p50, p95 = statistics.median(first_block), float(np.percentile(first_block, 95))
        requests = len(first_block)
        print(f"\nprimer bloque ({requests} peticiones): p50 {p50 * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms")
        assert p95 <= FIRST_BLOCK_P95_S

    def test_the_synthesis_runs_faster_than_real_time(
        self, service: RealService, voice_ids: list[str], warm: None
    ) -> None:
        factors = []
        for text in SENTENCES:
            _, total_s, pcm, rate = service.synthesize(text, voice_ids[0])
            factors.append(total_s / (len(pcm) / 4 / rate))

        print(f"\nRTF: mediana {statistics.median(factors):.2f}, máximo {max(factors):.2f}")
        assert statistics.median(factors) < MAX_RTF

    def test_the_process_vram_stays_under_4_gb(
        self, service: RealService, voice_ids: list[str], warm: None
    ) -> None:
        with VramPeak() as peak:
            for text in SENTENCES:
                service.synthesize(text, voice_ids[0])

        used_mib = peak.peak_mib - service.vram_baseline_mib
        print(f"\nVRAM del proceso (pico NVML menos línea base, con contexto CUDA): {used_mib:.0f} MiB")
        assert used_mib <= MAX_VRAM_MIB

    def test_the_audio_is_float32_mono_at_24_khz_and_plausible(
        self, service: RealService, voice_ids: list[str], warm: None
    ) -> None:
        text = SENTENCES[7]  # 15 palabras

        _, _, pcm, rate = service.synthesize(text, voice_ids[0])

        samples = np.frombuffer(pcm, dtype="<f4")
        assert rate == 24_000
        assert len(pcm) % 4 == 0
        assert np.all(np.isfinite(samples))
        assert float(np.max(np.abs(samples))) <= 1.0
        assert float(np.max(np.abs(samples))) > 0.05, "la voz sale en silencio"
        words = len(text.split())
        assert 0.15 * words <= len(samples) / rate <= 1.0 * words

    def test_every_installed_voice_synthesizes(
        self, service: RealService, voice_ids: list[str], warm: None
    ) -> None:
        for voice_id in voice_ids:
            first_block_s, _, pcm, _ = service.synthesize(SENTENCES[0], voice_id)

            assert len(pcm) > 0, voice_id
            assert first_block_s < 2.0, voice_id
