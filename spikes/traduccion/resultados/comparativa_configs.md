# Comparativa de variantes de prompt (misma semilla, una pasada cada una)

Variantes: `baseline`, `official_en`, `official_zh`, `sys_style`, `sys_fewshot`, `sys_fewshot_ctx`, `final`, `final_nofewshot`, `final_fewshot6`, `final_raw_turns`, `final_t02`, `final_lexicon`.

### 1 · S01 · Did you seriously finish the orange juice and put the empty carton back in the fridge?

- `baseline`: ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `official_en`: ¿De verdad terminaste el jugo de naranja y devolviste la caja vacía al refrigerador?
- `official_zh`: ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `sys_style`: ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `sys_fewshot`: ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?
- `sys_fewshot_ctx`: ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?
- `final`: ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?
- `final_nofewshot`: ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `final_fewshot6`: ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?
- `final_raw_turns`: ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?
- `final_t02`: ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?
- `final_lexicon`: ¿De verdad terminaste el zumo de naranja y volviste a poner la caja vacía en la nevera?

### 2 · S01 · Relax, it was almost empty anyway.

- `baseline`: Tranquilo, de todos modos, el lugar estaba casi vacío.
- `official_en`: [Información de fondo]   ⏎ Conversación hasta ahora (original en inglés, luego en español):   ⏎ Inglés: ¿De verdad terminaste el jugo de naranja y devolviste la caja vacía al refrigerador?   ⏎ Español: ¿
- `official_zh`: Tranquilo, de todos modos casi estaba vacío.
- `sys_style`: Tranquilo, de todos modos, el lugar estaba casi vacío.
- `sys_fewshot`: Tranquilos, de todos modos estaba casi vacío.
- `sys_fewshot_ctx`: Tranquilos, de todos modos estaba casi vacío.
- `final`: Tranquilos, de todos modos estaba casi vacío.
- `final_nofewshot`: Tranquilo, de todos modos estaba casi vacío.
- `final_fewshot6`: Tranquilos, de todos modos estaba casi vacío.
- `final_raw_turns`: Tranquilo, de todos modos estaba casi vacío.
- `final_t02`: Tranquilos, de todos modos estaba casi vacío.
- `final_lexicon`: Tranquilos, de todos modos casi no había nada.

### 3 · S01 · That's not the point, Danny. It was mine!

- `baseline`: Ese no es el punto, Danny. ¡Era mío!
- `official_en`: Eso no es lo importante, Danny. Era mío.
- `official_zh`: Ese no es el punto, Danny. Era mío.
- `sys_style`: Ese no es el punto, Danny. Era mío.
- `sys_fewshot`: Ese no es el punto, Danny. Era mío.
- `sys_fewshot_ctx`: Ese no es el punto, Danny. Era mío.
- `final`: Ese no es el punto, Danny. Era mío.
- `final_nofewshot`: Ese no es el punto, Danny. Era mío.
- `final_fewshot6`: Ese no es el punto, Danny. Era mío.
- `final_raw_turns`: Ese no es el punto, Danny. Era mío.
- `final_t02`: Ese no es el punto, Danny. Era mío.
- `final_lexicon`: Ese no es el punto, Danny. Era mío.

### 4 · S01 · Fine. I'll buy you another one tomorrow, okay?

- `baseline`: Está bien. Te compraré otra mañana, ¿de acuerdo?
- `official_en`: [Texto de origen]   ⏎ Bien. Te compro otra mañana, ¿de acuerdo?
- `official_zh`: Está bien. Te compraré otra mañana, ¿de acuerdo?
- `sys_style`: Está bien. Mañana te compraré otra, ¿de acuerdo?
- `sys_fewshot`: Está bien. Te compraré otra mañana, ¿de acuerdo?
- `sys_fewshot_ctx`: Está bien. Te compraré otra mañana, ¿de acuerdo?
- `final`: Está bien. Te compraré otra mañana, ¿de acuerdo?
- `final_nofewshot`: Está bien. Te compraré otra mañana, ¿de acuerdo?
- `final_fewshot6`: Está bien. Te compraré otra mañana, ¿de acuerdo?
- `final_raw_turns`: Está bien. Te compraré otra mañana, ¿de acuerdo?
- `final_t02`: Está bien. Te compraré otra mañana, ¿de acuerdo?
- `final_lexicon`: Está bien. Mañana te compraré otro, ¿de acuerdo?

### 5 · S01 · And promise me you won't tell Mom I took her car last night.

- `baseline`: Y prométeme que no le dirás a mamá que yo tomé su coche anoche.
- `official_en`: Y prométeme que no le dirás a mamá que tomé su coche anoche.
- `official_zh`: Y prométeme que no le dirás a mamá que tomé su coche anoche.
- `sys_style`: Y prométeme que no le dirás a mamá que tomé su coche anoche.
- `sys_fewshot`: Y prométeme que no le dirás a mamá que tomé su coche anoche.
- `sys_fewshot_ctx`: Y prométeme que no le dirás a mamá que tomé su coche anoche.
- `final`: Y prométeme que no le dirás a mamá que tomé su coche anoche.
- `final_nofewshot`: Y prométeme que no le dirás a mamá que tomé su coche anoche.
- `final_fewshot6`: Y prométeme que no le dirás a mamá que tomé su coche anoche.
- `final_raw_turns`: Y prométeme que no le dirás a mamá que tomé su coche anoche.
- `final_t02`: Y prométeme que no le dirás a mamá que tomé su coche anoche.
- `final_lexicon`: Y prométeme que no le dirás a mamá que tomé su coche anoche.

### 6 · S01 · I'm not lying for you, but I'm not snitching either.

- `baseline`: No les estoy mintiendo, pero tampoco estoy divulgando información alguna.
- `official_en`: No estoy mintiendo para ti, pero tampoco estoy chismorreando.
- `official_zh`: No estoy mintiendo por ti, pero tampoco estoy chismorreando.
- `sys_style`: No estoy mintiéndote, pero tampoco estoy informando secretos.
- `sys_fewshot`: No estoy mintiéndote, pero tampoco estoy chivándome.
- `sys_fewshot_ctx`: No estoy mintiéndote, pero tampoco estoy chivándome.
- `final`: No estoy mintiéndote, pero tampoco estoy chivándome.
- `final_nofewshot`: No estoy mintiéndote, pero tampoco estoy chivándome.
- `final_fewshot6`: No estoy mintiéndote, pero tampoco estoy chivándome.
- `final_raw_turns`: No estoy mintiendo para ti, pero tampoco estoy chismorreando.
- `final_t02`: No estoy mintiéndote, pero tampoco estoy chivándome.
- `final_lexicon`: No estoy mintiéndote, pero tampoco estoy chismorreando.

### 7 · S02 · Detective Morales, the lab just called. You're going to want to hear this.

- `baseline`: Detective Morales, el laboratorio acaba de llamar. Tendrá que escuchar esto.
- `official_en`: Detective Morales, el laboratorio acaba de llamar. Le gustará escuchar esto.
- `official_zh`: Detective Morales, el laboratorio acaba de llamar. Tendrá que escuchar esto.
- `sys_style`: Detective Morales, el laboratorio acaba de llamar. Tendrá que escuchar esto.
- `sys_fewshot`: Detective Morales, el laboratorio acaba de llamar. Lea esto, por favor.
- `sys_fewshot_ctx`: Detective Morales, el laboratorio acaba de llamar. Lea esto, por favor.
- `final`: Detective Morales, el laboratorio acaba de llamar. Lea esto, por favor.
- `final_nofewshot`: Detective Morales, el laboratorio acaba de llamar. Tendrá que escuchar esto.
- `final_fewshot6`: Detective Morales, el laboratorio acaba de llamar. Le gustará escuchar esto.
- `final_raw_turns`: Detective Morales, el laboratorio acaba de llamar. Tendrá que escuchar esto.
- `final_t02`: Detective Morales, el laboratorio acaba de llamar. Lea esto, por favor.
- `final_lexicon`: Detective Morales, el laboratorio acaba de llamar. Lea esto, por favor.

### 8 · S02 · Put it on speaker.

- `baseline`: Ponlo en modo altavoz.
- `official_en`: [Texto de origen] Ponga el altavoz.
- `official_zh`: Ponlo en altavoz.
- `sys_style`: Ponlo en altavoz.
- `sys_fewshot`: Ponlo en altavoz.
- `sys_fewshot_ctx`: Póngalo en altavoz.
- `final`: Póngalo en altavoz.
- `final_nofewshot`: Ponga en altavoz.
- `final_fewshot6`: Ponlo en altavoz.
- `final_raw_turns`: Ponlo en altavoz.
- `final_t02`: Póngalo en altavoz.
- `final_lexicon`: Póngalo en altavoz.

