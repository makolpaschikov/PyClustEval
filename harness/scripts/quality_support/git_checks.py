"""Read-only checks for assigned developer Git work."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from .common import QualityError

COMMANDS = {"staged"}
_FIELDS = {"format_version", "task_id", "developer_id", "repository", "worktree", "branch", "base", "allowed_files", "allowed_directories", "authority"}


def git(repo, *args, index=True, check=True):
    """Run read-only Git in repo; honor an active hook's GIT_INDEX_FILE."""
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_PREFIX", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        env.pop(key, None)
    if not index:
        env.pop("GIT_INDEX_FILE", None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(["git", "--no-replace-objects", "-C", str(repo), *args], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, check=False)
    except OSError as exc:
        raise QualityError(f"Cannot run Git: {exc}") from exc
    if check and result.returncode:
        raise QualityError(f"Git {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result


def _text(data):
    return data.decode("utf-8", "surrogateescape").strip()


def _duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise QualityError(f"Duplicate assignment field: {key}")
        result[key] = value
    return result


def _owned_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    if any(char in value for char in "*?[]:") or value.startswith("/"):
        return False
    parts = value.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def load_assignment(path, sha256):
    """Load and strictly validate assignment v1 and its pinned bytes."""
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise QualityError("Assignment SHA-256 must be 64 hexadecimal characters")
    path = Path(path).resolve(strict=True)
    if any(part.lower() == ".git" for part in path.parts):
        raise QualityError("Assignment must not reference Git internals")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256.lower():
        raise QualityError("Assignment SHA-256 does not match")
    try:
        assignment = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicates)
    except (ValueError, UnicodeError) as exc:
        raise QualityError(f"Invalid assignment JSON: {exc}") from exc
    if not isinstance(assignment, dict) or set(assignment) != _FIELDS:
        raise QualityError("Assignment must contain exactly the v1 fields")
    if type(assignment["format_version"]) is not int or assignment["format_version"] != 1:
        raise QualityError("Unsupported assignment format version")
    for key in ("task_id", "developer_id", "repository", "worktree", "branch", "base"):
        if not isinstance(assignment[key], str) or not assignment[key].strip():
            raise QualityError(f"Assignment {key} must be a nonempty string")
    authority = assignment["authority"]
    if not isinstance(authority, dict) or set(authority) != {"source", "scope"} or any(not isinstance(v, str) or not v.strip() for v in authority.values()):
        raise QualityError("Assignment authority requires nonempty source and scope")
    for key in ("allowed_files", "allowed_directories"):
        items = assignment[key]
        if not isinstance(items, list) or any(not _owned_path(item) for item in items) or len(set(items)) != len(items):
            raise QualityError(f"Invalid assignment {key}: expected unique exact relative POSIX paths")
    if not assignment["allowed_files"] and not assignment["allowed_directories"]:
        raise QualityError("Assignment owned scope is empty")
    for key in ("repository", "worktree"):
        value = Path(assignment[key])
        if not value.is_absolute() or str(value.resolve()) != assignment[key]:
            raise QualityError(f"Assignment {key} must be a resolved absolute path")
    coordinator = Path(assignment["repository"])
    tasks_location = coordinator / ".agent-work" / "tasks"
    tasks = tasks_location.resolve()
    if tasks != tasks_location or not tasks.is_relative_to(coordinator):
        raise QualityError("Assignment task directory must not resolve through a symlink or junction")
    if not path.is_relative_to(tasks) or path == tasks:
        raise QualityError("Assignment must be under coordinator .agent-work/tasks")
    relative = path.relative_to(coordinator).as_posix()
    if any(part.lower() == ".git" for part in path.relative_to(coordinator).parts):
        raise QualityError("Assignment must not reference Git internals")
    if git(coordinator, "check-ignore", "-q", "--", relative, index=False, check=False).returncode != 0:
        raise QualityError("Assignment must be Git-ignored in coordinator checkout")
    return assignment


def validate_checkout(repo, assignment):
    """Validate exact worktree, coordinator, branch and full ancestral base."""
    repo = Path(repo).resolve(strict=True)
    coordinator = Path(assignment["repository"]).resolve(strict=True)
    root = Path(_text(git(repo, "rev-parse", "--show-toplevel", index=False).stdout)).resolve()
    root_coord = Path(_text(git(coordinator, "rev-parse", "--show-toplevel", index=False).stdout)).resolve()
    if repo != root or repo != Path(assignment["worktree"]).resolve() or coordinator != root_coord:
        raise QualityError("Selected checkout or coordinator does not match the assignment")
    def common(p):
        raw = _text(git(p, "rev-parse", "--git-common-dir", index=False).stdout)
        return (p / raw).resolve()
    if common(repo) != common(coordinator):
        raise QualityError("Assignment checkouts do not share a Git common repository")
    branch = git(repo, "symbolic-ref", "--quiet", "HEAD", index=False, check=False)
    if branch.returncode or _text(branch.stdout) != "refs/heads/" + assignment["branch"]:
        raise QualityError("Checkout branch is detached or differs from assignment")
    base = assignment["base"]
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base):
        raise QualityError("Assignment base must be a full lowercase commit ID")
    resolved = _text(git(repo, "rev-parse", "--verify", base + "^{commit}", index=False).stdout)
    if resolved != base:
        raise QualityError("Assignment base must identify a commit directly")
    head = _text(git(repo, "rev-parse", "--verify", "HEAD^{commit}", index=False).stdout)
    if git(repo, "merge-base", "--is-ancestor", base, head, index=False, check=False).returncode:
        raise QualityError("Assignment base is not an ancestor of HEAD")
    return {"head": head, "base": base, "branch": assignment["branch"]}


