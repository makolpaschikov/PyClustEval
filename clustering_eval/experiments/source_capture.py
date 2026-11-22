"""Capture the working PyClustEval source used by a local campaign."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .source_archive import (
    CHECKS, FORMAT, PATCH_NAME, RECORD_NAME, REQUIRED, ZIP_NAME,
    SourceSnapshot, SourceSnapshotError, content_id, portable_path,
    validate_members, verify_source_snapshot,
)

_PACKAGE = "clustering_eval/"
_EXCLUDED = {"__pycache__", "build", "dist", "venv"}


def _git_environment() -> dict[str, str]:
    selectors = {"GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE"}
    return {key: value for key, value in os.environ.items() if key not in selectors}


def _git(root: Path, *args: str, env: dict[str, str] | None = None, data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "--no-optional-locks", "--literal-pathspecs", "-C", str(root), *args],
        input=data, capture_output=True, env=_git_environment() if env is None else env, check=False,
    )
    if result.returncode:
        reason = result.stderr.decode("utf-8", errors="replace").strip()
        raise SourceSnapshotError(f"git {args[0]} in {root}: {reason}")
    return result.stdout


def _names(raw: bytes) -> set[str]:
    return {os.fsdecode(name) for name in raw.split(b"\0") if name}


def _source_file(root: Path, name: str) -> Path:
    target = root / portable_path(name)
    current = root
    for part in name.split("/"):
        current /= part
        if current.is_symlink() or current.is_junction():
            raise SourceSnapshotError(f"Linked source path: {name}")
    if not target.is_file():
        raise SourceSnapshotError(f"Missing or non-regular source: {name}")
    return target


def _resources(metadata: bytes) -> set[str]:
    """Resolve literal package-data entries from the project's build metadata."""
    settings = tomllib.loads(metadata.decode("utf-8"))
    for key in ("tool", "setuptools", "package-data"):
        settings = settings.get(key, {})
        if not isinstance(settings, dict):
            raise SourceSnapshotError(f"Expected a TOML table for {key} in pyproject.toml")
    resources = set()
    for package, patterns in settings.items():
        if not all(part.isidentifier() for part in package.split(".")) or package.split(".")[0] != "clustering_eval":
            raise SourceSnapshotError(f"Unsupported package-data package: {package}")
        if not isinstance(patterns, list):
            raise SourceSnapshotError(f"Invalid package-data list for {package}")
        for pattern in patterns:
            if not isinstance(pattern, str) or any(c in pattern for c in "*?[]"):
                raise SourceSnapshotError(f"Unsupported package-data pattern: {pattern!r}")
            name = portable_path(f"{package.replace('.', '/')}/{pattern}")
            if any(part.startswith(".") or part in _EXCLUDED for part in name.split("/")):
                raise SourceSnapshotError(f"Unsupported package-data path: {name}")
            resources.add(name)
    return resources


def _package_source(name: str) -> bool:
    return (name.startswith(_PACKAGE) and name.endswith(".py")
            and not any(part.startswith(".") or part in _EXCLUDED for part in name.split("/")))


def _read_checkout(root: Path, scripts: set[str]) -> tuple[str, dict[str, bytes]]:
    head = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
    metadata = _source_file(root, "pyproject.toml").read_bytes()
    names = REQUIRED | _resources(metadata) | scripts
    # Include ignored but importable Python sources too. The index also exposes
    # vanished tracked files that a filesystem walk alone would silently miss.
    candidates = _names(_git(root, "ls-files", "-z", "--cached", "--others", "--", "clustering_eval"))
    for name in candidates:
        if _package_source(name):
            names.add(name)
        elif not any(part.startswith(".") or part in _EXCLUDED for part in name.split("/")):
            item = root / name
            if item.is_dir() and (item.is_symlink() or item.is_junction() or (item / ".git").exists()):
                raise SourceSnapshotError(f"Unsupported linked or nested source tree: {name}")
    validate_members(list(names))
    files = {name: _source_file(root, name).read_bytes() for name in sorted(names)}
    if files["pyproject.toml"] != metadata:
        raise SourceSnapshotError("Build metadata changed during capture")
    return head, files


