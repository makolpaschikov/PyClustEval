from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from clustering_eval.experiments.plan_identity import scientific_id
from clustering_eval.experiments.plan_io import read_document
from clustering_eval.experiments.plan_legacy import migrate_legacy
from clustering_eval.experiments.series_plan import resolve_document


SOURCE = "a" * 64


def plan() -> dict:
    return {"format": "pyclusteval.plan.v1", "campaign": {"name": "trial"},
            "datasets": {"data": {"provider": "registry", "name": "iris"}},
            "scenarios": {"baseline": {"mode": "local", "algorithms": ["kmeans"]}},
            "series": [{"name": "first", "dataset": "data", "seed": 17, "scenarios": ["baseline"]}]}


@pytest.mark.parametrize(("suffix", "content", "error"), [
    ("yaml", "data:\n  n: 2\n  n: 3\n", "duplicate key"),
    ("json", '{"data":{"n":2,"n":3}}', "duplicate key"),
    ("yaml", "v: .nan", "finite JSON value"),
    ("json", '{"v": 1e999}', "finite JSON value"),
    ("yaml", "data: 2021-01-02", "finite JSON value"),
    ("yaml", "v: &x [*x]", "aliases"),
])
def test_syntax_is_checked_before_model_resolution(tmp_path, suffix, content, error):
    src = tmp_path / ("plan." + suffix)
    src.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        read_document(src)


def test_hashes_are_versioned_and_ignore_object_order():
    assert scientific_id("a", {"x": 1, "y": [2, 3]}) == scientific_id("a", {"y": [2, 3], "x": 1})
    assert scientific_id("a", {"x": 1}) != scientific_id("b", {"x": 1})
    assert scientific_id("a", {"x": [1, 2]}) != scientific_id("a", {"x": [2, 1]})


def test_scientific_keys_survive_relocation_and_operational_changes(tmp_path):
    document = plan()
    source = tmp_path / "a.yaml"
    source.write_text(yaml.safe_dump(document), encoding="utf-8")
    moved = tmp_path / "moved folder"
    moved.mkdir()
    source2 = moved / "b.json"
    source2.write_text(json.dumps(document), encoding="utf-8")
    def resolve(path):
        return resolve_document(read_document(path), base_dir=path.parent, source_id=SOURCE)
    first, second = resolve(source), resolve(source2)
    assert first["counts"] == {"series": 1, "comparisons": 1, "jobs": 1}
    assert first["jobs"] == second["jobs"]
    assert first["campaign"]["output_dir"] != second["campaign"]["output_dir"]

    original = first["jobs"][0]["job_id"]
    for field, value in (("timeout_sec", 90), ("max_retries", 3)):
        changed = dict(document, execution={field: value})
        assert resolve_document(changed, base_dir=moved, source_id=SOURCE)["jobs"][0]["job_id"] == original
    for change in ("source", "seed", "profile", "data", "params"):
        changed = copy.deepcopy(document)
        source_id = SOURCE
        if change == "source":
            source_id = "b" * 64
        elif change == "seed":
            changed["series"][0]["seed"] += 1
        elif change == "profile":
            changed["execution"] = {"blas_threads": 2}
        elif change == "data":
            changed["datasets"]["data"]["name"] = "wine"
        else:
            changed["scenarios"]["baseline"]["algorithm_params_by_name"] = {"kmeans": {"n_init": 17}}
        assert resolve_document(changed, base_dir=moved, source_id=source_id)["jobs"][0]["job_id"] != original


def test_grid_expands_per_method_and_repeated_scientific_jobs_are_rejected(tmp_path):
    doc = plan()
    doc["scenarios"]["baseline"]["grid"] = {"kmeans": {"n_init": [2, 4]}}
    resolved = resolve_document(doc, base_dir=tmp_path, source_id=SOURCE)
    assert resolved["counts"]["jobs"] == 2 and resolved["counts"]["comparisons"] == 1
    assert [j["effective_params"]["n_init"] for j in resolved["jobs"]] == [2, 4]
    assert len({j["job_id"] for j in resolved["jobs"]}) == 2
    doc["series"].append(dict(doc["series"][0], name="renamed"))
    with pytest.raises(ValueError, match="duplicate"):
        resolve_document(doc, base_dir=tmp_path, source_id=SOURCE)


def test_legacy_grid_and_seed_policy_are_materialized(tmp_path):
    old = {"experiment": {"seeds": [17, 43]}, "datasets": [{"name": "blobs"}],
           "algorithms": [{"name": "kmeans", "params": {"n_init": [2, 4]}}]}
    source = migrate_legacy(old, plan_dir=tmp_path, legacy_cwd=tmp_path)
    assert len(source["legacy"]["jobs"]) == 4
    assert {d["params"]["random_state"] for d in source["datasets"].values()} == {17, 43}
    assert {j["preparation_seed_source"] for j in source["legacy"]["jobs"]} == {"benchmark_seed"}
    old["experiment"]["repetitions"] = 2
    with pytest.raises(ValueError, match="repetitions"):
        migrate_legacy(old, plan_dir=tmp_path, legacy_cwd=tmp_path)


