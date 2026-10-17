"""Pre-registered, label-free tuning and partition diagnostics for TimeEval v2.

These are SIMULATION diagnostics: label distributions are read by the trusted
benchmark evaluator, not obtained through a privacy-preserving FL protocol.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.spatial.distance import jensenshannon
from sklearn.cluster import KMeans, DBSCAN
from sklearn.metrics import silhouette_score
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler


def estimate_k_unlabeled(
    X: np.ndarray, *, seed: int, minimum: int = 2,
    maximum: int = 12, sample_size: int = 1000, budget: int = 8,
) -> tuple[int, dict[str, Any]]:
    """Choose k on a deterministic subset WITHOUT using y_true.

    Explicitly exploratory: maximizing in-sample silhouette can prefer too few
    clusters and must not be interpreted as recovering the true class count.
    """
    X = np.asarray(X, dtype=np.float64)
    if X.ndim != 2 or len(X) < minimum + 2 or not np.isfinite(X).all():
        raise ValueError("Cannot estimate k from the supplied finite 2-D data")
    rng = np.random.default_rng(seed ^ 0x51B07)
    idx = np.sort(rng.choice(len(X), min(len(X), sample_size), replace=False))
    subset = StandardScaler().fit_transform(X[idx])
    maximum = min(maximum, len(subset) - 2)
    if minimum > maximum or budget < 1:
        raise ValueError("No valid unsupervised k candidates")
    values = np.unique(np.rint(np.linspace(minimum, maximum, min(budget, maximum-minimum+1))).astype(int))
    candidates: list[dict[str, float | int]] = []
    for k in values.tolist():
        labels = KMeans(n_clusters=k, n_init=3, max_iter=100, random_state=seed).fit_predict(subset)
        score = float(silhouette_score(subset, labels)) if len(np.unique(labels)) > 1 else float('-inf')
        candidates.append({"k": int(k), "silhouette": score})
    chosen = max(candidates, key=lambda item: (item["silhouette"], -item["k"]))
    return int(chosen["k"]), {
        "method": "label_free_kmeans_silhouette_v1",
        "sample_count": len(subset), "seed": seed, "budget": len(candidates),
        "candidates": candidates,
        "limitations": "In-sample silhouette, not independent validation; favoring k=2 is possible.",
    }


def tune_dbscan_unlabeled(
    X: np.ndarray, *, seed: int, sample_size: int = 1000,
    min_samples_options: tuple[int, ...] = (5, 10),
    quantiles: tuple[float, ...] = (0.35, 0.5, 0.65, 0.8),
    min_coverage: float = 0.5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Tune DBSCAN using geometry/coverage only (NO ground-truth labels).

    Scores are *not* independent test scores. Report candidate diagnostics.
    This controls search budgets but does not equalize compute cost between
    fundamentally different algorithm families.
    """
    X = np.asarray(X, dtype=np.float64)
    rng = np.random.default_rng(seed ^ 0xDB5CA)
    subset = X[np.sort(rng.choice(len(X), min(len(X), sample_size), replace=False))]
    candidates: list[dict[str, Any]] = []
    for m in min_samples_options:
        if m < 2 or m >= len(subset):
            continue
        knn = NearestNeighbors(n_neighbors=m, metric="euclidean").fit(subset)
        kth = knn.kneighbors(subset, return_distance=True)[0][:, -1]
        for q in quantiles:
            eps = float(np.quantile(kth, q))
            if eps <= 0:
                continue
            labels = DBSCAN(eps=eps, min_samples=m).fit_predict(subset)
            assigned = labels != -1
            coverage = float(np.mean(assigned))
            n_clusters = len(set(labels[assigned].tolist()))
            valid = coverage >= min_coverage and 2 <= n_clusters < int(assigned.sum())
            silhouette = float(silhouette_score(subset[assigned], labels[assigned])) if valid else None
            # Penalize an apparently excellent clusterer which rejects half the dataset.
            score = float(silhouette * coverage) if valid else None
            candidates.append({"min_samples": m, "eps_quantile": q, "eps": eps,
                               "coverage": coverage, "clusters": n_clusters,
                               "silhouette": silhouette, "tuning_score": score})
    viable = [r for r in candidates if r["tuning_score"] is not None]
    if not viable:
        return {}, {"method": "dbscan_unlabeled_silhouette_coverage_v1",
                    "selected": None, "fallback": "default parameters, no viable tuning candidate",
                    "sample_count": len(subset), "candidates": candidates}
    best = max(viable, key=lambda r: (r["tuning_score"], r["coverage"], -r["min_samples"]))
    return {"eps": best["eps"], "min_samples": best["min_samples"]}, {
        "method": "dbscan_unlabeled_silhouette_coverage_v1",
        "sample_count": len(subset), "min_coverage": min_coverage,
        "selected": best, "candidates": candidates,
        "limitations": "Parameters selected on tuning subset, not independent held-out score.",
    }


def measure_partition_heterogeneity(
    partition: list[np.ndarray], y_true: np.ndarray | None,
) -> dict[str, Any]:
    """Report realized (not nominal) class heterogeneity; labels evaluator-only."""
    counts = np.array([len(c) for c in partition], dtype=float)
    if np.any(counts <= 0):
        raise ValueError("Clients must be nonempty")
    out: dict[str, Any] = {
        "n_clients": len(partition),
        "size_cv": float(np.std(counts) / np.mean(counts)),
        "min_size": int(counts.min()), "max_size": int(counts.max()),
    }
    if y_true is None:
        return out
    y_true = np.asarray(y_true)
    unique, inv = np.unique(y_true, return_inverse=True)
    distribution = np.bincount(inv, minlength=len(unique)).astype(float)
    distribution /= distribution.sum()
    p = np.zeros((len(partition), len(unique)), dtype=float)
    for i, inds in enumerate(partition):
        bincounts = np.bincount(inv[np.asarray(inds, dtype=int)], minlength=len(unique))
        p[i] = bincounts / bincounts.sum()
    weights = counts / counts.sum()
    divergence = np.array([jensenshannon(row, distribution, base=2.0) ** 2 for row in p])
    out.update({
        "class_js_divergence_weighted_bits": float(np.sum(weights * divergence)),
        "class_js_divergence_max_bits": float(np.max(divergence)),
        "class_support_min": int((p > 0).sum(axis=1).min()),
        "class_support_mean": float(np.mean((p > 0).sum(axis=1))),
        "client_class_distribution": p.tolist(),
        "label_dependency": "diagnostic_only_nonprivate_central_evaluator",
    })
    return out
