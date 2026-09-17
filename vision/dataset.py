# arma el manifest (path, label) y los splits train/val/test. no copia nada a disco.

from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.model_selection import train_test_split

IMG_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SEED = 123


def build_manifest(data_dir: Path):
    # data_dir/<clase>/*.jpg -> (classes, paths, labels)
    classes = sorted(d.name for d in data_dir.iterdir() if d.is_dir())
    if not classes:
        raise ValueError(f"No hay subcarpetas de clases en {data_dir}")

    paths, labels = [], []
    for idx, cls in enumerate(classes):
        for f in sorted((data_dir / cls).iterdir()):
            if f.suffix.lower() in IMG_EXTENSIONS:
                paths.append(str(f))
                labels.append(idx)

    return classes, np.array(paths), np.array(labels)


def split_manifest(paths, labels, val_size=0.15, test_size=0.15, seed=SEED):
    # split estratificado, mantiene proporción de clases en cada parte
    train_paths, rest_paths, train_labels, rest_labels = train_test_split(
        paths, labels,
        test_size=val_size + test_size,
        stratify=labels,
        random_state=seed,
    )
    rel_test = test_size / (val_size + test_size)
    val_paths, test_paths, val_labels, test_labels = train_test_split(
        rest_paths, rest_labels,
        test_size=rel_test,
        stratify=rest_labels,
        random_state=seed,
    )
    return (
        (train_paths, train_labels),
        (val_paths, val_labels),
        (test_paths, test_labels),
    )


def make_dataset(paths, labels, img_size, batch_size, shuffle=False):
    # ojo: no normalizo acá, MobileNetV3 ya trae su propio preprocessing (espera [0,255])

    def _load(path, label):
        img = tf.io.read_file(path)
        img = tf.io.decode_image(img, channels=3, expand_animations=False)
        img = tf.image.resize(img, img_size)
        return img, label

    ds = tf.data.Dataset.from_tensor_slices((paths, labels))
    if shuffle:
        ds = ds.shuffle(buffer_size=len(paths), seed=SEED, reshuffle_each_iteration=True)
    ds = ds.map(_load, num_parallel_calls=tf.data.AUTOTUNE)
    ds = ds.batch(batch_size)
    return ds.prefetch(tf.data.AUTOTUNE)
