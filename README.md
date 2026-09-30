# 2026-g5-ecosort — EcoSort

![EcoSort — Clasificador de Residuos Inteligente](docs/banner.png)


**Taller de Proyecto II 2026 — Grupo G5**

Clasificador automático de residuos en 5 categorías (plástico, papel, vidrio,
orgánico y metal) basado en visión por computadora sobre Raspberry Pi 3, con un
mecanismo físico de 5 compuertas y un pipeline de datos hacia un dashboard de
monitoreo propio.

> **Estado del repositorio:** Semana 5 — pipeline funcionando de punta a punta: modelo (`vision/`,
> MobileNetV2 desplegado y probado en la Pi real) → Raspberry Pi (`raspberry/`, captura +
> detección en cascada + inferencia + MQTT) → host cliente/servidor (`host/`, adapter + dashboard
> con API de estadísticas, procesos separados con Docker Compose). Contrato de eventos v1
> (5 clases y 5 compuertas, ADR 0008) y clase `ninguno` para lo que no es un residuo (ADR 0009)
> aceptados. Lo más reciente (`incierto`, estadísticas, Ansible) **todavía no se probó contra la
> Pi real**, solo con tests y Docker. Roles del equipo repartidos por área (ver tabla de Equipo).

---

## Equipo

| Integrante | usuario | área |
|---|---|---|
| Francisco Estrada | `festradax07` | Backend y comunicación (MQTT, adaptador, schema, CI) |
| Micaela Taini | `mikitalinda` | Modelo (`vision/`, datos, entrenamiento) |
| David Alvarez | `davidalvarezok` | Firmware (servos/GPIO) y frontend del dashboard |

Docente/cátedra: Gastón Maron, seguimiento de decisiones vía los ADR de `docs/adr/`.

---

## Visión general del sistema


```mermaid
---
config:
  theme: redux
---
flowchart LR
     subgraph PI["🍓 Raspberry Pi 3 — modo Access Point · 192.168.20.1"]
        CAM["📷 <br/> Cámara USB"]
        SERVOS["⚙️ <br/>Servos x5"]
        INF["🐍 <br/> INFERENCIA<br/>TFLite · control GPIO x5"]
        MOSQ["📡 <br/>MOSQUITTO<br/>Broker MQTT"]
        NODEEXP["📈 <br/> NODE_EXPORTER<br/>cpu · ram · tmp"]

        CAM --> INF
        INF -->|GPIO x5| SERVOS
        INF -->|event!| MOSQ
    end

    subgraph HOST["💻 Host cliente / servidor · 192.168.20.2"]
        ADAPTER["🐍 <br/>ADAPTER MQTT<br/>paho-mqtt<br/>suscriber MQTT"]
        SQLITE["🗄️ <br/> SQLITE DB<br/>persistencia · eventos"]
        PROM["🔥 <br/>PROMETHEUS<br/>time series metrics"]
        DASH["🖥️ <br/>Dashboard Sistema +<br/>Métricas + Alertas"]
        ADAPTER -->|Insert| SQLITE
        SQLITE -->|Datasource| DASH
        PROM -->|Datasource| DASH
    end

    MOSQ -->|"MQTT · WiFi (AP)"| ADAPTER
    NODEEXP -->|"Scrape · WiFi (AP)"| PROM
```

Versión renderizada: [`docs/arquitectura-mmd.png`](docs/arquitectura-mmd.png).
El diagrama original en drawio queda como referencia histórica en
[`docs/diagramas/`](docs/diagramas/).

### Componentes

- **Producto (dispositivo):** gabinete con cámara, tolva, plataforma fija de
  **5 compuertas** (una por clase — la quinta, metal, la suma el equipo en
  noviembre; en octubre las 5 salidas se simulan con LEDs, ADR 0008) y la
  Raspberry Pi 3 en el interior.