### 9 · S02 · They found fibers under the victim's fingernails and a sneaker print by the window. None of it matches anything in her apartment.

- `baseline`: Encontraron fibras debajo de las uñas del victimario y una marca de zapatillas cerca de la ventana. Nada de eso coincidía con nada que hubiera en su apartamento.
- `official_en`: [Información de fondo]   ⏎ Conversación hasta ahora (en inglés original, luego en español):   ⏎ Inglés: Detective Morales, el laboratorio acaba de llamar. Le gustará escuchar esto.   ⏎ Español: Detective Morales, el laboratorio acaba de llamar. Le interesará escuchar esto.   ⏎ Inglés: Ponga el altav
- `official_zh`: Encontraron fibras debajo de las uñas del víctima y una huella de zapatilla junto a la ventana. Nada de eso coincide con algo que hubiera en su apartamento.
- `sys_style`: Encontraron fibras debajo de las uñas del victimario y una marca de zapatillas junto a la ventana. Nada de eso coincidía con nada que hubiera en su apartamento.
- `sys_fewshot`: Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con algo que hubiera en su apartamento.
- `sys_fewshot_ctx`: Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con nada que haya en su apartamento.
- `final`: Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con nada que haya en su apartamento.
- `final_nofewshot`: Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con algo que estuviera en su apartamento.
- `final_fewshot6`: Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con algo que hubiera en su apartamento.
- `final_raw_turns`: Encontraron fibras debajo de las uñas del victimario y una huella de zapatilla junto a la ventana. Nada de eso coincide con nada en su apartamento.
- `final_t02`: Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con algo que hubiera en su apartamento.
- `final_lexicon`: Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con algo que haya en su piso.

### 10 · S02 · So someone else was there.

- `baseline`: Entonces, había otra persona allí.
- `official_en`: [Texto de origen] Alguien más estuvo allí.
- `official_zh`: Entonces, había otra persona allí.
- `sys_style`: Entonces, había otra persona allí.
- `sys_fewshot`: Entonces, había otra persona allí.
- `sys_fewshot_ctx`: Entonces, había otra persona allí.
- `final`: Entonces, había otra persona allí.
- `final_nofewshot`: Entonces, había otra persona allí.
- `final_fewshot6`: Entonces, había otra persona allí.
- `final_raw_turns`: Entonces, había otra persona allí.
- `final_t02`: Entonces, había otra persona allí.
- `final_lexicon`: Entonces, había otra persona allí.

### 11 · S02 · Or someone wants us to think so. Get me the security footage from the building across the street.

- `baseline`: O tal vez alguien quiere que lo creamos así. Consíganme las grabaciones de seguridad del edificio al otro lado de la calle.
- `official_en`: [Texto de origen] O alguien quiere que creamos eso. Consiga las grabaciones de seguridad del edificio al otro lado de la calle.
- `official_zh`: O alguien quiere que así lo pensemos. Consíganme las grabaciones de seguridad del edificio al otro lado de la calle.
- `sys_style`: O alguien quiere que pensemos así. Consíganme las grabaciones de seguridad del edificio al otro lado de la calle.
- `sys_fewshot`: O alguien quiere que así lo pensemos. Consíganos las grabaciones de seguridad del edificio al otro lado de la calle.
- `sys_fewshot_ctx`: O alguien quiere que lo creamos así. Denme las grabaciones de seguridad del edificio de enfrente.
- `final`: O alguien quiere que lo creamos así. Denme las grabaciones de seguridad del edificio de enfrente.
- `final_nofewshot`: O alguien quiere que creamos eso. Consigan las grabaciones de seguridad del edificio al otro lado de la calle.
- `final_fewshot6`: O alguien quiere que creamos eso. Consíganme las grabaciones de seguridad del edificio de enfrente.
- `final_raw_turns`: O alguien quiere que pensemos así. Consíganos las grabaciones de seguridad del edificio al otro lado de la calle.
- `final_t02`: O alguien quiere que pensemos así. Consíganos las grabaciones de seguridad del edificio de enfrente.
- `final_lexicon`: O alguien quiere que lo creamos así. Denme las imágenes de seguridad del edificio de enfrente.

### 12 · S02 · On it, chief.

- `baseline`: En eso, jefe.
- `official_en`: [Texto de origen] Sí, jefe.
- `official_zh`: De acuerdo, jefe.
- `sys_style`: En eso, jefe.
- `sys_fewshot`: De acuerdo, jefe.
- `sys_fewshot_ctx`: Está listo, jefe.
- `final`: Está listo, jefe.
- `final_nofewshot`: Está listo, jefe.
- `final_fewshot6`: En él, jefe.
- `final_raw_turns`: En marcha, jefe.
- `final_t02`: Está listo, jefe.
- `final_lexicon`: De acuerdo, jefe.

### 13 · S03 · Come on, you guys, we're going to miss the last bus!

- `baseline`: Vamos, chicos, vamos a perder el último autobús.
- `official_en`: Vamos, chicos, vamos a perder el último autobús.
- `official_zh`: Vamos, chicos, vamos a perder el último autobús.
- `sys_style`: Vamos, chicos, vamos a perder el último autobús.
- `sys_fewshot`: Vamos, chicos, vamos a perder el último autobús.
- `sys_fewshot_ctx`: Vamos, chicos, vamos a perder el último autobús.
- `final`: Vamos, chicos, vamos a perder el último autobús.
- `final_nofewshot`: Vamos, chicos, vamos a perder el último autobús.
- `final_fewshot6`: Vamos, chicos, vamos a perder el último autobús.
- `final_raw_turns`: Vamos, chicos, vamos a perder el último autobús.
- `final_t02`: Vamos, chicos, vamos a perder el último autobús.
- `final_lexicon`: Vamos, chicos, vamos a perder el último autobús.

### 14 · S03 · Hold on, I can't find my cell phone.

- `baseline`: Espera un momento, no puedo encontrar mi teléfono móvil.
- `official_en`: Espera, no puedo encontrar mi teléfono móvil.
- `official_zh`: Espera, no puedo encontrar mi teléfono móvil.
- `sys_style`: Espera un momento, no puedo encontrar mi teléfono móvil.
- `sys_fewshot`: Espera un momento, no puedo encontrar mi teléfono móvil.
- `sys_fewshot_ctx`: Espera un momento, no puedo encontrar mi teléfono móvil.
- `final`: Espera un momento, no puedo encontrar mi teléfono móvil.
- `final_nofewshot`: Espera un momento, no puedo encontrar mi teléfono móvil.
- `final_fewshot6`: Espera un momento, no puedo encontrar mi teléfono móvil.
- `final_raw_turns`: Espera, no puedo encontrar mi teléfono móvil.
- `final_t02`: Espera un momento, no puedo encontrar mi teléfono móvil.
- `final_lexicon`: Espera un momento, no puedo encontrar mi móvil.

### 15 · S03 · It's in your hand, genius.

- `baseline`: Está en tus manos, genio.
- `official_en`: Está en tu mano, genio.
- `official_zh`: Está en tu mano, genio.
- `sys_style`: Está en tus manos, genio.
- `sys_fewshot`: Está en tu mano, genio.
- `sys_fewshot_ctx`: Está en tu mano, genio.
- `final`: Está en tu mano, genio.
- `final_nofewshot`: Está en tu mano, genio.
- `final_fewshot6`: Está en tu mano, genio.
- `final_raw_turns`: Está en tu mano, genio.
- `final_t02`: Está en tu mano, genio.
- `final_lexicon`: Está en tu mano, genio.

### 16 · S03 · Did you two enjoy the movie, or was the popcorn the best part?

- `baseline`: ¿Les gustó la película a ustedes dos, o fue el palomar el aspecto más interesante de la película?
- `official_en`: ¿Les gustó la película a ustedes dos, o fue el palomar el mejor momento?
- `official_zh`: ¿Les gustó la película a ustedes dos, o fue el palomar lo mejor?
- `sys_style`: ¿Les gustó la película a los dos, o fue el palomar el aspecto más divertido?
- `sys_fewshot`: ¿Os gustó la película, o fue el palomar lo mejor del evento?
- `sys_fewshot_ctx`: ¿Os gustó la película, o fue el palomar lo mejor del espectáculo?
- `final`: ¿Os gustó la película, o fue el palomar lo mejor del espectáculo?
- `final_nofewshot`: ¿Les gustó la película, o fue el palomar el mejor momento?
- `final_fewshot6`: ¿Les gustó la película, o fue el palomar el mejor momento?
- `final_raw_turns`: ¿Os gustó la película, o fue el palomar el mejor momento?
- `final_t02`: ¿Os gustó la película, o fue el palomar lo mejor del espectáculo?
- `final_lexicon`: ¿Ustedes dos disfrutaron la película, o fueron las palomitas lo mejor del espectáculo?

### 17 · S03 · Can anyone explain the ending to me? I'm completely lost.

