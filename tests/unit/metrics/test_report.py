"""Tests del informe (T030): JSON con el esquema exacto de `contracts/informe.md` y su resumen en Markdown.

Incluye un JSON de referencia de una sesión sintética (`REFERENCE_JSON`): sus cifras están calculadas a mano
a partir de las etapas de cada frase (ver `SPOKEN_STAGES`) y fijan el esquema, el orden de las claves, los
redondeos y el criterio de los percentiles (solo frases pronunciadas, interpolación lineal).
"""

from __future__ import annotations

import io
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from instanttraductor.config import Settings
from instanttraductor.contracts import Outcome, StageTimings, TranslationMode, UtteranceRecord
from instanttraductor.metrics.recorder import MetricsRecorder
from instanttraductor.metrics.report import (
    SCHEMA_VERSION,
    build_report,
    report_to_json,
)
from instanttraductor.setup.manifest import Component
from instanttraductor.ui.terminal import TerminalUI

NORMAL = TranslationMode.NORMAL
CONCISE = TranslationMode.CONCISE
MADRID = timezone(timedelta(hours=2))
STARTED_AT = datetime(2026, 10, 1, 21, 30, 0, tzinfo=MADRID)

TOP_LEVEL_KEYS = [
    "schema_version",
    "session_id",
    "mode",
    "input_file",
    "started_at",
    "duration_s",
    "settings",
    "components",
    "summary",
    "diagnostics",
    "utterances",
]
SUMMARY_KEYS = [
    "utterances",
    "spoken",
    "concise",
    "accelerated",
    "dropped",
    "rejected",
    "failed",
    "sentence_delay_s",
    "stages_s",
]
STAGE_NAMES = ["capture", "asr", "mt", "tts_first", "playback"]
SETTINGS_KEYS = [
    "voz",
    "volumen_voz",
    "umbral_acelerar_s",
    "umbral_resumir_s",
    "umbral_descartar_s",
    "velocidad_max",
    "max_habla_sin_traducir_s",
]
UTTERANCE_KEYS = [
    "unit_id",
    "source_text",
    "translated_text",
    "mode",
    "speed",
    "outcome",
    "reason",
    "timings",
    "sentence_delay_s",
]
TIMINGS_KEYS = [
    "t_start_audio",
    "t_end_audio",
    "unit_ready_at",
    "captured_at",
    "asr_final_at",
    "mt_started_at",
    "mt_finished_at",
    "tts_started_at",
    "tts_first_audio_at",
    "tts_finished_at",
    "play_started_at",
    "play_finished_at",
]
DIAGNOSTICS_KEYS = [
    "startup_s",
    "rss_mb_min5",
    "rss_mb_end",
    "rss_children_mb_min5",
    "rss_children_mb_end",
    "max_lag_s",
    "lag_over_drop_max_streak_s",
    "echo_events",
    "component_restarts",
    "underruns",
    "mt_model",
]


# --------------------------------------------------------------------------------------------------
# Constructores de datos sintéticos
# --------------------------------------------------------------------------------------------------


def spoken(
    unit_id: int,
    t_end: float,
    stages: tuple[float, float, float, float, float],
    *,
    source: str = "hello",
    translated: str = "hola",
    mode: TranslationMode = NORMAL,
    speed: float = 1.0,
) -> UtteranceRecord:
    """Una frase pronunciada con una línea de tiempo sin huecos, a partir de sus cinco etapas.

    `stages` = (captura, ASR, traducción, primer audio, reproducción). El retardo de frase resulta ser la
    suma de las cuatro últimas.
    """
    capture, asr, mt, tts_first, playback = stages
    asr_final_at = t_end + asr
    mt_finished_at = asr_final_at + mt
    tts_first_audio_at = mt_finished_at + tts_first
    play_started_at = tts_first_audio_at + playback
    return UtteranceRecord(
        unit_id=unit_id,
        source_text=source,
        translated_text=translated,
        mode=mode,
        speed=speed,
        outcome=Outcome.SPOKEN,
        reason=None,
        timings=StageTimings(
            t_start_audio=t_end - 1.5,
            t_end_audio=t_end,
            unit_ready_at=asr_final_at,
            captured_at=t_end + capture,
            asr_final_at=asr_final_at,
            mt_started_at=asr_final_at,
            mt_finished_at=mt_finished_at,
            tts_started_at=mt_finished_at,
            tts_first_audio_at=tts_first_audio_at,
            tts_finished_at=tts_first_audio_at + 0.5,
            play_started_at=play_started_at,
            play_finished_at=play_started_at + 1.0,
        ),
    )


