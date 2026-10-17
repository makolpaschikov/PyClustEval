"""Distributed federated K-Means execution through Flower Simulation Runtime."""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from ..privacy.aggregate_dp import public_initial_centers, noisy_joint_aggregate, project_centers, stable_noisy_count_threshold
from sklearn.metrics import pairwise_distances_argmin

from ..algorithms.base import AlgorithmResult, ClusteringAlgorithm
from ..federated.environment import participation_entry_for_round
from ..federated.initialization import federated_priority_sample_centers


class FedKMeansFlowerAdapter(ClusteringAlgorithm):
    common_param_support = ("k", "rounds", "tol", "seed")
    """Run synchronous federated K-Means with one Flower client per partition.

    Protocol per round:
      1. Server sends global cluster centers to every selected client.
      2. Each client assigns local samples and returns cluster sums/counts.
      3. Server aggregates sufficient statistics and updates global centers.

    After initialization, clients send only sufficient statistics.  The
    deterministic benchmark initializer sends at most ``k`` candidate center
    vectors per active client (Gaussian-DP mode sanitizes them because it
    operates on X before initialization).  PyClustEval can additionally impose a
    deterministic per-round participation/dropout schedule.  Because Flower's
    strategy layer does not expose the dataset partition-id, all simulator
    supernodes remain alive and inactive clients return a no-op update; only the
    logically successful clients contribute to aggregation and benchmark traffic.
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

        init_participation = participation_entry_for_round(params, 0, num_clients)
        dp = params.get('dp_aggregate')
        if dp is None:
            initial_centers, init_report = federated_priority_sample_centers(
                X, partition, k, seed,
                active_client_ids=init_participation["successful_clients"],
            )
        else:
            initial_centers = public_initial_centers(k, X.shape[1], seed, dp['clip_norm'])
            init_report = {'communication_bytes': 0, 'mode': 'public_data_independent'}

        class KMeansClient(fl.client.NumPyClient):
            def __init__(self, local_X: np.ndarray, client_id: int) -> None:
                self.local_X = local_X
                self.client_id = int(client_id)

            def get_parameters(self, config: dict[str, Any]):
                return []

            def fit(self, parameters, config):
                centers = np.asarray(parameters[0], dtype=np.float64)
                round_index = max(int(config.get("server_round", 1)) - 1, 0)
                participation = participation_entry_for_round(
                    params, round_index, num_clients
                )
                active = self.client_id in participation["successful_clients"]
                if not active:
                    return [np.zeros_like(centers), np.zeros(k, dtype=np.int64)], 0, {
                        "inertia": 0.0,
                        "active": 0,
                    }

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
                return [sums, counts], len(self.local_X), {"inertia": (None if dp is not None else inertia), "active": 1}

            def evaluate(self, parameters, config):
                return 0.0, len(self.local_X), {}

        class FedKMeansStrategy(Strategy):
            def __init__(self) -> None:
                self.centers = initial_centers.copy()
                self.history: list[dict[str, Any]] = []
                self.communication_bytes = int(init_report["communication_bytes"])
                self.converged = False

            def initialize_parameters(self, client_manager: ClientManager):
                return ndarrays_to_parameters([self.centers])

            def configure_fit(self, server_round, parameters, client_manager):
                # Flower proxies do not expose the dataset partition-id to the
                # strategy layer.  We therefore keep all simulator clients alive
                # and enforce the shared benchmark schedule inside each client,
                # where context.node_config["partition-id"] is stable.
                clients = client_manager.sample(
                    num_clients=num_clients,
                    min_num_clients=num_clients,
                )
                participation = participation_entry_for_round(
                    params, max(int(server_round) - 1, 0), num_clients
                )
                instruction = FitIns(parameters, {"server_round": server_round})
                # Logical benchmark traffic: selected clients receive the model;
                # only successful clients return an update.  Flower's simulator
                # still dispatches no-op calls to inactive supernodes so IDs stay stable.
                self.communication_bytes += (
                    self.centers.nbytes * len(participation["selected_clients"])
                )
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

                active_results = 0
                for _, fit_res in results:
                    if int(fit_res.metrics.get("active", 1)) != 1:
                        continue
                    arrays = parameters_to_ndarrays(fit_res.parameters)
                    client_sums = np.asarray(arrays[0], dtype=np.float64)
                    client_counts = np.asarray(arrays[1], dtype=np.int64)
                    total_sums += client_sums
                    total_counts += client_counts
                    inertia += float(fit_res.metrics.get("inertia", 0.0))
                    self.communication_bytes += (
                        client_sums.nbytes + client_counts.nbytes
                    )
                    active_results += 1

                if active_results == 0:
                    raise RuntimeError(
                        f"Flower round {server_round} has no successful benchmark clients"
                    )

                if dp is not None:
                    total_sums, total_counts = noisy_joint_aggregate(dp, total_sums, total_counts)
                new_centers = self.centers.copy()
                nonempty = total_counts > (stable_noisy_count_threshold(dp) if dp is not None else 0)
                new_centers[nonempty] = (
                    total_sums[nonempty] / total_counts[nonempty, None]
                )
                shift = float(np.linalg.norm(new_centers - self.centers))
                self.centers = (project_centers(new_centers, dp['clip_norm'])
                                if dp is not None else new_centers)
                self.converged = shift < tol
                participation = participation_entry_for_round(
                    params, max(int(server_round) - 1, 0), num_clients
                )
                self.history.append(
                    {
                        "round": server_round,
                        "shift": shift,
                        "inertia": (None if dp is not None else inertia),
                        "selected_clients": participation["selected_clients"],
                        "successful_clients": participation["successful_clients"],
                        "dropped_clients": participation["dropped_clients"],
                    }
                )
                return ndarrays_to_parameters([self.centers]), {
                    "shift": shift,
                    "inertia": (None if dp is not None else inertia),
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
            return KMeansClient(X[local_indices], partition_id).to_client()

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
                "participation_schedule": params.get("participation_schedule", []),
                "participation_backend": "logical-noop-client-simulation",
                "initialization": init_report,
            },
            history=strategy.history,
            runtime_sec=runtime,
            communication_bytes=strategy.communication_bytes,
        )
