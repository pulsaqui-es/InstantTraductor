"""Variantes de prompt para «vosotros» (B1). La referencia es el prompt de producción de `mt/hymt2.py` (importado).

Cada variante es una función `(source, context, glossary, mode) -> mensajes de chat`. Los ejemplos nuevos están
escritos para este spike y NO coinciden con ninguna frase del corpus B0 (`corpus_b0.py`) ni del corpus S2.
Los ejemplos van en mini-escenas (turnos consecutivos): la escena anterior sirve de contexto de plural, como pasa en
un diálogo real, y hay ejemplos de singular informal y de formal para no empujar todo hacia «vosotros».
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence

from instanttraductor.contracts import GlossaryEntry
from instanttraductor.mt.hymt2 import (
    CONCISE_TEMPLATE,
    FEWSHOT_ES_ES,
    SYSTEM_PROMPT,
    TERMINOLOGY_ROW,
    TERMINOLOGY_TEMPLATE,
    TURN_TEMPLATE,
    build_concise_messages,
    build_normal_messages,
    concise_word_budget,
)

Message = dict[str, str]
Pair = tuple[str, str]

# --- ejemplos nuevos, en mini-escenas -------------------------------------------------------------------
EXTRA_SCENES: tuple[tuple[Pair, ...], ...] = (
    (
        ("Kids, dinner is ready!", "¡Niños, la cena está lista!"),
        ("Wash your hands and sit at the table.", "Lavaos las manos y sentaos a la mesa."),
        ("Don't start without me.", "No empecéis sin mí."),
        ("Did you finish the juice?", "¿Os habéis terminado el zumo?"),
    ),
    (
        ("Hey guys, over here!", "¡Eh, chicos, por aquí!"),
        ("Give me your passports, I'll show them.", "Dadme los pasaportes, yo los enseño."),
        ("Are you nervous?", "¿Estáis nerviosos?"),
        ("Don't worry, you'll love it there.", "No os preocupéis, os va a encantar."),
    ),
    (
        ("Okay, team, listen up.", "Vale, equipo, escuchad."),
        ("Stay focused and keep passing the ball.", "Mantened la concentración y seguid pasando el balón."),
        ("You can win this game.", "Podéis ganar este partido."),
        ("Go out there and show them who you are!", "¡Salid ahí fuera y demostradles quiénes sois!"),
    ),
    (
        ("Class, take out a piece of paper.", "Clase, sacad una hoja de papel."),
        ("Write your names at the top.", "Escribid vuestros nombres arriba."),
        ("Do you have any questions?", "¿Tenéis alguna pregunta?"),
        ("Don't copy from your neighbors.", "No copiéis de vuestros compañeros."),
    ),
    (
        ("The neighbors had another fight last night.", "Los vecinos se pelearon otra vez anoche."),
        ("They scream at each other every day.", "Se gritan el uno al otro todos los días."),
    ),
    (
        ("Hey, sweetheart, are you okay?", "Oye, cariño, ¿estás bien?"),
        ("Take your time, you don't have to answer now.", "Tómate tu tiempo, no hace falta que contestes ahora."),
        ("Call me tonight, will you?", "Llámame esta noche, ¿vale?"),
    ),
    (
        ("Excuse me, sir, could you help me?", "Disculpe, señor, ¿podría ayudarme?"),
        ("Please take a seat, Mrs. Ortiz.", "Siéntese, por favor, señora Ortiz."),
    ),
    (
        ("Put your hands up, all of you!", "¡Manos arriba, todos!"),
        ("Drop your weapons and come out slowly.", "Soltad las armas y salid despacio."),
    ),
)
EXTRA_FLAT: tuple[Pair, ...] = tuple(p for scene in EXTRA_SCENES for p in scene)

# --- ejemplos dinámicos por tipo de frase (todos plurales, con su escena) -------------------------------
DYN_POOL: dict[str, tuple[Pair, ...]] = {
    "imp": (
        ("Pack your things and meet me at the gate.", "Recoged vuestras cosas y quedad conmigo en la puerta."),
        ("Come in, close the door and be quiet.", "Pasad, cerrad la puerta y estad callados."),
        ("Take a seat, everyone, we'll start in a minute.", "Sentaos todos, empezamos en un minuto."),
        ("Get out of the pool, it's late.", "Salid de la piscina, que es tarde."),
        ("Tell me what you saw, both of you.", "Contadme lo que visteis, los dos."),
    ),
    "neg": (
        ("Don't open the box until I get back.", "No abráis la caja hasta que vuelva."),
        ("Don't be afraid, nothing will happen to you.", "No tengáis miedo, no os pasará nada."),
        ("Never leave the group, understood?", "No os separéis nunca del grupo, ¿entendido?"),
        ("Don't go out tonight, you guys.", "No salgáis esta noche, chicos."),
        ("Don't say a word about this.", "No digáis ni una palabra de esto."),
    ),
    "q": (
        ("Where are you going, you two?", "¿Adónde vais, vosotros dos?"),
        ("Do you want to come with us?", "¿Queréis venir con nosotros?"),
        ("Have you eaten yet?", "¿Habéis comido ya?"),
        ("What are you doing here, guys?", "¿Qué hacéis aquí, chicos?"),
        ("Can you hear that noise?", "¿Oís ese ruido?"),
    ),
    "st": (
        ("You're all invited to the wedding.", "Estáis todos invitados a la boda."),
        ("You were really brave tonight.", "Anoche fuisteis muy valientes."),
        ("You have to see this, it's incredible.", "Tenéis que ver esto, es increíble."),
        ("You always arrive late, you two.", "Siempre llegáis tarde, vosotros dos."),
        ("I'm so proud of you, guys.", "Estoy muy orgulloso de vosotros, chicos."),
    ),
}

_IMP_START = re.compile(
    r"^(please\b|come\b|go\b|take\b|put\b|get\b|give\b|tell\b|let\b|look\b|listen\b|wait\b|stay\b|keep\b|"
    r"hold\b|follow\b|be\b|sit\b|stand\b|stop\b|run\b|hurry\b|bring\b|leave\b|call\b|ask\b|try\b|watch\b|"
    r"move\b|open\b|close\b|turn\b|check\b|read\b|write\b|eat\b|drink\b|clean\b|help\b|pack\b|grab\b|"
    r"hand\b|send\b|make\b|show\b|pass\b|wash\b|calm\b|shake\b|slowly\b|cover\b|run\b|good morning,? \w+, "
    r"|alright,? \w+,? |okay,? \w+,? )",
    re.IGNORECASE,
)


def cue_kind(source: str) -> str:
    """Tipo de frase por la forma inglesa: neg (imperativo negativo), q (pregunta), imp (imperativo), st."""
    s = source.strip()
    if re.match(r"^(don't|do not|never)\b", s, re.IGNORECASE) or re.search(r"[,.!] ?(don't|never) ", s, re.IGNORECASE):
        return "neg"
    if s.endswith("?"):
        return "q"
    if _IMP_START.search(s):
        return "imp"
    return "st"


# --- plantillas -----------------------------------------------------------------------------------------
STYLE_FULL = (
    "natural Spanish from Spain (peninsular), informal: address several people with the 2nd person plural "
    '"vosotros" (¿Estáis listos? Venid, coged, no os preocupéis) and one person with "tú"'
)
STYLE_TURN_TEMPLATE = (
    "Please translate the following text into Spanish. Note that the translation style must strictly conform "
    "to [{style}]:\n\n{text}"
)
RETRY_NOTE = (
    "The listeners are several friends or colleagues: translate \"you\" as informal plural for Spain "
    '(use "vosotros" forms such as estáis, tenéis, venid, no os preocupéis; never "ustedes").'
)


def _glossary_turn(source: str, glossary: Sequence[GlossaryEntry], template: str) -> str:
    if not glossary:
        return template.format(text=source)
    rows = "\n".join(TERMINOLOGY_ROW.format(source=g.source, target=g.target) for g in glossary)
    return TERMINOLOGY_TEMPLATE.format(rows=rows, text=source)


def _pairs(context: Iterable[Pair]) -> list[Pair]:
    return [(o.strip(), t.strip()) for o, t in context if o.strip() and t.strip()]


# --- variantes ---------------------------------------------------------------------------------------------
def v_base(source: str, context: Iterable[Pair], glossary: Sequence[GlossaryEntry], concise: bool) -> list[Message]:
    """Producción actual (`build_normal_messages` / `build_concise_messages`)."""
    if concise:
        return build_concise_messages(source)
    return build_normal_messages(source, context, glossary)


def _chat(
    system: str | None,
    examples: Iterable[Pair],
    context: Iterable[Pair],
    source: str,
    glossary: Sequence[GlossaryEntry],
    wrap: Callable[[str], str],
    last_template: str | None = None,
) -> list[Message]:
    messages: list[Message] = [{"role": "system", "content": system}] if system else []
    for o, t in [*examples, *_pairs(context)]:
        messages.append({"role": "user", "content": wrap(o)})
        messages.append({"role": "assistant", "content": t})
    if glossary:
        rows = "\n".join(TERMINOLOGY_ROW.format(source=g.source, target=g.target) for g in glossary)
        last = TERMINOLOGY_TEMPLATE.format(rows=rows, text=source)
    else:
        last = wrap(source)
    messages.append({"role": "user", "content": last})
    return messages


def v_style_turn(source, context, glossary, concise):
    """B1(a): el estilo en cada turno (plantilla oficial *Style*), sin mensaje de sistema; mismos 12 ejemplos."""
    if concise:
        return build_concise_messages(source)
    wrap = lambda t: STYLE_TURN_TEMPLATE.format(style=STYLE_FULL, text=t)  # noqa: E731
    return _chat(None, FEWSHOT_ES_ES, context, source, glossary, wrap)


def v_ex36(source, context, glossary, concise):
    """B1(c): 12 + 24 ejemplos fijos (mini-escenas con plural, singular y formal), sistema y turnos como hoy."""
    if concise:
        return build_concise_messages(source)
    wrap = lambda t: TURN_TEMPLATE.format(text=t)  # noqa: E731
    return _chat(SYSTEM_PROMPT, [*FEWSHOT_ES_ES, *EXTRA_FLAT], context, source, glossary, wrap)


def v_ex36_style(source, context, glossary, concise):
    """B1(a+c): ejemplos extra + estilo en cada turno (sin sistema)."""
    if concise:
        return build_concise_messages(source)
    wrap = lambda t: STYLE_TURN_TEMPLATE.format(style=STYLE_FULL, text=t)  # noqa: E731
    return _chat(None, [*FEWSHOT_ES_ES, *EXTRA_FLAT], context, source, glossary, wrap)


def v_dyn(source, context, glossary, concise):
    """B1(d): fijos de producción + 3 ejemplos dinámicos del mismo tipo de frase, justo antes del contexto."""
    if concise:
        return build_concise_messages(source)
    wrap = lambda t: TURN_TEMPLATE.format(text=t)  # noqa: E731
    dyn = DYN_POOL[cue_kind(source)][:3]
    return _chat(SYSTEM_PROMPT, [*FEWSHOT_ES_ES, *dyn], context, source, glossary, wrap)


def v_ex36_dyn(source, context, glossary, concise):
    """B1(c+d): ejemplos extra fijos y 3 dinámicos."""
    if concise:
        return build_concise_messages(source)
    wrap = lambda t: TURN_TEMPLATE.format(text=t)  # noqa: E731
    dyn = DYN_POOL[cue_kind(source)][:3]
    return _chat(SYSTEM_PROMPT, [*FEWSHOT_ES_ES, *EXTRA_FLAT, *dyn], context, source, glossary, wrap)


def v_end_note(source, context, glossary, concise):
    """B1(b): la nota de estilo AL FINAL del turno (después del texto), con los 12 ejemplos de producción."""
    if concise:
        return build_concise_messages(source)
    note = (
        '\n\n(Spanish from Spain, informal: use "vosotros" when you address several people, never "ustedes".)'
    )
    wrap = lambda t: TURN_TEMPLATE.format(text=t) + note  # noqa: E731
    return _chat(SYSTEM_PROMPT, FEWSHOT_ES_ES, context, source, glossary, wrap)


# --- modo CONCISE ---------------------------------------------------------------------------------------
CONCISE_VOS_TEMPLATE = (
    "Please translate the following text into Spanish. Note that the translation style must strictly "
    "conform to [telegraphic Spanish from Spain, like a news headline: drop filler words, at most {max_words} "
    'words; informal register: several listeners = "vosotros" (estáis, tenéis, venid), one listener = "tú"]:'
    "\n\n{text}"
)
CONCISE_EX = (
    ("Don't touch anything until I say so, you two.", "No toquéis nada hasta que os avise."),
    ("Are you ready to go, guys?", "¿Listos, chicos?"),
)


def v_concise_vos(source, context, glossary, concise):
    """B1(e): CONCISE con la pista de estilo («vosotros») dentro de la plantilla *Style*. Un solo mensaje."""
    if not concise:
        return build_concise_messages(source)  # solo se mide en CONCISE
    return [
        {
            "role": "user",
            "content": CONCISE_VOS_TEMPLATE.format(max_words=concise_word_budget(source), text=source),
        }
    ]


def v_concise_vos_ex(source, context, glossary, concise):
    """B1(e): CONCISE con la pista y 2 ejemplos telegráficos como turnos de chat."""
    if not concise:
        return build_concise_messages(source)
    msgs: list[Message] = []
    for o, t in CONCISE_EX:
        msgs.append(
            {"role": "user", "content": CONCISE_VOS_TEMPLATE.format(max_words=concise_word_budget(o), text=o)}
        )
        msgs.append({"role": "assistant", "content": t})
    msgs.append(
        {"role": "user", "content": CONCISE_VOS_TEMPLATE.format(max_words=concise_word_budget(source), text=source)}
    )
    return msgs


# --- pista de plural condicionada por la escena ------------------------------------------------------------
PLURAL_EN = re.compile(
    r"\b(you guys|you two|you three|you both|both of you|all of you|you all|y'all|everyone|everybody|guys|kids|"
    r"folks|team|class|crew|soldiers|friends|ladies and gentlemen|children|boys|girls|gentlemen)\b",
    re.IGNORECASE,
)
SINGULAR_EN = re.compile(
    r"\b(buddy|sir|ma'am|madam|honey|sweetheart|kid|darling|mr\.|mrs\.|miss|detective)\b", re.IGNORECASE
)
STATE_WINDOW = 5
PLURAL_NOTE = (
    "\n\n(Spanish from Spain, informal: use \"vosotros\" when you address several people, never \"ustedes\".)"
)


def group_state(source: str, context: Iterable[Pair]) -> bool:
    """¿Se dirige el hablante a un grupo? Marca de plural en esta frase o en las últimas del contexto (inglés)."""
    recent = [o for o, _ in _pairs(context)][-STATE_WINDOW:] + [source]
    if SINGULAR_EN.search(source):
        return False
    if PLURAL_NOTE and PLURAL_EN.search(source):
        return True
    return any(PLURAL_EN.search(x) for x in recent[:-1]) and not any(SINGULAR_EN.search(x) for x in recent)


def v_state_note(source, context, glossary, concise):
    """B1(b'): como `end_note`, pero la nota de plural solo va cuando la escena indica un grupo."""
    if concise:
        return build_concise_messages(source)
    note = PLURAL_NOTE if group_state(source, context) else ""
    wrap = lambda t: TURN_TEMPLATE.format(text=t)  # noqa: E731
    messages = _chat(SYSTEM_PROMPT, FEWSHOT_ES_ES, context, source, glossary, wrap)
    messages[-1]["content"] += note
    return messages


def v_ex36_state(source, context, glossary, concise):
    """B1(c+b'): 36 ejemplos fijos y la nota de plural solo cuando la escena indica un grupo."""
    if concise:
        return build_concise_messages(source)
    note = PLURAL_NOTE if group_state(source, context) else ""
    wrap = lambda t: TURN_TEMPLATE.format(text=t)  # noqa: E731
    messages = _chat(SYSTEM_PROMPT, [*FEWSHOT_ES_ES, *EXTRA_FLAT], context, source, glossary, wrap)
    messages[-1]["content"] += note
    return messages


def v_ex36_end(source, context, glossary, concise):
    """B1(c+b): 36 ejemplos fijos y la nota de plural siempre al final del turno."""
    if concise:
        return build_concise_messages(source)
    wrap = lambda t: TURN_TEMPLATE.format(text=t) + PLURAL_NOTE  # noqa: E731
    return _chat(SYSTEM_PROMPT, [*FEWSHOT_ES_ES, *EXTRA_FLAT], context, source, glossary, wrap)


VARIANTS: dict[str, Callable] = {
    "state_note": v_state_note,
    "ex36_state": v_ex36_state,
    "ex36_end": v_ex36_end,
    "base": v_base,
    "style_turn": v_style_turn,
    "end_note": v_end_note,
    "ex36": v_ex36,
    "ex36_style": v_ex36_style,
    "dyn": v_dyn,
    "ex36_dyn": v_ex36_dyn,
    "concise_vos": v_concise_vos,
    "concise_vos_ex": v_concise_vos_ex,
}

__all__ = ["CONCISE_TEMPLATE", "RETRY_NOTE", "STYLE_FULL", "STYLE_TURN_TEMPLATE", "VARIANTS", "cue_kind"]
