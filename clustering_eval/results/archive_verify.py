"""Read-only integrity and semantic checks on a relocated research archive."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import csv
from hashlib import file_digest
import math
from pathlib import Path
import stat
import unicodedata
from typing import Any, Iterator
from zipfile import BadZipFile
import zlib

from ..experiments.archive_inputs import PROFILE, document
from ..experiments.runner_state import operational_read_error
from ..experiments.source_archive import portable_path

GENERAL = "pyclusteval.campaign-archive.v1"
DATA_ERRORS = (ValueError, TypeError, KeyError, IndexError, AttributeError, FileNotFoundError,
               NotADirectoryError, IsADirectoryError,
               OverflowError, EOFError, BadZipFile, zlib.error, csv.Error, RecursionError)


def expect(condition: bool, path: str, message: str) -> None:
    if not condition:
        raise ValueError(f"{path}: {message}")


@contextmanager
def checking(location: str) -> Iterator[None]:
    """Keep a useful archive locator when a malformed field prevents further checking."""
    try:
        yield
    except OSError as exc:
        if exc.filename is None:
            exc.filename = location
        if operational_read_error(exc) is not None:
            raise
        raise ValueError(f"{location}: {exc}") from exc
    except DATA_ERRORS as exc:
        raise ValueError(f"{location}: {exc}") from exc


def index(rows: list[dict], key: str, loc: str) -> dict[str, dict]:
    expect(isinstance(rows, list), loc, "expected an array")
    result = {}
    for row in rows:
        value = row[key]
        expect(isinstance(value, str) and bool(value) and value not in result, loc,
               f"invalid or duplicate {key} {value!r}")
        result[value] = row
    return result


def file_sha(path: Path) -> str:
    with checking(str(path)), path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


class Archive:
    """Inventory validated portable paths before native readers access any content."""

    def __init__(self, root: Path):
        self.root = root
        self.files: set[str] = set()
        self.dirs: set[str] = set()
        self.used: set[str] = set()
        self.errors: list[str] = []
        self.skipped: list[dict] = []
        self.counts: Counter[str] = Counter()
        self.complete = False

    def scan(self) -> None:
        def visit(directory: Path, prefix: str) -> None:
            siblings = set()
            for member in directory.iterdir():
                name = portable_path(prefix + member.name)
                folded = unicodedata.normalize("NFC", member.name).casefold()
                expect(folded not in siblings, name, "ambiguous portable path")
                siblings.add(folded)
                mode = member.lstat().st_mode
                expect(not member.is_symlink() and not member.is_junction(), name, "linked archive member")
                if stat.S_ISDIR(mode):
                    self.dirs.add(name)
                    visit(member, name + "/")
                else:
                    expect(stat.S_ISREG(mode), name, "expected a regular file")
                    self.files.add(name)

        expect(not self.root.is_symlink() and not self.root.is_junction(), str(self.root),
               "linked archive root")
        visit(self.root, "")

    def file(self, name: str) -> Path:
        expect(portable_path(name) in self.files, name, "missing or misnamed file")
        self.used.add(name)
        return self.root / name

    def json(self, name: str) -> Any:
        with checking(name):
            return document(self.file(name).read_bytes(), name)

    def csv(self, name: str, columns: tuple[str, ...] = ()) -> list[dict[str, str]]:
        with checking(name), self.file(name).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            header = reader.fieldnames or []
            expect(bool(header) and len(set(header)) == len(header) and set(columns) <= set(header),
                   name, "missing or duplicated CSV columns")
            rows = list(reader)
            expect(all(None not in row and None not in row.values() for row in rows), name,
                   "CSV row width differs from header")
            return rows

    def skip(self, scope: str, location: str, reason: str) -> None:
        self.skipped.append(dict(scope=scope, path=location, reason=reason))


def _catalog(a: Archive) -> None:
    name = "checksums.json"
    data = a.json(name)
    expect(data["algorithm"] == "sha256", name, "unsupported algorithm")
    entries = index(data["files"], "path", name)
    for path in entries:
        portable_path(path)
    expected = a.files - {name}
    for path in sorted(expected.symmetric_difference(entries)):
        a.errors.append(f"{path}: checksum catalog differs from archive file inventory")
    for path in sorted(expected.intersection(entries)):
        target, entry = a.file(path), entries[path]
        if (type(entry["bytes"]) is not int or entry["bytes"] != target.stat().st_size
                or entry["sha256"] != file_sha(target)):
            a.errors.append(f"{path}: checksum size or SHA-256 mismatch")
        else:
            a.counts["file_checksums"] += 1


def check_cells(row: dict, expected: dict, loc: str) -> None:
    """Round-trip CSV fields, including nullable values and full-precision observations."""
    for key, value in expected.items():
        actual = row[key]
        if isinstance(value, float):
            matches = actual != "" and math.isfinite(value) and float(actual) == value
        else:
            matches = actual == ("" if value is None else str(value))
        expect(matches, loc, f"CSV {key} differs ({actual!r} vs {value!r})")


def verify_archive(archive: Path, *, check_checksums: bool = True) -> dict:
    """Verify archive evidence without executing archived code or writing a saved report.

    Unknown declared versions raise ValueError. Corruption of recognized or unreadable
    archives is returned as evidence, separately from their recorded completeness.
    The preseal phase precedes creation of verification.json and checksums.json.
    """
    from .archive_verify_legacy import verify_legacy
    from .archive_verify_records import verify_general

    a = Archive(Path(archive))
    version = None
    supported = True
    try:
        a.scan()
        manifest = a.json("manifest.json")
        version = manifest["format"]
        expect(isinstance(version, str), "manifest.json", "invalid archive format")
        supported = version in (PROFILE, GENERAL)
        if supported:
            if check_checksums:
                with checking("checksums.json"):
                    _catalog(a)
            # A corrupt file has no trusted content to feed into subsequent consumers.
            if a.errors:
                a.skip("semantic_checks", ".", "file inventory or content hashes failed")
            else:
                a.used = {"manifest.json"}
                if version == GENERAL:
                    with checking("general archive"):
                        verify_general(a, manifest)
                    if check_checksums:
                        prior = a.json("verification.json")
                        sealed_counts = {r["scope"]: r["count"] for r in prior["checks"]}
                        fresh_counts = {k: v for k, v in a.counts.items() if k != "file_checksums"}
                        expect(prior["errors"] == [] and prior["not_checked"] == a.skipped and sealed_counts == fresh_counts,
                               "verification.json", "prepublication check coverage differs")
                        expect(prior["format"] == version and prior["valid"] is True
                               and prior["complete"] is a.complete, "verification.json",
                               "prepublication report disagrees with archive")
                    unbound = a.files - a.used - {"checksums.json"}
                    expect(not unbound, "manifest.json", f"unreferenced archive files: {sorted(unbound)[:8]}")
                else:
                    with checking("historical archive"):
                        verify_legacy(a, manifest)
    except DATA_ERRORS as exc:
        operational = operational_read_error(exc)
        if operational is not None:
            raise operational
        a.errors.append(str(exc) or type(exc).__name__)
    if not supported:
        raise ValueError(f"Unsupported archive format: {version!r}")
    totals = {}
    if not a.errors:
        keys = ["run_count", "comparison_count", "series_count"]
        if version == GENERAL:
            keys.extend(("planned", "totals"))
        totals = {key: manifest[key] for key in keys}
    return dict(valid=not a.errors, complete=a.complete, format=version, **totals,
                checks=[dict(scope=key, count=value) for key, value in sorted(a.counts.items())],
                errors=a.errors, not_checked=a.skipped)
