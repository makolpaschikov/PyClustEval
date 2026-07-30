from __future__ import annotations

import hashlib
import json

import numpy as np


def iid_partition(n_samples: int, num_clients: int, seed: int) -> list[np.ndarray]:
    _validate_partition_request(n_samples, num_clients)
    rng = np.random.default_rng(seed)
    indices = rng.permutation(n_samples)
    return [part.astype(int) for part in np.array_split(indices, num_clients)]


def dirichlet_partition(
    y: np.ndarray | None,
    n_samples: int,
    num_clients: int,
    alpha: float,
    seed: int,
    min_samples_per_client: int = 1,
    max_attempts: int = 100,
) -> list[np.ndarray]:
    """Create a deterministic label-aware non-IID split.

    The same dataset labels, seed, client count, and alpha always produce the
    same partition. Empty clients are rejected and the split is retried with
    deterministic child seeds. If labels are unavailable, IID is used.
    """
    _validate_partition_request(n_samples, num_clients)
    if alpha <= 0:
        raise ValueError("Dirichlet alpha must be greater than zero")
    if y is None:
        return iid_partition(n_samples, num_clients, seed)

    y = np.asarray(y)
    if len(y) != n_samples:
        raise ValueError("Length of y must equal n_samples")

    seed_sequence = np.random.SeedSequence(seed)
    for child_seed in seed_sequence.spawn(max_attempts):
        rng = np.random.default_rng(child_seed)
        client_indices: list[list[int]] = [[] for _ in range(num_clients)]

        for cls in np.unique(y):
            cls_indices = np.flatnonzero(y == cls)
            rng.shuffle(cls_indices)
            proportions = rng.dirichlet(np.full(num_clients, alpha))
            counts = rng.multinomial(len(cls_indices), proportions)

            offset = 0
            for client_id, count in enumerate(counts):
                next_offset = offset + int(count)
                client_indices[client_id].extend(
                    cls_indices[offset:next_offset].tolist()
                )
                offset = next_offset

        if min(map(len, client_indices)) >= min_samples_per_client:
            return [
                np.asarray(sorted(indices), dtype=int)
                for indices in client_indices
            ]

    raise RuntimeError(
        "Could not create a Dirichlet partition without empty clients. "
        "Increase alpha, reduce num_clients, or lower min_samples_per_client."
    )


def make_partition(
    mode: str,
    n_samples: int,
    num_clients: int,
    seed: int,
    y: np.ndarray | None = None,
    alpha: float = 0.5,
) -> list[np.ndarray]:
    normalized_mode = mode.lower().strip()
    if normalized_mode == "iid":
        return iid_partition(n_samples, num_clients, seed)
    if normalized_mode == "dirichlet":
        return dirichlet_partition(y, n_samples, num_clients, alpha, seed)
    raise ValueError(f"Unsupported partitioning mode: {mode}")


def partition_fingerprint(partition: list[np.ndarray]) -> str:
    """Return a stable identifier used to verify fair algorithm comparison."""
    payload = [np.asarray(indices, dtype=int).tolist() for indices in partition]
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


def _validate_partition_request(n_samples: int, num_clients: int) -> None:
    if n_samples <= 0:
        raise ValueError("n_samples must be greater than zero")
    if num_clients <= 0:
        raise ValueError("num_clients must be greater than zero")
    if num_clients > n_samples:
        raise ValueError(
            f"num_clients ({num_clients}) cannot exceed n_samples ({n_samples})"
        )
