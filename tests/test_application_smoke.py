from pathlib import Path

from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.results import HistoryStore


def test_local_comparison_and_history(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="local",
            dataset_name="blobs",
            algorithms=("kmeans", "agglomerative"),
            seed=42,
        )
    )

    assert len(report.results) == 2
    assert report.history_directory is not None
    assert (report.history_directory / "report.json").exists()
    assert (report.history_directory / "results.csv").exists()
    assert (report.history_directory / "execution.log").exists()


def test_federated_numpy_comparison(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"),
            seed=42,
            num_clients=5,
            partition_mode="iid",
        )
    )

    assert len(report.results) == 2
    assert report.partition is not None
    assert report.partition.num_clients == 5
    assert sum(report.partition.client_sample_counts) == report.n_samples


def test_hf_dbscan_author_preprocessing_is_used(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("Adapted HF_DBSCAN", "Adapted FKM"),
            seed=42,
            num_clients=5,
            partition_mode="iid",
            algorithm_params={"L": 0.15, "MIN_POINTS": 4, "rounds": 2},
        )
    )

    hf = next(item for item in report.results if item.algorithm == "Adapted HF_DBSCAN")
    assert hf.model_state["variant"] == "horizontal"
    assert hf.model_state["preprocessing"].startswith("MinMaxScaler")
    assert hf.ari is not None and hf.ari > 0.5
    assert len(hf.model_state["dense_cells"]) > 0


def test_pfclus_author_adapter_runs_through_comparison_service(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("Adapted p-FClus", "Adapted FKM"),
            seed=42,
            num_clients=5,
            partition_mode="iid",
            algorithm_params={"rounds": 2, "pfclus_max_iters": 2},
        )
    )

    pf = next(item for item in report.results if item.algorithm == "Adapted p-FClus")
    assert pf.model_state["preprocessing"].startswith("raw")
    assert pf.model_state["source_commit"] == "3fd7c09d98fb23c9807931c6363ad1181eb283f1"
    assert pf.rounds == 1
    assert pf.communication_bytes > 0
    assert len(pf.model_state["client_mean_clustering_costs"]) == 5
