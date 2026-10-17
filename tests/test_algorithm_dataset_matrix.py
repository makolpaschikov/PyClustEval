from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from clustering_eval.algorithms.registry import default_registry as algorithm_registry
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.application.comparison_service import _preprocess_algorithm_input
from clustering_eval.datasets.partitioning import make_partition
from clustering_eval.datasets.registry import default_registry as dataset_registry
from clustering_eval.results import HistoryStore


LOCAL_ALGORITHMS = ("kmeans", "dbscan", "gmm", "agglomerative")
FEDERATED_NON_FLOWER = (
    "fed_kmeans_numpy",
    "fed_fuzzy_cmeans_numpy",
    "fed_gmm_diag_numpy",
    "Adapted FKM",
    "Adapted HF_DBSCAN",
    "Adapted FKDC",
    "Adapted NN-FC",
    "Adapted p-FClus",
)
DATASETS = ("iris", "wine", "blobs", "digits")
PARTITIONS = ("iid", "dirichlet")


def _dataset(name: str):
    ds = dataset_registry().load(name)
    return np.asarray(ds.X, dtype=np.float64), np.asarray(ds.y)


def _common_params(k: int) -> dict[str, object]:
    return {
        "k": k,
        "n_clusters": k,
        "rounds": 10,
        "tol": 1e-4,
        "max_iter": 300,
        "density_min_samples": 4,
        "client_cpus": 1.0,
        "client_gpus": 0.0,
    }


@pytest.mark.parametrize("dataset_name", DATASETS)
@pytest.mark.parametrize("algorithm_name", LOCAL_ALGORITHMS)
def test_local_algorithm_dataset_matrix_runs(algorithm_name: str, dataset_name: str) -> None:
    X_raw, y = _dataset(dataset_name)
    algorithm = algorithm_registry().get(algorithm_name)
    X = _preprocess_algorithm_input(X_raw, algorithm)
    params = _common_params(len(np.unique(y)))
    params.update(dict(getattr(algorithm, "default_params", {}) or {}))
    result = algorithm.run(X, None, params, seed=42)
    assert len(result.labels) == len(X)
    assert np.isfinite(np.asarray(result.labels, dtype=float)).all()


@pytest.mark.parametrize("dataset_name", DATASETS)
@pytest.mark.parametrize("partition_mode", PARTITIONS)
@pytest.mark.parametrize("algorithm_name", FEDERATED_NON_FLOWER)
def test_federated_algorithm_dataset_matrix_runs(
    algorithm_name: str,
    dataset_name: str,
    partition_mode: str,
) -> None:
    X_raw, y = _dataset(dataset_name)
    algorithm = algorithm_registry().get(algorithm_name)
    X = _preprocess_algorithm_input(X_raw, algorithm)
    partition = make_partition(
        partition_mode,
        len(X),
        5,
        42,
        y=y,
        alpha=0.5,
        min_samples_per_client=3,
    )
    params = _common_params(len(np.unique(y)))
    params.update(dict(getattr(algorithm, "default_params", {}) or {}))
    result = algorithm.run(X, partition, params, seed=42)
    assert len(result.labels) == len(X)
    assert np.isfinite(np.asarray(result.labels, dtype=float)).all()


def test_common_benchmark_parameters_are_shared_and_recorded(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("fed_kmeans_numpy", "Adapted FKM"),
            seed=17,
            num_clients=5,
            partition_mode="dirichlet",
            dirichlet_alpha=0.5,
            target_clusters=4,
            rounds=7,
            tol=1e-5,
            max_iter=123,
            min_samples_per_client=3,
        )
    )
    assert report.partition is not None
    assert min(report.partition.client_sample_counts) >= 3
    for result in report.results:
        bench = result.model_state["benchmark"]
        assert bench["seed"] == 17
        assert bench["target_clusters"] == 4
        assert bench["cluster_count_source"] == "user"
        assert bench["round_budget"] == 7
        assert bench["tol"] == 1e-5
        assert bench["max_iter"] == 123
        assert bench["density_min_samples"] == 5
        assert bench["min_samples_per_client"] == 3
        assert bench["effective_params"]["k"] == 4
        assert bench["effective_params"]["rounds"] == 7
        assert bench["effective_params"]["tol"] == 1e-5
        assert bench["effective_params"]["max_iter"] == 123