def lost(
    unit_id: int,
    outcome: Outcome,
    reason: str,
    t_end: float,
    *,
    source: str = "never heard",
    translated: str | None = None,
    mode: TranslationMode = NORMAL,
    speed: float = 1.0,
    **timings: float | None,
) -> UtteranceRecord:
    """Una frase que no se pronunció (descartada, rechazada o fallida), con los tiempos que se pidan."""
    return UtteranceRecord(
        unit_id=unit_id,
        source_text=source,
        translated_text=translated,
        mode=mode,
        speed=speed,
        outcome=outcome,
        reason=reason,
        timings=StageTimings(
            **{"t_start_audio": t_end - 1.5, "t_end_audio": t_end, "unit_ready_at": t_end + 0.9, **timings}  # type: ignore[arg-type]
        ),
    )


def recorder_with(*records: UtteranceRecord, drop_after_s: float = 8.0) -> MetricsRecorder:
    recorder = MetricsRecorder(drop_after_s=drop_after_s)
    for record in records:
        recorder.add_record(record)
    return recorder


def build(recorder: MetricsRecorder | None = None, **overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "mode": "directo",
        "started_at": STARTED_AT,
        "duration_s": 600.0,
        "settings": Settings(voice="es-f-01"),
    }
    arguments.update(overrides)
    return build_report(recorder if recorder is not None else MetricsRecorder(), **arguments)


#: Cinco frases pronunciadas con etapas (captura, ASR, traducción, primer audio, reproducción) que
#: dan retardos de 1,5 · 2,0 · 3,0 · 4,0 · 6,0 s. Los percentiles se pueden comprobar a mano.
SPOKEN_STAGES = [
    (0.08, 0.60, 0.15, 0.30, 0.45),
    (0.10, 0.70, 0.20, 0.40, 0.70),
    (0.12, 0.80, 0.25, 0.45, 1.50),
    (0.12, 0.90, 0.35, 0.55, 2.20),
    (0.14, 1.00, 0.45, 0.60, 3.95),
]


def five_spoken(first_unit: int = 1) -> list[UtteranceRecord]:
    return [
        spoken(first_unit + index, 10.0 * (index + 1), stages) for index, stages in enumerate(SPOKEN_STAGES)
    ]


# --------------------------------------------------------------------------------------------------
# Esquema (contracts/informe.md)
# --------------------------------------------------------------------------------------------------


class TestSchema:
    def test_top_level_keys_and_their_order(self) -> None:
        assert list(build(recorder_with(*five_spoken()))) == TOP_LEVEL_KEYS

    def test_the_schema_version_is_one(self) -> None:
        assert SCHEMA_VERSION == 1
        assert build()["schema_version"] == 1

    def test_summary_keys(self) -> None:
        summary = build(recorder_with(*five_spoken()))["summary"]
        assert list(summary) == SUMMARY_KEYS
        assert list(summary["sentence_delay_s"]) == ["p50", "p95", "max"]
        assert list(summary["stages_s"]) == STAGE_NAMES
        for stage in STAGE_NAMES:
            assert list(summary["stages_s"][stage]) == ["p50", "p95"]

    def test_settings_block_has_the_seven_keys_in_spanish(self) -> None:
        settings = build(settings=Settings(voice="es-f-01", voice_volume=0.8, max_speed=1.3))["settings"]
        assert list(settings) == SETTINGS_KEYS
        assert settings == {
            "voz": "es-f-01",
            "volumen_voz": 0.8,
            "umbral_acelerar_s": 3.0,
            "umbral_resumir_s": 5.0,
            "umbral_descartar_s": 8.0,
            "velocidad_max": 1.3,
            "max_habla_sin_traducir_s": 6.0,
        }

    def test_each_utterance_has_the_contract_keys(self) -> None:
        report = build(recorder_with(*five_spoken()))
        for entry in report["utterances"]:
            assert list(entry) == UTTERANCE_KEYS
            assert list(entry["timings"]) == TIMINGS_KEYS

    def test_diagnostics_are_the_ones_of_the_recorder(self) -> None:
        recorder = recorder_with(*five_spoken())
        recorder.set_mt_model("hy-mt2-7b-q4")
        report = build(recorder)
        assert list(report["diagnostics"]) == DIAGNOSTICS_KEYS
        assert report["diagnostics"] == recorder.diagnostics(end_t=600.0)

    def test_the_mode_and_the_input_file(self) -> None:
        live = build()
        assert (live["mode"], live["input_file"]) == ("directo", None)
        offline = build(mode="archivo", input_file=Path("C:/videos/serie.mkv"))
        assert offline["mode"] == "archivo"
        assert offline["input_file"] == str(Path("C:/videos/serie.mkv"))

    def test_an_unknown_mode_is_refused(self) -> None:
        with pytest.raises(ValueError, match="modo"):
            build(mode="en vivo")

    def test_components_may_be_manifest_entries_or_mappings(self) -> None:
        component = Component(
            component_id="hy-mt2-7b-q4",
            name="Hy-MT2 7B",
            version="Q4_K_M",
            kind="modelo",
            license="Apache-2.0",
            install_dir="models/hy-mt2-7b",
        )
        report = build(
            components=[component, {"component_id": "qwen3-tts", "version": "0.6B", "license": "Apache-2.0"}]
        )
        assert report["components"] == [
            {"component_id": "hy-mt2-7b-q4", "version": "Q4_K_M", "license": "Apache-2.0"},
            {"component_id": "qwen3-tts", "version": "0.6B", "license": "Apache-2.0"},
        ]

    def test_without_components_the_list_is_empty(self) -> None:
        assert build()["components"] == []


