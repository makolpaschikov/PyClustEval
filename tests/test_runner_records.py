from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import numpy as np
import pytest

from clustering_eval.application import compute
from clustering_eval.experiments import prepared, runner_records, runner_worker
from clustering_eval.experiments.series_plan import checkout_source_id, resolve_document
from clustering_eval.results.history_store import _strict_json_value


@pytest.fixture(scope="module")
def source():
    return checkout_source_id()


def comparison(tmp_path, source, *, mode="local", privacy="none"):
    name = "agglomerative" if mode == "local" else "fed_kmeans_numpy"
    scenario = {"mode": mode, "algorithms": [name], "privacy_mode": privacy}
    if mode == "federated":
        scenario.update(stopping_profile="current_gui", num_clients=3, rounds=2)
    doc = {"format": "pyclusteval.plan.v1", "campaign": {"name": "small"},
           "datasets": {"iris": {"provider": "registry", "name": "iris"}},
           "scenarios": {"small": scenario},
           "series": [{"name": "series", "dataset": "iris", "scenarios": ["small"], "seed": 17}]}
    plan = resolve_document(doc, base_dir=tmp_path, source_id=source)
    comparison_id = plan["comparisons"][0]["comparison_id"]
    descriptor = prepared.prepare(plan, comparison_id, tmp_path / "inputs", source_id=source, base_dir=tmp_path)
    return descriptor, prepared.reopen(descriptor, source_id=source, comparison_id=comparison_id)


def attempt(tmp_path, inputs):
    job = inputs.jobs[0]
    req = {"attempt_id": uuid4().hex, "job_id": job["job_id"], "comparison_id": job["comparison_id"],
           "source_id": inputs.source_id, "dataset_id": inputs.dataset["dataset_id"], "job": job,
           "n_samples": len(inputs.X_raw), "fingerprints": inputs.fingerprints,
           "privacy_mode": inputs.comparison["protocol"]["privacy_mode"],
           "input_release_id": inputs.privacy_report.get("release_id")}
    for name, key in (("inputs/prepared.json", "descriptor_sha256"), ("inputs.reservation", "reservation_sha256")):
        req[key] = sha256((tmp_path / name).read_bytes()).hexdigest()
    folder = tmp_path / req["attempt_id"]
    folder.mkdir()
    (folder / "request.json").write_text(json.dumps(req), encoding="utf-8")
    return folder, req


def worker(folder, descriptor):
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    return subprocess.run([sys.executable, "-B", "-m", runner_worker.__name__, str(folder), str(descriptor)],
                          cwd=Path(__file__).resolve().parents[1], env=env,
                          capture_output=True, text=True, timeout=45)


def test_candidate_preserves_native_result_and_checks_self_consistency(tmp_path, source):
    descriptor, inputs = comparison(tmp_path, source)
    folder, req = attempt(tmp_path, inputs)
    execution = compute.execute_one(inputs, req["job_id"])
    info = {"pid": os.getpid(), "started_at_utc": execution.started_at.isoformat(),
            "finished_compute_at_utc": execution.finished_at.isoformat()}
    with pytest.raises(FileNotFoundError):
        runner_records.read_candidate(folder / "uncreated", req)
    assert runner_records.read_failure(folder / "uncreated", req) is None
    with pytest.raises(FileNotFoundError):
        runner_records.read_candidate(folder, req)
    runner_records.publish_success(folder, req, execution, info)
    accepted = runner_records.read_candidate(folder, req)
    assert accepted["compute_attempt_id"] == execution.attempt_id != req["attempt_id"]
    assert accepted["report"] == _strict_json_value(asdict(execution.report))
    assert accepted["report"]["history"] == []
    assert accepted["model_state"] == _strict_json_value(execution.model_state)
    labels_path = folder / accepted["labels"]["path"]
    labels = np.load(labels_path, allow_pickle=False)
    assert labels.dtype == execution.labels.dtype
    assert labels.tobytes() == execution.labels.tobytes()
    assert accepted["source_run"]["run_id"] == inputs.jobs[0]["run_id"]
    assert accepted == runner_records.read_candidate(folder, req, accepted_hash=accepted["manifest_sha256"])

    with pytest.raises(ValueError):
        runner_records.read_candidate(folder, dict(req, job_id="wrong"))
    result_path = folder / accepted["result"]["path"]
    result = json.loads(result_path.read_bytes())
    result["report"]["model_state"]["execution"]["source_id"] = "wrong"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        runner_records.read_candidate(folder, req)
    marker = folder / runner_records.CANDIDATE
    manifest = json.loads(marker.read_bytes())
    manifest["result"]["sha256"] = sha256(result_path.read_bytes()).hexdigest()
    marker.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="source_id"):
        runner_records.read_candidate(folder, req)
    with pytest.raises(ValueError, match="Accepted candidate checksum"):
        runner_records.read_candidate(folder, req, accepted_hash=accepted["manifest_sha256"])
    labels_path.unlink()
    with pytest.raises(ValueError, match="Incomplete"):
        runner_records.read_candidate(folder, req)
    manifest["labels"]["path"] = "../other.npy"
    marker.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="path"):
        runner_records.read_candidate(folder, req)


