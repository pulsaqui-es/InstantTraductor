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

**Idioma de origen** (spec 002, R10): ``request.source_language`` (en, ja, zh o ko). Con ja, zh y ko el
sistema y el turno final nombran el idioma («Translate the following Japanese text...»); con en el *prompt*
es el medido en S2 y S7, sin cambios. El filtro de longitud y ``max_tokens`` dependen del idioma (ja y zh
miden en caracteres, porque ``count_words`` cuenta una tira de ideogramas como una palabra) y el glosario
base de España solo actúa con origen en inglés.

**«Vosotros»** (spec 002, R8, solo con origen en inglés; ver ``mt/vosotros.py``): si las últimas 5 líneas en
inglés del contexto indican un grupo, el turno final lleva una nota de estilo de plural informal; se recorta
de la salida la nota que el modelo repite; se aplica la posedición por reglas; y, si aun así queda «ustedes»
con esa señal de grupo, se reintenta una vez con una nota más explícita (se queda con el reintento si sale
«vosotros» y no «ustedes»). El modo CONCISE lleva en su cláusula de estilo el registro informal.

**Filtros de salida**: traducción vacía, sin letras latinas (o con escrituras de otros idiomas), más larga
que 3 veces el original (en: 4 ko, 6 ja, 7 zh) o truncada, y eco del *prompt* (o muletillas del tipo «Aquí
tienes la traducción»). Si salta alguno, el resultado lleva ``rejected=True`` y el texto vacío, y la frase
no se pronuncia.
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
    SourceLanguage,
    TranslationMode,
    TranslationRequest,
    TranslationResult,
)
from instanttraductor.mt.selection import MtModel
from instanttraductor.mt.vosotros import (
    PLURAL_NOTE,
    RETRY_NOTE,
    clean_output,
    group_state,
    has_ustedes,
    has_vosotros,
    needs_vosotros_retry,
    postedit_vosotros,
)
from instanttraductor.pipeline.clock import SessionClock

