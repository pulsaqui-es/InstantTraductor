"""Tests de la interfaz de terminal (T017): renderizado a texto, teclas con un lector falso y resumen.

El renderizado se comprueba imprimiendo en una `rich.console.Console` que no es un terminal y recoge el
texto (`record=True`); así no hace falta pantalla. Las teclas llegan de un lector falso: la interfaz no
lee el teclado por sí sola (eso es de `platform.windows`).
"""

from __future__ import annotations

import io
import re
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest
from rich.console import Console

from instanttraductor.contracts import TranslationMode
from instanttraductor.ui.terminal import StatusSnapshot, TerminalUI


def make_console(width: int = 80) -> Console:
    """Consola que no es un terminal y recoge lo que se imprime."""
    return Console(file=io.StringIO(), record=True, width=width, force_terminal=False, color_system=None)


class FakeKeys:
    """Lector de teclas falso: entrega las teclas en orden y después `None`, como `read_key_nonblocking`."""

    def __init__(self, *keys: str | None) -> None:
        self._keys = deque(keys)
        self.calls = 0

    def __call__(self) -> str | None:
        self.calls += 1
        return self._keys.popleft() if self._keys else None


class Recorder:
    """Callbacks de la interfaz que apuntan lo que reciben."""

    def __init__(self) -> None:
        self.volumes: list[float] = []
        self.texts: list[bool] = []
        self.quits = 0

    def on_volume(self, volume: float) -> None:
        self.volumes.append(volume)

    def on_toggle_text(self, show: bool) -> None:
        self.texts.append(show)

    def on_quit(self) -> None:
        self.quits += 1


def make_ui(*keys: str | None, **kwargs: Any) -> tuple[TerminalUI, Recorder, FakeKeys]:
    recorder = Recorder()
    reader = FakeKeys(*keys)
    ui = TerminalUI(
        reader,
        console=kwargs.pop("console", make_console()),
        on_volume=recorder.on_volume,
        on_toggle_text=recorder.on_toggle_text,
        on_quit=recorder.on_quit,
        poll_interval_s=kwargs.pop("poll_interval_s", None),
        **kwargs,
    )
    return ui, recorder, reader


def text_of(ui: TerminalUI, snapshot: StatusSnapshot | None = None, *, width: int = 80) -> str:
    console = make_console(width)
    console.print(ui.render(snapshot))
    return console.export_text()


def snapshot(**kwargs: Any) -> StatusSnapshot:
    return StatusSnapshot(**kwargs)


# --------------------------------------------------------------------------------------------------
# StatusSnapshot
# --------------------------------------------------------------------------------------------------


class TestStatusSnapshot:
    def test_has_sensible_defaults(self) -> None:
        s = StatusSnapshot()
        assert s.state == "listening"
        assert s.lag_s == 0.0
        assert s.speed == 1.0
        assert s.mode == TranslationMode.NORMAL
        assert s.warnings == ()
        assert s.last_source is None
        assert s.last_translation is None

    def test_is_immutable(self) -> None:
        with pytest.raises((AttributeError, TypeError)):
            StatusSnapshot().state = "stopped"  # type: ignore[misc]

    def test_accepts_every_field_by_keyword(self) -> None:
        s = StatusSnapshot(
            state="speaking",
            lag_s=2.5,
            speed=1.2,
            mode=TranslationMode.CONCISE,
            warnings=("a", "b"),
            last_source="Hello",
            last_translation="Hola",
        )
        assert (s.state, s.lag_s, s.speed, s.mode) == ("speaking", 2.5, 1.2, TranslationMode.CONCISE)
        assert s.warnings == ("a", "b")


# --------------------------------------------------------------------------------------------------
# Renderizado
# --------------------------------------------------------------------------------------------------