def test_distinct_real_workers_reopen_one_shared_release(tmp_path, source):
    descriptor, inputs = comparison(tmp_path, source, mode="federated", privacy="gaussian_dp")
    records = []
    for _ in range(2):
        folder, req = attempt(tmp_path, inputs)
        completed = worker(folder, descriptor)
        assert completed.returncode == 0, completed.stderr
        records.append(runner_records.read_candidate(folder, req))
    first, second = records
    assert first["attempt_id"] != second["attempt_id"]
    assert first["compute_attempt_id"] != second["compute_attempt_id"]
    assert first["input_release_id"] == second["input_release_id"] == inputs.privacy_report["release_id"]
    assert first["fingerprints"] == second["fingerprints"] == inputs.fingerprints
    assert second["worker"]["thread_environment"]["MKL_NUM_THREADS"] == "1"
    pools = [item for item in second["worker"]["thread_pools_at_observation"] if item["user_api"] == "blas"]
    assert pools and all(item["num_threads"] == 1 for item in pools)
    assert second["worker"]["pid"] != os.getpid()
    assert worker(folder, descriptor).returncode == 4
    assert runner_records.read_candidate(folder, req)["manifest_sha256"] == second["manifest_sha256"]


def test_failure_keeps_indeterminate_aggregate_draw_before_later_success(tmp_path, source, monkeypatch):
    descriptor, inputs = comparison(tmp_path, source, mode="federated", privacy="gaussian_dp_aggregate")
    folder, req = attempt(tmp_path, inputs)
    def failed_call(*args, **kwargs):
        raise RuntimeError("interrupted after entering private adapter")
    with monkeypatch.context() as patch:
        patch.setattr(compute, "_invoke_algorithm", failed_call)
        assert runner_worker.run_attempt(folder, descriptor) == 1
    failure = runner_records.read_failure(folder, req)
    assert failure["exit_code"] == 1
    assert failure["aggregate_release_status"] == "unknown"
    assert failure["provenance"]["aggregate_release_status"] == "unknown"
    assert "RuntimeError: interrupted after entering private adapter" in failure["traceback"]
    with pytest.raises(FileNotFoundError):
        runner_records.read_candidate(folder, req)
    folder2, req2 = attempt(tmp_path, inputs)
    assert runner_worker.run_attempt(folder2, descriptor) == 0
    success = runner_records.read_candidate(folder2, req2)
    observed = success["report"]["model_state"]["execution"]
    assert observed["aggregate_release_status"] == "observed"
    assert observed["attempt_id"] != failure["provenance"]["attempt_id"]
    assert runner_records.read_failure(folder, req) == failure
    assert runner_records.read_failure(folder2, req2) is None


@pytest.mark.parametrize("key", ["fingerprints", "reservation_sha256", "descriptor_sha256"])
def test_worker_rejects_request_mismatching_actual_preparation(tmp_path, source, key):
    descriptor, inputs = comparison(tmp_path, source)
    folder, req = attempt(tmp_path, inputs)
    req[key] = dict(req[key], raw="different") if key == "fingerprints" else "e" * 64
    (folder / "request.json").write_text(json.dumps(req), encoding="utf-8")
    assert runner_worker.run_attempt(folder, descriptor) == 4
    failure = runner_records.read_failure(folder, req)
    assert failure["exit_code"] == 4
    assert ("fingerprints" if key == "fingerprints" else "preparation file") in failure["message"]
    assert failure["provenance"] is None
    with pytest.raises(FileNotFoundError):
        runner_records.read_candidate(folder, req)
