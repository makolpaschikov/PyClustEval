"""Small controls for the two stopping policies and the full paper compute profile."""
import numpy as np
import pytest

from clustering_eval.algorithms.author_adapters import AdaptedAuthorFDBSCAN, AdaptedAuthorFKM
from clustering_eval.algorithms.fed_kmeans_numpy import FedKMeansNumpy
from clustering_eval.algorithms.federated_extra import FedDiagonalGMMNumpy, FedFuzzyCMeansNumpy
from clustering_eval.federated.environment import early_stopping_allowed, participation_entry_for_round
from clustering_eval.privacy.aggregate_dp import clipped_public_features, make_dp_aggregate_config

CURRENT = {"_stopping_profile": "current_gui"}
HISTORICAL = {"_stopping_profile": "historical_paper"}
ARCHIVE = {**HISTORICAL, "_historical_compute": True}
METHODS = [FedKMeansNumpy(), FedFuzzyCMeansNumpy(), FedDiagonalGMMNumpy()]


def schedule(*successful):
    return [
        {"round": r + 1, "selected_clients": [0, 1], "successful_clients": active,
         "dropped_clients": [c for c in (0, 1) if c not in active]}
        for r, active in enumerate(successful)
    ]


@pytest.mark.parametrize("method", METHODS)
def test_stopping_changes_only_for_nonstationary_schedule(method):
    X = np.arange(16, dtype=float).reshape(8, 2)
    partition = np.array_split(np.arange(8), 2)
    params = {"rounds": 3, "tol": 1e6, "k": 2,
              "participation_schedule": schedule([0], [0], [1])}
    current = method.run(X, partition, {**params, **CURRENT}, 7)
    paper = method.run(X, partition, {**params, **HISTORICAL}, 7)
    assert current.model_state["rounds"] == 1
    assert current.model_state["stopping_reason"] == "tolerance"
    assert paper.model_state["stopping_reason"] == "round_budget"
    assert [r["successful_clients"] for r in paper.history] == [[0], [0], [1]]

    params["participation_schedule"] = schedule([0, 1], [1, 0], [1, 0])
    fixed = method.run(X, partition, {**params, **HISTORICAL}, 7)
    assert fixed.model_state["rounds"] == 1
    assert fixed.model_state["stopping_reason"] == "tolerance"
    assert participation_entry_for_round({**params, **HISTORICAL}, 1, 2)["successful_clients"] == [1, 0]


@pytest.mark.parametrize(("method", "kind", "downlink", "upload"), [
    (METHODS[0], "kmeans", 32, 48),
    (METHODS[1], "fuzzy", 32, 48),
    (METHODS[2], "gmm", 80, 80),
])
def test_fixed_budget_uses_actual_noise_and_counts_selected_downlink_only_for_archive(
    method, kind, downlink, upload,
):
    # 2 components/features; DP initializer has zero communication cost.
    X = np.arange(16, dtype=float).reshape(8, 2) / 16
    part = np.array_split(np.arange(8), 2)
    params = {"rounds": 3, "tol": 1e6, "k": 2,
              "participation_schedule": schedule([0], [0], [0])}
    cfg = make_dp_aggregate_config(kind=kind, epsilon=1.0, delta=1e-5,
                                   clip_norm=1.0, rounds=3, enabled=True)
    current = method.run(X, part, {**params, **CURRENT, "dp_aggregate": cfg}, 4)
    paper = method.run(X, part, {**params, **HISTORICAL, "dp_aggregate": cfg}, 4)
    archive = method.run(X, part, {**params, **ARCHIVE, "dp_aggregate": cfg}, 4)
    assert len(current.history) == 1
    assert len(paper.history) == len(archive.history) == 3
    assert paper.communication_bytes == 3 * (downlink + upload)
    assert archive.communication_bytes == 3 * (2 * downlink + upload)
    cfg = make_dp_aggregate_config(kind=kind, epsilon=1.0, delta=1e-5,
                                   clip_norm=1.0, rounds=3, enabled=False)
    control = method.run(X, part, {**params, **ARCHIVE, "dp_aggregate": cfg}, 4)
    assert len(control.history) == 1
    assert control.model_state["stopping_reason"] == "tolerance"