- `baseline`: ¿Alguien puede explicarme el final de la historia? Estoy completamente perdido.
- `official_en`: [Información de fondo]   ⏎ Conversación hasta ahora (original en inglés, luego en español):   ⏎ Inglés: Vamos, chicos, vamos a perder el último autobús.   ⏎ Español: Vamos, chicos, vamos
- `official_zh`: ¿Alguien puede explicarme el final? Estoy completamente perdido.
- `sys_style`: ¿Puede alguien explicarme el final de la frase? Estoy completamente perdido.
- `sys_fewshot`: ¿Alguien puede explicarme el final? Estoy completamente perdido.
- `sys_fewshot_ctx`: ¿Alguien puede explicarme el final? Estoy completamente perdido.
- `final`: ¿Alguien puede explicarme el final? Estoy completamente perdido.
- `final_nofewshot`: ¿Alguien puede explicarme el final? Estoy completamente perdido.
- `final_fewshot6`: ¿Alguien puede explicarme el final? Estoy completamente perdido.
- `final_raw_turns`: ¿Alguien puede explicarme el final? Estoy completamente perdido.
- `final_t02`: ¿Alguien puede explicarme el final? Estoy completamente perdido.
- `final_lexicon`: ¿Alguien puede explicarme el final? Estoy completamente perdido.

### 18 · S03 · It was all a dream, Emma. Obviously.

- `baseline`: Todo era un sueño, Emma. Obviamente.
- `official_en`: Era todo un sueño, Emma. Obviamente.
- `official_zh`: Era todo un sueño, Emma. Obviamente.
- `sys_style`: Todo fue un sueño, Emma. Obviamente.
- `sys_fewshot`: Todo fue un sueño, Emma. Obviamente.
- `sys_fewshot_ctx`: Todo fue un sueño, Emma. Obviamente.
- `final`: Todo fue un sueño, Emma. Obviamente.
- `final_nofewshot`: Todo fue un sueño, Emma. Obviamente.
- `final_fewshot6`: Todo fue un sueño, Emma. Obviamente.
- `final_raw_turns`: Todo fue un sueño, Emma. Obviamente.
- `final_t02`: Todo fue un sueño, Emma. Obviamente.
- `final_lexicon`: Todo fue un sueño, Emma. Obviamente.

### 19 · S04 · Doctor Patel, the patient in room twelve is crashing!

- `baseline`: Dr. Patel, el paciente en la habitación doce está de paso aquí.
- `official_en`: Doctor Patel, el paciente en la habitación doce está de paso aquí.
- `official_zh`: Doctor Patel, el paciente en la habitación doce está de paso.
- `sys_style`: Dr. Patel, el paciente en la habitación doce está de paso aquí.
- `sys_fewshot`: Doctor Patel, el paciente en la habitación doce está de paso.
- `sys_fewshot_ctx`: Doctor Patel, el paciente en la habitación doce está de paso.
- `final`: Doctor Patel, el paciente en la habitación doce está de paso.
- `final_nofewshot`: Dr. Patel, el paciente en la habitación doce está de paso aquí.
- `final_fewshot6`: Doctor Patel, el paciente en la habitación doce está de visita.
- `final_raw_turns`: Doctor Patel, el paciente en la habitación doce está teniendo una crisis!
- `final_t02`: Doctor Patel, el paciente en la habitación doce está de paso.
- `final_lexicon`: Doctor Patel, el paciente en la habitación doce está de paso.

### 20 · S04 · Push two milligrams of epinephrine, now!

- `baseline`: ¡Aplicar dos miligramos de epinefrina ahora!
- `official_en`: ¡Administre dos miligramos de epinefrina, ahora!
- `official_zh`: ¡Aumente los dos miligramos de epinefrina, ahora!
- `sys_style`: ¡Aplicar dos miligramos de epinefrina ahora!
- `sys_fewshot`: Administrad dos miligramos de epinefrina, ahora mismo.
- `sys_fewshot_ctx`: Aplicad dos miligramos de epinefrina, ahora mismo.
- `final`: Aplicad dos miligramos de epinefrina, ahora mismo.
- `final_nofewshot`: ¡Administre dos miligramos de epinefrina, ahora!
- `final_fewshot6`: Administre dos miligramos de epinefrina, ahora mismo.
- `final_raw_turns`: Aplicad dos miligramos de epinefrina, ahora!
- `final_t02`: Administren dos miligramos de epinefrina, ahora mismo.
- `final_lexicon`: Aplicad dos miligramos de epinefrina, ahora mismo.

### 21 · S04 · Her pulse is dropping. Somebody get me a crash cart!

- `baseline`: Su pulso está disminuyendo. Alguien, tráiganme un carro de emergencias.
- `official_en`: Su pulso está disminuyendo. Alguien traiga un carro de emergencias para mí.
- `official_zh`: Su pulso está disminuyendo. Alguien traiga un carro de emergencia para mí.
- `sys_style`: Su pulso está disminuyendo. Alguien, tráiganme una camilla de emergencias.
- `sys_fewshot`: Su pulso está disminuyendo. Alguien, traigáme un equipo de emergencias.
- `sys_fewshot_ctx`: Su pulso está disminuyendo. Alguien, traiga un carro de emergencias para mí.
- `final`: Su pulso está disminuyendo. Alguien, traiga un carro de emergencias para mí.
- `final_nofewshot`: Su pulso está disminuyendo. Alguien, traiga un carro de emergencia para mí.
- `final_fewshot6`: Su pulso está disminuyendo. Alguien llévenme un carro de emergencias.
- `final_raw_turns`: Su pulso está bajando. Alguien traiga un carro de emergencias para mí.
- `final_t02`: Su pulso está disminuyendo. Alguien llévenme un carro de emergencias.
- `final_lexicon`: Su pulso está disminuyendo. Alguien, traiga un carro de emergencias para mí.

### 22 · S04 · Clear!

- `baseline`: ¡Claro!
- `official_en`: [Texto de origen] ¡Claro!
- `official_zh`: ¡Claro!
- `sys_style`: ¡Claro!
- `sys_fewshot`: ¡Claro!
- `sys_fewshot_ctx`: ¡Claro!
- `final`: ¡Claro!
- `final_nofewshot`: ¡Claro!
- `final_fewshot6`: ¡Claro!
- `final_raw_turns`: ¡Claro!
- `final_t02`: ¡Claro!
- `final_lexicon`: ¡Claro!

### 23 · S04 · We're not losing her today.

- `baseline`: Hoy no la perdemos.
- `official_en`: Hoy no la perdemos.
- `official_zh`: Hoy no la perdemos.
- `sys_style`: Hoy no la perdemos.
- `sys_fewshot`: Hoy no la perdemos.
- `sys_fewshot_ctx`: Hoy no la perdemos.
- `final`: Hoy no la perdemos.
- `final_nofewshot`: Hoy no la perdemos.
- `final_fewshot6`: Hoy no la perdemos.
- `final_raw_turns`: Hoy no la perdemos.
- `final_t02`: Hoy no la perdemos.
- `final_lexicon`: Hoy no la perdemos.

### 24 · S04 · Okay, she's back. Good work, everyone. Take five, and somebody please get me a coffee.

- `baseline`: Bien, ha vuelto. Bien hecho, todos. Descansemos un momento, y que alguien me traiga un café, por favor.
- `official_en`: [Texto de origen] Bien, ha regresado. ¡Buen trabajo, todos! Descansen un momento, y por favor, traiganme un café.
- `official_zh`: ¡Bien, ha vuelto! Bien hecho, todos. Descansemos un momento, y por favor, traiganme un café.
- `sys_style`: Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y que alguien me traiga un café, por favor.
- `sys_fewshot`: Bien, ha vuelto. Bien hecho, todos. Descansen un momento, y que alguien me traiga un café, por favor.
- `sys_fewshot_ctx`: Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí.
- `final`: Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí.
- `final_nofewshot`: Bien, ha regresado. Bien hecho, todos. Descansen un momento, y por favor, que alguien me traiga un café.
- `final_fewshot6`: Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y que alguien me traiga un café.
- `final_raw_turns`: Bien, ha vuelto. Bien hecho, todos. Tomad un descanso y alguien traiga un café para mí.
- `final_t02`: Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí.
- `final_lexicon`: Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí.

### 25 · S05 · Captain, we're picking up a signal from the dead moon.

