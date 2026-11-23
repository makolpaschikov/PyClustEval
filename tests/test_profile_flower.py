"""Negative controls for optional Windows cold simulation support."""

from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace

import pytest

from clustering_eval.application import flower_profile


def test_missing_simulation_packages_preserve_base_runtime(monkeypatch):
    real_job = {"algorithm": "fed_kmeans_flower", "backend": "flower-simulation",
                "execution_profile": {"lifecycle": "cold", "processes": 1, "blas_threads": 1}, "effective_params": {}}
    protocol = {"stopping_profile": "current_gui", "privacy_mode": "none"}
    monkeypatch.setattr(flower_profile.sys, "platform", "win32")
    monkeypatch.setattr(flower_profile.sys, "version_info", (3, 12, 10))
    monkeypatch.setattr(flower_profile.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(flower_profile.sys, "getwindowsversion", lambda: SimpleNamespace(build=26200), raising=False)

    calls = []

    def missing(name):
        calls.append(name)
        raise PackageNotFoundError(name)

    monkeypatch.setattr(flower_profile, "version", missing)
    assert flower_profile.runtime_rejection(dict(real_job, algorithm="kmeans", backend="local"), {}) is None
    assert not calls
    assert "flwr" in flower_profile.runtime_rejection(real_job, protocol)
    assert calls == ["flwr"]


@pytest.mark.parametrize("mode", ["gaussian_dp", "gaussian_dp_aggregate", "public_clipped_control"])
def test_unattested_privacy_mode_does_not_inherit_nonprivate_flower_support(mode):
    job = {"algorithm": "fed_gmm_diag_flower", "backend": "flower-simulation", "effective_params": {},
           "execution_profile": {"lifecycle": "cold", "processes": 1, "blas_threads": 1}}
    assert flower_profile.runtime_rejection(job, {"stopping_profile": "historical_paper", "privacy_mode": mode})


def test_cold_campaign_rejects_partial_server_work_even_after_one_good_round():
    from clustering_eval.flower_adapter.simulation import validate_transport

    first = {"round": 1, "dispatched_clients": 2, "returned_clients": 2, "active_clients": 1}
    history = [{"round": 1, "successful_clients": [0]}]
    last = {"round": 2, "dispatched_clients": 0}
    validate_transport([first, last], history, budget=2, clients=2, stopped=True)
    with pytest.raises(RuntimeError, match="round budget"):
        validate_transport([first], history, budget=2, clients=2, stopped=False)
    with pytest.raises(RuntimeError, match="expected server update"):
        validate_transport([first, last], history, budget=2, clients=2, stopped=False)
    with pytest.raises(RuntimeError, match="client responses"):
        validate_transport([dict(first, returned_clients=1), last], history, budget=2, clients=2, stopped=True)
