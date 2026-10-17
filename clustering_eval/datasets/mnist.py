from __future__ import annotations

import gzip
import os
import shutil
import struct
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.model_selection import StratifiedShuffleSplit

from .base import Dataset

MNIST_SOURCE_URL = "http://yann.lecun.com/exdb/mnist/"
MNIST_MIRROR_BASE = "https://storage.googleapis.com/cvdf-datasets/mnist"
EXPECTED_INSTANCES = 70_000
EXPECTED_FEATURES = 28 * 28
EXPECTED_CLASSES = 10
DEFAULT_BENCHMARK_SAMPLES = 10_000
DEFAULT_SUBSET_SEED = 42

_FILES = {
    "train-images-idx3-ubyte.gz": f"{MNIST_MIRROR_BASE}/train-images-idx3-ubyte.gz",
    "train-labels-idx1-ubyte.gz": f"{MNIST_MIRROR_BASE}/train-labels-idx1-ubyte.gz",
    "t10k-images-idx3-ubyte.gz": f"{MNIST_MIRROR_BASE}/t10k-images-idx3-ubyte.gz",
    "t10k-labels-idx1-ubyte.gz": f"{MNIST_MIRROR_BASE}/t10k-labels-idx1-ubyte.gz",
}


def _default_cache_dir() -> Path:
    override = os.environ.get("PYCLUSTEVAL_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve() / "mnist"
    return Path.home() / ".cache" / "pyclusteval" / "datasets" / "mnist"


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "PyClustEval/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as out:
            shutil.copyfileobj(response, out)
        tmp.replace(destination)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            "Не удалось скачать MNIST. Проверь интернет и повтори запуск. "
            "Для офлайн-режима можно заранее положить четыре официальных IDX .gz "
            "файла MNIST в ~/.cache/pyclusteval/datasets/mnist/ или каталог "
            "PYCLUSTEVAL_DATA_DIR/mnist/."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)


def _resolve_files(params: dict[str, Any]) -> tuple[dict[str, Path], bool]:
    cache_dir = Path(str(params.get("cache_dir", _default_cache_dir()))).expanduser().resolve()
    explicit_dir = params.get("path")
    if explicit_dir:
        cache_dir = Path(str(explicit_dir)).expanduser().resolve()
        if not cache_dir.exists():
            raise FileNotFoundError(f"MNIST directory not found: {cache_dir}")
        download_missing = False
    else:
        download_missing = True

    resolved: dict[str, Path] = {}
    downloaded = False
    for filename, url in _FILES.items():
        path = cache_dir / filename
        if not path.exists():
            if not download_missing:
                raise FileNotFoundError(f"MNIST file not found: {path}")
            _download(url, path)
            downloaded = True
        resolved[filename] = path
    return resolved, downloaded


def _read_idx_images(path: Path) -> np.ndarray:
    with gzip.open(path, "rb") as stream:
        header = stream.read(16)
        if len(header) != 16:
            raise ValueError(f"Invalid MNIST image header: {path}")
        magic, count, rows, cols = struct.unpack(">IIII", header)
        if magic != 2051:
            raise ValueError(f"Invalid MNIST image magic {magic}: {path}")
        raw = stream.read()
    expected = count * rows * cols
    if len(raw) != expected:
        raise ValueError(
            f"Invalid MNIST image payload size in {path}: {len(raw)}; expected {expected}"
        )
    return np.frombuffer(raw, dtype=np.uint8).reshape(count, rows * cols)


def _read_idx_labels(path: Path) -> np.ndarray:
    with gzip.open(path, "rb") as stream:
        header = stream.read(8)
        if len(header) != 8:
            raise ValueError(f"Invalid MNIST label header: {path}")
        magic, count = struct.unpack(">II", header)
        if magic != 2049:
            raise ValueError(f"Invalid MNIST label magic {magic}: {path}")
        raw = stream.read()
    if len(raw) != count:
        raise ValueError(
            f"Invalid MNIST label payload size in {path}: {len(raw)}; expected {count}"
        )
    return np.frombuffer(raw, dtype=np.uint8).astype(np.int64, copy=False)


def _load_full_uint8(files: dict[str, Path]) -> tuple[np.ndarray, np.ndarray]:
    train_x = _read_idx_images(files["train-images-idx3-ubyte.gz"])
    train_y = _read_idx_labels(files["train-labels-idx1-ubyte.gz"])
    test_x = _read_idx_images(files["t10k-images-idx3-ubyte.gz"])
    test_y = _read_idx_labels(files["t10k-labels-idx1-ubyte.gz"])
    if len(train_x) != len(train_y) or len(test_x) != len(test_y):
        raise ValueError("MNIST image/label counts do not match")
    X = np.concatenate([train_x, test_x], axis=0)
    y = np.concatenate([train_y, test_y], axis=0)
    return X, y


