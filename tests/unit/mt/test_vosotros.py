"""Tests de ``mt/vosotros.py`` (T018, research R8): posedición, señales de escena y detectores.

Sin GPU ni modelos. Las frases inglesas son del corpus B0 del spike S7 (``spikes/habla_baja/corpus_b0.py``) y
las conversiones esperadas, de ``spikes/habla_baja/resultados/b2_conversiones_base_s42.txt`` (salidas
reales de Hy-MT2-7B). Los españoles de los singulares y de la 3.ª persona del plural son los que daría el
modelo; sirven para comprobar que la posedición no daña lo que no va a un grupo (S7: 0 de 24 y 0 de 19).
"""

from __future__ import annotations

import pytest

from instanttraductor.mt.vosotros import (
    PLURAL_NOTE,
    RETRY_NOTE,
    STATE_WINDOW,
    clean_output,
    group_state,
    has_ustedes,
    has_vosotros,
    postedit_vosotros,
)

# ---------------------------------------------------------------------------
# Posedición: conversiones del spike (salida real del 7B -> forma de vosotros)
# ---------------------------------------------------------------------------
CONVERSIONS: tuple[tuple[str, str, str], ...] = (
    (
        "Grab your sleeping bags and follow me.",
        "Tomen sus sacos de dormir y síganme.",
        "Tomad vuestros sacos de dormir y seguidme.",
    ),
    (
        "Sit down and I'll hand out the marshmallows.",
        "Siéntense y yo repartiré los malvaviscos.",
        "Sentaos y yo repartiré los malvaviscos.",
    ),
    (
        "Open your books to page twelve.",
        "Abren vuestros libros en la página doce.",
        "Abrid vuestros libros en la página doce.",
    ),
    ("Stop fighting, you two!", "¡Dejen de pelear, ustedes dos!", "¡Dejad de pelear, vosotros dos!"),
    ("Are you guys coming with me?", "¿Vienen ustedes conmigo?", "¿Venís vosotros conmigo?"),
    ("Crew, stand by for the jump.", "Equipo, prepárense para el salto.", "Equipo, preparaos para el salto."),
    (
        "Good morning, everyone, take a seat.",
        "Buenos días a todos, tomen asiento.",
        "Buenos días a todos, tomad asiento.",
    ),
    (
        "Welcome, everyone, please stay close together.",
        "Bienvenidos a todos, por favor quedense juntos.",
        "Bienvenidos a todos, por favor quedaos juntos.",
    ),
    ("Please sit down, both of you.", "Por favor, siéntense los dos.", "Por favor, sentaos los dos."),
    (
        "Do you have any questions about the treatment?",
        "¿Tienen alguna pregunta sobre el tratamiento?",
        "¿Tenéis alguna pregunta sobre el tratamiento?",
    ),
    (
        "Gather round, friends, and hear my tale!",
        "Reúnanse, amigos, y escuchen mi historia.",
        "Reuníos, amigos, y escuchad mi historia.",
    ),
    (
        "Welcome back, folks, are you ready to play?",
        "Bienvenidos de nuevo, ¿están listos para jugar?",
        "Bienvenidos de nuevo, ¿estáis listos para jugar?",
    ),
    ("Don't look at the audience!", "¡No miren al público!", "¡No miréis al público!"),
    (
        "Give it up for our contestants, everybody!",
        "¡Aplaudan a nuestros concursantes, todos!",
        "¡Aplaudid a nuestros concursantes, todos!",
    ),
    (
        "Did you guys see the mess in the kitchen?",
        "¿Vieron el desorden en la cocina?",
        "¿Visteis el desorden en la cocina?",
    ),
    (
        "Ladies and gentlemen, please fasten your seat belts.",
        "Señoras y señores, por favor, abróchense los cinturones de seguridad.",
        "Señoras y señores, por favor, abrochaos los cinturones de seguridad.",
    ),
    ("Have a nice trip, everyone.", "Que tengan un buen viaje, todos.", "Que tengáis un buen viaje, todos."),
    ("Pack your bags and let's go.", "Empaquen sus cosas y vámonos.", "Empacad vuestras cosas y vámonos."),
    ("Soldiers, listen carefully.", "Soldados, escuchen con atención.", "Soldados, escuchad con atención."),
    (
        "You have your orders, now move out.",
        "Tienen sus órdenes, ahora salgan.",
        "Tenéis vuestras órdenes, ahora salid.",
    ),
)


