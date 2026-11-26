"""Read a coherent campaign snapshot for status and downstream archive construction."""
from __future__ import annotations

from contextlib import closing
from hashlib import file_digest
import os
from pathlib import Path
import sqlite3
import time
from uuid import UUID

from .runner_campaign import saved_plan
from .runner_state import IntegrityError, STATUSES, checked_path, header, journal, raise_operational_read_error, unseal


def attempt_directory(root: Path, attempt_id: str) -> Path:
    try:
        if UUID(attempt_id).hex != attempt_id:
            raise ValueError("not canonical")
    except (TypeError, ValueError) as exc:
        raise IntegrityError(f"Invalid technical attempt ID: {attempt_id!r}") from exc
    return checked_path(root, "attempts", attempt_id)


def log_evidence(directory: Path) -> dict:
    """Read flushed, closed process logs after the owned tree has drained."""
    records = {}
    for name in ("stdout.log", "stderr.log"):
        path = checked_path(directory, name)
        try:
            with path.open("rb") as stream:
                digest = file_digest(stream, "sha256").hexdigest()
                size = os.fstat(stream.fileno()).st_size
        except OSError as exc:
            raise IntegrityError(f"Cannot verify {path}: {exc}") from exc
        records[name] = {"path": name, "sha256": digest, "bytes": size}
    return records


