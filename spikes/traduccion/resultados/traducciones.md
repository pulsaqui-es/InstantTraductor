# Traducciones de la prueba S2 (Hy-MT2-1.8B-Q8_0.gguf, prompt final)

- Configuración: `final` = mensaje de sistema con el estilo + 12 ejemplos previos de español de España + las 4 frases anteriores de la escena como turnos de chat (cada turno de usuario lleva la instrucción de traducir) + glosario con la plantilla oficial «Terminology» en chino (ver README, «Método»).
- Muestreo: temperatura 0,7, top_p 0,6, top_k 20, penalización de repetición 1,05, semilla 42.
- Modelo y servidor: `Hy-MT2-1.8B-Q8_0.gguf`, llama.cpp v0.5.0 (build b11146).
- Fecha de la medición: 2026-10-01T01:18:57+02:00.

Las traducciones NO están corregidas: son la salida tal cual del modelo, para revisión humana. La columna «Avisos» recoge lo que detectan las heurísticas automáticas (ver README); una línea sin avisos no garantiza que la traducción sea buena.

Significado de los avisos: `léxico:X` = NO se cumple la comprobación de vocabulario de España «X» (falta el término peninsular o aparece uno no peninsular); `plural:ustedes` o `plural:neutral` = frase dirigida a varias personas sin «vosotros»; `glosario:T` = falta el término T del glosario; el resto (`multiline`, `boilerplate`, `truncated`…) son fallos de estructura.

