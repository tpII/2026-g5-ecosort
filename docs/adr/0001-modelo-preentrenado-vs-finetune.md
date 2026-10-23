# ADR 0001 — Modelo: preentrenado vs. fine-tuning vs. entrenamiento desde cero

**Estado:** Aceptado. Corrección retroactiva: esta ADR quedó escrita para una herramienta
drag-and-drop que nunca se usó, y nadie la actualizó cuando se decidió lo que realmente se
implementó y ya está corriendo en la Pi. Lo de abajo describe lo que se hizo, no lo que se
planeaba hacer.

## Contexto

Necesitamos un clasificador de imágenes (hoy 5 clases de producto, ver la
[ADR 0008](0008-contrato-de-eventos.md); originalmente 4) que corra en una Raspberry Pi 3 vía
TFLite, con un cronograma de entrega en dos tramos (octubre / noviembre) y sin acceso a GPU de
entrenamiento dedicada.

## Decisión

Fine-tuning sobre **MobileNetV2** preentrenada con ImageNet, con código propio versionado en
[`vision/`](../../vision/) (`train.py`, `models.py`, TensorFlow/Keras) — no una herramienta
drag-and-drop. Se entrena en Google Colab (GPU T4 gratuita, `vision/notebooks/entrenar_colab.ipynb`,
un envoltorio delgado que llama a este mismo código) y se exporta a TFLite int8
(`export_tflite.py`). `MobileNetV3Small` queda como alternativa para comparar en igualdad de
condiciones (mismo split, mismas épocas) antes de decidir cuál va a producción — ver
`vision/README.md`.

Se descarta entrenar desde cero por: tiempo disponible, tamaño del dataset propio que el equipo
puede armar, y capacidad de cómputo disponible (sin GPU propia). Se descarta usar el preentrenado
sin ajuste por: las clases del dataset base no coinciden 1:1 con las del producto. Se descarta una
herramienta drag-and-drop (la idea original) porque el equipo tenía capacidad de escribir y
versionar el entrenamiento como código, con más control sobre el split, las clases y la
cuantización — sin costo real adicional una vez armado.

## Consecuencias

- Permite iterar el modelo probándolo con la cámara de una notebook (`vision/webcam_test.py`), en
  paralelo y desde el día 1, sin esperar a que el hardware esté armado (walking skeleton).
- El export a TFLite int8 es el mismo formato que corre en la Pi — no hay
  paso de conversión adicional que pueda introducir sorpresas de último
  momento.
- Dataset elegido: **TrashNet** (6 clases nativas, ver `vision/data/trashnet/`), mapeado a las
  clases del producto en el borde (`schema/clases.json`, ADR 0008) — no en el entrenamiento.
  Medido en la Pi: 31 ms de latencia, ~79 % de accuracy en test, sin la clase orgánico (TrashNet no
  la tiene) y con `metal` como la clase más floja (precisión 0,675). Fotos propias del gabinete
  (incluyendo orgánico y negativos para `ninguno`, ADR 0009) quedan pendientes para reentrenar.
