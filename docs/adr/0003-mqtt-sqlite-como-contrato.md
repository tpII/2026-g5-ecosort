# ADR 0003 — Contrato de datos y transporte: MQTT + SQLite

**Estado:** Aceptado.

## Contexto

Hay una frontera de red real entre la Raspberry Pi (donde corre la
inferencia) y el dispositivo externo que hostea el dashboard — no es un
escenario de todo-en-una-máquina. Se evaluaron: RabbitMQ, conexión directa
de MQTT a Grafana, y MQTT + SQLite vía un adaptador propio.

## Decisión

**Transporte:** MQTT, con Mosquitto como broker corriendo en la propia Pi.
No RabbitMQ: mismo rol de mensajería, pero RabbitMQ es un runtime AMQP/Erlang
más pesado con capacidad de ruteo que este caso de uso no necesita (1
publisher, pocos suscriptores). El catálogo del proyecto además especifica MQTT como
protocolo, no "un broker" en general.

**Persistencia:** SQLite (`eventos.db`), poblada por un script adaptador
(Python, `paho-mqtt`) que se suscribe al tópico y hace el único INSERT real.
MQTT no persiste por diseño (solo mantiene el último mensaje "retained" por
tópico) — sin este adaptador, Grafana no tendría de dónde leer historial
navegable.

Se descartó conectar Grafana directo a MQTT: el plugin oficial
`grafana-mqtt-datasource` solo soporta visualización en vivo/streaming, no
consultas históricas — insuficiente para el requisito de historial.

## Consecuencias

- El patrón resultante (broker + adaptador que persiste + capa de
  visualización separada) es el mismo que usan stacks de producción tipo
  Prometheus/Grafana, adaptado a que acá el dato es un evento discreto
  navegable, no una métrica agregada — ver ADR 0004.
- Si el notebook/servidor externo está apagado o se reinicia, Mosquitto no
  se cae ni pierde su rol de broker: el adaptador simplemente se reconecta
  cuando vuelve.
- El schema (`schema/eventos.sql`) incluye `dispositivo_id` desde el
  arranque, como forward-compatibility barata para un escenario de N
  dispositivos (hoy fuera de alcance, ver `plan-de-proyecto.pdf`).
- Sin TLS ni autenticación en MQTT: aceptable porque el tráfico nunca sale
  de la red que arma la propia Pi en modo AP.
