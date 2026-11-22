from __future__ import annotations

import pytest

from clustering_eval.experiments.plan_protocol import resolve_scenario


IRIS = {"name": "iris", "n_samples": 150, "n_features": 4, "n_classes": 3}


def resolve(methods, *, mode="federated", data=IRIS, **fields):
    if mode == "federated":
        fields.setdefault("stopping_profile", "current_gui")
    return resolve_scenario({"mode": mode, "algorithms": methods, **fields},
                            dataset=data, seed=19, path="scenarios.trial")


def test_protocol_defaults_grid_and_deferred_computation():
    shared, jobs = resolve(["kmeans", "dbscan"], mode="local", cluster_count_mode="estimated_k",
        tuning_mode="unsupervised", grid={"kmeans": {"n_init":[2,4]}},
        algorithm_params_by_name={"kmeans":{"init":"random"}})
    assert shared["target_clusters"] is None and shared["cluster_count_source"] == "estimated_unlabeled_silhouette"
    assert [(j["algorithm"],j["backend"]) for j in jobs] == [("kmeans","local"),("kmeans","local"),("dbscan","local")]
    assert [j["effective_params"]["n_init"] for j in jobs[:2]] == [2,4]
    assert all(j["deferred"]["k"] and j["effective_params"]["k"] is None for j in jobs[:2])
    assert jobs[0]["parameter_sources"]["n_init"] == "grid"
    assert jobs[-1]["deferred"]["min_samples"]
    assert jobs[-1]["effective_params"]["min_samples"] == 5


def test_singleton_and_applicable_aliases_without_fake_peer():
    shared, jobs = resolve(["Adapted HF_DBSCAN"], algorithm_params_by_name={"Adapted HF_DBSCAN":{"MIN_POINTS":9}})
    assert shared["num_clients"] == 5 and shared["min_samples_per_client"] == 3
    assert shared["target_clusters"] == 3
    assert len(jobs) == 1 and jobs[0]["backend"] == "author-source-port"
    assert jobs[0]["effective_params"]["min_points"] == 9
    assert "density_min_samples" not in jobs[0]["effective_params"]
    assert jobs[0]["preprocessing"] == "minmax"
    _, (job,) = resolve(["fed_kmeans_numpy"], algorithm_params_by_name={"fed_kmeans_numpy":{"n_clusters":4}})
    assert job["effective_params"]["k"] == job["effective_params"]["n_clusters"] == 4


@pytest.mark.parametrize("methods,fields,error", [
    (["fed_kmeans_numpy"], {"participation_rate":True}, "participation_rate"),
    (["fed_kmeans_numpy"], {"dirichlet_alpha":float("inf")}, "dirichlet_alpha"),
    (["fed_kmeans_numpy"], {"num_clients":100}, "num_clients"),
    (["Adapted NN-FC"], {"min_samples_per_client":2}, "min_samples_per_client"),
    (["fed_kmeans_numpy"], {"privacy_mode":"gaussian_dp_aggregate","partition_mode":"label_limited"}, "partition_mode"),
    (["fed_kmeans_numpy"], {"privacy_mode":"gaussian_dp_aggregate","cluster_count_mode":"estimated_k"}, "cluster_count_mode"),
    (["fed_kmeans_numpy"], {"privacy_mode":"gaussian_dp_aggregate","dp_clip_norm":21}, "dp_clip_norm"),
    (["fed_kmeans_numpy"], {"algorithm_params_by_name":{"fed_kmeans_numpy":{"dp_aggregate":{}}}}, "dp_aggregate"),
    (["fed_kmeans_numpy"], {"algorithm_params_by_name":{"fed_kmeans_numpy":{"participation_schedule":[]}}}, "participation_schedule"),
    (["fed_kmeans_numpy"], {"algorithm_params_by_name":{"fed_kmeans_numpy":{"k":3,"n_clusters":4}}}, "alias"),
    (["fed_kmeans_numpy"], {"algorithm_params_by_name":{"fed_kmeans_numpy":{"k":[2,3]}}}, "integer"),
    (["fed_kmeans_numpy"], {"grid":{"fed_kmeans_numpy":{"rounds":[11]}}}, "rounds"),
    (["fed_fuzzy_cmeans_numpy"], {"algorithm_params_by_name":{"fed_fuzzy_cmeans_numpy":{"fuzziness":1}}}, "fuzziness"),
    (["kmeans"], {}, "algorithms"),
    (["unknown"], {}, "algorithms"),
])
def test_inadmissible_parameters(methods, fields, error):
    with pytest.raises(ValueError, match=error):
        resolve(methods, **fields)