__all__ = [
    "BASE_GLOSSARY_RESOURCE",
    "FEWSHOT_ES_ES",
    "LANGUAGE_NAMES",
    "MAX_LENGTH_RATIO_BY_LANGUAGE",
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
_SYSTEM_STYLE: Final = (
    "The translation style must strictly conform to "
    '[natural and concise Spanish from Spain (peninsular); use "vosotros" for the informal plural "you"]. '
    "ONLY output the translated result without any additional explanation."
)
SYSTEM_PROMPT: Final = "Translate every user message into Spanish. " + _SYSTEM_STYLE
#: Mensaje de sistema con origen ja, zh o ko: nombra el idioma de origen (R10).
SYSTEM_PROMPT_FROM: Final = "Translate every user message from {language} into Spanish. " + _SYSTEM_STYLE
#: Cada turno de usuario envuelto en la plantilla oficial «Default Translation».
TURN_TEMPLATE: Final = (
    "Translate the following text into Spanish. Note that you must ONLY output the translated result "
    "without any additional explanation:\n\n{text}"
)
#: El mismo turno, nombrando el idioma de origen (solo el turno final con ja, zh o ko).
TURN_TEMPLATE_FROM: Final = (
    "Translate the following {language} text into Spanish. Note that you must ONLY output the translated "
    "result without any additional explanation:\n\n{text}"
)
#: Nombre en inglés de cada idioma de origen, tal como va en el *prompt*.
LANGUAGE_NAMES: Final[dict[SourceLanguage, str]] = {
    SourceLanguage.EN: "English",
    SourceLanguage.JA: "Japanese",
    SourceLanguage.ZH: "Chinese",
    SourceLanguage.KO: "Korean",
}
#: Plantilla oficial «Terminology» en chino (en inglés el glosario se respeta mucho menos: S2).
#: «参考下面的翻译» = «Consulta las traducciones siguientes»; «翻译成» = «se traduce como».
TERMINOLOGY_TEMPLATE: Final = (
    "参考下面的翻译：\n{rows}\n将以下文本翻译为西班牙语，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
)
TERMINOLOGY_ROW: Final = "{source} 翻译成 {target}"
#: Modo CONCISE: plantilla oficial «Style» con estilo telegráfico, tope de palabras (7B, S2) y registro
#: informal con «vosotros» (S7, B1e: sin la cláusula solo el 2 % de los plurales salía en «vosotros»).
CONCISE_TEMPLATE: Final = (
    "Please translate the following text into Spanish. Note that the translation style must strictly "
    "conform to [telegraphic Spanish from Spain, like a news headline: drop filler words, "
    "at most {max_words} words; "
    'informal register: several listeners = "vosotros" (estáis, tenéis, venid), one listener = "tú"]:'
    "\n\n{text}"
)
#: La misma plantilla CONCISE nombrando el idioma de origen (ja, zh y ko).
CONCISE_TEMPLATE_FROM: Final = (
    "Please translate the following {language} text into Spanish. Note that the translation style must "
    "strictly conform to [telegraphic Spanish from Spain, like a news headline: drop filler words, "
    "at most {max_words} words; "
    'informal register: several listeners = "vosotros" (estáis, tenéis, venid), one listener = "tú"]:'
    "\n\n{text}"
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
#: Tope del resumen: el 60 % de las palabras del original (configuración medida en el spike S2: −33 %)...
CONCISE_RATIO: Final = Fraction(3, 5)
#: ...sin factor de expansión: en S2 el español salió con 0,995 palabras por palabra inglesa.
SPANISH_EXPANSION: Final = Fraction(1)

_WORD = re.compile(r"[\w'’]+")

#: Idiomas sin espacios entre palabras: ``count_words`` cuenta una frase entera como una sola palabra.
_UNSPACED_LANGUAGES: Final = frozenset({SourceLanguage.JA, SourceLanguage.ZH})
#: Palabras españolas por carácter de origen en ja y zh: relación de caracteres de S5 (p50 de 3,9 en ja y 2,8
#: en zh) entre ~5,8 caracteres por palabra española con su espacio. Solo se usa en el tope del modo CONCISE.
_SPANISH_WORDS_PER_CHAR: Final[dict[SourceLanguage, Fraction]] = {
    SourceLanguage.JA: Fraction(13, 20),
    SourceLanguage.ZH: Fraction(1, 2),
}
#: Tokens de salida por carácter de origen en ja y zh: el máximo de S5 fue de 5 caracteres de salida por
#: carácter de origen, unos 1,7 tokens; con 3 sobra para no truncar y el tope sigue acotado.
TOKENS_PER_SOURCE_CHAR: Final = 3


def count_words(text: str) -> int:
    """Palabras de un texto (una contracción como «you're» cuenta como una)."""
    return len(_WORD.findall(text))


def count_characters(text: str) -> int:
    """Caracteres con contenido (letras, ideogramas, kana, hangul y cifras): sin espacios ni signos."""
    return sum(1 for char in text if char.isalnum())


def _source_words(source: str, source_language: SourceLanguage) -> int:
    """Palabras del original; en ja y zh, las palabras españolas que cabe esperar por sus caracteres."""
    if source_language in _UNSPACED_LANGUAGES:
        return ceil(_SPANISH_WORDS_PER_CHAR[source_language] * count_characters(source))
    return count_words(source)


def concise_word_budget(source: str, source_language: SourceLanguage = SourceLanguage.EN) -> int:
    """Tope N de palabras del modo CONCISE: ``ceil(0,6 × palabras del original)`` (mínimo 1)."""
    return max(1, ceil(CONCISE_RATIO * SPANISH_EXPANSION * _source_words(source, source_language)))


def max_tokens_for(source: str, source_language: SourceLanguage = SourceLanguage.EN) -> int:
    """Tope de tokens de salida (64 a 512): ~4 por palabra del original (S2); en ja y zh, 3 por carácter."""
    if source_language in _UNSPACED_LANGUAGES:
        return min(512, max(64, TOKENS_PER_SOURCE_CHAR * count_characters(source)))
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


def select_glossary(
    source: str,
    user: Iterable[GlossaryEntry] = (),
    *,
    source_language: SourceLanguage = SourceLanguage.EN,
) -> tuple[GlossaryEntry, ...]:
    """Glosario de una frase: el del usuario entero y, después, el base filtrado por la frase.

    - Del base (inglés → español de España) solo entran las entradas cuyo término aparece en ``source`` como
      palabra completa (con plural en «s»), para no engordar el *prompt*. Con origen ja, zh o ko no entra
      ninguna: sus términos están en inglés.
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
    if source_language is not SourceLanguage.EN:
        return tuple(chosen)
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
    *,
    source_language: SourceLanguage = SourceLanguage.EN,
    plural_note: bool = False,
) -> list[Message]:
    """Mensajes del modo NORMAL: sistema, 12 ejemplos, contexto y el turno final (con glosario si hay).

    Con ``source_language`` ja, zh o ko el sistema y el turno final nombran el idioma; los ejemplos y el
    contexto van con la plantilla genérica. Con ``plural_note`` el turno final lleva, tras el texto, la nota
    de plural informal (``vosotros``).
    """
    named = source_language is not SourceLanguage.EN
    language = LANGUAGE_NAMES[source_language]
    system = SYSTEM_PROMPT_FROM.format(language=language) if named else SYSTEM_PROMPT
    messages: list[Message] = [{"role": "system", "content": system}]
    previous = [*FEWSHOT_ES_ES, *((o.strip(), t.strip()) for o, t in context if o.strip() and t.strip())]
    for original, translation in previous:
        messages.append({"role": "user", "content": TURN_TEMPLATE.format(text=original)})
        messages.append({"role": "assistant", "content": translation})
    if glossary:
        rows = "\n".join(TERMINOLOGY_ROW.format(source=g.source, target=g.target) for g in glossary)
        last = TERMINOLOGY_TEMPLATE.format(rows=rows, text=source)
    elif named:
        last = TURN_TEMPLATE_FROM.format(language=language, text=source)
    else:
        last = TURN_TEMPLATE.format(text=source)
    if plural_note:
        last += PLURAL_NOTE
    messages.append({"role": "user", "content": last})
    return messages


def build_concise_messages(
    source: str, max_words: int | None = None, source_language: SourceLanguage = SourceLanguage.EN
) -> list[Message]:
    """Mensajes del modo CONCISE: un único mensaje de usuario con la plantilla *Style* telegráfica."""
    budget = concise_word_budget(source, source_language) if max_words is None else max_words
    if source_language is SourceLanguage.EN:
        content = CONCISE_TEMPLATE.format(max_words=budget, text=source)
    else:
        language = LANGUAGE_NAMES[source_language]
        content = CONCISE_TEMPLATE_FROM.format(language=language, max_words=budget, text=source)
    return [{"role": "user", "content": content}]


def build_messages(
    source: str,
    mode: TranslationMode,
    context: Iterable[tuple[str, str]] = (),
    glossary: Sequence[GlossaryEntry] = (),
    *,
    source_language: SourceLanguage = SourceLanguage.EN,
    plural_note: bool = False,
) -> list[Message]:
    """Mensajes de chat de una petición, según el modo."""
    if mode is TranslationMode.CONCISE:
        return build_concise_messages(source, source_language=source_language)
    return build_normal_messages(
        source, context, glossary, source_language=source_language, plural_note=plural_note
    )


# ---------------------------------------------------------------------------
# Filtros de salida
# ---------------------------------------------------------------------------
#: La salida no puede ser más larga que esto por el original (en caracteres) con origen en inglés.
MAX_LENGTH_RATIO: Final = 3
#: Lo mismo por idioma de origen (R10). En S5 la relación de caracteres tuvo p50 de 2,8 (zh), 3,9 (ja) y
#: 2,4 (ko) y máximo de 5,0: con 3 en todos el filtro rechazaba 48 de 50 frases en chino.
MAX_LENGTH_RATIO_BY_LANGUAGE: Final[dict[SourceLanguage, int]] = {
    SourceLanguage.EN: MAX_LENGTH_RATIO,
    SourceLanguage.KO: 4,
    SourceLanguage.JA: 6,
    SourceLanguage.ZH: 7,
}


def _char_class(*ranges: tuple[int, int]) -> re.Pattern[str]:
    """Clase de caracteres con rangos de puntos de código (así el fichero no lleva caracteres raros)."""
    return re.compile("[" + "".join(f"{chr(first)}-{chr(last)}" for first, last in ranges) + "]")


#: Letras latinas: ASCII, Latin-1 y Latin extendido A y B (á, ñ, ü...).
_LATIN_LETTER = _char_class((0x41, 0x5A), (0x61, 0x7A), (0xC0, 0xD6), (0xD8, 0xF6), (0xF8, 0x24F))
#: Escrituras que no son español: cirílico, hebreo, árabe, signos CJK, kana, ideogramas, hangul y ancho total.
_FOREIGN_SCRIPT = _char_class(
    (0x0400, 0x04FF),
    (0x0590, 0x05FF),
    (0x0600, 0x06FF),
    (0x3000, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xAC00, 0xD7AF),
    (0xFF00, 0xFFEF),
)

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


def rejection_reason(
    source: str,
    output: str,
    *,
    finish_reason: str | None = None,
    source_language: SourceLanguage = SourceLanguage.EN,
) -> str | None:
    """Motivo por el que ``output`` no vale como traducción de ``source``, o ``None`` si pasa los filtros.

    - ``"vacía"``: no hay texto.
    - ``"idioma"``: ninguna letra latina, o letras de otras escrituras (chino, japonés, cirílico...).
    - ``"longitud"``: más veces el original (en caracteres) que el tope del idioma de origen (en 3, ko 4,
      ja 6, zh 7) o cortada por ``max_tokens``.
    - ``"eco del prompt"``: repite el *prompt* (instrucciones, etiquetas) o empieza con una muletilla.
    """
    text = output.strip()
    if not text:
        return "vacía"
    if not _LATIN_LETTER.search(text) or _FOREIGN_SCRIPT.search(text):
        return "idioma"
    max_ratio = MAX_LENGTH_RATIO_BY_LANGUAGE[source_language]
    if finish_reason == "length" or len(text) > max_ratio * len(source.strip()):
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
        language = request.source_language
        english = language is SourceLanguage.EN

        reason: str | None
        text = ""
        if not source:
            reason = "vacía"
        else:
            concise = mode is TranslationMode.CONCISE
            glossary = () if concise else select_glossary(source, request.glossary, source_language=language)
            # «Vosotros» (R8): solo con origen en inglés, que es donde hay señal de plural que consultar.
            group = english and group_state(source, [original for original, _ in request.context])
            # Primera pasada sin nota (la nota en todas baja la cifra: S7, B2); el reintento con la nota va
            # solo a las marcadas, la combinación medida que llega al 81 % de «vosotros».
            messages = build_messages(source, mode, request.context, glossary, source_language=language)
            max_tokens = max_tokens_for(source, language)
            text, reason = self._attempt(messages, source, max_tokens, language)
            if reason is None and english and not concise and needs_vosotros_retry(source, text, group=group):
                text = self._retry_with_vosotros(messages, source, max_tokens, language) or text
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

    def _attempt(
        self, messages: list[Message], source: str, max_tokens: int, language: SourceLanguage
    ) -> tuple[str, str | None]:
        """Una petición al modelo: ``(texto, motivo de rechazo)``. Con origen en inglés, posedita el texto."""
        output, finish_reason = self._complete(messages, max_tokens)
        output = clean_output(output)
        reason = rejection_reason(source, output, finish_reason=finish_reason, source_language=language)
        if reason is not None:
            return "", reason
        text = output.strip()
        if language is SourceLanguage.EN:
            text = postedit_vosotros(source, text)
        return text, None

    def _retry_with_vosotros(
        self, messages: list[Message], source: str, max_tokens: int, language: SourceLanguage
    ) -> str | None:
        """Repite la petición con la nota de plural informal del reintento (B2).

        Devuelve el texto nuevo si pasa los filtros y sale «vosotros» sin «ustedes»; si no (o si el servidor
        falla), ``None`` y se queda la primera traducción.
        """
        retried = [dict(message) for message in messages]
        retried[-1]["content"] += RETRY_NOTE
        try:
            text, reason = self._attempt(retried, source, max_tokens, language)
        except EngineError as error:
            logger.warning("Reintento de «vosotros» fallido, se queda la primera traducción: %s", error)
            return None
        if reason is None and has_vosotros(text) and not has_ustedes(text):
            return text
        return None

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
