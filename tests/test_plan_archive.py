"""Bounded regression checks for joins within the archived scientific profile."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

import numpy as np
import pytest

from clustering_eval.datasets.partitioning import partition_fingerprint
from clustering_eval.experiments.archive_inputs import ArchiveInputs, partitions_inputs
from clustering_eval.experiments.archive_protocol import resolve_series


def comparison_fixture():
    algorithms = ["Adapted FKDC", "Adapted FKM"]
    definition = dict(series="sample", seed=17, dataset_name="dry_bean", num_clients=2,
                      rounds=2, tol=1e-4, max_iter=300, n_classes=2, dp_delta=1e-5, dp_clip_norm=4)
    request = dict(mode="federated", dataset_name="dry_bean", seed=17, algorithms=algorithms, num_clients=2,
                   rounds=2, tol=1e-4, max_iter=300, density_min_samples=5, target_clusters=2,
                   cluster_count_mode="known_k", min_samples_per_client=3, labels_per_client=2,
                   partition_mode="iid", dirichlet_alpha=.5, participation_rate=1., dropout_rate=0.,
                   privacy_mode="gaussian_dp_aggregate", dp_epsilon=1., dp_delta=1e-5,
                   dp_clip_norm=4., algorithm_params={}, algorithm_params_by_name={})
    schedule = [dict(round=n, selected_clients=[0, 1], successful_clients=[0, 1], dropped_clients=[])
                for n in [1, 2]]
    plan, runs = [], []
    for i, name in enumerate(algorithms):
        job = dict(series="sample", scenario="dp1", id=f"dp1_{i}", algorithm=name,
                   seed=17, partition="iid", participation=1., dropout=0., epsilon=1.)
        params = dict(k=2, n_clusters=2, rounds=2, tol=1e-4, max_iter=300, density_min_samples=5)
        request["algorithm_params_by_name"][name] = params.copy()
        params["dp_aggregate"] = dict(enabled=True, kind="kmeans", budgeted_rounds=i+1, epsilon_total=1.,
                                      delta_total=1e-5, clip_norm=4.)
        params["participation_schedule"] = deepcopy(schedule)
        runs.append(dict(job=job.copy(), params=params, schedule=deepcopy(schedule), status="ok",
                         client_sizes=[3,3], partition_hash="example", input_shape=[6,2],
                         preprocessing="clipped", backend="author-server DP proxy", display_algorithm=name+" [DP proxy]"))
        plan.append(job)
    report = dict(format="pyclusteval.benchmark-series.v1", series="sample", seed=17,
                  dataset_name="dry_bean", protocol=definition, runs=list(reversed(runs)),
                  experiments=[dict(scenario="dp1", request=request)], run_count=2, comparison_count=1)
    parts = {"iid": dict(mode="iid", alpha=.5, sizes=[3,3], fingerprint="example")}
    dataset = dict(name="dry_bean", dataset_id="data", n_samples=6, n_features=2)
    return definition, plan, parts, report, dataset, "sample", {"worker_sha256":"worker"}, "new-source"


def test_join_uses_historical_run_ids_and_preserves_shared_inputs():
    fixture = comparison_fixture()
    comparisons, jobs, templates = resolve_series(*fixture)
    assert [job["run_id"] for job in jobs] == ["dp1_0", "dp1_1"]
    assert [job["effective_params"]["dp_aggregate"]["budgeted_rounds"] for job in jobs] == [1, 2]
    assert all("participation_schedule" not in j["effective_params"] for j in jobs)
    common, = comparisons
    assert common["protocol"]["participation_schedule"] == fixture[3]["runs"][0]["schedule"]
    assert common["protocol"]["stopping_profile"] == templates["dp1"]["stopping_profile"] == "historical_paper"
    assert all(job["comparison_id"] == common["comparison_id"] for job in jobs)
    assert [job["job_id"] for job in resolve_series(*fixture[:-1], "different-code")[1]] != [j["job_id"] for j in jobs]


def test_inconsistent_schedule_or_budget_names_the_affected_run():
    fixture = comparison_fixture()
    run = fixture[3]["runs"][0]  # second planned run, found by ID
    run["params"]["dp_aggregate"]["budgeted_rounds"] = 1
    with pytest.raises(ValueError, match=r"sample.dp1_1.dp_aggregate"):
        resolve_series(*fixture)
    run["params"]["dp_aggregate"]["budgeted_rounds"] = 2
    run["params"]["participation_schedule"][0]["selected_clients"] = []
    with pytest.raises(ValueError, match="dp1_1: schedule mismatch"):
        resolve_series(*fixture)


def test_partition_checks_origins_against_y_and_not_just_total_counts():
    groups = [[0,1,2], [3,4,5]]
    y = np.array([0,0,0,1,1,1])
    part = dict(mode="iid", alpha=.5, indices=groups, sizes=[3,3], class_counts=[{"0":3},{"1":3}],
                fingerprint=partition_fingerprint(groups))
    result = partitions_inputs({"iid":part}, y, {"num_clients":2}, "partitions")["iid"]
    assert result["fingerprint"] == part["fingerprint"]
    part["class_counts"].reverse()
    with pytest.raises(ValueError, match="class counts"):
        partitions_inputs({"iid":part}, y, {"num_clients":2}, "partitions")
    part["indices"][0][-1] = 5
    with pytest.raises(ValueError, match="disjoint cover"):
        partitions_inputs({"iid":part}, y, {"num_clients":2}, "partitions")


def test_damaged_manifest_rejected_before_opening_any_dataset(tmp_path):
    original = b'{"format":"example"}'
    (tmp_path/"checksums.json").write_text(json.dumps({"algorithm":"sha256", "files":[
        {"path":"manifest.json", "sha256":sha256(original).hexdigest(), "bytes":len(original)}]}))
    (tmp_path/"manifest.json").write_bytes(original.replace(b"example", b"changed"))
    with pytest.raises(ValueError, match=r"manifest.json: size or SHA-256 mismatch"):
        ArchiveInputs(tmp_path)
