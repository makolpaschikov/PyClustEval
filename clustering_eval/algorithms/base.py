from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import numpy as np

@dataclass
class AlgorithmResult:
    labels: np.ndarray
    model_state: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    runtime_sec: float = 0.0
    communication_bytes: int = 0

class ClusteringAlgorithm:
    name: str = "base"

    def run(self, X: np.ndarray, partition: list[np.ndarray] | None, params: dict[str, Any], seed: int) -> AlgorithmResult:
        raise NotImplementedError
