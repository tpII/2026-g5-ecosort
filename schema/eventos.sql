-- schema/eventos.sql — tabla de eventos de clasificación de EcoSort.

CREATE TABLE IF NOT EXISTS eventos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id       TEXT    NOT NULL UNIQUE,  -- UUID generado en la Pi (QoS 1 puede duplicar)
    dispositivo_id  TEXT    NOT NULL,         -- forward-compat para N dispositivos (ADR 0003)
    clase           TEXT    NOT NULL,         -- plastico | papel | vidrio | organico
    confianza       REAL,
    compuerta       INTEGER,
    latencia_ms     REAL,
    modelo          TEXT,
    ts_dispositivo  TEXT,                     -- reloj de la Pi (puede estar mal: sin RTC ni NTP)
    ts_recepcion    TEXT    NOT NULL          -- reloj del host al recibir (confiable)
);

CREATE INDEX IF NOT EXISTS idx_eventos_ts    ON eventos (ts_recepcion);
CREATE INDEX IF NOT EXISTS idx_eventos_clase ON eventos (clase);
