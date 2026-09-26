"""Cuándo y si analizar un objeto (ADR 0009).

Máquina de estados pura: no abre la cámara ni carga el modelo. Recibe características de cada
cuadro y una función para clasificar, y decide. Por eso se prueba con secuencias sintéticas
(raspberry/tests/test_deteccion.py), sin cámara ni Pi.

El modelo es de clases cerradas: siempre elige alguna, aunque le muestres una mano, una cara o una
pared (medido: con entradas que no eran residuos, 6 de 9 superaron el umbral de confianza). La
protección no puede depender solo de su confianza, así que se exige, en cascada y de lo barato a lo
caro:

  1. presencia    la escena cambió respecto del fondo vacío (cada cuadro, casi gratis)
  2. quietud      lo que apareció dejó de moverse ~1 s. Una mano que se agita o alguien que pasa
                  nunca queda quieto, y ahí termina: no se corre el modelo
  3. plausibilidad el tamaño de la mancha es el de un residuo (una cara o un brazo ocupan mucho más)
  4. modelo       se clasifican solo los K cuadros más nítidos de los quietos y se decide por el
                  promedio de sus probabilidades, no por un cuadro suelto. Si el modelo dice
                  "ninguno" (o le da bastante probabilidad), se descarta

La decisión es una de tres, y se toma una sola vez por objeto:
  aceptado     es un residuo y se sabe cuál: la Pi publica el evento
  incierto     parece un residuo pero no se sabe cuál (baja confianza, cuadros que no coinciden)
  descartado   no es un residuo, o no se dieron las condiciones para analizarlo

Después espera a que la plataforma quede libre. Eso da, además, las señales que el firmware puede
convertir en luces y sonidos ("objeto no reconocido", "cayó", "se trabó"): ver `Resultado.senales`.

Los umbrales son valores iniciales, SIN calibrar con la cámara real del gabinete (ver ADR 0009).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np


class Estado(Enum):
    LIBRE = "libre"                          # plataforma vacía: se puede aprender el fondo
    ASENTANDO = "asentando"                  # hay algo: se espera a que quede quieto
    ESPERANDO_RETIRO = "esperando_retiro"    # ya se decidió: se espera a que la plataforma se libere


@dataclass(frozen=True)
class Parametros:
    # presencia (mismos valores que usaba ecosort_pi.py)
    umbral_cambio: float = 0.03       # fracción de la imagen distinta del fondo para decir "hay algo"
    frames_presente: int = 3          # cuadros seguidos con cambio para marcar que llegó algo
    frames_ausente: int = 8           # cuadros seguidos sin cambio para darlo por retirado
    # quietud
    umbral_quietud: float = 0.01      # fracción distinta del cuadro anterior: por debajo, está quieto
    frames_quietud: int = 8           # cuadros quietos seguidos (~1 s a 8 fps)
    max_asentando: int = 120          # si en ~15 s no se queda quieto, se descarta
    # plausibilidad: lo que cambió no puede ocupar más que esto de la imagen (una cara o un brazo sí;
    # no hace falta un mínimo: para existir, algo ya tiene que superar umbral_cambio)
    area_max: float = 0.60
    # análisis
    k_analisis: int = 5               # cuadros más nítidos que se clasifican
    umbral_conf: float = 0.70         # confianza mínima del promedio de probabilidades
    acuerdo_min: float = 0.60         # fracción de esos cuadros que tienen que coincidir con la clase final
    umbral_descarte: float = 0.40     # probabilidad (promedio) en las clases de descarte que ya alcanza
    nitidez_min: Optional[float] = None  # piso de nitidez; None = solo se elige a los más nítidos
    # retiro
    max_retiro: int = 240             # cuadros esperando que se libere la plataforma (~30 s)

    def __post_init__(self):
        if self.k_analisis > self.frames_quietud:
            raise ValueError("k_analisis no puede ser mayor que frames_quietud: no habría de dónde elegir")


@dataclass(frozen=True)
class Cuadro:
    """Lo que la máquina necesita saber de un cuadro (lo calcula ecosort_pi.py)."""
    cambio_fondo: float        # fracción de píxeles distintos del fondo vacío (0 a 1); también es el área
    cambio_prev: float         # fracción de píxeles distintos del cuadro anterior (0 a 1): movimiento
    nitidez: float = 0.0       # mayor = más nítido; solo se usa para ordenar los cuadros entre sí
    payload: object = None     # el cuadro en sí, que se le pasa a `clasificar` si hace falta


@dataclass(frozen=True)
class Decision:
    tipo: str                             # "aceptado" | "incierto" | "descartado"
    motivo: Optional[str] = None          # por qué (no aplica a "aceptado")
    etiqueta: Optional[str] = None        # clase del modelo con más probabilidad
    confianza: Optional[float] = None     # su probabilidad promedio
    probabilidades: tuple = ()            # promedio por etiqueta, en el orden de `etiquetas`


@dataclass(frozen=True)
class Resultado:
    estado: Estado
    senales: tuple = ()                   # ((nombre, dato), ...): ver abajo
    decision: Optional[Decision] = None   # solo en el cuadro en que se decide


# Señales (Resultado.senales), pensadas para que el firmware las convierta en luces y sonidos:
#   ("presente", None)                  llegó algo
#   ("transito", None)                  se fue antes de quedarse quieto (alguien que pasó)
#   ("aceptado", etiqueta)              reconocido: se abre la compuerta
#   ("incierto", motivo)                parece un residuo pero no se sabe cuál
#   ("descartado", motivo)              no es un residuo / no se pudo analizar ("objeto no reconocido")
#   ("retirado", tipo_de_decision)      la plataforma quedó libre; tras "aceptado" = cayó
#   ("no_retirado", tipo_de_decision)   sigue ocupada pasado el tiempo; tras "aceptado" = se trabó


def fraccion_distinta(a, b, umbral):
    """Fracción (0 a 1) de píxeles que difieren en más de `umbral` niveles entre a y b."""
    return float((np.abs(a - b) > umbral).mean())


class Deteccion:
    def __init__(self, etiquetas, descartes=(), params=None):
        """etiquetas: nombres de las salidas del modelo, en orden. descartes: cuáles de ellas
        significan "no es un residuo" (schema/clases.json)."""
        self.p = params or Parametros()
        self.etiquetas = list(etiquetas)
        descartes = set(descartes)
        self._idx_descarte = [i for i, e in enumerate(self.etiquetas) if e in descartes]
        self.reiniciar()

    def reiniciar(self):
        self.estado = Estado.LIBRE
        self._con_cambio = 0
        self._sin_cambio = 0
        self._frames = 0
        self._quietos = []
        self._contexto = None
        self._avisado = False

    @property
    def puede_aprender_fondo(self):
        """El fondo solo se actualiza con la plataforma vacía."""
        return self.estado is Estado.LIBRE

    def paso(self, c, clasificar):
        """Procesa un cuadro. `clasificar(c.payload)` devuelve el vector de probabilidades y solo se
        llama cuando ya se decidió analizar (después de la quietud y la plausibilidad)."""
        p = self.p
        hay_algo = c.cambio_fondo > p.umbral_cambio
        senales = []
        decision = None

        if self.estado is Estado.LIBRE:
            self._con_cambio = self._con_cambio + 1 if hay_algo else 0
            if self._con_cambio >= p.frames_presente:
                self.estado = Estado.ASENTANDO
                self._sin_cambio = self._frames = 0
                self._quietos = []
                senales.append(("presente", None))

        elif self.estado is Estado.ASENTANDO:
            self._frames += 1
            self._sin_cambio = 0 if hay_algo else self._sin_cambio + 1
            if self._sin_cambio >= p.frames_ausente:
                self.reiniciar()   # se fue antes de quedarse quieto: alguien que pasó, una mano
                senales.append(("transito", None))
            else:
                if hay_algo and c.cambio_prev < p.umbral_quietud:
                    self._quietos.append(c)
                else:
                    self._quietos = []   # cualquier movimiento reinicia la cuenta de quietud
                if len(self._quietos) >= p.frames_quietud:
                    decision = self._decidir(clasificar)
                elif self._frames >= p.max_asentando:
                    decision = Decision("descartado", "sin_quietud")
                if decision is not None:
                    self.estado = Estado.ESPERANDO_RETIRO
                    self._contexto = decision.tipo
                    self._sin_cambio = self._frames = 0
                    self._quietos = []
                    self._avisado = False
                    senales.append((decision.tipo, decision.motivo or decision.etiqueta))

        else:  # ESPERANDO_RETIRO
            self._frames += 1
            self._sin_cambio = 0 if hay_algo else self._sin_cambio + 1
            if self._sin_cambio >= p.frames_ausente:
                contexto = self._contexto
                self.reiniciar()
                senales.append(("retirado", contexto))
            elif self._frames >= p.max_retiro and not self._avisado:
                self._avisado = True
                senales.append(("no_retirado", self._contexto))

        return Resultado(self.estado, tuple(senales), decision)

    def _decidir(self, clasificar):
        p = self.p
        quietos = self._quietos

        areas = sorted(q.cambio_fondo for q in quietos)
        if areas[len(areas) // 2] > p.area_max:
            return Decision("descartado", "tamano")   # una cara, un brazo: mucho más que un residuo
        if p.nitidez_min is not None and max(q.nitidez for q in quietos) < p.nitidez_min:
            return Decision("descartado", "borroso")

        mejores = sorted(quietos, key=lambda q: q.nitidez, reverse=True)[:p.k_analisis]
        probs = np.array([np.asarray(clasificar(q.payload), dtype=float) for q in mejores])
        media = probs.mean(axis=0)
        top = int(media.argmax())
        etiqueta, conf = self.etiquetas[top], float(media[top])
        detalle = tuple(float(x) for x in media)

        p_descarte = float(media[self._idx_descarte].sum()) if self._idx_descarte else 0.0
        if top in self._idx_descarte or p_descarte >= p.umbral_descarte:
            return Decision("descartado", "no_residuo", etiqueta, conf, detalle)
        if conf < p.umbral_conf:
            return Decision("incierto", "baja_confianza", etiqueta, conf, detalle)
        if float((probs.argmax(axis=1) == top).mean()) < p.acuerdo_min:
            return Decision("incierto", "inconsistente", etiqueta, conf, detalle)
        return Decision("aceptado", None, etiqueta, conf, detalle)
