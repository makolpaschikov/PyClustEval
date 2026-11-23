"""Execute exactly one requested job in a fresh, supervisor-owned process."""

from __future__ import annotations

from datetime import datetime, timezone
import errno
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _worker_runtime() -> dict:
    from .runner_environment import interpreter_fields
    packages = {}
    for name in ("flwr", "ray"):
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = None
        module = sys.modules.get(name)
        packages[name] = {"installed": installed, "imported": module is not None,
                          "imported_version": getattr(module, "__version__", None)}
    return {"python": sys.version, "executable": sys.executable,
            "platform": platform.platform(), "packages": packages, **interpreter_fields()}


def _peak_memory() -> dict:
    """Read this Windows process's peak working set when the OS provides it."""
    if sys.platform == "win32":
        from .runner_windows import worker_peak_working_set
        try:
            peak = worker_peak_working_set()
        except OSError:
            pass
        else:
            return {"peak_working_set_bytes": peak, "source": "GetProcessMemoryInfo"}
    return {"peak_working_set_bytes": None, "source": "unavailable"}


def _worker_info(started: str, start: float) -> dict:
    from threadpoolctl import threadpool_info

    threads = {key: os.environ.get(key) for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}
    return {"pid": os.getpid(), "started_at_utc": started, "finished_compute_at_utc": _now(),
            "runtime": _worker_runtime(),
            "elapsed_to_observation_sec": time.perf_counter() - start,
            "cpu_time_sec": time.process_time(), "logical_cpu_count": os.cpu_count(),
            "cpu_source": "time.process_time and os.cpu_count", "memory": _peak_memory(),
            "thread_environment": threads, "thread_pools_at_observation": threadpool_info()}


def _validate_prepared(prepared: Any, expected: dict) -> None:
    from .archive_inputs import canonical

    job_id = expected["job_id"]
    matches = [job for job in prepared.jobs if job["job_id"] == job_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one prepared job {job_id}")
    scoped = {"comparison_id": prepared.comparison["comparison_id"], "source_id": prepared.source_id,
              "dataset_id": prepared.dataset["dataset_id"], "n_samples": len(prepared.X_raw),
              "fingerprints": prepared.fingerprints, "job": matches[0],
              "privacy_mode": prepared.comparison["protocol"]["privacy_mode"],
              "input_release_id": prepared.privacy_report.get("release_id")}
    for key, value in scoped.items():
        if canonical(expected[key]) != canonical(value):
            raise ValueError(f"Worker request disagrees with verified {key}")


def _verify_preparation_files(descriptor: Path, expected: dict) -> None:
    reservation = descriptor.parent.with_name(descriptor.parent.name + ".reservation")
    for path, key in ((descriptor, "descriptor_sha256"), (reservation, "reservation_sha256")):
        if (path.is_symlink() or path.is_junction() or not path.is_file()
                or sha256(path.read_bytes()).hexdigest() != expected[key]):
            raise ValueError(f"Changed or missing preparation file: {path}")


def run_attempt(directory: Path, descriptor: Path) -> int:
    """Consume an existing request once. Return 4 for unusable state/storage, 1 for a failed job."""
    started, start = _now(), time.perf_counter()
    print(f"Worker {os.getpid()} started at {started}", flush=True)
    print(json.dumps({"event": "worker_start", "attempt_id": directory.name, "runtime": _worker_runtime()}),
          flush=True)
    from .runner_records import publish_failure, publish_success, read_request
    from .prepared import reopen
    from ..application.compute import JobExecutionError, execute_one

    # Only the first process claiming this directory may enter an adapter.
    request = read_request(directory)
    with (directory / "worker.started").open("xb") as marker:
        marker.write(request["attempt_id"].encode("ascii"))
        marker.flush()
        os.fsync(marker.fileno())

    provenance = None
    release_status = "not_started" if request["privacy_mode"] == "gaussian_dp_aggregate" else "not_applicable"
    try:
        _verify_preparation_files(descriptor, request)
        prepared = reopen(descriptor, source_id=request["source_id"], comparison_id=request["comparison_id"])
        _verify_preparation_files(descriptor, request)
        _validate_prepared(prepared, request)
        if request["privacy_mode"] == "gaussian_dp_aggregate":
            release_status = "unknown"
        execution = execute_one(prepared, request["job_id"])
        provenance = execution.report.model_state["execution"]
        publish_success(directory, request, execution, _worker_info(started, start))
    except Exception as exc:
        diagnostics = traceback.format_exc()
        print(diagnostics, file=sys.stderr, flush=True)
        compute_error = isinstance(exc, JobExecutionError)
        if compute_error:
            provenance = exc.provenance
        if provenance is not None:
            release_status = provenance["aggregate_release_status"]
        cause = exc.__cause__ if compute_error else exc
        storage_full = isinstance(cause, OSError) and cause.errno == errno.ENOSPC
        code = 1 if compute_error and not storage_full else 4
        reason = "job_error" if code == 1 else "storage_full" if storage_full else "worker_integrity_error"
        publish_failure(directory, request, str(exc), diagnostics, provenance=provenance,
                        worker=_worker_info(started, start), reason=reason, exit_code=code,
                        release_status=release_status)
        return code
    return 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("attempt_dir", type=Path)
    parser.add_argument("descriptor", type=Path)
    args = parser.parse_args()
    try:
        return run_attempt(args.attempt_dir, args.descriptor)
    except Exception:
        # The dedicated log is still available if even the diagnostic file could not be written.
        traceback.print_exc()
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
