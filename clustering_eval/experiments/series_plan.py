"""Resolve a user-supplied campaign into auditable comparison and job records."""
from __future__ import annotations

from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from typing import Any
import unicodedata

from .plan_identity import comparison_key, group_key, job_key, scientific_id
from .plan_io import fields, integer, text_value
from .source_archive import portable_path

FORMAT = "pyclusteval.plan.v1"
RESOLVED_FORMAT = "pyclusteval.resolved-plan.v1"


def checkout_source_id() -> str:
    """Capture the code actually imported by this CLI, irrespective of the shell's cwd."""
    from .source_capture import capture_source_snapshot

    root = Path(__file__).resolve().parents[2]
    with TemporaryDirectory(prefix="pyclusteval-plan-source-") as temp:
        return capture_source_snapshot(root, Path(temp) / "source").source_id


def _name(value: Any, path: str) -> str:
    name = text_value(value, path)
    if "/" in name or name != name.strip():
        raise ValueError(f"{path}: expected a portable name, got {name!r}")
    try:
        return portable_path(name)
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error


def _unique_names(values: list, path: str) -> None:
    seen = set()
    for index, value in enumerate(values):
        name = _name(value, f"{path}[{index}]")
        folded = unicodedata.normalize("NFC", name).casefold()
        if folded in seen:
            raise ValueError(f"{path}[{index}]: duplicate or ambiguous name {name!r}")
        seen.add(folded)


def _definitions(value: Any, path: str) -> dict:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{path}: expected a nonempty object keyed by name")
    _unique_names(list(value), path)
    return value


def campaign_settings(value: Any, base_dir: Path) -> dict:
    obj = fields(value, {"name", "output_dir", "description"}, {"name"}, "campaign")
    name = _name(obj["name"], "campaign.name")
    output = text_value(obj.get("output_dir", name), "campaign.output_dir")
    description = obj.get("description", "")
    if not isinstance(description, str):
        raise ValueError("campaign.description: expected a string")
    return {"name": name, "output_dir": str((base_dir / output).resolve()), "description": description}


def execution_settings(value: Any) -> dict:
    defaults = {"processes": 1, "blas_threads": 1, "timeout_sec": None, "total_time_sec": None,
                "memory_limit_mb": None, "failure_policy": "continue", "max_retries": 0,
                "profile": "cold"}
    result = defaults | fields(value, set(defaults), set(), "execution")
    for field in ("processes", "blas_threads", "max_retries"):
        integer(result[field], f"execution.{field}", 0 if field == "max_retries" else 1)
    for field in ("timeout_sec", "total_time_sec"):
        n = result[field]
        if n is not None and (type(n) not in (int, float) or n <= 0 or not n <= sys.float_info.max):
            raise ValueError(f"execution.{field}: expected a finite positive duration or null")
    if result["memory_limit_mb"] is not None:
        integer(result["memory_limit_mb"], "execution.memory_limit_mb", 1)
    if result["failure_policy"] not in ("continue", "stop"):
        raise ValueError("execution.failure_policy: expected continue or stop")
    if result["profile"] not in ("cold", "warm"):
        raise ValueError("execution.profile: expected cold or warm")
    return result


def export_settings(value: Any) -> dict:
    obj = fields(value, {"profile", "verify_checksums"}, set(), "export")
    profile = obj.get("profile", "general")
    if profile != "general":
        raise ValueError("export.profile: ordinary campaigns use the general profile")
    if obj.get("verify_checksums", True) is not True:
        raise ValueError("export.verify_checksums: checksum verification is required")
    return {"profile": profile, "verify_checksums": True}


class ResolvedCampaign:
    """Collect groups, rejecting repeated scientific jobs regardless of their display names."""
    def __init__(self, source_id: str, campaign: dict, datasets: list[dict], execution: dict,
                 export: dict) -> None:
        self.source_id = source_id
        self.campaign = campaign
        self.datasets = datasets
        self.execution = execution
        self.export = export
        self.series: list[dict] = []
        self.comparisons: list[dict] = []
        self.jobs: list[dict] = []
        self._job_origins: dict[str, tuple[str, str]] = {}

    def add_comparison(self, series: dict, scenario: str, protocol: dict,
                       variants: list[dict]) -> None:
        if protocol.get("privacy_mode") == "gaussian_dp":
            # All variants consume a single release for this comparison, including grid points.
            members = [scientific_id("release-member", {k: v[k] for k in
                         ("algorithm", "backend", "effective_params")}) for v in variants]
            protocol = dict(protocol, input_release_members=sorted(members))
        input_key = comparison_key(source_id=self.source_id, dataset_id=series["dataset_id"],
                                   seed=series["seed"], protocol=protocol)
        jobs = []
        for index, variant in enumerate(variants):
            profile = variant.get("execution_profile", self.execution["profile"])
            # Parallel workers/BLAS configuration can change numerics or resource measurements.
            profile_id = {"lifecycle": profile, "processes": self.execution["processes"],
                          "blas_threads": self.execution["blas_threads"]}
            key = job_key(comparison_id=input_key, algorithm=variant["algorithm"],
                          backend=variant["backend"], effective_params=variant["effective_params"],
                          execution_profile=profile_id)
            run_id = f"{scenario}_{index}"
            external = (series["name"], run_id)
            if key in self._job_origins:
                raise ValueError(f"series.{external[0]}.{run_id}: duplicate scientific job; "
                                 f"same conditions as {self._job_origins[key]}")
            self._job_origins[key] = external
            jobs.append({**variant, "job_id": key, "run_id": run_id, "series": series["name"],
                         "execution_profile": profile_id})
        comparison = group_key(input_key, [job["job_id"] for job in jobs])
        self.comparisons.append({"comparison_id": comparison, "input_id": input_key,
                                 "series": series["name"], "scenario": scenario,
                                 "dataset_id": series["dataset_id"], "seed": series["seed"],
                                 "protocol": protocol})
        self.jobs.extend(dict(job, comparison_id=comparison) for job in jobs)

    def document(self) -> dict:
        return {"format": RESOLVED_FORMAT, "source_id": self.source_id,
                "campaign": self.campaign, "datasets": self.datasets, "series": self.series,
                "comparisons": self.comparisons, "jobs": self.jobs, "execution": self.execution,
                "export": self.export,
                "counts": {"series": len(self.series), "comparisons": len(self.comparisons),
                           "jobs": len(self.jobs)}}


