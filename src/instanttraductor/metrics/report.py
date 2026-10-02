"""Informe de la sesión: JSON con el esquema exacto de `contracts/informe.md` y su resumen en Markdown (T030).

`build_report(recorder, ...)` convierte lo que guarda el `MetricsRecorder` en el diccionario del informe,
con las claves en el orden del contrato; `report_to_json` lo escribe como texto y `report_to_markdown` lo
resume para personas. El Markdown se genera **solo a partir del diccionario**, así que también se puede
regenerar desde un `informe.json` guardado.

Criterios
---------
- **Tiempos:** segundos con 3 decimales (`round`). Un valor que no es finito (NaN, infinito) se guarda como
  `null`: el JSON nunca lleva `NaN`.
- **Percentiles** (p50 y p95): interpolación lineal entre los valores ordenados (la mediana de un número par
  de valores es la media de los dos centrales), **solo sobre las frases pronunciadas**. Con ninguna frase
  pronunciada valen `null`.
- **Etapas** (FR-023), cada una solo sobre las frases a las que no les falta ninguno de sus dos instantes:
  `capture` = `captured_at − t_end_audio`, `asr` = `asr_final_at − t_end_audio`, `mt` = `mt_finished_at −
  mt_started_at`, `tts_first` = `tts_first_audio_at − tts_started_at` y `playback` = `play_started_at −
  tts_first_audio_at`.
- **Recuentos:** `utterances` son todas las frases; `spoken`, `dropped`, `rejected` y `failed` la suman.
  `concise` y `accelerated` son subconjuntos de las **pronunciadas**: lo que la persona realmente oyó resumido
  o acelerado (velocidad por encima de 1,000 una vez redondeada).
- **Ajustes:** solo los siete del contrato (`voz`, `volumen_voz`, los tres umbrales, `velocidad_max` y
  `max_habla_sin_traducir_s`), con las claves en español del TOML.
- El bloque `diagnostics` es el del `MetricsRecorder`, con la racha de retraso medida contra el
  `umbral_descartar_s` de los ajustes que recoge el propio informe.

El Markdown usa coma decimal, como la interfaz. Cuando no hay frases dice «no se detectó habla» (modo
archivo con un fichero sin voz, o directo en silencio).
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Literal

import numpy as np

from instanttraductor.config import TOML_KEYS, Settings
from instanttraductor.contracts import Outcome, StageTimings, TranslationMode, UtteranceRecord
from instanttraductor.metrics.recorder import MetricsRecorder
from instanttraductor.pipeline.scheduler import LANGUAGE_REJECTED_REASON

__all__ = [
    "MAX_LAG_STREAK_S",
    "MAX_MEMORY_GROWTH",
    "REPORT_JSON_NAME",
    "REPORT_MD_NAME",
    "SCHEMA_VERSION",
    "SLOWEST_COUNT",
    "build_report",
    "report_to_json",
    "report_to_markdown",
    "report_warnings",
    "write_report",
]

SCHEMA_VERSION: Final = 2  # 2: spec 002 (idioma, escucha, etapa lid)
REPORT_JSON_NAME: Final = "informe.json"
REPORT_MD_NAME: Final = "informe.md"
SLOWEST_COUNT: Final = 10  # frases en la tabla de «las más lentas»
MAX_LAG_STREAK_S: Final = 10.0  # SC-005: el retraso no pasa del umbral de descarte más de 10 s seguidos
MAX_MEMORY_GROWTH: Final = 0.10  # SC-005: la memoria final no supera en más de un 10 % la del minuto 5
_TEXT_WIDTH: Final = 80  # ancho máximo de un texto en una celda del Markdown
_RESERVE_MODEL_MARKER: Final = "1.8b"  # el modelo de traducción de reserva (ADR-0011) lleva esto en su id

Mode = Literal["directo", "archivo"]

#: Los doce tiempos de `StageTimings`, en el orden de `contracts/informe.md`.
_TIMING_FIELDS: Final = (
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
    "lid_done_at",
)
#: Los ajustes que van al informe (atributo de `Settings`), en el orden del contrato.
_SETTINGS_FIELDS: Final = (
    "voice",
    "voice_volume",
    "accelerate_after_s",
    "concise_after_s",
    "drop_after_s",
    "max_speed",
    "max_untranslated_s",
    "source_language",
)


def _seconds_between(later: float | None, earlier: float | None) -> float | None:
    return None if later is None or earlier is None else later - earlier


#: Etapa → cómo se mide sobre los tiempos de una frase (FR-023).
_STAGES: Final[dict[str, Callable[[StageTimings], float | None]]] = {
    "capture": lambda t: _seconds_between(t.captured_at, t.t_end_audio),
    "asr": lambda t: _seconds_between(t.asr_final_at, t.t_end_audio),
    "mt": lambda t: _seconds_between(t.mt_finished_at, t.mt_started_at),
    "tts_first": lambda t: _seconds_between(t.tts_first_audio_at, t.tts_started_at),
    "playback": lambda t: _seconds_between(t.play_started_at, t.tts_first_audio_at),
    # Spec 002: de la unidad lista hasta el fin de la verificación de idioma (espera en cola incluida).
    "lid": lambda t: _seconds_between(t.lid_done_at, t.unit_ready_at),
}


# --- construcción del informe ----------------------------------------------------------------------


def _rounded(value: float | None) -> float | None:
    """Segundos con 3 decimales; `None` si falta o no es finito."""
    if value is None or not math.isfinite(value):
        return None
    return round(value, 3)


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    return _rounded(float(np.percentile(values, q)))


def _component_entry(component: Any) -> dict[str, str]:
    """`component_id`, `version` y `license` de un `Component` del manifiesto o de un diccionario."""

    def field(key: str) -> str:
        return component[key] if isinstance(component, Mapping) else getattr(component, key)

    return {key: field(key) for key in ("component_id", "version", "license")}


def _utterance_entry(record: UtteranceRecord) -> dict[str, Any]:
    timings = record.timings
    return {
        "unit_id": record.unit_id,
        "source_text": record.source_text,
        "translated_text": record.translated_text,
        "mode": record.mode.value,
        "speed": _rounded(record.speed),
        "outcome": record.outcome.value,
        "reason": record.reason,
        "timings": {name: _rounded(getattr(timings, name)) for name in _TIMING_FIELDS},
        "sentence_delay_s": _rounded(timings.sentence_delay),
    }


def _summary(records: Sequence[UtteranceRecord]) -> dict[str, Any]:
    spoken = [r for r in records if r.outcome is Outcome.SPOKEN]
    delays = [d for r in spoken if (d := r.timings.sentence_delay) is not None]
    stages: dict[str, dict[str, float | None]] = {}
    for name, measure in _STAGES.items():
        values = [v for r in spoken if (v := measure(r.timings)) is not None]
        stages[name] = {"p50": _percentile(values, 50), "p95": _percentile(values, 95)}
    return {
        "utterances": len(records),
        "spoken": len(spoken),
        "concise": sum(r.mode is TranslationMode.CONCISE for r in spoken),
        "accelerated": sum(round(r.speed, 3) > 1.0 for r in spoken),
        "dropped": sum(r.outcome is Outcome.DROPPED for r in records),
        "rejected": sum(r.outcome is Outcome.REJECTED for r in records),
        "failed": sum(r.outcome is Outcome.FAILED for r in records),
        "rejected_language": sum(
            r.outcome is Outcome.REJECTED and r.reason == LANGUAGE_REJECTED_REASON for r in records
        ),
        "sentence_delay_s": {
            "p50": _percentile(delays, 50),
            "p95": _percentile(delays, 95),
            "max": _rounded(max(delays)) if delays else None,
        },
        "stages_s": stages,
    }


def build_report(
    recorder: MetricsRecorder,
    *,
    mode: Mode,
    started_at: datetime,
    duration_s: float,
    settings: Settings,
    session_id: str | None = None,
    input_file: str | os.PathLike[str] | None = None,
    components: Iterable[Any] = (),
    capture: str | None = None,
) -> dict[str, Any]:
    """El informe de la sesión como diccionario, con el esquema y el orden de `contracts/informe.md`.

    - `mode`: `"directo"` o `"archivo"` (`ValueError` si es otro).
    - `started_at`: inicio de la sesión; si no lleva zona horaria se toma como hora local. `session_id` por
      defecto sale de él (`AAAAMMDD-HHMMSS`).
    - `duration_s`: duración de la sesión en el reloj de sesión (cierra una racha de retraso abierta).
    - `settings`: los ajustes con los que corrió la sesión.
    - `input_file`: solo en modo archivo.
    - `capture`: qué se escuchó en directo (spec 002): «todo el PC» o el nombre de la app; None en archivo.
    - `components`: los componentes usados, como `Component` del manifiesto o como diccionarios con
      `component_id`, `version` y `license`.
    """
    if mode not in ("directo", "archivo"):
        raise ValueError(f"El modo del informe debe ser «directo» o «archivo» (recibido: {mode!r}).")
    if started_at.tzinfo is None:
        started_at = started_at.astimezone()  # hora local, con su desfase
    duration = max(0.0, duration_s)
    records = recorder.records
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id if session_id is not None else started_at.strftime("%Y%m%d-%H%M%S"),
        "mode": mode,
        "input_file": None if input_file is None else os.fspath(input_file),
        "source_language": str(settings.source_language),
        "capture": capture,
        "started_at": started_at.isoformat(timespec="seconds"),
        "duration_s": _rounded(duration),
        "settings": {TOML_KEYS[name]: _setting_value(getattr(settings, name)) for name in _SETTINGS_FIELDS},
        "components": [_component_entry(component) for component in components],
        "summary": _summary(records),
        "diagnostics": recorder.diagnostics(end_t=duration, drop_after_s=settings.drop_after_s),
        "utterances": [_utterance_entry(record) for record in records],
    }


def _setting_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return str(value)
    return round(value, 3) if isinstance(value, float) else value


def report_to_json(report: Mapping[str, Any]) -> str:
    """El informe como texto JSON (UTF-8, sangría de 2, claves en su orden y un salto de línea final)."""
    return json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


# --- avisos y Markdown -----------------------------------------------------------------------------


def _section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    return value if isinstance(value, Mapping) else {}


def _count(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def _number(value: float | None, decimals: int) -> str:
    """Número con coma decimal; un guion si falta."""
    return "-" if value is None else f"{value:.{decimals}f}".replace(".", ",")


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _by_reason(utterances: Iterable[Mapping[str, Any]], outcome: Outcome) -> list[tuple[str, int]]:
    """Cuántas frases con este resultado hay por motivo, de más a menos frecuentes."""
    counter = Counter(
        str(entry.get("reason") or "sin motivo")
        for entry in utterances
        if entry.get("outcome") == outcome.value
    )
    return counter.most_common()


def _grew_too_much(minute_five: object, end: object) -> bool:
    if not (isinstance(minute_five, int | float) and isinstance(end, int | float)):
        return False
    return minute_five > 0 and end > minute_five * (1 + MAX_MEMORY_GROWTH)


def report_warnings(report: Mapping[str, Any]) -> list[str]:
    """Los avisos de la sesión, en español: lo que la persona debería saber de cómo fue.

    Sin habla, descartes (con su motivo), rechazadas, fallidas, reinicios, eco, cortes de audio, una racha
    de retraso por encima de lo que admite SC-005, crecimiento de la memoria y modelo de reserva.
    """
    summary = _section(report, "summary")
    diagnostics = _section(report, "diagnostics")
    utterances = [u for u in report.get("utterances", ()) if isinstance(u, Mapping)]
    warnings: list[str] = []

    if _count(summary, "utterances") == 0:
        warnings.append("Sin habla: no se detectó habla en el audio de la sesión.")
    if n := _count(summary, "dropped"):
        label = _plural(n, "frase descartada", "frases descartadas")
        reasons = _by_reason(utterances, Outcome.DROPPED)
        if len(reasons) == 1:
            warnings.append(f"{label} por «{reasons[0][0]}».")
        elif reasons:
            warnings.append(
                f"{label}: " + ", ".join(f"{count} por «{reason}»" for reason, count in reasons) + "."
            )
        else:
            warnings.append(f"{label}.")
    language = _count(summary, "rejected_language")
    if language:
        warnings.append(
            f"{_plural(language, 'frase en otro idioma ignorada', 'frases en otro idioma ignoradas')} "
            "(no eran del idioma de origen elegido)."
        )
    if n := _count(summary, "rejected") - language:
        warnings.append(
            f"{_plural(n, 'traducción rechazada', 'traducciones rechazadas')} por los filtros de salida: "
            + ("no se pronunció." if n == 1 else "no se pronunciaron.")
        )
    if n := _count(summary, "failed"):
        label = _plural(n, "frase fallida", "frases fallidas")
        detail = "; ".join(reason for reason, _ in _by_reason(utterances, Outcome.FAILED))
        warnings.append(f"{label} ({detail})." if detail else f"{label}.")
    if n := _count(diagnostics, "component_restarts"):
        verb = "reinició" if n == 1 else "reiniciaron"
        warnings.append(f"Se {verb} {_plural(n, 'componente', 'componentes')}.")
    if n := _count(diagnostics, "echo_events"):
        warnings.append(
            f"Se detectó eco {_plural(n, 'vez', 'veces')}: la voz en español volvió a la captura "
            "(SC-002 exige 0)."
        )
    if n := _count(diagnostics, "underruns"):
        warnings.append(
            f"Hubo {_plural(n, 'corte de audio', 'cortes de audio')} en la reproducción (underruns)."
        )
    streak = diagnostics.get("lag_over_drop_max_streak_s")
    if isinstance(streak, int | float) and streak > MAX_LAG_STREAK_S:
        warnings.append(
            f"El retraso estuvo {_number(streak, 1)} s seguidos por encima del umbral de descarte "
            f"(SC-005 admite hasta {_number(MAX_LAG_STREAK_S, 0)} s)."
        )
    for key, label in (("rss_mb", "del núcleo"), ("rss_children_mb", "de los procesos hijos")):
        if _grew_too_much(diagnostics.get(f"{key}_min5"), diagnostics.get(f"{key}_end")):
            start, end = diagnostics[f"{key}_min5"], diagnostics[f"{key}_end"]
            growth = (end / start - 1) * 100
            warnings.append(
                f"La memoria {label} creció un {_number(growth, 1)} % desde el minuto 5 "
                f"({start} → {end} MB; SC-005 admite hasta un {_number(MAX_MEMORY_GROWTH * 100, 0)} %)."
            )
    model = diagnostics.get("mt_model")
    if isinstance(model, str) and _RESERVE_MODEL_MARKER in model.lower():
        warnings.append(f"Se usó el modelo de traducción de reserva ({model}): no sabe resumir.")
    return warnings


def _duration_text(seconds: object) -> str:
    if not isinstance(seconds, int | float) or isinstance(seconds, bool):
        return "-"
    if seconds < 60:
        return f"{_number(float(seconds), 1)} s"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest:02d} s"


def _cell(value: object, *, limit: int | None = None) -> str:
    """Texto para una celda de tabla: una línea, con las barras escapadas y, si hace falta, recortado."""
    text = " ".join(str(value).split())
    if limit is not None and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text.replace("|", "\\|")


def _table(headers: Sequence[str], aligns: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    """Líneas de una tabla de Markdown; `aligns` son `"l"` (izquierda) o `"r"` (derecha) por columna."""
    separator = ["---:" if align == "r" else "---" for align in aligns]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(separator) + " |"]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return lines


_STAGE_LABELS: Final = (
    ("capture", "Captura"),
    ("asr", "Reconocimiento"),
    ("mt", "Traducción"),
    ("tts_first", "Voz (primer audio)"),
    ("playback", "Reproducción (hasta empezar a sonar)"),
    ("lid", "Verificación de idioma"),
)


def _slowest_rows(utterances: Iterable[Mapping[str, Any]]) -> list[list[str]]:
    spoken = [
        u
        for u in utterances
        if u.get("outcome") == Outcome.SPOKEN.value and isinstance(u.get("sentence_delay_s"), int | float)
    ]
    spoken.sort(key=lambda u: (-u["sentence_delay_s"], u.get("unit_id", 0)))
    rows = []
    for rank, entry in enumerate(spoken[:SLOWEST_COUNT], start=1):
        concise = entry.get("mode") == TranslationMode.CONCISE.value
        speed = entry.get("speed")
        rows.append(
            [
                str(rank),
                str(entry.get("unit_id", "-")),
                _number(entry["sentence_delay_s"], 3),
                "resumida" if concise else "normal",
                f"{_number(speed, 2)}×" if isinstance(speed, int | float) else "-",
                _cell(entry.get("source_text", ""), limit=_TEXT_WIDTH),
                _cell(entry.get("translated_text") or "", limit=_TEXT_WIDTH),
            ]
        )
    return rows


def report_to_markdown(report: Mapping[str, Any]) -> str:
    """El resumen legible del informe: percentiles, recuentos, las frases más lentas, avisos y diagnóstico."""
    summary = _section(report, "summary")
    diagnostics = _section(report, "diagnostics")
    delay = _section(summary, "sentence_delay_s")
    stages = _section(summary, "stages_s")
    utterances = [u for u in report.get("utterances", ()) if isinstance(u, Mapping)]

    lines = [f"# Informe de la sesión {report.get('session_id', '-')}", ""]
    lines.append(f"- **Modo:** {report.get('mode', '-')}")
    if report.get("input_file"):
        lines.append(f"- **Fichero de entrada:** {report['input_file']}")
    if report.get("source_language"):
        lines.append(f"- **Idioma de origen:** {report['source_language']}")
    if report.get("capture"):
        lines.append(f"- **Escucha:** {report['capture']}")
    lines.append(f"- **Inicio:** {report.get('started_at', '-')}")
    lines.append(f"- **Duración:** {_duration_text(report.get('duration_s'))}")
    lines.append(f"- **Modelo de traducción:** {diagnostics.get('mt_model') or '-'}")

    lines += ["", "## Retardo por etapas (segundos)", ""]
    rows = [
        ["Retardo de frase", *(_number(delay.get(key), 3) for key in ("p50", "p95", "max"))],
        *(
            [
                label,
                _number(_section(stages, key).get("p50"), 3),
                _number(_section(stages, key).get("p95"), 3),
                "-",
            ]
            for key, label in _STAGE_LABELS
        ),
    ]
    lines += _table(["Medida", "p50", "p95", "máx"], ["l", "r", "r", "r"], rows)

    lines += ["", "## Recuentos", ""]
    counts = (
        ("Total", "utterances"),
        ("Pronunciadas", "spoken"),
        ("Resumidas", "concise"),
        ("Aceleradas", "accelerated"),
        ("Descartadas", "dropped"),
        ("Rechazadas", "rejected"),
        ("Rechazadas por idioma", "rejected_language"),
        ("Fallidas", "failed"),
    )
    lines += _table(
        ["Frases", "Número"], ["l", "r"], [[label, _count(summary, key)] for label, key in counts]
    )

    lines += ["", f"## Las {SLOWEST_COUNT} frases más lentas", ""]
    slowest = _slowest_rows(utterances)
    if slowest:
        lines += _table(
            ["#", "Frase", "Retardo (s)", "Modo", "Velocidad", "Original", "Traducción"],
            ["r", "r", "r", "l", "r", "l", "l"],
            slowest,
        )
    else:
        lines.append("Ninguna frase llegó a pronunciarse.")

    lines += ["", "## Avisos", ""]
    warnings = report_warnings(report)
    lines += [f"- {warning}" for warning in warnings] if warnings else ["Sin avisos."]

    lines += ["", "## Diagnóstico", ""]
    startup = diagnostics.get("startup_s")
    lines += _table(
        ["Medida", "Valor"],
        ["l", "r"],
        [
            ["Arranque", _seconds_text(startup)],
            [
                "Memoria del núcleo (minuto 5 / final)",
                _memory_pair(diagnostics.get("rss_mb_min5"), diagnostics.get("rss_mb_end")),
            ],
            [
                "Memoria de los hijos (minuto 5 / final)",
                _memory_pair(diagnostics.get("rss_children_mb_min5"), diagnostics.get("rss_children_mb_end")),
            ],
            ["Retraso máximo", _seconds_text(diagnostics.get("max_lag_s"))],
            [
                "Racha más larga sobre el umbral de descarte",
                _seconds_text(diagnostics.get("lag_over_drop_max_streak_s")),
            ],
            ["Ecos detectados", _count(diagnostics, "echo_events")],
            ["Reinicios de componentes", _count(diagnostics, "component_restarts")],
            ["Cortes de audio (underruns)", _count(diagnostics, "underruns")],
            ["Modelo de traducción", _cell(diagnostics.get("mt_model") or "-")],
        ],
    )
    return "\n".join(lines) + "\n"


def _seconds_text(value: object) -> str:
    return f"{_number(float(value), 1)} s" if isinstance(value, int | float) else "-"


def _memory_pair(minute_five: object, end: object) -> str:
    """«812 / 830 MB»; un guion por cada valor que falta, y sin unidad si no hay ninguno."""
    if minute_five is None and end is None:
        return "- / -"
    values = [f"{int(v)}" if isinstance(v, int | float) else "-" for v in (minute_five, end)]
    return f"{values[0]} / {values[1]} MB"


# --- escritura en disco ----------------------------------------------------------------------------


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_report(report: Mapping[str, Any], directory: str | os.PathLike[str]) -> tuple[Path, Path]:
    """Escribe `informe.json` e `informe.md` en `directory` (se crea si falta) y devuelve sus rutas.

    Cada fichero se escribe primero a uno temporal y se renombra, así nunca queda uno a medias.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    json_path, markdown_path = target / REPORT_JSON_NAME, target / REPORT_MD_NAME
    _write_atomic(json_path, report_to_json(report))
    _write_atomic(markdown_path, report_to_markdown(report))
    return json_path, markdown_path