def test_federated_stopping_profile_is_scientific_input(tmp_path):
    doc = plan()
    scenario = doc["scenarios"]["baseline"] = {"mode": "federated", "algorithms": ["fed_kmeans_numpy"],
                                              "num_clients": 5, "partition_mode": "iid"}
    with pytest.raises(ValueError, match="stopping_profile"):
        resolve_document(doc, base_dir=tmp_path, source_id=SOURCE)
    jobs = []
    for profile in ("current_gui", "historical_paper"):
        scenario["stopping_profile"] = profile
        resolved = resolve_document(doc, base_dir=tmp_path, source_id=SOURCE)
        assert resolved["comparisons"][0]["protocol"]["stopping_profile"] == profile
        jobs.append(resolved["jobs"][0]["job_id"])
    assert jobs[0] != jobs[1]


def test_input_dp_identity_tracks_other_variants_sharing_the_release(tmp_path):
    doc = plan()
    scenario = doc["scenarios"]["baseline"] = {
        "mode": "federated", "stopping_profile": "current_gui", "privacy_mode": "gaussian_dp",
        "algorithms": ["fed_kmeans_numpy", "fed_fuzzy_cmeans_numpy"], "num_clients": 5,
    }
    before = resolve_document(doc, base_dir=tmp_path, source_id=SOURCE)
    scenario["grid"] = {"fed_fuzzy_cmeans_numpy": {"fuzziness": [1.8, 2.2]}}
    after = resolve_document(doc, base_dir=tmp_path, source_id=SOURCE)
    assert before["jobs"][0]["algorithm"] == after["jobs"][0]["algorithm"] == "fed_kmeans_numpy"
    assert before["jobs"][0]["job_id"] != after["jobs"][0]["job_id"]


@pytest.mark.parametrize("clients", [1, 3])
def test_legacy_federated_preserves_round_budget_and_both_k_aliases(tmp_path, clients):
    old = {"datasets": [{"name": "iris"}], "algorithms": [
        {"name": "fed_kmeans_numpy", "params": {"rounds": 20, "k": 2, "n_clusters": 3}}],
        "partitioning": {"clients": [clients]}}
    source = migrate_legacy(old, plan_dir=tmp_path, legacy_cwd=tmp_path)
    resolved = resolve_document(source, base_dir=tmp_path, source_id=SOURCE)
    job, = resolved["jobs"]
    assert job["legacy_benchmark_k"] == 3
    assert {k: job["effective_params"][k] for k in ("rounds", "k", "n_clusters")} == {
        "rounds": 20, "k": 2, "n_clusters": 3}
    protocol = resolved["comparisons"][0]["protocol"]
    assert protocol["num_clients"] == clients and protocol["stopping_profile"] == "legacy_run"
    assert protocol["schedule"] == "legacy_adapter_default"


def test_legacy_local_still_requires_a_possible_client_partition(tmp_path):
    old = {"datasets": [{"name": "iris"}], "algorithms": [{"name": "kmeans"}],
           "partitioning": {"clients": [1], "modes": ["label_limited"]}}
    with pytest.raises(ValueError, match="cannot cover 3 classes"):
        resolve_document(migrate_legacy(old, plan_dir=tmp_path, legacy_cwd=tmp_path),
                         base_dir=tmp_path, source_id=SOURCE)


def test_legacy_fkm_uses_server_capacity_and_real_alias_priority(tmp_path):
    params = {"k": 2, "n_clusters": 4, "drop": False}
    old = {"datasets": [{"name": "blobs", "params": {"n_samples": 150, "centers": 4, "cluster_std": 0}}],
           "algorithms": [{"name": "Adapted FKM", "params": params}],
           "partitioning": {"clients": [50]}}

    def resolve():
        source = migrate_legacy(old, plan_dir=tmp_path, legacy_cwd=tmp_path)
        return resolve_document(source, base_dir=tmp_path, source_id=SOURCE)

    # The old adapter reads n_clusters first, and its default drop_empty_clusters shadows drop.
    capacity = resolve()["jobs"][0]["first_round_capacity"]
    assert capacity["status"] == "requires_compute_check"
    assert capacity["required_k"] == 4 and capacity["upper_bound"] == 50
    params["drop_empty_clusters"] = False
    with pytest.raises(ValueError, match="local update"):
        resolve()

    old["datasets"] = [{"name": "iris"}]
    old["partitioning"]["clients"] = [1]
    params.update(n_clusters=76, drop_empty_clusters=True)
    with pytest.raises(ValueError, match="initial server needs >= 76 centers"):
        resolve()
