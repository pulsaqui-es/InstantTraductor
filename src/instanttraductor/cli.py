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

    archivo = sub.add_parser("archivo", help="traduce un fichero de audio o vídeo")
    archivo.add_argument("entrada", metavar="ENTRADA", type=Path, help="fichero de audio o vídeo en inglés")
    archivo.add_argument(
        "--salida", metavar="DIR", type=Path, help="carpeta de salida (por defecto <nombre>_es)"
    )
    archivo.add_argument("--voz", metavar="ID", help="voz de esta ejecución")
    archivo.set_defaults(func=cmd_archivo)

    preparar = sub.add_parser("preparar", help="descarga y verifica los componentes")
    preparar.add_argument("--comprobar", action="store_true", help="solo verifica (no descarga nada)")
    preparar.set_defaults(func=cmd_preparar)

    voces = sub.add_parser("voces", help="lista, escucha y elige la voz")
    voces.add_argument(
        "--escuchar", metavar="ID", nargs="?", const="", help="reproduce la muestra de una voz (o de todas)"
    )
    voces.add_argument("--elegir", metavar="ID", help="guarda la voz en los ajustes")
    voces.set_defaults(func=cmd_voces)

    diagnostico = sub.add_parser(
        "diagnostico", help="versiones, GPU, dispositivos y estado de la preparación"
    )
    diagnostico.set_defaults(func=cmd_diagnostico)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)  # argparse sale con código 2 si el uso es incorrecto
    _setup_logging()
    _break_as_interrupt()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return EXIT_OK
    except Exception as error:  # contracts/cli.md: código 1, con el detalle en el registro
        logger.exception("Error inesperado en «%s»", args.command)
        print(f"Error inesperado: {error}. El detalle está en el registro: {_log_path()}")
        return EXIT_ERROR


def _break_as_interrupt() -> None:
    """Ctrl+Break para igual que Ctrl+C (parada limpia con informe), no matando el proceso de golpe."""
    import signal
    import threading

    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None and threading.current_thread() is threading.main_thread():
        signal.signal(sigbreak, signal.default_int_handler)


def _log_path() -> Path:
    from instanttraductor.config import AppPaths

    return AppPaths().logs / "instanttraductor.log"


