# mapeo TrashNet (6 clases) -> clases de producto / compuertas del gabinete.
#
# la fuente única es schema/clases.json (ADR 0008); esto es una copia para el lado del
# entrenamiento, que no tiene schema/ en su imagen de Docker. schema/tests/test_contrato.py
# falla si dejan de coincidir. son 5 clases y 5 compuertas: metal tiene la suya (la quinta
# se suma en noviembre; en octubre las salidas se simulan con leds).
# train.py sigue entrenando con las 6 clases nativas, este mapeo se aplica al servir el modelo.

# orden alfabético, igual a build_manifest en dataset.py
TRASHNET_CLASSES = ["cardboard", "glass", "metal", "paper", "plastic", "trash"]

# clase de producto -> compuerta
COMPUERTAS = {"plastico": 1, "papel": 2, "vidrio": 3, "organico": 4, "metal": 5}

PRODUCT_CLASSES = list(COMPUERTAS)

# etiquetas que significan "no es un residuo" (manos, caras, animales, plataforma vacía): se
# entrenan como una clase más (carpeta ninguno/ con negativos), pero nunca abren una compuerta
DESCARTES = ["ninguno"]

TRASHNET_TO_PRODUCT = {
    "cardboard": "papel",
    "paper": "papel",
    "glass": "vidrio",
    "plastic": "plastico",
    "trash": "organico",
    "metal": "metal",
}
