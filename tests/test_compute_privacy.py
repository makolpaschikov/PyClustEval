from __future__ import annotations

import pytest

from clustering_eval.algorithms.registry import default_registry
from clustering_eval.application import ComparisonService, RunRequest
from clustering_eval.application.compute import JobExecutionError, assemble_report
from clustering_eval.results import HistoryStore


def _request(mode, **overrides):
    return RunRequest(mode="federated", dataset_name="iris", seed=17, rounds=3,
                      algorithms=("fed_kmeans_numpy", "fed_gmm_diag_numpy"), privacy_mode=mode, **overrides)


def test_shared_input_release_does_not_compose_or_mix(tmp_path):
    service = ComparisonService(history_store=HistoryStore(tmp_path))
    prepared = service.prepare(_request("gaussian_dp"))
    repeated = service.prepare(_request("gaussian_dp"))
    a, b = [service.execute_one(prepared, j["job_id"]) for j in prepared.jobs]
    c = service.execute_one(repeated, repeated.jobs[1]["job_id"])
    assert a.input_release_id == b.input_release_id
    assert c.input_release_id != a.input_release_id
    assert a.fingerprints["train"] == b.fingerprints["train"]
    assert assemble_report(prepared, [a, b]).privacy_report["release_id"] == a.input_release_id
    with pytest.raises(ValueError, match="different prepared inputs"):
        assemble_report(prepared, [a, c])


def test_aggregate_query_failure_retains_uncertainty_and_never_reinvokes(tmp_path):
    registry = default_registry()
    adapter = registry.get("fed_kmeans_numpy")
    calls = []
    def fail(X, partition, params, seed):
        calls.append(params)
        raise TypeError("failure in a private adapter")
    adapter.run = fail
    service = ComparisonService(algorithms=registry, history_store=HistoryStore(tmp_path))
    prepared = service.prepare(_request("gaussian_dp_aggregate", dp_clip_norm=4.))
    with pytest.raises(JobExecutionError, match="private adapter") as caught:
        service.execute_one(prepared, prepared.jobs[0]["job_id"])
    assert len(calls) == 1
    assert caught.value.provenance["aggregate_release_status"] == "unknown"
    assert caught.value.provenance["attempt_id"]
    successful = service.execute_one(prepared, prepared.jobs[1]["job_id"])
    report = assemble_report(prepared, [successful])
    assert report.privacy_report["scope"] == "included_successful_attempts_only"
    assert report.privacy_report["upper_bound_epsilon_across_selected_algorithms"] == 5.


def test_gui_calibrates_to_original_common_budget(tmp_path):
    service = ComparisonService(history_store=HistoryStore(tmp_path))
    capped = service.prepare(_request("gaussian_dp_aggregate",
                             algorithm_params_by_name={"fed_kmeans_numpy": {"rounds": 1}}))
    run = service.execute_one(capped, capped.jobs[0]["job_id"])
    assert run.report.rounds == 1
    assert run.report.model_state["benchmark"]["effective_params"]["dp_aggregate"]["budgeted_rounds"] == 3
    assert run.report.model_state["execution"]["joint_queries"] == 1
    with pytest.raises(ValueError, match="calibrated GUI round budget"):
        service.prepare(_request("gaussian_dp_aggregate",
                        algorithm_params_by_name={"fed_kmeans_numpy": {"rounds": 4}}))

def test_custom_adapter_cannot_supply_evidence_for_an_aggregate_bound(tmp_path):
    import numpy as np
    from clustering_eval.algorithms.base import AlgorithmResult

    class Custom:
        name = "fed_kmeans_numpy"
        is_federated = True
        input_preprocessing = "standard"
        def run(self, X, partition, params, seed):
            return AlgorithmResult(labels=np.arange(len(X)) % 3,
                                   model_state={"backend": "numpy-federated"}, history=[{"round": 1}])

    registry = default_registry()
    registry.register(Custom())
    service = ComparisonService(algorithms=registry, history_store=HistoryStore(tmp_path))
    prepared = service.prepare(_request("gaussian_dp_aggregate"))
    custom, known = [service.execute_one(prepared, job["job_id"]) for job in prepared.jobs]
    assert custom.report.model_state["execution"]["joint_queries"] is None
    assert known.report.model_state["execution"]["joint_queries"] >= 1
    for summary in (custom.report.model_state["benchmark"]["privacy_report"],
                    assemble_report(prepared, [custom, known]).privacy_report):
        assert summary["aggregate_release_status"] == "unknown"
        assert summary["upper_bound_epsilon_across_selected_algorithms"] is None
        assert summary["upper_bound_delta_across_selected_algorithms"] is None
        assert summary["per_algorithm_privacy_budgets_compose"] is None
        assert "mechanism" not in summary
    assert assemble_report(prepared, [known]).privacy_report["upper_bound_epsilon_across_selected_algorithms"] == 5.
