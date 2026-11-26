"""Durable results of one campaign worker. All member paths are attempt-relative."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import datetime, timedelta
from hashlib import file_digest, sha256
from io import BytesIO
import os
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, BinaryIO
from uuid import UUID

import numpy as np

from ..application.dto import AlgorithmRunReport
from ..metrics.diagnostics import array_fingerprint
from ..results.history_store import _strict_json_value
from .archive_inputs import canonical, document

if TYPE_CHECKING:
    from ..application.compute import JobExecution

CANDIDATE = "candidate.json"
FAILURE = "failure.json"
FORMAT = "pyclusteval.attempt.v1"
REQUEST_FIELDS = ("attempt_id", "job_id", "comparison_id", "source_id", "dataset_id",
                  "fingerprints", "input_release_id", "n_samples", "privacy_mode", "job",
                  "descriptor_sha256", "reservation_sha256")


def _directory(directory: Path) -> None:
    if not S_ISDIR(directory.lstat().st_mode) or directory.is_junction():
        raise ValueError(f"Invalid attempt directory: {directory}")


def _read(directory: Path, name: str) -> bytes:
    # Callers choose literal member names; never open a path supplied by a manifest.
    path = directory / name
    mode = path.lstat().st_mode
    if not S_ISREG(mode) or path.is_junction():
        raise ValueError(f"Invalid attempt member: {path}")
    return path.read_bytes()


def _object(raw: bytes, name: str) -> dict:
    value = document(raw, name)
    if not isinstance(value, dict):
        raise ValueError(f"{name}: expected an object")
    canonical(value)  # Also catch exponent overflow to infinity.
    return value


def _match(value: Any, expected: Any, location: str) -> None:
    if canonical(value) != canonical(expected):
        raise ValueError(f"Inconsistent {location}")


def read_request(directory: Path) -> dict:
    """Load the supervisor's prelaunch request from an existing attempt directory."""
    _directory(directory)
    request = _object(_read(directory, "request.json"), "request.json")
    if any(key not in request for key in REQUEST_FIELDS):
        raise ValueError("Incomplete attempt request")
    if not isinstance(request["attempt_id"], str) or UUID(request["attempt_id"]).hex != request["attempt_id"]:
        raise ValueError("Invalid outer attempt ID")
    return request


@contextmanager
def _publishing(path: Path) -> Iterator[BinaryIO]:
    """Finish and flush a temporary member before replacing its destination."""
    with NamedTemporaryFile("w+b", dir=path.parent, delete=False) as output:
        tmp = Path(output.name)
        try:
            yield output
            output.flush()
            os.fsync(output.fileno())
            output.close()
            os.replace(tmp, path)
        finally:
            output.close()
            tmp.unlink(missing_ok=True)


def _publish_json(path: Path, record: dict) -> str:
    raw = canonical(record)
    with _publishing(path) as stream:
        stream.write(raw)
    return sha256(raw).hexdigest()


def _binding(expected: dict) -> dict:
    return {"format": FORMAT, "attempt_id": expected["attempt_id"],
            "request_sha256": sha256(canonical(expected)).hexdigest()}


def _verify_binding(record: dict, expected: dict) -> None:
    for key, value in _binding(expected).items():
        _match(record.get(key), value, key)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("Expected a UTC timestamp")
    return parsed


def _provenance(provenance: dict, expected: dict) -> None:
    for key in ("job_id", "comparison_id", "dataset_id", "source_id", "privacy_mode", "input_release_id"):
        _match(provenance[key], expected[key], key)
    _match(provenance["dataset_fingerprints"], expected["fingerprints"], "input fingerprints")
    _match(provenance["requested_backend"], expected["job"]["backend"], "requested backend")
    _match(provenance["requested_execution_profile"], expected["job"]["execution_profile"], "execution profile")
    if UUID(provenance["attempt_id"]).hex != provenance["attempt_id"]:
        raise ValueError("Invalid COMPUTE attempt ID")
    _utc(provenance["started_at_utc"])
    _utc(provenance["finished_at_utc"])


