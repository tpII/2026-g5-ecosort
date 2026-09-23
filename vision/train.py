"""transfer learning para el clasificador de residuos (ADR 0001).

default: MobileNetV2 224px — el mismo backbone/resolución que
software_detección/MobileNetV2/entrenar_ecosort.ipynb, el que está
desplegado hoy en raspberry/modelo/. --backbone mobilenetv3small queda para
comparar en igualdad de condiciones (ver vision/README.md).

TODO: dataset trae 6 clases (TrashNet) pero el gabinete tiene 4 compuertas,
metal no tiene gate. por ahora entreno con las 6 tal cual, el mapeo queda
en classes.py hasta que lo definamos.

uso: python train.py --head-epochs 15 --finetune-epochs 15
"""

import argparse
import json
from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.utils.class_weight import compute_class_weight

from dataset import build_manifest, make_dataset, split_manifest
from models import BACKBONES, build_model, unfreeze_last_layers

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "trashnet"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backbone", choices=BACKBONES, default="mobilenetv2")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--img-size", type=int, default=224)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--val-size", type=float, default=0.15)
    parser.add_argument("--test-size", type=float, default=0.15)
    parser.add_argument("--head-epochs", type=int, default=15)
    parser.add_argument("--finetune-epochs", type=int, default=15)
    parser.add_argument("--finetune-layers", type=int, default=40,
                         help="Cuántas capas finales de la base descongelar en la fase 2")
    parser.add_argument("--out-dir", default=None,
                         help="default: runs/<backbone>")
    args = parser.parse_args()
    out_dir = Path(args.out_dir or f"runs/{args.backbone}")

    data_dir = Path(args.data_dir)
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

    model, base = build_model(args.backbone, len(classes), args.img_size, alpha=args.alpha)
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
        "backbone": args.backbone,
        "alpha": args.alpha,
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
