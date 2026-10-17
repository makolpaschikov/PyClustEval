from __future__ import annotations
from typing import Any
import time
import numpy as np
from ..privacy.aggregate_dp import public_initial_centers, noisy_joint_aggregate, project_centers, stable_noisy_count_threshold
from sklearn.metrics import pairwise_distances_argmin
from .base import ClusteringAlgorithm, AlgorithmResult
from ..federated.environment import participation_entry_for_round
from ..federated.initialization import federated_priority_sample_centers

class FedKMeansNumpy(ClusteringAlgorithm):
    common_param_support = ("k", "rounds", "tol", "seed")
    """Simple synchronous federated KMeans simulation without Flower.

    This implements the same algorithmic contract that a Flower Strategy/ClientApp
    would implement: server sends centers, clients return sums/counts, server aggregates.
    """
    name = "fed_kmeans_numpy"

    def run(self, X: np.ndarray, partition: list[np.ndarray] | None, params: dict[str, Any], seed: int) -> AlgorithmResult:
        if partition is None:
            partition = [np.arange(len(X))]
        k = int(params.get("k", 3))
        rounds = int(params.get("rounds", 20))
        init_participation = participation_entry_for_round(params, 0, len(partition))
        dp = params.get('dp_aggregate')
        if dp is None:
            centers, init_report = federated_priority_sample_centers(
                X, partition, k, seed,
                active_client_ids=init_participation["successful_clients"],
            )
        else:
            centers = public_initial_centers(k, X.shape[1], seed, dp['clip_norm'])
            init_report = {'communication_bytes': 0, 'mode': 'public_data_independent'}
        history: list[dict[str, Any]] = []
        communication_bytes = int(init_report["communication_bytes"])
        start = time.perf_counter()

        for rnd in range(rounds):
            sums = np.zeros_like(centers)
            counts = np.zeros(k, dtype=int)
            inertia = 0.0
            participation = participation_entry_for_round(
                params, rnd, len(partition)
            )
            for client_id in participation["successful_clients"]:
                idx = partition[client_id]
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

            if dp is not None:
                sums, counts = noisy_joint_aggregate(dp, sums, counts)
            new_centers = centers.copy()
            nonempty = counts > (stable_noisy_count_threshold(dp) if dp is not None else 0)
            new_centers[nonempty] = sums[nonempty] / counts[nonempty, None]
            shift = float(np.linalg.norm(new_centers - centers))
            centers = (project_centers(new_centers, dp['clip_norm'])
                       if dp is not None else new_centers)
            history.append({
                "round": rnd + 1,
                "shift": shift,
                "inertia": (None if dp is not None else inertia),
                "selected_clients": participation["selected_clients"],
                "successful_clients": participation["successful_clients"],
                "dropped_clients": participation["dropped_clients"],
            })
            if shift < float(params.get("tol", 1e-4)):
                break

        labels = pairwise_distances_argmin(X, centers)
        return AlgorithmResult(
            labels=labels,
            model_state={
                "centers": centers.tolist(),
                "rounds": len(history),
                "initialization": init_report,
                "backend": "numpy-federated",
            },
            history=history,
            runtime_sec=time.perf_counter()-start,
            communication_bytes=communication_bytes,
        )
