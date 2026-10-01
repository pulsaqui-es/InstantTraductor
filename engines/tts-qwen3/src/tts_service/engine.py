"""Motor de voz: Qwen3-TTS-12Hz-0.6B-Base sobre faster-qwen3-tts (T025, research R8, ADR-0008).

Se porta de ``spikes/voz/qwen3/bench_qwen3.py`` y ``spikes/voz/common/vozbench.py``. Lo medido en el spike S1
(RTX 5070, Windows nativo, sm_120) y fijado aquí:

- Carga en bf16 con atención SDPA y ``max_seq_len=2048`` (6,1 s), ``warmup()`` que captura los CUDA graphs
  (0,84 s) y unas síntesis de calentamiento: sin ellas, la primera petición tarda 1,4 s.
- ``chunk_size=4`` (333 ms de audio por trozo): primer audio p95 de 182 ms y RTF de 0,41.
- Modo ICL con la referencia de cada voz (``ref_text`` en su JSON), con el *prompt* creado una sola vez al
  arrancar (0,5 s por voz) y guardado en caché. Se añaden 0,5 s de silencio al final de la referencia
  contra el *phoneme bleeding* del modo ICL.
- ``x_vector_only`` como rescate: solo el *embedding* del hablante. Se usa en las voces sin ``ref_text``, si
  falla la creación del *prompt* ICL o en todas las voces con ``--x-vector-only`` (acento que se desvía o
  arranque en frío; gana 15-20 ms de primer audio y 0,5 GiB de VRAM, a costa del parecido de la voz).
- Audio PCM ``float32`` mono a 24 kHz. Qwen3-TTS Base no tiene parámetro de velocidad: ``speed`` se ignora
  (``supports_speed = False``) y el núcleo acelera con *time-stretch* (research R9).

Este módulo no importa ``torch`` ni ``faster_qwen3_tts`` al cargarse: solo ``load_engine`` (y ``vram_mb``) lo
hacen, así que el servidor y sus tests funcionan sin GPU con un motor falso (el protocolo ``Engine``).
"""

from __future__ import annotations

import contextlib
import gc
import json
import logging
import re
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, Protocol

import numpy as np
import numpy.typing as npt

__all__ = [
    "CHUNK_SIZE",
    "ENGINE_NAME",
    "LANGUAGE",
    "MODEL_DIR_NAME",
    "MODEL_NAME",
    "Engine",
    "EngineLoadError",
    "Qwen3Engine",
    "ServiceConfig",
    "UnknownVoiceError",
    "Voice",
    "VoiceCatalogError",
    "load_engine",
    "load_voices",
]

logger = logging.getLogger(__name__)

Samples = npt.NDArray[np.float32]
Gender = Literal["f", "m"]

#: Nombre del motor en la línea ``ready`` y en ``/health`` (el ``component_id`` del manifiesto).
ENGINE_NAME: Final = "qwen3-tts"
MODEL_NAME: Final = "Qwen3-TTS-12Hz-0.6B-Base"
#: Carpeta del modelo dentro de ``--models-dir`` (la de ``component_dir("qwen3-tts")`` del núcleo).
MODEL_DIR_NAME: Final = "qwen3-tts-12hz-0.6b-base"
#: Idioma de síntesis: el servicio solo habla español (de España: lo da la referencia de cada voz).
LANGUAGE: Final = "Spanish"
#: Pasos de códec por trozo (1 paso = 83 ms de audio): TTFA p95 de 182 ms en el spike S1.
CHUNK_SIZE: Final = 4
MAX_SEQ_LEN: Final = 2048
#: Longitud de *prefill* simulada para capturar los CUDA graphs (el grafo no depende de la posición).
WARMUP_PREFILL_LEN: Final = 100
WARMUP_TEXT: Final = "Vale, nos vemos luego en casa de Laura."
WARMUP_REQUESTS: Final = 2
#: Silencio que se añade al final de la referencia en modo ICL.
REFERENCE_SILENCE_S: Final = 0.5

_VOICE_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_MIB: Final = 1024 * 1024


class EngineLoadError(RuntimeError):
    """El motor no puede arrancar (falta el modelo, no hay CUDA, voces no válidas...)."""


