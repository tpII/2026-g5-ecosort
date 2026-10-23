# ADR 0006 — Servicios en la Raspberry Pi: systemd, no Docker

**Estado:** Aceptado.

## Contexto

En la Pi van a convivir varios procesos de larga duración: Mosquitto (ya
instalado vía `apt`), la inferencia + captura (`ecosort_pi.py`), y más
adelante `node_exporter` (decisión 6 de `CLAUDE.md`). El dashboard y el
adapter MQTT→SQLite no corren acá — viven en `host/`, en la máquina
cliente/servidor, no en la Pi. Hace falta decidir cómo se empaquetan y
supervisan los procesos que sí corren en la Pi: como contenedores Docker,
como servicios `systemd`, o una mezcla de ambos.

La Pi 3 tiene recursos acotados (1 GB de RAM, sin GPU) y depende de acceso
directo a hardware: cámara (USB o CSI) hoy, GPIO para los 4 servos más
adelante. `vision/` ya usa Docker, pero ahí corre en la notebook del equipo
o en CI, con recursos de sobra y sin ninguna dependencia de hardware físico
— un contexto distinto al de la Pi en producción.

## Decisión

**Todo lo que corre en la Pi usa `systemd`, no Docker**: Mosquitto (ya lo
hace, de fábrica), `ecosort_pi.py` (unit file nueva), y `node_exporter`
cuando se sume (se distribuye como binario estático + una unit mínima, el
caso de libro para no containerizar). El dashboard y el adapter, al correr
en `host/` y no en la Pi, quedan fuera del alcance de esta ADR — ver
[ADR 0007](0007-docker-compose-en-el-host.md) (ahí se decidió Docker Compose,
por motivos opuestos a los de acá).

Se descarta Docker en la Pi por dos motivos, no por rechazo general a
contenedores (`vision/` los sigue usando donde sí tienen sentido):

- **Acceso a hardware:** un contenedor no ve la cámara ni el GPIO por
  default — hay que exponerlos explícitamente (`--device`, a veces
  `--privileged` cuando la librería toca el bus directo, como
  `picamera2`/`pigpio`). Es complejidad para deshacer un aislamiento que acá
  no aporta nada, en el único componente que sí necesita acceso directo y
  estable al hardware.
- **Costo de la capa sin beneficio que lo justifique:** el daemon de Docker,
  una imagen con TFLite runtime + OpenCV, y un filesystem por capas sobre
  una SD ya lenta, todo compitiendo por 1 GB de RAM — para terminar
  corriendo un proceso Python por contenedor, sin conflicto de dependencias
  entre servicios (Mosquitto es un binario de `apt`, el resto un venv) ni
  necesidad de mover esa imagen a otro host.

## Consecuencias

- Reinicio automático ante crash (`Restart=on-failure`), arranque en boot y
  orden de dependencias entre servicios (`After=mosquitto.service`,
  etc.) quedan resueltos por `systemd` nativo, sin herramienta adicional.
- Logs centralizados y consultables con `journalctl`, sin agregar un stack
  de logging.
- Se pierde la reproducibilidad de "imagen versionada" que Docker daría —
  aceptable hoy porque hay un solo dispositivo real; si el proyecto
  escala a N Pis (fuera de alcance académico actual, ver contexto
  estratégico en `CLAUDE.md`), esto conviene revisitarlo.
- No cambia nada de `vision/`: el entrenamiento sigue en Docker, porque ahí
  el contexto (recursos abundantes, sin hardware físico de por medio) es
  distinto al de la Pi.
