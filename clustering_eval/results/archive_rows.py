"""Portable results rows, original attempt evidence and lossless prediction packages."""
from __future__ import annotations

import csv
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from ..application.dto import PartitionReport
from ..experiments.runner_reader import attempt_directory
from ..experiments.runner_state import IntegrityError, checked_path
from .archive_data import verified_bytes

METRICS = ("ari", "ami", "nmi", "silhouette", "davies_bouldin", "calinski_harabasz")
RESULT_COLUMNS = (
    "series", "dataset", "seed", "scenario", "run_id", "algorithm", "display_algorithm",
    "backend", "status", "n_samples", "n_features", "partition_mode", "alpha",
    "partition_fingerprint", "class_js_divergence_weighted_bits", "client_size_cv",
    "active_data_fingerprint", "participation_rate", "dropout_rate", "privacy_mode",
    "epsilon", "runtime_sec", "algorithm_wall_sec", "communication_bytes", "rounds",
    "cluster_count", "noise_fraction", "history_length", "prediction_hash", *METRICS,
    "started_at", "finished_at", "job_id", "comparison_id", "attempt_id", "group_id",
)


def write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def results_row(job: dict, dataset: dict, comparison: dict, candidate: dict,
                partition: PartitionReport | None, group: str) -> dict:
    report = candidate["report"]
    state = report["model_state"]
    diag = state["diagnostics"]
    worker = candidate["worker"]
    protocol = comparison["protocol"]
    heterogeneity = partition.heterogeneity if partition else {}
    return dict(
        series=job["series"], dataset=dataset["name"], seed=comparison["seed"],
        scenario=comparison["scenario"], run_id=job["run_id"], algorithm=job["algorithm"],
        display_algorithm=report["algorithm"], backend=report["backend"], status="ok",
        n_samples=dataset["n_samples"], n_features=dataset["n_features"],
        partition_mode=partition.mode if partition else None,
        alpha=partition.dirichlet_alpha if partition else None,
        partition_fingerprint=partition.fingerprint if partition else None,
        class_js_divergence_weighted_bits=heterogeneity.get("class_js_divergence_weighted_bits"),
        client_size_cv=heterogeneity.get("size_cv"),
        active_data_fingerprint=state["benchmark"].get("active_data_fingerprint"),
        participation_rate=protocol.get("participation_rate") if partition else None,
        dropout_rate=protocol.get("dropout_rate") if partition else None,
        privacy_mode=protocol["privacy_mode"], epsilon=state["benchmark"].get("dp_epsilon"),
        runtime_sec=report["runtime_sec"], algorithm_wall_sec=diag["runtime_algorithm_call_sec"],
        communication_bytes=report["communication_bytes"], rounds=report["rounds"],
        cluster_count=diag["cluster_count_excluding_noise"], noise_fraction=diag["noise_fraction"],
        history_length=len(report["history"]), prediction_hash=diag["prediction_hash"],
        **{key: report[key] for key in METRICS},
        started_at=worker["started_at_utc"], finished_at=worker["finished_compute_at_utc"],
        job_id=job["job_id"], comparison_id=comparison["comparison_id"],
        attempt_id=candidate["attempt_id"], group_id=group,
    )


def transfer_logs(campaign: Path, staging: Path, folder: Path, attempt: dict,
                  expected: dict | None) -> dict:
    """Keep closed streams' original bytes; an active stream has no final observed length."""
    records = {}
    for kind in ("stdout", "stderr"):
        item = dict(status="unavailable", path=None, sha256=None, bytes=None)
        records[kind] = item
        if attempt["status"] == "running":
            item.update(status="in_progress", reason="Stream was open at the journal snapshot")
            continue
        name = kind + ".log"
        source = checked_path(attempt_directory(campaign, attempt["attempt_id"]), name)
        if expected is not None:
            data = verified_bytes(source, expected[name]["sha256"])
            if len(data) != expected[name]["bytes"]:
                raise IntegrityError(f"Incorrect log length: {source}")
        else:
            try:
                data = source.read_bytes()
            except FileNotFoundError:
                item["reason"] = "No stream file was observed for the unsuccessful attempt"
                continue
        # The original worker or a child may have emitted bytes in a non-UTF-8 encoding.
        target = folder / "logs" / "streams" / (attempt["attempt_id"] + "-" + kind + ".bin")
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(data)
        item.update(status="available", path=target.relative_to(staging).as_posix(),
                    sha256=sha256(data).hexdigest(), bytes=len(data),
                    origin="accepted_stream" if expected is not None else "observed_unsuccessful_stream")
    return records


def export_job(campaign: Path, staging: Path, folder: Path, entry: dict,
               filename: str, history_path: str | None) -> dict:
    job = entry["job"]
    accepted = entry["accepted"]
    archived_attempts = []
    for attempt in entry["attempts"]:
        expected = accepted["logs"] if accepted and accepted["attempt_id"] == attempt["attempt_id"] else None
        streams = transfer_logs(campaign, staging, folder, attempt, expected)
        old_paths = {key: attempt[key] for key in ("directory", "stdout", "stderr")}
        record = {key: value for key, value in attempt.items() if key not in old_paths}
        archived_attempts.append(dict(record, original_paths=old_paths, archive_logs=streams))
    reason = entry["reason"]
    reason_source = "journal"
    if not reason and entry["status"] in ("pending", "running"):
        reason = "Not yet assigned" if not archived_attempts else "Attempt in progress at snapshot"
        reason_source = "derived_from_job_status"
    result = dict(job_id=job["job_id"], comparison_id=job["comparison_id"], series=job["series"],
                  run_id=job["run_id"], status=entry["status"], reason=reason,
                  reason_source=reason_source, attempts=archived_attempts, accepted=None)
    if not accepted:
        return result
    cid = accepted["attempt_id"]
    candidate = accepted["candidate"]
    source = attempt_directory(campaign, cid)
    result_path = folder / "source_results" / (filename + ".json")
    original = verified_bytes(checked_path(source, "result.json"), candidate["result"]["sha256"])
    result_path.write_bytes(original)
    prediction = folder / "predictions" / (filename + "-labels.npz")
    labels = verified_bytes(checked_path(source, "labels.npy"), candidate["labels"]["sha256"])
    with ZipFile(prediction, "x", compression=ZIP_DEFLATED) as bundle:
        bundle.writestr("labels.npy", labels)
    path = folder / "logs" / (filename + ".log")
    streams = next(a["archive_logs"] for a in archived_attempts if a["attempt_id"] == cid)
    with path.open("w", encoding="utf-8", newline="") as stream:
        for name, item in streams.items():
            stream.write(f"[{name}]\n")
            stream.write((staging / item["path"]).read_bytes().decode("utf-8", errors="backslashreplace"))
            stream.write("\n")
    result["accepted"] = dict(
        attempt_id=cid, compute_attempt_id=candidate["compute_attempt_id"],
        result_path=result_path.relative_to(staging).as_posix(), result_sha256=candidate["result"]["sha256"],
        prediction_path=prediction.relative_to(staging).as_posix(), labels_sha256=candidate["labels"]["sha256"],
        labels_dtype=candidate["labels"]["dtype"], labels_shape=candidate["labels"]["shape"],
        candidate_sha256=candidate["manifest_sha256"], history_report=history_path,
        log_path=path.relative_to(staging).as_posix(),
    )
    return result