def _setup_logging() -> None:
    from instanttraductor.config import AppPaths

    logs = AppPaths().logs
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(_log_path(), maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    # Las comprobaciones de salud de los hijos hacen una petición HTTP por segundo: solo los problemas.
    logging.getLogger("httpx").setLevel(logging.WARNING)


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
        if not _voice_exists(args.voz):
            console.print(
                f"No existe la voz «{args.voz}». Mira las voces con: instanttraductor voces", markup=False
            )
            return EXIT_USAGE
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


def cmd_archivo(args: argparse.Namespace) -> int:
    from rich.console import Console
    from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

    from instanttraductor.config import load_settings

    console = Console()
    missing = _missing_components()
    if missing:
        console.print(
            "Falta preparar el equipo (" + ", ".join(missing) + "). Ejecuta: instanttraductor preparar",
            markup=False,
        )
        return EXIT_NOT_PREPARED
    settings = load_settings()
    if args.voz:
        if not _voice_exists(args.voz):
            console.print(
                f"No existe la voz «{args.voz}». Mira las voces con: instanttraductor voces", markup=False
            )
            return EXIT_USAGE
        settings = replace(settings, voice=args.voz)

    from instanttraductor.pipeline.file_session import FileSession
    from instanttraductor.pipeline.session import SessionError
    from instanttraductor.ui.terminal import TerminalUI

    session = FileSession(
        settings,
        args.entrada,
        output_dir=args.salida,
        on_progress=lambda text: console.print(text, style="cyan", markup=False),
    )
    try:
        session.start()
        total = session.duration_s
        with Progress(
            TextColumn("Traduciendo"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f} %"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("archivo", total=total)
            session.run(on_tick=lambda t: progress.update(task, completed=min(t, total) if total else t))
            progress.update(task, completed=total)
        report = session.finish()
    except SessionError as error:
        session.abort()
        console.print(str(error), style="red", markup=False)
        return error.exit_code
    except KeyboardInterrupt:
        session.abort()
        console.print("Cancelado: no se ha escrito ninguna salida.", markup=False)
        return EXIT_OK
    TerminalUI(lambda: None, console=console, poll_interval_s=None).show_summary(report)
    console.print(f"Salidas en: {session.output_dir}", style="green", markup=False)
    return EXIT_OK


def _voice_exists(voice_id: str) -> bool:
    from instanttraductor.setup.voices import list_voices

    return any(voice.voice_id == voice_id for voice in list_voices())


def cmd_preparar(args: argparse.Namespace) -> int:
    from rich.console import Console

    from instanttraductor.config import AppPaths
    from instanttraductor.setup.installer import prepare
    from instanttraductor.setup.samples import generate_samples, missing_samples
    from instanttraductor.setup.voices import list_voices

    console = Console()
    paths = AppPaths()
    result = prepare(paths, check_only=args.comprobar, console=console)
    voices = [(voice.voice_id, voice.name) for voice in list_voices()]
    if args.comprobar:
        missing = missing_samples(paths, [voice_id for voice_id, _ in voices])
        if missing:
            console.print("Faltan muestras de voz: " + ", ".join(missing), markup=False)
        if missing and result.exit_code == EXIT_OK:
            return EXIT_NOT_PREPARED
        return result.exit_code
    if result.exit_code != EXIT_OK:
        return result.exit_code
    try:
        generate_samples(
            paths, voices, on_progress=lambda text: console.print(text, style="cyan", markup=False)
        )
    except Exception as error:  # las muestras no impiden usar la app
        logger.exception("No se pudieron generar las muestras de voz")
        console.print(f"No se pudieron generar las muestras de voz: {error}", style="yellow", markup=False)
    console.print("Listo. Para empezar: instanttraductor directo", style="green", markup=False)
    return EXIT_OK


def cmd_voces(args: argparse.Namespace) -> int:
    from rich.console import Console
    from rich.table import Table

    from instanttraductor.config import AppPaths, load_settings, save_settings
    from instanttraductor.setup.manifest import get_component
    from instanttraductor.setup.samples import play_sample, sample_path
    from instanttraductor.setup.voices import list_voices, voice_component_id

    console = Console()
    paths = AppPaths()
    voices = {voice.voice_id: voice for voice in list_voices()}
    settings = load_settings()

    if args.elegir is not None:
        if args.elegir not in voices:
            console.print(f"No existe la voz «{args.elegir}». Voces: " + ", ".join(voices), markup=False)
            return EXIT_USAGE
        save_settings(replace(settings, voice=args.elegir))
        console.print(f"Voz elegida: {voices[args.elegir].name} ({args.elegir}).", markup=False)
        return EXIT_OK

    if args.escuchar is not None:
        if args.escuchar and args.escuchar not in voices:
            console.print(f"No existe la voz «{args.escuchar}». Voces: " + ", ".join(voices), markup=False)
            return EXIT_USAGE
        chosen = [args.escuchar] if args.escuchar else list(voices)
        for voice_id in chosen:
            if not sample_path(paths, voice_id).is_file():
                console.print("Faltan las muestras. Ejecuta: instanttraductor preparar", markup=False)
                return EXIT_NOT_PREPARED
            console.print(f"▶ {voices[voice_id].name} ({voice_id})", markup=False)
            play_sample(paths, voice_id, volume=settings.voice_volume)
        return EXIT_OK

    table = Table(title="Voces")
    for column in ("", "Id", "Nombre", "Género", "Licencia"):
        table.add_column(column)
    for voice in voices.values():
        mark = "●" if voice.voice_id == settings.voice else ""
        gender = "femenina" if voice.gender == "f" else "masculina"
        short_license = get_component(voice_component_id(voice.voice_id)).license
        table.add_row(mark, voice.voice_id, voice.name, gender, short_license)
    console.print(table)
    console.print("● = la elegida. Escuchar: voces --escuchar [ID] · Elegir: voces --elegir ID", markup=False)
    return EXIT_OK


def cmd_diagnostico(args: argparse.Namespace) -> int:
    import io
    import platform
    import sys

    from rich.console import Console
    from rich.table import Table

    import instanttraductor
    from instanttraductor.config import AppPaths, ffmpeg_path, load_settings, settings_path
    from instanttraductor.setup.installer import RealSystem, prepare

    console = Console()
    paths = AppPaths()
    table = Table(title="Diagnóstico de InstantTraductor", show_header=False)
    table.add_column("Qué")
    table.add_column("Valor")
    table.add_row("Versión", instanttraductor.__version__)
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Windows", f"{platform.platform()} (build {RealSystem().windows_build()})")
    gpu = RealSystem().gpu_info()
    if gpu is None:
        table.add_row("GPU", "no se encontró una GPU NVIDIA (nvidia-smi)")
    else:
        cuda = ".".join(map(str, gpu.cuda_version)) if gpu.cuda_version else "?"
        table.add_row("GPU", f"{gpu.name} · driver {gpu.driver_version} · CUDA {cuda}")
    try:
        from instanttraductor.mt.selection import free_vram_mb

        table.add_row("VRAM libre", f"{free_vram_mb()} MiB")
    except Exception as error:
        table.add_row("VRAM libre", f"no disponible ({error})")
    table.add_row("Salida de audio", _default_playback_device())
    table.add_row("ffmpeg", str(ffmpeg_path() or "no encontrado"))
    table.add_row("Carpeta de datos", str(paths.home))
    table.add_row("Ajustes", f"{settings_path()} · voz {load_settings().voice}")
    table.add_row("Registro", str(paths.logs / "instanttraductor.log"))
    console.print(table)
    result = prepare(paths, check_only=True, console=Console(file=io.StringIO()))
    pending = [report.component.component_id for report in result.components if not report.ok]
    if result.exit_code == EXIT_OK:
        console.print("Preparación: completa.", style="green", markup=False)
    else:
        detail = ", ".join(pending) if pending else "requisitos o entorno de voz"
        console.print(f"Preparación: incompleta ({detail}). Ejecuta: instanttraductor preparar", markup=False)
    return EXIT_OK


def _default_playback_device() -> str:
    try:
        import importlib

        importlib.import_module("instanttraductor.audio")  # COM en modo MTA antes de comtypes
        from pycaw.pycaw import AudioUtilities

        return str(AudioUtilities.GetSpeakers().FriendlyName)
    except Exception as error:
        return f"no disponible ({error})"
