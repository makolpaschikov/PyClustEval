from __future__ import annotations

import inspect
import platform
import sys
import sklearn
import scipy
import time
import uuid
from datetime import datetime
from typing import Any, Callable

import numpy as np
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from ..algorithms.registry import default_registry as algorithm_registry
from ..default_profile import PROFILE_NAME, defaults_for
from ..datasets.partitioning import (
    make_partition,
    partition_class_counts,
    partition_fingerprint,
)
from ..datasets.registry import default_registry as dataset_registry
from ..federated.environment import make_participation_schedule
from ..metrics.clustering import (
    METRIC_SCHEMA_VERSION,
    SILHOUETTE_MAX_POINTS,
    SILHOUETTE_SAMPLING_SEED,
    compute_metrics,
    silhouette_reference_indices,
)
from ..metrics.diagnostics import (
    active_data_diagnostics,
    array_fingerprint,
    client_external_metrics,
    prediction_fingerprint,
)
from ..privacy.gaussian import apply_gaussian_input_dp
from ..privacy.aggregate_dp import clipped_public_features, make_dp_aggregate_config
from ..metrics.protocol_v2 import (estimate_k_unlabeled, tune_dbscan_unlabeled, measure_partition_heterogeneity)
from ..results.excel_export import export_comparison_xlsx
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

    def compare(
        self,
        request: RunRequest,
        *,
        on_log: LogCallback | None = None,
        on_partition: PartitionCallback | None = None,
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
        dataset_metadata = dict(getattr(dataset, "metadata", {}) or {})
        if X_raw.ndim != 2 or X_raw.shape[0] < 3 or X_raw.shape[1] < 1:
            raise ValueError(f"Invalid benchmark feature shape: {X_raw.shape}")
        if not np.isfinite(X_raw).all():
            raise ValueError("Benchmark dataset contains NaN or infinite features")
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

        privacy_report: dict[str, Any] = {"mode": "none"}
        X_benchmark_raw = X_raw
        if request.mode == "federated" and request.privacy_mode == "gaussian_dp":
            log(
                "Применение общего Gaussian DP input layer: "
                f"epsilon={request.dp_epsilon:g}, delta={request.dp_delta:g}, "
                f"clip_norm={request.dp_clip_norm:g}…"
            )
            X_benchmark_raw, privacy_report = apply_gaussian_input_dp(
                X_raw,
                epsilon=request.dp_epsilon,
                delta=request.dp_delta,
                clip_norm=request.dp_clip_norm,
                seed=request.seed,
            )
            log(
                "Gaussian DP: sigma="
                f"{privacy_report['sigma_raw_feature_space']:.6g} в raw feature space; "
                f"clipped records="
                f"{privacy_report['clipped_record_fraction']:.1%}."
            )
            log(
                "Приватизированная матрица сэмплируется один раз и одинаково "
                "используется всеми выбранными алгоритмами и всеми раундами."
            )
            privacy_report["end_to_end_report_is_dp"] = False
            privacy_report["nonprivate_report_outputs"] = [
                "ARI/NMI computed using original unprotected y_true",
                "silhouette/DB/CH computed using original unprotected X_raw",
                "label-aware partitions and original class-distribution reports",
                "deterministic clean-data evaluation hash",
                "fraction of records clipped before the DP noise is added",
            ]
            privacy_report["public_release_warning"] = (
                "Gaussian calibration only applies to the privatized training feature "
                "matrix. The full benchmark report is NOT end-to-end differentially private."
            )
            log("PRIVACY WARNING: весь benchmark report НЕ имеет end-to-end DP гарантий: "
                "оценочные метрики используют raw X / y и label-aware partitions.")

        aggregate_privacy = request.privacy_mode in ('gaussian_dp_aggregate', 'public_clipped_control')
        if aggregate_privacy:
            if request.privacy_mode == 'gaussian_dp_aggregate' and request.partition_mode in ('dirichlet', 'label_limited'):
                raise ValueError('Label-dependent partitioning uses private y and is not accounted by aggregate DP. Use IID/quantity_skew.')
            if request.cluster_count_mode != 'known_k':
                raise ValueError('Aggregate DP requires a public known-k; private estimated-k tuning is not DP-accounted.')
            supported_dp = {
                'fed_kmeans_numpy', 'fed_kmeans_flower',
                'fed_fuzzy_cmeans_numpy', 'fed_fuzzy_cmeans_flower',
                'fed_gmm_diag_numpy', 'fed_gmm_diag_flower',
                'Adapted FKM', 'Adapted FKDC', 'Adapted HF_DBSCAN',
                'Adapted NN-FC', 'Adapted p-FClus',
            }
            not_supported = sorted(set(request.algorithms) - supported_dp)
            if not_supported:
                raise ValueError('Aggregate-DP is not implemented for: '
                                 + ', '.join(not_supported)
                                 + '. Remove these algorithms or use the non-DP mode.')
        if aggregate_privacy:
            X_benchmark_raw, public_info = clipped_public_features(
                X_raw, request.dataset_name, request.dp_clip_norm
            )
            is_dp = request.privacy_mode == 'gaussian_dp_aggregate'
            privacy_report = {
                'mode': request.privacy_mode,
                'privacy_protocol_version': 'trusted_aggregate_dp_v2_author_server_surrogates',
                'author_algorithm_dp_scope': ('selected Adapted author methods use Gaussian DP local aggregates and modified author-server postprocessing'
                    if any(str(a).startswith('Adapted ') for a in request.algorithms) else 'no Adapted author algorithms selected'),
                'comparability_warning': ('DP author-server variants are NOT original author algorithms; changed private client stages. Analyze separately from unmodified author methods.'
                    if any(str(a).startswith('Adapted ') for a in request.algorithms) else 'DP quality must be assessed against matched clipping control'),
                'mechanism': 'trusted-server Gaussian aggregate sufficient statistics' if is_dp
                             else 'matched fixed-public-scaled clipping control; NO PRIVACY',
                'epsilon': request.dp_epsilon if is_dp else None,
                'delta': request.dp_delta if is_dp else None,
                'clip_norm_public_space': request.dp_clip_norm,
                'public_preprocessing': public_info,
                'per_algorithm_privacy_budgets_compose': True,
                'algorithm_count': len(request.algorithms),
                'upper_bound_epsilon_across_selected_algorithms': (
                    len(request.algorithms) * request.dp_epsilon if is_dp else None),
                'upper_bound_delta_across_selected_algorithms': (
                    min(1.0, len(request.algorithms) * request.dp_delta) if is_dp else None),

                'end_to_end_report_is_dp': False,
                'server_receives_unprotected_client_statistics': True,
                'public_release_warning': (
                    'TRUSTED SERVER ONLY. Client updates are NOT locally private and NOT '
                    'securely aggregated. Benchmark report with ground truth, diagnostics '
                    'and labels is NOT DP. Multiple different algorithm runs compose privacy loss.'
                ),
            }
            log(f"Aggregate mode: {request.privacy_mode}, public-space clip={request.dp_clip_norm:g}, "
                f"clipped={public_info['clipped_record_fraction_trusted_only']:.1%}; "
                "raw data never used to FIT normalization")
            log(privacy_report['public_release_warning'])

        # All internal geometric metrics are evaluated in one algorithm-independent
        # space.  For DP experiments we intentionally keep the clean benchmark
        # evaluator outside the privacy mechanism, just like y_true for ARI/NMI.
        X_eval = StandardScaler().fit_transform(X_raw)
        benchmark_input_hash = array_fingerprint(X_benchmark_raw)
        evaluation_input_hash = array_fingerprint(X_eval)
        silhouette_reference = silhouette_reference_indices(len(X_eval))
        log(
            f"Benchmark input hash: {benchmark_input_hash}; "
            f"common evaluation-space hash: {evaluation_input_hash}."
        )

        selected_algorithms = {
            name: _get_registry_item(self.algorithm_registry, name)
            for name in request.algorithms
        }

        partition = None
        partition_report = None
        participation_schedule: list[dict[str, Any]] = []
        active_data_report: dict[str, Any] = {"rounds": [], "active_data_fingerprint": None}
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
                labels_per_client=request.labels_per_client,
            )
            counts = [len(indices) for indices in partition]
            if any(count == 0 for count in counts):
                raise ValueError(
                    f"Partition contains empty clients: {counts}"
                )
            fingerprint = partition_fingerprint(partition)
            class_counts = partition_class_counts(partition, y)
            participation_schedule = make_participation_schedule(
                num_clients=request.num_clients,
                rounds=request.rounds,
                participation_rate=request.participation_rate,
                dropout_rate=request.dropout_rate,
                seed=request.seed,
            )
            active_data_report = active_data_diagnostics(partition, participation_schedule)
            by_round = {int(item["round"]): item for item in active_data_report["rounds"]}
            for entry in participation_schedule:
                diagnostics_for_round = by_round.get(int(entry["round"]), {})
                entry["active_sample_count"] = int(diagnostics_for_round.get("active_sample_count", 0))
                entry["active_data_hash"] = str(diagnostics_for_round.get("active_data_hash", ""))
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
                client_class_counts=class_counts,
                labels_per_client=(
                    request.labels_per_client
                    if request.partition_mode == "label_limited"
                    else None
                ),
                participation_rate=request.participation_rate,
                dropout_rate=request.dropout_rate,
                round_schedule=participation_schedule,
                heterogeneity=measure_partition_heterogeneity(partition, y),
            )
            log(f"Partition ID: {fingerprint}")
            log(f"Realized heterogeneity: {partition_report.heterogeneity}")
            log(f"Active-data schedule ID: {active_data_report['active_data_fingerprint']}")
            log(f"Размеры клиентов: {counts}")
            if y is not None:
                for client_id, distribution in enumerate(class_counts, start=1):
                    pretty = ", ".join(f"{label}: {count}" for label, count in distribution.items())
                    log(f"Client {client_id}: n={counts[client_id - 1]} | classes: {pretty or '—'}")
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
            for entry in participation_schedule:
                selected = [client + 1 for client in entry["selected_clients"]]
                successful = [client + 1 for client in entry["successful_clients"]]
                dropped = [client + 1 for client in entry["dropped_clients"]]
                log(
                    f"Round {entry['round']}: selected={selected} | "
                    f"successful={successful} | dropped={dropped} | "
                    f"active_samples={entry.get('active_sample_count', 0)} | "
                    f"active_hash={entry.get('active_data_hash', '')}"
                )

        k_tuning: dict[str, Any] | None = None
        if aggregate_privacy and request.target_clusters is None:
            # Public dataset class counts, NOT computed from the private y array.
            benchmark_k = {'dry_bean': 7, 'iris': 3, 'wine': 3, 'digits': 10}.get(request.dataset_name)
            if benchmark_k is None:
                raise ValueError('Set a PUBLIC target_clusters for aggregate DP')
            cluster_count_source = 'published_public_dataset_k'
        elif request.cluster_count_mode == "estimated_k":
            benchmark_k, k_tuning = estimate_k_unlabeled(
                X_benchmark_raw, seed=request.seed, minimum=request.estimated_k_min,
                maximum=request.estimated_k_max, sample_size=request.tuning_sample_size,
                budget=request.tuning_budget,
            )
            cluster_count_source = "estimated_unlabeled_silhouette"
            log(f"Label-free estimated-k={benchmark_k}; candidates={k_tuning['candidates']}")
        elif request.target_clusters is not None:
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
            "participation_schedule": participation_schedule,
        }

        results: list[AlgorithmRunReport] = []
        for name in request.algorithms:
            log(f"\nЗапуск {name}…")
            algorithm = selected_algorithms[name]
            wall_started = time.perf_counter()
            X = (np.asarray(X_benchmark_raw, dtype=np.float64)
                 if aggregate_privacy else _preprocess_algorithm_input(X_benchmark_raw, algorithm))
            preprocessing = ('fixed_public_reference_then_l2_clip' if aggregate_privacy
                             else getattr(algorithm, "input_preprocessing", "standard"))
            log(f"Preprocessing {name}: {preprocessing}")

            params = dict(common_params)
            params.update(dict(getattr(algorithm, "default_params", {}) or {}))
            # Dataset-agnostic profile: sklearn/common conventions for local
            # baselines, author-preserving constants for Adapted algorithms.
            # Explicit caller overrides remain highest priority.
            params.update(defaults_for(name))
            params.update(request.algorithm_params)
            params.update(request.algorithm_params_by_name.get(name, {}))
            if aggregate_privacy:
                kind_map = {
                    'fed_kmeans_numpy': 'kmeans', 'fed_kmeans_flower': 'kmeans',
                    'fed_fuzzy_cmeans_numpy': 'fuzzy', 'fed_fuzzy_cmeans_flower': 'fuzzy',
                    'fed_gmm_diag_numpy': 'gmm', 'fed_gmm_diag_flower': 'gmm',
                    'Adapted FKM': 'kmeans', 'Adapted FKDC': 'kmeans',
                    'Adapted HF_DBSCAN': 'kmeans', 'Adapted NN-FC': 'kmeans',
                    'Adapted p-FClus': 'kmeans',
                }
                if name not in kind_map:
                    raise ValueError(f"{name}: no vetted aggregate DP mechanism available")
                params['dp_aggregate'] = make_dp_aggregate_config(
                    kind=kind_map[name], epsilon=request.dp_epsilon,
                    delta=request.dp_delta, clip_norm=request.dp_clip_norm,
                    rounds=(request.rounds if name not in ('Adapted FKDC','Adapted HF_DBSCAN','Adapted NN-FC','Adapted p-FClus') else 1),
                    enabled=(request.privacy_mode == 'gaussian_dp_aggregate'),
                )
                if name == 'Adapted HF_DBSCAN' and params['dp_aggregate']['enabled']:
                    log(f"DP aggregate {name}: 2-stage split epsilon/2 + epsilon/2; "
                        "actual per-stage sigma in model_state, not single-round value")
                else:
                    log(f"DP aggregate {name}: sigma/coordinate/round="
                        f"{params['dp_aggregate']['sigma_per_coordinate']:.4f}; "
                        f"epsilon/round={params['dp_aggregate']['epsilon_per_round']}")

            tuning_diagnostics: dict[str, Any] | None = None
            if request.tuning_mode == "unsupervised" and name == "dbscan":
                # Explicit eps beats automatic tuning. All candidate scores use only X.
                if params.get("eps") is None:
                    tuned_params, tuning_diagnostics = tune_dbscan_unlabeled(
                        X, seed=request.seed, sample_size=request.tuning_sample_size
                    )
                    params.update(tuned_params)
                    log(f"DBSCAN unsupervised tuning: selected={tuning_diagnostics.get('selected')}")
                else:
                    tuning_diagnostics = {"skipped": "explicit_eps_override"}

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
            wall_including_preprocessing = time.perf_counter() - wall_started

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
                "assigned_fraction": float(non_noise_total / len(labels)),
                "assigned_sample_count": int(non_noise_total),
                "metric_schema_version": METRIC_SCHEMA_VERSION,
                "unsupervised_parameter_tuning": tuning_diagnostics,
                "silhouette_reference_sample_count": int(len(silhouette_reference)),
                "silhouette_assigned_sample_count": int(np.sum(labels[silhouette_reference] != -1)),
                "silhouette_reference_hash": array_fingerprint(silhouette_reference),
                "silhouette_sampling_policy": (
                    f"full if n<={SILHOUETTE_MAX_POINTS}, otherwise fixed "
                    f"{SILHOUETTE_MAX_POINTS}-point index sample, seed={SILHOUETTE_SAMPLING_SEED}"
                ),
                "runtime_wall_including_preprocessing_sec": float(wall_including_preprocessing),
                "runtime_algorithm_call_sec": float(elapsed),
                "runtime_reported_by_algorithm_sec": float(runtime),
                "dominant_cluster_fraction": dominant_fraction,
                "degenerate": len(non_noise) < 2,
                "near_degenerate": len(non_noise) >= 2 and dominant_fraction >= 0.95,
                "low_coverage": non_noise_total / len(labels) < 0.5,
                "prediction_hash": prediction_fingerprint(labels),
                "raw_prediction_hash": array_fingerprint(np.asarray(labels, dtype=np.int64)),
                "client_metrics": client_external_metrics(y, labels, partition),
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
            if diagnostics["low_coverage"]:
                log(
                    f"WARNING: {name} assigned only "
                    f"{diagnostics['assigned_fraction']:.1%} of samples. "
                    "Internal metrics on assigned samples may be selection-biased."
                )

            state = dict(state)
            # Preserve the data-driven DBSCAN radius actually used by sklearn in
            # the auditable effective parameter block.  The profile still records
            # eps=None + eps_strategy, so reports show both rule and realization.
            if name == "dbscan" and state.get("eps") is not None:
                params["resolved_eps"] = float(state["eps"])
            supported_common = list(getattr(algorithm, "common_param_support", ()) or ())
            shared_names = ("k", "rounds", "tol", "max_iter", "density_min_samples", "seed")
            state["benchmark"] = {
                "seed": request.seed,
                "target_clusters": benchmark_k,
                "cluster_count_source": cluster_count_source,
                "cluster_count_tuning": k_tuning,
                "cluster_count_mode": request.cluster_count_mode,
                "parameter_tuning_mode": request.tuning_mode,
                "fairness_note": "Algorithm-specific budgets and computational equivalence require explicit matched control experiments.",
                "environment": {"python": sys.version.split()[0], "numpy": np.__version__,
                                "sklearn": sklearn.__version__, "scipy": scipy.__version__,
                                "platform": platform.platform(), "machine": platform.machine()},
                "communication_scope": "logical_payload_only_not_network_wire_bytes",
                "round_budget": request.rounds,
                "tol": request.tol,
                "max_iter": request.max_iter,
                "density_min_samples": request.density_min_samples,
                "num_clients": request.num_clients if request.mode == "federated" else None,
                "partition_mode": request.partition_mode if request.mode == "federated" else None,
                "min_samples_per_client": request.min_samples_per_client if request.mode == "federated" else None,
                "participation_rate": request.participation_rate if request.mode == "federated" else None,
                "dropout_rate": request.dropout_rate if request.mode == "federated" else None,
                "participation_schedule": participation_schedule if request.mode == "federated" else [],
                "privacy_mode": request.privacy_mode if request.mode == "federated" else "none",
                "dp_epsilon": request.dp_epsilon if request.privacy_mode in ("gaussian_dp", "gaussian_dp_aggregate") else None,
                "dp_delta": request.dp_delta if request.privacy_mode in ("gaussian_dp", "gaussian_dp_aggregate") else None,
                "dp_clip_norm": request.dp_clip_norm if request.privacy_mode != "none" else None,
                "privacy_report": dict(privacy_report),
                "benchmark_input_hash": benchmark_input_hash,
                "evaluation_input_hash": evaluation_input_hash,
                "evaluation_space": "StandardScaler(original_raw_X)",
                "metric_schema_version": METRIC_SCHEMA_VERSION,
                "internal_metric_population": "non-noise assigned samples only",
                "external_metric_population": "all samples, with -1 as an assigned noise label",
                "active_data_fingerprint": active_data_report.get("active_data_fingerprint"),
                "round_active_data": list(active_data_report.get("rounds", [])),
                "preprocessing": str(preprocessing),
                "common_param_support": supported_common,
                "common_params_not_applicable": [name for name in shared_names if name not in supported_common],
                "dataset_source_metadata": dataset_metadata,
                "parameter_profile": PROFILE_NAME,
                "profile_defaults": defaults_for(name),
                "effective_params": dict(params),
            }
            state["diagnostics"] = diagnostics

            metrics = compute_metrics(
                X=X_eval,
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

            is_author_dp_proxy = bool(state.get('not_equivalent_to_author_original', False))
            if is_author_dp_proxy:
                log(f"WARNING {name}: DP proxy author-SERVER variant, not the original author implementation")
            result = AlgorithmRunReport(
                algorithm=f"{name} [DP proxy]" if is_author_dp_proxy else name,
                backend='author-server DP proxy' if is_author_dp_proxy else backend,
                runtime_sec=runtime,
                communication_bytes=communication,
                rounds=rounds,
                ari=metrics.get("ari"),
                nmi=metrics.get("nmi"),
                ami=metrics.get("ami"),
                silhouette=metrics.get("silhouette"),
                davies_bouldin=metrics.get("davies_bouldin"),
                calinski_harabasz=metrics.get("calinski_harabasz"),
                model_state=state,
                history=history,
            )
            results.append(result)
            client_ari = ((diagnostics.get("client_metrics") or {}).get("ari") or {})
            client_summary = (
                f"; client ARI mean={client_ari.get('mean'):.4f}, "
                f"worst={client_ari.get('worst'):.4f}"
                if client_ari else ""
            )
            log(
                f"{name} завершён за {runtime:.4f} сек.; "
                f"prediction_hash={diagnostics['prediction_hash']}{client_summary}"
            )

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
            privacy_report=privacy_report,
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