| Nº | Escena | Inglés | Español | Avisos |
|---:|:---|:---|:---|:---|
| 1 | S01 | Did you seriously finish the orange juice and put the empty carton back in the fridge? | ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador? | léxico:zumo, léxico:nevera |
| 2 | S01 | Relax, it was almost empty anyway. | Tranquilos, de todos modos estaba casi vacío. |  |
| 3 | S01 | That's not the point, Danny. It was mine! | Ese no es el punto, Danny. Era mío. |  |
| 4 | S01 | Fine. I'll buy you another one tomorrow, okay? | Está bien. Te compraré otra mañana, ¿de acuerdo? | léxico:vale |
| 5 | S01 | And promise me you won't tell Mom I took her car last night. | Y prométeme que no le dirás a mamá que tomé su coche anoche. | léxico:coger |
| 6 | S01 | I'm not lying for you, but I'm not snitching either. | No estoy mintiéndote, pero tampoco estoy chivándome. |  |
| 7 | S02 | Detective Morales, the lab just called. You're going to want to hear this. | Detective Morales, el laboratorio acaba de llamar. Lea esto, por favor. |  |
| 8 | S02 | Put it on speaker. | Póngalo en altavoz. |  |
| 9 | S02 | They found fibers under the victim's fingernails and a sneaker print by the window. None of it matches anything in her apartment. | Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con nada que haya en su apartamento. |  |
| 10 | S02 | So someone else was there. | Entonces, había otra persona allí. |  |
| 11 | S02 | Or someone wants us to think so. Get me the security footage from the building across the street. | O alguien quiere que lo creamos así. Denme las grabaciones de seguridad del edificio de enfrente. |  |
| 12 | S02 | On it, chief. | Está listo, jefe. |  |
| 13 | S03 | Come on, you guys, we're going to miss the last bus! | Vamos, chicos, vamos a perder el último autobús. | plural:neutral |
| 14 | S03 | Hold on, I can't find my cell phone. | Espera un momento, no puedo encontrar mi teléfono móvil. |  |
| 15 | S03 | It's in your hand, genius. | Está en tu mano, genio. |  |
| 16 | S03 | Did you two enjoy the movie, or was the popcorn the best part? | ¿Os gustó la película, o fue el palomar lo mejor del espectáculo? | léxico:palomitas |
| 17 | S03 | Can anyone explain the ending to me? I'm completely lost. | ¿Alguien puede explicarme el final? Estoy completamente perdido. |  |
| 18 | S03 | It was all a dream, Emma. Obviously. | Todo fue un sueño, Emma. Obviamente. |  |
| 19 | S04 | Doctor Patel, the patient in room twelve is crashing! | Doctor Patel, el paciente en la habitación doce está de paso. |  |
| 20 | S04 | Push two milligrams of epinephrine, now! | Aplicad dos miligramos de epinefrina, ahora mismo. |  |
| 21 | S04 | Her pulse is dropping. Somebody get me a crash cart! | Su pulso está disminuyendo. Alguien, traiga un carro de emergencias para mí. |  |
| 22 | S04 | Clear! | ¡Claro! |  |
| 23 | S04 | We're not losing her today. | Hoy no la perdemos. |  |
| 24 | S04 | Okay, she's back. Good work, everyone. Take five, and somebody please get me a coffee. | Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí. | plural:neutral |
| 25 | S05 | Captain, we're picking up a signal from the dead moon. | Capitán, estamos recibiendo una señal desde la luna muerta. |  |
| 26 | S05 | On screen. And keep the engines warm, just in case. | En pantalla. Y mantén los motores calientes, por si acaso. |  |
| 27 | S05 | It's a voice. Sir, it's saying our names. | Es una voz. Señor, está diciendo nuestros nombres. |  |
| 28 | S05 | Nobody panic. Helm, plot a course away from those coordinates, full speed. | Nadie se ponga nervioso. Helm, establece una ruta lejos de esas coordenadas, a toda velocidad. |  |
| 29 | S05 | Sir, the ship isn't responding. Navigation is locked. | Señor, la nave no responde. La navegación está bloqueada. |  |
| 30 | S05 | Then we'll have to do this the hard way. | Entonces tendremos que hacerlo de la manera difícil. |  |
| 31 | S06 | Another round of ale for my friends, and put it on my tab! | Otra ronda de cerveza para mis amigos, y ponla en mi cuenta. |  |
| 32 | S06 | Your tab is longer than the king's road, stranger. | Tu cuenta es más larga que el camino del rey, extraño. |  |
| 33 | S06 | Then I suppose I'd better start earning my keep, because I haven't slept in a real bed since the winter the river froze over and the king lost his crown. | Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona. |  |
| 34 | S06 | If you're looking for work, the blacksmith needs a hand. He pays well, but he has a nasty temper. | Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento terrible. |  |
| 35 | S06 | I've faced dragons, old man. A grumpy blacksmith doesn't scare me. | He enfrentado dragones, anciano. Un herrero gruñón no me asusta. |  |
| 36 | S06 | You haven't met his wife yet. | Todavía no has conocido a su esposa. |  |
| 37 | S07 | Guys, I have some great news and some terrible news. | Chicos, tengo buenas noticias y malas noticias. |  |
| 38 | S07 | The terrible news first, please. We like to end on a high. | Primero, las malas noticias. Nos gusta terminar bien. |  |
| 39 | S07 | The printer is on fire. Again. | La impresora está en llamas. De nuevo. |  |
| 40 | S07 | And the great news? | ¿Y las buenas noticias? |  |
| 41 | S07 | It's not our printer. | No es nuestra impresora. |  |
| 42 | S07 | Okay, everybody, grab your laptops and follow me. We're working in the parking lot today. | De acuerdo, todos, coged vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento. | léxico:aparcamiento |
| 43 | S08 | Can you pull over at the next gas station? I need a sandwich and a bathroom. | ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño. |  |
| 44 | S08 | We're already an hour late. Can't you hold it? | Llegamos con una hora de retraso. ¿No puedes controlar la situación? |  |
| 45 | S08 | No, I can't, and stop looking at me like that. | No, no puedo, y deja de mirarme así. |  |
| 46 | S08 | Fine, but you're driving after this. My eyes are killing me. | Está bien, pero conduzcas después de esto. Mis ojos están matándome. |  |
| 47 | S08 | Deal. And grab the map out of the glove compartment. | De acuerdo. Y saca el mapa del compartimento de las guías. | léxico:guantera |
| 48 | S08 | Dude, nobody uses maps anymore. We have GPS. | Tío, ya nadie usa mapas. Tenemos GPS. |  |
| 49 | S09 | Welcome back to Lucky Hour, everybody! Are you ready? Our next contestant is Marcus from Detroit. | Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit. | plural:ustedes |
| 50 | S09 | Marcus, for ten thousand dollars: what is the capital of Australia? | Marcus, por diez mil dólares: ¿cuál es la capital de Australia? |  |
| 51 | S09 | Uh, is it Sydney? No, wait, don't tell me, it's Canberra! | ¿Sí, es Sídney? No, espera, no me digas que es Canberra. |  |
| 52 | S09 | Are you absolutely sure about that? | ¿Estás absolutamente seguro de eso? |  |
| 53 | S09 | Yes! Lock it in, please. | ¡Sí! Por favor, bloéjalo. |  |
| 54 | S09 | Correct! You just won ten thousand dollars! | ¡Correcto! Acabas de ganar diez mil dólares. |  |
| 55 | S10 | Listen up, all of you. The vault opens at midnight, we grab the diamonds, and we're gone in ninety seconds. | Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos. |  |
| 56 | S10 | What if the guard changes his route? | ¿Qué pasa si el guardia cambia su ruta? |  |
| 57 | S10 | He won't. I've been watching him for three weeks. | No lo hará. Lo he estado vigilando durante tres semanas. |  |
| 58 | S10 | You're out of your mind, but I'm in. | Estás loco, pero yo sí estoy cuerdo. |  |
| 59 | S10 | Whatever happens, nobody goes back for anyone. Got it? | Pase lo que pase, nadie regresa por nadie. ¿Entendido? |  |
| 60 | S10 | Kill the lights. | Apague las luces. |  |
| 61 | S11 | Zephyrine Quill swore she would find the Hollowmere before the first frost. | Zefirina Quill juró que encontraría Yermomar antes de la primera helada. |  |
| 62 | S11 | The Ember Court has closed the gates of Glassreach, and nobody is allowed in or out. | La Corte de Ascuas ha cerrado las puertas de Cristalcanto, y a nadie se le permite entrar o salir. |  |
| 63 | S11 | Captain Brannoch, you'll ride with me to Thornwick Keep at dawn. | Capitán Brannoch, viajará conmigo a Fortaleza Espinal al amanecer. |  |
| 64 | S11 | Did you hear what Sir Aldous Fenn said about the Hollowmere? | ¿Escuchaste lo que dijo ser Aldous Fenn sobre Yermomar? |  |
| 65 | S11 | They say Kaelith Vorne still carries the blade of Zephyrine Quill into every battle. | Se dice que Kaelith Vorne sigue llevando la espada de Zefirina Quill en cada batalla. |  |

## Escenas

- **S01** (Cocina, hermanos): líneas 1–6
- **S02** (Comisaría): líneas 7–12
- **S03** (Saliendo del cine): líneas 13–18
- **S04** (Hospital): líneas 19–24
- **S05** (Nave espacial): líneas 25–30
- **S06** (Taberna de fantasía): líneas 31–36
- **S07** (Oficina): líneas 37–42
- **S08** (Viaje en coche): líneas 43–48
- **S09** (Concurso de la tele): líneas 49–54
- **S10** (Atraco): líneas 55–60
- **S11** (Saga inventada (glosario)): líneas 61–65

## Glosario usado

| Término (inglés) | Traducción obligatoria |
|:---|:---|
| Zephyrine Quill | Zefirina Quill |
| Hollowmere | Yermomar |
| Ember Court | Corte de Ascuas |
| Glassreach | Cristalcanto |
| Captain Brannoch | capitán Brannoch |
| Thornwick Keep | Fortaleza Espinal |
| Sir Aldous Fenn | ser Aldous Fenn |
| Kaelith Vorne | Kaelith Vorne |

El glosario solo se inyecta en el prompt cuando el término aparece en la frase o en el contexto previo. Las líneas 61–65 son las cinco con términos inventados.
