# vision — pruebas de MobileNetV3

Transfer learning sobre **MobileNetV3Small** (preentrenada en ImageNet) para
el clasificador de residuos. Implementa lo que ya definía la
[ADR 0001](../docs/adr/0001-modelo-preentrenado-vs-finetune.md).

No duplica el dataset: por ahora sigue leyendo las imágenes desde
`software_detección/TrashNate/Data/archive/dataset-resized/` (path relativo
por defecto en `train.py`). Si el equipo decide mover el dataset a
`vision/data/`, hay que actualizar ese default.

## Instalación

### Opción A: Docker (recomendado — no depende de tu SO ni de activar nada)

```bash
docker compose run --rm train      # entrena (usa el dataset de TrashNate montado como volumen)
docker compose run --rm evaluate   # evalúa runs/mobilenetv3small
docker compose run --rm export     # exporta a TFLite int8
```

Cada uno construye la imagen la primera vez (tarda unos minutos, después queda
cacheada) y deja los resultados en `runs/` en tu disco, no solo dentro del
contenedor. Para pasar otros flags, editar el `command:` de ese servicio en
`docker-compose.yml` o correr directo:

```bash
docker build -t ecosort-vision .
docker run --rm -v "$(pwd)/../software_detección:/data/software_detección:ro" \
  -v "$(pwd)/runs:/app/runs" ecosort-vision \
  train.py --data-dir /data/software_detección/TrashNate/Data/archive/dataset-resized --img-size 160
```

**`webcam_test.py` no entra acá** — necesita cámara + ventana (`cv2.imshow`),
y eso no es portable entre SO dentro de un contenedor (en Mac/Windows Docker
Desktop ni siquiera tiene acceso directo a la webcam del host). Para probar
contra la cámara, seguí con la opción B.

### Opción B: venv local (necesario para `webcam_test.py`)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
# 1. Entrenar (split 70/15/15 train/val/test, class weights, fine-tuning en 2 fases)
python train.py --img-size 128 --head-epochs 15 --finetune-epochs 10

# 2. Evaluar sobre el test set held-out (matriz de confusión + reporte)
python evaluate.py --run-dir runs/mobilenetv3small

# 3. Exportar a TFLite int8 (formato que corre en la Pi)
python export_tflite.py --run-dir runs/mobilenetv3small

# 4. Probar en vivo contra la webcam de la notebook (solo venv local, ver arriba)
python webcam_test.py --run-dir runs/mobilenetv3small --model final.keras
# o, para chequear que la cuantización int8 no rompió nada:
python webcam_test.py --run-dir runs/mobilenetv3small --model model_int8.tflite
```

Cada corrida queda en `runs/<nombre>/`: `final.keras`, `best.keras`,
`classes.json` (orden de clases), `split.json` (parámetros del split, para
que `evaluate.py`/`export_tflite.py` reconstruyan el mismo test set),
`history.json`, y después de evaluar/exportar: `confusion_matrix.png`,
`classification_report.txt`, `model_int8.tflite`.

## Pendiente / decisiones abiertas

- **Mapeo de clases 6→4** (`classes.py`): el dataset TrashNet trae 6 clases,
  el producto tiene 4 compuertas. Falta decidir qué hacer con `metal`, que
  no tiene compuerta — ver el TODO en `classes.py`. Por ahora se entrena
  sobre las 6 clases nativas.
- **Dataset propio**: TrashNet es un dataset genérico, no fotos propias
  real. Las pruebas acá sirven para validar el enfoque (transfer learning +
  TFLite) — el dataset final probablemente necesite fotos propias del
  equipo, con las condiciones reales de cámara/luz del gabinete.
- `runs/` no se versiona (ver `.gitignore`) — son artefactos de
  entrenamiento, no código.
- **CI** (`.github/workflows/continuous-integration.yml`, job `vision`): solo corre cuando el PR
  toca `vision/` o el dataset. Es un smoke test (1 epoch, img-size chico) que
  valida que el pipeline train→evaluate→export no está roto — no mide
  precisión. La matriz de confusión validada empíricamente que pide la
  cátedra para noviembre se corre a mano y se documenta aparte.
