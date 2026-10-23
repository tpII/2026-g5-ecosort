"""Compuertas de EcoSort: 4 servos, uno por categoría.

Pruebas sueltas (sin cámara ni modelo), en la Pi y con el entorno activado:
    python servos.py --test              # mueve cada compuerta, una por una
    python servos.py --abrir 2           # abre y cierra solo la compuerta 2
    python servos.py --angulo 1 45       # lleva la compuerta 1 a 45° (para calibrar)

Desde el detector:
    python ecosort_pi.py --modelo ecosort_int8.tflite --servos

Compuertas:  1 = plástico | 2 = papel/cartón | 3 = vidrio | 4 = orgánico

Conexión de cada servo (3 cables):
    marrón / negro     -> GND  (de la fuente externa Y también a un GND de la Pi)
    rojo               -> +5 V (de la fuente externa, NO del pin 5V de la Pi)
    naranja / amarillo -> pin GPIO de la tabla PINES

Requiere gpiozero (viene con Raspberry Pi OS). Para un PWM preciso, sin temblor:
    sudo apt install pigpio python3-pigpio
    sudo systemctl enable --now pigpiod
Si pigpio no está disponible, usa PWM por software (funciona, pero puede temblar un poco).
"""

import argparse
import threading
import time

from gpiozero import AngularServo, Device

# compuerta -> número de GPIO (numeración BCM). Pines físicos: 11, 13, 15 y 16.
PINES = {1: 17, 2: 27, 3: 22, 4: 23}
NOMBRES = {1: "plástico", 2: "papel/cartón", 3: "vidrio", 4: "orgánico"}

ANGULO_CERRADA = 0       # ajustar según el mecanismo
ANGULO_ABIERTA = 90
SEGUNDOS_ABIERTA = 2.0   # cuánto tiempo queda abierta
SEGUNDOS_MOVER = 0.6     # tiempo que tarda el servo en llegar a la posición
PULSO_MIN = 0.5 / 1000   # SG90/MG90S: 0,5 ms = 0°  ...
PULSO_MAX = 2.5 / 1000   # ... 2,5 ms = 180°. Si el servo zumba al llegar al tope, achicar el rango.
SOLTAR_AL_CERRAR = True  # corta los pulsos al cerrar: no tiembla ni consume en reposo


def _configurar_pines():
    """Usa pigpio (PWM por hardware/DMA, sin temblor) si está; si no, el PWM por software."""
    try:
        from gpiozero.pins.pigpio import PiGPIOFactory
        Device.pin_factory = PiGPIOFactory()
        print("[servos] PWM por pigpio (preciso)")
    except Exception:
        print("[servos] AVISO: pigpio no disponible, uso PWM por software (puede temblar un poco)")


class Compuertas:
    def __init__(self, pines=None):
        _configurar_pines()
        self.pines = pines or PINES
        self.servos = {}
        self._lock = threading.Lock()  # un solo servo se mueve a la vez: menos pico de corriente
        for n, pin in self.pines.items():
            self.servos[n] = AngularServo(
                pin, min_angle=0, max_angle=180, initial_angle=ANGULO_CERRADA,
                min_pulse_width=PULSO_MIN, max_pulse_width=PULSO_MAX)
            time.sleep(0.3)            # se encienden de a uno, no los 4 de golpe
            self._soltar(n)
        print(f"[servos] listas las compuertas {sorted(self.servos)} (cerradas)")

    def _soltar(self, n):
        if SOLTAR_AL_CERRAR:
            self.servos[n].detach()

    def abrir(self, n, segundos=SEGUNDOS_ABIERTA):
        """Abre la compuerta n, la deja `segundos` y la cierra. No bloquea al detector."""
        if n not in self.servos:
            print(f"[servos] la compuerta {n} no existe")
            return
        threading.Thread(target=self._ciclo, args=(n, segundos), daemon=True).start()

    def _ciclo(self, n, segundos):
        with self._lock:
            servo = self.servos[n]
            print(f"[servos] abriendo compuerta {n} ({NOMBRES.get(n, '')})")
            servo.angle = ANGULO_ABIERTA
            time.sleep(SEGUNDOS_MOVER + segundos)
            servo.angle = ANGULO_CERRADA
            time.sleep(SEGUNDOS_MOVER)
            self._soltar(n)

    def ir_a(self, n, angulo):
        """Lleva la compuerta n a un ángulo y la deja ahí (para calibrar)."""
        with self._lock:
            self.servos[n].angle = max(0, min(180, angulo))
            time.sleep(SEGUNDOS_MOVER)

    def cerrar(self):
        with self._lock:
            for servo in self.servos.values():
                try:
                    servo.angle = ANGULO_CERRADA
                    time.sleep(0.3)
                    servo.detach()
                    servo.close()
                except Exception:
                    pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="mover cada compuerta, una por una")
    ap.add_argument("--abrir", type=int, metavar="N", help="abrir y cerrar la compuerta N")
    ap.add_argument("--angulo", nargs=2, type=int, metavar=("N", "GRADOS"),
                    help="llevar la compuerta N a esos grados")
    args = ap.parse_args()

    c = Compuertas()
    try:
        if args.test:
            for n in sorted(c.servos):
                print(f"Probando compuerta {n} ({NOMBRES[n]}), pin GPIO{PINES[n]}...")
                c._ciclo(n, 1.0)
        elif args.abrir:
            c._ciclo(args.abrir, SEGUNDOS_ABIERTA)
        elif args.angulo:
            c.ir_a(*args.angulo)
            input("Servo en posición. Enter para soltarlo y salir...")
        else:
            ap.print_help()
    finally:
        c.cerrar()