@pytest.mark.parametrize(("source", "model_output", "expected"), CONVERSIONS)
def test_postedit_converts_the_listener_to_vosotros(source: str, model_output: str, expected: str) -> None:
    assert postedit_vosotros(source, model_output) == expected


@pytest.mark.parametrize(("source", "model_output", "expected"), CONVERSIONS)
def test_postedit_is_idempotent(source: str, model_output: str, expected: str) -> None:
    assert postedit_vosotros(source, expected) == expected


def test_postedit_covers_every_tense_the_spike_handles() -> None:
    assert postedit_vosotros("You were great tonight.", "Estuvieron geniales esta noche.") == (
        "Estuvisteis geniales esta noche."
    )
    assert postedit_vosotros("Tell me, you two.", "Díganme, ustedes dos.") == "Decidme, vosotros dos."
    assert postedit_vosotros("You guys never listen.", "Ustedes nunca escuchaban.") == (
        "Vosotros nunca escuchabais."
    )
    assert postedit_vosotros("Would you guys come?", "¿Vendrían ustedes?") == "¿Vendríais vosotros?"
    assert postedit_vosotros("Don't touch anything, you two.", "No toquen nada, ustedes dos.") == (
        "No toquéis nada, vosotros dos."
    )


def test_postedit_changes_the_possessive_only_with_your_in_the_english() -> None:
    assert postedit_vosotros("Take your coats, guys.", "Tomen sus abrigos, chicos.") == (
        "Tomad vuestros abrigos, chicos."
    )
    # Sin «your» en el inglés, «sus» puede ser de otra persona: no se toca.
    assert postedit_vosotros("Take the coats, guys.", "Tomen sus abrigos, chicos.") == (
        "Tomad sus abrigos, chicos."
    )


# ---------------------------------------------------------------------------
# Sin daños: singulares y 3.ª persona del plural (corpus B0, etiquetas S y T)
# ---------------------------------------------------------------------------
SINGULARS: tuple[tuple[str, str], ...] = (
    ("Hey, buddy, are you okay?", "Oye, amigo, ¿estás bien?"),
    ("Take a deep breath and sit down.", "Respira hondo y siéntate."),
    ("You look terrible, did you sleep at all?", "Tienes muy mala pinta, ¿has dormido algo?"),
    ("Don't worry about the money.", "No te preocupes por el dinero."),
    ("Call me when you get home.", "Llámame cuando llegues a casa."),
    ("You're the best friend I've ever had.", "Eres el mejor amigo que he tenido."),
    ("Honey, put on your coat, it's freezing.", "Cariño, ponte el abrigo, hace un frío que pela."),
    ("Did you finish your homework?", "¿Has terminado los deberes?"),
    ("Don't talk to strangers.", "No hables con extraños."),
    ("You can do anything you want.", "Puedes hacer lo que quieras."),
    ("Come here and let me fix your hair.", "Ven aquí y deja que te arregle el pelo."),
    ("Do you want a sandwich?", "¿Quieres un bocadillo?"),
    ("You look amazing tonight.", "Estás espectacular esta noche."),
    ("Do you want to dance?", "¿Quieres bailar?"),
)
THIRD_PERSON_PLURAL: tuple[tuple[str, str], ...] = (
    ("We're expecting some turbulence.", "Esperamos algo de turbulencia."),
    ("The neighbors are so loud tonight.", "Los vecinos están muy ruidosos esta noche."),
    ("They never sleep, do they?", "Ellos nunca duermen, ¿verdad?"),
    (
        "I told them to keep it down but they didn't listen.",
        "Les dije que bajaran la voz, pero no escucharon.",
    ),
    ("They are coming over for dinner tomorrow.", "Vienen a cenar mañana."),
    ("Their kids break everything they touch.", "Sus hijos rompen todo lo que tocan."),
    ("Let them come in, they look cold.", "Déjalos entrar, parecen tener frío."),
    ("Where did they take the hostages?", "¿Adónde se llevaron a los rehenes?"),
    ("They said they would call us back in an hour.", "Dijeron que nos llamarían en una hora."),
    ("The thieves were hiding in the warehouse.", "Los ladrones se escondían en el almacén."),
    ("Tell them we need more time.", "Diles que necesitamos más tiempo."),
    ("They don't know we're watching them.", "No saben que los estamos vigilando."),
    ("Why do they always lie to us?", "¿Por qué siempre nos mienten?"),
    ("The students are doing great this year.", "Los estudiantes lo están haciendo genial este año."),
)