class TestRender:
    @pytest.mark.parametrize(
        ("state", "label"),
        [
            ("listening", "Escuchando"),
            ("translating", "Traduciendo"),
            ("speaking", "Hablando"),
            ("stopped", "Detenido"),
        ],
    )
    def test_the_state_is_shown_in_spanish(self, state: str, label: str) -> None:
        text = text_of(make_ui()[0], snapshot(state=state))
        assert label in text
        assert state not in text  # el identificador interno no sale a la pantalla

    def test_numbers_use_the_decimal_comma(self) -> None:
        text = text_of(make_ui()[0], snapshot(lag_s=1.234, speed=1.25))
        assert "1,2 s" in text
        assert "1,25" in text
        assert "1.2" not in text

    def test_lag_zero_and_default_speed(self) -> None:
        text = text_of(make_ui()[0], snapshot())
        assert "Retraso" in text
        assert "0,0 s" in text
        assert "Velocidad" in text
        assert "1,00" in text

    def test_the_mode_is_shown_in_spanish(self) -> None:
        ui = make_ui()[0]
        assert "normal" in text_of(ui, snapshot(mode=TranslationMode.NORMAL))
        concise = text_of(ui, snapshot(mode=TranslationMode.CONCISE))
        assert "resumido" in concise
        assert "conciso" not in concise

    def test_a_plain_string_mode_works_too(self) -> None:
        text = text_of(make_ui()[0], snapshot(mode="conciso"))
        assert "resumido" in text

    def test_the_volume_is_shown_as_a_percentage(self) -> None:
        assert "100 %" in text_of(make_ui()[0], snapshot())
        assert "150 %" in text_of(make_ui(volume=1.5)[0], snapshot())

    def test_the_keys_are_explained_in_spanish(self) -> None:
        text = text_of(make_ui()[0], snapshot())
        assert "+/-" in text
        assert "volumen" in text
        assert "texto" in text
        assert "salir" in text

    def test_warnings_are_listed(self) -> None:
        text = text_of(make_ui()[0], snapshot(warnings=("Se descartaron 2 frases.", "Sin audio del origen.")))
        assert "Avisos" in text
        assert "Se descartaron 2 frases." in text
        assert "Sin audio del origen." in text

    def test_no_warnings_section_without_warnings(self) -> None:
        assert "Avisos" not in text_of(make_ui()[0], snapshot())

    def test_only_the_latest_warnings_are_shown(self) -> None:
        warnings = tuple(f"aviso numero {i}" for i in range(20))
        text = text_of(make_ui()[0], snapshot(warnings=warnings))
        assert "aviso numero 19" in text
        assert "aviso numero 0" not in text

    def test_text_is_hidden_by_default(self) -> None:
        text = text_of(
            make_ui()[0], snapshot(last_source="Where were you?", last_translation="¿Dónde estabas?")
        )
        assert "Where were you?" not in text
        assert "¿Dónde estabas?" not in text

    def test_text_is_shown_when_enabled(self) -> None:
        ui = make_ui(show_text=True)[0]
        text = text_of(ui, snapshot(last_source="Where were you?", last_translation="¿Dónde estabas?"))
        assert "Original" in text
        assert "Where were you?" in text
        assert "Traducción" in text
        assert "¿Dónde estabas?" in text

    def test_text_placeholders_when_nothing_has_been_said_yet(self) -> None:
        text = text_of(make_ui(show_text=True)[0], snapshot())
        assert "Original" in text
        assert "Traducción" in text

    def test_user_text_is_never_taken_for_rich_markup(self) -> None:
        ui = make_ui(show_text=True)[0]
        text = text_of(ui, snapshot(last_source="[laughs] [bold]hi[/bold]", warnings=("[red]peligro[/red]",)))
        assert "[laughs] [bold]hi[/bold]" in text
        assert "[red]peligro[/red]" in text

    def test_long_text_wraps_inside_the_width(self) -> None:
        ui = make_ui(show_text=True)[0]
        long = "palabra " * 120
        text = text_of(ui, snapshot(last_source=long, last_translation=long, warnings=(long,)), width=60)
        assert max(len(line) for line in text.splitlines()) <= 60

    def test_it_fits_a_narrow_terminal(self) -> None:
        text = text_of(make_ui(show_text=True)[0], snapshot(warnings=("algo",)), width=30)
        assert max(len(line) for line in text.splitlines()) <= 30

    def test_render_without_a_snapshot_uses_the_latest_one(self) -> None:
        ui = make_ui()[0]
        ui.update(snapshot(state="speaking"))
        assert "Hablando" in text_of(ui)

    def test_render_before_any_update_shows_the_initial_state(self) -> None:
        assert "Escuchando" in text_of(make_ui()[0])

    def test_everything_on_screen_is_in_spanish(self) -> None:
        ui = make_ui(show_text=True)[0]
        text = text_of(ui, snapshot(state="translating", mode=TranslationMode.CONCISE, warnings=("x",)))
        for english in ("listening", "translating", "speaking", "stopped", "lag", "speed", "volume", "quit"):
            assert not re.search(rf"\b{english}\b", text.lower()), english  # «volumen» no es «volume»


