# EcoSort — Guía de instalación en la Raspberry Pi

Guía paso a paso para dejar funcionando, en una Raspberry Pi 3, la detección de residuos con
cámara, la comunicación por MQTT (Mosquitto) y el dashboard web. Incluye los problemas que
aparecieron durante la puesta en marcha y cómo se resolvieron.

## Arquitectura

```
Cámara USB → ecosort_pi.py ──MQTT (Mosquitto)──→ dashboard.py → eventos.db (SQLite)
             detecta y cuenta                     guarda y sirve el panel web
```

| Archivo | Qué hace |
|---|---|
| `raspberry/ecosort_pi.py` | Lee la cámara, detecta cuándo aparece un objeto, lo clasifica y publica **un evento por objeto** por MQTT. Con `--video` también transmite el video. |
| `raspberry/inferencia_pi.py` | Carga el modelo TFLite y clasifica una imagen. También sirve para medir rendimiento (`--bench`). |
| `raspberry/ecosort_mqtt.py` | Publica por MQTT: eventos, estado en vivo y estado online/offline. |
| `raspberry/dashboard.py` | Se suscribe a MQTT, guarda en SQLite y sirve el panel web (conteo, vivo, CSV, reinicio). |
| `raspberry/vista_en_vivo.py` | Herramienta de prueba: video en el navegador con indicador de nitidez para enfocar. |
| `raspberry/mosquitto/ecosort.conf` | Configuración del broker Mosquitto. |
| `software_detección/MobileNetV2/entrenar_ecosort.ipynb` | Notebook de Google Colab que entrena el modelo y lo exporta a TFLite. |
| `schema/eventos.sql` | Estructura de la tabla de eventos. |

Tópicos MQTT (`<id>` = `ecosort-01`):

| Tópico | Contenido | QoS |
|---|---|---|
| `ecosort/<id>/eventos` | Un JSON por residuo contado (clase, confianza, hora, etc.) | 1 |
| `ecosort/<id>/vivo` | Lo que ve la cámara ahora, ~3 veces por segundo | 0 |
| `ecosort/<id>/estado` | `online` / `offline` (retenido, con Last Will) | 1 |

## Requisitos

- Raspberry Pi 3 con **Raspberry Pi OS de 64 bits** (se probó con Debian 13 "trixie", `aarch64`).
  Verificar con `uname -m` → tiene que decir `aarch64`.
- Fuente de 5 V y al menos 2,5 A.
- Cámara USB (se usó una "HD USB Camera" con lente M12).
- Notebook en la misma red que la Pi. En Windows alcanza con el `cmd` (trae `ssh` y `scp`).
- Cuenta de Google para entrenar el modelo en Colab.

> **Regla de oro:** los comandos `sudo`, `apt`, `python`, `mosquitto_sub`, etc. se ejecutan
> **en la Raspberry**, dentro de la sesión SSH (el prompt dice `usuario@rasberrypi:~ $`).
> En el `cmd` de Windows (`C:\...>`) solo van `ssh`, `scp`, `ping` y `arp`.

En esta guía, `<usuario>` es el usuario configurado al grabar la SD y `<ip-de-la-pi>` la IP de
la Pi en la red (por ejemplo `192.168.100.153`).

---

## 1. Conectarse a la Pi por SSH

Desde el `cmd` de la notebook:

```cmd
ssh <usuario>@<ip-de-la-pi>
```

La primera vez pregunta si confiás en el equipo: escribir `yes`. Después pide la contraseña
(no se ve mientras se escribe).

**Encontrar la IP de la Pi:**

```cmd
arp -a
```

La Raspberry se reconoce por la dirección física que empieza con `b8-27-eb`. También se puede
resolver por nombre forzando IPv4 (el hostname de nuestra Pi es `rasberrypi`):

```cmd
ping -4 rasberrypi.local
```

> En Linux, `ping` no termina solo: se corta con **Ctrl + C**.

---

## 2. Instalar Mosquitto

Hacerlo **mientras la Pi tiene internet** (antes de configurar el modo Access Point).

```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients python3-paho-mqtt
```

Crear la configuración con el contenido de `raspberry/mosquitto/ecosort.conf`:

```bash
sudo nano /etc/mosquitto/conf.d/ecosort.conf
```

```
listener 1883
allow_anonymous true
```

Guardar con `Ctrl + O` → `Enter` y salir con `Ctrl + X`. Ese archivo lleva **solo** esas líneas,
nunca comandos de la terminal. Después:

