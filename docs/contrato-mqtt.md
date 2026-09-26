# Contrato de eventos MQTT — v1

Lo que la Raspberry Pi le publica al host y lo que el host acepta. Es el punto de acople entre las tres
áreas (modelo, backend, firmware): cada una puede desarrollar y probar contra este documento sin
depender de que las otras estén listas. El porqué de las decisiones está en la
[ADR 0008](adr/0008-contrato-de-eventos.md); el transporte (MQTT + SQLite) en la
[ADR 0003](adr/0003-mqtt-sqlite-como-contrato.md).

**Fuentes de verdad** (cambiarlas requiere el review de los 3, y el CI falla si dejan de coincidir):

| Archivo | Qué define |
|---|---|
| [`schema/evento.schema.json`](../schema/evento.schema.json) | El payload del evento, en JSON Schema. Lo aplica el adapter. |
| [`schema/clases.json`](../schema/clases.json) | Las clases de producto, su compuerta, y cómo se mapea lo que devuelve el modelo. |
| [`schema/eventos.sql`](../schema/eventos.sql) | Cómo se persiste (tabla `eventos` y `eventos_rechazados`). |

## Tópicos

`<id>` es el `dispositivo_id` (hoy `ecosort-01`).

| Tópico | QoS | Retain | Payload | Se persiste |
|---|---|---|---|---|
| `ecosort/<id>/eventos` | 1 | no | JSON, un evento por residuo contado (ver abajo) | sí, lo hace el adapter |
| `ecosort/<id>/vivo` | 0 | no | JSON con lo que ve la cámara ahora (~3 por segundo) | no, ni se valida |
| `ecosort/<id>/estado` | 1 | **sí** | texto plano `online` / `offline` (no es JSON) | no |

- `estado` lo publica la Pi en `online` al conectarse, y el broker publica `offline` solo si la Pi
  se cae sin despedirse (Last Will).
- `vivo` es solo para el dashboard: `{presente, estado, clase, clase_modelo, confianza, contado, motivo}`
  más `dispositivo_id` y `ts`. `estado` es `libre`, `asentando` (algo apareció y se espera que quede quieto)
  o `esperando_retiro`; `clase` solo viene cuando el objeto fue aceptado; `motivo` explica por qué se descartó
  o quedó incierto. Usa el mismo vocabulario de clases que los eventos.
- Los clientes del host usan sesión persistente (`clean_session=False`) con `client_id` fijo
  (`ecosort-adapter`, `ecosort-dashboard`), así el broker les guarda lo que llegue mientras están
  caídos. **Dos instancias con el mismo `client_id` se desconectan entre sí**: si algún día hay más de
  un adapter, cada uno necesita el suyo.

## El evento (`ecosort/<id>/eventos`)

```json
{
  "schema_version": 1,
  "evento_id": "424f07b9-bc60-475d-9ee3-10f8a2512530",
  "dispositivo_id": "ecosort-01",
  "ts": "2026-09-26T13:15:30.063+00:00",
  "clase": "plastico",
  "clase_modelo": "plastic",
  "confianza": 0.9312,
  "compuerta": 1,
  "accionado": false,
  "latencia_ms": 31.2,
  "modelo": "ecosort_int8.tflite"
}
```

| Campo | Tipo | Req. | Significado |
|---|---|---|---|
| `schema_version` | entero, hoy `1` | sí | Versión del contrato. Un consumidor rechaza lo que no entiende. |
| `evento_id` | UUID en minúsculas | sí | Lo genera la Pi. QoS 1 puede entregar un mensaje dos veces: el adapter deduplica por este campo. |
| `dispositivo_id` | texto `[A-Za-z0-9._-]` | sí | Debe coincidir con el segmento `<id>` del tópico; si no, se rechaza. |
| `ts` | RFC 3339 con zona | sí | **Reloj de la Pi, que no tiene RTC: puede estar mal.** El adapter registra aparte `ts_recepcion` (reloj del host), que es el confiable. |
| `clase` | ver vocabulario | sí | Clase de producto: define a qué compuerta va. |
| `clase_modelo` | texto | sí | Etiqueta cruda que devolvió el modelo (`cardboard`, `glass`...). Se conserva para evaluar el modelo aunque cambie el mapeo. |
| `confianza` | número 0 a 1 | sí | **Promedio** de los frames que confirmaron la clase (3 hoy), no la de un solo frame. |
| `compuerta` | entero 1 a 5 | sí | Compuerta asignada a la clase. |
| `accionado` | booleano | sí | `true` si la salida física de esa compuerta se activó: un LED en octubre, el servo desde noviembre. **Es `false` mientras no exista el firmware.** |
| `latencia_ms` | número o `null` | no | Tiempo de inferencia del último frame. **No es captura-a-compuerta**, así que no sirve todavía para el requisito de 2 a 4 segundos. |
| `modelo` | texto o `null` | no | Identificador del modelo. Hoy es la ruta del `.tflite`, no una versión. |

