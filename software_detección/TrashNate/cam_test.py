import cv2
import numpy as np
from tensorflow.keras.models import load_model

model = load_model("modelo_trashnet.keras")
class_names = ['cardboard', 'glass', 'metal', 'paper', 'plastic', 'trash']

cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # 1. Convertir BGR a RGB
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    # 2. Redimensionar a (128, 128)
    img = cv2.resize(rgb, (128, 128))
    
    # 3. Expandir dimensión batch (sin dividir por 255 porque el modelo ya tiene Rescaling)
    img = np.expand_dims(img, axis=0).astype(np.float32)

    # 4. Inferencia
    pred = model.predict(img, verbose=0)
    idx = np.argmax(pred[0])
    confidence = pred[0][idx] * 100
    label = f"{class_names[idx]} ({confidence:.1f}%)"

    # Mostrar en pantalla
    cv2.putText(frame, f"Clase: {label}", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    cv2.imshow("Clasificador TrashNet", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()