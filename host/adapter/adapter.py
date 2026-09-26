"""Adaptador MQTT -> SQLite: el único INSERT real de la tabla eventos (ADR 0003).

Corre en el host cliente/servidor (no en la Pi) — se suscribe a
`ecosort/+/eventos` y persiste cada evento de clasificación en `eventos.db`.

Es quien hace cumplir el contrato (docs/contrato-mqtt.md, ADR 0008): cada mensaje se valida
contra schema/evento.schema.json. Lo que no cumple NO se guarda como evento: queda en la tabla
eventos_rechazados con el motivo, para poder diagnosticar un publisher desalineado en vez de
perder datos en silencio.

No sirve nada por HTTP: eso lo hace `host/dashboard/backend/`, un proceso
aparte que lee la misma base en modo consulta y tiene su propia suscripción
MQTT para lo que no se persiste (`vivo`, `estado`). Los dos procesos no se
conocen entre sí — solo comparten el broker y el archivo SQLite (WAL mode
soporta un escritor + lectores concurrentes sin coordinación extra).

    python adapter.py
    ECOSORT_BROKER=192.168.20.1 python adapter.py
"""

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
from jsonschema import Draft202012Validator

BROKER = os.getenv("ECOSORT_BROKER", "localhost")
DB_PATH = os.getenv("ECOSORT_DB", "eventos.db")
# ECOSORT_SCHEMA / ECOSORT_EVENTO_SCHEMA: en la imagen Docker no existe el layout del repo
# (ver host/adapter/Dockerfile)
_RAIZ = Path(__file__).resolve().parent.parent.parent / "schema"
SCHEMA_PATH = Path(os.getenv("ECOSORT_SCHEMA", _RAIZ / "eventos.sql"))
EVENTO_SCHEMA_PATH = Path(os.getenv("ECOSORT_EVENTO_SCHEMA", _RAIZ / "evento.schema.json"))

# Columnas que se sumaron después de la primera versión de la tabla: CREATE TABLE IF NOT
# EXISTS no las agrega a una base que ya existe, así que se migran acá.
COLUMNAS_AGREGADAS = {
    "schema_version": "INTEGER NOT NULL DEFAULT 1",
    "clase_modelo": "TEXT",
    "accionado": "INTEGER NOT NULL DEFAULT 0",
}
MAX_PAYLOAD_RECHAZADO = 2000

_esquema_evento = json.loads(EVENTO_SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_esquema_evento)  # falla al arrancar si el schema está roto
_validador = Draft202012Validator(_esquema_evento)

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA busy_timeout=5000")  # el backend también escribe (DELETE en /api/reiniciar)
db.executescript(SCHEMA_PATH.read_text())
db_lock = threading.Lock()


def migrar():
    existentes = {fila[1] for fila in db.execute("PRAGMA table_info(eventos)")}
    for columna, definicion in COLUMNAS_AGREGADAS.items():
        if columna not in existentes:
            db.execute(f"ALTER TABLE eventos ADD COLUMN {columna} {definicion}")
            print(f"[adapter] migración: columna {columna} agregada a eventos")
    db.commit()


migrar()


def ahora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def validar(evento, dispositivo):
    """Devuelve el motivo del rechazo, o None si el evento cumple el contrato."""
    errores = sorted(_validador.iter_errors(evento), key=lambda e: [str(p) for p in e.path])
    if errores:
        return "; ".join(f"{'/'.join(map(str, e.path)) or 'evento'}: {e.message}"
                         for e in errores)[:500]
    if evento["dispositivo_id"] != dispositivo:
        return (f"dispositivo_id del payload ({evento['dispositivo_id']}) "
                f"distinto del que figura en el tópico ({dispositivo})")
    return None


def rechazar(topico, payload, motivo):
    with db_lock:
        db.execute(
            "INSERT INTO eventos_rechazados (ts_recepcion, topico, motivo, payload) "
            "VALUES (?, ?, ?, ?)", (ahora(), topico, motivo, payload[:MAX_PAYLOAD_RECHAZADO]))
        db.commit()
    print(f"[adapter] evento rechazado ({motivo}): {payload[:200]}")


def guardar_evento(e):
    fila = {
        "schema_version": e["schema_version"],
        "evento_id": e["evento_id"],
        "dispositivo_id": e["dispositivo_id"],
        "clase": e["clase"],
        "clase_modelo": e["clase_modelo"],
        "confianza": e["confianza"],
        "compuerta": e["compuerta"],
        "accionado": int(e["accionado"]),
        "latencia_ms": e.get("latencia_ms"),
        "modelo": e.get("modelo"),
        "ts_dispositivo": e["ts"],
        "ts_recepcion": ahora(),
    }
    with db_lock:
        cur = db.execute(
            "INSERT OR IGNORE INTO eventos (schema_version, evento_id, dispositivo_id, clase, "
            "clase_modelo, confianza, compuerta, accionado, latencia_ms, modelo, ts_dispositivo, "
            "ts_recepcion) VALUES (:schema_version, :evento_id, :dispositivo_id, :clase, "
            ":clase_modelo, :confianza, :compuerta, :accionado, :latencia_ms, :modelo, "
            ":ts_dispositivo, :ts_recepcion)", fila)
        db.commit()
    if cur.rowcount:
        print(f"[adapter] guardado: {fila['clase']} ({fila['confianza']}) de {fila['dispositivo_id']}")
    else:
        print(f"[adapter] duplicado ignorado: {fila['evento_id']}")  # QoS 1 puede reenviar


def procesar(topico, payload):
    """Un mensaje de ecosort/<dispositivo>/eventos: valida y guarda, o rechaza con motivo."""
    partes = topico.split("/")
    if len(partes) != 3:
        return
    texto = payload.decode("utf-8", "replace")
    try:
        evento = json.loads(texto)
    except json.JSONDecodeError:
        rechazar(topico, texto, "el payload no es JSON válido")
        return
    motivo = validar(evento, partes[1])
    if motivo:
        rechazar(topico, texto, motivo)
        return
    guardar_evento(evento)


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"[adapter] MQTT rechazó la conexión: {reason_code}")
        return
    print(f"[adapter] conectado al broker {BROKER}")
    client.subscribe("ecosort/+/eventos", qos=1)


def on_connect_fail(client, userdata):
    print(f"[adapter] no pude conectar al broker {BROKER}, reintento...")


def on_message(client, userdata, msg):
    procesar(msg.topic, msg.payload)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ecosort-adapter",
                         clean_session=False)  # si se reinicia, no pierde eventos ya publicados
    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async(BROKER, 1883, keepalive=30)
    print(f"[adapter] escuchando ecosort/+/eventos, escribiendo en {DB_PATH}  (Ctrl+C para cortar)")
    try:
        # retry_first_connection: sin esto, si el broker no está al arrancar (el host prende
        # antes que la Pi) loop_forever() levanta la excepción y el proceso muere.
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        client.disconnect()


if __name__ == "__main__":
    main()
