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
    # Smallest client partition the implementation can consume safely.
    min_client_samples: int = 1
    # Algorithm-specific defaults are merged after the common benchmark profile.
    # Keep only parameters that do not have a meaningful cross-algorithm analogue.
    default_params: dict[str, Any] = {}
    # Names from the shared benchmark profile that this implementation actually
    # consumes. Recorded in reports so equalization claims stay auditable.
    common_param_support: tuple[str, ...] = ()

    def run(self, X: np.ndarray, partition: list[np.ndarray] | None, params: dict[str, Any], seed: int) -> AlgorithmResult:
        raise NotImplementedError
