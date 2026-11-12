"""Explicit v1-to-v2 migration preserving original manifests and evidence."""
from __future__ import annotations

import copy
import json
import os

from .artifacts import atomic_write, contained, git, load, writer_lock
from .formats import VERSION, digest, new_mathematics, require
from .lint import lint


def migrate(repo, directory, expected):
    manifest_path = directory / "task.json"
    require(not manifest_path.is_symlink(), "Manifest migration does not follow symlinks")
    manifest, revision = load(directory)
    require(expected == revision, "Migration requires the current --expect-sha256")
    lint(repo, directory, manifest, legacy=True)
    require(git(repo, "branch", "--show-current").decode().strip() == manifest["branch"],
            "Migration checkout differs from selected task branch")
    git(repo, "check-ignore", "--no-index", "--", manifest_path.relative_to(repo).as_posix())
    original = manifest_path.read_bytes()
    require(digest(original) == revision, "Manifest changed before migration")
    documents = {contained(directory, item[key]): contained(directory, item[key]).read_bytes()
                 for item in manifest["items"] for key in ("document", "specification") if item[key]}
    converted = copy.deepcopy(manifest)
    converted["format_version"] = VERSION
    for item in converted["items"]:
        item["mathematics"] = new_mathematics()
    lint(repo, directory, converted)
    data = json.dumps(converted, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    backup = directory / "task.v1.backup.json"
    with writer_lock(directory):
        require(manifest_path.read_bytes() == original, "Manifest changed during migration")
        require(all(path.read_bytes() == content for path, content in documents.items()),
                "Task documents changed during migration")
        require(not backup.is_symlink(), "Migration backup must not be a symlink")
        if backup.exists():
            require(backup.read_bytes() == original, "Conflicting migration backup; inspect before continuing")
        else:
            with backup.open("xb") as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
        # Cooperating writers are locked; external editors must also be stopped.
        require(manifest_path.read_bytes() == original, "Manifest changed before replacement")
        atomic_write(manifest_path, data)
    return backup.name
