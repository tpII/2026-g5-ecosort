"""Backend del dashboard de EcoSort: lee eventos.db (solo consulta, salvo
"reiniciar") y sirve la API + el panel web (`host/dashboard/frontend/`).

No inserta eventos — eso lo hace `host/adapter/` (proceso aparte, ADR 0003).
Este backend tiene su propia suscripción MQTT solo para lo que no se
persiste (`vivo`, `estado`) y para avisarle al navegador que pida
`/api/resumen` de nuevo cuando llega un evento — no valida el evento ni
lo guarda, esa responsabilidad es del adapter.

    python backend.py
    ECOSORT_BROKER=192.168.20.1 python backend.py
"""

import csv
import io
import json
import os
import queue
import sqlite3
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import paho.mqtt.client as mqtt

BROKER = os.getenv("ECOSORT_BROKER", "localhost")
PUERTO = int(os.getenv("ECOSORT_PUERTO", "8080"))
DB_PATH = os.getenv("ECOSORT_DB", "eventos.db")
VIDEO_URL = os.getenv("ECOSORT_VIDEO", "")  # vacío = http://<mismo host>:8000/stream

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent.parent / "schema" / "eventos.sql"
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

COLUMNAS = ["id", "evento_id", "dispositivo_id", "clase", "confianza", "compuerta",
            "latencia_ms", "modelo", "ts_dispositivo", "ts_recepcion"]

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA busy_timeout=5000")  # el adapter también escribe (INSERT de cada evento)
db.executescript(SCHEMA_PATH.read_text())  # idempotente: puede arrancar antes o después del adapter
db_lock = threading.Lock()

clientes = []                 # una cola por navegador conectado (Server-Sent Events)
clientes_lock = threading.Lock()
estado_dispositivos = {}      # ecosort-01 -> "online" / "offline"


def difundir(tipo, datos):
    msg = f"event: {tipo}\ndata: {json.dumps(datos, ensure_ascii=False)}\n\n".encode()
    with clientes_lock:
        for q in clientes:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


def resumen():
    with db_lock:
        total = db.execute("SELECT COUNT(*) FROM eventos").fetchone()[0]
        por_clase = {r["clase"]: r["n"] for r in
                     db.execute("SELECT clase, COUNT(*) AS n FROM eventos GROUP BY clase")}
        ultimos = [dict(r) for r in db.execute(
            "SELECT clase, confianza, ts_recepcion FROM eventos ORDER BY id DESC LIMIT 15")]
    return {"total": total, "por_clase": por_clase, "ultimos": ultimos,
            "estado": estado_dispositivos}


# ---------------------------------------------------------------- MQTT (solo relay, no inserta)

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"[dashboard] MQTT rechazó la conexión: {reason_code}")
        return
    print(f"[dashboard] conectado al broker {BROKER}")
    client.subscribe([("ecosort/+/eventos", 1), ("ecosort/+/vivo", 0), ("ecosort/+/estado", 1)])


def on_message(client, userdata, msg):
    partes = msg.topic.split("/")
    if len(partes) != 3:
        return
    _, dispositivo, tipo = partes
    texto = msg.payload.decode("utf-8", "replace")

    if tipo == "estado":
        estado_dispositivos[dispositivo] = texto
        difundir("estado", {"dispositivo": dispositivo, "estado": texto})
        return
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        return
    if tipo == "vivo":
        difundir("vivo", datos)
    elif tipo == "eventos":
        # el INSERT lo hace host/adapter/ — acá solo avisamos al navegador
        # que hay algo nuevo para que vuelva a pedir /api/resumen. Puede
        # llegar una fracción de segundo antes de que el adapter confirme
        # el commit; /api/resumen igual refleja el estado real de la base
        # en el momento en que el navegador lo pide, no lo que viaja acá.
        difundir("evento", {"clase": datos.get("clase"), "confianza": datos.get("confianza")})


def iniciar_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ecosort-dashboard",
                         clean_session=False)   # si el panel se reinicia, no pierde eventos
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async(BROKER, 1883, keepalive=30)
    client.loop_start()
    return client


# ---------------------------------------------------------------- Web

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ruta = self.path.split("?")[0]
        if ruta == "/":
            html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
            html = html.replace("__VIDEO_URL__", json.dumps(VIDEO_URL))
            self._enviar(200, "text/html; charset=utf-8", html.encode())
        elif ruta == "/api/resumen":
            self._json(resumen())
        elif ruta == "/api/stream":
            self._sse()
        elif ruta == "/api/descargar.csv":
            self._csv()
        else:
            self._enviar(404, "text/plain", b"no encontrado")

    def do_POST(self):
        if self.path == "/api/reiniciar":
            with db_lock:
                borrados = db.execute("DELETE FROM eventos").rowcount
                db.commit()
            print(f"[dashboard] datos reiniciados ({borrados} eventos borrados)")
            difundir("reinicio", {"borrados": borrados})
            self._json({"ok": True, "borrados": borrados})
        else:
            self._enviar(404, "text/plain", b"no encontrado")

    def _enviar(self, codigo, tipo, cuerpo, extra=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, datos):
        self._enviar(200, "application/json; charset=utf-8",
                     json.dumps(datos, ensure_ascii=False).encode())

    def _csv(self):
        with db_lock:
            filas = db.execute(f"SELECT {', '.join(COLUMNAS)} FROM eventos ORDER BY id").fetchall()
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")    # ";" y coma decimal: formato de Excel en español
        w.writerow(COLUMNAS)
        for f in filas:
            w.writerow([str(v).replace(".", ",") if isinstance(v, float) else v for v in f])
        cuerpo = ("﻿" + buf.getvalue()).encode("utf-8")   # BOM: Excel respeta los acentos
        nombre = datetime.now().strftime("ecosort_eventos_%Y%m%d_%H%M.csv")
        self._enviar(200, "text/csv; charset=utf-8", cuerpo,
                     {"Content-Disposition": f'attachment; filename="{nombre}"'})

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = queue.Queue(maxsize=200)
        with clientes_lock:
            clientes.append(q)
        try:
            self.wfile.write(b": conectado\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    msg = b": ping\n\n"          # mantiene viva la conexión
                self.wfile.write(msg)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with clientes_lock:
                clientes.remove(q)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    iniciar_mqtt()
    servidor = ThreadingHTTPServer(("0.0.0.0", PUERTO), Handler)
    servidor.daemon_threads = True
    print(f"[dashboard] panel en http://<ip>:{PUERTO}  (Ctrl+C para cortar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
