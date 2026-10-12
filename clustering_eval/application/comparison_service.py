from __future__ import annotations

import inspect
import time
import uuid
from datetime import datetime
from typing import Any, Callable

import numpy as np
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from ..algorithms.registry import default_registry as algorithm_registry
from ..datasets.partitioning import make_partition, partition_fingerprint
from ..datasets.registry import default_registry as dataset_registry
from ..metrics.clustering import compute_metrics
from ..results.history_store import HistoryStore
from .dto import (
    AlgorithmRunReport,
    ComparisonReport,
    PartitionReport,
    RunRequest,
)


METRICS = (
    "ari",
    "nmi",
    "silhouette",
    "davies_bouldin",
    "calinski_harabasz",
)

LogCallback = Callable[[str], None]


class ComparisonService:
    """Application service containing the complete comparison orchestration."""

    def __init__(
        self,
        *,
        algorithms: Any | None = None,
        datasets: Any | None = None,
        history_store: HistoryStore | None = None,
    ) -> None:
        self.algorithm_registry = algorithms or algorithm_registry()
        self.dataset_registry = datasets or dataset_registry()
        self.history_store = history_store or HistoryStore("history")

    def dataset_names(self) -> list[str]:
        return _registry_names(self.dataset_registry)

    def algorithm_names(self, *, federated: bool) -> list[str]:
        result: list[str] = []
        for name in _registry_names(self.algorithm_registry):
            algorithm = _get_registry_item(self.algorithm_registry, name)
            if _is_federated(name, algorithm) == federated:
                result.append(name)
        return result

    def compare(
        self,
        request: RunRequest,
        *,
        on_log: LogCallback | None = None,
    ) -> ComparisonReport:
        request.validate()
        started_at = datetime.now().astimezone()
        log_lines: list[str] = []

        def log(message: str) -> None:
            line = message if message.endswith("\n") else message + "\n"
            log_lines.append(line)
            if on_log is not None:
                on_log(line)

        log(f"Загрузка датасета {request.dataset_name}…")
        dataset = _load_dataset(self.dataset_registry, request.dataset_name)
        X_raw, y, dataset_display_name = _extract_xy(dataset)
        X_raw = np.asarray(X_raw, dtype=np.float64)

        selected_algorithms = {
            name: _get_registry_item(self.algorithm_registry, name)
            for name in request.algorithms
        }

        partition = None
        partition_report = None
        if request.mode == "federated":
            if request.num_clients > len(X_raw):
                raise ValueError(
                    f"Number of clients ({request.num_clients}) exceeds "
                    f"the number of samples ({len(X_raw)})"
                )
            required_min = max(
                int(getattr(algorithm, "min_client_samples", 1))
                for algorithm in selected_algorithms.values()
            )
            if request.min_samples_per_client < required_min:
                raise ValueError(
                    f"Selected algorithms require at least {required_min} samples "
                    f"per client; benchmark requested {request.min_samples_per_client}"
                )

            log(
                f"Внутреннее разбиение датасета на "
                f"{request.num_clients} клиентов…"
            )
            partition = make_partition(
                mode=request.partition_mode,
                n_samples=len(X_raw),
                num_clients=request.num_clients,
                seed=request.seed,
                y=y,
                alpha=request.dirichlet_alpha,
                min_samples_per_client=request.min_samples_per_client,
            )
            counts = [len(indices) for indices in partition]
            if any(count == 0 for count in counts):
                raise ValueError(
                    f"Partition contains empty clients: {counts}"
                )
            fingerprint = partition_fingerprint(partition)
            partition_report = PartitionReport(
                mode=request.partition_mode,
                num_clients=request.num_clients,
                client_sample_counts=counts,
                fingerprint=fingerprint,
                dirichlet_alpha=(
                    request.dirichlet_alpha
                    if request.partition_mode == "dirichlet"
                    else None
                ),
            )
            log(f"Partition ID: {fingerprint}")
            log(f"Размеры клиентов: {counts}")

        if request.target_clusters is not None:
            benchmark_k = int(request.target_clusters)
            cluster_count_source = "user"
        elif y is not None:
            benchmark_k = int(len(np.unique(y)))
            cluster_count_source = "ground_truth_oracle"
            log(
                f"Benchmark k={benchmark_k} взят из числа классов y_true "
                f"(oracle-k режим; метки объектов алгоритмам не передаются)."
            )
        else:
            benchmark_k = 3
            cluster_count_source = "fallback"
            log("Benchmark k=3 использован как fallback, потому что y_true отсутствует.")

        common_params = {
            "k": benchmark_k,
            "n_clusters": benchmark_k,
            "rounds": int(request.rounds),
            "tol": float(request.tol),
            "max_iter": int(request.max_iter),
            "density_min_samples": int(request.density_min_samples),
            "client_cpus": 1.0,
            "client_gpus": 0.0,
        }

        results: list[AlgorithmRunReport] = []
        for name in request.algorithms:
            log(f"\nЗапуск {name}…")
            algorithm = selected_algorithms[name]
            X = _preprocess_algorithm_input(X_raw, algorithm)
            preprocessing = getattr(algorithm, "input_preprocessing", "standard")
            log(f"Preprocessing {name}: {preprocessing}")

            params = dict(common_params)
            params.update(dict(getattr(algorithm, "default_params", {}) or {}))
            params.update(request.algorithm_params)
            params.update(request.algorithm_params_by_name.get(name, {}))

            actual_federated = _is_federated(name, algorithm)
            if request.mode == "local" and actual_federated:
                raise ValueError(
                    f"Federated algorithm {name!r} cannot run in local mode"
                )
            if request.mode == "federated" and not actual_federated:
                raise ValueError(
                    f"Local algorithm {name!r} cannot run in federated mode"
                )

            started = time.perf_counter()
            raw_result = _invoke_algorithm(
                algorithm,
                X=X,
                partition=partition,
                params=params,
                seed=request.seed,
            )
            elapsed = time.perf_counter() - started

            labels, runtime, communication, state, history = _extract_result(
                raw_result
            )
            labels = np.asarray(labels)
            if len(labels) != len(X):
                raise ValueError(
                    f"{name} returned {len(labels)} labels for {len(X)} samples"
                )
            if runtime <= 0:
                runtime = elapsed

            unique_labels, label_counts = np.unique(labels, return_counts=True)
            non_noise = [int(value) for value in unique_labels if int(value) != -1]
            noise_count = int(label_counts[list(unique_labels).index(-1)]) if -1 in unique_labels else 0
            non_noise_counts = [
                int(count)
                for value, count in zip(unique_labels, label_counts)
                if int(value) != -1
            ]
            non_noise_total = sum(non_noise_counts)
            dominant_fraction = (
                float(max(non_noise_counts) / non_noise_total)
                if non_noise_total and non_noise_counts
                else 0.0
            )
            diagnostics = {
                "unique_labels": [int(value) for value in unique_labels],
                "cluster_count_excluding_noise": len(non_noise),
                "cluster_count_delta_vs_benchmark_k": len(non_noise) - benchmark_k,
                "noise_fraction": float(noise_count / len(labels)),
                "dominant_cluster_fraction": dominant_fraction,
                "degenerate": len(non_noise) < 2,
                "near_degenerate": len(non_noise) >= 2 and dominant_fraction >= 0.95,
            }
            if diagnostics["degenerate"]:
                log(
                    f"WARNING: {name} выдал вырожденную кластеризацию: "
                    f"clusters={len(non_noise)}, noise_fraction={diagnostics['noise_fraction']:.3f}"
                )
            elif diagnostics["near_degenerate"]:
                log(
                    f"WARNING: {name} выдал почти вырожденную кластеризацию: "
                    f"dominant_cluster_fraction={dominant_fraction:.3f}"
                )

            state = dict(state)
            supported_common = list(getattr(algorithm, "common_param_support", ()) or ())
            shared_names = ("k", "rounds", "tol", "max_iter", "density_min_samples", "seed")
            state["benchmark"] = {
                "seed": request.seed,
                "target_clusters": benchmark_k,
                "cluster_count_source": cluster_count_source,
                "round_budget": request.rounds,
                "tol": request.tol,
                "max_iter": request.max_iter,
                "density_min_samples": request.density_min_samples,
                "num_clients": request.num_clients if request.mode == "federated" else None,
                "partition_mode": request.partition_mode if request.mode == "federated" else None,
                "min_samples_per_client": request.min_samples_per_client if request.mode == "federated" else None,
                "preprocessing": str(preprocessing),
                "common_param_support": supported_common,
                "common_params_not_applicable": [name for name in shared_names if name not in supported_common],
                "effective_params": dict(params),
            }
            state["diagnostics"] = diagnostics

            metrics = compute_metrics(
                X=X,
                y_true=y,
                y_pred=labels,
                requested=list(METRICS),
            )
            backend = str(
                state.get(
                    "backend",
                    "local" if request.mode == "local" else "federated",
                )
            )
            rounds: int | str = state.get(
                "rounds",
                len(history) if history else "—",
            )

            result = AlgorithmRunReport(
                algorithm=name,
                backend=backend,
                runtime_sec=runtime,
                communication_bytes=communication,
                rounds=rounds,
                ari=metrics.get("ari"),
                nmi=metrics.get("nmi"),
                silhouette=metrics.get("silhouette"),
                davies_bouldin=metrics.get("davies_bouldin"),
                calinski_harabasz=metrics.get("calinski_harabasz"),
                model_state=state,
                history=history,
            )
            results.append(result)
            log(f"{name} завершён за {runtime:.4f} сек.")

        report = ComparisonReport(
            experiment_id=uuid.uuid4().hex,
            started_at=started_at,
            finished_at=datetime.now().astimezone(),
            request=request,
            dataset_display_name=dataset_display_name,
            n_samples=int(X_raw.shape[0]),
            n_features=int(X_raw.shape[1]),
            results=results,
            partition=partition_report,
            log_lines=log_lines,
        )

        directory = self.history_store.save(report)
        log(f"\nРезультаты сохранены: {directory}")
        self.history_store.refresh_report(report)
        return report



