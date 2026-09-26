"""Tests del contrato de eventos (docs/contrato-mqtt.md, ADR 0008).

Amarran las cuatro piezas que tienen que decir lo mismo: schema/clases.json, el JSON Schema del
evento, lo que efectivamente publica la Pi (raspberry/ecosort_mqtt.py) y lo que acepta el adapter
del host. Corren sin red ni Docker:

    pip install paho-mqtt jsonschema
    python -m unittest discover -s schema/tests -v
"""

import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

RAIZ = Path(__file__).resolve().parents[2]
CLASES = json.loads((RAIZ / "schema" / "clases.json").read_text(encoding="utf-8"))
ESQUEMA = json.loads((RAIZ / "schema" / "evento.schema.json").read_text(encoding="utf-8"))

# El adapter abre la base y lee el schema al importarse: se apunta a una base temporal.
_tmp = tempfile.TemporaryDirectory()
os.environ["ECOSORT_DB"] = str(Path(_tmp.name) / "test.db")
sys.path.insert(0, str(RAIZ / "raspberry"))
sys.path.insert(0, str(RAIZ / "host" / "adapter"))
import adapter  # noqa: E402
import clases  # noqa: E402
import ecosort_mqtt  # noqa: E402


def _cargar(ruta, nombre):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def evento_valido(**cambios):
    e = ecosort_mqtt.armar_evento("ecosort-01", "cardboard", 0.93, latencia_ms=31.2,
                                  modelo="ecosort_int8.tflite")
    e.update(cambios)
    return e


class ConsistenciaDelVocabulario(unittest.TestCase):
    def test_el_schema_del_evento_acepta_exactamente_las_clases_y_compuertas_de_clases_json(self):
        props = ESQUEMA["properties"]
        self.assertEqual(props["clase"]["enum"], list(CLASES["compuertas"]))
        self.assertEqual(props["compuerta"]["minimum"], 1)
        self.assertEqual(props["compuerta"]["maximum"], len(CLASES["compuertas"]))

    def test_cada_clase_tiene_su_propia_compuerta(self):
        numeros = sorted(CLASES["compuertas"].values())
        self.assertEqual(numeros, list(range(1, len(numeros) + 1)))

    def test_todo_el_mapeo_del_modelo_termina_en_una_clase_de_producto(self):
        for etiqueta, producto in CLASES["mapeo_modelo"].items():
            self.assertIn(producto, CLASES["compuertas"], f"{etiqueta} -> {producto}")

    def test_vision_classes_no_diverge_de_la_fuente_unica(self):
        vision = _cargar(RAIZ / "vision" / "classes.py", "vision_classes")
        self.assertEqual(vision.COMPUERTAS, CLASES["compuertas"])
        self.assertEqual(vision.TRASHNET_TO_PRODUCT, CLASES["mapeo_modelo"])

    def test_las_barras_del_dashboard_son_las_clases_de_producto(self):
        html = (RAIZ / "host" / "dashboard" / "frontend" / "index.html").read_text(encoding="utf-8")
        base = json.loads(re.search(r"const BASE = (\[.*?\]);", html).group(1))
        self.assertEqual(sorted(base), sorted(CLASES["compuertas"]))


