"""Strict parameter checks for the built-in campaign planning profile."""
from __future__ import annotations

import math
from typing import Any, Collection

from sklearn.neighbors import VALID_METRICS

from ..algorithms.base import ClusteringAlgorithm
from ..default_profile import defaults_for


def mapping(value: Any, path: str, *, keys: Collection[str] | None = None) -> dict:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{path}: expected an object with string keys")
    if keys is not None:
        for key in value:
            if key not in keys:
                raise ValueError(f"{path}.{key}: unknown field")
    return value


def integer(value: Any, path: str, minimum: int = 1, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        upper = "" if maximum is None else f" and <= {maximum}"
        raise ValueError(f"{path}: expected an integer >= {minimum}{upper}")
    return value


def number(value: Any, path: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{path}: expected a finite number")
    try:
        result = float(value)
    except OverflowError:
        raise ValueError(f"{path}: number exceeds the supported range") from None
    if not math.isfinite(result):
        raise ValueError(f"{path}: expected a finite number")
    return result


def choice(value: Any, options: Collection[str], path: str) -> str:
    if not isinstance(value, str) or value not in options:
        raise ValueError(f"{path}: expected one of {', '.join(sorted(options))}")
    return value


# Common controls are declared by each algorithm's common_param_support.
# These are the additional named controls actually consumed by individual adapters.
_EXTRA = {
    "dbscan": {"min_samples"},
    "Adapted HF_DBSCAN": {"clients_selection_seed"},
}
_ALIASES = {
    "Adapted FKM": {"crounds": "rounds", "local_iter": "iter_local", "drop": "drop_empty_clusters"},
    "Adapted HF_DBSCAN": {"cell_size": "L", "MIN_POINTS": "min_points", "density_min_samples": "min_points"},
    "Adapted p-FClus": {"max_iters": "pfclus_max_iters"},
    "dbscan": {"density_min_samples": "min_samples"},
}

# The aggregate/clipped author-server adapters take a different execution path.
_PROXY_CONTROLS = {
    "Adapted FKM": {"k", "rounds", "weighted_agg"},
    "Adapted HF_DBSCAN": {"k", "min_points", "dp_proxy_cell_size"},
    "Adapted p-FClus": {"k"},
    "Adapted NN-FC": {"k"},
    "Adapted FKDC": {"k"},
}


def parameters_for(algorithm: ClusteringAlgorithm, proxy: bool) -> tuple[set[str], dict[str, str]]:
    name = algorithm.name
    if proxy:
        allowed = set(_PROXY_CONTROLS[name])
    else:
        allowed = set(algorithm.common_param_support) - {"seed"}
        allowed.update(algorithm.default_params)
        allowed.update(_EXTRA.get(name, ()))
    if name == "Adapted HF_DBSCAN":
        # Its adapter defaults always set min_points, which wins over the
        # common density_min_samples in the actual threshold selection.
        allowed.discard("density_min_samples")
    if name.endswith("_flower"):
        allowed.update(("client_cpus", "client_gpus"))
        # This implementation runs the full budget and does not read tol.
        if name in {"fed_gmm_diag_flower", "fed_fuzzy_cmeans_flower"}:
            allowed.discard("tol")
    aliases = dict(_ALIASES.get(name, {}))
    if "k" in allowed:
        aliases["n_clusters"] = "k"
    return allowed, {key: dest for key, dest in aliases.items() if dest in allowed}


def parameter_value(key: str, value: Any, path: str, n_samples: int) -> Any:
    if key == "k":
        return integer(value, path, 2, n_samples)
    if key in {"rounds", "max_iter", "n_init", "iter_local", "pfclus_max_iters", "min_points", "min_samples", "density_min_samples"}:
        return integer(value, path)
    if key == "missing_clients_percentage":
        return integer(value, path, 0, 99)
    if key == "clients_selection_seed":
        return integer(value, path, 0, 2**32 - 1)
    if key in {"drop_empty_clusters", "weighted_agg"}:
        if type(value) is not bool:
            raise ValueError(f"{path}: expected a boolean")
        return value
    if key == "eps" and (value is None or isinstance(value, str) and value.strip().lower() in {"", "auto", "none"}):
        return None
    choices = {
        "init": {"random", "k-means++"},
        "eps_strategy": {"k_distance_quantile"},
        "covariance_type": {"full", "diag", "tied", "spherical"},
        "init_params": {"kmeans", "random", "k-means++", "random_from_data"},
        "linkage": {"ward", "complete", "average", "single"},
        # Input is a feature matrix. Precomputed distances are a different protocol.
        "metric": set(VALID_METRICS["brute"]) - {"precomputed", "mahalanobis", "seuclidean"},
    }
    if key in choices:
        return choice(value, choices[key], path)
    numeric = number(value, path)
    if key == "eps_quantile":
        valid = 0 < numeric < 1
    elif key == "fuzziness":
        valid = numeric > 1
    elif key in {"client_gpus", "reg_covar"}:
        valid = numeric >= 0
    else:
        valid = numeric > 0
    if not valid:
        raise ValueError(f"{path}: {numeric} outside the supported range for {key}")
    return numeric


def normalize_overrides(
    raw: dict, algorithm: ClusteringAlgorithm, proxy: bool, path: str, n_samples: int, *, grid: bool,
) -> dict:
    allowed, aliases = parameters_for(algorithm, proxy)
    result = {}
    for supplied, value in mapping(raw, path).items():
        key = aliases.get(supplied, supplied)
        field = f"{path}.{supplied}"
        if key not in allowed:
            raise ValueError(f"{field}: unsupported or reserved parameter for {algorithm.name}")
        if key in result:
            raise ValueError(f"{field}: duplicate alias for {key}")
        if grid:
            if type(value) is not list or not value:
                raise ValueError(f"{field}: grid alternatives must be a nonempty list")
            result[key] = [parameter_value(key, v, f"{field}[{i}]", n_samples) for i, v in enumerate(value)]
        else:
            result[key] = parameter_value(key, value, field, n_samples)
    return result


def parameter_defaults(algorithm: ClusteringAlgorithm, common: dict, proxy: bool) -> tuple[dict, dict]:
    """Keep effective adapter inputs and the winning provider of each default."""
    allowed, _ = parameters_for(algorithm, proxy)
    params = {}
    sources = {}
    for label, options in (("comparison", common), ("adapter", algorithm.default_params),
                           ("generic_sane_defaults_v2", defaults_for(algorithm.name))):
        for key, value in options.items():
            if key in allowed:
                params[key] = value
                sources[key] = label
    if algorithm.name == "dbscan":
        params["min_samples"] = params.pop("density_min_samples")
        sources["min_samples"] = sources.pop("density_min_samples")
    if proxy and algorithm.name == "Adapted HF_DBSCAN":
        params["dp_proxy_cell_size"] = 0.75
        sources["dp_proxy_cell_size"] = "author_server_proxy"
    return params, sources
