"""Tests de estadisticas.py: agregaciones puras, sin DB ni HTTP.

    python -m unittest discover -s host/dashboard/backend -v
"""

import unittest

import estadisticas as e


def fila(clase="plastico", confianza=0.9, motivo=None, latencia_ms=200.0, dispositivo_id="ecosort-01",
        ts="2026-09-20T12:00:00-03:00"):
    return {"clase": clase, "confianza": confianza, "motivo": motivo, "latencia_ms": latencia_ms,
            "dispositivo_id": dispositivo_id, "ts_recepcion": ts}


class Resumen(unittest.TestCase):
    def test_cuenta_total_y_por_clase(self):
        filas = [fila(clase="plastico"), fila(clase="plastico"), fila(clase="papel")]
        r = e.resumen(filas)
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["por_clase"]["plastico"]["total"], 2)
        self.assertEqual(r["por_clase"]["papel"]["total"], 1)

    def test_confianza_promedio_ignora_nulos(self):
        filas = [fila(confianza=0.8), fila(confianza=1.0), fila(confianza=None)]
        r = e.resumen(filas)
        self.assertAlmostEqual(r["por_clase"]["plastico"]["confianza_promedio"], 0.9)

    def test_organico_separa_lo_incierto_de_lo_genuino(self):
        filas = [
            fila(clase="organico", motivo=None),                     # genuino
            fila(clase="organico", motivo="baja_confianza"),
            fila(clase="organico", motivo="baja_confianza"),
            fila(clase="organico", motivo="inconsistente"),
        ]
        r = e.resumen(filas)["por_clase"]["organico"]
        self.assertEqual(r["total"], 4)
        self.assertEqual(r["genuino"], 1)
        self.assertEqual(r["incierto"], {"baja_confianza": 2, "inconsistente": 1})

    def test_una_clase_sin_organico_no_lleva_la_clave_incierto(self):
        r = e.resumen([fila(clase="vidrio")])["por_clase"]["vidrio"]
        self.assertNotIn("incierto", r)

    def test_latencia_percentiles(self):
        filas = [fila(latencia_ms=v) for v in [100, 200, 300, 400, 500]]
        r = e.resumen(filas)["latencia_ms"]
        self.assertEqual(r["n"], 5)
        self.assertEqual(r["promedio"], 300.0)
        self.assertEqual(r["p50"], 300)

    def test_sin_eventos_no_rompe(self):
        r = e.resumen([])
        self.assertEqual(r, {"total": 0, "por_clase": {}, "latencia_ms": None})


class Serie(unittest.TestCase):
    def test_agrupar_invalido_levanta_valueerror(self):
        with self.assertRaises(ValueError):
            e.serie([], agrupar="semana")

    def test_por_dia_agrupa_por_fecha_calendario_en_la_zona_horaria_no_en_utc(self):
        # 02:30 UTC del día 28 es 23:30 del día 27 en Argentina (UTC-3): tiene que caer en el 27.
        filas = [fila(ts="2026-09-28T02:30:00+00:00")]
        puntos = e.serie(filas, agrupar="dia")["puntos"]
        self.assertEqual(puntos, [{"clave": "2026-09-27", "total": 1}])

    def test_hora_del_dia_usa_la_hora_local_no_la_del_string(self):
        # mismo cuadro: 02:30 UTC == 23:30 en Argentina -> hora 23, no 2.
        filas = [fila(ts="2026-09-28T02:30:00+00:00")]
        puntos = {p["clave"]: p["total"] for p in e.serie(filas, agrupar="hora_del_dia")["puntos"]}
        self.assertEqual(puntos[23], 1)
        self.assertEqual(puntos[2], 0)

    def test_hora_del_dia_siempre_devuelve_las_24_horas(self):
        puntos = e.serie([fila(ts="2026-09-20T10:00:00-03:00")], agrupar="hora_del_dia")["puntos"]
        self.assertEqual(len(puntos), 24)
        self.assertEqual([p["clave"] for p in puntos], list(range(24)))

    def test_por_hora_agrupa_fecha_y_hora(self):
        filas = [fila(ts="2026-09-20T10:15:00-03:00"), fila(ts="2026-09-20T10:45:00-03:00"),
                fila(ts="2026-09-20T11:05:00-03:00")]
        puntos = e.serie(filas, agrupar="hora")["puntos"]
        self.assertEqual(puntos, [{"clave": "2026-09-20T10:00", "total": 2},
                                  {"clave": "2026-09-20T11:00", "total": 1}])


class Filtrar(unittest.TestCase):
    def setUp(self):
        self.filas = [fila(ts="2026-09-18T10:00:00-03:00"), fila(ts="2026-09-20T10:00:00-03:00"),
                     fila(ts="2026-09-22T10:00:00-03:00")]

    def test_rango_es_inclusive_de_los_dos_extremos(self):
        r = e.filtrar(self.filas, desde="2026-09-18", hasta="2026-09-20")
        self.assertEqual(len(r), 2)

    def test_hasta_sin_hora_incluye_el_dia_completo(self):
        # un evento a las 10:00 del día 20 tiene que entrar con hasta="2026-09-20"
        r = e.filtrar(self.filas, desde="2026-09-20", hasta="2026-09-20")
        self.assertEqual(len(r), 1)

    def test_sin_limites_no_filtra_nada(self):
        self.assertEqual(len(e.filtrar(self.filas)), 3)

    def test_por_dispositivo(self):
        filas = [fila(dispositivo_id="ecosort-01"), fila(dispositivo_id="ecosort-02")]
        self.assertEqual(len(e.filtrar(filas, dispositivo="ecosort-02")), 1)


class Dispositivos(unittest.TestCase):
    def test_primer_y_ultimo_evento_por_dispositivo(self):
        filas = [fila(dispositivo_id="ecosort-01", ts="2026-09-20T10:00:00-03:00"),
                fila(dispositivo_id="ecosort-01", ts="2026-09-22T10:00:00-03:00"),
                fila(dispositivo_id="ecosort-02", ts="2026-09-21T10:00:00-03:00")]
        r = e.dispositivos(filas)
        self.assertEqual(r["ecosort-01"]["total"], 2)
        self.assertEqual(r["ecosort-01"]["primer_evento"], "2026-09-20T10:00:00-03:00")
        self.assertEqual(r["ecosort-01"]["ultimo_evento"], "2026-09-22T10:00:00-03:00")
        self.assertEqual(r["ecosort-02"]["total"], 1)

    def test_ordena_por_instante_real_no_por_texto_aunque_el_offset_cambie(self):
        # A son las 05:00 UTC y B las 11:00 UTC (A es antes) pero como texto B < A ("08" < "10"):
        # un sorted() de los strings los pondría al revés.
        a = "2026-09-20T10:00:00+05:00"
        b = "2026-09-20T08:00:00-03:00"
        self.assertLess(b, a)  # confirma que el string engaña, si no el test no probaría nada
        r = e.dispositivos([fila(ts=a), fila(ts=b)])["ecosort-01"]
        self.assertEqual(r["primer_evento"], a)
        self.assertEqual(r["ultimo_evento"], b)


if __name__ == "__main__":
    unittest.main()
