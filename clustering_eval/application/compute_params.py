"""Resolve only compute-time controls from an already bound comparison and job."""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import numpy as np

from ..metrics.protocol_v2 import tune_dbscan_unlabeled
from ..privacy.aggregate_dp import make_dp_aggregate_config

if TYPE_CHECKING:
    from ..experiments.prepared import PreparedComparison

AGGREGATE_MODES = {"gaussian_dp_aggregate", "public_clipped_control"}
ONE_SHOT = {"Adapted FKDC", "Adapted HF_DBSCAN", "Adapted NN-FC", "Adapted p-FClus"}
AGGREGATE_FAMILIES = {
    "fed_kmeans_numpy": "kmeans", "fed_kmeans_flower": "kmeans",
    "fed_fuzzy_cmeans_numpy": "fuzzy", "fed_fuzzy_cmeans_flower": "fuzzy",
    "fed_gmm_diag_numpy": "gmm", "fed_gmm_diag_flower": "gmm",
    **dict.fromkeys(ONE_SHOT | {"Adapted FKM"}, "kmeans"),
}


def run_parameters(prepared: PreparedComparison, job: dict, X: np.ndarray) -> tuple[dict, dict | None]:
    """Resolve shared K, job-local tuning, calibrated budget and adapter controls."""
    name = job["algorithm"]
    protocol = prepared.comparison["protocol"]
    mode = protocol["privacy_mode"]
    historical = "historical_implementation" in protocol
    legacy = protocol.get("compatibility_profile") == "legacy-run.v1"
    params = deepcopy(job["effective_params"])
    if not legacy and protocol.get("cluster_count_mode") == "estimated_k":
        for alias in ("k", "n_clusters"):
            if alias in params and params[alias] is None:
                params[alias] = prepared.estimated_k

    if {"_stopping_profile", "_historical_compute", "participation_schedule"} & params.keys():
        raise ValueError("Adapter controls are reserved for comparison preparation")
    if protocol["mode"] == "federated" and not legacy:
        stopping = protocol["stopping_profile"]
        if stopping not in {"historical_paper", "current_gui"} or historical and stopping != "historical_paper":
            raise ValueError(f"Unsupported stopping_profile for this comparison: {stopping}")
        if stopping == "historical_paper" and name in {"fed_fuzzy_cmeans_flower", "fed_gmm_diag_flower"}:
            # PLAN omits job-level tol for full-budget current GUI Flower adapters.
            params.setdefault("tol", protocol["tol"])
        params["_stopping_profile"] = stopping
        params["_historical_compute"] = historical
        params["participation_schedule"] = deepcopy(prepared.schedule)
    if legacy and protocol["mode"] == "federated":
        params["_stopping_profile"] = "legacy_run"
    if protocol["mode"] == "local" and not legacy:
        # Current GUI and paper local workers pass an empty schedule.
        params["participation_schedule"] = []

    if mode in AGGREGATE_MODES:
        if name not in AGGREGATE_FAMILIES:
            raise ValueError(f"{name}: no vetted aggregate DP mechanism available")
        rounds = 1 if name in ONE_SHOT else params.get("rounds", protocol["rounds"])
        if type(rounds) is not int or rounds < 1 or rounds > len(prepared.schedule):
            raise ValueError(f"{name}: invalid effective aggregate round budget")
        if job.get("execution_profile") == "in_process_gui" and name not in ONE_SHOT:
            # Old GUI calibrates to the comparison budget even when an adapter stops earlier.
            rounds = protocol["rounds"]
        config = make_dp_aggregate_config(
            kind=AGGREGATE_FAMILIES[name], epsilon=protocol.get("dp_epsilon", 5.0),
            delta=protocol.get("dp_delta", 1e-5), clip_norm=protocol["dp_clip_norm"],
            rounds=rounds, enabled=mode == "gaussian_dp_aggregate",
        )
        if historical and params.get("dp_aggregate") != config:
            raise ValueError(f"{name}: historical aggregate calibration differs from resolved parameters")
        if not historical and "dp_aggregate" in params:
            raise ValueError("dp_aggregate is reserved for calibrated preparation")
        params["dp_aggregate"] = config
    elif "dp_aggregate" in params:
        raise ValueError("Unexpected aggregate mechanism in a non-aggregate comparison")

    tuning = None
    if name == "dbscan" and protocol.get("tuning_mode") == "unsupervised":
        if params.get("eps") is None:
            tuned, tuning = tune_dbscan_unlabeled(
                X, seed=prepared.comparison["seed"], sample_size=protocol["tuning_sample_size"],
            )
            params.update(tuned)
        else:
            tuning = {"skipped": "explicit_eps_override"}
    return params, tuning


def stopping_outcome(name: str, state: dict, protocol: dict) -> dict:
    """Keep policy requests distinct from the actual behavior of this adapter."""
    requested = protocol.get("stopping_profile")
    if "stopping_reason" in state:
        return {"requested": requested, "rule": state.get("stopping_policy"),
                "measure": state.get("stopping_measure"), "reason": state["stopping_reason"]}
    if name in ONE_SHOT:
        return {"requested": requested, "rule": "one_shot", "reason": "one_shot_completed"}
    if name == "Adapted FKM":
        return {"requested": requested, "rule": "fixed_rounds", "reason": "round_budget"}
    return {"requested": requested, "rule": "adapter_default", "reason": None}
