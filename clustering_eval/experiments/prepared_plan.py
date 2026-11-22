"""Recheck the selected resolved PLAN group against its input bytes and protocol."""
from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import numpy as np

from .archive_inputs import (
    ArchiveInputs, INPUTS_SHA256, PROFILE, REPRODUCE, canonical, dataset_inputs, partitions_inputs, require,
)
from .archive_protocol import resolve_series
from .plan_data import _npz_input, _registry_input
from .plan_identity import scientific_id
from .series_plan import RESOLVED_FORMAT, ResolvedCampaign, execution_settings


def _one(rows: list[dict], key: str, value: str) -> dict:
    found = [row for row in rows if row[key] == value]
    if len(found) != 1:
        raise ValueError(f"Expected one {key}={value!r}, found {len(found)}")
    return found[0]


def _match(actual: object, expected: object, path: str) -> None:
    require(canonical(actual) == canonical(expected), path, "differs from verified inputs or effective protocol")


def _ordinary_data(record: dict, base_dir: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    spec = {key: record[key] for key in ("provider", "name")}
    if record["preparation_seed"] is not None:
        spec["preparation_seed"] = record["preparation_seed"]
    if record["provider"] == "registry":
        spec["params"] = dict(record["params"])
        if "input_path" in record:
            spec["params"]["path"] = record["input_path"]
        X, y, params, origin, seed = _registry_input(spec, base_dir, "dataset")
    elif record["provider"] == "npz":
        location = (base_dir / record["input_path"]).resolve()
        X, y, digest = _npz_input(location, "dataset")
        params, seed = {}, record["preparation_seed"]
        origin = {"input_path": str(location), "file_sha256": digest}
    else:
        raise ValueError(f"Unsupported dataset provider {record['provider']!r}")
    if X.ndim != 2 or y.shape != (len(X),) or y.dtype.kind not in "buifSU":
        raise ValueError("Unexpected X/y dimensions or label type")
    if y.dtype.kind == "f" and not np.isfinite(y).all():
        raise ValueError("Reference labels contain a nonfinite value")
    scientific = dict(provider=record["provider"], name=record["name"], params=params, preparation_seed=seed,
                      n_samples=len(X), n_features=X.shape[1], n_classes=len(np.unique(y)),
                      x_sha256=sha256(np.ascontiguousarray(X).view(np.uint8)).hexdigest(),
                      y_sha256=sha256(np.ascontiguousarray(y).view(np.uint8)).hexdigest(),
                      x_dtype=X.dtype.str, y_dtype=y.dtype.str)
    identity = sha256(canonical(["pyclusteval.dataset.v1", scientific])).hexdigest()
    _match(record, dict(scientific, **origin, dataset_id=identity, key=record["key"]), "dataset")
    return X, y, spec


def _scenario_variants(cmp: dict, jobs: list[dict], dataset: dict) -> tuple[dict, list[dict]]:
    """Replay PLAN's validation with one grid point at a time, retaining group-wide constraints."""
    from ..application.dto import RunRequest
    from .plan_protocol import resolve_scenario

    protocol = cmp["protocol"]
    controls = {field.name for field in fields(RunRequest)} | {"stopping_profile"}
    scene = {k: v for k, v in protocol.items() if k in controls}
    if protocol["cluster_count_source"] != "user":
        scene.pop("target_clusters", None)
    scene["algorithms"] = list(dict.fromkeys(job["algorithm"] for job in jobs))
    result = []
    for job in jobs:
        name = job["algorithm"]
        parameters = job["effective_params"]
        override, grid = {}, {}
        for key, source in job["parameter_sources"].items():
            if key == "n_clusters" and "k" in parameters:
                continue
            if source == "grid":
                grid[key] = [parameters[key]]
            elif source == "override":
                override[key] = parameters[key]
        subset = dict(scene, algorithm_params_by_name={name: override}, grid={name: grid})
        shared, variants = resolve_scenario(subset, dataset=dataset, seed=cmp["seed"], path="selected")
        result.append(_one(variants, "algorithm", name))
    return shared, result


def _legacy_variant(cmp: dict, jobs: list[dict], dataset: dict, spec: dict,
                    base_dir: Path, source_id: str) -> tuple[dict, list[dict]]:
    """Reuse the actual legacy resolver for the selected case, including alias priority."""
    from .plan_legacy import resolve_legacy

    require(len(jobs) == 1, "legacy", "expected one job")
    job, protocol = jobs[0], cmp["protocol"]
    overrides = {k: job["effective_params"][k] for k, v in job["parameter_sources"].items()
                 if v == "legacy_override"}
    case = dict(series=cmp["series"], algorithm=job["algorithm"], algorithm_params=overrides,
                num_clients=protocol["num_clients"], partition_mode=protocol["partition_mode"],
                dirichlet_alpha=protocol["dirichlet_alpha"], preparation_seed_source=job["preparation_seed_source"])
    doc = dict(format="pyclusteval.plan.v1", campaign={"name": "selected"}, datasets={dataset["key"]: spec},
               series=[dict(name=cmp["series"], dataset=dataset["key"], seed=cmp["seed"])],
               legacy=dict(profile=protocol["compatibility_profile"], metrics=protocol["metrics"], jobs=[case]))
    resolved = resolve_legacy(doc, base_dir=base_dir, source_id=source_id)
    _match(dataset, resolved["datasets"][0], "legacy.dataset")
    bindings = {"job_id", "comparison_id", "series", "run_id", "execution_profile"}
    variant = {key: value for key, value in resolved["jobs"][0].items() if key not in bindings}
    return resolved["comparisons"][0]["protocol"], [variant]

def _historical(plan: dict, cmp: dict, jobs: list[dict], series: dict, dataset: dict, base_dir: Path) -> dict:
    ref = plan["historical"]
    require(ref["profile"] == PROFILE and ref["inputs_sha256"] == INPUTS_SHA256,
            "historical", "unsupported archive profile")
    archive = ArchiveInputs(base_dir / ref["path"])
    entry = _one(archive.manifest["series"], "name", series["name"])
    name, folder = entry["dataset"], entry["path"]
    record, verified, labels = dataset_inputs(archive, name)
    record["dataset_id"] = scientific_id("dataset", {key: record[key] for key in
        ("name", "x_sha256", "y_sha256", "x_dtype", "y_dtype", "n_samples", "n_features", "preparation_seed")})
    _match(record, dataset, "archive.dataset")
    definition = archive.json(f"{folder}/protocol.json")
    parts = archive.json(f"{folder}/partitions.json")
    checked = partitions_inputs(parts, labels, definition, f"{folder}/partitions.json")
    # The pinned archive catalog authenticates the implementation files and series metadata.
    pins = {k: archive.checksum("reproduce/" + filename) for k, filename in {
        "snapshot_sha256": "source_snapshot.zip", "patch_sha256": "source_changes.patch",
        "worker_sha256": "worker.py", "prepare_sha256": "prepare.py", "runner_sha256": "run_persistent.py",
        "environment_sha256": "environment.json"}.items()}
    for filename in REPRODUCE:
        archive.read("reproduce/" + filename)
    _match(ref["reproduce_sha256"], {"reproduce/" + name: archive.checksum("reproduce/" + name)
                                    for name in REPRODUCE}, "archive.reproduce_sha256")
    _match(ref["common_protocol"], archive.manifest["common_protocol"], "archive.common_protocol")
    pins["source_head"] = archive.manifest["source_head"]
    _match(ref["implementation"], pins, "archive.implementation")
    cmps, rows, scenarios = resolve_series(definition, archive.json(f"{folder}/experiment_plan.json"), checked,
        archive.json(f"{folder}/report.json"), dataset, folder, pins, plan["source_id"])
    _match(series, dict(name=entry["name"], dataset=name, seed=entry["seed"], repetition=definition["repetition"],
                        scenarios=list(scenarios), protocol_path=f"{folder}/protocol.json",
                        partition_path=f"{folder}/partitions.json", plan_path=f"{folder}/experiment_plan.json",
                        report_path=f"{folder}/report.json"), "archive.series")
    _match(cmp, _one(cmps, "comparison_id", cmp["comparison_id"]), "archive.comparison")
    _match(jobs, [j for j in rows if j["comparison_id"] == cmp["comparison_id"]], "archive.jobs")
    location = cmp["provenance"]["partition"]
    partition = parts[location.split("#", 1)[1]]["indices"] if location else None
    with np.load(BytesIO(archive.read(record["path"])), allow_pickle=False) as data:
        X = data["X"]
    public = verified["metadata"] if name == "synthetic_anisotropic" else verified["dp_public_preprocessing"]
    return dict(X=X, y=labels, partition=partition, public_reference=public)


def select_inputs(plan: dict, comparison_id: str, *, base_dir: Path) -> dict:
    """Resolve and authenticate only the data and scientific rows needed by a single comparison."""
    from .plan_io import integer

    try:
        require(plan["format"] == RESOLVED_FORMAT, "format", "unsupported resolved-plan schema")
        cmp = _one(plan["comparisons"], "comparison_id", comparison_id)
        jobs = [job for job in plan["jobs"] if job["comparison_id"] == comparison_id]
        require(bool(jobs), "jobs", "comparison is empty")
        series = _one(plan["series"], "name", cmp["series"])
        integer(cmp["seed"], "comparison.seed", 0, 2**32-1)
        require(series["seed"] == cmp["seed"] and cmp["scenario"] in series["scenarios"],
                "series", "inconsistent seed or scenario")
        if "historical" in plan:
            dataset = _one(plan["datasets"], "dataset_id", cmp["dataset_id"])
            data = _historical(plan, cmp, jobs, series, dataset, base_dir)
        else:
            dataset = _one(plan["datasets"], "key", series["dataset"])
            require(series["dataset_id"] == dataset["dataset_id"] == cmp["dataset_id"],
                    "comparison", "dataset_id mismatch")
            X, y, spec = _ordinary_data(dataset, base_dir)
            if "compatibility_profile" in cmp["protocol"]:
                shared, variants = _legacy_variant(cmp, jobs, dataset, spec, base_dir, plan["source_id"])
            else:
                shared, variants = _scenario_variants(cmp, jobs, dataset)
            reconstructed = ResolvedCampaign(plan["source_id"], {}, [], execution_settings(plan["execution"]), {})
            reconstructed.add_comparison(series, cmp["scenario"], shared, variants)
            _match(cmp, reconstructed.comparisons[0], "comparison")
            _match(jobs, reconstructed.jobs, "jobs")
            data = dict(X=X, y=y)
        return dict(data, dataset=dataset, comparison=cmp, jobs=jobs, source_id=plan["source_id"])
    except (KeyError, IndexError, TypeError, OSError) as exc:
        raise ValueError(f"Invalid resolved comparison {comparison_id}: {exc}") from exc
