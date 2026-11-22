from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from clustering_eval.algorithms.registry import AlgorithmRegistry
from clustering_eval.application import ComparisonService, HistoryQueryService, RunRequest
from clustering_eval.application.compute import JobExecutionError, assemble_report, execute_one
from clustering_eval.experiments.prepared import build_inputs
from clustering_eval.experiments.prepared_plan import select_inputs
from clustering_eval.experiments.series_plan import resolve_document
from clustering_eval.results import HistoryStore


def _plan(tmp_path: Path, scenario: dict):
    source = "a" * 64
    plan = resolve_document({
        "format": "pyclusteval.plan.v1", "campaign": {"name": "test"},
        "datasets": {"data": {"provider": "registry", "name": "iris"}},
        "scenarios": {"example": scenario},
        "series": [{"name": "example", "dataset": "data", "seed": 17, "scenarios": ["example"]}],
    }, source_id=source, base_dir=tmp_path)
    selected = select_inputs(plan, plan["comparisons"][0]["comparison_id"], base_dir=tmp_path)
    return build_inputs(**selected)


def test_grouped_grid_runs_one_member_and_assembles_observed_results(tmp_path):
    prepared = _plan(tmp_path, {"mode": "local", "algorithms": ["kmeans"],
                                "grid": {"kmeans": {"k": [2, 4]}}})
    jobs = prepared.jobs
    first = execute_one(prepared, jobs[0]["job_id"])
    second = execute_one(prepared, jobs[1]["job_id"])
    assert first.model_state["centers"] != second.model_state["centers"]
    for index, result in enumerate((first, second)):
        assert len(set(result.labels.tolist())) == (2, 4)[index]
        assert result.report.history == []
        assert result.report.model_state["execution"]["job_id"] == jobs[index]["job_id"]
        assert result.started_at.utcoffset().total_seconds() == result.finished_at.utcoffset().total_seconds() == 0
        assert result.started_at <= result.finished_at
    single = assemble_report(prepared, [second])
    assert single.results == [second.report]
    assert single.started_at == second.started_at
    assert single.to_dict()["request"]["algorithms"] == ("kmeans",)
    assert "num_clients" not in single.to_dict()["request"]
    with pytest.raises(ValueError, match="Repeated job"):
        assemble_report(prepared, [first, first])
    report = assemble_report(prepared, [second, first])
    assert report.started_at == first.started_at
    assert report.finished_at == second.finished_at
    directory = HistoryStore(tmp_path).save(report)
    loaded = HistoryQueryService(tmp_path).get_experiment(directory.name)
    assert len(loaded.results) == 2
    assert loaded.results[1].communication_bytes == 0


def test_refuse_unverified_lifecycle_at_adapter_boundary(tmp_path):
    source = "a" * 64
    prepared = _plan(tmp_path, {"mode": "local", "algorithms": ["kmeans"]})
    for profile in ("persistent_worker", {"lifecycle": "warm"}):
        jobs = deepcopy(prepared.jobs)
        jobs[0]["execution_profile"] = profile
        from_worker = build_inputs(X=prepared.X_raw, y=prepared.y, dataset=prepared.dataset,
                                   comparison=prepared.comparison, jobs=jobs, source_id=source)
        with pytest.raises(JobExecutionError, match="Unverified backend/lifecycle"):
            execute_one(from_worker, jobs[0]["job_id"])


def test_gui_unknown_measurement_and_degenerate_success_survive_history(tmp_path):
    class RawLabels:
        is_federated = False
        def __init__(self, name):
            self.name = name
        def run(self, X, partition, params, seed):
            return np.full(len(X), -1, dtype=int)

    registry = AlgorithmRegistry()
    for name in ("first", "second"):
        registry.register(RawLabels(name))
    service = ComparisonService(algorithms=registry, history_store=HistoryStore(tmp_path))
    report = service.compare(RunRequest(mode="local", dataset_name="iris", algorithms=("first", "second")))
    row = report.results[0]
    assert row.communication_bytes is None
    assert row.model_state["diagnostics"]["runtime_reported_by_algorithm_sec"] is None
    assert row.model_state["execution"]["runtime_source"] == "measured_call"
    loaded = HistoryQueryService(tmp_path).get_experiment(report.history_directory.name).results[0]
    assert loaded.history == []
    assert loaded.silhouette is None
    assert loaded.communication_bytes is None
    assert loaded.model_state["diagnostics"]["noise_fraction"] == 1.

