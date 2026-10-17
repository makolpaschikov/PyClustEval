from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import numpy as np
from sklearn.datasets import load_iris

from clustering_eval.algorithms.base import AlgorithmResult, ClusteringAlgorithm
from clustering_eval.algorithms.registry import AlgorithmRegistry
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.federated.environment import make_participation_schedule
from clustering_eval.privacy.gaussian import apply_gaussian_input_dp, analytic_gaussian_sigma
from clustering_eval.results import HistoryStore


class XSpyAlgorithm(ClusteringAlgorithm):
    is_federated = True
    input_preprocessing = "raw"
    common_param_support = ("k", "seed")

    def __init__(self, name: str, seen: list[np.ndarray]) -> None:
        self.name = name
        self._seen = seen

    def run(self, X, partition, params, seed):
        self._seen.append(np.asarray(X, dtype=float).copy())
        k = int(params.get("k", 3))
        labels = np.arange(len(X), dtype=int) % k
        return AlgorithmResult(
            labels=labels,
            model_state={"backend": "x-spy", "rounds": 1},
            runtime_sec=0.001,
        )


def test_participation_schedule_is_deterministic_and_never_empty() -> None:
    schedule = make_participation_schedule(
        num_clients=5,
        rounds=8,
        participation_rate=0.6,
        dropout_rate=0.4,
        seed=42,
    )
    same = make_participation_schedule(
        num_clients=5,
        rounds=8,
        participation_rate=0.6,
        dropout_rate=0.4,
        seed=42,
    )
    assert schedule == same
    assert len(schedule) == 8
    for item in schedule:
        assert len(item["selected_clients"]) == 3
        assert 1 <= len(item["successful_clients"]) <= 3
        assert set(item["successful_clients"]).issubset(item["selected_clients"])
        assert set(item["dropped_clients"]).issubset(item["selected_clients"])
        assert set(item["successful_clients"]).isdisjoint(item["dropped_clients"])


def test_native_iterative_algorithms_consume_shared_round_schedule(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"),
            seed=7,
            num_clients=5,
            rounds=4,
            participation_rate=0.6,
            dropout_rate=0.25,
        )
    )
    assert report.partition is not None
    schedule = report.partition.round_schedule
    assert len(schedule) == 4
    for result in report.results:
        assert result.history
        for history_item in result.history:
            round_idx = int(history_item["round"]) - 1
            expected = schedule[round_idx]
            assert history_item["selected_clients"] == expected["selected_clients"]
            assert history_item["successful_clients"] == expected["successful_clients"]
            assert history_item["dropped_clients"] == expected["dropped_clients"]


def test_one_shot_adapted_algorithms_use_first_round_availability(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("Adapted HF_DBSCAN", "Adapted FKDC"),
            seed=11,
            num_clients=5,
            rounds=5,
            participation_rate=0.6,
            dropout_rate=0.0,
        )
    )
    assert report.partition is not None
    expected = report.partition.round_schedule[0]["successful_clients"]
    by_name = {result.algorithm: result for result in report.results}
    assert by_name["Adapted HF_DBSCAN"].model_state["selected_clients"] == expected
    assert by_name["Adapted FKDC"].model_state["participation"]["successful_clients"] == expected
    assert by_name["Adapted HF_DBSCAN"].rounds == 1
    assert by_name["Adapted FKDC"].rounds == 1



def test_flower_named_algorithms_are_not_rejected_by_shared_schedule(tmp_path: Path) -> None:
    """The application layer must not reject Flower adapters for Scenario 3.

    Real Flower adapters enforce the schedule client-side using the stable
    context partition-id.  This fake registry keeps the unit test independent
    from the optional Flower/Ray runtime.
    """
    seen: list[np.ndarray] = []
    registry = AlgorithmRegistry()
    registry.register(XSpyAlgorithm("fake_one_flower", seen))
    registry.register(XSpyAlgorithm("fake_two_flower", seen))
    service = ComparisonService(
        algorithms=registry,
        history_store=HistoryStore(tmp_path / "history"),
    )
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("fake_one_flower", "fake_two_flower"),
            seed=42,
            rounds=3,
            participation_rate=1.0,
            dropout_rate=0.8,
        )
    )
    assert report.partition is not None
    assert len(report.partition.round_schedule) == 3
    assert len(report.results) == 2


def test_analytic_gaussian_input_dp_is_deterministic_for_seed() -> None:
    X = load_iris().data.astype(float)
    sigma = analytic_gaussian_sigma(epsilon=5.0, delta=1e-5, sensitivity=2.0)
    assert sigma > 0
    first, first_report = apply_gaussian_input_dp(
        X, epsilon=5.0, delta=1e-5, clip_norm=1.0, seed=42
    )
    second, second_report = apply_gaussian_input_dp(
        X, epsilon=5.0, delta=1e-5, clip_norm=1.0, seed=42
    )
    other, _ = apply_gaussian_input_dp(
        X, epsilon=5.0, delta=1e-5, clip_norm=1.0, seed=43
    )
    assert np.allclose(first, second)
    assert not np.allclose(first, X)
    assert not np.allclose(first, other)
    assert first_report == second_report
    assert first_report["mode"] == "gaussian_dp"
    assert first_report["l2_sensitivity"] == 2.0


def test_gaussian_dp_matrix_is_shared_across_algorithms(tmp_path: Path) -> None:
    seen: list[np.ndarray] = []
    registry = AlgorithmRegistry()
    registry.register(XSpyAlgorithm("spy_a", seen))
    registry.register(XSpyAlgorithm("spy_b", seen))
    service = ComparisonService(
        algorithms=registry,
        history_store=HistoryStore(tmp_path / "history"),
    )
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("spy_a", "spy_b"),
            seed=42,
            privacy_mode="gaussian_dp",
            dp_epsilon=5.0,
            dp_delta=1e-5,
            dp_clip_norm=1.0,
        )
    )
    assert len(seen) == 2
    assert np.array_equal(seen[0], seen[1])
    assert not np.allclose(seen[0], load_iris().data)
    assert report.privacy_report["mode"] == "gaussian_dp"
    assert report.privacy_report["round_composition"]


def test_excel_export_contains_privacy_and_participation(tmp_path: Path) -> None:
    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="federated",
            dataset_name="iris",
            algorithms=("fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"),
            seed=42,
            rounds=3,
            participation_rate=0.8,
            dropout_rate=0.2,
            privacy_mode="gaussian_dp",
            dp_epsilon=5.0,
            dp_delta=1e-5,
            dp_clip_norm=1.0,
        )
    )
    output = tmp_path / "scenario_3_4.xlsx"
    service.export_excel(report, str(output))
    with ZipFile(output) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        assert "Privacy" in workbook_xml
        assert "Partition" in workbook_xml
        assert "Configuration" in workbook_xml