def _with_execution_readiness(plan: dict) -> dict:
    """Report requested runtime profiles separately from static validity and scientific IDs."""
    profiles = set()
    for job in plan["jobs"]:
        profile = job["execution_profile"]
        lifecycle = profile["lifecycle"] if isinstance(profile, dict) else profile
        profiles.add((job["backend"], lifecycle))
    plan["execution_readiness"] = {
        "status": "not_checked",
        "scope": "backend_and_lifecycle",
        "profiles": [{"backend": backend, "lifecycle": lifecycle} for backend, lifecycle in sorted(profiles)],
    }
    return plan


def resolve_document(document: dict, *, base_dir: Path, source_id: str) -> dict:
    """Validate and expand without starting a backend. Relative source paths use base_dir."""
    if not isinstance(document, dict) or document.get("format") != FORMAT:
        raise ValueError(f"format: expected {FORMAT!r}")
    if not isinstance(source_id, str) or not re.fullmatch(r"[0-9a-f]{64}", source_id):
        raise ValueError("source_id: expected a SOURCE content ID (64 lowercase hex digits)")
    if "historical" in document:
        from .plan_archive import resolve_historical
        return _with_execution_readiness(resolve_historical(document, base_dir=base_dir, source_id=source_id))
    if "legacy" in document:
        from .plan_legacy import resolve_legacy
        return _with_execution_readiness(resolve_legacy(document, base_dir=base_dir, source_id=source_id))

    from .plan_data import resolve_dataset
    from .plan_protocol import resolve_scenario

    required = {"format", "campaign", "datasets", "scenarios", "series"}
    fields(document, required | {"execution", "export"}, required, "$")
    data_specs = _definitions(document["datasets"], "datasets")
    scenarios = _definitions(document["scenarios"], "scenarios")
    data = {key: resolve_dataset(spec, base_dir=base_dir, path=f"datasets.{key}")
            for key, spec in data_specs.items()}
    result = ResolvedCampaign(source_id, campaign_settings(document["campaign"], base_dir),
                              [dict(item, key=key) for key, item in data.items()],
                              execution_settings(document.get("execution", {})),
                              export_settings(document.get("export", {})))
    entries = document["series"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("series: expected a nonempty list")
    used_scenarios = set()
    for i, raw_series in enumerate(entries):
        path = f"series[{i}]"
        keys = {"name", "dataset", "seed", "scenarios"}
        entry = fields(raw_series, keys, keys, path)
        dataset = text_value(entry["dataset"], f"{path}.dataset")
        if dataset not in data:
            raise ValueError(f"{path}.dataset: unknown dataset {dataset!r}")
        seed = integer(entry["seed"], f"{path}.seed", 0, 2**32 - 1)
        selected = entry["scenarios"]
        if not isinstance(selected, list) or not selected:
            raise ValueError(f"{path}.scenarios: expected a nonempty list")
        _unique_names(selected, f"{path}.scenarios")
        series = {"name": _name(entry["name"], f"{path}.name"), "dataset": dataset,
                  "dataset_id": data[dataset]["dataset_id"], "seed": seed, "scenarios": list(selected)}
        result.series.append(series)
        for name in selected:
            if name not in scenarios:
                raise ValueError(f"{path}.scenarios: unknown scenario {name!r}")
            protocol, variants = resolve_scenario(scenarios[name], dataset=data[dataset],
                                                  seed=seed, path=f"scenarios.{name}")
            result.add_comparison(series, name, protocol, variants)
            used_scenarios.add(name)
    _unique_names([entry["name"] for entry in result.series], "series.name")
    for name in scenarios.keys() - used_scenarios:
        raise ValueError(f"scenarios.{name}: unused scenario has no series/dataset binding")
    return _with_execution_readiness(result.document())
