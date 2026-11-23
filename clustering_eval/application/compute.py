"""Execute one prepared job without creating a comparison partner or writing history."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, TYPE_CHECKING
from uuid import uuid4

import numpy as np
from threadpoolctl import threadpool_limits

from ..algorithms.registry import default_registry
from ..metrics.clustering import compute_metrics
from ..metrics.diagnostics import array_fingerprint
from .comparison_service import _adapter_identity, _get_registry_item, _invoke_algorithm, _is_federated, _preprocess_algorithm_input
from .compute_params import AGGREGATE_MODES, run_parameters, stopping_outcome
from .compute_report import assemble_report, benchmark_metadata, privacy_summary, run_diagnostics
from .dto import AlgorithmRunReport
from .flower_profile import runtime_rejection

if TYPE_CHECKING:
    from ..experiments.prepared import PreparedComparison


@dataclass(frozen=True)
class JobExecution:
    """One actual success. Labels and adapter state are trusted research outputs."""
    job_id: str
    attempt_id: str
    comparison_id: str
    source_id: str
    fingerprints: dict
    input_release_id: str | None
    started_at: datetime
    finished_at: datetime
    labels: np.ndarray
    model_state: dict
    report: AlgorithmRunReport


class JobExecutionError(RuntimeError):
    """An unsuccessful attempt, including release uncertainty after an adapter call."""
    def __init__(self, cause: Exception, provenance: dict) -> None:
        super().__init__(str(cause))
        self.provenance = provenance


def _materialize_input(prepared: PreparedComparison, job: dict, algorithm: Any) -> tuple[np.ndarray, str]:
    mode = prepared.comparison["protocol"]["privacy_mode"]
    if mode in AGGREGATE_MODES:
        if job["preprocessing"] not in {"fixed_public_reference_then_l2_clip", "clipped"}:
            raise ValueError("Prepared preprocessing differs from calibrated input")
        return np.array(prepared.X_train, dtype=np.float64, copy=True), job["preprocessing"]
    preprocessing = getattr(algorithm, "input_preprocessing", "standard")
    if job["preprocessing"] != preprocessing:
        raise ValueError(f"Adapter preprocessing changed for {job['algorithm']}")
    key = (prepared.fingerprints["train"], prepared.X_train.dtype.str, prepared.X_train.shape,
           prepared.privacy_report.get("release_id"), preprocessing)
    if key not in prepared.transform_cache:
        if mode == "none" and preprocessing == "standard":
            transformed = prepared.X_eval
        else:
            transformed = _preprocess_algorithm_input(prepared.X_train, algorithm)
        transformed.flags.writeable = False
        prepared.transform_cache[key] = transformed
    return prepared.transform_cache[key].copy(), preprocessing


def _aggregate_evidence(algorithm: Any, name: str, params: dict, state: dict, history: list) -> dict:
    """Describe joint queries (separate from the number of scalar Gaussian draws)."""
    reference_type = type(default_registry().get(name))
    if type(algorithm) is not reference_type or getattr(algorithm.run, "__func__", None) is not reference_type.run:
        # An injected replacement may ignore the mechanism or self-report a built-in backend.
        return {"aggregate_release_status": "unknown", "joint_queries": None}
    cfg = params["dp_aggregate"]
    if not cfg["enabled"]:
        return {"aggregate_release_status": "no_noise_control", "noise_source": None,
                "joint_queries": 0}
    if state.get("backend") == "author-server DP proxy":
        clients = state["noised_client_prototype_queries"]
        stages = {"client_prototypes": {"joint_queries": clients, "sigma_per_coordinate":
                                       state["dp_sigma_prototype_per_coordinate"]}}
        if name == "Adapted HF_DBSCAN":
            stages["candidate_histogram"] = {"joint_queries": state["noised_histogram_queries"], "sigma_per_coordinate":
                                              state["dp_sigma_histogram_per_coordinate"]}
        return {"aggregate_release_status": "observed", "noise_source": "OS CSPRNG",
                "joint_queries": sum(s["joint_queries"] for s in stages.values()), "stages": stages}
    if state.get("backend") == "numpy-federated" and cfg["sigma_per_coordinate"] > 0 and history:
        return {"aggregate_release_status": "observed", "noise_source": "OS CSPRNG",
                "joint_queries": len(history), "sigma_per_coordinate": cfg["sigma_per_coordinate"]}
    return {"aggregate_release_status": "unknown", "joint_queries": None}


def execute_one(prepared: PreparedComparison, job_id: str) -> JobExecution:
    """Run a single worker call. Protocol errors and failures never create result rows."""
    return _execute_one(prepared, job_id, None, gui=False)


def _execute_one(prepared: PreparedComparison, job_id: str, registry: Any | None, *, gui: bool) -> JobExecution:
    prepared.validate_bindings()
    jobs = [item for item in prepared.jobs if item["job_id"] == job_id]
    if len(jobs) != 1:
        raise ValueError(f"Expected one prepared job for {job_id!r}")
    job = jobs[0]
    protocol = prepared.comparison["protocol"]
    name = job["algorithm"]
    started_at = datetime.now(timezone.utc)
    start = perf_counter()
    attempt_id = uuid4().hex
    provenance = {
        "source_id": prepared.source_id, "dataset_id": prepared.dataset["dataset_id"],
        "comparison_id": prepared.comparison["comparison_id"], "job_id": job_id, "attempt_id": attempt_id,
        "dataset_fingerprints": deepcopy(prepared.fingerprints),
        "started_at_utc": started_at.isoformat(), "requested_backend": job["backend"],
        "requested_execution_profile": deepcopy(job.get("execution_profile")),
        "execution_scope": "adapter_call_in_current_process", "shared_setup_sec": prepared.setup_sec,
        "privacy_mode": protocol["privacy_mode"], "input_release_id": prepared.privacy_report.get("release_id"),
        "input_release_status": prepared.privacy_report.get("release_status"),
        "aggregate_release_status": "not_started" if protocol["privacy_mode"] == "gaussian_dp_aggregate" else "not_applicable",
    }
    try:
        if not gui:
            rejected = runtime_rejection(job, protocol)
            if rejected:
                raise ValueError(rejected)
        algorithm = _get_registry_item(registry if registry is not None else default_registry(), name)
        if gui and _adapter_identity(algorithm) != job["backend"]:
            raise ValueError(f"Prepared GUI adapter implementation changed for {name!r}")
        if _is_federated(name, algorithm) != (protocol["mode"] == "federated"):
            raise ValueError(f"{name!r} does not support mode {protocol['mode']!r}")
        profile = job.get("execution_profile")
        threads = profile.get("blas_threads") if isinstance(profile, dict) else None
        with threadpool_limits(limits=threads, user_api="blas"):
            before_transform = perf_counter()
            X, preprocessing = _materialize_input(prepared, job, algorithm)
            after_transform = perf_counter()
            params, tuning = run_parameters(prepared, job, X)
            input_hash = array_fingerprint(X, length=64)
            adapter_params = deepcopy(params)
            if not gui and job["backend"] == "flower-simulation":
                adapter_params["_campaign_cold_flower"] = True
            before_call = perf_counter()
            if protocol["privacy_mode"] == "gaussian_dp_aggregate":
                # An exception, including a postprocessing failure, can follow a private draw.
                provenance["aggregate_release_status"] = "unknown"
            raw = _invoke_algorithm(algorithm, X=X, partition=prepared.partition,
                                    params=adapter_params, seed=prepared.comparison["seed"])
            after_call = perf_counter()
            labels = np.asarray(getattr(raw, "labels", raw if isinstance(raw, np.ndarray) else None))
            if labels.ndim != 1 or len(labels) != len(X):
                raise ValueError(f"{name} returned labels with shape {labels.shape} for {len(X)} rows")
            state = dict(getattr(raw, "model_state", {}) or {})
            history = list(getattr(raw, "history", []) or [])
            if "dp_aggregate" in params:
                provenance.update(_aggregate_evidence(algorithm, name, params, state, history))
                if provenance["aggregate_release_status"] == "observed":
                    cfg = params["dp_aggregate"]
                    provenance["upper_bound_epsilon"] = cfg["epsilon_total"]
                    provenance["upper_bound_delta"] = cfg["delta_total"]
            metrics = compute_metrics(prepared.X_eval, prepared.y, labels, list(protocol["metrics"]))
        elapsed = after_call - before_call
        reported = getattr(raw, "runtime_sec", None)
        reported = float(reported) if reported is not None and reported > 0 else None
        runtime = elapsed if reported is None else reported
        # Local sklearn adapters omit the backend field. The actual registered class supplies it.
        backend = state.get("backend")
        if backend is None:
            backend = "local" if algorithm.__class__.__module__.endswith(".sklearn_algorithms") else type(algorithm).__name__
        if not gui and backend != job["backend"]:
            raise ValueError(f"{name}: requested backend {job['backend']!r}, executed {backend!r}")
        privacy = privacy_summary(prepared, [provenance], scope="this_successful_attempt_only")
        annotated = dict(state)
        benchmark = benchmark_metadata(prepared, job, algorithm, params, preprocessing, input_hash, privacy)
        if name == "dbscan" and state.get("eps") is not None:
            realized_eps = float(state["eps"])
            benchmark["adapter_observations"] = {"resolved_eps": realized_eps}
            # Keep the native history view used by earlier DBSCAN reports.
            benchmark["effective_params"] = {**params, "resolved_eps": realized_eps}
        annotated["benchmark"] = benchmark
        annotated["diagnostics"] = run_diagnostics(
            labels, prepared.y, prepared.partition, annotated["benchmark"]["target_clusters"], tuning,
            elapsed=elapsed, reported_runtime=reported, preprocessing_sec=after_transform-before_transform,
            wall_including_preprocessing=after_call-start,
        )
        rounds = state.get("rounds", len(history) if history else "—")
        communication = getattr(raw, "communication_bytes", None)
        provenance.update(
            runtime_source="adapter" if reported is not None else "measured_call",
            parameter_setup_sec=before_call-after_transform,
            communication_bytes_observed=communication, backend=backend,
            stopping=stopping_outcome(name, state, protocol),
            source_scope=prepared.comparison.get("source_scope", "campaign_source_snapshot"),
        )
        proxy = state.get("not_equivalent_to_author_original", False)
        report = AlgorithmRunReport(
            algorithm=f"{name} [DP proxy]" if proxy else name, backend=str(backend),
            runtime_sec=runtime, communication_bytes=None if communication is None else int(communication), rounds=rounds,
            model_state=annotated, history=history,
            **{key: metrics.get(key) for key in ("ari","ami","nmi","silhouette","davies_bouldin","calinski_harabasz")},
        )
        finished_at = datetime.now(timezone.utc)
        provenance.update(finished_at_utc=finished_at.isoformat(), elapsed_sec=perf_counter()-start)
        annotated["execution"] = provenance
        return JobExecution(job_id, attempt_id, provenance["comparison_id"], prepared.source_id,
                            provenance["dataset_fingerprints"], provenance["input_release_id"],
                            started_at, finished_at, labels, state, report)
    except Exception as exc:
        provenance.update(finished_at_utc=datetime.now(timezone.utc).isoformat(), elapsed_sec=perf_counter()-start)
        raise JobExecutionError(exc, provenance) from exc
