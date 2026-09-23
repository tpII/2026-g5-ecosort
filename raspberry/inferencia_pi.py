"""Inferencia TFLite en la Raspberry Pi: benchmark, cámara en vivo y publicación MQTT.

Ejemplos:
    python inferencia_pi.py modelo_int8.tflite --bench            # latencia + RAM, sin cámara
    python inferencia_pi.py modelo_int8.tflite --camara           # clasifica con la webcam
    python inferencia_pi.py modelo_int8.tflite --camara --mqtt    # y publica en Mosquitto
    python inferencia_pi.py modelo_int8.tflite --camara --picam   # con la cámara CSI de la Pi

Pensado para el modelo de entrenar_ecosort.ipynb (labels.txt en la misma carpeta que el .tflite).
"""

import argparse
import resource
import time
from pathlib import Path

import cv2
import numpy as np

try:
    from ai_edge_litert.interpreter import Interpreter   # nombre nuevo de tflite-runtime
except ImportError:
    from tflite_runtime.interpreter import Interpreter

# El modelo nuevo (entrenar_ecosort.ipynb) escala la imagen adentro: se le pasa RGB 0..255.
RESCALE = False
# Por defecto; si hay un labels.txt junto al modelo, se usa ese.
CLASES = ["cardboard", "glass", "metal", "paper", "plastic", "trash"]
# TrashNet (6 clases) -> las 4 compuertas de EcoSort. None = sin compuerta todavía.
MAPEO = {
    "cardboard": ("papel", 2), "paper": ("papel", 2),
    "plastic": ("plastico", 1), "glass": ("vidrio", 3),
    "metal": (None, None), "trash": (None, None),
}
UMBRAL = 0.6


def ram_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KB -> MB


class Clasificador:
    def __init__(self, modelo, hilos=4):
        global CLASES
        etiquetas = Path(modelo).with_name("labels.txt")
        if etiquetas.exists():
            CLASES = [l.strip() for l in etiquetas.read_text().splitlines() if l.strip()]
        self.interp = Interpreter(model_path=modelo, num_threads=hilos)
        self.interp.allocate_tensors()
        self.inp = self.interp.get_input_details()[0]
        self.out = self.interp.get_output_details()[0]
        _, self.h, self.w, _ = self.inp["shape"]
        print(f"Entrada {self.inp['shape']} {self.inp['dtype'].__name__} | clases {CLASES} | RAM {ram_mb():.0f} MB")

    def preparar(self, frame_bgr):
        x = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        x = cv2.resize(x, (self.w, self.h)).astype(np.float32)
        if RESCALE:
            x /= 255.0
        if self.inp["dtype"] != np.float32:  # modelo con entrada cuantizada
            escala, cero = self.inp["quantization"]
            x = np.clip(np.round(x / escala + cero), -128, 255).astype(self.inp["dtype"])
        return x[np.newaxis, ...]

    def predecir(self, frame_bgr):
        self.interp.set_tensor(self.inp["index"], self.preparar(frame_bgr))
        t0 = time.perf_counter()
        self.interp.invoke()
        ms = (time.perf_counter() - t0) * 1000
        y = self.interp.get_tensor(self.out["index"])[0].astype(np.float32)
        if self.out["dtype"] != np.float32:
            escala, cero = self.out["quantization"]
            y = (y - cero) * escala
        i = int(np.argmax(y))
        return CLASES[i], float(y[i]), ms


def bench(clf, n=50):
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    for _ in range(5):  # calentamiento
        clf.predecir(frame)
    tiempos = [clf.predecir(frame)[2] for _ in range(n)]
    print(f"Latencia: media {np.mean(tiempos):.0f} ms | p95 {np.percentile(tiempos, 95):.0f} ms"
          f" | ~{1000 / np.mean(tiempos):.1f} fps | RAM pico {ram_mb():.0f} MB")


class CamUSB:
    def __init__(self, cam_id=0):
        self.cap = cv2.VideoCapture(cam_id)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not self.cap.isOpened():
            raise SystemExit("No se pudo abrir la cámara USB (probar otro --cam)")

    def leer(self):
        ok, frame = self.cap.read()
        return frame if ok else None

    def cerrar(self):
        self.cap.release()


class CamPi:
    """Cámara oficial por cable plano (CSI). Requiere: sudo apt install python3-picamera2"""
    def __init__(self):
        from picamera2 import Picamera2
        self.picam = Picamera2()
        # "RGB888" en Picamera2 entrega los píxeles en orden BGR, igual que OpenCV
        cfg = self.picam.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"})
        self.picam.configure(cfg)
        self.picam.start()
        time.sleep(1)  # dejar que ajuste exposición y balance de blancos

    def leer(self):
        return self.picam.capture_array()

    def cerrar(self):
        self.picam.stop()


def camara(clf, pub=None, cam_id=0, picam=False):
    cam = CamPi() if picam else CamUSB(cam_id)
    try:
        while True:
            frame = cam.leer()
            if frame is None:
                continue
            clase, conf, ms = clf.predecir(frame)
            destino, compuerta = MAPEO.get(clase, (None, None))
            print(f"{clase:10s} {conf:.2f}  {ms:5.0f} ms  -> {destino}")
            if pub and destino and conf >= UMBRAL:
                pub.publicar_evento(destino, conf, compuerta, latencia_ms=round(ms, 1),
                                    modelo=args.modelo)
                time.sleep(2)  # evita publicar el mismo residuo 20 veces
    except KeyboardInterrupt:
        pass
    finally:
        cam.cerrar()
        if pub:
            pub.cerrar()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modelo")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--camara", action="store_true")
    ap.add_argument("--mqtt", action="store_true")
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--picam", action="store_true", help="usar la cámara CSI (cable plano)")
    ap.add_argument("--hilos", type=int, default=4)
    args = ap.parse_args()

    clf = Clasificador(args.modelo, args.hilos)
    if args.bench:
        bench(clf)
    if args.camara:
        pub = None
        if args.mqtt:
            from ecosort_mqtt import EcoSortMQTT
            pub = EcoSortMQTT()
        camara(clf, pub, args.cam, args.picam)
