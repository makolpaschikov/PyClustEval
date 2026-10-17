from __future__ import annotations

import time
from typing import Any

import numpy as np
from ..privacy.aggregate_dp import public_initial_centers, noisy_joint_aggregate, project_centers, stable_noisy_count_threshold

from .base import AlgorithmResult, ClusteringAlgorithm
from ..federated.environment import participation_entry_for_round
from ..federated.initialization import federated_priority_sample_centers, federated_global_variance



def _squared_distances(X: np.ndarray, centers: np.ndarray) -> np.ndarray:
    return np.maximum(
        ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2),
        1e-12,
    )


class FedFuzzyCMeansNumpy(ClusteringAlgorithm):
    common_param_support = ("k", "rounds", "tol", "seed")
    """Synchronous federated Fuzzy C-Means using sufficient statistics."""

    name = "fed_fuzzy_cmeans_numpy"
    is_federated = True
    default_params = {"fuzziness": 2.0}
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
        communication = int(init_report["communication_bytes"])
        started = time.perf_counter()

        for rnd in range(rounds):
            weighted_sums = np.zeros_like(centers)
            weights = np.zeros(k, dtype=np.float64)
            objective = 0.0

            participation = participation_entry_for_round(
                params, rnd, len(partition)
            )
            for client_id in participation["successful_clients"]:
                indices = partition[client_id]
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

            if dp is not None:
                weighted_sums, weights = noisy_joint_aggregate(dp, weighted_sums, weights)
            updated = centers.copy()
            nonempty = weights > (stable_noisy_count_threshold(dp) if dp is not None else 0)
            updated[nonempty] = weighted_sums[nonempty] / weights[nonempty, None]
            shift = float(np.linalg.norm(updated - centers))
            centers = (project_centers(updated, dp['clip_norm'])
                       if dp is not None else updated)
            history.append({
                "round": rnd + 1,
                "shift": shift,
                "objective": (None if dp is not None else objective),
                "selected_clients": participation["selected_clients"],
                "successful_clients": participation["successful_clients"],
                "dropped_clients": participation["dropped_clients"],
            })
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
                "initialization": init_report,
            },
            history=history,
            runtime_sec=time.perf_counter() - started,
            communication_bytes=communication,
        )


class FedDiagonalGMMNumpy(ClusteringAlgorithm):
    common_param_support = ("k", "rounds", "tol", "seed")
    """Federated EM for a Gaussian mixture model with diagonal covariance."""

    name = "fed_gmm_diag_numpy"
    is_federated = True
    default_params = {"reg_covar": 1e-6}
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

        init_participation = participation_entry_for_round(params, 0, len(partition))
        dp = params.get('dp_aggregate')
        if dp is None:
            means, means_init_report = federated_priority_sample_centers(
                X, partition, k, seed,
                active_client_ids=init_participation["successful_clients"],
            )
            variance0, variance_init_report = federated_global_variance(
                X, partition,
                active_client_ids=init_participation["successful_clients"],
                reg_covar=reg,
            )
        else:
            means = public_initial_centers(k, X.shape[1], seed, dp['clip_norm'])
            variance0 = np.ones(X.shape[1])
            means_init_report = variance_init_report = {'communication_bytes': 0, 'mode': 'public_data_independent'}
            reg = max(reg, 0.05)
        variances = np.tile(variance0, (k, 1))
        weights = np.full(k, 1.0 / k)
        history: list[dict[str, Any]] = []
        communication = int(means_init_report["communication_bytes"]) + int(variance_init_report["communication_bytes"])
        started = time.perf_counter()

        for rnd in range(rounds):
            nk = np.zeros(k)
            sum_x = np.zeros_like(means)
            sum_x2 = np.zeros_like(means)
            log_likelihood = 0.0

            participation = participation_entry_for_round(
                params, rnd, len(partition)
            )
            for client_id in participation["successful_clients"]:
                indices = partition[client_id]
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

            if dp is not None:
                nk, sum_x, sum_x2 = noisy_joint_aggregate(dp, nk, sum_x, sum_x2)
            safe_nk = np.maximum(nk, stable_noisy_count_threshold(dp) if dp is not None else 1e-12)
            new_weights = safe_nk / safe_nk.sum()
            new_means = sum_x / safe_nk[:, None]
            new_variances = np.maximum(
                sum_x2 / safe_nk[:, None] - new_means * new_means,
                reg,
            )
            shift = float(np.linalg.norm(new_means - means))
            if dp is not None:
                new_means = project_centers(new_means, dp['clip_norm'])
                new_variances = np.clip(new_variances, reg, dp['clip_norm']**2)
            means, variances, weights = new_means, new_variances, new_weights
            history.append(
                {
                    "round": rnd + 1,
                    "shift": shift,
                    "log_likelihood": (None if dp is not None else log_likelihood),
                    "selected_clients": participation["selected_clients"],
                    "successful_clients": participation["successful_clients"],
                    "dropped_clients": participation["dropped_clients"],
                }
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
                "initialization": {
                    "means": means_init_report,
                    "variance": variance_init_report,
                },
            },
            history=history,
            runtime_sec=time.perf_counter() - started,
            communication_bytes=communication,
        )