@pytest.mark.parametrize(("source", "model_output"), SINGULARS)
def test_postedit_does_not_touch_singular_listeners(source: str, model_output: str) -> None:
    assert postedit_vosotros(source, model_output) == model_output


@pytest.mark.parametrize(("source", "model_output"), THIRD_PERSON_PLURAL)
def test_postedit_does_not_touch_the_third_person_plural(source: str, model_output: str) -> None:
    assert postedit_vosotros(source, model_output) == model_output


def test_a_formal_ustedes_with_a_third_party_in_the_english_is_left_alone() -> None:
    # «they» + «ustedes»: ambiguo, no se toca (es el reintento con el modelo el que lo intenta).
    assert postedit_vosotros("They are late, you guys.", "Ustedes llegan tarde.") == "Ustedes llegan tarde."


def test_a_verb_after_a_plural_noun_keeps_its_own_subject() -> None:
    # «dijeron» es de «you»; «están» tiene su propio sujeto («los niños»).
    assert postedit_vosotros("You said the kids are tired.", "Dijeron que los niños están cansados.") == (
        "Dijisteis que los niños están cansados."
    )


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_postedit_of_blank_text_is_the_same_text(text: str) -> None:
    assert postedit_vosotros("Are you guys ready?", text) == text


def test_postedit_keeps_the_capitalisation_and_punctuation() -> None:
    assert postedit_vosotros("Are you guys ready?", "¿Están Ustedes listos?") == "¿Estáis Vosotros listos?"
    assert postedit_vosotros("Leave it, you two!", "¡Dejen eso, ustedes dos!") == "¡Dejad eso, vosotros dos!"


# ---------------------------------------------------------------------------
# Señal de escena
# ---------------------------------------------------------------------------
def test_a_plural_marker_in_the_previous_lines_makes_a_group() -> None:
    assert group_state("Do you understand?", ["Alright, everybody, gather around."]) is True


def test_a_plural_marker_in_the_sentence_itself_makes_a_group() -> None:
    assert group_state("Are you guys ready?") is True


def test_without_any_marker_it_is_not_a_group() -> None:
    assert group_state("Do you understand?", ["Open your books to page twelve."]) is False
    assert group_state("Do you understand?") is False


def test_a_singular_marker_in_the_window_cancels_the_group() -> None:
    previous = ["Alright, everybody, gather around.", "Hey, buddy, come here."]
    assert group_state("Do you understand?", previous) is False


def test_a_singular_marker_in_the_sentence_wins_over_a_plural_one() -> None:
    assert group_state("Sir, are you guys coming?", ["Everyone sit down."]) is False


def test_only_the_last_five_lines_are_looked_at() -> None:
    old_plural = "Alright, everybody, gather around."
    filler = [f"Line number {n}." for n in range(STATE_WINDOW)]
    assert group_state("Do you understand?", [old_plural, *filler]) is False
    assert group_state("Do you understand?", [*filler, old_plural]) is True


def test_blank_previous_lines_do_not_count_in_the_window() -> None:
    previous = ["Everyone sit down.", "", "  ", "Line one.", "Line two."]
    assert group_state("Do you understand?", previous) is True


# ---------------------------------------------------------------------------
# Recorte de la nota repetida
# ---------------------------------------------------------------------------
def test_clean_output_cuts_the_note_the_model_repeats() -> None:
    echoed = "¿Tenéis hambre?\n\n(Español de España, informal: usa «vosotros» con varias personas.)"
    assert clean_output(echoed) == "¿Tenéis hambre?"


