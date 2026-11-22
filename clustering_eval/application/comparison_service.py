from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import inspect
import json
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

import numpy as np
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from ..algorithms.registry import default_registry as algorithm_registry
from ..datasets.registry import default_registry as dataset_registry
from ..default_profile import defaults_for
from ..experiments.plan_identity import comparison_key, group_key, job_key, scientific_id
from ..metrics.diagnostics import array_fingerprint
from ..results.excel_export import export_comparison_xlsx
from ..results.history_store import HistoryStore, _json_default, _strict_json_value
from .compute_params import AGGREGATE_FAMILIES, AGGREGATE_MODES, ONE_SHOT
from .compute_report import _assemble_report, partition_summary
from .dto import ComparisonReport, PartitionReport, RunRequest

if TYPE_CHECKING:
    from ..experiments.prepared import PreparedComparison
    from .compute import JobExecution


METRICS = (
    "ari",
    "nmi",
    "ami",
    "silhouette",
    "davies_bouldin",
    "calinski_harabasz",
)

LogCallback = Callable[[str], None]
PartitionCallback = Callable[[PartitionReport], None]


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

    def export_excel(self, report: ComparisonReport, destination: str) -> str:
        """Export a completed comparison to an .xlsx workbook."""
        return str(export_comparison_xlsx(report, destination))

    def prepare(self, request: RunRequest) -> PreparedComparison:
        """Prepare a GUI comparison once, including any shared input-DP matrix."""
        from ..experiments.prepared import build_inputs

        request.validate()
        dataset = _load_dataset(self.dataset_registry, request.dataset_name)
        X, y, display_name = _extract_xy(dataset)
        methods = {name: _get_registry_item(self.algorithm_registry, name) for name in request.algorithms}
        for name, method in methods.items():
            if _is_federated(name, method) != (request.mode == "federated"):
                raise ValueError(f"{name!r} cannot run in {request.mode} mode")
        if request.mode == "federated":
            minimum = max(getattr(method, "min_client_samples", 1) for method in methods.values())
            if request.min_samples_per_client < minimum:
                raise ValueError(f"Selected algorithms require at least {minimum} samples per client")
        aggregate = request.privacy_mode in AGGREGATE_MODES
        if aggregate:
            if request.privacy_mode == "gaussian_dp_aggregate" and request.partition_mode in {"dirichlet", "label_limited"}:
                raise ValueError("Label-dependent partitioning is not accounted by aggregate DP")
            if request.cluster_count_mode != "known_k":
                raise ValueError("Aggregate DP requires a public known-k")
            unsupported = set(methods) - AGGREGATE_FAMILIES.keys()
            if unsupported:
                raise ValueError(f"Aggregate-DP is not implemented for: {sorted(unsupported)}")

        k = request.target_clusters
        if k is not None:
            k_source = "user"
        elif aggregate:
            k = {"dry_bean": 7, "iris": 3, "wine": 3, "digits": 10}.get(request.dataset_name)
            if k is None:
                raise ValueError("Set a PUBLIC target_clusters for aggregate DP")
            k_source = "published_public_dataset_k"
        elif request.cluster_count_mode == "estimated_k":
            k_source = "estimated_unlabeled_silhouette"
        elif y is not None:
            k, k_source = len(np.unique(y)), "ground_truth_oracle"
        else:
            k, k_source = 3, "fallback"

        source_id = _gui_source_id()
        # Bind the same JSON values the native history writer would persist.
        metadata = json.loads(json.dumps(
            _strict_json_value(dict(getattr(dataset, "metadata", {}) or {})),
            default=_json_default, allow_nan=False,
        ))
        data_id = scientific_id("gui-dataset", {"name": request.dataset_name, "metadata": metadata,
                                "x": array_fingerprint(X, length=64),
                                "y": _label_fingerprint(y)})
        protocol = asdict(request)
        for field in ("algorithms", "algorithm_params", "algorithm_params_by_name", "seed", "dataset_name"):
            del protocol[field]
        protocol.update(metrics=list(METRICS), target_clusters=k, cluster_count_source=k_source,
                        evaluation_space="StandardScaler(original_raw_X)")
        if request.mode == "federated":
            protocol["stopping_profile"] = "current_gui"
        common = dict(k=k, n_clusters=k, rounds=request.rounds, tol=request.tol, max_iter=request.max_iter,
                      density_min_samples=request.density_min_samples, client_cpus=1.0, client_gpus=0.0)
        input_id = comparison_key(source_id=source_id, dataset_id=data_id, seed=request.seed, protocol=protocol)
        jobs = []
        for name, method in methods.items():
            params = dict(common)
            for layer in (getattr(method, "default_params", {}), defaults_for(name), request.algorithm_params,
                          request.algorithm_params_by_name.get(name, {})):
                if layer.keys() & {"_stopping_profile", "_historical_compute", "participation_schedule", "dp_aggregate"}:
                    raise ValueError(f"{name}: reserved protocol override")
                params.update(layer)
            if aggregate and name not in ONE_SHOT and params["rounds"] > request.rounds:
                raise ValueError(f"{name}: effective rounds exceed the calibrated GUI round budget")
            backend = _adapter_identity(method)
            job_id = job_key(comparison_id=input_id, algorithm=name, backend=backend,
                             effective_params=params, execution_profile="in_process_gui")
            jobs.append(dict(job_id=job_id, algorithm=name, backend=backend, effective_params=params,
                             preprocessing="fixed_public_reference_then_l2_clip" if aggregate
                             else getattr(method, "input_preprocessing", "standard"),
                             execution_profile="in_process_gui"))
        comparison_id = group_key(input_id, [job["job_id"] for job in jobs])
        return build_inputs(
            X=X, y=y, dataset={"name": request.dataset_name, "display_name": display_name, "dataset_id": data_id,
                               "metadata": metadata},
            comparison={"comparison_id": comparison_id, "dataset_id": data_id, "seed": request.seed,
                        "source_scope": "gui_package_files_excludes_external_registry_code", "protocol": protocol},
            jobs=jobs, source_id=source_id,
        )

    def execute_one(self, prepared: PreparedComparison, job_id: str) -> JobExecution:
        """Execute one member of an in-memory comparison built by this GUI service."""
        from .compute import _execute_one

        if prepared.comparison.get("source_scope") != "gui_package_files_excludes_external_registry_code":
            raise ValueError("Expected an in-memory GUI comparison")
        return _execute_one(prepared, job_id, self.algorithm_registry, gui=True)

    def compare(
        self, request: RunRequest, *, on_log: LogCallback | None = None,
        on_partition: PartitionCallback | None = None,
    ) -> ComparisonReport:
        from .compute import JobExecutionError

        started_at = datetime.now().astimezone()
        log_lines: list[str] = []

        def log(message: str) -> None:
            line = message if message.endswith("\n") else message + "\n"
            log_lines.append(line)
            if on_log is not None:
                on_log(line)

        log(f"Загрузка датасета {request.dataset_name}…")
        if request.dataset_name == "dry_bean":
            log(
                "Dry Bean: 13 611 объектов × 16 признаков × 7 классов. "
                "Полный датасет используется без subsampling; Adapted NN-FC/FKDC "
                "и другие тяжёлые author implementations могут выполняться заметно дольше."
            )
        elif request.dataset_name == "mnist_10k":
            log(
                "MNIST 10k: детерминированная stratified-выборка 10 000 объектов "
                "из полного MNIST (70 000 × 784, 10 классов), seed=42. "
                "Пиксели нормализованы в [0, 1]. На 784 признаках Adapted HF_DBSCAN, "
                "FKDC, NN-FC и другие тяжёлые author implementations могут быть очень медленными."
            )
        elif request.dataset_name == "mnist_full":
            log(
                "MNIST FULL: полный набор 70 000 объектов × 784 признака × 10 классов. "
                "Пиксели нормализованы в [0, 1]. Для некоторых author implementations "
                "такой запуск может потребовать очень много времени и памяти; автоматический "
                "subsampling не выполняется."
            )

        prepared = self.prepare(request)
        if request.privacy_mode != "none":
            log(f"Privacy mode: {request.privacy_mode}")
            log(f"PRIVACY WARNING: {prepared.privacy_report.get('public_release_warning', 'trusted research only')}")
        log(f"Benchmark input hash: {array_fingerprint(prepared.X_train)}; "
            f"common evaluation-space hash: {array_fingerprint(prepared.X_eval)}.")
        partition_report = partition_summary(prepared)
        if partition_report is not None:
            log(f"Partition ID: {partition_report.fingerprint}")
            log(f"Realized heterogeneity: {partition_report.heterogeneity}")
            log(f"Active-data schedule ID: {prepared.active_data['active_data_fingerprint']}")
            log(f"Размеры клиентов: {partition_report.client_sample_counts}")
            if prepared.y is not None:
                for client_id, distribution in enumerate(partition_report.client_class_counts, start=1):
                    pretty = ", ".join(f"{label}: {count}" for label, count in distribution.items())
                    log(f"Client {client_id}: n={partition_report.client_sample_counts[client_id - 1]} | classes: {pretty or '—'}")
            if on_partition is not None:
                on_partition(partition_report)
            log(
                f"Partition подготовлен один раз и будет повторно использован "
                f"для {len(request.algorithms)} алгоритмов."
            )
            log(
                "Federated environment: participation="
                f"{request.participation_rate:.0%}, dropout={request.dropout_rate:.0%}."
            )
            for entry in prepared.schedule:
                selected = [client + 1 for client in entry["selected_clients"]]
                successful = [client + 1 for client in entry["successful_clients"]]
                dropped = [client + 1 for client in entry["dropped_clients"]]
                log(
                    f"Round {entry['round']}: selected={selected} | "
                    f"successful={successful} | dropped={dropped} | "
                    f"active_samples={entry.get('active_sample_count', 0)} | "
                    f"active_hash={entry.get('active_data_hash', '')}"
                )

        executions = []
        for job in prepared.jobs:
            name = job["algorithm"]
            log(f"\nЗапуск {name}…")
            log(f"Preprocessing {name}: {job['preprocessing']}")
            try:
                execution = self.execute_one(prepared, job["job_id"])
            except JobExecutionError as error:
                # Keep existing GUI exception types while retaining release evidence on the cause.
                if error.__cause__ is not None:
                    error.__cause__.add_note(str(error.provenance))
                    raise error.__cause__
                raise
            executions.append(execution)
            result = execution.report
            diagnostics = result.model_state["diagnostics"]
            if diagnostics["degenerate"]:
                log(
                    f"WARNING: {name} выдал вырожденную кластеризацию: "
                    f"clusters={diagnostics['cluster_count_excluding_noise']}, noise_fraction={diagnostics['noise_fraction']:.3f}"
                )
            elif diagnostics["near_degenerate"]:
                log(
                    f"WARNING: {name} выдал почти вырожденную кластеризацию: "
                    f"dominant_cluster_fraction={diagnostics['dominant_cluster_fraction']:.3f}"
                )
            if diagnostics["low_coverage"]:
                log(
                    f"WARNING: {name} assigned only "
                    f"{diagnostics['assigned_fraction']:.1%} of samples. "
                    "Internal metrics on assigned samples may be selection-biased."
                )

            log(f"{name} завершён за {result.runtime_sec:.4f} сек.; prediction_hash={diagnostics['prediction_hash']}")

        report = _assemble_report(prepared, executions, request=request, started_at=started_at,
                                 finished_at=datetime.now().astimezone(), log_lines=log_lines, partition=partition_report)
        directory = self.history_store.save(report)
        log(f"\nРезультаты сохранены: {directory}")
        self.history_store.refresh_report(report)
        return report


