"""transfer learning sobre MobileNetV3Small (ADR 0001), reemplaza la CNN
desde cero de TrashNate/main.py.

TODO: dataset trae 6 clases (TrashNet) pero el gabinete tiene 4 compuertas,
metal no tiene gate. por ahora entreno con las 6 tal cual, el mapeo queda
en classes.py hasta que lo definamos.

uso: python train.py --img-size 128 --head-epochs 15 --finetune-epochs 10
"""

import argparse
import json
from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.utils.class_weight import compute_class_weight

from dataset import build_manifest, make_dataset, split_manifest

DEFAULT_DATA_DIR = (
    Path(__file__).resolve().parent.parent
    / "software_detección" / "TrashNate" / "Data" / "archive" / "dataset-resized"
)


def build_model(num_classes: int, img_size: int, alpha: float = 1.0):
    # alpha=1.0: los pesos imagenet de keras para v3 solo están para ese ancho.
    # si necesito algo más chico para la Pi, cambiar a MobileNetV2 (soporta 0.35/0.5/0.75/1.0)
    base = tf.keras.applications.MobileNetV3Small(
        input_shape=(img_size, img_size, 3),
        alpha=alpha,
        include_top=False,
        weights="imagenet",
        pooling="avg",
        include_preprocessing=True,  # normaliza internamente, espera [0,255]
    )
    base.trainable = False

    augment = tf.keras.Sequential([
        tf.keras.layers.RandomFlip("horizontal"),
        tf.keras.layers.RandomRotation(0.1),
        tf.keras.layers.RandomZoom(0.1),
        # brightness/contrast fuerte porque TrashNet es fondo de estudio parejo,
        # la webcam no
        tf.keras.layers.RandomBrightness(0.25),
        tf.keras.layers.RandomContrast(0.25),
    ], name="augmentation")

    inputs = tf.keras.Input(shape=(img_size, img_size, 3))
    x = augment(inputs)
    x = base(x, training=False)
    x = tf.keras.layers.Dropout(0.3)(x)
    outputs = tf.keras.layers.Dense(num_classes, activation="softmax")(x)

    model = tf.keras.Model(inputs, outputs, name="ecosort_mobilenetv3small")
    return model, base


def unfreeze_last_layers(base: tf.keras.Model, n_layers: int):
    base.trainable = True
    for layer in base.layers[:-n_layers]:
        layer.trainable = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--img-size", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--val-size", type=float, default=0.15)
    parser.add_argument("--test-size", type=float, default=0.15)
    parser.add_argument("--head-epochs", type=int, default=15)
    parser.add_argument("--finetune-epochs", type=int, default=10)
    parser.add_argument("--finetune-layers", type=int, default=30,
                         help="Cuántas capas finales de la base descongelar en la fase 2")
    parser.add_argument("--out-dir", default="runs/mobilenetv3small")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    img_size = (args.img_size, args.img_size)

    classes, paths, labels = build_manifest(data_dir)
    print(f"Clases detectadas ({len(classes)}): {classes}")
    print(f"Total de imágenes: {len(paths)}")

    (train_p, train_y), (val_p, val_y), (test_p, test_y) = split_manifest(
        paths, labels, val_size=args.val_size, test_size=args.test_size
    )
    print(f"Split -> train: {len(train_p)}  val: {len(val_p)}  test: {len(test_p)}")

    train_ds = make_dataset(train_p, train_y, img_size, args.batch_size, shuffle=True)
    val_ds = make_dataset(val_p, val_y, img_size, args.batch_size)
    test_ds = make_dataset(test_p, test_y, img_size, args.batch_size)

    class_weight_values = compute_class_weight(
        class_weight="balanced", classes=np.unique(labels), y=labels
    )
    class_weight = dict(enumerate(class_weight_values))
    print(f"Class weights (por desbalance del dataset): {class_weight}")

    model, base = build_model(len(classes), args.img_size, alpha=args.alpha)
    model.summary()

    checkpoint_path = out_dir / "best.keras"
    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(
            str(checkpoint_path), monitor="val_accuracy", save_best_only=True
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor="val_accuracy", patience=5, restore_best_weights=True
        ),
    ]

    # Fase 1: base congelada, solo se entrena el head nuevo.
    model.compile(
        optimizer=tf.keras.optimizers.Adam(1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    print("\n=== Fase 1: entrenando head (base congelada) ===")
    history_head = model.fit(
        train_ds, validation_data=val_ds,
        epochs=args.head_epochs, class_weight=class_weight, callbacks=callbacks,
    )

    # Fase 2: descongelar las últimas capas de la base y afinar con LR bajo.
    unfreeze_last_layers(base, args.finetune_layers)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(1e-5),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    print(f"\n=== Fase 2: fine-tuning ({args.finetune_layers} capas finales de la base) ===")
    history_ft = model.fit(
        train_ds, validation_data=val_ds,
        epochs=args.finetune_epochs, class_weight=class_weight, callbacks=callbacks,
    )

    print("\n=== Evaluación sobre test set (held-out, nunca visto en entrenamiento) ===")
    test_loss, test_acc = model.evaluate(test_ds)
    print(f"Test accuracy: {test_acc:.4f}  Test loss: {test_loss:.4f}")

    model.save(out_dir / "final.keras")

    # evaluate.py y export_tflite.py necesitan esto para reproducir el mismo split
    (out_dir / "classes.json").write_text(json.dumps(classes, ensure_ascii=False, indent=2))
    (out_dir / "split.json").write_text(json.dumps({
        "data_dir": str(data_dir),
        "val_size": args.val_size,
        "test_size": args.test_size,
        "seed": 123,
        "img_size": args.img_size,
    }, indent=2))
    history = {
        "head": history_head.history,
        "finetune": history_ft.history,
        "test_accuracy": test_acc,
        "test_loss": test_loss,
    }
    (out_dir / "history.json").write_text(json.dumps(history, indent=2))

    print(f"\nModelo, clases e historial guardados en {out_dir}/")


if __name__ == "__main__":
    main()
