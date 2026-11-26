"""Shared scientific inputs for individual campaign and interactive comparison runs."""
from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import numpy as np
from sklearn.preprocessing import StandardScaler

from ..datasets.partitioning import make_partition
from ..federated.environment import make_participation_schedule
from ..metrics.diagnostics import active_data_diagnostics, array_fingerprint
from ..metrics.protocol_v2 import estimate_k_unlabeled
from ..privacy.aggregate_dp import clipped_public_features
from ..privacy.gaussian import apply_gaussian_input_dp
from .archive_inputs import canonical
from .archive_protocol import check_schedule


class ProtectedPartition(list):
    """Keep one adapter-compatible list object and prevent cross-method index replacement."""

    def __init__(self, rows: Iterable[np.ndarray]) -> None:
        super().__init__(rows)
        for row in self:
            row.flags.writeable = False

    def __reduce__(self) -> tuple:
        # Multiprocessing transports reconstruct through the protected constructor.
        return type(self), (list(self),)

    def _readonly(self, *args, **kwargs) -> None:
        raise TypeError("A shared client partition is read-only")

    __setitem__ = __delitem__ = __iadd__ = __imul__ = _readonly
    append = clear = extend = insert = pop = remove = reverse = sort = _readonly


@dataclass(frozen=True)
class PreparedComparison:
    """Trusted inputs shared across a comparison. Arrays are read-only."""
    source_id: str
    dataset: dict
    comparison: dict
    jobs: list[dict]
    X_raw: np.ndarray
    y: np.ndarray | None
    X_train: np.ndarray
    X_eval: np.ndarray
    partition: list[np.ndarray] | None
    schedule: list[dict]
    active_data: dict
    privacy_report: dict
    fingerprints: dict
    estimated_k: int | None
    k_tuning: dict | None
    setup_sec: float
    transform_cache: dict = field(default_factory=dict, repr=False)
    _binding: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_binding", self._record_digest())

    def _record_digest(self) -> bytes:
        return sha256(canonical([self.source_id, self.dataset, self.comparison, self.jobs,
                                 self.schedule, self.active_data, self.privacy_report, self.fingerprints,
                                 self.estimated_k, self.k_tuning])).digest()

    def validate_bindings(self) -> None:
        """Reject changes to scientific records since preparation or verified reopen."""
        if self._record_digest() != self._binding:
            raise ValueError("Prepared scientific records changed after preparation")


def _client_inputs(X: np.ndarray, y: np.ndarray | None, protocol: dict, seed: int,
                   partition: list[np.ndarray] | None) -> tuple[list | None, list, dict]:
    legacy = protocol.get("compatibility_profile") == "legacy-run.v1"
    schedule = []
    diagnostics = {"rounds": [], "active_data_fingerprint": None}
    if protocol["mode"] == "local" and not legacy:
        if partition is not None or protocol.get("participation_schedule"):
            raise ValueError("Local comparison cannot have client inputs")
        return None, schedule, diagnostics
    count = protocol["num_clients"]
    minimum = protocol["min_samples_per_client"]
    if partition is None:
        partition = make_partition(protocol["partition_mode"], len(X), count, seed, y=y,
                                   alpha=protocol.get("dirichlet_alpha", 0.5),
                                   min_samples_per_client=minimum,
                                   labels_per_client=protocol.get("labels_per_client", 2))
    partition = ProtectedPartition(np.array(indices, copy=True) for indices in partition)
    if (len(partition) != count or
        any(row.ndim != 1 or row.dtype.kind not in "iu" or len(row) < minimum for row in partition)
        or not np.array_equal(np.sort(np.concatenate(partition)), np.arange(len(X)))):
        raise ValueError("Client partition must cover the data exactly once with the requested client sizes")
    if legacy:
        return partition, schedule, diagnostics
    if "participation_schedule" in protocol:
        schedule = deepcopy(protocol["participation_schedule"])
    else:
        schedule = make_participation_schedule(num_clients=count, rounds=protocol["rounds"],
                                               participation_rate=protocol["participation_rate"],
                                               dropout_rate=protocol["dropout_rate"], seed=seed)
    check_schedule(schedule, count, protocol["rounds"], "participation_schedule")
    diagnostics = active_data_diagnostics(partition, schedule)
    if "participation_schedule" not in protocol:
        for entry, info in zip(schedule, diagnostics["rounds"], strict=True):
            entry.update(info)
    return partition, schedule, diagnostics


