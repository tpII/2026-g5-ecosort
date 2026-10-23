"""prueba en vivo contra la webcam, como cam_test.py de TrashNate pero para
los modelos de train.py/export_tflite.py. sirve para .keras y .tflite (probar
el .tflite acá confirma que la cuantización no rompió nada antes de subirlo a la Pi).

uso:
    python webcam_test.py --run-dir runs/mobilenetv3small --model final.keras
    python webcam_test.py --run-dir runs/mobilenetv3small --model model_int8.tflite
"""

import argparse
import json
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf


class KerasPredictor:
    def __init__(self, model_path: Path, img_size):
        self.model = tf.keras.models.load_model(model_path)
        self.img_size = img_size

    def predict(self, img_rgb):
        img = cv2.resize(img_rgb, self.img_size).astype(np.float32)
        img = np.expand_dims(img, axis=0)  # [0,255] — el modelo normaliza internamente
        return self.model.predict(img, verbose=0)[0]


class TFLitePredictor:
    def __init__(self, model_path: Path, img_size):
        self.interpreter = tf.lite.Interpreter(model_path=str(model_path))
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()[0]
        self.output_details = self.interpreter.get_output_details()[0]
        self.img_size = img_size

    def predict(self, img_rgb):
        img = cv2.resize(img_rgb, self.img_size)
        img = np.expand_dims(img, axis=0).astype(self.input_details["dtype"])
        self.interpreter.set_tensor(self.input_details["index"], img)
        self.interpreter.invoke()
        out = self.interpreter.get_tensor(self.output_details["index"])[0]

        # des-cuantizar la salida a probabilidades reales
        scale, zero_point = self.output_details["quantization"]
        if scale:
            out = (out.astype(np.float32) - zero_point) * scale
        return out


def get_roi_box(frame_shape, fraction):
    # cuadrado centrado, simula lo que después hace el collar centrador en el gabinete
    h, w = frame_shape[:2]
    side = int(min(h, w) * fraction)
    cx, cy = w // 2, h // 2
    x1, y1 = cx - side // 2, cy - side // 2
    return x1, y1, x1 + side, y1 + side


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default="runs/mobilenetv3small")
    parser.add_argument("--model", default="final.keras")
    parser.add_argument("--img-size", type=int, default=128)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--smooth-frames", type=int, default=8,
                         help="frames a promediar para que no titile la predicción (0 = sin suavizado)")
    parser.add_argument("--min-confidence", type=float, default=50.0,
                         help="por debajo de esto muestra 'Incierto' en vez de forzar una clase")
    parser.add_argument("--roi-fraction", type=float, default=0.5,
                         help="lado del recuadro central que se clasifica (0-1, fracción del lado "
                              "más chico del frame)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    classes = json.loads((run_dir / "classes.json").read_text())
    model_path = run_dir / args.model
    img_size = (args.img_size, args.img_size)

    if model_path.suffix == ".tflite":
        predictor = TFLitePredictor(model_path, img_size)
    else:
        predictor = KerasPredictor(model_path, img_size)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise RuntimeError(
            f"No se pudo abrir la cámara {args.camera} "
            "(¿está en uso por otra app, o es otro índice? probá --camera 1)"
        )

    history = deque(maxlen=max(args.smooth_frames, 1))

    print("Cámara abierta. Presioná 'q' para salir.")
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        x1, y1, x2, y2 = get_roi_box(frame.shape, args.roi_fraction)
        roi_bgr = frame[y1:y2, x1:x2]

        rgb = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB)
        probs = predictor.predict(rgb)

        # promedio de las últimas N para que no titile entre frames
        history.append(probs)
        smoothed = np.mean(history, axis=0)

        idx = int(np.argmax(smoothed))
        confidence = float(smoothed[idx]) * 100
        if confidence >= args.min_confidence:
            label = f"{classes[idx]} ({confidence:.1f}%)"
            color = (0, 255, 0)
        else:
            label = f"Incierto (max: {classes[idx]} {confidence:.1f}%)"
            color = (0, 165, 255)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, "Colocar objeto aca", (x1, max(y1 - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.putText(frame, f"Clase: {label}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        cv2.imshow("EcoSort - prueba webcam", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
