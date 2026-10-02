"""Detector de «vosotros» / «ustedes» / «tú» / «usted» en una traducción al español (B0).

Es un detector léxico y morfológico por reglas (sin modelos) que usa el español de la salida y, para los casos
ambiguos, el inglés de la entrada. La precisión y la cobertura se miden contra una muestra etiquetada a mano
(`detector_eval.py`, README).

`classify(es, en)` devuelve un conjunto de marcas:
  vos     2.ª persona del plural de España («vosotros», «os», «vuestro», «-áis/-éis/-ís», «-ad/-ed/-id»...)
  ust     «ustedes» explícito o verbo/imperativo en 3.ª plural dirigido al oyente
  tu      «tú», «tu(s)», «ti», «contigo», «te» o verbos en 2.ª singular conocidos
  usted   «usted» o imperativo/verbo formal singular conocido
  voseo   formas rioplatenses («vos», «querés»...)
`primary(es, en)` = «vos» si hay marca de vosotros, si no «ust», si no «tu», si no «usted», si no «neu».
`mixed(es, en)` = hay a la vez marca de vosotros y de ustedes o de tú (salida incoherente).

Un verbo en 3.ª plural solo cuenta como «ust» si el inglés tiene «you/your/guys...» y no tiene «they/them/their»
(y, si no es un imperativo, si va sin sujeto propio): con elisión de sujeto («están resbaladizas») no se puede saber de
quién habla el español sin mirar el inglés.
"""

from __future__ import annotations

import re

_F = re.IGNORECASE
_W = r"(?<![\wáéíóúñü])"  # «inicio de palabra» sin depender de \b con acentos
_E = r"(?![\wáéíóúñü])"
_L = "a-záéíóúñü"

# --- inglés ---------------------------------------------------------------------------------------------
_EN_YOU = re.compile(r"\b(you|your|yours|yourself|yourselves|y'all|you're|you've|you'd|you'll|ya|guys|everyone|everybody|folks|kids|team|class|crew|soldiers)\b", _F)
_EN_THEY = re.compile(r"\b(they|them|their|theirs|they're|they've|they'd)\b", _F)
_EN_IMP = re.compile(
    r"^(please\b|don't\b|do not\b|never\b|let's\b|let me\b|come\b|go\b|take\b|put\b|get\b|give\b|tell\b|look\b|listen\b|"
    r"wait\b|stay\b|keep\b|hold\b|follow\b|be\b|sit\b|stand\b|stop\b|run\b|hurry\b|bring\b|leave\b|call\b|ask\b|try\b|"
    r"watch\b|move\b|open\b|close\b|turn\b|check\b|read\b|write\b|eat\b|drink\b|clean\b|help\b|pack\b|grab\b|hand\b|"
    r"send\b|make\b|show\b|pass\b|wash\b|calm\b|shake\b|slowly\b|cover\b|drop\b|gather\b|welcome\b|alright\b|okay\b|"
    r"good morning\b|hey\b|crew\b|class\b|kids\b|soldiers\b|ladies\b)",
    _F,
)

# --- vosotros -------------------------------------------------------------------------------------------
_VOS_PRON = re.compile(rf"{_W}(vosotros|vosotras|vuestr[oa]s?|os){_E}", _F)
_VOS_SHORT = re.compile(rf"{_W}(vais|sois|veis|dais|oís|habéis|reís|decís|salís|venís|vivís|sentís|pedís|podéis|queréis){_E}", _F)
_VOS_PRESENT = re.compile(rf"{_W}[{_L}]{{2,}}(áis|éis|ís){_E}", _F)
_VOS_PAST = re.compile(
    rf"{_W}[{_L}]{{2,}}(asteis|isteis|ásteis|ísteis|abais|íais|aréis|eréis|iréis|aríais|eríais|iríais|ais|eis){_E}", _F
)
_VOS_ENCL = re.compile(rf"{_W}[{_L}]{{2,}}(aos|eos|íos|ios){_E}", _F)  # «sentaos», «abrochaos»
_VOS_IMP = re.compile(rf"{_W}([{_L}]{{2,}}[aei]d)(me|te|lo|la|los|las|le|les|nos|se)?{_E}", _F)
_VOS_IMP_OS = re.compile(rf"{_W}(volved|id)(os)?{_E}", _F)
_NOUNS_D = re.compile(r"(dad|tad|bad|ud|ced|sed|red|pared|mitad|verdad|edad)$", _F)
_VOSEO = re.compile(rf"{_W}(vos|tenés|querés|podés|sabés|sos|andá|vení|decime|mirá|escuchá|esperá|respondeme|dejame|contame|fijate){_E}", _F)

