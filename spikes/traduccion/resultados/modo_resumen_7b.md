# Modo resumen: traducción concisa con Hy-MT2 (generado por concise.py)

Modelo: `Hy-MT2-7B-Q4_K_M.gguf`.

Diez frases largas del corpus (≥ 15 palabras: líneas 1, 9, 11, 24, 33, 34, 42, 43, 49, 55), 1 semillas (42) por variante = 10 traducciones por variante. La reducción se calcula contra la traducción normal (prompt final) de la misma frase y la misma semilla.

## Resumen por variante

| Variante | Palabras de media | Reducción de palabras: mediana / media | Reducción de caracteres: mediana | Frases con ≥ 25 % menos | Frases sin acortar | Elementos clave conservados | Salidas que no son traducción | Total p50, ms | 1.er token p50, ms | Tokens generados (media) |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `normal` | 18,6 | 0 % / 0 % | 0 % | 0% | 100% | 93% | 0 | 449 | 187 | 32,5 |
| `official_style_en` | 16,5 | 8 % / 9 % | 12 % | 10% | 30% | 92% | 0 | 288 | 46 | 29,2 |
| `official_style_es` | 17,4 | 5 % / 5 % | 8 % | 0% | 40% | 91% | 0 | 297 | 46 | 30,0 |
| `official_style_zh` | 17,7 | 5 % / 5 % | 6 % | 0% | 40% | 90% | 0 | 298 | 45 | 30,9 |
| `official_style_budget` | 14,5 | 18 % / 19 % | 22 % | 30% | 0% | 89% | 0 | 272 | 50 | 25,9 |
| `official_style_subtitle_en` | 18,7 | 0 % / -1 % | 4 % | 0% | 60% | 92% | 0 | 319 | 44 | 32,7 |
| `official_style_subtitle_zh` | 18,6 | 0 % / 0 % | 1 % | 0% | 80% | 91% | 0 | 310 | 46 | 32,5 |
| `official_style_telegraphic` | 12,4 | 32 % / 32 % | 29 % | 60% | 0% | 86% | 0 | 246 | 51 | 24,0 |
| `official_personalization` | 10,4 | 43 % / 46 % | 45 % | 90% | 0% | 66% | 0 | 197 | 54 | 19,5 |
| `official_personalization_zh` | 11,4 | 37 % / 38 % | 39 % | 80% | 10% | 67% | 0 | 231 | 56 | 21,3 |
| `final_sys_concise` | 18,1 | 0 % / 3 % | 1 % | 0% | 60% | 93% | 0 | 444 | 189 | 31,6 |
| `final_concise_fs` | 18,4 | 0 % / 1 % | 1 % | 0% | 70% | 93% | 0 | 413 | 157 | 31,8 |
| `final_concise_fs_budget` | 16,6 | 12 % / 10 % | 9 % | 0% | 20% | 93% | 0 | 417 | 170 | 29,9 |
| `two_step` | 12,5 | 32 % / 31 % | 33 % | 60% | 10% | 80% | 0 | 703 | 514 | 22,8 |
| `derived_drop_last_sentence` | 11,5 | 45 % / 43 % | 45 % | 80% | 20% | 50% | 0 | — | — | — |

Descripción de las variantes:

- `normal`: prompt final, sin pedir concisión (referencia).
- `official_style_en` / `official_style_es` / `official_style_zh`: plantilla oficial «Style» en un solo mensaje (sin contexto ni ejemplos) con el estilo conciso en inglés / en español («traduce de forma muy concisa, solo lo esencial, en español de España») / en chino.
- `official_style_budget`: como `official_style_en` más «at most N words» (N = 60 % de las palabras de la frase inglesa).
- `official_style_subtitle_en` / `official_style_subtitle_zh`: plantilla «Style» con estilo de subtítulos de vídeo (conciso, hablado, fácil de leer rápido), en inglés y en chino.
- `official_style_telegraphic`: plantilla «Style» con estilo telegráfico, de titular, con tope de palabras.
- `official_personalization` / `official_personalization_zh`: plantilla oficial «Personalization» con la preferencia de concisión y el tope de palabras, en inglés y en chino.
- `final_sys_concise`: prompt final con el estilo conciso en el mensaje de sistema (ejemplos normales).
- `final_concise_fs`: igual, con 6 ejemplos previos de traducción CONCISA en lugar de los 12 normales.
- `final_concise_fs_budget`: ejemplos concisos y tope de palabras en cada turno.
- `two_step`: traducción normal y una segunda llamada que la acorta (latencia = suma de las dos).
- `derived_drop_last_sentence`: NO es una petición al modelo; es la traducción normal sin su última oración (si tiene dos o más). Referencia de lo que se ganaría descartando contenido.

## Salidas de todas las variantes (semilla 42)

### 1 · Did you seriously finish the orange juice and put the empty carton back in the fridge?

