"""convierte el .keras a TFLite: una versión int8 (la que corre en la Pi,
ADR 0001) y una fp32 sin cuantizar, de referencia para comparar latencia
(ver la tabla de benchmark en docs/guia-instalacion-raspberry.md).
usa un subset del train set como representative_dataset para calibrar la cuantización int8.

uso: python export_tflite.py --run-dir runs/mobilenetv2
"""

import argparse
import json
from pathlib import Path

import tensorflow as tf

from dataset import build_manifest, split_manifest
import models  # noqa: F401 — registra Clip255 para que load_model la encuentre


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
    parser.add_argument("--run-dir", default="runs/mobilenetv2")
    parser.add_argument("--model-name", default="final.keras")
    parser.add_argument("--rep-samples", type=int, default=200)
    parser.add_argument("--out-name", default="model_int8.tflite")
    parser.add_argument("--io-dtype", choices=["float32", "uint8"], default="float32",
                         help="dtype de entrada/salida del .tflite int8. float32 es lo "
                              "que corre hoy en raspberry/ (entrenar_ecosort.ipynb); "
                              "uint8 da un archivo más chico pero raspberry/inferencia_pi.py "
                              "todavía no se probó contra esa variante.")
    parser.add_argument("--skip-fp32", action="store_true",
                         help="no generar la versión fp32 de referencia (solo el int8)")
    parser.add_argument("--fp32-out-name", default="model_fp32.tflite")
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
    if args.io_dtype == "uint8":
        converter.inference_input_type = tf.uint8
        converter.inference_output_type = tf.uint8
    # float32 (default): pesos y activaciones internas quedan en int8, pero la
    # entrada/salida del modelo sigue en float32 — es lo que ya corre en la Pi
    # (ver raspberry/inferencia_pi.py, que interpreta ambos casos por dtype).

    tflite_int8 = converter.convert()
    out_path = run_dir / args.out_name
    out_path.write_bytes(tflite_int8)
    print(f"Modelo TFLite int8 guardado en {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")

    if not args.skip_fp32:
        # sin cuantizar — solo de referencia para comparar latencia contra el int8
        converter_fp32 = tf.lite.TFLiteConverter.from_keras_model(model)
        tflite_fp32 = converter_fp32.convert()
        fp32_path = run_dir / args.fp32_out_name
        fp32_path.write_bytes(tflite_fp32)
        print(f"Modelo TFLite fp32 guardado en {fp32_path} ({fp32_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