def test_numpy_gmm_historical_shift_includes_variances_before_projection(monkeypatch):
    import clustering_eval.algorithms.federated_extra as gmm

    monkeypatch.setattr(gmm, "public_initial_centers", lambda *args: np.zeros((1, 1)))
    X = np.array([[-2.], [2.], [-2.], [2.]])
    # A deliberately unconstrained controlled input to observe shift measurement BEFORE
    # parameter projection. Variance proposal = 4, previous and projected = 1.
    cfg = make_dp_aggregate_config(kind="gmm", epsilon=2., delta=1e-5,
                                   clip_norm=1., rounds=3, enabled=False)
    kwargs = {"dp_aggregate": cfg, "k": 1, "tol": 0.01, "rounds": 3}
    current = FedDiagonalGMMNumpy().run(X, None, {**kwargs, **CURRENT}, 0)
    paper = FedDiagonalGMMNumpy().run(X, None, {**kwargs, **HISTORICAL}, 0)
    assert [r["shift"] for r in current.history] == [0.]
    assert [r["shift"] for r in paper.history] == [3., 3., 3.]
    assert paper.model_state["variances"] == [[1.]]
    assert paper.model_state["means"] == [[0.]]


def test_gmm_weight_change_alone_prevents_first_historical_stop(monkeypatch):
    import clustering_eval.algorithms.federated_extra as gmm

    monkeypatch.setattr(gmm, "public_initial_centers", lambda *args: np.zeros((2, 1)))
    nk = np.array([2., 6.])
    monkeypatch.setattr(gmm, "noisy_joint_aggregate",
                        lambda cfg, *arrays: (nk.copy(), np.zeros((2, 1)), nk[:, None].copy()))
    cfg = make_dp_aggregate_config(kind="gmm", epsilon=2., delta=1e-5,
                                   clip_norm=1., rounds=3, enabled=False)
    params = {"dp_aggregate": cfg, "k": 2, "tol": .01, "rounds": 3}
    X = np.zeros((8, 1))
    current = FedDiagonalGMMNumpy().run(X, None, {**params, **CURRENT}, 0)
    paper = FedDiagonalGMMNumpy().run(X, None, {**params, **HISTORICAL}, 0)
    assert [r["shift"] for r in current.history] == [0.]
    np.testing.assert_allclose([r["shift"] for r in paper.history], [np.sqrt(.125), 0.])


def test_paper_rejects_invalid_schedule_and_budget_before_early_exit():
    for rows in (schedule([0]), schedule([0], [0, 0]), schedule([0], [1.0]),
                 [schedule([0])[0], {"round": 2, "selected_clients": [0],
                  "successful_clients": [0], "dropped_clients": [0]}]):
        with pytest.raises(ValueError):
            early_stopping_allowed({**HISTORICAL, "participation_schedule": rows}, 2, 2)
    cfg = {"sigma_per_coordinate": 1., "enabled": True, "budgeted_rounds": 1}
    with pytest.raises(ValueError, match="budget"):
        early_stopping_allowed({**HISTORICAL, "dp_aggregate": cfg}, 2, 2)


def test_public_references_use_pixel_coordinates_and_generator_moments():
    X = np.eye(2, 784)
    pixels, pixel_info = clipped_public_features(X, "mnist_10k", 0.5, public_reference={})
    np.testing.assert_array_equal(pixels, X * 0.5)
    assert not pixel_info["private_data_fitted_scaler"]
    with pytest.raises(ValueError, match="784"):
        clipped_public_features(X[:, :2], "mnist_10k", 1., public_reference={})
    with pytest.raises(ValueError, match="normalized"):
        clipped_public_features(255 * X, "mnist_10k", 1., public_reference={})
    meta = {"public_center": [1., 2.], "public_scale": [2., 3.],
            "public_reference_note": "public generator"}
    scaled, info = clipped_public_features(
        np.array([[7., 14.]]), "synthetic_anisotropic", 2.5, public_reference=meta)
    np.testing.assert_allclose(scaled, [[1.5, 2.]])
    assert info["source"] == "public generator"
    with pytest.raises(ValueError, match="public center or scale"):
        clipped_public_features(X[:, :2], "synthetic_anisotropic", 2.5,
                                public_reference={**meta, "public_scale": [0., 1.]})


