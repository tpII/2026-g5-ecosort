# ADR 0008 — Contrato de eventos v1: clases de producto, 5 compuertas y validación

**Estado:** Propuesto — a la espera del review cruzado de los 3 integrantes (regla para todo lo que
vive en `schema/`).

## Contexto

La [ADR 0003](0003-mqtt-sqlite-como-contrato.md) decidió el *mecanismo* (MQTT + SQLite con un adapter)
pero no qué viaja por él. Al revisarlo contra el código apareció que el contrato existía solo de forma
implícita, y que no se cumplía:

- **Tres vocabularios de clases distintos.** El schema y la documentación decían
  `plastico|papel|vidrio|organico`, pero el runtime real publicaba las etiquetas crudas de TrashNet
  (`cardboard`, `glass`...) con `compuerta` en `null`. El mapeo a producto existía en dos lugares que
  discrepaban: `trash` iba a orgánico en `vision/classes.py` y a ninguna compuerta en `inferencia_pi.py`, y
  `metal` no iba a ninguna.
- **El adapter aceptaba cualquier cosa.** Solo exigía `evento_id` y `clase`: una clase `banana`, una
  confianza `"abc"` o una compuerta 99 terminaban en la base y en el dashboard.
- **Campos con semántica engañosa y sin documentar** (`confianza` es un promedio de frames, `latencia_ms`
  no es captura-a-compuerta, `ts` sale de un reloj sin RTC, `modelo` es una ruta), y sin versión.
- El schema implementado había cambiado respecto del acordado (`accionado` desapareció) sin review.

Además, el metal es muy reciclable y el modelo ya lo reconoce, pero no tenía dónde ir: el diseño tenía
4 compuertas y el metal no era una clase del producto.

## Decisión

1. **Son 5 clases de producto y 5 compuertas**: `plastico`=1, `papel`=2, `vidrio`=3, `organico`=4,
   `metal`=5. La quinta compuerta la suma el equipo por cuenta propia en noviembre (un SG90 más). **En
   octubre las cinco salidas se simulan con LEDs.** Esto amplía la [ADR 0002](0002-plataforma-4-compuertas-collar.md).
2. **El vocabulario del producto se resuelve en el borde, en la Pi.** El evento lleva `clase` (producto),
   `clase_modelo` (la etiqueta cruda, para poder evaluar el modelo aunque cambie el mapeo), `compuerta`
   (1 a 5) y `accionado` (si la salida física se activó). La Pi falla al arrancar si el modelo tiene una
   etiqueta que el contrato no sabe mapear (salvo los *descartes*, como `ninguno`, que la
   [ADR 0009](0009-deteccion-en-cascada-y-rechazo.md) define: lo que no es un residuo nunca se publica).
3. **Fuente única y versionada**: `schema/clases.json` (clases, compuertas y mapeo del modelo) y
   `schema/evento.schema.json` (JSON Schema del payload, con `schema_version: 1`). Se documenta en
   [`docs/contrato-mqtt.md`](../contrato-mqtt.md).
4. **El adapter valida contra ese JSON Schema y no pierde nada en silencio**: lo que no cumple se guarda en
   `eventos_rechazados` con el motivo, y no se cuenta como evento. También rechaza un `dispositivo_id` que
   no coincide con el del tópico.
5. **Tests de contrato en CI** (`schema/tests`): la Pi produce un evento válido para cada etiqueta del
   modelo, el adapter acepta y rechaza lo que corresponde, y `clases.json`, el JSON Schema,
   `vision/classes.py` y las barras del dashboard no pueden divergir.

Alternativas descartadas:

- **Mandar el metal como `organico` en el contrato:** destruye información (el dashboard mostraría latas
  como orgánico) y no se puede deshacer.
- **`compuerta` en `null` para el metal hasta noviembre:** superada por definir las 5 compuertas desde el
  diseño, con los LEDs simulando las salidas.
- **Validar con código a mano en el adapter:** duplica las reglas del JSON Schema y termina divergiendo.

## Consecuencias

- Las tres áreas desarrollan contra un documento y un test, no contra el código de la otra.
- Los eventos de la Pi actual (formato anterior) no pasan la validación: hay que redesplegar la Pi con el
  código nuevo (y copiar `schema/`, ver la guía de instalación, paso 7). Una base `eventos.db` vieja gana
  las columnas nuevas sola al arrancar el adapter.
- Un cambio de clases o de campos es un cambio coordinado en varios archivos, pero el CI avisa si falta
  alguno.
- Un publisher desalineado no rompe el dashboard: sus mensajes quedan visibles en `eventos_rechazados`.
- El adapter suma una dependencia (`jsonschema`).

**Trabajo que esto le deja a otros:**

- **Firmware (David):** cinco salidas configurables (una lista de pines, no cuatro fijas), LEDs en octubre;
  al accionar una, publicar `accionado: true`. Reservar el quinto hueco en la maqueta ahora, porque el cambio
  mecánico es lo más caro de rehacer tarde, y comprar el quinto SG90 con el resto del pedido.
- **Modelo (Mica):** revisar el mapeo (`trash` → `organico`) y, cuando haya fotos propias, incluir latas y
  aluminio: `metal` es de las clases más flojas del modelo (precisión de 0,675 en test). Conviene decidir
  de antemano que la matriz de confusión oficial es de 5 clases.
- **Cátedra:** avisar (no pedir permiso) que el Plan entregado dice 4 compuertas y que se agrega una quinta por
  cuenta del equipo.
- **Fuera de este ADR, queda abierto:** cómo se expresa la baja confianza (la ADR 0002 dice que abre la
  compuerta de orgánico; hoy no genera evento) y una latencia captura-a-compuerta.
