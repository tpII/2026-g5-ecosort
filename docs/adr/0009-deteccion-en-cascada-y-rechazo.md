# ADR 0009 — Detección: cascada (quietud, tamaño, modelo) y rechazo con la clase `ninguno`

**Estado:** Aceptado (26/9/2026) — la clase `ninguno` y la detección en cascada se le mostraron a los 3
integrantes por el chat del equipo y las aprobaron. Los umbrales siguen sin calibrar (ver abajo).

## Contexto

Al probar el sistema aparecieron dos preocupaciones: que un objeto que no es un residuo (una mano, una
cara, un animal, alguien que pasa cerca de la cámara) termine contado como un evento, y que la Pi esté
procesando imágenes todo el tiempo. Se midió antes de decidir:

- **El modelo es de clases cerradas**: siempre elige alguna, aunque no sea un residuo. Con 9 entradas
  sintéticas que no lo eran, 6 superaron el umbral de 0,60: piel clara y rosada dieron `cardboard` con
  0,62, y gris, negro y ruido dieron `trash` con 0,66 a 0,82 (que en el contrato es `organico`). Son
  entradas sintéticas, no una mano real.
- **La confianza no refleja el enfoque**: con imágenes cada vez más borrosas la confianza casi no se movió,
  mientras la nitidez (varianza del Laplaciano) cayó unas 100 veces. Pero **un umbral absoluto de nitidez es
  frágil**: calibrado una vez con imágenes limpias, con solo 2 niveles de ruido de sensor deja pasar el 100 %
  de las desenfocadas (el umbral correcto se corre ~10 veces con el ruido y la luz).
- **La lógica anterior era muy permisiva**: bastaba un cambio del 3 % de la imagen durante 3 cuadros y 3
  predicciones iguales con ≥ 0,60, clasificando el cuadro entero en cada cuadro. En la comparación
  sintética de abajo dio 4 eventos falsos sobre 6.
- El costo no viene de la detección de presencia (0,2 ms por cuadro contra ~8 ms de inferencia en una
  notebook) sino de correr el modelo cuando no hace falta.

## Decisión

1. **Cascada, de lo barato a lo caro** (`raspberry/deteccion.py`, una máquina de estados pura y testeada
   sin cámara ni modelo):
   1. *presencia*: la escena cambió respecto del fondo vacío;
   2. *quietud*: lo que apareció dejó de moverse ~1 s. Una mano que se agita o alguien que pasa nunca queda
      quieto, y ahí termina: no se corre el modelo;
   3. *plausibilidad*: el tamaño de la mancha es el de un residuo (una cara o un brazo ocupan mucho más);
   4. *modelo*: se clasifican solo los 5 cuadros más nítidos de los quietos y se decide por el **promedio de
      sus probabilidades**, no por un cuadro suelto. Nunca por un umbral absoluto de nitidez: se ordena y se
      eligen los mejores, que se autocalibra con la luz y no descarta los objetos lisos.
2. **La clase `ninguno`**, primera de una lista de *descartes* en `schema/clases.json`: etiquetas que el modelo
   puede devolver y significan "esto no es un residuo". Se entrena como una clase más, con negativos
   (manos, brazos, caras, pelo, animales, plataforma vacía, sombras). Si el modelo la elige, o le da ≥ 0,40 de
   probabilidad aunque no gane, el objeto se descarta: **no abre ninguna compuerta y nunca se publica como
   evento**, así que no ensucia los mensajes ni la base.
3. **Tres resultados, no dos**: `aceptado` (es un residuo y se sabe cuál: se publica el evento), `incierto`
   (parece un residuo pero no se sabe cuál: baja confianza, cuadros que no coinciden) y `descartado` (no es un
   residuo, o no se dieron las condiciones para analizarlo). La ADR 0002 dice que la baja confianza abre la
   compuerta de orgánico; ese caso es `incierto` y sigue pendiente de decidir (hoy no genera evento).
4. **Las señales de la máquina son la interfaz para el firmware**: `presente`, `transito`, `aceptado`,
   `incierto`, `descartado` (con su motivo), `retirado` y `no_retirado`. Con ellas se pueden hacer las luces y
   los sonidos que le den expresión a la papelera (tabla abajo). Tras `aceptado`, `retirado` significa que
   **el objeto cayó**, y `no_retirado`, que **se trabó**.
