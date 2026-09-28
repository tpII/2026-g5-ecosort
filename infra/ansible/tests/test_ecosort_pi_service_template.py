"""Renderiza templates/ecosort_pi.service.j2 con Jinja2 puro (sin Ansible) y valida el resultado.

No reemplaza correr el playbook contra una Pi real (eso se hace a mano y se registra en
BITACORA.md, como el resto de lo que depende de hardware) — prueba que la plantilla no tiene
errores de sintaxis y que arma bien el .service para los dos casos de ecosort_video.

    pip install jinja2
    python -m unittest discover -s infra/ansible/tests -v
"""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

AQUI = Path(__file__).resolve().parent
PLANTILLAS = AQUI.parent / "templates"

VARS_BASE = {
    "ecosort_user": "pi",
    "ecosort_dir": "/home/pi/ecosort",
    "ecosort_venv": "/home/pi/ecosort-venv",
    "ecosort_broker": "localhost",
    "ecosort_modelo": "ecosort_int8.tflite",
}


def renderizar(**variables):
    env = Environment(loader=FileSystemLoader(str(PLANTILLAS)))
    return env.get_template("ecosort_pi.service.j2").render(**{**VARS_BASE, **variables})


class ServicioEcosortPi(unittest.TestCase):
    def test_las_secciones_systemd_estan_presentes(self):
        salida = renderizar(ecosort_video=True)
        for seccion in ("[Unit]", "[Service]", "[Install]"):
            self.assertIn(seccion, salida)

    def test_no_quedan_placeholders_sin_resolver(self):
        salida = renderizar(ecosort_video=True)
        self.assertNotIn("{{", salida)
        self.assertNotIn("}}", salida)

    def test_directorio_de_trabajo_es_la_carpeta_raspberry_del_despliegue(self):
        # ahí es donde despliegue.yml sincroniza raspberry/, y de donde clases.py resuelve
        # ../schema/clases.json (ver raspberry/clases.py)
        salida = renderizar()
        self.assertIn("WorkingDirectory=/home/pi/ecosort/raspberry", salida)

    def test_con_video_agrega_la_bandera(self):
        salida = renderizar(ecosort_video=True)
        linea_exec = [l for l in salida.splitlines() if l.startswith("ExecStart=")][0]
        self.assertTrue(linea_exec.endswith("--video"))
        self.assertIn("modelo/ecosort_int8.tflite", linea_exec)

    def test_sin_video_no_agrega_la_bandera(self):
        salida = renderizar(ecosort_video=False)
        linea_exec = [l for l in salida.splitlines() if l.startswith("ExecStart=")][0]
        self.assertNotIn("--video", linea_exec)
        self.assertTrue(linea_exec.endswith(VARS_BASE["ecosort_modelo"]))

    def test_reinicia_solo_si_falla_no_si_se_para_a_mano(self):
        # Restart=on-failure (no "always"): "systemctl stop" o un cambio de servicio no lo revive
        # solo; un crash de la cámara o del modelo, sí.
        self.assertIn("Restart=on-failure", renderizar())

    def test_usa_el_broker_configurado(self):
        salida = renderizar(ecosort_broker="192.168.20.1")
        self.assertIn("Environment=ECOSORT_BROKER=192.168.20.1", salida)


if __name__ == "__main__":
    unittest.main()