```bash
sudo systemctl enable --now mosquitto
sudo systemctl restart mosquitto
sudo systemctl status mosquitto
```

Tiene que decir **`active (running)`**. Con `enable`, Mosquitto arranca solo al encender la Pi.

---

## 3. Probar la comunicación MQTT

En la Pi, dejar escuchando (la terminal queda en blanco esperando, es normal):

```bash
mosquitto_sub -h localhost -t "ecosort/prueba" -v
```

En la notebook, con la app gráfica **MQTTX** (https://mqttx.app):

1. Nueva conexión → Host `<ip-de-la-pi>`, Port `1883` → **Connect**.
2. Topic `ecosort/prueba` → escribir un mensaje → enviar.

El mensaje aparece en la terminal de la Pi. El topic tiene que coincidir **exactamente**
(un punto de más al final y no llega).

---

## 4. Cámara USB

```bash
lsusb                              # tiene que aparecer "HD USB Camera"
sudo apt install -y v4l-utils fswebcam
v4l2-ctl --list-devices            # la cámara figura con /dev/video0 y /dev/video1
```

Usar **`/dev/video0`**: el `video1` es de metadatos. Los `/dev/video1x` son del chip de la Pi.

Foto de prueba (en la Pi) y descarga a la notebook (en el `cmd`):

```bash
fswebcam -d /dev/video0 -r 640x480 -S 10 --no-banner prueba.jpg
```

```cmd
scp <usuario>@<ip-de-la-pi>:~/prueba.jpg .
```

---

## 5. Entorno de Python y TFLite en la Pi

```bash
sudo apt install -y python3-venv python3-opencv
python3 -m venv --system-site-packages ~/ecosort-venv
source ~/ecosort-venv/bin/activate
pip install ai-edge-litert
```

- `ai-edge-litert` es el intérprete de TensorFlow Lite (Google lo renombró "LiteRT"). Instala
  solo lo necesario para ejecutar el modelo, no TensorFlow completo.
- `--system-site-packages` permite que el entorno use OpenCV y paho-mqtt instalados con `apt`.

Verificar:

```bash
python -c "from ai_edge_litert.interpreter import Interpreter; print('TFLite OK')"
```

Para que el entorno se active solo en cada sesión SSH (una sola vez):

```bash
echo 'source ~/ecosort-venv/bin/activate' >> ~/.bashrc
```

---

## 6. Entrenar el modelo (Google Colab)

> **Si `raspberry/modelo/` ya tiene `ecosort_int8.tflite` y `labels.txt`, este paso se puede
> saltear:** el modelo entrenado viene en el repo. Solo hace falta reentrenar para mejorarlo
> (por ejemplo, con fotos propias del gabinete).

Se usa **transfer learning sobre MobileNetV2** preentrenada con ImageNet (ADR 0001), entrenada
con el dataset TrashNet (6 clases: cardboard, glass, metal, paper, plastic, trash).

1. Entrar a https://colab.research.google.com → *Subir* →
   `software_detección/MobileNetV2/entrenar_ecosort.ipynb`.
2. *Entorno de ejecución → Cambiar tipo de entorno de ejecución → GPU (T4)*.
   Si no conecta, probar con **CPU** (tarda más, el resultado es el mismo).
3. *Entorno de ejecución → Ejecutar todas*. Al final se descarga `ecosort_modelo.zip`.

Copiar `ecosort_int8.tflite`, `ecosort_fp32.tflite` y `labels.txt` a `raspberry/modelo/`.

> El escalado de la imagen está **dentro** del modelo: se le pasa la imagen RGB 0–255 tal cual.

---

## 7. Copiar los archivos a la Pi

Desde el `cmd`, parado en la carpeta del repo:

```cmd
scp -r raspberry <usuario>@<ip-de-la-pi>:~/ecosort
```

Queda todo en `~/ecosort` en la Pi (si esa carpeta ya existía, se crea `~/ecosort/raspberry`).

---

## 8. Medir rendimiento

```bash
cd ~/ecosort
python inferencia_pi.py modelo/ecosort_int8.tflite --bench
python inferencia_pi.py modelo/ecosort_fp32.tflite --bench
vcgencmd measure_temp
vcgencmd get_throttled
```

Resultados en nuestra Raspberry Pi 3 (sin disipador):

| Modelo | Latencia media | p95 | Velocidad | RAM pico |
|---|---|---|---|---|
| **int8** | **31 ms** | 40 ms | ~32 fps | 155 MB |
| fp32 | 81 ms | 87 ms | ~12 fps | 171 MB |

Temperatura 43,5 °C, `throttled=0x0`. **Se usa el modelo int8.**

---

## 9. Enfocar la cámara (vista en vivo)

```bash
cd ~/ecosort
python vista_en_vivo.py
```

Abrir `http://<ip-de-la-pi>:8000`. La barra muestra la **nitidez**: aflojar el tornillo de la
lente M12, girarla buscando el valor más alto con un objeto donde van a caer los residuos, y
volver a ajustar el tornillo. El botón *Descargar foto* sirve para juntar imágenes para el dataset.

Con `--modelo modelo/ecosort_int8.tflite` también muestra la clase detectada.
Cortar con `Ctrl + C` antes de seguir: la cámara la puede usar un solo programa a la vez.

---

## 10. Sistema completo: detector + dashboard

```bash
cd ~/ecosort
source ~/ecosort-venv/bin/activate
nohup python dashboard.py > dashboard.log 2>&1 &
nohup python ecosort_pi.py --modelo modelo/ecosort_int8.tflite --video > detector.log 2>&1 &
```

Durante los primeros 2 segundos la cámara tiene que ver la escena **vacía** (aprende el fondo).
Después, abrir en la notebook **`http://<ip-de-la-pi>:8080`**:

- **En vivo:** residuo que ve la cámara, confianza y video.
- **Residuos detectados:** total y conteo por tipo.
- **Últimos registros:** hora, residuo y confianza.
- **Descargar datos (CSV):** todos los registros, listo para Excel.
- **Reiniciar datos:** borra los registros (pide confirmación).

Los datos quedan en `~/ecosort/eventos.db` y sobreviven a reinicios. `nohup` hace que los
programas sigan corriendo aunque se cierre la sesión SSH.

```bash
pkill -f ecosort_pi.py        # detener el detector
pkill -f dashboard.py         # detener el dashboard
cat detector.log              # ver mensajes / errores
```

Ajustes en `ecosort_pi.py`: `UMBRAL_CONF` (confianza mínima para contar, 0,60) y
`UMBRAL_CAMBIO` (cuánto tiene que cambiar la imagen para considerar que hay un objeto).

El dashboard puede correr en otra computadora apuntando a la Pi:
`ECOSORT_BROKER=<ip-de-la-pi> python dashboard.py`.

---

## Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| `Could not resolve hostname raspberrypi.local` | El hostname es `rasberrypi` | Usar la IP o `rasberrypi.local` |
| `Permission denied (publickey,password)` | Usuario o contraseña incorrectos | Usar el usuario configurado en el Imager |
| `client_loop: send disconnect: Connection reset` | Se cortó el SSH (red o suspensión de la notebook) | Volver a conectar; usar `nohup` para lo que tiene que seguir corriendo |
| `"sudo" no se reconoce...` en Windows | Comando de Linux ejecutado en el `cmd` | Entrar primero por `ssh` |
| Mosquitto `status=3`, `Unknown configuration variable "sudo"` | Se pegaron comandos dentro de `ecosort.conf` | Dejar solo `listener 1883` y `allow_anonymous true` |
| `cat` se queda colgado | Se ejecutó sin archivo | `Ctrl + C` |
| El mensaje MQTT no llega | Topic distinto (espacio o punto de más) | Revisar que coincida exactamente |
| `ModuleNotFoundError: ai_edge_litert` | Entorno virtual sin activar | `source ~/ecosort-venv/bin/activate` |
| `No se pudo abrir /dev/video0` | Otro programa usa la cámara | `pkill -f vista_en_vivo.py` / `pkill -f ecosort_pi.py` |
| Colab: "no se ha podido conectar el entorno" | Sin GPU disponible o bloqueo del navegador/red | Cambiar a CPU, desactivar extensiones, probar otra red |
| La Pi se reinicia o anda lenta | Fuente floja o temperatura | `vcgencmd get_throttled` debe dar `0x0` |

---

## Limitaciones conocidas y próximos pasos

- **TrashNet no representa la cámara real:** sus fotos son objetos sobre fondo blanco con buena
  luz. Con la cámara del gabinete el modelo acierta menos. Solución: juntar fotos propias dentro
  del gabinete (50–100 por clase) y reentrenar con el mismo notebook.
- **Faltan las 4 clases finales** (plástico, papel, vidrio, orgánico): TrashNet no tiene orgánico.
  Se resuelve con el dataset propio.
- **Pendiente:** control de los servos por GPIO, modo Access Point (`192.168.20.1`), y mover el
  dashboard a la notebook/servidor según la arquitectura del proyecto.