# --- ustedes --------------------------------------------------------------------------------------------
_UST_PRON = re.compile(rf"{_W}ustedes{_E}", _F)
_UST_IMP_LIST = (
    "tomen vengan vayan síganme siganme sígame miren mírenme escuchen esperen abran cierren pasen entren salgan vean "
    "digan díganme hagan háganme pongan sean estén tengan den déjenme dejen callen corran suban bajen levanten coman "
    "beban lleven traigan tráiganme ayuden respiren mantengan permanezcan queden sigan vuelvan retrocedan recuerden "
    "olviden piensen intenten prueben acepten permitan compartan cojan agarren sujeten aguanten llamen contesten "
    "respondan ignoren confíen escuchen disparen disfruten abróchense aplaudan empaquen mantengan dejen"
).split()
_UST_IMP = re.compile(rf"{_W}({'|'.join(sorted(set(_UST_IMP_LIST), key=len, reverse=True))}){_E}", _F)
_UST_ENCL = re.compile(rf"{_W}[{_L}]{{2,}}[eaéá]nse{_E}|{_W}[{_L}]{{2,}}[eaé]n(me|nos|lo|la|los|las){_E}", _F)
_UST_VERBS = re.compile(
    rf"{_W}(están|estan|tienen|quieren|pueden|saben|van|vienen|hacen|piensan|necesitan|entienden|escuchan|"
    rf"vieron|hicieron|dijeron|trajeron|terminaron|comieron|vinieron|estaban|tenían|querían|podían|"
    rf"deben|deberían|podrían|tendrán|harán|irán|serán|llegaron|dejaron|hayan|han|habían|iban|"
    rf"parecen|merecen|conocen|vuelven|salen|llevan|duermen|piden|dicen|ven|creen|sienten|miran|"
    rf"cenaron|terminan|empiezan|comen|beben|trabajan|hablan|llegan|jugaron|quedan|pasan|funcionan|"
    rf"son|fueron|eran|viven|pagan|ganan|perdieron|ganaron|volvieron|salieron|prometieron|mintieron){_E}",
    _F,
)
_UST_VERBS_STOP_BEFORE = re.compile(
    rf"{_W}(los|las|sus|tus|mis|unos|unas|estos|esos|aquellos|nuestros|vuestros|muchos|todos los|dos|tres|ellos|ellas|"
    rf"[{_L}]+s)\s+[{_L}]+\s*$",
    _F,
)
# imperativo 3.ª plural genérico: primer verbo de la frase acabado en -en/-an cuando el inglés es un imperativo
_SKIP_START = frozenset(
    "no por favor venga vamos bueno vale oye eh ey hey ¡ ¿ y pero ahora ya entonces bien claro mejor así que".split()
)
_NOT_VERB_EN_AN = frozenset("también tan quien quienes pan plan clan van son ven den dan cuan mientras bien según sin jamás aún".split())