class Descartes(unittest.TestCase):
    """'ninguno' y compañía: lo que el modelo puede ver pero NO es un residuo (ADR 0009)."""

    def test_un_descarte_no_es_una_clase_de_producto_ni_tiene_mapeo(self):
        self.assertTrue(CLASES["descartes"])
        for d in CLASES["descartes"]:
            self.assertNotIn(d, CLASES["compuertas"])
            self.assertNotIn(d, CLASES["mapeo_modelo"])
            self.assertNotIn(d, ESQUEMA["properties"]["clase"]["enum"])

    def test_la_pi_los_reconoce_y_no_les_inventa_una_clase(self):
        for d in CLASES["descartes"]:
            self.assertTrue(clases.es_descarte(d))
            self.assertIsNone(clases.producto_de(d))
        self.assertFalse(clases.es_descarte("cardboard"))

    def test_un_descarte_nunca_se_publica_como_evento(self):
        for d in CLASES["descartes"]:
            with self.assertRaises(ValueError):
                ecosort_mqtt.armar_evento("ecosort-01", d, 0.99)

    def test_un_modelo_con_clase_ninguno_arranca_pero_uno_con_una_clase_desconocida_no(self):
        clases.validar_etiquetas(list(CLASES["mapeo_modelo"]) + list(CLASES["descartes"]))
        with self.assertRaises(SystemExit):
            clases.validar_etiquetas(list(CLASES["mapeo_modelo"]) + ["banana"])

    def test_el_estado_en_vivo_de_un_descarte_queda_sin_clase(self):
        publicados = []
        pub = ecosort_mqtt.EcoSortMQTT.__new__(ecosort_mqtt.EcoSortMQTT)   # sin conectar al broker
        pub.dispositivo_id, pub.topic_vivo = "ecosort-01", "ecosort/ecosort-01/vivo"
        pub.client = type("Cliente", (), {"publish": lambda self, t, p, qos: publicados.append(json.loads(p))})()
        pub.publicar_vivo({"presente": True, "clase": "ninguno", "contado": False})
        pub.publicar_vivo({"presente": True, "clase": "cardboard", "contado": True})
        self.assertEqual((publicados[0]["clase"], publicados[0]["clase_modelo"]), (None, "ninguno"))
        self.assertEqual((publicados[1]["clase"], publicados[1]["clase_modelo"]), ("papel", "cardboard"))

    def test_vision_classes_tiene_los_mismos_descartes(self):
        vision = _cargar(RAIZ / "vision" / "classes.py", "vision_classes_descartes")
        self.assertEqual(vision.DESCARTES, CLASES["descartes"])


class LoQuePublicaLaPi(unittest.TestCase):
    def test_todas_las_etiquetas_del_modelo_producen_un_evento_valido(self):
        validador = Draft202012Validator(ESQUEMA)
        for etiqueta in CLASES["mapeo_modelo"]:
            evento = ecosort_mqtt.armar_evento("ecosort-01", etiqueta, 0.8)
            self.assertEqual(list(validador.iter_errors(evento)), [], etiqueta)
            self.assertEqual(evento["clase"], CLASES["mapeo_modelo"][etiqueta])
            self.assertEqual(evento["compuerta"], CLASES["compuertas"][evento["clase"]])
            self.assertEqual(evento["clase_modelo"], etiqueta)

    def test_un_modelo_que_ya_devuelve_clases_de_producto_tambien_funciona(self):
        for clase in CLASES["compuertas"]:
            evento = ecosort_mqtt.armar_evento("ecosort-01", clase, 0.8)
            self.assertEqual(evento["clase"], clase)

    def test_una_etiqueta_desconocida_falla_en_la_pi_y_no_llega_al_broker(self):
        with self.assertRaises(KeyError):
            ecosort_mqtt.armar_evento("ecosort-01", "banana", 0.9)

    def test_metal_va_a_la_quinta_compuerta_y_todavia_no_esta_accionado(self):
        evento = ecosort_mqtt.armar_evento("ecosort-01", "metal", 0.9)
        self.assertEqual((evento["clase"], evento["compuerta"], evento["accionado"]),
                         ("metal", 5, False))

    def test_el_evento_es_json_serializable_y_los_ids_no_se_repiten(self):
        a = ecosort_mqtt.armar_evento("ecosort-01", "glass", 0.9)
        b = ecosort_mqtt.armar_evento("ecosort-01", "glass", 0.9)
        json.dumps(a)
        self.assertNotEqual(a["evento_id"], b["evento_id"])


