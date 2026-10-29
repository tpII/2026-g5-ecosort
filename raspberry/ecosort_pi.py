"""EcoSort en la Raspberry Pi: cámara + detección + clasificación + MQTT.

    python ecosort_pi.py --modelo ecosort_int8.tflite           # detecta, cuenta y publica
    python ecosort_pi.py --modelo ecosort_int8.tflite --video   # además video en http://<pi>:8000
    python ecosort_pi.py --modelo ecosort_int8.tflite --servos  # además abre la compuerta física (GPIO)

IMPORTANTE: al arrancar, la cámara tiene que ver la escena VACÍA unos 2 segundos.
Ahí aprende cómo es el fondo.

Cuándo se analiza un objeto lo decide raspberry/deteccion.py (ADR 0009): hace falta que lo que
apareció quede quieto ~1 s y tenga un tamaño de residuo; recién ahí se clasifican los cuadros más
nítidos y se decide por el promedio. Una mano que pasa, una cara o un animal no llegan al modelo, o
si llegan el modelo los descarta con la clase "ninguno". Se cuenta UN evento por objeto aceptado, y
no vuelve a analizar nada hasta que la plataforma queda libre.

Un objeto incierto (parece un residuo pero no se sabe cuál) también publica un evento, pero
forzado a la clase "organico" (ADR 0002): comparte contenedor con la baja confianza, a costa
de su pureza — es un trade-off documentado, no un error.

Tópicos MQTT que publica:
    ecosort/<id>/vivo     -> estado de la detección, ~3 veces por segundo (QoS 0)
    ecosort/<id>/eventos  -> un mensaje por residuo aceptado o incierto (QoS 1), ver docs/contrato-mqtt.md

Necesita en la misma carpeta: inferencia_pi.py, ecosort_mqtt.py, clases.py, deteccion.py,
labels.txt, y la carpeta schema/ (schema/clases.json). Además vista_en_vivo.py si se usa --video,
y servos.py (+ gpiozero) si se usa --servos.
"""

import argparse
import os
import threading
import time

import cv2
import numpy as np

from clases import DESCARTES, compuerta_de, producto_de
from deteccion import Cuadro, Deteccion, Estado, Parametros, fraccion_distinta
from ecosort_mqtt import EcoSortMQTT
from inferencia_pi import Clasificador

PARAMETROS = Parametros(
    # Primer ajuste empírico con cámara real (ver BITACORA.md): por defecto, cualquier
    # movimiento (hasta el temblor de la mano o ruido del sensor) reinicia la cuenta de quietud
    # a cero, y 8 cuadros quietos seguidos a ~8 fps piden ~1 s de pulso perfecto — se sentía como
    # que "no respondía" o que hacía falta un ángulo exacto. Se relaja sin sacar la protección
    # (sigue exigiendo presencia + quietud + tamaño antes de correr el modelo):
    umbral_quietud=0.02,   # antes 0.01: tolera algo más de temblor/ruido entre cuadro y cuadro
    frames_quietud=5,      # antes 8 (~1 s): ahora ~0.6 s a 8 fps nominales (la fps real puede ser menor)
    area_max=0.70,         # antes 0.60: no descarta por "tamaño" un objeto sostenido cerca de cámara
    frames_ausente=4,      # antes 8: más rápido en notar que el objeto (y la mano) ya se fueron de
                            # encima de la plataforma — con fps real por debajo del nominal, 8 cuadros
                            # se sentían como ~10 s hasta poder analizar el siguiente objeto
    # umbral_conf: 0.70 -> 0.55, TRADE-OFF EXPLÍCITO (29/10, ver BITACORA.md), no una mejora real de
    # confianza: con el modelo actual, la etiqueta más probable suele ser la correcta aunque quede
    # por debajo de 0.70, y hoy eso se pierde entero en orgánico. Bajarlo acepta más esos casos como
    # clasificación real, a costa de más contaminación cruzada cuando SÍ se equivoca. Revisar este
    # valor en cuanto haya un modelo reentrenado con datos propios — ahí la confianza real
    # debería subir y este número debería poder volver a acercarse a 0.70.
    umbral_conf=0.55,
)
DIF_PIXEL = 30              # diferencia de gris (0-255) para considerar que un píxel cambió respecto del fondo
DIF_MOV = 20                # ... respecto del cuadro anterior: eso es movimiento


