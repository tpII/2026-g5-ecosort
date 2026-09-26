# ADR 0007 — Servicios en el host: Docker Compose

**Estado:** Aceptado.

## Contexto

Del lado del host cliente/servidor (`host/`, ver README raíz) corren el
adapter MQTT→SQLite y el dashboard, y más adelante Prometheus (ADR 0005).
La [ADR 0006](0006-systemd-vs-docker-en-la-pi.md) decidió **systemd, sin
Docker, en la Pi**, por acceso directo a hardware (cámara, GPIO) y recursos
acotados (1 GB de RAM, sin GPU). Esas razones no aplican acá:

- No hay hardware que exponer: ninguno de estos servicios toca cámara ni GPIO.
- Los recursos sobran: el host puede ser cualquier notebook del equipo.
- El host **no es un dispositivo fijo**: hoy es una notebook, mañana la de otro
  integrante, eventualmente un servidor. Y el equipo usa distintos sistemas
  operativos (la guía de instalación asume Windows en el lado del cliente).
- Son varios procesos con estado compartido (`eventos.db`) y ciclos de vida
  independientes — justo el caso donde un archivo declarativo pesa más que una
  lista de comandos a copiar a mano.

## Decisión

El lado host se despliega con **Docker Compose** (`host/docker-compose.yml`):
un servicio por proceso (`adapter`, `dashboard`), cada uno con su imagen y
`restart: unless-stopped`. Prometheus se sumará como un servicio más cuando
exista (hoy está fuera de alcance, ver ADR 0005).

**El broker Mosquitto no va en el compose**: corre en la Pi (ADR 0003 y 0006),
y el host se conecta a él (`ECOSORT_BROKER`, por defecto `192.168.20.1`). Para
desarrollar sin Pi, `host/docker-compose.dev.yml` suma un broker local con la
misma conf que usa la Pi (`raspberry/mosquitto/ecosort.conf`) y apunta los
servicios a él.

Decisiones de implementación que conviene dejar por escrito:

- **`eventos.db` vive en un volumen nombrado, no en un bind mount.** Adapter y
  dashboard lo escriben a la vez con SQLite en modo WAL, que necesita memoria
  compartida entre procesos y no es confiable sobre algunos sistemas de
  archivos montados desde el host (Docker Desktop en Windows/Mac).
- **El schema no se duplica**: ambas imágenes copian `schema/eventos.sql` de la
  raíz del repo mediante un build context adicional (`additional_contexts`), y
  las rutas del schema y del frontend son configurables por variable de entorno
  (`ECOSORT_SCHEMA`, `ECOSORT_FRONTEND`), porque dentro de la imagen no existe
  el layout del repo.
- Los procesos corren como usuario no-root (mismo uid en ambas imágenes, así
  comparten el volumen).

## Consecuencias

- `docker compose up -d` levanta todo igual en cualquier máquina del equipo; no
  hay venv, ni versión de Python, ni pasos por SO que mantener.
- Los servicios toleran que la Pi no esté al arrancar: reintentan la conexión
  MQTT solos (verificado levantando el host antes que el broker), sin caerse ni
  entrar en crash-loop. Y son independientes entre sí: con el dashboard caído el
  adapter sigue guardando.
- Cada integrante necesita Docker instalado (Docker Desktop en Windows/Mac).
  Correr los scripts directo con Python sigue funcionando (`host/README.md`),
  útil para depurar.
- La dirección de la Pi (`192.168.20.1`) queda como default del compose; si la
  red cambia, se pisa con `ECOSORT_BROKER` / `ECOSORT_VIDEO`.
- Si en el futuro el dashboard se separa en frontend y backend independientes
  (ADR 0005 dejó el framework "a definir"), se parte la imagen en dos.
