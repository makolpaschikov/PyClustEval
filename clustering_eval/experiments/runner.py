from __future__ import annotations

from typing import Any

from ..algorithms.registry import default_registry as default_algorithm_registry
from ..datasets.partitioning import make_partition, partition_fingerprint
from ..datasets.registry import default_registry as default_dataset_registry
from ..metrics.clustering import compute_metrics
from ..results.store import ResultStore
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

        # The partition depends only on dataset/run settings, never on algorithm.
        # Therefore all algorithms in the same benchmark case receive identical
        # client indices. partition_id is persisted for verification.
        partition = make_partition(
            mode=spec.partition_mode,
            n_samples=len(dataset.X),
            num_clients=spec.num_clients,
            seed=spec.seed,
            y=dataset.y,
            alpha=spec.dirichlet_alpha or 0.5,
        )
        partition_id = partition_fingerprint(partition)

        algorithm = self.algorithms.get(spec.algorithm_name)
        result = algorithm.run(
            dataset.X,
            partition,
            spec.algorithm_params,
            spec.seed,
        )
        metric_values = compute_metrics(
            dataset.X,
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