def _stratified_subset(
    X: np.ndarray,
    y: np.ndarray,
    n_samples: int,
    random_state: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if n_samples <= 0:
        raise ValueError("MNIST subset_size must be positive")
    if n_samples >= len(X):
        idx = np.arange(len(X), dtype=np.int64)
        return X, y, idx
    splitter = StratifiedShuffleSplit(
        n_splits=1,
        train_size=n_samples,
        random_state=random_state,
    )
    idx, _ = next(splitter.split(np.zeros(len(y), dtype=np.uint8), y))
    idx = np.sort(idx.astype(np.int64, copy=False))
    return X[idx], y[idx], idx


def load_mnist(params: dict[str, Any] | None = None) -> Dataset:
    """Load MNIST from IDX gzip files.

    Default mode is a deterministic stratified 10k benchmark subset of the
    canonical 70k train+test corpus. Pass ``subset_size=None`` or ``full=True``
    for the entire 70k set. Pixel values are normalized from uint8 [0,255] to
    float32 [0,1] before they enter algorithm-specific preprocessing.
    """
    params = dict(params or {})
    files, downloaded = _resolve_files(params)
    X_u8, y = _load_full_uint8(files)
    total_loaded_samples = int(len(X_u8))

    if X_u8.shape != (EXPECTED_INSTANCES, EXPECTED_FEATURES):
        # Explicit/offline test directories may intentionally contain a tiny
        # valid IDX fixture. Strict canonical-shape validation is only required
        # for the default downloaded/cache path.
        if not params.get("path"):
            raise ValueError(
                f"Unexpected MNIST shape: {X_u8.shape}; expected "
                f"({EXPECTED_INSTANCES}, {EXPECTED_FEATURES})"
            )
    if len(np.unique(y)) != EXPECTED_CLASSES and not params.get("path"):
        raise ValueError(
            f"Unexpected MNIST class count: {len(np.unique(y))}; expected {EXPECTED_CLASSES}"
        )

    full = bool(params.get("full", False))
    subset_raw = params.get("subset_size", None if full else DEFAULT_BENCHMARK_SAMPLES)
    subset_size = None if subset_raw is None else int(subset_raw)
    subset_seed = int(params.get("random_state", DEFAULT_SUBSET_SEED))

    selected_indices = np.arange(len(X_u8), dtype=np.int64)
    if subset_size is not None:
        X_u8, y, selected_indices = _stratified_subset(
            X_u8, y, subset_size, subset_seed
        )

    X = X_u8.astype(np.float32) / np.float32(255.0)
    class_names = [str(int(v)) for v in sorted(np.unique(y).tolist())]
    metadata = {
        "source": "MNIST handwritten digit database",
        "source_url": MNIST_SOURCE_URL,
        "download_mirror": MNIST_MIRROR_BASE,
        "n_total_samples": total_loaded_samples,
        "n_samples": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "n_classes": int(len(class_names)),
        "class_names": class_names,
        "image_shape": [28, 28] if X.shape[1] == 784 else None,
        "pixel_scaling": "uint8 / 255 -> float32 [0, 1]",
        "subset_size": None if subset_size is None else int(X.shape[0]),
        "subset_strategy": "stratified deterministic sample" if subset_size is not None and subset_size < EXPECTED_INSTANCES else "full corpus",
        "subset_seed": subset_seed if subset_size is not None else None,
        "downloaded_this_run": bool(downloaded),
        "data_directory": str(next(iter(files.values())).parent),
    }
    return Dataset("mnist", X, y.astype(np.int64, copy=False), metadata)


def load_mnist_10k(params: dict[str, Any] | None = None) -> Dataset:
    options = dict(params or {})
    options.setdefault("subset_size", DEFAULT_BENCHMARK_SAMPLES)
    options["full"] = False
    dataset = load_mnist(options)
    metadata = dict(dataset.metadata)
    metadata["registry_name"] = "mnist_10k"
    return Dataset("mnist_10k", dataset.X, dataset.y, metadata)


def load_mnist_full(params: dict[str, Any] | None = None) -> Dataset:
    options = dict(params or {})
    options["subset_size"] = None
    options["full"] = True
    dataset = load_mnist(options)
    metadata = dict(dataset.metadata)
    metadata["registry_name"] = "mnist_full"
    return Dataset("mnist_full", dataset.X, dataset.y, metadata)