def changed_paths(raw):
    """Parse git diff --name-status -z, including both rename/copy sides."""
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        raise QualityError("Truncated NUL-delimited Git diff")
    fields = raw[:-1].split(b"\0")
    paths = []
    i = 0
    while i < len(fields):
        status = fields[i].decode("ascii", "strict")
        i += 1
        if not re.fullmatch(r"(?:[ACDMRTUXB][0-9]*|[ACDMRTUXB])", status):
            raise QualityError("Invalid Git diff status")
        count = 2 if status[0] in "RC" else 1
        if i + count > len(fields) or any(not item for item in fields[i:i + count]):
            raise QualityError("Truncated NUL-delimited Git diff")
        paths.extend(item.decode("utf-8", "surrogateescape") for item in fields[i:i + count])
        i += count
    return paths


def path_allowed(path, assignment):
    """Check exact file and directory ownership, excluding local evidence."""
    if not _owned_path(path) or any(part.lower() in {".git", ".agent-work"} for part in path.split("/")):
        return False
    return path in assignment["allowed_files"] or any(path == d or path.startswith(d + "/") for d in assignment["allowed_directories"])


def git_identity(repo):
    """Return HEAD and a fingerprint of the selected index, without writing Git objects."""
    head = _text(git(repo, "rev-parse", "--verify", "HEAD^{commit}", index=False).stdout)
    index_path = Path(_text(git(repo, "rev-parse", "--git-path", "index").stdout))
    if not index_path.is_absolute():
        index_path = Path(repo) / index_path
    index_bytes = index_path.read_bytes() if index_path.exists() else b""
    entries = git(repo, "ls-files", "--stage", "-z").stdout
    cached = git(repo, "diff", "--cached", "--raw", "-z", "--no-ext-diff", "--ignore-submodules=none").stdout
    return {"head": head, "index_sha256": hashlib.sha256(index_bytes + b"\0" + entries + b"\0" + cached).hexdigest()}


def add_commands(subparsers):
    parser = subparsers.add_parser("staged", help="check staged work against an assignment")
    parser.add_argument("--assignment", required=True, type=Path)
    parser.add_argument("--assignment-sha256", required=True)


def run_command(args, repo):
    assignment = load_assignment(args.assignment, args.assignment_sha256)
    checkout = validate_checkout(repo, assignment)
    before = git_identity(repo)
    unmerged = git(repo, "ls-files", "--unmerged", "-z").stdout
    paths = changed_paths(git(repo, "diff", "--cached", "--name-status", "-z", "--find-renames", "--no-ext-diff", "--ignore-submodules=none").stdout)
    remaining = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none").stdout
    after = git_identity(repo)
    again = load_assignment(args.assignment, args.assignment_sha256)
    checkout_after = validate_checkout(repo, again)
    diagnostics = []
    if before != after or checkout != checkout_after or assignment != again:
        diagnostics.append({"code": "changed_input", "message": "Assignment, HEAD, checkout or index changed during the check"})
    if unmerged:
        diagnostics.append({"code": "unmerged", "message": "Index contains unresolved entries"})
    for path in dict.fromkeys(paths):
        if not path_allowed(path, assignment):
            diagnostics.append({"code": "disallowed_path", "path": path, "message": "Staged path is outside the assignment or forbidden"})
    return {"command": "staged", "ok": not diagnostics, "diagnostics": diagnostics,
            "assignment_path": str(Path(args.assignment).resolve()),
            "assignment_sha256": args.assignment_sha256.lower(),
            "task_id": assignment["task_id"], "developer_id": assignment["developer_id"],
            "base": checkout["base"], "branch": checkout["branch"],
            "head": before["head"], "index_sha256": before["index_sha256"],
            "staged_paths": paths, "remaining_status": remaining.decode("utf-8", "surrogateescape").split("\0")[:-1],
            "inspection_required": "Inspect the full staged diff for task compliance."}
