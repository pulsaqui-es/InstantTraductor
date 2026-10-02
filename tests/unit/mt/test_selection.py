"""Tests de ``mt/selection.py``: elección del modelo según la VRAM libre y lectura de ``nvidia-smi``.

``nvidia-smi`` se sustituye por procesos falsos (un ``python -c ...``): no hace falta GPU.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from instanttraductor.contracts import EngineError
from instanttraductor.mt.selection import (
    VRAM_MARGIN_MIB,
    MtModel,
    choose_mt_model,
    free_vram_mb,
    model_path,
)
from instanttraductor.setup.manifest import component_dir

# Umbrales de T021 (ADR-0011): lo que ocupa cada modelo más 1 024 MiB de margen.
NEEDED_7B = 5_200 + 1_024
NEEDED_1_8B = 2_300 + 1_024


def fake_nvidia_smi(output: str = "", *, stderr: str = "", exit_code: int = 0) -> tuple[str, ...]:
    """Comando que imita a ``nvidia-smi``: imprime ``output`` y sale con ``exit_code``."""
    program = (
        "import sys; "
        f"sys.stdout.write({output!r}); sys.stdout.flush(); "
        f"sys.stderr.write({stderr!r}); sys.exit({exit_code})"
    )
    return (sys.executable, "-c", program)


# ---------------------------------------------------------------------------
# choose_mt_model
# ---------------------------------------------------------------------------
def test_the_7b_needs_5200_plus_1024_mib_free() -> None:
    assert VRAM_MARGIN_MIB == 1_024
    assert MtModel.HY_MT2_7B.required_free_mib == NEEDED_7B
    assert MtModel.HY_MT2_1_8B.required_free_mib == NEEDED_1_8B


@pytest.mark.parametrize("free_mb", [NEEDED_7B, NEEDED_7B + 1, 8_000, 12_000, 12_199.5])
def test_enough_vram_for_the_7b_picks_the_7b(free_mb: float) -> None:
    assert choose_mt_model(free_mb) is MtModel.HY_MT2_7B


@pytest.mark.parametrize("free_mb", [NEEDED_7B - 1, 6_000, 4_000, NEEDED_1_8B + 1, NEEDED_1_8B])
def test_not_enough_for_the_7b_falls_back_to_the_1_8b(
    free_mb: float, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="instanttraductor.mt.selection"):
        assert choose_mt_model(free_mb) is MtModel.HY_MT2_1_8B
    assert "Hy-MT2-1.8B" in caplog.text  # se avisa de que no habrá modo resumen


@pytest.mark.parametrize("free_mb", [NEEDED_1_8B - 1, 2_000, 500, 0, -1])
def test_not_enough_for_any_model_is_a_non_recoverable_engine_error(free_mb: float) -> None:
    with pytest.raises(EngineError) as error:
        choose_mt_model(free_mb)
    assert error.value.recoverable is False
    assert error.value.engine == "hy-mt2"
    assert "MiB" in str(error.value)


def test_choosing_the_7b_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="instanttraductor.mt.selection"):
        choose_mt_model(10_000)
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# MtModel y rutas
# ---------------------------------------------------------------------------
def test_only_the_7b_supports_concise() -> None:
    assert MtModel.HY_MT2_7B.supports_concise is True
    assert MtModel.HY_MT2_1_8B.supports_concise is False


def test_model_values_are_the_manifest_component_ids() -> None:
    assert MtModel.HY_MT2_7B.value == "hy-mt2-7b-q4"
    assert MtModel.HY_MT2_1_8B.value == "hy-mt2-1.8b-q8"
    for model in MtModel:
        component_dir(model.component_id)  # KeyError si el manifiesto no lo conoce


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("7b", MtModel.HY_MT2_7B),
        ("7B", MtModel.HY_MT2_7B),
        ("hy-mt2-7b-q4", MtModel.HY_MT2_7B),
        (MtModel.HY_MT2_7B, MtModel.HY_MT2_7B),
        ("1.8b", MtModel.HY_MT2_1_8B),
        (" 1.8B ", MtModel.HY_MT2_1_8B),
        ("hy-mt2-1.8b-q8", MtModel.HY_MT2_1_8B),
    ],
)
def test_parse_accepts_the_enum_the_component_id_and_the_short_alias(
    value: str | MtModel, expected: MtModel
) -> None:
    assert MtModel.parse(value) is expected


def test_parse_rejects_unknown_models() -> None:
    with pytest.raises(ValueError, match="desconocido"):
        MtModel.parse("13b")


def test_model_path_is_the_gguf_inside_the_component_dir() -> None:
    assert model_path(MtModel.HY_MT2_7B) == component_dir("hy-mt2-7b-q4") / "Hy-MT2-7B-Q4_K_M.gguf"
    assert model_path("1.8b") == component_dir("hy-mt2-1.8b-q8") / "Hy-MT2-1.8B-Q8_0.gguf"


def test_model_path_follows_the_app_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("INSTANTTRADUCTOR_HOME", str(tmp_path))
    assert model_path(MtModel.HY_MT2_7B).is_relative_to(tmp_path)


# ---------------------------------------------------------------------------
# free_vram_mb con un nvidia-smi falso
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("10516\n", 10_516),
        ("10516\r\n", 10_516),
        ("  7340  \n", 7_340),
        ("9000.5\n", 9_000),
        ("8192 MiB\n", 8_192),
        ("11000\n3000\n", 11_000),  # varias GPU: la primera
        ("\n\n4096\n", 4_096),
    ],
)
def test_free_vram_reads_the_first_gpu_in_mib(output: str, expected: int) -> None:
    assert free_vram_mb(command=fake_nvidia_smi(output)) == expected


def test_free_vram_result_feeds_the_choice_of_model() -> None:
    free = free_vram_mb(command=fake_nvidia_smi("6300\n"))
    assert choose_mt_model(free) is MtModel.HY_MT2_7B
    free = free_vram_mb(command=fake_nvidia_smi("6200\n"))
    assert choose_mt_model(free) is MtModel.HY_MT2_1_8B


def test_free_vram_without_nvidia_smi_is_a_non_recoverable_engine_error(tmp_path: Path) -> None:
    with pytest.raises(EngineError) as error:
        free_vram_mb(command=[str(tmp_path / "no-existe.exe")])
    assert error.value.recoverable is False
    assert "nvidia-smi" in str(error.value)


def test_free_vram_with_a_failing_nvidia_smi_reports_its_error() -> None:
    command = fake_nvidia_smi("", stderr="NVIDIA-SMI has failed", exit_code=9)
    with pytest.raises(EngineError) as error:
        free_vram_mb(command=command)
    assert error.value.recoverable is False
    assert "9" in str(error.value)
    assert "NVIDIA-SMI has failed" in str(error.value)


@pytest.mark.parametrize("output", ["", "\n", "N/A\n", "No devices were found\n"])
def test_free_vram_with_unreadable_output_is_an_engine_error(output: str) -> None:
    with pytest.raises(EngineError) as error:
        free_vram_mb(command=fake_nvidia_smi(output))
    assert error.value.recoverable is False


def test_free_vram_times_out_if_nvidia_smi_hangs() -> None:
    command = (sys.executable, "-c", "import time; time.sleep(30)")
    with pytest.raises(EngineError) as error:
        free_vram_mb(command=command, timeout_s=0.5)
    assert error.value.recoverable is False
    assert "0,5" in str(error.value) or "0.5" in str(error.value)
