"""Traductor Hy-MT2 sobre ``llama-server`` (T022, research R7, ADR-0011).

``HyMt2Translator`` implementa ``Translator`` con el *prompt* final del spike S2
(``spikes/traduccion/README.md``, «Prompt final»):

- Mensaje de sistema con el estilo («español de España», «vosotros»).
- 12 ejemplos fijos de castellano como turnos de chat (el servidor los cachea: ``cache_prompt``).
- Las frases previas de la escena (``request.context``) como turnos de chat.
- Cada turno de usuario va envuelto en la instrucción de traducir (sin ella el modelo obedece las órdenes
  del diálogo en vez de traducirlas).
- Glosario con la plantilla *Terminology* en chino, en el último turno: el del usuario más el base de
  léxico de España (``glossary_es.toml``) filtrado por la frase.

**Modo CONCISE** (solo con el 7B): un único mensaje con la plantilla *Style* «telegraphic Spanish… at most
N words», sin ejemplos, sin contexto y sin glosario: con los 12 ejemplos el modelo no acorta (S2). El 1.8B no
sabe resumir: una petición CONCISE se traduce en modo normal y el resultado lleva ``mode=NORMAL``.

**Filtros de salida**: traducción vacía, sin letras latinas (o con escrituras de otros idiomas), más larga
que 3 veces el original o truncada, y eco del *prompt* (o muletillas del tipo «Aquí tienes la traducción»).
Si salta alguno, el resultado lleva ``rejected=True`` y el texto vacío, y la frase no se pronuncia.
"""

from __future__ import annotations

import functools
import logging
import re
import socket
import tomllib
from collections.abc import Iterable, Sequence
from fractions import Fraction
from importlib import resources
from math import ceil
from typing import Any, Final

import httpx

from instanttraductor.contracts import (
    Clock,
    EngineError,
    GlossaryEntry,
    TranslationMode,
    TranslationRequest,
    TranslationResult,
)
from instanttraductor.mt.selection import MtModel
from instanttraductor.pipeline.clock import SessionClock