@pytest.mark.parametrize("min_points", [1, 1000])
def test_historical_density_cells_match_author_and_remain_one_shot(min_points):
    X = np.array([[0.10, 0.10], [0.11, 0.12], [0.80, 0.80], [0.81, 0.82]])
    part = [np.array([0, 2]), np.array([1, 3])]
    params = {"L": .25, "MIN_POINTS": min_points, "rounds": 3,
              "participation_schedule": schedule([0, 1], [1], [0])}
    original = AdaptedAuthorFDBSCAN().run(X, part, {**params, **CURRENT}, 3)
    historical = AdaptedAuthorFDBSCAN().run(X, part, {**params, **ARCHIVE}, 3)
    np.testing.assert_array_equal(original.labels, historical.labels)
    assert bool(historical.model_state["dense_cells"]) == (min_points == 1)
    if min_points == 1000:
        assert np.all(historical.labels == -1)
    assert historical.history == original.history == []
    assert historical.model_state["rounds"] == 1
    assert historical.communication_bytes == original.communication_bytes


def test_actual_fkm_initial_server_capacity_failure_reports_surviving_centers():
    X = np.arange(8, dtype=float).reshape(4, 2)
    with pytest.raises(ValueError, match="initial active clients retained 0 centers for K=2"):
        AdaptedAuthorFKM().run(X, [np.array([0, 1]), np.array([2, 3])], {"k": 2}, 7)


def test_archive_kmeans_accepts_historical_dtype_and_k_alias():
    X = np.arange(16, dtype=np.float32).reshape(8, 2)
    params = {**ARCHIVE, "n_clusters": 2, "rounds": 2}
    method = FedKMeansNumpy()
    actual = method.run(X, None, params, 2)
    expected = method.run(X.astype(np.float64), None, {**params, "k": 2}, 2)
    assert len(actual.model_state["centers"]) == 2
    np.testing.assert_array_equal(actual.labels, expected.labels)
    assert actual.model_state == expected.model_state



@pytest.mark.parametrize(("enabled", "method", "histograms"), [
    (True, AdaptedAuthorFDBSCAN(), 1), (False, AdaptedAuthorFDBSCAN(), 0),
    (True, AdaptedAuthorFKM(), 0),
])
def test_proxy_reports_only_executed_noise_queries(monkeypatch, enabled, method, histograms):
    import clustering_eval.privacy.aggregate_dp as aggregate
    import clustering_eval.privacy.author_dp_proxy as proxy

    prototype_draws, histogram_draws = [], []

    def capture_draw(calls):
        def draw(shape, sigma):
            calls.append(sigma)
            return np.zeros(shape)
        return draw

    monkeypatch.setattr(aggregate, "secure_normal_noise", capture_draw(prototype_draws))
    monkeypatch.setattr(proxy, "secure_normal_noise", capture_draw(histogram_draws))
    X = np.arange(24, dtype=float).reshape(12, 2) / 24
    part = np.array_split(np.arange(len(X)), 2)
    cfg = make_dp_aggregate_config(kind="kmeans", epsilon=4., delta=1e-5,
                                   clip_norm=4., rounds=1, enabled=enabled)
    result = method.run(X, part, {"k": 2, "dp_aggregate": cfg, "min_points": 999, **ARCHIVE}, 4)
    state = result.model_state
    # A joint prototype query draws the Gaussian coordinates of sums and counts.
    assert state["noised_client_prototype_queries"] == len(prototype_draws) // 2 == (2 if enabled else 0)
    assert state["noised_histogram_queries"] == len(histogram_draws) == histograms
    assert state["clipped_control"] == (not enabled)
    if enabled:
        assert "OS" in state["dp_noise_rng"]
        assert state["dp_sigma_prototype_per_coordinate"] == prototype_draws[0]
    else:
        assert state["dp_noise_rng"] is state["protected_release"] is state["dp_accounting"] is None
        assert "privacy_budget_split" not in state
    if histograms:
        assert state["histogram_candidate_count"] == 0
        assert state["dp_sigma_histogram_per_coordinate"] == histogram_draws[0]


