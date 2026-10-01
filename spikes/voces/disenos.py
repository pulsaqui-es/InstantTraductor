"""Voces femeninas DISEÑADAS con Qwen3-TTS-12Hz-1.7B-VoiceDesign (camino A del spike T040, 2.ª vuelta).

Cada diseño es una descripción en lenguaje natural (`instruct`). Se escriben en inglés (el idioma de los ejemplos de la documentación
del modelo: «Male, 17 years old, tenor range, ...») con la procedencia y el rasgo de acento pedidos de forma explícita; hay una
variante en español para comprobar si el modelo la entiende igual de bien. Los nombres son solo etiquetas para recordarlas.
"""

from __future__ import annotations

# Textos de referencia (8-10 s al ritmo natural). Son distintos de las 4 frases de prueba y llevan palabras con /θ/ y con /s/.
REF_TEXTOS: dict[str, str] = {
    "R1": "Cuando llegué a la estación, el tren ya se había marchado. Entonces me senté, respiré hondo y decidí esperar con calma al siguiente.",
    "R2": "¡Qué maravilla de día! Hace un sol precioso y el cielo está despejado. ¿Por qué no salimos a dar un paseo?",
    "R3": "A veces pienso que lo mejor de la vida son las cosas sencillas: un café caliente, una conversación tranquila y nada de prisa.",
    "R4": "Mi abuela siempre decía que la paciencia es la mejor medicina, y con el tiempo he entendido por qué lo decía tan convencida.",
}

ACENTO_EN = (
    "Native of {lugar}, Spain, NOT Latin American: a strong Castilian accent with distinción. She always pronounces 'z' and 'ce'/'ci' "
    "as the interdental fricative /θ/ like the English 'th' in 'think', and keeps the apical 's' for 's'. No seseo."
)

ACENTO_ES = (
    "Hablante nativa de castellano estándar de {lugar}, España, con acento peninsular: "
    "pronuncia la «z» y la «c» ante e/i como la fricativa interdental /θ/ (como la «th» inglesa), distinta de la «s»."
)

DISENOS: list[dict] = [
    {"id": "es-f-dis-01", "nombre": "Lucía", "lugar": "Madrid", "ref": "R1",
     "en": "Female, 25 years old, medium-pitched soft and warm voice, gentle and friendly, natural expressive intonation with a melodic contour, clear diction, relaxed natural pace.",
     "es": "Mujer de 25 años, voz suave y cálida de tono medio, amable y cercana, entonación natural y expresiva con una melodía marcada, dicción clara, ritmo pausado y natural.",
     "timbre": "tono medio, suave y cálida"},
    {"id": "es-f-dis-02", "nombre": "Paula", "lugar": "Valladolid", "ref": "R2",
     "en": "Female, 22 years old, slightly higher-pitched bright and sweet voice, youthful and cheerful with a smiling tone, lively and expressive intonation, crisp clear diction.",
     "es": "Mujer de 22 años, voz algo más aguda, brillante y dulce, juvenil y alegre con un tono sonriente, entonación viva y expresiva, dicción nítida.",
     "timbre": "algo aguda, brillante y dulce, alegre"},
    {"id": "es-f-dis-03", "nombre": "Marta", "lugar": "Toledo", "ref": "R3",
     "en": "Female, 28 years old, lower-pitched mellow velvety voice (alto), calm and soothing, soft intimate delivery, natural expressive intonation, clear diction, unhurried pace.",
     "es": "Mujer de 28 años, voz grave y aterciopelada (contralto), tranquila y reconfortante, entrega suave e íntima, entonación natural y expresiva, dicción clara, ritmo sin prisa.",
     "timbre": "grave, aterciopelada, serena"},
    {"id": "es-f-dis-04", "nombre": "Elena", "lugar": "Salamanca", "ref": "R4",
     "en": "Female, 24 years old, soft breathy gentle voice, tender and delicate, slightly quiet but perfectly clear, natural expressive intonation, relaxed pace.",
     "es": "Mujer de 24 años, voz suave, aireada y delicada, tierna, algo baja de volumen pero perfectamente clara, entonación natural y expresiva, ritmo relajado.",
     "timbre": "susurrante, tierna y delicada"},
    {"id": "es-f-dis-05", "nombre": "Carmen", "lugar": "Burgos", "ref": "R1",
     "en": "Female, 27 years old, clear articulate warm voice of medium pitch, like a friendly radio presenter, confident and engaging, expressive intonation with natural pitch variation, very clear diction.",
     "es": "Mujer de 27 años, voz clara, articulada y cálida de tono medio, como una locutora de radio cercana, segura y atractiva, entonación expresiva con variación natural del tono, dicción muy clara.",
     "timbre": "clara y articulada, tipo locutora cercana"},
    {"id": "es-f-dis-06", "nombre": "Irene", "lugar": "Madrid", "ref": "R2",
     "en": "Female, 26 years old, warm slightly husky voice with a smoky touch, relaxed and friendly conversational tone, medium-low pitch, natural expressive intonation, clear diction.",
     "es": "Mujer de 26 años, voz cálida y algo ronca con un toque ahumado, tono conversacional relajado y amistoso, tono medio-grave, entonación natural y expresiva, dicción clara.",
     "timbre": "cálida, algo ronca, conversacional"},
    {"id": "es-f-dis-07", "nombre": "Sofía", "lugar": "Zaragoza", "ref": "R3",
     "en": "Female, 23 years old, light airy voice with a smiling upbeat tone, soft and kind, medium-high pitch, lively natural intonation, clear diction.",
     "es": "Mujer de 23 años, voz ligera y aireada con un tono sonriente y animado, suave y amable, tono medio-agudo, entonación viva y natural, dicción clara.",
     "timbre": "ligera, aireada, sonriente"},
    {"id": "es-f-dis-08", "nombre": "Clara", "lugar": "Segovia", "ref": "R4",
     "en": "Female, 30 years old, calm reassuring warm voice of medium pitch, steady unhurried pace, soft and kind tone, natural expressive intonation, very clear diction.",
     "es": "Mujer de 30 años, voz serena, tranquilizadora y cálida de tono medio, ritmo constante y sin prisa, tono suave y amable, entonación natural y expresiva, dicción muy clara.",
     "timbre": "serena, tranquilizadora, ritmo constante"},
]


def respell_th(texto: str) -> str:
    """Reescribe z/ce/ci con «th» para que el modelo (que pronuncia las grafías inglesas) produzca un /θ/ (ver README, camino A).

    Solo se usa en el texto que se envía a VoiceDesign; el `ref_text` del modo ICL sigue siendo el texto normal.
    """
    import re

    t = re.sub(r"c(?=[eiéí])", "th", texto)
    t = re.sub(r"C(?=[eiéí])", "Th", t)
    t = t.replace("z", "th").replace("Z", "Th")
    return t


def instruct(d: dict, variante: str = "en") -> str:
    """Descripción completa de la voz: timbre + procedencia/acento, en inglés (`en`) o en español (`es`)."""
    plantilla = ACENTO_EN if variante == "en" else ACENTO_ES
    return d[variante] + " " + plantilla.format(lugar=d["lugar"])
