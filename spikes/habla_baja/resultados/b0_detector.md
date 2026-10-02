# Detector de «vosotros»: precisión y cobertura frente a mi etiquetado de 228 salidas (7B, prompt actual, semilla 42)

- **vosotros**: n gold = 81, precisión 97.6 % (81/83), cobertura 100.0 % (81/81)
- **ustedes**: n gold = 30, precisión 93.5 % (29/31), cobertura 96.7 % (29/30)
- **tú**: n gold = 72, precisión 100.0 % (66/66), cobertura 91.7 % (66/72)
- **usted**: n gold = 14, precisión 87.5 % (14/16), cobertura 100.0 % (14/14)

Errores (idx, gold, detector):

- 20 gold=t det=n | Hurry up, the doors are closing! => ¡Date prisa, se están cerrando las puertas!
- 50 gold=m det=v | Please send me your ideas by Friday. => Por favor, envíame vuestras ideas para el viernes.
- 53 gold=m det=v | Let me know if you need anything. => Avísame si necesitáis algo.
- 82 gold=t det=u | Make sure he rests and drinks plenty of water. => Asegúrate de que descanse y beba mucha agua.
- 122 gold=t det=n | Make sure you hit the subscribe button. => Asegúrate de pulsar el botón de suscribirte.
- 128 gold=m det=n | Shake hands and forget about it. => Daos la mano y olvídalo.
- 130 gold=t det=n | Don't make this worse than it is. => No empeores las cosas más de lo que ya están.
- 174 gold=t det=n | Honey, put on your coat, it's freezing. => Cariño, pónete el abrigo, hace un frío terrible.
- 178 gold=t det=u | Come here and let me fix your hair. => Ven aquí y déjame arreglarte el pelo.
- 179 gold=x det=n | Do you want a sandwich? => ¿Querés un sándwich?
- 207 gold=u det=n | My lords, will you stand with me? => Mis señores, ¿estarán a mi lado?
- 214 gold=n det=s | Their kids break everything they touch. => Sus hijos rompen todo lo que tocan.
- 223 gold=n det=s | They finish all their homework on time. => Ellos terminan toda su tarea a tiempo.