def test_per_algorithm_override_does_not_leak_to_competitor(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("Adapted HF_DBSCAN", "Adapted FKM"),
            algorithm_params_by_name={
                "Adapted HF_DBSCAN": {"L": 0.25, "MIN_POINTS": 4}
            },
        )
    )
    by_name = {item.algorithm: item for item in report.results}
    hf_params = by_name["Adapted HF_DBSCAN"].model_state["benchmark"]["effective_params"]
    fkm_params = by_name["Adapted FKM"].model_state["benchmark"]["effective_params"]
    assert hf_params["L"] == 0.25
    assert "L" not in fkm_params
    assert "MIN_POINTS" not in fkm_params


def test_oracle_k_is_explicit_when_target_clusters_not_provided(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="local",
            dataset_name="iris",
            algorithms=("kmeans", "gmm"),
        )
    )
    for result in report.results:
        bench = result.model_state["benchmark"]
        assert bench["target_clusters"] == 3
        assert bench["cluster_count_source"] == "ground_truth_oracle"


def test_degenerate_density_result_is_detected_not_silently_treated_as_failure(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="wine",
            algorithms=("Adapted HF_DBSCAN", "Adapted FKM"),
        )
    )
    hf = next(item for item in report.results if item.algorithm == "Adapted HF_DBSCAN")
    assert hf.model_state["diagnostics"]["degenerate"] is True
    assert hf.model_state["diagnostics"]["noise_fraction"] == 1.0
    assert any("вырожденную кластеризацию" in line for line in report.log_lines)



def test_near_degenerate_result_is_detected(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="digits",
            algorithms=("Adapted NN-FC", "Adapted FKM"),
        )
    )
    nnfc = next(item for item in report.results if item.algorithm == "Adapted NN-FC")
    diagnostics = nnfc.model_state["diagnostics"]
    assert diagnostics["near_degenerate"] is True
    assert diagnostics["dominant_cluster_fraction"] >= 0.95
    assert any("почти вырожденную кластеризацию" in line for line in report.log_lines)

def test_flower_adapters_are_matrix_ready_when_optional_dependency_is_installed() -> None:
    # Matrix tests for Flower are intentionally conditional: the base project keeps
    # Flower/Ray optional. In an environment with flwr[simulation], this test makes
    # the omission visible rather than pretending the runtime was exercised here.
    if importlib.util.find_spec("flwr") is None:
        pytest.skip("flwr[simulation] is optional and not installed in this test environment")
    names = algorithm_registry().names()
    assert "fed_kmeans_flower" in names
    assert "fed_fuzzy_cmeans_flower" in names
    assert "fed_gmm_diag_flower" in names


def test_density_defaults_are_algorithm_appropriate_and_common_dbscan_control_still_works():
    local = algorithm_registry().get("dbscan")
    hf = algorithm_registry().get("Adapted HF_DBSCAN")
    X_raw, y = _dataset("iris")
    common = _common_params(len(np.unique(y)))
    common["density_min_samples"] = 7

    X_local = _preprocess_algorithm_input(X_raw, local)
    local_params = dict(common)
    local_params.update(dict(getattr(local, "default_params", {}) or {}))
    local_result = local.run(X_local, None, local_params, 42)
    assert local_result.model_state["min_samples"] == 7

    X_hf = _preprocess_algorithm_input(X_raw, hf)
    partition = make_partition(
        "iid", len(X_hf), 5, 42, y=y, alpha=0.5, min_samples_per_client=3
    )
    hf_params = dict(common)
    hf_params.update(dict(getattr(hf, "default_params", {}) or {}))
    hf_result = hf.run(X_hf, partition, hf_params, 42)
    # HF_DBSCAN preserves the author's MIN_POINTS=4 instead of inheriting
    # sklearn DBSCAN's generic min_samples control.
    assert hf_result.model_state["MIN_POINTS"] == 4


def test_common_parameter_applicability_is_recorded(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="local",
            dataset_name="iris",
            algorithms=("kmeans", "agglomerative"),
            target_clusters=3,
        )
    )
    by_name = {item.algorithm: item for item in report.results}
    assert set(by_name["kmeans"].model_state["benchmark"]["common_param_support"]) == {"k", "max_iter", "tol", "seed"}
    assert "tol" not in by_name["kmeans"].model_state["benchmark"]["common_params_not_applicable"]
    assert by_name["agglomerative"].model_state["benchmark"]["common_param_support"] == ["k"]
    assert "max_iter" in by_name["agglomerative"].model_state["benchmark"]["common_params_not_applicable"]
