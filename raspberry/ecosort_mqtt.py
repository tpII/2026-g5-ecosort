"""Publicador MQTT de EcoSort (corre en la Raspberry Pi junto a la inferencia).

Uso desde el script de inferencia:

    from ecosort_mqtt import EcoSortMQTT
    mqtt_pub = EcoSortMQTT()
    ...
    mqtt_pub.publicar_evento(clase="plastico", confianza=0.93, compuerta=1,
                             latencia_ms=210.5, modelo="trashnet-v1")
    ...
    mqtt_pub.cerrar()

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

    def publicar_evento(self, clase, confianza, compuerta, latencia_ms=None, modelo=None):
        """Publica un evento de clasificación. No bloquea: si no hay conexión,
        paho lo encola en memoria y lo manda al reconectar."""
        payload = {
            "evento_id": str(uuid.uuid4()),  # permite deduplicar en el adaptador
            "dispositivo_id": self.dispositivo_id,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "clase": clase,
            "confianza": round(float(confianza), 4),
            "compuerta": int(compuerta) if compuerta is not None else None,
            "latencia_ms": latencia_ms,
            "modelo": modelo,
        }
        return self.client.publish(self.topic_eventos, json.dumps(payload), qos=1)

    def publicar_vivo(self, datos):
        """Estado en tiempo real (lo que ve la cámara ahora). QoS 0: si se pierde uno, no importa."""
        datos = dict(datos, dispositivo_id=self.dispositivo_id,
                     ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
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
    # Prueba sin cámara ni modelo: publica eventos falsos cada 2 segundos.
    import random

    clases = ["plastico", "papel", "vidrio", "organico"]
    pub = EcoSortMQTT()
    try:
        while True:
            i = random.randrange(4)
            pub.publicar_evento(clases[i], random.uniform(0.5, 1.0), compuerta=i + 1,
                                latencia_ms=round(random.uniform(150, 400), 1),
                                modelo="fake")
            print(f"[test] publicado: {clases[i]}")
            time.sleep(2)
    except KeyboardInterrupt:
        pub.cerrar()
