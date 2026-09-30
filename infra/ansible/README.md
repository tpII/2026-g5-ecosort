# infra/ansible — instalación y despliegue de la Pi

Empaqueta como Ansible lo que hoy es la [guía de instalación](../../docs/guia-instalacion-raspberry.md)
hecha a mano: Mosquitto, la cámara, el entorno de Python con TensorFlow Lite, copiar
`raspberry/` + `schema/`, y el servicio de `ecosort_pi.py`. La guía sigue siendo la referencia de
**qué** hace falta y **por qué** (los problemas reales que aparecieron, las decisiones); esto es
**cómo** aplicarlo sin escribirlo a mano cada vez, de forma repetible.

## Uso

```bash
cd infra/ansible
ansible-galaxy collection install -r requirements.yml     # una vez (ansible.posix.synchronize)
cp inventory/hosts.example.yml inventory/hosts.yml         # gitignored: es tu IP, no la del repo
# editar inventory/hosts.yml con la IP real y el usuario de la Pi

ansible-playbook pi.yml -k -K
```

`-k` pide la contraseña de SSH y `-K` la de `sudo` (la Pi, tal como la deja el Raspberry Pi
Imager, usa contraseña — no hay claves configuradas). Si más adelante se configura acceso por
clave, se pueden sacar los dos flags.

Corre completo (instala, copia y (re)inicia lo que cambió) o por partes, con `--tags`:

```bash
ansible-playbook pi.yml -k -K --tags despliegue     # solo copiar el código y reiniciar el servicio
ansible-playbook pi.yml -k -K --tags mosquitto,camara,entorno   # solo la instalación de paquetes
ansible-playbook pi.yml -k -K --tags verificar      # paso 8 de la guía: bench + temperatura (tarda, no corre solo)
```

## Configuración

Lo que varía por Pi física (a qué broker se conecta, con qué `dispositivo_id` publica) se define
en `group_vars/all.yml` (`ecosort_broker`, `ecosort_dispositivo`) — se puede pisar por host en
`inventory/hosts.yml` o con `-e ecosort_broker=...` en la línea de comandos. `tasks/servicio.yml`
lo vuelca en `/etc/ecosort/ecosort_pi.env` (`templates/ecosort_pi.env.j2`), que el `.service`
carga con `EnvironmentFile=` — el equivalente nativo de systemd a un `.env`. `ecosort_pi.py` los
lee como `ECOSORT_BROKER`/`ECOSORT_DISPOSITIVO` (con `os.getenv(...)` como default de sus propios
flags `--broker`/`--dispositivo`), así que correrlo a mano con un flag explícito sigue pisando lo
que diga el archivo. Nada de esto queda hardcodeado en el `.service` ni en el script.

## Qué hace (y de qué paso de la guía sale)

| Tarea | Paso | Qué automatiza |
|---|---|---|
| `tasks/mosquitto.yml` | 2 | Instala Mosquitto, copia `raspberry/mosquitto/ecosort.conf` (fuente única, no se duplica acá) y lo deja habilitado. |
| `tasks/camara.yml` | 4 | Instala `v4l-utils`/`fswebcam`, suma el usuario al grupo `video`, y muestra qué cámara detecta (sin fallar si todavía no está enchufada). |
| `tasks/entorno_python.yml` | 5 | Crea `~/ecosort-venv` (`--system-site-packages`) e instala `ai-edge-litert`, con una verificación de que se puede importar. |
| `tasks/despliegue.yml` | 7 | Sincroniza `raspberry/` y `schema/` a `~/ecosort/` (rsync, con `--delete`: una corrida deja la Pi igual a este checkout). |
| `tasks/servicio.yml` | 10 | Un servicio `systemd` (`ecosort_pi.service`) en vez del `nohup ... &` manual — con reinicio automático si el proceso se cae (ADR 0006). |
| `tasks/verificar.yml` | 8 | Opcional (`--tags verificar`): bench del modelo y temperatura. |

