"""Verify and measure the three approved cold Dry Bean jobs from the paper archive."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from tempfile import TemporaryDirectory
import time

from clustering_eval.experiments.runner_process import run_owned, worker_env

METHODS = ("Adapted NN-FC", "Adapted FKDC", "fed_gmm_diag_flower")
TOTAL_SECONDS = 1800
CHECKOUT = Path(__file__).resolve().parents[2]
OPERATOR_SCRIPTS = ("tools/campaign_profile/drybean.py", "tools/campaign_profile/observations.py")


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, allow_nan=False, indent=2)
        output.write("\n")


def check_equal(key: str, actual: object, reference: object) -> None:
    if actual != reference:
        raise ValueError(f"Scientific mismatch in {key}; inspect the source and plan before execution")


def preflight(archive_root: Path, out: Path) -> None:
    """Project the ordinary cold jobs onto the inputs consumed by the archived methods."""
    from clustering_eval.application.compute_params import run_parameters
    from clustering_eval.experiments.archive_inputs import ArchiveInputs, dataset_inputs
    from clustering_eval.experiments.prepared import build_inputs
    from clustering_eval.experiments.prepared_plan import select_inputs
    from clustering_eval.experiments.series_plan import checkout_source_id, resolve_document
    from clustering_eval.experiments.source_capture import capture_source_snapshot
    from clustering_eval.experiments.source_archive import verify_source_snapshot

    # Git for Windows may reject deep paths when building the temporary source index.
    with TemporaryDirectory(prefix="profile-source-") as scratch:
        source = capture_source_snapshot(CHECKOUT, Path(scratch) / "source",
                                         reproduction_scripts=OPERATOR_SCRIPTS)
        destination = out / "operator-source"
        shutil.copytree(source.directory, destination)
        operator = verify_source_snapshot(destination, expected_source_id=source.source_id)
    archive = ArchiveInputs(archive_root)
    data, _, _ = dataset_inputs(archive, "dry_bean")
    report = archive.json("drybean1/report.json")
    partition = archive.json("drybean1/partitions.json")["iid"]
    request, = (e["request"] for e in report["experiments"] if e["scenario"] == "iid_full")
    scenario = {k: v for k, v in request.items() if k not in {
        "algorithms", "algorithm_params", "algorithm_params_by_name", "seed", "dataset_name",
        "dp_epsilon", "dp_delta", "dp_clip_norm"}}
    check_equal("series/seed", (request["dataset_name"], request["seed"]), ("dry_bean", 17))
    check_equal("shape/classes", (data["n_samples"], data["n_features"], data["n_classes"]),
                (13611, 16, 7))
    scenario.update(algorithms=list(METHODS), stopping_profile="historical_paper",
                    algorithm_params_by_name={"fed_gmm_diag_flower": {
                        "client_cpus": 1.0, "client_gpus": 0.0, "reg_covar": 1e-6}})
    dataset = {"provider": "npz", "name": "dry_bean",
               "path": str(archive.root / data["path"]), "sha256": data["file_sha256"],
               "x_sha256": data["x_sha256"], "y_sha256": data["y_sha256"],
               "expected_shape": [13611, 16]}
    plan = {"format": "pyclusteval.plan.v1", "campaign": {"name": "drybean-cold",
             "output_dir": "campaign"}, "datasets": {"dry_bean": dataset},
            "scenarios": {"iid_full": scenario}, "series": [{"name": "drybean-cold-17",
            "dataset": "dry_bean", "seed": 17, "scenarios": ["iid_full"]}],
            "execution": {"profile": "cold", "processes": 1, "blas_threads": 1,
                          "timeout_sec": 600, "memory_limit_mb": 6144,
                          "total_time_sec": TOTAL_SECONDS, "max_retries": 0,
                          "failure_policy": "continue"}}
    resolved = resolve_document(plan, base_dir=out, source_id=checkout_source_id())
    comparison, = resolved["comparisons"]
    prepared = build_inputs(**select_inputs(resolved, comparison["comparison_id"], base_dir=out))
    check_equal("IID indices in original order", [a.tolist() for a in prepared.partition],
                partition["indices"])
    checked_jobs = []
    for job in prepared.jobs:
        name = job["algorithm"]
        prior, = (r for r in report["runs"] if r["job"]["scenario"] == "iid_full"
                  and r["job"]["algorithm"] == name)
        check_equal(f"{name} preprocessing", job["preprocessing"], prior["preprocessing"])
        check_equal(f"{name} backend", job["backend"], prior["backend"])
        schedule = [{key: entry[key] for key in ("round", "selected_clients", "successful_clients",
                                                  "dropped_clients")} for entry in prepared.schedule]
        check_equal(f"{name} schedule", schedule, prior["schedule"])
        params, _ = run_parameters(prepared, job, prepared.X_train)
        consumed = {k: v for k, v in params.items()
                    if k not in ("participation_schedule", "_stopping_profile", "_historical_compute")}
        for key, value in consumed.items():
            check_equal(f"{name}.{key}", value, prior["params"][key])
        check_equal(f"{name}.K", consumed["k"], prior["params"]["n_clusters"])
        checked_jobs.append({"algorithm": name, "source_job": prior["job"]["id"],
                             "parameters": consumed, "preprocessing": job["preprocessing"],
                             "backend": job["backend"]})
    write_json(out / "preflight.json", {"source_id": resolved["source_id"], "dataset": dataset,
               "operator_source": {"path": destination.name, "source_id": operator.source_id,
                                   "source_head": operator.source_head},
               "reference": "drybean1/iid_full", "seed": 17, "stopping_profile": "historical_paper",
               "fingerprints": prepared.fingerprints, "ordered_indices_equal": True,
               "round_client_sets_equal": True, "jobs": checked_jobs,
               "differences": ["three selected methods", "Windows cold worker per job",
                               "current source and native execution profile"]})
    write_json(out / "plan.json", plan)


def measure(archive: Path, out: Path, start: float, deadline: float) -> int:
    """Use one outer Job Object at a time, sharing one absolute preparation/execution deadline."""
    from tools.campaign_profile.observations import host, measurements

    env = worker_env(1)
    env["PYTHONPATH"] = str(CHECKOUT)
    write_json(out / "host.json", host(out))
    write_json(out / "budget.json", {"planned_methods": METHODS, "deadline_epoch_utc": deadline,
               "total_sec": TOTAL_SECONDS, "worker_timeout_sec": 600,
               "worker_commit_limit_bytes": 6144 * 1024**2})
    common = dict(cwd=CHECKOUT, env=env, deadline_utc=deadline, memory_limit_mb=None)
    steps = [
        ("preflight", ["tools.campaign_profile.drybean", "preflight", str(archive), str(out / "inputs")]),
        ("run", ["clustering_eval.cli", "series", "run", str(out / "inputs/plan.json"), "--json"]),
    ]
    stages = []
    for stage, argv in steps:
        try:
            observed = run_owned([sys.executable, "-B", "-m", *argv], **common,
                                 stdout_path=out / f"{stage}.out", stderr_path=out / f"{stage}.err",
                                 timeout_sec=max(0., TOTAL_SECONDS - (time.monotonic() - start)))
        except (OSError, ValueError) as error:
            stages.append({"phase": stage, "exit_code": 3, "reason": "cannot_execute",
                           "error": str(error)})
            break
        stages.append({"phase": stage, "exit_code": observed.returncode,
                       "reason": observed.reason, "wall_sec": observed.wall_sec})
        if observed.reason != "exited" or observed.returncode != 0:
            break
    measurement = {"elapsed_sec": time.monotonic() - start, "stages": stages}
    last = stages[-1]
    # Reporting the final durable state reads the journal after the outer tree has drained.
    campaign = out / "inputs" / "campaign"
    if (campaign / "state" / "journal.sqlite").is_file():
        try:
            measurement["campaign"] = measurements(campaign)
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
            measurement["report_error"] = str(error)
    else:
        measurement["planned_without_journal"] = list(METHODS)
    if last["reason"] != "exited":
        measurement["incomplete_reason"] = last["reason"]
    write_json(out / "measurement.json", measurement)
    if measurement.get("report_error") or measurement.get("campaign", {}).get("integrity_errors"):
        return 4
    if last["reason"] != "exited":
        return 3
    return last["exit_code"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "measure"))
    parser.add_argument("archive", type=Path, help="read-only historical experiments root")
    parser.add_argument("out", type=Path, help="fresh destination outside the reference archive")
    args = parser.parse_args()
    start, deadline = time.monotonic(), time.time() + TOTAL_SECONDS
    archive, out = args.archive.resolve(strict=True), args.out.resolve()
    if out.is_relative_to(archive):
        parser.error("destination must be outside the reference archive")
    out.mkdir(parents=True, exist_ok=False)
    if args.action == "preflight":
        preflight(archive, out)
        return 0
    if os.name != "nt":
        parser.error("the Windows Job Object resource profile requires Windows")
    return measure(archive, out, start, deadline)


if __name__ == "__main__":
    raise SystemExit(main())