- `baseline`: Capitán, estamos captando una señal proveniente de la luna muerta.
- `official_en`: Capitán, estamos captando una señal desde la luna muerta.
- `official_zh`: Capitán, estamos recibiendo una señal desde la luna muerta.
- `sys_style`: Capitán, estamos captando una señal desde la luna muerta.
- `sys_fewshot`: Capitán, estamos recibiendo una señal desde la luna muerta.
- `sys_fewshot_ctx`: Capitán, estamos recibiendo una señal desde la luna muerta.
- `final`: Capitán, estamos recibiendo una señal desde la luna muerta.
- `final_nofewshot`: Capitán, estamos captando una señal desde la luna muerta.
- `final_fewshot6`: Capitán, estamos recibiendo una señal desde la luna muerta.
- `final_raw_turns`: Capitán, estamos recibiendo una señal desde la luna muerta.
- `final_t02`: Capitán, estamos recibiendo una señal desde la luna muerta.
- `final_lexicon`: Capitán, estamos recibiendo una señal desde la luna muerta.

### 26 · S05 · On screen. And keep the engines warm, just in case.

- `baseline`: En la pantalla. Y mantengan los motores calientes, por si acaso.
- `official_en`: [Información de fondo]   ⏎ Conversación hasta ahora (original en inglés, luego en español):   ⏎ Inglés: Capitán, estamos captando una señal desde la luna muerta.   ⏎ Español: Capitán, estamos recibiendo
- `official_zh`: En la pantalla. Y mantengan los motores calientes, por si acaso.
- `sys_style`: En la pantalla. Y mantengan los motores calientes, por si acaso.
- `sys_fewshot`: En la pantalla. Y mantén los motores calientes, por si acaso.
- `sys_fewshot_ctx`: En pantalla. Y mantén los motores calientes, por si acaso.
- `final`: En pantalla. Y mantén los motores calientes, por si acaso.
- `final_nofewshot`: En pantalla. Y mantengan los motores calientes, por si acaso.
- `final_fewshot6`: En pantalla. Y mantén los motores calientes, por si acaso.
- `final_raw_turns`: En pantalla. Y mantén los motores calientes, por si acaso.
- `final_t02`: En pantalla. Y mantén los motores calientes, por si acaso.
- `final_lexicon`: En pantalla. Y mantén los motores calientes, por si acaso.

### 27 · S05 · It's a voice. Sir, it's saying our names.

- `baseline`: Es una voz. Señor, está diciendo nuestros nombres.
- `official_en`: [Texto de origen]   ⏎ Es una voz. Señor, está diciendo nuestros nombres.
- `official_zh`: Es una voz. Señor, dice nuestros nombres.
- `sys_style`: Es una voz. Señor, está diciendo nuestros nombres.
- `sys_fewshot`: Es una voz. Señor, está diciendo nuestros nombres.
- `sys_fewshot_ctx`: Es una voz. Señor, está diciendo nuestros nombres.
- `final`: Es una voz. Señor, está diciendo nuestros nombres.
- `final_nofewshot`: Es una voz. Señor, está diciendo nuestros nombres.
- `final_fewshot6`: Es una voz. Señor, está diciendo nuestros nombres.
- `final_raw_turns`: Es una voz. Señor, está diciendo nuestros nombres.
- `final_t02`: Es una voz. Señor, está diciendo nuestros nombres.
- `final_lexicon`: Es una voz. Señor, está diciendo nuestros nombres.

### 28 · S05 · Nobody panic. Helm, plot a course away from those coordinates, full speed.

- `baseline`: Nadie tenga pánico. Helm, planifique un rumbo alejándose de esas coordenadas, a toda velocidad.
- `official_en`: [Texto de origen]   ⏎ Nadie se ponga nervioso. Helm, establece una ruta alejándose de esas coordenadas, a toda velocidad.
- `official_zh`: Nadie se ponga nervioso. Helm, establece una ruta lejos de esas coordenadas, a toda velocidad.
- `sys_style`: Nadie se ponga nervioso. Helm, planifique un curso lejos de esas coordenadas, a toda velocidad.
- `sys_fewshot`: Que nadie se ponga nervioso. Helm, planea un camino lejos de esas coordenadas, a toda velocidad.
- `sys_fewshot_ctx`: Nadie se ponga nervioso. Helm, establece una ruta lejos de esas coordenadas, a toda velocidad.
- `final`: Nadie se ponga nervioso. Helm, establece una ruta lejos de esas coordenadas, a toda velocidad.
- `final_nofewshot`: Nadie se ponga nervioso. Helm, planee una ruta lejos de esas coordenadas, a toda velocidad.
- `final_fewshot6`: Nadie se ponga nervioso. Helm, planifique un curso lejos de esas coordenadas, a toda velocidad.
- `final_raw_turns`: Nadie pase de pánico. Helm, planifica un curso lejos de esas coordenadas, a toda velocidad.
- `final_t02`: Nadie se ponga nervioso. Helm, establece una ruta lejos de esas coordenadas, a toda velocidad.
- `final_lexicon`: Nadie se ponga nervioso. Helm, establece una ruta lejos de esas coordenadas, a toda velocidad.

### 29 · S05 · Sir, the ship isn't responding. Navigation is locked.

- `baseline`: Señor, el barco no responde. La navegación está bloqueada.
- `official_en`: Señor, la nave no responde. La navegación está bloqueada.
- `official_zh`: Señor, la nave no responde. La navegación está bloqueada.
- `sys_style`: Señor, el barco no responde. La navegación está bloqueada.
- `sys_fewshot`: Señor, el barco no responde. La navegación está bloqueada.
- `sys_fewshot_ctx`: Señor, la nave no responde. La navegación está bloqueada.
- `final`: Señor, la nave no responde. La navegación está bloqueada.
- `final_nofewshot`: Señor, la nave no responde. La navegación está bloqueada.
- `final_fewshot6`: Señor, la nave no responde. La navegación está bloqueada.
- `final_raw_turns`: Señor, la nave no responde. La navegación está bloqueada.
- `final_t02`: Señor, la nave no responde. La navegación está bloqueada.
- `final_lexicon`: Señor, la nave no responde. La navegación está bloqueada.

### 30 · S05 · Then we'll have to do this the hard way.

- `baseline`: Entonces, tendremos que hacerlo de la manera difícil.
- `official_en`: Entonces tendremos que hacerlo de la manera difícil.
- `official_zh`: Entonces tendremos que hacerlo de la manera difícil.
- `sys_style`: Entonces tendremos que hacerlo de la manera difícil.
- `sys_fewshot`: Entonces tendremos que hacerlo de la manera difícil.
- `sys_fewshot_ctx`: Entonces tendremos que hacerlo de la manera difícil.
- `final`: Entonces tendremos que hacerlo de la manera difícil.
- `final_nofewshot`: Entonces tendremos que hacerlo de la manera difícil.
- `final_fewshot6`: Entonces tendremos que hacerlo de la manera difícil.
- `final_raw_turns`: Entonces tendremos que hacerlo de la manera difícil.
- `final_t02`: Entonces tendremos que hacerlo de la manera difícil.
- `final_lexicon`: Entonces tendremos que hacerlo de la manera difícil.

### 31 · S06 · Another round of ale for my friends, and put it on my tab!

- `baseline`: Otra ronda de cerveza para mis amigos… ¡Y pásala a mi tablero!
- `official_en`: Otra ronda de cerveza para mis amigos, y ponla en mi tablero.
- `official_zh`: Otra ronda de cerveza para mis amigos, y ponla en mi cuenta.
- `sys_style`: Otra ronda de cerveza para mis amigos, y pónganla en mi tablero de notas.
- `sys_fewshot`: Otra ronda de cerveza para mis amigos, y ponla en mi cuenta.
- `sys_fewshot_ctx`: Otra ronda de cerveza para mis amigos, y ponla en mi cuenta.
- `final`: Otra ronda de cerveza para mis amigos, y ponla en mi cuenta.
- `final_nofewshot`: Otra ronda de cerveza para mis amigos, y pónganla en mi tablero de notas.
- `final_fewshot6`: Otra ronda de cerveza para mis amigos, y ponla en mi cuenta.
- `final_raw_turns`: Otra ronda de cerveza para mis amigos, y ponla en mi cuenta.
- `final_t02`: Otra ronda de cerveza para mis amigos, y ponla en mi cuenta.
- `final_lexicon`: Otra ronda de cerveza para mis amigos, y ponla en mi cuenta.

### 32 · S06 · Your tab is longer than the king's road, stranger.

- `baseline`: Tu tabla es más larga que el camino del rey, extraño.
- `official_en`: Tu tablero es más largo que el camino del rey, extraño.
- `official_zh`: Tu tabula es más larga que el camino del rey, extraño.
- `sys_style`: Tu tab es más larga que el camino del rey, extraño.
- `sys_fewshot`: Tu tabla es más larga que el camino del rey, extraño.
- `sys_fewshot_ctx`: Tu cuenta es más larga que el camino del rey, extraño.
- `final`: Tu cuenta es más larga que el camino del rey, extraño.
- `final_nofewshot`: Tu tablero es más largo que el camino del rey, extraño.
- `final_fewshot6`: Tu cuenta es más larga que el camino del rey, extraño.
- `final_raw_turns`: Tu cuenta es más larga que el camino del rey, extraño.
- `final_t02`: Tu cuenta es más larga que el camino del rey, extraño.
- `final_lexicon`: Tu cuenta es más larga que el camino del rey, extraño.

