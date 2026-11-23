"""Transactional state owned by one campaign supervisor. Readers use SQLite snapshots."""
from __future__ import annotations

from contextlib import closing, contextmanager
from hashlib import sha256
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import time
from typing import Iterator
from uuid import uuid4

FORMAT = "pyclusteval.campaign-state.v1"
STATUSES = ("pending", "running", "ok", "error", "timeout", "interrupted", "cancelled", "skipped")


class IntegrityError(ValueError):
    """A saved campaign cannot establish the integrity of its inputs or outcomes."""


def operational_read_error(error: BaseException) -> OSError | None:
    """Recover an I/O failure from a saved-record reader's explicit exception chain.

    Missing members and directory/file mismatches are evidence problems for callers
    that require those members. A locked or inaccessible file establishes no such defect.
    """
    cause = error
    while cause is not None:
        if isinstance(cause, OSError) and not isinstance(
            cause, (FileNotFoundError, NotADirectoryError, IsADirectoryError)
        ):
            return cause
        if isinstance(cause, sqlite3.DatabaseError):
            # Extended SQLite codes retain their primary result in the low eight bits.
            primary_code = getattr(cause, "sqlite_errorcode", 0) & 255
            if primary_code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_PERM,
                                sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_FULL,
                                sqlite3.SQLITE_READONLY, sqlite3.SQLITE_NOMEM, sqlite3.SQLITE_INTERRUPT):
                return OSError(f"Cannot access campaign journal: {cause}")
        cause = cause.__cause__
    return None


def raise_operational_read_error(error: BaseException, location: Path, stage: str) -> None:
    """Propagate operational errors, retaining the observed stage if the OS omits the filename."""
    operational = operational_read_error(error)
    if operational is None:
        return
    if operational.filename is not None:
        raise operational
    if operational.errno is not None:
        raise OSError(operational.errno, f"{stage}: {operational.strerror}", location.as_posix()) from error
    raise OSError(f"{stage} at {location}: {operational}") from error


def checked_path(root: Path, *parts: str) -> Path:
    """Keep runner-owned paths in the campaign even on Windows with junctions."""
    target = root.joinpath(*parts)
    if any(not p or Path(p).name != p or p in (".", "..") for p in parts):
        raise IntegrityError(f"Invalid campaign path: {target}")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise IntegrityError(f"Linked campaign path: {current}")
    return target


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))


def checksum(data: bytes) -> str:
    return sha256(data).hexdigest()


def sealed(value: object) -> tuple[str, str]:
    data = encode(value)
    return data, checksum(data.encode("utf-8"))


def unseal(data: str, digest: str) -> dict:
    if not isinstance(data, str) or checksum(data.encode("utf-8")) != digest:
        raise IntegrityError("Campaign journal record checksum mismatch")
    try:
        record = json.loads(data)
    except ValueError as exc:
        raise IntegrityError("Malformed campaign journal record") from exc
    if not isinstance(record, dict):
        raise IntegrityError("Campaign journal record must be an object")
    return record