class VoiceCatalogError(EngineLoadError):
    """La carpeta de voces no existe, está vacía o tiene voces mal definidas."""


class UnknownVoiceError(KeyError):
    """Se pidió una voz que el motor no tiene."""


# ---------------------------------------------------------------------------
# Voces
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Voice:
    """Una voz del catálogo: su referencia (``<voice_id>.wav``) y sus metadatos (``<voice_id>.json``)."""

    voice_id: str
    name: str
    gender: Gender
    source: str
    license: str
    wav_path: Path
    ref_text: str = ""  # lo que dice la referencia: lo necesita el modo ICL

    def public(self) -> dict[str, str]:
        """Los campos de ``VoiceInfo`` que publica ``GET /voices`` (sin ``ref_text`` ni rutas)."""
        return {
            "voice_id": self.voice_id,
            "name": self.name,
            "gender": self.gender,
            "source": self.source,
            "license": self.license,
        }


def _required_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"falta «{key}» o no es un texto")
    return value.strip()


def _read_voice(json_path: Path) -> Voice:
    """Lee ``<id>.json`` y comprueba que existe ``<id>.wav``. Lanza ``ValueError`` con el motivo."""
    voice_id = json_path.stem
    if not _VOICE_ID.fullmatch(voice_id):
        raise ValueError("el nombre del fichero debe ser el identificador ASCII de la voz")
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"no se puede leer ({error})") from error
    except ValueError as error:  # JSONDecodeError y UnicodeDecodeError
        raise ValueError(f"JSON no válido ({error})") from error
    if not isinstance(data, dict):
        raise ValueError("debe ser un objeto JSON")
    declared = data.get("voice_id", voice_id)
    if declared != voice_id:
        raise ValueError(f"«voice_id» ({declared!r}) no coincide con el nombre del fichero")
    gender = data.get("gender")
    if gender not in ("f", "m"):
        raise ValueError("«gender» debe ser «f» o «m»")
    ref_text = data.get("ref_text", "")
    if not isinstance(ref_text, str):
        raise ValueError("«ref_text» debe ser un texto")
    wav_path = json_path.with_suffix(".wav")
    if not wav_path.is_file():
        raise ValueError(f"falta la referencia {wav_path.name}")
    return Voice(
        voice_id=voice_id,
        name=_required_text(data, "name"),
        gender=gender,
        source=_required_text(data, "source"),
        license=_required_text(data, "license"),
        wav_path=wav_path,
        ref_text=ref_text.strip(),
    )


def load_voices(voices_dir: Path) -> tuple[Voice, ...]:
    """Las voces de ``voices_dir``: cada ``<id>.json`` con su ``<id>.wav``, ordenadas por identificador.

    Lanza ``VoiceCatalogError`` si la carpeta no existe, no tiene voces o alguna está mal definida (se
    listan todos los problemas a la vez).
    """
    if not voices_dir.is_dir():
        raise VoiceCatalogError(
            f"No existe la carpeta de voces {voices_dir}: ejecuta «instanttraductor preparar»."
        )
    voices: list[Voice] = []
    problems: list[str] = []
    for json_path in sorted(voices_dir.glob("*.json")):
        try:
            voices.append(_read_voice(json_path))
        except ValueError as error:
            problems.append(f"{json_path.name}: {error}")
    if problems:
        details = "\n".join(f"  - {problem}" for problem in problems)
        raise VoiceCatalogError(f"Voces no válidas en {voices_dir}:\n{details}")
    if not voices:
        raise VoiceCatalogError(f"No hay voces en {voices_dir}: ejecuta «instanttraductor preparar».")
    return tuple(voices)


# ---------------------------------------------------------------------------
# Protocolo del motor y configuración
# ---------------------------------------------------------------------------
class Engine(Protocol):
    """Lo que el servidor necesita de un motor de voz. Sirve cualquier clase que lo cumpla.

    Los tests usan un motor falso. Todas las llamadas llegan desde el mismo hilo, de una en una (lo garantiza
    el servidor).
    """

    name: str  # identificador del motor (línea ``ready`` y ``/health``)
    model_name: str  # nombre del modelo (``/health``)
    sample_rate: int
    supports_speed: bool  # False: el núcleo aplica el time-stretch

    def voices(self) -> Sequence[Voice]: ...

    def synthesize(self, text: str, voice_id: str, speed: float) -> Iterator[Samples]:
        """Audio PCM ``float32`` mono en trozos, según se genera. ``UnknownVoiceError`` si no hay esa voz."""
        ...

    def vram_mb(self) -> int: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    """Lo que el motor recibe de la línea de comandos."""

    voices_dir: Path
    models_dir: Path
    chunk_size: int = CHUNK_SIZE
    x_vector_only: bool = False


