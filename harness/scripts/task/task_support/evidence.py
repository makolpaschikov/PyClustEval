"""Package and explicitly adopt immutable task evidence."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unicodedata

from . import bundles
from .artifacts import git, read_json, repository, spec_digest, workspace
from .formats import TaskError, digest, require
from .lint import lint
from .mathematics import exclusions, scope_digest
from .snapshots import capture_context
from .state import mutate_task

COMMANDS = ("package-review", "inspect-evidence", "import-evidence")
KINDS = ("spec_review", "code_review", "math_specification", "math_implementation")
BINDINGS = ("task_root", "item_id", "spec_sha256", "source_sha256", "stage", "scope_sha256")


def add_commands(subparsers):
    package = subparsers.add_parser("package-review")
    package.add_argument("directory", type=Path)
    package.add_argument("--id", required=True)
    package.add_argument("--kind", choices=KINDS, required=True)
    package.add_argument("--before", type=Path, required=True)
    package.add_argument("--descriptor", type=Path, required=True)
    package.add_argument("--report", type=Path, required=True)
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--source-repo", type=Path)
    inspect = subparsers.add_parser("inspect-evidence")
    inspect.add_argument("--bundle", type=Path, required=True)
    inspect.add_argument("--text-payload", help="return one UTF-8 text payload without extracting it")
    imp = subparsers.add_parser("import-evidence")
    imp.add_argument("directory", type=Path)
    imp.add_argument("--bundle", type=Path, required=True)
    imp.add_argument("--adopt", action="store_true")
    imp.add_argument("--expect-sha256")


def _safe_path(path):
    path = Path(os.path.abspath(path))
    require(path.resolve() == path, f"Redirected path is unsupported: {path}")
    for part in (path, *path.parents):
        require(not part.is_symlink(), f"Symlink path is unsupported: {part}")
    return path


def _bytes(path):
    path = _safe_path(path)
    require(path.is_file(), f"Not a regular file: {path}")
    require(path.stat().st_size <= bundles.MAX_ARCHIVE_SIZE, f"File exceeds size limit: {path}")
    first = path.read_bytes()
    require(path.read_bytes() == first and not path.is_symlink(), f"File changed while reading: {path}")
    return first


def _binding_equal(left, right):
    return all(left[key] == right[key] for key in BINDINGS)


def _destination(repo, directory, content):
    target_dir = _safe_path(directory / "evidence")
    require(target_dir.parent == directory, "Invalid evidence directory")
    git(repo, "check-ignore", "--no-index", "--", (target_dir / "archive.zip").relative_to(repo).as_posix())
    target_dir.mkdir(exist_ok=True)
    require(target_dir.is_dir() and not target_dir.is_symlink() and target_dir.resolve() == target_dir, "Invalid evidence directory")
    target = target_dir / (digest(content) + ".zip")
    if target.exists() or target.is_symlink():
        require(not target.is_symlink() and target.is_file() and _bytes(target) == content,
                "Conflicting evidence archive")
        return target, None, None
    fd, name = tempfile.mkstemp(prefix=".import-", dir=target_dir)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            _safe_path(target)
            os.link(temporary, target)
        except FileExistsError:
            require(not target.is_symlink() and target.is_file() and _bytes(target) == content,
                    "Conflicting evidence archive")
        require(_bytes(target) == content, "Imported archive changed")
    except BaseException as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as cleanup:
            if hasattr(exc, "add_note"):
                exc.add_note(f"Temporary file retained at {temporary}; cleanup failed: {cleanup}")
        raise
    try:
        temporary.unlink(missing_ok=True)
    except OSError as exc:
        return target, str(exc), temporary
    return target, None, None


def _adopt(candidate, snapshot, directory, metadata, artifact, archive_hash):
    before, after = metadata["before"], metadata["after"]
    require(after is not None and _binding_equal(before, after), "Evidence inputs changed or are unavailable")
    index = {item["id"]: item for item in candidate["items"]}
    require(before["task_root"] == candidate["root"] and before["item_id"] in index, "Evidence task/item does not match")
    item = index[before["item_id"]]
    require(before["spec_sha256"] == spec_digest(directory, candidate, item), "Evidence specification is stale")
    require(before["source_sha256"] == snapshot["source_sha256"], "Evidence source is stale")
    kind, record = metadata["kind"], dict(metadata["record"])
    stage = {"math_specification": "specification", "math_implementation": "implementation"}.get(kind)
    require(before["stage"] == stage, "Evidence review stage differs")
    if stage:
        require(item["mathematics"]["required"] is True, "Mathematical review is not selected")
        require(before["scope_sha256"] == scope_digest(directory, candidate, item, stage), "Mathematical scope is stale")
        require(record["reviewer"] not in exclusions(index, item, candidate["coordinator"], stage), "Mathematical reviewer is not independent")
    record.update(artifact=artifact, sha256=archive_hash, spec_sha256=before["spec_sha256"])
    if kind in ("check", "code_review", "math_implementation"):
        record["source_sha256"] = before["source_sha256"]
    if stage:
        record["scope_sha256"] = before["scope_sha256"]
    if kind == "check":
        require(record["id"] in {c for checks in item["verification"].values() for c in checks}, "Check is not planned")
        execution = metadata["execution"]
        require(execution["inputs_stable"] and execution["reason"] != "input_drift", "Check inputs were not stable")
        item["checks"] = [old for old in item["checks"] if old["id"] != record["id"]] + [record]
    else:
        require(record["verdict"] != "incomplete", "Incomplete review cannot be adopted")
        if kind == "spec_review":
            expected = {"readiness", "alignment"} if item["review_policy"] == "separate" else {"combined"}
            require(record["kind"] in expected, "Specification review kind is not selected")
            require(record["reviewer"] != candidate["coordinator"], "Specification reviewer must differ from coordinator")
            others = [old for old in item["spec_reviews"] if old["kind"] != record["kind"]]
            require(all(old["reviewer"] != record["reviewer"] for old in others), "Separate specification reviews require separate reviewers")
            item["spec_reviews"] = others + [record]
        elif kind == "code_review":
            contributors = set(item["contributors"])
            if item["kind"] == "epic":
                for child in index.values():
                    if child["parent"] == item["id"]:
                        contributors.update(child["contributors"])
            require(record["reviewer"] not in contributors | {candidate["coordinator"]}, "Implementation reviewer is not independent")
            item["code_review"] = record
        else:
            item["mathematics"][stage + "_review"] = record


def run_command(args, repo):
    if args.command == "inspect-evidence":
        raw = _bytes(args.bundle)
        metadata, payloads = bundles.read_bundle(_safe_path(args.bundle))
        require(_bytes(args.bundle) == raw, "Bundle changed during inspection")
        result = {"command": args.command, "sha256": digest(raw), "metadata": metadata}
        if args.text_payload is not None:
            require(args.text_payload in payloads, "Selected text payload does not exist")
            try:
                text = payloads[args.text_payload].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise TaskError("Selected payload is not UTF-8 text") from exc
            require(all(ch in "\t\n\r" or unicodedata.category(ch) != "Cc" for ch in text),
                    "Selected payload contains binary control characters")
            result["text_payload"] = {"path": args.text_payload, "text": text}
        return result, 0
    _safe_path(args.directory if args.directory.is_absolute() else repo / args.directory)
    directory = workspace(repo, args.directory)
    if args.command == "package-review":
        source = repository(args.source_repo) if args.source_repo else repo
        output = _safe_path(args.output if args.output.is_absolute() else source / args.output)
        workspace(source, output.parent)
        git(source, "check-ignore", "--no-index", "--", output.relative_to(source).as_posix())
        before_raw = _bytes(args.before)
        descriptor_raw = _bytes(args.descriptor)
        before = read_json(_safe_path(args.before))
        bundles.validate_context(before)
        descriptor = read_json(_safe_path(args.descriptor))
        require(_bytes(args.before) == before_raw and _bytes(args.descriptor) == descriptor_raw, "Review inputs changed during reading")
        report = _bytes(args.report)
        stage = {"math_specification": "specification", "math_implementation": "implementation"}.get(args.kind)
        after = capture_context(repo, directory, args.id, source, stage)
        require(_bytes(args.before) == before_raw and _bytes(args.descriptor) == descriptor_raw and _bytes(args.report) == report, "Review inputs changed during capture")
        require(before.get("item_id") == args.id and before.get("task_root") == after["task_root"] and before.get("stage") == stage, "Before context does not match selected task/item/stage")
        metadata = {"format_version": 1, "kind": args.kind, "before": before, "after": after,
                    "record": descriptor, "execution": None}
        bundles.write_bundle(output, metadata, {"report.bin": report})
        return {"command": args.command, "bundle": str(output), "sha256": digest(_bytes(output)),
                "inputs_stable": _binding_equal(before, after)}, 0
    require(args.adopt or args.expect_sha256 is None, "--expect-sha256 requires --adopt")
    require(not args.adopt or args.expect_sha256 is not None, "--adopt requires --expect-sha256")
    raw = _bytes(args.bundle)
    metadata, _ = bundles.read_bundle(_safe_path(args.bundle))
    require(_bytes(args.bundle) == raw, "Bundle changed during validation")
    target, cleanup_error, retained_temporary = _destination(repo, directory, raw)
    require(_bytes(args.bundle) == raw and _bytes(target) == raw, "Bundle changed during import")
    result = {"command": args.command, "bundle": str(target), "sha256": digest(raw), "adopted": False}
    if cleanup_error is not None:
        result.update(cleanup_error=cleanup_error, retained_temporary=str(retained_temporary))
        return result, 1
    if args.adopt:
        def change(candidate, snapshot):
            _adopt(candidate, snapshot, directory, metadata, target.relative_to(directory).as_posix(), digest(raw))
            require(_bytes(args.bundle) == raw and _bytes(target) == raw, "Bundle changed during adoption")
        try:
            result.update(mutate_task(repo, directory, args.expect_sha256, args.command, change))
        except (TaskError, OSError, UnicodeError, ValueError) as exc:
            result["error"] = str(exc)
            return result, 1
        result["adopted"] = True
    return result, 1 if "cleanup_error" in result else 0
