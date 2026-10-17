from __future__ import annotations

import gzip
import struct
from pathlib import Path

import numpy as np

from clustering_eval.application import ComparisonService
from clustering_eval.datasets.mnist import load_mnist, load_mnist_10k, load_mnist_full
from clustering_eval.datasets.registry import default_registry


def _write_images(path: Path, images: np.ndarray) -> None:
    images = np.asarray(images, dtype=np.uint8)
    n, rows, cols = images.shape
    with gzip.open(path, "wb") as f:
        f.write(struct.pack(">IIII", 2051, n, rows, cols))
        f.write(images.tobytes(order="C"))


def _write_labels(path: Path, labels: np.ndarray) -> None:
    labels = np.asarray(labels, dtype=np.uint8)
    with gzip.open(path, "wb") as f:
        f.write(struct.pack(">II", 2049, len(labels)))
        f.write(labels.tobytes(order="C"))


def _fixture_dir(tmp_path: Path) -> Path:
    # 20 tiny 2x2 images, two examples of every digit, split 10/10.
    labels = np.tile(np.arange(10, dtype=np.uint8), 2)
    images = np.arange(20 * 4, dtype=np.uint8).reshape(20, 2, 2)
    _write_images(tmp_path / "train-images-idx3-ubyte.gz", images[:10])
    _write_labels(tmp_path / "train-labels-idx1-ubyte.gz", labels[:10])
    _write_images(tmp_path / "t10k-images-idx3-ubyte.gz", images[10:])
    _write_labels(tmp_path / "t10k-labels-idx1-ubyte.gz", labels[10:])
    return tmp_path


def test_mnist_variants_are_exposed_without_eager_download() -> None:
    registry = default_registry()
    assert "mnist_10k" in registry._loaders
    assert "mnist_full" in registry._loaders
    names = ComparisonService(datasets=registry).dataset_names()
    assert "mnist_10k" in names
    assert "mnist_full" in names


def test_mnist_loader_reads_offline_idx_and_normalizes_pixels(tmp_path: Path) -> None:
    root = _fixture_dir(tmp_path)
    dataset = load_mnist({"path": str(root), "subset_size": None, "full": True})

    assert dataset.name == "mnist"
    assert dataset.X.shape == (20, 4)
    assert dataset.X.dtype == np.float32
    assert dataset.X.min() >= 0.0
    assert dataset.X.max() <= 1.0
    assert dataset.y is not None
    assert set(np.unique(dataset.y).tolist()) == set(range(10))
    assert dataset.metadata["pixel_scaling"] == "uint8 / 255 -> float32 [0, 1]"


def test_mnist_subset_is_deterministic_and_stratified(tmp_path: Path) -> None:
    root = _fixture_dir(tmp_path)
    first = load_mnist({"path": str(root), "subset_size": 10, "random_state": 7})
    second = load_mnist({"path": str(root), "subset_size": 10, "random_state": 7})

    assert np.array_equal(first.X, second.X)
    assert np.array_equal(first.y, second.y)
    assert len(first.y) == 10
    # With 2 samples/class and a 10-sample stratified subset, every digit appears once.
    assert sorted(np.bincount(first.y, minlength=10).tolist()) == [1] * 10


def test_named_mnist_variants_preserve_registry_names(tmp_path: Path) -> None:
    root = _fixture_dir(tmp_path)
    small = load_mnist_10k({"path": str(root), "subset_size": 10, "random_state": 1})
    full = load_mnist_full({"path": str(root)})
    assert small.name == "mnist_10k"
    assert len(small.X) == 10
    assert full.name == "mnist_full"
    assert len(full.X) == 20
