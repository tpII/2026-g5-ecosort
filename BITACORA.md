
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
- **Contrato de eventos v1** (`docs/contrato-mqtt.md`, ADR 0008). La revisión mostró que el contrato era implícito y no se cumplía: el runtime real publicaba las etiquetas crudas de TrashNet con `compuerta` en `null` aunque el schema decía otra cosa, el mapeo a producto estaba duplicado y discrepaba entre archivos (`trash`, `metal`), y el adapter guardaba cualquier cosa (una clase `banana`, una confianza `"abc"`, una compuerta 99). Se decidió: **5 clases y 5 compuertas** (el metal se suma como clase propia por ser muy reciclable y ya estar en el modelo; la quinta compuerta la pone el equipo en noviembre y **en octubre las cinco salidas se simulan con LEDs**), el vocabulario de producto se resuelve en la Pi (`clase` + `clase_modelo` + `compuerta` + `accionado`), y todo queda en fuentes únicas versionadas (`schema/clases.json`, `schema/evento.schema.json`, `schema_version: 1`). El adapter ahora valida y guarda los mensajes inválidos en `eventos_rechazados` con el motivo, y 18 tests de contrato (sin red ni Docker) corren en CI. Probado de punta a punta con el publicador real de la Pi contra el adapter en contenedor: las 5 clases llegan, 0 rechazados. Queda **pendiente el review de los 3** (regla para `schema/`).
- **Detección robusta** (ADR 0009). La preocupación: que una mano, una cara o un animal terminen contados como residuo. Medimos: el modelo es de clases cerradas (con 9 entradas sintéticas que no eran residuos, 6 superaron el umbral de confianza; la piel dio `cardboard` 0,62), la confianza no refleja el enfoque, y un umbral absoluto de nitidez es frágil (con 2 niveles de ruido de sensor deja pasar el 100 % de lo desenfocado). Se armó `raspberry/deteccion.py`, una máquina de estados pura y con 19 tests (verificados con mutaciones: rompiendo la lógica a propósito fallan los que corresponden): presencia, luego **quietud ~1 s**, luego tamaño plausible, y recién ahí se clasifican los 5 cuadros más nítidos decidiendo por el promedio de probabilidades. Se agregó la clase **`ninguno`** (descartes en `schema/clases.json`): lo que no es un residuo nunca se publica, así que no ensucia los eventos ni la base; y la decisión distingue aceptado, incierto y descartado. Integrada en `ecosort_pi.py` y probada con el `Detector` real contra una cámara falsa: 4 eventos falsos sobre 6 antes, 0 ahora, y 15 inferencias en vez de 285. Sin la clase `ninguno` un objeto quieto, de tamaño plausible y clasificado con confianza alta todavía pasa, por eso hay que juntar los negativos. **Los umbrales están sin calibrar con la cámara real.** Las señales de la máquina (presente, aceptado, descartado, retirado, no retirado) quedan como interfaz para que el firmware las convierta en luces y sonidos expresivos (idea del equipo: "objeto no reconocido", "cayó", "se trabó"); y se recomienda un sensor de distancia como disparador.

### Pendiente para Semana 4

- Review de los 3 del contrato v1 y de la detección (ADR 0008 y 0009) antes de mergearlos.
- Juntar fotos propias (50–100 por clase, incluyendo orgánico y latas/aluminio para metal) y los negativos para `ninguno` (manos, caras, animales, plataforma vacía; más datasets públicos de personas y animales), y reentrenar — es la mejora de precisión más importante que queda pendiente.
- Calibrar los umbrales de la detección con la cámara real y hacer la sesión de "el gracioso" (10 minutos intentando engañarlo), midiendo eventos falsos por sesión y por hora con fondo vacío.
- Firmware: 5 salidas por GPIO configurables (LEDs en octubre, servos en noviembre), publicando `accionado: true` al activarlas, y luces y sonidos expresivos a partir de las señales de la detección; sumar a la lista de materiales el sensor de distancia (ToF), un buzzer o parlante pequeño y LEDs de estado.
- Quinta compuerta (metal): reservar el hueco en la maqueta, comprar el quinto SG90 con el resto del pedido y avisar a la cátedra (el Plan entregado dice 4 compuertas).
- Comparar MobileNetV2 contra MobileNetV3Small en igualdad de condiciones y decidir con datos (accuracy, tamaño, latencia real en la Pi) cuál queda como backbone definitivo.
- Armar las unit files de `systemd` para `ecosort_pi.py` en la Pi (ADR 0006), y sumar Prometheus como servicio del compose de `host/` cuando exista `node_exporter`.
- Definir cómo se expresa la baja confianza en el contrato (la ADR 0002 dice que abre la compuerta de orgánico; hoy no genera evento).