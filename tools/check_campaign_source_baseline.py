"""Verify the paper archive's pinned source snapshot and Git patch without running them."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile

SOURCE_HEAD = "6c79b384e7537c4b94c6c1887ba36eceded7314c"
COMPARISON_HEAD = "5d3723a08f8a7fe9003050923a66d705f1e77c09"
SNAPSHOT_SHA256 = "6c04276c803018475602b78dfb8b7be3b23a2714c6ad1b2cce5b1ae9616ad3e5"
PATCH_SHA256 = "844167891479ee9513d3ec8b5fcd156649f7f7977702a4f36215281ed531d073"
METADATA_SHA256 = "fda5b129d9ee67d2d36cafa2c3ba83acf2411eafa66a6e194f21dd0c47899b96"
PATCH_ONLY = {"tests/test_author_adapters.py", "tests/test_hfdbscan_compatibility_patch.py"}


def git(directory: Path, *args: str, data: bytes | None = None) -> bytes:
    """Use the selected repository even when called from a Git hook or linked checkout."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(["git", "-C", directory, *args], input=data,
                            capture_output=True, env=env, check=False)
    if result.returncode:
        raise ValueError(f"git {args[0]}: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def pinned_bytes(path: Path, expected: str) -> bytes:
    content = path.read_bytes()
    actual = sha256(content).hexdigest()
    if actual != expected:
        raise ValueError(f"{path.name}: expected SHA-256 {expected}, found {actual}")
    return content


def read_blobs(repo: Path, tree: str, names: list[str]) -> dict[str, tuple[str, bytes]]:
    """Read exact Git object IDs and unfiltered bytes for tree entries or the index."""
    queries = "".join(f"{tree}:{name}\n" for name in names).encode()
    stream = BytesIO(git(repo, "cat-file", "--batch", data=queries))
    blobs = {}
    for name in names:
        header = stream.readline().decode().split()
        if len(header) != 3 or header[1] != "blob":
            raise ValueError(f"Missing Git blob for {tree}:{name}")
        content = stream.read(int(header[2]))
        if stream.read(1) != b"\n":
            raise ValueError(f"Incomplete Git blob for {tree}:{name}")
        blobs[name] = header[0], content
    return blobs


def apply_in_private_index(repo: Path, patch: bytes, names: list[str]) -> dict[str, tuple[str, bytes]]:
    """Reconstruct postimages in a disposable bare repository sharing read-only source objects."""
    object_dir = git(repo, "rev-parse", "--path-format=absolute", "--git-path", "objects").rstrip(b"\r\n")
    with TemporaryDirectory(prefix="pyclusteval-baseline-") as temp:
        bare = Path(temp)
        git(bare, "init", "--bare", "--quiet", "--template=")
        (bare / "objects/info/alternates").write_bytes(object_dir + b"\n")
        git(bare, "read-tree", SOURCE_HEAD)
        git(bare, "apply", "--cached", "--whitespace=nowarn", "-", data=patch)
        return read_blobs(bare, "", names)


def compare_bytes(reference: bytes, actual: bytes | None) -> str:
    if actual is None:
        return "missing"
    if reference == actual:
        return "exact"
    if reference.replace(b"\r\n", b"\n") == actual.replace(b"\r\n", b"\n"):
        return "eol_only"
    return "content"


def audit(repo: Path, archive: Path) -> dict:
    """Audit this specific release and classify each member against the selected working files."""
    reproduce = archive / "reproduce"
    snapshot = pinned_bytes(reproduce / "source_snapshot.zip", SNAPSHOT_SHA256)
    patch = pinned_bytes(reproduce / "source_changes.patch", PATCH_SHA256)
    metadata = json.loads(pinned_bytes(reproduce / "source_code_verification.json", METADATA_SHA256))
    if not isinstance(metadata, dict) or (metadata.get("source_head"), metadata.get("working_tree_patch_sha256")) != (
        SOURCE_HEAD, PATCH_SHA256
    ):
        raise ValueError("source_code_verification.json does not identify the pinned source commit and patch")

    with ZipFile(BytesIO(snapshot)) as packed:
        members = {name: packed.read(name) for name in packed.namelist()}
        if len(members) != 79 or len(packed.namelist()) != len(members):
            raise ValueError("Expected exactly 79 distinct snapshot members")

    # The pinned patch uses simple modify records. Git applies and checks the actual hunks.
    changes = re.findall(
        rb"^diff --git a/([^\n]+) b/\1\nindex ([a-f0-9]+)\.\.([a-f0-9]+) 100644$",
        patch, re.MULTILINE,
    )
    patch_ids = {name.decode(): (old.decode(), new.decode()) for name, old, new in changes}
    if len(patch_ids) != 17 or set(patch_ids) - members.keys() != PATCH_ONLY:
        raise ValueError("Unexpected patch paths or incomplete blob identities")
    names = sorted(set(members) | patch_ids.keys())
    repo = repo.resolve(strict=True)
    root = Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel").rstrip(b"\r\n"))).resolve()
    if root != repo:
        raise ValueError(f"Expected checkout root {root}, got {repo}")
    git(repo, "merge-base", "--is-ancestor", SOURCE_HEAD, COMPARISON_HEAD)
    if git(repo, "diff", "--no-ext-diff", "--name-only", SOURCE_HEAD, COMPARISON_HEAD, "--", *names):
        raise ValueError("The pinned comparison commit differs from the source commit on audited paths")
    base = read_blobs(repo, SOURCE_HEAD, names)
    updated = apply_in_private_index(repo, patch, names)
    for name, (old, new) in patch_ids.items():
        if not base[name][0].startswith(old) or not updated[name][0].startswith(new):
            raise ValueError(f"{name}: patch preimage/postimage differs from the declared Git blob")

    categories: dict[str, str] = {}
    drift = []
    for name in names:
        path = repo / name
        if not path.resolve().is_relative_to(repo):
            raise ValueError(f"{name}: working path resolves outside the checkout")
        actual = path.read_bytes() if path.is_file() else None
        if compare_bytes(base[name][1], actual) in {"missing", "content"}:
            drift.append(name)
        if name in members:
            if compare_bytes(members[name], updated[name][1]) == "content":
                raise ValueError(f"{name}: snapshot differs from reconstructed postimage")
            categories[name] = compare_bytes(members[name], actual)
    totals = Counter(categories.values())
    return {
        "source_head": SOURCE_HEAD, "comparison_head": COMPARISON_HEAD,
        "checkout_head": git(repo, "rev-parse", "HEAD").decode().strip(),
        "snapshot_sha256": SNAPSHOT_SHA256, "patch_sha256": PATCH_SHA256, "metadata_sha256": METADATA_SHA256,
        "patch_paths_verified": len(patch_ids), "patch_only": sorted(PATCH_ONLY),
        "snapshot_vs_checkout": categories, "counts": dict(sorted(totals.items())),
        "checkout_drift_from_pinned_baseline": drift,
        "verified": not drift and totals["content"] == 15 and totals["exact"] + totals["eol_only"] == 64,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Article experiments directory containing reproduce/")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                        help="PyClustEval checkout whose working files should be compared")
    args = parser.parse_args()
    try:
        report = audit(args.repo, args.archive)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
