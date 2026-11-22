"""Create a campaign from PLAN and authenticate its scientific inputs on resume."""
from __future__ import annotations

from importlib.metadata import distributions
from pathlib import Path
import json
import platform
import sqlite3
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from .plan_io import read_document
from .prepared import prepare
from .prepared_store import DESCRIPTOR, read as read_prepared
from .runner_state import (FORMAT, IntegrityError, checked_path, checksum, create_file, encode,
                           initialize, sealed, unseal)
from .series_plan import checkout_source_id, resolve_document
from .source_archive import RECORD_NAME, verify_source_snapshot
from .source_capture import capture_source_snapshot

CHECKOUT = Path(__file__).resolve().parents[2]
CREATION_MARKER = ".pyclusteval-initializing"


def input_plan(source: Path) -> tuple[bytes, dict]:
    raw = source.read_bytes()
    parsed = read_document(source)
    if raw != source.read_bytes():
        raise ValueError("Plan changed while reading")
    if "historical" in parsed:
        raise ValueError("Unsupported campaign execution: historical_reference/persistent_worker")
    resolved = resolve_document(parsed, base_dir=source.parent, source_id=checkout_source_id())
    execution = resolved["execution"]
    if execution["processes"] != 1 or execution["profile"] != "cold":
        raise ValueError("Campaign execution requires processes=1 and profile=cold")
    return raw, resolved


def protect_root(root: Path) -> None:
    for parent in (root, *root.parents):
        if ((parent / "manifest.json").is_file() and (parent / "checksums.json").is_file()
                and (parent / "reproduce").is_dir()):
            raise ValueError(f"Output would modify an existing campaign archive: {parent}")


def create_campaign(root: Path, source: Path, raw: bytes, plan: dict) -> None:
    """Called under exclusive ownership. Leave an identifiable interrupted initialization."""
    started = time.time()
    protect_root(root)
    if root.exists():
        if not root.is_dir():
            raise ValueError(f"Campaign destination is an existing file: {root}")
        if checked_path(root, CREATION_MARKER).exists():
            raise IntegrityError(f"Campaign initialization was interrupted: {root}")
        if checked_path(root, "state", "journal.sqlite").exists():
            raise FileExistsError(f"Campaign already exists. Use series resume: {root}")
        if any(root.iterdir()):
            raise ValueError(f"Campaign destination must be empty: {root}")
    else:
        root.mkdir(parents=True)
    marker = root / CREATION_MARKER
    create_file(marker, b"campaign creation in progress\n")
    (root / "state").mkdir()
    for name in ("raw", "attempts", "cache"):
        (root / name).mkdir()
    suffix = ".json" if source.suffix.lower() == ".json" else ".yaml"
    # SOURCE builds a temporary Git index. Deep campaign paths may exceed Git for Windows' path limit.
    target = root / "raw" / "source"
    target.mkdir()
    with TemporaryDirectory(prefix="campaign-source-") as scratch:
        captured = capture_source_snapshot(CHECKOUT, Path(scratch) / "source")
        if captured.source_id != plan["source_id"]:
            raise IntegrityError("Checkout changed between planning and source capture")
        for member in (captured.archive, captured.patch, captured.verification):
            create_file(target / member.name, member.read_bytes())
    snapshot = verify_source_snapshot(target, expected_source_id=plan["source_id"])
    resolved_bytes = encode(plan).encode("utf-8")
    create_file(root / "raw" / ("plan" + suffix), raw)
    create_file(root / "raw" / "resolved_plan.json", resolved_bytes)
    packages = sorted((d.metadata["Name"], d.version) for d in distributions() if d.metadata.get("Name"))
    metadata = {
        "format": FORMAT, "created": started, "source_id": snapshot.source_id,
        "source_record_sha256": checksum(snapshot.verification.read_bytes()),
        "original": str(source), "base_dir": str(source.parent), "plan_file": "plan" + suffix,
        "plan_sha256": checksum(raw), "resolved_sha256": checksum(resolved_bytes),
        "runtime": {"python": sys.version, "executable": sys.executable,
                    "platform": platform.platform(), "packages": packages},
    }
    initialize(root, metadata, plan["jobs"])
    marker.unlink()


def saved_plan(root: Path, meta: dict) -> dict:
    """Check saved artifacts independently of the current checkout or original data."""
    if checked_path(root, CREATION_MARKER).exists():
        raise IntegrityError("Campaign initialization incomplete")
    try:
        saved = checked_path(root, "raw", meta["plan_file"])
        resolved = checked_path(root, "raw", "resolved_plan.json")
        if checksum(saved.read_bytes()) != meta["plan_sha256"]:
            raise IntegrityError(f"Saved plan checksum mismatch: {saved}")
        data = resolved.read_bytes()
        if checksum(data) != meta["resolved_sha256"]:
            raise IntegrityError(f"Resolved plan checksum mismatch: {resolved}")
        source = checked_path(root, "raw", "source")
        if checksum((source / RECORD_NAME).read_bytes()) != meta["source_record_sha256"]:
            raise IntegrityError("Saved source verification record changed")
        verify_source_snapshot(source, expected_source_id=meta["source_id"])
        plan = json.loads(data)
        if plan["source_id"] != meta["source_id"]:
            raise IntegrityError("Campaign source binding mismatch")
        return plan
    except (OSError, ValueError, KeyError) as exc:
        raise IntegrityError(f"Saved campaign materials: {exc}") from exc