def _training_input(X: np.ndarray, comparison: dict, dataset: dict, jobs: list[dict],
                    public_reference: dict | None) -> tuple[np.ndarray, dict]:
    protocol = comparison["protocol"]
    mode = protocol["privacy_mode"]
    report = dict(mode=mode, comparison_id=comparison["comparison_id"], release_id=None,
                  release_status="no_input_release", end_to_end_report_is_dp=False)
    if mode == "none":
        return X, report
    if protocol["mode"] != "federated":
        raise ValueError("Privacy protocols require a federated comparison")
    if mode == "gaussian_dp":
        trained, mechanism = apply_gaussian_input_dp(
            X, epsilon=protocol["dp_epsilon"], delta=protocol["dp_delta"],
            clip_norm=protocol["dp_clip_norm"], seed=comparison["seed"])
        report.update(mechanism, release_id=uuid4().hex, release_status="released",
                      release_scope="one_shared_input_matrix_per_comparison",
                      nonprivate_report_outputs=["Evaluation on original X and labels",
                                                 "Partition metadata and trusted diagnostics"],
                      public_release_warning="The full benchmark report is NOT end-to-end differentially private.")
        return trained, report
    if mode not in {"gaussian_dp_aggregate", "public_clipped_control"}:
        raise ValueError(f"Unknown privacy mode {mode!r}")
    is_dp = mode == "gaussian_dp_aggregate"
    if protocol.get("cluster_count_mode") != "known_k":
        raise ValueError("Aggregate preprocessing requires a public known-k")
    if is_dp and protocol["partition_mode"] in {"dirichlet", "label_limited"}:
        raise ValueError("Label-dependent partitioning is outside the aggregate DP accounting")
    options = {} if public_reference is None else {"public_reference": public_reference}
    train, public = clipped_public_features(X, dataset["name"], protocol["dp_clip_norm"], **options)
    adapted = any(job["algorithm"].startswith("Adapted ") for job in jobs)
    report.update(
        privacy_protocol_version="trusted_aggregate_dp_v2_author_server_surrogates",
        mechanism=("trusted-server Gaussian aggregate sufficient statistics" if is_dp else
                   "matched fixed-public-scaled clipping control; NO PRIVACY"),
        author_algorithm_dp_scope=("Adapted variants use modified author-server postprocessing"
                                   if adapted else "no Adapted author algorithms selected"),
        comparability_warning=("Analyze author-server variants separately from original author methods."
                               if adapted else "Compare aggregate DP with matched clipping control."),
        epsilon=protocol["dp_epsilon"] if is_dp else None, delta=protocol["dp_delta"] if is_dp else None,
        clip_norm_public_space=protocol["dp_clip_norm"], public_preprocessing=public,
        per_algorithm_privacy_budgets_compose=is_dp, server_receives_unprotected_client_statistics=True,
        public_release_warning="Trusted server only. The benchmark report and labels are not end-to-end DP.")
    return train, report