class TestSessionHeader:
    def test_the_session_id_comes_from_the_start_time(self) -> None:
        assert build()["session_id"] == "20261001-213000"

    def test_an_explicit_session_id_wins(self) -> None:
        assert build(session_id="20260101-000000")["session_id"] == "20260101-000000"

    def test_started_at_is_iso_with_the_offset_and_without_fractions(self) -> None:
        report = build(started_at=STARTED_AT.replace(microsecond=654321))
        assert report["started_at"] == "2026-10-01T21:30:00+02:00"

    def test_a_naive_start_time_is_taken_as_local_time_and_gets_an_offset(self) -> None:
        report = build(started_at=datetime(2026, 10, 1, 21, 30, 0))
        assert re.fullmatch(r"2026-10-01T21:30:00[+-]\d\d:\d\d", report["started_at"])
        assert report["session_id"] == "20261001-213000"

    def test_the_duration_has_three_decimals_and_is_never_negative(self) -> None:
        assert build(duration_s=1800.123456)["duration_s"] == 1800.123
        assert build(duration_s=-5.0)["duration_s"] == 0.0


# --------------------------------------------------------------------------------------------------
# Estadísticas
# --------------------------------------------------------------------------------------------------


class TestSummary:
    def test_percentiles_of_the_sentence_delay_and_of_each_stage(self) -> None:
        summary = build(recorder_with(*five_spoken()))["summary"]
        assert summary["sentence_delay_s"] == {"p50": 3.0, "p95": 5.6, "max": 6.0}
        assert summary["stages_s"] == {
            "capture": {"p50": 0.12, "p95": 0.136},
            "asr": {"p50": 0.8, "p95": 0.98},
            "mt": {"p50": 0.25, "p95": 0.43},
            "tts_first": {"p50": 0.45, "p95": 0.59},
            "playback": {"p50": 1.5, "p95": 3.6},
        }

    def test_the_percentiles_interpolate_linearly(self) -> None:
        records = [spoken(n, 10.0 * n, (0.1, 0.4, 0.1, 0.1, n - 0.6)) for n in (1, 2, 3, 4)]
        delays = sorted(r.timings.sentence_delay for r in records if r.timings.sentence_delay is not None)
        assert delays == pytest.approx([1.0, 2.0, 3.0, 4.0])
        delay = build(recorder_with(*records))["summary"]["sentence_delay_s"]
        assert delay == {"p50": 2.5, "p95": 3.85, "max": 4.0}  # índices 1,5 y 2,85 de 0 a 3

    def test_a_single_spoken_unit_gives_the_same_value_everywhere(self) -> None:
        delay = build(recorder_with(spoken(1, 10.0, (0.1, 1.0, 0.2, 0.3, 0.4))))["summary"][
            "sentence_delay_s"
        ]
        assert delay == {"p50": 1.9, "p95": 1.9, "max": 1.9}

    def test_units_that_were_not_spoken_never_enter_the_percentiles(self) -> None:
        records = [
            *five_spoken(),
            lost(6, Outcome.DROPPED, "retraso excesivo", 60.0, captured_at=61.0, asr_final_at=69.0),
            lost(
                7,
                Outcome.REJECTED,
                "filtros",
                70.0,
                asr_final_at=79.0,
                mt_started_at=79.0,
                mt_finished_at=99.0,
            ),
            lost(8, Outcome.FAILED, "voz", 80.0, tts_started_at=81.0, tts_first_audio_at=99.0),
        ]
        summary = build(recorder_with(*records))["summary"]
        assert summary["sentence_delay_s"] == {"p50": 3.0, "p95": 5.6, "max": 6.0}
        assert summary["stages_s"]["asr"] == {"p50": 0.8, "p95": 0.98}
        assert summary["stages_s"]["mt"] == {"p50": 0.25, "p95": 0.43}
        assert summary["stages_s"]["capture"] == {"p50": 0.12, "p95": 0.136}

    def test_a_stage_skips_the_units_that_lack_one_of_its_two_instants(self) -> None:
        records = five_spoken()
        tweaked = [_without(records[0], "captured_at"), *records[1:]]
        summary = build(recorder_with(*tweaked))["summary"]
        # Capture con cuatro valores (0,10 · 0,12 · 0,12 · 0,14): mediana 0,12 y p95 = 0,12 + 0,85 × 0,02
        assert summary["stages_s"]["capture"] == {"p50": 0.12, "p95": 0.137}
        assert summary["stages_s"]["asr"] == {"p50": 0.8, "p95": 0.98}  # esta etapa sigue con las cinco
        assert summary["sentence_delay_s"]["max"] == 6.0

    def test_counts(self) -> None:
        records = [
            spoken(1, 10.0, SPOKEN_STAGES[0]),
            spoken(2, 20.0, SPOKEN_STAGES[1], speed=1.1),
            spoken(3, 30.0, SPOKEN_STAGES[2], mode=CONCISE, speed=1.25),
            lost(4, Outcome.DROPPED, "retraso excesivo", 40.0),
            lost(5, Outcome.DROPPED, "parada", 50.0),
            lost(6, Outcome.REJECTED, "filtros", 60.0),
            lost(7, Outcome.FAILED, "voz", 70.0),
        ]
        summary = build(recorder_with(*records))["summary"]
        assert {key: summary[key] for key in SUMMARY_KEYS[:7]} == {
            "utterances": 7,
            "spoken": 3,
            "concise": 1,
            "accelerated": 2,
            "dropped": 2,
            "rejected": 1,
            "failed": 1,
        }

    def test_concise_and_accelerated_only_count_what_was_actually_heard(self) -> None:
        records = [
            spoken(1, 10.0, SPOKEN_STAGES[0], mode=CONCISE, speed=1.2),
            lost(2, Outcome.DROPPED, "retraso excesivo", 20.0, mode=CONCISE, speed=1.25),
            lost(3, Outcome.FAILED, "voz", 30.0, mode=CONCISE, speed=1.25),
            lost(4, Outcome.REJECTED, "filtros", 40.0, mode=CONCISE, speed=1.25),
        ]
        summary = build(recorder_with(*records))["summary"]
        assert (summary["concise"], summary["accelerated"]) == (1, 1)

    def test_a_speed_of_one_is_not_an_acceleration(self) -> None:
        records = [
            spoken(1, 10.0, SPOKEN_STAGES[0], speed=1.0),
            spoken(2, 20.0, SPOKEN_STAGES[1], speed=1.0004),  # se ve como 1,0 en el informe
            spoken(3, 30.0, SPOKEN_STAGES[2], speed=1.001),
        ]
        assert build(recorder_with(*records))["summary"]["accelerated"] == 1

    def test_an_empty_session_has_zero_counts_and_null_percentiles(self) -> None:
        summary = build()["summary"]
        assert {key: summary[key] for key in SUMMARY_KEYS[:7]} == dict.fromkeys(SUMMARY_KEYS[:7], 0)
        assert summary["sentence_delay_s"] == {"p50": None, "p95": None, "max": None}
        assert summary["stages_s"] == {stage: {"p50": None, "p95": None} for stage in STAGE_NAMES}
        assert build()["utterances"] == []

    def test_a_session_where_nothing_was_spoken_still_counts_what_happened(self) -> None:
        records = [lost(1, Outcome.DROPPED, "parada", 10.0), lost(2, Outcome.REJECTED, "filtros", 20.0)]
        summary = build(recorder_with(*records))["summary"]
        assert (summary["utterances"], summary["spoken"], summary["dropped"], summary["rejected"]) == (
            2,
            0,
            1,
            1,
        )
        assert summary["sentence_delay_s"]["p50"] is None


