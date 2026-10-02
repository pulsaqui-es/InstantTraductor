"""«Vosotros» en español de España: posedición por reglas, detector de «ustedes» y señales (T018, R8).

Portado de ``spikes/habla_baja/postedit.py`` y ``prompts_b1.py`` (spike S7, ``spikes/habla_baja/README.md``,
parte B). Lo medido allí (corpus B0, 228 frases inglesas, Hy-MT2-7B):

- **Posedición** (``postedit_vosotros``): «ustedes» -> «vosotros»; la 3.ª persona del plural dirigida al
  oyente pasa a 2.ª plural (``están -> estáis``, ``tomaron -> tomasteis``, ``no tomen -> no toméis``,
  ``tomen -> tomad``, ``siéntense -> sentaos``); «su(s)» -> «vuestro(s)/vuestra(s)» y «les» -> «os» solo
  con «your» y sin «they/their» en el inglés. El léxico de formas sale de reglas de conjugación y ~300
  verbos de diálogo.
  Quién es el oyente lo decide el INGLÉS: solo se convierte con «you/your/guys...» (o un imperativo) y sin
  «they/them/their»; los verbos precedidos de un sustantivo plural no se tocan. Medido: 0 daños en singulares
  y en 3.ª plural, 18 a 32 µs por frase.
- **Señales de escena** (``group_state``): marca de plural en las últimas 5 líneas en inglés y ninguna de
  singular; decide si se añade la nota de plural informal al turno (``PLURAL_NOTE``) y si compensa reintentar.
- **Detector de «ustedes» residual** (``has_ustedes``): «ustedes» explícito, imperativos en 3.ª plural y
  reflexivos enclíticos («siéntense»). Dispara el reintento con el modelo.
- ``clean_output``: quita la nota repetida por el modelo (salto de línea doble y paréntesis), que el filtro
  de longitud rechazaría.

Todo es específico del origen en inglés: con ja, zh y ko no hay señal del inglés que consultar.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final


# ---------------------------------------------------------------------------------------------------------
# Léxico de formas
# ---------------------------------------------------------------------------------------------------------
def _words(text: str) -> list[str]:
    """Palabras separadas por espacios (listas de léxico en texto corrido)."""
    return text.split()


# (lemma, banderas). Banderas: ie (e>ie), ue (o>ue), i (e>i), jue (u>ue), sent (sentir), dorm (dormir),
# zc (conocer), cz (vencer), uy (construir), iacc (enviar), g:<raíz> (raíz irregular del subjuntivo).
_REGULAR = _words(
    """
    hablar llamar tomar mirar esperar escuchar ayudar buscar dejar pasar entrar llegar llevar quedar
    cantar bailar bajar subir cambiar cerrar:ie ganar usar pagar cuidar preparar contar:ue encontrar:ue
    mostrar:ue recordar:ue probar:ue sonar:ue soñar:ue volar:ue costar:ue almorzar:ue acordar:ue
    demostrar:ue colgar:ue pensar:ie empezar:ie comenzar:ie sentar:ie despertar:ie recomendar:ie
    negar:ie apretar:ie atravesar:ie gobernar:ie temblar:ie regalar terminar acabar necesitar trabajar
    caminar practicar explicar tocar sacar olvidar empacar comprar vender lavar limpiar cocinar disparar
    aplaudir abrir escribir recibir vivir subir sufrir decidir permitir compartir aceptar ignorar
    disfrutar apoyar confiar:iacc enviar:iacc guiar:iacc evitar mejorar notar armar ahorrar alejar
    acercar levantar relajar calmar tranquilizar abrochar sentir:sent mentir:sent preferir:sent
    divertir:sent convertir:sent sugerir:sent advertir:sent herir:sent dormir:dorm morir:dorm comer
    beber aprender correr romper creer deber meter responder esconder temer coger escoger recoger
    proteger prometer ceder vencer:cz torcer:cz entender:ie perder:ie encender:ie defender:ie querer:ie
    volver:ue poder:ue mover:ue resolver:ue devolver:ue envolver:ue doler:ue soler:ue llover:ue
    parecer:zc conocer:zc ofrecer:zc merecer:zc agradecer:zc crecer:zc nacer:zc desaparecer:zc
    aparecer:zc pedir:i servir:i repetir:i vestir:i elegir:i competir:i despedir:i medir:i impedir:i
    corregir:i seguir:i conseguir:i perseguir:i reír:rei construir:uy destruir:uy incluir:uy huir:uy
    contribuir:uy distribuir:uy dirigir exigir salir:g:salg conducir:zc traducir:zc producir:zc
    reducir:zc jugar:jue permanecer:zc obedecer:zc establecer:zc pertenecer:zc reconocer:zc descubrir
    cubrir ocurrir unir partir existir insistir asistir cumplir discutir retroceder retirar agarrar
    sujetar apartar soltar:ue rendir:i disculpar perdonar firmar entregar señalar abandonar atacar
    respetar arrodillar tumbar colocar apagar prestar interrumpir separar juntar ocultar callar gritar
    llorar sonar:ue aguantar sacudir meter lanzar cruzar abrazar alcanzar realizar utilizar organizar
    comenzar:ie despedir:i repartir cortar tirar tapar cargar recargar vigilar proteger acompañar
    invitar ofrecer:zc
    """
)

# Irregulares explícitos: (presente 3pl, presente 2pl, subjuntivo 3pl, subjuntivo 2pl, imperativo 2pl).
_IRREGULAR: dict[str, tuple[str, str, str, str, str]] = {
    "ser": ("son", "sois", "sean", "seáis", "sed"),
    "estar": ("están", "estáis", "estén", "estéis", "estad"),
    "ir": ("van", "vais", "vayan", "vayáis", "id"),
    "haber": ("han", "habéis", "hayan", "hayáis", "habed"),
    "dar": ("dan", "dais", "den", "deis", "dad"),
    "saber": ("saben", "sabéis", "sepan", "sepáis", "sabed"),
    "ver": ("ven", "veis", "vean", "veáis", "ved"),
    "oír": ("oyen", "oís", "oigan", "oigáis", "oíd"),
    "decir": ("dicen", "decís", "digan", "digáis", "decid"),
    "tener": ("tienen", "tenéis", "tengan", "tengáis", "tened"),
    "venir": ("vienen", "venís", "vengan", "vengáis", "venid"),
    "hacer": ("hacen", "hacéis", "hagan", "hagáis", "haced"),
    "poner": ("ponen", "ponéis", "pongan", "pongáis", "poned"),
    "traer": ("traen", "traéis", "traigan", "traigáis", "traed"),
    "caer": ("caen", "caéis", "caigan", "caigáis", "caed"),
    "caber": ("caben", "cabéis", "quepan", "quepáis", "cabed"),
    "reunir": ("reúnen", "reunís", "reúnan", "reunáis", "reunid"),
    "satisfacer": ("satisfacen", "satisfacéis", "satisfagan", "satisfagáis", "satisfaced"),
}
# Derivados por prefijo de un irregular: (lemma, prefijo, base).
_DERIVED = (
    ("mantener", "man", "tener"),
    ("obtener", "ob", "tener"),
    ("contener", "con", "tener"),
    ("detener", "de", "tener"),
    ("sostener", "sos", "tener"),
    ("retener", "re", "tener"),
    ("convenir", "con", "venir"),
    ("intervenir", "inter", "venir"),
    ("prevenir", "pre", "venir"),
    ("proponer", "pro", "poner"),
    ("suponer", "su", "poner"),
    ("componer", "com", "poner"),
    ("imponer", "im", "poner"),
    ("disponer", "dis", "poner"),
    ("exponer", "ex", "poner"),
    ("reponer", "re", "poner"),
    ("deshacer", "des", "hacer"),
    ("rehacer", "re", "hacer"),
    ("contradecir", "contra", "decir"),
    ("predecir", "pre", "decir"),
    ("atraer", "at", "traer"),
    ("distraer", "dis", "traer"),
    ("contraer", "con", "traer"),
    ("extraer", "ex", "traer"),
)

_VOWELS = "aeiouáéíóú"


def _unaccent(s: str) -> str:
    return s.translate(str.maketrans("áéíóúü", "aeiouu"))


def _change(stem: str, flag: str) -> str:
    """Raíz con el cambio vocálico de las formas con acento en la raíz (pienso, cuento, pido, juego)."""
    if flag in ("ie", "sent"):
        i = stem.rfind("e")
        return stem[:i] + "ie" + stem[i + 1 :] if i >= 0 else stem
    if flag in ("ue", "dorm"):
        i = stem.rfind("o")
        return stem[:i] + "ue" + stem[i + 1 :] if i >= 0 else stem
    if flag == "i":
        i = stem.rfind("e")
        s = stem[:i] + "i" + stem[i + 1 :] if i >= 0 else stem
        return s
    if flag == "jue":
        i = stem.rfind("u")
        return stem[:i] + "ue" + stem[i + 1 :]
    return stem


def _vos_stem(stem: str, flag: str) -> str:
    """Raíz de las formas de vosotros del subjuntivo (sentir -> sint-, dormir -> durm-, pedir -> pid-)."""
    if flag == "sent":
        i = stem.rfind("e")
        return stem[:i] + "i" + stem[i + 1 :]
    if flag == "dorm":
        i = stem.rfind("o")
        return stem[:i] + "u" + stem[i + 1 :]
    if flag == "i":
        return _change(stem, "i")
    return stem


def _subj_spell(stem: str, ending: str) -> str:
    """Raíz + terminación del subjuntivo con el cambio ortográfico (buscar -> busquen, coger -> cojan)."""
    first = ending[0]
    if first in "eé":  # verbos en -ar (subjuntivo en -e/-éis)
        if stem.endswith("c"):
            return stem[:-1] + "qu" + ending
        if stem.endswith("g"):
            return stem[:-1] + "gu" + ending
        if stem.endswith("z"):
            return stem[:-1] + "c" + ending
    else:  # a: verbos en -er / -ir
        if stem.endswith("gu"):
            return stem[:-2] + "g" + ending
        if stem.endswith("g"):
            return stem[:-1] + "j" + ending
    return stem + ending


def _gen(lemma: str, flag: str) -> tuple[str, str, str, str, str]:
    """Formas de un verbo: (presente 3pl, presente 2pl, subjuntivo 3pl, subjuntivo 2pl, imperativo 2pl)."""
    if lemma in _IRREGULAR:
        return _IRREGULAR[lemma]
    suf = lemma[-2:]
    stem = lemma[:-2]
    imperative = lemma[:-1] + "d"
    if lemma == "reír":
        return ("ríen", "reís", "rían", "riáis", "reíd")
    cs = _change(stem, flag)
    if flag == "uy":
        return (stem + "yen", stem + "ís", stem + "yan", stem + "yáis", imperative)
    if flag == "iacc":
        accented = stem[:-1] + "í" + stem[-1:]
        return (accented + "an", stem + "áis", accented + "en", stem + "éis", imperative)
    if suf == "ar":
        pres3, pres2 = cs + "an", stem + "áis"
        subj3 = _subj_spell(cs, "en")
        subj2 = _subj_spell(stem, "éis")
    else:
        pres3 = cs + "en"
        pres2 = stem + ("éis" if suf == "er" else "ís")
        if flag.startswith("g:"):
            base = flag[2:]
            subj3, subj2 = base + "an", base + "áis"
        else:
            sub_stem = cs
            vos_stem = _vos_stem(stem, flag)
            if flag == "zc":
                sub_stem = stem[:-1] + "zc" if stem.endswith("c") else stem + "zc"
                vos_stem = sub_stem
            elif flag == "cz":
                sub_stem = stem[:-1] + "z" if stem.endswith("c") else cs
                vos_stem = sub_stem
            subj3 = _subj_spell(sub_stem, "an")
            subj2 = _subj_spell(vos_stem, "áis")
    return (pres3, pres2, subj3, subj2, imperative)


@dataclass(frozen=True)
class Lexicon:
    pres3: dict[str, str]  # presente 3pl -> 2pl
    pres3_imp: dict[
        str, str
    ]  # presente 3pl -> imperativo de vosotros (para «Abren vuestros libros» -> «Abrid»)
    subj3: dict[
        str, tuple[str, str, str]
    ]  # subj/imperativo ustedes -> (imperativo vosotros, subjuntivo 2pl, lemma)


def _build() -> Lexicon:
    pres3: dict[str, str] = {}
    pres3_imp: dict[str, str] = {}
    subj3: dict[str, tuple[str, str, str]] = {}

    def add(lemma: str, forms: tuple[str, str, str, str, str]) -> None:
        p3, p2, s3, s2, imp = forms
        pres3.setdefault(p3, p2)
        pres3_imp.setdefault(p3, imp)
        subj3.setdefault(s3, (imp, s2, lemma))
        subj3.setdefault(_unaccent(s3), (imp, s2, lemma))

    for item in _REGULAR:
        parts = item.split(":", 1)
        lemma, flag = parts[0], (parts[1] if len(parts) > 1 else "")
        if flag == "rei":
            flag = ""
        add(lemma, _gen(lemma, flag))
    for lemma, forms in _IRREGULAR.items():
        add(lemma, forms)
    for lemma, _prefix, base in _DERIVED:
        # el derivado lleva delante lo que sobra del lema antes de la base (mantener = man + tener)
        head = lemma[: len(lemma) - len(base)]
        p3, p2, s3, s2, imp = (head + form for form in _IRREGULAR[base])
        add(lemma, (p3, p2, s3, s2, imp))
    return Lexicon(pres3, pres3_imp, subj3)


LEX = _build()

# Pasados, imperfectos, futuros y condicionales: reglas generales sobre la forma de 3.ª plural.
_SUFFIX_RULES: tuple[tuple[str, str], ...] = (
    ("aron", "asteis"),
    ("ieron", "isteis"),
    ("yeron", "ísteis"),
    ("jeron", "jisteis"),
    ("aban", "abais"),
    ("ían", "íais"),
    ("rán", "réis"),
)
_SUFFIX_EXCEPTIONS = {
    "fueron": "fuisteis",
    "dieron": "disteis",
    "vieron": "visteis",
    "iban": "ibais",
    "eran": "erais",
    "oyeron": "oísteis",
    "hicieron": "hicisteis",
    "quisieron": "quisisteis",
    "pusieron": "pusisteis",
    "pudieron": "pudisteis",
    "supieron": "supisteis",
    "tuvieron": "tuvisteis",
    "vinieron": "vinisteis",
    "estuvieron": "estuvisteis",
    "trajeron": "trajisteis",
    "dijeron": "dijisteis",
    "hubieron": "hubisteis",
}
# Verbos de uso frecuente que acaban igual pero no son pasados o futuros de 3.ª plural.
_NOT_VERBS = frozenset(
    _words(
        "camaron aron ieron aban rán afán alemán capitán galán refrán sartén también tan quién cuán "
        "esperanzán jamás además demás compás ademán desván huracán volcán rehén bien sin según aún pan "
        "plan clan estén tengan estén sean vengan vayan"
    )
)

_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
_EN_YOU = re.compile(
    r"\b(you|your|yours|yourself|yourselves|y'all|you're|you've|you'd|you'll|guys|everyone|everybody|folks|"
    r"kids|team|class|crew|soldiers|friends)\b",
    re.I,
)
_EN_YOUR = re.compile(r"\b(your|yours|yourselves|yourself)\b", re.I)
_EN_THEY = re.compile(r"\b(they|them|their|theirs|they're|they've|they'd)\b", re.I)
_EN_OTHER_POSS = re.compile(r"\b(his|her|its|hers)\b", re.I)
_EN_IMP = re.compile(
    r"^(please\b|don't\b|do not\b|never\b|let me\b|come\b|go\b|take\b|put\b|get\b|give\b|tell\b|look\b|"
    r"listen\b|"
    r"wait\b|stay\b|keep\b|hold\b|follow\b|be\b|sit\b|stand\b|stop\b|run\b|hurry\b|bring\b|leave\b|call\b|"
    r"ask\b|try\b|"
    r"watch\b|move\b|open\b|close\b|turn\b|check\b|read\b|write\b|eat\b|drink\b|clean\b|help\b|pack\b|"
    r"grab\b|hand\b|"
    r"send\b|make\b|show\b|pass\b|wash\b|calm\b|shake\b|slowly\b|cover\b|drop\b|gather\b|welcome\b|"
    r"alright\b|okay\b|"
    r"good morning\b|hey\b|crew\b|class\b|kids\b|soldiers\b|ladies\b|everyone\b|folks\b|guys\b|[A-Z][a-z]+,)",
    re.I,
)
# Antes del verbo solo puede haber estas palabras (sujeto elidido o «ustedes») para convertirlo.
_PRE_OK = frozenset(
    _words(
        "ustedes vosotros no se ya siempre nunca también todavía aún ahora así entonces y e o pero que si "
        "cuando donde como por favor bien mejor casi solo sólo todos todas tampoco jamás ¿ ¡ aquí allí hoy "
        "mañana anoche ayer más mucho muy aquí ahí luego después antes tan estoy"
    )
)
_DET_PL = re.compile(
    r"^(los|las|unos|unas|estos|esas|esos|estas|aquellos|aquellas|mis|tus|sus|nuestros|nuestras|vuestros|"
    r"vuestras|muchos|muchas|dos|tres|cuatro|cinco)$",
    re.I,
)


def _match_case(src: str, new: str) -> str:
    return new.capitalize() if src[:1].isupper() else new


def _clause_start_ok(tokens: list[tuple[str, bool]], i: int) -> bool:
    """¿Las palabras entre el comienzo de la cláusula y la palabra `i` son solo de la lista blanca?"""
    j = i - 1
    while j >= 0:
        word, is_word = tokens[j]
        if not is_word:
            if re.search(r"[,;.!?¿¡:—-]", word):
                return True  # frontera de cláusula
            j -= 1
            continue
        w = word.lower()
        if w in {"y", "e", "o", "u", "pero", "pues", "ni"}:
            return True  # una conjunción coordinante abre una cláusula nueva
        if w in _PRE_OK:
            j -= 1
            continue
        return False
    return True


def _convert_form(w: str, *, imperative_slot: bool, negative: bool) -> tuple[str, str] | None:
    """Pasa una forma de 3.ª plural a 2.ª plural. Devuelve (forma nueva, regla) o None si no la conoce."""
    wl = w.lower()
    if wl in _NOT_VERBS and wl not in LEX.subj3 and wl not in LEX.pres3:
        return None
    # Subjuntivo / imperativo de ustedes
    if wl in LEX.subj3 and (imperative_slot or negative or wl not in LEX.pres3):
        imp, subj2, _ = LEX.subj3[wl]
        if negative or not imperative_slot:
            return subj2, "subj"
        return imp, "imp"
    if wl in LEX.pres3:
        return LEX.pres3[wl], "pres"
    if wl in _SUFFIX_EXCEPTIONS:
        return _SUFFIX_EXCEPTIONS[wl], "pret"
    if wl in _NOT_VERBS:
        return None
    for old, new in _SUFFIX_RULES:
        if wl.endswith(old) and len(wl) > len(old) + 1:
            if old == "rán" and not re.search(r"(ar|er|ir|[aeií])rán$", wl) and not re.search(r"rán$", wl):
                continue
            return wl[: -len(old)] + new, "tense"
    return None


def _convert_reflexive_imperative(w: str) -> tuple[str, str] | None:
    """«siéntense» -> «sentaos», «síganme» -> «seguidme», «váyanse» -> «idos»."""
    m = re.match(r"^(?P<verb>[a-záéíóúñü]+?)(?P<cl>se|me|nos|lo|la|los|las)$", w.lower())
    if not m:
        return None
    verb = _unaccent(m.group("verb"))
    cl = m.group("cl")
    if verb not in LEX.subj3:
        return None
    imp, _, lemma = LEX.subj3[verb]
    if cl == "se":
        if lemma == "ir":
            return "idos", "imp-refl"
        if imp.endswith("id") and lemma != "ir":
            return imp[:-2] + "íos", "imp-refl"
        return imp[:-1] + "os", "imp-refl"
    return imp + cl, "imp-clit"


def postedit_vosotros(source_en: str, text: str) -> str:
    """Convierte «ustedes» y la 3.ª plural dirigida al oyente en 2.ª plural de España (señal del inglés).

    ``source_en`` es el original en inglés y ``text`` su traducción. Solo se toca el texto si el inglés
    indica que se habla a varias personas (hay «you/your/guys...» o un imperativo) y no habla de un tercero
    plural («they/them/their»); si el caso es ambiguo, el texto queda igual. Es rápida (decenas de µs).
    """
    en, es = source_en, text
    if not es.strip():
        return es
    en_you = bool(_EN_YOU.search(en))
    en_they = bool(_EN_THEY.search(en))
    en_imp = bool(_EN_IMP.search(en.strip()))
    tokens: list[tuple[str, bool]] = []
    pos = 0
    for m in _WORD.finditer(es):
        if m.start() > pos:
            tokens.append((es[pos : m.start()], False))
        tokens.append((m.group(0), True))
        pos = m.end()
    if pos < len(es):
        tokens.append((es[pos:], False))

    has_ust = any(is_w and w.lower() == "ustedes" for w, is_w in tokens)
    if en_they and not has_ust:
        return es
    if not (en_you or en_imp or has_ust):
        return es
    if en_they and has_ust:
        return es  # ambiguo: no se toca (el reintento con el modelo puede resolverlo)

    converted_any = has_ust
    out = [w for w, _ in tokens]
    first_word_idx = next(
        (i for i, (w, is_w) in enumerate(tokens) if is_w and w.lower() not in {"no", "por", "favor"}), None
    )
    seen_neg = False
    for i, (w, is_w) in enumerate(tokens):
        if not is_w:
            continue
        wl = w.lower()
        if wl == "no":
            seen_neg = True
        if wl == "ustedes":
            out[i] = _match_case(w, "vosotros")
            continue
        refl = (
            _convert_reflexive_imperative(w)
            if (en_imp or has_ust) and re.search(r"(nse|nme|nnos|nlo|nla|nlos|nlas)$", wl)
            else None
        )
        if refl and _clause_start_ok(tokens, i):
            out[i] = _match_case(w, refl[0])
            converted_any = True
            continue
        if not _clause_start_ok(tokens, i):
            continue
        # Un sustantivo plural directamente delante indica otro sujeto
        prev_words = [x for x, ok in tokens[:i] if ok]
        if prev_words and _DET_PL.match(prev_words[-1]):
            continue
        prev1 = prev_words[-1].lower() if prev_words else ""
        neg_here = seen_neg and prev1 == "no"
        # En un imperativo inglés, el verbo de ustedes es imperativo salvo tras «que», «no», «si», «cuando»...
        imperative_slot = prev1 not in {"que", "para", "si", "cuando", "hasta", "aunque", "ojalá", "no"}
        if (
            wl in LEX.subj3
            or wl in LEX.pres3
            or wl in _SUFFIX_EXCEPTIONS
            or any(wl.endswith(o) for o, _ in _SUFFIX_RULES)
        ):
            if not imperative_slot and not (en_you or has_ust or (en_imp and wl in LEX.subj3)):
                continue  # sin «you» en el inglés, un verbo en 3.ª plural suelto puede ser de otro sujeto
            if wl == "ven" and not has_ust:
                continue  # «ven» es el imperativo de «venir» (tú) mucho más a menudo que «ven» de «ver»
            if prev1 == "se" and not has_ust and wl not in LEX.subj3:
                continue  # «se están cerrando»: pasiva refleja, el sujeto es otro
            if (
                en_imp
                and i == first_word_idx
                and wl in LEX.pres3_imp
                and wl not in LEX.subj3
                and not neg_here
            ):
                out[i] = _match_case(w, LEX.pres3_imp[wl])
                converted_any = True
                continue
            conv = _convert_form(w, imperative_slot=bool(imperative_slot) and not neg_here, negative=neg_here)
            if conv:
                out[i] = _match_case(w, conv[0])
                converted_any = True
    text = "".join(out)
    if converted_any and (en_you or has_ust):
        # «se» delante de un verbo convertido -> «os»; «les» -> «os»; posesivos
        text = re.sub(r"(?<![\wáéíóúñü])se(?= [a-záéíóúñü]*(?:éis|áis|ís)\b)", "os", text)
        text = re.sub(r"(?<![\wáéíóúñü])Se(?= [a-záéíóúñü]*(?:éis|áis|ís)\b)", "Os", text)
        text = re.sub(r"(?<![\wáéíóúñü])les(?![\wáéíóúñü])", "os", text)
        text = re.sub(r"(?<![\wáéíóúñü])Les(?![\wáéíóúñü])", "Os", text)
        if _EN_YOUR.search(en) and not _EN_OTHER_POSS.search(en):
            text = _fix_possessives(text)
    return text


_FEM_NOUN = re.compile(r"(a|as|ión|iones|dad|dades|tad|tades|umbre|umbres|ez|eces|is|ie)$", re.I)
_MASC_EXC = frozenset(
    _words("día días mapa mapas problema problemas sistema sistemas tema temas idioma programa programas")
)
_FEM_EXC = frozenset(
    _words(
        "órdenes noches llaves clases tardes partes fuentes calles manos flores voces luces cruces leyes "
        "imágenes señales mano clase noche llave parte fuente calle flor voz luz cruz ley imagen señal"
    )
)


def _fix_possessives(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        poss, noun = m.group(1), m.group(2)
        plural = poss.lower() == "sus"
        fem = (bool(_FEM_NOUN.search(noun)) and noun.lower() not in _MASC_EXC) or noun.lower() in _FEM_EXC
        new = ("vuestras" if fem else "vuestros") if plural else ("vuestra" if fem else "vuestro")
        return _match_case(poss, new) + " " + noun

    return re.sub(r"(?<![\wáéíóúñü])(su|sus|Su|Sus)\s+([a-záéíóúñü]+)", repl, text)


# ---------------------------------------------------------------------------------------------------------
# Señales del inglés y de la escena
# ---------------------------------------------------------------------------------------------------------
#: Marcas de plural en el inglés: se habla a varias personas.
PLURAL_EN: Final = re.compile(
    r"\b(you guys|you two|you three|you both|both of you|all of you|you all|y'all|everyone|everybody|guys|"
    r"kids|folks|team|class|crew|soldiers|friends|ladies and gentlemen|children|boys|girls|gentlemen)\b",
    re.IGNORECASE,
)
#: Marcas de singular (vocativos): se habla a una sola persona.
SINGULAR_EN: Final = re.compile(
    r"\b(buddy|sir|ma'am|madam|honey|sweetheart|kid|darling|mr\.|mrs\.|miss|detective)\b", re.IGNORECASE
)
#: Líneas previas en inglés que se miran para saber a quién se habla.
STATE_WINDOW: Final = 5

#: Nota de estilo tras el texto del turno cuando la escena indica un grupo (B1, variante ``state_note``).
PLURAL_NOTE: Final = (
    '\n\n(Spanish from Spain, informal: use "vosotros" when you address several people, never "ustedes".)'
)
#: Nota del reintento (B2): más explícita; se añade al mismo turno.
RETRY_NOTE: Final = (
    '\n\n(The listeners are several friends or colleagues: translate "you" as informal plural for Spain '
    '(use "vosotros" forms such as estáis, tenéis, venid, no os preocupéis; never "ustedes").)'
)


def group_state(source: str, previous_sources: Iterable[str] = ()) -> bool:
    """¿Se dirige el hablante a un grupo? Mira el inglés de la frase y de las últimas 5 líneas de la escena.

    - Con marca de singular en la frase («sir», «honey»...) es que no.
    - Con marca de plural en la frase («you guys», «everyone»...) es que sí.
    - Si no, sí cuando hay marca de plural en las últimas 5 líneas previas y ninguna de singular.
    """
    if SINGULAR_EN.search(source):
        return False
    if PLURAL_EN.search(source):
        return True
    recent = [line for line in previous_sources if line.strip()][-STATE_WINDOW:]
    return any(PLURAL_EN.search(line) for line in recent) and not any(
        SINGULAR_EN.search(line) for line in recent
    )


# ---------------------------------------------------------------------------------------------------------
# Salida del modelo
# ---------------------------------------------------------------------------------------------------------
_NOTE_ECHO = re.compile(r"\n\s*\n\s*[\(\[].*$", re.DOTALL)


def clean_output(text: str) -> str:
    """Quita la nota de estilo que el modelo a veces repite tras la traducción (salto doble y paréntesis).

    En S7 ocurrió en el 6,6 % de las frases con la nota de plural; sin este recorte el filtro de longitud
    las rechazaría y no se pronunciarían.
    """
    return _NOTE_ECHO.sub("", text).strip()


# ---------------------------------------------------------------------------------------------------------
# Detector de «ustedes» residual
# ---------------------------------------------------------------------------------------------------------
# Imperativos y subjuntivos de ustedes frecuentes en diálogo (del detector del spike S7).
_USTED_FORMS: Final = frozenset(
    _words("""
    tomen vengan vayan síganme siganme sígame miren mírenme escuchen esperen abran cierren pasen entren salgan
    vean digan díganme hagan háganme pongan sean estén tengan den déjenme dejen callen corran suban bajen
    levanten coman beban lleven traigan tráiganme ayuden respiren mantengan permanezcan queden sigan vuelvan
    retrocedan recuerden olviden piensen intenten prueben acepten permitan compartan cojan agarren sujeten
    aguanten llamen contesten respondan ignoren confíen disparen disfruten abróchense aplaudan empaquen
    """)
)
_USTED_PRONOUN: Final = re.compile(r"(?<![\wáéíóúñü])ustedes(?![\wáéíóúñü])", re.IGNORECASE)
_ENCLITIC_END: Final = re.compile(r"(nse|nme|nnos|nlo|nla|nlos|nlas)$")


def has_ustedes(text: str) -> bool:
    """¿Queda «ustedes» en la traducción? Pronombre, imperativo en 3.ª plural o reflexivo («siéntense»).

    Es un detector léxico sin el inglés: puede dar falsos positivos con «que sean felices» o «que den»; por
    eso el reintento exige además la señal de plural informal de la escena (``group_state``).
    """
    if _USTED_PRONOUN.search(text):
        return True
    for match in _WORD.finditer(text):
        word = match.group(0).lower()
        if word in _USTED_FORMS:
            return True
        if _ENCLITIC_END.search(word) and _convert_reflexive_imperative(word) is not None:
            return True
    return False


# ---------------------------------------------------------------------------------------------------------
# Detector de «vosotros»
# ---------------------------------------------------------------------------------------------------------
_B: Final = r"(?<![\wáéíóúñü])"  # inicio de palabra sin depender de \b con acentos
_E: Final = r"(?![\wáéíóúñü])"
_L: Final = "a-záéíóúñü"
_VOS_PRONOUN: Final = re.compile(rf"{_B}(vosotros|vosotras|vuestr[oa]s?|os){_E}", re.IGNORECASE)
_VOS_SHORT: Final = re.compile(
    rf"{_B}(vais|sois|veis|dais|oís|habéis|reís|decís|salís|venís|vivís|sentís|pedís|podéis|queréis){_E}",
    re.IGNORECASE,
)
_VOS_PRESENT: Final = re.compile(rf"{_B}[{_L}]{{2,}}(áis|éis|ís){_E}", re.IGNORECASE)
_VOS_PAST: Final = re.compile(
    rf"{_B}[{_L}]{{2,}}(asteis|isteis|ásteis|ísteis|abais|íais|aréis|eréis|iréis|aríais|eríais|iríais|ais|eis){_E}",
    re.IGNORECASE,
)
_VOS_ENCLITIC: Final = re.compile(rf"{_B}[{_L}]{{2,}}(aos|eos|íos|ios){_E}", re.IGNORECASE)
_VOS_IMPERATIVE: Final = re.compile(
    rf"{_B}([{_L}]{{2,}}[aei]d)(me|te|lo|la|los|las|le|les|nos|se)?{_E}", re.IGNORECASE
)
_VOS_IMPERATIVE_OS: Final = re.compile(rf"{_B}(volved|id)(os)?{_E}", re.IGNORECASE)
# Sustantivos en -ad/-ed/-ud que no son imperativos de vosotros («ciudad», «verdad», «pared»).
_NOUNS_IN_D: Final = re.compile(r"(dad|tad|bad|ud|ced|sed|red|pared|mitad|verdad|edad)$", re.IGNORECASE)


def has_vosotros(text: str) -> bool:
    """¿Hay formas de 2.ª persona del plural de España («vosotros», «os», «vuestro», «-áis», «-ad»...)?

    Detector léxico y morfológico del spike S7 (precisión del 97,6 % en «vosotros» sobre 228 salidas).
    """
    if any(
        pattern.search(text)
        for pattern in (
            _VOS_PRONOUN,
            _VOS_SHORT,
            _VOS_PRESENT,
            _VOS_PAST,
            _VOS_ENCLITIC,
            _VOS_IMPERATIVE_OS,
        )
    ):
        return True
    return any(
        not _NOUNS_IN_D.search(match.group(1).lower()) or match.group(1).lower() == "dad"
        for match in _VOS_IMPERATIVE.finditer(text)
    )
