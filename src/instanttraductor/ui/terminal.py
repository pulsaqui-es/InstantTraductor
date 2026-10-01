"""Interfaz de terminal del modo directo (T017, research R13): estado en vivo con `rich`, teclas y resumen.

- `StatusSnapshot`: lo que la sesión cuenta a la interfaz (estado, retraso, velocidad, modo, avisos y el
  último texto). Es un dato inmutable: la sesión crea uno nuevo cada vez y llama a `TerminalUI.update`.
- `TerminalUI`: pinta el estado con `rich.live.Live`, atiende las teclas y, al final, `show_summary(informe)`.

**La interfaz no lee el teclado.** Recibe `key_reader`, una función sin argumentos que devuelve una tecla o
`None` sin bloquear (`platform.windows.read_key_nonblocking`, el único sitio del núcleo que toca el teclado de
la consola). Así este módulo no depende de Windows y se prueba con un lector falso.

Teclas (se procesan por *callbacks*): `+` y `-` cambian el volumen de la voz en pasos del 10 %
(de 0 % a 200 %), `t` muestra u oculta el texto y `q` pide salir. **Todos los textos van en español.**
Los textos que llegan de fuera (transcripción, avisos, informe) se imprimen tal cual, nunca como marcado de
`rich`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Final, Literal

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from instanttraductor.contracts import TranslationMode

logger = logging.getLogger(__name__)

__all__ = ["StatusSnapshot", "TerminalUI", "UiState"]

UiState = Literal["listening", "translating", "speaking", "stopped"]

_STATE_LABELS: Final = {
    "listening": "Escuchando",
    "translating": "Traduciendo",
    "speaking": "Hablando",
    "stopped": "Detenido",
}
_STATE_STYLES: Final = {
    "listening": "green",
    "translating": "yellow",
    "speaking": "cyan",
    "stopped": "dim",
}
_TITLE: Final = "InstantTraductor · modo directo"
_KEYS_HELP: Final = "+/- volumen · t texto · q salir"
_MAX_WARNINGS_SHOWN: Final = 5
_MAX_KEYS_PER_POLL: Final = 100  # tope por vuelta: un lector que nunca devuelve None no cuelga la interfaz
_VOLUME_STEP: Final = 0.1
_VOLUME_MAX: Final = 2.0
_POLL_THREAD_NAME: Final = "terminal-teclas"


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    """Estado de la sesión en un instante, tal como lo muestra la interfaz.

    `state` es el identificador interno (`listening`, `translating`, `speaking` o `stopped`); la interfaz lo
    traduce. `mode` es el de traducción de la última decisión de retraso (normal o conciso). `last_source`
    y `last_translation` son el último original y su traducción: solo se ven si el texto está activado.
    """

    state: UiState = "listening"
    lag_s: float = 0.0
    speed: float = 1.0
    mode: TranslationMode | str = TranslationMode.NORMAL
    warnings: tuple[str, ...] = ()
    last_source: str | None = None
    last_translation: str | None = None


def _label_grid() -> Table:
    """Tabla de dos columnas (etiqueta en negrita y valor) sin bordes."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", no_wrap=True)
    grid.add_column(overflow="fold")
    return grid


def _stepped(volume: float, delta: float) -> float:
    """`volume + delta` dentro de [0, 2] y redondeado a centésimas: los pasos de 0,1 no acumulan error."""
    return round(min(max(volume + delta, 0.0), _VOLUME_MAX), 2)


def _num(value: float | None, decimals: int) -> str:
    """Número con coma decimal; un guion si falta."""
    return "-" if value is None else f"{value:.{decimals}f}".replace(".", ",")


def _seconds(value: float | None, decimals: int = 1) -> str:
    return "-" if value is None else f"{_num(value, decimals)} s"


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


