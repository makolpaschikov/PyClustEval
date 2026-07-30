from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


RunMode = Literal["local", "federated"]
PartitionMode = Literal["iid", "dirichlet"]


@dataclass(frozen=True, slots=True)
class RunRequest:
    mode: RunMode
    dataset_name: str
    algorithms: tuple[str, str]
    seed: int = 42
    num_clients: int = 5
    partition_mode: PartitionMode = "iid"
    dirichlet_alpha: float = 0.5
    algorithm_params: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.mode not in ("local", "federated"):
            raise ValueError(f"Unsupported run mode: {self.mode}")
        if not self.dataset_name:
            raise ValueError("dataset_name cannot be empty")
        if len(self.algorithms) != 2:
            raise ValueError("Exactly two algorithms are required")
        if self.algorithms[0] == self.algorithms[1]:
            raise ValueError("Algorithms must be different")
        if self.mode == "federated":
            if self.num_clients < 2:
                raise ValueError("Federated mode requires at least two clients")
            if self.partition_mode not in ("iid", "dirichlet"):
                raise ValueError(
                    f"Unsupported partition mode: {self.partition_mode}"
                )
            if self.partition_mode == "dirichlet" and self.dirichlet_alpha <= 0:
                raise ValueError("dirichlet_alpha must be greater than zero")


@dataclass(slots=True)
class AlgorithmRunReport:
    algorithm: str
    backend: str
    runtime_sec: float
    communication_bytes: int
    rounds: int | str
    ari: float | None
    nmi: float | None
    silhouette: float | None
    davies_bouldin: float | None
    calinski_harabasz: float | None
    model_state: dict[str, Any] = field(default_factory=dict)
    history: list[Any] = field(default_factory=list)

    def metrics_dict(self) -> dict[str, float | None]:
        return {
            "ari": self.ari,
            "nmi": self.nmi,
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


@dataclass(slots=True)
class ComparisonReport:
    experiment_id: str
    started_at: datetime
    finished_at: datetime
    request: RunRequest
    dataset_display_name: str
    n_samples: int
    n_features: int
    results: list[AlgorithmRunReport]
    partition: PartitionReport | None = None
    log_lines: list[str] = field(default_factory=list)
    history_directory: Path | None = None

    @property
    def duration_sec(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["started_at"] = self.started_at.isoformat()
        value["finished_at"] = self.finished_at.isoformat()
        value["duration_sec"] = self.duration_sec
        value["history_directory"] = (
            str(self.history_directory) if self.history_directory else None
        )
        return value