def _dirty_patch(root: Path, scratch: Path, head: str, files: dict[str, bytes]) -> bytes:
    """Compare the captured working bytes to HEAD in a private Git index/object store."""
    base_names = _names(_git(root, "ls-tree", "-rz", "--name-only", head, "--", "clustering_eval"))
    base_resources = _resources(_git(root, "show", f"{head}:pyproject.toml"))
    selected = set(files) | {name for name in base_names if _package_source(name) or name in base_resources}
    work = scratch / "source"
    objects = scratch / "objects"
    objects.mkdir()
    for name, data in files.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        # Preserve executable mode for tracked scripts on hosts which use it.
        path.chmod((root / name).stat().st_mode & 0o777)
    local_objects = _git(root, "rev-parse", "--path-format=absolute", "--git-path", "objects")
    git_dir = _git(root, "rev-parse", "--absolute-git-dir")
    environment = dict(_git_environment(), GIT_DIR=os.fsdecode(git_dir.rstrip(b"\n")),
                       GIT_WORK_TREE=str(work), GIT_INDEX_FILE=str(scratch / "index"),
                       GIT_OBJECT_DIRECTORY=str(objects),
                       GIT_ALTERNATE_OBJECT_DIRECTORIES=os.fsdecode(local_objects.rstrip(b"\n")))
    options = ("-c", "core.splitIndex=false", "-c", "core.sparseCheckout=false", "-c", "core.fsmonitor=false")
    _git(work, *options, "read-tree", head, env=environment)
    pathspec = b"".join(os.fsencode(name) + b"\0" for name in sorted(selected))
    _git(work, *options, "add", "-A", "-f", "--pathspec-from-file=-", "--pathspec-file-nul",
         env=environment, data=pathspec)
    return _git(work, *options, "diff", "--cached", "--binary", "--full-index", "--no-color",
                "--no-ext-diff", "--no-textconv", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/",
                head, "--", env=environment)


def capture_source_snapshot(
    checkout: Path | str, destination: Path | str, *, reproduction_scripts: tuple[str, ...] = (),
) -> SourceSnapshot:
    """Publish a verified, immutable source bundle at a dedicated destination."""
    root = Path(checkout).absolute()
    target = Path(destination).absolute()
    scripts = set(reproduction_scripts)
    for name in scripts:
        portable_path(name)
        if not name.startswith(("tools/", "reproduce/")) or not name.endswith(".py") or any(
                part.startswith(".") or part in _EXCLUDED for part in name.split("/")):
            raise SourceSnapshotError(f"Expected a project reproduction script: {name}")
    try:
        root = root.resolve(strict=True)
        top = Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel").rstrip(b"\n")))
        if top.resolve() != root:
            raise SourceSnapshotError(f"Expected Git checkout root: {root}")
        if target.is_symlink() or target.is_junction() or target.resolve().is_relative_to(root / "clustering_eval"):
            raise SourceSnapshotError(f"Invalid snapshot destination: {target}")
        head, files = _read_checkout(root, scripts)
        hashes = {name: sha256(data).hexdigest() for name, data in files.items()}
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".source-capture-", dir=target.parent) as tmp:
            temporary = Path(tmp)
            patch = _dirty_patch(root, temporary, head, files)
            bundle = temporary / "bundle"
            bundle.mkdir()
            with ZipFile(bundle / ZIP_NAME, "w") as archive:
                for name, data in files.items():
                    member = ZipInfo(name)  # fixed timestamp for portable packaging
                    member.create_system = 3
                    member.external_attr = 0o100644 << 16
                    archive.writestr(member, data, compress_type=ZIP_DEFLATED)
            (bundle / PATCH_NAME).write_bytes(patch)
            record = {
                "format": FORMAT, "source_id": content_id(hashes), "source_head": head,
                "files": hashes, "snapshot_sha256": sha256((bundle / ZIP_NAME).read_bytes()).hexdigest(),
                "working_tree_patch_sha256": sha256(patch).hexdigest(), "checks": CHECKS,
            }
            (bundle / RECORD_NAME).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            verified = verify_source_snapshot(bundle)
            if _read_checkout(root, scripts) != (head, files) or _git(root, "rev-parse", "HEAD").decode().strip() != head:
                raise SourceSnapshotError("Checkout source or HEAD changed during capture")
            if not target.exists():
                try:
                    bundle.rename(target)
                    return SourceSnapshot(verified.source_id, head, target)
                except OSError:
                    if not target.exists():
                        raise
            previous = verify_source_snapshot(target, expected_source_id=verified.source_id)
            if previous.source_head != head or previous.patch.read_bytes() != patch:
                raise SourceSnapshotError(f"Existing destination holds different source provenance: {target}")
            return previous
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise SourceSnapshotError(f"Cannot capture {root}: {exc}") from exc
