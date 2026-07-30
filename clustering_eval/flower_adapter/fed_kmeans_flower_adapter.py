"""Distributed federated K-Means execution through Flower Simulation Runtime."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from sklearn.metrics import pairwise_distances_argmin

from ..algorithms.base import AlgorithmResult, ClusteringAlgorithm


class FedKMeansFlowerAdapter(ClusteringAlgorithm):
    """Run synchronous federated K-Means with one Flower client per partition.

    Protocol per round:
      1. Server sends global cluster centers to every selected client.
      2. Each client assigns local samples and returns cluster sums/counts.
      3. Server aggregates sufficient statistics and updates global centers.

    Raw samples never leave the client. All configured clients participate in
    every round, which makes the run deterministic for a fixed partition/seed.
    """

    name = "fed_kmeans_flower"

    def run(
        self,
        X: np.ndarray,
        partition: list[np.ndarray] | None,
        params: dict[str, Any],
        seed: int,
    ) -> AlgorithmResult:
        try:
            import flwr as fl
            from flwr.client import ClientApp
            from flwr.common import (
                FitIns,
                Parameters,
                ndarrays_to_parameters,
                parameters_to_ndarrays,
            )
            from flwr.server import ServerApp, ServerAppComponents, ServerConfig
            from flwr.server.client_manager import ClientManager
            from flwr.server.strategy import Strategy
            from flwr.simulation import run_simulation
        except ImportError as exc:
            raise RuntimeError(
                'Flower is not installed. Run: pip install -e ".[flower]"'
            ) from exc

        if partition is None:
            raise ValueError("fed_kmeans_flower requires a client partition")
        if not partition:
            raise ValueError("Partition must contain at least one client")
        if any(len(indices) == 0 for indices in partition):
            raise ValueError("Flower execution does not allow empty clients")

        X = np.asarray(X, dtype=np.float64)
        num_clients = len(partition)
        k = int(params.get("k", 3))
        rounds = int(params.get("rounds", 20))
        tol = float(params.get("tol", 1e-4))
        client_cpus = float(params.get("client_cpus", 1.0))
        client_gpus = float(params.get("client_gpus", 0.0))

        if k <= 0 or k > len(X):
            raise ValueError(f"k must be in [1, {len(X)}], got {k}")
        if rounds <= 0:
            raise ValueError("rounds must be greater than zero")

        rng = np.random.default_rng(seed)
        initial_indices = rng.choice(len(X), size=k, replace=False)
        initial_centers = X[initial_indices].copy()

        class KMeansClient(fl.client.NumPyClient):
            def __init__(self, local_X: np.ndarray) -> None:
                self.local_X = local_X

            def get_parameters(self, config: dict[str, Any]):
                return []

            def fit(self, parameters, config):
                centers = np.asarray(parameters[0], dtype=np.float64)
                labels = pairwise_distances_argmin(self.local_X, centers)
                sums = np.zeros_like(centers)
                counts = np.zeros(k, dtype=np.int64)

                for cluster_id in range(k):
                    mask = labels == cluster_id
                    if np.any(mask):
                        sums[cluster_id] = self.local_X[mask].sum(axis=0)
                        counts[cluster_id] = int(mask.sum())

                inertia = float(
                    np.square(self.local_X - centers[labels]).sum()
                )
                return [sums, counts], len(self.local_X), {"inertia": inertia}

            def evaluate(self, parameters, config):
                return 0.0, len(self.local_X), {}

        class FedKMeansStrategy(Strategy):
            def __init__(self) -> None:
                self.centers = initial_centers.copy()
                self.history: list[dict[str, Any]] = []
                self.communication_bytes = 0
                self.converged = False

            def initialize_parameters(self, client_manager: ClientManager):
                return ndarrays_to_parameters([self.centers])

            def configure_fit(self, server_round, parameters, client_manager):
                clients = client_manager.sample(
                    num_clients=num_clients,
                    min_num_clients=num_clients,
                )
                instruction = FitIns(parameters, {"server_round": server_round})
                self.communication_bytes += self.centers.nbytes * len(clients)
                return [(client, instruction) for client in clients]

            def aggregate_fit(self, server_round, results, failures):
                if failures:
                    raise RuntimeError(
                        f"Flower round {server_round} failed on {len(failures)} clients"
                    )
                if not results:
                    return None, {}

                total_sums = np.zeros_like(self.centers)
                total_counts = np.zeros(k, dtype=np.int64)
                inertia = 0.0

                for _, fit_res in results:
                    arrays = parameters_to_ndarrays(fit_res.parameters)
                    client_sums = np.asarray(arrays[0], dtype=np.float64)
                    client_counts = np.asarray(arrays[1], dtype=np.int64)
                    total_sums += client_sums
                    total_counts += client_counts
                    inertia += float(fit_res.metrics.get("inertia", 0.0))
                    self.communication_bytes += (
                        client_sums.nbytes + client_counts.nbytes
                    )

                new_centers = self.centers.copy()
                nonempty = total_counts > 0
                new_centers[nonempty] = (
                    total_sums[nonempty] / total_counts[nonempty, None]
                )
                shift = float(np.linalg.norm(new_centers - self.centers))
                self.centers = new_centers
                self.converged = shift < tol
                self.history.append(
                    {
                        "round": server_round,
                        "shift": shift,
                        "inertia": inertia,
                    }
                )
                return ndarrays_to_parameters([self.centers]), {
                    "shift": shift,
                    "inertia": inertia,
                }

            def configure_evaluate(self, server_round, parameters, client_manager):
                return []

            def aggregate_evaluate(self, server_round, results, failures):
                return None, {}

            def evaluate(self, server_round, parameters):
                return None

        def client_fn(context):
            partition_id = int(context.node_config["partition-id"])
            local_indices = partition[partition_id]
            return KMeansClient(X[local_indices]).to_client()

        strategy = FedKMeansStrategy()
        client_app = ClientApp(client_fn=client_fn)

        def server_fn(context):
            return ServerAppComponents(
                strategy=strategy,
                config=ServerConfig(num_rounds=rounds),
            )

        server_app = ServerApp(server_fn=server_fn)
        start = time.perf_counter()

        run_simulation(
            server_app=server_app,
            client_app=client_app,
            num_supernodes=num_clients,
            backend_config={
                "client_resources": {
                    "num_cpus": client_cpus,
                    "num_gpus": client_gpus,
                }
            },
        )

        runtime = time.perf_counter() - start
        labels = pairwise_distances_argmin(X, strategy.centers)
        return AlgorithmResult(
            labels=labels,
            model_state={
                "centers": strategy.centers.tolist(),
                "rounds": len(strategy.history),
                "converged": strategy.converged,
                "backend": "flower-simulation",
                "num_clients": num_clients,
            },
            history=strategy.history,
            runtime_sec=runtime,
            communication_bytes=strategy.communication_bytes,
        )