# --------------------------------------------------------------------------------------------------
# Teclas
# --------------------------------------------------------------------------------------------------


class TestKeys:
    def test_plus_and_minus_change_the_volume_in_steps_of_10_percent(self) -> None:
        ui, rec, _ = make_ui()
        ui.handle_key("+")
        ui.handle_key("+")
        ui.handle_key("-")
        assert rec.volumes == [1.1, 1.2, 1.1]
        assert ui.volume == pytest.approx(1.1)

    def test_the_volume_is_clamped_to_0_and_200_percent(self) -> None:
        ui, rec, _ = make_ui(volume=1.95)
        ui.handle_key("+")
        assert ui.volume == 2.0
        ui.handle_key("+")  # ya está en el máximo: no cambia ni avisa
        assert rec.volumes == [2.0]
        low, rec_low, _ = make_ui(volume=0.05)
        low.handle_key("-")
        assert low.volume == 0.0
        low.handle_key("-")
        assert rec_low.volumes == [0.0]

    def test_steps_do_not_accumulate_floating_point_error(self) -> None:
        ui, rec, _ = make_ui(volume=0.0)
        for _ in range(20):
            ui.handle_key("+")
        assert ui.volume == 2.0
        assert rec.volumes[-1] == 2.0
        assert rec.volumes[2] == 0.3  # 0,1 + 0,1 + 0,1 sin 0,30000000000000004

    def test_the_shown_volume_follows_the_keys(self) -> None:
        ui, _, _ = make_ui()
        ui.handle_key("+")
        assert "110 %" in text_of(ui)
        ui.handle_key("-")
        ui.handle_key("-")
        assert "90 %" in text_of(ui)

    def test_t_toggles_the_text(self) -> None:
        ui, rec, _ = make_ui()
        assert ui.show_text is False
        ui.handle_key("t")
        assert ui.show_text is True
        ui.handle_key("t")
        assert ui.show_text is False
        assert rec.texts == [True, False]

    def test_the_text_toggle_changes_what_is_rendered(self) -> None:
        ui, _, _ = make_ui()
        ui.update(snapshot(last_source="Hello there", last_translation="Hola"))
        assert "Hello there" not in text_of(ui)
        ui.handle_key("t")
        assert "Hello there" in text_of(ui)

    def test_q_asks_to_quit_once(self) -> None:
        ui, rec, _ = make_ui()
        ui.handle_key("q")
        ui.handle_key("q")
        assert rec.quits == 1

    @pytest.mark.parametrize("key", ["Q", "T"])
    def test_upper_case_works_too(self, key: str) -> None:
        ui, rec, _ = make_ui()
        ui.handle_key(key)
        assert rec.quits + len(rec.texts) == 1

    @pytest.mark.parametrize("key", ["x", "1", " ", "\r", "\x1b", "", "++", "ñ"])
    def test_other_keys_do_nothing(self, key: str) -> None:
        ui, rec, _ = make_ui()
        ui.handle_key(key)
        assert (rec.volumes, rec.texts, rec.quits) == ([], [], 0)
        assert ui.volume == 1.0
        assert ui.show_text is False

    def test_poll_keys_handles_every_pending_key_and_stops_at_none(self) -> None:
        ui, rec, reader = make_ui("+", "+", "t", "-", None, "q")
        ui.poll_keys()
        assert rec.volumes == [1.1, 1.2, 1.1]
        assert rec.texts == [True]
        assert rec.quits == 0  # la «q» llega después del None: queda para la siguiente vuelta
        ui.poll_keys()
        assert rec.quits == 1
        assert reader.calls == 7

    def test_poll_keys_with_nothing_pending_returns_at_once(self) -> None:
        ui, _, reader = make_ui()
        ui.poll_keys()
        assert reader.calls == 1

    def test_a_flood_of_keys_does_not_hang_poll_keys(self) -> None:
        ui = TerminalUI(lambda: "x", console=make_console(), poll_interval_s=None)  # nunca devuelve None
        ui.poll_keys()  # tiene que volver

    def test_callbacks_are_optional(self) -> None:
        ui = TerminalUI(FakeKeys("+", "t", "q"), console=make_console(), poll_interval_s=None)
        ui.poll_keys()
        assert ui.volume == pytest.approx(1.1)
        assert ui.show_text is True

    def test_a_failing_callback_does_not_break_the_interface(self) -> None:
        def boom(*_args: object) -> None:
            raise RuntimeError("fallo del suscriptor")

        ui = TerminalUI(
            FakeKeys("+", "t", "q", "-"),
            console=make_console(),
            on_volume=boom,
            on_toggle_text=boom,
            on_quit=boom,
            poll_interval_s=None,
        )
        ui.poll_keys()
        assert ui.volume == pytest.approx(1.0)  # +10 % y -10 %
        assert ui.show_text is True