- **Inferencia:** *fine-tuning* de MobileNetV2 (código propio en
  [`vision/`](vision/), no una herramienta drag-and-drop, ver ADR 0001),
  exportado a **TFLite int8**. Antes de publicar un evento, una máquina de
  estados (`raspberry/deteccion.py`, ADR 0009) exige que el objeto quede
  quieto y tenga tamaño de residuo, y descarta lo que el modelo ve como
  `ninguno` (una mano, una cara, un animal).
- **Transporte:** **MQTT** con **Mosquitto** como broker corriendo en la
  propia Pi.
- **Persistencia:** **SQLite** (`eventos.db`), poblada por un script
  adaptador (Python + `paho-mqtt`) suscripto al tópico de eventos.
- **Visualización:** **dashboard propio (Front End)**, leyendo el dato de
  negocio desde SQLite y, como segundo datasource, Prometheus para la salud
  del dispositivo — reemplaza a Grafana a pedido del docente (ver
  [ADR 0005](docs/adr/0005-dashboard-propio-reemplaza-grafana.md)).
- **Observabilidad del dispositivo (EXTRA, opcional, fase final):**
  `node_exporter` en la Pi + **Prometheus** en el host externo, como
  datasource del dashboard propio, con reglas de alerting a reimplementar
  (staleness de `eventos`, `up == 0`, temperatura ~80 °C, CPU sostenida alta).

### Red

**Diseño:** la Pi arma su propia red en modo Access Point, `192.168.20.0/28` (14 hosts usables),
Pi en `.1`, host cliente/servidor en `.2`. El tráfico MQTT nunca sale de esta red, por lo que se
acepta operar **sin TLS ni autenticación**.

**Hoy:** el modo Access Point todavía no está implementado (ni a mano ni en
[`infra/ansible/`](infra/ansible/)) — se prueba compartiendo la red que ya tiene internet (ver
`docs/guia-instalacion-raspberry.md`, "Limitaciones conocidas").

---

## Modelo — [`vision/`](vision/)

Transfer learning (ADR 0001) sobre el dataset público
[TrashNet](https://github.com/garythung/trashnet) (`vision/data/trashnet/`,
6 clases nativas: cardboard, glass, metal, paper, plastic, trash), mapeadas
a las 5 clases de producto **en el borde** (`schema/clases.json`, ADR 0008),
no en el entrenamiento — ver `vision/classes.py`. Falta la clase `organico`
propia (TrashNet no la tiene) y los negativos para `ninguno` (ADR 0009).
Backbone por defecto: **MobileNetV2 224px**, el mismo que está desplegado
en `raspberry/modelo/`; `mobilenetv3small` queda como alternativa para
comparar en igualdad de condiciones. Se entrena en Colab
([`vision/notebooks/entrenar_colab.ipynb`](vision/notebooks/entrenar_colab.ipynb))
o local/Docker — ver [`vision/README.md`](vision/README.md).

## Raspberry Pi — [`raspberry/`](raspberry/)

Lo que corre **en la Pi**: captura por cámara USB, inferencia TFLite,
conteo de objetos por diferencia de fondo y publicación MQTT (Mosquitto).
Ya no incluye el dashboard — ver la sección siguiente. Guía completa de
puesta en marcha:
[`docs/guia-instalacion-raspberry.md`](docs/guia-instalacion-raspberry.md).

## Host cliente/servidor — [`host/`](host/)

Lo que corre **fuera de la Pi**, en la misma LAN: el adapter (MQTT → SQLite,
único INSERT real, ADR 0003) y el dashboard (backend + frontend, lee esa
misma base). Dos procesos independientes, no un monolito — ver
[`host/README.md`](host/README.md) para el porqué y cómo correrlos.

---

## Documentos y entregas