class TerminalUI:
    """Estado en vivo en la terminal, teclas y resumen final.

    `key_reader`: función sin argumentos que devuelve una tecla (un carácter) o `None` si no hay ninguna.
    No debe bloquear.

    Callbacks (todos opcionales; se llaman desde el hilo que procesa la tecla y sus fallos no rompen la
    interfaz): `on_volume(volumen)` con el nuevo volumen (0,0 a 2,0) solo si cambió, `on_toggle_text(mostrar)`
    con el nuevo valor y `on_quit()` la primera vez que se pulsa `q`.

    `volume` (0,0 a 2,0) y `show_text` son los valores iniciales (ajustes u opciones de la línea de comandos).
    `console`: por defecto, la de la terminal. `poll_interval_s`: cada cuánto, desde un hilo propio, se
    leen las teclas mientras la interfaz está en marcha (`None`: sin hilo; quien use la interfaz llama a
    `poll_keys` él mismo).

    Uso típico: `with TerminalUI(read_key_nonblocking, on_volume=sink.set_volume, on_quit=stop.set) as ui:`
    y, en la sesión, `ui.update(StatusSnapshot(...))` a ~2-4 Hz; al terminar, `ui.show_summary(informe)`.
    Se puede llamar a `update` y `handle_key` desde varios hilos.
    """

    def __init__(
        self,
        key_reader: Callable[[], str | None],
        *,
        console: Console | None = None,
        volume: float = 1.0,
        show_text: bool = False,
        on_volume: Callable[[float], None] | None = None,
        on_toggle_text: Callable[[bool], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        poll_interval_s: float | None = 0.05,
    ) -> None:
        self._key_reader = key_reader
        self._console = console if console is not None else Console()
        self._volume = _stepped(volume, 0.0)
        self._show_text = show_text
        self._on_volume = on_volume
        self._on_toggle_text = on_toggle_text
        self._on_quit = on_quit
        self._poll_interval_s = poll_interval_s
        self._snapshot = StatusSnapshot()
        self._quit_asked = False
        self._lock = threading.RLock()
        self._live: Live | None = None
        self._poll_thread: threading.Thread | None = None
        self._stop_polling = threading.Event()

    # --- Estado ----------------------------------------------------------------------------------

    @property
    def volume(self) -> float:
        """Volumen actual de la voz, de 0,0 a 2,0 (1,0 = 100 %)."""
        return self._volume

    @property
    def show_text(self) -> bool:
        """True si se muestran el original y la traducción."""
        return self._show_text

    @property
    def snapshot(self) -> StatusSnapshot:
        """El último estado recibido con `update`."""
        return self._snapshot

    # --- Ciclo de vida ---------------------------------------------------------------------------

    def start(self) -> None:
        """Empieza a pintar (y, si hay `poll_interval_s`, a leer las teclas). Idempotente."""
        with self._lock:
            if self._live is not None:
                return
            self._live = Live(
                self.render(),
                console=self._console,
                auto_refresh=False,  # se repinta en cada `update` y en cada tecla
                transient=False,  # el último estado se queda en pantalla
                vertical_overflow="visible",
            )
            self._live.start(refresh=True)
        if self._poll_interval_s is not None:
            self._stop_polling.clear()
            self._poll_thread = threading.Thread(target=self._poll_loop, name=_POLL_THREAD_NAME, daemon=True)
            self._poll_thread.start()

    def stop(self) -> None:
        """Deja de leer teclas y de pintar; el último estado queda en pantalla. Idempotente."""
        self._stop_polling.set()
        thread, self._poll_thread = self._poll_thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._lock:
            live, self._live = self._live, None
            if live is not None:
                live.stop()

    def __enter__(self) -> TerminalUI:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def update(self, snapshot: StatusSnapshot) -> None:
        """Guarda el nuevo estado y repinta."""
        with self._lock:
            self._snapshot = snapshot
        self._refresh()

    # --- Teclas ----------------------------------------------------------------------------------

    def poll_keys(self) -> None:
        """Procesa las teclas pendientes (hasta que el lector devuelve `None`) sin bloquear."""
        for _ in range(_MAX_KEYS_PER_POLL):
            try:
                key = self._key_reader()
            except Exception:
                logger.exception("Falló el lector de teclas")
                return
            if key is None:
                return
            self.handle_key(key)

    def handle_key(self, key: str) -> None:
        """Atiende una tecla: `+`/`-` volumen, `t` texto, `q` salir. Cualquier otra se ignora."""
        if len(key) != 1:
            return
        key = key.lower()
        volume: float | None = None
        show: bool | None = None
        quit_now = False
        with self._lock:
            if key in "+-":
                new = _stepped(self._volume, _VOLUME_STEP if key == "+" else -_VOLUME_STEP)
                if new != self._volume:
                    self._volume = volume = new
            elif key == "t":
                self._show_text = show = not self._show_text
            elif key == "q" and not self._quit_asked:
                self._quit_asked = quit_now = True
            else:
                return
        if volume is not None:
            self._call(self._on_volume, volume)
        if show is not None:
            self._call(self._on_toggle_text, show)
        if quit_now:
            self._call(self._on_quit)
        self._refresh()

    def _poll_loop(self) -> None:
        assert self._poll_interval_s is not None
        while not self._stop_polling.wait(self._poll_interval_s):
            self.poll_keys()

    # --- Pantalla --------------------------------------------------------------------------------

    def render(self, snapshot: StatusSnapshot | None = None) -> RenderableType:
        """Lo que se pinta para `snapshot` (por defecto, el último estado): un panel en español."""
        with self._lock:
            snap = self._snapshot if snapshot is None else snapshot
            volume, show_text = self._volume, self._show_text
        state = str(snap.state)
        concise = snap.mode == TranslationMode.CONCISE

        grid = _label_grid()
        grid.add_row("Estado", Text(_STATE_LABELS.get(state, state), style=_STATE_STYLES.get(state, "")))
        grid.add_row("Retraso", Text(_seconds(snap.lag_s)))
        grid.add_row("Velocidad", Text(f"{_num(snap.speed, 2)}×"))
        grid.add_row(
            "Modo", Text("resumido" if concise else str(snap.mode), style="yellow" if concise else "")
        )
        grid.add_row("Volumen", Text(f"{round(volume * 100)} %"))
        if show_text:
            grid.add_row("", "")
            grid.add_row("Original", Text(snap.last_source or "-"))
            grid.add_row("Traducción", Text(snap.last_translation or "-", style="cyan"))

        parts: list[RenderableType] = [grid]
        if snap.warnings:
            parts += [Text(""), Text("Avisos", style="bold yellow")]
            parts += [
                Text(f"! {warning}", style="yellow") for warning in snap.warnings[-_MAX_WARNINGS_SHOWN:]
            ]
        return Panel(
            Group(*parts),
            title=_TITLE,
            subtitle=_KEYS_HELP,
            border_style=_STATE_STYLES.get(state, ""),
        )

    def _refresh(self) -> None:
        with self._lock:
            if self._live is not None:
                self._live.update(self.render(), refresh=True)

    # --- Resumen ---------------------------------------------------------------------------------

    def show_summary(self, report: Mapping[str, Any]) -> None:
        """Para el estado en vivo y muestra el resumen de la sesión a partir del informe.

        `report` es el informe de `contracts/informe.md` (`summary`, `diagnostics`...), como diccionario o
        como dataclass con esos campos. Tolera un informe incompleto: lo que falta sale como un guion.
        """
        self.stop()
        if is_dataclass(report) and not isinstance(report, type):
            report = asdict(report)
        summary = _section(report, "summary")
        diagnostics = _section(report, "diagnostics")
        delay = _section(summary, "sentence_delay_s")
        stages = _section(summary, "stages_s")

        grid = _label_grid()

        def row(label: str, value: object, *, indent: bool = False) -> None:
            grid.add_row(("  " if indent else "") + label, Text("-" if value is None else str(value)))

        row("Duración", _duration(report.get("duration_s")))
        row("Frases", summary.get("utterances"))
        for label, key in (
            ("pronunciadas", "spoken"),
            ("resumidas", "concise"),
            ("aceleradas", "accelerated"),
            ("descartadas", "dropped"),
            ("rechazadas", "rejected"),
            ("fallidas", "failed"),
        ):
            row(label, summary.get(key), indent=True)
        grid.add_row("", "")
        p50, p95, worst = (_seconds(delay.get(key)) for key in ("p50", "p95", "max"))
        row("Retardo de frase", f"p50 {p50} · p95 {p95} · máx {worst}")
        grid.add_row("Etapas (p50 / p95)", "")
        for label, key in (
            ("captura", "capture"),
            ("reconocimiento", "asr"),
            ("traducción", "mt"),
            ("voz (primer audio)", "tts_first"),
            ("reproducción", "playback"),
        ):
            stage = _section(stages, key)
            row(label, f"{_seconds(stage.get('p50'), 2)} / {_seconds(stage.get('p95'), 2)}", indent=True)
        grid.add_row("", "")
        row("Arranque", _seconds(diagnostics.get("startup_s")))
        row("Retraso máximo", _seconds(diagnostics.get("max_lag_s")))
        row("Modelo de traducción", diagnostics.get("mt_model"))

        parts: list[RenderableType] = [grid]
        if warnings := _summary_warnings(summary, diagnostics):
            parts += [Text(""), Text("Avisos", style="bold yellow")]
            parts += [Text(f"! {warning}", style="yellow") for warning in warnings]
        self._console.print(Panel(Group(*parts), title="Resumen de la sesión"))

    # --- Callbacks -------------------------------------------------------------------------------

    @staticmethod
    def _call(callback: Callable[..., None] | None, *args: object) -> None:
        """Llama a un callback del suscriptor sin dejar que su fallo rompa la interfaz."""
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            logger.exception("Falló un callback de la interfaz")


def _section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    return value if isinstance(value, Mapping) else {}


def _duration(seconds: object) -> str | None:
    if not isinstance(seconds, (int, float)):
        return None
    if seconds < 60:
        return _seconds(float(seconds))
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest:02d} s"


def _count(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    return int(value) if isinstance(value, (int, float)) else 0


def _summary_warnings(summary: Mapping[str, Any], diagnostics: Mapping[str, Any]) -> list[str]:
    """Avisos del final de la sesión: lo que el humano debería saber de cómo fue."""
    warnings: list[str] = []
    if n := _count(summary, "dropped"):
        warnings.append(f"{_plural(n, 'frase descartada', 'frases descartadas')} por retraso.")
    if n := _count(summary, "rejected"):
        warnings.append(
            f"{_plural(n, 'traducción rechazada', 'traducciones rechazadas')} (no se pronunciaron)."
        )
    if n := _count(summary, "failed"):
        warnings.append(f"{_plural(n, 'frase fallida', 'frases fallidas')}.")
    if n := _count(diagnostics, "echo_events"):
        warnings.append(
            f"Se detectó eco {_plural(n, 'vez', 'veces')}: la voz en español volvió a la captura."
        )
    if n := _count(diagnostics, "component_restarts"):
        warnings.append(f"Se reinició {_plural(n, 'componente', 'componentes')}.")
    if n := _count(diagnostics, "underruns"):
        warnings.append(f"Cortes de audio en la reproducción: {n}.")
    return warnings
