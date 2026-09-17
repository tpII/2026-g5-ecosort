"""convierte el .keras a TFLite int8 (lo que corre en la Pi, ADR 0001).
usa un subset del train set como representative_dataset para calibrar la cuantización.

uso: python export_tflite.py --run-dir runs/mobilenetv3small
"""

import argparse
import json
from pathlib import Path

import tensorflow as tf

from dataset import build_manifest, split_manifest


def representative_dataset_gen(paths, img_size, n_samples=200):
    rng_paths = paths[:n_samples]
    for path in rng_paths:
        img = tf.io.read_file(path)
        img = tf.io.decode_image(img, channels=3, expand_animations=False)
        img = tf.image.resize(img, img_size)
        img = tf.expand_dims(img, axis=0)  # batch de 1
        yield [img]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default="runs/mobilenetv3small")
    parser.add_argument("--model-name", default="final.keras")
    parser.add_argument("--rep-samples", type=int, default=200)
    parser.add_argument("--out-name", default="model_int8.tflite")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    split_cfg = json.loads((run_dir / "split.json").read_text())
    # tiene que matchear el img_size del entrenamiento, si no la calibración sale mal
    img_size_px = split_cfg.get("img_size", 128)
    img_size = (img_size_px, img_size_px)

    data_dir = Path(split_cfg["data_dir"])
    _, paths, labels = build_manifest(data_dir)
    (train_p, _), _, _ = split_manifest(
        paths, labels,
        val_size=split_cfg["val_size"], test_size=split_cfg["test_size"], seed=split_cfg["seed"],
    )

    model = tf.keras.models.load_model(run_dir / args.model_name)

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = lambda: representative_dataset_gen(
        train_p, img_size, args.rep_samples
    )
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.uint8
    converter.inference_output_type = tf.uint8

    tflite_model = converter.convert()

    out_path = run_dir / args.out_name
    out_path.write_bytes(tflite_model)
    size_kb = out_path.stat().st_size / 1024
    print(f"Modelo TFLite int8 guardado en {out_path} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
