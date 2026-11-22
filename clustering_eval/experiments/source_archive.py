"""Portable campaign source evidence. Verification reads data without executing it."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import file_digest, sha256
import json
from pathlib import Path
import re
import stat
import unicodedata
from zipfile import BadZipFile, ZipFile
import zlib

FORMAT = "pyclusteval.source-snapshot.v1"
ZIP_NAME = "source_snapshot.zip"
PATCH_NAME = "source_changes.patch"
RECORD_NAME = "source_code_verification.json"
REQUIRED = {"pyproject.toml", "pyclusteval_ui.py", "clustering_eval/__init__.py", "clustering_eval/cli.py"}
CHECKS = ["checkout_read_twice", "git_head_stable", "zip_members_and_hashes", "patch_hash"]
_RESERVED = re.compile(r"^(?:AUX|CON|CONIN\$|CONOUT\$|NUL|PRN|(?:COM|LPT)[1-9¹²³])(?:\.|$)", re.I)


class SourceSnapshotError(ValueError):
    """The capture or verification cannot establish a consistent source snapshot."""


@dataclass(frozen=True)
class SourceSnapshot:
    """Verified identity and location of the three source artifacts."""

    source_id: str
    source_head: str
    directory: Path

    @property
    def archive(self) -> Path:
        return self.directory / ZIP_NAME

    @property
    def patch(self) -> Path:
        return self.directory / PATCH_NAME

    @property
    def verification(self) -> Path:
        return self.directory / RECORD_NAME


def portable_path(name: str) -> str:
    """Validate an exact relative archive member name on both Windows and POSIX."""
    if not isinstance(name, str) or not name:
        raise SourceSnapshotError(f"Invalid source path: {name!r}")
    for part in name.split("/"):
        if (not part or part in {".", ".."} or part.endswith((" ", ".")) or _RESERVED.match(part)
                or any(ord(c) < 32 or c in '\\:<>"|?*' for c in part)):
            raise SourceSnapshotError(f"Non-portable source path: {name!r}")
    return name


def validate_members(names: list[str]) -> None:
    """Check required members, aliases and collisions at every directory level."""
    seen: set[str] = set()
    components: dict[str, str] = {}
    for name in names:
        portable_path(name)
        if name in seen:
            raise SourceSnapshotError(f"Duplicate source path: {name}")
        seen.add(name)
        parts = name.split("/")
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            key = unicodedata.normalize("NFC", prefix).casefold()
            if components.setdefault(key, prefix) != prefix:
                raise SourceSnapshotError(f"Ambiguous source path: {name}")
    for prefix in components.values():
        parent = prefix.rpartition("/")[0]
        if parent in seen:
            raise SourceSnapshotError(f"File used as a directory: {parent}")
    missing = REQUIRED - seen
    if missing:
        raise SourceSnapshotError(f"Missing required source: {', '.join(sorted(missing))}")


def content_id(files: dict[str, str]) -> str:
    """Hash the versioned, sorted (portable path, raw byte SHA-256) inventory."""
    canonical = json.dumps([FORMAT, sorted(files.items())], ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceSnapshotError(f"Duplicate verification field: {key}")
        result[key] = value
    return result


def _file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def verify_source_snapshot(directory: Path | str, *, expected_source_id: str | None = None) -> SourceSnapshot:
    """Read the portable evidence and optionally compare it with a caller's pinned identity."""
    path = Path(directory)
    try:
        for name in (ZIP_NAME, PATCH_NAME, RECORD_NAME):
            member = path / name
            if member.is_symlink() or not member.is_file():
                raise SourceSnapshotError(f"Missing or non-regular artifact: {member}")
        record = json.loads((path / RECORD_NAME).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(record, dict) or record.get("format") != FORMAT or record.get("checks") != CHECKS:
            raise SourceSnapshotError(f"Unexpected verification format/checks in {RECORD_NAME}")
        head = record.get("source_head")
        if not isinstance(head, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head):
            raise SourceSnapshotError(f"Invalid source_head in {RECORD_NAME}")
        files = record.get("files")
        if not isinstance(files, dict):
            raise SourceSnapshotError(f"Missing file inventory in {RECORD_NAME}")
        validate_members(list(files))
        if _file_hash(path / PATCH_NAME) != record.get("working_tree_patch_sha256"):
            raise SourceSnapshotError(f"Checksum mismatch: {PATCH_NAME}")
        with ZipFile(path / ZIP_NAME) as archive:
            infos = archive.infolist()
            validate_members([info.orig_filename for info in infos])
            actual = {info.orig_filename for info in infos}
            if actual != files.keys():
                raise SourceSnapshotError(f"ZIP inventory mismatch: {sorted(actual ^ files.keys())}")
            for info in infos:
                if stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG):
                    raise SourceSnapshotError(f"Non-regular ZIP member: {info.filename}")
                with archive.open(info) as stream:
                    if file_digest(stream, "sha256").hexdigest() != files[info.filename]:
                        raise SourceSnapshotError(f"Member checksum mismatch: {info.filename}")
        if _file_hash(path / ZIP_NAME) != record.get("snapshot_sha256"):
            raise SourceSnapshotError(f"Checksum mismatch: {ZIP_NAME}")
        identity = content_id(files)
        if identity != record.get("source_id") or expected_source_id is not None and identity != expected_source_id:
            raise SourceSnapshotError("Source identity mismatch")
        return SourceSnapshot(identity, head, path)
    except (OSError, BadZipFile, zlib.error, UnicodeError, json.JSONDecodeError, NotImplementedError, RuntimeError) as exc:
        raise SourceSnapshotError(f"Cannot verify {path}: {exc}") from exc
