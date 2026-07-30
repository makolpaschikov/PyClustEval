"""
Compare KMeans and DBSCAN on the Iris dataset.

Run:
    python compare_iris_kmeans_dbscan.py

Optional:
    python compare_iris_kmeans_dbscan.py --dbscan-eps 0.6 --dbscan-min-samples 5
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans, DBSCAN
from sklearn.datasets import load_iris
from sklearn.metrics import (
    adjusted_rand_score,
    normalized_mutual_info_score,
    silhouette_score,
    davies_bouldin_score,
    calinski_harabasz_score,
)
from sklearn.preprocessing import StandardScaler


@dataclass
class ClusteringResult:
    algorithm: str
    clusters_found: int
    noise_points: int
    ari: float
    nmi: float
    silhouette: float | None
    davies_bouldin: float | None
    calinski_harabasz: float | None
    runtime_sec: float


def safe_internal_metrics(X: np.ndarray, labels: np.ndarray) -> tuple[float | None, float | None, float | None]:
    """
    Internal clustering metrics require at least 2 clusters.
    For DBSCAN, noise points have label -1, so we exclude them for internal metrics.
    """
    mask = labels != -1
    filtered_labels = labels[mask]
    filtered_X = X[mask]

    unique_clusters = set(filtered_labels.tolist())

    if len(unique_clusters) < 2:
        return None, None, None

    return (
        silhouette_score(filtered_X, filtered_labels),
        davies_bouldin_score(filtered_X, filtered_labels),
        calinski_harabasz_score(filtered_X, filtered_labels),
    )


def evaluate_algorithm(name: str, model, X: np.ndarray, y_true: np.ndarray) -> ClusteringResult:
    start = time.perf_counter()
    labels = model.fit_predict(X)
    runtime_sec = time.perf_counter() - start

    unique_labels = set(labels.tolist())
    clusters_found = len(unique_labels - {-1})
    noise_points = int(np.sum(labels == -1))

    silhouette, davies_bouldin, calinski_harabasz = safe_internal_metrics(X, labels)

    return ClusteringResult(
        algorithm=name,
        clusters_found=clusters_found,
        noise_points=noise_points,
        ari=adjusted_rand_score(y_true, labels),
        nmi=normalized_mutual_info_score(y_true, labels),
        silhouette=silhouette,
        davies_bouldin=davies_bouldin,
        calinski_harabasz=calinski_harabasz,
        runtime_sec=runtime_sec,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=3, help="Number of clusters for KMeans")
    parser.add_argument("--dbscan-eps", type=float, default=0.6, help="DBSCAN eps parameter")
    parser.add_argument("--dbscan-min-samples", type=int, default=5, help="DBSCAN min_samples parameter")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for KMeans")
    args = parser.parse_args()

    iris = load_iris()
    X = iris.data
    y_true = iris.target

    X_scaled = StandardScaler().fit_transform(X)

    algorithms = [
        (
            "KMeans",
            KMeans(
                n_clusters=args.k,
                random_state=args.seed,
                n_init="auto",
            ),
        ),
        (
            "DBSCAN",
            DBSCAN(
                eps=args.dbscan_eps,
                min_samples=args.dbscan_min_samples,
            ),
        ),
    ]

    results = [
        evaluate_algorithm(name, model, X_scaled, y_true)
        for name, model in algorithms
    ]

    df = pd.DataFrame([asdict(result) for result in results])

    metric_columns = [
        "ari",
        "nmi",
        "silhouette",
        "davies_bouldin",
        "calinski_harabasz",
        "runtime_sec",
    ]

    for column in metric_columns:
        df[column] = df[column].astype(float).round(4)

    print("\nIris clustering comparison")
    print("=" * 80)
    print(df.to_string(index=False))

    print("\nHow to read this:")
    print("- ARI and NMI compare clusters with true Iris labels: higher is better.")
    print("- Silhouette and Calinski-Harabasz: higher is better.")
    print("- Davies-Bouldin: lower is better.")
    print("- DBSCAN may mark some points as noise with label -1.")

    best_by_ari = df.sort_values("ari", ascending=False).iloc[0]
    print(f"\nBest by ARI: {best_by_ari['algorithm']} with ARI={best_by_ari['ari']}")


if __name__ == "__main__":
    main()