def _clase_y_compuerta(d):
    """Qué compuerta corresponde a una decisión aceptada o incierta: la misma regla que
    ecosort_mqtt.armar_evento usa para el evento que se publica (ADR 0002: incierto se fuerza a
    'organico'), para que el servo que se abre sea siempre el mismo contenedor donde cae el evento."""
    clase = "organico" if d.tipo == "incierto" else producto_de(d.etiqueta)
    return clase, compuerta_de(clase)


def recorte_centrado(forma, fraccion):
    """Cuadrado centrado del cuadro (misma idea que vision/webcam_test.py:get_roi_box): simula en
    software el collar centrador del gabinete, que todavía no está armado. Se usa para medir
    presencia/quietud y para lo que se le pasa al modelo — así el ruido de los bordes (luz,
    sombras, algo que se mueve al costado) no reinicia la cuenta de quietud, y el objeto ocupa más
    del cuadro que se clasifica en vez de diluirse en el resto de la imagen."""
    h, w = forma[:2]
    lado = int(min(h, w) * fraccion)
    cx, cy = w // 2, h // 2
    x1, y1 = cx - lado // 2, cy - lado // 2
    return x1, y1, x1 + lado, y1 + lado


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
    def __init__(self, clf, pub, modelo, cam_id=0, fps=8, video=False, roi_fraccion=0.9, compuertas=None):
        self.clf, self.pub, self.modelo, self.video = clf, pub, modelo, video
        self.compuertas = compuertas   # servos.Compuertas, o None (sin hardware: solo se publica el evento)
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
        self.roi = recorte_centrado((480, 640), roi_fraccion)   # fijo: la resolución de captura no cambia
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
        ultimo_fps, cuadros_fps = time.monotonic(), 0   # fps real del loop, para calibrar frames_* a ojo

        while True:
            t0 = time.monotonic()
            cuadros_fps += 1
            if t0 - ultimo_fps >= 5.0:
                print(f"[fps] {cuadros_fps / (t0 - ultimo_fps):.1f} cuadros/s reales "
                      f"(nominal: {1 / self.periodo:.0f})")
                ultimo_fps, cuadros_fps = t0, 0
            frame = self._leer()
            if frame is None:
                time.sleep(0.1)
                continue
            original = frame.copy()
            x1, y1, x2, y2 = self.roi
            recorte = frame[y1:y2, x1:x2]

            # 1) Qué cambió en el recorte centrado (no en el cuadro completo: lo que se mueve fuera
            # de ahí no cuenta ni como presencia ni como quietud — ver recorte_centrado) y, mientras
            # algo se asienta, qué tan nítido
            cambio, g = self.fondo.medir(recorte)
            cambio_prev = fraccion_distinta(g, g_prev, DIF_MOV) if g_prev is not None else 0.0
            g_prev = g
            nitidez = self._nitidez(recorte, g) if maquina.estado is Estado.ASENTANDO else 0.0

            # 2) La máquina decide. El modelo solo corre si pasó la quietud y la plausibilidad.
            tiempos = []

            def clasificar(f):
                probs, ms = self.clf.probabilidades(f)
                tiempos.append(ms)
                return probs

            r = maquina.paso(Cuadro(cambio, cambio_prev, nitidez, recorte), clasificar)
            if maquina.puede_aprender_fondo:
                self.fondo.aprender(g)

            d = r.decision
            if d is not None:
                ultima = d
                if d.tipo in ("aceptado", "incierto"):
                    # incierto: mismo evento, pero armar_evento fuerza la clase a "organico"
                    # (ADR 0002) cuando se le pasa un motivo — el modelo vio d.etiqueta, no organico.
                    _, compuerta = _clase_y_compuerta(d)
                    # compuerta in self.compuertas.pines: hoy solo hay servo para 1-4 (metal, la
                    # quinta compuerta, todavía no tiene servo propio — ver BITACORA.md). Sin eso,
                    # el evento se publica igual, pero accionado queda en False (no se movió nada).
                    accionado = bool(self.compuertas and compuerta in self.compuertas.pines)
                    if accionado:
                        self.compuertas.abrir(compuerta)   # no bloquea: corre en otro hilo
                    self.pub.publicar_evento(d.etiqueta, d.confianza,
                                             latencia_ms=round(sum(tiempos) / len(tiempos), 1),
                                             modelo=self.modelo,
                                             motivo=d.motivo if d.tipo == "incierto" else None,
                                             accionado=accionado)
                    total += 1
                    if d.tipo == "aceptado":
                        print(f"[{total}] contado: {d.etiqueta} ({d.confianza:.0%})")
                    else:
                        print(f"[{total}] incierto -> organico: el modelo vio {d.etiqueta} "
                             f"({d.confianza:.0%}), motivo {d.motivo}")
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
            publicada = ultima is not None and ultima.tipo in ("aceptado", "incierto")
            if t0 - ultimo_vivo >= 0.33:
                self.pub.publicar_vivo({
                    "presente": maquina.estado is not Estado.LIBRE,
                    "estado": maquina.estado.value,
                    # incierto también publica un evento, pero a "organico" (ADR 0002): acá se
                    # muestra esa clase real, no la etiqueta cruda que vio el modelo (esa va en vivo
                    # como "motivo", igual que un descarte)
                    "clase": ("organico" if ultima.tipo == "incierto" else ultima.etiqueta) if publicada else None,
                    "confianza": round(ultima.confianza, 4) if publicada else None,
                    "contado": publicada,
                    "motivo": ultima.motivo if ultima is not None else None,
                })
                ultimo_vivo = t0

            if self.video:
                if ultima is not None and ultima.tipo == "aceptado":
                    texto = f"{ultima.etiqueta} {ultima.confianza:.0%}  [contado]"
                elif ultima is not None and ultima.tipo == "incierto":
                    texto = f"incierto ({ultima.motivo}): el modelo vio {ultima.etiqueta} -> organico"
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
        x1, y1, x2, y2 = self.roi
        cv2.rectangle(frame, (x1, y1), (x2, y2), (80, 255, 80), 1)   # recorte que de verdad se analiza
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
    ap.add_argument("--roi-fraccion", type=float, default=0.9,
                     help="lado del recuadro central que se analiza y se clasifica, como fracción "
                          "del lado más chico del cuadro (0-1); ver recorte_centrado. Default alto "
                          "a propósito: con el objeto sostenido en mano a distancia variable, un "
                          "recorte ajustado corta el objeto (ver BITACORA.md) — conviene volver a "
                          "ajustar esto cuando haya una distancia cámara-objeto fija (gabinete real)")
    # ECOSORT_BROKER / ECOSORT_DISPOSITIVO: lo que varía por Pi física (qué broker, con qué
    # identidad se publica). Los lee systemd desde infra/ansible/templates/ecosort_pi.env.j2
    # (EnvironmentFile); el flag sigue existiendo para correrlo a mano y gana si se pasa.
    ap.add_argument("--broker", default=os.getenv("ECOSORT_BROKER", "localhost"))
    ap.add_argument("--dispositivo", default=os.getenv("ECOSORT_DISPOSITIVO", "ecosort-01"))
    ap.add_argument("--servos", action="store_true",
                     help="abrir de verdad la compuerta correspondiente por GPIO (raspberry/servos.py). "
                          "Requiere gpiozero y los 4 servos conectados; sin este flag, el evento se "
                          "publica igual pero no se mueve nada (accionado: false)")
    args = ap.parse_args()

    clf = Clasificador(args.modelo)
    pub = EcoSortMQTT(dispositivo_id=args.dispositivo, host=args.broker)
    compuertas = None
    if args.servos:
        from servos import Compuertas
        compuertas = Compuertas()
    det = Detector(clf, pub, args.modelo, args.cam, video=args.video, roi_fraccion=args.roi_fraccion,
                   compuertas=compuertas)

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
        if compuertas:
            compuertas.cerrar()
