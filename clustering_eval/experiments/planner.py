from __future__ import annotations
from dataclasses import dataclass, asdict
from itertools import product
from typing import Any

@dataclass(frozen=True)
class ExperimentSpec:
    experiment_name: str
    dataset_name: str
    dataset_params: dict[str, Any]
    algorithm_name: str
    algorithm_params: dict[str, Any]
    partition_mode: str
    num_clients: int
    dirichlet_alpha: float | None
    seed: int
    repetition: int

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


def expand_params(params: dict[str, Any] | None) -> list[dict[str, Any]]:
    params = params or {}
    if not params:
        return [{}]
    keys = list(params.keys())
    values = [v if isinstance(v, list) else [v] for v in params.values()]
    return [dict(zip(keys, combo)) for combo in product(*values)]


def build_plan(config: dict[str, Any]) -> list[ExperimentSpec]:
    exp = config.get("experiment", {})
    pname = exp.get("name", "experiment")
    seeds = exp.get("seeds", [42])
    repetitions = int(exp.get("repetitions", 1))
    part = config.get("partitioning", {})
    clients = part.get("clients", [1])
    modes = part.get("modes", ["iid"])
    alphas = part.get("dirichlet_alpha", [None])

    specs: list[ExperimentSpec] = []
    for ds_cfg, algo_cfg, seed, rep in product(config.get("datasets", []), config.get("algorithms", []), seeds, range(repetitions)):
        for ds_params in expand_params(ds_cfg.get("params", {})):
            for algo_params in expand_params(algo_cfg.get("params", {})):
                for num_clients, mode in product(clients, modes):
                    alpha_values = alphas if mode == "dirichlet" else [None]
                    for alpha in alpha_values:
                        specs.append(ExperimentSpec(
                            experiment_name=pname,
                            dataset_name=ds_cfg["name"],
                            dataset_params=ds_params,
                            algorithm_name=algo_cfg["name"],
                            algorithm_params=algo_params,
                            partition_mode=mode,
                            num_clients=int(num_clients),
                            dirichlet_alpha=None if alpha is None else float(alpha),
                            seed=int(seed),
                            repetition=rep,
                        ))
    return specs
