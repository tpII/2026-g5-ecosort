# host — adapter + dashboard

Todo lo que corre en el "host cliente/servidor" del diagrama de
arquitectura (`192.168.20.2` en el README raíz), **no en la Raspberry Pi**.
Dos servicios independientes que no se conocen entre sí — solo comparten el
broker MQTT y el archivo `eventos.db` (ADR 0003), desplegados con Docker
Compose ([ADR 0007](../docs/adr/0007-docker-compose-en-el-host.md)):

```
host/
├── docker-compose.yml        # adapter + dashboard (el broker está en la Pi)
├── docker-compose.dev.yml    # override: suma un broker local para trabajar sin Pi
├── adapter/                  # MQTT -> SQLite, el único INSERT real
│   ├── adapter.py
│   ├── Dockerfile
│   └── requirements.txt
└── dashboard/
    ├── Dockerfile
    ├── backend/               # lee SQLite (+ MQTT para vivo/estado), sirve la API + el panel
    │   ├── backend.py
    │   └── requirements.txt
    └── frontend/              # HTML/CSS/JS estáticos
        └── index.html
```

`raspberry/` (lo que corre en la Pi) antes tenía un `dashboard.py` que hacía
todo esto en un solo proceso — era una prueba de integración para validar
que las piezas encajaban, corriendo entero en la Pi por `localhost` (con lo
cual MQTT ni siquiera cruzaba la red). Esta carpeta es la separación real,
en la topología que ya mostraba el diagrama de arquitectura del README.

## Uso con Docker Compose

```bash
cd host

# contra la Pi (192.168.20.1 por defecto)
docker compose up -d --build
ECOSORT_BROKER=<otra-ip> docker compose up -d      # si la red es otra

docker compose logs -f          # ver qué hacen adapter y dashboard
docker compose down             # frena todo; los datos quedan (volumen eventos-data)
docker compose down -v          # ...y BORRA los datos
```

Abrir `http://localhost:8080` (o `DASHBOARD_PORT=9090 docker compose up -d`
para otro puerto). Variables: `ECOSORT_BROKER` (IP de la Pi), `ECOSORT_VIDEO`
(por defecto `http://192.168.20.1:8000/stream`, el video lo sirve la Pi, no
este host).

**Sin la Pi** (para trabajar en el dashboard, el adapter o el contrato):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
pip install paho-mqtt && python ../raspberry/ecosort_mqtt.py   # eventos falsos → localhost:1883
```

El override suma un Mosquitto local con la misma conf que usa la Pi, y monta
`dashboard/frontend/` para que editar `index.html` y refrescar el navegador
alcance, sin rebuild.

`eventos.db` vive en un volumen nombrado y no en una carpeta tuya: SQLite en
modo WAL no es confiable sobre carpetas montadas desde el host en Docker
Desktop (Windows/Mac). Para sacar los datos, el botón *Descargar datos (CSV)*
del dashboard.

## Sin Docker (para depurar)

```bash
pip install -r adapter/requirements.txt -r dashboard/backend/requirements.txt

export ECOSORT_BROKER=192.168.20.1
export ECOSORT_DB=eventos.db          # mismo archivo para ambos procesos
export ECOSORT_VIDEO=http://192.168.20.1:8000/stream

python adapter/adapter.py &
python dashboard/backend/backend.py &
```

Abrir `http://<ip-de-este-host>:8080`. `ECOSORT_PUERTO` cambia el puerto
del panel (default `8080`).

## Por qué dos procesos y no uno

- **Desacoplados de verdad**: si el dashboard se cae, el adapter sigue
  guardando eventos — no se pierde nada. Si hay que reiniciar el panel para
  un cambio de frontend, la persistencia no se interrumpe.
- **Cada uno se suscribe a lo que necesita**: el adapter solo a
  `ecosort/+/eventos` (lo único que persiste). El backend a `eventos`
  (para saber cuándo avisarle al navegador que refresque), `vivo` y
  `estado` (tiempo real, no se guardan en la base).
- **SQLite en modo WAL soporta esto sin coordinación extra**: un escritor
  (adapter) + lectores/escritor ocasional (backend, solo en
  `/api/reiniciar`) concurrentes. Los dos procesos abren
  `PRAGMA busy_timeout=5000` para tolerar el raro caso de choque.
- El schema lo leen los dos de `schema/eventos.sql` (la fuente canónica, no
  una copia embebida) — antes `dashboard.py` tenía su propia copia inline
  que ya había divergido (le faltaba un índice).
- **Toleran que la Pi no esté**: si el host arranca antes que ella, los dos
  reintentan la conexión MQTT solos (lo avisan en el log) y se conectan
  cuando aparece, sin caerse.
- **El adapter hace cumplir el contrato** ([`docs/contrato-mqtt.md`](../docs/contrato-mqtt.md), ADR 0008):
  valida cada evento contra `schema/evento.schema.json`. Lo que no cumple no se
  cuenta: queda en la tabla `eventos_rechazados` con el motivo, para diagnosticar un
  publisher desalineado en vez de perder datos en silencio.
  `SELECT ts_recepcion, motivo FROM eventos_rechazados ORDER BY id DESC LIMIT 20;`

## Pruebas

```bash
bash host/tests/e2e_smoke.sh      # necesita Docker; ~40 s
```

Levanta broker local + adapter + dashboard (proyecto de Compose y puertos
propios, no pisa un stack de desarrollo que tengas levantado) y verifica:
que el adapter **sobrevive sin broker y reintenta**, que adapter y dashboard se
conectan solos cuando el broker aparece, que un evento del contrato v1
llega hasta `/api/resumen`, que un `evento_id` repetido no se cuenta dos
veces, y que un evento inválido no se cuenta y queda en `eventos_rechazados`. Lo mismo corre en
CI (`.github/workflows/ci.yml`, job `host`), **solo cuando el PR toca `host/**`**.

Los tests del contrato (sin Docker ni red, segundos) están en `schema/tests` y corren en CI
(job `contrato`) cuando cambia `schema/`, `raspberry/`, `host/adapter/`, el frontend o
`vision/classes.py`:

```bash
pip install paho-mqtt jsonschema
python -m unittest discover -s schema/tests -v
```

## Pendiente

- Prometheus como tercer servicio del compose, cuando exista `node_exporter`
  en la Pi (ADR 0005) — hoy `/api/resumen` solo devuelve el dato de negocio.
- `dashboard/backend/` sigue sirviendo con `http.server` puro, no Flask —
  la ADR 0005 dejó el framework como "a definir".
- El job de CI de Docker (`host`) mira solo `host/**`: un cambio en `schema/` (que las
  imágenes copian) o en `raspberry/mosquitto/ecosort.conf` (que usa el
  override de desarrollo) no lo dispara. Lo de `schema/` sí lo cubre el job `contrato`, que es liviano.
