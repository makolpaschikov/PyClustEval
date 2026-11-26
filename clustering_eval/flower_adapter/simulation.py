"""Resource configuration and transport observations for a cold campaign simulation."""

from typing import Any


def backend_config(params: dict[str, Any]) -> dict:
    """Give campaign jobs a fresh local, CPU-only Ray instance in their worker tree."""
    resources = {
        "num_cpus": float(params.get("client_cpus", 1.0)),
        "num_gpus": float(params.get("client_gpus", 0.0)),
    }
    config = {"client_resources": resources}
    if params.get("_campaign_cold_flower"):
        import ray

        if ray.is_initialized():
            raise RuntimeError("Cold Flower requires a fresh process without a Ray runtime")
        config["init_args"] = {
            "address": "local",
            "_node_ip_address": "127.0.0.1",
            "num_cpus": 1,
            "num_gpus": 0,
            "object_store_memory": 128 * 1024**2,
            "include_dashboard": False,
        }
    return config


def received_fit(round_number: int, results: list) -> dict:
    """Record returned client counts and field names at the server, excluding values."""
    keys: dict[str, set[str]] = {"active": set(), "inactive": set()}
    active = 0
    for _, response in results:
        if response.metrics.get("active") == 1:
            active += 1
            keys["active"].update(response.metrics)
        else:
            keys["inactive"].update(response.metrics)
    return {
        "round": round_number,
        "returned_clients": len(results),
        "active_clients": active,
        "active_metric_keys": sorted(keys["active"]),
        "inactive_metric_keys": sorted(keys["inactive"]),
    }


def validate_transport(transport: list[dict], history: list[dict], *, budget: int,
                       clients: int, stopped: bool) -> None:
    """Reject an unfinished simulation before a campaign can accept its labels."""
    if len(transport) != budget or not history or len(history) > budget:
        raise RuntimeError("Flower simulation did not complete its round budget")
    for index, event in enumerate(transport):
        if event["round"] != index + 1:
            raise RuntimeError("Flower simulation returned out-of-order rounds")
        if index < len(history):
            update = history[index]
            if (update["round"] != index + 1 or event["dispatched_clients"] != clients
                    or event.get("returned_clients") != clients
                    or event.get("active_clients") != len(update["successful_clients"])):
                raise RuntimeError("Flower round has missing or inconsistent client responses")
        elif not stopped or event["dispatched_clients"] != 0:
            raise RuntimeError("Flower simulation skipped an expected server update")
