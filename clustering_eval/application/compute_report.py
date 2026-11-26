"""Native reports and trusted per-attempt diagnostics for prepared comparisons."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import platform
import sys
from typing import Any, TYPE_CHECKING
from uuid import uuid4

import numpy as np
import scipy
import sklearn

from ..datasets.partitioning import partition_class_counts, partition_fingerprint
from ..default_profile import PROFILE_NAME, defaults_for
from ..metrics.clustering import (
    METRIC_SCHEMA_VERSION, SILHOUETTE_MAX_POINTS, SILHOUETTE_SAMPLING_SEED,
    silhouette_reference_indices,
)
from ..metrics.diagnostics import array_fingerprint, client_external_metrics, prediction_fingerprint
from ..metrics.protocol_v2 import measure_partition_heterogeneity
from .dto import CampaignReportRequest, ComparisonReport, PartitionReport, RunRequest

if TYPE_CHECKING:
    from ..experiments.prepared import PreparedComparison
    from .compute import JobExecution


def run_diagnostics(labels: np.ndarray, y: np.ndarray | None, partition: list | None,
                    benchmark_k: int | None, tuning_diagnostics: dict | None, *,
                    elapsed: float, reported_runtime: float | None,
                    preprocessing_sec: float, wall_including_preprocessing: float) -> dict:
    silhouette_reference = silhouette_reference_indices(len(labels))
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
        "cluster_count_delta_vs_benchmark_k": None if benchmark_k is None else len(non_noise) - benchmark_k,
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
        "preprocessing_sec": preprocessing_sec,
        "runtime_reported_by_algorithm_sec": reported_runtime,
        "dominant_cluster_fraction": dominant_fraction,
        "degenerate": len(non_noise) < 2,
        "near_degenerate": len(non_noise) >= 2 and dominant_fraction >= 0.95,
        "low_coverage": non_noise_total / len(labels) < 0.5,
        "prediction_hash": prediction_fingerprint(labels),
        "raw_prediction_hash": array_fingerprint(np.asarray(labels, dtype=np.int64)),
        "client_metrics": client_external_metrics(y, labels, partition),
    }

    return diagnostics


def benchmark_metadata(prepared: PreparedComparison, job: dict, algorithm: Any, params: dict,
                       preprocessing: str, input_hash: str, privacy: dict) -> dict:
    protocol = prepared.comparison["protocol"]
    legacy = protocol.get("compatibility_profile") == "legacy-run.v1"
    historical = "historical_implementation" in protocol
    k = job.get("legacy_benchmark_k", protocol.get("target_clusters"))
    if protocol.get("cluster_count_mode") == "estimated_k":
        k = prepared.estimated_k
    supported = list(getattr(algorithm, "common_param_support", ()))
    profile = "historical_paper" if historical else "legacy-run.v1" if legacy else PROFILE_NAME
    effective_k = None
    if "k" in supported or "dp_aggregate" in params:
        key = "n_clusters" if job["algorithm"].startswith("Adapted ") and "dp_aggregate" not in params else "k"
        effective_k = params.get(key)
    return {
        "seed": prepared.comparison["seed"], "target_clusters": k,
        "cluster_count_source": protocol.get("cluster_count_source", "legacy_benchmark" if legacy else "historical_protocol"),
        "cluster_count_tuning": prepared.k_tuning, "cluster_count_mode": protocol.get("cluster_count_mode"),
        "parameter_tuning_mode": protocol.get("tuning_mode"),
        "fairness_note": "Algorithm-specific budgets and computational equivalence require explicit matched control experiments.",
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__, "scipy": scipy.__version__,
                        "sklearn": sklearn.__version__, "platform": platform.platform(), "machine": platform.machine()},
        "communication_scope": "logical_payload_only_not_network_wire_bytes",
        "round_budget": protocol.get("rounds", params.get("rounds")),
        "effective_round_budget": params.get("rounds") if "rounds" in supported else None,
        "effective_k": effective_k,
        "tol": protocol.get("tol", params.get("tol")), "max_iter": protocol.get("max_iter", params.get("max_iter")),
        "density_min_samples": protocol.get("density_min_samples"),
        **{key: protocol.get(key) if prepared.partition is not None else None for key in
           ("num_clients", "partition_mode", "min_samples_per_client", "participation_rate", "dropout_rate")},
        "participation_schedule": deepcopy(prepared.schedule), "privacy_mode": protocol["privacy_mode"],
        "dp_epsilon": protocol.get("dp_epsilon") if protocol["privacy_mode"].startswith("gaussian_dp") else None,
        "dp_delta": protocol.get("dp_delta") if protocol["privacy_mode"].startswith("gaussian_dp") else None,
        "dp_clip_norm": protocol.get("dp_clip_norm") if protocol["privacy_mode"] != "none" else None,
        "privacy_report": deepcopy(privacy),
        "benchmark_input_hash": array_fingerprint(prepared.X_train),
        "evaluation_input_hash": array_fingerprint(prepared.X_eval),
        "algorithm_input_hash": input_hash,
        "evaluation_space": protocol.get("evaluation_space", "StandardScaler(original_raw_X)"),
        "metric_schema_version": METRIC_SCHEMA_VERSION, "metrics": list(protocol["metrics"]),
        "internal_metric_population": "non-noise assigned samples only",
        "external_metric_population": "all samples, with -1 as an assigned noise label",
        "active_data_fingerprint": prepared.active_data.get("active_data_fingerprint"),
        "round_active_data": deepcopy(prepared.active_data.get("rounds", [])),
        "preprocessing": preprocessing, "common_param_support": supported,
        "common_params_not_applicable": [k for k in ("k","rounds","tol","max_iter","density_min_samples","seed") if k not in supported],
        "dataset_source_metadata": deepcopy(prepared.dataset.get("metadata", {})),
        "parameter_profile": profile, "profile_defaults": defaults_for(job["algorithm"]) if profile == PROFILE_NAME else {},
        "effective_params": params, "parameter_sources": deepcopy(job.get("parameter_sources", {})),
    }


def partition_summary(prepared: PreparedComparison) -> PartitionReport | None:
    part = prepared.partition
    if part is None:
        return None
    protocol = prepared.comparison["protocol"]
    return PartitionReport(
        mode=protocol["partition_mode"], num_clients=len(part),
        client_sample_counts=[len(client) for client in part], fingerprint=partition_fingerprint(part),
        dirichlet_alpha=protocol.get("dirichlet_alpha") if protocol["partition_mode"] == "dirichlet" else None,
        client_class_counts=partition_class_counts(part, prepared.y),
        labels_per_client=protocol.get("labels_per_client") if protocol["partition_mode"] == "label_limited" else None,
        participation_rate=protocol.get("participation_rate", 1.), dropout_rate=protocol.get("dropout_rate", 0.),
        round_schedule=deepcopy(prepared.schedule), heterogeneity=measure_partition_heterogeneity(part, prepared.y),
    )


def privacy_summary(prepared: PreparedComparison, attempts: list[dict], *, scope: str) -> dict:
    """Compose only the supplied attempts. The supervisor accounts for other attempts."""
    privacy = deepcopy(prepared.privacy_report)
    privacy.update(scope=scope, algorithm_count=len(attempts))
    protocol = prepared.comparison["protocol"]
    if protocol["privacy_mode"] == "gaussian_dp_aggregate":
        observed = all(attempt["aggregate_release_status"] == "observed" for attempt in attempts)
        privacy["aggregate_release_status"] = "observed" if observed else "unknown"
        if observed:
            privacy["upper_bound_epsilon_across_selected_algorithms"] = sum(a["upper_bound_epsilon"] for a in attempts)
            privacy["upper_bound_delta_across_selected_algorithms"] = min(1., sum(a["upper_bound_delta"] for a in attempts))
        else:
            for key in ("mechanism", "epsilon", "delta", "author_algorithm_dp_scope"):
                privacy["requested_" + key] = privacy.pop(key, None)
            privacy.update(upper_bound_epsilon_across_selected_algorithms=None,
                           upper_bound_delta_across_selected_algorithms=None,
                           per_algorithm_privacy_budgets_compose=None)
    return privacy


def assemble_report(prepared: PreparedComparison, executions: list[JobExecution]) -> ComparisonReport:
    """Build a native report whose interval and scope come from actual successes."""
    return _assemble_report(prepared, executions)


def _assemble_report(prepared: PreparedComparison, executions: list[JobExecution], *,
                    request: RunRequest | None = None, started_at: datetime | None = None,
                    finished_at: datetime | None = None, log_lines: list[str] | None = None,
                    partition: PartitionReport | None = None) -> ComparisonReport:
    """Build a native comparison from actual successes for the same prepared inputs."""
    prepared.validate_bindings()
    if not executions:
        raise ValueError("A comparison report requires at least one completed job")
    jobs = {job["job_id"]: job for job in prepared.jobs}
    seen = set()
    for execution in executions:
        if (execution.job_id not in jobs or execution.job_id in seen
                or execution.comparison_id != prepared.comparison["comparison_id"]
                or execution.source_id != prepared.source_id or execution.fingerprints != prepared.fingerprints
                or execution.input_release_id != prepared.privacy_report.get("release_id")):
            raise ValueError("Repeated job or execution from different prepared inputs/release")
        seen.add(execution.job_id)
    protocol = prepared.comparison["protocol"]
    if request is None:
        request = CampaignReportRequest(
            mode=protocol["mode"], dataset_name=prepared.dataset["name"],
            algorithms=tuple(jobs[e.job_id]["algorithm"] for e in executions),
            seed=prepared.comparison["seed"], protocol=deepcopy(protocol),
        )
    return ComparisonReport(
        experiment_id=uuid4().hex, started_at=started_at or min(e.started_at for e in executions),
        finished_at=finished_at or max(e.finished_at for e in executions), request=request,
        dataset_display_name=prepared.dataset.get("display_name", prepared.dataset["name"]),
        n_samples=len(prepared.X_raw), n_features=prepared.X_raw.shape[1], results=[e.report for e in executions],
        partition=partition if partition is not None else partition_summary(prepared),
        log_lines=[] if log_lines is None else log_lines,
        privacy_report=privacy_summary(prepared, [e.report.model_state["execution"] for e in executions],
                                       scope="included_successful_attempts_only"),
    )
