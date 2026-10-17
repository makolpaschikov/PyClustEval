from __future__ import annotations

from typing import Any

import numpy as np


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
    if isinstance(schedule, list) and schedule:
        item = schedule[min(max(int(round_index), 0), len(schedule) - 1)]
        if isinstance(item, dict):
            selected = _validated_client_ids(item.get("selected_clients"), num_clients)
            successful = _validated_client_ids(item.get("successful_clients"), num_clients)
            dropped = _validated_client_ids(item.get("dropped_clients"), num_clients)
            if not successful:
                raise ValueError("Participation schedule contains a round with no successful clients")
            return {
                "round": int(item.get("round", round_index + 1)),
                "selected_clients": selected,
                "successful_clients": successful,
                "dropped_clients": dropped,
            }
    all_clients = list(range(num_clients))
    return {
        "round": int(round_index) + 1,
        "selected_clients": all_clients,
        "successful_clients": all_clients,
        "dropped_clients": [],
    }


def successful_clients_for_round(
    params: dict[str, Any],
    round_index: int,
    num_clients: int,
) -> list[int]:
    return participation_entry_for_round(params, round_index, num_clients)[
        "successful_clients"
    ]


def _validated_client_ids(value: Any, num_clients: int) -> list[int]:
    if value is None:
        return []
    result = sorted({int(v) for v in value})
    if any(v < 0 or v >= num_clients for v in result):
        raise ValueError(
            f"Participation schedule contains client outside 0..{num_clients - 1}: {result}"
        )
    return result
