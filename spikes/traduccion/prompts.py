"""Construcción de los prompts de Hy-MT2 a partir de sus plantillas OFICIALES.

Fuente: model card de ``tencent/Hy-MT2-1.8B`` (tabla «Translation Task Instruction
Examples»). En el README original los marcadores ``{...}`` van entre comillas
invertidas y algunas frases en negrita o cursiva: es formato Markdown, no parte del
texto (``train/data/example_data.jsonl`` del repositorio oficial usa texto plano).
Aquí se usa texto plano, salvo en la variante de diagnóstico ``markdown=True``, que
copia el Markdown literalmente.

Plantillas oficiales en inglés (``{target_lang}`` = nombre completo del idioma):

- Default Translation::

      Translate the following text into {target_lang}. Note that you should only
      output the translated result without any additional explanation:

      {source_text}

- Terminology::

      Reference the following translations:
      {text} translates to {text}
      ...

      Translate the following text into {target_lang}. Note that you must ONLY output
      the translated result without any additional explanation:

      {source_text}

- Style::

      Please translate the following text into {target_lang}. Note that the
      translation style must strictly conform to [{target_style}]:

      {source_text}

- Context (en la tabla figura como «Structured Data 2»)::

      [Background Information]
      {background_text}

      Please translate the following text into {target_lang}, taking the provided
      background information into consideration.

      [Source Text]
      {source_text}

- Personalization::

      [Source Text]
      {source_text}

      [Translation Tasks]
      1. {user_preferences}
      2. {user_preferences}
      3. ...
      4. Translate the [Source Text] into {target_lang}.

El modelo NO tiene *system prompt* por defecto: todo va en un único mensaje de usuario
(salvo en las disposiciones de chat, que reparten el contexto en turnos previos).
La card no dice cómo combinar plantillas, y el informe técnico (arXiv 2605.22064) tampoco
detalla qué texto se usa como «background». ``build_messages`` implementa varias
disposiciones para poder compararlas (ver ``prompt_lab.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Estilo en inglés (dentro de la plantilla oficial «Style»).
STYLE_EN = (
    'natural and concise Spanish from Spain (peninsular); '
    'use "vosotros" for the informal plural "you"'
)
#: Estilo tal y como lo formula el ADR-0007 (en español).
STYLE_ES = "español de España, natural y conciso; usa vosotros"
#: Estilo para las plantillas oficiales en chino.
STYLE_ZH = "西班牙本土西班牙语，自然简洁；第二人称复数使用vosotros"

HISTORY_INTRO = "Conversation so far (English original, then the Spanish already spoken):"

#: Pares (fuente, traducción ya hablada).
History = tuple[tuple[str, str], ...]
#: Pares (término fuente, traducción obligatoria).
Glossary = tuple[tuple[str, str], ...]

LAYOUTS = ("composed", "personalization", "chat", "chat_system", "chat_zh", "zh", "delimited")

#: Ejemplos de español de España (vosotros, léxico peninsular) para cebar el estilo como
#: turnos previos de chat. Se eligieron con vocabulario DISTINTO del corpus de prueba
#: (patatas, gafas de sol, entradas, camiseta, piscina...) para medir si se generaliza.
FEWSHOT_ES_ES: tuple[tuple[str, str], ...] = (
    ("Are you guys hungry? I can make some mashed potatoes.", "¿Tenéis hambre? Puedo hacer un puré de patatas."),
    ("Put your sunglasses on, it's really sunny out there.", "Ponte las gafas de sol, hace mucho sol ahí fuera."),
    ("Hey, did you two buy the tickets for tonight?", "Oye, ¿habéis comprado las entradas para esta noche?"),
    ("Come in and sit down, all of you.", "Pasad y sentaos todos."),
    ("That's so cool! I love your t-shirt.", "¡Qué guay! Me encanta tu camiseta."),
    ("Grab a taxi, we'll meet you at the pool.", "Coged un taxi, nos vemos en la piscina."),
)

#: Ampliación (12 ejemplos): más plurales con «vosotros» y más léxico de España.
FEWSHOT_ES_ES_12: tuple[tuple[str, str], ...] = FEWSHOT_ES_ES + (
    ("You guys are late again. What happened this time?", "Otra vez llegáis tarde. ¿Qué ha pasado esta vez?"),
    ("Pick up your jackets, it's getting cold.", "Coged las chaquetas, que empieza a hacer frío."),
    ("Do you two want to come with us to the supermarket?", "¿Queréis venir con nosotros al supermercado?"),
    ("I can't believe you didn't tell me, man.", "No me puedo creer que no me lo dijeras, tío."),
    ("Turn off the light and go to sleep, kids.", "Apagad la luz y a dormir, niños."),
    ("We'll take the subway to the stadium.", "Cogeremos el metro hasta el estadio."),
)


@dataclass(frozen=True)
class PromptConfig:
    """Qué piezas lleva el prompt, cómo se disponen y con qué muestreo se pide."""

    name: str
    layout: str = "composed"
    style: str | None = None
    context: bool = False
    glossary: bool = False
    #: Formato del texto de fondo: pares «English/Spanish», solo inglés o en prosa.
    bg_format: str = "pairs"
    #: Etiqueta «[Source Text]» delante de la frase (solo con contexto, como la card).
    source_label: bool = True
    #: Frase «ONLY output the translated result...» (la plantilla Context no la trae).
    only_clause: bool = True
    #: Copia literal del Markdown de la card (diagnóstico).
    markdown: bool = False
    #: Plantilla «Default Translation» oficial, sin ninguna pieza añadida.
    default_template: bool = False
    temperature: float = 0.7
    #: Nombre del idioma de destino en los prompts en inglés / en chino.
    target_lang: str = "Spanish"
    target_lang_zh: str = "西班牙语"
    #: Pares (inglés, español) que se anteponen como turnos previos de chat (few-shot).
    fewshot: tuple[tuple[str, str], ...] = ()
    #: En las disposiciones de chat: ¿llevan la cláusula de estilo los turnos PREVIOS?
    #: (el último turno siempre la lleva si hay estilo).
    turn_style: bool = True
    #: En ``chat_system``: ¿lleva cada turno de usuario la instrucción de traducir («Default
    #: Translation»)? Sin ella los turnos son texto crudo: más corto, pero el modelo a veces
    #: obedece órdenes que aparecen en el diálogo en vez de traducirlas.
    wrap_turns: bool = False
    #: Glosario con la plantilla oficial «Terminology» en chino (en el último turno).
    glossary_zh: bool = False
    #: Añade el léxico de España (``corpus.SPAIN_LEXICON``) al glosario (prueba de techo).
    lexicon: bool = False


#: PROMPT FINAL del spike (ver README, «Método»): mensaje de sistema con el estilo,
#: 12 ejemplos previos de español de España (few-shot) y las últimas frases de la escena
#: como turnos de chat, cada turno de usuario envuelto en la instrucción oficial
#: «Default Translation»; si hay glosario, el último turno usa la plantilla oficial
#: «Terminology» en chino. Las variantes se construyen con ``dataclasses.replace``.
def final_config() -> PromptConfig:
    return PromptConfig(
        "final",
        layout="chat_system",
        fewshot=FEWSHOT_ES_ES_12,
        style=STYLE_EN,
        context=True,
        glossary=True,
        glossary_zh=True,
        wrap_turns=True,
    )


def _bt(text: str, md: bool) -> str:
    """Envuelve en comillas invertidas solo en la variante Markdown literal."""
    return f"`{text}`" if md else text


def terminology_block(glossary: Glossary, md: bool = False) -> str:
    """Bloque «Reference the following translations» (plantilla Terminology)."""
    head = "*Reference the following translations:*" if md else "Reference the following translations:"
    rows = [f"{_bt(src, md)} translates to {_bt(tgt, md)}" for src, tgt in glossary]
    return "\n".join([head, *rows])


def background_text(history: History, bg_format: str = "pairs") -> str:
    """Texto de ``{background_text}`` a partir de los pares previos."""
    if bg_format == "english":
        return "\n".join(en for en, _es in history)
    if bg_format == "prose":
        rows = [f'"{en}" was translated as "{es}".' for en, es in history]
        return "Earlier in this scene: " + " ".join(rows)
    rows = [HISTORY_INTRO]
    for en, es in history:
        rows.append(f"English: {en}")
        rows.append(f"Spanish: {es}")
    return "\n".join(rows)


def background_block(history: History, md: bool = False, bg_format: str = "pairs") -> str:
    """Bloque «[Background Information]» con los últimos pares (plantilla Context)."""
    head = "*[Background Information]*" if md else "[Background Information]"
    return f"{head}\n{_bt(background_text(history, bg_format), md)}"


# ---------------------------------------------------------------------------
# Disposiciones
# ---------------------------------------------------------------------------
def _composed(source: str, cfg: PromptConfig, history: History, glossary: Glossary) -> str:
    """Terminología + contexto + instrucción (con estilo) + texto, en un solo mensaje."""
    md = cfg.markdown
    use_history = cfg.context and bool(history)
    use_glossary = cfg.glossary and bool(glossary)

    lang = _bt(cfg.target_lang, md)
    if use_history:
        instr = (
            f"Please translate the following text into {lang}, taking the provided "
            "background information into consideration."
        )
    elif cfg.style:
        instr = f"Please translate the following text into {lang}."
    else:
        instr = f"Translate the following text into {lang}."
    if cfg.style:
        style = f"**`{cfg.style}`**" if md else cfg.style
        instr += f" Note that the translation style must strictly conform to [{style}]."
    if cfg.only_clause:
        only = (
            "**ONLY output the translated result without any additional explanation**"
            if md
            else "ONLY output the translated result without any additional explanation"
        )
        instr += f" Note that you must {only}:"
    elif not instr.endswith((".", ":")):
        instr += "."

    parts: list[str] = []
    if use_glossary:
        parts.append(terminology_block(glossary, md))
    if use_history:
        parts.append(background_block(history, md, cfg.bg_format))
    parts.append(instr)
    if use_history and cfg.source_label:
        label = "*[Source Text]*" if md else "[Source Text]"
        parts.append(f"{label}\n{_bt(source, md)}")
    else:
        parts.append(_bt(source, md))
    return "\n\n".join(parts)


def _personalization(source: str, cfg: PromptConfig, history: History, glossary: Glossary) -> str:
    """Plantilla «Personalization»: primero el texto, después la lista de tareas."""
    use_history = cfg.context and bool(history)
    use_glossary = cfg.glossary and bool(glossary)
    blocks: list[str] = []
    if use_history:
        blocks.append(background_block(history, False, cfg.bg_format))
    blocks.append(f"[Source Text]\n{source}")
    tasks: list[str] = []
    if use_glossary:
        rows = "; ".join(f"{s} translates to {t}" for s, t in glossary)
        tasks.append(f"Use these reference translations: {rows}.")
    if cfg.style:
        tasks.append(f"The translation style must strictly conform to [{cfg.style}].")
    if use_history:
        tasks.append("Take the background information into consideration.")
    tasks.append(f"Translate the [Source Text] into {cfg.target_lang}.")
    if cfg.only_clause:
        tasks.append("Output ONLY the translated result without any additional explanation.")
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(tasks, 1))
    blocks.append(f"[Translation Tasks]\n{numbered}")
    return "\n\n".join(blocks)


def _turn(source: str, cfg: PromptConfig, glossary: Glossary = (), style_on: bool = True) -> str:
    """Un turno de usuario autónomo (plantillas Terminology/Style sin contexto)."""
    style = cfg.style if style_on else None
    instr = f"Translate the following text into {cfg.target_lang}."
    if style:
        instr = f"Please translate the following text into {cfg.target_lang}."
        instr += f" Note that the translation style must strictly conform to [{style}]."
    if cfg.only_clause:
        instr += " Note that you must ONLY output the translated result without any additional explanation:"
    else:
        instr += ":"
    parts = [terminology_block(glossary)] if glossary else []
    parts += [instr, source]
    return "\n\n".join(parts)


def _turn_zh(source: str, cfg: PromptConfig, glossary: Glossary = (), style_on: bool = True) -> str:
    """Un turno de usuario autónomo con las plantillas oficiales en chino."""
    style = cfg.style if style_on else None
    instr = f"请将以下文本翻译为{cfg.target_lang_zh}。"
    if style:
        instr += f"注意翻译的风格要严格符合【{style}】。"
    if cfg.only_clause:
        instr += "注意只需要输出翻译后的结果，不要额外解释："
    parts = []
    if glossary:
        rows = "\n".join(f"{s} 翻译成 {t}" for s, t in glossary)
        parts.append(f"参考下面的翻译：\n{rows}")
    parts += [instr, source]
    return "\n\n".join(parts)


def _zh_terminology_turn(source: str, cfg: PromptConfig, glossary: Glossary, style_on: bool) -> str:
    """Plantilla oficial «Terminology» en chino (glosario) + estilo opcional."""
    rows = "\n".join(f"{s} 翻译成 {t}" for s, t in glossary)
    instr = f"将以下文本翻译为{cfg.target_lang_zh}，"
    if style_on and cfg.style:
        instr += f"注意翻译的风格要严格符合【{cfg.style}】，"
    instr += "注意只需要输出翻译后的结果，不要额外解释："
    return f"参考下面的翻译：\n{rows}\n{instr}\n\n{source}"


def _chat(source: str, cfg: PromptConfig, history: History, glossary: Glossary) -> list[dict]:
    """El contexto son turnos previos de chat (usuario pide, asistente responde)."""
    turn = _turn_zh if cfg.layout == "chat_zh" else _turn
    past = (*cfg.fewshot, *(history if cfg.context else ()))
    use_glossary = cfg.glossary and bool(glossary)
    msgs: list[dict] = []
    if cfg.layout == "chat_system":
        rules = [f"Translate every user message into {cfg.target_lang}."]
        if cfg.style:
            rules.append(f"The translation style must strictly conform to [{cfg.style}].")
        if use_glossary and not cfg.glossary_zh:
            rows = "; ".join(f"{s} translates to {t}" for s, t in glossary)
            rules.append(f"Reference translations: {rows}.")
        rules.append("ONLY output the translated result without any additional explanation.")
        msgs.append({"role": "system", "content": " ".join(rules)})
        for en, es in past:
            msgs.append({"role": "user", "content": _turn(en, cfg, (), False) if cfg.wrap_turns else en})
            msgs.append({"role": "assistant", "content": es})
        if use_glossary and cfg.glossary_zh:
            final = _zh_terminology_turn(source, cfg, glossary, False)
        else:
            final = _turn(source, cfg, (), False) if cfg.wrap_turns else source
        msgs.append({"role": "user", "content": final})
        return msgs
    for en, es in past:
        msgs.append({"role": "user", "content": turn(en, cfg, (), cfg.turn_style)})
        msgs.append({"role": "assistant", "content": es})
    if use_glossary and cfg.glossary_zh:
        final = _zh_terminology_turn(source, cfg, glossary, True)
    else:
        final = turn(source, cfg, glossary if use_glossary else (), True)
    msgs.append({"role": "user", "content": final})
    return msgs


#: Nombres de idioma y fragmentos fijos en chino (plantillas oficiales en chino).
def _zh(source: str, cfg: PromptConfig, history: History, glossary: Glossary) -> str:
    use_history = cfg.context and bool(history)
    parts: list[str] = []
    if cfg.glossary and glossary:
        rows = "\n".join(f"{s} 翻译成 {t}" for s, t in glossary)
        parts.append(f"参考下面的翻译：\n{rows}")
    if use_history:
        parts.append("【背景信息】\n" + background_text(history, cfg.bg_format))
    lang = cfg.target_lang_zh
    instr = f"请结合背景信息将以下文本翻译为{lang}。" if use_history else f"请将以下文本翻译为{lang}。"
    if cfg.style:
        instr += f"注意翻译的风格要严格符合【{cfg.style}】。"
    if cfg.only_clause:
        instr += "注意只需要输出翻译后的结果，不要额外解释："
    parts.append(instr)
    parts.append(f"【待翻译文本】\n{source}" if use_history and cfg.source_label else source)
    return "\n\n".join(parts)


def _delimited(source: str, cfg: PromptConfig, history: History, glossary: Glossary) -> str:
    """Disposición propia (no oficial): secciones rotuladas y texto entre delimitadores."""
    parts = [
        f"Translate the text between <source> tags into {cfg.target_lang}. "
        "ONLY output the translated result without any additional explanation."
    ]
    if cfg.style:
        parts.append(f"Style: {cfg.style}.")
    if cfg.glossary and glossary:
        rows = "\n".join(f"{s} translates to {t}" for s, t in glossary)
        parts.append(f"Reference translations (mandatory):\n{rows}")
    if cfg.context and history:
        parts.append(
            "Previous dialogue (for context only, do NOT translate it):\n"
            + background_text(history, cfg.bg_format)
        )
    parts.append(f"<source>\n{source}\n</source>")
    return "\n\n".join(parts)


def build_messages(
    source: str,
    cfg: PromptConfig,
    history: History = (),
    glossary: Glossary = (),
) -> list[dict]:
    """Mensajes de chat listos para enviar al servidor para traducir ``source``."""
    if cfg.default_template:
        text = (
            f"Translate the following text into {cfg.target_lang}. Note that you should only "
            f"output the translated result without any additional explanation:\n\n{source}"
        )
        return [{"role": "user", "content": text}]
    if cfg.layout in ("chat", "chat_system", "chat_zh"):
        return _chat(source, cfg, history, glossary)
    builders = {
        "composed": _composed,
        "personalization": _personalization,
        "zh": _zh,
        "delimited": _delimited,
    }
    if cfg.layout not in builders:
        raise ValueError(f"Disposición desconocida: {cfg.layout!r}")
    return [{"role": "user", "content": builders[cfg.layout](source, cfg, history, glossary)}]


def build_prompt(
    source: str,
    cfg: PromptConfig,
    history: History = (),
    glossary: Glossary = (),
) -> str:
    """Texto del último mensaje de usuario (útil para imprimir o documentar)."""
    return build_messages(source, cfg, history, glossary)[-1]["content"]


def messages_to_text(messages: list[dict]) -> str:
    """Representación legible de una conversación (para guardar en los registros)."""
    if len(messages) == 1:
        return messages[0]["content"]
    return "\n".join(f"<{m['role']}>\n{m['content']}" for m in messages)


# ---------------------------------------------------------------------------
# Modo resumen (traducción concisa)
# ---------------------------------------------------------------------------
#: Fracción de las palabras de la frase inglesa que se permite en el modo resumen.
BUDGET_RATIO = 0.6

CONCISE_STYLE_EN = (
    "very concise Spanish from Spain: keep only the essential meaning, "
    "drop filler words and secondary details"
)
CONCISE_STYLE_ES = "traduce de forma muy concisa, solo lo esencial, en español de España"


def word_budget(n_source_words: int) -> int:
    """Tope de palabras del modo resumen para una frase de ``n_source_words`` palabras."""
    return max(4, math.ceil(BUDGET_RATIO * n_source_words))
