# Modo resumen: traducción concisa con Hy-MT2 (generado por concise.py)

Modelo: `Hy-MT2-1.8B-Q8_0.gguf`.

Diez frases largas del corpus (≥ 15 palabras: líneas 1, 9, 11, 24, 33, 34, 42, 43, 49, 55), 3 semillas (42, 43, 44) por variante = 30 traducciones por variante. La reducción se calcula contra la traducción normal (prompt final) de la misma frase y la misma semilla.

## Resumen por variante

| Variante | Palabras de media | Reducción de palabras: mediana / media | Reducción de caracteres: mediana | Frases con ≥ 25 % menos | Frases sin acortar | Elementos clave conservados | Salidas que no son traducción | Total p50, ms | 1.er token p50, ms | Tokens generados (media) |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `normal` | 18,5 | 0 % / 0 % | 0 % | 0% | 100% | 93% | 0 | 222 | 74 | 34,7 |
| `official_style_en` | 18,6 | 0 % / 0 % | 1 % | 0% | 70% | 91% | 0 | 186 | 38 | 34,2 |
| `official_style_es` | 18,7 | 0 % / -1 % | 0 % | 0% | 80% | 95% | 0 | 184 | 35 | 34,1 |
| `official_style_zh` | 18,4 | 0 % / 1 % | 0 % | 0% | 67% | 89% | 0 | 179 | 35 | 34,0 |
| `official_style_budget` | 18,4 | 0 % / 1 % | 0 % | 0% | 70% | 91% | 0 | 183 | 36 | 33,9 |
| `official_style_subtitle_en` | 18,4 | 0 % / 1 % | 1 % | 0% | 63% | 92% | 0 | 183 | 38 | 34,2 |
| `official_style_subtitle_zh` | 18,6 | 0 % / 0 % | 1 % | 0% | 67% | 90% | 0 | 177 | 36 | 34,1 |
| `official_style_telegraphic` | 18,5 | 0 % / 0 % | 1 % | 0% | 70% | 91% | 0 | 185 | 36 | 34,0 |
| `official_personalization` | 18,6 | 0 % / -1 % | 0 % | 0% | 73% | 91% | 5 | 192 | 43 | 34,7 |
| `official_personalization_zh` | 17,8 | 0 % / 3 % | 3 % | 0% | 53% | 90% | 0 | 180 | 41 | 33,2 |
| `final_sys_concise` | 18,4 | 0 % / 0 % | 0 % | 0% | 93% | 93% | 0 | 225 | 74 | 34,6 |
| `final_concise_fs` | 18,5 | 0 % / 0 % | 0 % | 0% | 87% | 91% | 0 | 212 | 67 | 34,2 |
| `final_concise_fs_budget` | 18,2 | 0 % / 1 % | 0 % | 0% | 63% | 90% | 0 | 212 | 68 | 33,7 |
| `two_step` | 18,2 | 0 % / 1 % | 0 % | 0% | 80% | 72% | 6 | 396 | 262 | 31,5 |
| `derived_drop_last_sentence` | 11,3 | 47 % / 42 % | 45 % | 80% | 20% | 52% | 0 | — | — | — |

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

