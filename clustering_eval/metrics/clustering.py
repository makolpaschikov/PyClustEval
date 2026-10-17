from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    adjusted_rand_score,
    normalized_mutual_info_score,
    adjusted_mutual_info_score,
    silhouette_score,
    davies_bouldin_score,
    calinski_harabasz_score,
)


# v2: ARI/NMI on ALL records (-1 is one predicted label); internal geometric
# metrics on ASSIGNED records only. Non-noise coverage must be shown alongside
# internal metrics, because selective assignment can make them look too good.
METRIC_SCHEMA_VERSION = "clustering_metrics_v3_ami_assigned_only"
SILHOUETTE_MAX_POINTS = 2_000
SILHOUETTE_SAMPLING_SEED = 0xC10A5E


def silhouette_reference_indices(n_samples: int) -> np.ndarray:
    """Return a fixed data-index sample shared by every evaluated algorithm.

    Exact (all samples) at n<=2000, deterministic subset otherwise. This
    prevents silhouette's O(n^2) memory/time from exploding on MNIST.
    Unlike sklearn sample_size(X_assigned), identities are fixed BEFORE
    algorithms mark different observations as -1.
    """
    if n_samples <= SILHOUETTE_MAX_POINTS:
        return np.arange(n_samples, dtype=int)
    rng = np.random.default_rng(SILHOUETTE_SAMPLING_SEED)
    return np.sort(rng.choice(n_samples, SILHOUETTE_MAX_POINTS, replace=False))


def safe_metric(fn, default=float("nan")):
    try:
        return float(fn())
    except (ValueError, FloatingPointError, ZeroDivisionError):
        return default


def compute_metrics(
    X: np.ndarray,
    y_true: np.ndarray | None,
    y_pred: np.ndarray,
    requested: list[str],
) -> dict[str, float]:
    labels = np.asarray(y_pred)
    X = np.asarray(X)
    if X.ndim != 2 or labels.ndim != 1 or len(X) != len(labels):
        raise ValueError("X and y_pred dimensions / sample counts must agree")
    if y_true is not None and len(y_true) != len(labels):
        raise ValueError("y_true and y_pred lengths must agree")

    assigned = labels != -1
    X_assigned = X[assigned]
    labels_assigned = labels[assigned]
    clusters = np.unique(labels_assigned)
    valid_geometry = 2 <= len(clusters) < len(labels_assigned)
    # Silhouette is quadratic in the number of points; use a fixed reference
    # subset for scalability and only then filter points labeled as noise.
    reference = silhouette_reference_indices(len(labels))
    reference = reference[assigned[reference]]
    X_silhouette = X[reference]
    y_silhouette = labels[reference]
    silhouette_cluster_count = len(np.unique(y_silhouette))
    valid_silhouette = 2 <= silhouette_cluster_count < len(y_silhouette)

    out: dict[str, float] = {}
    if "ari" in requested:
        out["ari"] = (
            safe_metric(lambda: adjusted_rand_score(y_true, labels))
            if y_true is not None else float("nan")
        )
    if "ami" in requested:
        out["ami"] = (
            safe_metric(lambda: adjusted_mutual_info_score(y_true, labels))
            if y_true is not None else float("nan")
        )
    if "nmi" in requested:
        out["nmi"] = (
            safe_metric(lambda: normalized_mutual_info_score(y_true, labels))
            if y_true is not None else float("nan")
        )
    if "silhouette" in requested:
        out["silhouette"] = (
            safe_metric(lambda: silhouette_score(X_silhouette, y_silhouette))
            if valid_silhouette else float("nan")
        )
    if "davies_bouldin" in requested:
        out["davies_bouldin"] = (
            safe_metric(lambda: davies_bouldin_score(X_assigned, labels_assigned))
            if valid_geometry else float("nan")
        )
    if "calinski_harabasz" in requested:
        out["calinski_harabasz"] = (
            safe_metric(lambda: calinski_harabasz_score(X_assigned, labels_assigned))
            if valid_geometry else float("nan")
        )
    return out