def _preprocess_algorithm_input(X_raw: np.ndarray, algorithm: Any) -> np.ndarray:
    """Apply the preprocessing declared by an algorithm adapter.

    Historical PyClustEval algorithms use StandardScaler. Author adapters can
    opt into the preprocessing required by their published implementation.
    """
    mode = str(getattr(algorithm, "input_preprocessing", "standard")).lower()
    X = np.asarray(X_raw, dtype=np.float64)
    if mode == "standard":
        return StandardScaler().fit_transform(X)
    if mode == "minmax":
        return MinMaxScaler().fit_transform(X)
    if mode in {"raw", "none"}:
        return np.array(X, copy=True)
    raise ValueError(
        f"Unsupported input preprocessing {mode!r} for "
        f"{getattr(algorithm, 'name', type(algorithm).__name__)}"
    )


def _registry_names(registry: Any) -> list[str]:
    for attr in ("names", "list", "keys", "available", "registered"):
        member = getattr(registry, attr, None)
        if member is None:
            continue
        try:
            value = member() if callable(member) else member
        except TypeError:
            continue
        if isinstance(value, dict):
            names = sorted(str(item) for item in value.keys())
            if names:
                return names
        if isinstance(value, (list, tuple, set)):
            names = sorted(str(item) for item in value)
            if names:
                return names

    for attr in (
        "_items", "_registry", "_algorithms", "_datasets", "_loaders",
        "items", "registry", "algorithms", "datasets", "loaders",
    ):
        value = getattr(registry, attr, None)
        if isinstance(value, dict) and value:
            return sorted(str(item) for item in value.keys())

    for value in vars(registry).values():
        if (
            isinstance(value, dict)
            and value
            and all(isinstance(key, str) for key in value)
        ):
            return sorted(value.keys())

    registry_type = type(registry).__name__.lower()
    if "dataset" in registry_type:
        candidates = (
            "iris", "wine", "breast_cancer",
            "digits", "blobs", "moons",
        )
        methods = ("load", "get", "create")
    else:
        candidates = (
            "kmeans", "dbscan", "gmm", "agglomerative",
            "fed_kmeans_numpy", "fed_kmeans_flower",
            "fed_fuzzy_cmeans_numpy", "fed_fuzzy_cmeans_flower",
            "fed_gmm_diag_numpy", "fed_gmm_diag_flower",
        )
        methods = ("get", "create", "load")

    discovered: list[str] = []
    for name in candidates:
        for method_name in methods:
            method = getattr(registry, method_name, None)
            if not callable(method):
                continue
            try:
                method(name)
            except Exception:
                continue
            discovered.append(name)
            break

    if discovered:
        return discovered

    raise RuntimeError(
        f"Cannot discover entries from registry {type(registry).__name__}"
    )