class TestUtterances:
    def test_are_listed_in_unit_order(self) -> None:
        records = five_spoken()
        report = build(recorder_with(*reversed(records)))
        assert [entry["unit_id"] for entry in report["utterances"]] == [1, 2, 3, 4, 5]

    def test_each_one_carries_its_texts_outcome_and_reason(self) -> None:
        records = [
            spoken(1, 10.0, SPOKEN_STAGES[0], source="Where were you?", translated="¿Dónde estabas?"),
            lost(2, Outcome.DROPPED, "retraso excesivo", 20.0, source="Never mind."),
        ]
        first, second = build(recorder_with(*records))["utterances"]
        assert (first["source_text"], first["translated_text"]) == ("Where were you?", "¿Dónde estabas?")
        assert (first["mode"], first["speed"], first["outcome"], first["reason"]) == (
            "normal",
            1.0,
            "pronunciada",
            None,
        )
        assert (second["translated_text"], second["outcome"], second["reason"]) == (
            None,
            "descartada",
            "retraso excesivo",
        )

    def test_the_mode_and_the_outcome_are_the_values_of_the_contract(self) -> None:
        records = [
            spoken(1, 10.0, SPOKEN_STAGES[0], mode=CONCISE),
            lost(2, Outcome.REJECTED, "filtros", 20.0),
            lost(3, Outcome.FAILED, "voz", 30.0),
        ]
        entries = build(recorder_with(*records))["utterances"]
        assert [(e["mode"], e["outcome"]) for e in entries] == [
            ("conciso", "pronunciada"),
            ("normal", "rechazada"),
            ("normal", "fallida"),
        ]

    def test_the_sentence_delay_is_play_started_minus_the_end_of_the_speech(self) -> None:
        records = [spoken(1, 10.0, SPOKEN_STAGES[0]), lost(2, Outcome.DROPPED, "parada", 20.0)]
        first, second = build(recorder_with(*records))["utterances"]
        assert first["sentence_delay_s"] == 1.5
        assert second["sentence_delay_s"] is None

    def test_the_timings_are_listed_in_the_order_of_the_contract_with_nulls_for_missing_ones(self) -> None:
        record = lost(1, Outcome.FAILED, "voz", 20.0, captured_at=20.1, mt_started_at=21.0)
        timings = build(recorder_with(record))["utterances"][0]["timings"]
        assert timings == {
            "t_start_audio": 18.5,
            "t_end_audio": 20.0,
            "unit_ready_at": 20.9,
            "captured_at": 20.1,
            "asr_final_at": None,
            "mt_started_at": 21.0,
            "mt_finished_at": None,
            "tts_started_at": None,
            "tts_first_audio_at": None,
            "tts_finished_at": None,
            "play_started_at": None,
            "play_finished_at": None,
        }

    def test_times_are_rounded_to_three_decimals(self) -> None:
        record = spoken(1, 3.1234567, (0.0123456, 0.5555555, 0.1111111, 0.2222222, 0.3333333), speed=1.23456)
        entry = build(recorder_with(record))["utterances"][0]
        assert entry["timings"]["t_end_audio"] == 3.123
        assert entry["timings"]["captured_at"] == 3.136
        assert entry["speed"] == 1.235
        assert entry["sentence_delay_s"] == 1.222

    def test_a_time_that_is_not_finite_becomes_null(self) -> None:
        record = lost(1, Outcome.FAILED, "voz", 20.0, captured_at=math.nan, asr_final_at=math.inf)
        timings = build(recorder_with(record))["utterances"][0]["timings"]
        assert timings["captured_at"] is None and timings["asr_final_at"] is None