5. **Sensor de distancia (ToF) recomendado como capa 0**: dispara el análisis y verifica que la altura de lo
   que hay sobre la plataforma sea plausible; deja a la Pi ociosa el resto del tiempo. No reemplaza a
   `ninguno`: una mano a 10 cm dispara cualquier sensor. Hasta que exista, la presencia sale de la cámara.
6. En `vivo` (transitorio, no se persiste) la Pi suma `estado` (`libre`, `asentando`, `esperando_retiro`) y
   `motivo`, para que el dashboard pueda mostrar "analizando" o "objeto no reconocido".

## Consecuencias

**Comparación sintética** (`Detector` real, cámara y modelo falsos; 6 escenas con 2 residuos reales; el
modelo falso imita lo medido: la piel da `cardboard` 0,62):

| Escena | Debería | Lógica anterior | Nueva | Nueva, piel con conf. 0,85 | Nueva con `ninguno` |
|---|---|---|---|---|---|
| mano que pasa | 0 | 1 | 0 | 0 | 0 |
| mano que se agita | 0 | 1 | 0 | 0 | 0 |
| residuo real (x2) | 2 | 2 | 2 | 2 | 2 |
| cara quieta (25 % de la imagen) | 0 | 1 | 0 | **1** | 0 |
| algo enorme y quieto | 0 | 1 | 0 | 0 | 0 |
| **Eventos falsos** | 0 | **4** | 0 | **1** | 0 |
| **Veces que corrió el modelo** | | 285 | 15 | 15 | 15 |

- Sin `ninguno`, algo **quieto, de tamaño plausible y clasificado con confianza alta** todavía pasa (cuarta
  columna): la cascada frena lo que se mueve o es enorme, pero solo `ninguno` arregla eso. Por eso hace falta
  juntar los negativos.
- Son escenas sintéticas: prueban la lógica, no el rendimiento real. **Los umbrales son valores iniciales sin
  calibrar** con la cámara del gabinete.
- Cada objeto analizado cuesta 5 inferencias (unos 155 ms a 31 ms cada una en la Pi) más ~1 s de quietud: cabe
  en los 2 a 4 s del requisito 4.1, a verificar en la Pi.
- **Validación pendiente**: una sesión de 10 minutos donde los tres intenten engañarlo (manos, caras, el
  celular, lo que sea), contando eventos falsos; y una de fondo vacío con gente pasando, midiendo falsos por
  hora. Sirven también como parte de la metodología de noviembre.
- **Limitación heredada**: la presencia compara en gris contra el fondo, así que un objeto de gris parecido al
  de la plataforma, o transparente, no se ve. Conviene una plataforma lisa de un color que contraste con lo
  habitual de los residuos (a probar). Apareció en las pruebas sintéticas.
- Si algo queda sobre la plataforma ~30 s (`no_retirado`), además de la señal se recalibra el fondo, como antes:
  un objeto trabado pasa a ser "fondo". La señal es entonces el único aviso.
- Se modificaron `ecosort_pi.py` e `inferencia_pi.py` (código de Mica): necesitan su review.

**Señales y expresión** (propuesta, a definir con David; suma un buzzer o parlante pequeño y LEDs de estado a
la lista de materiales, junto con el quinto SG90 y el sensor de distancia):

| Señal | Cuándo | Expresión sugerida |
|---|---|---|
| `presente` | llegó algo | LED de estado pulsando ("pensando") |
| `aceptado` | reconocido | LED de la compuerta y un sonido corto y alegre |
| `descartado` (no_residuo, tamano, sin_quietud) | "objeto no reconocido" | LED ámbar parpadeando y un sonido suave de "hmm"; no se abre nada |
| `incierto` | parece un residuo pero no sabe cuál | LED ámbar fijo y un sonido de duda |
| `retirado` tras `aceptado` | **cayó** | luz verde y un "gracias" |
| `no_retirado` tras `aceptado` | **se trabó** | alarma distinta y persistente |
| `no_retirado` tras `descartado` | dejaron algo | recordatorio suave |

**Trabajo que queda**
- **Modelo (Mica):** juntar los negativos para `ninguno` (datasets públicos de personas y animales, más fotos
  propias del gabinete) en `vision/data/.../ninguno/`, y reentrenar. Ver `vision/README.md`.
- **Firmware (David):** enganchar las señales a LEDs y sonidos; sumar el sensor de distancia a la lista de
  materiales.
- **Contrato (abierto):** persistir los descartes como telemetría (por ejemplo un tópico `descartes` y una tabla
  aparte, nunca en `eventos`) para medir la tasa de falsos sin ensuciar los datos.
