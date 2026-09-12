import cv2
import numpy as np
from tensorflow.keras.models import load_model

# Cargar modelo entrenado
model = load_model("modelo_trashnet.h5")
class_names = ['cardboard', 'glass', 'metal', 'paper', 'plastic', 'trash']

cap = cv2.VideoCapture(0)  # abre la webcam

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Preprocesar imagen
    img = cv2.resize(frame, (128, 128))       # redimensionar
    img = np.expand_dims(img, axis=0) / 255.0 # normalizar

    # Predicción
    pred = model.predict(img)
    label = class_names[np.argmax(pred)]

    # Mostrar resultado en pantalla
    cv2.putText(frame, f"Prediccion: {label}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
    cv2.imshow("Clasificador TrashNet", frame)

    # salir con 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
