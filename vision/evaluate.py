"""evalúa sobre el test set held-out: matriz de confusión + precision/recall/f1.
reproduce el split de train.py (lee split.json) para no evaluar con nada ya visto.

uso: python evaluate.py --run-dir runs/mobilenetv3small
"""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from sklearn.metrics import ConfusionMatrixDisplay, classification_report, confusion_matrix

from dataset import build_manifest, make_dataset, split_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default="runs/mobilenetv3small")
    parser.add_argument("--model-name", default="final.keras",
                         help="final.keras (último) o best.keras (mejor val_accuracy)")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    classes = json.loads((run_dir / "classes.json").read_text())
    split_cfg = json.loads((run_dir / "split.json").read_text())

    data_dir = Path(split_cfg["data_dir"])
    _, paths, labels = build_manifest(data_dir)
    _, _, (test_p, test_y) = split_manifest(
        paths, labels,
        val_size=split_cfg["val_size"], test_size=split_cfg["test_size"], seed=split_cfg["seed"],
    )

    # img_size tiene que ser el mismo con el que se entrenó, si no el modelo
    # rechaza el input shape. split.json (runs viejos) puede no tenerlo -> 128.
    img_size_px = split_cfg.get("img_size", 128)
    img_size = (img_size_px, img_size_px)
    test_ds = make_dataset(test_p, test_y, img_size, args.batch_size)

    model = tf.keras.models.load_model(run_dir / args.model_name)
    probs = model.predict(test_ds)
    y_pred = np.argmax(probs, axis=1)

    report = classification_report(test_y, y_pred, target_names=classes, digits=3)
    print(report)
    (run_dir / "classification_report.txt").write_text(report)

    cm = confusion_matrix(test_y, y_pred)
    np.savetxt(run_dir / "confusion_matrix.csv", cm, fmt="%d", delimiter=",")

    fig, ax = plt.subplots(figsize=(7, 7))
    ConfusionMatrixDisplay(cm, display_labels=classes).plot(ax=ax, xticks_rotation=45, cmap="Blues")
    fig.tight_layout()
    fig.savefig(run_dir / "confusion_matrix.png", dpi=150)
    print(f"\nMatriz de confusión y reporte guardados en {run_dir}/")


if __name__ == "__main__":
    main()
