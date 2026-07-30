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
