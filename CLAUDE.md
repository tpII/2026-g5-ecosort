# EcoSort (`tpII/2026-g5-ecosort`)

Contenedor de reciclaje inteligente: clasifica residuos (plástico, papel, vidrio, orgánico, metal) por visión artificial sobre una Raspberry Pi 3 y aciona 5 compuertas físicas (servos SG90) para dirigirlos al contenedor correcto. Proyecto de la materia Taller de Proyecto II (UNLP). Equipo de 3: Francisco Estrada (infra/backend), Juan David Alvarez (embebido/hardware), Micaela Taini (ML/visión). Docente: Gastón Maron.

Este archivo es a la vez `CLAUDE.md` y `AGENTS.md` (un *symlink* al otro, mismo contenido real) — así cualquiera de los tres lo tiene como contexto sin importar qué asistente de IA use: Claude Code lo lee solo por el nombre `CLAUDE.md`, varias herramientas con acceso al repo (Cursor, Copilot, Windsurf, Codex CLI, etc.) leen `AGENTS.md` por convención, y para un chat sin acceso al repo (ChatGPT, Gemini web) alcanza con pegar este archivo al principio de la conversación. Edita cualquiera de los dos nombres: es el mismo archivo.

**Antes de asumir cualquier ruta de este documento, listá el repo real** (`ls`, `find`, o el explorador de archivos) — este archivo describe tanto lo que ya existe como la estructura objetivo todavía no mergeada; están marcadas por separado más abajo. Para el detalle semana a semana (qué se hizo, qué se rompió, qué sigue abierto) la fuente única es `BITACORA.md` — este archivo da una foto del estado, no el historial.

## Qué es, en una frase por capa

- **Edge (Raspberry Pi 3):** cámara → inferencia (TFLite) → decide clase → aciona el servo de la compuerta correspondiente → publica el evento por MQTT. Corre (o debería correr) en modo Access Point propio, red `192.168.20.0/28` (Pi en `.1`, host en `.2`) — **hoy el modo AP todavía no está armado**, se prueba compartiendo una red con internet (ver `docs/guia-instalacion-raspberry.md`, "Limitaciones conocidas").
- **Host externo (misma LAN):** adaptador MQTT→SQLite (único INSERT real) + dashboard propio (servidor HTTP propio en stdlib de Python, sin framework, + Chart.js para los gráficos — **no Grafana**, ver ADR 0005). Prometheus/`node_exporter` para la salud del dispositivo está **diseñado pero no implementado**: es el objetivo secundario/stretch, no algo que ya corra.
- **Contrato entre ambos:** MQTT (transporte, tópicos `ecosort/<dispositivo_id>/eventos` y `/vivo` y `/estado`) + tabla SQLite `eventos` (persistencia, WAL mode). Cualquiera de las 3 áreas puede desarrollar y testear publicando eventos MQTT fake sin depender de que las otras estén listas (`raspberry/ecosort_mqtt.py` corrido directo publica eventos falsos).

El schema completo y canónico vive en `schema/eventos.sql` — **no lo copies inline acá** (ya duplicarlo fue la causa de que este bloque quedara desactualizado una vez; mejor un puntero que se rompe visiblemente a uno que miente calladamente). Campos clave: `clase` (la que se publica, puede quedar forzada a `organico` — ADR 0002), `clase_modelo` (lo que vio el modelo de verdad), `compuerta`, `accionado` (si el servo se movió en serio), `motivo` (solo si es incierto), métricas (`confianza`, `latencia_ms`) y trazabilidad (`evento_id`, `schema_version`, `ts_dispositivo`/`ts_recepcion`). Semántica completa en `docs/contrato-mqtt.md`.

Cambios a este schema requieren acuerdo de los 3 integrantes — rompe a los otros dos en silencio si se cambia unilateralmente.

## Decisiones ya tomadas (no las reabras sin motivo — están en `docs/adr/`)

1. Modelo: fine-tuning sobre preentrenado, exportado a TFLite int8 (no entrenamiento desde cero).
2. Mecanismo físico: plataforma de 5 compuertas (plástico, papel, vidrio, orgánico, metal) + collar centrador (no otras alternativas evaluadas).
3. Contrato de datos/transporte: MQTT + SQLite (no RabbitMQ, no conexión directa a un dashboard).
4. Visualización: dashboard propio como entrega principal; Grafana secundario (ADR 0005 supersede parcialmente a la 0004, que evaluaba Grafana como principal).
5. Alimentación: la Pi y los servos van en **rails separados** (Pi con su fuente oficial 5V/2.5A; servos con fuente externa 5V ≥2-3A), compartiendo solo GND — evita que los picos de corriente de los servos reseteen la Pi (que además tira abajo el AP WiFi del que depende todo el sistema). Los LEDs sí pueden ir directo del rail de la Pi (consumo despreciable).
6. **Objetivo nuevo (pedido explícito del docente, agregado tarde):** investigar si conviene procesar el modelo 100% en el edge (Pi) o derivar parte del procesamiento al host externo, en función de la cantidad de elementos a analizar (throughput). Esto es medible sin instrumentación nueva — los timestamps de `eventos` ya alcanzan. Candidata a ADR 6, todavía sin definir.