class LoQueAceptaElAdapter(unittest.TestCase):
    def setUp(self):
        with adapter.db_lock:
            adapter.db.execute("DELETE FROM eventos")
            adapter.db.execute("DELETE FROM eventos_rechazados")
            adapter.db.commit()

    def _n(self, tabla):
        return adapter.db.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]

    def _procesar(self, evento, dispositivo="ecosort-01"):
        adapter.procesar(f"ecosort/{dispositivo}/eventos", json.dumps(evento).encode())

    def test_un_evento_valido_se_guarda_con_todos_sus_campos(self):
        self._procesar(evento_valido(clase_modelo="glass", clase="vidrio", compuerta=3))
        fila = adapter.db.execute(
            "SELECT schema_version, clase, clase_modelo, compuerta, accionado FROM eventos").fetchone()
        self.assertEqual(fila, (1, "vidrio", "glass", 3, 0))
        self.assertEqual(self._n("eventos_rechazados"), 0)

    def test_un_evento_repetido_no_se_cuenta_dos_veces(self):
        e = evento_valido()
        self._procesar(e)
        self._procesar(e)
        self.assertEqual(self._n("eventos"), 1)

    def test_lo_que_no_cumple_el_contrato_se_rechaza_con_motivo_y_no_se_cuenta(self):
        casos = {
            "clase fuera del vocabulario": evento_valido(clase="banana"),
            "confianza no numérica": evento_valido(confianza="abc"),
            "confianza fuera de rango": evento_valido(confianza=7.5),
            "compuerta imposible": evento_valido(compuerta=99),
            "compuerta booleana": evento_valido(compuerta=True),
            "sin schema_version": {k: v for k, v in evento_valido().items() if k != "schema_version"},
            "versión futura": evento_valido(schema_version=2),
            "sin evento_id": {k: v for k, v in evento_valido().items() if k != "evento_id"},
            "evento_id que no es uuid": evento_valido(evento_id="123"),
            "ts sin formato": evento_valido(ts="ayer"),
            "accionado no booleano": evento_valido(accionado="si"),
            "no es un objeto": ["plastico"],
        }
        for nombre, evento in casos.items():
            antes = self._n("eventos_rechazados")
            self._procesar(evento)
            self.assertEqual(self._n("eventos_rechazados"), antes + 1, nombre)
        self.assertEqual(self._n("eventos"), 0)

    def test_un_payload_que_no_es_json_se_rechaza(self):
        adapter.procesar("ecosort/ecosort-01/eventos", b"esto no es json")
        self.assertEqual(self._n("eventos"), 0)
        motivo = adapter.db.execute("SELECT motivo FROM eventos_rechazados").fetchone()[0]
        self.assertIn("JSON", motivo)

    def test_el_dispositivo_del_payload_tiene_que_coincidir_con_el_del_topico(self):
        self._procesar(evento_valido(dispositivo_id="ecosort-01"), dispositivo="ecosort-99")
        self.assertEqual(self._n("eventos"), 0)
        motivo = adapter.db.execute("SELECT motivo FROM eventos_rechazados").fetchone()[0]
        self.assertIn("ecosort-99", motivo)

    def test_los_campos_desconocidos_se_toleran_para_poder_evolucionar_sin_romper_v1(self):
        self._procesar(evento_valido(campo_nuevo_opcional="x"))
        self.assertEqual(self._n("eventos"), 1)

    def test_el_payload_rechazado_se_guarda_truncado(self):
        adapter.procesar("ecosort/ecosort-01/eventos", b"x" * 5000)
        largo = adapter.db.execute("SELECT LENGTH(payload) FROM eventos_rechazados").fetchone()[0]
        self.assertEqual(largo, adapter.MAX_PAYLOAD_RECHAZADO)


class MigracionDeUnaBaseVieja(unittest.TestCase):
    def test_una_base_anterior_al_contrato_gana_las_columnas_nuevas_sin_perder_datos(self):
        ruta = Path(_tmp.name) / "vieja.db"
        vieja = sqlite3.connect(ruta)
        vieja.executescript("""
            CREATE TABLE eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, evento_id TEXT NOT NULL UNIQUE,
                dispositivo_id TEXT NOT NULL, clase TEXT NOT NULL, confianza REAL, compuerta INTEGER,
                latencia_ms REAL, modelo TEXT, ts_dispositivo TEXT, ts_recepcion TEXT NOT NULL);
            INSERT INTO eventos (evento_id, dispositivo_id, clase, confianza, ts_recepcion)
                VALUES ('x', 'ecosort-01', 'cardboard', 0.9, '2026-09-20T10:00:00-03:00');
        """)
        vieja.commit()
        original = adapter.db
        try:
            adapter.db = vieja
            adapter.db.executescript((RAIZ / "schema" / "eventos.sql").read_text())
            adapter.migrar()
            adapter.migrar()  # idempotente: una segunda vez no falla ni duplica columnas
            columnas = {f[1] for f in vieja.execute("PRAGMA table_info(eventos)")}
            self.assertTrue({"schema_version", "clase_modelo", "accionado"} <= columnas)
            fila = vieja.execute("SELECT clase, schema_version, accionado FROM eventos").fetchone()
            self.assertEqual(fila, ("cardboard", 1, 0))
        finally:
            adapter.db = original
            vieja.close()


if __name__ == "__main__":
    unittest.main()
