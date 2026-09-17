# mapeo TrashNet (6 clases) -> 4 compuertas del gabinete.
#
# falta cerrar qué hacer con metal (sin compuerta, ver ADR 0002): o lo saco
# del dataset o lo mapeo a otra clase para que no confunda al modelo en la
# cámara real. hasta entonces train.py sigue entrenando con las 6 clases
# nativas, este mapeo se aplica recién al servir el modelo.

# orden alfabético, igual a build_manifest en dataset.py
TRASHNET_CLASSES = ["cardboard", "glass", "metal", "paper", "plastic", "trash"]

# una por compuerta (ADR 0002)
PRODUCT_CLASSES = ["papel", "vidrio", "plastico", "organico"]

# TODO: definir metal antes de usar esto en producción
TRASHNET_TO_PRODUCT = {
    "cardboard": "papel",
    "paper": "papel",
    "glass": "vidrio",
    "plastic": "plastico",
    "trash": "organico",  # baja confianza / residuo no clasificable también cae acá
    "metal": None,  # sin compuerta — TODO
}
