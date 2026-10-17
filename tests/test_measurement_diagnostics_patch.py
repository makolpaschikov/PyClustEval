from __future__ import annotations

from pathlib import Path

import numpy as np
from sklearn.datasets import load_iris
from sklearn.preprocessing import StandardScaler

from clustering_eval.algorithms.base import AlgorithmResult, ClusteringAlgorithm
from clustering_eval.algorithms.registry import AlgorithmRegistry
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.datasets.partitioning import iid_partition, label_limited_partition
from clustering_eval.federated.initialization import federated_priority_sample_centers
from clustering_eval.results import HistoryStore


class FixedLabelsAlgorithm(ClusteringAlgorithm):
    is_federated = True
    common_param_support = ("k", "seed")

    def __init__(self, name: str, preprocessing: str) -> None:
        self.name = name
        self.input_preprocessing = preprocessing

    def run(self, X, partition, params, seed):
        k = int(params.get("k", 3))
        labels = np.arange(len(X), dtype=int) % k
        return AlgorithmResult(
            labels=labels,
            model_state={"backend": "fixed-labels", "rounds": 1},
            runtime_sec=0.001,
        )


def test_federated_priority_initialization_is_partition_invariant_when_all_clients_active() -> None:
    data = load_iris()
    X = StandardScaler().fit_transform(data.data)
    iid = iid_partition(len(X), 5, 42, min_samples_per_client=3)
    label_limited = label_limited_partition(
        data.target, len(X), 5, 42, labels_per_client=2, min_samples_per_client=3
    )
    active = list(range(5))
    centers_a, report_a = federated_priority_sample_centers(
        X, iid, 3, 42, active_client_ids=active
    )
    centers_b, report_b = federated_priority_sample_centers(
        X, label_limited, 3, 42, active_client_ids=active
    )
    assert report_a["selected_sample_indices"] == report_b["selected_sample_indices"]
    assert np.array_equal(centers_a, centers_b)


def test_full_participation_exact_stats_can_keep_same_prediction_but_client_metrics_change(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    base = dict(
        mode="federated",
        dataset_name="iris",
        algorithms=("fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"),
        seed=42,
        num_clients=5,
        rounds=10,
        participation_rate=1.0,
        dropout_rate=0.0,
    )
    iid = service.compare(RunRequest(**base, partition_mode="iid"))
    skew = service.compare(RunRequest(**base, partition_mode="label_limited"))

    iid_kmeans = iid.results[0].model_state["diagnostics"]
    skew_kmeans = skew.results[0].model_state["diagnostics"]
    assert iid.partition is not None and skew.partition is not None
    assert iid.partition.fingerprint != skew.partition.fingerprint
    assert iid_kmeans["prediction_hash"] == skew_kmeans["prediction_hash"]
    assert iid_kmeans["client_metrics"]["ari"] != skew_kmeans["client_metrics"]["ari"]


def test_partial_participation_changes_active_data_fingerprint(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    common = dict(
        mode="federated",
        dataset_name="iris",
        algorithms=("fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"),
        seed=7,
        num_clients=5,
        partition_mode="label_limited",
        rounds=4,
    )
    full = service.compare(RunRequest(**common, participation_rate=1.0, dropout_rate=0.0))
    partial = service.compare(RunRequest(**common, participation_rate=0.6, dropout_rate=0.25))
    full_id = full.results[0].model_state["benchmark"]["active_data_fingerprint"]
    partial_id = partial.results[0].model_state["benchmark"]["active_data_fingerprint"]
    assert full_id != partial_id
    assert all("active_data_hash" in row for row in partial.partition.round_schedule)


def test_gaussian_dp_changes_benchmark_input_hash_but_not_eval_space_hash(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    common = dict(
        mode="federated",
        dataset_name="iris",
        algorithms=("fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"),
        seed=42,
        num_clients=5,
        partition_mode="iid",
    )
    plain = service.compare(RunRequest(**common, privacy_mode="none"))
    private = service.compare(RunRequest(
        **common,
        privacy_mode="gaussian_dp",
        dp_epsilon=1.0,
        dp_delta=1e-5,
        dp_clip_norm=1.0,
    ))
    b_plain = plain.results[0].model_state["benchmark"]
    b_private = private.results[0].model_state["benchmark"]
    assert b_plain["benchmark_input_hash"] != b_private["benchmark_input_hash"]
    assert b_plain["evaluation_input_hash"] == b_private["evaluation_input_hash"]


def test_internal_metrics_use_common_eval_space_across_algorithm_preprocessing(tmp_path: Path) -> None:
    registry = AlgorithmRegistry()
    registry.register(FixedLabelsAlgorithm("raw_fixed", "raw"))
    registry.register(FixedLabelsAlgorithm("minmax_fixed", "minmax"))
    service = ComparisonService(
        algorithms=registry,
        history_store=HistoryStore(tmp_path / "history"),
    )
    report = service.compare(RunRequest(
        mode="federated",
        dataset_name="iris",
        algorithms=("raw_fixed", "minmax_fixed"),
        seed=42,
        num_clients=5,
    ))
    first, second = report.results
    assert first.silhouette == second.silhouette
    assert first.davies_bouldin == second.davies_bouldin
    assert first.calinski_harabasz == second.calinski_harabasz
    assert first.model_state["benchmark"]["evaluation_space"] == "StandardScaler(original_raw_X)"


def test_excel_export_includes_client_metrics_and_hash_diagnostics(tmp_path: Path) -> None:
    from zipfile import ZipFile

    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(RunRequest(
        mode="federated",
        dataset_name="iris",
        algorithms=("fed_kmeans_numpy", "fed_gmm_diag_numpy"),
        seed=42,
        num_clients=5,
        partition_mode="label_limited",
        rounds=4,
        participation_rate=0.6,
        dropout_rate=0.25,
    ))
    output = tmp_path / "diagnostics.xlsx"
    service.export_excel(report, str(output))
    assert output.exists()
    with ZipFile(output) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        assert "Client Metrics" in workbook_xml
        assert "Partition" in workbook_xml