| Documento | Contenido |
|---|---|
| [`docs/Plan de Proyecto-G5.pdf`](<docs/Plan de Proyecto-G5.pdf>) | Plan de Proyecto entregado (requerimientos, objetivos, alcance) |
| [`docs/presentaciones/EcoSort_Presentacion.pdf`](docs/presentaciones/EcoSort_Presentacion.pdf) | PowerPoint de la presentación del proyecto |
| [`docs/circuito-de-alimentacion/Circuito de alimentación.pdf`](<docs/circuito-de-alimentacion/Circuito de alimentación.pdf>) | Circuito de alimentación de Raspberry Pi, servos y demás componentes |
| [`docs/modelo-ideas/varios-prototipos-propuestos.pdf`](docs/modelo-ideas/varios-prototipos-propuestos.pdf) | Prototipos de maqueta evaluados para el gabinete |

---

## Estructura del repositorio

```
.
├── README.md
├── BITACORA.md                              # Bitácora semanal del equipo
├── docs/
│   ├── Plan de Proyecto-G5.pdf              # Entrega del Plan de Proyecto
│   ├── arquitectura-mmd.png                 # Render del diagrama Mermaid
│   ├── arquitectura-software.png            # Diagrama de arquitectura (versión anterior)
│   ├── adr/                                 # Architecture Decision Records
│   │   ├── 0001-modelo-preentrenado-vs-finetune.md
│   │   ├── 0002-plataforma-4-compuertas-collar.md
│   │   ├── 0003-mqtt-sqlite-como-contrato.md
│   │   ├── 0004-grafana-vs-dashboard-propio.md
│   │   ├── 0005-dashboard-propio-reemplaza-grafana.md
│   │   ├── 0006-systemd-vs-docker-en-la-pi.md
│   │   ├── 0007-docker-compose-en-el-host.md
│   │   ├── 0008-contrato-de-eventos.md
│   │   └── 0009-deteccion-en-cascada-y-rechazo.md
│   ├── circuito-de-alimentacion/
│   │   └── Circuito de alimentación.pdf
│   ├── diagramas/
│   │   ├── arquitectura.mmd                 # Fuente Mermaid (canónica)
│   │   └── TDP2 - ECOSORT-SYSTEM-DIAGRAM(4).drawio   # Fuente drawio (histórica)
│   ├── modelo-ideas/
│   │   ├── prototipo-vista-general-1.png
│   │   └── varios-prototipos-propuestos.pdf
│   └── presentaciones/
│       └── EcoSort_Presentacion.pdf
├── vision/                                   # entrenamiento del modelo (ver vision/README.md)
│   ├── data/trashnet/                       # dataset TrashNet versionado
│   ├── notebooks/entrenar_colab.ipynb       # entrena en Colab, llama a estos scripts
│   ├── models.py, train.py, evaluate.py, export_tflite.py, webcam_test.py
│   └── Dockerfile, docker-compose.yml       # entrenar/evaluar/exportar reproducible
├── raspberry/                                # corre EN la Pi
│   ├── modelo/                              # ecosort_int8.tflite, ecosort_fp32.tflite, labels.txt
│   ├── ecosort_pi.py, inferencia_pi.py, ecosort_mqtt.py, vista_en_vivo.py
│   ├── deteccion.py, clases.py             # cuándo y si analizar (ADR 0009); vocabulario de clases
│   ├── tests/test_deteccion.py
│   └── mosquitto/ecosort.conf
├── host/                                     # corre en el host cliente/servidor, no en la Pi
│   ├── docker-compose.yml                   # adapter + dashboard (+ docker-compose.dev.yml: broker local)
│   ├── adapter/adapter.py                   # MQTT -> SQLite, único INSERT real
│   └── dashboard/
│       ├── backend/backend.py, estadisticas.py  # API + panel; agregaciones para graficar
│       └── frontend/index.html
├── schema/                                   # el contrato de eventos (docs/contrato-mqtt.md)
│   ├── evento.schema.json, clases.json, eventos.sql
│   └── tests/test_contrato.py
└── infra/ansible/                            # instalar/desplegar la Pi (ver su README.md)
    ├── pi.yml, tasks/*.yml                   # Mosquitto, cámara, entorno Python, despliegue, servicio
    └── templates/ecosort_pi.service.j2       # reemplaza al nohup manual (ADR 0006)
```