def publish_success(directory: Path, expected: dict, execution: JobExecution, worker: dict) -> None:
    """Publish checked native result and lossless NPY labels, then the commit marker."""
    labels = execution.labels
    if labels.shape != (expected["n_samples"],) or labels.dtype.kind not in "iu":
        raise ValueError(f"Invalid prediction dtype or shape: {labels.dtype}, {labels.shape}")
    for key in ("job_id", "comparison_id", "source_id", "fingerprints", "input_release_id"):
        _match(getattr(execution, key), expected[key], key)
    native = _strict_json_value(asdict(execution.report))
    provenance = native["model_state"]["execution"]
    _provenance(provenance, expected)
    _match(provenance["attempt_id"], execution.attempt_id, "COMPUTE attempt ID")
    _match(provenance["started_at_utc"], execution.started_at.isoformat(), "COMPUTE start")
    _match(provenance["finished_at_utc"], execution.finished_at.isoformat(), "COMPUTE finish")
    result = {**_binding(expected), "compute_attempt_id": execution.attempt_id,
              "worker": worker, "model_state": _strict_json_value(execution.model_state), "report": native}
    result_hash = _publish_json(directory / "result.json", result)
    with _publishing(directory / "labels.npy") as stream:
        np.save(stream, labels, allow_pickle=False)
        stream.seek(0)
        labels_hash = file_digest(stream, "sha256").hexdigest()
    manifest = {**_binding(expected), "result": {"path": "result.json", "sha256": result_hash},
                "labels": {"path": "labels.npy", "sha256": labels_hash,
                           "dtype": labels.dtype.str, "shape": list(labels.shape)}}
    _publish_json(directory / CANDIDATE, manifest)


def _checked_member(directory: Path, reference: dict, name: str) -> bytes:
    if reference["path"] != name:
        raise ValueError(f"Unexpected {name} path")
    raw = _read(directory, name)
    if sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError(f"{name} checksum mismatch")
    return raw


def _inspect_success(result: dict, labels: np.ndarray, expected: dict) -> None:
    _verify_binding(result, expected)
    report = result["report"]
    if not isinstance(report, dict) or set(report) != {f.name for f in fields(AlgorithmRunReport)}:
        raise ValueError("Incomplete native algorithm report")
    if not isinstance(report["history"], list) or not isinstance(result["model_state"], dict):
        raise ValueError("Invalid native history or adapter state")
    if type(report["runtime_sec"]) not in (int, float) or report["runtime_sec"] < 0:
        raise ValueError("Invalid algorithm runtime")
    communication = report["communication_bytes"]
    if communication is not None and (type(communication) is not int or communication < 0):
        raise ValueError("Invalid observed communication")
    state = report["model_state"]
    provenance = state["execution"]
    _provenance(provenance, expected)
    _match(result["compute_attempt_id"], provenance["attempt_id"], "COMPUTE attempt ID")
    _match(report["backend"], expected["job"]["backend"], "executed backend")
    _match(provenance["backend"], report["backend"], "native backend")
    _match(provenance["communication_bytes_observed"], communication, "native communication")
    if provenance["aggregate_release_status"] not in {"observed", "unknown", "no_noise_control", "not_applicable"}:
        raise ValueError("Invalid aggregate release status")
    algorithm = expected["job"]["algorithm"]
    if result["model_state"].get("not_equivalent_to_author_original"):
        algorithm += " [DP proxy]"
    _match(report["algorithm"], algorithm, "algorithm")
    for key, value in result["model_state"].items():
        _match(state[key], value, f"native adapter state {key}")
    if set(state) != set(result["model_state"]) | {"execution", "benchmark", "diagnostics"}:
        raise ValueError("Native report disagrees with original adapter state")
    benchmark = state["benchmark"]
    privacy = benchmark["privacy_report"]
    _match(benchmark["privacy_mode"], expected["privacy_mode"], "privacy mode")
    _match(privacy["comparison_id"], expected["comparison_id"], "privacy comparison")
    _match(privacy["release_id"], expected["input_release_id"], "input release")
    _match(privacy["scope"], "this_successful_attempt_only", "privacy scope")
    _match(benchmark["benchmark_input_hash"], expected["fingerprints"]["train"][:16], "training input")
    _match(benchmark["evaluation_input_hash"], expected["fingerprints"]["evaluation"][:16], "evaluation input")
    _match(state["diagnostics"]["raw_prediction_hash"], array_fingerprint(labels.astype(np.int64)),
           "predictions and native report")
    for key in ("ari", "ami", "nmi", "silhouette", "davies_bouldin", "calinski_harabasz"):
        if report[key] is not None and type(report[key]) not in (int, float):
            raise ValueError(f"Invalid metric: {key}")
    worker = result["worker"]
    _utc(worker["started_at_utc"])
    _utc(worker["finished_compute_at_utc"])
    if type(worker["pid"]) is not int or worker["pid"] <= 0:
        raise ValueError("Invalid worker identity")