## Estado actual (resumen — detalle semana a semana en `BITACORA.md`)

- **Walking skeleton de octubre: logrado.** Primer despliegue real con Ansible contra una Pi física y primera validación end-to-end (cámara → modelo → MQTT → SQLite → dashboard) con hardware real, no solo con datos fake ni Docker.
- **La confianza del modelo da sistemáticamente baja con objetos reales** (no es un bug: se revisó el preprocesamiento — color, resize, escalado, cuantización — y está correcto). La causa real es que el modelo **nunca se reentrenó con datos propios** (fotos del gabinete, clase `organico`, negativos para `ninguno`) — sigue siendo TrashNet puro. Esto es la ruta crítica real hoy, no el hardware ni el backend.
- **Detección calibrada contra cámara real** (`PARAMETROS` en `raspberry/ecosort_pi.py`, con el motivo de cada cambio documentado inline): tiempos de quietud/espera relajados, `umbral_conf` bajado como parche explícito (trade-off documentado, no una mejora real de confianza), y un recorte centrado del cuadro (ROI) para enfocar el análisis.
- **Compuertas reales conectadas al flujo de detección:** `servos.py` (antes solo en la rama `Mica`) ya está en `main`, con el hook en `ecosort_pi.py` resolviendo la compuerta por el mismo contrato que usa el evento (`compuerta_de`/`producto_de` de `clases.py`, no un diccionario propio). `accionado: true` solo cuando el servo se mueve de verdad. **Falta probar contra el hardware físico** (protoboard) — el código nunca corrió con un GPIO real todavía.
- **Dashboard con gráficos** sobre `/api/estadisticas/*` (Chart.js): por clase con la pureza real de orgánico (genuino vs. incierto), evolución diaria, patrón horario, con auto-refresh.
- `docs/backlog.md` se eliminó: duplicaba el seguimiento de `BITACORA.md` y quedaba desactualizado en paralelo — el tablero de tareas del equipo vive solo en `BITACORA.md`, no hay un segundo lugar para buscarlo.
- **Lo que más pesa como pendiente:** nada del lado de ML arrancó todavía — fotos propias, reentrenar, y documentar la validación (`docs/validacion.md`, matriz de confusión) es el entregable de noviembre que sigue en cero.

## Alcance: qué entra en cada entrega

- **Octubre — "walking skeleton" (logrado):** el pipeline completo end-to-end funcionando aunque cada parte esté poco desarrollada (modelo baseline, compuertas simuladas o parciales, dashboard con tabla simple). El orden de arranque fue: congelar `schema/eventos.sql` primero → backend arma generador de eventos fake + adaptador + dashboard → hardware valida timing/wiring contra esas filas fake → ML reemplaza el generador fake por el modelo real en cuanto esté exportado.
- **Noviembre — sistema integrado:**
  - precisión de clasificación **validada empíricamente** (matriz de confusión + metodología documentada — **sin empezar, es el riesgo real hoy**);
  - las 5 compuertas funcionando (**código conectado, falta probar contra hardware real**, y la de metal todavía no tiene servo físico);
  - manejo de baja confianza, deriva a orgánico, trade-off de contaminación cruzada documentado (**hecho**, ver `PARAMETROS` en `ecosort_pi.py` y `BITACORA.md`);
  - todo corriendo como servicio `systemd` con reinicio automático (**hecho**, vía Ansible + ADR 0006);
  - documentación a nivel "maqueta replicable", BOM + wiring + montaje (**parcial** — falta actualizar el BOM y fotos del montaje final).
- **Fuera de alcance salvo que sobre tiempo:** Coral accelerator, Grafana, Prometheus/alerting activo, soporte multi-dispositivo real (N Pis), entrenamiento desde cero.

## Estructura del repo

