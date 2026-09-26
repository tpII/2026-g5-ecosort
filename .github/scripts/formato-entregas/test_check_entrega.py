import copy
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_entrega  # noqa: E402

# un informe de analizar_pdf.py --json que cumple todo
OK = {
    "fuentes": {"cuerpo": {"familia": "Arial", "size": 12.0, "pct": 90.0}, "fuente_ok": True, "tamano_ok": True},
    "interlineado": {"salto_pt": 18.0, "ratio": 1.5, "clase": "1,5", "paginas_fuera": []},
    "justificado": {"justificado": "sí", "paginas_dudosas": []},
    "estructura": {
        "caratula": {"pag1_parece_caratula": True},
        "indice": {"presente": True, "paginas": [2], "entradas": 8},
        "indice_figuras": {"presente": True, "paginas": [3]},
        "indice_tablas": {"presente": True, "paginas": [3]},
        "bibliografia": {"presente": True, "paginas": [9]},
    },
    "epigrafes": {"imagenes_por_pagina": {"4": 1}, "tablas_detectadas": 1, "imagenes_grandes_sin_epigrafe": []},
    "lenguaje": [],
}


def con(**cambios):
    d = copy.deepcopy(OK)
    for ruta, valor in cambios.items():
        *padres, hoja = ruta.split("__")
        x = d
        for p in padres:
            x = x[p]
        x[hoja] = valor
    return d


class Evaluar(unittest.TestCase):
    def test_cumple_todo(self):
        self.assertEqual(check_entrega.evaluar(OK), ([], []))

    def test_fuente_no_permitida_falla(self):
        errores, _ = check_entrega.evaluar(con(fuentes__fuente_ok=False))
        self.assertEqual(len(errores), 1)
        self.assertIn("Fuente", errores[0])

    def test_tamano_falla(self):
        errores, _ = check_entrega.evaluar(con(fuentes__tamano_ok=False))
        self.assertEqual(len(errores), 1)
        self.assertIn("12 pt", errores[0])

    def test_interlineado_falla(self):
        for clase in ("simple", "doble"):
            errores, _ = check_entrega.evaluar(con(interlineado__clase=clase))
            self.assertEqual(len(errores), 1, clase)

    def test_lo_ambiguo_avisa_pero_no_falla(self):
        d = con(justificado__justificado="parcial",
                estructura__indice={"presente": False, "paginas": [], "entradas": 0},
                estructura__bibliografia={"presente": False, "paginas": []},
                epigrafes__imagenes_grandes_sin_epigrafe=[{"pag": 6, "top": 1}],
                lenguaje=[{"pag": 4, "tipo": "x", "palabra": "y", "contexto": "z"}])
        errores, avisos = check_entrega.evaluar(d)
        self.assertEqual(errores, [])
        self.assertEqual(len(avisos), 5)

    def test_sin_figuras_no_pide_indice_de_figuras(self):
        d = con(epigrafes__imagenes_por_pagina={}, epigrafes__tablas_detectadas=0,
                estructura__indice_figuras={"presente": False, "paginas": []},
                estructura__indice_tablas={"presente": False, "paginas": []})
        self.assertEqual(check_entrega.evaluar(d), ([], []))


class SinPdfs(unittest.TestCase):
    def test_sin_pdfs_sale_con_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, check_entrega.__file__], cwd=tmp, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nada que chequear", r.stdout)


if __name__ == "__main__":
    unittest.main()
