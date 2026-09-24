
# Bitácora de Proyecto - ECOSORT - G5

## [2026-09-1] - Semana 1

* Configuración del repositorio en GitHub y validación de permisos del equipo.

### Verificación de Accesos y Entorno
* [x] **Francisco Estrada:** Acceso verificado y commit inicial de prueba realizado.
* [x] **Micaela Taini:** Acceso verificado y commit inicial de prueba realizado.
* [x] **David Alvarez:** Acceso verificado y commit inicial de prueba realizado.
## [2026-09-6)] - Fin Semana 1
### Modelo físico (PRODUCTO)

- Definido y cerrado con el docente: **plataforma fija de 4 compuertas (una por clase)**, las 4 arrancan cerradas. Reemplaza las iteraciones anteriores (torreta rotativa de un solo servo, rampa con aletas distribuidas, rampa única con estación de 3 aletas).
- Confirmado con la cátedra: se pueden usar **4 servos SG90**, no 3 — esto fue lo que permitió pasar de "3 compuertas + 1 default abierta" a las 4 cerradas.
- Diagrama del gabinete armado (vista isométrica, con cámara, tolva, plataforma de 4 compuertas y Pi interior) — ver `docs/modelo`.

### Arquitectura de software

- Pipeline de datos definido de punta a punta: Raspberry Pi 3 (modo Access Point) → captura + inferencia TFLite + control GPIO (4 servos) → publica evento por MQTT → Mosquitto (broker local, en la Pi) → adaptador Python (`paho-mqtt`, en un host externo) → SQLite (`eventos.db`) → Grafana.
- Sumada una segunda parte del sistema **observabilidad del dispositivo**, en paralelo al dato de negocio: `node_exporter` en la Pi + Prometheus en el host externo, como segundo datasource de Grafana. Reglas de alerting definidas: staleness de la tabla `eventos`, `up == 0` (target down), temperatura sostenida alta (~80°C, umbral de throttling de la Pi 3), CPU sostenida alta. (NOTA: Esta parte solo se empezará a trabajar cercano a la entrega final, cuando el modelo CORE esté completamente operativo)
- Decisión de transporte: MQTT + Mosquitto, pasaje de mensajes entre hosts de manera ligera, requiere un adapter de parte del destinatario que se Suscriba a la cola del broker. 
- Decisión de visualización: Evaluando la creación de un dashboard en FLASK, acabamos encontrando la herramienta de Monitoreo/Observabilidad Grafana, la cual cumple con todo lo que necesitariamos para poder realizar en la demo, sin la necesidad de tener que crear un sistema Front End desde 0, enfocandonos asi en la funcionalidad del dashboard en vez del diseño.
- 4 ADRs redactadas y versionadas en `docs/adr/`: modelo preentrenado vs. fine-tuning, mecanismo físico, contrato MQTT+SQLite, Grafana/Prometheus vs. desarrollo propio.
- Diagrama de arquitectura de software armado dibujado a mano en drawio, agregando direccionamiento IP real de la red que arma la Pi en modo AP (`192.168.20.0/28`, Pi en `.1`, host cliente/servidor en `.2`) — validado el subnetting (14 hosts usables en un `/28`).

### Pendiente para Semana 2

- Definir circuito de Alimentación para los componentes de Hardware.
- Hacer pruebas de los modelos a utilizar de manera local dentro del repositorio.
- Definir en el `docs/plan-de-proyecto.pdf` los modelos de mvp con los que vamos a trabajar en las distintas instancias del proyecto.

## [2026-09-13] - Semana 2

### Avances del proyecto

- Se avanzó en la elaboración del informe del proyecto, trabajando sobre la definición y documentación de los **requerimientos**, los **objetivos principales** y el alcance del sistema.
- Se trabajó en la definición del **circuito de alimentación** para los distintos componentes de hardware, considerando las necesidades de alimentación de la Raspberry Pi, los servos y los demás componentes involucrados.
- Se realizaron pruebas con **distintos modelos y herramientas de detección y clasificación de residuos**, evaluando su comportamiento en diferentes escenarios.
- Se probaron los modelos utilizando imágenes con **distintos tipos de fondos, iluminación y disposición de los residuos**, con el objetivo de analizar su capacidad de detección en condiciones similares a las que tendrá el sistema real.
- A partir de estas pruebas se comenzó a comparar el desempeño de las distintas alternativas para definir qué solución resulta más adecuada para integrar posteriormente en la Raspberry Pi y en el pipeline de detección del proyecto.
- Se realizó la entrega del Plan de Proyecto, junto con la creación de un power point y un video presentación del Proyecto. 
- se actualizó la arquitectura a un documento .mmd a recomendación del docente.

### Pendiente para Semana 3

