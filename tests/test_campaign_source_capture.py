"""Integration checks for source capture using small, local Git checkouts."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import warnings
from zipfile import ZipFile

from clustering_eval.experiments import source_capture
from clustering_eval.experiments.source_archive import SourceSnapshotError, verify_source_snapshot
from clustering_eval.experiments.source_capture import capture_source_snapshot


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


class CheckoutFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.checkout = self.base / "working tree"
        self.checkout.mkdir()
        git(self.checkout, "init", "--quiet")
        git(self.checkout, "config", "user.name", "Source fixture")
        git(self.checkout, "config", "user.email", "fixture@example.invalid")
        git(self.checkout, "config", "core.autocrlf", "false")
        files = {
            "clustering_eval/__init__.py": b"",
            "clustering_eval/cli.py": b"print('original')\n",
            "clustering_eval/results/store.py": b"# package implementation\n",
            "clustering_eval/nested/weights.dat": b"\x00weights\xff",
            "pyclusteval_ui.py": b"# gui\n",
            "pyproject.toml": b'[tool.setuptools.package-data]\n"clustering_eval.nested" = ["weights.dat"]\n',
            "tools/replay.py": b"# custom entrypoint\n",
        }
        for name, data in files.items():
            path = self.checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        git(self.checkout, "add", ".")
        git(self.checkout, "commit", "-qm", "fixture")
        self.destination = self.base / "campaign" / "reproduce"


class CaptureTests(CheckoutFixture):
    def test_capture_is_relocatable_and_repeatable(self):
        initial = capture_source_snapshot(self.checkout, self.destination, reproduction_scripts=("tools/replay.py",))
        self.assertEqual(initial.patch.read_bytes(), b"")
        clone = self.base / "other checkout"
        git(self.base, "clone", "--config", "core.autocrlf=false", "--quiet", str(self.checkout), str(clone))
        again = capture_source_snapshot(clone, self.base / "second", reproduction_scripts=("tools/replay.py",))
        self.assertEqual((initial.source_id, initial.source_head), (again.source_id, again.source_head))
        with ZipFile(initial.archive) as archive:
            self.assertEqual(archive.read("clustering_eval/nested/weights.dat"), b"\x00weights\xff")
            self.assertIn("clustering_eval/results/store.py", archive.namelist())
            self.assertEqual(archive.read("tools/replay.py"), b"# custom entrypoint\n")
        moved = self.base / "moved bundle"
        shutil.move(initial.directory, moved)
        with patch("subprocess.run", side_effect=AssertionError("verification must run without Git")):
            self.assertEqual(verify_source_snapshot(moved, expected_source_id=initial.source_id).source_id, initial.source_id)
        self.assertEqual(git(self.checkout, "status", "--porcelain"), b"")

    def test_git_changes_and_new_code_are_captured_without_touching_the_index(self):
        initial = capture_source_snapshot(self.checkout, self.destination)
        cli = self.checkout / "clustering_eval/cli.py"
        cli.write_bytes(b"print('staged')\n")
        git(self.checkout, "add", "clustering_eval/cli.py")
        staged = capture_source_snapshot(self.checkout, self.base / "staged")
        cli.write_bytes(b"print('working bytes')\n")
        unstaged = capture_source_snapshot(self.checkout, self.base / "unstaged")
        new_module = self.checkout / "clustering_eval/nested/new.py"
        new_module.write_bytes(b"# new\r\n")
        (self.checkout / ".gitignore").write_bytes(b"new.py\n")
        before = git(self.checkout, "diff", "--cached")
        current = capture_source_snapshot(self.checkout, self.base / "current")
        self.assertEqual(len({initial.source_id, staged.source_id, unstaged.source_id, current.source_id}), 4)
        self.assertEqual(git(self.checkout, "diff", "--cached"), before)
        self.assertEqual(initial.source_head, current.source_head)
        with ZipFile(current.archive) as archive:
            self.assertEqual(archive.read("clustering_eval/cli.py"), cli.read_bytes())
            self.assertEqual(archive.read("clustering_eval/nested/new.py"), new_module.read_bytes())
        diff = current.patch.read_bytes()
        self.assertIn(b"+print('working bytes')", diff)
        self.assertIn(b"new file mode", diff)
        self.assertNotIn(b"+print('staged')", diff)
        replay = self.base / "fresh checkout"
        git(self.base, "clone", "--config", "core.autocrlf=false", "--quiet", str(self.checkout), str(replay))
        git(replay, "apply", "--check", str(current.patch))
        git(replay, "apply", str(current.patch))
        self.assertEqual((replay / "clustering_eval/cli.py").read_bytes(), cli.read_bytes())

    def test_service_files_do_not_change_identity_or_reused_bytes(self):
        initial = capture_source_snapshot(self.checkout, self.destination)
        original = {p.name: p.read_bytes() for p in self.destination.iterdir()}
        for name in ("clustering_eval/__pycache__/junk.py", "results/worker.py",
                     "clustering_eval/.env", "clustering_eval/nested/output.csv"):
            path = self.checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"ignored\n")
        again = capture_source_snapshot(self.checkout, self.destination)
        self.assertEqual(initial, again)
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.destination.iterdir()})


class TamperTests(CheckoutFixture):
    def test_rejects_missing_changed_and_inconsistent_artifacts(self):
        snapshot = capture_source_snapshot(self.checkout, self.destination)
        for path in (snapshot.archive, snapshot.patch, snapshot.verification):
            old = path.read_bytes()
            with self.subTest(missing=path.name):
                path.unlink()
                with self.assertRaises(SourceSnapshotError):
                    verify_source_snapshot(self.destination)
            with self.subTest(changed=path.name):
                path.write_bytes(b"changed")
                with self.assertRaises(SourceSnapshotError):
                    verify_source_snapshot(self.destination)
                with self.assertRaises(SourceSnapshotError):
                    capture_source_snapshot(self.checkout, self.destination)
                self.assertEqual(path.read_bytes(), b"changed")
            path.write_bytes(old)
        with self.assertRaisesRegex(SourceSnapshotError, "identity"):
            verify_source_snapshot(self.destination, expected_source_id="0" * 64)

    def test_rejects_wrong_members_even_if_outer_zip_checksum_matches(self):
        snapshot = capture_source_snapshot(self.checkout, self.destination)
        with ZipFile(snapshot.archive) as original:
            files = [(name, original.read(name)) for name in original.namelist()]
        cases = (
            ("missing or unlisted", files[:-1]),
            ("duplicate", files + [files[0]]),
            ("extra", files + [("extra.py", b"added")]),
            ("parent path", files + [("../outside.py", b"bad path")]),
            ("drive path", files + [("C:/outside.py", b"bad path")]),
            ("case alias", files + [(files[0][0].upper(), b"alias")]),
            ("changed member", [(files[0][0], b"different")] + files[1:]),
        )
        for label, members in cases:
            with self.subTest(label), warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with ZipFile(snapshot.archive, "w") as archive:
                    for name, data in members:
                        archive.writestr(name, data)
                record = json.loads(snapshot.verification.read_bytes())
                record["snapshot_sha256"] = sha256(snapshot.archive.read_bytes()).hexdigest()
                snapshot.verification.write_text(json.dumps(record), encoding="utf-8")
                with self.assertRaises(SourceSnapshotError):
                    verify_source_snapshot(self.destination)
                self.assertFalse((self.base / "outside.py").exists())

    def test_changes_during_capture_or_new_head_leave_prior_capture_intact(self):
        previous = capture_source_snapshot(self.checkout, self.destination)
        cli = self.checkout / "clustering_eval/cli.py"
        for change in ("content", "commit"):
            original_reader = source_capture._read_checkout
            def read_then_change(*args):
                captured = original_reader(*args)
                if change == "content":
                    cli.write_bytes(cli.read_bytes() + b"# changed\n")
                else:
                    git(self.checkout, "commit", "--allow-empty", "-qm", "changed head")
                return captured
            with self.subTest(change), patch.object(source_capture, "_read_checkout", side_effect=read_then_change):
                with self.assertRaisesRegex(SourceSnapshotError, "changed"):
                    capture_source_snapshot(self.checkout, self.destination)
            self.assertEqual(verify_source_snapshot(self.destination), previous)
        with self.assertRaises(SourceSnapshotError):
            capture_source_snapshot(self.checkout, self.destination)
        with patch.object(ZipFile, "writestr", side_effect=OSError("storage unavailable")):
            with self.assertRaisesRegex(SourceSnapshotError, "storage unavailable"):
                capture_source_snapshot(self.checkout, self.destination)
        cli.unlink()
        with self.assertRaisesRegex(SourceSnapshotError, "cli.py"):
            capture_source_snapshot(self.checkout, self.destination)
        self.assertEqual(verify_source_snapshot(self.destination), previous)


if __name__ == "__main__":
    unittest.main()
