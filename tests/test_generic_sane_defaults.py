from __future__ import annotations

import numpy as np

from clustering_eval.algorithms.sklearn_algorithms import (
    SklearnAgglomerative,
    SklearnDBSCAN,
    SklearnGMM,
    SklearnKMeans,
)
from clustering_eval.default_profile import PROFILE_NAME, defaults_for
from clustering_eval.benchmarks.density_sensitivity import density_radius_candidates


def _toy(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.r_[rng.normal(-2, 0.2, (30, 2)), rng.normal(2, 0.2, (30, 2))]


def test_profile_is_dataset_agnostic_and_has_expected_conventional_defaults():
    assert PROFILE_NAME == "generic_sane_defaults_v2"
    assert defaults_for("kmeans")["n_init"] == 10
    assert defaults_for("kmeans")["init"] == "k-means++"
    assert defaults_for("dbscan") == {
        "eps": None,
        "eps_strategy": "k_distance_quantile",
        "eps_quantile": 0.50,
        "metric": "euclidean",
    }
    assert defaults_for("gmm")["covariance_type"] == "full"
    assert defaults_for("Adapted HF_DBSCAN")["min_points"] == 4
    assert defaults_for("Adapted HF_DBSCAN")["L"] == 0.15
    assert defaults_for("Adapted FKDC") == {}
    assert defaults_for("Adapted NN-FC") == {}


def test_sklearn_algorithms_accept_and_report_generic_profile_values():
    X = _toy()

    km = SklearnKMeans().run(X, None, {"k": 2, **defaults_for("kmeans")}, 42)
    assert km.model_state["n_init"] == 10
    assert km.model_state["init"] == "k-means++"

    db = SklearnDBSCAN().run(X, None, {"density_min_samples": 5, **defaults_for("dbscan")}, 42)
    expected_eps = density_radius_candidates(
        X, 5, quantiles=(0.50,), metric="euclidean"
    )[0].radius
    assert np.isclose(db.model_state["eps"], expected_eps)
    assert db.model_state["eps_strategy"] == "k_distance_quantile"
    assert db.model_state["eps_quantile"] == 0.50
    assert db.model_state["min_samples"] == 5
    assert db.model_state["metric"] == "euclidean"

    # A numeric override remains possible for scripts, even though the UI no
    # longer exposes eps.  It must bypass the automatic rule deterministically.
    db_fixed = SklearnDBSCAN().run(
        X, None, {"density_min_samples": 5, **defaults_for("dbscan"), "eps": 0.123}, 42
    )
    assert db_fixed.model_state["eps"] == 0.123
    assert db_fixed.model_state["eps_strategy"] == "fixed_override"

    gm = SklearnGMM().run(X, None, {"k": 2, "max_iter": 300, "tol": 1e-4, **defaults_for("gmm")}, 42)
    assert gm.model_state["covariance_type"] == "full"
    assert gm.model_state["max_iter"] == 300
    assert gm.model_state["tol"] == 1e-4

    ag = SklearnAgglomerative().run(X, None, {"k": 2, **defaults_for("agglomerative")}, 42)
    assert ag.model_state == {"linkage": "ward", "metric": "euclidean"}


def test_dbscan_report_records_label_free_resolved_eps(tmp_path):
    from clustering_eval.application.comparison_service import ComparisonService
    from clustering_eval.application.dto import RunRequest
    from clustering_eval.results.history_store import HistoryStore

    service = ComparisonService(history_store=HistoryStore(tmp_path / "history"))
    report = service.compare(
        RunRequest(
            mode="local",
            dataset_name="iris",
            algorithms=("dbscan", "kmeans"),
        )
    )
    db = next(item for item in report.results if item.algorithm == "dbscan")
    benchmark = db.model_state["benchmark"]
    assert benchmark["parameter_profile"] == "generic_sane_defaults_v2"
    assert benchmark["profile_defaults"]["eps"] is None
    assert benchmark["profile_defaults"]["eps_quantile"] == 0.50
    assert benchmark["effective_params"]["resolved_eps"] == db.model_state["eps"]
    assert db.model_state["eps_strategy"] == "k_distance_quantile"
