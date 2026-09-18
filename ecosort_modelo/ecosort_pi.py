"""EcoSort en la Raspberry Pi: cámara + clasificación + conteo por objeto + MQTT.

    python ecosort_pi.py --modelo ecosort_int8.tflite           # detecta, cuenta y publica
    python ecosort_pi.py --modelo ecosort_int8.tflite --video   # además video en http://<pi>:8000

IMPORTANTE: al arrancar, la cámara tiene que ver la escena VACÍA unos 2 segundos.
Ahí aprende cómo es el fondo; después cuenta UN evento por cada objeto que aparece,
y no vuelve a contar hasta que el objeto se retira.

Tópicos MQTT que publica:
    ecosort/<id>/vivo     -> lo que ve ahora, ~3 veces por segundo (QoS 0)
    ecosort/<id>/eventos  -> un mensaje por residuo contado (QoS 1)

Necesita en la misma carpeta: inferencia_pi.py, ecosort_mqtt.py, labels.txt
(y vista_en_vivo.py si se usa --video).
"""

import argparse
import threading
import time

import cv2
import numpy as np

from ecosort_mqtt import EcoSortMQTT
from inferencia_pi import Clasificador

UMBRAL_CONF = 0.60      # confianza mínima para contar un residuo
FRAMES_ESTABLE = 3      # cuadros seguidos con la misma clase para confirmarlo
UMBRAL_CAMBIO = 0.03    # fracción de la imagen que tiene que cambiar para decir "hay algo"
FRAMES_PRESENTE = 3     # cuadros seguidos con cambio para marcar que llegó un objeto
FRAMES_AUSENTE = 8      # cuadros seguidos sin cambio para darlo por retirado
MAX_PRESENTE_S = 30     # si "hay algo" más de esto, se asume que cambió el fondo y se recalibra
DIF_PIXEL = 30          # diferencia de gris (0-255) para considerar que un píxel cambió


class Fondo:
    """Detecta si hay un objeto comparando contra la imagen de la escena vacía."""

    def __init__(self):
        self.ref = None

    @staticmethod
    def _gris(frame):
        g = cv2.cvtColor(cv2.resize(frame, (160, 120)), cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(g, (5, 5), 0).astype(np.float32)

    def medir(self, frame):
        g = self._gris(frame)
        if self.ref is None:
            self.ref = g.copy()
        return float((np.abs(g - self.ref) > DIF_PIXEL).mean()), g

    def aprender(self, g, velocidad=0.05):
        # Actualiza el fondo de a poco (cambios lentos de luz). Solo sin objeto en escena.
        cv2.accumulateWeighted(g, self.ref, velocidad)

    def reiniciar(self, g):
        self.ref = g.copy()


class Detector:
    def __init__(self, clf, pub, modelo, cam_id=0, fps=8, video=False):
        self.clf, self.pub, self.modelo, self.video = clf, pub, modelo, video
        self.periodo = 1.0 / fps
        self.cap = cv2.VideoCapture(cam_id, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            raise SystemExit(f"No se pudo abrir /dev/video{cam_id} "
                             "(¿quedó corriendo vista_en_vivo.py? -> pkill -f vista_en_vivo.py)")
        self.fondo = Fondo()
        # Atributos que usa el servidor de video (mismo formato que vista_en_vivo.Camara)
        self.cond = threading.Condition()
        self.jpeg = None
        self.original = None

    def _leer(self):
        ok, frame = self.cap.read()
        return frame if ok else None

    def calibrar(self, segundos=2.0):
        print("Calibrando fondo: dejá la escena VACÍA...")
        fin = time.monotonic() + segundos
        while time.monotonic() < fin:
            frame = self._leer()
            if frame is not None:
                _, g = self.fondo.medir(frame)
                self.fondo.aprender(g, 0.3)
        print("Listo. Esperando residuos (Ctrl+C para cortar).")

    def correr(self):
        self.calibrar()
        presente = contado = False
        con_cambio = sin_cambio = 0
        historial = []
        desde = ultimo_vivo = 0.0
        total = 0

        while True:
            t0 = time.monotonic()
            frame = self._leer()
            if frame is None:
                time.sleep(0.1)
                continue
            original = frame.copy()

            # 1) ¿Hay un objeto en escena?
            cambio, g = self.fondo.medir(frame)
            if cambio > UMBRAL_CAMBIO:
                con_cambio, sin_cambio = con_cambio + 1, 0
            else:
                con_cambio, sin_cambio = 0, sin_cambio + 1

            if not presente and con_cambio >= FRAMES_PRESENTE:
                presente, contado, historial, desde = True, False, [], t0
            elif presente and sin_cambio >= FRAMES_AUSENTE:
                presente = False
            elif presente and t0 - desde > MAX_PRESENTE_S:
                print("Mucho tiempo con algo en escena: se toma como fondo nuevo.")
                self.fondo.reiniciar(g)
                presente = False
            if not presente:
                self.fondo.aprender(g)

            # 2) Si hay objeto, clasificar y contarlo UNA vez cuando la clase se estabiliza
            clase = conf = None
            if presente:
                clase, conf, ms = self.clf.predecir(frame)
                historial.append((clase if conf >= UMBRAL_CONF else None, conf))
                ult = historial[-FRAMES_ESTABLE:]
                if (not contado and len(ult) == FRAMES_ESTABLE and ult[0][0] is not None
                        and all(c == ult[0][0] for c, _ in ult)):
                    conf_media = sum(p for _, p in ult) / len(ult)
                    self.pub.publicar_evento(ult[0][0], conf_media, compuerta=None,
                                             latencia_ms=round(ms, 1), modelo=self.modelo)
                    contado = True
                    total += 1
                    print(f"[{total}] contado: {ult[0][0]} ({conf_media:.0%})")

            # 3) Estado en vivo para el dashboard (~3 por segundo)
            if t0 - ultimo_vivo >= 0.33:
                self.pub.publicar_vivo({
                    "presente": presente,
                    "clase": clase,
                    "confianza": round(conf, 4) if conf is not None else None,
                    "contado": contado,
                })
                ultimo_vivo = t0

            if self.video:
                self._video(frame, original, presente, clase, conf, contado)

            espera = self.periodo - (time.monotonic() - t0)
            if espera > 0:
                time.sleep(espera)

    def _video(self, frame, original, presente, clase, conf, contado):
        if presente and clase:
            texto = f"{clase} {conf:.0%}" + ("  [contado]" if contado else "")
        else:
            texto = "esperando residuo..."
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 34), (0, 0, 0), -1)
        cv2.putText(frame, texto, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (80, 255, 80), 2)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        with self.cond:
            self.original = original
            self.jpeg = buf.tobytes()
            self.cond.notify_all()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", required=True)
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--video", action="store_true", help="servir el video en el puerto 8000")
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--dispositivo", default="ecosort-01")
    args = ap.parse_args()

    clf = Clasificador(args.modelo)
    pub = EcoSortMQTT(dispositivo_id=args.dispositivo, host=args.broker)
    det = Detector(clf, pub, args.modelo, args.cam, video=args.video)

    if args.video:
        from http.server import ThreadingHTTPServer
        from vista_en_vivo import Handler
        Handler.cam = det
        srv = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print("Video en http://<ip-de-la-pi>:8000")

    try:
        det.correr()
    except KeyboardInterrupt:
        pass
    finally:
        pub.cerrar()
