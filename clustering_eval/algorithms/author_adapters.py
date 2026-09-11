from __future__ import annotations

import importlib.util
import json
import sys
import threading
import types
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

import numpy as np
from sklearn.cluster import KMeans

from .base import AlgorithmResult, ClusteringAlgorithm


_THIRD_PARTY = Path(__file__).resolve().parents[1] / "third_party"
_LOAD_LOCK = threading.Lock()


@contextmanager
def _numpy_seed(seed: int) -> Iterator[None]:
    """Run legacy author code deterministically without permanently changing NumPy RNG."""
    state = np.random.get_state()
    np.random.seed(seed)
    try:
        yield
    finally:
        np.random.set_state(state)


def _load_module(path: Path, module_name: str, aliases: dict[str, types.ModuleType] | None = None):
    aliases = aliases or {}
    with _LOAD_LOCK:
        previous = {name: sys.modules.get(name) for name in aliases}
        try:
            for name, module in aliases.items():
                sys.modules[name] = module
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load author source: {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        finally:
            for name, old in previous.items():
                if old is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old
            # The unique module stays cached by our lru_cache wrapper below.


@lru_cache(maxsize=1)
def _fedkmeans_module():
    # fed_kmeans.py imports `common` with a star import, but client_FKM/server_FKM do
    # not depend on those dataset/plotting helpers. A blank module keeps the author
    # source itself byte-for-byte unchanged while avoiding unrelated plotting deps.
    common_stub = types.ModuleType("common")
    return _load_module(
        _THIRD_PARTY / "fedkmeans" / "fed_kmeans.py",
        "pyclusteval_author_fedkmeans",
        {"common": common_stub},
    )


@lru_cache(maxsize=1)
def _fdbscan_module():
    return _load_module(
        _THIRD_PARTY / "fdbscan" / "fd_dbscan.py",
        "pyclusteval_author_fdbscan",
    )


def _load_legacy_utils(path: Path, unique_name: str):
    # Both FKDC and NN-FC contain `from utils import *` inside utils.py itself.
    # Loading under the temporary name `utils` reproduces the original import
    # environment, then we retain the module object under a unique cache key.
    with _LOAD_LOCK:
        old = sys.modules.get("utils")
        try:
            spec = importlib.util.spec_from_file_location("utils", path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load author source: {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules["utils"] = module
            spec.loader.exec_module(module)
            sys.modules[unique_name] = module
            return module
        finally:
            if old is None:
                sys.modules.pop("utils", None)
            else:
                sys.modules["utils"] = old


@lru_cache(maxsize=1)
def _fkdc_module():
    return _load_legacy_utils(
        _THIRD_PARTY / "fkdc" / "utils.py",
        "pyclusteval_author_fkdc",
    )


@lru_cache(maxsize=1)
def _nnfc_module():
    return _load_legacy_utils(
        _THIRD_PARTY / "nnfc" / "utils.py",
        "pyclusteval_author_nnfc",
    )


def _require_partition(partition: list[np.ndarray] | None) -> list[np.ndarray]:
    if partition is None or not partition:
        raise ValueError("Author-adapted federated algorithm requires a non-empty partition")
    return [np.asarray(idx, dtype=int) for idx in partition]


def _cluster_count(params: dict[str, Any]) -> int:
    k = int(params.get("n_clusters", params.get("k", 3)))
    if k < 1:
        raise ValueError("n_clusters/k must be >= 1")
    return k


def _nearest_center_labels(X: np.ndarray, centers: np.ndarray) -> np.ndarray:
    dist2 = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    return np.argmin(dist2, axis=1).astype(int)


def _source_state(repo: str, commit: str, source_file: str) -> dict[str, Any]:
    return {
        "backend": "author-source-port",
        "source_repo": repo,
        "source_commit": commit,
        "source_file": source_file,
        "implementation_kind": "vendored author implementation with thin PyClustEval adapter",
    }


class AdaptedAuthorFKM(ClusteringAlgorithm):
    """Thin in-process adapter around the uploaded fedKMeans client_FKM/server_FKM."""

    name = "Adapted FKM"
    is_federated = True

    def run(self, X: np.ndarray, partition: list[np.ndarray] | None, params: dict[str, Any], seed: int) -> AlgorithmResult:
        part = _require_partition(partition)
        k = _cluster_count(params)
        rounds = int(params.get("rounds", params.get("crounds", 10)))
        local_iter = int(params.get("iter_local", params.get("local_iter", 1)))
        drop = bool(params.get("drop_empty_clusters", params.get("drop", True)))
        weighted = bool(params.get("weighted_agg", True))
        init = str(params.get("init", "k-means++"))
        if rounds < 1:
            raise ValueError("rounds must be >= 1")

        mod = _fedkmeans_module()
        start = perf_counter()
        history: list[dict[str, Any]] = []
        communication = 0

        with _numpy_seed(seed):
            server = mod.server_FKM(k, weighted=weighted)
            clients = []
            local_clusters = []
            cluster_sizes = []
            for indices in part:
                data = np.asarray(X[indices], dtype=float)
                if len(data) == 0:
                    raise ValueError("fedKMeans author implementation cannot run on an empty client")
                client = mod.client_FKM(
                    data,
                    None,  # Author code says labels are validation-only.
                    k,
                    drop_empty_clusters=drop,
                    n_iter=local_iter,
                    init=init,
                )
                clients.append(client)
                local_clusters.append(np.asarray(client.means))
                cluster_sizes.append(np.asarray(client.sample_amts))

            local_clusters_arr = np.concatenate(local_clusters)
            cluster_sizes_arr = np.concatenate(cluster_sizes)
            communication += local_clusters_arr.nbytes + cluster_sizes_arr.nbytes

            global_clusters = None
            for round_idx in range(rounds):
                global_clusters = np.asarray(server.aggregate(local_clusters_arr, cluster_sizes_arr))
                # Server broadcasts global centers to every client.
                communication += global_clusters.nbytes * len(clients)

                next_clusters = []
                next_sizes = []
                for client in clients:
                    client.means = np.copy(global_clusters)
                    local_cluster, cluster_size, _score = client.det_local_clusters()
                    local_cluster = np.asarray(local_cluster)
                    cluster_size = np.asarray(cluster_size)
                    next_clusters.append(local_cluster)
                    next_sizes.append(cluster_size)
                    communication += local_cluster.nbytes + cluster_size.nbytes
                local_clusters_arr = np.concatenate(next_clusters)
                cluster_sizes_arr = np.concatenate(next_sizes)
                history.append({
                    "round": round_idx + 1,
                    "global_centers": np.copy(global_clusters),
                    "num_uploaded_local_centers": int(len(local_clusters_arr)),
                })

        if global_clusters is None:
            raise RuntimeError("fedKMeans author implementation produced no global centers")
        labels = _nearest_center_labels(X, global_clusters)
        runtime = perf_counter() - start
        state = _source_state(
            "https://github.com/swiergarst/fedKMeans",
            "b1f39cf481721da232f9426bc35feb2b79cf18d1",
            "fed_kmeans.py: client_FKM, server_FKM",
        )
        state.update({
            "rounds": rounds,
            "global_centers": global_clusters,
            "weighted_agg": weighted,
            "requested_clusters": k,
            "iter_local": local_iter,
            "drop_empty_clusters": drop,
            "adapter_changes": [
                "author dataset loader replaced with PyClustEval partition arrays",
                "author validation labels set to None",
                "final labels derived from author global centers for the common AlgorithmResult API",
                "NumPy RNG seeded/restored by benchmark harness for reproducibility",
            ],
        })
        return AlgorithmResult(labels=labels, model_state=state, history=history, runtime_sec=runtime, communication_bytes=int(communication))


class AdaptedAuthorFDBSCAN(ClusteringAlgorithm):
    """In-process adapter that directly calls the author's HF_DBSCAN kernel classes."""

    name = "Adapted HF_DBSCAN"
    is_federated = True
    input_preprocessing = "minmax"

    def run(self, X: np.ndarray, partition: list[np.ndarray] | None, params: dict[str, Any], seed: int) -> AlgorithmResult:
        part = _require_partition(partition)
        # The author repository uses L=0.03 for the banana dataset specifically.
        # PyClustEval benchmarks arbitrary datasets, so 0.15 is the UI/framework
        # default after MinMax scaling; callers can pass L=0.03 to reproduce banana.
        L = float(params.get("L", params.get("cell_size", 0.15)))
        min_points = int(params.get("MIN_POINTS", params.get("min_points", 4)))
        missing_pct = int(params.get("missing_clients_percentage", 0))
        if L <= 0 or min_points < 1:
            raise ValueError("F_DBSCAN requires L > 0 and MIN_POINTS >= 1")
        if not 0 <= missing_pct < 100:
            raise ValueError("missing_clients_percentage must be in [0, 100)")

        mod = _fdbscan_module()
        start = perf_counter()
        communication = 0
        with _numpy_seed(seed):
            clients = []
            for indices in part:
                client = mod.FDBSCAN_Client()
                client.initialize({
                    "dataset": np.asarray(X[indices], dtype=float),
                    "L": L,
                    "true_labels": np.zeros(len(indices), dtype=int),
                })
                clients.append(client)

            # Mirror fd_server.training client selection, but execute calls in-process.
            import random
            rng = random.Random(int(params.get("clients_selection_seed", seed)))
            n_selected = int(len(clients) * (100 - missing_pct) / 100)
            selected_idx = rng.sample(range(len(clients)), n_selected)
            contribution_map: dict[tuple, float] = {}
            for i in selected_idx:
                local = clients[i].compute_local_update()
                # Estimate the same JSON payload shape used by fd_client.py.
                json_map = {','.join(str(c) for c in key): float(value) for key, value in local.items()}
                communication += len(json.dumps(json_map, separators=(",", ":")).encode("utf-8"))
                for key, value in local.items():
                    contribution_map[key] = contribution_map.get(key, 0.0) + value

            server = mod.FDBSCAN_Server()
            server.initialize({"MIN_POINTS": min_points})
            cells, cell_labels = server.compute_clusters(contribution_map)

            outbound = {"action": "assign_points_to_cluster", "cells": cells, "labels": cell_labels}
            outbound_size = len(json.dumps(outbound, separators=(",", ":")).encode("utf-8"))
            communication += outbound_size * len(clients)

            labels = np.full(len(X), -1, dtype=int)
            for indices, client in zip(part, clients):
                client.assign_points_to_cluster(cells, cell_labels)
                local_labels, _unused_true, _points = client.get_labels()
                labels[indices] = np.asarray(local_labels, dtype=int)

        runtime = perf_counter() - start
        state = _source_state(
            "https://github.com/GM862001/F_DBSCAN",
            "6223c2d9a0f893f5b92699afd918775c2e09adf4",
            "HF_DBSCAN/fd_dbscan.py: FDBSCAN_Client, FDBSCAN_Server",
        )
        state.update({
            "rounds": 1,
            "L": L,
            "MIN_POINTS": min_points,
            "selected_clients": selected_idx,
            "variant": "horizontal",
            "preprocessing": "MinMaxScaler(feature_range=(0, 1))",
            "dense_cells": cells,
            "dense_cell_labels": cell_labels,
            "adapter_changes": [
                "Flask/HTTP transport replaced by direct in-process method calls",
                "author MinMaxScaler preprocessing retained via algorithm input_preprocessing=minmax",
                "PyClustEval partition arrays replace author ARFF loader/StratifiedKFold",
                "NumPy/Python client-selection RNG seeded by benchmark harness",
                "clustering kernel FDBSCAN_Client/FDBSCAN_Server is the vendored author source",
            ],
        })
        return AlgorithmResult(labels=labels, model_state=state, history=[], runtime_sec=runtime, communication_bytes=int(communication))


def _author_pickle_dataset(X: np.ndarray, part: list[np.ndarray], k: int) -> dict[str, Any]:
    # FKDC/NN-FC source uses true_label only to derive the requested number of
    # final clusters and to compute validation metrics. We provide synthetic
    # labels carrying exactly k unique values; predicted labels are captured
    # before the author's metric calls. No ground-truth class assignment enters
    # the clustering calculations.
    n = len(X)
    synthetic = (np.arange(n, dtype=int) % k)
    dataset: dict[str, Any] = {
        "full_data": np.asarray(X, dtype=float),
        "true_label": synthetic,
        "num_clusters": k,
        "order": np.arange(len(part), dtype=int),
        "eachlable": [synthetic[idx] for idx in part],
    }
    for i, idx in enumerate(part):
        dataset[f"client_{i}"] = np.asarray(X[idx], dtype=float)
    return dataset


@contextmanager
def _capture_author_labels(module: Any, dataset: dict[str, Any]) -> Iterator[dict[str, np.ndarray]]:
    captured: dict[str, np.ndarray] = {}
    old_load = module.load_dataset
    old_ari = module.adjusted_rand_score
    old_nmi = module.normalized_mutual_info_score
    old_ami = getattr(module, "adjusted_mutual_info_score", None)

    def fake_load(_path: str):
        return dataset

    def capture_ari(_true, pred):
        captured["labels"] = np.asarray(pred, dtype=int).copy()
        return 0.0

    module.load_dataset = fake_load
    module.adjusted_rand_score = capture_ari
    module.normalized_mutual_info_score = lambda _true, _pred: 0.0
    if old_ami is not None:
        module.adjusted_mutual_info_score = lambda _true, _pred: 0.0
    try:
        yield captured
    finally:
        module.load_dataset = old_load
        module.adjusted_rand_score = old_ari
        module.normalized_mutual_info_score = old_nmi
        if old_ami is not None:
            module.adjusted_mutual_info_score = old_ami


class AdaptedAuthorFKDC(ClusteringAlgorithm):
    """Executes FKDC's original utils.results flow with only I/O/metric seams replaced."""

    name = "Adapted FKDC"
    is_federated = True

    def run(self, X: np.ndarray, partition: list[np.ndarray] | None, params: dict[str, Any], seed: int) -> AlgorithmResult:
        part = _require_partition(partition)
        if any(len(idx) < 2 for idx in part):
            raise ValueError("FKDC author code requires at least 2 samples per client")
        k = _cluster_count(params)
        if k > len(X):
            raise ValueError("n_clusters cannot exceed n_samples")
        dataset = _author_pickle_dataset(X, part, k)
        mod = _fkdc_module()
        start = perf_counter()
        with _numpy_seed(seed), _capture_author_labels(mod, dataset) as captured:
            _ari, _nmi, _ami, original_parameters = mod.results("<pyclusteval-in-memory>")
        runtime = perf_counter() - start
        if "labels" not in captured:
            raise RuntimeError("FKDC author code did not reach its label evaluation stage")
        labels = captured["labels"] - 1  # Author code emits 1..K; normalize to 0..K-1.
        d = int(X.shape[1])
        upstream = sum(min(len(idx) // 2, 50) * d * np.dtype(float).itemsize for idx in part)
        state = _source_state(
            "https://github.com/mlyizhang/FKDC",
            "37f10faa27fbc6bc0335882909cf744b8a2c237e",
            "federatedclustering/FKDC/utils.py: results, SNN",
        )
        state.update({
            "rounds": 1,
            "original_parameters": original_parameters,
            "oracle_cluster_count": k,
            "adapter_changes": [
                "author SNN scalar min compatibility-fixed to numpy.minimum; original preserved in utils_original.txt",
                "load_dataset patched to return PyClustEval in-memory partition data",
                "true_label replaced by synthetic labels carrying only the requested cluster count",
                "author metric functions patched only to capture predicted labels for AlgorithmResult",
                "author output labels normalized from 1..K to 0..K-1",
                "NumPy RNG seeded/restored by benchmark harness",
            ],
            "known_author_behavior": "results() derives cnum from true_label and performs final assignment over full_data centrally",
        })
        return AlgorithmResult(labels=labels, model_state=state, history=[], runtime_sec=runtime, communication_bytes=int(upstream))


class AdaptedAuthorNNFC(ClusteringAlgorithm):
    """Executes NN-FC's original nnfc flow; only the archive's TabError is syntax-fixed."""

    name = "Adapted NN-FC"
    is_federated = True

    def run(self, X: np.ndarray, partition: list[np.ndarray] | None, params: dict[str, Any], seed: int) -> AlgorithmResult:
        part = _require_partition(partition)
        if any(len(idx) < 3 for idx in part):
            raise ValueError("NN-FC author code requires at least 3 samples per client")
        k = _cluster_count(params)
        dataset = _author_pickle_dataset(X, part, k)
        mod = _nnfc_module()
        start = perf_counter()
        with _numpy_seed(seed), _capture_author_labels(mod, dataset) as captured:
            _ari, _nmi, original_parameters = mod.nnfc("<pyclusteval-in-memory>")
        runtime = perf_counter() - start
        if "labels" not in captured:
            raise RuntimeError("NN-FC author code did not reach its label evaluation stage")
        labels = captured["labels"] - 1
        d = int(X.shape[1])
        upstream = sum(min(len(idx) // 3, 50) * d * np.dtype(float).itemsize for idx in part)
        state = _source_state(
            "https://github.com/mlyizhang/nnfc",
            "404af20bf4abd524dd1c5bc0968e0e1a2491f828",
            "codes/utils.py: nnfc, SNN",
        )
        state.update({
            "rounds": 1,
            "original_parameters": original_parameters,
            "oracle_cluster_count": k,
            "adapter_changes": [
                "TabError indentation and shadowed scalar min compatibility fixes applied to executable codes/utils.py; original preserved as utils_original.txt",
                "load_dataset patched to return PyClustEval in-memory partition data",
                "true_label replaced by synthetic labels carrying only the requested cluster count",
                "author metric functions patched only to capture predicted labels for AlgorithmResult",
                "author output labels normalized from 1..K to 0..K-1",
                "NumPy RNG seeded/restored by benchmark harness",
            ],
            "known_author_behavior": "nnfc() derives cnum from true_label and performs final assignment over full_data centrally",
        })
        return AlgorithmResult(labels=labels, model_state=state, history=[], runtime_sec=runtime, communication_bytes=int(upstream))
