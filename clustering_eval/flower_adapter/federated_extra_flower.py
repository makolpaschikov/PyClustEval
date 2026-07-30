from __future__ import annotations

import time
from typing import Any

import numpy as np

from ..algorithms.base import AlgorithmResult, ClusteringAlgorithm


def _require_flower():
    try:
        import flwr as fl
        from flwr.client import ClientApp
        from flwr.common import FitIns, ndarrays_to_parameters, parameters_to_ndarrays
        from flwr.server import ServerApp, ServerAppComponents, ServerConfig
        from flwr.server.strategy import Strategy
        from flwr.simulation import run_simulation
    except ImportError as exc:
        raise RuntimeError(
            'Flower Simulation is missing. Install: python -m pip install "flwr[simulation]"'
        ) from exc
    return (
        fl,
        ClientApp,
        FitIns,
        ndarrays_to_parameters,
        parameters_to_ndarrays,
        ServerApp,
        ServerAppComponents,
        ServerConfig,
        Strategy,
        run_simulation,
    )


def _init_centers(X: np.ndarray, k: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return X[rng.choice(len(X), size=k, replace=False)].astype(float).copy()


def _dist2(X: np.ndarray, centers: np.ndarray) -> np.ndarray:
    return np.maximum(
        ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2),
        1e-12,
    )


class FedFuzzyCMeansFlowerAdapter(ClusteringAlgorithm):
    name = "fed_fuzzy_cmeans_flower"
    is_federated = True
    execution_backend = "flower-simulation"

    def run(self, X, partition, params, seed):
        (
            fl, ClientApp, FitIns, ndarrays_to_parameters, parameters_to_ndarrays,
            ServerApp, ServerAppComponents, ServerConfig, Strategy, run_simulation,
        ) = _require_flower()

        X = np.asarray(X, dtype=np.float64)
        if not partition or any(len(p) == 0 for p in partition):
            raise ValueError("A non-empty client partition is required")

        n_clients = len(partition)
        k = int(params.get("k", params.get("n_clusters", 3)))
        rounds = int(params.get("rounds", 20))
        tol = float(params.get("tol", 1e-4))
        m = float(params.get("fuzziness", 2.0))
        initial = _init_centers(X, k, seed)

        class Client(fl.client.NumPyClient):
            def __init__(self, local_x):
                self.local_x = local_x

            def get_parameters(self, config):
                return []

            def fit(self, parameters, config):
                centers = np.asarray(parameters[0], dtype=np.float64)
                distances = _dist2(self.local_x, centers)
                inverse = distances ** (-1.0 / (m - 1.0))
                membership = inverse / inverse.sum(axis=1, keepdims=True)
                powered = membership**m
                sums = powered.T @ self.local_x
                weights = powered.sum(axis=0)
                objective = float((powered * distances).sum())
                return [sums, weights], len(self.local_x), {"objective": objective}

            def evaluate(self, parameters, config):
                return 0.0, len(self.local_x), {}

        class FedStrategy(Strategy):
            def __init__(self):
                self.centers = initial.copy()
                self.history = []
                self.communication_bytes = 0

            def initialize_parameters(self, client_manager):
                return ndarrays_to_parameters([self.centers])

            def configure_fit(self, server_round, parameters, client_manager):
                clients = client_manager.sample(n_clients, min_num_clients=n_clients)
                self.communication_bytes += self.centers.nbytes * len(clients)
                instruction = FitIns(parameters, {"round": server_round})
                return [(client, instruction) for client in clients]

            def aggregate_fit(self, server_round, results, failures):
                if failures:
                    raise RuntimeError(f"{len(failures)} Flower clients failed")
                total_sums = np.zeros_like(self.centers)
                total_weights = np.zeros(k)
                objective = 0.0
                for _, fit_res in results:
                    arrays = parameters_to_ndarrays(fit_res.parameters)
                    sums = np.asarray(arrays[0])
                    weights = np.asarray(arrays[1])
                    total_sums += sums
                    total_weights += weights
                    objective += float(fit_res.metrics.get("objective", 0.0))
                    self.communication_bytes += sums.nbytes + weights.nbytes

                updated = self.centers.copy()
                mask = total_weights > 0
                updated[mask] = total_sums[mask] / total_weights[mask, None]
                shift = float(np.linalg.norm(updated - self.centers))
                self.centers = updated
                self.history.append(
                    {"round": server_round, "shift": shift, "objective": objective}
                )
                return ndarrays_to_parameters([self.centers]), {"shift": shift}

            def configure_evaluate(self, server_round, parameters, client_manager):
                return []

            def aggregate_evaluate(self, server_round, results, failures):
                return None, {}

            def evaluate(self, server_round, parameters):
                return None

        def client_fn(context):
            client_id = int(context.node_config["partition-id"])
            return Client(X[partition[client_id]]).to_client()

        strategy = FedStrategy()
        started = time.perf_counter()
        run_simulation(
            server_app=ServerApp(
                server_fn=lambda context: ServerAppComponents(
                    strategy=strategy,
                    config=ServerConfig(num_rounds=rounds),
                )
            ),
            client_app=ClientApp(client_fn=client_fn),
            num_supernodes=n_clients,
            backend_config={
                "client_resources": {
                    "num_cpus": float(params.get("client_cpus", 1.0)),
                    "num_gpus": float(params.get("client_gpus", 0.0)),
                }
            },
        )
        labels = np.argmin(_dist2(X, strategy.centers), axis=1)
        return AlgorithmResult(
            labels=labels,
            model_state={
                "centers": strategy.centers.tolist(),
                "rounds": len(strategy.history),
                "fuzziness": m,
                "backend": "flower-simulation",
                "num_clients": n_clients,
            },
            history=strategy.history,
            runtime_sec=time.perf_counter() - started,
            communication_bytes=strategy.communication_bytes,
        )


