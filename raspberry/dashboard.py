"""Dashboard de EcoSort.

Recibe los eventos por MQTT, los guarda en SQLite (eventos.db) y sirve un panel web con:
  - conteo por tipo de residuo y total
  - lo que la cámara está viendo en este momento (clase + confianza)
  - últimos residuos registrados
  - descarga de todos los datos en CSV (se abre directo en Excel)
  - botón para reiniciar (borrar) los datos

    python3 dashboard.py                                  # corriendo en la Pi (broker local)
    ECOSORT_BROKER=192.168.100.153 python dashboard.py    # corriendo en otra computadora

Abrir en el navegador:  http://<ip-donde-corre>:8080
Reemplaza a adapter_mqtt.py: hace lo mismo y además sirve el panel.
Solo necesita paho-mqtt 2.x (en la Pi ya está: python3-paho-mqtt).
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

import paho.mqtt.client as mqtt

BROKER = os.getenv("ECOSORT_BROKER", "localhost")
PUERTO = int(os.getenv("ECOSORT_PUERTO", "8080"))
DB_PATH = os.getenv("ECOSORT_DB", "eventos.db")
VIDEO_URL = os.getenv("ECOSORT_VIDEO", "")  # vacío = http://<mismo host>:8000/stream

SCHEMA = """
CREATE TABLE IF NOT EXISTS eventos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_id       TEXT    NOT NULL UNIQUE,
    dispositivo_id  TEXT    NOT NULL,
    clase           TEXT    NOT NULL,
    confianza       REAL,
    compuerta       INTEGER,
    latencia_ms     REAL,
    modelo          TEXT,
    ts_dispositivo  TEXT,
    ts_recepcion    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eventos_ts ON eventos (ts_recepcion);
