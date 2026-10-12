from __future__ import annotations

from typing import Any

import numpy as np

from ..algorithms.registry import default_registry as default_algorithm_registry
from ..datasets.partitioning import make_partition, partition_fingerprint
from ..datasets.registry import default_registry as default_dataset_registry
from ..metrics.clustering import compute_metrics
from ..results.store import ResultStore
from ..application.comparison_service import _preprocess_algorithm_input
from .planner import ExperimentSpec


class ExperimentRunner:
    def __init__(self, metrics: list[str], output_dir: str) -> None:
        self.datasets = default_dataset_registry()
        self.algorithms = default_algorithm_registry()
        self.metrics = metrics
        self.store = ResultStore(output_dir)

    def run_one(self, spec: ExperimentSpec) -> dict[str, Any]:
        dataset_params = dict(spec.dataset_params)
        dataset_params.setdefault("random_state", spec.seed)
        dataset = self.datasets.load(spec.dataset_name, dataset_params)

        algorithm = self.algorithms.get(spec.algorithm_name)
        min_client_samples = max(
            3, int(getattr(algorithm, "min_client_samples", 1))
        )

        # The partition depends only on dataset/run settings, never on algorithm.
        # A common minimum of 3 samples/client keeps the built-in author adapters
        # on the same admissible partition space (NN-FC is the strictest one).
        partition = make_partition(
            mode=spec.partition_mode,
            n_samples=len(dataset.X),
            num_clients=spec.num_clients,
            seed=spec.seed,
            y=dataset.y,
            alpha=spec.dirichlet_alpha or 0.5,
            min_samples_per_client=min_client_samples,
        )
        partition_id = partition_fingerprint(partition)

        y = None if dataset.y is None else np.asarray(dataset.y)
        benchmark_k = int(
            spec.algorithm_params.get(
                "n_clusters",
                spec.algorithm_params.get(
                    "k", len(np.unique(y)) if y is not None else 3
                ),
            )
        )
        params = {
            "k": benchmark_k,
            "n_clusters": benchmark_k,
            "rounds": 10,
            "tol": 1e-4,
            "max_iter": 300,
            "client_cpus": 1.0,
            "client_gpus": 0.0,
        }
        params.update(dict(getattr(algorithm, "default_params", {}) or {}))
        params.update(spec.algorithm_params)

        X = _preprocess_algorithm_input(np.asarray(dataset.X, dtype=float), algorithm)
        result = algorithm.run(X, partition, params, spec.seed)
        metric_values = compute_metrics(
            X,
            dataset.y,
            result.labels,
            self.metrics,
        )
        row = {
            **spec.asdict(),
            **metric_values,
            "partition_id": partition_id,
            "client_sample_counts": [len(indices) for indices in partition],
            "runtime_sec": result.runtime_sec,
            "communication_bytes": result.communication_bytes,
            "rounds": result.model_state.get("rounds"),
            "execution_backend": result.model_state.get("backend", "local"),
            "n_samples": len(dataset.X),
            "n_features": dataset.X.shape[1],
            "preprocessing": getattr(algorithm, "input_preprocessing", "standard"),
            "benchmark_k": benchmark_k,
            "effective_algorithm_params": params,
            "min_samples_per_client": min_client_samples,
        }
        self.store.add(row)
        self.store.write_jsonl(
            "history.jsonl",
            {
                "spec": spec.asdict(),
                "partition_id": partition_id,
                "client_indices": [indices.tolist() for indices in partition],
                "history": result.history,
                "model_state": result.model_state,
            },
        )
        return row

    def run_many(self, specs: list[ExperimentSpec]) -> list[dict[str, Any]]:
        rows = []
        for index, spec in enumerate(specs, start=1):
            print(
                f"[{index}/{len(specs)}] {spec.algorithm_name} on "
                f"{spec.dataset_name}, {spec.partition_mode}, "
                f"clients={spec.num_clients}, seed={spec.seed}"
            )
            rows.append(self.run_one(spec))
        return rows
