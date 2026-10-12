from pathlib import Path
import warnings

import numpy as np

from clustering_eval.algorithms.author_adapters import (
    AdaptedAuthorFDBSCAN,
    AdaptedAuthorFKDC,
    AdaptedAuthorFKM,
    AdaptedAuthorNNFC,
    AdaptedAuthorPFClus,
)
from clustering_eval.algorithms.registry import default_registry


def _tiny_data():
    rng = np.random.default_rng(7)
    X = np.vstack([
        rng.normal((-2.0, -2.0), 0.15, size=(12, 2)),
        rng.normal((2.0, 2.0), 0.15, size=(12, 2)),
    ])
    partition = [np.arange(0, 12), np.arange(12, 24)]
    return X, partition


def test_registry_contains_author_adapters():
    names = default_registry().names()
    assert "Adapted FKM" in names
    assert "Adapted HF_DBSCAN" in names
    assert "Adapted FKDC" in names
    assert "Adapted NN-FC" in names
    assert "Adapted p-FClus" in names


def test_fkm_uses_vendored_author_source():
    X, partition = _tiny_data()
    result = AdaptedAuthorFKM().run(X, partition, {"n_clusters": 2, "rounds": 2}, 42)
    assert len(result.labels) == len(X)
    assert result.model_state["source_commit"] == "b1f39cf481721da232f9426bc35feb2b79cf18d1"
    assert result.communication_bytes > 0


def test_fdbscan_uses_vendored_author_source():
    X, partition = _tiny_data()
    result = AdaptedAuthorFDBSCAN().run(X, partition, {"L": 0.5, "MIN_POINTS": 2}, 42)
    assert len(result.labels) == len(X)
    assert result.model_state["source_commit"] == "6223c2d9a0f893f5b92699afd918775c2e09adf4"


def test_fkdc_executes_author_results_flow():
    X, partition = _tiny_data()
    result = AdaptedAuthorFKDC().run(X, partition, {"n_clusters": 2}, 42)
    assert len(result.labels) == len(X)
    assert result.model_state["source_commit"] == "37f10faa27fbc6bc0335882909cf744b8a2c237e"


def test_nnfc_executes_author_flow_and_syntax_patch_is_minimal():
    X, partition = _tiny_data()
    result = AdaptedAuthorNNFC().run(X, partition, {"n_clusters": 2}, 42)
    assert len(result.labels) == len(X)
    assert result.model_state["source_commit"] == "404af20bf4abd524dd1c5bc0968e0e1a2491f828"

    root = Path(__file__).resolve().parents[1] / "clustering_eval" / "third_party" / "nnfc"
    original = (root / "utils_original.txt").read_text(encoding="utf-8")
    patched = (root / "utils.py").read_text(encoding="utf-8")
    expected = original.replace("\t\tnum1,num2=float(i)/float(j),float(j )/float(i)\n", "                num1,num2=float(i)/float(j),float(j )/float(i)\n")
    expected = expected.replace("delta[a] = min(delta[a], distance[a, b] * (distanceNeighborSum[a] + distanceNeighborSum[b]))", "delta[a] = minimum(delta[a], distance[a, b] * (distanceNeighborSum[a] + distanceNeighborSum[b]))")
    expected = expected.replace("indexSharedNeighbor = empty([n, n, k], int)", "indexSharedNeighbor = full([n, n, k], -1, int)", 1)
    old_ratio = """        arr = noisenew.reshape(1, noise.shape[0] * noise.shape[1])[0]\n        ratio = []\n        for i in arr:\n            for j in arr:\n                num1,num2=float(i)/float(j),float(j )/float(i)\n                ratio.append(max([num1,num2]))    \n        maxratio = max(ratio)\n"""
    new_ratio = """        arr = noisenew.reshape(1, noise.shape[0] * noise.shape[1])[0]\n        # Compatibility/performance patch: for strictly positive arr values,\n        # max(max(i/j, j/i) for all pairs) == max(arr) / min(arr). The author\n        # code computes the same value with an O(m^2) Python loop, which becomes\n        # impractical on high-dimensional datasets such as Digits.\n        arr_min = float(np.min(arr))\n        arr_max = float(np.max(arr))\n        maxratio = arr_max / arr_min\n"""
    expected = expected.replace(old_ratio, new_ratio)
    assert expected == patched

    fkdc_root = Path(__file__).resolve().parents[1] / "clustering_eval" / "third_party" / "fkdc"
    fkdc_original = (fkdc_root / "utils_original.txt").read_text(encoding="utf-8")
    fkdc_patched = (fkdc_root / "utils.py").read_text(encoding="utf-8")
    fkdc_expected = fkdc_original.replace(
        "delta[a] = min(delta[a], distance[a, b] * (distanceNeighborSum[a] + distanceNeighborSum[b]))",
        "delta[a] = minimum(delta[a], distance[a, b] * (distanceNeighborSum[a] + distanceNeighborSum[b]))",
    )
    fkdc_expected = fkdc_expected.replace(
        "indexSharedNeighbor = empty([n, n, k], int)",
        "indexSharedNeighbor = full([n, n, k], -1, int)",
        1,
    )
    assert fkdc_expected == fkdc_patched


def test_pfclus_executes_uploaded_author_functions_without_rewriting_source():
    X, partition = _tiny_data()
    result = AdaptedAuthorPFClus().run(
        X, partition, {"n_clusters": 2, "pfclus_max_iters": 2}, 42
    )
    assert len(result.labels) == len(X)
    assert set(np.unique(result.labels)).issubset({0, 1})
    assert result.model_state["source_commit"] == "3fd7c09d98fb23c9807931c6363ad1181eb283f1"
    assert result.model_state["rounds"] == 1
    assert result.communication_bytes > 0

    root = (
        Path(__file__).resolve().parents[1]
        / "clustering_eval"
        / "third_party"
        / "pfclus"
    )
    vendored = (root / "p-FClus.py").read_bytes()
    import hashlib
    assert hashlib.sha256(vendored).hexdigest() == (
        "1ab947e641b5bc95213041eda98e663d105d7c342b7d638b404a421c1b1cee3e"
    )


def test_fkdc_snn_patch_removes_uninitialized_buffer_runtime_warning():
    from clustering_eval.datasets.registry import default_registry as dataset_registry
    from clustering_eval.datasets.partitioning import make_partition
    from clustering_eval.application.comparison_service import _preprocess_algorithm_input

    ds = dataset_registry().load("wine")
    X = np.asarray(ds.X, dtype=float)
    y = np.asarray(ds.y)
    algorithm = AdaptedAuthorFKDC()
    X = _preprocess_algorithm_input(X, algorithm)
    partition = make_partition(
        "dirichlet", len(X), 5, 42, y=y, alpha=0.5, min_samples_per_client=3
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = algorithm.run(X, partition, {"n_clusters": 3, "k": 3}, 42)
    assert len(result.labels) == len(X)
    assert not [
        w for w in caught
        if "invalid value encountered in scalar divide" in str(w.message)
    ]