def test_privacy_modes_keep_public_k_and_proxy_identity():
    shared, (job,) = resolve(["Adapted HF_DBSCAN"], privacy_mode="gaussian_dp_aggregate")
    assert shared["cluster_count_source"] == "published_public_dataset_k"
    assert shared["public_reference"] == "iris" and shared["dp_epsilon"] == 5
    assert job["display_algorithm"].endswith("[DP proxy]")
    assert job["effective_params"]["dp_proxy_cell_size"] == .75
    assert "dp_aggregate" not in job["effective_params"]
    control, _ = resolve(["fed_kmeans_numpy"], privacy_mode="public_clipped_control")
    assert "dp_epsilon" not in control
    with pytest.raises(ValueError, match="PUBLIC"):
        resolve(["fed_kmeans_numpy"], privacy_mode="gaussian_dp_aggregate", data=dict(IRIS,name="custom"))


def test_ward_metric_and_extraneous_controls():
    with pytest.raises(ValueError, match="ward"):
        resolve(["agglomerative"], mode="local", algorithm_params_by_name={"agglomerative":{"metric":"cosine"}})
    with pytest.raises(ValueError, match="num_clients"):
        resolve(["kmeans"], mode="local", num_clients=5)

def test_federated_stopping_profile_is_explicit():
    base = {"mode": "federated", "algorithms": ["fed_kmeans_numpy"]}
    for bad in (base, dict(base, stopping_profile="auto"),
                {"mode": "local", "algorithms":["kmeans"], "stopping_profile":"current_gui"}):
        with pytest.raises(ValueError, match="stopping_profile"):
            resolve_scenario(bad, dataset=IRIS, seed=1, path="scenarios.stopping")
    for profile in ("current_gui", "historical_paper"):
        shared, _ = resolve_scenario(dict(base, stopping_profile=profile), dataset=IRIS, seed=1, path="scenarios.stopping")
        assert shared["stopping_profile"] == profile

@pytest.mark.parametrize("fields", [
    {"target_clusters": 76},
    {"algorithm_params_by_name": {"Adapted FKM": {"n_clusters": 76}}},
    {"grid": {"Adapted FKM": {"k": [3, 76]}}},
    {"cluster_count_mode": "estimated_k", "estimated_k_min": 76, "estimated_k_max": 80},
    {"num_clients": 50, "participation_rate": 0.02, "target_clusters": 4},
])
def test_original_fkm_rejects_impossible_initial_server_capacity(fields):
    with pytest.raises(ValueError, match="initial server"):
        resolve(["Adapted FKM"], **fields)


def test_original_fkm_distinguishes_client_capacity_from_global_k():
    # Fifty 3-row clients can retain at most one nonsingleton center each.
    # Sufficient aggregate candidates depend on data, not just local size.
    options = {"num_clients": 50, "target_clusters": 4}
    _, (original,) = resolve(["Adapted FKM"], **options)
    capacity = original["first_round_capacity"]
    assert capacity["upper_bound"] == 50 and capacity["required_k"] == 4
    assert capacity["status"] == "requires_compute_check"
    with pytest.raises(ValueError, match="local update"):
        resolve(["Adapted FKM"], **options,
                algorithm_params_by_name={"Adapted FKM": {"drop_empty_clusters": False}})
    # The DP proxy supplies server representatives by another mechanism.
    for mode in ("gaussian_dp_aggregate", "public_clipped_control"):
        _, (proxy,) = resolve(["Adapted FKM"], num_clients=50, participation_rate=0.02,
                              target_clusters=4, privacy_mode=mode)
        assert "first_round_capacity" not in proxy


def test_non_iid_fkm_uses_guaranteed_sizes_without_assuming_equal_clients():
    fields = {"partition_mode": "quantity_skew", "num_clients": 5,
              "algorithm_params_by_name": {"Adapted FKM": {"drop_empty_clusters": False}}}
    # A requested lower bound of three does not prevent individual clients
    # from supporting a larger K; actual sizes and surviving centers still matter.
    _, (job,) = resolve(["Adapted FKM"], target_clusters=4, **fields)
    assert job["first_round_capacity"]["status"] == "requires_compute_check"
    # The 150 samples and explicit minimum of 30 force exactly 30 per client.
    with pytest.raises(ValueError, match="local update"):
        resolve(["Adapted FKM"], target_clusters=31, min_samples_per_client=30, **fields)
