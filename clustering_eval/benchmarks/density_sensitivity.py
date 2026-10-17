from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from sklearn.neighbors import NearestNeighbors

from clustering_eval.algorithms.registry import default_registry as algorithm_registry
from clustering_eval.application.comparison_service import _preprocess_algorithm_input
from clustering_eval.datasets.partitioning import make_partition
from clustering_eval.datasets.registry import default_registry as dataset_registry
from clustering_eval.metrics.clustering import compute_metrics


DEFAULT_DENSITY_QUANTILES: tuple[float, ...] = (0.20, 0.35, 0.50, 0.65, 0.80)


@dataclass(frozen=True, slots=True)
class DensityCandidate:
    quantile: float
    radius: float


def density_radius_candidates(
    X: np.ndarray,
    min_samples: int,
    quantiles: Iterable[float] = DEFAULT_DENSITY_QUANTILES,
    *,
    metric: str = "euclidean",
) -> list[DensityCandidate]:
    """Generate a fixed-budget, label-free radius grid from k-NN distances.

    The same quantile budget is used for DBSCAN eps and HF_DBSCAN L. Numeric
    radii are computed *after each implementation's declared preprocessing*, so
    we do not force identical values across StandardScaler and MinMaxScaler
    spaces. Ground-truth labels are never used to generate candidates.
    """
    X = np.asarray(X, dtype=np.float64)
    if len(X) < 2:
        raise ValueError("density sensitivity requires at least two samples")
    if min_samples < 1:
        raise ValueError("min_samples must be >= 1")

    # +1 because a training-set kNN query includes the point itself at distance 0.
    neighbor_rank = min(int(min_samples) + 1, len(X))
    nn = NearestNeighbors(n_neighbors=neighbor_rank, metric=metric)
    distances = nn.fit(X).kneighbors(X, return_distance=True)[0]
    kth = distances[:, -1]

    result: list[DensityCandidate] = []
    for q in quantiles:
        q = float(q)
        if not 0.0 < q < 1.0:
            raise ValueError(f"quantile must be in (0, 1), got {q}")
        radius = float(np.quantile(kth, q))
        # Exact duplicate observations can produce a zero quantile. Both DBSCAN
        # eps and HF_DBSCAN L require a positive radius/cell size.
        if radius <= 0.0:
            positive = kth[kth > 0.0]
            radius = float(np.min(positive)) if len(positive) else float(np.finfo(float).eps)
        result.append(DensityCandidate(q, radius))
    return result


def _status(labels: np.ndarray) -> tuple[str, int, float, float]:
    unique, counts = np.unique(labels, return_counts=True)
    non_noise = [(int(v), int(c)) for v, c in zip(unique, counts) if int(v) != -1]
    noise_count = sum(int(c) for v, c in zip(unique, counts) if int(v) == -1)
    non_noise_total = sum(c for _, c in non_noise)
    dominant = (
        max((c for _, c in non_noise), default=0) / non_noise_total
        if non_noise_total
        else 0.0
    )
    if len(non_noise) < 2:
        status = "degenerate"
    elif dominant >= 0.95:
        status = "near_degenerate"
    else:
        status = "ok"
    return status, len(non_noise), noise_count / len(labels), dominant


def run_density_sensitivity(
    dataset_name: str,
    *,
    seed: int = 42,
    num_clients: int = 5,
    partition_modes: tuple[str, ...] = ("iid", "dirichlet"),
    dirichlet_alpha: float = 0.5,
    density_min_samples: int = 4,
    quantiles: Iterable[float] = DEFAULT_DENSITY_QUANTILES,
) -> list[dict[str, object]]:
    """Run equal-budget, label-free sensitivity sweeps for DBSCAN-family methods.

    No candidate is selected by ARI/NMI. Those metrics are recorded only after
    every pre-registered candidate has run, so the report can be inspected
    without turning the sweep into label-based hyperparameter tuning.
    """
    ds = dataset_registry().load(dataset_name)
    X_raw = np.asarray(ds.X, dtype=np.float64)
    y = None if ds.y is None else np.asarray(ds.y)
    k = len(np.unique(y)) if y is not None else 3
    rows: list[dict[str, object]] = []

    specs = (
        # sklearn DBSCAN uses Euclidean neighborhoods by default.
        ("dbscan", "eps", "euclidean", ("local",)),
        # HF_DBSCAN L is an axis-aligned grid-cell edge, so Chebyshev kNN
        # distance is the closest label-free scale statistic in the same units.
        ("Adapted HF_DBSCAN", "L", "chebyshev", partition_modes),
    )
    for algorithm_name, radius_param, candidate_metric, modes in specs:
        algorithm = algorithm_registry().get(algorithm_name)
        X = _preprocess_algorithm_input(X_raw, algorithm)
        candidates = density_radius_candidates(
            X, density_min_samples, quantiles, metric=candidate_metric
        )

        for partition_mode in modes:
            partition = None
            if partition_mode != "local":
                partition = make_partition(
                    partition_mode,
                    len(X),
                    num_clients,
                    seed,
                    y=y,
                    alpha=dirichlet_alpha,
                    min_samples_per_client=3,
                )

            for candidate_index, candidate in enumerate(candidates, 1):
                params: dict[str, object] = {
                    "k": k,
                    "n_clusters": k,
                    "rounds": 10,
                    "tol": 1e-4,
                    "max_iter": 300,
                    "density_min_samples": density_min_samples,
                    "client_cpus": 1.0,
                    "client_gpus": 0.0,
                }
                params.update(dict(getattr(algorithm, "default_params", {}) or {}))
                params[radius_param] = candidate.radius

                result = algorithm.run(X, partition, params, seed)
                labels = np.asarray(result.labels)
                metrics = compute_metrics(X, y, labels, ["ari", "nmi", "silhouette"])
                status, found, noise, dominant = _status(labels)
                rows.append(
                    {
                        "dataset": dataset_name,
                        "algorithm": algorithm_name,
                        "partition": partition_mode,
                        "candidate_index": candidate_index,
                        "candidate_budget": len(candidates),
                        "quantile": candidate.quantile,
                        "radius_param": radius_param,
                        "radius": candidate.radius,
                        "density_min_samples": density_min_samples,
                        "status": status,
                        "clusters_found": found,
                        "noise_fraction": noise,
                        "dominant_cluster_fraction": dominant,
                        "ari": metrics.get("ari"),
                        "nmi": metrics.get("nmi"),
                        "silhouette": metrics.get("silhouette"),
                        "runtime_sec": result.runtime_sec,
                        "preprocessing": getattr(algorithm, "input_preprocessing", "standard"),
                        "candidate_metric": candidate_metric,
                        "candidate_source": "algorithm-native kNN-distance quantile; labels unused",
                    }
                )
    return rows
