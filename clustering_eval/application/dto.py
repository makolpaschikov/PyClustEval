from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any, Literal


RunMode = Literal["local", "federated"]
PartitionMode = Literal["iid", "dirichlet", "quantity_skew", "label_limited"]
PrivacyMode = Literal["none", "gaussian_dp", "gaussian_dp_aggregate", "public_clipped_control"]


@dataclass(frozen=True, slots=True)
class RunRequest:
    mode: RunMode
    dataset_name: str
    algorithms: tuple[str, ...]
    seed: int = 42
    num_clients: int = 5
    partition_mode: PartitionMode = "iid"
    dirichlet_alpha: float = 0.5
    # Common benchmark controls. target_clusters=None means use the number of
    # ground-truth classes only as an explicit oracle-k benchmark condition.
    target_clusters: int | None = None
    cluster_count_mode: Literal["known_k", "estimated_k"] = "known_k"
    estimated_k_min: int = 2
    estimated_k_max: int = 12
    tuning_sample_size: int = 1000
    tuning_budget: int = 8
    tuning_mode: Literal["none", "unsupervised"] = "none"
    rounds: int = 10
    tol: float = 1e-4
    max_iter: int = 300
    # Shared density-neighborhood threshold for DBSCAN-family algorithms.
    # Algorithm-specific radius parameters (eps/L) remain separate.
    density_min_samples: int = 5
    min_samples_per_client: int = 3
    # Hidden benchmark default for the label-limited stress scenario.
    labels_per_client: int = 2
    # Federated-environment stress controls.  Participation is sampled once per
    # benchmark round and reused by every selected algorithm.  Dropout is
    # applied after client selection; at least one successful client is kept.
    participation_rate: float = 1.0
    dropout_rate: float = 0.0
    # Algorithm-independent record-level Gaussian input perturbation.  Raw
    # feature vectors are L2-clipped/noised once and the same privatized matrix
    # is passed through each algorithm's declared preprocessing.
    privacy_mode: PrivacyMode = "none"
    dp_epsilon: float = 5.0
    dp_delta: float = 1e-5
    dp_clip_norm: float = 1.0
    # Legacy/global overrides plus optional per-algorithm overrides.
    algorithm_params: dict[str, Any] = field(default_factory=dict)
    algorithm_params_by_name: dict[str, dict[str, Any]] = field(default_factory=dict)

    def validate(self) -> None:
        if self.mode not in ("local", "federated"):
            raise ValueError(f"Unsupported run mode: {self.mode}")
        if not self.dataset_name:
            raise ValueError("dataset_name cannot be empty")
        if len(self.algorithms) < 2:
            raise ValueError("At least two algorithms are required")
        if len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError("Algorithms must be unique")
        if self.cluster_count_mode not in ("known_k", "estimated_k"):
            raise ValueError("Invalid cluster_count_mode")
        if self.cluster_count_mode == "estimated_k" and self.target_clusters is not None:
            raise ValueError("estimated_k mode cannot use an explicit target_clusters")
        if self.estimated_k_min < 2 or self.estimated_k_max < self.estimated_k_min:
            raise ValueError("Invalid estimated k bounds")
        if self.tuning_sample_size < 25 or self.tuning_budget < 1:
            raise ValueError("Invalid tuning resource budget")
        if self.tuning_mode not in ("none", "unsupervised"):
            raise ValueError("Unsupported tuning mode")
        if self.target_clusters is not None and self.target_clusters < 2:
            raise ValueError("target_clusters must be at least 2 when provided")
        if type(self.rounds) is not int or self.rounds < 1:
            raise ValueError("rounds must be a positive integer")
        for field_name in ("tol", "dp_epsilon", "dp_delta", "dp_clip_norm"):
            value = getattr(self, field_name)
            if type(value) not in (int, float) or not isfinite(value):
                raise ValueError(f"{field_name} must be finite")
        if self.target_clusters is not None and type(self.target_clusters) is not int:
            raise ValueError("target_clusters must be an integer")
        for layer in (self.algorithm_params, *self.algorithm_params_by_name.values()):
            if not isinstance(layer, dict):
                raise ValueError("Expected a mapping of algorithm overrides")
            for key in ("rounds", "k", "n_clusters"):
                if key in layer and (type(layer[key]) is not int or layer[key] < 1):
                    raise ValueError(f"Override {key} must be a positive integer")
            if "k" in layer and "n_clusters" in layer and layer["k"] != layer["n_clusters"]:
                raise ValueError("Conflicting k and n_clusters overrides in the same layer")
            if "tol" in layer and (type(layer["tol"]) not in (int, float)
                                   or not isfinite(layer["tol"]) or layer["tol"] <= 0):
                raise ValueError("Override tol must be finite and positive")
        if self.tol <= 0:
            raise ValueError("tol must be greater than zero")
        if self.max_iter < 1:
            raise ValueError("max_iter must be at least 1")
        if self.density_min_samples < 1:
            raise ValueError("density_min_samples must be at least 1")
        if self.min_samples_per_client < 1:
            raise ValueError("min_samples_per_client must be at least 1")
        if self.labels_per_client < 1:
            raise ValueError("labels_per_client must be at least 1")
        if not 0 < self.participation_rate <= 1:
            raise ValueError("participation_rate must be in (0, 1]")
        if not 0 <= self.dropout_rate < 1:
            raise ValueError("dropout_rate must be in [0, 1)")
        if self.privacy_mode not in ("none", "gaussian_dp", "gaussian_dp_aggregate", "public_clipped_control"):
            raise ValueError(f"Unsupported privacy mode: {self.privacy_mode}")
        if self.dp_epsilon <= 0:
            raise ValueError("dp_epsilon must be greater than zero")
        if not 0 < self.dp_delta < 1:
            raise ValueError("dp_delta must be in (0, 1)")
        if self.dp_clip_norm <= 0:
            raise ValueError("dp_clip_norm must be greater than zero")
        if self.privacy_mode in ("gaussian_dp_aggregate", "public_clipped_control") and self.dp_clip_norm > 20:
            raise ValueError("Aggregate DP uses a PUBLIC scaled feature space. Set clip norm to 4, NOT 100000.")
        if self.mode == "federated":
            if self.num_clients < 2:
                raise ValueError("Federated mode requires at least two clients")
            if self.partition_mode not in ("iid", "dirichlet", "quantity_skew", "label_limited"):
                raise ValueError(
                    f"Unsupported partition mode: {self.partition_mode}"
                )
            if self.partition_mode == "dirichlet" and self.dirichlet_alpha <= 0:
                raise ValueError("dirichlet_alpha must be greater than zero")
        else:
            if self.privacy_mode != "none":
                raise ValueError("Gaussian DP is available only in federated mode")
            if self.participation_rate != 1.0 or self.dropout_rate != 0.0:
                raise ValueError(
                    "Participation/dropout controls are available only in federated mode"
                )


