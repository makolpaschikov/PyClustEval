"""Sequential job scheduling, recovery and explicit retry policy for a locked campaign."""
from __future__ import annotations

import errno
from collections.abc import Callable
from pathlib import Path
import sqlite3
import sys
import time
from uuid import uuid4

from .runner_campaign import CHECKOUT, descriptor_path, ensure_prepared
from .runner_reader import attempt_directory, log_evidence
from .runner_state import (IntegrityError, begin_attempt, create_file, encode, finish_attempt,
                           record_unavailable, sealed, unseal)


def release_evidence(expected: dict) -> dict:
    """Conservative evidence for a process which may have entered an aggregate adapter."""
    return {"input_release_id": expected["input_release_id"],
            "aggregate_release_status": ("unknown" if expected["privacy_mode"] == "gaussian_dp_aggregate"
                                         else "not_applicable")}


def failure_detail(path: Path, expected: dict) -> dict:
    from .runner_records import read_failure

    detail = release_evidence(expected)
    try:
        failure = read_failure(path, expected) if path.is_dir() else None
    except (OSError, ValueError) as exc:
        raise IntegrityError(f"Invalid failure evidence in {path}: {exc}") from exc
    if failure is not None:
        detail["failure"] = failure
        provenance = failure.get("provenance") or {}
        if "aggregate_release_status" in provenance:
            detail["aggregate_release_status"] = provenance["aggregate_release_status"]
    return detail


def accept(db: sqlite3.Connection, root: Path, request: dict, details: dict) -> None:
    from .runner_records import read_candidate

    path = attempt_directory(root, request["attempt_id"])
    candidate = read_candidate(path, request)
    finish_attempt(db, request["attempt_id"], "ok", "verified result and labels",
                   accepted_hash=candidate["manifest_sha256"], details={**details, "logs": log_evidence(path)})


def recover_running(db: sqlite3.Connection, root: Path) -> None:
    """Called under newly acquired tree ownership before taking fresh work."""
    row = db.execute("SELECT * FROM attempts WHERE status='running'").fetchone()
    if row is None:
        return
    request = unseal(row["request"], row["request_sha"])
    path = attempt_directory(root, row["id"])
    try:
        accept(db, root, request, {"recovered": True})
    except FileNotFoundError:
        evidence = failure_detail(path, request)
        failed = evidence.get("failure")
        status = "error" if failed else "interrupted"
        reason = (failed.get("message", "worker failed before recovery") if failed
                  else "supervisor stopped before a complete worker publication")
        finish_attempt(db, row["id"], status, reason, details=evidence)
        if failed and failed.get("exit_code") == 4:
            raise IntegrityError(f"Recovered worker integrity or publication failure: {reason}")
    except ValueError as exc:
        finish_attempt(db, row["id"], "error", str(exc), details=release_evidence(request))
        raise IntegrityError(f"Invalid worker publication during recovery: {exc}") from exc


def automatic_left(db: sqlite3.Connection, job_id: str, policy: dict) -> bool:
    count = db.execute("SELECT COUNT(*) FROM attempts WHERE job_id=? AND kind='automatic'", (job_id,)).fetchone()[0]
    return count < policy["max_retries"]