- Continuar con las pruebas y selección del modelo de detección de residuos.
- Integrar el modelo seleccionado al entorno de ejecución de la Raspberry Pi.
- Avanzar con la implementación del circuito de alimentación y las pruebas de los componentes de hardware.
- Continuar con la documentación del informe y actualizar los modelos de MVP definidos para las distintas instancias del proyecto.

## [2026-09-23] - Semana 3

### Avances del proyecto

- **Modelo entrenado y desplegado en la Raspberry Pi real**: transfer learning sobre **MobileNetV2** (ADR 0001), entrenado en Google Colab sobre el dataset TrashNet (6 clases). Exportado a TFLite int8, medido en la Pi 3: **31ms de latencia** (vs. 81ms en fp32, sin pérdida de precisión por la cuantización) y **~79% de accuracy** en el test set — todavía sin la clase orgánico, que TrashNet no tiene.
- **Runtime completo de la Raspberry Pi armado y documentado** (rama `Mica`, mergeada a `main` como PR #1): captura por cámara USB, inferencia TFLite, conteo de residuos por diferencia de fondo (un evento por objeto, se recalibra solo), publicación MQTT (Mosquitto, con reconexión y estado online/offline), y un dashboard propio (SQLite + panel web con conteo en vivo, descarga CSV y reinicio). Todo documentado en una guía de instalación paso a paso (`docs/guia-instalacion-raspberry.md`), con los problemas reales de la puesta en marcha y sus soluciones.
- **Reordenamos y unificamos el código de entrenamiento** en una sola carpeta (`vision/`), que antes estaba repartido en dos pipelines distintos sin conexión entre sí (uno en Colab con MobileNetV2, otro local con MobileNetV3Small). Quedó **MobileNetV2 224px como backbone por defecto** — el mismo que ya corre en la Pi — y MobileNetV3Small como alternativa, para compararlos en igualdad de condiciones (mismo split, mismas épocas) antes de decidir cuál va a producción definitiva.
  - Se eliminó el prototipo viejo (`software_detección/TrashNate/main.py`), una CNN entrenada desde cero que contradecía la ADR 0001.
  - El notebook de Colab se simplificó a un envoltorio delgado que llama al código versionado en `vision/`, en vez de reimplementar el entrenamiento adentro.
  - Se mantuvo y ordenó la infraestructura reproducible que ya existía (Docker, CI con smoke test, matriz de confusión) para que corra igual con cualquier backbone.
- **Repartimos las áreas del equipo** para lo que sigue: Micaela queda a cargo del modelo (datos propios, mapeo de clases, entrenamiento), Francisco de backend y comunicación (MQTT, adaptador, schema, CI, dashboard backend), y David de firmware (servos/GPIO, todavía bloqueado por hardware que llega en unas semanas) y el frontend del dashboard.
- **Separamos `raspberry/` de `host/`**: lo que se había mergeado como integración de prueba corría todo en la Pi por `localhost` (ni MQTT cruzaba red de verdad). Ahora `raspberry/` tiene solo lo que corre en la Pi (captura, inferencia, publicación MQTT), y `host/adapter/` (MQTT→SQLite, único INSERT, ADR 0003) + `host/dashboard/` (backend + frontend, procesos separados entre sí) corren en el host cliente/servidor — la topología real que ya mostraba el diagrama de arquitectura. De paso, el schema SQLite dejó de estar duplicado inline (había divergido de `schema/eventos.sql`, le faltaba un índice). Documentada la decisión de systemd sin Docker en la Pi (ADR 0006) y, del lado del host, la contraria: Docker Compose (ADR 0007), ya implementado en `host/docker-compose.yml` (con un override para trabajar sin la Pi) y probado de punta a punta con un broker real — de esa prueba salió y se corrigió un bug: el adapter moría si el broker no estaba al arrancar. La prueba quedó como script reproducible (`host/tests/e2e_smoke.sh`, verificado que falla si se reintroduce ese bug) y como job de CI que corre solo cuando cambia `host/`.

### Pendiente para Semana 4

- Juntar fotos propias (50–100 por clase, incluyendo orgánico) y reentrenar — es la mejora de precisión más importante que queda pendiente.
- Cerrar el mapeo de las 6 clases de TrashNet a las 4 compuertas del producto: qué hacer con `metal`, que no tiene compuerta asignada.
- Comparar MobileNetV2 contra MobileNetV3Small en igualdad de condiciones y decidir con datos (accuracy, tamaño, latencia real en la Pi) cuál queda como backbone definitivo.
- Armar las unit files de `systemd` para `ecosort_pi.py` en la Pi (ADR 0006), y sumar Prometheus como servicio del compose de `host/` cuando exista `node_exporter`.
- Congelar el contrato de datos MQTT (versión de schema, mapeo de clases) entre las 3 áreas para poder desarrollar en paralelo sin pisarse.