def verify_live_inputs(root: Path, meta: dict, plan: dict) -> None:
    try:
        original = Path(meta["original"])
        if original.exists() and checksum(original.read_bytes()) != meta["plan_sha256"]:
            raise IntegrityError(f"Original plan bytes changed: {original}")
        if checkout_source_id() != meta["source_id"]:
            raise IntegrityError("Current checkout differs from the campaign source")
        source = checked_path(root, "raw", meta["plan_file"])
        current = resolve_document(read_document(source), base_dir=Path(meta["base_dir"]),
                                   source_id=meta["source_id"])
        if current != plan:
            raise IntegrityError("Re-resolved scientific plan/data differ from saved campaign")
    except (OSError, ValueError) as exc:
        raise IntegrityError(f"Cannot verify inputs for a new worker: {exc}") from exc


def descriptor_path(root: Path, comparison_id: str) -> Path:
    return checked_path(root, "cache", comparison_id, DESCRIPTOR)


def prepared_binding(root: Path, plan: dict, comparison_id: str) -> dict:
    descriptor = descriptor_path(root, comparison_id)
    reservation = checked_path(root, "cache", comparison_id + ".reservation")
    try:
        if not reservation.is_file():
            raise IntegrityError(f"Missing preparation reservation: {reservation}")
        prepared = read_prepared(descriptor, plan["source_id"], comparison_id)
        comparison = next(c for c in plan["comparisons"] if c["comparison_id"] == comparison_id)
        jobs = [j for j in plan["jobs"] if j["comparison_id"] == comparison_id]
        if prepared.comparison != comparison or prepared.jobs != jobs:
            raise IntegrityError(f"Prepared records differ from plan: {comparison_id}")
        return {"descriptor_sha256": checksum(descriptor.read_bytes()),
                "reservation_sha256": checksum(reservation.read_bytes()),
                "fingerprints": prepared.fingerprints, "n_samples": len(prepared.X_raw),
                "dataset_id": comparison["dataset_id"], "privacy_mode": comparison["protocol"]["privacy_mode"],
                "input_release_id": prepared.privacy_report.get("release_id")}
    except (OSError, ValueError, StopIteration, KeyError) as exc:
        raise IntegrityError(f"Incomplete or changed preparation {comparison_id}; release may be unknown: {exc}") from exc


def ensure_prepared(db: sqlite3.Connection, root: Path, plan: dict, comparison_id: str, base_dir: Path) -> dict:
    descriptor = descriptor_path(root, comparison_id)
    reservation = checked_path(root, "cache", comparison_id + ".reservation")
    row = db.execute("SELECT record,sha FROM preparations WHERE comparison_id=?", (comparison_id,)).fetchone()
    if row is None:
        if descriptor.parent.exists() or reservation.exists():
            raise IntegrityError(f"Unexpected preparation without campaign intent: {comparison_id}")
        with db:
            db.execute("INSERT INTO preparations VALUES (?,NULL,NULL)", (comparison_id,))
    elif row["record"] is None and not descriptor.exists():
        comparison = next(c for c in plan["comparisons"] if c["comparison_id"] == comparison_id)
        mode = comparison["protocol"]["privacy_mode"]
        if mode not in {"none", "gaussian_dp_aggregate", "public_clipped_control"}:
            raise IntegrityError(f"Incomplete {mode} preparation {comparison_id}; release may be unknown")
        # No attempt can start before the preparation binding commits. Only this
        # unbound, unpublished, non-release case may rebuild from verified inputs.
        if descriptor.parent.exists() or reservation.exists():
            partial = checked_path(root, "cache", comparison_id + ".incomplete-" + uuid4().hex)
            partial.mkdir()
            if descriptor.parent.exists():
                descriptor.parent.rename(partial / "bundle")
            if reservation.exists():
                reservation.rename(partial / "reservation")
    if row is None or (row["record"] is None and not descriptor.exists()):
        try:
            prepare(plan, comparison_id, descriptor.parent, source_id=plan["source_id"], base_dir=base_dir)
        except ValueError as exc:
            raise IntegrityError(f"Preparation failed ({comparison_id}): {exc}") from exc
    observed = prepared_binding(root, plan, comparison_id)
    if row is None or row["record"] is None:
        with db:
            db.execute("UPDATE preparations SET record=?,sha=? WHERE comparison_id=?",
                       (*sealed(observed), comparison_id))
    elif unseal(*row) != observed:
        raise IntegrityError(f"Prepared input or shared release changed: {comparison_id}")
    return observed