def build_inputs(*, X: np.ndarray, y: np.ndarray | None, dataset: dict, comparison: dict,
                 jobs: list[dict], source_id: str, partition: list[np.ndarray] | None = None,
                 public_reference: dict | None = None) -> PreparedComparison:
    """Prepare one trusted, already validated request. Use prepare for an external plan."""
    started = perf_counter()
    raw = np.array(X, copy=True, order="C")
    if (raw.ndim != 2 or len(raw) < 3 or raw.shape[1] < 1 or raw.dtype.kind not in "biuf"
            or not np.isfinite(raw).all()):
        raise ValueError("Expected a finite numeric feature matrix")
    labels = None if y is None else np.array(y, copy=True)
    if labels is not None and labels.shape != (len(raw),):
        raise ValueError("Expected one reference label per data row")
    protocol = comparison["protocol"]
    if protocol["mode"] not in {"local", "federated"}:
        raise ValueError("Unsupported comparison mode")
    legacy = protocol.get("compatibility_profile")
    if legacy not in {None, "legacy-run.v1"}:
        raise ValueError("Unsupported compatibility profile")
    if protocol["mode"] == "federated":
        valid = {"legacy_run"} if legacy else {"current_gui", "historical_paper"}
        if protocol.get("stopping_profile") not in valid:
            raise ValueError("Missing or unsupported federated stopping_profile")
    partition, schedule, active = _client_inputs(raw, labels, protocol, comparison["seed"], partition)
    numeric = np.asarray(raw, dtype=np.float64)
    X_eval = StandardScaler().fit_transform(numeric)
    X_train, privacy = _training_input(numeric, comparison, dataset, jobs, public_reference)
    estimated, tuning = None, None
    if protocol.get("cluster_count_mode") == "estimated_k":
        estimated, tuning = estimate_k_unlabeled(
            X_train, seed=comparison["seed"], minimum=protocol["estimated_k_min"],
            maximum=protocol["estimated_k_max"], sample_size=protocol["tuning_sample_size"],
            budget=protocol["tuning_budget"])
        # A collapsed candidate has an undefined silhouette. Retain its outcome in JSON.
        for candidate in tuning["candidates"]:
            if not np.isfinite(candidate["silhouette"]):
                candidate["silhouette"] = None
    hashes = {name: array_fingerprint(arr, length=64) for name, arr in
              (("raw", raw), ("train", X_train), ("evaluation", X_eval))}
    hashes["partition"] = (sha256(canonical([row.tolist() for row in partition])).hexdigest()
                           if partition is not None else None)
    hashes["schedule"] = sha256(canonical(schedule)).hexdigest() if schedule else None
    if privacy["mode"] == "gaussian_dp":
        privacy["release_fingerprint"] = hashes["train"]
    for array in (raw, labels, X_train, X_eval):
        if array is not None:
            array.flags.writeable = False
    return PreparedComparison(source_id, deepcopy(dataset), deepcopy(comparison), deepcopy(jobs),
                              raw, labels, X_train, X_eval, partition, schedule, active, privacy, hashes,
                              estimated, tuning, perf_counter() - started)


def prepare(resolved_plan: dict, comparison_id: str, destination: Path, *,
            source_id: str, base_dir: Path) -> Path:
    """Validate one selected PLAN comparison and publish its reusable descriptor.

    A destination identifies one preparation attempt. Retain the adjacent reservation
    with the bundle to distinguish an interrupted/lost release from a new attempt.
    Repeating prepare with the same destination verifies and returns the existing release.
    """
    from .prepared_plan import select_inputs
    from .prepared_store import publish
    from .series_plan import checkout_source_id

    if source_id != resolved_plan.get("source_id") or source_id != checkout_source_id():
        raise ValueError("Resolved plan source_id differs from the running source")
    inputs = select_inputs(resolved_plan, comparison_id, base_dir=Path(base_dir))
    return publish(Path(destination), inputs, source_id)


def reopen(descriptor: Path, *, source_id: str, comparison_id: str | None = None) -> PreparedComparison:
    """Open a relocated descriptor without reading original data or generating privacy noise."""
    from .prepared_store import read
    from .series_plan import checkout_source_id

    if source_id != checkout_source_id():
        raise ValueError("Requested source_id differs from the running source")
    return read(Path(descriptor), source_id, comparison_id)