# --------------------------------------------------------------------------------------------------
# Live
# --------------------------------------------------------------------------------------------------


class TestLive:
    def test_update_before_start_only_stores_the_snapshot(self) -> None:
        console = make_console()
        ui, _, _ = make_ui(console=console)
        ui.update(snapshot(state="speaking"))
        assert ui.snapshot.state == "speaking"
        assert console.export_text() == ""

    def test_the_last_frame_stays_on_screen_when_it_stops(self) -> None:
        console = make_console()
        ui, _, _ = make_ui(console=console)
        ui.start()
        ui.update(snapshot(state="translating", lag_s=2.0))
        ui.update(snapshot(state="speaking", lag_s=3.5))
        ui.stop()
        text = console.export_text()
        assert "Hablando" in text
        assert "3,5 s" in text

    def test_it_works_on_an_interactive_terminal_too(self) -> None:
        """Con un terminal de verdad `Live` repinta en el sitio con códigos de control."""
        output = io.StringIO()
        console = Console(file=output, force_terminal=True, width=80, color_system="standard")
        ui = TerminalUI(FakeKeys(), console=console, poll_interval_s=None)
        ui.start()
        ui.update(snapshot(state="translating", lag_s=1.0))
        ui.handle_key("+")
        ui.update(snapshot(state="speaking", lag_s=2.0))
        ui.stop()
        screen = output.getvalue()
        assert "\x1b[" in screen  # hubo códigos de control
        assert "Traduciendo" in screen
        assert "Hablando" in screen
        assert "110 %" in screen

    def test_start_and_stop_are_idempotent(self) -> None:
        ui, _, _ = make_ui()
        ui.stop()  # sin arrancar
        ui.start()
        ui.start()
        ui.stop()
        ui.stop()

    def test_it_works_as_a_context_manager(self) -> None:
        console = make_console()
        ui, _, _ = make_ui(console=console)
        with ui:
            ui.update(snapshot(state="speaking"))
        assert "Hablando" in console.export_text()

    def test_a_key_press_while_running_refreshes_the_screen(self) -> None:
        console = make_console()
        ui, _, _ = make_ui(console=console)
        ui.start()
        ui.handle_key("+")
        ui.stop()
        assert "110 %" in console.export_text()

    def test_the_polling_thread_reads_keys_by_itself(self) -> None:
        quit_asked = threading.Event()
        ui = TerminalUI(
            FakeKeys(None, "+", "q"),
            console=make_console(),
            on_quit=quit_asked.set,
            poll_interval_s=0.01,
        )
        with ui:
            assert quit_asked.wait(3.0)
        assert ui.volume == pytest.approx(1.1)

    def test_stop_ends_the_polling_thread(self) -> None:
        ui = TerminalUI(lambda: None, console=make_console(), poll_interval_s=0.01)
        ui.start()
        assert any(t.name == "terminal-teclas" for t in threading.enumerate())
        ui.stop()
        assert not any(t.name == "terminal-teclas" for t in threading.enumerate())

    def test_without_a_poll_interval_no_thread_is_started(self) -> None:
        ui, _, reader = make_ui()
        ui.start()
        assert not any(t.name == "terminal-teclas" for t in threading.enumerate())
        ui.stop()
        assert reader.calls == 0

    def test_updates_from_several_threads_are_safe(self) -> None:
        ui, _, _ = make_ui()
        ui.start()

        def spam(n: int) -> None:
            for i in range(50):
                ui.update(snapshot(lag_s=i / 10, warnings=(f"hilo {n}",)))
                ui.handle_key("+" if i % 2 else "-")

        threads = [threading.Thread(target=spam, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        ui.stop()
        assert not any(t.is_alive() for t in threads)


# --------------------------------------------------------------------------------------------------
# Resumen final
# --------------------------------------------------------------------------------------------------


REPORT: dict[str, Any] = {
    "schema_version": 1,
    "session_id": "20261001-213000",
    "mode": "directo",
    "duration_s": 1800.0,
    "summary": {
        "utterances": 412,
        "spoken": 403,
        "concise": 12,
        "accelerated": 30,
        "dropped": 7,
        "rejected": 2,
        "failed": 0,
        "sentence_delay_s": {"p50": 2.41, "p95": 4.62, "max": 7.9},
        "stages_s": {
            "capture": {"p50": 0.09, "p95": 0.12},
            "asr": {"p50": 0.62, "p95": 0.95},
            "mt": {"p50": 0.18, "p95": 0.31},
            "tts_first": {"p50": 0.33, "p95": 0.52},
            "playback": {"p50": 0.40, "p95": 2.10},
        },
    },
    "diagnostics": {
        "startup_s": 34.2,
        "max_lag_s": 7.4,
        "lag_over_drop_max_streak_s": 0.0,
        "echo_events": 0,
        "component_restarts": 0,
        "underruns": 0,
        "mt_model": "hy-mt2-7b-q4",
    },
}


def summary_text(report: Mapping[str, Any], *, width: int = 100) -> str:
    console = make_console(width)
    ui = TerminalUI(FakeKeys(), console=console, poll_interval_s=None)
    ui.show_summary(report)
    return console.export_text()


class TestSummary:
    def test_shows_the_session_figures_in_spanish(self) -> None:
        text = summary_text(REPORT)
        assert "Resumen de la sesión" in text
        assert "Duración" in text
        assert "30 min 00 s" in text
        for label in ("pronunciadas", "resumidas", "aceleradas", "descartadas", "rechazadas", "fallidas"):
            assert label in text
        for number in ("412", "403", "12", "30", "7"):
            assert number in text

    def test_shows_the_sentence_delay_percentiles(self) -> None:
        text = summary_text(REPORT)
        assert "Retardo de frase" in text
        for value in ("2,4 s", "4,6 s", "7,9 s"):
            assert value in text

    def test_shows_every_stage(self) -> None:
        text = summary_text(REPORT)
        for stage in ("captura", "reconocimiento", "traducción", "voz", "reproducción"):
            assert stage in text.lower()
        assert "0,62 s" in text
        assert "2,10 s" in text

    def test_shows_the_diagnostics(self) -> None:
        text = summary_text(REPORT)
        assert "Arranque" in text
        assert "34,2 s" in text
        assert "Retraso máximo" in text
        assert "7,4 s" in text
        assert "hy-mt2-7b-q4" in text

    def test_dropped_sentences_are_warned_about(self) -> None:
        text = summary_text(REPORT)
        assert "Avisos" in text
        assert "7 frases descartadas" in text

    def test_echo_restarts_and_underruns_are_warned_about(self) -> None:
        report = {
            **REPORT,
            "diagnostics": {
                **REPORT["diagnostics"],
                "echo_events": 3,
                "component_restarts": 1,
                "underruns": 5,
            },
        }
        text = summary_text(report)
        assert "eco" in text.lower()
        assert "3" in text
        assert "reinici" in text.lower()
        assert "cortes" in text.lower()

    def test_no_warnings_when_the_session_was_clean(self) -> None:
        clean = {**REPORT, "summary": {**REPORT["summary"], "dropped": 0, "rejected": 0, "failed": 0}}
        assert "Avisos" not in summary_text(clean)

    def test_failed_and_rejected_are_warned_about(self) -> None:
        report = {**REPORT, "summary": {**REPORT["summary"], "failed": 2, "rejected": 4}}
        text = summary_text(report)
        assert "2 frases fallidas" in text
        assert "4 traducciones rechazadas" in text

    def test_a_short_session_shows_seconds(self) -> None:
        assert "12,5 s" in summary_text({**REPORT, "duration_s": 12.5})
        assert "1 min 05 s" in summary_text({**REPORT, "duration_s": 65.0})

    def test_a_session_without_utterances_does_not_crash(self) -> None:
        report = {"duration_s": 5.0, "summary": {"utterances": 0}, "diagnostics": {}}
        text = summary_text(report)
        assert "Resumen de la sesión" in text
        assert "0" in text

    def test_a_dataclass_report_works_like_a_dictionary(self) -> None:
        @dataclass
        class Delay:
            p50: float = 2.41
            p95: float = 4.62
            max: float = 7.9

        @dataclass
        class Summary:
            utterances: int = 5
            dropped: int = 1
            sentence_delay_s: Delay = field(default_factory=Delay)

        @dataclass
        class Report:
            duration_s: float = 90.0
            summary: Summary = field(default_factory=Summary)

        text = summary_text(Report())  # type: ignore[arg-type]
        assert "1 min 30 s" in text
        assert "2,4 s" in text
        assert "1 frase descartada" in text

    def test_an_empty_report_does_not_crash(self) -> None:
        assert "Resumen de la sesión" in summary_text({})

    def test_missing_values_are_shown_as_a_dash(self) -> None:
        text = summary_text({"summary": {"utterances": 3, "sentence_delay_s": {"p50": None}}})
        assert "Retardo de frase" in text
        assert "-" in text

    def test_markup_in_the_report_is_not_interpreted(self) -> None:
        text = summary_text({**REPORT, "diagnostics": {"mt_model": "[bold]x[/bold]"}})
        assert "[bold]x[/bold]" in text

    def test_it_stops_the_live_display_first(self) -> None:
        console = make_console()
        ui = TerminalUI(FakeKeys(), console=console, poll_interval_s=None)
        ui.start()
        ui.update(snapshot(state="speaking"))
        ui.show_summary(REPORT)
        text = console.export_text(clear=False)
        assert text.index("Hablando") < text.index("Resumen de la sesión")  # primero el último estado
        ui.stop()  # no falla ni vuelve a pintar la pantalla
        assert console.export_text() == text

    def test_the_default_console_is_used_when_none_is_given(self) -> None:
        ui = TerminalUI(FakeKeys(), poll_interval_s=None)
        assert ui.render() is not None


def test_a_callable_object_works_as_a_key_reader() -> None:
    reader: Callable[[], str | None] = FakeKeys("q")
    ui = TerminalUI(reader, console=make_console(), poll_interval_s=None)
    ui.poll_keys()
