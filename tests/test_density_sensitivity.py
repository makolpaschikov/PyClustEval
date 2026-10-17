from __future__ import annotations

import numpy as np

from clustering_eval.benchmarks.density_sensitivity import (
    DEFAULT_DENSITY_QUANTILES,
    density_radius_candidates,
    run_density_sensitivity,
)


def test_density_candidate_grid_has_fixed_budget_and_is_label_free():
    rng = np.random.default_rng(123)
    X = rng.normal(size=(50, 3))
    candidates = density_radius_candidates(X, min_samples=4)
    assert len(candidates) == len(DEFAULT_DENSITY_QUANTILES)
    assert [c.quantile for c in candidates] == list(DEFAULT_DENSITY_QUANTILES)
    assert all(c.radius > 0 for c in candidates)


def test_density_sensitivity_uses_equal_candidate_budget_for_dbscan_family():
    rows = run_density_sensitivity(
        "iris",
        partition_modes=("iid",),
        density_min_samples=4,
    )
    local = [r for r in rows if r["algorithm"] == "dbscan"]
    hf = [r for r in rows if r["algorithm"] == "Adapted HF_DBSCAN"]
    assert len(local) == len(DEFAULT_DENSITY_QUANTILES)
    assert len(hf) == len(DEFAULT_DENSITY_QUANTILES)
    assert {r["candidate_budget"] for r in rows} == {len(DEFAULT_DENSITY_QUANTILES)}
    assert {r["density_min_samples"] for r in rows} == {4}
    assert {r["candidate_source"] for r in rows} == {"algorithm-native kNN-distance quantile; labels unused"}
    assert {r["candidate_metric"] for r in local} == {"euclidean"}
    assert {r["candidate_metric"] for r in hf} == {"chebyshev"}