# ---------------------------------------------------------------------------
# Qwen3-TTS
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _VoicePrompt:
    """El *prompt* de clonación de una voz, creado al arrancar."""

    items: Any  # lista de ``VoiceClonePromptItem`` de qwen-tts
    ref_text: str  # vacío en x_vector_only
    x_vector_only: bool


def _read_reference(path: Path) -> tuple[Samples, int]:
    """La referencia como mono ``float32`` y su frecuencia (qwen-tts la remuestrea por dentro)."""
    import soundfile

    audio, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    return np.ascontiguousarray(audio.mean(axis=1), dtype=np.float32), int(rate)


class Qwen3Engine:
    """``Engine`` sobre ``FasterQwen3TTS`` (CUDA graphs) con el *prompt* de cada voz en caché.

    ``model`` es el ``FasterQwen3TTS`` ya cargado (``load_engine`` lo crea; los tests, uno falso). Construir
    el motor crea el *prompt* de clonación de todas las voces, que es lo que tarda 0,5 s por voz.
    """

    name = ENGINE_NAME
    model_name = MODEL_NAME
    supports_speed = False

    def __init__(
        self,
        model: Any,
        voices: Sequence[Voice],
        *,
        chunk_size: int = CHUNK_SIZE,
        x_vector_only: bool = False,
    ) -> None:
        if not voices:
            raise ValueError("Hace falta al menos una voz.")
        if chunk_size < 1:
            raise ValueError(f"chunk_size debe ser al menos 1 (recibido {chunk_size}).")
        self._model: Any = model
        self.sample_rate = int(model.sample_rate)
        self._chunk_size = chunk_size
        self._force_x_vector = x_vector_only
        self._voices = {voice.voice_id: voice for voice in voices}
        self._prompts: dict[str, _VoicePrompt] = {}
        self.load_vram_mib = 0.0  # lo que subió el uso de la GPU al cargar (lo rellena ``load_engine``)
        for voice in voices:
            started = time.perf_counter()
            self._prompts[voice.voice_id] = self._build_prompt(voice)
            mode = "x_vector_only" if self._prompts[voice.voice_id].x_vector_only else "ICL"
            logger.info(
                "Voz «%s» lista (modo %s, prompt en %.2f s)",
                voice.voice_id,
                mode,
                time.perf_counter() - started,
            )

    # -- voces y prompts ---------------------------------------------------------------------------
    def voices(self) -> tuple[Voice, ...]:
        return tuple(self._voices.values())

    def _build_prompt(self, voice: Voice) -> _VoicePrompt:
        if self._force_x_vector:
            return self._x_vector_prompt(voice)
        if not voice.ref_text:
            logger.warning("La voz «%s» no tiene ref_text: se usa x_vector_only.", voice.voice_id)
            return self._x_vector_prompt(voice)
        try:
            return self._icl_prompt(voice)
        except Exception:
            logger.exception(
                "No se pudo crear el prompt ICL de «%s»: rescate con x_vector_only.", voice.voice_id
            )
            return self._x_vector_prompt(voice)

    def _icl_prompt(self, voice: Voice) -> _VoicePrompt:
        audio, rate = _read_reference(voice.wav_path)
        silence = np.zeros(round(REFERENCE_SILENCE_S * rate), dtype=np.float32)
        items = self._model.model.create_voice_clone_prompt(
            ref_audio=(np.concatenate([audio, silence]), rate), ref_text=voice.ref_text
        )
        return _VoicePrompt(items, voice.ref_text, x_vector_only=False)

    def _x_vector_prompt(self, voice: Voice) -> _VoicePrompt:
        items = self._model.model.create_voice_clone_prompt(
            ref_audio=str(voice.wav_path), ref_text="", x_vector_only_mode=True
        )
        return _VoicePrompt(items, "", x_vector_only=True)

    # -- calentamiento y síntesis ---------------------------------------------------------------------
    def warmup(self) -> None:
        """Captura los CUDA graphs y hace unas síntesis cortas con la primera voz.

        Sin este calentamiento, la primera petición tarda 1,4 s en dar audio.
        """
        started = time.perf_counter()
        self._model.warmup(prefill_len=WARMUP_PREFILL_LEN)
        voice_id = next(iter(self._voices))
        for _ in range(WARMUP_REQUESTS):
            for _chunk in self.synthesize(WARMUP_TEXT, voice_id, 1.0):
                pass
        logger.info("Calentamiento hecho en %.2f s", time.perf_counter() - started)

    def synthesize(self, text: str, voice_id: str, speed: float) -> Iterator[Samples]:
        """Síntesis en streaming con el *prompt* de la voz en caché. ``speed`` se ignora: no hay parámetro."""
        prompt = self._prompts.get(voice_id)
        if prompt is None:
            raise UnknownVoiceError(voice_id)
        stream = self._model.generate_voice_clone_streaming(
            text=text,
            language=LANGUAGE,
            ref_text=prompt.ref_text,
            voice_clone_prompt=prompt.items,
            chunk_size=self._chunk_size,
            xvec_only=prompt.x_vector_only,
        )
        try:
            for audio, _sample_rate, _timing in stream:
                yield np.asarray(audio, dtype=np.float32).reshape(-1)
        finally:
            stream.close()

    # -- recursos ----------------------------------------------------------------------------------------
    def vram_mb(self) -> int:
        """VRAM del proceso en MiB: lo que subió la GPU al cargar o, si es más, lo que reserva torch."""
        reserved = 0.0
        with contextlib.suppress(Exception):
            import torch

            if torch.cuda.is_available():
                reserved = torch.cuda.memory_reserved() / _MIB
        return round(max(self.load_vram_mib, reserved))

    def close(self) -> None:
        """Suelta el modelo y la memoria de la GPU. Es idempotente."""
        self._prompts.clear()
        self._model = None
        gc.collect()
        with contextlib.suppress(Exception):
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()