def read_snapshot(db: sqlite3.Connection, root: Path, meta: dict, plan: dict, *,
                  propagate_io_errors: bool = False) -> dict:
    from .runner_process import is_campaign_active
    from .runner_records import read_candidate

    jobs = {j["job_id"]: dict(job=j, attempts=[], accepted=None) for j in plan["jobs"]}
    recorded = db.execute("SELECT job_id,status,reason FROM jobs ORDER BY rowid").fetchall()
    if [r["job_id"] for r in recorded] != list(jobs):
        raise IntegrityError("Journal jobs differ from the resolved plan")
    preparations = {}
    for row in db.execute("SELECT * FROM preparations ORDER BY rowid"):
        binding = None if row["record"] is None else unseal(row["record"], row["sha"])
        preparations[row["comparison_id"]] = binding
    sessions = []
    for row in db.execute("SELECT * FROM sessions ORDER BY rowid"):
        sessions.append({"session_id": row["id"], "command": row["command"], "started": row["started"],
                         "ended": row["ended"], "stop_reason": row["stop_reason"],
                         "limits": unseal(row["limits"], row["limits_sha"]), "runtime": None,
                         "unavailable_jobs": []})
    by_session = {s["session_id"]: s for s in sessions}
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "session_runtime" in tables:
        for sid, data, digest in db.execute("SELECT session_id,record,sha FROM session_runtime"):
            if sid not in by_session:
                raise IntegrityError("Runtime record refers to an unknown session")
            by_session[sid]["runtime"] = unseal(data, digest)
    if "unavailable_jobs" in tables:
        for sid, jid, data, digest in db.execute("SELECT session_id,job_id,record,sha FROM unavailable_jobs ORDER BY rowid"):
            issue = unseal(data, digest)
            if sid not in by_session or jid not in jobs or issue.get("job_id") != jid:
                raise IntegrityError("Unavailable job record differs from campaign or session")
            by_session[sid]["unavailable_jobs"].append(issue)
    problems = []
    last_error = None
    for row in db.execute("SELECT * FROM attempts ORDER BY rowid"):
        entry = jobs.get(row["job_id"])
        if entry is None or row["status"] not in STATUSES or row["number"] != len(entry["attempts"]) + 1:
            raise IntegrityError("Attempt belongs to an unknown job, status or sequence")
        expected = unseal(row["request"], row["request_sha"])
        job = entry["job"]
        binding = preparations.get(job["comparison_id"])
        if (not binding or expected.get("job") != job or expected.get("attempt_id") != row["id"]
                or expected.get("source_id") != plan["source_id"] or expected.get("job_id") != job["job_id"]
                or expected.get("comparison_id") != job["comparison_id"]
                or any(expected.get(key) != value for key, value in binding.items())):
            raise IntegrityError(f"Attempt request binding differs: {row['id']}")
        path = attempt_directory(root, row["id"])
        relative = path.relative_to(root).as_posix()
        attempt = {"attempt_id": row["id"], "directory": relative, "number": row["number"],
                   "session_id": row["session_id"], "kind": row["kind"], "status": row["status"],
                   "reason": row["reason"], "started": row["started"], "ended": row["ended"],
                   "stdout": relative + "/stdout.log", "stderr": relative + "/stderr.log",
                   "request": expected, "details": unseal(row["details"], row["details_sha"])}
        entry["attempts"].append(attempt)
        if row["status"] == "ok":
            if not row["accepted_hash"] or entry["accepted"] is not None:
                raise IntegrityError(f"Invalid acceptance pointer: {row['id']}")
            try:
                candidate = read_candidate(path, expected, accepted_hash=row["accepted_hash"])
                logs = log_evidence(path)
                if logs != attempt["details"].get("logs"):
                    raise IntegrityError("Accepted stdout/stderr checksum mismatch")
                entry["accepted"] = {"attempt_id": row["id"], "directory": relative,
                                     "candidate": candidate, "logs": logs}
            except (OSError, ValueError) as exc:
                if propagate_io_errors:
                    raise_operational_read_error(exc, path, "Reading accepted attempt artifacts")
                reason = f"Accepted attempt {row['id']} failed verification: {exc}"
                entry["integrity_error"] = reason
                problems.append(reason)
        elif row["accepted_hash"] is not None:
            raise IntegrityError(f"Non-success attempt has an accepted pointer: {row['id']}")
        if row["status"] in ("error", "timeout", "interrupted", "cancelled"):
            last_error = {"job_id": row["job_id"], "attempt_id": row["id"], "reason": row["reason"]}

    active = is_campaign_active(root)
    counts = dict.fromkeys(STATUSES, 0)
    current = []
    for row in recorded:
        item = jobs[row["job_id"]]
        status = row["status"]
        attempts = item["attempts"]
        if (status not in STATUSES or attempts and attempts[-1]["status"] != status
                or not attempts and status not in ("pending", "skipped")):
            raise IntegrityError(f"Inconsistent job status: {row['job_id']}")
        item.update(status="error" if "integrity_error" in item else status,
                    recorded_status=status, reason=item.get("integrity_error", row["reason"]))
        counts[item["status"]] += 1
        if status == "running":
            current.append({"job_id": row["job_id"], "attempt_id": attempts[-1]["attempt_id"],
                            "supervisor_active": active, "worker_liveness": "unconfirmed"})
    now = time.time()
    modes = {c["comparison_id"]: c["protocol"]["privacy_mode"] for c in plan["comparisons"]}
    preparation_status = {}
    for cid, binding in preparations.items():
        if cid not in modes:
            raise IntegrityError(f"Unknown prepared comparison in journal: {cid}")
        if binding is None:
            preparation_status[cid] = ("release_outcome_unknown" if modes[cid] == "gaussian_dp"
                                       else "preparation_incomplete")
        else:
            preparation_status[cid] = "recorded"
    return {"format": "pyclusteval.campaign-reader.v1", "source_id": meta["source_id"],
            "environment": meta["runtime"], "plan": plan, "jobs": list(jobs.values()),
            "preparations": preparations,
            "preparation_status": preparation_status,
            "sessions": sessions, "integrity_errors": problems,
            "summary": {"planned": len(jobs), "totals": counts, "current": current,
                        "supervisor_active": active, "created_utc_epoch": meta["created"],
                        "elapsed_sec": max(0., now - meta["created"]), "last_error": last_error,
                        "stop_reason": sessions[-1]["stop_reason"] if sessions else None,
                        "unavailable_jobs": sessions[-1]["unavailable_jobs"] if sessions else [],
                        "report_path": None}}


def read_campaign(root: Path, *, propagate_io_errors: bool = False) -> dict:
    """Read saved files only. Each accepted pointer contains fully verified candidate evidence.

    A damaged accepted job is returned as error with no accepted pointer. Other
    valid results remain usable. Structural journal corruption raises IntegrityError.
    Export can request propagation of access/locking errors while reading accepted
    members so a transient I/O failure is distinguishable from damaged evidence.
    """
    root = Path(root).resolve()
    # Finish the live read transaction before verifying potentially large result files.
    with closing(sqlite3.connect(":memory:")) as snapshot:
        snapshot.row_factory = sqlite3.Row
        with journal(root, readonly=True) as db:
            db.backup(snapshot)
        meta = header(snapshot)
        try:
            plan = saved_plan(root, meta)
        except (OSError, ValueError) as exc:
            if propagate_io_errors:
                raise_operational_read_error(exc, root / "raw", "Reading saved plans and captured source")
            raise
        return read_snapshot(snapshot, root, meta, plan, propagate_io_errors=propagate_io_errors)
