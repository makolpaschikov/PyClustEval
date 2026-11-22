"""Versioned content identifiers for scientific conditions, independent of file location."""
from __future__ import annotations

from hashlib import sha256
import json


def scientific_id(kind: str, payload: dict) -> str:
    """Hash UTF-8 JSON with stable object ordering and unmodified list order."""
    encoded = json.dumps(
        ["pyclusteval.scientific-id.v1", kind, payload], sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def comparison_key(*, source_id: str, dataset_id: str, seed: int, protocol: dict) -> str:
    return scientific_id("comparison", {
        "source_id": source_id, "dataset_id": dataset_id, "seed": seed, "protocol": protocol,
    })


def job_key(*, comparison_id: str, algorithm: str, backend: str,
            effective_params: dict, execution_profile: str | dict) -> str:
    return scientific_id("job", {
        "comparison_id": comparison_id, "algorithm": algorithm, "backend": backend,
        "effective_params": effective_params, "execution_profile": execution_profile,
    })


def group_key(input_key: str, job_ids: list[str]) -> str:
    """Identify a comparison's membership separately from each job's scientific inputs."""
    return scientific_id("group", {"input_id": input_key, "job_ids": sorted(job_ids)})
