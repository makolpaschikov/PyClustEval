from __future__ import annotations
from typing import Any
import time
import numpy as np
from sklearn.cluster import KMeans, DBSCAN, AgglomerativeClustering
from sklearn.mixture import GaussianMixture
from .base import ClusteringAlgorithm, AlgorithmResult

class SklearnKMeans(ClusteringAlgorithm):
    name = "kmeans"
    common_param_support = ("k", "max_iter", "seed")
    def run(self, X: np.ndarray, partition, params: dict[str, Any], seed: int) -> AlgorithmResult:
        start = time.perf_counter()
        model = KMeans(n_clusters=int(params.get("k", 3)), max_iter=int(params.get("max_iter", 300)), n_init="auto", random_state=seed)
        labels = model.fit_predict(X)
        return AlgorithmResult(labels=labels, model_state={"centers": model.cluster_centers_.tolist(), "inertia": float(model.inertia_)}, runtime_sec=time.perf_counter()-start)

class SklearnDBSCAN(ClusteringAlgorithm):
    name = "dbscan"
    common_param_support = ("density_min_samples",)
    default_params = {"eps": 0.5}
    def run(self, X: np.ndarray, partition, params: dict[str, Any], seed: int) -> AlgorithmResult:
        start = time.perf_counter()
        eps = float(params.get("eps", 0.5))
        min_samples = int(params.get("min_samples", params.get("density_min_samples", 4)))
        model = DBSCAN(eps=eps, min_samples=min_samples)
        labels = model.fit_predict(X)
        return AlgorithmResult(
            labels=labels,
            model_state={
                "n_clusters": int(len(set(labels)) - (1 if -1 in labels else 0)),
                "eps": eps,
                "min_samples": min_samples,
            },
            runtime_sec=time.perf_counter()-start,
        )

class SklearnGMM(ClusteringAlgorithm):
    name = "gmm"
    common_param_support = ("k", "max_iter", "tol", "seed")
    default_params = {"reg_covar": 1e-6}
    def run(self, X: np.ndarray, partition, params: dict[str, Any], seed: int) -> AlgorithmResult:
        start = time.perf_counter()
        model = GaussianMixture(
            n_components=int(params.get("k", 3)),
            max_iter=int(params.get("max_iter", 300)),
            tol=float(params.get("tol", 1e-4)),
            reg_covar=float(params.get("reg_covar", 1e-6)),
            random_state=seed,
        )
        labels = model.fit_predict(X)
        return AlgorithmResult(labels=labels, model_state={"weights": model.weights_.tolist()}, runtime_sec=time.perf_counter()-start)

class SklearnAgglomerative(ClusteringAlgorithm):
    name = "agglomerative"
    common_param_support = ("k",)
    def run(self, X: np.ndarray, partition, params: dict[str, Any], seed: int) -> AlgorithmResult:
        start = time.perf_counter()
        model = AgglomerativeClustering(n_clusters=int(params.get("k", 3)))
        labels = model.fit_predict(X)
        return AlgorithmResult(labels=labels, model_state={}, runtime_sec=time.perf_counter()-start)
