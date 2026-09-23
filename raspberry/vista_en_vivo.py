"""Vista en vivo de la cámara de EcoSort en el navegador (herramienta de prueba).

Corre en la Raspberry Pi. Después abrís en la notebook:  http://<ip-de-la-pi>:8000

    python3 vista_en_vivo.py                             # solo video + nitidez (para enfocar)
    python3 vista_en_vivo.py --modelo modelo_int8.tflite # además muestra la clase detectada

Solo necesita OpenCV (sudo apt install python3-opencv). Con --modelo usa
inferencia_pi.py, que tiene que estar en la misma carpeta.
NO dejarlo corriendo en el funcionamiento final: consume CPU.
"""

import argparse
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

HTML = b"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>EcoSort - camara</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{margin:0;background:#111;color:#eee;font-family:system-ui,sans-serif;text-align:center}
 img{max-width:100%;margin-top:12px;border:1px solid #333}
 a{display:inline-block;margin:12px;padding:8px 16px;background:#2e7d32;color:#fff;
   text-decoration:none;border-radius:6px}
 p{color:#999;font-size:14px}
</style></head><body>
<img src="/stream" alt="camara">
<br><a href="/foto">Descargar foto</a>
<p>Nitidez: mas alto = mas enfocado. Gira el lente buscando el valor maximo.</p>
</body></html>"""


class Camara:
    def __init__(self, cam_id, ancho, alto, fps, clf=None):
        self.cap = cv2.VideoCapture(cam_id, cv2.CAP_V4L2)
        # MJPG: la cámara comprime ella misma -> menos carga en el USB y la CPU de la Pi
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # siempre el cuadro más reciente
        if not self.cap.isOpened():
            raise SystemExit(f"No se pudo abrir /dev/video{cam_id}")

        self.clf = clf
        self.periodo = 1.0 / fps
        self.cond = threading.Condition()
        self.jpeg = None      # cuadro con anotaciones, para el stream
        self.original = None  # cuadro limpio, para /foto
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            t0 = time.monotonic()
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.1)
                continue
            original = frame.copy()

            gris = cv2.cvtColor(cv2.resize(frame, (320, 240)), cv2.COLOR_BGR2GRAY)
            nitidez = cv2.Laplacian(gris, cv2.CV_64F).var()
            texto = f"nitidez {nitidez:.0f}"
            if self.clf:
                clase, conf, ms = self.clf.predecir(frame)
                texto = f"{clase} {conf:.0%} ({ms:.0f} ms) | " + texto

            cv2.rectangle(frame, (0, 0), (frame.shape[1], 34), (0, 0, 0), -1)
            cv2.putText(frame, texto, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (80, 255, 80), 2)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])

            with self.cond:
                self.original = original
                self.jpeg = buf.tobytes()
                self.cond.notify_all()

            espera = self.periodo - (time.monotonic() - t0)
            if espera > 0:
                time.sleep(espera)


class Handler(BaseHTTPRequestHandler):
    cam = None

    def do_GET(self):
        if self.path == "/":
            self._enviar(200, "text/html; charset=utf-8", HTML)
        elif self.path == "/stream":
            self._stream()
        elif self.path == "/foto":
            self._foto()
        else:
            self._enviar(404, "text/plain", b"no encontrado")

    def _enviar(self, codigo, tipo, cuerpo, extra=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                with self.cam.cond:
                    self.cam.cond.wait(timeout=2)
                    jpg = self.cam.jpeg
                if jpg is None:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass  # el navegador cerró la pestaña

    def _foto(self):
        with self.cam.cond:
            frame = self.cam.original
        if frame is None:
            return self._enviar(503, "text/plain", b"todavia no hay imagen")
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        nombre = datetime.now().strftime("ecosort_%Y%m%d_%H%M%S.jpg")
        self._enviar(200, "image/jpeg", buf.tobytes(),
                     {"Content-Disposition": f'attachment; filename="{nombre}"'})

    def log_message(self, *args):
        pass  # no llenar la terminal con cada request


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--ancho", type=int, default=640)
    ap.add_argument("--alto", type=int, default=480)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--puerto", type=int, default=8000)
    ap.add_argument("--modelo", help="archivo .tflite para mostrar la clase detectada")
    args = ap.parse_args()

    clf = None
    if args.modelo:
        from inferencia_pi import Clasificador
        clf = Clasificador(args.modelo)

    Handler.cam = Camara(args.cam, args.ancho, args.alto, args.fps, clf)
    servidor = ThreadingHTTPServer(("0.0.0.0", args.puerto), Handler)
    servidor.daemon_threads = True
    print(f"Vista en vivo en http://<ip-de-la-pi>:{args.puerto}  (Ctrl+C para cortar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
