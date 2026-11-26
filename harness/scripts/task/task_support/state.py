"""Transactional task mutation and checkpoint/completion commands."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

from .artifacts import (atomic_write, contained, git, load, stable_snapshot,
                        workspace, writer_lock)
from .formats import canonical, digest, nonempty, require, sha
from .gates import check_gate
from .lint import lint

COMMANDS = ("checkpoint", "complete")


def add_commands(subparsers):
    for name in COMMANDS:
        parser = subparsers.add_parser(name)
        parser.add_argument("directory", type=Path)
        parser.add_argument("--id", required=True)
        parser.add_argument("--expect-sha256", required=True)
        if name == "checkpoint":
            parser.add_argument("--reason")


def _references(directory, manifest):
    names = set()
    for item in manifest["items"]:
        names.update(item[key] for key in ("document", "specification") if item[key])
        records = item["spec_reviews"] + item["checks"]
        records += [item["code_review"], item["mathematics"]["specification_review"],
                    item["mathematics"]["implementation_review"]]
        names.update(record["artifact"] for record in records if record is not None)
    result = {}
    for name in names:
        path = contained(directory, name)
        if not path.is_file():
            result[name] = None
            continue
        fingerprint = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                fingerprint.update(chunk)
        result[name] = fingerprint.hexdigest()
    return result


def _evidence_bindings(manifest):
    """Index evidence records by item and role without requiring gate completion."""
    result = {}
    for item in manifest["items"]:
        item_id = item["id"]
        for record in item["spec_reviews"]:
            result[(item_id, "spec_review", record["kind"])] = record
        for record in item["checks"]:
            result[(item_id, "check", record["id"])] = record
        for role, record in (("code_review", item["code_review"]),
                             ("math_specification", item["mathematics"]["specification_review"]),
                             ("math_implementation", item["mathematics"]["implementation_review"])):
            if record is not None:
                result[(item_id, role)] = record
    return result

def _write_once(path, data):
    require(not path.is_symlink(), f"History file is a symlink: {path.name}")
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        require(path.is_file() and path.read_bytes() == data,
                f"Conflicting history file: {path.name}")


@contextmanager
def _owned_lock(directory, outcome):
    """Attach cleanup failures only after the mutation body has completed."""
    try:
        with writer_lock(directory):
            yield
    except OSError as exc:
        if not outcome:
            raise
        outcome[0]["cleanup_error"] = str(exc)

def mutate_task(repo, directory, expected, operation, change, reason=None):
    """Apply change(candidate, snapshot) under a cooperative compare-and-swap lock."""
    repo, directory = Path(repo).resolve(), workspace(Path(repo).resolve(), directory)
    sha(expected, "expected manifest SHA-256")
    nonempty(operation, "operation")
    if reason is not None:
        nonempty(reason, "reason")
    path = directory / "task.json"
    require(not path.is_symlink(), "Manifest must not be a symlink")
    git(repo, "check-ignore", "--", path.relative_to(repo).as_posix())
    manifest, revision = load(directory)
    require(expected == revision, "Expected manifest SHA-256 is stale")
    original = path.read_bytes()
    require(digest(original) == revision, "Manifest changed before mutation")
    outcome = []
    with _owned_lock(directory, outcome):
        # load() intentionally refuses every lock; ownership is established by
        # writer_lock above, so inspect the exact bytes already parsed by load().
        require(not path.is_symlink() and path.read_bytes() == original,
                "Manifest changed before lock acquisition")
        lint(repo, directory, manifest)
        refs = _references(directory, manifest)
        lint(repo, directory, manifest)
        snapshot = stable_snapshot(repo)
        require(snapshot["branch"] == manifest["branch"], "Checkout differs from selected task branch")
        candidate = copy.deepcopy(manifest)
        change(candidate, snapshot)
        lint(repo, directory, candidate)
        new_refs = _references(directory, candidate)
        old_evidence = _evidence_bindings(manifest)
        for key, record in _evidence_bindings(candidate).items():
            if old_evidence.get(key) != record:
                require(new_refs[record["artifact"]] == record["sha256"],
                        f"New or changed evidence content differs from its binding: {record['artifact']}")
        for name in refs.keys() & new_refs.keys():
            require(refs[name] == new_refs[name], f"Referenced task input changed: {name}")
        require(path.read_bytes() == original, "Manifest changed during mutation")
        require(snapshot == stable_snapshot(repo), "Source changed during mutation")
        require(refs == _references(directory, manifest) and new_refs == _references(directory, candidate),
                "Referenced task document or evidence changed during mutation")
        if candidate == manifest:
            report = {"command": operation, "changed": False, "before_sha256": revision,
                      "manifest_sha256": revision}
            outcome.append(report)
            return report
        data = json.dumps(candidate, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        after = digest(data)
        history = directory / ".state-history"
        require(not history.is_symlink(), "History directory must not be a symlink")
        history.mkdir(exist_ok=True)
        require(history.is_dir() and history.resolve().parent == directory.resolve(), "Invalid history directory")
        _write_once(history / f"{revision}.json", original)
        record = {"format_version": 1, "operation": operation, "reason": reason,
                  "before_sha256": revision, "after_sha256": after,
                  "source_snapshot": snapshot,
                  "before_references": dict(sorted(refs.items())),
                  "after_references": dict(sorted(new_refs.items()))}
        record_bytes = canonical(record) + b"\n"
        _write_once(history / f"operation-{digest(record_bytes)}.json", record_bytes)
        require(not path.is_symlink() and path.read_bytes() == original, "Manifest changed before replacement")
        require(snapshot == stable_snapshot(repo), "Source changed before replacement")
        require(refs == _references(directory, manifest) and new_refs == _references(directory, candidate),
                "Referenced task document or evidence changed before replacement")
        atomic_write(path, data)
        report = {"command": operation, "changed": True, "before_sha256": revision,
                  "manifest_sha256": after}
        outcome.append(report)
        return report


def run_command(args, repo):
    directory = workspace(repo, args.directory)
    def change(candidate, snapshot):
        index, _ = lint(repo, directory, candidate)
        require(args.id in index, f"Unknown item: {args.id}")
        item = index[args.id]
        if args.command == "complete":
            receipt = check_gate(repo, directory, candidate, args.id, "completion", snapshot)
            item["status"] = "done"
            item["completion"] = receipt
            item["checkpoint"] = receipt.copy()
        else:
            from .artifacts import spec_digest
            receipt = {"spec_sha256": spec_digest(directory, candidate, item),
                       "source_sha256": snapshot["source_sha256"]}
            if item["checkpoint"] is not None and item["checkpoint"] != receipt:
                nonempty(args.reason, "Reconciliation reason")
            item["checkpoint"] = receipt
        check_gate(repo, directory, candidate, args.id, "resumption", snapshot)
    report = mutate_task(repo, directory, args.expect_sha256, args.command, change,
                         getattr(args, "reason", None))
    return report, 1 if "cleanup_error" in report else 0
