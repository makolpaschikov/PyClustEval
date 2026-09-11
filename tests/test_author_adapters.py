from pathlib import Path

import numpy as np

from clustering_eval.algorithms.author_adapters import (
    AdaptedAuthorFDBSCAN,
    AdaptedAuthorFKDC,
    AdaptedAuthorFKM,
    AdaptedAuthorNNFC,
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
    assert expected == patched

    fkdc_root = Path(__file__).resolve().parents[1] / "clustering_eval" / "third_party" / "fkdc"
    fkdc_original = (fkdc_root / "utils_original.txt").read_text(encoding="utf-8")
    fkdc_patched = (fkdc_root / "utils.py").read_text(encoding="utf-8")
    assert fkdc_original.replace("delta[a] = min(delta[a], distance[a, b] * (distanceNeighborSum[a] + distanceNeighborSum[b]))", "delta[a] = minimum(delta[a], distance[a, b] * (distanceNeighborSum[a] + distanceNeighborSum[b]))") == fkdc_patched
