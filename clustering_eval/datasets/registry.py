from __future__ import annotations
from typing import Callable, Any
from sklearn.datasets import load_iris, make_blobs, load_wine, load_digits
from .base import Dataset

Loader = Callable[[dict[str, Any]], Dataset]

class DatasetRegistry:
    def __init__(self) -> None:
        self._loaders: dict[str, Loader] = {}

    def register(self, name: str, loader: Loader) -> None:
        self._loaders[name] = loader

    def load(self, name: str, params: dict[str, Any] | None = None) -> Dataset:
        if name not in self._loaders:
            raise KeyError(f"Unknown dataset: {name}. Available: {sorted(self._loaders)}")
        return self._loaders[name](params or {})


def default_registry() -> DatasetRegistry:
    reg = DatasetRegistry()

    def iris(_: dict[str, Any]) -> Dataset:
        data = load_iris()
        return Dataset("iris", data.data, data.target, {"source": "sklearn"})

    def wine(_: dict[str, Any]) -> Dataset:
        data = load_wine()
        return Dataset("wine", data.data, data.target, {"source": "sklearn"})

    def digits(_: dict[str, Any]) -> Dataset:
        data = load_digits()
        return Dataset("digits", data.data, data.target, {"source": "sklearn"})

    def blobs(params: dict[str, Any]) -> Dataset:
        X, y = make_blobs(
            n_samples=int(params.get("n_samples", 500)),
            centers=int(params.get("centers", 3)),
            cluster_std=float(params.get("cluster_std", 1.0)),
            random_state=int(params.get("random_state", 42)),
        )
        return Dataset("blobs", X, y, {"source": "synthetic", **params})

    reg.register("iris", iris)
    reg.register("wine", wine)
    reg.register("digits", digits)
    reg.register("blobs", blobs)
    return reg
