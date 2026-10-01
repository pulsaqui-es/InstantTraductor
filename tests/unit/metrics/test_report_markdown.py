"""Tests de `informe.md`, de los avisos del informe y de su escritura en disco (T030).

El Markdown es un «resumen legible del JSON» (`contracts/informe.md`): tabla de percentiles, recuentos, las
10 frases más lentas y avisos (reinicios, descartes, eco...). Se genera solo a partir del diccionario del
informe, con coma decimal y todo el texto en español.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from instanttraductor.config import Settings
from instanttraductor.contracts import Outcome
from instanttraductor.metrics.recorder import MetricsRecorder
from instanttraductor.metrics.report import (
    REPORT_JSON_NAME,
    REPORT_MD_NAME,
    build_report,
    report_to_json,
    report_to_markdown,
    report_warnings,
    write_report,
)
from tests.unit.metrics.test_report import (
    CONCISE,
    SPOKEN_STAGES,
    STARTED_AT,
    build,
    five_spoken,
    lost,
    recorder_with,
    reference_report,
    spoken,
)

HEADINGS = [
    "# Informe de la sesión 20261001-213000",
    "## Retardo por etapas (segundos)",
    "## Recuentos",
    "## Las 10 frases más lentas",
    "## Avisos",
    "## Diagnóstico",
]


def markdown_of(recorder: MetricsRecorder | None = None, **overrides: Any) -> str:
    return report_to_markdown(build(recorder, **overrides))


def table_rows(markdown: str, heading: str) -> list[list[str]]:
    """Filas de datos (sin la cabecera ni la línea de guiones) de la tabla que sigue a `heading`."""
    section = markdown.split(heading + "\n", 1)[1].split("\n## ", 1)[0]
    lines = [line for line in section.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip()[1:-1])] for line in lines[2:]]


def many_spoken(count: int) -> list:
    """`count` frases pronunciadas cuyo retardo crece con el número de la frase."""
    return [spoken(n, 10.0 * n, (0.1, 0.5, 0.2, 0.3, 0.1 * n)) for n in range(1, count + 1)]


# --------------------------------------------------------------------------------------------------
# Estructura y cifras
# --------------------------------------------------------------------------------------------------


class TestMarkdown:
    def test_has_the_sections_in_order(self) -> None:
        text = markdown_of(recorder_with(*five_spoken()))
        assert re.findall(r"^#{1,2} .+$", text, re.MULTILINE) == HEADINGS

    def test_is_a_text_that_ends_with_one_newline(self) -> None:
        text = markdown_of(recorder_with(*five_spoken()))
        assert text.endswith("\n") and not text.endswith("\n\n")

    def test_the_header_shows_the_session_data(self) -> None:
        recorder = recorder_with(*five_spoken())
        recorder.set_mt_model("hy-mt2-7b-q4")
        text = markdown_of(recorder, duration_s=1800.0)
        assert "- **Modo:** directo" in text
        assert "- **Inicio:** 2026-10-01T21:30:00+02:00" in text
        assert "- **Duración:** 30 min 00 s" in text
        assert "- **Modelo de traducción:** hy-mt2-7b-q4" in text
        assert "Fichero de entrada" not in text

    def test_the_file_mode_shows_the_input_file(self) -> None:
        text = markdown_of(mode="archivo", input_file="C:/videos/serie.mkv")
        assert "- **Modo:** archivo" in text
        assert "- **Fichero de entrada:** C:/videos/serie.mkv" in text

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [(0.0, "0,0 s"), (12.34, "12,3 s"), (59.9, "59,9 s"), (60.0, "1 min 00 s"), (125.0, "2 min 05 s")],
    )
    def test_the_duration_is_written_for_people(self, seconds: float, expected: str) -> None:
        assert f"- **Duración:** {expected}" in markdown_of(duration_s=seconds)

    def test_the_percentile_table_has_the_figures_with_decimal_commas(self) -> None:
        rows = table_rows(markdown_of(recorder_with(*five_spoken())), "## Retardo por etapas (segundos)")
        assert rows == [
            ["Retardo de frase", "3,000", "5,600", "6,000"],
            ["Captura", "0,120", "0,136", "-"],
            ["Reconocimiento", "0,800", "0,980", "-"],
            ["Traducción", "0,250", "0,430", "-"],
            ["Voz (primer audio)", "0,450", "0,590", "-"],
            ["Reproducción (hasta empezar a sonar)", "1,500", "3,600", "-"],
        ]

    def test_an_empty_percentile_is_a_dash(self) -> None:
        rows = table_rows(markdown_of(), "## Retardo por etapas (segundos)")
        assert all(cells[1:] == ["-", "-", "-"] for cells in rows)

    def test_the_counts_table(self) -> None:
        records = [
            spoken(1, 10.0, SPOKEN_STAGES[0]),
            spoken(2, 20.0, SPOKEN_STAGES[1], mode=CONCISE, speed=1.2),
            lost(3, Outcome.DROPPED, "retraso excesivo", 30.0),
            lost(4, Outcome.REJECTED, "filtros", 40.0),
            lost(5, Outcome.FAILED, "voz", 50.0),
        ]
        rows = table_rows(markdown_of(recorder_with(*records)), "## Recuentos")
        assert rows == [
            ["Total", "5"],
            ["Pronunciadas", "2"],
            ["Resumidas", "1"],
            ["Aceleradas", "1"],
            ["Descartadas", "1"],
            ["Rechazadas", "1"],
            ["Fallidas", "1"],
        ]

    def test_the_diagnostics_table(self) -> None:
        recorder = recorder_with(*five_spoken())
        recorder.set_startup_s(34.2)
        recorder.set_mt_model("hy-mt2-7b-q4")
        recorder.set_underruns(2)
        recorder.count_echo_event()
        recorder.count_component_restart()
        for t, lag in ((100.0, 2.0), (100.5, 9.0), (101.0, 9.5), (101.5, 3.0)):
            recorder.add_lag_sample(t, lag)
        recorder.sample_memory(300.0)  # sondas reales: solo se comprueba la forma
        rows = {cells[0]: cells[1] for cells in table_rows(markdown_of(recorder), "## Diagnóstico")}
        assert rows["Arranque"] == "34,2 s"
        assert rows["Retraso máximo"] == "9,5 s"
        assert rows["Racha más larga sobre el umbral de descarte"] == "1,0 s"
        assert rows["Ecos detectados"] == "1"
        assert rows["Reinicios de componentes"] == "1"
        assert rows["Cortes de audio (underruns)"] == "2"
        assert rows["Modelo de traducción"] == "hy-mt2-7b-q4"
        assert re.fullmatch(r"\d+ / \d+ MB", rows["Memoria del núcleo (minuto 5 / final)"])

    def test_what_was_not_measured_is_a_dash(self) -> None:
        rows = {cells[0]: cells[1] for cells in table_rows(markdown_of(), "## Diagnóstico")}
        assert rows["Arranque"] == "-"
        assert rows["Memoria del núcleo (minuto 5 / final)"] == "- / -"
        assert rows["Modelo de traducción"] == "-"

    def test_it_is_built_from_the_json_alone(self) -> None:
        report = build(recorder_with(*five_spoken()))
        assert report_to_markdown(json.loads(report_to_json(report))) == report_to_markdown(report)

    def test_no_table_number_uses_a_decimal_point(self) -> None:
        text = markdown_of(recorder_with(*five_spoken()))
        tables = "\n".join(line for line in text.splitlines() if line.startswith("|"))
        assert not re.search(r"\d\.\d", tables)


class TestSlowest:
    def test_lists_at_most_ten_sorted_from_the_slowest(self) -> None:
        rows = table_rows(markdown_of(recorder_with(*many_spoken(12))), "## Las 10 frases más lentas")
        assert len(rows) == 10
        assert [row[0] for row in rows] == [str(n) for n in range(1, 11)]  # posición
        assert [row[1] for row in rows] == [str(n) for n in range(12, 2, -1)]  # frase: de la 12 a la 3
        delays = [float(row[2].replace(",", ".")) for row in rows]
        assert delays == sorted(delays, reverse=True)

    def test_lists_fewer_when_fewer_were_spoken(self) -> None:
        rows = table_rows(markdown_of(recorder_with(*five_spoken())), "## Las 10 frases más lentas")
        assert [row[1] for row in rows] == ["5", "4", "3", "2", "1"]

    def test_ties_keep_the_unit_order(self) -> None:
        records = [spoken(n, 10.0 * n, SPOKEN_STAGES[0]) for n in (3, 1, 2)]  # los tres con el mismo retardo
        rows = table_rows(markdown_of(recorder_with(*records)), "## Las 10 frases más lentas")
        assert [row[1] for row in rows] == ["1", "2", "3"]

    def test_only_spoken_units_are_listed(self) -> None:
        records = [*five_spoken(), lost(6, Outcome.DROPPED, "retraso excesivo", 60.0)]
        rows = table_rows(markdown_of(recorder_with(*records)), "## Las 10 frases más lentas")
        assert "6" not in [row[1] for row in rows]

    def test_each_row_shows_the_mode_the_speed_and_the_texts(self) -> None:
        record = spoken(
            7, 10.0, SPOKEN_STAGES[4], source="Where were you?", translated="¿Dónde estabas?",
            mode=CONCISE, speed=1.25,
        )  # fmt: skip
        (row,) = table_rows(markdown_of(recorder_with(record)), "## Las 10 frases más lentas")
        assert row == ["1", "7", "6,000", "resumida", "1,25×", "Where were you?", "¿Dónde estabas?"]

    def test_a_normal_unit_says_normal(self) -> None:
        (row,) = table_rows(
            markdown_of(recorder_with(spoken(1, 10.0, SPOKEN_STAGES[0]))), "## Las 10 frases más lentas"
        )
        assert row[3:5] == ["normal", "1,00×"]

    def test_cells_escape_the_pipes_and_flatten_new_lines(self) -> None:
        record = spoken(1, 10.0, SPOKEN_STAGES[0], source="a | b\nc", translated="x | y")
        (row,) = table_rows(markdown_of(recorder_with(record)), "## Las 10 frases más lentas")
        assert row[5] == "a \\| b c" and row[6] == "x \\| y"

    def test_long_texts_are_cut_with_an_ellipsis(self) -> None:
        record = spoken(1, 10.0, SPOKEN_STAGES[0], source="word " * 60)
        (row,) = table_rows(markdown_of(recorder_with(record)), "## Las 10 frases más lentas")
        assert row[5].endswith("…") and len(row[5]) <= 80

    def test_says_so_when_nothing_was_spoken(self) -> None:
        text = markdown_of(recorder_with(lost(1, Outcome.DROPPED, "parada", 10.0)))
        assert "Ninguna frase llegó a pronunciarse." in text


# --------------------------------------------------------------------------------------------------
# Avisos
# --------------------------------------------------------------------------------------------------


def warnings_of(recorder: MetricsRecorder | None = None, **overrides: Any) -> list[str]:
    return report_warnings(build(recorder, **overrides))


def with_streak(recorder: MetricsRecorder, seconds: float) -> None:
    """Una racha por encima del umbral de descarte que dura `seconds` s (muestras cada 0,5 s)."""
    for index in range(round(seconds / 0.5)):
        recorder.add_lag_sample(100.0 + 0.5 * index, 9.0)
    recorder.add_lag_sample(100.0 + seconds, 1.0)


class TestWarnings:
    def test_a_clean_session_has_no_warnings(self) -> None:
        recorder = recorder_with(*five_spoken())
        assert warnings_of(recorder) == []
        assert "Sin avisos." in markdown_of(recorder)

    def test_no_speech(self) -> None:
        found = warnings_of()
        assert len(found) == 1 and "no se detectó habla" in found[0]
        assert "no se detectó habla" in markdown_of()

    def test_dropped_units_are_counted_with_their_reasons(self) -> None:
        records = [
            *five_spoken(),
            lost(6, Outcome.DROPPED, "retraso excesivo", 60.0),
            lost(7, Outcome.DROPPED, "retraso excesivo", 70.0),
            lost(8, Outcome.DROPPED, "parada", 80.0),
        ]
        (message,) = warnings_of(recorder_with(*records))
        assert message.startswith("3 frases descartadas")
        assert "2 por «retraso excesivo»" in message and "1 por «parada»" in message

    def test_one_dropped_unit_is_singular(self) -> None:
        records = [*five_spoken(), lost(6, Outcome.DROPPED, "retraso excesivo", 60.0)]
        (message,) = warnings_of(recorder_with(*records))
        assert message.startswith("1 frase descartada") and "«retraso excesivo»" in message

    def test_rejected_and_failed_units(self) -> None:
        records = [
            *five_spoken(),
            lost(6, Outcome.REJECTED, "filtros", 60.0),
            lost(7, Outcome.REJECTED, "filtros", 70.0),
            lost(8, Outcome.FAILED, "voz: el servicio no responde", 80.0),
        ]
        found = warnings_of(recorder_with(*records))
        assert any(w.startswith("2 traducciones rechazadas") and "no se pronunciaron" in w for w in found)
        assert any(w.startswith("1 frase fallida") and "voz: el servicio no responde" in w for w in found)

    def test_restarts_echo_and_underruns(self) -> None:
        recorder = recorder_with(*five_spoken())
        recorder.count_component_restart(2)
        recorder.count_echo_event()
        recorder.set_underruns(3)
        found = warnings_of(recorder)
        assert any("Se reiniciaron 2 componentes" in w for w in found)
        assert any("Se detectó eco 1 vez" in w and "SC-002" in w for w in found)
        assert any("3 cortes de audio" in w for w in found)

    def test_a_single_restart_is_singular(self) -> None:
        recorder = recorder_with(*five_spoken())
        recorder.count_component_restart()
        assert any("Se reinició 1 componente" in w for w in warnings_of(recorder))

    def test_a_lag_streak_over_ten_seconds(self) -> None:
        recorder = recorder_with(*five_spoken())
        with_streak(recorder, 12.0)
        found = warnings_of(recorder, duration_s=112.5)
        assert any("12,0 s seguidos" in w and "SC-005" in w for w in found)

    def test_a_lag_streak_of_exactly_ten_seconds_is_fine(self) -> None:
        recorder = recorder_with(*five_spoken())
        with_streak(recorder, 10.0)
        assert warnings_of(recorder, duration_s=110.5) == []

    @pytest.mark.parametrize(
        ("minute_five", "end", "warns"),
        [(1000.0, 1101.0, True), (1000.0, 1100.0, False), (1000.0, 900.0, False)],
    )
    def test_memory_growth_of_the_core_over_ten_percent(
        self, minute_five: float, end: float, warns: bool
    ) -> None:
        found = memory_warnings(core=(minute_five, end), children=(100.0, 100.0))
        assert any("memoria del núcleo creció" in w and "SC-005" in w for w in found) is warns

    @pytest.mark.parametrize(
        ("minute_five", "end", "warns"), [(8000.0, 8801.0, True), (8000.0, 8800.0, False)]
    )
    def test_memory_growth_of_the_children_over_ten_percent(
        self, minute_five: float, end: float, warns: bool
    ) -> None:
        found = memory_warnings(core=(1000.0, 1000.0), children=(minute_five, end))
        assert any("memoria de los procesos hijos creció" in w for w in found) is warns

    def test_no_memory_warning_without_minute_five(self) -> None:
        assert warnings_of(recorder_with(*five_spoken())) == []

    def test_the_reserve_translation_model_is_flagged(self) -> None:
        recorder = recorder_with(*five_spoken())
        recorder.set_mt_model("hy-mt2-1.8b-q8")
        found = warnings_of(recorder)
        assert any("reserva" in w and "hy-mt2-1.8b-q8" in w and "resumir" in w for w in found)

    def test_the_main_translation_model_is_not_flagged(self) -> None:
        recorder = recorder_with(*five_spoken())
        recorder.set_mt_model("hy-mt2-7b-q4")
        assert warnings_of(recorder) == []

    def test_the_markdown_lists_every_warning(self) -> None:
        recorder = recorder_with(*five_spoken(), lost(6, Outcome.DROPPED, "retraso excesivo", 60.0))
        recorder.count_echo_event()
        text = markdown_of(recorder)
        section = text.split("## Avisos\n", 1)[1].split("\n## ", 1)[0]
        bullets = [line for line in section.splitlines() if line.startswith("- ")]
        assert bullets == [f"- {w}" for w in warnings_of(recorder)] and len(bullets) == 2
        assert "Sin avisos" not in text


def memory_warnings(*, core: tuple[float, float], children: tuple[float, float]) -> list[str]:
    """Avisos de una sesión de 30 min cuya memoria vale `core` y `children` en el minuto 5 y al final."""
    values = {"core": core[0], "children": children[0]}
    recorder = MetricsRecorder(
        core_rss_mb=lambda: values["core"],
        children_rss_mb=lambda pids: values["children"],
        memory_interval_s=1.0,
    )
    for record in five_spoken():
        recorder.add_record(record)
    recorder.sample_memory(300.0)
    values["core"], values["children"] = core[1], children[1]
    recorder.sample_memory(1800.0)
    return report_warnings(build(recorder, duration_s=1800.0))


# --------------------------------------------------------------------------------------------------
# Escritura en disco
# --------------------------------------------------------------------------------------------------


class TestWriteReport:
    def test_writes_the_json_and_the_markdown_into_the_folder(self, tmp_path: Path) -> None:
        report = build(recorder_with(*five_spoken()))
        json_path, md_path = write_report(report, tmp_path / "informes" / "20261001-213000")
        assert json_path.name == REPORT_JSON_NAME == "informe.json"
        assert md_path.name == REPORT_MD_NAME == "informe.md"
        assert json_path.read_text(encoding="utf-8") == report_to_json(report)
        assert md_path.read_text(encoding="utf-8") == report_to_markdown(report)

    def test_leaves_no_temporary_files_and_uses_lf(self, tmp_path: Path) -> None:
        report = build(recorder_with(*five_spoken()))
        write_report(report, tmp_path)
        assert sorted(path.name for path in tmp_path.iterdir()) == ["informe.json", "informe.md"]
        assert b"\r\n" not in (tmp_path / "informe.json").read_bytes()
        assert b"\r\n" not in (tmp_path / "informe.md").read_bytes()

    def test_overwrites_a_previous_report(self, tmp_path: Path) -> None:
        write_report(build(recorder_with(*five_spoken())), tmp_path)
        report = build()
        write_report(report, tmp_path)
        assert (
            json.loads((tmp_path / "informe.json").read_text(encoding="utf-8"))["summary"]["utterances"] == 0
        )

    def test_build_report_is_pure(self) -> None:
        recorder = recorder_with(*five_spoken())
        settings = Settings(voice="es-f-01")
        first = build_report(
            recorder, mode="directo", started_at=STARTED_AT, duration_s=60.0, settings=settings
        )
        second = build_report(
            recorder, mode="directo", started_at=STARTED_AT, duration_s=60.0, settings=settings
        )
        assert first == second


# --------------------------------------------------------------------------------------------------
# Sesión sintética de referencia
# --------------------------------------------------------------------------------------------------


#: `informe.md` de `reference_report()`.
REFERENCE_MARKDOWN = """\
# Informe de la sesión 20261001-213000

