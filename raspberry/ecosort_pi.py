"""EcoSort en la Raspberry Pi: cámara + detección + clasificación + MQTT.

    python ecosort_pi.py --modelo ecosort_int8.tflite           # detecta, cuenta y publica
    python ecosort_pi.py --modelo ecosort_int8.tflite --video   # además video en http://<pi>:8000

IMPORTANTE: al arrancar, la cámara tiene que ver la escena VACÍA unos 2 segundos.
Ahí aprende cómo es el fondo.

Cuándo se analiza un objeto lo decide raspberry/deteccion.py (ADR 0009): hace falta que lo que
apareció quede quieto ~1 s y tenga un tamaño de residuo; recién ahí se clasifican los cuadros más
nítidos y se decide por el promedio. Una mano que pasa, una cara o un animal no llegan al modelo, o
si llegan el modelo los descarta con la clase "ninguno". Se cuenta UN evento por objeto aceptado, y
no vuelve a analizar nada hasta que la plataforma queda libre.

Tópicos MQTT que publica:
    ecosort/<id>/vivo     -> estado de la detección, ~3 veces por segundo (QoS 0)
    ecosort/<id>/eventos  -> un mensaje por residuo aceptado (QoS 1), ver docs/contrato-mqtt.md

Necesita en la misma carpeta: inferencia_pi.py, ecosort_mqtt.py, clases.py, deteccion.py,
labels.txt, y la carpeta schema/ (schema/clases.json). Además vista_en_vivo.py si se usa --video.
"""

import argparse
import threading
import time

import cv2
import numpy as np

from clases import DESCARTES
from deteccion import Cuadro, Deteccion, Estado, Parametros, fraccion_distinta
from ecosort_mqtt import EcoSortMQTT
from inferencia_pi import Clasificador

PARAMETROS = Parametros()   # umbrales de la detección (raspberry/deteccion.py): sin calibrar con la cámara real
DIF_PIXEL = 30              # diferencia de gris (0-255) para considerar que un píxel cambió respecto del fondo
DIF_MOV = 20                # ... respecto del cuadro anterior: eso es movimiento


class Fondo:
    """Detecta si hay un objeto comparando contra la imagen de la escena vacía."""

    def __init__(self):
        self.ref = None

    @staticmethod
    def _gris(frame):
        g = cv2.cvtColor(cv2.resize(frame, (160, 120)), cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(g, (5, 5), 0).astype(np.float32)

    def mascara(self, g):
        return np.abs(g - self.ref) > DIF_PIXEL

    def medir(self, frame):
        g = self._gris(frame)
        if self.ref is None:
            self.ref = g.copy()
        return float(self.mascara(g).mean()), g

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

    def _nitidez(self, frame, g):
        """Nitidez (varianza del Laplaciano) de la zona que cambió, a resolución completa. Solo sirve
        para ordenar los cuadros de un mismo objeto entre sí y quedarse con los más nítidos."""
        ys, xs = np.where(self.fondo.mascara(g))
        if len(ys) == 0:
            return 0.0
        fy, fx = frame.shape[0] / g.shape[0], frame.shape[1] / g.shape[1]
        zona = frame[int(ys.min() * fy):int((ys.max() + 1) * fy),
                     int(xs.min() * fx):int((xs.max() + 1) * fx)]
        if zona.size == 0:
            return 0.0
        return float(cv2.Laplacian(cv2.cvtColor(zona, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())

    def correr(self):
        self.calibrar()
        maquina = Deteccion(self.clf.etiquetas, descartes=DESCARTES, params=PARAMETROS)
        g_prev = None
        ultimo_vivo = 0.0
        total = 0
        ultima = None   # última decisión: se muestra mientras se espera que la plataforma se libere

        while True:
            t0 = time.monotonic()
            frame = self._leer()
            if frame is None:
                time.sleep(0.1)
                continue
            original = frame.copy()

            # 1) Qué cambió en la escena (barato: imagen chica) y, mientras algo se asienta, qué tan nítido
            cambio, g = self.fondo.medir(frame)
            cambio_prev = fraccion_distinta(g, g_prev, DIF_MOV) if g_prev is not None else 0.0
            g_prev = g
            nitidez = self._nitidez(frame, g) if maquina.estado is Estado.ASENTANDO else 0.0

            # 2) La máquina decide. El modelo solo corre si pasó la quietud y la plausibilidad.
            tiempos = []

            def clasificar(f):
                probs, ms = self.clf.probabilidades(f)
                tiempos.append(ms)
                return probs

            r = maquina.paso(Cuadro(cambio, cambio_prev, nitidez, frame), clasificar)
            if maquina.puede_aprender_fondo:
                self.fondo.aprender(g)

            d = r.decision
            if d is not None:
                ultima = d
                if d.tipo == "aceptado":
                    self.pub.publicar_evento(d.etiqueta, d.confianza,
                                             latencia_ms=round(sum(tiempos) / len(tiempos), 1),
                                             modelo=self.modelo)
                    total += 1
                    print(f"[{total}] contado: {d.etiqueta} ({d.confianza:.0%})")
                else:
                    visto = f" (el modelo vio {d.etiqueta}, {d.confianza:.0%})" if d.etiqueta else ""
                    print(f"[{d.tipo}] {d.motivo}{visto}")
            for nombre, dato in r.senales:
                if nombre == "no_retirado":
                    # Además de avisar (acá se engancharía una alarma), se sigue como antes: si algo
                    # queda ~30 s se asume que cambió el fondo y se recalibra.
                    print(f"[no_retirado] la plataforma sigue ocupada tras '{dato}': se toma como fondo nuevo.")
                    self.fondo.reiniciar(g)
                    maquina.reiniciar()
            if maquina.estado is Estado.LIBRE:
                ultima = None

            # 3) Estado en vivo para el dashboard (~3 por segundo)
            aceptada = ultima is not None and ultima.tipo == "aceptado"
            if t0 - ultimo_vivo >= 0.33:
                self.pub.publicar_vivo({
                    "presente": maquina.estado is not Estado.LIBRE,
                    "estado": maquina.estado.value,
                    "clase": ultima.etiqueta if aceptada else None,
                    "confianza": round(ultima.confianza, 4) if aceptada else None,
                    "contado": aceptada,
                    "motivo": ultima.motivo if ultima is not None else None,
                })
                ultimo_vivo = t0

            if self.video:
                if aceptada:
                    texto = f"{ultima.etiqueta} {ultima.confianza:.0%}  [contado]"
                elif ultima is not None:
                    texto = f"no reconocido ({ultima.motivo})"
                elif maquina.estado is Estado.ASENTANDO:
                    texto = "analizando..."
                else:
                    texto = "esperando residuo..."
                self._video(frame, original, texto)

            espera = self.periodo - (time.monotonic() - t0)
            if espera > 0:
                time.sleep(espera)

    def _video(self, frame, original, texto):
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