### 33 · S06 · Then I suppose I'd better start earning my keep, because I haven't slept in a real bed since the winter the river froze over and the king lost his crown.

- `baseline`: Entonces, supongo que sería mejor que comenzara a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_en`: Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_zh`: Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `sys_style`: Entonces supongo que sería mejor que comenzara a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `sys_fewshot`: Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `sys_fewshot_ctx`: Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `final`: Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `final_nofewshot`: Entonces supongo que sería mejor que comenzara a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `final_fewshot6`: Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `final_raw_turns`: Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `final_t02`: Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `final_lexicon`: Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.

### 34 · S06 · If you're looking for work, the blacksmith needs a hand. He pays well, but he has a nasty temper.

- `baseline`: Si buscas trabajo, el herrero necesita ayuda. Él paga bien, pero tiene un temperamento difícil.
- `official_en`: Si estás buscando trabajo, el herrero necesita ayuda. Pagaba bien, pero tenía un mal carácter.
- `official_zh`: Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un mal carácter.
- `sys_style`: Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un carácter difícil.
- `sys_fewshot`: Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un mal carácter.
- `sys_fewshot_ctx`: Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento terrible.
- `final`: Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento terrible.
- `final_nofewshot`: Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tenía un temperamento malo.
- `final_fewshot6`: Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tenía un temperamento difícil.
- `final_raw_turns`: Si estás buscando trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un mal carácter.
- `final_t02`: Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento terrible.
- `final_lexicon`: Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento terrible.

### 35 · S06 · I've faced dragons, old man. A grumpy blacksmith doesn't scare me.

- `baseline`: He enfrentado dragones, anciano. Un herrero gruñón no me asusta.
- `official_en`: He enfrentado dragones, anciano. Un herrero gruñón no me asusta.
- `official_zh`: He enfrentado dragones, anciano. Un herrero malhumorado no me asusta.
- `sys_style`: He enfrentado dragones, anciano. Un herrero gruñón no me asusta.
- `sys_fewshot`: He enfrentado dragones, viejo. Un herrero gruñón no me asusta.
- `sys_fewshot_ctx`: He enfrentado dragones, anciano. Un herrero gruñón no me asusta.
- `final`: He enfrentado dragones, anciano. Un herrero gruñón no me asusta.
- `final_nofewshot`: He enfrentado dragones, anciano. Un herrero gruñón no me asusta.
- `final_fewshot6`: He enfrentado dragones, anciano. Un herrero gruñón no me asusta.
- `final_raw_turns`: He enfrentado dragones, viejo. Un herrero gruñón no me asusta.
- `final_t02`: He enfrentado dragones, anciano. Un herrero gruñón no me asusta.
- `final_lexicon`: He enfrentado dragones, anciano. Un herrero gruñón no me asusta.

### 36 · S06 · You haven't met his wife yet.

- `baseline`: Aún no has conocido a su esposa.
- `official_en`: [Texto de origen] Aún no has conocido a su esposa.
- `official_zh`: Todavía no has conocido a su esposa.
- `sys_style`: Aún no has conocido a su esposa.
- `sys_fewshot`: Todavía no has conocido a su esposa.
- `sys_fewshot_ctx`: Todavía no has conocido a su esposa.
- `final`: Todavía no has conocido a su esposa.
- `final_nofewshot`: Todavía no has conocido a su esposa.
- `final_fewshot6`: Todavía no has conocido a su esposa.
- `final_raw_turns`: Todavía no has conocido a su esposa.
- `final_t02`: Todavía no has conocido a su esposa.
- `final_lexicon`: Todavía no has conocido a su esposa.

### 37 · S07 · Guys, I have some great news and some terrible news.

- `baseline`: Chicos, tengo algunas buenas noticias y algunas malas noticias.
- `official_en`: Chicos, tengo buenas noticias y malas noticias.
- `official_zh`: Chicos, tengo buenas noticias y malas noticias.
- `sys_style`: Chicos, tengo algunas buenas noticias y algunas malas noticias.
- `sys_fewshot`: Chicos, tengo buenas noticias y malas noticias.
- `sys_fewshot_ctx`: Chicos, tengo buenas noticias y malas noticias.
- `final`: Chicos, tengo buenas noticias y malas noticias.
- `final_nofewshot`: Chicos, tengo algunas buenas noticias y algunas malas noticias.
- `final_fewshot6`: Chicos, tengo buenas noticias y malas noticias.
- `final_raw_turns`: Chicos, tengo buenas noticias y malas noticias.
- `final_t02`: Chicos, tengo buenas noticias y malas noticias.
- `final_lexicon`: Chicos, tengo buenas noticias y malas noticias.

### 38 · S07 · The terrible news first, please. We like to end on a high.

- `baseline`: Por favor, primero, las noticias terribles. Nos gusta terminar con algo positivo.
- `official_en`: [Información de fondo]   ⏎ Conversación hasta ahora (en inglés original, luego en español):   ⏎ Inglés: Chicos, tengo buenas noticias y malas noticias.   ⏎ Español: Chicos, tengo buenas noticias y mal
- `official_zh`: Primero, las malas noticias. Nos gusta terminar bien.
- `sys_style`: Por favor, primero, las noticias terribles. Nos gusta terminar con algo positivo.
- `sys_fewshot`: Primero, por favor, las malas noticias. Nos gusta terminar bien.
- `sys_fewshot_ctx`: Primero, las malas noticias. Nos gusta terminar bien.
- `final`: Primero, las malas noticias. Nos gusta terminar bien.
- `final_nofewshot`: Primero, las malas noticias. Nos gusta terminar con algo positivo.
- `final_fewshot6`: Primero, las malas noticias. Nos gusta terminar con algo positivo.
- `final_raw_turns`: Las malas noticias primero, por favor. Nos gusta terminar con algo positivo.
- `final_t02`: Primero, las malas noticias. Nos gusta terminar bien.
- `final_lexicon`: Primero, las malas noticias. Nos gusta terminar bien.

### 39 · S07 · The printer is on fire. Again.

- `baseline`: La impresora está en llamas. De nuevo.
- `official_en`: La impresora está en llamas. De nuevo.
- `official_zh`: La impresora está en llamas. De nuevo.
- `sys_style`: La impresora está en llamas. De nuevo.
- `sys_fewshot`: La impresora está en llamas. De nuevo.
- `sys_fewshot_ctx`: La impresora está en llamas. De nuevo.
- `final`: La impresora está en llamas. De nuevo.
- `final_nofewshot`: La impresora está en llamas. De nuevo.
- `final_fewshot6`: La impresora está en llamas. De nuevo.
- `final_raw_turns`: La impresora está en llamas. De nuevo.
- `final_t02`: La impresora está en llamas. De nuevo.
- `final_lexicon`: La impresora está en llamas. De nuevo.

### 40 · S07 · And the great news?

- `baseline`: ¿Y las buenas noticias?
- `official_en`: ¿Y las buenas noticias?
- `official_zh`: ¿Y las buenas noticias?
- `sys_style`: ¿Y las buenas noticias?
- `sys_fewshot`: ¿Y las buenas noticias?
- `sys_fewshot_ctx`: ¿Y las buenas noticias?
- `final`: ¿Y las buenas noticias?
- `final_nofewshot`: ¿Y las buenas noticias?
- `final_fewshot6`: ¿Y las buenas noticias?
- `final_raw_turns`: ¿Y las buenas noticias?
- `final_t02`: ¿Y las buenas noticias?
- `final_lexicon`: ¿Y las buenas noticias?

### 41 · S07 · It's not our printer.

- `baseline`: No es nuestra impresora.
- `official_en`: No es nuestra impresora.
- `official_zh`: No es nuestra impresora.
- `sys_style`: No es nuestra impresora.
- `sys_fewshot`: No es nuestra impresora.
- `sys_fewshot_ctx`: No es nuestra impresora.
- `final`: No es nuestra impresora.
- `final_nofewshot`: No es nuestra impresora.
- `final_fewshot6`: No es nuestra impresora.
- `final_raw_turns`: No es nuestra impresora.
- `final_t02`: No es nuestra impresora.
- `final_lexicon`: No es nuestra impresora.

### 42 · S07 · Okay, everybody, grab your laptops and follow me. We're working in the parking lot today.