def test_gui_dataset_metadata_preserves_native_history_types(tmp_path):
    from clustering_eval.datasets.registry import default_registry

    registry = default_registry()
    dataset = registry.load("iris")
    data_path = Path("fixtures") / "iris.csv"
    dataset.metadata.update(class_count=np.int64(3), counts=np.array([50, 50, 50]),
                            provenance={"files": [data_path]})
    registry.register("iris-with-metadata", lambda _: dataset)
    service = ComparisonService(datasets=registry, history_store=HistoryStore(tmp_path))
    report = service.compare(RunRequest(mode="local", dataset_name="iris-with-metadata",
                                        algorithms=("kmeans", "agglomerative")))
    stored = HistoryQueryService(tmp_path).get_experiment(report.history_directory.name)
    metadata = stored.results[0].model_state["benchmark"]["dataset_source_metadata"]
    assert metadata["class_count"] == 3
    assert metadata["counts"] == [50, 50, 50]
    assert metadata["provenance"]["files"] == [str(data_path)]

@pytest.mark.parametrize("algorithm", ["fed_fuzzy_cmeans_flower", "fed_gmm_diag_flower"])
def test_paper_flower_stopping_uses_bound_scenario_tolerance(tmp_path, algorithm):
    from clustering_eval.application.compute_params import run_parameters

    prepared = _plan(tmp_path, {"mode": "federated", "algorithms": [algorithm],
                                "stopping_profile": "historical_paper", "tol": 0.3})
    params, _ = run_parameters(prepared, prepared.jobs[0], prepared.X_eval)
    assert params["tol"] == 0.3
    assert params["_stopping_profile"] == "historical_paper"
    with pytest.raises(JobExecutionError, match="Unverified backend/lifecycle"):
        execute_one(prepared, prepared.jobs[0]["job_id"])

def test_object_label_identity_tracks_values_across_loads(tmp_path):
    from sklearn.datasets import load_iris

    X, y = load_iris(return_X_y=True)
    class Strings:
        changed = False
        def load(self, name):
            labels = np.array([f"class-{number}" for number in y], dtype=object)
            if self.changed:
                labels[0] = "class-1"
            return X, labels

    data = Strings()
    service = ComparisonService(datasets=data, history_store=HistoryStore(tmp_path))
    request = RunRequest(mode="local", dataset_name="iris-strings", algorithms=("kmeans", "agglomerative"))
    first = service.prepare(request)
    second = service.prepare(request)
    assert first.dataset["dataset_id"] == second.dataset["dataset_id"]
    assert first.comparison["comparison_id"] == second.comparison["comparison_id"]
    data.changed = True
    changed = service.prepare(request)
    assert changed.dataset["dataset_id"] != first.dataset["dataset_id"]

def test_gui_records_inputs_before_adapter_mutates_its_arguments(tmp_path):
    from clustering_eval.metrics.diagnostics import array_fingerprint

    observed = []

    class InPlace:
        is_federated = False
        input_preprocessing = "raw"
        def __init__(self, name):
            self.name = name
        def run(self, X, partition, params, seed):
            observed.append(array_fingerprint(X, length=64))
            X -= X.min(axis=0)
            params["nested"]["used"].append("adapter change")
            return np.zeros(len(X), dtype=int)

    registry = AlgorithmRegistry()
    for name in ("first", "second"):
        registry.register(InPlace(name))
    service = ComparisonService(algorithms=registry, history_store=HistoryStore(tmp_path))
    request = RunRequest(mode="local", dataset_name="iris", algorithms=("first", "second"),
                         algorithm_params={"nested": {"used": ["caller"]}})
    report = service.compare(request)
    assert observed[0] == observed[1]
    for row in report.results:
        benchmark = row.model_state["benchmark"]
        assert benchmark["algorithm_input_hash"] == observed[0]
        assert benchmark["effective_params"]["nested"]["used"] == ["caller"]


def test_gui_rejects_replacement_before_invoking_private_adapter(tmp_path):
    from clustering_eval.algorithms.registry import default_registry

    registry = default_registry()
    service = ComparisonService(algorithms=registry, history_store=HistoryStore(tmp_path))
    prepared = service.prepare(RunRequest(mode="federated", dataset_name="iris",
                               algorithms=("fed_kmeans_numpy", "fed_gmm_diag_numpy"),
                               privacy_mode="gaussian_dp_aggregate"))
    called = []
    class Replacement:
        is_federated = True
        name = "fed_kmeans_numpy"
        def run(self, X, partition, params, seed):
            called.append(True)
            return np.zeros(len(X), dtype=int)
    registry.register(Replacement())
    with pytest.raises(JobExecutionError, match="adapter implementation changed") as exc:
        service.execute_one(prepared, prepared.jobs[0]["job_id"])
    assert called == []
    assert exc.value.provenance["aggregate_release_status"] == "not_started"