def _without(record: UtteranceRecord, field: str) -> UtteranceRecord:
    """Copia del registro con un tiempo de `StageTimings` a `None`."""
    values = {name: getattr(record.timings, name) for name in TIMINGS_KEYS}
    values[field] = None
    return UtteranceRecord(
        record.unit_id,
        record.source_text,
        record.translated_text,
        record.mode,
        record.speed,
        record.outcome,
        record.reason,
        StageTimings(**values),
    )


# --------------------------------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------------------------------


class TestJson:
    def test_is_utf8_text_with_the_accents_unescaped(self) -> None:
        record = spoken(
            1,
            10.0,
            SPOKEN_STAGES[0],
            source="Where were you last night?",
            translated="¿Dónde estuviste anoche?",
        )
        text = report_to_json(build(recorder_with(record)))
        assert "¿Dónde estuviste anoche?" in text
        assert "\\u" not in text

    def test_round_trips_to_the_same_report(self) -> None:
        report = build(recorder_with(*five_spoken()))
        assert json.loads(report_to_json(report)) == report

    def test_ends_with_a_newline_and_keeps_the_key_order(self) -> None:
        text = report_to_json(build(recorder_with(*five_spoken())))
        assert text.endswith("\n") and not text.endswith("\n\n")
        assert list(json.loads(text)) == TOP_LEVEL_KEYS

    def test_numbers_that_are_not_finite_never_reach_the_file(self) -> None:
        report = build(recorder_with(lost(1, Outcome.FAILED, "voz", 20.0, captured_at=math.nan)))
        assert "NaN" not in report_to_json(report) and "Infinity" not in report_to_json(report)


# --------------------------------------------------------------------------------------------------
# Compatibilidad con la interfaz de terminal
# --------------------------------------------------------------------------------------------------