- `baseline`: Bien, todos, tomen sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `official_en`: [Texto de origen]   ⏎ Bien, todos, tomen sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `official_zh`: De acuerdo, todos, tomen sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `sys_style`: Bien, todos, por favor, tomen sus portátiles y síganme. Hoy trabajaremos en el estacionamiento.
- `sys_fewshot`: De acuerdo, todos, guardad vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento.
- `sys_fewshot_ctx`: De acuerdo, todos, coged vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento.
- `final`: De acuerdo, todos, coged vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento.
- `final_nofewshot`: De acuerdo, todos, recogen vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento.
- `final_fewshot6`: De acuerdo, todos, llevad vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento.
- `final_raw_turns`: Bien, todos, coged vuestros portátiles y seguidme. Hoy trabajaremos en el estacionamiento.
- `final_t02`: Está bien, todos, coged vuestros portátiles y seguidme. Hoy trabajaremos en el estacionamiento.
- `final_lexicon`: De acuerdo, todos, guardad vuestras portátiles y seguidme. Hoy trabajaremos en el aparcamiento.

### 43 · S08 · Can you pull over at the next gas station? I need a sandwich and a bathroom.

- `baseline`: ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `official_en`: ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `official_zh`: ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `sys_style`: ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `sys_fewshot`: ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `sys_fewshot_ctx`: ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `final`: ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `final_nofewshot`: ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `final_fewshot6`: ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `final_raw_turns`: ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `final_t02`: ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `final_lexicon`: ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.

### 44 · S08 · We're already an hour late. Can't you hold it?

- `baseline`: Ya estamos una hora tarde. ¿No puedes adelantar el tiempo?
- `official_en`: Ya estamos una hora retrasados. ¿No puedes adelantar un poco?
- `official_zh`: Ya estamos una hora retrasados. ¿No puedes esperar un poco?
- `sys_style`: Ya estamos una hora retrasados. ¿No puedes controlar el tiempo?
- `sys_fewshot`: Llegamos con una hora de retraso. ¿No puedes controlarlo?
- `sys_fewshot_ctx`: Llegamos con una hora de retraso. ¿No puedes controlar la situación?
- `final`: Llegamos con una hora de retraso. ¿No puedes controlar la situación?
- `final_nofewshot`: Ya estamos una hora retrasados. ¿No puedes esperar un poco?
- `final_fewshot6`: Llegamos con una hora de retraso. ¿No puedes controlarlo?
- `final_raw_turns`: Ya estamos una hora tarde. ¿No puedes esperar un poco?
- `final_t02`: Llegamos con una hora de retraso. ¿No puedes esperar un poco?
- `final_lexicon`: Ya estamos una hora tarde. ¿No puedes esperar un poco?

### 45 · S08 · No, I can't, and stop looking at me like that.

- `baseline`: No, no puedo. Deja de mirarme así.
- `official_en`: [Texto de origen] No, no puedo, y deja de mirarme así.
- `official_zh`: No, no puedo, y deja de mirarme así.
- `sys_style`: No, no puedo. Deja de mirarme así.
- `sys_fewshot`: No, no puedo, y deja de mirarme así.
- `sys_fewshot_ctx`: No, no puedo, y deja de mirarme así.
- `final`: No, no puedo, y deja de mirarme así.
- `final_nofewshot`: No, no puedo, y deja de mirarme así.
- `final_fewshot6`: No, no puedo, y deja de mirarme así.
- `final_raw_turns`: No, no puedo, y deja de mirarme así.
- `final_t02`: No, no puedo, y deja de mirarme así.
- `final_lexicon`: No, no puedo, y deja de mirarme así.

### 46 · S08 · Fine, but you're driving after this. My eyes are killing me.

- `baseline`: Está bien, pero vas a conducir después de esto. Mis ojos se están matando de tanto trabajo.
- `official_en`: [Texto de origen] Está bien, pero debes conducir después de esto. Mis ojos se están muriendo de cansancio.
- `official_zh`: Está bien, pero tienes que seguir conduciendo después de esto. Mis ojos se están muriendo de cansancio.
- `sys_style`: Está bien, pero vas a conducir después de esto. Mis ojos se están muriendo de cansancio.
- `sys_fewshot`: Está bien, pero conduces después de esto. Mis ojos se están muriendo de cansancio.
- `sys_fewshot_ctx`: Está bien, pero conduzcas después de esto. Mis ojos están matándome.
- `final`: Está bien, pero conduzcas después de esto. Mis ojos están matándome.
- `final_nofewshot`: Está bien, pero conduces después de esto. Mis ojos se están muriendo de cansancio.
- `final_fewshot6`: Está bien, pero conduces después de esto. Mis ojos se están muriendo.
- `final_raw_turns`: Está bien, pero conduces después de esto. Me estoy muriendo de cansancio.
- `final_t02`: Está bien, pero conduzcas después de esto. Mis ojos están matándome.
- `final_lexicon`: Está bien, pero conduzcas después de esto. Mis ojos se están muriendo de cansancio.

### 47 · S08 · Deal. And grab the map out of the glove compartment.

- `baseline`: Trato hecho. Y saca la mapa del compartimento de herramientas.
- `official_en`: [Texto de origen] De acuerdo. Y saca el mapa del compartimento del puño.
- `official_zh`: De acuerdo. Y saca el mapa del compartimento de las guantes.
- `sys_style`: Trato hecho. Y toma el mapa del compartimento de herramientas.
- `sys_fewshot`: De acuerdo. Y saca el mapa del compartimento de las guías.
- `sys_fewshot_ctx`: De acuerdo. Y saca el mapa del compartimento de las guías.
- `final`: De acuerdo. Y saca el mapa del compartimento de las guías.
- `final_nofewshot`: De acuerdo. Y saca el mapa del compartimento del portón trasero.
- `final_fewshot6`: De acuerdo. Y saca el mapa del compartimento del asiento del conductor.
- `final_raw_turns`: De acuerdo. Y saca el mapa del compartimento del asiento trasero.
- `final_t02`: De acuerdo. Y saca el mapa del compartimento de las guías.
- `final_lexicon`: De acuerdo. Y toma el mapa del guantera.

### 48 · S08 · Dude, nobody uses maps anymore. We have GPS.

- `baseline`: Amigo, ya nadie utiliza mapas. Tenemos el GPS.
- `official_en`: Amigo, ya nadie usa mapas. Tenemos GPS.
- `official_zh`: Oye, ya nadie usa mapas. Tenemos GPS.
- `sys_style`: Amigo, ya nadie utiliza mapas. Tenemos GPS.
- `sys_fewshot`: Tío, ya nadie usa mapas. Tenemos GPS.
- `sys_fewshot_ctx`: Tío, ya nadie usa mapas. Tenemos GPS.
- `final`: Tío, ya nadie usa mapas. Tenemos GPS.
- `final_nofewshot`: Oye, nadie usa mapas ahora. Tenemos GPS.
- `final_fewshot6`: Oye, ya nadie usa mapas. Tenemos GPS.
- `final_raw_turns`: Tío, nadie usa mapas ahora. Tenemos GPS.
- `final_t02`: Tío, ya nadie usa mapas. Tenemos GPS.
- `final_lexicon`: Tío, ya nadie usa mapas. Tenemos GPS.

### 49 · S09 · Welcome back to Lucky Hour, everybody! Are you ready? Our next contestant is Marcus from Detroit.

- `baseline`: Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo participante es Marcus, de Detroit.
- `official_en`: Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `official_zh`: Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `sys_style`: Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `sys_fewshot`: Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `sys_fewshot_ctx`: Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `final`: Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `final_nofewshot`: Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `final_fewshot6`: Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `final_raw_turns`: Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `final_t02`: Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `final_lexicon`: Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.

### 50 · S09 · Marcus, for ten thousand dollars: what is the capital of Australia?

- `baseline`: Marcus, por diez mil dólares: ¿Cuál es la capital de Australia?
- `official_en`: Marcus, por diez mil dólares: ¿Cuál es la capital de Australia?
- `official_zh`: Marcus, por diez mil dólares: ¿Cuál es la capital de Australia?
- `sys_style`: Marcus, por diez mil dólares: ¿Cuál es la capital de Australia?
- `sys_fewshot`: Marcus, por diez mil dólares: ¿cuál es la capital de Australia?
- `sys_fewshot_ctx`: Marcus, por diez mil dólares: ¿cuál es la capital de Australia?
- `final`: Marcus, por diez mil dólares: ¿cuál es la capital de Australia?
- `final_nofewshot`: Marcus, por diez mil dólares: ¿Cuál es la capital de Australia?
- `final_fewshot6`: Marcus, por diez mil dólares: ¿cuál es la capital de Australia?
- `final_raw_turns`: Marcus, por diez mil dólares: ¿cuál es la capital de Australia?
- `final_t02`: Marcus, por diez mil dólares: ¿cuál es la capital de Australia?
- `final_lexicon`: Marcus, por diez mil dólares: ¿cuál es la capital de Australia?

### 51 · S09 · Uh, is it Sydney? No, wait, don't tell me, it's Canberra!

