from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from clustering_eval.algorithms.base import AlgorithmResult, ClusteringAlgorithm
from clustering_eval.algorithms.registry import AlgorithmRegistry
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.results import HistoryStore


class PartitionSpyAlgorithm(ClusteringAlgorithm):
    is_federated = True
    input_preprocessing = "raw"
    common_param_support = ("k", "seed")

    def __init__(self, name: str, seen: list[tuple[int, tuple[tuple[int, ...], ...]]]) -> None:
        self.name = name
        self._seen = seen

    def run(
        self,
        X: np.ndarray,
        partition: list[np.ndarray] | None,
        params: dict[str, object],
        seed: int,
    ) -> AlgorithmResult:
        assert partition is not None
        signature = tuple(tuple(int(v) for v in client) for client in partition)
        self._seen.append((id(partition), signature))
        labels = np.arange(len(X), dtype=int) % int(params.get("k", 3))
        return AlgorithmResult(
            labels=labels,
            model_state={"backend": "partition-spy", "rounds": 1},
            runtime_sec=0.001,
        )


def test_run_request_accepts_arbitrary_algorithm_count() -> None:
    RunRequest(
        mode="local",
        dataset_name="iris",
        algorithms=("a", "b", "c", "d"),
    ).validate()

    with pytest.raises(ValueError, match="At least two"):
        RunRequest(mode="local", dataset_name="iris", algorithms=("a",)).validate()

    with pytest.raises(ValueError, match="unique"):
        RunRequest(
            mode="local",
            dataset_name="iris",
            algorithms=("a", "b", "a"),
        ).validate()


def test_local_multi_algorithm_comparison_returns_all_results(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    algorithms = ("kmeans", "gmm", "agglomerative", "dbscan")

    report = service.compare(
        RunRequest(
            mode="local",
            dataset_name="iris",
            algorithms=algorithms,
            seed=42,
        )
    )

    assert tuple(result.algorithm for result in report.results) == algorithms
    assert len(report.results) == 4
    assert report.partition is None


def test_federated_multi_algorithm_run_reuses_exact_same_partition(tmp_path: Path) -> None:
    seen: list[tuple[int, tuple[tuple[int, ...], ...]]] = []
    registry = AlgorithmRegistry()
    names = tuple(f"spy_{index}" for index in range(4))
    for name in names:
        registry.register(PartitionSpyAlgorithm(name, seen))

    service = ComparisonService(
        algorithms=registry,
        history_store=HistoryStore(tmp_path / "history"),
    )
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=names,
            seed=42,
            num_clients=5,
            partition_mode="iid",
            target_clusters=3,
        )
    )

    assert len(report.results) == 4
    assert report.partition is not None
    assert len(seen) == 4
    # Strong guarantee: the same partition object is handed to every algorithm.
    assert len({partition_id for partition_id, _ in seen}) == 1
    # And the actual client indices are byte-for-byte/equivalently identical.
    assert len({signature for _, signature in seen}) == 1
    assert sum(report.partition.client_sample_counts) == 150
    assert any(
        "Partition подготовлен один раз" in line for line in report.log_lines
    )