def _get_registry_item(registry: Any, name: str) -> Any:
    for method_name in ("get", "load", "create"):
        method = getattr(registry, method_name, None)
        if callable(method):
            try:
                return method(name)
            except (KeyError, TypeError, ValueError):
                continue

    for attr in (
        "_items", "_registry", "_algorithms", "_datasets", "_loaders",
        "items", "registry", "algorithms", "datasets", "loaders",
    ):
        mapping = getattr(registry, attr, None)
        if isinstance(mapping, dict) and name in mapping:
            return mapping[name]

    for value in vars(registry).values():
        if isinstance(value, dict) and name in value:
            return value[name]

    raise KeyError(f"Registry entry not found: {name}")


def _is_federated(name: str, algorithm: Any) -> bool:
    for attr in ("is_federated", "federated"):
        value = getattr(algorithm, attr, None)
        if value is not None:
            return bool(value)

    backend = str(getattr(algorithm, "backend", "")).lower()
    execution_backend = str(
        getattr(algorithm, "execution_backend", "")
    ).lower()
    lowered = name.lower()
    return (
        lowered.startswith("fed_")
        or "federated" in lowered
        or "flower" in lowered
        or "federated" in backend
        or "flower" in backend
        or "federated" in execution_backend
        or "flower" in execution_backend
    )


