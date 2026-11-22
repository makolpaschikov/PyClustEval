"""Seal and replace one campaign's archive, with recoverable directory renames."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import file_digest
import json
import os
from pathlib import Path
import shutil
from tempfile import mkdtemp
from typing import Iterator
from uuid import uuid4

from ..experiments.runner_state import IntegrityError, checked_path, checksum, create_file, encode, header, journal

GENERAL = "pyclusteval.campaign-archive.v1"
_TRANSACTION = ".archive-publication"


class PublicationBusy(OSError):
    """Another publisher has this campaign open."""


class VerificationFailure(IntegrityError):
    """An independently checked archive failed a publication gate."""

    def __init__(self, report: dict):
        self.report = report
        super().__init__("; ".join(report["errors"]) or "Archive verification failed")


@contextmanager
def _publisher_lock(state: Path) -> Iterator[None]:
    """The OS releases this byte-range lock when the handle or process closes."""
    lock = checked_path(state, ".archive-publisher.lock")
    with lock.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except PermissionError as exc:
                raise PublicationBusy("Another archive publisher holds the campaign lock") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise PublicationBusy("Another archive publisher holds the campaign lock") from exc
        yield


def _campaign_id(root: Path) -> str:
    if not root.is_dir():
        raise ValueError(f"Expected a campaign directory: {root}")
    if not any((root / item).exists() for item in ("state/journal.sqlite", "raw/resolved_plan.json",
                                                   ".pyclusteval-initializing")):
        raise ValueError(f"Unrecognized campaign directory: {root}")
    try:
        with journal(root, readonly=True) as db:
            meta = header(db)
    except (IntegrityError, OSError) as exc:
        from ..experiments.runner_state import operational_read_error

        failure = operational_read_error(exc)
        if failure is not None:
            raise OSError(f"Cannot read campaign journal {root / 'state/journal.sqlite'}: {failure}") from exc
        if str(exc) == "Unsupported campaign journal format":
            raise ValueError(str(exc)) from exc
        raise
    try:
        identity = [meta[key] for key in ("source_id", "created", "plan_sha256", "resolved_sha256")]
    except KeyError as exc:
        raise IntegrityError(f"Campaign header lacks {exc}") from exc
    return checksum(encode(identity).encode("utf-8"))


def _verified(directory: Path, *, sealed: bool = True) -> dict:
    from .archive_verify import verify_archive

    report = verify_archive(directory, check_checksums=sealed)
    if not report["valid"]:
        raise VerificationFailure(report)
    return report


def _digest(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            return file_digest(handle, "sha256").hexdigest()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as exc:
        raise IntegrityError(f"Required archive file missing or invalid: {path}") from exc
    except OSError as exc:
        if path.is_dir():
            raise IntegrityError(f"Expected an archive file at {path}") from exc
        raise OSError(f"Cannot hash {path}: {exc}") from exc


def _seal(directory: Path) -> dict:
    report = _verified(directory, sealed=False)
    create_file(directory / "verification.json", encode(report).encode("utf-8"))
    entries = []
    for item in sorted(directory.rglob("*")):
        if item.is_symlink() or item.is_junction():
            raise IntegrityError(f"Linked staging member: {item}")
        if item.is_file():
            entries.append({"path": item.relative_to(directory).as_posix(),
                            "bytes": item.stat().st_size, "sha256": _digest(item)})
    create_file(directory / "checksums.json", encode({"algorithm": "sha256", "files": entries}).encode("utf-8"))
    return _verified(directory)


def _object(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, ValueError) as exc:
        raise IntegrityError(f"Cannot read required record {path}: {exc}") from exc
    except OSError as exc:
        # On Windows opening a directory as a file also reports access denied.
        if path.is_dir():
            raise IntegrityError(f"Expected a record file at {path}") from exc
        raise OSError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"Expected an object in {path}")
    return value


def _owned_version(directory: Path, campaign_id: str) -> str:
    manifest = _object(checked_path(directory, "manifest.json"))
    if manifest.get("format") != GENERAL or manifest.get("campaign_id") != campaign_id:
        raise IntegrityError(f"Refusing to replace an archive from another source: {directory}")
    _verified(directory)
    return _digest(directory / "checksums.json")


def _retire(transaction: Path) -> str | None:
    # Detach the whole transaction before removing any files. A crash during cleanup
    # can leave a retired directory, but can never leave a half-deleted recovery slot.
    retired = transaction.with_name(".archive-retired-" + uuid4().hex)
    try:
        transaction.rename(retired)
        shutil.rmtree(retired)
    except OSError as exc:
        return f"Publication workspace cleanup pending: {exc}"
    return None


def _recover(transaction: Path, target: Path, campaign_id: str) -> str | None:
    """Restore the old version after a gap, or confirm an already installed replacement."""
    if not transaction.exists():
        return None
    owner = _object(checked_path(transaction, "owner.json"))
    if owner != {"format": "pyclusteval.export-transaction.v1", "campaign_id": campaign_id}:
        raise IntegrityError(f"Unrecognized publication workspace: {transaction}")
    previous = checked_path(transaction, "previous")
    if previous.exists():
        swap = _object(checked_path(transaction, "swap.json"))
        if _owned_version(previous, campaign_id) != swap.get("previous_sha256"):
            raise IntegrityError(f"Previous archive does not match publication record: {previous}")
        if target.exists():
            if _owned_version(target, campaign_id) != swap.get("staged_sha256"):
                raise IntegrityError(f"Published archive does not match interrupted replacement: {target}")
        else:
            previous.rename(target)
    return _retire(transaction)


def publish_archive(campaign: Path) -> dict:
    """Publish a checked snapshot under campaign/archive. A partial valid snapshot is publishable."""
    root = campaign.resolve()
    campaign_id = _campaign_id(root)
    from .archive_build import build_archive

    state = checked_path(root, "state")
    warnings = []
    with _publisher_lock(state):
        target = checked_path(root, "archive")
        transaction = checked_path(state, _TRANSACTION)
        warning = _recover(transaction, target, campaign_id)
        if warning:
            warnings.append(warning)
        if transaction.exists():
            raise OSError(f"Cannot retire prior publication workspace: {transaction}")
        # A recognizable owner marker is visible at the fixed recovery path from
        # its first instant. An interrupted initialization can leave only a unique scratch.
        initial = Path(mkdtemp(prefix=".archive-init-", dir=state))
        try:
            create_file(initial / "owner.json", encode({
                "format": "pyclusteval.export-transaction.v1", "campaign_id": campaign_id
            }).encode("utf-8"))
            initial.rename(transaction)
        finally:
            if initial.exists():
                shutil.rmtree(initial)
        previous = transaction / "previous"
        stage = transaction / "staging"
        try:
            stage.mkdir()
            manifest = build_archive(root, stage)
            if manifest.get("campaign_id") != campaign_id:
                raise IntegrityError("Campaign identity changed while exporting")
            report = _seal(stage)
            if report["complete"] != manifest["complete"]:
                raise IntegrityError("Staging completeness differs from the checked manifest")
            if target.exists():
                old_hash = _owned_version(target, campaign_id)
                create_file(transaction / "swap.json", encode({
                    "previous_sha256": old_hash, "staged_sha256": _digest(stage / "checksums.json"),
                }).encode("utf-8"))
                target.rename(previous)
            stage.rename(target)
        except BaseException:
            # In particular, antivirus/readers may temporarily prevent the second rename.
            # Keep both the recovery evidence and the last verified generation if restore fails.
            if previous.exists() and not target.exists():
                previous.rename(target)
            if not previous.exists():
                _retire(transaction)
            raise
        warning = _retire(transaction)
        if warning:
            warnings.append(warning)
        return {"published": True, "path": str(target), "complete": manifest["complete"],
                "planned": manifest["planned"], "totals": manifest["totals"],
                "verification": report, "warnings": warnings}
