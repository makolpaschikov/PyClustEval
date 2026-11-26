"""Copy native comparisons from an exported archive to a history directory.

This module is also distributed as merge_history.py and uses only the standard library.
"""

from __future__ import annotations

import argparse
from hashlib import file_digest, sha256
import json
from pathlib import Path, PureWindowsPath
import shutil
import stat
from tempfile import TemporaryDirectory
import unicodedata
from collections.abc import Iterator


GENERAL = "pyclusteval.campaign-archive.v1"
HISTORICAL = "pyclusteval.three-datasets-three-seeds.v1"


def _alias(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _linked(path: Path) -> bool:
    attrs = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _parts(name: str) -> list[str]:
    if not isinstance(name, str) or not name:
        raise ValueError(f"Invalid archive reference: {name!r}")
    parts = name.split("/")
    for part in parts:
        if (not part or part in (".", "..") or part.endswith((".", " "))
                or PureWindowsPath(part).is_reserved()
                or any(ord(c) < 32 or c in '\\:<>"|?*' for c in part)):
            raise ValueError(f"Nonportable archive reference: {name!r}")
    return parts


def archive_path(root: Path, name: str) -> Path:
    """Resolve an existing archive reference without following links or junctions."""
    current = root
    for part in _parts(name):
        current = current / part
        if _linked(current):
            raise ValueError(f"Linked archive path: {current}")
    return current


def manifest_at(root: Path) -> dict:
    manifest = json.loads(archive_path(root, "manifest.json").read_text(encoding="utf-8"))
    if manifest["format"] not in (GENERAL, HISTORICAL):
        raise ValueError(f"Unsupported archive format: {manifest['format']!r}")
    return manifest


def _destination_name(series: str, history_key: str) -> str:
    name = series + "_" + history_key
    if len(name.encode("utf-8")) > 240:
        return "comparison-" + sha256(json.dumps([series, history_key], ensure_ascii=False).encode()).hexdigest()
    return name


def native_histories(root: Path, manifest: dict) -> Iterator[tuple[str, str, Path]]:
    """Yield declared (series, scenario, native report) records for either archive version."""
    locations = {}
    prefixes = set()
    names = set()
    for series in manifest["series"]:
        name = series["name"]
        if len(_parts(name)) != 1 or _alias(name) in names or _alias(series["path"]) in prefixes:
            raise ValueError(f"Ambiguous archive series: {name!r}")
        names.add(_alias(name))
        prefixes.add(_alias(series["path"]))
        locations[name] = archive_path(root, series["path"])

    if manifest["format"] == GENERAL:
        sources = ((item["series"], item["scenario"], archive_path(root, item["history_report"]))
                   for item in manifest["comparisons"] if item["history_report"] is not None)
    else:
        def historical_records() -> Iterator[tuple[str, str, Path]]:
            for name, folder in locations.items():
                series_report = json.loads(archive_path(folder, "report.json").read_text(encoding="utf-8"))
                for item in series_report["experiments"]:
                    yield name, item["scenario"], archive_path(folder, item["history_report"])
        sources = historical_records()
    seen = set()
    for series, scenario, path in sources:
        if (series not in locations or path.name != "report.json" or not path.is_file()
                or path.parent.parent != locations[series] / "history"):
            raise ValueError(f"Invalid native history for {series!r}: {path}")
        key = _alias(_destination_name(series, path.parent.name))
        if key in seen:
            raise ValueError(f"Duplicate native history key: {key}")
        seen.add(key)
        yield series, scenario, path


def _inventory(directory: Path) -> dict[str, str | None]:
    """Hash the contents of a history, including the names of empty directories."""
    if _linked(directory) or not directory.is_dir():
        raise ValueError(f"Expected an ordinary history directory: {directory}")
    output = {}
    def visit(folder: Path) -> None:
        names = set()
        for child in folder.iterdir():
            _parts(child.name)
            if _linked(child) or _alias(child.name) in names:
                raise ValueError(f"Linked or ambiguous history member: {child}")
            names.add(_alias(child.name))
            key = child.relative_to(directory).as_posix()
            if child.is_dir():
                output[key] = None
                visit(child)
            elif child.is_file():
                with child.open("rb") as stream:
                    output[key] = file_digest(stream, "sha256").hexdigest()
            else:
                raise ValueError(f"Unsupported history member: {child}")
    visit(directory)
    return output


def merge_history(archive: Path, destination: Path) -> dict:
    """Import new histories, skip byte-identical copies and report other collisions."""
    archive = archive.resolve(strict=True)
    if destination.is_symlink() or (destination.exists() and _linked(destination)):
        raise ValueError(f"Linked import destination: {destination}")
    destination = destination.resolve()
    if destination.is_relative_to(archive):
        raise ValueError("Import destination is inside the source archive")
    sources = list(native_histories(archive, manifest_at(archive)))
    destination.mkdir(parents=True, exist_ok=True)
    existing = {_alias(path.name): path for path in destination.iterdir()}
    copied = skipped = 0
    conflicts = []
    for series, _, report in sources:
        name = _destination_name(series, report.parent.name)
        target = destination / name
        original = _inventory(report.parent)
        collision = existing.get(_alias(name))
        if collision is None:
            # A reader must never see a half-copied report. Keep the staged native
            # directory nested so HistoryQueryService cannot discover it.
            with TemporaryDirectory(prefix=".history-import-", dir=destination) as temp:
                staged = Path(temp) / "entry"
                shutil.copytree(report.parent, staged, symlinks=True)
                if _inventory(staged) != original:
                    raise ValueError(f"History changed during import: {report.parent}")
                try:
                    staged.rename(target)
                except OSError:
                    if not target.exists() and not target.is_symlink():
                        raise
                    collision = target
                else:
                    copied += 1
                    existing[_alias(name)] = target
                    continue
        try:
            identical = collision.name == name and collision.is_dir() and _inventory(collision) == original
        except ValueError:
            identical = False
        if identical:
            skipped += 1
        else:
            conflicts.append(str(collision))
    return {"copied": copied, "skipped": skipped, "conflicts": conflicts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--into", type=Path, required=True, help="PyClustEval history directory")
    parser.add_argument("--archive", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try:
        outcome = merge_history(args.archive, args.into)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"History import failed: {error}\n")
    print(json.dumps(outcome))
    return 3 if outcome["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