def _load_dataset(registry: Any, name: str) -> Any:
    load = getattr(registry, "load", None)
    if callable(load):
        return load(name)

    item = _get_registry_item(registry, name)
    return item() if callable(item) else item


def _extract_xy(
    dataset: Any,
) -> tuple[np.ndarray, np.ndarray | None, str]:
    if hasattr(dataset, "X"):
        X = np.asarray(dataset.X)
        y_value = getattr(dataset, "y", None)
        y = None if y_value is None else np.asarray(y_value)
        name = str(getattr(dataset, "name", "dataset"))
        return X, y, name

    if isinstance(dataset, tuple) and len(dataset) >= 1:
        X = np.asarray(dataset[0])
        y = (
            None
            if len(dataset) < 2 or dataset[1] is None
            else np.asarray(dataset[1])
        )
        return X, y, "dataset"

    raise TypeError(
        "Dataset must expose X and optional y or return (X, y)"
    )


def _invoke_algorithm(
    algorithm: Any,
    *,
    X: np.ndarray,
    partition: Any | None,
    params: dict[str, Any],
    seed: int,
) -> Any:
    run = getattr(algorithm, "run", None)
    if run is None and callable(algorithm):
        run = algorithm
    if run is None:
        raise TypeError(
            f"{type(algorithm).__name__} has no run() method"
        )

    signature = inspect.signature(run)
    accepted = set(signature.parameters)
    kwargs: dict[str, Any] = {}
    aliases = {
        "X": X,
        "x": X,
        "data": X,
        "partition": partition,
        "partitions": partition,
        "client_partitions": partition,
        "params": params,
        "parameters": params,
        "seed": seed,
        "random_state": seed,
    }
    has_var_kwargs = any(
        item.kind == inspect.Parameter.VAR_KEYWORD
        for item in signature.parameters.values()
    )

    for key, value in aliases.items():
        is_partition = key in {
            "partition", "partitions", "client_partitions",
        }
        if (value is not None or is_partition) and (
            has_var_kwargs or key in accepted
        ):
            kwargs[key] = value

    try:
        return run(**kwargs)
    except TypeError as first_error:
        try:
            return run(
                X,
                partition=partition,
                params=params,
                seed=seed,
            )
        except TypeError:
            raise first_error


def _extract_result(
    result: Any,
) -> tuple[np.ndarray, float, int, dict[str, Any], list[Any]]:
    labels = getattr(result, "labels", None)
    if labels is None and isinstance(result, np.ndarray):
        labels = result
    if labels is None:
        raise TypeError("Algorithm result does not contain labels")

    runtime = float(getattr(result, "runtime_sec", 0.0))
    communication = int(
        getattr(result, "communication_bytes", 0)
    )
    state = getattr(result, "model_state", {}) or {}
    history = getattr(result, "history", []) or []
    return (
        np.asarray(labels),
        runtime,
        communication,
        dict(state),
        list(history),
    )