Los campos que el consumidor no conoce se ignoran, así que agregar campos opcionales no rompe a nadie.

## Vocabulario de clases

| `clase` (producto) | `compuerta` | Etiquetas del modelo actual (TrashNet) |
|---|---|---|
| `plastico` | 1 | `plastic` |
| `papel` | 2 | `paper`, `cardboard` |
| `vidrio` | 3 | `glass` |
| `organico` | 4 | `trash` |
| `metal` | 5 | `metal` |

Son **5 clases y 5 compuertas**. La del metal la suma el equipo en noviembre; hasta entonces las cinco
salidas se simulan con LEDs. Si el modelo se reentrena y ya devuelve clases de producto, se aceptan
tal cual sin tocar `mapeo_modelo`. Una etiqueta que el contrato no sabe mapear **hace fallar a la Pi al
arrancar** (no en medio de la clasificación) con un mensaje que dice qué agregar.

### Lo que no es un residuo: `ninguno`

`schema/clases.json` tiene además una lista de **descartes**: etiquetas que el modelo puede devolver y
significan "esto no es un residuo" (hoy `ninguno`: una mano, una cara, un animal, la plataforma vacía). Un
descarte **no tiene clase de producto, no abre ninguna compuerta y nunca se publica como evento**: la Pi lo
descarta antes de publicar (ver la [ADR 0009](adr/0009-deteccion-en-cascada-y-rechazo.md)), así que no
ensucia los eventos ni la base. La clase se entrena con negativos; el modelo actual todavía no la tiene.

Hay tres resultados posibles al analizar un objeto: **aceptado** (se publica el evento), **incierto** (parece
un residuo pero no se sabe cuál) y **descartado** (no es un residuo, o no se pudo analizar). Los dos últimos
no generan evento.

**Todavía no implementado:** la ADR 0002 dice que una clasificación de baja confianza abre la compuerta
de orgánico. Ese caso es `incierto`, y hoy no genera evento: decidir cómo se expresa (¿`organico` con un
motivo?) es parte del firmware.

## Validación y rechazos

El adapter valida cada mensaje contra `schema/evento.schema.json`. Lo que no cumple **no se cuenta como
evento**: queda en la tabla `eventos_rechazados` con el motivo y el payload crudo (truncado a 2000
caracteres), para poder diagnosticar un publisher desalineado en vez de perder datos en silencio:

```sql
SELECT ts_recepcion, motivo, payload FROM eventos_rechazados ORDER BY id DESC LIMIT 20;
```

Se rechaza: un payload que no es JSON, una clase fuera del vocabulario, una confianza no numérica o fuera
de 0 a 1, una compuerta fuera de 1 a 5, un campo obligatorio ausente, un `schema_version` distinto de 1, y
un `dispositivo_id` que no coincide con el del tópico.

## Cómo evoluciona

- **Compatible dentro de v1:** agregar un campo *opcional*.
- **Requiere `schema_version` 2** (y una ADR): quitar, renombrar o cambiar el tipo o el significado de un
  campo, o volver obligatorio uno nuevo.
- **Agregar una clase** es un cambio coordinado: `schema/clases.json`, el `enum` de
  `schema/evento.schema.json`, `vision/classes.py` y las barras del dashboard. El test de contrato falla
  si falta alguno.
- Una base `eventos.db` anterior al contrato gana las columnas nuevas sola al arrancar el adapter, sin
  perder datos.

## Cómo probarlo

```bash
# sin red ni Docker: la Pi publica algo válido, el adapter acepta y rechaza lo que corresponde
pip install paho-mqtt jsonschema
python -m unittest discover -s schema/tests -v

# con Docker: broker + adapter + dashboard, y el camino completo (~40 s)
bash host/tests/e2e_smoke.sh

# a mano: eventos falsos con las etiquetas reales del modelo, contra un broker local
docker compose -f host/docker-compose.yml -f host/docker-compose.dev.yml up -d
python raspberry/ecosort_mqtt.py
```

## Desplegar en la Pi

La Pi necesita `schema/clases.json` junto a los scripts (la guía de instalación, paso 7, ya lo copia):

```bash
scp -r raspberry <usuario>@<ip-de-la-pi>:~/ecosort
scp -r schema <usuario>@<ip-de-la-pi>:~/ecosort
```

## Abierto

- Baja confianza (`incierto`) → compuerta de orgánico (ver arriba).
- Persistir los descartes como telemetría, para medir la tasa de falsos (por ejemplo un tópico `descartes` y
  una tabla aparte, nunca en `eventos`). Hoy se ven solo en `vivo` y en el log de la Pi.
- `accionado` real: depende del firmware (LEDs en octubre, servos en noviembre).
- `modelo` como versión, y una latencia captura-a-compuerta, si se quiere medir el requisito de tiempo.
