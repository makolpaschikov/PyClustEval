"""Publication transactions on the real filesystem with small deterministic archive content."""
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from clustering_eval.experiments.runner_state import IntegrityError, initialize
from clustering_eval.results import archive_publish as publish


def campaign(path):
    path.mkdir()
    (path / "state").mkdir()
    initialize(path, {"format": "pyclusteval.campaign-state.v1", "source_id": "a" * 64, "created": 1,
                      "plan_sha256": "b" * 64, "resolved_sha256": "c" * 64}, [])
    return path


def tiny_modules(root):
    # Model the sibling components at their public interfaces. Publication, file hashing,
    # locking, interruption and recovery run on the local filesystem.
    builder = ModuleType("clustering_eval.results.archive_build")
    verifier = ModuleType("clustering_eval.results.archive_verify")

    def build_archive(campaign_root, directory):
        manifest = {"format": publish.GENERAL, "campaign_id": publish._campaign_id(campaign_root),
                    "planned": 1, "totals": {"ok": 1}, "complete": True}
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (directory / "payload.txt").write_text((root / "control.txt").read_text(), encoding="utf-8")
        return manifest

    def verify_archive(directory, *, check_checksums=True):
        errors = []
        if (directory / "payload.txt").read_text() == "invalid":
            errors.append("payload.txt: failed content control")
        if check_checksums:
            catalog = json.loads((directory / "checksums.json").read_bytes())
            entries = {x["path"]: x for x in catalog["files"]}
            expected = {p.name for p in directory.iterdir() if p.name != "checksums.json"}
            if set(entries) != expected:
                errors.append("checksums.json: file coverage")
            for name in set(entries) & expected:
                if entries[name]["sha256"] != publish._digest(directory / name):
                    errors.append(f"{name}: changed content")
        return dict(format=publish.GENERAL, valid=not errors, complete=True,
                    checks=[{"scope": "payloads", "count": 1}], errors=errors, not_checked=[])

    builder.build_archive = build_archive
    verifier.verify_archive = verify_archive
    return builder, verifier


@pytest.fixture
def saved(tmp_path, monkeypatch):
    root = campaign(tmp_path / "saved campaign")
    (root / "control.txt").write_text("first", encoding="utf-8")
    for module in tiny_modules(root):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    return root


def inventory(archive):
    return {p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}


def test_checked_publication_and_rejected_staging_preserves_old_bytes(saved):
    first = publish.publish_archive(saved)
    archive = Path(first["path"])
    assert first["published"] and first["complete"]
    hashes = json.loads((archive / "checksums.json").read_bytes())["files"]
    assert {e["path"] for e in hashes} == {"manifest.json", "payload.txt", "verification.json"}
    assert json.loads((archive / "verification.json").read_bytes())["valid"]
    original = inventory(archive)

    (saved / "control.txt").write_text("invalid", encoding="utf-8")
    with pytest.raises(publish.VerificationFailure, match="payload.txt"):
        publish.publish_archive(saved)
    assert inventory(archive) == original

    (saved / "control.txt").write_text("next", encoding="utf-8")
    assert publish.publish_archive(saved)["published"]
    assert (archive / "payload.txt").read_text() == "next"


def test_foreign_or_damaged_target_and_workspace_are_preserved(saved):
    archive = saved / "archive"
    archive.mkdir()
    (archive / "sentinel").write_text("unrelated")
    with pytest.raises(IntegrityError):
        publish.publish_archive(saved)
    assert inventory(archive) == {Path("sentinel"): b"unrelated"}
    archive.rename(saved / "other")
    publish.publish_archive(saved)
    (archive / "payload.txt").write_text("edited", encoding="utf-8")
    with pytest.raises(IntegrityError, match="payload.txt"):
        publish.publish_archive(saved)
    assert (archive / "payload.txt").read_text() == "edited"

    txn = saved / "state" / ".archive-publication"
    txn.mkdir()
    (txn / "notes").write_text("unrelated")
    with pytest.raises(IntegrityError, match="owner.json"):
        publish.publish_archive(saved)
    assert (txn / "notes").is_file()


def test_rename_error_restores_previous_generation(saved, monkeypatch):
    publish.publish_archive(saved)
    before = inventory(saved / "archive")
    (saved / "control.txt").write_text("replacement")
    rename = Path.rename

    def denied(path, new):
        if path.name == "staging":
            raise PermissionError("Sharing violation at install")
        return rename(path, new)

    monkeypatch.setattr(Path, "rename", denied)
    with pytest.raises(PermissionError, match="Sharing violation"):
        publish.publish_archive(saved)
    assert inventory(saved / "archive") == before


def test_os_lock_excludes_second_publisher(saved):
    with publish._publisher_lock(saved / "state"):
        with pytest.raises(publish.PublicationBusy):
            publish.publish_archive(saved)
        assert not (saved / "archive").exists()
    assert publish.publish_archive(saved)["published"]


@pytest.mark.parametrize("interruption,expected", [("previous", "first"), ("archive", "second")])
def test_reopen_after_process_death_between_renames(saved, interruption, expected):
    publish.publish_archive(saved)
    (saved / "control.txt").write_text("second")
    child = """
import os, runpy, sys
from pathlib import Path
from clustering_eval.results import archive_publish as publish
root = Path(sys.argv[1])
helpers = runpy.run_path(sys.argv[2])
for module in helpers['tiny_modules'](root):
    sys.modules[module.__name__] = module
rename = Path.rename
def stop_after_rename(path, target):
    result = rename(path, target)
    if target.name == sys.argv[3]:
        os._exit(71)
    return result
Path.rename = stop_after_rename
publish.publish_archive(root)
"""
    result = subprocess.run([sys.executable, "-B", "-c", child, str(saved), __file__, interruption],
                            cwd=Path(__file__).resolve().parents[1], timeout=40)
    assert result.returncode == 71
    (saved / "control.txt").write_text("invalid")
    with pytest.raises(publish.VerificationFailure):
        publish.publish_archive(saved)
    assert (saved / "archive" / "payload.txt").read_text() == expected
    assert not (saved / "state" / ".archive-publication").exists()
