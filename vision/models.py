# fábrica de backbones para transfer learning (ADR 0001).
#
# mobilenetv2 es el que está desplegado hoy en raspberry/modelo/ (entrenado
# originalmente en software_detección/MobileNetV2/entrenar_ecosort.ipynb,
# ahora vision/notebooks/entrenar_colab.ipynb) — es el default. mobilenetv3small
# queda como alternativa para comparar tamaño/latencia/precisión en igualdad
# de condiciones (mismo split, mismo img-size, mismas épocas).

import tensorflow as tf

BACKBONES = ("mobilenetv2", "mobilenetv3small")


@tf.keras.utils.register_keras_serializable(package="ecosort")
class Clip255(tf.keras.layers.Layer):
    """Recorta a [0,255] tras RandomBrightness/RandomContrast.

    No es un Lambda: Keras rechaza deserializar lambdas de Python en un
    .keras por riesgo de ejecución de código arbitrario (load_model tira
    ValueError salvo que se pase safe_mode=False) — con una capa registrada
    como esta, evaluate.py/export_tflite.py cargan el modelo sin flags raros.
    """

    def call(self, x):
        return tf.clip_by_value(x, 0.0, 255.0)


def build_augmentation():
    # TrashNet es fondo de estudio parejo, la cámara real (webcam o gabinete)
    # no — brightness/contrast fuertes para no depender de esa iluminación.
    # mismos parámetros que entrenar_ecosort.ipynb.
    return tf.keras.Sequential([
        tf.keras.layers.RandomFlip("horizontal_and_vertical"),
        tf.keras.layers.RandomRotation(0.1),
        tf.keras.layers.RandomZoom(0.15),
        tf.keras.layers.RandomBrightness(0.2, value_range=(0, 255)),
        tf.keras.layers.RandomContrast(0.2),
        Clip255(),
    ], name="augmentation")


def build_model(backbone: str, num_classes: int, img_size: int, alpha: float = 1.0):
    """Backbone preentrenado (congelado) + head nuevo. Devuelve (model, base)
    — base se usa después para el fine-tuning (unfreeze_last_layers)."""
    if backbone == "mobilenetv2":
        base = tf.keras.applications.MobileNetV2(
            input_shape=(img_size, img_size, 3), alpha=alpha,
            include_top=False, weights="imagenet",
        )
        preprocess = tf.keras.layers.Rescaling(1 / 127.5, offset=-1)  # [0,255] -> [-1,1]
        pool = tf.keras.layers.GlobalAveragePooling2D()
        dropout_rate = 0.2
    elif backbone == "mobilenetv3small":
        base = tf.keras.applications.MobileNetV3Small(
            input_shape=(img_size, img_size, 3), alpha=alpha,
            include_top=False, weights="imagenet", pooling="avg",
            include_preprocessing=True,  # normaliza internamente, espera [0,255]
        )
        preprocess = None
        pool = None  # ya viene con pooling="avg"
        dropout_rate = 0.3
    else:
        raise ValueError(f"backbone desconocido: {backbone!r} (opciones: {BACKBONES})")

    base.trainable = False

    inputs = tf.keras.Input(shape=(img_size, img_size, 3))
    x = build_augmentation()(inputs)
    if preprocess is not None:
        x = preprocess(x)
    x = base(x, training=False)
    if pool is not None:
        x = pool(x)
    x = tf.keras.layers.Dropout(dropout_rate)(x)
    outputs = tf.keras.layers.Dense(num_classes, activation="softmax")(x)

    model = tf.keras.Model(inputs, outputs, name=f"ecosort_{backbone}")
    return model, base


def unfreeze_last_layers(base: tf.keras.Model, n_layers: int):
    """Descongela las últimas n_layers de la base para fine-tuning.
    BatchNorm siempre queda congelado (estable con batches chicos, mismo
    criterio que entrenar_ecosort.ipynb)."""
    base.trainable = True
    for layer in base.layers[:-n_layers]:
        layer.trainable = False
    for layer in base.layers:
        if isinstance(layer, tf.keras.layers.BatchNormalization):
            layer.trainable = False
