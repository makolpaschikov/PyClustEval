from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

from clustering_eval.third_party.fdbscan.fd_dbscan import FDBSCAN_Client, get_all_neighbors


def _load_original_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "clustering_eval"
        / "third_party"
        / "fdbscan"
        / "fd_dbscan_original.py"
    )
    spec = importlib.util.spec_from_file_location("fdbscan_original_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sparse_hfdbscan_patch_preserves_low_dimensional_cell_counts() -> None:
    original = _load_original_module()
    X = np.array([
        [0.02, 0.03],
        [0.04, 0.08],
        [0.31, 0.32],
        [0.35, 0.39],
        [0.35, 0.39],
    ])
    params = {"dataset": X, "L": 0.1, "true_labels": np.zeros(len(X), dtype=int)}
    old_client = original.FDBSCAN_Client()
    old_client.initialize(params)
    new_client = FDBSCAN_Client()
    new_client.initialize(params)
    assert old_client.compute_local_update() == new_client.compute_local_update()


def test_direct_neighbor_patch_is_set_equivalent_to_original() -> None:
    original = _load_original_module()
    for cell in [(0, 0), (2, -1, 4), (3, 2, 1, 0)]:
        assert set(original.get_all_neighbors(cell)) == set(get_all_neighbors(cell))
        assert len(get_all_neighbors(cell)) == 2 * len(cell)


def test_sparse_hfdbscan_client_handles_high_dimensional_input_without_dense_grid() -> None:
    rng = np.random.default_rng(42)
    X = rng.random((80, 64))
    client = FDBSCAN_Client()
    client.initialize({"dataset": X, "L": 0.15, "true_labels": np.zeros(len(X), dtype=int)})
    contribution = client.compute_local_update()
    assert sum(contribution.values()) == len(X)
    assert len(contribution) <= len(X)
