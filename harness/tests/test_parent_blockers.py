"""Regression checks for blockers on shared parent contracts."""
from pathlib import Path
import tempfile
import unittest

import test_mathematics
from task_support.formats import TaskError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / ".agent-work/tasks/harness-gate-fixes/parent-blockers/fixtures"


class Fixture(test_mathematics.Fixture):
    def __init__(self):
        FIXTURES.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=FIXTURES)
        self.repo = Path(self.temporary.name).resolve()
        self.directory = self.repo / ".agent-work/tasks/example"
        self.git("init", "-q", "-b", "test-main")
        (self.repo / ".gitignore").write_text("/.agent-work/tasks/\n", encoding="utf-8")
        (self.repo / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git("add", ".gitignore", "source.py")

    def close(self):
        if not self.repo.is_relative_to(FIXTURES.resolve()):
            raise RuntimeError("Refusing fixture cleanup outside its assigned directory")
        self.temporary.cleanup()


class ParentBlockerTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)
        self.manifest = self.fx.epic_with_children()
        self.parent, self.child, self.sibling = self.manifest["items"]
        self.fx.completed(self.manifest, self.child)

    def finding(self, blocking=True, disposition="open"):
        return {"id": "F-1", "blocking": blocking, "disposition": disposition,
                "reason": "Shared contract finding"}

    def run_stage(self, stage):
        if stage == "start":
            self.child["status"] = "ready"
        elif stage == "active resumption":
            self.child["status"] = "in_progress"
        else:
            self.child["status"] = "done"
        gate = "resumption" if stage.endswith("resumption") else stage
        self.fx.gate(self.manifest, gate, self.child["id"])

    def test_unresolved_parent_blockers_block_all_child_execution_gates(self):
        for disposition in ("open", "deferred", "unchanged"):
            self.parent["findings"] = [self.finding(disposition=disposition)]
            for stage in ("start", "active resumption", "done resumption", "completion"):
                with self.subTest(disposition=disposition, stage=stage):
                    with self.assertRaisesRegex(TaskError, "EPIC-001:.*blocking"):
                        self.run_stage(stage)

    def test_nonblocking_or_resolved_parent_and_sibling_findings_do_not_block(self):
        for location, finding in (("parent", self.finding(False, "open")),
                                  ("parent", self.finding(True, "resolved")),
                                  ("sibling", self.finding(True, "open"))):
            self.parent["findings"] = [finding] if location == "parent" else []
            self.sibling["findings"] = [finding] if location == "sibling" else []
            for stage in ("start", "active resumption", "done resumption", "completion"):
                with self.subTest(location=location, finding=finding, stage=stage):
                    self.run_stage(stage)

    def test_nonactive_resumption_does_not_enforce_parent_blocker(self):
        self.parent["findings"] = [self.finding()]
        for status in ("draft", "ready"):
            self.child["status"] = status
            with self.subTest(status=status):
                self.fx.gate(self.manifest, "resumption", self.child["id"])

    def test_own_blockers_still_block_start_active_resume_and_completion(self):
        self.child["findings"] = [self.finding()]
        for stage in ("start", "active resumption", "done resumption", "completion"):
            with self.subTest(stage=stage), self.assertRaises(TaskError):
                self.run_stage(stage)

    def test_mathematical_parent_retains_review_and_blocker_contract(self):
        self.fx.classify(self.parent)
        self.fx.completed(self.manifest, self.child)
        self.fx.math_report(self.manifest, self.parent, "specification")
        self.parent["findings"] = [self.finding()]
        for stage in ("start", "active resumption", "done resumption", "completion"):
            with self.subTest(stage=stage), self.assertRaisesRegex(TaskError, "mathematical contract.*blocking"):
                self.run_stage(stage)
        self.parent["findings"] = []
        self.parent["mathematics"]["specification_review"] = None
        with self.assertRaisesRegex(TaskError, "accepted mathematical specification"):
            self.run_stage("start")