- `normal` (17 pal., 0 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste a poner la lata vacía en el refrigerador?
- `official_style_en` (19 pal., -12 %, claves 2/3): ¿De verdad te bebiste todo el jugo de naranja y volviste a meter la lata vacía en el frigorífico?
- `official_style_es` (19 pal., -12 %, claves 2/3): ¿De verdad te has bebido todo el zumo y has vuelto a meter la lata vacía en el frigorífico?
- `official_style_zh` (19 pal., -12 %, claves 2/3): ¿De verdad te bebiste todo el jugo de naranja y volviste a poner la lata vacía en el refrigerador?
- `official_style_budget` (13 pal., 24 %, claves 2/3): ¿De verdad terminaste el zumo y pusiste la lata vacía en el frigorífico?
- `official_style_subtitle_en` (19 pal., -12 %, claves 2/3): ¿En serio te bebiste todo el jugo de naranja y volviste a meter la lata vacía en el frigorífico?
- `official_style_subtitle_zh` (17 pal., 0 %, claves 2/3): ¿En serio terminaste el jugo de naranja y volviste a poner la lata vacía en el refrigerador?
- `official_style_telegraphic` (13 pal., 24 %, claves 2/3): Acabó el jugo de naranja y guardó la lata vacía en el frigorífico.
- `official_personalization` (8 pal., 53 %, claves 1/3): ¿De verdad terminaste el zumo y lo guardaste?
- `official_personalization_zh` (14 pal., 18 %, claves 1/3): ¿De verdad te bebiste todo el jugo y volviste a guardar la lata vacía?
- `final_sys_concise` (17 pal., 0 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y pusiste la lata vacía de vuelta en el refrigerador?
- `final_concise_fs` (19 pal., -12 %, claves 2/3): ¿De verdad te bebiste todo el jugo de naranja y volviste a poner la lata vacía en el refrigerador?
- `final_concise_fs_budget` (15 pal., 12 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y pusiste la lata vacía en el frigorífico?
- `two_step` (11 pal., 35 %, claves 2/3): Terminaste el jugo y pusiste la lata vacía en el frigorífico.
- `derived_drop_last_sentence` (17 pal., 0 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste a poner la lata vacía en el refrigerador?

### 9 · They found fibers under the victim's fingernails and a sneaker print by the window. None of it matches anything in her apartment.

- `normal` (28 pal., 0 %, claves 5/6): Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla deportiva junto a la ventana. Nada de eso coincide con nada en su apartamento.
- `official_style_en` (22 pal., 21 %, claves 6/6): Encontraron fibras bajo las uñas de la víctima y huellas de zapatilla junto a la ventana. Nada coincide con lo del piso.
- `official_style_es` (27 pal., 4 %, claves 5/6): Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla junto a la ventana. Nada de eso coincide con nada en su piso.
- `official_style_zh` (27 pal., 4 %, claves 5/6): Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla junto a la ventana. Nada de eso coincide con nada en su apartamento.
- `official_style_budget` (17 pal., 39 %, claves 6/6): Encontraron fibras bajo uñas y huella de zapatilla cerca de la ventana; nada coincide con su piso.
- `official_style_subtitle_en` (27 pal., 4 %, claves 5/6): Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla junto a la ventana. Nada de eso coincide con nada en su apartamento.
- `official_style_subtitle_zh` (27 pal., 4 %, claves 5/6): Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla cerca de la ventana. Nada de eso coincide con nada en su apartamento.
- `official_style_telegraphic` (15 pal., 46 %, claves 6/6): Hallaron fibras bajo uñas víctima y huella zapatilla cerca ventana. Ninguna coincide con objetos apartamento.
- `official_personalization` (18 pal., 36 %, claves 5/6): Encontraron fibras bajo sus uñas y huellas de zapatilla cerca de la ventana; nada corresponde a su apartamento.
- `official_personalization_zh` (18 pal., 36 %, claves 6/6): Encontraron fibras bajo sus uñas y huellas de zapatilla cerca de la ventana. Nada coincide con su piso.
- `final_sys_concise` (27 pal., 4 %, claves 5/6): Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla junto a la ventana. Nada de eso coincide con nada en su apartamento.
- `final_concise_fs` (27 pal., 4 %, claves 5/6): Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla junto a la ventana. Nada de eso coincide con nada en su apartamento.
- `final_concise_fs_budget` (23 pal., 18 %, claves 6/6): Encontraron fibras debajo de las uñas de la víctima y huellas de zapatilla junto a la ventana. Nada coincide con lo del apartamento.
- `two_step` (17 pal., 39 %, claves 5/6): Hallaron fibras bajo uñas y huella de zapatilla cerca de la ventana, sin coincidir con su apartamento.
- `derived_drop_last_sentence` (19 pal., 32 %, claves 4/6): Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla deportiva junto a la ventana.

### 11 · Or someone wants us to think so. Get me the security footage from the building across the street.

- `normal` (15 pal., 0 %, claves 5/5): O alguien quiere que pensemos eso. Tráeme las grabaciones de seguridad del edificio de enfrente.
- `official_style_en` (15 pal., 0 %, claves 5/5): O alguien quiere que lo pensemos. Trae las grabaciones de seguridad del edificio de enfrente.
- `official_style_es` (16 pal., -7 %, claves 5/5): O alguien quiere que lo pensemos así. Tráeme las grabaciones de seguridad del edificio de enfrente.
- `official_style_zh` (15 pal., 0 %, claves 5/5): O alguien quiere que pensemos eso. Tráigame las grabaciones de seguridad del edificio de enfrente.
- `official_style_budget` (14 pal., 7 %, claves 5/5): Alguien quiere que pensemos eso. Trae las grabaciones de seguridad del edificio de enfrente.
- `official_style_subtitle_en` (15 pal., 0 %, claves 5/5): O alguien quiere que pensemos eso. Tráeme las grabaciones de seguridad del edificio de enfrente.
- `official_style_subtitle_zh` (15 pal., 0 %, claves 5/5): O alguien quiere que pensemos eso. Tráiganme las grabaciones de seguridad del edificio de enfrente.
- `official_style_telegraphic` (12 pal., 20 %, claves 5/5): Quieren que lo pensemos. Traigan grabaciones de seguridad del edificio de enfrente.
- `official_personalization` (9 pal., 40 %, claves 4/5): Tráeme las grabaciones de seguridad del edificio de enfrente.
- `official_personalization_zh` (7 pal., 53 %, claves 3/5): Quiero las grabaciones del edificio de enfrente.
- `final_sys_concise` (15 pal., 0 %, claves 5/5): O alguien quiere que pensemos eso. Tráeme las grabaciones de seguridad del edificio de enfrente.
- `final_concise_fs` (15 pal., 0 %, claves 5/5): O alguien quiere que pensemos eso. Tráeme las grabaciones de seguridad del edificio de enfrente.
- `final_concise_fs_budget` (15 pal., 0 %, claves 5/5): O alguien quiere que pensemos eso. Tráeme las grabaciones de seguridad del edificio de enfrente.
- `two_step` (12 pal., 20 %, claves 4/5): Alguien quiere que pensemos eso. Trae las grabaciones del edificio de enfrente.
- `derived_drop_last_sentence` (6 pal., 60 %, claves 1/5): O alguien quiere que pensemos eso.

### 24 · Okay, she's back. Good work, everyone. Take five, and somebody please get me a coffee.

- `normal` (19 pal., 0 %, claves 4/4): Vale, ella ha vuelto. Buen trabajo, todos. Tomen un descanso, y por favor que alguien me traiga un café.
- `official_style_en` (17 pal., 11 %, claves 4/4): Vale, ya está aquí. Bien hecho todos. Descansen un momento, y que alguien me traiga un café.
- `official_style_es` (16 pal., 16 %, claves 4/4): Vale, ya está aquí. Bien hecho, todos. Descansen un momento; que alguien me traiga un café.
- `official_style_zh` (15 pal., 21 %, claves 4/4): Bien, ya volvió. Bien hecho, todos. Descansen un rato; por favor, alguien tráigame un café.
- `official_style_budget` (16 pal., 16 %, claves 4/4): Ya está de vuelta. Bien hecho, todos. Descansen un poco. Que alguien me traiga un café.
- `official_style_subtitle_en` (22 pal., -16 %, claves 4/4): Vale, ya está de vuelta. Bien hecho todo el mundo. Hagan un descanso, y que alguien me traiga un café, por favor.
- `official_style_subtitle_zh` (20 pal., -5 %, claves 4/4): Bueno, ella está de vuelta. Bien hecho, todos. Den un respiro, y por favor que alguien me traiga un café.
- `official_style_telegraphic` (9 pal., 53 %, claves 3/4): Ella regresó. Buen trabajo. Descansen cinco minutos. Traigan café.
- `official_personalization` (7 pal., 63 %, claves 2/4): Ya está de vuelta. Bien hecho, todos.
- `official_personalization_zh` (5 pal., 74 %, claves 2/4): Ya volvió. Bien hecho, todos.
- `final_sys_concise` (17 pal., 11 %, claves 4/4): Bien, ella ha vuelto. Buen trabajo, todos. Tomen un descanso, y por favor alguien tráigame un café.
- `final_concise_fs` (18 pal., 5 %, claves 4/4): Bien, ya ha vuelto. Buen trabajo, todos. Tomad un descanso; por favor, que alguien me traiga un café.
- `final_concise_fs_budget` (16 pal., 16 %, claves 4/4): Bien, ella ha vuelto. Buen trabajo, todos. Descansen un momento; alguien, por favor, tráigame un café.
- `two_step` (7 pal., 63 %, claves 3/4): Ella ha vuelto. Descansen y tráiganme café.
- `derived_drop_last_sentence` (7 pal., 63 %, claves 2/4): Vale, ella ha vuelto. Buen trabajo, todos.

### 33 · Then I suppose I'd better start earning my keep, because I haven't slept in a real bed since the winter the river froze over and the king lost his crown.

- `normal` (33 pal., 0 %, claves 8/8): Entonces supongo que mejor empiezo a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_en` (25 pal., 24 %, claves 6/8): Mejor empiezo a ganarme la vida; no duermo en una cama de verdad desde que el río se congeló y el rey perdió su corona.
- `official_style_es` (27 pal., 18 %, claves 6/8): Entonces mejor empiezo a ganarme la vida, que no duermo en una cama de verdad desde que el río se congeló y el rey perdió su corona.
- `official_style_zh` (31 pal., 6 %, claves 7/8): Entonces mejor empiezo a ganarme la vida, ya que no duermo en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_budget` (23 pal., 30 %, claves 6/8): Mejor empiezo a ganarme la vida, pues no duermo en cama desde que el río se congeló y el rey perdió su corona.
- `official_style_subtitle_en` (32 pal., 3 %, claves 8/8): Bueno, supongo que mejor empiezo a ganarme la vida, porque no duermo en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_subtitle_zh` (33 pal., 0 %, claves 8/8): Bueno, supongo que mejor empiezo a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_telegraphic` (22 pal., 33 %, claves 7/8): Debo empezar a ganarme la vida; no duermo en cama desde que el río se congeló y el rey perdió su corona.
- `official_personalization` (22 pal., 33 %, claves 7/8): Debo empezar a ganarme la vida; no duermo en cama desde que el río se congeló y el rey perdió su corona.
- `official_personalization_zh` (22 pal., 33 %, claves 7/8): Me toca ganarme la vida, pues no duermo en cama desde que el río se congeló y el rey perdió su corona.
- `final_sys_concise` (33 pal., 0 %, claves 8/8): Entonces supongo que mejor empiezo a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `final_concise_fs` (33 pal., 0 %, claves 8/8): Entonces supongo que mejor empiezo a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `final_concise_fs_budget` (29 pal., 12 %, claves 7/8): Mejor empiezo a ganarme la vida, ya que no duermo en una cama de verdad desde que el río se congeló en invierno y el rey perdió su corona.
- `two_step` (23 pal., 30 %, claves 7/8): Debo empezar a ganarme la vida, pues no duermo en cama desde que el río se congeló y el rey perdió su corona.
- `derived_drop_last_sentence` (33 pal., 0 %, claves 8/8): Entonces supongo que mejor empiezo a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.

### 34 · If you're looking for work, the blacksmith needs a hand. He pays well, but he has a nasty temper.

- `normal` (15 pal., 0 %, claves 5/5): Si estás buscando trabajo, el herrero necesita ayuda. Paga bien, pero tiene un genio terrible.
- `official_style_en` (11 pal., 27 %, claves 5/5): Buscas trabajo? El herrero necesita ayuda. Paga bien, pero es malhumorado.
- `official_style_es` (12 pal., 20 %, claves 5/5): Buscas trabajo: el herrero necesita ayuda. Paga bien, pero es muy malhumorado.
- `official_style_zh` (13 pal., 13 %, claves 5/5): Si busca trabajo, el herrero necesita ayuda. Paga bien, pero es muy malhumorado.
- `official_style_budget` (11 pal., 27 %, claves 5/5): Buscas trabajo? El herrero necesita ayuda. Paga bien, pero es malhumorado.
- `official_style_subtitle_en` (13 pal., 13 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero es muy malhumorado.
- `official_style_subtitle_zh` (15 pal., 0 %, claves 5/5): Si estás buscando trabajo, el herrero necesita ayuda. Paga bien, pero es de mal genio.
- `official_style_telegraphic` (10 pal., 33 %, claves 5/5): Buscan trabajo: herrero necesita ayudante. Paga bien, pero es malhumorado.
- `official_personalization` (9 pal., 40 %, claves 4/5): El herrero necesita ayuda; paga bien pero es malhumorado.
- `official_personalization_zh` (7 pal., 53 %, claves 4/5): Necesitan herrero: bien paga, pero es malhumorado.
- `final_sys_concise` (14 pal., 7 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un mal genio.
- `final_concise_fs` (13 pal., 13 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene mal genio.
- `final_concise_fs_budget` (13 pal., 13 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene mal genio.
- `two_step` (10 pal., 33 %, claves 4/5): El herrero necesita ayudante; paga bien pero es muy malhumorado.
- `derived_drop_last_sentence` (8 pal., 47 %, claves 3/5): Si estás buscando trabajo, el herrero necesita ayuda.

### 42 · Okay, everybody, grab your laptops and follow me. We're working in the parking lot today.

- `normal` (13 pal., 0 %, claves 4/5): Bueno, todos, tomen sus ordenadores portátiles y síganme. Hoy trabajaremos en el estacionamiento.
- `official_style_en` (12 pal., 8 %, claves 5/5): Vamos, todos, cojan sus portátiles y síganme. Hoy trabajamos en el aparcamiento.
- `official_style_es` (12 pal., 8 %, claves 5/5): Vamos, todos: cojan sus portátiles y síganme. Hoy trabajamos en el aparcamiento.
- `official_style_zh` (12 pal., 8 %, claves 4/5): Bueno, todos, tomen sus laptops y síganme. Hoy trabajamos en el estacionamiento.
- `official_style_budget` (12 pal., 8 %, claves 5/5): Vamos, todos, cojan sus portátiles y síganme. Trabajamos en el aparcamiento hoy.
- `official_style_subtitle_en` (12 pal., 8 %, claves 5/5): Vale, todos, coged vuestros portátiles y seguidme. Hoy trabajamos en el aparcamiento.
- `official_style_subtitle_zh` (12 pal., 8 %, claves 4/5): Bueno, todos, tomen sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `official_style_telegraphic` (10 pal., 23 %, claves 4/5): Todos, lleven ordenadores y síganme. Trabajamos hoy en el aparcamiento.
- `official_personalization` (6 pal., 54 %, claves 2/5): Todos, a los ordenadores, al aparcamiento.
- `official_personalization_zh` (8 pal., 38 %, claves 3/5): Todos, ordenadores y fuera. Trabajamos en el aparcamiento.
- `final_sys_concise` (13 pal., 0 %, claves 4/5): Bien, todos, tomen sus ordenadores portátiles y síganme. Hoy trabajaremos en el estacionamiento.
- `final_concise_fs` (13 pal., 0 %, claves 4/5): Bien, todos, tomen sus ordenadores portátiles y síganme. Hoy trabajamos en el estacionamiento.
- `final_concise_fs_budget` (11 pal., 15 %, claves 4/5): Bien, tomen sus laptops y síganme. Trabajamos en el estacionamiento hoy.
- `two_step` (11 pal., 15 %, claves 4/5): Todos, tomen sus laptops y síganme. Trabajaremos en el estacionamiento hoy.
- `derived_drop_last_sentence` (8 pal., 38 %, claves 1/5): Bueno, todos, tomen sus ordenadores portátiles y síganme.

### 43 · Can you pull over at the next gas station? I need a sandwich and a bathroom.

- `normal` (13 pal., 0 %, claves 4/4): ¿Podrías detenerte en la próxima gasolinera? Necesito un sándwich y usar el baño.
- `official_style_en` (12 pal., 8 %, claves 4/4): ¿Puedes parar en la próxima gasolinera? Necesito un sándwich y un baño.
- `official_style_es` (13 pal., 0 %, claves 4/4): ¿Puede detenerse en la próxima gasolinera? Necesito un sándwich y usar el baño.
- `official_style_zh` (13 pal., 0 %, claves 4/4): ¿Puede detenerse en la próxima gasolinera? Necesito un sándwich y usar el baño.
- `official_style_budget` (12 pal., 8 %, claves 4/4): Para, por favor, en la próxima gasolinera. Necesito un sándwich y baño.
- `official_style_subtitle_en` (13 pal., 0 %, claves 4/4): ¿Puedes parar en la próxima gasolinera? Necesito un sándwich y usar el baño.
- `official_style_subtitle_zh` (13 pal., 0 %, claves 4/4): ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y usar el baño.
- `official_style_telegraphic` (8 pal., 38 %, claves 4/4): Parar en próxima gasolinera. Necesito sándwich y baño.
- `official_personalization` (7 pal., 46 %, claves 3/4): Para un sándwich y baño, ¿puede parar?
- `official_personalization_zh` (13 pal., 0 %, claves 4/4): ¿Puede detenerse en la próxima gasolinera? Necesito un sándwich y usar el baño.
- `final_sys_concise` (12 pal., 8 %, claves 4/4): ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `final_concise_fs` (13 pal., 0 %, claves 4/4): ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y usar el baño.
- `final_concise_fs_budget` (12 pal., 8 %, claves 4/4): ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `two_step` (13 pal., 0 %, claves 4/4): Detente en la próxima gasolinera, necesito algo de comer y usar el baño.
- `derived_drop_last_sentence` (6 pal., 54 %, claves 2/4): ¿Podrías detenerte en la próxima gasolinera?

### 49 · Welcome back to Lucky Hour, everybody! Are you ready? Our next contestant is Marcus from Detroit.

- `normal` (16 pal., 0 %, claves 6/6): ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `official_style_en` (15 pal., 6 %, claves 6/6): ¡Bienvenidos de nuevo a Lucky Hour! ¿Están listos? Nuestro próximo concursante es Marcus, de Detroit.
- `official_style_es` (15 pal., 6 %, claves 6/6): ¡Bienvenidos de nuevo a Lucky Hour! ¿Están listos? Nuestro próximo concursante es Marcus, de Detroit.
- `official_style_zh` (15 pal., 6 %, claves 6/6): ¡Bienvenidos de nuevo a Lucky Hour! ¿Están listos? Nuestro próximo concursante es Marcus, de Detroit.
- `official_style_budget` (13 pal., 19 %, claves 5/6): ¡Bienvenidos de nuevo a Lucky Hour! El siguiente concursante es Marcus, de Detroit.
- `official_style_subtitle_en` (17 pal., -6 %, claves 6/6): ¡Bienvenidos de nuevo a Lucky Hour, a todos! ¿Están listos? Nuestro próximo concursante es Marcus, de Detroit.
- `official_style_subtitle_zh` (16 pal., 0 %, claves 6/6): ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo concursante es Marcus, de Detroit.
- `official_style_telegraphic` (11 pal., 31 %, claves 5/6): ¡Bienvenidos de nuevo a Lucky Hour! Próximo concursante: Marcus, de Detroit.
- `official_personalization` (4 pal., 75 %, claves 3/6): ¡Bienvenido, Marcus! ¿Estás listo?
- `official_personalization_zh` (9 pal., 44 %, claves 3/6): ¡Bienvenidos de vuelta! El siguiente es Marcus, de Detroit.
- `final_sys_concise` (16 pal., 0 %, claves 6/6): ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `final_concise_fs` (16 pal., 0 %, claves 6/6): ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `final_concise_fs_budget` (15 pal., 6 %, claves 6/6): ¡Bienvenidos de nuevo a Lucky Hour! ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `two_step` (7 pal., 56 %, claves 4/6): Bienvenidos a Lucky Hour, Marcus de Detroit.
- `derived_drop_last_sentence` (9 pal., 44 %, claves 3/6): ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos?

### 55 · Listen up, all of you. The vault opens at midnight, we grab the diamonds, and we're gone in ninety seconds.

- `normal` (17 pal., 0 %, claves 6/6): Escuchad todos. La bóveda se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `official_style_en` (17 pal., 0 %, claves 5/6): Escuchad todos. La caja se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `official_style_es` (17 pal., 0 %, claves 5/6): Escuchad todos: la caja se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `official_style_zh` (17 pal., 0 %, claves 5/6): Escuchen todos: la caja se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `official_style_budget` (14 pal., 18 %, claves 4/6): A medianoche abre el cofre. Sacamos los diamantes y nos vamos en 90 segundos.
- `official_style_subtitle_en` (17 pal., 0 %, claves 4/6): Oigan todos. La caja se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `official_style_subtitle_zh` (18 pal., -6 %, claves 5/6): ¡Oigan todos! La caja fuerte se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `official_style_telegraphic` (14 pal., 18 %, claves 4/6): A medianoche abre la caja. Tomamos los diamantes y nos vamos en 90 segundos.
- `official_personalization` (14 pal., 18 %, claves 5/6): Abre el bóveda a medianoche, cogemos los diamantes y nos vamos en 90 segundos.
- `official_personalization_zh` (11 pal., 35 %, claves 3/6): A medianoche abrimos el cofre, cogemos los diamantes y nos vamos.
- `final_sys_concise` (17 pal., 0 %, claves 6/6): Escuchen todos. La bóveda se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `final_concise_fs` (17 pal., 0 %, claves 6/6): Escuchen todos: la bóveda se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `final_concise_fs_budget` (17 pal., 0 %, claves 6/6): Escuchen todos: la bóveda se abre a medianoche, tomamos los diamantes y nos vamos en 90 segundos.
- `two_step` (14 pal., 18 %, claves 5/6): A medianoche abrimos la bóveda, tomamos los diamantes y nos vamos en 90 segundos.
- `derived_drop_last_sentence` (2 pal., 88 %, claves 1/6): Escuchad todos.

## Detalle de `official_style_telegraphic` (semilla 42)

| Nº | Inglés | Normal | Conciso | Palabras (normal → conciso) | Caracteres (normal → conciso) | Total, ms (normal → conciso) | Elementos clave | Sentido (valoración manual) |
|---:|:---|:---|:---|---:|---:|---:|---:|:---|
| 1 | Did you seriously finish the orange juice and put the empty carton back in the fridge? | ¿De verdad terminaste el jugo de naranja y volviste a poner la lata vacía en el refrigerador? | Acabó el jugo de naranja y guardó la lata vacía en el frigorífico. | 17 → 13 (-24 %) | 93 → 66 (-29 %) | 438 → 291 | 2/3 (falta: cartón/envase vacío) | **parcial** — pasa de pregunta en 2.ª persona a afirmación en 3.ª: pierde «¿De verdad…?» |
| 9 | They found fibers under the victim's fingernails and a sneaker print by the window. None of it matches anything in her apartment. | Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla deportiva junto a la ventana. Nada de eso coincide con nada en su apartamento. | Hallaron fibras bajo uñas víctima y huella zapatilla cerca ventana. Ninguna coincide con objetos apartamento. | 28 → 15 (-46 %) | 156 → 109 (-30 %) | 576 → 298 | 6/6 | **sí** — telegráfico (sin artículos ni preposiciones) pero con los 6 elementos |
| 11 | Or someone wants us to think so. Get me the security footage from the building across the street. | O alguien quiere que pensemos eso. Tráeme las grabaciones de seguridad del edificio de enfrente. | Quieren que lo pensemos. Traigan grabaciones de seguridad del edificio de enfrente. | 15 → 12 (-20 %) | 96 → 83 (-14 %) | 437 → 233 | 5/5 | **sí** — «Quieren…» en plural en vez de «alguien»; conserva la orden |
| 24 | Okay, she's back. Good work, everyone. Take five, and somebody please get me a coffee. | Vale, ella ha vuelto. Buen trabajo, todos. Tomen un descanso, y por favor que alguien me traiga un café. | Ella regresó. Buen trabajo. Descansen cinco minutos. Traigan café. | 19 → 9 (-53 %) | 104 → 66 (-37 %) | 498 → 213 | 3/4 (falta: ha vuelto) | **sí** — conserva los 4 elementos |
| 33 | Then I suppose I'd better start earning my keep, because I haven't slept in a real bed since the winter the river froze over and the king lost his crown. | Entonces supongo que mejor empiezo a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona. | Debo empezar a ganarme la vida; no duermo en cama desde que el río se congeló y el rey perdió su corona. | 33 → 22 (-33 %) | 166 → 104 (-37 %) | 674 → 387 | 7/8 (falta: invierno) | **sí** — pierde «invierno» y «de verdad» |
| 34 | If you're looking for work, the blacksmith needs a hand. He pays well, but he has a nasty temper. | Si estás buscando trabajo, el herrero necesita ayuda. Paga bien, pero tiene un genio terrible. | Buscan trabajo: herrero necesita ayudante. Paga bien, pero es malhumorado. | 15 → 10 (-33 %) | 94 → 74 (-21 %) | 443 → 243 | 5/5 | **sí** — «Buscan trabajo» (persona cambiada); mismo sentido |
| 42 | Okay, everybody, grab your laptops and follow me. We're working in the parking lot today. | Bueno, todos, tomen sus ordenadores portátiles y síganme. Hoy trabajaremos en el estacionamiento. | Todos, lleven ordenadores y síganme. Trabajamos hoy en el aparcamiento. | 13 → 10 (-23 %) | 97 → 71 (-27 %) | 474 → 248 | 4/5 (falta: seguir) | **sí** — conserva la orden, el destino y el «hoy» |
| 43 | Can you pull over at the next gas station? I need a sandwich and a bathroom. | ¿Podrías detenerte en la próxima gasolinera? Necesito un sándwich y usar el baño. | Parar en próxima gasolinera. Necesito sándwich y baño. | 13 → 8 (-38 %) | 81 → 54 (-33 %) | 424 → 222 | 4/4 | **sí** — infinitivo («Parar…»); conserva los 4 elementos |
| 49 | Welcome back to Lucky Hour, everybody! Are you ready? Our next contestant is Marcus from Detroit. | ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo concursante es Marcus de Detroit. | ¡Bienvenidos de nuevo a Lucky Hour! Próximo concursante: Marcus, de Detroit. | 16 → 11 (-31 %) | 107 → 76 (-29 %) | 445 → 241 | 5/6 (falta: listos) | **sí** — pierde «¿Están listos?» |
| 55 | Listen up, all of you. The vault opens at midnight, we grab the diamonds, and we're gone in ninety seconds. | Escuchad todos. La bóveda se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos. | A medianoche abre la caja. Tomamos los diamantes y nos vamos en 90 segundos. | 17 → 14 (-18 %) | 102 → 76 (-25 %) | 454 → 270 | 4/6 (falta: escuchad, cámara acorazada) | **parcial** — «la caja» por la bóveda y pierde «Escuchad todos» |

Sentido (manual): 8 «sí», 2 «parcial», 0 «no», 0 sin reducción que valorar, de 10 frases.

## Detalle de `official_personalization` (semilla 42)

| Nº | Inglés | Normal | Conciso | Palabras (normal → conciso) | Caracteres (normal → conciso) | Total, ms (normal → conciso) | Elementos clave | Sentido (valoración manual) |
|---:|:---|:---|:---|---:|---:|---:|---:|:---|
| 1 | Did you seriously finish the orange juice and put the empty carton back in the fridge? | ¿De verdad terminaste el jugo de naranja y volviste a poner la lata vacía en el refrigerador? | ¿De verdad terminaste el zumo y lo guardaste? | 17 → 8 (-53 %) | 93 → 45 (-52 %) | 438 → 175 | 1/3 (falta: cartón/envase vacío, nevera) | **parcial** — pierde «vacío» y la nevera |
| 9 | They found fibers under the victim's fingernails and a sneaker print by the window. None of it matches anything in her apartment. | Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla deportiva junto a la ventana. Nada de eso coincide con nada en su apartamento. | Encontraron fibras bajo sus uñas y huellas de zapatilla cerca de la ventana; nada corresponde a su apartamento. | 28 → 18 (-36 %) | 156 → 111 (-29 %) | 576 → 323 | 5/6 (falta: nada coincide) | **sí** — «nada corresponde a su apartamento» |
| 11 | Or someone wants us to think so. Get me the security footage from the building across the street. | O alguien quiere que pensemos eso. Tráeme las grabaciones de seguridad del edificio de enfrente. | Tráeme las grabaciones de seguridad del edificio de enfrente. | 15 → 9 (-40 %) | 96 → 61 (-36 %) | 437 → 198 | 4/5 (falta: alguien quiere que lo creamos) | **parcial** — pierde la primera frase (alguien quiere que lo creamos) |
| 24 | Okay, she's back. Good work, everyone. Take five, and somebody please get me a coffee. | Vale, ella ha vuelto. Buen trabajo, todos. Tomen un descanso, y por favor que alguien me traiga un café. | Ya está de vuelta. Bien hecho, todos. | 19 → 7 (-63 %) | 104 → 37 (-64 %) | 498 → 144 | 2/4 (falta: cinco minutos, café) | **parcial** — pierde el descanso y el café |
| 33 | Then I suppose I'd better start earning my keep, because I haven't slept in a real bed since the winter the river froze over and the king lost his crown. | Entonces supongo que mejor empiezo a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona. | Debo empezar a ganarme la vida; no duermo en cama desde que el río se congeló y el rey perdió su corona. | 33 → 22 (-33 %) | 166 → 104 (-37 %) | 674 → 387 | 7/8 (falta: invierno) | **sí** — pierde «invierno» |
| 34 | If you're looking for work, the blacksmith needs a hand. He pays well, but he has a nasty temper. | Si estás buscando trabajo, el herrero necesita ayuda. Paga bien, pero tiene un genio terrible. | El herrero necesita ayuda; paga bien pero es malhumorado. | 15 → 9 (-40 %) | 94 → 57 (-39 %) | 443 → 200 | 4/5 (falta: trabajo) | **sí** — conserva trabajo, herrero, sueldo y carácter |
| 42 | Okay, everybody, grab your laptops and follow me. We're working in the parking lot today. | Bueno, todos, tomen sus ordenadores portátiles y síganme. Hoy trabajaremos en el estacionamiento. | Todos, a los ordenadores, al aparcamiento. | 13 → 6 (-54 %) | 97 → 42 (-57 %) | 474 → 175 | 2/5 (falta: seguir, hoy, trabajar) | **no** — «Todos, a los ordenadores, al aparcamiento»: pierde «seguidme» y cambia el sentido |
| 43 | Can you pull over at the next gas station? I need a sandwich and a bathroom. | ¿Podrías detenerte en la próxima gasolinera? Necesito un sándwich y usar el baño. | Para un sándwich y baño, ¿puede parar? | 13 → 7 (-46 %) | 81 → 38 (-53 %) | 424 → 195 | 3/4 (falta: gasolinera) | **no** — «Para un sándwich y baño, ¿puede parar?»: pierde la gasolinera y pasa a «usted» |
| 49 | Welcome back to Lucky Hour, everybody! Are you ready? Our next contestant is Marcus from Detroit. | ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo concursante es Marcus de Detroit. | ¡Bienvenido, Marcus! ¿Estás listo? | 16 → 4 (-75 %) | 107 → 34 (-68 %) | 445 → 172 | 3/6 (falta: Lucky Hour, concursante, Detroit) | **no** — «¡Bienvenido, Marcus! ¿Estás listo?»: cambia el sentido y pierde Lucky Hour y Detroit |
| 55 | Listen up, all of you. The vault opens at midnight, we grab the diamonds, and we're gone in ninety seconds. | Escuchad todos. La bóveda se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos. | Abre el bóveda a medianoche, cogemos los diamantes y nos vamos en 90 segundos. | 17 → 14 (-18 %) | 102 → 78 (-24 %) | 454 → 293 | 5/6 (falta: escuchad) | **sí** — «Abre el bóveda» (género mal); conserva el plan |

Sentido (manual): 4 «sí», 3 «parcial», 3 «no», 0 sin reducción que valorar, de 10 frases.

## Detalle de `derived_drop_last_sentence` (semilla 42)

| Nº | Inglés | Normal | Conciso | Palabras (normal → conciso) | Caracteres (normal → conciso) | Total, ms (normal → conciso) | Elementos clave | Sentido (valoración manual) |
|---:|:---|:---|:---|---:|---:|---:|---:|:---|
| 1 | Did you seriously finish the orange juice and put the empty carton back in the fridge? | ¿De verdad terminaste el jugo de naranja y volviste a poner la lata vacía en el refrigerador? | ¿De verdad terminaste el jugo de naranja y volviste a poner la lata vacía en el refrigerador? | 17 → 17 (0 %) | 93 → 93 (0 %) | 438 → — | 2/3 (falta: cartón/envase vacío) | **n/a** — una sola oración: no hay nada que quitar |
| 9 | They found fibers under the victim's fingernails and a sneaker print by the window. None of it matches anything in her apartment. | Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla deportiva junto a la ventana. Nada de eso coincide con nada en su apartamento. | Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla deportiva junto a la ventana. | 28 → 19 (-32 %) | 156 → 107 (-31 %) | 576 → — | 4/6 (falta: nada coincide, piso) | **parcial** — pierde la conclusión («nada coincide con su piso») |
| 11 | Or someone wants us to think so. Get me the security footage from the building across the street. | O alguien quiere que pensemos eso. Tráeme las grabaciones de seguridad del edificio de enfrente. | O alguien quiere que pensemos eso. | 15 → 6 (-60 %) | 96 → 34 (-65 %) | 437 → — | 1/5 (falta: imágenes de seguridad, seguridad, edificio, de enfrente) | **no** — pierde la orden (conseguir las grabaciones), que es lo accionable |
| 24 | Okay, she's back. Good work, everyone. Take five, and somebody please get me a coffee. | Vale, ella ha vuelto. Buen trabajo, todos. Tomen un descanso, y por favor que alguien me traiga un café. | Vale, ella ha vuelto. Buen trabajo, todos. | 19 → 7 (-63 %) | 104 → 42 (-60 %) | 498 → — | 2/4 (falta: cinco minutos, café) | **parcial** — pierde el descanso y el café, secundarios |
| 33 | Then I suppose I'd better start earning my keep, because I haven't slept in a real bed since the winter the river froze over and the king lost his crown. | Entonces supongo que mejor empiezo a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona. | Entonces supongo que mejor empiezo a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona. | 33 → 33 (0 %) | 166 → 166 (0 %) | 674 → — | 8/8 | **n/a** — una sola oración: no hay nada que quitar |
| 34 | If you're looking for work, the blacksmith needs a hand. He pays well, but he has a nasty temper. | Si estás buscando trabajo, el herrero necesita ayuda. Paga bien, pero tiene un genio terrible. | Si estás buscando trabajo, el herrero necesita ayuda. | 15 → 8 (-47 %) | 94 → 53 (-44 %) | 443 → — | 3/5 (falta: paga bien, mal carácter) | **parcial** — pierde el sueldo y el mal carácter |
| 42 | Okay, everybody, grab your laptops and follow me. We're working in the parking lot today. | Bueno, todos, tomen sus ordenadores portátiles y síganme. Hoy trabajaremos en el estacionamiento. | Bueno, todos, tomen sus ordenadores portátiles y síganme. | 13 → 8 (-38 %) | 97 → 57 (-41 %) | 474 → — | 1/5 (falta: seguir, aparcamiento, hoy, trabajar) | **parcial** — pierde el destino (el aparcamiento) |
| 43 | Can you pull over at the next gas station? I need a sandwich and a bathroom. | ¿Podrías detenerte en la próxima gasolinera? Necesito un sándwich y usar el baño. | ¿Podrías detenerte en la próxima gasolinera? | 13 → 6 (-54 %) | 81 → 44 (-46 %) | 424 → — | 2/4 (falta: bocadillo, baño) | **parcial** — pierde el motivo (el bocadillo y el baño) |
| 49 | Welcome back to Lucky Hour, everybody! Are you ready? Our next contestant is Marcus from Detroit. | ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo concursante es Marcus de Detroit. | ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? | 16 → 9 (-44 %) | 107 → 57 (-47 %) | 445 → — | 3/6 (falta: concursante, Marcus, Detroit) | **no** — pierde quién concursa (Marcus de Detroit) |
| 55 | Listen up, all of you. The vault opens at midnight, we grab the diamonds, and we're gone in ninety seconds. | Escuchad todos. La bóveda se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos. | Escuchad todos. | 17 → 2 (-88 %) | 102 → 15 (-85 %) | 454 → — | 1/6 (falta: cámara acorazada, medianoche, diamantes, noventa segundos, nos vamos) | **no** — queda solo «Escuchad»: pierde todo el plan |

Sentido (manual): 0 «sí», 5 «parcial», 3 «no», 2 sin reducción que valorar, de 10 frases.