class FedDiagonalGMMFlowerAdapter(ClusteringAlgorithm):
    name = "fed_gmm_diag_flower"
    is_federated = True
    execution_backend = "flower-simulation"

    def run(self, X, partition, params, seed):
        (
            fl, ClientApp, FitIns, ndarrays_to_parameters, parameters_to_ndarrays,
            ServerApp, ServerAppComponents, ServerConfig, Strategy, run_simulation,
        ) = _require_flower()

        X = np.asarray(X, dtype=np.float64)
        if not partition or any(len(p) == 0 for p in partition):
            raise ValueError("A non-empty client partition is required")

        n_clients = len(partition)
        k = int(params.get("k", params.get("n_clusters", 3)))
        rounds = int(params.get("rounds", 20))
        reg = float(params.get("reg_covar", 1e-6))
        means0 = _init_centers(X, k, seed)
        variances0 = np.tile(np.var(X, axis=0) + reg, (k, 1))
        weights0 = np.full(k, 1.0 / k)

        class Client(fl.client.NumPyClient):
            def __init__(self, local_x):
                self.local_x = local_x

            def get_parameters(self, config):
                return []

            def fit(self, parameters, config):
                means = np.asarray(parameters[0])
                variances = np.asarray(parameters[1])
                weights = np.asarray(parameters[2])
                log_prob = []
                for cluster in range(k):
                    diff = self.local_x - means[cluster]
                    log_det = np.log(2.0 * np.pi * variances[cluster]).sum()
                    quadratic = (diff * diff / variances[cluster]).sum(axis=1)
                    log_prob.append(
                        np.log(weights[cluster] + 1e-15)
                        - 0.5 * (log_det + quadratic)
                    )
                log_prob = np.stack(log_prob, axis=1)
                maximum = log_prob.max(axis=1, keepdims=True)
                exp_prob = np.exp(log_prob - maximum)
                normalizer = exp_prob.sum(axis=1, keepdims=True)
                resp = exp_prob / normalizer
                nk = resp.sum(axis=0)
                sum_x = resp.T @ self.local_x
                sum_x2 = resp.T @ (self.local_x * self.local_x)
                ll = float((maximum[:, 0] + np.log(normalizer[:, 0])).sum())
                return [nk, sum_x, sum_x2], len(self.local_x), {"ll": ll}

            def evaluate(self, parameters, config):
                return 0.0, len(self.local_x), {}

        class FedStrategy(Strategy):
            def __init__(self):
                self.means = means0.copy()
                self.variances = variances0.copy()
                self.weights = weights0.copy()
                self.history = []
                self.communication_bytes = 0

            def _parameters(self):
                return ndarrays_to_parameters(
                    [self.means, self.variances, self.weights]
                )

            def initialize_parameters(self, client_manager):
                return self._parameters()

            def configure_fit(self, server_round, parameters, client_manager):
                clients = client_manager.sample(n_clients, min_num_clients=n_clients)
                payload = self.means.nbytes + self.variances.nbytes + self.weights.nbytes
                self.communication_bytes += payload * len(clients)
                instruction = FitIns(parameters, {"round": server_round})
                return [(client, instruction) for client in clients]

            def aggregate_fit(self, server_round, results, failures):
                if failures:
                    raise RuntimeError(f"{len(failures)} Flower clients failed")
                nk = np.zeros(k)
                sum_x = np.zeros_like(self.means)
                sum_x2 = np.zeros_like(self.means)
                ll = 0.0
                for _, fit_res in results:
                    arrays = parameters_to_ndarrays(fit_res.parameters)
                    client_nk = np.asarray(arrays[0])
                    client_sum_x = np.asarray(arrays[1])
                    client_sum_x2 = np.asarray(arrays[2])
                    nk += client_nk
                    sum_x += client_sum_x
                    sum_x2 += client_sum_x2
                    ll += float(fit_res.metrics.get("ll", 0.0))
                    self.communication_bytes += (
                        client_nk.nbytes + client_sum_x.nbytes + client_sum_x2.nbytes
                    )

                safe_nk = np.maximum(nk, 1e-12)
                new_weights = safe_nk / safe_nk.sum()
                new_means = sum_x / safe_nk[:, None]
                new_variances = np.maximum(
                    sum_x2 / safe_nk[:, None] - new_means * new_means,
                    reg,
                )
                shift = float(np.linalg.norm(new_means - self.means))
                self.means = new_means
                self.variances = new_variances
                self.weights = new_weights
                self.history.append(
                    {"round": server_round, "shift": shift, "log_likelihood": ll}
                )
                return self._parameters(), {"shift": shift, "log_likelihood": ll}

            def configure_evaluate(self, server_round, parameters, client_manager):
                return []

            def aggregate_evaluate(self, server_round, results, failures):
                return None, {}

            def evaluate(self, server_round, parameters):
                return None

        def client_fn(context):
            client_id = int(context.node_config["partition-id"])
            return Client(X[partition[client_id]]).to_client()

        strategy = FedStrategy()
        started = time.perf_counter()
        run_simulation(
            server_app=ServerApp(
                server_fn=lambda context: ServerAppComponents(
                    strategy=strategy,
                    config=ServerConfig(num_rounds=rounds),
                )
            ),
            client_app=ClientApp(client_fn=client_fn),
            num_supernodes=n_clients,
            backend_config={
                "client_resources": {
                    "num_cpus": float(params.get("client_cpus", 1.0)),
                    "num_gpus": float(params.get("client_gpus", 0.0)),
                }
            },
        )

        scores = []
        for cluster in range(k):
            diff = X - strategy.means[cluster]
            log_det = np.log(2.0 * np.pi * strategy.variances[cluster]).sum()
            quadratic = (diff * diff / strategy.variances[cluster]).sum(axis=1)
            scores.append(
                np.log(strategy.weights[cluster] + 1e-15)
                - 0.5 * (log_det + quadratic)
            )
        labels = np.argmax(np.stack(scores, axis=1), axis=1)

        return AlgorithmResult(
            labels=labels,
            model_state={
                "means": strategy.means.tolist(),
                "variances": strategy.variances.tolist(),
                "weights": strategy.weights.tolist(),
                "rounds": len(strategy.history),
                "backend": "flower-simulation",
                "num_clients": n_clients,
            },
            history=strategy.history,
            runtime_sec=time.perf_counter() - started,
            communication_bytes=strategy.communication_bytes,
        )
