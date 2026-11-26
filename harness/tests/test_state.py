"""Isolated behavioral tests for transactional task state."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_task as fixtures
import task
from task_support.artifacts import load
from task_support.formats import TaskError
from task_support.state import mutate_task


class StateTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.TaskTests(methodName="runTest")
        self.f.setUp()
        self.manifest = self.f.init()
        self.path = self.f.directory / "task.json"

    def tearDown(self):
        self.f.tearDown()

    def mutate(self, fn, expected=None):
        return mutate_task(self.f.repo, self.f.directory, expected or load(self.f.directory)[1], "test", fn)

    def cli(self, command, *extra):
        return subprocess.run([sys.executable, "-B", str(fixtures.HELPER / "task.py"), "--repo", str(self.f.repo), command, str(self.f.directory), "--id", "TASK-001", "--expect-sha256", load(self.f.directory)[1], *extra], capture_output=True, text=True)

    def test_checkpoint_noop_history_and_lock(self):
        before = self.path.read_bytes()
        first = self.cli("checkpoint")
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        self.assertTrue(result["changed"])
        self.assertEqual((self.f.directory / ".state-history" / (result["before_sha256"] + ".json")).read_bytes(), before)
        history = list((self.f.directory / ".state-history").iterdir())
        second = self.cli("checkpoint")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(json.loads(second.stdout)["changed"])
        self.assertEqual(set(history), set((self.f.directory / ".state-history").iterdir()))
        revision = load(self.f.directory)[1]
        (self.f.directory / ".task.lock").write_text("other")
        with self.assertRaises(TaskError):
            self.mutate(lambda c, s: None, revision)
        self.assertEqual((self.f.directory / ".task.lock").read_text(), "other")

    def test_reconcile_requires_reason_and_keeps_previous_checkpoint(self):
        first = self.cli("checkpoint")
        self.assertEqual(first.returncode, 0, first.stderr)
        previous = self.path.read_bytes()
        old_hash = load(self.f.directory)[1]
        (self.f.repo / "source.py").write_text("new source")
        self.assertNotEqual(self.cli("checkpoint").returncode, 0)
        self.assertEqual(self.path.read_bytes(), previous)
        result = self.cli("checkpoint", "--reason", "Source was deliberately revised")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.f.directory / ".state-history" / (old_hash + ".json")).read_bytes(), previous)
        records = [json.loads(p.read_text(encoding="utf-8")) for p in (self.f.directory / ".state-history").glob("operation-*.json")]
        self.assertTrue(any(r["reason"] == "Source was deliberately revised" for r in records))
    def test_stale_invalid_branch_and_failed_atomic_write(self):
        before = self.path.read_bytes()
        for value in ("0" * 64, "invalid"):
            with self.assertRaises(TaskError):
                self.mutate(lambda c, s: None, value)
        self.f.git("symbolic-ref", "HEAD", "refs/heads/other")
        with self.assertRaises(TaskError):
            self.mutate(lambda c, s: None)
        self.f.git("symbolic-ref", "HEAD", "refs/heads/test-main")
        with patch("task_support.state.atomic_write", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                self.mutate(lambda c, s: c["handoff"].update(notes="changed"))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(self.mutate(lambda c, s: c["handoff"].update(notes="changed"))["changed"])

    def test_cli_rejects_legacy_and_malformed_without_writing(self):
        for kind in ("legacy", "malformed"):
            with self.subTest(kind=kind):
                manifest = json.loads(json.dumps(self.manifest))
                if kind == "legacy":
                    manifest["format_version"] = 1
                    del manifest["items"][0]["mathematics"]
                else:
                    manifest["items"][0]["mathematics"] = None
                self.f.save(manifest)
                before = self.path.read_bytes()
                result = self.cli("checkpoint")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertFalse((self.f.directory / ".state-history").exists())
                self.assertFalse((self.f.directory / ".task.lock").exists())
    def test_tracked_manifest_cli_refuses_without_writes(self):
        before = self.path.read_bytes()
        self.f.git("add", "-f", "--", ".agent-work/tasks/example/task.json")
        result = self.cli("checkpoint")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.f.directory / ".state-history").exists())
        self.assertFalse((self.f.directory / ".task.lock").exists())

    def test_cli_reports_postcommit_cleanup_failure_and_noop(self):
        old_sha = load(self.f.directory)[1]
        lock = self.f.directory / ".task.lock"
        unlink = Path.unlink
        def failing_unlink(path, *args, **kwargs):
            if path == lock:
                raise PermissionError("injected lock cleanup failure")
            return unlink(path, *args, **kwargs)
        def invoke(expected):
            stdout, stderr = io.StringIO(), io.StringIO()
            args = ["--repo", str(self.f.repo), "checkpoint", str(self.f.directory),
                    "--id", "TASK-001", "--expect-sha256", expected]
            with patch.object(Path, "unlink", failing_unlink), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = task.main(args)
            return code, json.loads(stdout.getvalue()), stderr.getvalue()
        code, report, error = invoke(old_sha)
        self.assertEqual(code, 1)
        self.assertEqual(error, "")
        self.assertTrue(report["changed"])
        self.assertEqual(report["before_sha256"], old_sha)
        self.assertEqual(report["manifest_sha256"], fixtures.digest(self.path.read_bytes()))
        self.assertIn("injected lock cleanup failure", report["cleanup_error"])
        self.assertTrue(lock.exists())
        lock.unlink()
        current_sha = load(self.f.directory)[1]
        code, report, error = invoke(current_sha)
        self.assertEqual(code, 1)
        self.assertFalse(report["changed"])
        self.assertEqual(report["before_sha256"], current_sha)
        self.assertEqual(report["manifest_sha256"], current_sha)
        self.assertIn("injected lock cleanup failure", report["cleanup_error"])
        self.assertTrue(lock.exists())
        lock.unlink()

    def test_cleanup_failure_does_not_turn_body_failure_into_success(self):
        revision = load(self.f.directory)[1]
        lock = self.f.directory / ".task.lock"
        unlink = Path.unlink
        def failing_unlink(path, *args, **kwargs):
            if path == lock:
                raise PermissionError("cleanup failure")
            return unlink(path, *args, **kwargs)
        before = self.path.read_bytes()
        with patch.object(Path, "unlink", failing_unlink):
            with self.assertRaises(PermissionError):
                self.mutate(lambda candidate, snapshot: (_ for _ in ()).throw(OSError("body failure")), revision)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(lock.exists())
        lock.unlink()
    def test_new_evidence_drift_after_callback_is_refused(self):
        from task_support.artifacts import spec_digest
        from task_support import state
        item = self.manifest["items"][0]
        signature = spec_digest(self.f.directory, self.manifest, item)
        record = self.f.report("new-review.md", signature, kind="readiness",
                               reviewer="reviewer", verdict="accepted")
        evidence_path = self.f.directory / record["artifact"]
        good_bytes = evidence_path.read_bytes()
        before = self.path.read_bytes()
        real_lint = state.lint
        calls = 0
        def drift_after_lint(repo, directory, manifest):
            nonlocal calls
            result = real_lint(repo, directory, manifest)
            calls += 1
            if calls == 3:
                evidence_path.write_bytes(b"corrupted after callback")
            return result
        def adopt(candidate, snapshot):
            candidate["items"][0]["spec_reviews"].append(record.copy())
        with patch("task_support.state.lint", side_effect=drift_after_lint):
            with self.assertRaisesRegex(TaskError, "evidence content differs"):
                self.mutate(adopt)
        self.assertEqual(calls, 3)
        self.assertEqual(self.path.read_bytes(), before)
        evidence_path.write_bytes(good_bytes)
        result = self.mutate(adopt)
        self.assertTrue(result["changed"])
        result = self.mutate(lambda candidate, snapshot: None)
        self.assertFalse(result["changed"])
    def test_input_drift(self):
        for kind in ("source", "document", "manifest"):
            with self.subTest(kind=kind):
                original = self.path.read_bytes()
                doc = self.f.directory / self.manifest["items"][0]["document"]
                source = self.f.repo / "source.py"
                old_doc, old_source = doc.read_bytes(), source.read_bytes()
                def change(candidate, snapshot):
                    candidate["handoff"]["notes"] = "change"
                    target = {"source": source, "document": doc, "manifest": self.path}[kind]
                    target.write_bytes(target.read_bytes() + b"\n")
                with self.assertRaises(TaskError):
                    self.mutate(change)
                self.path.write_bytes(original)
                doc.write_bytes(old_doc)
                source.write_bytes(old_source)

    def test_complete_gates_reconciliation_and_done_idempotence(self):
        manifest = self.manifest
        item = self.f.fill(manifest, "TASK-001")
        self.f.approve(manifest, item)
        self.f.save(manifest)
        self.assertNotEqual(self.cli("complete").returncode, 0)
        self.f.completed(manifest, item)
        item["status"] = "ready"
        item["completion"] = None
        item["checkpoint"] = None
        self.f.save(manifest)
        first = self.cli("complete")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(load(self.f.directory)[0]["items"][0]["status"], "done")
        second = self.cli("complete")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertFalse(json.loads(second.stdout)["changed"])
        (self.f.repo / "source.py").write_text("changed")
        old = self.path.read_bytes()
        self.assertNotEqual(self.cli("checkpoint").returncode, 0)
        self.assertNotEqual(self.cli("checkpoint", "--reason", "reconcile").returncode, 0)
        self.assertEqual(self.path.read_bytes(), old)

    def test_report_drift_and_history_conflict(self):
        manifest = self.manifest
        item = self.f.fill(manifest, "TASK-001")
        self.f.approve(manifest, item)
        self.f.save(manifest)
        report = self.f.directory / item["spec_reviews"][0]["artifact"]
        before = self.path.read_bytes()
        def drift(candidate, snapshot):
            candidate["handoff"]["notes"] = "changed"
            report.write_bytes(report.read_bytes() + b"changed")
        with self.assertRaises(TaskError):
            self.mutate(drift)
        self.assertEqual(self.path.read_bytes(), before)
        revision = load(self.f.directory)[1]
        history = self.f.directory / ".state-history"
        history.mkdir()
        (history / (revision + ".json")).write_bytes(b"conflict")
        with self.assertRaises(TaskError):
            self.mutate(lambda c, s: c["handoff"].update(notes="changed"))
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
