"""Read-only CLI bindings for source, task contracts and mathematical scope."""
from __future__ import annotations

from pathlib import Path
import subprocess

from .artifacts import contained, git, load, repository, source_snapshot, spec_digest, workspace
from .formats import TaskError, digest, identifier, require
from .lint import lint
from .mathematics import review_scope, scope_digest


COMMANDS = ("source-snapshot", "context", "math-scope")
STAGES = ("specification", "implementation")


def add_commands(subparsers):
    subparsers.add_parser("source-snapshot", help="inspect source content without a task")
    context = subparsers.add_parser("context", help="capture task and source bindings")
    math_scope = subparsers.add_parser("math-scope", help="inspect a mathematical review scope")
    for command in (context, math_scope):
        command.add_argument("directory", type=Path)
        command.add_argument("--id", required=True)
        command.add_argument("--stage", choices=STAGES, required=command is math_scope)
    context.add_argument("--source-repo", type=Path,
                         help="source checkout root when different from the task repository")


def _source_inputs(repo):
    snapshot = source_snapshot(repo)
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", "HEAD^{commit}"],
        capture_output=True,
    )
    if head.returncode == 1 and not head.stderr:
        commit = None  # The branch exists symbolically before its first commit.
    else:
        require(head.returncode == 0, head.stderr.decode("utf-8", "replace").strip() or "Cannot resolve HEAD")
        commit = head.stdout.decode("ascii").strip()
    return {**snapshot, "origin": {
        "repository": str(repo), "branch": snapshot["branch"], "head": commit,
    }}


def _load_task(repo, directory):
    path = directory / "task.json"
    require(not path.is_symlink(), "Task manifest must not be a symlink")
    try:
        git(repo, "check-ignore", "--quiet", "--", path.relative_to(repo).as_posix())
    except TaskError as exc:
        raise TaskError("Task manifest must be ignored by Git") from exc
    return load(directory)


def _document_inputs(directory, manifest):
    # Lint inspects every declared contract. Record their bytes and resolved paths
    # on both sides of lint and binding calculation, including unclassified items.
    require(isinstance(manifest, dict) and isinstance(manifest.get("items"), list),
            "task.json: expected an items list")
    documents = {}
    for item in manifest["items"]:
        require(isinstance(item, dict), "item: expected an object")
        for key in ("document", "specification"):
            name = item.get(key)
            if name is not None:
                path = contained(directory, name)
                documents[name] = (path, digest(path.read_bytes()))
    return documents


def _task_branch(repo):
    return git(repo, "branch", "--show-current").decode("utf-8").strip()


def _capture(repo, directory, item_id, source_repo, stage):
    repo = repository(repo)
    directory = workspace(repo, directory)
    source_repo = repo if source_repo is None else repository(source_repo)
    identifier(item_id, "id")
    require(stage is None or stage in STAGES, "Invalid mathematical review stage")
    manifest, revision = _load_task(repo, directory)
    source = _source_inputs(source_repo)
    branch = source["branch"] if source_repo == repo else _task_branch(repo)
    documents = _document_inputs(directory, manifest)
    index, _ = lint(repo, directory, manifest)
    require(branch and branch == manifest["branch"], "Checkout differs from selected task branch")
    require(item_id in index, f"Unknown item: {item_id}")
    item = index[item_id]
    context = {
        "format_version": 1,
        "task_root": manifest["root"],
        "item_id": item_id,
        "spec_sha256": spec_digest(directory, manifest, item),
        "source_sha256": source["source_sha256"],
        "stage": stage,
        "scope_sha256": None,
        "origin": source["origin"],
    }
    included = []
    if stage is not None:
        context["scope_sha256"] = scope_digest(directory, manifest, item, stage)
        scope = review_scope(index, item, descendants=stage == "implementation")
        included = [
            {
                "id": entry["id"],
                "document": entry["document"],
                "specification": entry["specification"],
                "required": entry["mathematics"]["required"],
                "rationale": entry["mathematics"]["rationale"],
            }
            for entry in sorted(scope, key=lambda entry: entry["id"])
        ]

    require(_source_inputs(source_repo) == source, "Source changed during context capture; retry when writers stop")
    if source_repo != repo:
        require(_task_branch(repo) == branch, "Task branch changed during context capture")
    require(_document_inputs(directory, manifest) == documents, "Task documents changed during context capture")
    require(_load_task(repo, directory)[1] == revision, "Manifest changed during context capture")
    return context, included


def capture_context(repo, directory, item_id, source_repo=None, stage=None):
    """Capture context-v1 with the task in its canonical repository."""
    context, _ = _capture(repo, directory, item_id, source_repo, stage)
    return context


def run_command(args, repo):
    if args.command == "source-snapshot":
        source = _source_inputs(repo)
        require(_source_inputs(repo) == source, "Source changed during snapshot; retry when writers stop")
        return {"command": args.command, **source}, 0
    if args.command == "context":
        return capture_context(repo, args.directory, args.id, args.source_repo, args.stage), 0
    context, items = _capture(repo, args.directory, args.id, None, args.stage)
    return {**context, "items": items}, 0
