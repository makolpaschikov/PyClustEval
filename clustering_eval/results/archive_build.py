"""Build the scientific contents of a portable campaign archive in empty staging."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re

from ..application.compute_report import partition_summary
from ..experiments.prepared import PreparedComparison
from ..experiments.runner_reader import read_campaign
from ..experiments.runner_state import IntegrityError, STATUSES, encode
from .archive_data import (
    DirectoryNames, copy_reproduction, read_comparison, required_input, write_dataset, write_json, write_replay,
)
from .archive_native import source_run, write_history
from .archive_rows import METRICS, RESULT_COLUMNS, export_job, results_row, write_csv

FORMAT = "pyclusteval.campaign-archive.v1"
ROOT_NAMES = ("datasets", "reproduce", "README.md", "merge_history.py", "manifest.json",
              "all_results.csv", "aggregate_by_dataset.csv", "checksums.json", "verification.json")


def _datasets(output: Path, plan: dict) -> dict[str, dict]:
    (output / "datasets").mkdir()
    datasets = {}
    names = DirectoryNames()
    for item in plan["datasets"]:
        key = item["dataset_id"]
        if key not in datasets:
            directory = "datasets/" + names.allocate(item["name"], key)
            (output / directory).mkdir()
            datasets[key] = dict(dataset_id=key, path=directory, keys=[], dataset=item,
                                 checked_comparisons=[], available=False,
                                 reason="No completed preparation for this dataset in the journal snapshot")
        datasets[key]["keys"].append(item["key"])
    return datasets


def _series(staging: Path, series: dict, name: str, dataset: dict) -> dict:
    folder = staging / name
    folder.mkdir()
    for child in ("history", "predictions", "logs", "source_results"):
        (folder / child).mkdir()
    return dict(**series, path=name, dataset_name=dataset["name"], n_samples=dataset["n_samples"],
                n_features=dataset["n_features"], n_classes=dataset["n_classes"])


def _partition(prepared: PreparedComparison | None) -> tuple:
    if prepared is None or prepared.partition is None:
        return None, None
    summary = partition_summary(prepared)
    record = dict(indices=[a.tolist() for a in prepared.partition], sizes=summary.client_sample_counts,
                  class_counts=summary.client_class_counts, fingerprint=summary.fingerprint,
                  heterogeneity=summary.heterogeneity, mode=summary.mode, alpha=summary.dirichlet_alpha,
                  schedule=prepared.schedule)
    return summary, record


def _collection_run(candidate: dict, archived: dict, row: dict, series_path: str,
                    prepared: PreparedComparison) -> dict:
    accepted = archived["accepted"]
    origin = source_run(candidate, accepted, series_path)
    bench = candidate["report"]["model_state"]["benchmark"]
    job = dict(candidate["job"], id=row["run_id"], scenario=row["scenario"], seed=row["seed"])
    if prepared.comparison["protocol"]["mode"] == "local":
        job["local"] = True
    else:
        job.update(partition=prepared.comparison["comparison_id"],
                   participation=row["participation_rate"], dropout=row["dropout_rate"])
    if row["epsilon"] is not None:
        job["epsilon"] = row["epsilon"]
    return dict(row, id=row["run_id"], job=job, params=bench["effective_params"],
                input_shape=list(prepared.X_train.shape), partition_hash=row["partition_fingerprint"],
                client_sizes=[len(indices) for indices in prepared.partition] if prepared.partition else [],
                total_wall_sec=origin["total_wall_sec"], cpu_affinity=origin["cpu_affinity"],
                metrics={m: row[m] for m in METRICS}, source_run=origin,
                history_report=accepted["history_report"].removeprefix(series_path + "/"),
                history_report_path=accepted["history_report"], prediction_file=origin["prediction_file"],
                log_path=accepted["log_path"], schedule=prepared.schedule,
                preprocessing=bench["preprocessing"], execution_profile=candidate["job"]["execution_profile"])


def _export_series(campaign: Path, staging: Path, series: dict, comparisons: list[dict],
                   snapshot: dict, entries: dict[str, list[dict]], groups: dict[str, str],
                   dataset_record: dict) -> tuple[list[dict], list[dict], list[dict]]:
    from .archive_science import privacy_report

    path = series["path"]
    folder = staging / path
    dataset = dataset_record["dataset"]
    rows, jobs, observations = [], [], []
    experiment_plan, runs, experiments = [], [], []
    partitions = {}
    filenames = DirectoryNames()
    for comparison in comparisons:
        cid = comparison["comparison_id"]
        batch = entries[cid]
        binding = snapshot["preparations"].get(cid)
        status = snapshot["preparation_status"].get(cid, "unprepared")
        prepared = None
        if binding is not None:
            prepared = read_comparison(campaign, snapshot["plan"], comparison, [e["job"] for e in batch], binding)
            write_dataset(staging, dataset_record, prepared)
        part, partitions[cid] = _partition(prepared)
        accepted_count = sum(e["accepted"] is not None for e in batch)
        release = None if binding is None else binding["input_release_id"]
        prepared_privacy = None if prepared is None else prepared.privacy_report
        privacy = privacy_report(comparison, batch, status, release, input_privacy_report=prepared_privacy)
        hist = path + "/history/" + cid + "/report.json" if accepted_count else None
        observed_jobs = []
        for entry in batch:
            job = entry["job"]
            filename = filenames.allocate(job["run_id"], job["job_id"])
            archived = export_job(campaign, staging, folder, entry, filename, hist)
            archived["group_id"] = groups[job["job_id"]]
            observed_jobs.append(archived)
            accepted = archived["accepted"]
            experiment_plan.append(dict(job, id=job["run_id"], status=archived["status"],
                                        reason=archived["reason"], group_id=archived["group_id"],
                                        accepted_attempt_id=accepted["attempt_id"] if accepted else None))
            if accepted:
                if prepared is None:
                    raise IntegrityError(f"Accepted job without a recorded preparation: {job['job_id']}")
                candidate = entry["accepted"]["candidate"]
                row = results_row(job, dataset, comparison, candidate, part, archived["group_id"])
                rows.append(row)
                runs.append(_collection_run(candidate, archived, row, path, prepared))
        jobs.extend(observed_jobs)
        if hist:
            experiments.append(write_history(staging, path, dataset, comparison, batch, observed_jobs, part, privacy))
        observations.append(dict(
            comparison_id=cid, series=series["name"], scenario=comparison["scenario"],
            dataset_id=dataset["dataset_id"], planned=len(batch), accepted=accepted_count,
            complete=accepted_count == len(batch), preparation_status=status, preparation=binding,
            prepared_privacy_report=prepared_privacy, history_report=hist, privacy_report=privacy,
        ))
    totals = Counter(j["status"] for j in jobs)
    series.update(planned=len(jobs), accepted=len(rows), complete=len(rows) == len(jobs),
                  run_count=len(rows), comparison_count=len(experiments),
                  planned_comparisons=len(comparisons), totals={s: totals[s] for s in STATUSES})
    protocol = dict(format="pyclusteval.series-protocol.v1", series=series["name"],
                    dataset_name=dataset["name"], dataset_id=dataset["dataset_id"], seed=series["seed"],
                    execution=snapshot["plan"]["execution"], comparisons=comparisons)
    write_json(folder / "protocol.json", protocol)
    write_json(folder / "experiment_plan.json", experiment_plan)
    write_json(folder / "partitions.json", partitions)
    write_json(folder / "report.json", dict(
        format="pyclusteval.benchmark-series.v1", series=series["name"], dataset_name=dataset["name"],
        seed=series["seed"], n_samples=dataset["n_samples"], n_features=dataset["n_features"],
        n_classes=dataset["n_classes"], run_count=len(rows), comparison_count=len(experiments),
        complete=series["complete"], planned=len(jobs), protocol=protocol, experiments=experiments, runs=runs,
    ))
    write_csv(folder / "results.csv", RESULT_COLUMNS, rows)
    return rows, jobs, observations


def build_archive(campaign: Path, staging: Path) -> dict:
    """Build from one reader snapshot. Caller owns staging, final verification and publication."""
    from . import archive_history
    from .archive_science import AGGREGATE_COLUMNS, aggregate_rows, group_ids

    root = Path(campaign).resolve()
    output = Path(staging)
    if output.is_symlink() or output.is_junction() or not output.is_dir() or any(output.iterdir()):
        raise ValueError(f"Expected an empty staging directory: {output}")
    observed_start = datetime.now(timezone.utc)
    with required_input(root, "Reading campaign snapshot"):
        snapshot = read_campaign(root, propagate_io_errors=True)
    observed_end = datetime.now(timezone.utc)
    if snapshot["format"] != "pyclusteval.campaign-reader.v1":
        raise ValueError(f"Unknown campaign reader format: {snapshot['format']}")
    if snapshot["integrity_errors"]:
        raise IntegrityError("; ".join(snapshot["integrity_errors"]))
    plan = snapshot["plan"]
    meta = copy_reproduction(root, output / "reproduce", snapshot)
    datasets = _datasets(output, plan)
    groups = group_ids(plan)
    batches = defaultdict(list)
    for entry in snapshot["jobs"]:
        batches[entry["job"]["comparison_id"]].append(entry)
    by_series = defaultdict(list)
    for comparison in plan["comparisons"]:
        if not re.fullmatch(r"[0-9a-f]{64}", comparison["comparison_id"]):
            raise IntegrityError("Invalid comparison identifier in saved plan")
        by_series[comparison["series"]].append(comparison)
    root_names = DirectoryNames(ROOT_NAMES)
    series_records = []
    rows_by_job, jobs_by_id, comparisons_by_id = {}, {}, {}
    for series in plan["series"]:
        dataset = datasets[series["dataset_id"]]
        name = root_names.allocate(series["name"], series["name"])
        record = _series(output, series, name, dataset["dataset"])
        series_records.append(record)
        rows, jobs, comparisons = _export_series(root, output, record, by_series[series["name"]],
                                                  snapshot, batches, groups, dataset)
        rows_by_job.update((r["job_id"], r) for r in rows)
        jobs_by_id.update((j["job_id"], j) for j in jobs)
        comparisons_by_id.update((c["comparison_id"], c) for c in comparisons)
    # Migrated plans can interleave series. Materialize global views in their original order.
    all_jobs = [jobs_by_id[j["job_id"]] for j in plan["jobs"]]
    all_rows = [rows_by_job[j["job_id"]] for j in all_jobs if j["accepted"] is not None]
    all_comparisons = [comparisons_by_id[c["comparison_id"]] for c in plan["comparisons"]]
    for record in datasets.values():
        write_json(output / record["path"] / "verification.json", record)
    write_csv(output / "all_results.csv", RESULT_COLUMNS, all_rows)
    write_csv(output / "aggregate_by_dataset.csv", AGGREGATE_COLUMNS, aggregate_rows(plan, all_rows))
    write_replay(output, meta, list(datasets.values()))
    (output / "merge_history.py").write_bytes(Path(archive_history.__file__).read_bytes())
    summary = snapshot["summary"]
    identity = [meta["source_id"], meta["created"], meta["plan_sha256"], meta["resolved_sha256"]]
    manifest = dict(
        format=FORMAT, campaign=plan["campaign"]["name"], source_id=plan["source_id"],
        campaign_id=sha256(encode(identity).encode("utf-8")).hexdigest(),
        campaign_created_utc_epoch=meta["created"], original_plan_path="reproduce/" + meta["plan_file"],
        plan_sha256=meta["plan_sha256"], resolved_sha256=meta["resolved_sha256"],
        source_record_sha256=meta["source_record_sha256"],
        complete=summary["planned"] == len(all_rows), planned=summary["planned"], totals=summary["totals"],
        run_count=len(all_rows), comparison_count=sum(c["history_report"] is not None for c in all_comparisons),
        series_count=len(series_records), series=series_records, datasets=list(datasets.values()),
        comparisons=all_comparisons, jobs=all_jobs, sessions=snapshot["sessions"],
        observation=dict(started_at_utc=observed_start.isoformat(), finished_at_utc=observed_end.isoformat(),
                         boundary="Committed journal snapshot within this interval",
                         supervisor_active=summary["supervisor_active"], stop_reason=summary["stop_reason"]),
        privacy=dict(scope="recorded preparations and attempts in this campaign",
                     end_to_end_report_is_dp=False, global_privacy_bound=None,
                     reason="Raw research data, labels and diagnostics are included; outside releases are unknown."),
    )
    write_json(output / "manifest.json", manifest)
    (output / "README.md").write_text(
        "# Local experiment campaign\n\n"
        f"Campaign: {manifest['campaign']}\n\n"
        f"Accepted {len(all_rows)} of {summary['planned']} planned jobs. "
        "manifest.json lists every job, attempt, completion status and reason. "
        "Use its series and dataset path mappings to locate reports and arrays. Paths with "
        "the suffix _path and the manifest's history_report entries are relative to this "
        "archive. The series collection's history_report, prediction_file and native "
        "history_directory are relative to that series. Original paths inside plans, "
        "requests, worker evidence and runtime are provenance.\n\n"
        "all_results.csv contains one row per accepted job. aggregate_by_dataset.csv "
        "describes comparable planned groups; each statistic uses the accepted, finite "
        "observations of that measure. Join its group_id with manifest.jobs or a series' "
        "experiment_plan.json to see every planned job, its status and its reason. For a pending "
        "job without its own journal reason, reason_source identifies the derived status explanation. "
        "The manifest.sessions list records each session's stop_reason separately. Blank cells are undefined "
        "or unavailable. "
        "Worker timestamps are UTC. Round counts, logical payloads and empty histories "
        "have their recorded meanings. Comparisons distinguish known releases from uncertain "
        "outcomes across attempts. This research archive includes raw data and has no "
        "end-to-end differential privacy guarantee.\n\n"
        "Run `python -m clustering_eval.cli series verify <archive-dir>` after transfer. "
        "Use `python merge_history.py --into <history-dir>` to import native reports. "
        "See reproduce/README.md for replay and its limits.\n", encoding="utf-8")
    return manifest