def create_file(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


SCHEMA = """
CREATE TABLE metadata (record TEXT NOT NULL, sha TEXT NOT NULL);
CREATE TABLE jobs (job_id TEXT PRIMARY KEY, status TEXT NOT NULL, reason TEXT);
CREATE TABLE preparations (comparison_id TEXT PRIMARY KEY, record TEXT, sha TEXT);
CREATE TABLE sessions (id TEXT PRIMARY KEY, command TEXT NOT NULL, started REAL NOT NULL,
                       ended REAL, stop_reason TEXT, limits TEXT NOT NULL, limits_sha TEXT NOT NULL);
CREATE TABLE attempts (
    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs, number INTEGER NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions, kind TEXT NOT NULL, started REAL NOT NULL,
    ended REAL, status TEXT NOT NULL, reason TEXT, accepted_hash TEXT,
    request TEXT NOT NULL, request_sha TEXT NOT NULL, details TEXT NOT NULL, details_sha TEXT NOT NULL,
    UNIQUE (job_id, number)
);
CREATE UNIQUE INDEX one_accepted ON attempts(job_id) WHERE status='ok';
CREATE UNIQUE INDEX one_running ON attempts(status) WHERE status='running';
"""


def initialize(root: Path, metadata: dict, jobs: list[dict]) -> None:
    path = checked_path(root, "state", "journal.sqlite")
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO metadata VALUES (?, ?)", sealed(metadata))
        db.executemany("INSERT INTO jobs VALUES (?, 'pending', NULL)", ((j["job_id"],) for j in jobs))


@contextmanager
def journal(root: Path, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    path = checked_path(root, "state", "journal.sqlite")
    if not path.is_file():
        raise IntegrityError(f"Campaign journal missing or initialization incomplete: {path}")
    uri = path.as_uri() + ("?mode=ro" if readonly else "?mode=rw")
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            if readonly:
                db.execute("BEGIN")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise IntegrityError("SQLite integrity check failed")
            yield db
    except sqlite3.DatabaseError as exc:
        if getattr(exc, "sqlite_errorcode", None) in (sqlite3.SQLITE_FULL, sqlite3.SQLITE_IOERR):
            raise OSError(f"Campaign journal write/read failed: {exc}") from exc
        raise IntegrityError(f"Cannot open or interpret campaign journal: {exc}") from exc


def header(db: sqlite3.Connection) -> dict:
    rows = db.execute("SELECT record,sha FROM metadata").fetchall()
    if len(rows) != 1:
        raise IntegrityError("Invalid campaign header")
    item = unseal(*rows[0])
    if item.get("format") != FORMAT:
        raise IntegrityError("Unsupported campaign journal format")
    return item


def latest_session(db: sqlite3.Connection) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM sessions ORDER BY rowid DESC LIMIT 1").fetchone()


def supervisor_runtime() -> dict:
    """Describe distributions visible to the interpreter managing this session."""
    from .runner_environment import interpreter_fields
    packages = sorted((d.metadata["Name"], d.version) for d in distributions() if d.metadata.get("Name"))
    return {"python": sys.version, "executable": sys.executable,
            "platform": platform.platform(), "packages": packages, **interpreter_fields()}


def start_session(db: sqlite3.Connection, command: str, limits: dict, *, runtime: dict | None = None) -> str:
    session = uuid4().hex
    now = time.time()
    if runtime is None:
        runtime = supervisor_runtime()
    with db:
        db.execute("UPDATE sessions SET ended=?,stop_reason='supervisor interrupted' WHERE ended IS NULL", (now,))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?, NULL, NULL, ?, ?)",
                   (session, command, now, *sealed(limits)))
        # Additive tables keep earlier sessions readable and their unobserved environments unknown.
        db.execute("CREATE TABLE IF NOT EXISTS session_runtime (session_id TEXT PRIMARY KEY REFERENCES sessions, "
                   "record TEXT NOT NULL, sha TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS unavailable_jobs (session_id TEXT NOT NULL REFERENCES sessions, "
                   "job_id TEXT NOT NULL REFERENCES jobs, record TEXT NOT NULL, sha TEXT NOT NULL, "
                   "PRIMARY KEY(session_id, job_id))")
        db.execute("INSERT INTO session_runtime VALUES (?, ?, ?)", (session, *sealed(runtime)))
    return session


def stop_session(db: sqlite3.Connection, session: str, reason: str) -> None:
    with db:
        db.execute("UPDATE sessions SET ended=?,stop_reason=? WHERE id=?", (time.time(), reason, session))


def begin_attempt(db: sqlite3.Connection, request: dict, session: str, kind: str) -> None:
    job_id = request["job_id"]
    with db:
        number = db.execute("SELECT COUNT(*)+1 FROM attempts WHERE job_id=?", (job_id,)).fetchone()[0]
        before = db.execute("UPDATE jobs SET status='running',reason=NULL WHERE job_id=? "
                            "AND status NOT IN ('ok','running','skipped')", (job_id,))
        if before.rowcount != 1:
            raise IntegrityError(f"Invalid attempt start for {job_id}")
        observation = {"input_release_id": request.get("input_release_id"),
                       "aggregate_release_status": ("unknown" if request.get("privacy_mode") == "gaussian_dp_aggregate"
                                                    else "not_applicable")}
        db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,NULL,'running',NULL,NULL,?,?,?,?)",
                   (request["attempt_id"], job_id, number, session, kind, time.time(),
                    *sealed(request), *sealed(observation)))


def finish_attempt(db: sqlite3.Connection, attempt: str, status: str, reason: str, *,
                   accepted_hash: str | None = None, details: dict | None = None) -> None:
    """The acceptance pointer and both state transitions commit together."""
    with db:
        changed = db.execute("UPDATE attempts SET ended=?,status=?,reason=?,accepted_hash=?,details=?,details_sha=? "
                             "WHERE id=? AND status='running'",
                             (time.time(), status, reason, accepted_hash, *sealed(details or {}), attempt))
        if changed.rowcount != 1:
            raise IntegrityError(f"Attempt is not running: {attempt}")
        db.execute("UPDATE jobs SET status=?,reason=? WHERE job_id=(SELECT job_id FROM attempts WHERE id=?)",
                   (status, reason, attempt))


def record_unavailable(db: sqlite3.Connection, session: str, job_id: str, status: str, reason: str) -> None:
    """Record a rejected action even when the job retains a prior attempt and outcome."""
    with db:
        observation = {"job_id": job_id, "prior_status": status, "reason": reason}
        db.execute("INSERT INTO unavailable_jobs VALUES (?, ?, ?, ?)", (session, job_id, *sealed(observation)))
        db.execute("UPDATE jobs SET status='skipped',reason=? WHERE job_id=? AND status='pending'",
                   (reason, job_id))
