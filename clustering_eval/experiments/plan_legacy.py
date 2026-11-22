"""Explicit conversion of legacy grids while retaining the original runner's protocol."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..algorithms.base import ClusteringAlgorithm
from ..algorithms.registry import default_registry
from ..application.comparison_service import _is_federated
from ..application.dto import RunRequest
from .plan_identity import scientific_id
from .plan_io import fields, integer, relative_location, text_value
from .planner import build_plan
from .series_plan import (
    FORMAT, ResolvedCampaign, _definitions, _unique_names, campaign_settings, execution_settings, export_settings,
)

_METRICS = {"ari", "ami", "nmi", "silhouette", "davies_bouldin", "calinski_harabasz"}
_PARTITIONS = {"iid", "dirichlet", "quantity_skew", "label_limited"}


def _list(value: Any, path: str) -> list:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path}: expected a nonempty list")
    return value


def _metrics(value: Any) -> list[str]:
    values = _list(value, "legacy.metrics")
    for i, name in enumerate(values):
        if not isinstance(name, str) or name not in _METRICS or name in values[:i]:
            raise ValueError(f"legacy.metrics[{i}]: unknown or repeated metric {name!r}")
    return values


def migrate_legacy(config: dict, *, plan_dir: Path, legacy_cwd: Path) -> dict:
    """Materialize the old Cartesian product using its own planner, before publishing."""
    fields(config, {"experiment", "datasets", "algorithms", "partitioning", "metrics"},
           {"datasets", "algorithms"}, "$")
    exp = fields(config.get("experiment", {}), {"name", "output_dir", "repetitions", "seeds"},
                 set(), "experiment")
    repetitions = integer(exp.get("repetitions", 1), "experiment.repetitions", 1)
    if repetitions != 1:
        raise ValueError("experiment.repetitions: legacy repetitions reuse the same seed; "
                         "choose independent seeds or remove repeated conditions explicitly")
    for i, seed in enumerate(_list(exp.get("seeds", [42]), "experiment.seeds")):
        integer(seed, f"experiment.seeds[{i}]", 0, 2**32 - 1)
    part = fields(config.get("partitioning", {}), {"clients", "modes", "dirichlet_alpha"},
                  set(), "partitioning")
    for i, n in enumerate(_list(part.get("clients", [1]), "partitioning.clients")):
        integer(n, f"partitioning.clients[{i}]", 1)
    for i, mode in enumerate(_list(part.get("modes", ["iid"]), "partitioning.modes")):
        if not isinstance(mode, str) or mode not in _PARTITIONS:
            raise ValueError(f"partitioning.modes[{i}]: unknown partition {mode!r}")
    for i, alpha in enumerate(_list(part.get("dirichlet_alpha", [None]), "partitioning.dirichlet_alpha")):
        if alpha is not None and (type(alpha) not in (int, float) or alpha < 0):
            raise ValueError(f"partitioning.dirichlet_alpha[{i}]: expected nonnegative legacy alpha or null")
    for category in ("datasets", "algorithms"):
        for i, spec in enumerate(_list(config[category], category)):
            label = f"{category}[{i}]"
            fields(spec, {"name", "params"}, {"name"}, label)
            text_value(spec["name"], label + ".name")
            params = spec.get("params", {})
            if not isinstance(params, dict) or any(isinstance(v, list) and not v for v in params.values()):
                raise ValueError(f"{label}.params: expected a mapping with nonempty legacy grid axes")

    output = text_value(exp.get("output_dir", "results"), "experiment.output_dir")
    campaign = {"name": exp.get("name", "experiment"),
                "output_dir": relative_location((legacy_cwd / output).resolve(), plan_dir)}
    datasets: dict[str, dict] = {}
    series: dict[tuple[str, int], dict] = {}
    cases = []
    for item in build_plan(config):
        params = dict(item.dataset_params)
        prep_source = "provider_has_fixed_data"
        if item.dataset_name in {"blobs", "mnist_10k"}:
            prep_source = "explicit_random_state" if "random_state" in params else "benchmark_seed"
            params.setdefault("random_state", item.seed)
        elif "random_state" in params and item.dataset_name in {"iris", "wine", "digits", "dry_bean", "mnist_full"}:
            # The legacy runner forwarded random_state; these loaders did not use it to select observations.
            params.pop("random_state")
        if "path" in params:
            old = Path(text_value(params["path"], f"datasets.{item.dataset_name}.params.path"))
            params["path"] = relative_location((legacy_cwd / old).resolve(), plan_dir)
        definition = {"provider": "registry", "name": item.dataset_name, "params": params}
        key = "dataset-" + scientific_id("legacy-dataset-reference", definition)
        datasets.setdefault(key, definition)
        pair = (key, item.seed)
        if pair not in series:
            series[pair] = {"name": f"series-{len(series) + 1}", "dataset": key, "seed": item.seed}
        cases.append({"series": series[pair]["name"], "algorithm": item.algorithm_name,
                      "algorithm_params": item.algorithm_params, "partition_mode": item.partition_mode,
                      "num_clients": item.num_clients, "dirichlet_alpha": item.dirichlet_alpha,
                      "preparation_seed_source": prep_source})
    return {"format": FORMAT, "campaign": campaign, "datasets": datasets, "series": list(series.values()),
            "legacy": {"profile": "legacy-run.v1", "metrics": _metrics(config.get("metrics", ["ari","nmi","silhouette"])),
                       "jobs": cases}}


def _legacy_parameters(adapter: ClusteringAlgorithm, overrides: dict, data: dict, path: str) -> tuple[int, dict]:
    """Validate values without rewriting legacy aliases or imposing a GUI round schedule."""
    from .plan_parameters import parameters_for, parameter_value

    benchmark_k = overrides.get("n_clusters", overrides.get("k", data["n_classes"] or 3))
    common = {"k": benchmark_k, "n_clusters": benchmark_k, "rounds": 10, "tol": 1e-4,
              "max_iter": 300, "client_cpus": 1.0, "client_gpus": 0.0}
    allowed, aliases = parameters_for(adapter, proxy=False)
    for name, value in overrides.items():
        field = f"{path}.algorithm_params.{name}"
        key = aliases.get(name, name)
        if name not in common and key not in allowed:
            raise ValueError(f"{field}: unsupported or reserved legacy parameter for {adapter.name}")
        if name in ("k", "n_clusters"):
            integer(value, field, 1, data["n_samples"])
        else:
            parameter_value(key, value, field, data["n_samples"])
    # The benchmark row used n_clusters first; individual adapters read the actual mapping.
    supplied = common | adapter.default_params | overrides
    if supplied.get("linkage") == "ward" and supplied.get("metric") != "euclidean":
        raise ValueError(f"{path}.algorithm_params.metric: ward linkage requires euclidean")
    if supplied.get("metric") == "haversine" and data["n_features"] != 2:
        raise ValueError(f"{path}.algorithm_params.metric: haversine requires two features")
    return benchmark_k, supplied


def resolve_legacy(document: dict, *, base_dir: Path, source_id: str) -> dict:
    from .plan_data import resolve_dataset
    from .plan_protocol import _backend, _fkm_capacity

    keys = {"format", "campaign", "datasets", "series", "legacy"}
    fields(document, keys, keys, "$")
    legacy = fields(document["legacy"], {"profile", "metrics", "jobs"},
                    {"profile", "metrics", "jobs"}, "legacy")
    if legacy["profile"] != "legacy-run.v1":
        raise ValueError("legacy.profile: expected legacy-run.v1")
    metrics = _metrics(legacy["metrics"])
    ds = _definitions(document["datasets"], "datasets")
    datasets = {}
    for name, spec in ds.items():
        text_value(name, "datasets.key")
        if not isinstance(spec, dict) or spec.get("provider") != "registry":
            raise ValueError(f"datasets.{name}.provider: legacy runner uses registry inputs")
        datasets[name] = resolve_dataset(spec, base_dir=base_dir, path=f"datasets.{name}")
    result = ResolvedCampaign(source_id, campaign_settings(document["campaign"], base_dir),
                              [dict(data, key=key) for key, data in datasets.items()],
                              execution_settings({}), export_settings({}))
    by_name = {}
    for i, item in enumerate(_list(document["series"], "series")):
        path = f"series[{i}]"
        fields(item, {"name", "dataset", "seed"}, {"name", "dataset", "seed"}, path)
        name = text_value(item["name"], path + ".name")
        key = text_value(item["dataset"], path + ".dataset")
        if name in by_name or key not in datasets:
            raise ValueError(f"{path}: duplicate series or unknown dataset")
        entry = {"name": name, "dataset": key, "dataset_id": datasets[key]["dataset_id"],
                 "seed": integer(item["seed"], path + ".seed", 0, 2**32 - 1), "scenarios": []}
        by_name[name] = entry
        result.series.append(entry)
    _unique_names(list(by_name), "series.name")
    registry = default_registry()
    for i, case in enumerate(_list(legacy["jobs"], "legacy.jobs")):
        path = f"legacy.jobs[{i}]"
        keys = {"series", "algorithm", "algorithm_params", "partition_mode", "num_clients",
                "dirichlet_alpha", "preparation_seed_source"}
        fields(case, keys, keys, path)
        series_name = text_value(case["series"], path + ".series")
        algorithm = text_value(case["algorithm"], path + ".algorithm")
        if series_name not in by_name or algorithm not in registry.names():
            raise ValueError(f"{path}: unknown series {series_name!r} or algorithm {algorithm!r}")
        entry = by_name[series_name]
        data = datasets[entry["dataset"]]
        adapter = registry.get(algorithm)
        mode = "federated" if _is_federated(algorithm, adapter) else "local"
        clients = integer(case["num_clients"], path + ".num_clients", 1)
        partition = text_value(case["partition_mode"], path + ".partition_mode")
        alpha = case["dirichlet_alpha"]
        if partition not in _PARTITIONS or alpha is not None and (type(alpha) not in (int,float) or alpha < 0):
            raise ValueError(f"{path}: invalid partition_mode or dirichlet_alpha")
        minimum = max(3, int(adapter.min_client_samples))
        if clients * minimum > data["n_samples"]:
            raise ValueError(f"{path}.num_clients: too few samples for {clients} clients of size {minimum}")
        # make_partition defaults to two labels/client, including for a local legacy algorithm.
        if partition == "label_limited" and (data["n_classes"] is None or clients * 2 < data["n_classes"]):
            raise ValueError(f"{path}.partition_mode: label_limited with {clients} clients and "
                             f"2 labels per client cannot cover {data['n_classes']} classes")
        seed_source = case["preparation_seed_source"]
        if seed_source not in ("explicit_random_state", "benchmark_seed", "provider_has_fixed_data"):
            raise ValueError(f"{path}.preparation_seed_source: unsupported origin")
        if seed_source == "benchmark_seed" and datasets[entry["dataset"]]["params"].get("random_state") != entry["seed"]:
            raise ValueError(f"{path}: dataset random_state disagrees with the legacy benchmark seed")
        overrides = case["algorithm_params"]
        if not isinstance(overrides, dict):
            raise ValueError(f"{path}.algorithm_params: expected an object")
        benchmark_k, supplied = _legacy_parameters(adapter, overrides, data, path)
        protocol = {"compatibility_profile":"legacy-run.v1", "mode":mode,
                    "num_clients":clients, "partition_mode":partition, "dirichlet_alpha":alpha or 0.5,
                    "min_samples_per_client":minimum, "metrics":metrics, "privacy_mode":"none",
                    "schedule":"legacy_adapter_default", "evaluation_space":"StandardScaler(original_raw_X)"}
        if partition == "label_limited":
            protocol["labels_per_client"] = 2
        if mode == "federated":
            protocol["stopping_profile"] = "legacy_run"
        variant = {"algorithm":algorithm, "backend":_backend(algorithm, False), "effective_params":supplied,
                   "legacy_benchmark_k":benchmark_k,
                   "parameter_sources":{k: "legacy_override" if k in overrides else
                                        "adapter_default" if k in adapter.default_params else "legacy_common"
                                        for k in supplied},
                   "preparation_seed_source":seed_source,
                   "preprocessing":adapter.input_preprocessing,
                   "execution_readiness":"requires_legacy_protocol_support"}
        if algorithm == "Adapted FKM":
            # Legacy workers passed no schedule. The initial author round uses all clients.
            request = RunRequest(mode="federated", dataset_name=data["name"], algorithms=(algorithm,),
                                 num_clients=clients, partition_mode=partition, min_samples_per_client=minimum,
                                 participation_rate=1.0, dropout_rate=0.0)
            adapter_inputs = {"k": supplied["n_clusters"],
                              "drop_empty_clusters": supplied["drop_empty_clusters"]}
            variant["first_round_capacity"] = _fkm_capacity(
                request, data["n_samples"], adapter_inputs, f"{path}.algorithm_params"
            )
        name = f"case-{i + 1}"
        entry["scenarios"].append(name)
        result.add_comparison(entry, name, protocol, [variant])
    if any(not entry["scenarios"] for entry in result.series):
        raise ValueError("legacy.jobs: a declared series has no jobs")
    return result.document()
