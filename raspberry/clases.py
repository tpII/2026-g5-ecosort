"""Vocabulario de clases del contrato (schema/clases.json, ADR 0008 y 0009).

Traduce lo que devuelve el modelo (p. ej. 'cardboard') a la clase de producto que viaja
por MQTT ('papel') y a su compuerta. Si el modelo se reentrena y ya devuelve clases de
producto, se aceptan tal cual. Las etiquetas de "descarte" (p. ej. 'ninguno': una mano, una
cara, un animal) no tienen clase de producto: la Pi no abre nada y no publica ningún evento.
"""

import json
import os
from pathlib import Path


def _ubicar_json():
    if os.getenv("ECOSORT_CLASES"):
        return Path(os.environ["ECOSORT_CLASES"])
    aqui = Path(__file__).resolve().parent
    # en el repo, schema/ es hermana de raspberry/; en la Pi (guía, paso 7) queda en
    # ~/ecosort/schema/ junto a los scripts
    candidatas = (aqui.parent / "schema" / "clases.json", aqui / "schema" / "clases.json")
    for c in candidatas:
        if c.exists():
            return c
    raise FileNotFoundError(
        "No encuentro schema/clases.json (busqué en: " + ", ".join(map(str, candidatas)) + "). "
        "Copiá la carpeta schema/ a la Pi junto a los scripts, o definí ECOSORT_CLASES.")


_datos = json.loads(_ubicar_json().read_text(encoding="utf-8"))
COMPUERTAS = _datos["compuertas"]        # clase de producto -> número de compuerta
MAPEO_MODELO = _datos["mapeo_modelo"]    # etiqueta del modelo -> clase de producto
DESCARTES = frozenset(_datos["descartes"])  # etiquetas del modelo que significan "no es un residuo"


def es_descarte(clase_modelo):
    return clase_modelo in DESCARTES


def producto_de(clase_modelo):
    """Clase de producto para una etiqueta del modelo, o None si es un descarte ('no es un
    residuo'). KeyError si no se puede mapear."""
    if clase_modelo in DESCARTES:
        return None
    if clase_modelo in MAPEO_MODELO:
        return MAPEO_MODELO[clase_modelo]
    if clase_modelo in COMPUERTAS:
        return clase_modelo
    raise KeyError(f"la etiqueta del modelo {clase_modelo!r} no está en schema/clases.json "
                   f"(mapeo_modelo) ni es una clase de producto {list(COMPUERTAS)}")


def compuerta_de(clase_producto):
    return COMPUERTAS[clase_producto]


def validar_etiquetas(etiquetas):
    """Falla al arrancar, no en medio de la clasificación, si el modelo tiene una etiqueta
    que el contrato no sabe mapear (p. ej. se reentrenó con una clase nueva)."""
    sin_mapeo = [e for e in etiquetas
                 if e not in MAPEO_MODELO and e not in COMPUERTAS and e not in DESCARTES]
    if sin_mapeo:
        raise SystemExit(f"El modelo tiene etiquetas sin mapeo en schema/clases.json: {sin_mapeo}. "
                         "Agregalas a 'mapeo_modelo' (requiere review de los 3).")