"""
COLUMNAS = ["id", "evento_id", "dispositivo_id", "clase", "confianza", "compuerta",
            "latencia_ms", "modelo", "ts_dispositivo", "ts_recepcion"]

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.executescript(SCHEMA)
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


def guardar_evento(e, dispositivo):
    if not (e.get("evento_id") and e.get("clase")):
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
        print(f"[dashboard] guardado: {fila['clase']} ({fila['confianza']})")
        difundir("evento", {k: fila[k] for k in ("clase", "confianza", "ts_recepcion")})


# ---------------------------------------------------------------- MQTT

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
        guardar_evento(datos, dispositivo)


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
            html = HTML.replace("__VIDEO_URL__", json.dumps(VIDEO_URL))
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
        cuerpo = ("\ufeff" + buf.getvalue()).encode("utf-8")   # BOM: Excel respeta los acentos
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


HTML = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EcoSort · Dashboard</title>
<style>
:root{--bg:#f4f6f3;--card:#fff;--txt:#1d2a1f;--sub:#66756a;--borde:#dfe5df;
      --verde:#2e7d32;--verde2:#a5d6a7;--rojo:#c62828;--gris:#9e9e9e}
@media (prefers-color-scheme:dark){:root{--bg:#121613;--card:#1c221d;--txt:#e6ede7;
      --sub:#93a296;--borde:#2c352e;--verde:#66bb6a;--verde2:#2e5d31;--rojo:#ef5350}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;
       padding:16px 24px;border-bottom:1px solid var(--borde);background:var(--card)}
h1{margin:0;font-size:22px} h1 span{color:var(--verde)}
.estado{font-size:14px;color:var(--sub)} .punto{display:inline-block;width:10px;height:10px;
       border-radius:50%;background:var(--gris);margin-right:6px;vertical-align:middle}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;padding:16px 24px;
     max-width:1300px;margin:auto}
.card{background:var(--card);border:1px solid var(--borde);border-radius:12px;padding:18px}
.card h2{margin:0 0 12px;font-size:15px;color:var(--sub);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
#vivo-clase{font-size:38px;font-weight:700;margin:4px 0}
#vivo-sub{color:var(--sub);min-height:20px}
.barra{height:12px;background:var(--borde);border-radius:6px;overflow:hidden;margin:10px 0 4px}
.barra>div{height:100%;background:var(--verde);width:0;transition:width .25s}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;background:var(--verde2);font-size:13px;margin-top:8px}
#video{width:100%;border-radius:8px;margin-top:12px;background:#000}
.total{font-size:48px;font-weight:700;color:var(--verde);line-height:1}
.fila{display:grid;grid-template-columns:90px 1fr 44px;align-items:center;gap:10px;margin:9px 0;font-size:15px}
.fila .barra{margin:0}
.num{text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:7px 4px;border-bottom:1px solid var(--borde);text-align:left}
th{color:var(--sub);font-weight:600}
.acciones{display:flex;gap:10px;flex-wrap:wrap}
button,.boton{border:0;border-radius:8px;padding:10px 16px;font-size:14px;cursor:pointer;
       text-decoration:none;font-family:inherit}
.boton{background:var(--verde);color:#fff} .peligro{background:transparent;color:var(--rojo);border:1px solid var(--rojo)}
.vacio{color:var(--sub);font-style:italic}
</style></head><body>
<header>
  <h1>♻️ Eco<span>Sort</span></h1>
  <div class="estado"><span class="punto" id="punto"></span><span id="estado-txt">Conectando…</span></div>
  <div class="acciones">
    <a class="boton" href="/api/descargar.csv">⬇ Descargar datos (CSV)</a>
    <button class="peligro" id="reiniciar">↺ Reiniciar datos</button>
  </div>
</header>
<main>
  <section class="card">
    <h2>En vivo</h2>
    <div id="vivo-clase">—</div>
    <div class="barra"><div id="vivo-barra"></div></div>
    <div id="vivo-sub">Esperando datos del detector…</div>
    <div id="vivo-badge"></div>
    <img id="video" alt="video de la cámara">
    <div id="video-nota" class="vacio" hidden>Video no disponible (iniciá ecosort_pi.py con --video).</div>
  </section>
  <section class="card">
    <h2>Residuos detectados</h2>
    <div class="total" id="total">0</div><div class="vacio" style="margin-bottom:10px">en total</div>
    <div id="clases"></div>
  </section>
  <section class="card">
    <h2>Últimos registros</h2>
    <table><thead><tr><th>Hora</th><th>Residuo</th><th>Confianza</th></tr></thead>
    <tbody id="ultimos"></tbody></table>
  </section>
</main>
<script>
const VIDEO_URL = __VIDEO_URL__ || `http://${location.hostname}:8000/stream`;
const NOMBRES = {cardboard:"Cartón", glass:"Vidrio", metal:"Metal", paper:"Papel", plastic:"Plástico",
  trash:"Basura", plastico:"Plástico", papel:"Papel", vidrio:"Vidrio", organico:"Orgánico"};
const BASE = ["plastic","paper","cardboard","glass","metal","trash"];
const nombre = c => NOMBRES[c] || c;
const pct = x => x == null ? "—" : Math.round(x * 100) + "%";
const hora = ts => ts ? new Date(ts).toLocaleTimeString("es-AR") : "";
const $ = id => document.getElementById(id);
let datos = {total: 0, por_clase: {}, ultimos: [], estado: {}};
let ultimoVivo = 0;

async function cargar() {
  try { datos = await (await fetch("/api/resumen")).json(); pintar(); } catch (e) {}
}

function pintar() {
  $("total").textContent = datos.total;
  const clases = [...new Set([...BASE, ...Object.keys(datos.por_clase)])];
  const max = Math.max(1, ...Object.values(datos.por_clase));
  $("clases").innerHTML = clases.map(c => {
    const n = datos.por_clase[c] || 0;
    return `<div class="fila"><span>${nombre(c)}</span>
      <div class="barra"><div style="width:${n / max * 100}%"></div></div>
      <span class="num">${n}</span></div>`;
  }).join("");
  $("ultimos").innerHTML = datos.ultimos.length
    ? datos.ultimos.map(u => `<tr><td>${hora(u.ts_recepcion)}</td><td>${nombre(u.clase)}</td>
        <td>${pct(u.confianza)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="vacio">Todavía no hay registros</td></tr>`;
  pintarEstado();
}

function pintarEstado() {
  const estados = Object.values(datos.estado || {});
  const online = estados.includes("online");
  const sinSenal = Date.now() - ultimoVivo > 3000;
  $("punto").style.background = online && !sinSenal ? "var(--verde)" : online ? "orange" : "var(--gris)";
  $("estado-txt").textContent = !estados.length ? "Detector sin conectar"
    : !online ? "Detector desconectado" : sinSenal ? "Detector conectado, sin imagen" : "Detector funcionando";
}

function vivo(d) {
  ultimoVivo = Date.now();
  if (d.presente && d.clase) {
    $("vivo-clase").textContent = nombre(d.clase);
    $("vivo-barra").style.width = pct(d.confianza);
    $("vivo-sub").textContent = `Confianza: ${pct(d.confianza)}`;
    $("vivo-badge").innerHTML = d.contado ? `<span class="badge">✓ Registrado</span>` : "";
  } else {
    $("vivo-clase").textContent = "—";
    $("vivo-barra").style.width = "0";
    $("vivo-sub").textContent = "Esperando residuo…";
    $("vivo-badge").innerHTML = "";
  }
  pintarEstado();
}

const es = new EventSource("/api/stream");
es.addEventListener("vivo", e => vivo(JSON.parse(e.data)));
es.addEventListener("evento", cargar);
es.addEventListener("reinicio", cargar);
es.addEventListener("estado", e => {
  const d = JSON.parse(e.data); datos.estado[d.dispositivo] = d.estado; pintarEstado();
});
es.onopen = cargar;
setInterval(pintarEstado, 1000);

$("reiniciar").onclick = async () => {
  if (!confirm("¿Borrar TODOS los datos registrados?\n\nSi los querés conservar, descargá el CSV antes.")) return;
  await fetch("/api/reiniciar", {method: "POST"});
  cargar();
};

$("video").src = VIDEO_URL;
$("video").onerror = () => { $("video").hidden = true; $("video-nota").hidden = false; };
cargar();
</script>
</body></html>
"""


if __name__ == "__main__":
    iniciar_mqtt()
    servidor = ThreadingHTTPServer(("0.0.0.0", PUERTO), Handler)
    servidor.daemon_threads = True
    print(f"[dashboard] panel en http://<ip>:{PUERTO}  (Ctrl+C para cortar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