# ---------------------------------------------------------------------------
# Carga del motor real
# ---------------------------------------------------------------------------
def _gpu_used_mib() -> float | None:
    """VRAM usada en total en la GPU 0 (NVML, lo mismo que ``nvidia-smi``), o ``None`` si no se puede leer."""
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            return pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0)).used / _MIB
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return None


def load_engine(config: ServiceConfig) -> Qwen3Engine:
    """Carga Qwen3-TTS en la GPU, crea el *prompt* de cada voz y lo calienta. Tarda unos 10 s.

    Lanza ``EngineLoadError`` si falta el modelo o no hay CUDA, y ``VoiceCatalogError`` si las voces no valen.
    """
    started = time.perf_counter()
    voices = load_voices(config.voices_dir)  # las voces primero: es lo barato que más suele fallar
    model_dir = config.models_dir / MODEL_DIR_NAME
    if not (model_dir / "config.json").is_file():
        raise EngineLoadError(f"Falta el modelo en {model_dir}: ejecuta «instanttraductor preparar».")

    import torch

    if not torch.cuda.is_available():
        raise EngineLoadError("CUDA no está disponible: Qwen3-TTS con CUDA graphs necesita la GPU NVIDIA.")
    from faster_qwen3_tts import FasterQwen3TTS

    baseline_mib = _gpu_used_mib()
    model = FasterQwen3TTS.from_pretrained(
        str(model_dir),
        device="cuda",
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
        max_seq_len=MAX_SEQ_LEN,
    )
    logger.info("Modelo cargado en %.1f s", time.perf_counter() - started)
    engine = Qwen3Engine(model, voices, chunk_size=config.chunk_size, x_vector_only=config.x_vector_only)
    engine.warmup()
    used_mib = _gpu_used_mib()
    if baseline_mib is not None and used_mib is not None:
        engine.load_vram_mib = max(0.0, used_mib - baseline_mib)
    logger.info(
        "Motor listo en %.1f s (VRAM %d MiB, %d voces)",
        time.perf_counter() - started,
        engine.vram_mb(),
        len(voices),
    )
    return engine
