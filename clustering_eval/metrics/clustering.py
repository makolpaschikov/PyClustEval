from __future__ import annotations
import numpy as np
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, silhouette_score, davies_bouldin_score, calinski_harabasz_score


def safe_metric(fn, default=float('nan')):
    try:
        return float(fn())
    except Exception:
        return default


def compute_metrics(X: np.ndarray, y_true: np.ndarray | None, y_pred: np.ndarray, requested: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    unique = set(np.unique(y_pred).tolist())
    non_noise_labels = unique - {-1}
    has_multiple_clusters = len(non_noise_labels) >= 2

    if "ari" in requested:
        out["ari"] = safe_metric(lambda: adjusted_rand_score(y_true, y_pred)) if y_true is not None else float('nan')
    if "nmi" in requested:
        out["nmi"] = safe_metric(lambda: normalized_mutual_info_score(y_true, y_pred)) if y_true is not None else float('nan')
    if "silhouette" in requested:
        out["silhouette"] = safe_metric(lambda: silhouette_score(X, y_pred)) if has_multiple_clusters else float('nan')
    if "davies_bouldin" in requested:
        out["davies_bouldin"] = safe_metric(lambda: davies_bouldin_score(X, y_pred)) if has_multiple_clusters else float('nan')
    if "calinski_harabasz" in requested:
        out["calinski_harabasz"] = safe_metric(lambda: calinski_harabasz_score(X, y_pred)) if has_multiple_clusters else float('nan')
    return out
