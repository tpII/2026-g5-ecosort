# 2026-g5-ecosort — EcoSort

![EcoSort — Clasificador de Residuos Inteligente](docs/banner.png)


**Taller de Proyecto II 2026 — Grupo G5**

Clasificador automático de residuos en 4 categorías (plástico, papel, vidrio,
orgánico) basado en visión por computadora sobre Raspberry Pi 3, con un
mecanismo físico de 4 compuertas y un pipeline de datos hacia un dashboard de
monitoreo.

> **Estado del repositorio:** fin de Semana 3 — pipeline funcionando de
> punta a punta: modelo (`vision/`, MobileNetV2 desplegado) → Raspberry Pi
> (`raspberry/`, captura + inferencia + MQTT + dashboard) → guía de
> instalación. Roles del equipo repartidos por área (ver tabla de Equipo).

---

## Equipo

| Integrante | usuario | área |
|---|---|---|
| Francisco Estrada | `festradax07` | Backend y comunicación (MQTT, adaptador, schema, CI) |
| Micaela Taini | `mikitalinda` | Modelo (`vision/`, datos, entrenamiento) |
| David Alvarez | `davidalvarezok` | Firmware (servos/GPIO) y frontend del dashboard |

Docente/cátedra: seguimiento de decisiones (ver ADRs con estado *Pendiente
confirmar con el docente*).

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
        SERVOS["⚙️ <br/>Servos x4"]
        INF["🐍 <br/> INFERENCIA<br/>TFLite · control GPIO x4"]
        MOSQ["📡 <br/>MOSQUITTO<br/>Broker MQTT"]
        NODEEXP["📈 <br/> NODE_EXPORTER<br/>cpu · ram · tmp"]

        CAM --> INF
        INF -->|GPIO x4| SERVOS
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
  **4 compuertas** (una por clase, cada una con su servo SG90, las 4 arrancan
  cerradas) y la Raspberry Pi 3 en el interior.
- **Inferencia:** modelo de clasificación de 4 clases exportado a **TFLite
  int8**, obtenido por *fine-tuning* sobre un modelo preentrenado con una
  herramienta drag-and-drop (a confirmar con el docente).
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

La Pi arma su propia red en modo Access Point: `192.168.20.0/28` (14 hosts
usables), Pi en `.1`, host cliente/servidor en `.2`. El tráfico MQTT nunca
sale de esta red, por lo que se acepta operar **sin TLS ni autenticación**.

---

## Modelo — [`vision/`](vision/)

Transfer learning (ADR 0001) sobre el dataset público
[TrashNet](https://github.com/garythung/trashnet) (`vision/data/trashnet/`,
6 clases: cardboard, glass, metal, paper, plastic, trash — todavía sin
mapear a las 4 clases finales del producto, ver `vision/classes.py`).
Backbone por defecto: **MobileNetV2 224px**, el mismo que está desplegado
en `raspberry/modelo/`; `mobilenetv3small` queda como alternativa para
comparar en igualdad de condiciones. Se entrena en Colab
([`vision/notebooks/entrenar_colab.ipynb`](vision/notebooks/entrenar_colab.ipynb))
o local/Docker — ver [`vision/README.md`](vision/README.md).

## Raspberry Pi — [`raspberry/`](raspberry/)

Runtime desplegado: captura por cámara USB, inferencia TFLite, conteo de
objetos por diferencia de fondo, publicación MQTT (Mosquitto) y un
dashboard propio (SQLite + panel web) que se suscribe a esos eventos. Guía
completa de puesta en marcha:
[`docs/guia-instalacion-raspberry.md`](docs/guia-instalacion-raspberry.md).

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
│   │   └── 0005-dashboard-propio-reemplaza-grafana.md
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
├── raspberry/                                # runtime desplegado en la Pi
│   ├── modelo/                              # ecosort_int8.tflite, ecosort_fp32.tflite, labels.txt
│   ├── ecosort_pi.py, inferencia_pi.py, ecosort_mqtt.py, dashboard.py, vista_en_vivo.py
│   └── mosquitto/ecosort.conf
└── schema/eventos.sql
```

Referenciados en la documentación pero **aún no versionados**:
`schema/eventos.sql`, el código del dashboard propio (framework a definir,
ver [ADR 0005](docs/adr/0005-dashboard-propio-reemplaza-grafana.md)) y
`docs/validacion.md`.

---

## Decisiones de arquitectura (ADRs)

| # | Decisión | Estado |
|---|---|---|
| [0001](docs/adr/0001-modelo-preentrenado-vs-finetune.md) | Fine-tuning sobre modelo preentrenado (export TFLite int8) en vez de entrenar desde cero | Propuesto — falta confirmar herramienta exacta |
| [0002](docs/adr/0002-plataforma-4-compuertas-collar.md) | Plataforma fija de 4 compuertas (una por clase), reemplaza 3 iteraciones previas | Aceptado |
| [0003](docs/adr/0003-mqtt-sqlite-como-contrato.md) | Transporte MQTT + Mosquitto; persistencia SQLite vía adaptador propio | Aceptado |
| [0004](docs/adr/0004-grafana-vs-dashboard-propio.md) | Grafana (+ Prometheus/node_exporter opcional) en vez de dashboard propio | Rechazada — reemplazada por ADR 0005 |
| [0005](docs/adr/0005-dashboard-propio-reemplaza-grafana.md) | Dashboard propio (Front End) leyendo SQLite + Prometheus, en vez de Grafana — a pedido del docente | Aceptado |

---

## Avances (Semana 3)

- [x] Mergeado el runtime completo de la Raspberry Pi (`raspberry/`): captura por cámara, inferencia TFLite, conteo de residuos, MQTT y dashboard propio — funcionando de punta a punta contra la Pi real.
- [x] Modelo entrenado y desplegado (MobileNetV2, TFLite int8): 31ms de latencia en la Pi, ~79% de accuracy en test (dataset TrashNet, todavía sin la clase orgánico).
- [x] Unificados los dos pipelines de entrenamiento en `vision/`, con MobileNetV2 como backbone por defecto y MobileNetV3Small como alternativa a comparar.
- [x] Repartidos los roles del equipo para lo que sigue (ver tabla de arriba).

## Pendiente para Semana 4

- [ ] Fotos propias del gabinete (con la clase orgánico) para reentrenar — la mejora de precisión más importante pendiente.
- [ ] Cerrar el mapeo de las 6 clases de TrashNet a las 4 compuertas del producto.
- [ ] Firmware: control de los 4 servos por GPIO (bloqueado por hardware, llega en unas semanas).
- [ ] Separar `dashboard.py` en backend (API) y frontend, y congelar el contrato de datos MQTT entre las 3 áreas.

Detalle completo semana a semana en [`BITACORA.md`](BITACORA.md).

Cronograma general: dos tramos de entrega (octubre / noviembre). ML es la ruta
crítica; la observabilidad del dispositivo se aborda recién cerca de la
entrega final.

---

## Bitácora

El seguimiento semanal del proyecto se lleva en [`BITACORA.md`](BITACORA.md).