@dataclass(slots=True)
class AlgorithmRunReport:
    algorithm: str
    backend: str
    runtime_sec: float
    communication_bytes: int | None
    rounds: int | str
    ari: float | None
    nmi: float | None
    silhouette: float | None
    davies_bouldin: float | None
    calinski_harabasz: float | None
    ami: float | None = None
    model_state: dict[str, Any] = field(default_factory=dict)
    history: list[Any] = field(default_factory=list)

    def metrics_dict(self) -> dict[str, float | None]:
        return {
            "ari": self.ari,
            "nmi": self.nmi,
            "ami": self.ami,
            "silhouette": self.silhouette,
            "davies_bouldin": self.davies_bouldin,
            "calinski_harabasz": self.calinski_harabasz,
        }


@dataclass(slots=True)
class PartitionReport:
    mode: PartitionMode
    num_clients: int
    client_sample_counts: list[int]
    fingerprint: str
    dirichlet_alpha: float | None = None
    client_class_counts: list[dict[str, int]] = field(default_factory=list)
    labels_per_client: int | None = None
    participation_rate: float = 1.0
    dropout_rate: float = 0.0
    round_schedule: list[dict[str, Any]] = field(default_factory=list)
    heterogeneity: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CampaignReportRequest:
    """Native-history view of the recorded controls of a resolved campaign comparison."""
    mode: RunMode
    dataset_name: str
    algorithms: tuple[str, ...]
    seed: int
    protocol: dict[str, Any]

    def __getattr__(self, name: str) -> Any:
        # Native exporters also read GUI controls absent from some campaign profiles.
        if name in RunRequest.__dataclass_fields__:
            return self.protocol.get(name)
        raise AttributeError(name)

    def to_dict(self) -> dict[str, Any]:
        return {**self.protocol, "mode": self.mode, "dataset_name": self.dataset_name,
                "algorithms": self.algorithms, "seed": self.seed}


@dataclass(slots=True)
class ComparisonReport:
    experiment_id: str
    started_at: datetime
    finished_at: datetime
    request: RunRequest | CampaignReportRequest
    dataset_display_name: str
    n_samples: int
    n_features: int
    results: list[AlgorithmRunReport]
    partition: PartitionReport | None = None
    privacy_report: dict[str, Any] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)
    history_directory: Path | None = None

    @property
    def duration_sec(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if isinstance(self.request, CampaignReportRequest):
            value["request"] = self.request.to_dict()
        value["started_at"] = self.started_at.isoformat()
        value["finished_at"] = self.finished_at.isoformat()
        value["duration_sec"] = self.duration_sec
        value["history_directory"] = (
            str(self.history_directory) if self.history_directory else None
        )
        return value

@dataclass(frozen=True, slots=True)
class HistoryExperimentSummary:
    history_key: str
    experiment_id: str
    started_at: datetime
    mode: RunMode
    dataset_name: str
    algorithms: tuple[str, ...]
    duration_sec: float
    result_count: int


@dataclass(slots=True)
class HistoryExperimentDetails:
    history_key: str
    experiment_id: str
    started_at: datetime
    finished_at: datetime
    mode: RunMode
    dataset_name: str
    dataset_display_name: str
    n_samples: int
    n_features: int
    seed: int
    algorithms: tuple[str, ...]
    results: list[AlgorithmRunReport]
    duration_sec: float
    partition: PartitionReport | None = None
    log_text: str = ""
