from dataclasses import dataclass, field
from typing import Any
import numpy as np

@dataclass(frozen=True)
class Dataset:
    name: str
    X: np.ndarray
    y: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
