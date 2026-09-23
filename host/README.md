# host — adapter + dashboard

Todo lo que corre en el "host cliente/servidor" del diagrama de
arquitectura (`192.168.20.2` en el README raíz), **no en la Raspberry Pi**.
Dos procesos independientes que no se conocen entre sí — solo comparten el
broker MQTT y el archivo `eventos.db` (ADR 0003):

```
host/
├── adapter/            # MQTT -> SQLite, el único INSERT real
│   ├── adapter.py
│   └── requirements.txt
└── dashboard/
    ├── backend/         # lee SQLite (+ MQTT para vivo/estado), sirve la API + el panel
    │   ├── backend.py
    │   └── requirements.txt
    └── frontend/        # HTML/CSS/JS estáticos
        └── index.html
```

`raspberry/` (lo que corre en la Pi) antes tenía un `dashboard.py` que hacía
todo esto en un solo proceso — era una prueba de integración para validar
que las piezas encajaban, corriendo entero en la Pi por `localhost` (con lo
cual MQTT ni siquiera cruzaba la red). Esta carpeta es la separación real,
en la topología que ya mostraba el diagrama de arquitectura del README.

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

## Uso

```bash
cd host/adapter && pip install -r requirements.txt
cd host/dashboard/backend && pip install -r requirements.txt

# variables de entorno (mismas para los dos, ECOSORT_BROKER es la IP de la Pi en la AP)
export ECOSORT_BROKER=192.168.20.1
export ECOSORT_DB=eventos.db          # mismo archivo para ambos procesos
export ECOSORT_VIDEO=http://192.168.20.1:8000/stream   # opcional, video de vista_en_vivo.py/ecosort_pi.py --video

python host/adapter/adapter.py &
python host/dashboard/backend/backend.py &
```

Abrir `http://<ip-de-este-host>:8080`. `ECOSORT_PUERTO` cambia el puerto
del panel (default `8080`).

## Pendiente

- **systemd o Docker para este lado**: a diferencia de la Pi (ver
  [ADR 0006](../docs/adr/0006-systemd-vs-docker-en-la-pi.md), sin Docker
  por el acceso a hardware), acá no hay cámara ni GPIO de por medio y el
  host puede ser cualquier notebook del equipo — candidato real a
  `docker-compose.yml` (adapter + backend + Prometheus). Discusión abierta,
  candidata a ADR 0007.
- `dashboard/backend/` sigue sirviendo con `http.server` puro, no Flask —
  la ADR 0005 dejó el framework como "a definir".
- Falta el segundo datasource (Prometheus, scrapeando `node_exporter` de la
  Pi) — hoy `resumen()`/`/api/resumen` solo devuelve el dato de negocio.
