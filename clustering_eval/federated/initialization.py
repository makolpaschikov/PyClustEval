from __future__ import annotations

"""Federated-safe initialization helpers for native/Flower benchmark adapters.

The helpers simulate messages that clients could compute locally.  The server
never needs to sample from the full raw ``X`` matrix directly.
"""

import hashlib
from typing import Any, Iterable

import numpy as np


def _priority(seed: int, sample_index: int) -> int:
    """Stable pseudo-random 64-bit priority for one global sample id."""
    payload = f"{int(seed)}:{int(sample_index)}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def _active_clients(partition: list[np.ndarray], active_client_ids: Iterable[int] | None) -> list[int]:
    if active_client_ids is None:
        ids = list(range(len(partition)))
    else:
        ids = sorted({int(v) for v in active_client_ids})
    if not ids:
        raise ValueError("Federated initialization requires at least one active client")
    if ids[0] < 0 or ids[-1] >= len(partition):
        raise ValueError("Federated initialization received an invalid client id")
    return ids


def federated_priority_sample_centers(
    X: np.ndarray,
    partition: list[np.ndarray],
    k: int,
    seed: int,
    *,
    active_client_ids: Iterable[int] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Choose ``k`` initial centers through client-local candidate messages.

    Every sample gets a deterministic pseudo-random priority derived from
    ``(seed, global_sample_id)``.  Each active client sends only its local top-k
    candidates.  The server then chooses the global top-k candidates from those
    messages.  Because a global top-k item must also be in its client's local
    top-k, the result is independent of how the same samples are partitioned
    when the set of active clients is unchanged.
    """
    X = np.asarray(X, dtype=np.float64)
    if k <= 0:
        raise ValueError("k must be positive")
    client_ids = _active_clients(partition, active_client_ids)

    messages: list[tuple[int, int, np.ndarray]] = []
    per_client_counts: dict[int, int] = {}
    communication_bytes = 0
    for client_id in client_ids:
        indices = np.asarray(partition[client_id], dtype=int)
        if len(indices) == 0:
            per_client_counts[client_id] = 0
            continue
        ranked = sorted((_priority(seed, int(idx)), int(idx)) for idx in indices)
        selected = ranked[: min(k, len(ranked))]
        per_client_counts[client_id] = len(selected)
        for priority, sample_index in selected:
            vector = np.asarray(X[sample_index], dtype=np.float64).copy()
            messages.append((priority, sample_index, vector))
            communication_bytes += int(vector.nbytes + 16)  # priority + sample id

    if len(messages) < k:
        raise ValueError(
            f"Only {len(messages)} initialization candidates are available from "
            f"active clients, but k={k}"
        )
    messages.sort(key=lambda item: (item[0], item[1]))
    chosen = messages[:k]
    centers = np.stack([item[2] for item in chosen], axis=0)
    selected_indices = [int(item[1]) for item in chosen]
    return centers, {
        "method": "federated_priority_topk_v1",
        "active_clients": client_ids,
        "client_candidate_counts": per_client_counts,
        "candidate_count": len(messages),
        "selected_sample_indices": selected_indices,
        "communication_bytes": communication_bytes,
    }


def federated_global_variance(
    X: np.ndarray,
    partition: list[np.ndarray],
    *,
    active_client_ids: Iterable[int] | None = None,
    reg_covar: float = 0.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Aggregate global per-feature variance from client sufficient statistics."""
    X = np.asarray(X, dtype=np.float64)
    client_ids = _active_clients(partition, active_client_ids)
    count = 0
    total_sum = np.zeros(X.shape[1], dtype=np.float64)
    total_sum2 = np.zeros(X.shape[1], dtype=np.float64)
    communication_bytes = 0
    per_client_counts: dict[int, int] = {}
    for client_id in client_ids:
        indices = np.asarray(partition[client_id], dtype=int)
        local = X[indices]
        n = int(len(local))
        per_client_counts[client_id] = n
        if n == 0:
            continue
        local_sum = local.sum(axis=0)
        local_sum2 = (local * local).sum(axis=0)
        count += n
        total_sum += local_sum
        total_sum2 += local_sum2
        communication_bytes += int(local_sum.nbytes + local_sum2.nbytes + 8)

    if count <= 0:
        raise ValueError("Federated variance initialization has no active samples")
    mean = total_sum / count
    variance = np.maximum(total_sum2 / count - mean * mean, float(reg_covar))
    return variance, {
        "method": "federated_moments_v1",
        "active_clients": client_ids,
        "active_samples": count,
        "client_sample_counts": per_client_counts,
        "communication_bytes": communication_bytes,
    }
