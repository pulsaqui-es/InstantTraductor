"""Salidas del modo archivo (T036): pista de voz, mezclas, transcripción, traducción e informe.

`write_outputs` escribe en una carpeta de salida lo que describe `contracts/informe.md`:

| Fichero | Contenido |
|---|---|
| `voz_es.wav` | 48 kHz, mono, float32 (WAV IEEE float escrito a mano): la pista de `TimelineSink.track()` |
| `mezcla.wav` | 48 kHz, estéreo, 16 bits: original + voz (`amix=normalize=0`) con limitador |
| `mezcla.mkv` | solo con vídeo: vídeo copiado, pista 1 = mezcla (AAC), pista 2 = original copiado |
| `transcripcion.srt` / `.json` | una entrada por unidad: `t_start_audio → t_end_audio` y el texto original |
| `traduccion.srt` / `.json` | una por unidad pronunciada: `play_started_at → play_finished_at` y el texto |
| `informe.json` / `.md` | el informe, tal como llega (ya serializado) |

Formato de los JSON (el contrato solo fija el contenido; esta es la estructura)::

    {"schema_version": 1, "input_file": "<nombre>", "segments": [
        {"unit_id": 1, "start": 3.12, "end": 4.48, "text": "Where were you?"} ]}

Los de `traduccion.json` añaden a cada segmento `"concise"` (resumida) y `"speed"`. En `traduccion.srt` las
frases resumidas llevan delante la marca `[resumida]`. Los tiempos van en segundos con 3 decimales; los
SRT, UTF-8 con saltos de línea `\\n`, numerados desde 1 y ordenados por tiempo.

Escritura atómica (FR-022)
--------------------------
Todo se genera primero en una carpeta temporal hermana de la de salida y solo al final, con todo
completo, pasa a su sitio. Si algo falla, no queda ni la temporal ni ficheros a medias. Si la carpeta de
salida ya existe, se sustituyen solo los ficheros que esta función produce (los de ejecuciones anteriores
que ya no se generan, como un `mezcla.mkv` viejo, también se retiran) y el resto de su contenido no se
toca; si el cambio fallara a medias, se restaura lo anterior.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import shutil
import struct
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from instanttraductor.audio.file_source import ENGINE_NAME, ffprobe_path, probe_input
from instanttraductor.config import ffmpeg_path
from instanttraductor.contracts import PLAYBACK_RATE, EngineError, Outcome, TranslationMode, UtteranceRecord

logger = logging.getLogger(__name__)

__all__ = [
    "OUTPUT_NAMES",
    "build_srt",
    "format_srt_time",
    "transcription_entries",
    "translation_entries",
    "write_float_wav",
    "write_outputs",
]

VOICE_WAV: Final = "voz_es.wav"
MIX_WAV: Final = "mezcla.wav"
MIX_MKV: Final = "mezcla.mkv"
TRANSCRIPT_SRT: Final = "transcripcion.srt"
TRANSCRIPT_JSON: Final = "transcripcion.json"
TRANSLATION_SRT: Final = "traduccion.srt"
TRANSLATION_JSON: Final = "traduccion.json"
REPORT_JSON: Final = "informe.json"
REPORT_MD: Final = "informe.md"

#: Todo lo que produce `write_outputs` (los únicos nombres que sustituye o retira en una carpeta existente).
OUTPUT_NAMES: Final = (
    VOICE_WAV,
    MIX_WAV,
    MIX_MKV,
    TRANSCRIPT_SRT,
    TRANSCRIPT_JSON,
    TRANSLATION_SRT,
    TRANSLATION_JSON,
    REPORT_JSON,
    REPORT_MD,
)

SCHEMA_VERSION: Final = 1
CONCISE_MARK: Final = "[resumida]"
MIX_LIMIT: Final = 0.97
AAC_BITRATE: Final = "192k"
MAX_VOICE_GAIN: Final = 2.0
_FFMPEG_TIMEOUT_S: Final = 3600.0
_WRITE_BLOCK_SAMPLES: Final = 1 << 20
_NO_WINDOW: Final = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_WAV_MAX_DATA_BYTES: Final = 0xFFFFFFFF - 64  # los tamaños de RIFF son de 32 bits

Samples = npt.NDArray[np.float32]


# --------------------------------------------------------------------------------------------------
# WAV float32 a mano (soundfile es solo de desarrollo)
# --------------------------------------------------------------------------------------------------


def write_float_wav(path: Path, samples: Samples, *, sample_rate: int = PLAYBACK_RATE) -> None:
    """Escribe un WAV mono de `float32` (formato 3, IEEE float), con `fmt ` de 18 bytes y `fact`."""
    audio = np.ascontiguousarray(samples, dtype="<f4")
    if audio.ndim != 1:
        raise ValueError(f"La pista debe ser mono (un array 1-D); forma recibida: {audio.shape}.")
    data_bytes = audio.size * 4
    if data_bytes > _WAV_MAX_DATA_BYTES:
        raise ValueError("La pista es demasiado larga para un WAV (más de 4 GiB).")
    byte_rate = sample_rate * 4
    header = (
        b"RIFF"
        + struct.pack("<I", 4 + (8 + 18) + (8 + 4) + (8 + data_bytes) + (data_bytes & 1))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHHH", 18, 3, 1, sample_rate, byte_rate, 4, 32, 0)
        + b"fact"
        + struct.pack("<II", 4, audio.size)
        + b"data"
        + struct.pack("<I", data_bytes)
    )
    with path.open("wb") as handle:
        handle.write(header)
        for start in range(0, audio.size, _WRITE_BLOCK_SAMPLES):
            handle.write(audio[start : start + _WRITE_BLOCK_SAMPLES].tobytes())


# --------------------------------------------------------------------------------------------------
# SRT y JSON de transcripción y traducción
# --------------------------------------------------------------------------------------------------


def format_srt_time(seconds: float) -> str:
    """`HH:MM:SS,mmm`; los negativos se acotan a cero."""
    total_ms = max(0, round(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _entry(record: UtteranceRecord, start: float, end: float, text: str) -> dict[str, Any]:
    return {
        "unit_id": record.unit_id,
        "start": round(start, 3),
        "end": round(max(end, start), 3),
        "text": text.strip(),
    }


def transcription_entries(records: Sequence[UtteranceRecord]) -> list[dict[str, Any]]:
    """Una entrada por unidad: `t_start_audio → t_end_audio` y el texto original, por orden de tiempo."""
    entries = [
        _entry(r, r.timings.t_start_audio, r.timings.t_end_audio, r.source_text)
        for r in records
        if r.source_text.strip()
    ]
    return sorted(entries, key=lambda e: (e["start"], e["unit_id"]))


def translation_entries(records: Sequence[UtteranceRecord]) -> list[dict[str, Any]]:
    """Una entrada por unidad pronunciada: `play_started_at → play_finished_at` y el texto en español."""
    entries: list[dict[str, Any]] = []
    for r in records:
        t = r.timings
        if r.outcome is not Outcome.SPOKEN or not (r.translated_text or "").strip():
            continue
        if t.play_started_at is None or t.play_finished_at is None:
            continue
        entry = _entry(r, t.play_started_at, t.play_finished_at, r.translated_text or "")
        entry["concise"] = r.mode is TranslationMode.CONCISE
        entry["speed"] = round(r.speed, 3)
        entries.append(entry)
    return sorted(entries, key=lambda e: (e["start"], e["unit_id"]))


def build_srt(entries: Sequence[Mapping[str, Any]], *, mark_concise: bool = False) -> str:
    """El SRT de unas entradas: índice desde 1, intervalo, texto y línea en blanco. Vacío si no hay."""
    blocks = []
    for number, entry in enumerate(entries, start=1):
        text = str(entry["text"])
        if mark_concise and entry.get("concise"):
            text = f"{CONCISE_MARK} {text}"
        blocks.append(
            f"{number}\n{format_srt_time(entry['start'])} --> {format_srt_time(entry['end'])}\n{text}\n"
        )
    return "\n".join(blocks)


def _segments_json(input_path: Path, entries: Sequence[Mapping[str, Any]]) -> str:
    document = {"schema_version": SCHEMA_VERSION, "input_file": input_path.name, "segments": list(entries)}
    return json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------------------------------
# ffmpeg
# --------------------------------------------------------------------------------------------------


def _run_ffmpeg(args: Sequence[str]) -> None:
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        raise EngineError(
            "No se encuentra ffmpeg: instálalo con `instanttraductor preparar` o ponlo en el PATH.",
            engine=ENGINE_NAME,
            recoverable=False,
        )
    command = [str(ffmpeg), "-nostdin", "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=_FFMPEG_TIMEOUT_S,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise EngineError("ffmpeg tardó demasiado generando la mezcla.", engine=ENGINE_NAME) from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise EngineError(
            f"ffmpeg falló generando la mezcla (código {result.returncode}): {detail[-1] if detail else ''}",
            engine=ENGINE_NAME,
            recoverable=False,
        )


def _original_channels(input_path: Path) -> int | None:
    """Canales de la primera pista de audio (None si no se puede saber)."""
    ffprobe = ffprobe_path()
    if ffprobe is None:
        return None
    try:
        result = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=channels",
                "-of",
                "csv=p=0",
                str(input_path),
            ],
            capture_output=True,
            timeout=30.0,
            check=False,
            creationflags=_NO_WINDOW,
        )
        return int(result.stdout.decode().strip().splitlines()[0])
    except (subprocess.TimeoutExpired, OSError, ValueError, IndexError):
        return None


def _stereo(label_in: str, label_out: str, channels: int | None) -> str:
    """Cadena que deja `label_in` en 48 kHz estéreo. El mono se duplica en los dos canales sin atenuar."""
    if channels == 1:
        return f"[{label_in}]aresample={PLAYBACK_RATE},pan=stereo|c0=c0|c1=c0[{label_out}]"
    return f"[{label_in}]aresample={PLAYBACK_RATE},aformat=channel_layouts=stereo[{label_out}]"


def _mix_wav(input_path: Path, voice_wav: Path, target: Path, voice_volume: float) -> None:
    graph = ";".join(
        [
            _stereo("0:a:0", "o", _original_channels(input_path)),
            _stereo("1:a:0", "v0", 1),
            f"[v0]volume={voice_volume:.4f}[v]",
            f"[o][v]amix=inputs=2:duration=first:normalize=0,alimiter=limit={MIX_LIMIT}:level=disabled[m]",
        ]
    )
    _run_ffmpeg(
        [
            "-i",
            str(input_path),
            "-i",
            str(voice_wav),
            "-filter_complex",
            graph,
            "-map",
            "[m]",
            "-ar",
            str(PLAYBACK_RATE),
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(target),
        ]
    )


def _mix_mkv(input_path: Path, mix_wav: Path, target: Path) -> None:
    """Vídeo copiado; pista 1 = la mezcla en AAC; pista 2 = el audio original copiado."""
    _run_ffmpeg(
        [
            "-i",
            str(input_path),
            "-i",
            str(mix_wav),
            "-map",
            "0:V:0",
            "-map",
            "1:a:0",
            "-map",
            "0:a:0",
            "-c:v",
            "copy",
            "-c:a:0",
            "aac",
            "-b:a:0",
            AAC_BITRATE,
            "-c:a:1",
            "copy",
            "-metadata:s:a:0",
            "title=Mezcla (original y español)",
            "-metadata:s:a:1",
            "title=Original",
            "-disposition:a:0",
            "default",
            "-disposition:a:1",
            "0",
            str(target),
        ]
    )


# --------------------------------------------------------------------------------------------------
# Escritura atómica
# --------------------------------------------------------------------------------------------------


def _first_missing_ancestor(path: Path) -> Path | None:
    missing = None
    for candidate in (path, *path.parents):
        if candidate.exists():
            return missing
        missing = candidate
    return missing


def _install(staging: Path, out_dir: Path, produced: Sequence[str]) -> None:
    """Pone en `out_dir` los ficheros de `staging`; si falla a medias, deja `out_dir` como estaba."""
    if not out_dir.exists():
        os.replace(staging, out_dir)  # carpeta nueva: un solo renombrado
        return
    backup = staging.with_name(staging.name + ".old")
    backup.mkdir()
    moved: list[str] = []
    installed: list[str] = []
    try:
        for name in OUTPUT_NAMES:  # lo anterior, aparte (también lo que ya no se genera)
            if (out_dir / name).exists():
                os.replace(out_dir / name, backup / name)
                moved.append(name)
        for name in produced:
            os.replace(staging / name, out_dir / name)
            installed.append(name)
    except BaseException:
        for name in installed:
            with contextlib.suppress(OSError):
                (out_dir / name).unlink()
        for name in moved:
            with contextlib.suppress(OSError):
                os.replace(backup / name, out_dir / name)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)


def write_outputs(
    out_dir: str | os.PathLike[str],
    *,
    input_path: str | os.PathLike[str],
    track_48k: Samples,
    records: Sequence[UtteranceRecord],
    report_json: str,
    report_md: str,
    voice_volume: float = 1.0,
) -> list[Path]:
    """Genera todas las salidas del modo archivo en `out_dir` y devuelve las rutas finales.

    - `track_48k`: la voz en español (`TimelineSink.track()`): mono, 48 kHz, `float32`, con la duración de
      la entrada. Se guarda tal cual en `voz_es.wav`; el volumen solo se aplica a la mezcla.
    - `records`: los `UtteranceRecord` de la sesión.
    - `report_json` y `report_md`: el informe ya serializado (`report_to_json` y `report_to_markdown`).
    - `voice_volume`: ganancia de la voz en la mezcla, de 0 a 2 (`volumen_voz` de los ajustes). No la apliques
      además con `TimelineSink.set_volume`, o sonaría al cuadrado.

    Todo se escribe antes en una carpeta temporal hermana y pasa a `out_dir` al final: si algo falla no queda
    ni la temporal ni salidas a medias (la excepción sube). Lanza `InputFileError` si la entrada no es
    válida y `EngineError(recoverable=False)` si ffmpeg falla o no está.
    """
    destination = Path(out_dir)
    source = Path(input_path)
    if not math.isfinite(voice_volume) or voice_volume < 0:
        raise ValueError(f"voice_volume debe ser un número finito no negativo (recibido: {voice_volume}).")
    voice_volume = min(MAX_VOICE_GAIN, voice_volume)
    if destination.exists() and not destination.is_dir():
        raise NotADirectoryError(f"La salida {destination} existe y no es una carpeta.")
    has_video = probe_input(source).has_video  # valida la entrada antes de tocar nada

    created_root = _first_missing_ancestor(destination.parent)
    staging = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        produced = _write_all(
            staging, source, track_48k, records, report_json, report_md, voice_volume, has_video
        )
        _install(staging, destination, produced)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(staging.with_name(staging.name + ".old"), ignore_errors=True)
        if created_root is not None and not destination.exists():
            with contextlib.suppress(OSError):  # solo si ya no hay nada dentro
                for folder in (destination.parent, *destination.parent.parents):
                    folder.rmdir()
                    if folder == created_root:
                        break
        raise
    return [destination / name for name in produced]


def _write_all(
    staging: Path,
    source: Path,
    track_48k: Samples,
    records: Sequence[UtteranceRecord],
    report_json: str,
    report_md: str,
    voice_volume: float,
    has_video: bool,
) -> list[str]:
    """Genera cada fichero dentro de `staging` y devuelve los nombres producidos."""
    write_float_wav(staging / VOICE_WAV, track_48k)
    _mix_wav(source, staging / VOICE_WAV, staging / MIX_WAV, voice_volume)
    if has_video:
        _mix_mkv(source, staging / MIX_WAV, staging / MIX_MKV)
    transcript = transcription_entries(records)
    translation = translation_entries(records)
    _write_text(staging / TRANSCRIPT_SRT, build_srt(transcript))
    _write_text(staging / TRANSCRIPT_JSON, _segments_json(source, transcript))
    _write_text(staging / TRANSLATION_SRT, build_srt(translation, mark_concise=True))
    _write_text(staging / TRANSLATION_JSON, _segments_json(source, translation))
    _write_text(staging / REPORT_JSON, report_json)
    _write_text(staging / REPORT_MD, report_md)
    return [name for name in OUTPUT_NAMES if (staging / name).exists()]
