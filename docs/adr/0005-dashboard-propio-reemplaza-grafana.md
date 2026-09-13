# ADR 0005 — Visualización: dashboard propio reemplaza a Grafana

**Estado:** Aceptado. Reemplaza la decisión de visualización de la
[ADR 0004](0004-grafana-vs-dashboard-propio.md).

## Contexto

La ADR 0004 había elegido Grafana para la visualización del dato de negocio,
justamente para ahorrar tiempo de desarrollo de frontend en un cronograma
donde ML es la ruta crítica. El docente evaluó esa decisión y pidió que el
equipo desarrolle un **dashboard propio**, en vez de apoyarse en una
herramienta de monitoreo de terceros — la implementación del frontend pasa a
ser parte de lo que se evalúa del proyecto, no algo a resolver "gratis" con
una herramienta externa.

## Decisión

Se descarta Grafana como capa de visualización. El equipo va a construir un
**dashboard propio** (Front End) que:

- Lee el dato de negocio desde **SQLite** (`eventos.db`) — mismo contrato de
  datos definido en la [ADR 0003](0003-mqtt-sqlite-como-contrato.md), no
  cambia el pipeline MQTT → adaptador → SQLite.
- Lee, como segundo datasource, **Prometheus** para la observabilidad del
  dispositivo (`node_exporter`: CPU, RAM, temperatura) — se mantiene el
  mismo criterio de la ADR 0004 de separar dato de negocio (SQLite) de salud
  del dispositivo (Prometheus).

Queda pendiente definir el framework/stack concreto del dashboard (a
resolver en las próximas semanas — ver `BITACORA.md`).

## Consecuencias

- Se suma trabajo de desarrollo de frontend al cronograma, que antes se
  evitaba usando Grafana — impacto a seguir de cerca porque ML sigue siendo
  la ruta crítica.
- Se gana control total sobre la UX del dashboard (relevante para la demo) y
  se elimina la dependencia de plugins de terceros
  (`grafana-sqlite-datasource`, `grafana-mqtt-datasource`) y de su
  aprovisionamiento como código (`grafana/provisioning/`,
  `grafana/dashboards/`, ya no aplican).
- Los datasources (SQLite para negocio, Prometheus para salud del
  dispositivo) y las reglas de alerting definidas en la ADR 0004 se
  mantienen como requisito funcional; el dashboard propio deberá
  reimplementar ese alerting, que en Grafana venía de fábrica.