Referenciado en la documentación pero **aún no versionado**: `docs/validacion.md`
(la metodología de validación del modelo, entregable de noviembre). El dashboard propio ya existe,
sin framework todavía (ver [ADR 0005](docs/adr/0005-dashboard-propio-reemplaza-grafana.md)).

---

## Decisiones de arquitectura (ADRs)

| # | Decisión | Estado |
|---|---|---|
| [0001](docs/adr/0001-modelo-preentrenado-vs-finetune.md) | Fine-tuning de MobileNetV2 con código propio (export TFLite int8), no una herramienta drag-and-drop | Aceptado |
| [0002](docs/adr/0002-plataforma-4-compuertas-collar.md) | Plataforma fija de compuertas (una por clase), reemplaza 3 iteraciones previas — ampliada por la ADR 0008 a 5 | Aceptado |
| [0003](docs/adr/0003-mqtt-sqlite-como-contrato.md) | Transporte MQTT + Mosquitto; persistencia SQLite vía adaptador propio | Aceptado |
| [0004](docs/adr/0004-grafana-vs-dashboard-propio.md) | Grafana (+ Prometheus/node_exporter opcional) en vez de dashboard propio | Rechazada — reemplazada por ADR 0005 |
| [0005](docs/adr/0005-dashboard-propio-reemplaza-grafana.md) | Dashboard propio (Front End) leyendo SQLite + Prometheus, en vez de Grafana — a pedido del docente | Aceptado |
| [0006](docs/adr/0006-systemd-vs-docker-en-la-pi.md) | Servicios en la Pi (Mosquitto, inferencia, node_exporter) corren con systemd, no Docker | Aceptado |
| [0007](docs/adr/0007-docker-compose-en-el-host.md) | Servicios del host (adapter, dashboard, luego Prometheus) se despliegan con Docker Compose | Aceptado |
| [0008](docs/adr/0008-contrato-de-eventos.md) | Contrato de eventos v1: 5 clases de producto y 5 compuertas (metal incluido; LEDs en octubre), validación en el adapter | Aceptado (26/9) |
| [0009](docs/adr/0009-deteccion-en-cascada-y-rechazo.md) | Detección en cascada (quietud, tamaño, modelo) y clase `ninguno` para rechazar lo que no es un residuo (manos, caras, animales) | Aceptado (26/9) |

---

## Avances (Semana 3 y 4)

- [x] Mergeado el runtime completo de la Raspberry Pi (rama `Mica`, integración de prueba): captura por cámara, inferencia TFLite, conteo de residuos, MQTT y dashboard — funcionando de punta a punta contra la Pi real.
- [x] Modelo entrenado y desplegado (MobileNetV2, TFLite int8): 31ms de latencia en la Pi, ~79% de accuracy en test (dataset TrashNet, todavía sin la clase orgánico).
- [x] Unificados los dos pipelines de entrenamiento en `vision/`, con MobileNetV2 como backbone por defecto y MobileNetV3Small como alternativa a comparar.
- [x] Separado el dashboard en procesos independientes (`host/adapter/` + `host/dashboard/`), sacándolo de la Pi — la integración anterior corría todo por `localhost`, sin que MQTT cruzara red de verdad. ADR 0006 (systemd en la Pi) y ADR 0007 (Docker Compose en el host) documentadas, y `host/` ya se levanta con `docker compose up`.
- [x] Contrato de eventos v1 definido y verificado ([`docs/contrato-mqtt.md`](docs/contrato-mqtt.md), ADR 0008): 5 clases y 5 compuertas (el metal se suma; en octubre las salidas se simulan con LEDs), JSON Schema versionado, validación en el adapter con registro de rechazos y tests de contrato en CI.
- [x] Detección robusta (ADR 0009): una máquina de estados exige que el objeto quede quieto y tenga tamaño de residuo antes de analizarlo, y la nueva clase `ninguno` permite rechazar lo que no es un residuo sin ensuciar los eventos. En una comparación sintética pasó de 4 eventos falsos sobre 6 a 0, y de 285 a 15 inferencias. Umbrales todavía sin calibrar con la cámara real.
- [x] Repartidos los roles del equipo para lo que sigue (ver tabla de arriba).