# --- tú ---------------------------------------------------------------------------------------------------
_TU_PRON = re.compile(rf"{_W}(tú|tu|tus|ti|contigo|te|tuyo|tuya|tuyos|tuyas){_E}", _F)
_TU_VERBS = re.compile(
    rf"{_W}(tienes|quieres|puedes|eres|estás|vas|haces|sabes|ves|dices|vienes|necesitas|piensas|entiendes|"
    rf"escuchas|crees|sientes|tendrás|harás|serás|estuviste|fuiste|hiciste|dijiste|viste|trajiste|"
    rf"ponte|siéntate|cállate|mira|escucha|toma|espera|oye|déjame|dime|cuéntame|llámame|corre|sigue|"
    rf"cuídate|ven|di|haz|sal|ten|ve|pon|vete|quédate|relájate|dame|pareces|cierra|respira|abre|"
    rf"limpia|bebe|come|pide|sopla|estira|baja|entra|avisa|ayúdame|pásame|cúbreme|mantén|"
    rf"has|estabas|llegaste|aprendiste|terminaste|dormiste|salvaste|prometiste|puedes|quieras|estés|seas|hagas|"
    rf"dispares|mientas|preocupes|olvides|hables|pienses|confíes|contengas|llegues|notas|\w+aste|\w+iste){_E}",
    _F,
)
_USTED = re.compile(
    rf"{_W}(usted|siéntese|póngase|pase|acompáñeme|dígame|permítame|tenga|mire|escuche|espere|cuénteme|"
    rf"déjeme|llámeme|firme|disculpe|perdone|venga|siga|quédese|pida|diga|pruebe|acepte|disfrute|"
    rf"desea|necesita|reconoce|podría|ayudarle|su|sus|le gustaría){_E}",
    _F,
)


def _tokens(es: str) -> list[str]:
    return re.findall(rf"[{_L}]+", es.lower())


def _first_verbal_token(es: str) -> str | None:
    """Primer token verbal de una frase en imperativo: salta «no», «por favor», vocativos y partículas."""
    # Quita un vocativo inicial antes de la primera coma si es corto («Equipo, prepárense...»).
    head, sep, tail = es.partition(",")
    if sep and 1 <= len(_tokens(head)) <= 3 and tail.strip():
        es = tail
    for tok in _tokens(es):
        if tok in _SKIP_START:
            continue
        return tok
    return None


def _en_signals(en: str | None) -> tuple[bool, bool, bool]:
    if en is None:
        return True, False, False
    return bool(_EN_YOU.search(en)), bool(_EN_THEY.search(en)), bool(_EN_IMP.search(en.strip()))


def classify(es: str, en: str | None = None) -> set[str]:
    """Marcas de persona/tratamiento halladas en `es`, con ayuda del inglés `en` (opcional)."""
    marks: set[str] = set()
    if not es:
        return marks
    en_you, en_they, en_imp = _en_signals(en)

    # vosotros
    if _VOS_PRON.search(es) or _VOS_SHORT.search(es) or _VOS_PRESENT.search(es) or _VOS_PAST.search(es) or _VOS_ENCL.search(es) or _VOS_IMP_OS.search(es):
        marks.add("vos")
    for m in _VOS_IMP.finditer(es):
        stem = m.group(1).lower()
        if not _NOUNS_D.search(stem) or stem in {"dad"}:
            marks.add("vos")

    # ustedes
    if _UST_PRON.search(es) or _UST_IMP.search(es) or _UST_ENCL.search(es):
        marks.add("ust")
    if en_imp:
        tok = _first_verbal_token(es)
        if tok and tok not in _NOT_VERB_EN_AN and re.search(r"(en|an)(me|nos|lo|la|los|las|se)?$", tok) and len(tok) >= 4:
            marks.add("ust")
    if en_you and not en_they:
        for m in _UST_VERBS.finditer(es):
            before = es[: m.start()]
            clause = re.split(r"[,;.!?¿¡]", before)[-1]
            if not _UST_VERBS_STOP_BEFORE.search(clause):
                marks.add("ust")
                break

    # tú / usted
    if _TU_PRON.search(es) or _TU_VERBS.search(es):
        marks.add("tu")
    if _USTED.search(es):
        marks.add("usted")
    if _VOSEO.search(es):
        marks.add("voseo")
    return marks


def primary(es: str, en: str | None = None) -> str:
    """Etiqueta principal: vos > ust > tu > usted > neu."""
    marks = classify(es, en)
    for label in ("vos", "ust", "tu", "usted"):
        if label in marks:
            return label
    return "neu"


def mixed(es: str, en: str | None = None) -> bool:
    """Marcas incompatibles en la misma salida: vosotros junto con ustedes o con tú."""
    marks = classify(es, en)
    return "vos" in marks and bool(marks & {"ust", "tu"})
