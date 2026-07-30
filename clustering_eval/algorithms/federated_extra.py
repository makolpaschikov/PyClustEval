from __future__ import annotations

import time
from typing import Any

import numpy as np

from .base import AlgorithmResult, ClusteringAlgorithm


def _init_centers(X: np.ndarray, k: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return X[rng.choice(len(X), size=k, replace=False)].astype(float).copy()


def _squared_distances(X: np.ndarray, centers: np.ndarray) -> np.ndarray:
    return np.maximum(
        ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2),
        1e-12,
    )


class FedFuzzyCMeansNumpy(ClusteringAlgorithm):
    """Synchronous federated Fuzzy C-Means using sufficient statistics."""

    name = "fed_fuzzy_cmeans_numpy"
    is_federated = True
    execution_backend = "numpy-federated"

    def run(
        self,
        X: np.ndarray,
        partition: list[np.ndarray] | None,
        params: dict[str, Any],
        seed: int,
    ) -> AlgorithmResult:
        X = np.asarray(X, dtype=np.float64)
        partition = partition or [np.arange(len(X))]
        k = int(params.get("k", params.get("n_clusters", 3)))
        rounds = int(params.get("rounds", 20))
        tol = float(params.get("tol", 1e-4))
        m = float(params.get("fuzziness", 2.0))
        if m <= 1:
            raise ValueError("fuzziness must be greater than 1")

        centers = _init_centers(X, k, seed)
        history: list[dict[str, Any]] = []
        communication = 0
        started = time.perf_counter()

        for rnd in range(rounds):
            weighted_sums = np.zeros_like(centers)
            weights = np.zeros(k, dtype=np.float64)
            objective = 0.0

            for indices in partition:
                Xc = X[indices]
                if len(Xc) == 0:
                    continue
                dist2 = _squared_distances(Xc, centers)
                inv = dist2 ** (-1.0 / (m - 1.0))
                membership = inv / inv.sum(axis=1, keepdims=True)
                um = membership**m
                weighted_sums += um.T @ Xc
                weights += um.sum(axis=0)
                objective += float((um * dist2).sum())
                communication += centers.nbytes + weighted_sums.nbytes + weights.nbytes

            updated = centers.copy()
            nonempty = weights > 0
            updated[nonempty] = weighted_sums[nonempty] / weights[nonempty, None]
            shift = float(np.linalg.norm(updated - centers))
            centers = updated
            history.append({"round": rnd + 1, "shift": shift, "objective": objective})
            if shift < tol:
                break

        labels = np.argmin(_squared_distances(X, centers), axis=1)
        return AlgorithmResult(
            labels=labels,
            model_state={
                "centers": centers.tolist(),
                "rounds": len(history),
                "fuzziness": m,
                "backend": "numpy-federated",
            },
            history=history,
            runtime_sec=time.perf_counter() - started,
            communication_bytes=communication,
        )


class FedDiagonalGMMNumpy(ClusteringAlgorithm):
    """Federated EM for a Gaussian mixture model with diagonal covariance."""

    name = "fed_gmm_diag_numpy"
    is_federated = True
    execution_backend = "numpy-federated"

    def run(
        self,
        X: np.ndarray,
        partition: list[np.ndarray] | None,
        params: dict[str, Any],
        seed: int,
    ) -> AlgorithmResult:
        X = np.asarray(X, dtype=np.float64)
        partition = partition or [np.arange(len(X))]
        k = int(params.get("k", params.get("n_clusters", 3)))
        rounds = int(params.get("rounds", 20))
        tol = float(params.get("tol", 1e-4))
        reg = float(params.get("reg_covar", 1e-6))

        means = _init_centers(X, k, seed)
        variances = np.tile(np.var(X, axis=0) + reg, (k, 1))
        weights = np.full(k, 1.0 / k)
        history: list[dict[str, Any]] = []
        communication = 0
        started = time.perf_counter()

        for rnd in range(rounds):
            nk = np.zeros(k)
            sum_x = np.zeros_like(means)
            sum_x2 = np.zeros_like(means)
            log_likelihood = 0.0

            for indices in partition:
                Xc = X[indices]
                if len(Xc) == 0:
                    continue
                log_prob = []
                for cluster in range(k):
                    diff = Xc - means[cluster]
                    log_det = np.log(2.0 * np.pi * variances[cluster]).sum()
                    quadratic = (diff * diff / variances[cluster]).sum(axis=1)
                    log_prob.append(np.log(weights[cluster] + 1e-15) - 0.5 * (log_det + quadratic))
                log_prob = np.stack(log_prob, axis=1)
                maximum = log_prob.max(axis=1, keepdims=True)
                exp_prob = np.exp(log_prob - maximum)
                normalizer = exp_prob.sum(axis=1, keepdims=True)
                resp = exp_prob / normalizer
                log_likelihood += float((maximum[:, 0] + np.log(normalizer[:, 0])).sum())

                nk += resp.sum(axis=0)
                sum_x += resp.T @ Xc
                sum_x2 += resp.T @ (Xc * Xc)
                communication += (
                    means.nbytes + variances.nbytes + weights.nbytes
                    + nk.nbytes + sum_x.nbytes + sum_x2.nbytes
                )

            safe_nk = np.maximum(nk, 1e-12)
            new_weights = safe_nk / safe_nk.sum()
            new_means = sum_x / safe_nk[:, None]
            new_variances = np.maximum(
                sum_x2 / safe_nk[:, None] - new_means * new_means,
                reg,
            )
            shift = float(np.linalg.norm(new_means - means))
            means, variances, weights = new_means, new_variances, new_weights
            history.append(
                {"round": rnd + 1, "shift": shift, "log_likelihood": log_likelihood}
            )
            if shift < tol:
                break

        scores = []
        for cluster in range(k):
            diff = X - means[cluster]
            log_det = np.log(2.0 * np.pi * variances[cluster]).sum()
            quadratic = (diff * diff / variances[cluster]).sum(axis=1)
            scores.append(np.log(weights[cluster] + 1e-15) - 0.5 * (log_det + quadratic))
        labels = np.argmax(np.stack(scores, axis=1), axis=1)

        return AlgorithmResult(
            labels=labels,
            model_state={
                "means": means.tolist(),
                "variances": variances.tolist(),
                "weights": weights.tolist(),
                "rounds": len(history),
                "backend": "numpy-federated",
            },
            history=history,
            runtime_sec=time.perf_counter() - started,
            communication_bytes=communication,
        )
