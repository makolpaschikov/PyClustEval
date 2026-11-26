from __future__ import annotations

from numbers import Integral
from typing import Any

import numpy as np


def validate_round_budget(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError("rounds must be a positive integer")
    return int(value)


def make_participation_schedule(
    *,
    num_clients: int,
    rounds: int,
    participation_rate: float,
    dropout_rate: float,
    seed: int,
) -> list[dict[str, Any]]:
    """Create one deterministic client-availability schedule for an experiment.

    Selection happens first, then selected clients independently drop with the
    requested probability.  At least one successful client is retained in every
    round so algorithms never receive an empty aggregation set.
    """
    if num_clients < 1:
        raise ValueError("num_clients must be at least 1")
    if rounds < 1:
        raise ValueError("rounds must be at least 1")
    if not 0 < participation_rate <= 1:
        raise ValueError("participation_rate must be in (0, 1]")
    if not 0 <= dropout_rate < 1:
        raise ValueError("dropout_rate must be in [0, 1)")

    rng = np.random.default_rng(int(seed) ^ 0x5A17C1E)
    selected_count = max(1, min(num_clients, int(np.ceil(num_clients * participation_rate))))
    schedule: list[dict[str, Any]] = []

    for round_idx in range(rounds):
        selected = np.sort(
            rng.choice(num_clients, size=selected_count, replace=False)
        ).astype(int)
        dropped_mask = rng.random(selected_count) < dropout_rate
        if dropped_mask.all():
            # Keep one deterministic successful client from this draw.  This
            # avoids undefined all-dropout rounds while preserving reproducibility.
            dropped_mask[int(rng.integers(0, selected_count))] = False
        dropped = selected[dropped_mask]
        successful = selected[~dropped_mask]
        schedule.append(
            {
                "round": round_idx + 1,
                "selected_clients": [int(v) for v in selected],
                "successful_clients": [int(v) for v in successful],
                "dropped_clients": [int(v) for v in dropped],
            }
        )
    return schedule


def participation_entry_for_round(
    params: dict[str, Any],
    round_index: int,
    num_clients: int,
) -> dict[str, Any]:
    schedule = params.get("participation_schedule")
    strict = historical_stopping(params)
    if isinstance(schedule, list) and schedule:
        if strict and not 0 <= round_index < len(schedule):
            raise ValueError("Participation schedule does not cover the requested round")
        item = schedule[min(max(int(round_index), 0), len(schedule) - 1)]
        if isinstance(item, dict):
            selected = _validated_client_ids(item.get("selected_clients"), num_clients, strict)
            successful = _validated_client_ids(item.get("successful_clients"), num_clients, strict)
            dropped = _validated_client_ids(item.get("dropped_clients"), num_clients, strict)
            if not successful:
                raise ValueError("Participation schedule contains a round with no successful clients")
            if strict and item.get("round", round_index + 1) != round_index + 1:
                raise ValueError("Participation schedule has an unexpected round number")
            if strict and (set(successful) & set(dropped)
                    or (set(successful) | set(dropped)) != set(selected)):
                raise ValueError("Successful and dropped clients must partition the selected clients")
            return {
                "round": int(item.get("round", round_index + 1)),
                "selected_clients": selected,
                "successful_clients": successful,
                "dropped_clients": dropped,
            }
        if strict:
            raise ValueError("Participation schedule entries must be dictionaries")
    if strict and schedule is not None and not isinstance(schedule, list):
        raise ValueError("Participation schedule must be a list")
    all_clients = list(range(num_clients))
    return {
        "round": int(round_index) + 1,
        "selected_clients": all_clients,
        "successful_clients": all_clients,
        "dropped_clients": [],
    }


def historical_stopping(params: dict[str, Any]) -> bool:
    """Identify the requested stopping rule, independent of traffic and preprocessing."""
    profile = params.get("_stopping_profile", "current_gui")
    if profile not in {"legacy_run", "current_gui", "historical_paper"}:
        raise ValueError(f"Unknown stopping profile: {profile!r}")
    if params.get("_historical_compute") and profile != "historical_paper":
        raise ValueError("The paper compute profile requires historical_paper stopping")
    return profile == "historical_paper"


def early_stopping_allowed(
    params: dict[str, Any], rounds: int, num_clients: int, *, current: bool = True
) -> bool:
    """Check historical eligibility over the effective budget before any update."""
    if not historical_stopping(params):
        return current
    validate_round_budget(params.get("rounds", rounds))
    successful_sets = {
        frozenset(participation_entry_for_round(params, rnd, num_clients)["successful_clients"])
        for rnd in range(rounds)
    }
    dp = params.get("dp_aggregate")
    if dp is not None and dp.get("enabled") and rounds > validate_round_budget(dp["budgeted_rounds"]):
        raise ValueError("Requested rounds exceed the calibrated aggregate-DP budget")
    noisy = dp is not None and float(dp["sigma_per_coordinate"]) > 0
    return len(successful_sets) == 1 and not noisy


def stopping_report(
    params: dict[str, Any], allowed: bool, stopped: bool, measure: str
) -> dict[str, Any]:
    """Describe an observed stop separately from the scientific profile request."""
    if "_stopping_profile" not in params:
        return {}
    if allowed:
        policy = "tolerance_fixed_clients" if historical_stopping(params) else "tolerance_each_update"
    else:
        policy = "fixed_round_budget"
    return {
        "stopping_policy": policy,
        "stopping_reason": "tolerance" if stopped else "round_budget",
        "stopping_measure": measure if allowed else None,
    }


def downlink_recipients(
    params: dict[str, Any], participation: dict[str, Any], partition: list[np.ndarray]
) -> int:
    """Count logical model recipients under the selected communication convention."""
    if params.get("_historical_compute"):
        return len(participation["selected_clients"])
    return sum(bool(len(partition[c])) for c in participation["successful_clients"])


def successful_clients_for_round(
    params: dict[str, Any],
    round_index: int,
    num_clients: int,
) -> list[int]:
    return participation_entry_for_round(params, round_index, num_clients)[
        "successful_clients"
    ]


def _validated_client_ids(value: Any, num_clients: int, strict: bool) -> list[int]:
    if strict:
        if not isinstance(value, list) or any(type(v) is not int for v in value):
            raise ValueError("Historical participation requires a list of integer client IDs")
        if len(set(value)) != len(value):
            raise ValueError("Duplicate client ID in historical participation")
    if value is None:
        return []
    result = list(value) if strict else sorted({int(v) for v in value})
    if any(v < 0 or v >= num_clients for v in result):
        raise ValueError(
            f"Participation schedule contains client outside 0..{num_clients - 1}: {result}"
        )
    return result
