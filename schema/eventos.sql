-- schema/eventos.sql — persistencia del contrato de eventos (docs/contrato-mqtt.md, ADR 0008).
-- Las columnas agregadas después de la primera versión (schema_version, clase_modelo,
-- accionado) las suma a una base ya existente host/adapter/adapter.py (migrar()).

CREATE TABLE IF NOT EXISTS eventos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version  INTEGER NOT NULL DEFAULT 1,
    evento_id       TEXT    NOT NULL UNIQUE,  -- UUID generado en la Pi (QoS 1 puede duplicar)
    dispositivo_id  TEXT    NOT NULL,         -- forward-compat para N dispositivos (ADR 0003)
    clase           TEXT    NOT NULL,         -- plastico | papel | vidrio | organico | metal
    clase_modelo    TEXT,                     -- etiqueta cruda del modelo (cardboard, glass, ...)
    confianza       REAL,
    compuerta       INTEGER,                  -- 1 plastico, 2 papel, 3 vidrio, 4 organico, 5 metal
    accionado       INTEGER NOT NULL DEFAULT 0, -- 1 si la salida física (LED/servo) se activó
    latencia_ms     REAL,
    modelo          TEXT,
    ts_dispositivo  TEXT,                     -- reloj de la Pi (puede estar mal: sin RTC ni NTP)
    ts_recepcion    TEXT    NOT NULL          -- reloj del host al recibir (confiable)
);

CREATE INDEX IF NOT EXISTS idx_eventos_ts    ON eventos (ts_recepcion);
CREATE INDEX IF NOT EXISTS idx_eventos_clase ON eventos (clase);

-- Mensajes de ecosort/+/eventos que no cumplen el contrato: se guardan con el motivo
-- en vez de perderse. Es un registro de diagnóstico, no un dato de negocio.
CREATE TABLE IF NOT EXISTS eventos_rechazados (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_recepcion    TEXT    NOT NULL,
    topico          TEXT    NOT NULL,
    motivo          TEXT    NOT NULL,
    payload         TEXT    NOT NULL          -- crudo, truncado a 2000 caracteres
);
