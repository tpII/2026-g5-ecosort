# ADR 0004 — Visualización y observabilidad: Grafana vs. dashboard propio

**Estado:** Pendiente confirmar con el docente.

## Contexto

Se necesita mostrar tanto el dato de negocio (eventos de clasificación,
histórico, estadísticas por clase) como la salud del propio dispositivo
(CPU, RAM, temperatura de la Pi, si sigue vivo, ya que consideramos que es importante en dispositivos de este estilo con recursos limitados y procesamiento de imagenes). Se evaluó construir un
dashboard web propio (Flask) contra usar Grafana.

## Decisión

**Visualización del dato de negocio:** Grafana, leyendo SQLite vía el
plugin comunitario `grafana-sqlite-datasource` y dashboards versionados como código
(`grafana/provisioning/`, `grafana/dashboards/`), no configurados a mano en
la UI para su replicación.

**Observabilidad del dispositivo (EXTRA, OPCIONAL ):** `node_exporter` en la Pi (expone
`/metrics`: CPU, RAM, temperatura) + Prometheus en el dispositivo externo
(scrapea esa métrica), como segundo datasource de Grafana. Reglas de
alerting sobre: staleness de la tabla `eventos`, `up == 0` (target down,
nativo de Prometheus), temperatura sostenida alta (~80°C, umbral de
throttling de la Pi 3) y CPU sostenida alta.

Se descartó instrumentar la observabilidad con código propio: `node_exporter`
y Prometheus son binarios estándar, mantenidos, sin una línea de código
nuestro — la única pieza de software nueva en todo el pipeline es el
adaptador MQTT→SQLite (ADR 0003), porque no existe un exporter genérico para
"eventos de clasificación de residuos".

## Consecuencias

- Ahorra tiempo de desarrollo de frontend en un cronograma donde ML es la
  ruta crítica, y da funcionalidad de serie (auto-refresh, rango de tiempo,
  alerting) sin código adicional.
- Suma piezas corriendo (Grafana + Prometheus + 2 plugins) en vez de un
  único proceso Flask — es un trade-off.
- Dos datasources con naturalezas distintas (SQLite para el dato de
  negocio, Prometheus para la salud del dispositivo) en vez de forzar todo
  en una sola base.
- El mismo patrón (Grafana + Prometheus + node_exporter) es el estándar de
  observabilidad de infraestructura en la industria.
