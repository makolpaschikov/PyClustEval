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
    # ComparisonService keeps the historical StandardScaler behavior unless an
    # adapter declares the preprocessing used by its author implementation.
    input_preprocessing: str = "standard"

    def run(self, X: np.ndarray, partition: list[np.ndarray] | None, params: dict[str, Any], seed: int) -> AlgorithmResult:
        raise NotImplementedError
