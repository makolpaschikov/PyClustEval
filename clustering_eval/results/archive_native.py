"""Assemble native comparisons from already verified worker observations."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path

from ..application.dto import AlgorithmRunReport, CampaignReportRequest, ComparisonReport, PartitionReport
from .archive_data import write_json
from .history_store import HistoryStore


def source_run(candidate: dict, accepted: dict, series_path: str) -> dict:
    """Preserve IDs and times in their original scopes and add root-relative evidence links."""
    worker = candidate["worker"]
    affinity = worker.get("cpu_affinity")
    elapsed = worker.get("elapsed_to_observation_sec")
    return {
        **candidate["source_run"], "worker": worker,
        "started_at": worker["started_at_utc"], "finished_at": worker["finished_compute_at_utc"],
        "seed": candidate["report"]["model_state"]["benchmark"]["seed"],
        "total_wall_sec": elapsed,
        "algorithm_wall_sec": candidate["report"]["model_state"]["diagnostics"]["runtime_algorithm_call_sec"],
        "cpu_affinity": affinity, "client_metrics_origin": "COMPUTE diagnostics from predictions and prepared inputs",
        "job_id": candidate["job_id"], "comparison_id": candidate["comparison_id"],
        "dataset_id": candidate["dataset_id"], "source_id": candidate["source_id"],
        "result_path": accepted["result_path"], "prediction_path": accepted["prediction_path"],
        "source_json_sha256": accepted["result_sha256"], "source_labels_sha256": accepted["labels_sha256"],
        "prediction_file": accepted["prediction_path"].removeprefix(series_path + "/"),
        "field_origins": {"started_at_utc": "COMPUTE execution", "finished_at_utc": "COMPUTE execution",
                          "cpu_affinity": "worker.cpu_affinity" if affinity is not None else "not recorded",
                          "total_wall_sec": "worker.elapsed_to_observation_sec" if elapsed is not None else "not recorded",
                          "input_shape": "prepared training matrix before shape-preserving adapter preprocessing",
                          "worker": "worker process observation", "source_json_sha256": "saved result.json",
                          "source_labels_sha256": "saved labels.npy", "prediction_file": "packaged NPY member"},
    }


def write_history(staging: Path, series_path: str, dataset: dict, comparison: dict, entries: list[dict],
                  archived: list[dict], partition: PartitionReport | None, privacy: dict) -> dict:
    """Write one stable native history directory for a comparison with accepted results."""
    cid = comparison["comparison_id"]
    directory = staging / series_path / "history" / cid
    directory.mkdir()
    results = []
    runs = []
    starts, finishes, logs = [], [], []
    for entry, job in zip(entries, archived, strict=True):
        accepted = job["accepted"]
        if not accepted:
            continue
        candidate = entry["accepted"]["candidate"]
        origin = source_run(candidate, accepted, series_path)
        native = deepcopy(candidate["report"])
        native["model_state"].setdefault("source_run", origin)
        results.append(AlgorithmRunReport(**native))
        runs.append(origin)
        starts.append(datetime.fromisoformat(candidate["worker"]["started_at_utc"]))
        finishes.append(datetime.fromisoformat(candidate["worker"]["finished_compute_at_utc"]))
        logs.extend([f"\n[{job['run_id']} attempt {accepted['attempt_id']}]\n",
                     (staging / accepted["log_path"]).read_text(encoding="utf-8")])
    request = CampaignReportRequest(
        mode=comparison["protocol"]["mode"], dataset_name=dataset["name"],
        algorithms=tuple(r.algorithm for r in results), seed=comparison["seed"], protocol=comparison["protocol"],
    )
    report = ComparisonReport(
        experiment_id=cid, started_at=min(starts), finished_at=max(finishes), request=request,
        dataset_display_name=dataset["name"], n_samples=dataset["n_samples"], n_features=dataset["n_features"],
        results=results, partition=partition, privacy_report=privacy, log_lines=logs,
    )
    # The native CSV schema is owned by HistoryStore. Use its serializer while choosing
    # the stable directory ourselves (save() allocates a new timestamp-based key).
    HistoryStore(directory.parent)._write_csv_atomic(directory / "results.csv", report)
    relative = "history/" + cid
    complete = len(results) == len(entries)
    payload = report.to_dict()
    for result, origin in zip(payload["results"], runs, strict=True):
        result["source_run"] = origin
    payload.update(
        history_directory=relative, comparison_id=cid, complete=complete,
        export_provenance={
            "source_scenario": comparison["scenario"], "series": comparison["series"],
            "source_run_ids": [r["run_id"] for r in runs], "exported_without_rerun": True,
            "interval_origin": "earliest worker start to latest worker compute observation among accepted jobs",
            "timestamp_timezone": "UTC", "plan_path": series_path + "/experiment_plan.json",
            "privacy_scope": "comparison journal including unsuccessful attempts",
        },
    )
    write_json(directory / "report.json", payload)
    (directory / "execution.log").write_text("".join(logs), encoding="utf-8")
    return dict(comparison_id=cid, scenario=comparison["scenario"], history_key=cid,
                history_report=relative + "/report.json", history_report_path=series_path + "/" + relative + "/report.json",
                request=request.to_dict(), complete=complete)