class TestTerminalSummary:
    def test_the_terminal_ui_can_show_the_report(self) -> None:
        recorder = recorder_with(*five_spoken(), lost(6, Outcome.DROPPED, "retraso excesivo", 60.0))
        recorder.set_mt_model("hy-mt2-7b-q4")
        report = build(recorder)
        console = Console(file=io.StringIO(), record=True, width=100, force_terminal=False, color_system=None)
        TerminalUI(lambda: None, console=console, poll_interval_s=None).show_summary(report)
        text = console.export_text()
        assert "Resumen de la sesión" in text
        assert "hy-mt2-7b-q4" in text
        assert "p50 3,0 s" in text and "p95 5,6 s" in text


# --------------------------------------------------------------------------------------------------
# Sesión sintética de referencia
# --------------------------------------------------------------------------------------------------


def reference_report() -> dict[str, Any]:
    """Informe de una sesión sintética de 30 minutos, con todo lo que puede pasarle a una frase.

    Ocho frases: cinco pronunciadas (`SPOKEN_STAGES`), una descartada por retraso, una rechazada por los
    filtros y una fallida (resumida y acelerada, pero que no llegó a sonar). A las no pronunciadas se les
    dan tiempos enormes a propósito: si entraran en los percentiles se notaría.
    """
    values = {"core": 0.0, "children": 0.0}
    recorder = MetricsRecorder(
        drop_after_s=8.0,
        core_rss_mb=lambda: values["core"],
        children_rss_mb=lambda pids: values["children"],
        memory_interval_s=1.0,
    )
    records = [
        spoken(
            1, 10.0, SPOKEN_STAGES[0],
            source="Where were you last night?", translated="¿Dónde estuviste anoche?",
        ),
        spoken(
            2, 20.0, SPOKEN_STAGES[1],
            source="I was at the office until late.", translated="Estuve en la oficina hasta tarde.",
        ),
        spoken(
            3, 30.0, SPOKEN_STAGES[2],
            source="That is not what he told me.", translated="Eso no es lo que él me dijo.", speed=1.05,
        ),
        spoken(
            4, 40.0, SPOKEN_STAGES[3],
            source="So the plan is simple: we wait here.",
            translated="Esperamos aquí.", mode=CONCISE, speed=1.25,
        ),
        spoken(
            5, 50.0, SPOKEN_STAGES[4],
            source="We should call the whole thing off.",
            translated="Mejor cancelarlo todo.", mode=CONCISE, speed=1.25,
        ),
        lost(
            6, Outcome.DROPPED, "retraso excesivo", 60.0, source="Never mind.",
            unit_ready_at=69.0, captured_at=60.1, asr_final_at=69.0,
        ),
        lost(
            7, Outcome.REJECTED, "traducción rechazada por los filtros de salida", 70.0, source="Uh-huh.",
            unit_ready_at=70.7, captured_at=70.1, asr_final_at=70.7, mt_started_at=70.7, mt_finished_at=75.7,
        ),
        lost(
            8, Outcome.FAILED, "voz: el servicio no responde", 80.0,
            source="See you tomorrow, everyone.", translated="Hasta mañana.", mode=CONCISE, speed=1.25,
            unit_ready_at=80.7, captured_at=80.1, asr_final_at=80.7, mt_started_at=80.7, mt_finished_at=80.9,
            tts_started_at=80.9,
        ),
    ]  # fmt: skip
    for record in records:
        recorder.add_record(record)
    for t, lag in (
        (100.0, 2.0), (100.5, 3.1), (101.0, 6.2), (101.5, 8.3), (102.0, 8.6), (102.5, 8.1),
        (103.0, 7.4), (103.5, 2.0), (200.0, 8.2), (200.5, 3.0),
    ):  # fmt: skip
        recorder.add_lag_sample(t, lag)
    for t, core, children in (
        (60.0, 700.0, 7000.0), (300.0, 812.4, 7900.4), (900.0, 820.0, 7950.0), (1800.0, 830.2, 8050.6),
    ):  # fmt: skip
        values["core"], values["children"] = core, children
        recorder.sample_memory(t)
    recorder.set_startup_s(34.2)
    recorder.set_mt_model("hy-mt2-7b-q4")
    recorder.count_echo_event()
    recorder.count_component_restart()
    recorder.set_underruns(2)
    return build(
        recorder,
        duration_s=1800.0,
        components=[
            {"component_id": "hy-mt2-7b-q4", "version": "Q4_K_M", "license": "Apache-2.0"},
            {"component_id": "qwen3-tts", "version": "12Hz-0.6B-Base", "license": "Apache-2.0"},
        ],
    )