def test_flower_strategy_callbacks_without_simulation(monkeypatch):
    # Exercise this project's client/strategy logic only. A real runtime, transport
    # and simulator lifecycle are outside this test and require the PROFILE pilot.
    import sys
    from types import SimpleNamespace

    from clustering_eval.flower_adapter.fed_kmeans_flower_adapter import FedKMeansFlowerAdapter
    from clustering_eval.flower_adapter.federated_extra_flower import (
        FedDiagonalGMMFlowerAdapter, FedFuzzyCMeansFlowerAdapter,
    )

    class Client:
        def to_client(self):
            return self

    events = []

    def drive_callbacks(*, server_app, client_app, num_supernodes, backend_config):
        components = server_app.server_fn(None)
        strategy = components.strategy
        clients = [client_app.client_fn(SimpleNamespace(node_config={"partition-id": n}))
                   for n in range(num_supernodes)]
        manager = SimpleNamespace(sample=lambda *args, **kwargs: clients)
        parameters = strategy.initialize_parameters(manager)
        for r in range(1, components.config.num_rounds + 1):
            instructions = strategy.configure_fit(r, parameters, manager)
            events.append({"dispatch": len(instructions), "clients": []})
            if instructions:
                results = []
                for client, (model, config) in instructions:
                    values, count, metrics = client.fit(model, config)
                    events[-1]["clients"].append(metrics)
                    results.append((client, SimpleNamespace(parameters=values, metrics=metrics)))
                parameters, events[-1]["server"] = strategy.aggregate_fit(r, results, [])

    ns = SimpleNamespace
    client_api = ns(NumPyClient=Client, ClientApp=ns)
    modules = {
        "flwr": ns(client=client_api), "flwr.client": client_api,
        "flwr.common": ns(FitIns=lambda model, config: (model, config),
                          ndarrays_to_parameters=lambda arrays: arrays, parameters_to_ndarrays=lambda p: p),
        "flwr.server": ns(ServerApp=ns, ServerConfig=ns, ServerAppComponents=ns),
        "flwr.server.strategy": ns(Strategy=object), "flwr.server.client_manager": ns(ClientManager=object),
        "flwr.simulation": ns(run_simulation=drive_callbacks),
    }
    for key, module in modules.items():
        monkeypatch.setitem(sys.modules, key, module)

    X = np.arange(16, dtype=float).reshape(8, 2) / 16
    part = np.array_split(np.arange(8), 2)
    for method, kind in [(FedKMeansFlowerAdapter(), "kmeans"), (FedFuzzyCMeansFlowerAdapter(), "fuzzy"),
                         (FedDiagonalGMMFlowerAdapter(), "gmm")]:
        params = {"k": 2, "rounds": 3, "tol": 1e6}
        events.clear()
        current = method.run(X, part, {**params, **CURRENT}, 2)
        assert [e["dispatch"] for e in events] == [2, 2, 2]
        assert len(current.history) == 3

        events.clear()
        paper = method.run(X, part, {**params, **HISTORICAL}, 2)
        assert len(paper.history) == 1
        assert [e["dispatch"] for e in events] == [2, 0, 0]
        single = method.run(X, part, {**params, **HISTORICAL, "rounds": 1}, 2)
        assert single.communication_bytes == paper.communication_bytes

        events.clear()
        dp = make_dp_aggregate_config(kind=kind, epsilon=2., delta=1e-5,
                                      clip_norm=1., rounds=3, enabled=True)
        noisy = method.run(X, part, {**params, **ARCHIVE, "dp_aggregate": dp}, 2)
        assert len(noisy.history) == 3
        assert all(set(metrics) == {"active"} for e in events for metrics in e["clients"])
        assert all(set(e["server"]) == {"shift"} for e in events)

    with pytest.raises(ValueError, match="fuzziness"):
        FedFuzzyCMeansFlowerAdapter().run(X, part, {**ARCHIVE, "fuzziness": 1., "k": 2}, 2)
