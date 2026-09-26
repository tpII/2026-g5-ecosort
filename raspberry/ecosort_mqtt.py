"""Publicador MQTT de EcoSort (corre en la Raspberry Pi junto a la inferencia).

Uso desde el script de inferencia:

    from ecosort_mqtt import EcoSortMQTT
    mqtt_pub = EcoSortMQTT()
    ...
    # se pasa la etiqueta que devolvió el modelo: la clase de producto y la compuerta
    # las resuelve schema/clases.json (raspberry/clases.py)
    mqtt_pub.publicar_evento("cardboard", confianza=0.93, latencia_ms=210.5,
                             modelo="ecosort_int8.tflite")
    ...
    mqtt_pub.cerrar()

Contrato completo (campos, versionado, semántica): docs/contrato-mqtt.md y
schema/evento.schema.json.

Tópicos:
    ecosort/<dispositivo_id>/eventos   -> un JSON por residuo clasificado (QoS 1)
    ecosort/<dispositivo_id>/estado    -> "online" / "offline" (retained, con LWT)
    ecosort/<dispositivo_id>/vivo      -> lo que ve la cámara ahora (QoS 0, varias veces por segundo)

Requiere paho-mqtt >= 2.0.
"""

import json
import time
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from clases import compuerta_de, producto_de

SCHEMA_VERSION = 1


def armar_evento(dispositivo_id, clase_modelo, confianza, latencia_ms=None, modelo=None,
                 accionado=False):
    """Payload de un evento según schema/evento.schema.json. Función pura (sin red):
    es lo que valida el test de contrato."""
    clase = producto_de(clase_modelo)
    if clase is None:
        raise ValueError(f"{clase_modelo!r} es un descarte (no es un residuo): no se publica como evento")
    return {
        "schema_version": SCHEMA_VERSION,
        "evento_id": str(uuid.uuid4()),  # permite deduplicar en el adaptador
        "dispositivo_id": dispositivo_id,
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "clase": clase,
        "clase_modelo": clase_modelo,
        "confianza": round(float(confianza), 4),
        "compuerta": compuerta_de(clase),
        "accionado": bool(accionado),
        "latencia_ms": latencia_ms,
        "modelo": modelo,
    }


class EcoSortMQTT:
    def __init__(self, dispositivo_id="ecosort-01", host="localhost", port=1883):
        self.dispositivo_id = dispositivo_id
        self.topic_eventos = f"ecosort/{dispositivo_id}/eventos"
        self.topic_estado = f"ecosort/{dispositivo_id}/estado"
        self.topic_vivo = f"ecosort/{dispositivo_id}/vivo"

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{dispositivo_id}-inferencia",
        )
        # Si el proceso muere sin despedirse, el broker publica "offline" solo.
        self.client.will_set(self.topic_estado, "offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        # connect_async + loop_start: no bloquea la inferencia y reintenta solo
        # si el broker todavía no arrancó.
        self.client.connect_async(host, port, keepalive=30)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"[mqtt] conexión rechazada: {reason_code}")
            return
        print("[mqtt] conectado al broker")
        client.publish(self.topic_estado, "online", qos=1, retain=True)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        print(f"[mqtt] desconectado ({reason_code}), reintentando...")

    def publicar_evento(self, clase_modelo, confianza, latencia_ms=None, modelo=None,
                        accionado=False):
        """Publica un evento de clasificación. No bloquea: si no hay conexión,
        paho lo encola en memoria y lo manda al reconectar. Levanta KeyError si la
        etiqueta del modelo no está en schema/clases.json."""
        payload = armar_evento(self.dispositivo_id, clase_modelo, confianza,
                               latencia_ms, modelo, accionado)
        return self.client.publish(self.topic_eventos, json.dumps(payload), qos=1)

    def publicar_vivo(self, datos):
        """Estado en tiempo real (lo que ve la cámara ahora). QoS 0: si se pierde uno, no importa.
        Si trae 'clase' (etiqueta del modelo), publica también la clase de producto, con el
        mismo vocabulario que los eventos ('clase' queda en null si es un descarte). No se
        persiste ni se valida."""
        datos = dict(datos, dispositivo_id=self.dispositivo_id,
                     ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        if datos.get("clase"):
            datos["clase_modelo"] = datos["clase"]
            datos["clase"] = producto_de(datos["clase"])
        return self.client.publish(self.topic_vivo, json.dumps(datos), qos=0)

    def cerrar(self):
        info = self.client.publish(self.topic_estado, "offline", qos=1, retain=True)
        try:
            info.wait_for_publish(timeout=2)
        except RuntimeError:
            pass  # no había conexión; el LWT no se dispara en un cierre limpio
        self.client.loop_stop()
        self.client.disconnect()


if __name__ == "__main__":
    # Prueba sin cámara ni modelo: publica eventos falsos cada 2 segundos, con las etiquetas
    # que hoy devuelve el modelo (así ejercita el mapeo a clase de producto y a compuerta).
    # ECOSORT_BROKER apunta a otro broker (por defecto, localhost).
    import os
    import random

    from clases import MAPEO_MODELO

    etiquetas = list(MAPEO_MODELO)
    pub = EcoSortMQTT(host=os.getenv("ECOSORT_BROKER", "localhost"))
    try:
        while True:
            etiqueta = random.choice(etiquetas)
            pub.publicar_evento(etiqueta, random.uniform(0.5, 1.0),
                                latencia_ms=round(random.uniform(150, 400), 1),
                                modelo="fake")
            print(f"[test] publicado: {etiqueta} -> {producto_de(etiqueta)}")
            time.sleep(2)
    except KeyboardInterrupt:
        pub.cerrar()
