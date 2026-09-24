# adapter MQTT -> SQLite (ver host/README.md). El schema viene de un build context
# extra llamado "schema" (la carpeta schema/ de la raíz del repo, definido en
# host/docker-compose.yml), para no copiar el repo entero a la imagen ni duplicar
# schema/eventos.sql.
FROM python:3.12-slim

# PYTHONUNBUFFERED: sin esto los print() no aparecen en `docker compose logs`
ENV PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ECOSORT_SCHEMA=/app/schema/eventos.sql \
    ECOSORT_DB=/data/eventos.db

# /data lo comparte con el dashboard (volumen nombrado). Mismo uid en las dos imágenes,
# y el dueño lo hereda el volumen la primera vez que se crea.
RUN useradd --system --uid 10001 ecosort && mkdir /data && chown ecosort /data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY adapter.py .
COPY --from=schema eventos.sql /app/schema/eventos.sql

USER ecosort
CMD ["python", "adapter.py"]
