# dashboard = backend (API + SSE) + frontend estático que ese mismo proceso sirve.
# El schema viene de un build context extra llamado "schema" (la carpeta schema/ de
# la raíz del repo, definido en host/docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ECOSORT_SCHEMA=/app/schema/eventos.sql \
    ECOSORT_FRONTEND=/app/frontend \
    ECOSORT_DB=/data/eventos.db

# Mismo uid que la imagen del adapter: los dos escriben en el mismo volumen /data.
RUN useradd --system --uid 10001 ecosort && mkdir /data && chown ecosort /data

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/backend.py .
COPY frontend/ /app/frontend/
COPY --from=schema eventos.sql /app/schema/eventos.sql

USER ecosort
EXPOSE 8080
CMD ["python", "backend.py"]