- `baseline`: Uh, ¿es Sydney? No, espera, no me digas que es Canberra.
- `official_en`: [Información de fondo]   ⏎ Conversación hasta ahora (original en inglés, luego en español):   ⏎ Inglés: Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo participante es Marcus de Detroit.   ⏎ Esp
- `official_zh`: Uh, ¿es Sídney? No, espera, no me digas, ¡es Canberra!
- `sys_style`: Uh, ¿es Sydney? No, espera, no me digas que es Canberra.
- `sys_fewshot`: ¿Es Sydney? No, espera, no me digas que es Canberra.
- `sys_fewshot_ctx`: ¿Sí, es Sídney? No, espera, no me digas que es Canberra.
- `final`: ¿Sí, es Sídney? No, espera, no me digas que es Canberra.
- `final_nofewshot`: Uh, ¿es Sídney? No, espera, no me digas que es Canberra.
- `final_fewshot6`: ¿Sydney? No, espera, no me digas que es Canberra.
- `final_raw_turns`: Eh, ¿es Sídney? No, espera, no me digas, ¡es Canberra!
- `final_t02`: ¿Sí, es Sídney? No, espera, no me digas que es Canberra.
- `final_lexicon`: ¿Sí, es Sídney? No, espera, no me digas que es Canberra.

### 52 · S09 · Are you absolutely sure about that?

- `baseline`: ¿Estás completamente seguro de eso?
- `official_en`: ¿Estás completamente seguro de eso?
- `official_zh`: ¿Estás completamente seguro de eso?
- `sys_style`: ¿Estás absolutamente seguro de eso?
- `sys_fewshot`: ¿Estás completamente seguro de eso?
- `sys_fewshot_ctx`: ¿Estás absolutamente seguro de eso?
- `final`: ¿Estás absolutamente seguro de eso?
- `final_nofewshot`: ¿Estás absolutamente seguro de eso?
- `final_fewshot6`: ¿Estás completamente seguro de eso?
- `final_raw_turns`: ¿Estás absolutamente seguro de eso?
- `final_t02`: ¿Estás completamente seguro de eso?
- `final_lexicon`: ¿Estás absolutamente seguro de eso?

### 53 · S09 · Yes! Lock it in, please.

- `baseline`: ¡Sí! Por favor, bloéalo.
- `official_en`: [Texto de origen]   ⏎ ¡Sí! Por favor, ¡fíjalo en su lugar!
- `official_zh`: ¡Sí! Por favor, anótelo.
- `sys_style`: ¡Sí! Por favor, bloéjalo.
- `sys_fewshot`: ¡Sí! Por favor, bloquea eso.
- `sys_fewshot_ctx`: ¡Sí! Por favor, bloéjalo.
- `final`: ¡Sí! Por favor, bloéjalo.
- `final_nofewshot`: ¡Sí! Por favor, bloéalo.
- `final_fewshot6`: ¡Sí! Por favor, bloéjalo.
- `final_raw_turns`: ¡Sí! ¡Guárdalo, por favor.
- `final_t02`: ¡Sí! Por favor, bloéjalo.
- `final_lexicon`: ¡Sí! Por favor, bloéjalo.

### 54 · S09 · Correct! You just won ten thousand dollars!

- `baseline`: ¡Correcto! Acabas de ganar diez mil dólares.
- `official_en`: ¡Correcto! Acabas de ganar diez mil dólares.
- `official_zh`: ¡Correcto! Acabas de ganar diez mil dólares.
- `sys_style`: ¡Correcto! Acabas de ganar diez mil dólares.
- `sys_fewshot`: ¡Correcto! Acabas de ganar diez mil dólares.
- `sys_fewshot_ctx`: ¡Correcto! Acabas de ganar diez mil dólares.
- `final`: ¡Correcto! Acabas de ganar diez mil dólares.
- `final_nofewshot`: ¡Correcto! Acabas de ganar diez mil dólares.
- `final_fewshot6`: ¡Correcto! Acabas de ganar diez mil dólares.
- `final_raw_turns`: Correcto. Acabas de ganar diez mil dólares.
- `final_t02`: ¡Correcto! Acabas de ganar diez mil dólares.
- `final_lexicon`: ¡Correcto! Acabas de ganar diez mil dólares.

### 55 · S10 · Listen up, all of you. The vault opens at midnight, we grab the diamonds, and we're gone in ninety seconds.

- `baseline`: Escuchen bien, todos ustedes. El cofre se abre a medianoche; tomamos los diamantes y nos vamos en noventa segundos.
- `official_en`: Escuchen bien, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `official_zh`: Escuchen bien, todos ustedes. El cofre se abrirá a medianoche, tomaremos los diamantes y nos iremos en noventa segundos.
- `sys_style`: Escuchen bien, todos ustedes. El cofre se abrirá a medianoche, tomaremos los diamantes y nos iremos en noventa segundos.
- `sys_fewshot`: Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `sys_fewshot_ctx`: Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `final`: Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `final_nofewshot`: Escuchen bien, todos ustedes. El cofre se abrirá a medianoche, tomaremos los diamantes y nos iremos en noventa segundos.
- `final_fewshot6`: Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `final_raw_turns`: Escuchad bien, todos vosotros. El búnker se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `final_t02`: Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `final_lexicon`: Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.

### 56 · S10 · What if the guard changes his route?

- `baseline`: ¿Qué pasará si el guardia cambie su ruta?
- `official_en`: ¿Qué pasa si el guardia cambia su ruta?
- `official_zh`: ¿Qué pasa si el guardia cambia su ruta?
- `sys_style`: ¿Qué pasaría si el guardia cambiara su ruta?
- `sys_fewshot`: ¿Qué pasará si el guardia cambia su ruta?
- `sys_fewshot_ctx`: ¿Qué pasa si el guardia cambia su ruta?
- `final`: ¿Qué pasa si el guardia cambia su ruta?
- `final_nofewshot`: ¿Qué pasa si el guardia cambia su ruta?
- `final_fewshot6`: ¿Qué pasa si el guardia cambia su ruta?
- `final_raw_turns`: ¿Qué pasa si el guardia cambia su ruta?
- `final_t02`: ¿Qué pasará si el guardia cambia su ruta?
- `final_lexicon`: ¿Qué pasa si el guardia cambia su ruta?

### 57 · S10 · He won't. I've been watching him for three weeks.

- `baseline`: No lo hará. Lo he estado observando durante tres semanas.
- `official_en`: Él no lo hará. Lo he estado observando durante tres semanas.
- `official_zh`: No lo hará. Lo he estado vigilando durante tres semanas.
- `sys_style`: No lo hará. Lo he estado observando durante tres semanas.
- `sys_fewshot`: No lo hará. Lo he estado observando durante tres semanas.
- `sys_fewshot_ctx`: No lo hará. Lo he estado vigilando durante tres semanas.
- `final`: No lo hará. Lo he estado vigilando durante tres semanas.
- `final_nofewshot`: No lo hará. Lo he estado vigilando durante tres semanas.
- `final_fewshot6`: No lo hará. Lo he estado vigilando durante tres semanas.
- `final_raw_turns`: No lo hará. Lo he estado vigilando durante tres semanas.
- `final_t02`: No lo hará. Lo he estado vigilando durante tres semanas.
- `final_lexicon`: No lo hará. Lo he estado vigilando durante tres semanas.

### 58 · S10 · You're out of your mind, but I'm in.

- `baseline`: Estás loco, pero yo sí estoy cuerdo.
- `official_en`: [Información de fondo]   ⏎ Conversación hasta ahora (original en inglés, luego en español):   ⏎ Inglés: Escuchen bien, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segund
- `official_zh`: Estás loco, pero yo sí estoy cuerdo.
- `sys_style`: Estás loco, pero yo sí estoy cuerdo.
- `sys_fewshot`: Estás loco, pero yo sí lo estoy.
- `sys_fewshot_ctx`: Estás loco, pero yo sí estoy cuerdo.
- `final`: Estás loco, pero yo sí estoy cuerdo.
- `final_nofewshot`: Estás loco, pero yo sí estoy cuerdo.
- `final_fewshot6`: Estás loco, pero yo sí estoy cuerdo.
- `final_raw_turns`: Estás loco, pero yo sí estoy cuerdo.
- `final_t02`: Estás loco, pero yo sí estoy cuerdo.
- `final_lexicon`: Estás loco, pero yo sí estoy cuerdo.

### 59 · S10 · Whatever happens, nobody goes back for anyone. Got it?

