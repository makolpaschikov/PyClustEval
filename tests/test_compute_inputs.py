"""Selected real PLAN inputs, scientific identity, partition and legacy controls."""
from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest
from sklearn.preprocessing import StandardScaler

from clustering_eval.experiments.plan_legacy import migrate_legacy
from clustering_eval.experiments.prepared import build_inputs
from clustering_eval.experiments.prepared_plan import select_inputs
from clustering_eval.experiments.series_plan import resolve_document


def ordinary(tmp_path, **controls):
    spec = dict(format="pyclusteval.plan.v1", campaign={"name": "tiny"},
                datasets={"data": {"provider": "npz", "name": "fixture", "path": "data.npz"}},
                scenarios={"fed": dict(mode="federated", algorithms=["fed_kmeans_numpy"],
                                       stopping_profile="current_gui", num_clients=3, rounds=4, **controls)},
                series=[dict(name=str(seed), dataset="data", seed=seed, scenarios=["fed"])
                        for seed in [17, 43]])
    rng = np.random.default_rng(792)
    X = rng.standard_normal((45, 2)).astype(np.float32)
    y = np.arange(len(X)) % 3
    np.savez(tmp_path / "data.npz", X=X, y=y)
    return resolve_document(spec, base_dir=tmp_path, source_id="a"*64), X, y


def test_two_benchmark_seeds_use_the_same_exact_fixed_input_and_separate_partitions(tmp_path):
    plan, X, y = ordinary(tmp_path, grid={"fed_kmeans_numpy": {"k": [2, 3]}})
    groups = [build_inputs(**select_inputs(plan, c["comparison_id"], base_dir=tmp_path))
              for c in plan["comparisons"]]
    for group in groups:
        assert group.X_raw.dtype == X.dtype
        np.testing.assert_array_equal(group.X_raw, X)
        np.testing.assert_array_equal(group.y, y)
        np.testing.assert_array_equal(group.X_eval, StandardScaler().fit_transform(X.astype(float)))
        np.testing.assert_array_equal(np.sort(np.concatenate(group.partition)), np.arange(len(X)))
        assert len(group.schedule) == 4 and len(group.jobs) == 2
        with pytest.raises(TypeError, match="read-only"):
            group.partition.clear()
        with pytest.raises(ValueError):
            group.partition[0][0] = 4
    groups[0].jobs[0]["effective_params"]["k"] += 1
    with pytest.raises(ValueError, match="records changed"):
        groups[0].validate_bindings()
    assert groups[0].fingerprints["raw"] == groups[1].fingerprints["raw"]
    assert groups[0].fingerprints["partition"] != groups[1].fingerprints["partition"]


def test_changed_plan_dataset_and_unbound_job_fields_are_detected(tmp_path):
    plan, X, y = ordinary(tmp_path)
    key = plan["comparisons"][0]["comparison_id"]
    changed = deepcopy(plan)
    changed["jobs"][0]["preprocessing"] = "raw"
    with pytest.raises(ValueError, match="jobs"):
        select_inputs(changed, key, base_dir=tmp_path)
    changed = deepcopy(plan)
    changed["comparisons"][0]["protocol"]["stopping_profile"] = "historical_paper"
    with pytest.raises(ValueError, match="comparison"):
        select_inputs(changed, key, base_dir=tmp_path)
    np.savez(tmp_path / "data.npz", X=X[::-1], y=y[::-1])
    with pytest.raises(ValueError, match="dataset"):
        select_inputs(plan, key, base_dir=tmp_path)


def test_legacy_local_uses_generated_data_seed_and_a_real_partition(tmp_path):
    old = dict(experiment={"seeds": [17, 43]}, datasets=[{"name": "blobs", "params": {"n_samples": 36}}],
               algorithms=[{"name": "kmeans", "params": {"n_clusters": 2}}],
               partitioning={"clients": [3]}, metrics=["ari"])
    spec = migrate_legacy(old, plan_dir=tmp_path, legacy_cwd=tmp_path)
    plan = resolve_document(spec, base_dir=tmp_path, source_id="a"*64)
    groups = [build_inputs(**select_inputs(plan, cmp["comparison_id"], base_dir=tmp_path))
              for cmp in plan["comparisons"]]
    assert groups[0].fingerprints["raw"] != groups[1].fingerprints["raw"]
    for group in groups:
        assert len(group.partition) == 3 and group.schedule == []
        assert group.comparison["protocol"]["metrics"] == ["ari"]
        assert group.jobs[0]["effective_params"]["n_clusters"] == 2
        assert group.dataset["params"]["random_state"] == group.comparison["seed"]
