from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
from sklearn.metrics import silhouette_score, davies_bouldin_score, calinski_harabasz_score

from clustering_eval.metrics.clustering import compute_metrics
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.results import HistoryStore


def test_noise_is_not_a_third_cluster_for_geometric_scores():
    X = np.asarray([[0, 0], [0, .1], [.1, 0], [6, 6], [6.1, 6], [6, 6.1], [60, -40]], dtype=float)
    labels = np.asarray([0, 0, 0, 1, 1, 1, -1])
    metrics = compute_metrics(X, None, labels, ["silhouette", "davies_bouldin", "calinski_harabasz"])
    assert math.isclose(metrics["silhouette"], silhouette_score(X[:-1], labels[:-1]))
    assert math.isclose(metrics["davies_bouldin"], davies_bouldin_score(X[:-1], labels[:-1]))
    assert math.isclose(metrics["calinski_harabasz"], calinski_harabasz_score(X[:-1], labels[:-1]))
    assert not math.isclose(metrics["silhouette"], silhouette_score(X, labels))


def test_zero_or_one_assigned_cluster_is_undefined():
    X = np.asarray([[0, 0], [2, 2], [8, 8]], dtype=float)
    for labels in ([0, -1, -1], [-1, -1, -1]):
        out = compute_metrics(X, np.array([0, 1, 1]), np.asarray(labels),
                              ["ari", "nmi", "silhouette", "davies_bouldin", "calinski_harabasz"])
        assert math.isnan(out["silhouette"])
        assert math.isnan(out["davies_bouldin"])
        assert math.isnan(out["calinski_harabasz"])
        assert np.isfinite(out["ari"])


def test_history_contains_metric_schema_coverage_and_wall_time(tmp_path: Path):
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(RunRequest(mode="local", dataset_name="iris", algorithms=("dbscan", "kmeans")))
    for result in report.results:
        d = result.model_state["diagnostics"]
        assert d["metric_schema_version"] == "clustering_metrics_v3_ami_assigned_only"
        assert 0 <= d["assigned_fraction"] <= 1
        assert d["runtime_wall_including_preprocessing_sec"] > 0
        assert result.model_state["benchmark"]["metric_schema_version"] == d["metric_schema_version"]
    with (report.history_directory / "results.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert all(r["metric_schema_version"] for r in rows)
    assert all(r["runtime_wall_including_preprocessing_sec"] for r in rows)


def test_dp_report_does_not_claim_end_to_end_dp(tmp_path: Path):
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(RunRequest(mode="federated", dataset_name="iris",
                  algorithms=("fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"),
                  privacy_mode="gaussian_dp", seed=2))
    assert report.privacy_report["end_to_end_report_is_dp"] is False
    assert "NOT end-to-end" in report.privacy_report["public_release_warning"]
    assert any("PRIVACY WARNING" in item for item in report.log_lines)


def test_large_dataset_silhouette_fixed_and_bounded(monkeypatch):
    import clustering_eval.metrics.clustering as m
    from sklearn.datasets import make_blobs
    X, _ = make_blobs(n_samples=3000, centers=3, random_state=4)
    labels = np.r_[np.zeros(1000, dtype=int), np.ones(1000, dtype=int), np.full(1000, 2, dtype=int)]
    indices = m.silhouette_reference_indices(len(X))
    assert len(indices) == 2000
    assert np.array_equal(indices, m.silhouette_reference_indices(len(X)))
    captured = []
    original = m.silhouette_score
    def spy(data, predicted):
        captured.append(len(data))
        return original(data, predicted)
    monkeypatch.setattr(m, "silhouette_score", spy)
    result = m.compute_metrics(X, None, labels, ["silhouette"])
    assert np.isfinite(result["silhouette"])
    assert captured == [2000]
