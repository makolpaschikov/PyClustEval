"""Integrated CLI lifecycle using real isolated task and Git fixtures."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_task
from task_support.artifacts import load


class AutomationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fx = test_task.TaskTests(methodName="runTest")
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)
        manifest, item = self.fx.ready()
        item["contributors"] = ["developer"]
        self.fx.save(manifest)
        self.cli_path = test_task.HELPER / "task.py"

    def cli(self, command, *args, expected=0):
        result = subprocess.run(
            [sys.executable, "-B", str(self.cli_path), "--repo", str(self.fx.repo),
             command, *map(str, args)], capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def adopt(self, bundle, expected=0):
        return self.cli("import-evidence", self.fx.directory, "--bundle", bundle,
                        "--adopt", "--expect-sha256", load(self.fx.directory)[1],
                        expected=expected)

    def run_check(self, name, source, code, expected=0):
        output_dir = source / ".agent-work/tasks/worker-results"
        output_dir.mkdir(parents=True, exist_ok=True)
        bundle = output_dir / (name + ".zip")
        self.cli("run-check", self.fx.directory, "--id", "TASK-001", "--check-id", "CHECK-001",
                 "--source-repo", source, "--output", bundle, "--timeout", "5",
                 "--", sys.executable, "-c", code, expected=expected)
        return bundle

    def test_run_import_review_complete_resume_and_later_failure(self):
        bundle = self.run_check("passed", self.fx.repo, "print('checked')")
        imported = self.adopt(bundle)
        self.assertTrue(imported["adopted"])
        self.cli("complete", self.fx.directory, "--id", "TASK-001", "--expect-sha256",
                 load(self.fx.directory)[1], expected=1)
        context = self.cli("context", self.fx.directory, "--id", "TASK-001")
        before = self.fx.directory / "before.json"
        before.write_text(json.dumps(context), encoding="utf-8")
        descriptor = self.fx.directory / "descriptor.json"
        descriptor.write_text(json.dumps({"reviewer": "independent-code-reviewer",
                                          "verdict": "accepted"}), encoding="utf-8")
        report = self.fx.directory / "review.md"
        report.write_text("Independent isolated fixture review; synthetic task evidence.\n", encoding="utf-8")
        review_bundle = self.fx.directory / "review.zip"
        self.cli("package-review", self.fx.directory, "--id", "TASK-001", "--kind", "code_review",
                 "--before", before, "--descriptor", descriptor, "--report", report,
                 "--output", review_bundle)
        self.adopt(review_bundle)
        self.cli("complete", self.fx.directory, "--id", "TASK-001", "--expect-sha256",
                 load(self.fx.directory)[1])
        self.cli("check", self.fx.directory, "--id", "TASK-001", "--gate", "resumption")
        item = load(self.fx.directory)[0]["items"][0]
        self.assertEqual(item["status"], "done")
        self.assertEqual(item["completion"], item["checkpoint"])
        prior_artifact = self.fx.directory / item["checks"][0]["artifact"]
        prior_bytes = prior_artifact.read_bytes()
        failed = self.run_check("failed", self.fx.repo, "raise SystemExit(7)", expected=1)
        self.adopt(failed)
        self.assertEqual(prior_artifact.read_bytes(), prior_bytes)
        self.assertEqual(load(self.fx.directory)[0]["items"][0]["checks"][0]["outcome"], "failed")
        self.cli("complete", self.fx.directory, "--id", "TASK-001", "--expect-sha256",
                 load(self.fx.directory)[1], expected=1)
        self.cli("check", self.fx.directory, "--id", "TASK-001", "--gate", "resumption", expected=1)

    def test_worker_transfer_reuses_identical_content_but_archives_stale_content(self):
        worker = test_task.TaskTests(methodName="runTest")
        worker.setUp()
        self.addCleanup(worker.tearDown)
        worker.git("symbolic-ref", "HEAD", "refs/heads/worker")
        good = self.run_check("worker-good", worker.repo, "print('worker')")
        self.adopt(good)
        original = (self.fx.directory / "task.json").read_bytes()
        (worker.repo / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
        stale = self.run_check("worker-new-content", worker.repo, "print('changed')")
        result = self.adopt(stale, expected=1)
        self.assertFalse(result["adopted"])
        self.assertTrue(Path(result["bundle"]).is_file())
        self.assertEqual((self.fx.directory / "task.json").read_bytes(), original)
