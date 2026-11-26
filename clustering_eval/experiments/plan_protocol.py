"""Resolve scientific protocol and per-algorithm parameters without fitting models."""
from __future__ import annotations

from dataclasses import fields
from itertools import product
from math import ceil
from typing import Any

from ..algorithms.base import ClusteringAlgorithm
from ..algorithms.registry import default_registry
from ..application.comparison_service import METRICS, _is_federated
from ..application.dto import RunRequest
from ..metrics.clustering import METRIC_SCHEMA_VERSION
from .plan_parameters import choice, integer, mapping, normalize_overrides, number, parameter_defaults

# These references are the built-in public transforms and public class counts
# used by public_scaled_features and ComparisonService, not inferred from y.
_PUBLIC = {"dry_bean": (16, 7), "iris": (4, 3), "wine": (13, 3), "digits": (64, 10)}
_AGGREGATE = {"gaussian_dp_aggregate", "public_clipped_control"}
_FEDERATED = {"num_clients", "partition_mode", "dirichlet_alpha", "min_samples_per_client",
              "labels_per_client", "participation_rate", "dropout_rate"}

def _request(scenario: dict, dataset: dict, seed: int, path: str) -> RunRequest:
    all_fields = {f.name: f for f in fields(RunRequest)}
    controls = all_fields.keys() - {"dataset_name", "algorithms", "algorithm_params", "algorithm_params_by_name", "seed"}
    mapping(scenario, path, keys=controls | {"algorithms", "algorithm_params_by_name", "grid", "stopping_profile"})
    mode = choice(scenario.get("mode"), {"local", "federated"}, f"{path}.mode")
    if mode == "federated":
        choice(scenario.get("stopping_profile"), {"current_gui", "historical_paper"}, f"{path}.stopping_profile")
    elif "stopping_profile" in scenario:
        raise ValueError(f"{path}.stopping_profile: local algorithms do not use a federated stopping profile")
    algorithms = scenario.get("algorithms")
    if not isinstance(algorithms, list) or not algorithms or any(not isinstance(x, str) for x in algorithms):
        raise ValueError(f"{path}.algorithms: expected a nonempty list of algorithm names")
    if len(set(algorithms)) != len(algorithms):
        raise ValueError(f"{path}.algorithms: duplicate algorithm")
    seed = integer(seed, f"{path}.seed", 0, 2**32 - 1)
    values = {k: scenario.get(k, all_fields[k].default) for k in controls}
    enum = {"partition_mode": {"iid", "dirichlet", "quantity_skew", "label_limited"},
            "cluster_count_mode": {"known_k", "estimated_k"},
            "tuning_mode": {"none", "unsupervised"}, "privacy_mode": _AGGREGATE | {"none", "gaussian_dp"}}
    for key, options in enum.items():
        values[key] = choice(values[key], options, f"{path}.{key}")
    for key in ("num_clients", "estimated_k_min", "estimated_k_max", "tuning_sample_size", "tuning_budget",
                "rounds", "max_iter", "density_min_samples", "min_samples_per_client", "labels_per_client"):
        minimum = {"estimated_k_min": 2, "estimated_k_max": 2, "tuning_sample_size": 25}.get(key, 1)
        values[key] = integer(values[key], f"{path}.{key}", minimum)
    for key in ("dirichlet_alpha", "tol", "participation_rate", "dropout_rate", "dp_epsilon", "dp_delta", "dp_clip_norm"):
        values[key] = number(values[key], f"{path}.{key}")
        if key != "dropout_rate" and values[key] <= 0:
            raise ValueError(f"{path}.{key}: expected > 0")
    if values["target_clusters"] is not None:
        values["target_clusters"] = integer(values["target_clusters"], f"{path}.target_clusters", 2, dataset["n_samples"])
    req = RunRequest(dataset_name=dataset["name"], algorithms=tuple(algorithms), seed=seed, **values)
    if req.participation_rate > 1 or not 0 <= req.dropout_rate < 1:
        raise ValueError(f"{path}.participation_rate/dropout_rate: expected (0,1] / [0,1)")
    if not 0 < req.dp_delta < 1:
        raise ValueError(f"{path}.dp_delta: expected (0,1)")
    if req.estimated_k_min > req.estimated_k_max:
        raise ValueError(f"{path}.estimated_k_max: less than estimated_k_min")
    if req.cluster_count_mode == "estimated_k":
        if req.target_clusters is not None:
            raise ValueError(f"{path}.target_clusters: conflicts with estimated_k")
        if req.estimated_k_min + 2 > min(dataset["n_samples"], req.tuning_sample_size):
            raise ValueError(f"{path}.estimated_k_min: insufficient samples for k estimation")
    if mode == "local":
        if req.privacy_mode != "none" or req.participation_rate != 1 or req.dropout_rate != 0:
            raise ValueError(f"{path}.privacy_mode/participation_rate/dropout_rate: requires federated mode")
        irrelevant = _FEDERATED.intersection(scenario) - {"participation_rate", "dropout_rate"}
        if irrelevant:
            raise ValueError(f"{path}.{sorted(irrelevant)[0]}: local comparisons have no client partition")
    if mode == "federated" and req.num_clients < 2:
        raise ValueError(f"{path}.num_clients: federated scenarios require at least two clients")
    if req.privacy_mode == "none":
        for key in ("dp_epsilon", "dp_delta", "dp_clip_norm"):
            if key in scenario:
                raise ValueError(f"{path}.{key}: requires a privacy or clipped-control protocol")
    if req.privacy_mode == "public_clipped_control" and ("dp_epsilon" in scenario or "dp_delta" in scenario):
        raise ValueError(f"{path}.dp_epsilon/dp_delta: clipping control does not use a privacy budget")
    if req.privacy_mode in _AGGREGATE:
        if req.dp_clip_norm > 20 or req.cluster_count_mode != "known_k":
            raise ValueError(f"{path}.dp_clip_norm/cluster_count_mode: public preprocessing requires clip <=20 and public known K")
        if req.privacy_mode == "gaussian_dp_aggregate" and req.partition_mode in {"dirichlet", "label_limited"}:
            raise ValueError(f"{path}.partition_mode: aggregate DP does not account for a label-dependent partition")
        reference = _PUBLIC.get(req.dataset_name)
        if reference is None or reference[0] != dataset["n_features"]:
            raise ValueError(f"{path}.privacy_mode: no matching PUBLIC feature transform for {req.dataset_name!r}")
    # Reuse DTO-level rules whenever its comparison cardinality applies. Singleton
    # jobs are handled by the same typed/conditional checks without inventing a peer.
    if len(algorithms) > 1:
        try:
            req.validate()
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    return req