#: `informe.json` de `reference_report()`: las cifras se comprobaron a mano contra `SPOKEN_STAGES`.
REFERENCE_JSON = """\
{
  "schema_version": 1,
  "session_id": "20261001-213000",
  "mode": "directo",
  "input_file": null,
  "started_at": "2026-10-01T21:30:00+02:00",
  "duration_s": 1800.0,
  "settings": {
    "voz": "es-f-01",
    "volumen_voz": 1.0,
    "umbral_acelerar_s": 3.0,
    "umbral_resumir_s": 5.0,
    "umbral_descartar_s": 8.0,
    "velocidad_max": 1.25,
    "max_habla_sin_traducir_s": 6.0
  },
  "components": [
    {
      "component_id": "hy-mt2-7b-q4",
      "version": "Q4_K_M",
      "license": "Apache-2.0"
    },
    {
      "component_id": "qwen3-tts",
      "version": "12Hz-0.6B-Base",
      "license": "Apache-2.0"
    }
  ],
  "summary": {
    "utterances": 8,
    "spoken": 5,
    "concise": 2,
    "accelerated": 3,
    "dropped": 1,
    "rejected": 1,
    "failed": 1,
    "sentence_delay_s": {
      "p50": 3.0,
      "p95": 5.6,
      "max": 6.0
    },
    "stages_s": {
      "capture": {
        "p50": 0.12,
        "p95": 0.136
      },
      "asr": {
        "p50": 0.8,
        "p95": 0.98
      },
      "mt": {
        "p50": 0.25,
        "p95": 0.43
      },
      "tts_first": {
        "p50": 0.45,
        "p95": 0.59
      },
      "playback": {
        "p50": 1.5,
        "p95": 3.6
      }
    }
  },
  "diagnostics": {
    "startup_s": 34.2,
    "rss_mb_min5": 812,
    "rss_mb_end": 830,
    "rss_children_mb_min5": 7900,
    "rss_children_mb_end": 8051,
    "max_lag_s": 8.6,
    "lag_over_drop_max_streak_s": 1.5,
    "echo_events": 1,
    "component_restarts": 1,
    "underruns": 2,
    "mt_model": "hy-mt2-7b-q4"
  },
  "utterances": [
    {
      "unit_id": 1,
      "source_text": "Where were you last night?",
      "translated_text": "¿Dónde estuviste anoche?",
      "mode": "normal",
      "speed": 1.0,
      "outcome": "pronunciada",
      "reason": null,
      "timings": {
        "t_start_audio": 8.5,
        "t_end_audio": 10.0,
        "unit_ready_at": 10.6,
        "captured_at": 10.08,
        "asr_final_at": 10.6,
        "mt_started_at": 10.6,
        "mt_finished_at": 10.75,
        "tts_started_at": 10.75,
        "tts_first_audio_at": 11.05,
        "tts_finished_at": 11.55,
        "play_started_at": 11.5,
        "play_finished_at": 12.5
      },
      "sentence_delay_s": 1.5
    },
    {
      "unit_id": 2,
      "source_text": "I was at the office until late.",
      "translated_text": "Estuve en la oficina hasta tarde.",
      "mode": "normal",
      "speed": 1.0,
      "outcome": "pronunciada",
      "reason": null,
      "timings": {
        "t_start_audio": 18.5,
        "t_end_audio": 20.0,
        "unit_ready_at": 20.7,
        "captured_at": 20.1,
        "asr_final_at": 20.7,
        "mt_started_at": 20.7,
        "mt_finished_at": 20.9,
        "tts_started_at": 20.9,
        "tts_first_audio_at": 21.3,
        "tts_finished_at": 21.8,
        "play_started_at": 22.0,
        "play_finished_at": 23.0
      },
      "sentence_delay_s": 2.0
    },
    {
      "unit_id": 3,
      "source_text": "That is not what he told me.",
      "translated_text": "Eso no es lo que él me dijo.",
      "mode": "normal",
      "speed": 1.05,
      "outcome": "pronunciada",
      "reason": null,
      "timings": {
        "t_start_audio": 28.5,
        "t_end_audio": 30.0,
        "unit_ready_at": 30.8,
        "captured_at": 30.12,
        "asr_final_at": 30.8,
        "mt_started_at": 30.8,
        "mt_finished_at": 31.05,
        "tts_started_at": 31.05,
        "tts_first_audio_at": 31.5,
        "tts_finished_at": 32.0,
        "play_started_at": 33.0,
        "play_finished_at": 34.0
      },
      "sentence_delay_s": 3.0
    },
    {
      "unit_id": 4,
      "source_text": "So the plan is simple: we wait here.",
      "translated_text": "Esperamos aquí.",
      "mode": "conciso",
      "speed": 1.25,
      "outcome": "pronunciada",
      "reason": null,
      "timings": {
        "t_start_audio": 38.5,
        "t_end_audio": 40.0,
        "unit_ready_at": 40.9,
        "captured_at": 40.12,
        "asr_final_at": 40.9,
        "mt_started_at": 40.9,
        "mt_finished_at": 41.25,
        "tts_started_at": 41.25,
        "tts_first_audio_at": 41.8,
        "tts_finished_at": 42.3,
        "play_started_at": 44.0,
        "play_finished_at": 45.0
      },
      "sentence_delay_s": 4.0
    },
    {
      "unit_id": 5,
      "source_text": "We should call the whole thing off.",
      "translated_text": "Mejor cancelarlo todo.",
      "mode": "conciso",
      "speed": 1.25,
      "outcome": "pronunciada",
      "reason": null,
      "timings": {
        "t_start_audio": 48.5,
        "t_end_audio": 50.0,
        "unit_ready_at": 51.0,
        "captured_at": 50.14,
        "asr_final_at": 51.0,
        "mt_started_at": 51.0,
        "mt_finished_at": 51.45,
        "tts_started_at": 51.45,
        "tts_first_audio_at": 52.05,
        "tts_finished_at": 52.55,
        "play_started_at": 56.0,
        "play_finished_at": 57.0
      },
      "sentence_delay_s": 6.0
    },
    {
      "unit_id": 6,
      "source_text": "Never mind.",
      "translated_text": null,
      "mode": "normal",
      "speed": 1.0,
      "outcome": "descartada",
      "reason": "retraso excesivo",
      "timings": {
        "t_start_audio": 58.5,
        "t_end_audio": 60.0,
        "unit_ready_at": 69.0,
        "captured_at": 60.1,
        "asr_final_at": 69.0,
        "mt_started_at": null,
        "mt_finished_at": null,
        "tts_started_at": null,
        "tts_first_audio_at": null,
        "tts_finished_at": null,
        "play_started_at": null,
        "play_finished_at": null
      },
      "sentence_delay_s": null
    },
    {
      "unit_id": 7,
      "source_text": "Uh-huh.",
      "translated_text": null,
      "mode": "normal",
      "speed": 1.0,
      "outcome": "rechazada",
      "reason": "traducción rechazada por los filtros de salida",
      "timings": {
        "t_start_audio": 68.5,
        "t_end_audio": 70.0,
        "unit_ready_at": 70.7,
        "captured_at": 70.1,
        "asr_final_at": 70.7,
        "mt_started_at": 70.7,
        "mt_finished_at": 75.7,
        "tts_started_at": null,
        "tts_first_audio_at": null,
        "tts_finished_at": null,
        "play_started_at": null,
        "play_finished_at": null
      },
      "sentence_delay_s": null
    },
    {
      "unit_id": 8,
      "source_text": "See you tomorrow, everyone.",
      "translated_text": "Hasta mañana.",
      "mode": "conciso",
      "speed": 1.25,
      "outcome": "fallida",
      "reason": "voz: el servicio no responde",
      "timings": {
        "t_start_audio": 78.5,
        "t_end_audio": 80.0,
        "unit_ready_at": 80.7,
        "captured_at": 80.1,
        "asr_final_at": 80.7,
        "mt_started_at": 80.7,
        "mt_finished_at": 80.9,
        "tts_started_at": 80.9,
        "tts_first_audio_at": null,
        "tts_finished_at": null,
        "play_started_at": null,
        "play_finished_at": null
      },
      "sentence_delay_s": null
    }
  ]
}
"""


class TestReferenceSession:
    def test_the_json_is_exactly_the_reference(self) -> None:
        assert report_to_json(reference_report()) == REFERENCE_JSON

    def test_the_reference_has_the_shape_of_the_contract(self) -> None:
        report = json.loads(REFERENCE_JSON)
        assert list(report) == TOP_LEVEL_KEYS
        assert list(report["summary"]) == SUMMARY_KEYS
        assert list(report["settings"]) == SETTINGS_KEYS
        assert list(report["diagnostics"]) == DIAGNOSTICS_KEYS
        assert all(list(entry) == UTTERANCE_KEYS for entry in report["utterances"])
        assert all(list(entry["timings"]) == TIMINGS_KEYS for entry in report["utterances"])

    def test_the_reference_counts_add_up(self) -> None:
        summary = json.loads(REFERENCE_JSON)["summary"]
        assert (
            summary["spoken"] + summary["dropped"] + summary["rejected"] + summary["failed"]
            == (summary["utterances"])
        )