## Avances (Semana 5)

- [x] CI de formato de entregas: los PDF de `docs/entregas/` se chequean (fuente, tamaño, interlineado) al promoverlos de `main` a una rama `entrega_N`, con la skill de la cátedra ([`ia-guidelines-taller`](https://github.com/tpII/ia-guidelines-taller)).
- [x] `incierto` implementado en el contrato (ADR 0002 + 0009): un objeto de baja confianza o cuadros inconsistentes ahora publica un evento igual, forzado a `clase: "organico"` (con `motivo` para distinguirlo de un orgánico genuino), en vez de no generar nada.
- [x] API de estadísticas del dashboard (`/api/estadisticas/*`): cantidad y confianza por clase, pureza de orgánico, latencia de inferencia, y series por día / hora del día para graficar — la base para los contadores y gráficos propios (la observabilidad de infraestructura con Prometheus/Grafana sigue siendo un objetivo aparte, para después).
- [x] Ansible para la Pi (`infra/ansible/`): empaqueta la instalación manual de Mosquitto, la cámara, el entorno de Python/TFLite, copiar `raspberry/` + `schema/`, y un servicio `systemd` para `ecosort_pi.py` con reinicio automático (ADR 0006) en vez del `nohup ... &` de la guía. Falta correrlo contra la Pi real.
- [x] ADR 0001 corregida: describía una herramienta drag-and-drop que nunca se usó; ahora documenta lo que realmente se implementó (fine-tuning con código propio en `vision/`).
- [x] Configuración por `.env`/`EnvironmentFile`, no hardcodeada: `host/.env.example` (Docker Compose lo lee solo) y `/etc/ecosort/ecosort_pi.env` (generado por Ansible, `EnvironmentFile` del servicio). De paso se encontró un bug real: el `.service` de `ecosort_pi` seteaba `ECOSORT_BROKER` como variable de entorno, pero el script nunca la leía — no hacía nada.

## Pendiente para Semana 6

- [ ] Fotos propias del gabinete (con orgánico, latas/aluminio para metal, y **negativos para la clase `ninguno`**: manos, caras, animales, plataforma vacía) para reentrenar — la mejora de precisión más importante pendiente.
- [ ] Calibrar los umbrales de la detección con la cámara real y hacer la sesión de "el gracioso" (10 minutos intentando engañarlo) midiendo eventos falsos.
- [ ] Firmware: 5 salidas por GPIO configurables — LEDs en octubre, servos en noviembre (bloqueado por hardware, llega en unas semanas) — y enganchar las señales de la detección a LEDs y sonidos que le den expresión a la papelera (objeto no reconocido, cayó, se trabó).
- [ ] Sumar a la lista de materiales el sensor de distancia (ToF), un buzzer o parlante pequeño y LEDs de estado.
- [ ] Quinta compuerta (metal): reservar el hueco en la maqueta y comprar el quinto SG90 con el resto del pedido; avisar a la cátedra (el Plan entregado dice 4).
- [ ] Correr el playbook de Ansible (`infra/ansible/`) contra una Pi real y registrar el resultado en `BITACORA.md`.
- [ ] Arrancar el frontend del dashboard (hoy es una tabla y barras estáticas) — ya tiene de dónde traer los gráficos y contadores.
- [ ] Sacar `docs/entregas/Plan de Proyecto-G5.pdf` de `main` y armar el ruleset de `entrega_*` en GitHub.

Detalle completo semana a semana en [`BITACORA.md`](BITACORA.md).

Cronograma general: dos tramos de entrega (octubre / noviembre). ML es la ruta
crítica; la observabilidad del dispositivo se aborda recién cerca de la
entrega final.

---

## Bitácora

El seguimiento semanal del proyecto se lleva en [`BITACORA.md`](BITACORA.md).
