# vision — entrenamiento del modelo

Transfer learning (ADR 0001) para el clasificador de residuos. Backbone por
defecto: **MobileNetV2 224px** — el mismo que está desplegado hoy en
`raspberry/modelo/` (entrenado originalmente en
`software_detección/MobileNetV2/entrenar_ecosort.ipynb`, ahora
[`notebooks/entrenar_colab.ipynb`](notebooks/entrenar_colab.ipynb)).
`--backbone mobilenetv3small` queda como alternativa para comparar tamaño,
latencia y precisión en igualdad de condiciones (mismo split, mismo
img-size, mismas épocas) — ver `models.py`.

El dataset (TrashNet, 6 clases) vive en `data/trashnet/`, versionado en git
junto con el código.

## Dónde entrenar

- **Colab** (recomendado para entrenar en serio): abrir
  [`notebooks/entrenar_colab.ipynb`](notebooks/entrenar_colab.ipynb) en
  https://colab.research.google.com, activar GPU T4, *Ejecutar todas*. El
  notebook es un envoltorio delgado — clona el repo y llama a estos mismos
  scripts, no reimplementa nada. Al final descarga un `.zip` listo para
  copiar a `raspberry/modelo/`.
- **Docker** (reproducible, sin GPU, lo que corre en CI):

  ```bash
  export GID=$(id -g); export UID   # una vez por sesión de terminal — ver nota abajo
  docker compose run --rm train      # entrena (dataset montado como volumen)
  docker compose run --rm evaluate   # evalúa runs/mobilenetv2
  docker compose run --rm export     # exporta a TFLite (int8 + fp32)
  ```

  Sin esto, el contenedor corre como root y los archivos que escribe en
  `runs/` quedan con dueño root en tu máquina — no vas a poder borrarlos ni
  sobreescribirlos después sin `sudo`. `UID` ya es una variable de shell en
  bash (de solo lectura, pero exportable tal cual); `GID` no existe como
  variable de shell, por eso hay que asignarla a mano con `id -g`.

  Para otros flags, editar el `command:` del servicio en
  `docker-compose.yml` o correr directo:

  ```bash
  docker build -t ecosort-vision .
  docker run --rm --user "$(id -u):$(id -g)" \
    -v "$(pwd)/data:/app/data:ro" -v "$(pwd)/runs:/app/runs" \
    ecosort-vision train.py --backbone mobilenetv3small --img-size 160
  ```

  **`webcam_test.py` no entra en Docker** — necesita cámara + ventana
  (`cv2.imshow`), no portable entre SO dentro de un contenedor. Para eso,
  usar un venv local:

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```

## Uso

```bash
# 1. Entrenar (split 70/15/15 train/val/test, class weights, fine-tuning en 2 fases)
python train.py --backbone mobilenetv2 --head-epochs 15 --finetune-epochs 15

# 2. Evaluar sobre el test set held-out (matriz de confusión + reporte)
python evaluate.py --run-dir runs/mobilenetv2

# 3. Exportar a TFLite: int8 (el que va a la Pi) + fp32 (referencia de latencia)
python export_tflite.py --run-dir runs/mobilenetv2

# 4. Probar en vivo contra la webcam (solo venv local, ver arriba)
python webcam_test.py --run-dir runs/mobilenetv2 --model final.keras
# o, para chequear que la cuantización int8 no rompió nada:
python webcam_test.py --run-dir runs/mobilenetv2 --model model_int8.tflite
```

Cada corrida queda en `runs/<backbone>/`: `final.keras`, `best.keras`,
`classes.json` (orden de clases), `split.json` (parámetros del split y del
modelo — `evaluate.py`/`export_tflite.py`/`webcam_test.py` lo leen para
reconstruir el mismo test set y el mismo img-size), `history.json`, y
después de evaluar/exportar: `confusion_matrix.png`,
`classification_report.txt`, `model_int8.tflite`, `model_fp32.tflite`.

## Comparar MobileNetV2 contra MobileNetV3Small

Correr `train.py` dos veces cambiando solo `--backbone` (mismo dataset,
mismo split — la seed es fija — mismas épocas), y comparar:
`runs/<backbone>/history.json` (test_accuracy), el tamaño de
`model_int8.tflite`, y la latencia real en la Pi con
`raspberry/inferencia_pi.py --bench`. Con eso se decide con datos, no a
ojo, cuál va a producción.

## Pendiente / decisiones abiertas

- **Mapeo de clases** (`classes.py`, copia de `schema/clases.json`, ADR 0008): el dataset
  TrashNet trae 6 clases y el producto tiene 5 (con `metal` como clase propia y su quinta
  compuerta). El mapeo lo aplica la Pi en runtime (`raspberry/clases.py`), no el
  entrenamiento: se entrena con las etiquetas nativas.
- **Clase `ninguno` (ADR 0009): falta juntar los negativos.** Es la clase que le permite al
  modelo decir "esto no es un residuo" (una mano, una cara, un animal, la plataforma vacía)
  en vez de forzar alguna de las otras. Se agrega como una carpeta más del dataset,
  `data/trashnet/ninguno/*.jpg`, y `train.py` la toma sola (arma las clases a partir de las
  carpetas). Qué juntar: fotos propias del gabinete con la plataforma vacía, manos, brazos, caras,
  pelo, sombras, celulares, llaves, y de datasets públicos imágenes de personas y animales.
  Conviene un tamaño parecido al de las otras clases (~400 a 600) y variedad de luz y fondo.
  `classes.py` ya la declara en `DESCARTES` y la Pi la reconoce (`schema/clases.json`).
- **Falta la clase orgánico**: TrashNet no la tiene (`trash` se mapea a `organico`). El
  dataset final va a necesitar fotos propias del gabinete — ver
  `docs/guia-instalacion-raspberry.md`, sección "Limitaciones conocidas" — y latas y aluminio
  para `metal`, que es de las clases más flojas.
- `data/` y `runs/` no se versionan igual: `data/trashnet/` sí está en git
  (es el dataset base), `runs/` no (son artefactos de una corrida, ver
  `.gitignore`).
- **CI** (`.github/workflows/ci.yml`, job `vision`): solo corre cuando el PR
  toca `vision/`. Es un smoke test (1 época, img-size chico) que valida que
  train→evaluate→export no está roto — no mide precisión. La matriz de
  confusión validada empíricamente que pide la cátedra para noviembre se
  corre a mano (o en Colab) y se documenta aparte.
