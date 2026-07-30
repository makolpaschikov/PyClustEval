from __future__ import annotations

from .base import ClusteringAlgorithm
from .fed_kmeans_numpy import FedKMeansNumpy
from .sklearn_algorithms import (
    SklearnAgglomerative,
    SklearnDBSCAN,
    SklearnGMM,
    SklearnKMeans,
)
from ..flower_adapter.fed_kmeans_flower_adapter import FedKMeansFlowerAdapter


class AlgorithmRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ClusteringAlgorithm] = {}

    def register(self, algorithm: ClusteringAlgorithm) -> None:
        self._items[algorithm.name] = algorithm

    def get(self, name: str) -> ClusteringAlgorithm:
        if name not in self._items:
            raise KeyError(
                f"Unknown algorithm: {name}. Available: {sorted(self._items)}"
            )
        return self._items[name]


def default_registry() -> AlgorithmRegistry:
    registry = AlgorithmRegistry()
    algorithms = [
        SklearnKMeans(),
        SklearnDBSCAN(),
        SklearnGMM(),
        SklearnAgglomerative(),
        FedKMeansNumpy(),
        FedKMeansFlowerAdapter(),
    ]
    for algorithm in algorithms:
        registry.register(algorithm)
    return registry
