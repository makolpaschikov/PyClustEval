"""
Compare the two federated implementations currently available in the project:

1. fed_kmeans_numpy  — local synchronous federated simulation
2. fed_kmeans_flower — distributed execution through Flower Simulation Runtime

The user does not split the dataset manually. The script loads the selected
dataset through DatasetRegistry and creates one shared client partition through
clustering_eval.datasets.partitioning.make_partition.

Run from the project root:

    python compare_federated_kmeans_5_clients.py

Examples:

    python compare_federated_kmeans_5_clients.py --dataset iris --clients 5
    python compare_federated_kmeans_5_clients.py --partition-mode dirichlet --alpha 0.5
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from clustering_eval.algorithms.registry import default_registry as algorithm_registry
from clustering_eval.datasets.partitioning import (
    make_partition,
    partition_fingerprint,
)
from clustering_eval.datasets.registry import default_registry as dataset_registry
from clustering_eval.metrics.clustering import compute_metrics


@dataclass
class ComparisonRow:
    algorithm: str
    backend: str
    dataset: str
    num_clients: int
    partition_mode: str
    partition_id: str
    client_sample_counts: str
    rounds: int
    runtime_sec: float
    communication_bytes: int
    ari: float
    nmi: float
    silhouette: float
    davies_bouldin: float
    calinski_harabasz: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the project's federated NumPy and Flower KMeans "
            "implementations on one identical internal dataset partition."
        )
    )
    parser.add_argument("--dataset", default="iris")
    parser.add_argument("--clients", type=int, default=5)
    parser.add_argument(
        "--partition-mode",
        choices=("iid", "dirichlet"),
        default="iid",
    )
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--tol", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--client-cpus", type=float, default=1.0)
    parser.add_argument("--client-gpus", type=float, default=0.0)
    parser.add_argument(
        "--output",
        default="federated_kmeans_comparison.csv",
        help="CSV file for comparison results.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.clients <= 0:
        raise ValueError("--clients must be greater than zero")
    if args.rounds <= 0:
        raise ValueError("--rounds must be greater than zero")
    if args.k <= 0:
        raise ValueError("--k must be greater than zero")

    # Dataset loading is delegated to the application.
    datasets = dataset_registry()
    dataset = datasets.load(args.dataset)

    # Preprocessing is performed once, before one common partition is created.
    X = StandardScaler().fit_transform(np.asarray(dataset.X, dtype=np.float64))
    y = None if dataset.y is None else np.asarray(dataset.y)

    # The application itself divides the selected dataset among clients.
    # Exactly the same partition object is passed to both implementations.
    partition = make_partition(
        mode=args.partition_mode,
        n_samples=len(X),
        num_clients=args.clients,
        seed=args.seed,
        y=y,
        alpha=args.alpha,
    )
    partition_id = partition_fingerprint(partition)
    client_counts = [int(len(indices)) for indices in partition]

    algorithms = algorithm_registry()
    algorithm_names = (
        "fed_kmeans_numpy",
        "fed_kmeans_flower",
    )

    common_params: dict[str, Any] = {
        "k": args.k,
        "rounds": args.rounds,
        "tol": args.tol,
        "client_cpus": args.client_cpus,
        "client_gpus": args.client_gpus,
    }
    requested_metrics = [
        "ari",
        "nmi",
        "silhouette",
        "davies_bouldin",
        "calinski_harabasz",
    ]

    print(f"Dataset: {dataset.name}")
    print(f"Clients: {args.clients}")
    print(f"Partition mode: {args.partition_mode}")
    print(f"Partition ID: {partition_id}")
    print(f"Client sample counts: {client_counts}")
    print()

    rows: list[ComparisonRow] = []

    for algorithm_name in algorithm_names:
        print(f"Running {algorithm_name}...")
        algorithm = algorithms.get(algorithm_name)
        result = algorithm.run(
            X=X,
            partition=partition,
            params=common_params,
            seed=args.seed,
        )

        metrics = compute_metrics(
            X=X,
            y_true=y,
            y_pred=result.labels,
            requested=requested_metrics,
        )
        backend = str(
            result.model_state.get(
                "backend",
                "numpy-local-federated-simulation",
            )
        )

        rows.append(
            ComparisonRow(
                algorithm=algorithm_name,
                backend=backend,
                dataset=dataset.name,
                num_clients=args.clients,
                partition_mode=args.partition_mode,
                partition_id=partition_id,
                client_sample_counts=",".join(map(str, client_counts)),
                rounds=int(result.model_state.get("rounds", len(result.history))),
                runtime_sec=float(result.runtime_sec),
                communication_bytes=int(result.communication_bytes),
                ari=float(metrics["ari"]),
                nmi=float(metrics["nmi"]),
                silhouette=float(metrics["silhouette"]),
                davies_bouldin=float(metrics["davies_bouldin"]),
                calinski_harabasz=float(metrics["calinski_harabasz"]),
            )
        )

    frame = pd.DataFrame([asdict(row) for row in rows])
    numeric_columns = [
        "runtime_sec",
        "ari",
        "nmi",
        "silhouette",
        "davies_bouldin",
        "calinski_harabasz",
    ]
    frame[numeric_columns] = frame[numeric_columns].round(4)
    frame.to_csv(args.output, index=False)

    print("\nFederated comparison")
    print("=" * 120)
    print(frame.to_string(index=False))
    print(f"\nResults saved to: {args.output}")
    print(
        "\nNote: both runs use a federated sums/counts protocol and the same "
        "application-generated partition. fed_kmeans_flower runs through "
        "Flower; fed_kmeans_numpy is the local reference implementation."
    )


if __name__ == "__main__":
    main()
