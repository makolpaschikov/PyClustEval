"""Exercise read-only snapshot commands with isolated real Git checkouts."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_task

from task_support import snapshots
from task_support.artifacts import source_snapshot, spec_digest
from task_support.formats import TaskError
from task_support.mathematics import scope_digest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / ".agent-work/tasks/harness-task-automation/m1/fixtures"
CLI = ROOT / "harness/scripts/task/task.py"


class SnapshotTests(unittest.TestCase):
    git = test_task.TaskTests.git
    init = test_task.TaskTests.init
    save = test_task.TaskTests.save
    fill = test_task.TaskTests.fill
    epic_with_children = test_task.TaskTests.epic_with_children

    def setUp(self):
        FIXTURES.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=FIXTURES)
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.cleanup_fixture)
        self.repo = self.root / "canonical"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "test-main")
        (self.repo / ".gitignore").write_text("/.agent-work/tasks/\n", encoding="utf-8")
        (self.repo / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git("add", ".gitignore", "source.py")
        self.directory = self.repo / ".agent-work/tasks/example"

    def cleanup_fixture(self):
        self.assertTrue(self.root.resolve().is_relative_to(FIXTURES.resolve()))
        self.temp.cleanup()

    def commit(self):
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgSign=false", "commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD").decode().strip()

    def cli(self, command, *args, repo=None):
        return subprocess.run(
            [sys.executable, "-B", str(CLI), "--repo", str(repo or self.repo),
             command, *map(str, args)],
            capture_output=True,
            text=True,
        )

    def result(self, command, *args, repo=None):
        result = self.cli(command, *args, repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def refused(self, command, *args, message, code=1, repo=None):
        result = self.cli(command, *args, repo=repo)
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertIn(message, result.stderr)
        self.assertEqual(result.stdout, "")

    def task_files(self):
        return {path.relative_to(self.directory): path.read_bytes()
                for path in self.directory.rglob("*") if path.is_file()}

    def test_source_snapshot_needs_no_manifest_and_records_unborn_then_committed_head(self):
        expected = source_snapshot(self.repo)
        original_index = (self.repo / ".git/index").read_bytes()
        unborn = self.result("source-snapshot")
        self.assertEqual(unborn, {"command": "source-snapshot", **expected, "origin": {
            "repository": str(self.repo), "branch": "test-main", "head": None,
        }})
        self.assertFalse((self.repo / ".agent-work").exists())
        self.assertEqual((self.repo / ".git/index").read_bytes(), original_index)

        head = self.commit()
        committed = self.result("source-snapshot")
        self.assertEqual(committed["source_sha256"], unborn["source_sha256"])
        self.assertEqual(committed["origin"]["head"], head)

    def test_context_contract_matches_legacy_hashes_and_preserves_task_bytes(self):
        item_id = "TASK-001"
        self.init()
        before = self.task_files()
        legacy = self.result("snapshot", self.directory, "--id", item_id)
        context = self.result("context", ".agent-work/tasks/example", "--id", item_id)
        self.assertEqual(context, {
            "format_version": 1,
            "task_root": item_id,
            "item_id": item_id,
            "spec_sha256": legacy["spec_sha256"],
            "source_sha256": legacy["source_sha256"],
            "stage": None,
            "scope_sha256": None,
            "origin": {"repository": str(self.repo), "branch": legacy["branch"], "head": None},
        })
        self.assertEqual(snapshots.capture_context(self.repo, self.directory, item_id), context)
        self.assertEqual(self.task_files(), before)
        self.assertEqual(self.result("snapshot", self.directory, "--id", item_id), legacy)

    def test_context_uses_explicit_worker_checkout_but_validates_canonical_branch(self):
        head = self.commit()
        manifest = self.init()
        item = manifest["items"][0]
        before = self.task_files()
        worker = self.root / "worker"
        self.git("worktree", "add", "-q", "-b", "worker-branch", str(worker))
        (worker / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
        worker_snapshot = self.result("source-snapshot", repo=worker)
        args = (self.directory, "--id", item["id"], "--source-repo", worker,
                "--stage", "implementation")
        context = self.result("context", *args)
        self.assertEqual(context["origin"], worker_snapshot["origin"])
        self.assertEqual(context["origin"], {
            "repository": str(worker), "branch": "worker-branch", "head": head,
        })
        self.assertEqual(context["source_sha256"], worker_snapshot["source_sha256"])
        self.assertNotEqual(context["source_sha256"], source_snapshot(self.repo)["source_sha256"])
        self.assertEqual(context["spec_sha256"], spec_digest(self.directory, manifest, item))
        self.assertEqual(context["scope_sha256"], scope_digest(self.directory, manifest, item, "implementation"))
        self.assertFalse((worker / ".agent-work").exists())
        self.assertEqual(self.task_files(), before)

        self.git("switch", "-qc", "wrong-canonical-branch")
        self.refused("context", *args, message="Checkout differs from selected task branch")
        self.assertEqual(self.task_files(), before)

    def test_math_scope_reports_transitive_dependencies_and_stage_specific_children(self):
        manifest = self.epic_with_children()
        self.save(manifest)
        self.init("subtask", "TASK-003", "EPIC-001")
        manifest = self.init("subtask", "TASK-004", "EPIC-001")
        epic, first, second, third, fourth = manifest["items"]
        first["mathematics"].update(required=True, rationale="Changes a mathematical rule.")
        third["depends_on"] = [second["id"]]
        self.save(manifest)
        before = self.task_files()

        for item, stage, included in (
            (epic, "specification", [epic]),
            (epic, "implementation", [epic, first, second, third, fourth]),
            (third, "specification", [epic, first, second, third]),
            (third, "implementation", [epic, first, second, third]),
        ):
            with self.subTest(item=item["id"], stage=stage):
                args = (self.directory, "--id", item["id"], "--stage", stage)
                context = self.result("context", *args)
                report = self.result("math-scope", *args)
                self.assertEqual(report.pop("items"), [
                    {"id": entry["id"], "document": entry["document"],
                     "specification": entry["specification"],
                     "required": entry["mathematics"]["required"],
                     "rationale": entry["mathematics"]["rationale"]}
                    for entry in included
                ])
                self.assertEqual(report, context)
                self.assertEqual(report["scope_sha256"], scope_digest(self.directory, manifest, item, stage))
        self.assertEqual(self.task_files(), before)

    def test_capture_rejects_raw_manifest_contract_and_source_drift_during_lint(self):
        manifest = self.init()
        item = manifest["items"][0]
        original_lint = snapshots.lint

        for path, change, message in (
            (self.directory / "task.json", b"\n", "Manifest changed"),
            (self.directory / item["document"], b"\n<!-- formatting -->\n", "Task documents changed"),
            (self.repo / "source.py", b"\nVALUE = 3\n", "Source changed"),
        ):
            with self.subTest(path=path):
                original = path.read_bytes()

                def change_input(*args):
                    parsed = original_lint(*args)
                    path.write_bytes(original + change)
                    return parsed

                try:
                    with patch.object(snapshots, "lint", side_effect=change_input):
                        with self.assertRaisesRegex(TaskError, message):
                            snapshots.capture_context(self.repo, self.directory, item["id"])
                    self.assertEqual(path.read_bytes(), original + change)
                finally:
                    path.write_bytes(original)

    def test_context_refuses_invalid_inputs_without_writes(self):
        self.init()
        args = (self.directory, "--id", "TASK-001")
        before = self.task_files()
        self.refused("context", self.directory, "--id", "UNKNOWN", message="Unknown item")
        self.refused("context", self.directory, "--id", "../TASK-001", message="invalid ID")
        self.refused("context", self.repo, "--id", "TASK-001", message="must be below")
        self.refused("context", *args, "--source-repo", self.directory, message="repository root")
        self.refused("context", *args, "--stage", "other", code=2, message="invalid choice")
        self.refused("math-scope", *args, code=2, message="--stage")
        self.refused("source-snapshot", self.directory, code=2, message="unrecognized arguments")
        self.assertEqual(self.task_files(), before)

        (self.repo / ".gitignore").write_text("", encoding="utf-8")
        self.refused("context", *args, message="Task manifest must be ignored")
        self.assertEqual(self.task_files(), before)

    def test_context_refuses_symlink_manifest(self):
        self.init()
        link = self.directory / "manifest-link.json"
        original = self.directory / "task.json"
        outside = self.root / "external.json"
        outside.write_bytes(original.read_bytes())
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"File symlinks unavailable: {exc}")
        link.replace(original)
        before = outside.read_bytes()
        self.refused("context", self.directory, "--id", "TASK-001", message="must not be a symlink")
        self.assertEqual(outside.read_bytes(), before)
        self.assertTrue(original.is_symlink())

    def test_source_snapshot_refuses_detached_head_and_gitlink(self):
        head = self.commit()
        self.git("switch", "--detach", "-q", head)
        self.refused("source-snapshot", message="Detached HEAD")
        self.git("switch", "-q", "test-main")
        (self.repo / "gitlink").mkdir()
        self.git("update-index", "--add", "--cacheinfo", f"160000,{head},gitlink")
        self.refused("source-snapshot", message="submodule")


if __name__ == "__main__":
    unittest.main()
