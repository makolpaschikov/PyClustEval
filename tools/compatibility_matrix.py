from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np

from clustering_eval.algorithms.registry import default_registry as algorithm_registry
from clustering_eval.application.comparison_service import _preprocess_algorithm_input, _is_federated
from clustering_eval.datasets.partitioning import make_partition
from clustering_eval.datasets.registry import default_registry as dataset_registry
from clustering_eval.metrics.clustering import compute_metrics


DATASETS = ("iris", "wine", "blobs", "digits")
COMMON = {
    "rounds": 10,
    "tol": 1e-4,
    "max_iter": 300,
    "density_min_samples": 4,
    "client_cpus": 1.0,
    "client_gpus": 0.0,
}


def _status(labels: np.ndarray) -> tuple[str, int, float, float]:
    unique, counts = np.unique(labels, return_counts=True)
    non_noise = [(int(v), int(c)) for v, c in zip(unique, counts) if int(v) != -1]
    noise = sum(int(c) for v, c in zip(unique, counts) if int(v) == -1)
    non_noise_total = sum(c for _, c in non_noise)
    dominant = max((c for _, c in non_noise), default=0) / non_noise_total if non_noise_total else 0.0
    if len(non_noise) < 2:
        status = "degenerate"
    elif dominant >= 0.95:
        status = "near_degenerate"
    else:
        status = "ok"
    return status, len(non_noise), noise / len(labels), dominant


def run(include_flower: bool = False) -> list[dict[str, object]]:
    algorithms = algorithm_registry()
    datasets = dataset_registry()
    rows: list[dict[str, object]] = []

    for dataset_name in DATASETS:
        dataset = datasets.load(dataset_name)
        X_raw = np.asarray(dataset.X, dtype=np.float64)
        y = None if dataset.y is None else np.asarray(dataset.y)
        k = len(np.unique(y)) if y is not None else 3

        for algorithm_name in algorithms.names():
            algorithm = algorithms.get(algorithm_name)
            federated = _is_federated(algorithm_name, algorithm)
            if "flower" in algorithm_name.lower() and not include_flower:
                continue
            partition_modes = ("iid", "dirichlet") if federated else ("local",)

            for partition_mode in partition_modes:
                try:
                    X = _preprocess_algorithm_input(X_raw, algorithm)
                    partition = None
                    if federated:
                        partition = make_partition(
                            partition_mode,
                            len(X),
                            5,
                            42,
                            y=y,
                            alpha=0.5,
                            min_samples_per_client=3,
                        )
                    params = {
                        "k": k,
                        "n_clusters": k,
                        **COMMON,
                    }
                    params.update(dict(getattr(algorithm, "default_params", {}) or {}))
                    result = algorithm.run(X, partition, params, 42)
                    labels = np.asarray(result.labels)
                    metrics = compute_metrics(X, y, labels, ["ari", "nmi", "silhouette"])
                    status, found, noise, dominant = _status(labels)
                    rows.append({
                        "dataset": dataset_name,
                        "partition": partition_mode,
                        "algorithm": algorithm_name,
                        "status": status,
                        "clusters_found": found,
                        "noise_fraction": noise,
                        "dominant_cluster_fraction": dominant,
                        "ari": metrics.get("ari"),
                        "nmi": metrics.get("nmi"),
                        "silhouette": metrics.get("silhouette"),
                        "runtime_sec": result.runtime_sec,
                        "preprocessing": getattr(algorithm, "input_preprocessing", "standard"),
                        "error": "",
                    })
                except Exception as exc:  # matrix should report failures, not stop at first one
                    rows.append({
                        "dataset": dataset_name,
                        "partition": partition_mode,
                        "algorithm": algorithm_name,
                        "status": "error",
                        "clusters_found": "",
                        "noise_fraction": "",
                        "dominant_cluster_fraction": "",
                        "ari": "",
                        "nmi": "",
                        "silhouette": "",
                        "runtime_sec": "",
                        "preprocessing": getattr(algorithm, "input_preprocessing", "standard"),
                        "error": f"{type(exc).__name__}: {exc}",
                    })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="compatibility_matrix.csv")
    parser.add_argument("--include-flower", action="store_true")
    args = parser.parse_args()
    rows = run(include_flower=args.include_flower)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
    print(f"wrote {len(rows)} cases to {output}")
    print("status counts:", counts)


if __name__ == "__main__":
    main()