- `normal` (17 pal., 0 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?
- `official_style_en` (14 pal., 18 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `official_style_es` (14 pal., 18 %, claves 3/3): ¿De verdad terminaste el jugo de naranja y devolviste el cartón vacío al refrigerador?
- `official_style_zh` (14 pal., 18 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `official_style_budget` (14 pal., 18 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `official_style_subtitle_en` (14 pal., 18 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `official_style_subtitle_zh` (14 pal., 18 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `official_style_telegraphic` (14 pal., 18 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y devolviste la caja vacía al refrigerador?
- `official_personalization` (14 pal., 18 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `official_personalization_zh` (14 pal., 18 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `final_sys_concise` (17 pal., 0 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?
- `final_concise_fs` (17 pal., 0 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?
- `final_concise_fs_budget` (14 pal., 18 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador?
- `two_step` (17 pal., 0 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?
- `derived_drop_last_sentence` (17 pal., 0 %, claves 2/3): ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador?

### 9 · They found fibers under the victim's fingernails and a sneaker print by the window. None of it matches anything in her apartment.

- `normal` (28 pal., 0 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con nada que haya en su apartamento.
- `official_style_en` (27 pal., 4 %, claves 5/6): Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla junto a la ventana. Nada de eso coincide con algo en su apartamento.
- `official_style_es` (26 pal., 7 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla junto a la ventana. Nada de eso coincide con nada en su apartamento.
- `official_style_zh` (26 pal., 7 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla junto a la ventana. Nada de eso coincide con algo en su apartamento.
- `official_style_budget` (26 pal., 7 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla junto a la ventana. Nada de eso coincide con algo en su apartamento.
- `official_style_subtitle_en` (27 pal., 4 %, claves 5/6): Encontraron fibras debajo de las uñas de la víctima y una huella de zapatilla junto a la ventana. Nada de esto coincide con algo en su apartamento.
- `official_style_subtitle_zh` (26 pal., 7 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una marca de zapatillas junto a la ventana. Nada de eso coincide con algo en su apartamento.
- `official_style_telegraphic` (26 pal., 7 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una huella de zapatilla junto a la ventana. Nada de eso coincide con algo en su apartamento.
- `official_personalization` (26 pal., 7 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una huella de zapatilla junto a la ventana. Nada de esto coincide con nada en su apartamento.
- `official_personalization_zh` (26 pal., 7 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una huella de zapatilla junto a la ventana. Nada de esto coincide con algo en su apartamento.
- `final_sys_concise` (28 pal., 0 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con algo que hubiera en su apartamento.
- `final_concise_fs` (28 pal., 0 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con nada que haya en su apartamento.
- `final_concise_fs_budget` (28 pal., 0 %, claves 5/6): Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de esto coincide con algo que hubiera en su apartamento.
- `two_step` (22 pal., 21 %, claves 0/6): They found fibers under the victim’s nails and a shoe mark near the window. None of this matches anything in his apartment.
- `derived_drop_last_sentence` (17 pal., 39 %, claves 4/6): Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana.

### 11 · Or someone wants us to think so. Get me the security footage from the building across the street.

- `normal` (16 pal., 0 %, claves 5/5): O alguien quiere que lo creamos así. Denme las grabaciones de seguridad del edificio de enfrente.
- `official_style_en` (19 pal., -19 %, claves 5/5): O alguien quiere que pensemos así. Denme las grabaciones de seguridad del edificio al otro lado de la calle.
- `official_style_es` (20 pal., -25 %, claves 5/5): O alguien quiere que lo pensemos así. Consíganos las grabaciones de seguridad del edificio al otro lado de la calle.
- `official_style_zh` (18 pal., -12 %, claves 5/5): Alguien quiere que pensemos así. Consíganme las grabaciones de seguridad del edificio al otro lado de la calle.
- `official_style_budget` (19 pal., -19 %, claves 5/5): O alguien quiere que pensemos así. Obtén las grabaciones de seguridad del edificio al otro lado de la calle.
- `official_style_subtitle_en` (20 pal., -25 %, claves 5/5): O alguien quiere que lo pensemos así. Denme las grabaciones de seguridad del edificio al otro lado de la calle.
- `official_style_subtitle_zh` (19 pal., -19 %, claves 5/5): O alguien quiere que pensemos así. Envíenme las imágenes de seguridad del edificio al otro lado de la calle.
- `official_style_telegraphic` (20 pal., -25 %, claves 5/5): O alguien quiere que lo pensemos así. Denme las grabaciones de seguridad del edificio al otro lado de la calle.
- `official_personalization` (24 pal., -50 %, claves 5/5): [Texto de origen]  
O tal vez alguien quiere que piense así. Consíganme las grabaciones de seguridad del edificio al otro lado de la calle.
- `official_personalization_zh` (20 pal., -25 %, claves 5/5): O alguien quiere que lo pensemos así. Consíganme las grabaciones de seguridad del edificio al otro lado de la calle.
- `final_sys_concise` (15 pal., 6 %, claves 5/5): O alguien quiere que pensemos así. Denme las grabaciones de seguridad del edificio de enfrente.
- `final_concise_fs` (17 pal., -6 %, claves 5/5): O alguien quiere que pensemos así. Por favor, obtenga las grabaciones de seguridad del edificio de enfrente.
- `final_concise_fs_budget` (21 pal., -31 %, claves 5/5): O alguien quiere que pensemos así. Por favor, obtenga las grabaciones de seguridad del edificio al otro lado de la calle.
- `two_step` (18 pal., -12 %, claves 0/5): Or someone wants us to believe that. Give me the security recordings from the building across the street.
- `derived_drop_last_sentence` (7 pal., 56 %, claves 1/5): O alguien quiere que lo creamos así.

### 24 · Okay, she's back. Good work, everyone. Take five, and somebody please get me a coffee.

- `normal` (18 pal., 0 %, claves 4/4): Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí.
- `official_style_en` (18 pal., 0 %, claves 4/4): Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí.
- `official_style_es` (18 pal., 0 %, claves 4/4): Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y que alguien me traiga un café, por favor.
- `official_style_zh` (18 pal., 0 %, claves 4/4): Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí.
- `official_style_budget` (18 pal., 0 %, claves 4/4): Bien, ha vuelto. Bien hecho, todos. Descansen un momento, y que alguien me traiga un café, por favor.
- `official_style_subtitle_en` (16 pal., 11 %, claves 4/4): Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor tráigame un café.
- `official_style_subtitle_zh` (18 pal., 0 %, claves 4/4): Okey, ha vuelto. Bien hecho, todos. Descansen un momento, y alguien por favor traiga un café para mí.
- `official_style_telegraphic` (18 pal., 0 %, claves 4/4): Bien, ha vuelto. Bien hecho, todos. Descansen un momento, y que alguien me traiga un café, por favor.
- `official_personalization` (19 pal., -6 %, claves 4/4): [Texto de origen]  
Bueno, ha vuelto. Bien hecho, todos. Descanse un momento, y que alguien me traiga un café.
- `official_personalization_zh` (16 pal., 11 %, claves 3/4): Bien, ha regresado. Bien hecho, todos. Descanse un momento, y alguien traiga un café para mí.
- `final_sys_concise` (18 pal., 0 %, claves 4/4): Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí.
- `final_concise_fs` (18 pal., 0 %, claves 4/4): Bien, ha vuelto. Bien hecho, todos. Descansen un momento, y alguien, por favor, traiga un café para mí.
- `final_concise_fs_budget` (14 pal., 22 %, claves 4/4): Bien, ha vuelto. Bien hecho, todos. Descanse un momento y alguien llévenme un café.
- `two_step` (17 pal., 6 %, claves 4/4): He vuelto. Bien hecho, todos. Descansa un momento, y por favor, que alguien me traiga un café.
- `derived_drop_last_sentence` (6 pal., 67 %, claves 2/4): Bien, ha vuelto. Bien hecho, todos.

### 33 · Then I suppose I'd better start earning my keep, because I haven't slept in a real bed since the winter the river froze over and the king lost his crown.

- `normal` (32 pal., 0 %, claves 8/8): Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_en` (34 pal., -6 %, claves 8/8): Entonces supongo que sería mejor empezar a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_es` (34 pal., -6 %, claves 8/8): Entonces supongo que sería mejor empezar a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_zh` (35 pal., -9 %, claves 8/8): Entonces supongo que sería mejor que comenzara a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_budget` (34 pal., -6 %, claves 8/8): Entonces supongo que sería mejor que comenzara a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_subtitle_en` (35 pal., -9 %, claves 8/8): Entonces supongo que sería mejor que comenzara a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_subtitle_zh` (35 pal., -9 %, claves 8/8): Entonces supongo que sería mejor que comenzara a ganarme la vida, porque no he dormido en una cama de verdad desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_style_telegraphic` (34 pal., -6 %, claves 8/8): Entonces supongo que sería mejor que comenzara a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_personalization` (32 pal., 0 %, claves 8/8): Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `official_personalization_zh` (32 pal., 0 %, claves 8/8): Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `final_sys_concise` (32 pal., 0 %, claves 8/8): Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `final_concise_fs` (32 pal., 0 %, claves 8/8): Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `final_concise_fs_budget` (32 pal., 0 %, claves 8/8): Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `two_step` (32 pal., 0 %, claves 8/8): Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.
- `derived_drop_last_sentence` (32 pal., 0 %, claves 8/8): Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona.

### 34 · If you're looking for work, the blacksmith needs a hand. He pays well, but he has a nasty temper.

- `normal` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento terrible.
- `official_style_en` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un temperamento violento.
- `official_style_es` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un mal carácter.
- `official_style_zh` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento terrible.
- `official_style_budget` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un temperamento desagradable.
- `official_style_subtitle_en` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un mal carácter.
- `official_style_subtitle_zh` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un mal carácter.
- `official_style_telegraphic` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un mal carácter.
- `official_personalization` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un temperamento terrible.
- `official_personalization_zh` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un temperamento violento.
- `final_sys_concise` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento horrible.
- `final_concise_fs` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento horrible.
- `final_concise_fs_budget` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un temperamento violento.
- `two_step` (14 pal., 0 %, claves 5/5): Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento terrible.
- `derived_drop_last_sentence` (7 pal., 50 %, claves 3/5): Si buscas trabajo, el herrero necesita ayuda.

### 42 · Okay, everybody, grab your laptops and follow me. We're working in the parking lot today.

- `normal` (14 pal., 0 %, claves 5/5): De acuerdo, todos, coged vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento.
- `official_style_en` (12 pal., 14 %, claves 4/5): Bien, todos, agarren sus portátiles y síganme. Hoy trabajaremos en el estacionamiento.
- `official_style_es` (13 pal., 7 %, claves 4/5): Bien, todos, guarden sus laptops y síganme. Hoy estamos trabajando en el estacionamiento.
- `official_style_zh` (12 pal., 14 %, claves 4/5): Bien, todos, tomen sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `official_style_budget` (12 pal., 14 %, claves 4/5): Bien, todos, tomen sus portátiles y síganme. Hoy trabajaremos en el estacionamiento.
- `official_style_subtitle_en` (12 pal., 14 %, claves 4/5): Bien, todos, tomen sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `official_style_subtitle_zh` (13 pal., 7 %, claves 4/5): Por favor, todos, guarden sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `official_style_telegraphic` (12 pal., 14 %, claves 4/5): Bien, todos, agarren sus portátiles y síganme. Hoy trabajaremos en el estacionamiento.
- `official_personalization` (15 pal., -7 %, claves 4/5): [Texto de origen]  
Bien, todos, tomen sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `official_personalization_zh` (12 pal., 14 %, claves 4/5): Bien, todos, tomen sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `final_sys_concise` (14 pal., 0 %, claves 5/5): De acuerdo, todos, coged vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento.
- `final_concise_fs` (12 pal., 14 %, claves 4/5): Bien, todos, guarden sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `final_concise_fs_budget` (13 pal., 7 %, claves 4/5): Está bien, todos, guarden sus laptops y síganme. Hoy trabajaremos en el estacionamiento.
- `two_step` (14 pal., 0 %, claves 5/5): De acuerdo, todos, coged vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento.
- `derived_drop_last_sentence` (9 pal., 36 %, claves 2/5): De acuerdo, todos, coged vuestros ordenadores portátiles y seguidme.

### 43 · Can you pull over at the next gas station? I need a sandwich and a bathroom.

- `normal` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `official_style_en` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `official_style_es` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `official_style_zh` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `official_style_budget` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `official_style_subtitle_en` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `official_style_subtitle_zh` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `official_style_telegraphic` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `official_personalization` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `official_personalization_zh` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `final_sys_concise` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño.
- `final_concise_fs` (14 pal., -17 %, claves 4/4): ¿Puedes detenerte en la próxima estación de servicio? Necesito un sándwich y un baño.
- `final_concise_fs_budget` (14 pal., -17 %, claves 4/4): ¿Puedes detenerte en la próxima estación de servicio? Necesito un sándwich y un baño.
- `two_step` (12 pal., 0 %, claves 4/4): ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño.
- `derived_drop_last_sentence` (6 pal., 50 %, claves 2/4): ¿Puedes detenerte en la próxima gasolinera?

### 49 · Welcome back to Lucky Hour, everybody! Are you ready? Our next contestant is Marcus from Detroit.

- `normal` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `official_style_en` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `official_style_es` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `official_style_zh` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `official_style_budget` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `official_style_subtitle_en` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `official_style_subtitle_zh` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `official_style_telegraphic` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `official_personalization` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `official_personalization_zh` (16 pal., 0 %, claves 6/6): ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo participante es Marcus de Detroit.
- `final_sys_concise` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `final_concise_fs` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `final_concise_fs_budget` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `two_step` (16 pal., 0 %, claves 6/6): Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit.
- `derived_drop_last_sentence` (9 pal., 44 %, claves 3/6): Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos?

### 55 · Listen up, all of you. The vault opens at midnight, we grab the diamonds, and we're gone in ninety seconds.

- `normal` (19 pal., 0 %, claves 5/6): Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `official_style_en` (19 pal., 0 %, claves 5/6): Escuchen bien, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `official_style_es` (19 pal., 0 %, claves 5/6): Escuchen bien, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `official_style_zh` (19 pal., 0 %, claves 5/6): Escuchen bien, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `official_style_budget` (19 pal., 0 %, claves 5/6): Escuchen bien, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `official_style_subtitle_en` (18 pal., 5 %, claves 4/6): Atentos, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `official_style_subtitle_zh` (18 pal., 5 %, claves 4/6): Atentos, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `official_style_telegraphic` (19 pal., 0 %, claves 5/6): Escuchen bien, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `official_personalization` (19 pal., 0 %, claves 5/6): Escuchen bien, todos ustedes. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `official_personalization_zh` (17 pal., 11 %, claves 5/6): Escuchen todos. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `final_sys_concise` (19 pal., 0 %, claves 5/6): Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `final_concise_fs` (17 pal., 11 %, claves 5/6): Escuchen bien: el cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `final_concise_fs_budget` (17 pal., 11 %, claves 5/6): Escuchen bien: el cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos.
- `two_step` (19 pal., 0 %, claves 5/6): Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos.
- `derived_drop_last_sentence` (4 pal., 79 %, claves 1/6): Escuchad bien, todos vosotros.

## Detalle de `official_personalization_zh` (semilla 42)

| Nº | Inglés | Normal | Conciso | Palabras (normal → conciso) | Caracteres (normal → conciso) | Total, ms (normal → conciso) | Elementos clave | Sentido (valoración manual) |
|---:|:---|:---|:---|---:|---:|---:|---:|:---|
| 1 | Did you seriously finish the orange juice and put the empty carton back in the fridge? | ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador? | ¿De verdad terminaste el jugo de naranja y volviste la caja vacía al refrigerador? | 17 → 14 (-18 %) | 93 → 82 (-12 %) | 221 → 161 | 2/3 (falta: cartón/envase vacío) | **sí** — quita «volviste a poner»: -18 %, mismo sentido |
| 9 | They found fibers under the victim's fingernails and a sneaker print by the window. None of it matches anything in her apartment. | Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con nada que haya en su apartamento. | Encontraron fibras debajo de las uñas del victimario y una huella de zapatilla junto a la ventana. Nada de esto coincide con algo en su apartamento. | 28 → 26 (-7 %) | 156 → 148 (-5 %) | 268 → 221 | 5/6 (falta: nada coincide) | **sí** — casi igual (-7 %); mantiene el error de «victimario» |
| 11 | Or someone wants us to think so. Get me the security footage from the building across the street. | O alguien quiere que lo creamos así. Denme las grabaciones de seguridad del edificio de enfrente. | O alguien quiere que lo pensemos así. Consíganme las grabaciones de seguridad del edificio al otro lado de la calle. | 16 → 20 (25 %) | 97 → 116 (20 %) | 221 → 213 | 5/5 | **sí** — más larga que la normal (+25 %) |
| 24 | Okay, she's back. Good work, everyone. Take five, and somebody please get me a coffee. | Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí. | Bien, ha regresado. Bien hecho, todos. Descanse un momento, y alguien traiga un café para mí. | 18 → 16 (-11 %) | 100 → 93 (-7 %) | 232 → 165 | 3/4 (falta: ha vuelto) | **sí** — «ha regresado»…, -11 % |
| 33 | Then I suppose I'd better start earning my keep, because I haven't slept in a real bed since the winter the river froze over and the king lost his crown. | Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona. | Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona. | 32 → 32 (0 %) | 163 → 163 (0 %) | 314 → 263 | 8/8 | **n/a** — idéntica a la normal |
| 34 | If you're looking for work, the blacksmith needs a hand. He pays well, but he has a nasty temper. | Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento terrible. | Si buscas trabajo, el herrero necesita ayuda. Paga bien, pero tiene un temperamento violento. | 14 → 14 (0 %) | 95 → 93 (-2 %) | 194 → 158 | 5/5 | **n/a** — idéntica salvo «violento» por «terrible» |
| 42 | Okay, everybody, grab your laptops and follow me. We're working in the parking lot today. | De acuerdo, todos, coged vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento. | Bien, todos, tomen sus laptops y síganme. Hoy trabajaremos en el estacionamiento. | 14 → 12 (-14 %) | 108 → 81 (-25 %) | 252 → 163 | 4/5 (falta: seguir) | **sí** — -14 %, pero pasa a «tomen sus laptops» (peor castellano) |
| 43 | Can you pull over at the next gas station? I need a sandwich and a bathroom. | ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño. | ¿Puedes detenerte en la siguiente gasolinera? Necesito un sándwich y un baño. | 12 → 12 (0 %) | 75 → 77 (3 %) | 198 → 155 | 4/4 | **n/a** — idéntica salvo «siguiente» por «próxima» |
| 49 | Welcome back to Lucky Hour, everybody! Are you ready? Our next contestant is Marcus from Detroit. | Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit. | ¡Bienvenidos de nuevo a Lucky Hour, todos! ¿Están listos? Nuestro próximo participante es Marcus de Detroit. | 16 → 16 (0 %) | 106 → 108 (2 %) | 222 → 180 | 6/6 | **n/a** — idéntica salvo signos de exclamación |
| 55 | Listen up, all of you. The vault opens at midnight, we grab the diamonds, and we're gone in ninety seconds. | Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos. | Escuchen todos. El cofre se abre a medianoche, tomamos los diamantes y nos vamos en noventa segundos. | 19 → 17 (-11 %) | 116 → 101 (-13 %) | 242 → 175 | 5/6 (falta: cámara acorazada) | **sí** — -11 %: «Escuchen todos»; mantiene el error de «cofre» |

Sentido (manual): 6 «sí», 0 «parcial», 0 «no», 4 sin reducción que valorar, de 10 frases.

## Detalle de `derived_drop_last_sentence` (semilla 42)

| Nº | Inglés | Normal | Conciso | Palabras (normal → conciso) | Caracteres (normal → conciso) | Total, ms (normal → conciso) | Elementos clave | Sentido (valoración manual) |
|---:|:---|:---|:---|---:|---:|---:|---:|:---|
| 1 | Did you seriously finish the orange juice and put the empty carton back in the fridge? | ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador? | ¿De verdad terminaste el jugo de naranja y volviste a poner la caja vacía en el refrigerador? | 17 → 17 (0 %) | 93 → 93 (0 %) | 221 → — | 2/3 (falta: cartón/envase vacío) | **n/a** — una sola oración: no hay nada que quitar |
| 9 | They found fibers under the victim's fingernails and a sneaker print by the window. None of it matches anything in her apartment. | Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. Nada de eso coincide con nada que haya en su apartamento. | Encontraron fibras debajo de las uñas del victimario y una marca de zapatilla cerca de la ventana. | 28 → 17 (-39 %) | 156 → 98 (-37 %) | 268 → — | 4/6 (falta: nada coincide, piso) | **parcial** — pierde la conclusión («nada coincide con su piso») |
| 11 | Or someone wants us to think so. Get me the security footage from the building across the street. | O alguien quiere que lo creamos así. Denme las grabaciones de seguridad del edificio de enfrente. | O alguien quiere que lo creamos así. | 16 → 7 (-56 %) | 97 → 36 (-63 %) | 221 → — | 1/5 (falta: imágenes de seguridad, seguridad, edificio, de enfrente) | **no** — pierde la orden (conseguir las grabaciones), que es lo accionable |
| 24 | Okay, she's back. Good work, everyone. Take five, and somebody please get me a coffee. | Bien, ha vuelto. Bien hecho, todos. Descanse un momento, y alguien por favor traiga un café para mí. | Bien, ha vuelto. Bien hecho, todos. | 18 → 6 (-67 %) | 100 → 35 (-65 %) | 232 → — | 2/4 (falta: cinco minutos, café) | **parcial** — pierde el descanso y el café, secundarios |
| 33 | Then I suppose I'd better start earning my keep, because I haven't slept in a real bed since the winter the river froze over and the king lost his crown. | Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona. | Entonces supongo que debería empezar a ganarme la vida, porque no he dormido en una cama real desde el invierno en que el río se congeló y el rey perdió su corona. | 32 → 32 (0 %) | 163 → 163 (0 %) | 314 → — | 8/8 | **n/a** — una sola oración: no hay nada que quitar |
| 34 | If you're looking for work, the blacksmith needs a hand. He pays well, but he has a nasty temper. | Si buscas trabajo, el herrero necesita ayuda. Pagaba bien, pero tiene un temperamento terrible. | Si buscas trabajo, el herrero necesita ayuda. | 14 → 7 (-50 %) | 95 → 45 (-53 %) | 194 → — | 3/5 (falta: paga bien, mal carácter) | **parcial** — pierde el sueldo y el mal carácter |
| 42 | Okay, everybody, grab your laptops and follow me. We're working in the parking lot today. | De acuerdo, todos, coged vuestros ordenadores portátiles y seguidme. Hoy trabajaremos en el estacionamiento. | De acuerdo, todos, coged vuestros ordenadores portátiles y seguidme. | 14 → 9 (-36 %) | 108 → 68 (-37 %) | 252 → — | 2/5 (falta: aparcamiento, hoy, trabajar) | **parcial** — pierde el destino (el aparcamiento) |
| 43 | Can you pull over at the next gas station? I need a sandwich and a bathroom. | ¿Puedes detenerte en la próxima gasolinera? Necesito un sándwich y un baño. | ¿Puedes detenerte en la próxima gasolinera? | 12 → 6 (-50 %) | 75 → 43 (-43 %) | 198 → — | 2/4 (falta: bocadillo, baño) | **parcial** — pierde el motivo (el bocadillo y el baño) |
| 49 | Welcome back to Lucky Hour, everybody! Are you ready? Our next contestant is Marcus from Detroit. | Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? Nuestro próximo concursante es Marcus de Detroit. | Bienvenidos de nuevo a Lucky Hour, todos. ¿Están listos? | 16 → 9 (-44 %) | 106 → 56 (-47 %) | 222 → — | 3/6 (falta: concursante, Marcus, Detroit) | **no** — pierde quién concursa (Marcus de Detroit) |
| 55 | Listen up, all of you. The vault opens at midnight, we grab the diamonds, and we're gone in ninety seconds. | Escuchad bien, todos vosotros. El cofre se abre a medianoche, cogemos los diamantes y nos vamos en noventa segundos. | Escuchad bien, todos vosotros. | 19 → 4 (-79 %) | 116 → 30 (-74 %) | 242 → — | 1/6 (falta: cámara acorazada, medianoche, diamantes, noventa segundos, nos vamos) | **no** — queda solo «Escuchad»: pierde todo el plan |

Sentido (manual): 0 «sí», 5 «parcial», 3 «no», 2 sin reducción que valorar, de 10 frases.

