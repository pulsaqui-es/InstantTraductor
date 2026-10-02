"""Posedición por reglas: «ustedes» -> «vosotros» (español de España, tratamiento informal) con la señal del inglés.

Qué hace (B2):
- Pronombre: «ustedes» -> «vosotros»; posesivo «su(s)» -> «vuestro(s)/vuestra(s)» y «les» -> «os» solo si el inglés
  tiene «your»/«you» y no tiene «they/their/them».
- Verbos en 3.ª persona del plural dirigidos al oyente -> 2.ª plural, con un léxico de formas generado por reglas
  de conjugación (presente, pretérito, imperfecto, futuro, condicional, subjuntivo e imperativo):
  `están -> estáis`, `tomaron -> tomasteis`, `no tomen -> no toméis`, `tomen -> tomad`, `siéntense -> sentaos`.
- Quién es el oyente lo decide el INGLÉS: solo se convierte si el original lleva «you/your/guys...» (o es un
  imperativo) y no lleva «they/them/their». Los verbos precedidos de un sustantivo plural («los vecinos están...»)
  no se tocan, porque su sujeto es otro.
- Los casos que no se pueden resolver (verbo desconocido, ambiguo) se marcan en `Result.unresolved` para el reintento
  con el 7B.

Sin dependencias externas. Coste: décimas de milisegundo por frase (ver `bench`).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------------------------------------
# Léxico de formas
# ---------------------------------------------------------------------------------------------------------
# (lemma, banderas). Banderas: ie (e>ie), ue (o>ue), i (e>i), jue (u>ue), sent (sentir), dorm (dormir),
# zc (conocer), cz (vencer), uy (construir), iacc (enviar), g:<raíz> (raíz irregular del subjuntivo).
_REGULAR = """
hablar llamar tomar mirar esperar escuchar ayudar buscar dejar pasar entrar llegar llevar quedar cantar bailar
bajar subir cambiar cerrar:ie ganar usar pagar cuidar preparar contar:ue encontrar:ue mostrar:ue recordar:ue
probar:ue sonar:ue soñar:ue volar:ue costar:ue almorzar:ue acordar:ue demostrar:ue colgar:ue pensar:ie empezar:ie
comenzar:ie sentar:ie despertar:ie recomendar:ie negar:ie apretar:ie atravesar:ie gobernar:ie temblar:ie
regalar terminar acabar necesitar trabajar caminar practicar explicar tocar sacar olvidar empacar comprar vender
lavar limpiar cocinar disparar aplaudir abrir escribir recibir vivir subir sufrir decidir permitir compartir
aceptar ignorar disfrutar apoyar confiar:iacc enviar:iacc guiar:iacc evitar mejorar notar
armar ahorrar alejar acercar levantar relajar calmar tranquilizar abrochar sentir:sent mentir:sent preferir:sent
divertir:sent convertir:sent sugerir:sent advertir:sent herir:sent dormir:dorm morir:dorm
comer beber aprender correr romper creer deber meter responder esconder temer coger escoger recoger proteger
prometer ceder vencer:cz torcer:cz entender:ie perder:ie encender:ie defender:ie querer:ie
volver:ue poder:ue mover:ue resolver:ue devolver:ue envolver:ue doler:ue soler:ue llover:ue
parecer:zc conocer:zc ofrecer:zc merecer:zc agradecer:zc crecer:zc nacer:zc desaparecer:zc aparecer:zc
pedir:i servir:i repetir:i vestir:i elegir:i competir:i despedir:i medir:i impedir:i corregir:i seguir:i conseguir:i
perseguir:i reír:rei construir:uy destruir:uy incluir:uy huir:uy contribuir:uy distribuir:uy
dirigir exigir salir:g:salg conducir:zc traducir:zc producir:zc reducir:zc
jugar:jue
permanecer:zc obedecer:zc establecer:zc pertenecer:zc reconocer:zc descubrir cubrir ocurrir unir partir existir insistir
asistir cumplir discutir retroceder retirar agarrar sujetar apartar soltar:ue rendir:i disculpar perdonar firmar
entregar señalar abandonar atacar respetar arrodillar tumbar colocar apagar prestar interrumpir separar juntar
ocultar callar gritar llorar sonar:ue aguantar sacudir meter lanzar cruzar abrazar alcanzar realizar utilizar
organizar comenzar:ie despedir:i repartir cortar tirar tapar cargar recargar vigilar proteger acompañar invitar
ofrecer:zc
""".split()

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
    ("mantener", "man", "tener"), ("obtener", "ob", "tener"), ("contener", "con", "tener"),
    ("detener", "de", "tener"), ("sostener", "sos", "tener"), ("retener", "re", "tener"),
    ("convenir", "con", "venir"), ("intervenir", "inter", "venir"), ("prevenir", "pre", "venir"),
    ("proponer", "pro", "poner"), ("suponer", "su", "poner"), ("componer", "com", "poner"),
    ("imponer", "im", "poner"), ("disponer", "dis", "poner"), ("exponer", "ex", "poner"),
    ("reponer", "re", "poner"), ("deshacer", "des", "hacer"), ("rehacer", "re", "hacer"),
    ("contradecir", "contra", "decir"), ("predecir", "pre", "decir"), ("atraer", "at", "traer"),
    ("distraer", "dis", "traer"), ("contraer", "con", "traer"), ("extraer", "ex", "traer"),
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
    if first == "e":  # verbos en -ar
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
    if lemma in _IRREGULAR:
        return _IRREGULAR[lemma]
    suf = lemma[-2:]
    stem = lemma[:-2]
    if lemma == "reír":
        return ("ríen", "reís", "rían", "riáis", "reíd")
    cs = _change(stem, flag)
    if flag == "uy":
        return (stem + "yen", stem + "ís", stem + "yan", stem + "yáis", lemma[:-1] + "d")
    if flag == "iacc":
        return (stem + "ían" if False else stem[:-1] + "í" + stem[-1:] + "an", stem + "áis", stem[:-1] + "í" + stem[-1:] + "en", stem + "éis", lemma[:-1] + "d")
    if suf == "ar":
        pres3, pres2 = cs + "an", stem + "áis"
        subj3 = _subj_spell(cs, "en")
        subj2 = _subj_spell(stem, "éis")
    else:
        pres3 = cs + "en"
        if flag == "jue":
            pres3 = cs + "en"
        pres2 = stem + ("éis" if suf == "er" else "ís")
        if flag.startswith("g:"):
            base = flag[2:]
            subj3, subj2 = base + "an", base + "áis"
        else:
            sub_stem = cs
            if flag == "zc":
                sub_stem = stem + ("zc" if not stem.endswith("c") else "")
                sub_stem = stem[:-1] + "zc" if stem.endswith("c") else stem + "zc"
            elif flag == "cz":
                sub_stem = stem[:-1] + "z" if stem.endswith("c") else cs
            subj3 = _subj_spell(sub_stem, "an")
            vs = _vos_stem(stem, flag)
            if flag == "zc":
                vs = sub_stem
            elif flag == "cz":
                vs = sub_stem
            subj2 = _subj_spell(vs, "áis")
    return (pres3, pres2, subj3, subj2, lemma[:-1] + "d")


@dataclass(frozen=True)
class Lexicon:
    pres3: dict[str, str]  # presente 3pl -> 2pl
    pres3_imp: dict[str, str]  # presente 3pl -> imperativo de vosotros (para «Abren vuestros libros» -> «Abrid»)
    subj3: dict[str, tuple[str, str, str]]  # subj/imperativo ustedes -> (imperativo vosotros, subjuntivo 2pl, lemma)


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
    for lemma, prefix, base in _DERIVED:
        p3, p2, s3, s2, imp = _IRREGULAR[base]
        b = base
        # el derivado se forma quitando el infinitivo de la base y poniendo el prefijo
        stem_len = len(b) - 2
        del stem_len
        add(lemma, tuple(_prefixed(prefix, base, f, lemma) for f in (p3, p2, s3, s2, imp)))  # type: ignore[arg-type]
    return Lexicon(pres3, pres3_imp, subj3)


def _prefixed(prefix: str, base: str, form: str, lemma: str) -> str:
    """Forma de un derivado: el prefijo (lo que sobra del lema antes de la base) + la forma de la base."""
    head = lemma[: len(lemma) - len(base)]
    return head + form


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
_SUFFIX_EXCEPTIONS = {"fueron": "fuisteis", "dieron": "disteis", "vieron": "visteis", "iban": "ibais", "eran": "erais",
                      "oyeron": "oísteis", "hicieron": "hicisteis", "quisieron": "quisisteis", "pusieron": "pusisteis",
                      "pudieron": "pudisteis", "supieron": "supisteis", "tuvieron": "tuvisteis", "vinieron": "vinisteis",
                      "estuvieron": "estuvisteis", "trajeron": "trajisteis", "dijeron": "dijisteis", "hubieron": "hubisteis"}
# Verbos de uso frecuente que acaban igual pero no son pasados o futuros de 3.ª plural.
_NOT_VERBS = frozenset(
    "camaron aron ieron aban rán afán alemán capitán galán refrán sartén también tan quién cuán esperanzán "
    "jamás además demás compás ademán desván huracán volcán rehén bien sin según aún pan plan clan estén tengan "
    "estén sean vengan vayan".split()
)

_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
_EN_YOU = re.compile(r"\b(you|your|yours|yourself|yourselves|y'all|you're|you've|you'd|you'll|guys|everyone|everybody|folks|kids|team|class|crew|soldiers|friends)\b", re.I)
_EN_YOUR = re.compile(r"\b(your|yours|yourselves|yourself)\b", re.I)
_EN_THEY = re.compile(r"\b(they|them|their|theirs|they're|they've|they'd)\b", re.I)
_EN_OTHER_POSS = re.compile(r"\b(his|her|its|hers)\b", re.I)
_EN_IMP = re.compile(
    r"^(please\b|don't\b|do not\b|never\b|let me\b|come\b|go\b|take\b|put\b|get\b|give\b|tell\b|look\b|listen\b|"
    r"wait\b|stay\b|keep\b|hold\b|follow\b|be\b|sit\b|stand\b|stop\b|run\b|hurry\b|bring\b|leave\b|call\b|ask\b|try\b|"
    r"watch\b|move\b|open\b|close\b|turn\b|check\b|read\b|write\b|eat\b|drink\b|clean\b|help\b|pack\b|grab\b|hand\b|"
    r"send\b|make\b|show\b|pass\b|wash\b|calm\b|shake\b|slowly\b|cover\b|drop\b|gather\b|welcome\b|alright\b|okay\b|"
    r"good morning\b|hey\b|crew\b|class\b|kids\b|soldiers\b|ladies\b|everyone\b|folks\b|guys\b|[A-Z][a-z]+,)",
    re.I,
)
_NEG_EN = re.compile(r"^(don't|do not|never)\b", re.I)
# Antes del verbo solo puede haber estas palabras (sujeto elidido o «ustedes») para convertirlo.
_PRE_OK = frozenset(
    "ustedes vosotros no se ya siempre nunca también todavía aún ahora así entonces y e o pero que si cuando donde "
    "como por favor bien mejor casi solo sólo todos todas tampoco jamás ¿ ¡ aquí allí hoy mañana anoche ayer más "
    "mucho muy aquí ahí luego después antes tan estoy".split()
)
_DET_PL = re.compile(r"^(los|las|unos|unas|estos|esas|esos|estas|aquellos|aquellas|mis|tus|sus|nuestros|nuestras|vuestros|vuestras|muchos|muchas|dos|tres|cuatro|cinco)$", re.I)


@dataclass
class Result:
    text: str
    changed: bool = False
    rules: list[str] = field(default_factory=list)
    unresolved: bool = False  # hay una marca de «ustedes» o 3.ª plural que no se ha podido convertir


def _match_case(src: str, new: str) -> str:
    return new.capitalize() if src[:1].isupper() else new


def _clause_start_ok(tokens: list[tuple[str, bool]], i: int) -> bool:
    """¿Las palabras entre el comienzo de la cláusula y la palabra `i` son solo elementos de la lista blanca?"""
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
    """Convierte una forma de 3.ª plural a 2.ª plural. Devuelve (forma nueva, regla) o None si no la conoce."""
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


def postedit(en: str, es: str, *, policy: str = "plural") -> Result:
    """Convierte «ustedes» y la 3.ª plural dirigida al oyente en 2.ª plural de España, con la señal del inglés."""
    res = Result(es)
    if not es.strip():
        return res
    en_you = bool(_EN_YOU.search(en))
    en_they = bool(_EN_THEY.search(en))
    en_imp = bool(_EN_IMP.search(en.strip()))
    negative = bool(_NEG_EN.match(en.strip()))
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
        return res
    if not (en_you or en_imp or has_ust):
        return res
    if en_they and has_ust:
        res.unresolved = True  # ambiguo: no se toca
        return res

    converted_any = has_ust
    out = [w for w, _ in tokens]
    first_word_idx = next((i for i, (w, is_w) in enumerate(tokens) if is_w and w.lower() not in {"no", "por", "favor"}), None)
    seen_neg = False
    for i, (w, is_w) in enumerate(tokens):
        if not is_w:
            continue
        wl = w.lower()
        if wl == "no":
            seen_neg = True
        if wl == "ustedes":
            out[i] = _match_case(w, "vosotros")
            res.rules.append("pron")
            continue
        refl = _convert_reflexive_imperative(w) if (en_imp or has_ust) and re.search(r"(nse|nme|nnos|nlo|nla|nlos|nlas)$", wl) else None
        if refl and _clause_start_ok(tokens, i):
            out[i] = _match_case(w, refl[0])
            res.rules.append(refl[1])
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
        if wl in LEX.subj3 or wl in LEX.pres3 or wl in _SUFFIX_EXCEPTIONS or any(wl.endswith(o) for o, _ in _SUFFIX_RULES):
            if not imperative_slot and not (en_you or has_ust or (en_imp and wl in LEX.subj3)):
                continue  # sin «you» en el inglés, un verbo en 3.ª plural suelto puede ser de otro sujeto
            if wl == "ven" and not has_ust:
                continue  # «ven» es el imperativo de «venir» (tú) mucho más a menudo que «ven» de «ver»
            if prev1 == "se" and not has_ust and wl not in LEX.subj3:
                continue  # «se están cerrando»: pasiva refleja, el sujeto es otro
            if en_imp and i == first_word_idx and wl in LEX.pres3_imp and wl not in LEX.subj3 and not neg_here:
                out[i] = _match_case(w, LEX.pres3_imp[wl])
                res.rules.append("imp-from-pres")
                converted_any = True
                continue
            conv = _convert_form(w, imperative_slot=bool(imperative_slot) and not neg_here, negative=neg_here)
            if conv:
                out[i] = _match_case(w, conv[0])
                res.rules.append(conv[1])
                converted_any = True
    text = "".join(out)
    if converted_any:
        # «se» delante de un verbo convertido -> «os»; «les» -> «os»; posesivos
        if en_you or has_ust:
            text = re.sub(r"(?<![\wáéíóúñü])se(?= [a-záéíóúñü]*(?:éis|áis|ís)\b)", "os", text)
            text = re.sub(r"(?<![\wáéíóúñü])Se(?= [a-záéíóúñü]*(?:éis|áis|ís)\b)", "Os", text)
            text = re.sub(r"(?<![\wáéíóúñü])les(?![\wáéíóúñü])", "os", text)
            text = re.sub(r"(?<![\wáéíóúñü])Les(?![\wáéíóúñü])", "Os", text)
            if _EN_YOUR.search(en) and not _EN_OTHER_POSS.search(en):
                text = _fix_possessives(text)
    # ¿Queda 3.ª plural dirigida sin convertir?
    res.text = text
    res.changed = text != es
    if res.changed:
        res.rules = sorted(set(res.rules))
    return res


_FEM_NOUN = re.compile(r"(a|as|ión|iones|dad|dades|tad|tades|umbre|umbres|ez|eces|is|ie)$", re.I)
_MASC_EXC = frozenset("día días mapa mapas problema problemas sistema sistemas tema temas idioma programa programas".split())
_FEM_EXC = frozenset("órdenes noches llaves clases tardes partes fuentes calles manos flores voces luces cruces leyes imágenes señales mano clase noche llave parte fuente calle flor voz luz cruz ley imagen señal".split())


def _fix_possessives(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        poss, noun = m.group(1), m.group(2)
        plural = poss.lower() == "sus"
        fem = (bool(_FEM_NOUN.search(noun)) and noun.lower() not in _MASC_EXC) or noun.lower() in _FEM_EXC
        if plural:
            new = "vuestras" if fem else "vuestros"
        else:
            new = "vuestra" if fem else "vuestro"
        return _match_case(poss, new) + " " + noun

    return re.sub(r"(?<![\wáéíóúñü])(su|sus|Su|Sus)\s+([a-záéíóúñü]+)", repl, text)


def postedit_for_context(en: str, es: str) -> str:
    """Para el contexto del prompt (B1f): la traducción previa saneada con las mismas reglas."""
    return postedit(en, es).text


def bench(n: int = 2000) -> float:
    """Microsegundos medios por frase."""
    samples = [
        ("Are you guys ready?", "¿Están ustedes listos?"),
        ("Take your coats and follow me.", "Tomen sus abrigos y síganme."),
        ("They said they would call.", "Dijeron que llamarían."),
        ("Don't touch anything, you two.", "No toquen nada, ustedes dos."),
    ]
    t = time.perf_counter()
    for k in range(n):
        en, es = samples[k % len(samples)]
        postedit(en, es)
    return (time.perf_counter() - t) / n * 1e6


if __name__ == "__main__":
    tests = [
        ("Are you guys ready?", "¿Están ustedes listos?"),
        ("Grab your sleeping bags and follow me.", "Tomen sus sacos de dormir y síganme."),
        ("Sit down and I'll hand out the marshmallows.", "Siéntense y yo repartiré los malvaviscos."),
        ("Don't look at the audience!", "¡No miren al público!"),
        ("Do you have any questions about the treatment?", "¿Tienen alguna pregunta sobre el tratamiento?"),
        ("Did you guys see the mess in the kitchen?", "¿Vieron el desorden en la cocina?"),
        ("Pack your bags and let's go.", "Empaquen sus cosas y vámonos."),
        ("You have your orders, now move out.", "Tienen sus órdenes, ahora salgan."),
        ("Have a nice trip, everyone.", "Que tengan un buen viaje, todos."),
        ("Keep your heads down and stay together.", "Mantengan la cabeza baja y permanezcan juntos."),
        ("Stay for dessert, you can't leave yet.", "Quédense a tomar el postre, aún no pueden irse."),
        ("They never sleep, do they?", "Ellos nunca duermen, ¿verdad?"),
        ("Be careful on the stairs, they're slippery.", "Ten cuidado en las escaleras, están resbaladizas."),
        ("Welcome back, folks, are you ready to play?", "Bienvenidos de nuevo, ¿están listos para jugar?"),
        ("Help yourselves to the drinks.", "Sírvanse las bebidas ustedes mismos."),
        ("You'll never see them again.", "Nunca los volverán a ver."),
        ("Do you want to come?", "¿Quieren venir?"),
        ("Come in and take a seat.", "Entren y tomen asiento."),
        ("Ladies and gentlemen, please fasten your seat belts.", "Señoras y señores, por favor, abróchense los cinturones."),
        ("Don't forget your tickets.", "No olviden sus entradas."),
        ("You were great tonight.", "Estuvieron geniales esta noche."),
        ("Stand up and tell me your names.", "Levántense y díganme sus nombres."),
    ]
    for en, es in tests:
        r = postedit(en, es)
        print(f"{'*' if r.changed else ' '} {en}\n    {es}\n    {r.text}  {r.rules}")
    print(f"{bench():.0f} µs/frase")
