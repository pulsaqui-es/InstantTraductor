"""Línea de comandos de InstantTraductor (contracts/cli.md).

Subcomandos: ``directo`` (US1), ``archivo`` (US2, T037), ``preparar``, ``voces`` y ``diagnostico``
(US3, T043). Los módulos pesados (audio, modelos) se importan solo dentro de cada subcomando.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import threading
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_NOT_PREPARED = 3
EXIT_SELFTEST = 4
EXIT_BAD_INPUT = 5
EXIT_REQUIREMENTS = 6

logger = logging.getLogger("instanttraductor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="instanttraductor",
        description="Traductor simultáneo local: lo que suena en el PC, hablado en español de España.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="subcomando")

    directo = sub.add_parser("directo", help="traduce en directo lo que suena en el PC")
    directo.add_argument("--voz", metavar="ID", help="voz de esta sesión (no cambia el ajuste guardado)")
    directo.add_argument(
        "--volumen",
        metavar="N",
        type=int,
        choices=range(0, 201),
        help="volumen de la voz en español (0–200 %%)",
    )
    directo.add_argument("--mostrar-texto", action="store_true", help="muestra el original y la traducción")
    directo.add_argument("--informe", metavar="DIR", type=Path, help="carpeta del informe de la sesión")
    directo.set_defaults(func=cmd_directo)

    for name, help_text in (
        ("archivo", "traduce un fichero de audio o vídeo"),
        ("preparar", "descarga y verifica los componentes"),
        ("voces", "lista, escucha y elige la voz"),
        ("diagnostico", "versiones, GPU, dispositivos y estado de la preparación"),
    ):
        pending = sub.add_parser(name, help=help_text)
        pending.add_argument("resto", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
        pending.set_defaults(func=_not_yet_available)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)  # argparse sale con código 2 si el uso es incorrecto
    _setup_logging()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return EXIT_OK


def _setup_logging() -> None:
    from instanttraductor.config import AppPaths

    logs = AppPaths().logs
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        logs / "instanttraductor.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)


def _not_yet_available(args: argparse.Namespace) -> int:
    print(f"El subcomando «{args.command}» todavía no está disponible en esta versión.")
    return EXIT_USAGE


def _missing_components() -> list[str]:
    from instanttraductor.setup.manifest import COMPONENTS, is_installed

    return [c.component_id for c in COMPONENTS if not c.optional and not is_installed(c.component_id)]


def cmd_directo(args: argparse.Namespace) -> int:
    from rich.console import Console

    from instanttraductor.config import load_settings, save_settings

    console = Console()
    missing = _missing_components()
    if missing:
        console.print(
            "Falta preparar el equipo (" + ", ".join(missing) + "). Ejecuta: instanttraductor preparar",
            markup=False,
        )
        return EXIT_NOT_PREPARED

    saved = load_settings()
    settings = saved
    if args.voz:
        settings = replace(settings, voice=args.voz)
    if args.volumen is not None:
        settings = replace(settings, voice_volume=args.volumen / 100)
    if args.mostrar_texto:
        settings = replace(settings, show_text=True)

    from instanttraductor.pipeline.live import LiveSession
    from instanttraductor.pipeline.session import SessionError
    from instanttraductor.platform.windows import read_key_nonblocking
    from instanttraductor.ui.terminal import TerminalUI

    stop_event = threading.Event()
    session: LiveSession | None = None

    def on_volume(gain: float) -> None:
        if session is not None:
            session.set_volume(gain)

    ui = TerminalUI(
        read_key_nonblocking,
        console=console,
        volume=settings.voice_volume,
        show_text=settings.show_text,
        on_volume=on_volume,
        on_quit=stop_event.set,
    )
    session = LiveSession(
        settings,
        report_dir=args.informe,
        on_status=ui.update,
        on_progress=lambda text: console.print(text, style="cyan", markup=False),
    )
    try:
        session.start()
    except SessionError as error:
        console.print(str(error), style="red", markup=False)
        return error.exit_code
    except KeyboardInterrupt:
        session.stop()
        return EXIT_OK

    try:
        with ui, contextlib.suppress(KeyboardInterrupt):
            session.run_until(stop_event)
    finally:
        report = session.stop()
    if report is not None:
        ui.show_summary(report)
    # Persisten los cambios hechos con las teclas, salvo lo que se fijó solo para esta sesión.
    persisted = saved
    if args.volumen is None:
        persisted = replace(persisted, voice_volume=ui.volume)
    if not args.mostrar_texto:
        persisted = replace(persisted, show_text=ui.show_text)
    if persisted != saved:
        save_settings(persisted)
    fatal = session.fatal_error
    if fatal is not None:
        console.print(str(fatal), style="red", markup=False)
        return fatal.exit_code
    return EXIT_OK