def _label_fingerprint(labels: np.ndarray | None) -> str | None:
    if labels is None:
        return None
    if labels.dtype.hasobject:
        # NumPy stores pointers in an object array. Hash the ordered category values.
        return scientific_id("gui-object-labels", {"dtype": labels.dtype.str, "shape": list(labels.shape),
                                                    "values": _strict_json_value(labels)})
    return array_fingerprint(labels, length=64)


def _gui_source_id() -> str:
    """Identify installed package code, including vendored Python used by adapters."""
    package = Path(__file__).resolve().parents[1]
    hashes = {file.relative_to(package).as_posix(): sha256(file.read_bytes()).hexdigest()
              for file in package.rglob("*.py")}
    return scientific_id("gui-package-files", hashes)


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
            "iris", "wine", "dry_bean", "mnist_10k", "mnist_full", "breast_cancer",
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


def _adapter_identity(adapter: Any) -> str:
    """Identify the class or callable selected by the interactive registry."""
    implementation = adapter if inspect.isroutine(adapter) or inspect.isclass(adapter) else type(adapter)
    return f"{implementation.__module__}.{implementation.__qualname__}"


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
        signature.bind(**kwargs)
    except TypeError:
        # Some registered callables accept X positionally. Resolve that before entering
        # the adapter: a TypeError inside an adapter must never trigger a second release.
        signature.bind(X, partition=partition, params=params, seed=seed)
        return run(X, partition=partition, params=params, seed=seed)
    return run(**kwargs)
