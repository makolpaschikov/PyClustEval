"""Bounded file access, initialization and content snapshots; no task commands run."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile

from .formats import VERSION, TaskError, canonical, digest, identifier, new_item, require

CODE_ROOT = Path(__file__).resolve().parents[4]
TEMPLATES = CODE_ROOT / ".agents/skills/analyst-orchestrator/assets"


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode:
        raise TaskError(result.stderr.decode("utf-8", "replace").strip() or "Git command failed")
    return result.stdout


def repository(path):
    path = Path(path).resolve()
    actual = Path(os.fsdecode(git(path, "rev-parse", "--show-toplevel")).strip()).resolve()
    require(path == actual, "--repo must name the repository root")
    return path


def workspace(repo, path):
    path = Path(path)
    if not path.is_absolute():
        path = repo / path
    path = path.resolve()
    allowed = repo / ".agent-work/tasks"
    require(path.is_relative_to(allowed) and path != allowed,
            "Task directory must be below the repository's .agent-work/tasks/")
    require(not allowed.is_symlink() and not (repo / ".agent-work").is_symlink(),
            "Task workspace must not use symlink roots")
    return path


def contained(directory, name):
    require(isinstance(name, str) and bool(name), "Artifact path must be nonempty text")
    relative = Path(name)
    require(not relative.is_absolute() and ".." not in relative.parts and ":" not in name,
            f"Artifact path must be a safe relative path: {name}")
    target = (directory / relative).resolve()
    require(target.is_relative_to(directory.resolve()) and target != directory.resolve(),
            f"Artifact escapes task directory: {name}")
    return target


def read_json(path):
    def pairs(entries):
        result = {}
        for key, value in entries:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(TaskError(f"Invalid JSON constant: {value}")))
    except (OSError, ValueError) as exc:
        raise TaskError(f"Cannot read {path.name}: {exc}") from exc


def load(directory):
    require(not (directory / ".task.lock").exists(), "Task writer lock exists; inspect its owner")
    raw = (directory / "task.json").read_bytes()
    manifest = read_json(directory / "task.json")
    require((directory / "task.json").read_bytes() == raw, "Manifest changed while reading")
    return manifest, digest(raw)


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".task-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def writer_lock(directory):
    path = directory / ".task.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise TaskError("Task writer lock exists; inspect its owner") from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(f"pid={os.getpid()}\n")
        yield
    finally:
        path.unlink()


def source_snapshot(repo):
    names = sorted(set(git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")) - {b""})
    entries = []
    for raw in names:
        name = os.fsdecode(raw)
        path = repo / name
        require(not path.is_symlink(), f"Source symlink unsupported for snapshots: {name}")
        require(path.resolve().is_relative_to(repo), f"Source path escapes repository: {name}")
        if not path.exists():
            # The absence itself changes the tree digest. Do not encode index-only
            # tombstones: staging/committing a deletion must not change evidence
            # for otherwise identical working-tree content.
            continue
        require(path.is_file(), f"Source entry is not a regular file (submodule?): {name}")
        content = digest(path.read_bytes())
        entries.append([name, content])
    branch = git(repo, "branch", "--show-current").decode().strip()
    require(branch, "Detached HEAD requires an explicit branch choice")
    return {"branch": branch, "source_sha256": digest(canonical(entries))}


def stable_snapshot(repo):
    first = source_snapshot(repo)
    require(first == source_snapshot(repo), "Source changed during snapshot; wait for writers")
    return first


def spec_digest(directory, manifest, item):
    """Bind approval to this brief/spec and all ancestor task contracts."""
    index = {entry["id"]: entry for entry in manifest["items"]}
    values, seen = [], set()
    current = item
    while current is not None:
        require(current["id"] not in seen, "Parent cycle in specification closure")
        seen.add(current["id"])
        for key in ("document", "specification"):
            if current[key]:
                path = contained(directory, current[key])
                values.append([current["id"], key, digest(path.read_bytes())])
        # These fields change the agreement/verification scope, unlike execution status.
        values.append([current["id"], "contract", {
            key: current[key] for key in ("kind", "parent", "depends_on", "scale",
                                          "review_policy", "review_rationale", "coverage", "verification")
        }])
        current = index[current["parent"]] if current["parent"] else None
    values.append(["task", manifest["scope"]])
    return digest(canonical(values))


def initialize(repo, directory, item_id, kind, branch, scope, parent, expected):
    from .lint import lint
    identifier(item_id, "id")
    current_branch = git(repo, "branch", "--show-current").decode().strip()
    require(current_branch and current_branch == branch, "Selected branch does not match checkout")
    # An ignored workspace is part of the artifact contract, including empty/new paths.
    relative = (directory / "task.json").relative_to(repo).as_posix()
    git(repo, "check-ignore", "--no-index", "--", relative)
    existing = (directory / "task.json").exists()
    if existing:
        manifest, revision = load(directory)
        lint(repo, directory, manifest)
        require(expected == revision, "Existing task requires current --expect-sha256 from lint")
        require(manifest["branch"] == branch and manifest["scope"] == scope,
                "Existing task branch/scope differs; do not silently replace it")
    else:
        require(not directory.exists(), "New task directory already exists; inspect it instead of overwriting")
        require(kind != "subtask" and parent is None, "Start with an epic or standalone specification")
        manifest = {"format_version": VERSION, "root": item_id, "branch": branch,
                    "scope": scope, "coordinator": "analyst", "application_authorization": None,
                    "handoff": {"next_action": "", "active_agents": [], "permissions": "", "notes": ""}, "items": []}
        revision = None
    index = {item["id"]: item for item in manifest["items"]}
    if item_id in index:
        item = index[item_id]
        require(kind == "specification" and item["kind"] == "subtask" and item["specification"] is None,
                "Only a missing subtask specification may be added to an existing ID")
        require(parent is None or parent == item["parent"], "Parent differs from existing subtask")
        filename = f"items/{item_id}/specification.md"
        item["specification"] = filename
    else:
        if existing:
            require(kind == "subtask" and parent in index and index[parent]["kind"] == "epic",
                    "Additional items must be subtasks of an existing epic")
        filename = f"items/{item_id}/{kind}.md"
        manifest["items"].append(new_item(item_id, kind, parent, filename))
    template = (TEMPLATES / f"{kind}.md").read_text(encoding="utf-8")
    content = template.replace("{{ID}}", item_id).replace("{{PARENT}}", parent or "None")
    # Templates are checked by the same parser as generated documents.
    from .lint import parse_document
    parse_document(content, kind, item_id)
    directory.mkdir(parents=True, exist_ok=existing)
    with writer_lock(directory):
        manifest_path = directory / "task.json"
        if existing:
            require(digest(manifest_path.read_bytes()) == revision, "Task changed before initialization")
        else:
            require(not manifest_path.exists(), "Task appeared during initialization")
        target = contained(directory, filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        require(not target.exists(), "Document already exists; no overwrite")
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        try:
            lint(repo, directory, manifest)
            atomic_write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
        except Exception:
            target.unlink()
            raise
    return manifest
