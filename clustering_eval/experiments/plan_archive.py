"""Import the explicitly supported historical paper profile without running its code."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .archive_inputs import ArchiveInputs, INPUTS_SHA256, PROFILE, REPRODUCE, dataset_inputs, partitions_inputs, require
from .archive_protocol import resolve_series
from .plan_identity import scientific_id


@dataclass
class HistoricalPlan:
    source: dict
    resolved: dict


def _archive_path(root: Path, plan_dir: Path) -> str:
    try:
        return Path(os.path.relpath(root, plan_dir)).as_posix()
    except ValueError:  # Windows cannot express a relative path across drive letters.
        return root.as_posix()


def _read_archive(root: Path, base: Path, source_id: str | None) -> HistoricalPlan:
    archive = ArchiveInputs(root)
    manifest = archive.manifest
    reproduce = {}
    for name in REPRODUCE:
        relative = f"reproduce/{name}"
        archive.read(relative)
        reproduce[relative] = archive.checksum(relative)
    code = archive.json("reproduce/source_code_verification.json")
    require(code["source_head"] == manifest["source_head"]
            and code["working_tree_patch_sha256"] == reproduce["reproduce/source_changes.patch"],
            "reproduce/source_code_verification.json", "historical code provenance disagrees with manifest")
    implementation = dict(source_head=code["source_head"], snapshot_sha256=reproduce["reproduce/source_snapshot.zip"],
                          patch_sha256=code["working_tree_patch_sha256"], worker_sha256=reproduce["reproduce/worker.py"],
                          prepare_sha256=reproduce["reproduce/prepare.py"], environment_sha256=reproduce["reproduce/environment.json"],
                          runner_sha256=reproduce["reproduce/run_persistent.py"])
    # Import checks the complete join too, but exports no provisional IDs in the editable input document.
    current_source = source_id if source_id is not None else implementation["snapshot_sha256"]
    datasets: dict = {}
    inputs: dict = {}
    scenarios: dict = {}
    series, comparisons, jobs = [], [], []
    execution = None
    for entry in manifest["series"]:
        name, folder, dataset = entry["name"], entry["path"], entry["dataset"]
        require(name not in {row["name"] for row in series}, "manifest.json.series", f"duplicate {name!r}")
        definition = archive.json(f"{folder}/protocol.json")
        if dataset not in datasets:
            record, verification, labels = dataset_inputs(archive, dataset)
            record["dataset_id"] = scientific_id("dataset", {key: record[key] for key in (
                "name", "x_sha256", "y_sha256", "x_dtype", "y_dtype", "n_samples", "n_features", "preparation_seed")})
            datasets[dataset] = record
            inputs[dataset] = verification, labels
        record = datasets[dataset]
        verification, labels = inputs[dataset]
        require(definition["data_verification"] == verification and definition["data_archive_path"] == record["path"]
                and definition["series"] == name and definition["dataset_name"] == dataset and definition["seed"] == entry["seed"]
                and all(definition[key] == record[key] == entry[key] for key in ("n_samples", "n_features", "n_classes")),
                f"{folder}/protocol.json", "data, seed or dimensions disagree with manifest and verified arrays")
        parts_file = f"{folder}/partitions.json"
        parts = partitions_inputs(archive.json(parts_file), labels, definition, parts_file)
        local_comparisons, local_jobs, local_scenarios = resolve_series(
            definition, archive.json(f"{folder}/experiment_plan.json"), parts, archive.json(f"{folder}/report.json"),
            record, folder, implementation, current_source)
        require(len(parts) == 6 and len(local_jobs) == entry["run_count"]
                and len(local_comparisons) == entry["comparison_count"], folder, "series counts disagree with manifest")
        if execution is None:
            execution = definition["execution_resources"]
            scenarios = local_scenarios
        else:
            require(scenarios == local_scenarios and execution == definition["execution_resources"],
                    folder, "historical series do not share declared scenarios and execution conditions")
        series.append(dict(name=name, dataset=dataset, seed=entry["seed"], repetition=definition["repetition"],
                           scenarios=list(local_scenarios), protocol_path=f"{folder}/protocol.json",
                           partition_path=parts_file, plan_path=f"{folder}/experiment_plan.json",
                           report_path=f"{folder}/report.json"))
        comparisons.extend(local_comparisons)
        jobs.extend(local_jobs)
    counts = dict(series=len(series), comparisons=len(comparisons), jobs=len(jobs))
    require(counts == {"series": 9, "comparisons": 207, "jobs": 1620}
            and counts["comparisons"] == manifest["comparison_count"] and counts["jobs"] == manifest["run_count"],
            "manifest.json", "historical matrix does not match the paper profile")
    require(len({job["job_id"] for job in jobs}) == len(jobs) and
            len({cmp["comparison_id"] for cmp in comparisons}) == len(comparisons),
            "historical", "duplicate scientific conditions")
    historical = dict(profile=PROFILE, path=_archive_path(archive.root, base), inputs_sha256=INPUTS_SHA256)
    campaign = dict(name="paper-three-datasets-three-seeds")
    execution = {"profile": "historical_reference", "historical_resources": execution,
                 "historical_timeouts_sec": {"default": 900, "local_gmm": 1800},
                 "readiness": "requires_compute_and_profile_verification"}
    export = {"profile": PROFILE}
    source = dict(format="pyclusteval.plan.v1", campaign=campaign, historical=historical, datasets=datasets,
                  series=series, scenarios=scenarios, execution=execution, export=export)
    resolved = dict(format="pyclusteval.resolved-plan.v1", campaign=campaign, source_id=current_source,
                    historical=dict(historical, implementation=implementation, reproduce_sha256=reproduce,
                                    common_protocol=manifest["common_protocol"]),
                    datasets=list(datasets.values()), series=series, comparisons=comparisons, jobs=jobs,
                    execution=execution, export=export, counts=counts)
    return HistoricalPlan(source, resolved)


def import_archive(archive: Path, *, plan_dir: Path) -> dict:
    """Verify the paper archive and return a source document relative to its intended directory."""
    return _read_archive(Path(archive), Path(plan_dir).resolve(), None).source


def _mismatch(actual: object, expected: object, path: str) -> str | None:
    """Find the first changed, unknown or missing field, including type changes at leaves."""
    if type(actual) is not type(expected):
        return path
    if isinstance(expected, dict):
        for key in (*expected, *(k for k in actual if k not in expected)):
            child = f"{path}.{key}"
            if key not in expected or key not in actual:
                return child
            difference = _mismatch(actual[key], expected[key], child)
            if difference:
                return difference
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            return path
        for index, (left, right) in enumerate(zip(actual, expected)):
            difference = _mismatch(left, right, f"{path}[{index}]")
            if difference:
                return difference
    elif actual != expected:
        return path
    return None


def resolve_historical(document: dict, *, base_dir: Path, source_id: str) -> dict:
    """Reverify referenced inputs and bind the imported scientific conditions to the current source ID."""
    reference = document.get("historical")
    require(isinstance(reference, dict) and isinstance(reference.get("path"), str)
            and bool(reference["path"].strip()), "historical.path", "expected a non-empty archive path")
    require(reference.get("profile") == PROFILE, "historical.profile", "unknown historical profile")
    require(reference.get("inputs_sha256") == INPUTS_SHA256, "historical.inputs_sha256", "unknown input version")
    plan = _read_archive(Path(base_dir) / reference["path"], Path(base_dir).resolve(), source_id)
    # Equivalent spellings/relocation of the archive path do not change its scientific meaning.
    plan.source["historical"]["path"] = reference["path"]
    changed = _mismatch(document, plan.source, "plan")
    if changed:
        raise ValueError(f"{changed}: does not match the linked historical scientific plan")
    return plan.resolved
