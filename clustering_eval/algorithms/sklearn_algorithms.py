from __future__ import annotations
from typing import Any
import time
import numpy as np
from sklearn.cluster import KMeans, DBSCAN, AgglomerativeClustering
from sklearn.mixture import GaussianMixture
from sklearn.neighbors import NearestNeighbors
from .base import ClusteringAlgorithm, AlgorithmResult

class SklearnKMeans(ClusteringAlgorithm):
    name = "kmeans"
    common_param_support = ("k", "max_iter", "tol", "seed")
    default_params = {"init": "k-means++", "n_init": 10}
    def run(self, X: np.ndarray, partition, params: dict[str, Any], seed: int) -> AlgorithmResult:
        start = time.perf_counter()
        model = KMeans(
            n_clusters=int(params.get("k", 3)),
            init=str(params.get("init", "k-means++")),
            n_init=int(params.get("n_init", 10)),
            max_iter=int(params.get("max_iter", 300)),
            tol=float(params.get("tol", 1e-4)),
            random_state=seed,
        )
        labels = model.fit_predict(X)
        return AlgorithmResult(
            labels=labels,
            model_state={
                "centers": model.cluster_centers_.tolist(),
                "inertia": float(model.inertia_),
                "init": model.init,
                "n_init": model.n_init,
                "max_iter": model.max_iter,
                "tol": model.tol,
            },
            runtime_sec=time.perf_counter()-start,
        )

def _estimate_dbscan_eps_kdist_quantile(
    X: np.ndarray,
    *,
    min_samples: int,
    metric: str,
    quantile: float,
) -> float:
    """Estimate DBSCAN eps from X only using a fixed k-distance quantile.

    The rule is deliberately label-free and dataset-agnostic.  It mirrors the
    kNN-distance construction used by PyClustEval's density-sensitivity tool:
    query ``min_samples`` neighbors (including the sample at distance zero,
    as in sklearn DBSCAN core-point convention), then take one pre-registered quantile
    of the resulting k-distances.
    """
    X = np.asarray(X, dtype=np.float64)
    if len(X) < 2:
        raise ValueError("DBSCAN automatic eps estimation requires at least two samples")
    if min_samples < 1:
        raise ValueError("min_samples must be >= 1")
    quantile = float(quantile)
    if not 0.0 < quantile < 1.0:
        raise ValueError(f"eps_quantile must be in (0, 1), got {quantile}")

    neighbor_rank = min(int(min_samples), len(X))
    nn = NearestNeighbors(n_neighbors=neighbor_rank, metric=metric)
    distances = nn.fit(X).kneighbors(X, return_distance=True)[0]
    kth = distances[:, -1]
    eps = float(np.quantile(kth, quantile))
    if eps <= 0.0:
        positive = kth[kth > 0.0]
        eps = float(np.min(positive)) if len(positive) else float(np.finfo(float).eps)
    return eps


class SklearnDBSCAN(ClusteringAlgorithm):
    name = "dbscan"
    common_param_support = ("density_min_samples",)
    default_params = {
        "eps": None,
        "eps_strategy": "k_distance_quantile",
        "eps_quantile": 0.50,
        "metric": "euclidean",
    }

    def run(self, X: np.ndarray, partition, params: dict[str, Any], seed: int) -> AlgorithmResult:
        start = time.perf_counter()
        min_samples = int(params.get("min_samples", params.get("density_min_samples", 5)))
        metric = str(params.get("metric", "euclidean"))
        raw_eps = params.get("eps")
        strategy = str(params.get("eps_strategy", "k_distance_quantile"))
        eps_quantile = float(params.get("eps_quantile", 0.50))

        # An explicit numeric eps remains a supported programmatic override.
        # The UI/default benchmark profile uses the label-free automatic rule.
        if raw_eps is not None and str(raw_eps).strip().lower() not in {"", "auto", "none"}:
            eps = float(raw_eps)
            resolved_strategy = "fixed_override"
        elif strategy == "k_distance_quantile":
            eps = _estimate_dbscan_eps_kdist_quantile(
                X,
                min_samples=min_samples,
                metric=metric,
                quantile=eps_quantile,
            )
            resolved_strategy = strategy
        else:
            raise ValueError(f"Unsupported DBSCAN eps_strategy: {strategy!r}")

        model = DBSCAN(eps=eps, min_samples=min_samples, metric=metric)
        labels = model.fit_predict(X)
        return AlgorithmResult(
            labels=labels,
            model_state={
                "n_clusters": int(len(set(labels)) - (1 if -1 in labels else 0)),
                "eps": eps,
                "eps_strategy": resolved_strategy,
                "eps_quantile": eps_quantile if resolved_strategy == "k_distance_quantile" else None,
                "min_samples": min_samples,
                "metric": metric,
            },
            runtime_sec=time.perf_counter()-start,
        )

class SklearnGMM(ClusteringAlgorithm):
    name = "gmm"
    common_param_support = ("k", "max_iter", "tol", "seed")
    default_params = {
        "covariance_type": "full",
        "reg_covar": 1e-6,
        "n_init": 1,
        "init_params": "kmeans",
    }
    def run(self, X: np.ndarray, partition, params: dict[str, Any], seed: int) -> AlgorithmResult:
        start = time.perf_counter()
        model = GaussianMixture(
            n_components=int(params.get("k", 3)),
            covariance_type=str(params.get("covariance_type", "full")),
            max_iter=int(params.get("max_iter", 100)),
            tol=float(params.get("tol", 1e-3)),
            reg_covar=float(params.get("reg_covar", 1e-6)),
            n_init=int(params.get("n_init", 1)),
            init_params=str(params.get("init_params", "kmeans")),
            random_state=seed,
        )
        labels = model.fit_predict(X)
        return AlgorithmResult(
            labels=labels,
            model_state={
                "weights": model.weights_.tolist(),
                "covariance_type": model.covariance_type,
                "max_iter": model.max_iter,
                "tol": model.tol,
                "reg_covar": model.reg_covar,
                "n_init": model.n_init,
                "init_params": model.init_params,
            },
            runtime_sec=time.perf_counter()-start,
        )

class SklearnAgglomerative(ClusteringAlgorithm):
    name = "agglomerative"
    common_param_support = ("k",)
    default_params = {"linkage": "ward", "metric": "euclidean"}
    def run(self, X: np.ndarray, partition, params: dict[str, Any], seed: int) -> AlgorithmResult:
        start = time.perf_counter()
        linkage = str(params.get("linkage", "ward"))
        metric = str(params.get("metric", "euclidean"))
        model = AgglomerativeClustering(
            n_clusters=int(params.get("k", 3)),
            linkage=linkage,
            metric=metric,
        )
        labels = model.fit_predict(X)
        return AlgorithmResult(
            labels=labels,
            model_state={"linkage": linkage, "metric": metric},
            runtime_sec=time.perf_counter()-start,
        )