def _shared(req: RunRequest, dataset: dict, methods: list[ClusteringAlgorithm], path: str) -> dict:
    protocol = {"mode": req.mode, "cluster_count_mode": req.cluster_count_mode, "tuning_mode": req.tuning_mode,
                "privacy_mode": req.privacy_mode, "rounds": req.rounds, "tol": req.tol,
                "max_iter": req.max_iter, "density_min_samples": req.density_min_samples,
                "evaluation_space": "StandardScaler(original_raw_X)", "metrics": list(METRICS),
                "metric_schema": METRIC_SCHEMA_VERSION}
    if req.target_clusters is not None:
        k, source = req.target_clusters, "user"
    elif req.privacy_mode in _AGGREGATE:
        k, source = _PUBLIC[req.dataset_name][1], "published_public_dataset_k"
    elif req.cluster_count_mode == "estimated_k":
        k, source = None, "estimated_unlabeled_silhouette"
        protocol.update(estimated_k_min=req.estimated_k_min, estimated_k_max=req.estimated_k_max,
                        tuning_sample_size=req.tuning_sample_size, tuning_budget=req.tuning_budget)
    elif dataset["n_classes"] is not None:
        k, source = dataset["n_classes"], "ground_truth_oracle"
    else:
        k, source = 3, "fallback"
    if k is not None and not 1 <= k <= dataset["n_samples"]:
        raise ValueError(f"{path}.target_clusters: outside dataset sample count")
    protocol.update(target_clusters=k, cluster_count_source=source)
    if req.tuning_mode == "unsupervised":
        protocol["tuning_sample_size"] = req.tuning_sample_size
    if req.mode == "federated":
        minimum = max(method.min_client_samples for method in methods)
        if req.min_samples_per_client < minimum:
            raise ValueError(f"{path}.min_samples_per_client: selected methods require at least {minimum}")
        if req.num_clients < 2 or req.num_clients * req.min_samples_per_client > dataset["n_samples"]:
            raise ValueError(f"{path}.num_clients: cannot allocate the requested client sizes")
        protocol.update(num_clients=req.num_clients, partition_mode=req.partition_mode,
                        min_samples_per_client=req.min_samples_per_client,
                        participation_rate=req.participation_rate, dropout_rate=req.dropout_rate,
                        partition_seed=req.seed, schedule_seed=req.seed, schedule_rounds=req.rounds)
        if req.partition_mode == "dirichlet":
            if dataset["n_classes"] is None:
                raise ValueError(f"{path}.partition_mode: Dirichlet assignment requires labels")
            protocol["dirichlet_alpha"] = req.dirichlet_alpha
        if req.partition_mode == "label_limited":
            if dataset["n_classes"] is None or req.num_clients * req.labels_per_client < dataset["n_classes"]:
                raise ValueError(f"{path}.labels_per_client: cannot cover the classes with the requested clients")
            protocol["labels_per_client"] = req.labels_per_client
    if req.privacy_mode != "none":
        protocol["privacy_group_algorithms"] = sorted(req.algorithms)
        protocol["dp_clip_norm"] = req.dp_clip_norm
        if req.privacy_mode != "public_clipped_control":
            protocol.update(dp_epsilon=req.dp_epsilon, dp_delta=req.dp_delta)
        if req.privacy_mode == "gaussian_dp":
            protocol["release_scope"] = "one_shared_input_matrix_per_comparison"
            protocol["noise_source"] = "OS_randomness_independent_of_benchmark_seed"
        else:
            protocol["public_reference"] = req.dataset_name
            if req.privacy_mode == "gaussian_dp_aggregate":
                protocol["noise_source"] = "OS_randomness_independent_of_benchmark_seed"
    return protocol