**Sigue siendo manual**, y por qué: el paso 1 (SSH) es justamente cómo Ansible llega a la Pi, no
hay nada que automatizar aparte del inventario. El paso 3 (probar MQTT con MQTTX) y el 9 (enfocar
la cámara mirando el video) son verificaciones interactivas, no cambios de estado. El paso 6
(entrenar el modelo) corre en Google Colab, fuera de la Pi.

**El modo Access Point (`192.168.20.0/28`) no está acá.** La guía dice que hoy se prueba
compartiendo la red que ya tiene internet — no está implementado ni a mano todavía, así que no hay
nada que este playbook pueda reproducir. Cuando se decida cómo (`hostapd`/`dnsmasq` o
NetworkManager), es la extensión natural de este rol, pero es una decisión de red nueva, no un
"empaquetado" de algo que ya existe.

## Decisiones de diseño

- **Layout en la Pi:** `~/ecosort/raspberry/` + `~/ecosort/schema/` (mismo layout que el repo, uno
  espejo del otro) — no el layout "aplanado" que da `scp -r raspberry ... ~/ecosort` cuando
  `~/ecosort` todavía no existe (ver la guía, paso 7). `raspberry/clases.py` soporta los dos
  (`aqui.parent / "schema"`, el primer candidato); acá se usa ese, porque es más explícito y no
  depende de si `~/ecosort` ya existía al correr el primer `scp`.
- **`rsync` con `--delete`** (`ansible.posix.synchronize`): una corrida del playbook deja la Pi
  exactamente como este checkout, sin ir acumulando versiones viejas. `--delete` nunca borra lo que
  está en `--exclude` (`__pycache__`, `tests/`), es el comportamiento por defecto de `rsync`.
- **El entorno virtual y `~/.bashrc` corren sin `become`.** Si corrieran como root, quedarían
  archivos de root en el home del usuario — el típico dolor de cabeza de Ansible + Raspberry Pi.
  Solo lo que necesita privilegios (`apt`, escribir en `/etc`, `systemd`) usa `become: true`.
- **El servicio solo se reinicia cuando algo cambió** (handler disparado por la plantilla o por el
  código sincronizado), no en cada corrida — para no cortar una clasificación en curso por correr
  el playbook de nuevo sin haber cambiado nada.
- **`host_key_checking = False`** (`ansible.cfg`): cómodo para una Pi que se re-flashea seguido en
  una LAN cerrada de laboratorio. No es una postura razonable para algo expuesto a internet.
- **`EnvironmentFile` en vez de `Environment=` inline en el `.service`**: lo que varía por Pi
  (broker, `dispositivo_id`) vive en un archivo aparte, no horneado en la unit de systemd. Antes
  el `.service` tenía `Environment=ECOSORT_BROKER=...`, pero `ecosort_pi.py` nunca la leía (solo el
  flag `--broker`) — quedaba ahí sin hacer nada. Ahora el env file es real: `ecosort_pi.py` lo lee.

## Probarlo sin una Pi real

```bash
ansible-playbook pi.yml --syntax-check
ansible-playbook pi.yml --list-tasks
python -m unittest discover -s tests -v   # renderiza templates/ecosort_pi.service.j2 con Jinja2
```

Nada de esto reemplaza correrlo contra la Pi real — eso, como el resto de lo que depende de
hardware, se valida a mano y se registra en `BITACORA.md`.

## Pendiente

- Correrlo contra la Pi real y registrar el resultado en `BITACORA.md` (todavía no se hizo).
- El paso 6 (entrenar en Colab) y el paso 9 (enfocar la cámara) quedan fuera a propósito: ver
  arriba.
- Modo Access Point: ver la sección de arriba.
- Cuando el firmware sume GPIO (servos), el usuario también va a necesitar el grupo `gpio` — no
  se agregó todavía porque `ecosort_pi.py` no lo usa aún.