def test_clean_output_cuts_from_the_first_double_break_with_a_parenthesis() -> None:
    assert clean_output("Venid aquí.\n\n(Note: algo)\n\nmás") == "Venid aquí."
    assert clean_output("Venid aquí.\n \n[nota]") == "Venid aquí."


def test_clean_output_keeps_a_normal_translation() -> None:
    assert clean_output("  Venid aquí (rápido).  ") == "Venid aquí (rápido)."
    assert (
        clean_output("Primera frase.\nSegunda (con paréntesis).")
        == "Primera frase.\nSegunda (con paréntesis)."
    )


def test_the_notes_are_appended_to_the_turn_as_a_parenthesised_paragraph() -> None:
    for note in (PLURAL_NOTE, RETRY_NOTE):
        assert note.startswith("\n\n(") and note.endswith(")")
        assert "vosotros" in note
        assert "ustedes" in note  # «never "ustedes"»
    # Lo que el modelo repita de estas notas lo recorta clean_output.
    assert clean_output("Hola." + PLURAL_NOTE) == "Hola."
    assert clean_output("Hola." + RETRY_NOTE) == "Hola."


# ---------------------------------------------------------------------------
# Detector de «ustedes» residual
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "¿Están ustedes listos?",
        "USTEDES llegan tarde.",
        "Tomen asiento.",
        "No miren al público.",
        "Siéntense, por favor.",
        "Abróchense los cinturones.",
        "Síganme.",
        "Tráiganme eso.",
    ],
)
def test_has_ustedes_finds_the_explicit_and_the_verbal_forms(text: str) -> None:
    assert has_ustedes(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "¿Estáis listos?",
        "Tomad asiento.",
        "Sentaos, por favor.",
        "¿Estás bien?",
        "Siéntate aquí.",
        "El señor Ustedo no ha venido.",
        "La ciudad estadounidense es enorme.",
        "Los vecinos están muy ruidosos.",
        "",
    ],
)
def test_has_ustedes_ignores_everything_else(text: str) -> None:
    assert has_ustedes(text) is False


def test_postedit_removes_the_ustedes_it_can_convert() -> None:
    for source, model_output, _ in CONVERSIONS:
        assert has_ustedes(postedit_vosotros(source, model_output)) is False, source


# ---------------------------------------------------------------------------
# Detector de «vosotros»
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "¿Tenéis hambre?",
        "Vosotros no sabéis nada.",
        "Venid aquí.",
        "Sentaos todos.",
        "Coged vuestras cosas.",
        "No os preocupéis.",
        "¿Vais a venir?",
        "Visteis el desorden.",
        "Llegabais tarde.",
        "Preparaos para el salto.",
    ],
)
def test_has_vosotros_finds_second_person_plural_forms(text: str) -> None:
    assert has_vosotros(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "¿Tienes hambre?",
        "Ustedes llegan tarde.",
        "La ciudad es enorme.",
        "Dime la verdad.",
        "La pared está sucia.",
        "Pon tu abrigo.",
        "",
    ],
)
def test_has_vosotros_ignores_other_forms_and_nouns_in_d(text: str) -> None:
    assert has_vosotros(text) is False


def test_postedit_output_is_detected_as_vosotros() -> None:
    for source, model_output, _ in CONVERSIONS:
        assert has_vosotros(postedit_vosotros(source, model_output)) is True, source


@pytest.mark.parametrize(
    ("source", "model_output", "expected"),
    [
        ("Don't touch it, you guys.", "No toquen nada, chicos.", "No toquéis nada, chicos."),
        ("Don't pay yet, you guys.", "No paguen todavía, chicos.", "No paguéis todavía, chicos."),
        ("Don't start yet, you guys.", "No empiecen todavía, chicos.", "No empecéis todavía, chicos."),
        ("Don't take it, you guys.", "No cojan nada, chicos.", "No cojáis nada, chicos."),
        ("Don't look any more, you guys.", "No busquen más, chicos.", "No busquéis más, chicos."),
    ],
)
def test_the_negative_imperative_keeps_the_spelling_of_the_stem(
    source: str, model_output: str, expected: str
) -> None:
    """Cambios ortográficos del subjuntivo de vosotros (-car, -gar, -zar, -ger): toquéis, paguéis..."""
    assert postedit_vosotros(source, model_output) == expected