__all__ = [
    "BASE_GLOSSARY_RESOURCE",
    "FEWSHOT_ES_ES",
    "HyMt2Translator",
    "build_concise_messages",
    "build_messages",
    "build_normal_messages",
    "concise_word_budget",
    "count_words",
    "load_base_glossary",
    "max_tokens_for",
    "rejection_reason",
    "select_glossary",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Muestreo y petición
# ---------------------------------------------------------------------------
#: Parámetros de muestreo de la model card de Hy-MT2 (1.8B y 7B).
TEMPERATURE: Final = 0.7
TOP_P: Final = 0.6
TOP_K: Final = 20
REPEAT_PENALTY: Final = 1.05
#: Semilla fija, como en S2: la misma entrada da la misma salida (métricas comparables).
SEED: Final = 42

CHAT_PATH: Final = "/v1/chat/completions"
#: Tiempo máximo de una traducción. La p95 con el 7B es de ~0,35 s: si tarda más, el servidor falla.
REQUEST_TIMEOUT_S: Final = 10.0
CONNECT_TIMEOUT_S: Final = 2.0

# ---------------------------------------------------------------------------
# Plantillas del prompt (idénticas a las de S2: no se pueden retocar sin volver a medir)
# ---------------------------------------------------------------------------
#: Mensaje de sistema. El estilo no cambia la variante por sí solo, pero es lo medido en S2.
SYSTEM_PROMPT: Final = (
    "Translate every user message into Spanish. "
    "The translation style must strictly conform to "
    '[natural and concise Spanish from Spain (peninsular); use "vosotros" for the informal plural "you"]. '
    "ONLY output the translated result without any additional explanation."
)
#: Cada turno de usuario envuelto en la plantilla oficial «Default Translation».
TURN_TEMPLATE: Final = (
    "Translate the following text into Spanish. Note that you must ONLY output the translated result "
    "without any additional explanation:\n\n{text}"
)
#: Plantilla oficial «Terminology» en chino (en inglés el glosario se respeta mucho menos: S2).
#: «参考下面的翻译» = «Consulta las traducciones siguientes»; «翻译成» = «se traduce como».
TERMINOLOGY_TEMPLATE: Final = (
    "参考下面的翻译：\n{rows}\n将以下文本翻译为西班牙语，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
)
TERMINOLOGY_ROW: Final = "{source} 翻译成 {target}"
#: Modo CONCISE: plantilla oficial «Style» con estilo telegráfico y tope de palabras (7B, S2).
CONCISE_TEMPLATE: Final = (
    "Please translate the following text into Spanish. Note that the translation style must strictly "
    "conform to [telegraphic Spanish from Spain, like a news headline: drop filler words, "
    "at most {max_words} words]:\n\n{text}"
)

#: 12 ejemplos fijos (inglés, español de España: «vosotros», léxico peninsular) para cebar el estilo.
FEWSHOT_ES_ES: Final[tuple[tuple[str, str], ...]] = (
    (
        "Are you guys hungry? I can make some mashed potatoes.",
        "¿Tenéis hambre? Puedo hacer un puré de patatas.",
    ),
    (
        "Put your sunglasses on, it's really sunny out there.",
        "Ponte las gafas de sol, hace mucho sol ahí fuera.",
    ),
    ("Hey, did you two buy the tickets for tonight?", "Oye, ¿habéis comprado las entradas para esta noche?"),
    ("Come in and sit down, all of you.", "Pasad y sentaos todos."),
    ("That's so cool! I love your t-shirt.", "¡Qué guay! Me encanta tu camiseta."),
    ("Grab a taxi, we'll meet you at the pool.", "Coged un taxi, nos vemos en la piscina."),
    ("You guys are late again. What happened this time?", "Otra vez llegáis tarde. ¿Qué ha pasado esta vez?"),
    ("Pick up your jackets, it's getting cold.", "Coged las chaquetas, que empieza a hacer frío."),
    ("Do you two want to come with us to the supermarket?", "¿Queréis venir con nosotros al supermercado?"),
    ("I can't believe you didn't tell me, man.", "No me puedo creer que no me lo dijeras, tío."),
    ("Turn off the light and go to sleep, kids.", "Apagad la luz y a dormir, niños."),
    ("We'll take the subway to the stadium.", "Cogeremos el metro hasta el estadio."),
)

# ---------------------------------------------------------------------------
# Modo CONCISE: tope de palabras
# ---------------------------------------------------------------------------
#: El resumen debe quedar en el 70 % de lo que saldría normalmente...
CONCISE_RATIO: Final = Fraction(7, 10)
#: ...y en español salen ~1,15 palabras por cada palabra del original.
SPANISH_EXPANSION: Final = Fraction(115, 100)

_WORD = re.compile(r"[\w'’]+")


def count_words(text: str) -> int:
    """Palabras de un texto (una contracción como «you're» cuenta como una)."""
    return len(_WORD.findall(text))


def concise_word_budget(source: str) -> int:
    """Tope N de palabras del modo CONCISE: ``ceil(0,7 × 1,15 × palabras del original)`` (mínimo 1)."""
    return max(1, ceil(CONCISE_RATIO * SPANISH_EXPANSION * count_words(source)))


def max_tokens_for(source: str) -> int:
    """Tope de tokens de salida: ~4 por palabra del original, entre 64 y 512 (S2)."""
    return min(512, max(64, 4 * count_words(source)))


# ---------------------------------------------------------------------------
# Glosario base (léxico de España)
# ---------------------------------------------------------------------------
BASE_GLOSSARY_RESOURCE: Final = "glossary_es.toml"


@functools.cache
def load_base_glossary() -> tuple[GlossaryEntry, ...]:
    """Glosario base inglés → español de España, de ``glossary_es.toml`` (tabla ``[terms]``).

    Se lee con ``importlib.resources`` (va dentro del paquete) y se guarda en memoria. Lanza
    ``ValueError`` si el fichero está mal formado.
    """
    text = resources.files("instanttraductor.mt").joinpath(BASE_GLOSSARY_RESOURCE).read_text(encoding="utf-8")
    terms = tomllib.loads(text).get("terms")
    if not isinstance(terms, dict) or not terms:
        raise ValueError(f"{BASE_GLOSSARY_RESOURCE}: falta la tabla [terms] o está vacía.")
    entries: list[GlossaryEntry] = []
    for source, target in terms.items():
        if not (isinstance(target, str) and source.strip() and target.strip()):
            raise ValueError(f"{BASE_GLOSSARY_RESOURCE}: la entrada {source!r} no es un par de textos.")
        entries.append(GlossaryEntry(source.strip(), target.strip()))
    return tuple(entries)


def _term_pattern(term: str) -> re.Pattern[str]:
    """Palabra (o palabras) completa, sin distinguir mayúsculas, con plural en «s» opcional."""
    words = r"\s+".join(re.escape(part) for part in term.split())
    return re.compile(rf"(?<!\w){words}s?(?!\w)", re.IGNORECASE)


@functools.cache
def _base_matchers() -> tuple[tuple[GlossaryEntry, re.Pattern[str]], ...]:
    return tuple((entry, _term_pattern(entry.source)) for entry in load_base_glossary())


def select_glossary(source: str, user: Iterable[GlossaryEntry] = ()) -> tuple[GlossaryEntry, ...]:
    """Glosario de una frase: el del usuario entero y, después, el base filtrado por la frase.

    - Del base solo entran las entradas cuyo término aparece en ``source`` como palabra completa (con
      plural en «s»), para no engordar el *prompt*.
    - Si el usuario define un término que también está en el base, manda el del usuario.
    - Se ignoran las entradas con el origen o el destino en blanco.
    """
    chosen: list[GlossaryEntry] = []
    seen: set[str] = set()
    for entry in user:
        key = entry.source.strip().casefold()
        if key and entry.target.strip() and key not in seen:
            seen.add(key)
            chosen.append(entry)
    for entry, pattern in _base_matchers():
        if entry.source.casefold() not in seen and pattern.search(source):
            chosen.append(entry)
    return tuple(chosen)


# ---------------------------------------------------------------------------
# Construcción de los mensajes
# ---------------------------------------------------------------------------
Message = dict[str, str]


def build_normal_messages(
    source: str,
    context: Iterable[tuple[str, str]] = (),
    glossary: Sequence[GlossaryEntry] = (),
) -> list[Message]:
    """Mensajes del modo NORMAL: sistema, 12 ejemplos, contexto y el turno final (con glosario si hay)."""
    messages: list[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
    previous = [*FEWSHOT_ES_ES, *((o.strip(), t.strip()) for o, t in context if o.strip() and t.strip())]
    for original, translation in previous:
        messages.append({"role": "user", "content": TURN_TEMPLATE.format(text=original)})
        messages.append({"role": "assistant", "content": translation})
    if glossary:
        rows = "\n".join(TERMINOLOGY_ROW.format(source=g.source, target=g.target) for g in glossary)
        last = TERMINOLOGY_TEMPLATE.format(rows=rows, text=source)
    else:
        last = TURN_TEMPLATE.format(text=source)
    messages.append({"role": "user", "content": last})
    return messages


def build_concise_messages(source: str, max_words: int | None = None) -> list[Message]:
    """Mensajes del modo CONCISE: un único mensaje de usuario con la plantilla *Style* telegráfica."""
    budget = concise_word_budget(source) if max_words is None else max_words
    return [{"role": "user", "content": CONCISE_TEMPLATE.format(max_words=budget, text=source)}]


def build_messages(
    source: str,
    mode: TranslationMode,
    context: Iterable[tuple[str, str]] = (),
    glossary: Sequence[GlossaryEntry] = (),
) -> list[Message]:
    """Mensajes de chat de una petición, según el modo."""
    if mode is TranslationMode.CONCISE:
        return build_concise_messages(source)
    return build_normal_messages(source, context, glossary)


# ---------------------------------------------------------------------------
# Filtros de salida
# ---------------------------------------------------------------------------
#: La salida no puede ser más larga que esto por el original (en caracteres).
MAX_LENGTH_RATIO: Final = 3

#: Letras latinas: ASCII, Latin-1 y Latin extendido (á, ñ, ü...).
_LATIN_LETTER = re.compile(r"[A-Za-zÀ-ÖØ-öø-ɏ]")
#: Escrituras que no son español: cirílico, árabe, hebreo, kana, CJK, hangul y signos de ancho completo.
_FOREIGN_SCRIPT = re.compile("[Ѐ-ӿ֐-׿؀-ۿ　-ヿ㐀-䶿一-鿿가-힯＀-￯]")

#: Frases de las plantillas del *prompt* (en inglés y traducidas) que no deben salir en una traducción.
#: Si el propio original contiene alguna, no se puede distinguir un eco de una traducción fiel: no se filtra.
_PROMPT_MARKERS: Final = (
    "translate every user message",
    "translate the following text",
    "only output the translated result",
    "any additional explanation",
    "translation style must strictly conform",
    "reference the following translations",
    "telegraphic spanish",
    "natural and concise spanish",
    "[source text]",
    "[background information]",
    "[translation tasks]",
    "[texto de origen]",
    "[texto original]",
    "[información de fondo]",
    "[tareas de traducción]",
    "traduce el siguiente texto",
    "traduce todos los mensajes",
    "sin ninguna explicación adicional",
    "sin explicaciones adicionales",
    "sin explicación adicional",
    "el resultado traducido",
)
#: Etiqueta al principio de la salida («[Source Text]», «Spanish:»).
_LABEL_START = re.compile(
    r"^\s*(?:[\[<]\s*(?:spanish|español|english|inglés|source\s+text|texto\s+(?:de\s+origen|original|fuente)"
    r"|background(?:\s+information)?|información\s+de\s+fondo)\s*[\]>]"
    r"|(?:spanish|español|english|inglés)\s*:)",
    re.IGNORECASE,
)
#: Muletillas del modelo al principio de la salida («Aquí tienes la traducción:», «Translation:»).
#: Solo las inequívocas: «Claro, ...» o «Aquí tienes tu café» son frases de diálogo válidas.
_BOILERPLATE_START = re.compile(
    r"^\W*(?:"
    r"aqu[ií]\s+(?:tienes|est[aá]|va|te\s+dejo)\s+(?:la|tu|el|una)\s+traducci[oó]n"
    r"|(?:esta|esa)\s+es\s+la\s+traducci[oó]n"
    r"|la\s+traducci[oó]n\s+(?:es|ser[ií]a)\b"
    r"|(?:traducci[oó]n|translation|texto\s+traducido|translated\s+text)\s*:"
    r"|here(?:'s|\s+is)\s+(?:the|your)\s+translation"
    r"|(?:nota|note)\s*:"
    r")",
    re.IGNORECASE,
)


def _echoes_the_prompt(source: str, text: str) -> bool:
    folded, source_folded = text.casefold(), source.casefold()
    if any(marker in source_folded for marker in _PROMPT_MARKERS):
        return False  # el propio original habla de traducir: su traducción puede decir lo mismo
    if any(marker in folded for marker in _PROMPT_MARKERS):
        return True
    for pattern in (_LABEL_START, _BOILERPLATE_START):
        match = pattern.match(text)
        if match and match.group(0).strip().casefold() not in source_folded:
            return True
    return False


def rejection_reason(source: str, output: str, *, finish_reason: str | None = None) -> str | None:
    """Motivo por el que ``output`` no vale como traducción de ``source``, o ``None`` si pasa los filtros.

    - ``"vacía"``: no hay texto.
    - ``"idioma"``: ninguna letra latina, o letras de otras escrituras (chino, japonés, cirílico...).
    - ``"longitud"``: más de 3 veces el original (en caracteres) o cortada por ``max_tokens``.
    - ``"eco del prompt"``: repite el *prompt* (instrucciones, etiquetas) o empieza con una muletilla.
    """
    text = output.strip()
    if not text:
        return "vacía"
    if not _LATIN_LETTER.search(text) or _FOREIGN_SCRIPT.search(text):
        return "idioma"
    if finish_reason == "length" or len(text) > MAX_LENGTH_RATIO * len(source.strip()):
        return "longitud"
    if _echoes_the_prompt(source, text):
        return "eco del prompt"
    return None


# ---------------------------------------------------------------------------
# Traductor
# ---------------------------------------------------------------------------
class HyMt2Translator:
    """``Translator`` de Hy-MT2 (7B o reserva 1.8B) sobre un ``llama-server`` ya listo.

    - ``base_url``: URL de ``llama-server`` (``LlamaServerProcess.base_url``).
    - ``model_kind``: ``MtModel`` (o ``"7b"``, ``"1.8b"``, o su ``component_id``). ``supports_concise`` vale
      ``True`` solo con el 7B; ``name`` es el ``component_id`` (el ``mt_model`` del informe).
    - ``clock``: reloj de sesión para ``started_at`` y ``finished_at``. La sesión debe pasar el suyo; si no
      se da, usa un ``SessionClock`` propio que arranca al construir el traductor.
    - ``timeout_s``: tiempo máximo de cada petición. ``transport``: solo en los tests (``MockTransport``).

    ``translate`` lanza ``EngineError`` (con ``engine=name``) si el servidor no responde o responde mal; es
    recuperable salvo en los errores 4xx. Es seguro llamarlo desde varios hilos.
    """

    def __init__(
        self,
        base_url: str,
        model_kind: MtModel | str,
        *,
        clock: Clock | None = None,
        timeout_s: float = REQUEST_TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = MtModel.parse(model_kind)
        self.name: str = self.model.value
        self.supports_concise: bool = self.model.supports_concise
        self._clock: Clock = clock if clock is not None else SessionClock()
        if transport is None:
            # TCP_NODELAY: sin él, el algoritmo de Nagle puede añadir decenas de ms por petición.
            transport = httpx.HTTPTransport(socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)])
        self._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_s, connect=min(timeout_s, CONNECT_TIMEOUT_S)),
            transport=transport,
            trust_env=False,  # solo se habla con 127.0.0.1: nada de proxys del entorno
        )
        self._closed = False

    def __repr__(self) -> str:
        return f"HyMt2Translator(name={self.name!r}, base_url={str(self._client.base_url)!r})"

    # -- Translator ------------------------------------------------------------
    def translate(self, request: TranslationRequest) -> TranslationResult:
        """Traduce una unidad. El resultado conserva ``unit_id`` y lleva el modo realmente aplicado."""
        started_at = self._clock.now()
        mode = request.mode
        if mode is TranslationMode.CONCISE and not self.supports_concise:
            mode = TranslationMode.NORMAL  # el 1.8B no sabe resumir (ADR-0011)
        source = request.unit.source_text.strip()

        reason: str | None
        text = ""
        if not source:
            reason = "vacía"
        else:
            glossary = () if mode is TranslationMode.CONCISE else select_glossary(source, request.glossary)
            messages = build_messages(source, mode, request.context, glossary)
            output, finish_reason = self._complete(messages, max_tokens_for(source))
            reason = rejection_reason(source, output, finish_reason=finish_reason)
            if reason is None:
                text = output.strip()
        if reason is not None:
            logger.warning("Traducción rechazada (%s): unidad %d", reason, request.unit.unit_id)
        return TranslationResult(
            unit_id=request.unit.unit_id,
            text=text,
            mode=mode,
            started_at=started_at,
            finished_at=self._clock.now(),
            rejected=reason is not None,
        )

    def close(self) -> None:
        """Cierra la conexión con el servidor (idempotente). No para a ``llama-server``."""
        self._closed = True
        self._client.close()

    # -- HTTP ------------------------------------------------------------------
    def _complete(self, messages: list[Message], max_tokens: int) -> tuple[str, str | None]:
        """Pide la traducción a ``/v1/chat/completions``; devuelve ``(texto, finish_reason)``."""
        if self._closed:
            raise EngineError("El traductor está cerrado.", engine=self.name, recoverable=False)
        body: dict[str, Any] = {
            "messages": messages,
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "top_k": TOP_K,
            "repeat_penalty": REPEAT_PENALTY,
            "max_tokens": max_tokens,
            "seed": SEED,
            "cache_prompt": True,
            "stream": False,
        }
        try:
            response = self._client.post(CHAT_PATH, json=body)
        except httpx.HTTPError as error:
            raise EngineError(
                f"No se pudo hablar con llama-server: {error!r}", engine=self.name, recoverable=True
            ) from error
        if response.status_code != 200:
            raise EngineError(
                f"llama-server respondió {response.status_code}: {response.text[:200]}",
                engine=self.name,
                recoverable=not 400 <= response.status_code < 500,  # un 4xx se repetiría igual
            )
        try:
            choice = response.json()["choices"][0]
            content = choice["message"].get("content") or ""
            finish_reason = choice.get("finish_reason")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise EngineError(
                f"Respuesta no válida de llama-server: {response.text[:200]}",
                engine=self.name,
                recoverable=True,
            ) from error
        return str(content), finish_reason if isinstance(finish_reason, str) else None