**Confirmado que existe hoy** (verificar igual, puede haber cambiado):
```
2026-g5-ecosort/
├── README.md
├── BITACORA.md                    # bitácora fechada, pedido explícito de cátedra — fuente única del historial
├── CLAUDE.md / AGENTS.md          # este archivo (symlink entre los dos nombres)
├── docs/                          # Plan de Proyecto, ADRs, guía de instalación de la Pi, material de presentación
├── vision/                        # entrenamiento del modelo (dataset, train/evaluate/export, notebook Colab)
├── raspberry/                     # corre EN la Pi: captura + inferencia + detección + servos + publicación MQTT
│   ├── ecosort_pi.py              # loop principal: cámara, detección, abre la compuerta, publica
│   ├── deteccion.py               # máquina de estados pura (ADR 0009), sin cámara ni GPIO — se testea sola
│   ├── servos.py                  # control de los servos por GPIO (gpiozero) — sin probar en hardware real
│   └── clases.py                  # resuelve etiqueta del modelo -> clase de producto -> compuerta (schema/clases.json)
├── host/                          # corre en el host cliente/servidor, NO en la Pi; se despliega con Docker Compose (ADR 0007)
│   ├── docker-compose.yml         # adapter + dashboard; docker-compose.dev.yml suma un broker local para trabajar sin Pi
│   ├── adapter/                   # MQTT -> SQLite, único INSERT real (ADR 0003)
│   └── dashboard/
│       ├── backend/                # http.server + sqlite3 (sin framework); sirve la API + el panel
│       └── frontend/               # HTML/CSS/JS estáticos + Chart.js (CDN) para los gráficos
├── schema/eventos.sql             # fuente canónica del schema — la leen adapter/ y dashboard/backend/, no la copies inline
└── infra/ansible/                 # instala y despliega la Pi (Mosquitto, cámara, entorno, código, servicio systemd)
```

`vision/` reemplaza a `software_detección/TrashNate` (eliminado — era la CNN entrenada desde cero, contradecía la ADR 0001) y a `software_detección/MobileNetV2` (el notebook se movió a `vision/notebooks/`). Detalle del layout de `vision/` en su propio `README.md`, no lo dupliques acá.

`raspberry/` y `host/` **ya están separados como procesos independientes** — no es más una decisión pendiente. Originalmente (rama `Mica`, mergeada) todo vivía junto en `raspberry/dashboard.py`, corriendo entero en la Pi por `localhost` como prueba de integración (MQTT ni cruzaba red). Eso se separó: `raspberry/` quedó con lo que necesita hardware de la Pi (cámara, y ahora GPIO), `host/adapter/` y `host/dashboard/backend/`+`frontend/` son 3 procesos independientes entre sí (ver `host/README.md` para el porqué). Firmware (servos/GPIO) tiene código integrado pero **sin validar contra hardware real**; Grafana (secundario, ver ADR 0005) sigue sin empezar.

Nomenclatura: le decimos `host/`, no `backend/` — coincide con la etiqueta del diagrama de arquitectura del README ("💻 Host cliente/servidor").

## CI

Un job por dominio, gateado por qué carpetas tocó el PR (`changes`, vía `dorny/paths-filter`): `vision` (build + lint + smoke del entrenamiento), `host` (lint, tests de `estadisticas.py`, `compose config`, smoke del adapter+dashboard), `contrato` (tests de `schema/` y de `deteccion.py`), `entrega` (chequea el formato de los PDF de `docs/entregas/` con `prolijito`, solo al promover a una rama `entrega_*`), `ansible` (sintaxis + tests de la plantilla del servicio systemd). `ci-ok` agrega todo y es el único *required status check* — nunca marcar como required un job individual que se puede skipear (queda pending para siempre). Nada que dependa de GPIO/servo/cámara real corre en el runner; eso se valida a mano contra la Pi y se registra en `BITACORA.md`.

## Convenciones

- Rama por dominio (`vision/...`, `firmware/...`, `backend/...`, `frontend/...`), PR + al menos 1 review contra `main` protegida.
- Cambios a `schema/eventos.sql` (y a `schema/clases.json`): review cruzado de los 3 integrantes, sin excepción.
- Cualquier decisión de arquitectura nueva o revertida: documentarla como ADR en `docs/adr/`, no solo en un commit message.
- Nada de credenciales/tokens en el repo — la red del proyecto es una LAN cerrada sin exposición externa (el dashboard MVP no tiene auth, es aceptable en ese contexto, no lo es si el dashboard se expone a internet).
- Evitar duplicar seguimiento o documentación en dos archivos a la vez (pasó con `docs/backlog.md` vs. `BITACORA.md`, y con el schema SQL copiado inline acá): un dato, una fuente única, el resto apunta ahí.