- **Modo:** directo
- **Inicio:** 2026-10-01T21:30:00+02:00
- **Duración:** 30 min 00 s
- **Modelo de traducción:** hy-mt2-7b-q4

## Retardo por etapas (segundos)

| Medida | p50 | p95 | máx |
| --- | ---: | ---: | ---: |
| Retardo de frase | 3,000 | 5,600 | 6,000 |
| Captura | 0,120 | 0,136 | - |
| Reconocimiento | 0,800 | 0,980 | - |
| Traducción | 0,250 | 0,430 | - |
| Voz (primer audio) | 0,450 | 0,590 | - |
| Reproducción (hasta empezar a sonar) | 1,500 | 3,600 | - |

## Recuentos

| Frases | Número |
| --- | ---: |
| Total | 8 |
| Pronunciadas | 5 |
| Resumidas | 2 |
| Aceleradas | 3 |
| Descartadas | 1 |
| Rechazadas | 1 |
| Fallidas | 1 |

## Las 10 frases más lentas

| # | Frase | Retardo (s) | Modo | Velocidad | Original | Traducción |
| ---: | ---: | ---: | --- | ---: | --- | --- |
| 1 | 5 | 6,000 | resumida | 1,25× | We should call the whole thing off. | Mejor cancelarlo todo. |
| 2 | 4 | 4,000 | resumida | 1,25× | So the plan is simple: we wait here. | Esperamos aquí. |
| 3 | 3 | 3,000 | normal | 1,05× | That is not what he told me. | Eso no es lo que él me dijo. |
| 4 | 2 | 2,000 | normal | 1,00× | I was at the office until late. | Estuve en la oficina hasta tarde. |
| 5 | 1 | 1,500 | normal | 1,00× | Where were you last night? | ¿Dónde estuviste anoche? |

## Avisos

- 1 frase descartada por «retraso excesivo».
- 1 traducción rechazada por los filtros de salida: no se pronunció.
- 1 frase fallida (voz: el servicio no responde).
- Se reinició 1 componente.
- Se detectó eco 1 vez: la voz en español volvió a la captura (SC-002 exige 0).
- Hubo 2 cortes de audio en la reproducción (underruns).

## Diagnóstico

| Medida | Valor |
| --- | ---: |
| Arranque | 34,2 s |
| Memoria del núcleo (minuto 5 / final) | 812 / 830 MB |
| Memoria de los hijos (minuto 5 / final) | 7900 / 8051 MB |
| Retraso máximo | 8,6 s |
| Racha más larga sobre el umbral de descarte | 1,5 s |
| Ecos detectados | 1 |
| Reinicios de componentes | 1 |
| Cortes de audio (underruns) | 2 |
| Modelo de traducción | hy-mt2-7b-q4 |
"""


class TestReferenceSession:
    def test_the_markdown_is_exactly_the_reference(self) -> None:
        assert report_to_markdown(reference_report()) == REFERENCE_MARKDOWN