def _backend(name: str, proxy: bool) -> str:
    if proxy:
        return "author-server DP proxy"
    if name.startswith("Adapted "):
        return "author-source-port"
    if name.endswith("_numpy"):
        return "numpy-federated"
    if name.endswith("_flower"):
        return "flower-simulation"
    return "local"


def _fkm_capacity(req: RunRequest, n_samples: int, params: dict, path: str) -> dict:
    """Bound the first author server input without drawing partitions or fitting models."""
    clients = req.num_clients
    # The framework selects ceil(rate * clients); dropout can only reduce this count.
    selected = min(clients, max(1, ceil(req.participation_rate * clients)))
    k = params["k"]
    minimum_k = req.estimated_k_min if k is None else k
    if req.partition_mode == "iid":
        # np.array_split yields 'large' clients of size small+1, the rest of size small.
        small, large = divmod(n_samples, clients)
        active_large = min(selected, large)
        capacity = active_large * ((small + 1) // 2) + (selected - active_large) * (small // 2)
        eligible = clients if minimum_k <= small else (large if minimum_k == small + 1 else 0)
    else:
        minimum_size = req.min_samples_per_client
        active_samples = n_samples - (clients - selected) * minimum_size
        capacity = active_samples // 2
        eligible = clients
        if minimum_k > minimum_size:
            eligible = min(clients, (n_samples - clients * minimum_size) // (minimum_k - minimum_size))
    # init_means retains a center only when it represents more than one sample.
    if capacity < minimum_k:
        raise ValueError(f"{path}.k: initial server needs >= {minimum_k} centers, "
                         f"but active clients can retain at most {capacity}")
    # With dropping disabled km_local must fit every broadcast center locally.
    min_active = selected if req.dropout_rate == 0 else 1
    if not params["drop_empty_clusters"] and eligible < min_active:
        raise ValueError(f"{path}.k: local update requires >= {minimum_k} samples at each active "
                         f"client when drop_empty_clusters is false")
    return {"upper_bound": capacity, "required_k": k, "status": "requires_compute_check",
            "check": "verify active clients' surviving nonsingleton centers against global k"}


def _variants(method: ClusteringAlgorithm, req: RunRequest, dataset: dict, shared: dict,
              overrides: dict, grid: dict, path: str) -> list[dict]:
    name = method.name
    proxy = req.privacy_mode in _AGGREGATE and name.startswith("Adapted ")
    common = {"k": shared["target_clusters"], "rounds": req.rounds, "tol": req.tol, "max_iter": req.max_iter,
              "density_min_samples": req.density_min_samples, "client_cpus": 1.0, "client_gpus": 0.0}
    defaults, sources = parameter_defaults(method, common, proxy)
    if name == "Adapted HF_DBSCAN" and not proxy:
        defaults["clients_selection_seed"] = req.seed
        sources["clients_selection_seed"] = "benchmark_seed"
    input_path = f"{path}.algorithm_params_by_name.{name}"
    supplied = normalize_overrides(overrides.get(name, {}), method, proxy, input_path, dataset["n_samples"], grid=False)
    alternatives = normalize_overrides(grid.get(name, {}), method, proxy, f"{path}.grid.{name}", dataset["n_samples"], grid=True)
    overlap = set(supplied) & alternatives.keys()
    if overlap:
        raise ValueError(f"{path}.grid.{name}.{sorted(overlap)[0]}: also present in algorithm_params_by_name")
    variants = []
    for values in product(*alternatives.values()):
        combination = dict(zip(alternatives, values))
        params = {**defaults, **supplied, **combination}
        provenance = {**sources, **dict.fromkeys(supplied, "override"), **dict.fromkeys(combination, "grid")}
        if params.get("linkage") == "ward" and params["metric"] != "euclidean":
            raise ValueError(f"{path}.{name}.metric: ward linkage requires euclidean")
        if params.get("metric") == "haversine" and dataset["n_features"] != 2:
            raise ValueError(f"{path}.{name}.metric: haversine requires two features")
        if req.cluster_count_mode == "estimated_k" and ("k" in supplied or "k" in combination):
            raise ValueError(f"{path}.{name}.k: conflicts with estimated_k")
        if "k" in params:
            params["n_clusters"] = params["k"]
            provenance["n_clusters"] = provenance["k"]
        if "rounds" in params and params["rounds"] > req.rounds:
            raise ValueError(f"{path}.{name}.rounds: exceeds the shared schedule; raise scenario.rounds")
        if req.privacy_mode in _AGGREGATE and "rounds" in params and params["rounds"] != req.rounds:
            raise ValueError(f"{path}.{name}.rounds: aggregate calibration uses the common round budget")
        if name == "Adapted HF_DBSCAN" and proxy and dataset["n_features"] < 2:
            raise ValueError(f"{path}.{name}: DP density projection requires >=2 features")
        rules = {}
        if req.cluster_count_mode == "estimated_k" and "k" in params:
            rules["k"] = rules["n_clusters"] = "COMPUTE.estimated_unlabeled_silhouette"
        if name == "dbscan" and params.get("eps") is None:
            rules["eps"] = "COMPUTE.k_distance_quantile"
            if req.tuning_mode == "unsupervised":
                rules["eps"] = rules["min_samples"] = "COMPUTE.tune_dbscan_unlabeled_or_profile_default"
        result = {"algorithm": name, "backend": _backend(name, proxy),
                  "effective_params": params, "parameter_sources": provenance, "deferred": rules,
                  "preprocessing": ("fixed_public_reference_then_l2_clip" if req.privacy_mode in _AGGREGATE
                                    else method.input_preprocessing)}
        if name == "Adapted FKM" and not proxy:
            result["first_round_capacity"] = _fkm_capacity(req, dataset["n_samples"], params, f"{path}.{name}")
        if proxy:
            result["display_algorithm"] = f"{name} [DP proxy]"
        variants.append(result)
    return variants


def resolve_scenario(scenario: dict, *, dataset: dict, seed: int, path: str) -> tuple[dict, list[dict]]:
    """Return one shared comparison protocol and ordered algorithm/grid variants."""
    req = _request(scenario, dataset, seed, path)
    registry = default_registry()
    methods = []
    for i, name in enumerate(req.algorithms):
        try:
            method = registry.get(name)
        except KeyError as exc:
            raise ValueError(f"{path}.algorithms[{i}]: unknown algorithm {name!r}") from exc
        if _is_federated(name, method) != (req.mode == "federated"):
            raise ValueError(f"{path}.algorithms[{i}]: {name!r} is incompatible with {req.mode}")
        methods.append(method)
    shared = _shared(req, dataset, methods, path)
    if req.mode == "federated":
        shared["stopping_profile"] = scenario["stopping_profile"]
    overrides = mapping(scenario.get("algorithm_params_by_name", {}), f"{path}.algorithm_params_by_name", keys=req.algorithms)
    grid = mapping(scenario.get("grid", {}), f"{path}.grid", keys=req.algorithms)
    variants = []
    for method in methods:
        variants.extend(_variants(method, req, dataset, shared, overrides, grid, path))
    return shared, variants
