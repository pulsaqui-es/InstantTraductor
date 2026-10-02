"""Corpus B0: frases inglesas nuevas (no están en el corpus de S2) para medir «vosotros».

Cada escena es un trozo de diálogo de 6 líneas con un destinatario por defecto; la etiqueta de cada línea es
lo que se espera del español de España con tratamiento INFORMAL por defecto (decisión del humano):

  P  «you» PLURAL informal -> vosotros (2.ª persona del plural)
  S  «you» singular informal -> tú
  F  «you» formal (usted/ustedes) -> control: no se mide como fallo; informa de un futuro ajuste «auto»
  T  3.ª persona del plural legítima («they», «the kids»...) -> control de daño: NO debe pasar a «vosotros»

Etiquetado a mano (por mí, no por la persona usuaria: ver README, límites). `kind`: imp (imperativo), neg
(imperativo negativo), q (pregunta con «you» sin marca), st (afirmación). `marked`: la frase lleva una marca
explícita de plural en inglés («you guys», «all of you», «you two», «everyone»...).

El contexto de cada línea (las líneas anteriores de su escena) lo aporta `run_translation` con las
traducciones que el propio modelo ha producido, como en la sesión real.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    idx: int
    scene: int
    text: str
    label: str  # P, S, F, T
    kind: str  # imp, neg, q, st
    marked: bool


_MARK = re.compile(
    r"\b(you guys|you two|you three|you both|both of you|all of you|you all|y'all|everyone|everybody|"
    r"guys|kids|children|boys|girls|folks|team|class|gentlemen|ladies|yourselves|you lot)\b",
    re.IGNORECASE,
)

# (destinatario por defecto, [(texto, etiqueta_o_None, tipo)]) - None = destinatario por defecto.
_RAW: list[tuple[str, list[tuple[str, str | None, str]]]] = [
    ("P", [  # 1. monitor de campamento
        ("Alright, everybody, gather around the fire.", None, "imp"),
        ("Grab your sleeping bags and follow me.", None, "imp"),
        ("Don't wander off, it gets dark fast out here.", None, "neg"),
        ("Are you ready for the hike tomorrow?", None, "q"),
        ("You did a great job setting up the tents today.", None, "st"),
        ("Sit down and I'll hand out the marshmallows.", None, "imp"),
    ]),
    ("P", [  # 2. profesora
        ("Open your books to page twelve.", None, "imp"),
        ("Please be quiet and listen carefully.", None, "imp"),
        ("Do you understand the instructions?", None, "q"),
        ("You have ten minutes to finish the exercise.", None, "st"),
        ("Don't talk to each other during the test.", None, "neg"),
        ("Hand in your papers when you're done.", None, "imp"),
    ]),
    ("P", [  # 3. madre con dos hijos
        ("Wash your hands before dinner, both of you.", None, "imp"),
        ("Are you hungry?", None, "q"),
        ("Eat your vegetables, please.", None, "imp"),
        ("Stop fighting, you two!", None, "imp"),
        ("You're going to be late for school.", None, "st"),
        ("Put your shoes on and get in the car.", None, "imp"),
    ]),
    ("P", [  # 4. amigos de viaje
        ("Are you guys coming with me?", None, "q"),
        ("Come on, we're going to miss the train.", None, "imp"),
        ("Hurry up, the doors are closing!", None, "imp"),
        ("Did you bring the snacks?", None, "q"),
        ("Wait for me at the station.", None, "imp"),
        ("You look tired, get some rest on the way.", None, "imp"),
    ]),
    ("P", [  # 5. entrenador
        ("Listen up, team, this is our last practice.", None, "imp"),
        ("Run three laps and then stretch.", None, "imp"),
        ("Don't give up now, you're almost there!", None, "neg"),
        ("Have you all warmed up?", None, "q"),
        ("You played better than I expected.", None, "st"),
        ("Drink some water and take a break.", None, "imp"),
    ]),
    ("P", [  # 6. agente a dos sospechosos (informal, entre colegas de patrulla)
        ("Where were you two last night?", None, "q"),
        ("Don't lie to me, I know you were there.", None, "neg"),
        ("Tell me the truth, both of you.", None, "imp"),
        ("Do you know what happens if you keep quiet?", None, "q"),
        ("Stay right here and don't move.", None, "neg"),
        ("You can call a lawyer if you want.", None, "st"),
    ]),
    ("P", [  # 7. nave espacial, capitana a la tripulación
        ("Crew, stand by for the jump.", None, "imp"),
        ("Check your harnesses and strap in.", None, "imp"),
        ("Do you have the coordinates?", None, "q"),
        ("Keep your eyes on the monitors.", None, "imp"),
        ("Don't touch anything until I say so.", None, "neg"),
        ("You've all done an amazing job.", None, "st"),
    ]),
    ("P", [  # 8. niños en el parque
        ("Look, you guys, a squirrel!", None, "imp"),
        ("Do you want to play hide and seek?", None, "q"),
        ("Come with me, I know a secret place.", None, "imp"),
        ("Don't tell anybody where we're going.", None, "neg"),
        ("You're the best friends ever.", None, "st"),
        ("Let's race, and the last one to the tree loses.", None, "imp"),
    ]),
    ("P", [  # 9. jefa a su equipo de oficina
        ("Good morning, everyone, take a seat.", None, "imp"),
        ("Have you read the report I sent you?", None, "q"),
        ("Please send me your ideas by Friday.", None, "imp"),
        ("You have a big opportunity here.", None, "st"),
        ("Don't forget the deadline.", None, "neg"),
        ("Let me know if you need anything.", None, "imp"),
    ]),
    ("P", [  # 10. cocina, hermanos adolescentes
        ("Did you two eat all the cookies?", None, "q"),
        ("Clean this mess up right now.", None, "imp"),
        ("You never listen to me!", None, "st"),
        ("Don't make me ask again.", None, "neg"),
        ("Come downstairs and help me with the groceries.", None, "imp"),
        ("Are you coming or not?", None, "q"),
    ]),
    ("P", [  # 11. guía turístico
        ("Welcome, everyone, please stay close together.", None, "imp"),
        ("You can take pictures, but don't use the flash.", None, "st"),
        ("Follow me to the main hall.", None, "imp"),
        ("Do you see the painting on the left?", None, "q"),
        ("Be careful on the stairs, they're slippery.", None, "imp"),
        ("Take your time, you have an hour to explore.", None, "imp"),
    ]),
    ("P", [  # 12. juego cooperativo, equipo en el chat de voz
        ("Okay guys, here's the plan.", None, "st"),
        ("You take the left side and we'll go right.", None, "st"),
        ("Cover me while I reload.", None, "imp"),
        ("Where are you?", None, "q"),
        ("Don't shoot, it's us!", None, "neg"),
        ("Nice work, you saved the whole team.", None, "st"),
    ]),
    ("P", [  # 13. abuela con los nietos
        ("Come here, you two, give me a big hug.", None, "imp"),
        ("You've grown so much since last summer!", None, "st"),
        ("Are you hungry? I made your favorite soup.", None, "q"),
        ("Sit down and tell me everything about school.", None, "imp"),
        ("Don't run in the house.", None, "neg"),
        ("Do you want to hear a story?", None, "q"),
    ]),
    ("P", [  # 14. médico a los padres y al niño... (plural: a los padres)
        ("Please sit down, both of you.", None, "imp"),
        ("Do you have any questions about the treatment?", None, "q"),
        ("You should bring him back next week.", None, "st"),
        ("Don't worry, he's going to be fine.", None, "neg"),
        ("Make sure he rests and drinks plenty of water.", None, "imp"),
        ("Call me if you notice anything strange.", None, "imp"),
    ]),
    ("P", [  # 15. taberna de fantasía
        ("Gather round, friends, and hear my tale!", None, "imp"),
        ("Do you dare to enter the cave?", None, "q"),
        ("Take up your swords and follow me.", None, "imp"),
        ("You'll never find the treasure without me.", None, "st"),
        ("Don't trust the stranger by the door.", None, "neg"),
        ("Drink up, you'll need your strength.", None, "imp"),
    ]),
    ("P", [  # 16. presentador de concurso
        ("Welcome back, folks, are you ready to play?", None, "q"),
        ("You have thirty seconds to answer.", None, "st"),
        ("Don't look at the audience!", None, "neg"),
        ("Give it up for our contestants, everybody!", None, "imp"),
        ("Do you want to lock in your answer?", None, "q"),
        ("Stay with us, we'll be right back.", None, "imp"),
    ]),
    ("P", [  # 17. compañeros de piso
        ("Did you guys see the mess in the kitchen?", None, "q"),
        ("Please clean up after yourselves.", None, "imp"),
        ("You promised you would do the dishes.", None, "st"),
        ("Don't leave your stuff in the hallway.", None, "neg"),
        ("Tell me when you're leaving so I can lock the door.", None, "imp"),
        ("Are you going to the party tonight?", None, "q"),
    ]),
    ("P", [  # 18. piloto a los pasajeros
        ("Ladies and gentlemen, please fasten your seat belts.", None, "imp"),
        ("We're expecting some turbulence.", "T", "st"),
        ("Stay seated until the light goes off.", None, "imp"),
        ("Thank you for flying with us, we hope you enjoy the flight.", None, "st"),
        ("Don't use your phones during takeoff.", None, "neg"),
        ("Have a nice trip, everyone.", None, "imp"),
    ]),
    ("P", [  # 19. hermanas
        ("Are you coming to the beach with us?", None, "q"),
        ("Pack your bags and let's go.", None, "imp"),
        ("You two always take forever to get ready.", None, "st"),
        ("Don't forget the sunscreen.", None, "neg"),
        ("Do you have your towels?", None, "q"),
        ("Wait here, I'll bring the car around.", None, "imp"),
    ]),
    ("P", [  # 20. capitán a los soldados
        ("Soldiers, listen carefully.", None, "imp"),
        ("You have your orders, now move out.", None, "imp"),
        ("Do you understand what's at stake?", None, "q"),
        ("Don't fire until I give the signal.", None, "neg"),
        ("Keep your heads down and stay together.", None, "imp"),
        ("I'm proud of every one of you.", None, "st"),
    ]),
    ("P", [  # 21. youtubers, a su audiencia
        ("What's up, guys, welcome back to the channel!", None, "st"),
        ("Today you're going to see something crazy.", None, "st"),
        ("Make sure you hit the subscribe button.", None, "imp"),
        ("Let me know in the comments what you think.", None, "imp"),
        ("Don't forget to like the video.", None, "neg"),
        ("Do you want to see more videos like this?", None, "q"),
    ]),
    ("P", [  # 22. dos vecinos a punto de pelearse
        ("Calm down, you two, there's no need to shout.", None, "imp"),
        ("Why are you so angry?", None, "q"),
        ("Shake hands and forget about it.", None, "imp"),
        ("You're acting like children.", None, "st"),
        ("Don't make this worse than it is.", None, "neg"),
        ("Come inside and have a cup of tea.", None, "imp"),
    ]),
    ("P", [  # 23. instructora de yoga
        ("Close your eyes and breathe deeply.", None, "imp"),
        ("Can you feel the tension leaving your shoulders?", None, "q"),
        ("Stretch your arms above your heads.", None, "imp"),
        ("Don't hold your breath.", None, "neg"),
        ("You're doing great, everyone.", None, "st"),
        ("Slowly open your eyes when you're ready.", None, "imp"),
    ]),
    ("P", [  # 24. policía a un grupo de manifestantes (informal en el doblaje)
        ("Move back, all of you!", None, "imp"),
        ("Don't cross the line.", None, "neg"),
        ("You're blocking the street.", None, "st"),
        ("Go home before someone gets hurt.", None, "imp"),
        ("Do you hear me?", None, "q"),
        ("Leave now and nobody will be arrested.", None, "imp"),
    ]),
    ("P", [  # 25. película de aventuras, grupo en una cueva
        ("Keep quiet, you guys, I hear something.", None, "imp"),
        ("Look at the walls, do you see those symbols?", None, "q"),
        ("Hold on to the rope and don't let go.", None, "imp"),
        ("You'd better get out of here, now!", None, "st"),
        ("Run, run, don't look back!", None, "imp"),
        ("Come on, you can make it!", None, "imp"),
    ]),
    ("P", [  # 26. fiesta de cumpleaños
        ("Come in, everyone, the cake is ready!", None, "imp"),
        ("Make a wish and blow out the candles.", None, "imp"),
        ("Did you all bring a present?", None, "q"),
        ("You really didn't have to.", None, "st"),
        ("Help yourselves to the drinks.", None, "imp"),
        ("Don't leave without saying goodbye.", None, "neg"),
    ]),
    ("P", [  # 27. conductor de autobús escolar
        ("Sit down and buckle up, kids.", None, "imp"),
        ("Where are you going this weekend?", None, "q"),
        ("Don't stick your hands out the window.", None, "neg"),
        ("Be good and listen to your teacher.", None, "imp"),
        ("You're my favorite group this year.", None, "st"),
        ("Get off here, you've arrived.", None, "imp"),
    ]),
    ("P", [  # 28. cena con amigos
        ("Do you want some more wine?", None, "q"),
        ("Pass me the salt, please.", None, "imp"),
        ("You should try the lasagna, it's amazing.", None, "st"),
        ("Don't be shy, there's plenty for everyone.", None, "neg"),
        ("Have you met my brother?", None, "q"),
        ("Stay for dessert, you can't leave yet.", None, "imp"),
    ]),
    ("S", [  # 29. a un solo amigo (control singular informal)
        ("Hey, buddy, are you okay?", None, "q"),
        ("Take a deep breath and sit down.", None, "imp"),
        ("You look terrible, did you sleep at all?", None, "q"),
        ("Don't worry about the money.", None, "neg"),
        ("Call me when you get home.", None, "imp"),
        ("You're the best friend I've ever had.", None, "st"),
    ]),
    ("S", [  # 30. madre a su hija
        ("Honey, put on your coat, it's freezing.", None, "imp"),
        ("Did you finish your homework?", None, "q"),
        ("Don't talk to strangers.", None, "neg"),
        ("You can do anything you want.", None, "st"),
        ("Come here and let me fix your hair.", None, "imp"),
        ("Do you want a sandwich?", None, "q"),
    ]),
    ("S", [  # 31. dos amigos en una cita
        ("You look amazing tonight.", None, "st"),
        ("Do you want to dance?", None, "q"),
        ("Tell me about your day.", None, "imp"),
        ("Don't be nervous, I'm just as scared as you.", None, "neg"),
        ("Where did you learn to cook like this?", None, "q"),
        ("Come closer, I can't hear you.", None, "imp"),
    ]),
    ("S", [  # 32. entrenador a un jugador
        ("Take the ball and run, kid!", None, "imp"),
        ("You've got a gift, you know that?", None, "st"),
        ("Don't think, just react.", None, "neg"),
        ("Are you ready for the final?", None, "q"),
        ("Keep your head up.", None, "imp"),
        ("Go and show them what you can do.", None, "imp"),
    ]),
    ("F", [  # 33. comisaría, agente a un testigo (formal singular)
        ("Please have a seat, sir.", None, "imp"),
        ("Could you tell me where you were last night, ma'am?", None, "q"),
        ("Do you recognize this man, Mr. Hale?", None, "q"),
        ("Thank you for your time, Detective.", None, "st"),
        ("Would you like some water, Madam Chair?", None, "q"),
        ("Your Honor, may I approach the bench?", None, "q"),
    ]),
    ("F", [  # 34. hotel, recepcionista a un cliente
        ("Good evening, sir, how may I help you?", None, "q"),
        ("Please sign here, Mrs. Collins.", None, "imp"),
        ("Do you need help with your luggage?", None, "q"),
        ("Your room is on the third floor.", None, "st"),
        ("Enjoy your stay, Mr. Reyes.", None, "imp"),
        ("Would you care for a wake-up call?", None, "q"),
    ]),
    ("F", [  # 35. rey a su corte (formal plural: ustedes)
        ("Ladies and gentlemen of the court, please be seated.", None, "imp"),
        ("Honored guests, I thank you for coming.", None, "st"),
        ("Gentlemen, you may now proceed to the hall.", None, "st"),
        ("My lords, will you stand with me?", None, "q"),
        ("Your Majesty, the guests have arrived.", None, "st"),
        ("Please accept our humble gratitude, my lord.", None, "imp"),
    ]),
    ("T", [  # 36. vecinos ruidosos: tercera persona del plural, control de daño
        ("The neighbors are so loud tonight.", None, "st"),
        ("They never sleep, do they?", None, "q"),
        ("I told them to keep it down but they didn't listen.", None, "st"),
        ("They are coming over for dinner tomorrow.", None, "st"),
        ("Their kids break everything they touch.", None, "st"),
        ("Let them come in, they look cold.", None, "imp"),
    ]),
    ("T", [  # 37. conversación sobre unos criminales
        ("Where did they take the hostages?", None, "q"),
        ("They said they would call us back in an hour.", None, "st"),
        ("The thieves were hiding in the warehouse.", None, "st"),
        ("Tell them we need more time.", None, "imp"),
        ("They don't know we're watching them.", None, "st"),
        ("Why do they always lie to us?", None, "q"),
    ]),
    ("T", [  # 38. profesor habla de los alumnos con otro profesor
        ("The students are doing great this year.", None, "st"),
        ("They finish all their homework on time.", None, "st"),
        ("Did they pass the math exam?", None, "q"),
        ("Give them a few more days to study.", None, "imp"),
        ("They want to go on a trip in June.", None, "st"),
        ("I think they deserve a reward.", None, "st"),
    ]),
]


def _build() -> tuple[Line, ...]:
    lines: list[Line] = []
    for scene_no, (default, items) in enumerate(_RAW):
        for text, label, kind in items:
            lines.append(Line(len(lines), scene_no, text, label or default, kind, bool(_MARK.search(text))))
    return tuple(lines)


LINES: tuple[Line, ...] = _build()
N_SCENES = len(_RAW)


def validate() -> None:
    counts: dict[str, int] = {}
    for line in LINES:
        counts[line.label] = counts.get(line.label, 0) + 1
    assert counts.get("P", 0) >= 120, counts
    assert len(LINES) >= 150, len(LINES)


if __name__ == "__main__":
    validate()
    from collections import Counter

    print(len(LINES), "frases", N_SCENES, "escenas", dict(Counter(line.label for line in LINES)))
    print("P por tipo:", dict(Counter(line.kind for line in LINES if line.label == "P")))
    print("P con marca:", sum(1 for line in LINES if line.label == "P" and line.marked))
