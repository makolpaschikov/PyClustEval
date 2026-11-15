"""Task CLI diagnostics for invalid manifest item kinds."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TASK_CLI = ROOT / "harness/scripts/task/task.py"


class KindDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        fixture_root = (ROOT / ".agent-work/tasks/_kind-diagnostics-tests").resolve()
        self.assertTrue(fixture_root.is_relative_to(ROOT))
        fixture_root.mkdir(parents=True, exist_ok=True)
        self.repo = Path(tempfile.mkdtemp(dir=fixture_root)).resolve()
        self.addCleanup(self.remove_fixture, fixture_root)
        subprocess.run(["git", "init", "-q", "-b", "test-main", str(self.repo)],
                       check=True, capture_output=True, timeout=15)
        (self.repo / ".gitignore").write_text("/.agent-work/tasks/\n", encoding="utf-8")
        self.tasks = self.repo / ".agent-work/tasks"

    def remove_fixture(self, fixture_root):
        repo = self.repo.resolve()
        self.assertTrue(repo != fixture_root and repo.is_relative_to(fixture_root))
        shutil.rmtree(repo)

    def task(self, command, directory, *args):
        return subprocess.run([sys.executable, "-B", str(TASK_CLI), "--repo", str(self.repo),
                               command, str(directory), *args],
                              capture_output=True, text=True, timeout=15)

    def init(self, directory, item_id, kind, *args):
        result = self.task("init", directory, "--id", item_id, "--kind", kind,
                           "--branch", "test-main", "--scope", "harness", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["manifest_sha256"]

    def init_epic(self):
        epic = self.tasks / "epic"
        revision = self.init(epic, "EPIC-001", "epic")
        self.init(epic, "TASK-001", "subtask", "--parent", "EPIC-001",
                  "--expect-sha256", revision)
        return epic

    def fixture_state(self):
        return {path.relative_to(self.repo): (path.stat().st_mtime_ns,
                                             path.read_bytes() if path.is_file() else None)
                for path in self.repo.rglob("*")}

    def test_lint_rejects_invalid_item_kinds_without_traceback_or_writes(self):
        manifest_path = self.init_epic() / "task.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for kind in ([], {}, None, 1, True, "unknown"):
            with self.subTest(kind=kind):
                manifest["items"][1]["kind"] = kind
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                before = self.fixture_state()

                result = self.task("lint", manifest_path.parent)

                self.assertEqual(self.fixture_state(), before)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr.strip(), "error: TASK-001: invalid kind",
                                 result.stderr)

    def test_lint_accepts_all_supported_item_kinds(self):
        epic = self.init_epic()
        standalone = self.tasks / "standalone"
        self.init(standalone, "SPEC-001", "specification")
        for directory, items in ((epic, ["EPIC-001", "TASK-001"]), (standalone, ["SPEC-001"])):
            with self.subTest(directory=directory.name):
                result = self.task("lint", directory)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["items"], items)