def read_candidate(attempt_dir: Path, expected: dict, *, accepted_hash: str | None = None) -> dict:
    """Read a committed success without running any algorithm. Paths are relative to attempt_dir.

    Missing marker raises FileNotFoundError. A published, malformed or inconsistent
    attempt raises ValueError, including missing members of an accepted bundle.
    """
    _directory(attempt_dir)
    marker = _read(attempt_dir, CANDIDATE)
    digest = sha256(marker).hexdigest()
    if accepted_hash is not None and digest != accepted_hash:
        raise ValueError("Accepted candidate checksum mismatch")
    try:
        manifest = _object(marker, CANDIDATE)
        _verify_binding(manifest, expected)
        _match(read_request(attempt_dir), expected, "request.json")
        result = _object(_checked_member(attempt_dir, manifest["result"], "result.json"), "result.json")
        encoded_labels = _checked_member(attempt_dir, manifest["labels"], "labels.npy")
        with BytesIO(encoded_labels) as stream:
            labels = np.load(stream, allow_pickle=False)
            if not isinstance(labels, np.ndarray) or stream.read(1):
                raise ValueError("Invalid labels.npy")
        if (labels.dtype.kind not in "iu" or labels.dtype.str != manifest["labels"]["dtype"]
                or labels.shape != (expected["n_samples"],) or list(labels.shape) != manifest["labels"]["shape"]):
            raise ValueError("Inconsistent labels dtype or shape")
        _inspect_success(result, labels, expected)
    except (KeyError, TypeError, AttributeError, EOFError, FileNotFoundError) as exc:
        raise ValueError(f"Incomplete or invalid published result in {attempt_dir}: {exc}") from exc
    provenance = result["report"]["model_state"]["execution"]
    source_run = {"series": expected["job"]["series"], "run_id": expected["job"]["run_id"],
                  "attempt_id": expected["attempt_id"], "compute_attempt_id": result["compute_attempt_id"],
                  "worker_pid": result["worker"]["pid"],
                  "started_at_utc": provenance["started_at_utc"], "finished_at_utc": provenance["finished_at_utc"],
                  "result": manifest["result"], "predictions": manifest["labels"]}
    return {**expected, **result, "manifest_sha256": digest, "result": manifest["result"],
            "labels": manifest["labels"], "source_run": source_run}


def publish_failure(directory: Path, expected: dict, message: str, traceback_text: str, *,
                    provenance: dict | None, worker: dict, reason: str, exit_code: int, release_status: str) -> None:
    payload = {"message": message, "reason": reason, "traceback": traceback_text,
               "worker": worker, "exit_code": exit_code, "provenance": _strict_json_value(provenance),
               "aggregate_release_status": release_status}
    _publish_json(directory / FAILURE, {**_binding(expected), "payload": payload,
                                       "payload_sha256": sha256(canonical(payload)).hexdigest()})


def read_failure(attempt_dir: Path, expected: dict) -> dict | None:
    """Return checked failure evidence, or None if the worker could not publish it."""
    try:
        _directory(attempt_dir)
        raw = _read(attempt_dir, FAILURE)
    except FileNotFoundError:
        return None
    failure = _object(raw, FAILURE)
    try:
        _verify_binding(failure, expected)
        _match(read_request(attempt_dir), expected, "request.json")
        payload = failure["payload"]
        _match(sha256(canonical(payload)).hexdigest(), failure["payload_sha256"], "failure checksum")
        provenance = payload["provenance"]
        if provenance is not None:
            _provenance(provenance, expected)
            _match(provenance["aggregate_release_status"], payload["aggregate_release_status"], "failed release")
        if not isinstance(payload["message"], str) or not isinstance(payload["traceback"], str):
            raise ValueError("Invalid failure diagnosis")
        codes = {"job_error": 1, "storage_full": 4, "worker_integrity_error": 4}
        _match(payload["exit_code"], codes[payload["reason"]], "failure exit code")
        return {**_binding(expected), **payload, "failure_sha256": sha256(raw).hexdigest()}
    except (KeyError, AttributeError, TypeError, FileNotFoundError) as exc:
        raise ValueError(f"Incomplete failure evidence in {attempt_dir}: {exc}") from exc
