from __future__ import annotations

"""Dataset-agnostic benchmark parameter profile.

The values in this module are deliberately *not* selected by ARI/NMI on any
PyClustEval dataset.  For sklearn baselines they follow stable/common sklearn
conventions.  For vendored author implementations they preserve author-side
constants where the adapter exposes them, plus the documented generic
HF_DBSCAN cell size used after MinMax scaling.

Explicit request.algorithm_params / algorithm_params_by_name overrides still
win over this profile.
"""

PROFILE_NAME = "generic_sane_defaults_v2"

# These are algorithm-specific defaults, not dataset-specific tuning.
GENERIC_SANE_DEFAULTS: dict[str, dict[str, object]] = {
    # Centralized sklearn baselines.
    "kmeans": {
        "init": "k-means++",
        # Explicit 10 restarts makes the benchmark robust across sklearn
        # versions (newer releases changed the default to n_init='auto').
        "n_init": 10,
    },
    "dbscan": {
        # Label-free, dataset-agnostic automatic radius: median distance to the
        # min_samples-th neighbor (self included) after the algorithm's StandardScaler.
        "eps": None,
        "eps_strategy": "k_distance_quantile",
        "eps_quantile": 0.50,
        "metric": "euclidean",
    },
    "gmm": {
        "covariance_type": "full",
        "reg_covar": 1e-6,
        "n_init": 1,
        "init_params": "kmeans",
    },
    "agglomerative": {
        "linkage": "ward",
        "metric": "euclidean",
    },

    # PyClustEval federated baselines.  The common round budget remains an
    # experiment control; these values only specify algorithm-specific knobs.
    "fed_fuzzy_cmeans_numpy": {"fuzziness": 2.0},
    "fed_fuzzy_cmeans_flower": {"fuzziness": 2.0},
    "fed_gmm_diag_numpy": {"reg_covar": 1e-6},
    "fed_gmm_diag_flower": {"reg_covar": 1e-6},

    # Vendored author implementations.  Do not add dataset-specific tuning.
    "Adapted FKM": {
        "iter_local": 1,
        "drop_empty_clusters": True,
        "weighted_agg": True,
        "init": "k-means++",
    },
    "Adapted HF_DBSCAN": {
        # Author repository uses L=0.03 for banana.  0.15 is PyClustEval's
        # documented generic value after MinMax scaling, not a tuned value.
        "L": 0.15,
        "min_points": 4,
    },
    "Adapted p-FClus": {"pfclus_max_iters": 10},
    # FKDC and NN-FC keep their fixed author constants inside vendored source.
    "Adapted FKDC": {},
    "Adapted NN-FC": {},
}


def defaults_for(algorithm_name: str) -> dict[str, object]:
    """Return a copy so callers cannot mutate the global profile."""
    return dict(GENERIC_SANE_DEFAULTS.get(algorithm_name, {}))
