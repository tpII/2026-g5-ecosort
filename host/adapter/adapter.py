"""Adaptador MQTT -> SQLite: el único INSERT real de la tabla eventos (ADR 0003).

Corre en el host cliente/servidor (no en la Pi) — se suscribe a
`ecosort/+/eventos` y persiste cada evento de clasificación en `eventos.db`.

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

BROKER = os.getenv("ECOSORT_BROKER", "localhost")
DB_PATH = os.getenv("ECOSORT_DB", "eventos.db")
SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schema" / "eventos.sql"

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA busy_timeout=5000")  # el backend también escribe (DELETE en /api/reiniciar)
db.executescript(SCHEMA_PATH.read_text())
db_lock = threading.Lock()


def guardar_evento(e, dispositivo):
    if not (e.get("evento_id") and e.get("clase")):
        print(f"[adapter] evento sin evento_id/clase, descartado: {e}")
        return
    fila = {
        "evento_id": e["evento_id"],
        "dispositivo_id": e.get("dispositivo_id") or dispositivo,
        "clase": e["clase"],
        "confianza": e.get("confianza"),
        "compuerta": e.get("compuerta"),
        "latencia_ms": e.get("latencia_ms"),
        "modelo": e.get("modelo"),
        "ts_dispositivo": e.get("ts"),
        "ts_recepcion": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    with db_lock:
        cur = db.execute(
            "INSERT OR IGNORE INTO eventos (evento_id, dispositivo_id, clase, confianza, "
            "compuerta, latencia_ms, modelo, ts_dispositivo, ts_recepcion) VALUES "
            "(:evento_id, :dispositivo_id, :clase, :confianza, :compuerta, :latencia_ms, "
            ":modelo, :ts_dispositivo, :ts_recepcion)", fila)
        db.commit()
    if cur.rowcount:
        print(f"[adapter] guardado: {fila['clase']} ({fila['confianza']}) de {fila['dispositivo_id']}")
    else:
        print(f"[adapter] duplicado ignorado: {fila['evento_id']}")  # QoS 1 puede reenviar


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"[adapter] MQTT rechazó la conexión: {reason_code}")
        return
    print(f"[adapter] conectado al broker {BROKER}")
    client.subscribe("ecosort/+/eventos", qos=1)


def on_message(client, userdata, msg):
    partes = msg.topic.split("/")
    if len(partes) != 3:
        return
    _, dispositivo, _tipo = partes
    try:
        datos = json.loads(msg.payload.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        print(f"[adapter] payload no es JSON válido en {msg.topic}, descartado")
        return
    guardar_evento(datos, dispositivo)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ecosort-adapter",
                         clean_session=False)  # si se reinicia, no pierde eventos ya publicados
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async(BROKER, 1883, keepalive=30)
    print(f"[adapter] escuchando ecosort/+/eventos, escribiendo en {DB_PATH}  (Ctrl+C para cortar)")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        client.disconnect()


if __name__ == "__main__":
    main()