- `baseline`: Pase lo que pase, nadie regresa por nadie. ¿Entiendes?
- `official_en`: [Información de fondo]   ⏎ Conversación hasta ahora (original en inglés, luego en español):   ⏎ Inglés: Escuchen bien, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segund
- `official_zh`: Sea lo que sea que pase, nadie regresa por nadie. ¿Entendido?
- `sys_style`: Sea lo que sea que pase, nadie regresa por nadie. ¿Entendido?
- `sys_fewshot`: Sea lo que sea que pase, nadie regresa por nadie. ¿Entendido?
- `sys_fewshot_ctx`: Pase lo que pase, nadie regresa por nadie. ¿Entendido?
- `final`: Pase lo que pase, nadie regresa por nadie. ¿Entendido?
- `final_nofewshot`: Pase lo que pase, nadie regresa por nadie. ¿Entendido?
- `final_fewshot6`: Pase lo que pase, nadie regresa por nadie. ¿Entendido?
- `final_raw_turns`: Pase lo que pase, nadie regresa por nadie. ¿Entendido?
- `final_t02`: Pase lo que pase, nadie regresa por nadie. ¿Entendido?
- `final_lexicon`: Pase lo que pase, nadie regresa por nadie. ¿Entendido?

### 60 · S10 · Kill the lights.

- `baseline`: Apague las luces.
- `official_en`: [Texto de origen]   ⏎ Apague las luces.
- `official_zh`: Apague las luces.
- `sys_style`: Apague las luces.
- `sys_fewshot`: Apaguen las luces.
- `sys_fewshot_ctx`: Apague las luces.
- `final`: Apague las luces.
- `final_nofewshot`: Apague las luces.
- `final_fewshot6`: Apague las luces.
- `final_raw_turns`: Apague las luces.
- `final_t02`: Apague las luces.
- `final_lexicon`: Apague las luces.

### 61 · S11 · Zephyrine Quill swore she would find the Hollowmere before the first frost.

- `baseline`: Zephyrine Quill juró que encontraría Hollowmere antes de que llegara el primer frío.
- `official_en`: Zephyrine Quill juró que encontraría Hollowmere antes del primer frío.
- `official_zh`: Zefirina Quill juró que encontraría Yermomar antes del primer frío.
- `sys_style`: Zephyrine Quill juró que encontraría Hollowmere antes del primer frío.
- `sys_fewshot`: Zephyrine Quill juró que encontraría Hollowmere antes de la primera helada.
- `sys_fewshot_ctx`: Zephyrine Quill juró que encontraría Hollowmere antes de la primera helada.
- `final`: Zefirina Quill juró que encontraría Yermomar antes de la primera helada.
- `final_nofewshot`: Zefirina Quill juró que encontraría Yermomar antes de la primera helada.
- `final_fewshot6`: Zefirina Quill juró que encontraría Yermomar antes del primer frío.
- `final_raw_turns`: Zefirina Quill juró que encontraría Yermomar antes del primer frío.
- `final_t02`: Zefirina Quill juró que encontraría Yermomar antes del primer frío.
- `final_lexicon`: Zefirina Quill juró que encontraría Yermomar antes de la primera helada.

### 62 · S11 · The Ember Court has closed the gates of Glassreach, and nobody is allowed in or out.

- `baseline`: Ember Court ha cerrado las puertas de Glassreach; nadie puede entrar ni salir.
- `official_en`: El Ember Court ha cerrado las puertas de Glassreach, y nadie está autorizado a entrar ni salir.
- `official_zh`: Corte de Ascuas ha cerrado las puertas de Cristalcanto, y nadie está autorizado a entrar ni salir.
- `sys_style`: El Ember Court ha cerrado las puertas de Glassreach, y a nadie se le permite entrar ni salir.
- `sys_fewshot`: Ember Court ha cerrado las puertas de Glassreach, y nadie está autorizado a entrar o salir.
- `sys_fewshot_ctx`: Ember Court ha cerrado las puertas de Glassreach, y nadie está autorizado a entrar o salir.
- `final`: La Corte de Ascuas ha cerrado las puertas de Cristalcanto, y a nadie se le permite entrar o salir.
- `final_nofewshot`: La Corte de Ascuas ha cerrado las puertas de Cristalcanto, y a nadie se le permite entrar ni salir.
- `final_fewshot6`: El Corte de Ascuas ha cerrado las puertas de Cristalcanto, y nadie puede entrar ni salir.
- `final_raw_turns`: La Corte de Ascuas ha cerrado las puertas de Cristalcanto, y nadie puede entrar ni salir.
- `final_t02`: El Corte de Ascuas ha cerrado las puertas de Cristalcanto, y nadie está autorizado a entrar o salir.
- `final_lexicon`: La Corte de Ascuas ha cerrado las puertas de Cristalcanto, y a nadie se le permite entrar o salir.

### 63 · S11 · Captain Brannoch, you'll ride with me to Thornwick Keep at dawn.

- `baseline`: Capitán Brannoch, viajará conmigo a Thornwick Keep al amanecer.
- `official_en`: Capitán Brannoch, viajará conmigo a Fortaleza Espinal al amanecer.
- `official_zh`: Capitán Brannoch, viajará conmigo a Fortaleza Espinal al amanecer.
- `sys_style`: Capitán Brannoch, viajará conmigo a Thornwick Keep al amanecer.
- `sys_fewshot`: Capitán Brannoch, viajará conmigo a Thornwick Keep al amanecer.
- `sys_fewshot_ctx`: Capitán Brannoch, viajará conmigo a Thornwick Keep al amanecer.
- `final`: Capitán Brannoch, viajará conmigo a Fortaleza Espinal al amanecer.
- `final_nofewshot`: Capitán Brannoch, cabalgaremos conmigo a Fortaleza Espinal al amanecer.
- `final_fewshot6`: Capitán Brannoch, cabalgaremos conmigo a Fortaleza Espinal al amanecer.
- `final_raw_turns`: Capitán Brannoch, viajarás conmigo a Fortaleza Espinal al amanecer.
- `final_t02`: Capitán Brannoch, viajarás conmigo a Fortaleza Espinal al amanecer.
- `final_lexicon`: Capitán Brannoch, viajará conmigo a Fortaleza Espinal al amanecer.

### 64 · S11 · Did you hear what Sir Aldous Fenn said about the Hollowmere?

- `baseline`: ¿Escuchó lo que dijo Sir Aldous Fenn sobre Hollowmere?
- `official_en`: ¿Escuchaste lo que dijo Ser Aldous Fenn sobre Hollowmere?
- `official_zh`: ¿Escuchaste lo que dijo ser Aldous Fenn sobre Yermomar?
- `sys_style`: ¿Escuchó lo que dijo Sir Aldous Fenn sobre Hollowmere?
- `sys_fewshot`: ¿Escuchaste lo que dijo Sir Aldous Fenn sobre Hollowmere?
- `sys_fewshot_ctx`: ¿Escuchaste lo que dijo Sir Aldous Fenn sobre Hollowmere?
- `final`: ¿Escuchaste lo que dijo ser Aldous Fenn sobre Yermomar?
- `final_nofewshot`: ¿Escuchaste lo que dijo ser Aldous Fenn sobre Yermomar?
- `final_fewshot6`: ¿Escuchaste lo que dijo ser Aldous Fenn sobre Yermomar?
- `final_raw_turns`: ¿Escuchaste lo que dijo ser Aldous Fenn sobre Yermomar?
- `final_t02`: ¿Escuchaste lo que dijo ser Aldous Fenn sobre Yermomar?
- `final_lexicon`: ¿Escuchaste lo que dijo ser Aldous Fenn sobre Yermomar?

### 65 · S11 · They say Kaelith Vorne still carries the blade of Zephyrine Quill into every battle.

- `baseline`: Se dice que Kaelith Vorne sigue llevando consigo la espada de Zephyrine Quill en cada batalla.
- `official_en`: Dicen que Kaelith Vorne sigue llevando la espada de Zephyrine Quill en cada batalla.
- `official_zh`: Dicen que Kaelith Vorne sigue llevando la espada de Zefirina Quill en cada batalla.
- `sys_style`: Se dice que Kaelith Vorne sigue llevando la espada de Zephyrine Quill en cada batalla.
- `sys_fewshot`: Dicen que Kaelith Vorne sigue llevando la espada de Zephyrine Quill en cada batalla.
- `sys_fewshot_ctx`: Dicen que Kaelith Vorne sigue llevando la espada de Zephyrine Quill en cada batalla.
- `final`: Se dice que Kaelith Vorne sigue llevando la espada de Zefirina Quill en cada batalla.
- `final_nofewshot`: Se dice que Kaelith Vorne sigue llevando la espada de Zefirina Quill en cada batalla.
- `final_fewshot6`: Se dice que Kaelith Vorne sigue llevando la espada de Zefirina Quill a cada batalla.
- `final_raw_turns`: Se dice que Kaelith Vorne sigue llevando la espada de Zefirina Quill a cada batalla.
- `final_t02`: Se dice que Kaelith Vorne sigue llevando la espada de Zefirina Quill en cada batalla.
- `final_lexicon`: Se dice que Kaelith Vorne sigue llevando la espada de Zefirina Quill en cada batalla.