def execute(db: sqlite3.Connection, root: Path, plan: dict, job: dict, binding: dict, *,
            policy: dict, deadline: float | None, session: str, kind: str) -> tuple[str, str]:
    from .runner_process import run_owned, worker_env

    outer = uuid4().hex
    cid = job["comparison_id"]
    request = dict(binding)
    request.update(attempt_id=outer, job_id=job["job_id"], comparison_id=cid,
                   source_id=plan["source_id"], job=job, launch_executable=sys.executable)
    begin_attempt(db, request, session, kind)
    path = attempt_directory(root, outer)
    path.mkdir()
    create_file(path / "request.json", encode(request).encode("utf-8"))
    argv = [sys.executable, "-B", "-m", "clustering_eval.experiments.runner_worker",
            str(path), str(descriptor_path(root, cid))]
    exit_status = {"timeout": "timeout", "total_time": "interrupted", "cancelled": "cancelled"}

    def stopped(reason: str) -> None:
        finish_attempt(db, outer, exit_status[reason], reason, details=release_evidence(request))

    environment = worker_env(policy["blas_threads"])
    if job["backend"] == "flower-simulation":
        environment.pop("RAY_ADDRESS", None)
        environment.update(FLWR_TELEMETRY_ENABLED="0", RAY_USAGE_STATS_ENABLED="0")
    try:
        proc = run_owned(argv, cwd=CHECKOUT, env=environment,
                         stdout_path=path / "stdout.log", stderr_path=path / "stderr.log",
                         timeout_sec=policy["timeout_sec"], deadline_utc=deadline,
                         memory_limit_mb=policy["memory_limit_mb"], on_stop=stopped)
    except OSError as exc:
        if exc.errno != errno.ENOSPC:
            row = db.execute("SELECT status FROM attempts WHERE id=?", (outer,)).fetchone()
            if row["status"] == "running":
                finish_attempt(db, outer, "error", str(exc), details=release_evidence(request))
        raise
    timing = {"worker_wall_sec": proc.wall_sec, "returncode": proc.returncode,
              "tree_resources": proc.tree_resources}
    if proc.reason in exit_status:
        # The durable terminal decision already exists even if this observation cannot be saved.
        with db:
            db.execute("UPDATE attempts SET details=?,details_sha=? WHERE id=?",
                       (*sealed({**release_evidence(request), **timing}), outer))
        return exit_status[proc.reason], proc.reason
    if proc.returncode == 0:
        try:
            accept(db, root, request, timing)
            return "ok", "verified"
        except (OSError, ValueError) as exc:
            finish_attempt(db, outer, "error", str(exc), details=release_evidence(request) | timing)
            raise IntegrityError(f"Invalid success from worker {outer}: {exc}") from exc
    evidence = failure_detail(path, request)
    reason = (evidence.get("failure") or {}).get("message") or f"worker exited with code {proc.returncode}"
    finish_attempt(db, outer, "error", reason, details=evidence | timing)
    if proc.returncode == 4:
        raise IntegrityError(f"Worker integrity or publication failure: {reason}")
    return "error", reason


def _elapsed(deadline: float | None) -> bool:
    return deadline is not None and time.time() >= deadline


def schedule(db: sqlite3.Connection, root: Path, meta: dict, plan: dict, session: str,
             policy: dict, command: str, selected: str | None, only_job: str | None,
             *, before_work: Callable[[], None] | None = None) -> tuple[str, int]:
    from ..application.flower_profile import runtime_rejection

    total_time = policy["total_time_sec"]
    deadline = None if total_time is None else meta["created"] + total_time
    jobs = {j["job_id"]: j for j in plan["jobs"]}
    protocols = {c["comparison_id"]: c["protocol"] for c in plan["comparisons"]}
    if only_job is not None and only_job not in jobs:
        raise ValueError(f"Unknown --job-id: {only_job}")
    processed = 0
    rejected = []
    for row in db.execute("SELECT job_id,status FROM jobs ORDER BY rowid").fetchall():
        status, job_id = row["status"], row["job_id"]
        job = jobs[job_id]
        if command == "retry":
            if status != selected or only_job is not None and job_id != only_job:
                continue
            kind = "manual"
        elif status in ("pending", "interrupted", "cancelled"):
            kind = "initial" if status == "pending" else "resumed"
        elif status in ("error", "timeout") and automatic_left(db, job_id, policy):
            kind = "automatic"
        else:
            continue
        if _elapsed(deadline):
            return "total_time", processed
        if before_work is not None:
            before_work()
        cid = job["comparison_id"]
        reason = runtime_rejection(job, protocols[cid])
        if reason is not None:
            record_unavailable(db, session, job_id, status, reason)
            if policy["failure_policy"] == "stop":
                return reason, processed
            rejected.append(reason)
            continue
        binding = ensure_prepared(db, root, plan, cid, Path(meta["base_dir"]))
        while True:
            if _elapsed(deadline):
                return "total_time", processed
            status, reason = execute(db, root, plan, job, binding, policy=policy,
                                     deadline=deadline, session=session, kind=kind)
            processed += 1
            if status in ("cancelled", "interrupted"):
                return reason, processed
            if status == "ok":
                break
            if command != "retry" and automatic_left(db, job_id, policy):
                kind = "automatic"
                continue
            if policy["failure_policy"] == "stop":
                return reason, processed
            break
    if rejected:
        return f"Queue exhausted with {len(rejected)} unavailable jobs; first reason: {rejected[0]}", processed
    return "queue exhausted", processed
