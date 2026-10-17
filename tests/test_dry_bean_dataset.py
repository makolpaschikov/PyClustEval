from __future__ import annotations

from pathlib import Path

import numpy as np

from clustering_eval.application import ComparisonService
from clustering_eval.datasets.dry_bean import load_dry_bean
from clustering_eval.datasets.registry import default_registry


MINI_ARFF = """@RELATION dry_bean_test

@ATTRIBUTE Area NUMERIC
@ATTRIBUTE Perimeter NUMERIC
@ATTRIBUTE MajorAxisLength NUMERIC
@ATTRIBUTE Class {SEKER,BARBUNYA,BOMBAY}

@DATA
100,20.0,11.0,SEKER
120,22.0,12.0,BARBUNYA
140,24.0,13.0,BOMBAY
160,26.0,14.0,SEKER
"""


def test_dry_bean_is_exposed_by_default_registry_without_eager_download() -> None:
    registry = default_registry()
    assert "dry_bean" in registry._loaders
    assert "dry_bean" in ComparisonService(datasets=registry).dataset_names()


def test_dry_bean_loader_supports_offline_arff_path(tmp_path: Path) -> None:
    path = tmp_path / "Dry_Bean_Dataset.arff"
    path.write_text(MINI_ARFF, encoding="utf-8")

    dataset = load_dry_bean({"path": str(path)})

    assert dataset.name == "dry_bean"
    assert dataset.X.shape == (4, 3)
    assert dataset.y is not None
    assert dataset.y.shape == (4,)
    assert np.isfinite(dataset.X).all()
    assert len(np.unique(dataset.y)) == 3
    assert dataset.metadata["source"] == "UCI Machine Learning Repository"
    assert dataset.metadata["uci_dataset_id"] == 602
    assert dataset.metadata["doi"] == "10.24432/C50S4B"
    assert dataset.metadata["feature_names"] == [
        "Area", "Perimeter", "MajorAxisLength"
    ]
    assert dataset.metadata["downloaded_and_cached"] is False
