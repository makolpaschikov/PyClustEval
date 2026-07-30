from __future__ import annotations
from typing import Any
import time
import numpy as np
from sklearn.metrics import pairwise_distances_argmin
from .base import ClusteringAlgorithm, AlgorithmResult

class FedKMeansNumpy(ClusteringAlgorithm):
    """Simple synchronous federated KMeans simulation without Flower.

    This implements the same algorithmic contract that a Flower Strategy/ClientApp
    would implement: server sends centers, clients return sums/counts, server aggregates.
    """
    name = "fed_kmeans_numpy"

    def run(self, X: np.ndarray, partition: list[np.ndarray] | None, params: dict[str, Any], seed: int) -> AlgorithmResult:
        if partition is None:
            partition = [np.arange(len(X))]
        rng = np.random.default_rng(seed)
        k = int(params.get("k", 3))
        rounds = int(params.get("rounds", 20))
        initial_idx = rng.choice(len(X), size=k, replace=False)
        centers = X[initial_idx].astype(float).copy()
        history: list[dict[str, Any]] = []
        communication_bytes = 0
        start = time.perf_counter()

        for rnd in range(rounds):
            sums = np.zeros_like(centers)
            counts = np.zeros(k, dtype=int)
            inertia = 0.0
            for idx in partition:
                if len(idx) == 0:
                    continue
                Xc = X[idx]
                local_labels = pairwise_distances_argmin(Xc, centers)
                for cluster_id in range(k):
                    mask = local_labels == cluster_id
                    if mask.any():
                        sums[cluster_id] += Xc[mask].sum(axis=0)
                        counts[cluster_id] += int(mask.sum())
                inertia += float(((Xc - centers[local_labels]) ** 2).sum())
                communication_bytes += sums.nbytes + counts.nbytes + centers.nbytes

            new_centers = centers.copy()
            nonempty = counts > 0
            new_centers[nonempty] = sums[nonempty] / counts[nonempty, None]
            shift = float(np.linalg.norm(new_centers - centers))
            centers = new_centers
            history.append({"round": rnd + 1, "shift": shift, "inertia": inertia})
            if shift < float(params.get("tol", 1e-4)):
                break

        labels = pairwise_distances_argmin(X, centers)
        return AlgorithmResult(labels=labels, model_state={"centers": centers.tolist(), "rounds": len(history)}, history=history, runtime_sec=time.perf_counter()-start, communication_bytes=communication_bytes)
