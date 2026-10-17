from __future__ import annotations

import os
import shutil
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import arff

from .base import Dataset

UCI_DATASET_ID = 602
UCI_DATASET_URL = "https://archive.ics.uci.edu/dataset/602/dry+bean+dataset"
UCI_DOWNLOAD_URL = "https://archive.ics.uci.edu/static/public/602/dry%2Bbean%2Bdataset.zip"
UCI_DOI = "10.24432/C50S4B"
EXPECTED_INSTANCES = 13_611
EXPECTED_FEATURES = 16


def _default_cache_dir() -> Path:
    override = os.environ.get("PYCLUSTEVAL_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve() / "dry_bean"
    return Path.home() / ".cache" / "pyclusteval" / "datasets" / "dry_bean"


def _download_official_arff(destination: Path) -> None:
    """Download the official UCI archive and extract only the ARFF file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive_tmp = destination.parent / "dry_bean_dataset.zip.part"
    request = urllib.request.Request(
        UCI_DOWNLOAD_URL,
        headers={"User-Agent": "PyClustEval/0.1 (+https://archive.ics.uci.edu/)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response, archive_tmp.open("wb") as out:
            shutil.copyfileobj(response, out)
        with zipfile.ZipFile(archive_tmp) as archive:
            candidates = [
                name for name in archive.namelist()
                if name.lower().endswith("dry_bean_dataset.arff")
            ]
            if not candidates:
                raise RuntimeError(
                    "UCI Dry Bean archive does not contain Dry_Bean_Dataset.arff"
                )
            payload = archive.read(candidates[0])
        tmp_arff = destination.with_suffix(destination.suffix + ".part")
        tmp_arff.write_bytes(payload)
        tmp_arff.replace(destination)
    except (urllib.error.URLError, TimeoutError, OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(
            "Не удалось скачать Dry Bean с UCI. Проверь интернет и повтори запуск. "
            "Для офлайн-режима можно заранее скачать Dry_Bean_Dataset.arff и "
            "передать его через DatasetRegistry.load('dry_bean', {'path': '...'}), "
            "либо задать PYCLUSTEVAL_DATA_DIR для общего кэша."
        ) from exc
    finally:
        archive_tmp.unlink(missing_ok=True)


def _resolve_data_path(params: dict[str, Any]) -> tuple[Path, bool]:
    explicit = params.get("path")
    if explicit:
        path = Path(str(explicit)).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Dry Bean data file not found: {path}")
        return path, False

    cache_dir = Path(str(params.get("cache_dir", _default_cache_dir()))).expanduser()
    arff_path = cache_dir / "Dry_Bean_Dataset.arff"
    if not arff_path.exists():
        _download_official_arff(arff_path)
    return arff_path, True


def _read_arff(path: Path) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    data, _meta = arff.loadarff(path)
    names = list(data.dtype.names or ())
    if not names:
        raise ValueError(f"Dry Bean ARFF contains no columns: {path}")

    target_name = next((name for name in names if name.lower() == "class"), None)
    if target_name is None:
        raise ValueError("Dry Bean ARFF does not contain the Class target column")

    feature_names = [name for name in names if name != target_name]
    X = np.column_stack(
        [np.asarray(data[name], dtype=np.float64) for name in feature_names]
    ).astype(np.float64, copy=False)

    raw_target = np.asarray(data[target_name])
    decoded = np.asarray(
        [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in raw_target],
        dtype=object,
    )
    class_names_arr, y = np.unique(decoded, return_inverse=True)
    class_names = [str(item) for item in class_names_arr.tolist()]

    if not np.isfinite(X).all():
        raise ValueError("Dry Bean contains non-finite feature values")
    return X, y.astype(np.int64, copy=False), feature_names, class_names


def load_dry_bean(params: dict[str, Any] | None = None) -> Dataset:
    """Load UCI Dry Bean (13,611 rows, 16 numeric features, 7 classes).

    The official UCI archive is downloaded lazily on first use and the extracted
    ARFF file is cached locally. Supplying ``path`` is supported for offline use
    and tests; it may point to an ARFF file with the same schema.
    """
    params = dict(params or {})
    path, official_cached = _resolve_data_path(params)
    X, y, feature_names, class_names = _read_arff(path)

    if official_cached:
        if X.shape != (EXPECTED_INSTANCES, EXPECTED_FEATURES):
            raise ValueError(
                "Unexpected UCI Dry Bean shape: "
                f"{X.shape}; expected ({EXPECTED_INSTANCES}, {EXPECTED_FEATURES})"
            )
        if len(class_names) != 7:
            raise ValueError(
                f"Unexpected UCI Dry Bean class count: {len(class_names)}; expected 7"
            )

    metadata = {
        "source": "UCI Machine Learning Repository",
        "uci_dataset_id": UCI_DATASET_ID,
        "source_url": UCI_DATASET_URL,
        "download_url": UCI_DOWNLOAD_URL,
        "doi": UCI_DOI,
        "license": "CC BY 4.0",
        "n_samples": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "n_classes": int(len(class_names)),
        "feature_names": feature_names,
        "class_names": class_names,
        "data_path": str(path),
        "downloaded_and_cached": bool(official_cached),
    }
    return Dataset("dry_bean", X, y, metadata)
