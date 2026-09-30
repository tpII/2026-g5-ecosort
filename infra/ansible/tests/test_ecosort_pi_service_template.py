"""Renderiza las plantillas de infra/ansible/templates/ con Jinja2 puro (sin Ansible) y valida
el resultado.

No reemplaza correr el playbook contra una Pi real (eso se hace a mano y se registra en
BITACORA.md, como el resto de lo que depende de hardware) — prueba que las plantillas no tienen
errores de sintaxis y arman bien el .service y el env file para los casos que importan.

    pip install jinja2
    python -m unittest discover -s infra/ansible/tests -v
"""

import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

AQUI = Path(__file__).resolve().parent
PLANTILLAS = AQUI.parent / "templates"
_env = Environment(loader=FileSystemLoader(str(PLANTILLAS)))

VARS_BASE = {
    "ecosort_user": "pi",
    "ecosort_dir": "/home/pi/ecosort",
    "ecosort_venv": "/home/pi/ecosort-venv",
    "ecosort_modelo": "ecosort_int8.tflite",
}


def renderizar(**variables):
    return _env.get_template("ecosort_pi.service.j2").render(**{**VARS_BASE, **variables})


def renderizar_env(**variables):
    base = {"ecosort_broker": "localhost", "ecosort_dispositivo": "ecosort-01"}
    return _env.get_template("ecosort_pi.env.j2").render(**{**base, **variables})


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

    def test_lee_el_broker_y_el_dispositivo_del_environmentfile_no_hardcodeados(self):
        # lo que varía por Pi física (broker, dispositivo_id) va en el env file, no en el .service
        # (ver ecosort_pi.env.j2): así una corrida de Ansible con otro group_vars no pisa el
        # .service, solo el env file, y el handler nota el cambio igual.
        salida = renderizar()
        self.assertIn("EnvironmentFile=/etc/ecosort/ecosort_pi.env", salida)
        self.assertNotIn("ECOSORT_BROKER", salida)


class EnvFileEcosortPi(unittest.TestCase):
    def test_trae_broker_y_dispositivo(self):
        salida = renderizar_env(ecosort_broker="192.168.20.1", ecosort_dispositivo="ecosort-02")
        self.assertIn("ECOSORT_BROKER=192.168.20.1", salida)
        self.assertIn("ECOSORT_DISPOSITIVO=ecosort-02", salida)

    def test_no_quedan_placeholders_sin_resolver(self):
        salida = renderizar_env()
        self.assertNotIn("{{", salida)
        self.assertNotIn("}}", salida)


if __name__ == "__main__":
    unittest.main()
