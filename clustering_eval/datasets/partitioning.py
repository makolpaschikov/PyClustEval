from __future__ import annotations

import hashlib
import json

import numpy as np


def iid_partition(
    n_samples: int,
    num_clients: int,
    seed: int,
    min_samples_per_client: int = 1,
) -> list[np.ndarray]:
    _validate_partition_request(n_samples, num_clients)
    if n_samples < num_clients * min_samples_per_client:
        raise ValueError(
            f"Cannot give {min_samples_per_client} samples to each of "
            f"{num_clients} clients from {n_samples} samples"
        )
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
    """Create a deterministic label-aware non-IID split."""
    _validate_partition_request(n_samples, num_clients)
    if alpha <= 0:
        raise ValueError("Dirichlet alpha must be greater than zero")
    if y is None:
        return iid_partition(
            n_samples, num_clients, seed, min_samples_per_client=min_samples_per_client
        )

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


def quantity_skew_partition(
    n_samples: int,
    num_clients: int,
    seed: int,
    min_samples_per_client: int = 1,
) -> list[np.ndarray]:
    """Create a deterministic quantity-skew split.

    Client weights increase linearly from 1 to 3.  With five clients this is
    exactly the familiar 10% / 15% / 20% / 25% / 30% target profile before
    integer rounding.  Labels are not consulted.
    """
    _validate_partition_request(n_samples, num_clients)
    if n_samples < num_clients * min_samples_per_client:
        raise ValueError(
            f"Cannot give {min_samples_per_client} samples to each of "
            f"{num_clients} clients from {n_samples} samples"
        )

    weights = np.linspace(1.0, 3.0, num_clients, dtype=np.float64)
    weights /= weights.sum()
    raw_counts = weights * n_samples
    counts = np.floor(raw_counts).astype(int)
    remainder = int(n_samples - counts.sum())
    if remainder:
        fractional_order = np.argsort(-(raw_counts - counts))
        counts[fractional_order[:remainder]] += 1

    if int(counts.min()) < min_samples_per_client:
        counts[:] = min_samples_per_client
        remaining = n_samples - int(counts.sum())
        if remaining < 0:
            raise ValueError("Not enough samples for requested minimum client size")
        if remaining:
            extra_raw = weights * remaining
            extra = np.floor(extra_raw).astype(int)
            counts += extra
            leftover = n_samples - int(counts.sum())
            if leftover:
                fractional_order = np.argsort(-(extra_raw - extra))
                counts[fractional_order[:leftover]] += 1

    rng = np.random.default_rng(seed)
    shuffled = rng.permutation(n_samples)
    parts: list[np.ndarray] = []
    offset = 0
    for count in counts:
        next_offset = offset + int(count)
        parts.append(np.asarray(shuffled[offset:next_offset], dtype=int))
        offset = next_offset
    return parts


def label_limited_partition(
    y: np.ndarray | None,
    n_samples: int,
    num_clients: int,
    seed: int,
    labels_per_client: int = 2,
    min_samples_per_client: int = 1,
    max_attempts: int = 100,
) -> list[np.ndarray]:
    """Create a deterministic split where each client sees few classes.

    Every sample is assigned exactly once.  Each client is allocated at most
    ``labels_per_client`` classes.  The class windows are spread across the
    complete label set so this also works when there are more classes than
    clients (e.g. Digits: 10 classes, 5 clients).
    """
    _validate_partition_request(n_samples, num_clients)
    if labels_per_client < 1:
        raise ValueError("labels_per_client must be at least 1")
    if y is None:
        raise ValueError("label_limited partitioning requires ground-truth labels")
    if n_samples < num_clients * min_samples_per_client:
        raise ValueError(
            f"Cannot give {min_samples_per_client} samples to each of "
            f"{num_clients} clients from {n_samples} samples"
        )

    y = np.asarray(y)
    if len(y) != n_samples:
        raise ValueError("Length of y must equal n_samples")
    classes = np.unique(y)
    if len(classes) == 0:
        raise ValueError("label_limited partitioning requires at least one class")
    labels_per_client = min(labels_per_client, len(classes))

    seed_sequence = np.random.SeedSequence(seed)
    for attempt, child_seed in enumerate(seed_sequence.spawn(max_attempts)):
        rng = np.random.default_rng(child_seed)
        offset = attempt % len(classes)
        allowed: list[set[object]] = []
        for client_id in range(num_clients):
            start = (int(np.floor(client_id * len(classes) / num_clients)) + offset) % len(classes)
            allowed.append({
                classes[(start + step) % len(classes)].item()
                if isinstance(classes[(start + step) % len(classes)], np.generic)
                else classes[(start + step) % len(classes)]
                for step in range(labels_per_client)
            })

        client_indices: list[list[int]] = [[] for _ in range(num_clients)]
        possible = True
        for cls in classes:
            cls_value = cls.item() if isinstance(cls, np.generic) else cls
            eligible = [i for i, labels in enumerate(allowed) if cls_value in labels]
            if not eligible:
                possible = False
                break
            cls_indices = np.flatnonzero(y == cls)
            rng.shuffle(cls_indices)
            splits = np.array_split(cls_indices, len(eligible))
            for client_id, split in zip(eligible, splits):
                client_indices[client_id].extend(int(v) for v in split)

        if possible and min(map(len, client_indices)) >= min_samples_per_client:
            return [
                np.asarray(sorted(indices), dtype=int)
                for indices in client_indices
            ]

    raise RuntimeError(
        "Could not create a label-limited partition satisfying the minimum "
        "client size. Reduce num_clients or min_samples_per_client."
    )


def make_partition(
    mode: str,
    n_samples: int,
    num_clients: int,
    seed: int,
    y: np.ndarray | None = None,
    alpha: float = 0.5,
    min_samples_per_client: int = 1,
    labels_per_client: int = 2,
) -> list[np.ndarray]:
    normalized_mode = mode.lower().strip()
    if normalized_mode == "iid":
        return iid_partition(
            n_samples, num_clients, seed, min_samples_per_client=min_samples_per_client
        )
    if normalized_mode == "dirichlet":
        return dirichlet_partition(
            y, n_samples, num_clients, alpha, seed,
            min_samples_per_client=min_samples_per_client,
        )
    if normalized_mode == "quantity_skew":
        return quantity_skew_partition(
            n_samples, num_clients, seed,
            min_samples_per_client=min_samples_per_client,
        )
    if normalized_mode == "label_limited":
        return label_limited_partition(
            y, n_samples, num_clients, seed,
            labels_per_client=labels_per_client,
            min_samples_per_client=min_samples_per_client,
        )
    raise ValueError(f"Unsupported partitioning mode: {mode}")


def partition_class_counts(
    partition: list[np.ndarray],
    y: np.ndarray | None,
) -> list[dict[str, int]]:
    """Return display/export-friendly class counts for each client."""
    if y is None:
        return [{} for _ in partition]
    y = np.asarray(y)
    result: list[dict[str, int]] = []
    for indices in partition:
        labels, counts = np.unique(y[np.asarray(indices, dtype=int)], return_counts=True)
        result.append({str(label.item() if isinstance(label, np.generic) else label): int(count)
                       for label, count in zip(labels, counts)})
    return result


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
