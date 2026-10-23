"""Tests de la máquina de estados de detección (raspberry/deteccion.py, ADR 0009).

Secuencias sintéticas de cuadros: una mano que pasa, una que se agita, una cara quieta y enorme, un
objeto que se asienta... Sin cámara, sin modelo y sin Pi:

    pip install numpy
    python -m unittest discover -s raspberry/tests -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deteccion import Cuadro, Deteccion, Estado, Parametros, fraccion_distinta  # noqa: E402

ETIQUETAS = ["cardboard", "glass", "metal", "ninguno", "paper", "plastic", "trash"]


def probs(**valores):
    """Vector de probabilidades en el orden de ETIQUETAS; lo que no se nombra queda en 0."""
    return np.array([valores.get(e, 0.0) for e in ETIQUETAS])


def vacio(n):
    return [Cuadro(0.0, 0.0) for _ in range(n)]


def moviendo(n, area=0.2):
    return [Cuadro(area, 0.15) for _ in range(n)]


def quieto(n, area=0.10, nitidez=None):
    nitidez = nitidez or [0.0] * n
    return [Cuadro(area, 0.001, nitidez[i], payload=i) for i in range(n)]


class Banco:
    """Alimenta la máquina con cuadros y registra qué pasó y cuántas veces se corrió el modelo."""

    def __init__(self, respuesta, params=None, etiquetas=ETIQUETAS):
        self.det = Deteccion(etiquetas, descartes=("ninguno",), params=params)
        self.respuesta = respuesta
        self.llamadas = []
        self.resultados = []

    def clasificar(self, payload):
        self.llamadas.append(payload)
        return self.respuesta(payload) if callable(self.respuesta) else self.respuesta

    def alimentar(self, *tramos):
        for tramo in tramos:
            for cuadro in tramo:
                self.resultados.append(self.det.paso(cuadro, self.clasificar))
        return self

    @property
    def decisiones(self):
        return [r.decision for r in self.resultados if r.decision]

    @property
    def senales(self):
        return [s for r in self.resultados for s in r.senales]


class LoQueNoDebeAnalizarse(unittest.TestCase):
    def test_una_mano_que_pasa_no_llega_al_modelo(self):
        b = Banco(probs(cardboard=0.9)).alimentar(vacio(5), moviendo(6, area=0.3), vacio(10))
        self.assertEqual(b.decisiones, [])
        self.assertEqual(b.llamadas, [], "el modelo no tendría que haber corrido")
        self.assertEqual([n for n, _ in b.senales], ["presente", "transito"])
        self.assertIs(b.det.estado, Estado.LIBRE)

    def test_una_mano_que_se_agita_mucho_tiempo_se_descarta_sin_correr_el_modelo(self):
        b = Banco(probs(cardboard=0.9), Parametros(max_asentando=20))
        b.alimentar(vacio(3), moviendo(30), vacio(10))
        self.assertEqual([(d.tipo, d.motivo) for d in b.decisiones], [("descartado", "sin_quietud")])
        self.assertEqual(b.llamadas, [])
        self.assertIn(("retirado", "descartado"), b.senales)

    def test_una_cara_quieta_pero_enorme_se_descarta_por_tamano(self):
        b = Banco(probs(cardboard=0.9)).alimentar(moviendo(3, area=0.8), quieto(8, area=0.8))
        self.assertEqual([(d.tipo, d.motivo) for d in b.decisiones], [("descartado", "tamano")])
        self.assertEqual(b.llamadas, [])

    def test_el_ruido_del_fondo_no_dispara_nada(self):
        b = Banco(probs(cardboard=0.9)).alimentar([Cuadro(0.01, 0.005)] * 200)
        self.assertEqual(b.senales, [])
        self.assertIs(b.det.estado, Estado.LIBRE)

    def test_un_cuadro_borroso_no_se_analiza_si_se_pide_un_piso_de_nitidez(self):
        b = Banco(probs(cardboard=0.9), Parametros(nitidez_min=50))
        b.alimentar(moviendo(3), quieto(8, nitidez=[10.0] * 8))
        self.assertEqual([(d.tipo, d.motivo) for d in b.decisiones], [("descartado", "borroso")])
        self.assertEqual(b.llamadas, [])


class QuietudYAnalisis(unittest.TestCase):
    def test_un_objeto_que_se_asienta_se_acepta_una_sola_vez(self):
        b = Banco(probs(plastic=0.9, glass=0.1))
        b.alimentar(vacio(3), moviendo(6, area=0.1), quieto(8))
        self.assertEqual(len(b.decisiones), 1)
        d = b.decisiones[0]
        self.assertEqual((d.tipo, d.etiqueta), ("aceptado", "plastic"))
        b.alimentar(quieto(40))          # sigue ahí: no se vuelve a decidir
        self.assertEqual(len(b.decisiones), 1)
        b.alimentar(vacio(10))
        self.assertEqual([n for n, _ in b.senales], ["presente", "aceptado", "retirado"])
        self.assertIn(("retirado", "aceptado"), b.senales)   # después de aceptado, retirado = cayó

    def test_cualquier_movimiento_reinicia_la_cuenta_de_quietud(self):
        b = Banco(probs(plastic=0.9))
        b.alimentar(moviendo(3), quieto(5), moviendo(1), quieto(7))
        self.assertEqual(b.decisiones, [], "7 cuadros quietos seguidos no alcanzan")
        b.alimentar(quieto(1))
        self.assertEqual(len(b.decisiones), 1, "el octavo cuadro quieto seguido sí")

    def test_se_clasifican_solo_los_k_cuadros_mas_nitidos(self):
        nitidez = [1, 9, 3, 8, 2, 7, 4, 6]
        b = Banco(probs(plastic=0.9)).alimentar(moviendo(3), quieto(8, nitidez=nitidez))
        self.assertEqual(len(b.llamadas), 5)
        self.assertEqual(set(b.llamadas), {1, 3, 5, 7, 6})   # nitidez 9, 8, 7, 6 y 4

    def test_se_decide_por_el_promedio_de_probabilidades_no_por_un_cuadro(self):
        # un cuadro suelto dice "trash" con fuerza, los otros cuatro dicen "paper": gana paper
        def respuesta(i):
            return probs(trash=1.0) if i == 0 else probs(paper=0.9, plastic=0.1)
        b = Banco(respuesta).alimentar(moviendo(3), quieto(8, nitidez=[5, 9, 8, 7, 6, 1, 1, 1]))
        self.assertEqual(b.decisiones[0].etiqueta, "paper")

    def test_al_retirarse_se_puede_analizar_un_segundo_objeto(self):
        b = Banco(probs(glass=0.9))
        b.alimentar(moviendo(3), quieto(8), vacio(10), moviendo(3), quieto(8), vacio(10))
        self.assertEqual([d.tipo for d in b.decisiones], ["aceptado", "aceptado"])

    def test_si_no_se_retira_pasado_el_tiempo_avisa_una_sola_vez(self):
        b = Banco(probs(glass=0.9), Parametros(max_retiro=15))
        b.alimentar(moviendo(3), quieto(8), quieto(40))
        self.assertEqual(b.senales.count(("no_retirado", "aceptado")), 1)   # tras aceptado = se trabó
        b.alimentar(vacio(10))
        self.assertIn(("retirado", "aceptado"), b.senales)

    def test_el_fondo_solo_se_aprende_con_la_plataforma_libre(self):
        b = Banco(probs(glass=0.9))
        self.assertTrue(b.det.puede_aprender_fondo)
        b.alimentar(moviendo(3))
        self.assertFalse(b.det.puede_aprender_fondo)
        b.alimentar(moviendo(3), quieto(8))
        self.assertFalse(b.det.puede_aprender_fondo, "esperando el retiro tampoco")
        b.alimentar(vacio(10))
        self.assertTrue(b.det.puede_aprender_fondo)


class ClaseNinguno(unittest.TestCase):
    def test_si_el_modelo_dice_ninguno_se_descarta_y_no_se_acepta_nunca(self):
        b = Banco(probs(ninguno=0.9, cardboard=0.1)).alimentar(moviendo(3), quieto(8), vacio(10))
        self.assertEqual([(d.tipo, d.motivo) for d in b.decisiones], [("descartado", "no_residuo")])
        self.assertNotIn("aceptado", [n for n, _ in b.senales])
        self.assertEqual(len(b.llamadas), 5, "el modelo sí corrió: fue él quien lo rechazó")

    def test_si_ninguno_tiene_mucha_probabilidad_aunque_no_gane_tambien_se_descarta(self):
        b = Banco(probs(cardboard=0.5, ninguno=0.45, paper=0.05)).alimentar(moviendo(3), quieto(8))
        self.assertEqual([(d.tipo, d.motivo) for d in b.decisiones], [("descartado", "no_residuo")])

    def test_con_el_modelo_actual_de_6_clases_funciona_igual(self):
        seis = [e for e in ETIQUETAS if e != "ninguno"]
        respuesta = np.array([0.9 if e == "cardboard" else 0.02 for e in seis])
        b = Banco(respuesta, etiquetas=seis).alimentar(moviendo(3), quieto(8))
        self.assertEqual([(d.tipo, d.etiqueta) for d in b.decisiones], [("aceptado", "cardboard")])


class Incertidumbre(unittest.TestCase):
    def test_baja_confianza_es_incierto_y_no_se_acepta(self):
        b = Banco(probs(cardboard=0.5, glass=0.3, paper=0.2)).alimentar(moviendo(3), quieto(8))
        self.assertEqual([(d.tipo, d.motivo) for d in b.decisiones], [("incierto", "baja_confianza")])
        self.assertIn(("incierto", "baja_confianza"), b.senales)

    def test_cuadros_que_no_coinciden_entre_si_es_incierto(self):
        def respuesta(i):   # los 3 primeros dicen cardboard por poco, los 2 últimos glass con fuerza
            return probs(cardboard=0.55, glass=0.45) if i < 3 else probs(glass=0.9, cardboard=0.05)
        b = Banco(respuesta, Parametros(umbral_conf=0.5))
        b.alimentar(moviendo(3), quieto(8, nitidez=[9, 8, 7, 6, 5, 1, 1, 1]))
        self.assertEqual([(d.tipo, d.motivo) for d in b.decisiones], [("incierto", "inconsistente")])


class Auxiliares(unittest.TestCase):
    def test_k_analisis_no_puede_superar_los_cuadros_quietos(self):
        with self.assertRaises(ValueError):
            Parametros(k_analisis=9, frames_quietud=8)

    def test_fraccion_distinta_mide_movimiento(self):
        a = np.zeros((120, 160), np.float32)
        b = a.copy()
        b[10:30, 10:30] = 200          # un cuadrado de 20x20 = 400 de 19200 píxeles
        self.assertAlmostEqual(fraccion_distinta(a, b, 30), 400 / 19200)
        self.assertEqual(fraccion_distinta(a, a, 30), 0.0)
        self.assertEqual(fraccion_distinta(a, a + 10, 30), 0.0, "un cambio chico de luz no cuenta")


if __name__ == "__main__":
    unittest.main()
