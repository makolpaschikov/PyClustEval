"""Read-only inspection of every commit delivered under an assignment."""
from __future__ import annotations

from pathlib import Path
import re

from .common import QualityError
from .git_checks import changed_paths, git, git_identity, load_assignment, path_allowed, validate_checkout

COMMANDS = {"handoff"}


def add_commands(subparsers):
    parser = subparsers.add_parser("handoff", help="check each delivered commit against an assignment")
    parser.add_argument("--assignment", required=True, type=Path)
    parser.add_argument("--assignment-sha256", required=True)
    parser.add_argument("--head", required=True, help="full delivered commit ID")


def run_command(args, repo):
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", args.head):
        raise QualityError("Delivered HEAD must be a full lowercase commit ID")
    assignment = load_assignment(args.assignment, args.assignment_sha256)
    checkout = validate_checkout(repo, assignment)
    before = git_identity(repo)
    if args.head != checkout["head"] or args.head != before["head"]:
        raise QualityError("Delivered HEAD does not match checkout HEAD")
    status = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none").stdout
    unmerged = git(repo, "ls-files", "--unmerged", "-z").stdout
    history = git(repo, "rev-list", "--reverse", "--parents", f"{checkout['base']}..{args.head}", index=False).stdout.decode("ascii").splitlines()
    diagnostics = []
    commits = []
    for line in history:
        ids = line.split()
        if len(ids) != 2:
            diagnostics.append({"code": "unsupported_history", "message": f"Commit {ids[0]} is a merge or has no parent; linear history is required"})
            continue
        commit, parent = ids
        raw = git(repo, "diff", "--name-status", "-z", "--find-renames", "--no-ext-diff", "--ignore-submodules=none", parent, commit, "--", index=False).stdout
        paths = changed_paths(raw)
        commits.append({"commit": commit, "parent": parent, "paths": paths})
        for path in dict.fromkeys(paths):
            if not path_allowed(path, assignment):
                diagnostics.append({"code": "disallowed_path", "commit": commit, "path": path,
                                    "message": "Committed path is outside the assignment or forbidden"})
    if unmerged:
        diagnostics.append({"code": "unmerged", "message": "Index contains unresolved entries"})
    status_after = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none").stdout
    after = git_identity(repo)
    again = load_assignment(args.assignment, args.assignment_sha256)
    checkout_after = validate_checkout(repo, again)
    if before != after or checkout != checkout_after or assignment != again or status != status_after:
        diagnostics.append({"code": "changed_input", "message": "Assignment, checkout, HEAD, index or remaining status changed during the check"})
    return {"command": "handoff", "ok": not diagnostics, "diagnostics": diagnostics,
            "assignment_path": str(Path(args.assignment).resolve()), "assignment_sha256": args.assignment_sha256.lower(),
            "task_id": assignment["task_id"], "developer_id": assignment["developer_id"],
            "base": checkout["base"], "branch": checkout["branch"], "head": before["head"],
            "index_sha256": before["index_sha256"], "commits": commits,
            "remaining_status": status.decode("utf-8", "surrogateescape").split("\0")[:-1],
            "worktree_clean": not status,
            "inspection_required": "Inspect the full committed diffs and remaining work for task compliance; path checks do not establish acceptance."}
