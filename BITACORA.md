
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

### Pendiente para Semana 3

- Continuar con las pruebas y selección del modelo de detección de residuos.
- Integrar el modelo seleccionado al entorno de ejecución de la Raspberry Pi.
- Avanzar con la implementación del circuito de alimentación y las pruebas de los componentes de hardware.
- Continuar con la documentación del informe y actualizar los modelos de MVP definidos para las distintas instancias del proyecto.