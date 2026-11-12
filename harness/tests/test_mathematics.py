"""Independent behavioral checks of mathematical gates and explicit migration.

Only isolated harness Git fixtures execute; no application code is imported.
The existing TaskTests methods are composed, not inherited or imported as a
TestCase, so unittest discovery does not run its cases twice.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_task

from task_support.artifacts import load, source_snapshot, spec_digest
from task_support.formats import TaskError, digest, new_mathematics
from task_support.lint import lint
from task_support.mathematics import scope_digest
from task_support.migration import migrate


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "harness/scripts/task/task.py"
FIXTURES = ROOT / ".agent-work/tasks/harness-mathematics-reviewer/helper-verification/fixtures"


class Fixture:
    """Use established document/evidence setup without inheriting test methods."""

    git = test_task.TaskTests.git
    save = test_task.TaskTests.save
    init = test_task.TaskTests.init
    fill = test_task.TaskTests.fill
    report = test_task.TaskTests.report
    approve = test_task.TaskTests.approve
    completed = test_task.TaskTests.completed
    gate = test_task.TaskTests.gate
    ready = test_task.TaskTests.ready
    epic_with_children = test_task.TaskTests.epic_with_children

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

    @staticmethod
    def classify(item, required=True):
        item["mathematics"].update(
            required=required,
            rationale="Changes a mathematical weighting rule." if required else
                      "Changes presentation only and preserves numerical behavior.",
            authors=[f"formulator-{item['id']}"] if required else [])

    def math_report(self, manifest, item, stage, reviewer=None):
        source = source_snapshot(self.repo)["source_sha256"] if stage == "implementation" else None
        record = self.report(
            f"{item['id']}-math-{stage}.md", spec_digest(self.directory, manifest, item), source,
            reviewer=reviewer or f"math-{stage}-{item['id']}", verdict="accepted",
            scope_sha256=scope_digest(self.directory, manifest, item, stage))
        item["mathematics"][f"{stage}_review"] = record
        return record

    def mathematical(self):
        manifest, item = self.ready()
        self.classify(item)
        self.approve(manifest, item)
        self.math_report(manifest, item, "specification")
        return manifest, item

    def finish_math(self, manifest, item):
        self.completed(manifest, item)
        if item["mathematics"]["required"]:
            self.math_report(manifest, item, "specification")
            self.math_report(manifest, item, "implementation")

    def cli(self, command, *args):
        return subprocess.run(
            [sys.executable, "-B", str(HELPER), "--repo", str(self.repo), command,
             str(self.directory), *args], capture_output=True, text=True)

    def bytes(self):
        return {p.relative_to(self.directory).as_posix(): p.read_bytes()
                for p in self.directory.rglob("*") if p.is_file()}

    def legacy(self, completed=False):
        manifest, item = self.ready()
        if completed:
            self.completed(manifest, item)
        manifest["format_version"] = 1
        for entry in manifest["items"]:
            del entry["mathematics"]
        # Old records deliberately use a prior digest that must never be rebound.
        item["approval"]["spec_sha256"] = "a" * 64
        for record in [*item["spec_reviews"], *item["checks"], item["code_review"],
                       item["checkpoint"], item["completion"]]:
            if record is not None:
                record["spec_sha256"] = "a" * 64
        self.save(manifest)
        lint(self.repo, self.directory, manifest, legacy=True)
        return manifest


class MathematicsTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)

    def test_new_manifest_is_v2_and_documents_stay_v1(self):
        manifest = self.fx.init()
        item = manifest["items"][0]
        self.assertEqual(manifest["format_version"], 2)
        self.assertEqual(item["mathematics"], new_mathematics())
        self.assertTrue((self.fx.directory / item["document"]).read_text(
            encoding="utf-8").startswith("<!-- task-format: 1;"))
        lint(self.fx.repo, self.fx.directory, manifest)

    def test_unassessed_impact_is_structurally_valid_but_blocks_specification(self):
        manifest, item = self.fx.ready()
        item["mathematics"] = new_mathematics()
        lint(self.fx.repo, self.fx.directory, manifest)
        with self.assertRaisesRegex(TaskError, "unassessed"):
            self.fx.gate(manifest, "specification")

    def test_assessed_impact_requires_boolean_and_reason(self):
        manifest, item = self.fx.ready()
        for required in (1, 0, "false", [], {}):
            with self.subTest(required=required):
                item["mathematics"]["required"] = required
                with self.assertRaisesRegex(TaskError, "Boolean"):
                    lint(self.fx.repo, self.fx.directory, manifest)
        for required in (False, True):
            for reason in ("", " \t\n", None, 5):
                with self.subTest(required=required, reason=reason):
                    item["mathematics"].update(required=required, rationale=reason)
                    with self.assertRaises(TaskError):
                        self.fx.gate(manifest, "specification")

    def test_justified_nonmathematical_work_needs_no_math_reports(self):
        manifest, item = self.fx.ready()
        self.fx.gate(manifest, "specification")
        self.fx.gate(manifest)
        self.fx.completed(manifest, item)
        self.fx.gate(manifest, "completion")
        self.fx.gate(manifest, "resumption")
        self.assertIsNone(item["mathematics"]["implementation_review"])

    def test_digest_binds_classification_and_reason_but_not_provenance_or_progress(self):
        manifest, item = self.fx.mathematical()
        original = spec_digest(self.fx.directory, manifest, item)
        for field, value in (("required", False), ("rationale", "Different mathematical scope.")):
            candidate = copy.deepcopy(manifest)
            candidate["items"][0]["mathematics"][field] = value
            self.assertNotEqual(original, spec_digest(self.fx.directory, candidate, candidate["items"][0]))
        item["mathematics"]["authors"].append("adopted-correction-proposer")
        item["mathematics"]["specification_review"]["reviewer"] = "different-reviewer"
        item["status"] = "in_progress"
        item["findings"] = [{"id": "F-1", "blocking": True, "disposition": "open", "reason": "Gap"}]
        self.assertEqual(original, spec_digest(self.fx.directory, manifest, item))

    def test_specification_gate_permits_required_work_before_math_review(self):
        manifest, item = self.fx.mathematical()
        item["mathematics"]["specification_review"] = None
        self.fx.gate(manifest, "specification")
        with self.assertRaisesRegex(TaskError, "accepted mathematical specification"):
            self.fx.gate(manifest)

    def test_start_rejects_missing_rejected_incomplete_or_invalid_math_evidence(self):
        manifest, _ = self.fx.mathematical()
        for change in (
            lambda m: m.update(specification_review=None),
            lambda m: m["specification_review"].update(verdict="changes_requested"),
            lambda m: m["specification_review"].update(verdict="incomplete"),
            lambda m: m["specification_review"].update(spec_sha256="0" * 64),
            lambda m: m["specification_review"].update(sha256="0" * 64),
            lambda m: m["specification_review"].update(artifact="evidence/missing.md"),
            lambda m: m["specification_review"].update(source_sha256="0" * 64),
            lambda m: m["specification_review"].update(scope_sha256="0" * 64),
            lambda m: m["specification_review"].pop("scope_sha256"),
        ):
            candidate = copy.deepcopy(manifest)
            change(candidate["items"][0]["mathematics"])
            with self.subTest(change=change), self.assertRaises(TaskError):
                self.fx.gate(candidate)
        self.fx.gate(manifest)

    def test_report_content_is_checked_for_empty_and_modified_evidence(self):
        manifest, item = self.fx.mathematical()
        path = self.fx.directory / item["mathematics"]["specification_review"]["artifact"]
        for content in ("", "A changed finding after acceptance.\n"):
            path.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(TaskError):
                self.fx.gate(manifest)

    def test_specification_reviewer_cannot_be_coordinator_formulator_or_contributor(self):
        manifest, item = self.fx.mathematical()
        item["contributors"] = ["developer"]
        for reviewer in (manifest["coordinator"], item["mathematics"]["authors"][0], "developer"):
            item["mathematics"]["specification_review"]["reviewer"] = reviewer
            with self.subTest(reviewer=reviewer), self.assertRaisesRegex(TaskError, "independent"):
                self.fx.gate(manifest)

    def test_adopted_correction_disqualifies_original_reviewer_without_digest_change(self):
        manifest, item = self.fx.mathematical()
        self.fx.gate(manifest)
        previous = spec_digest(self.fx.directory, manifest, item)
        item["mathematics"]["authors"].append(item["mathematics"]["specification_review"]["reviewer"])
        self.assertEqual(previous, spec_digest(self.fx.directory, manifest, item))
        with self.assertRaisesRegex(TaskError, "independent"):
            self.fx.gate(manifest)

    def test_specification_drift_requires_math_reassessment_after_ordinary_reapproval(self):
        manifest, item = self.fx.mathematical()
        path = self.fx.directory / item["document"]
        path.write_text(path.read_text(encoding="utf-8") + "\nNew weighting definition.\n", encoding="utf-8")
        self.fx.approve(manifest, item)
        with self.assertRaisesRegex(TaskError, "stale specification"):
            self.fx.gate(manifest)

    def test_completion_requires_distinct_independent_implementation_reviewer(self):
        manifest, item = self.fx.mathematical()
        self.fx.finish_math(manifest, item)
        self.fx.gate(manifest, "completion")
        prohibited = [manifest["coordinator"], "developer", *item["mathematics"]["authors"],
                      item["mathematics"]["specification_review"]["reviewer"]]
        for reviewer in prohibited:
            item["mathematics"]["implementation_review"]["reviewer"] = reviewer
            with self.subTest(reviewer=reviewer), self.assertRaisesRegex(TaskError, "independent"):
                self.fx.gate(manifest, "completion")

    def test_completion_rejects_missing_rejected_incomplete_stale_and_corrupt_report(self):
        manifest, item = self.fx.mathematical()
        self.fx.finish_math(manifest, item)
        for change in (
            lambda m: m.update(implementation_review=None),
            lambda m: m["implementation_review"].update(verdict="changes_requested"),
            lambda m: m["implementation_review"].update(verdict="incomplete"),
            lambda m: m["implementation_review"].update(source_sha256="0" * 64),
            lambda m: m["implementation_review"].update(spec_sha256="0" * 64),
            lambda m: m["implementation_review"].update(sha256="0" * 64),
            lambda m: m["implementation_review"].update(artifact="evidence/missing.md"),
            lambda m: m["implementation_review"].pop("source_sha256"),
            lambda m: m["implementation_review"].update(scope_sha256="0" * 64),
            lambda m: m["implementation_review"].pop("scope_sha256"),
        ):
            candidate = copy.deepcopy(manifest)
            change(candidate["items"][0]["mathematics"])
            with self.subTest(change=change), self.assertRaises(TaskError):
                self.fx.gate(candidate, "completion")

    def test_source_drift_cannot_reuse_math_review_when_other_evidence_is_refreshed(self):
        manifest, item = self.fx.mathematical()
        self.fx.finish_math(manifest, item)
        (self.fx.repo / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.fx.completed(manifest, item)
        with self.assertRaisesRegex(TaskError, "stale source"):
            self.fx.gate(manifest, "completion")

    def test_resumption_rechecks_math_record_and_independence(self):
        manifest, item = self.fx.mathematical()
        self.fx.finish_math(manifest, item)
        self.fx.gate(manifest, "resumption")
        item["mathematics"]["authors"].append(item["mathematics"]["implementation_review"]["reviewer"])
        with self.assertRaisesRegex(TaskError, "independent"):
            self.fx.gate(manifest, "resumption")
        item["mathematics"]["authors"].pop()
        item["status"] = "in_progress"
        item["mathematics"]["specification_review"] = None
        with self.assertRaisesRegex(TaskError, "accepted mathematical specification"):
            self.fx.gate(manifest, "resumption")

    def test_open_math_blocker_prevents_start_completion_and_active_resumption(self):
        manifest, item = self.fx.mathematical()
        self.fx.finish_math(manifest, item)
        item["status"] = "in_progress"
        item["findings"] = [{"id": "MATH-1", "blocking": True, "disposition": "open", "reason": "Unverified assumption"}]
        for gate in ("start", "completion", "resumption"):
            with self.subTest(gate=gate), self.assertRaisesRegex(TaskError, "blocking"):
                self.fx.gate(manifest, gate)

    def test_math_structure_rejects_unknown_fields_duplicate_authors_and_wrong_evidence_types(self):
        manifest, _ = self.fx.mathematical()
        for change in (
            lambda m: m.update(unknown=True),
            lambda m: m.update(authors=["same", "same"]),
            lambda m: m.update(authors="author"),
            lambda m: m["specification_review"].update(reviewer=" "),
            lambda m: m["specification_review"].update(sha256=True),
            lambda m: m["specification_review"].update(scope_sha256=True),
            lambda m: m.update(required=False),
            lambda m: m.pop("implementation_review"),
        ):
            candidate = copy.deepcopy(manifest)
            change(candidate["items"][0]["mathematics"])
            with self.subTest(change=change), self.assertRaises(TaskError):
                lint(self.fx.repo, self.fx.directory, candidate)


class MathematicalStructureTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)

    def epic(self, *, parent_required=False, first_required=False, second_required=True):
        manifest = self.fx.epic_with_children()
        for item, required in zip(manifest["items"], (parent_required, first_required, second_required)):
            self.fx.classify(item, required)
        for item in manifest["items"]:
            self.fx.approve(manifest, item)
            if item["mathematics"]["required"]:
                self.fx.math_report(manifest, item, "specification")
        return manifest

    def test_child_start_requires_parent_classification_and_accepted_math_review(self):
        manifest = self.epic(parent_required=True, second_required=False)
        epic, first, _ = manifest["items"]
        self.fx.gate(manifest)
        epic["mathematics"]["specification_review"] = None
        with self.assertRaisesRegex(TaskError, "EPIC-001: accepted mathematical specification"):
            self.fx.gate(manifest)
        epic["mathematics"] = new_mathematics()
        self.fx.approve(manifest, first)
        with self.assertRaisesRegex(TaskError, "EPIC-001: mathematical impact is unassessed"):
            self.fx.gate(manifest)

    def test_parent_classification_changes_child_digest(self):
        manifest = self.epic()
        epic, first, _ = manifest["items"]
        previous = spec_digest(self.fx.directory, manifest, first)
        self.fx.classify(epic)
        self.assertNotEqual(previous, spec_digest(self.fx.directory, manifest, first))

    def test_parent_blocker_prevents_child_start(self):
        manifest = self.epic(parent_required=True)
        manifest["items"][0]["findings"] = [{"id": "MATH-1", "blocking": True,
            "disposition": "open", "reason": "Unresolved shared assumption"}]
        with self.assertRaisesRegex(TaskError, "mathematical contract.*blocking"):
            self.fx.gate(manifest)

    def test_child_math_review_cannot_be_parent_formulator(self):
        manifest = self.epic(parent_required=True, first_required=True)
        epic, first, _ = manifest["items"]
        first["mathematics"]["specification_review"]["reviewer"] = epic["mathematics"]["authors"][0]
        with self.assertRaisesRegex(TaskError, "independent"):
            self.fx.gate(manifest)

    def test_dependency_evidence_remains_bound_to_accepted_source_revision(self):
        manifest = self.epic(first_required=True)
        _, first, second = manifest["items"]
        self.fx.finish_math(manifest, first)
        previous = first["completion"]["source_sha256"]
        (self.fx.repo / "source.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.assertNotEqual(previous, source_snapshot(self.fx.repo)["source_sha256"])
        self.fx.gate(manifest, item_id=second["id"])
        self.fx.finish_math(manifest, second)
        self.fx.gate(manifest, "completion", second["id"])
        first["mathematics"]["implementation_review"]["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(TaskError, "stale source"):
            self.fx.gate(manifest, "completion", second["id"])

    def test_dependency_formulator_cannot_review_successor(self):
        manifest = self.epic(first_required=True)
        _, first, second = manifest["items"]
        self.fx.finish_math(manifest, first)
        second["mathematics"]["specification_review"]["reviewer"] = first["mathematics"]["authors"][0]
        with self.assertRaisesRegex(TaskError, "independent"):
            self.fx.gate(manifest, item_id=second["id"])

    def test_dependency_specification_reviewer_cannot_review_successor_implementation(self):
        manifest = self.epic(first_required=True)
        _, first, second = manifest["items"]
        for item in (first, second):
            self.fx.finish_math(manifest, item)
        second["mathematics"]["implementation_review"]["reviewer"] = first["mathematics"]["specification_review"]["reviewer"]
        with self.assertRaisesRegex(TaskError, "independent"):
            self.fx.gate(manifest, "completion", second["id"])

    def test_transitive_dependency_author_excluded_without_unrelated_sibling_exclusion(self):
        self.fx.epic_with_children()
        self.fx.init("subtask", "TASK-003", "EPIC-001")
        self.fx.init("specification", "TASK-003")
        self.fx.init("subtask", "TASK-004", "EPIC-001")
        manifest = self.fx.init("specification", "TASK-004")
        epic, first, second, third, unrelated = manifest["items"]
        for item in manifest["items"]:
            self.fx.fill(manifest, item["id"])
            # A nonmathematical intermediary still declares a mathematical input.
            self.fx.classify(item, item not in (epic, second))
        second["depends_on"] = [first["id"]]
        third["depends_on"] = [second["id"]]
        for item in manifest["items"]:
            self.fx.approve(manifest, item)
            if item["mathematics"]["required"]:
                self.fx.math_report(manifest, item, "specification")
        for item in (first, second):
            self.fx.finish_math(manifest, item)
        record = third["mathematics"]["specification_review"]
        record["reviewer"] = unrelated["mathematics"]["authors"][0]
        self.fx.gate(manifest, item_id=third["id"])
        record["reviewer"] = first["mathematics"]["authors"][0]
        with self.assertRaisesRegex(TaskError, "independent"):
            self.fx.gate(manifest, item_id=third["id"])

    def test_required_epic_needs_its_own_integrated_math_review(self):
        manifest = self.epic(parent_required=True, first_required=True)
        epic, first, second = manifest["items"]
        for item in (first, second, epic):
            self.fx.finish_math(manifest, item)
        self.fx.gate(manifest, "completion", epic["id"])
        epic["mathematics"]["implementation_review"] = None
        with self.assertRaisesRegex(TaskError, "EPIC-001: accepted mathematical implementation"):
            self.fx.gate(manifest, "completion", epic["id"])

    def test_epic_rejects_child_authors_contributors_and_child_specification_reviewers(self):
        manifest = self.epic(parent_required=True, first_required=True)
        epic, first, second = manifest["items"]
        for item in (first, second, epic):
            self.fx.finish_math(manifest, item)
        first["contributors"] = ["unique-child-developer"]
        excluded = [first["mathematics"]["authors"][0], "unique-child-developer",
                    first["mathematics"]["specification_review"]["reviewer"]]
        for reviewer in excluded:
            epic["mathematics"]["implementation_review"]["reviewer"] = reviewer
            with self.subTest(reviewer=reviewer), self.assertRaisesRegex(TaskError, "independent"):
                self.fx.gate(manifest, "completion", epic["id"])

    def test_nonmathematical_parent_cannot_bypass_required_child_completion_review(self):
        manifest = self.epic(first_required=True)
        epic, first, second = manifest["items"]
        for item in (first, second, epic):
            self.fx.finish_math(manifest, item)
        self.fx.gate(manifest, "completion", epic["id"])
        first["mathematics"]["implementation_review"] = None
        with self.assertRaisesRegex(TaskError, "TASK-001: accepted mathematical implementation"):
            self.fx.gate(manifest, "completion", epic["id"])


class MathematicalScopeBindingTests(unittest.TestCase):
    """Regressions for PR-001: drift of included contracts must reach their users."""

    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)

    def completed_epic(self, *, parent_required=True, first_required=True):
        manifest = self.fx.epic_with_children()
        epic, first, second = manifest["items"]
        for item, required in zip(manifest["items"], (parent_required, first_required, True)):
            self.fx.classify(item, required)
        for item in (first, second, epic):
            self.fx.finish_math(manifest, item)
        self.fx.gate(manifest, "completion", epic["id"])
        return manifest

    def change_formula(self, item):
        path = self.fx.directory / (item["specification"] or item["document"])
        path.write_text(path.read_text(encoding="utf-8") +
                        "\nMathematical fixture revision: normalize by n - 1 instead of n.\n",
                        encoding="utf-8")

    def test_dependency_drift_requires_both_stages_to_reassess_successor(self):
        manifest = self.completed_epic(parent_required=False)
        _, first, second = manifest["items"]
        previous = copy.deepcopy(second)
        snapshot = source_snapshot(self.fx.repo)
        self.change_formula(first)
        self.fx.finish_math(manifest, first)
        self.assertEqual(snapshot, source_snapshot(self.fx.repo))
        self.assertEqual(previous, second)
        self.assertEqual(previous["approval"]["spec_sha256"], spec_digest(self.fx.directory, manifest, second))
        for gate, status in (("start", "ready"), ("completion", "done"), ("resumption", "done")):
            second["status"] = status
            with self.subTest(gate=gate), self.assertRaisesRegex(TaskError, "TASK-002: mathematical specification.*stale included contracts"):
                self.fx.gate(manifest, gate, second["id"])
        # The fixture represents a new bounded review; refreshing ordinary
        # approvals alone must not suffice, and each stage must be reassessed.
        self.fx.approve(manifest, second)
        second["status"] = "ready"
        with self.assertRaisesRegex(TaskError, "stale included contracts"):
            self.fx.gate(manifest, "start", second["id"])
        self.fx.math_report(manifest, second, "specification")
        self.fx.gate(manifest, "start", second["id"])
        second["status"] = "done"
        for gate in ("completion", "resumption"):
            with self.subTest(gate=gate), self.assertRaisesRegex(TaskError, "TASK-002: mathematical implementation.*stale included contracts"):
                self.fx.gate(manifest, gate, second["id"])
        self.fx.math_report(manifest, second, "implementation")
        self.fx.gate(manifest, "completion", second["id"])
        self.fx.gate(manifest, "resumption", second["id"])

    def test_child_drift_invalidates_epic_integration_without_widening_approval(self):
        manifest = self.completed_epic()
        epic, _, second = manifest["items"]
        previous = copy.deepcopy(epic)
        self.change_formula(second)
        self.fx.finish_math(manifest, second)
        self.assertEqual(previous, epic)
        self.assertEqual(previous["approval"]["spec_sha256"], spec_digest(self.fx.directory, manifest, epic))
        self.assertEqual(previous["mathematics"]["specification_review"]["scope_sha256"],
                         scope_digest(self.fx.directory, manifest, epic, "specification"))
        for gate in ("completion", "resumption"):
            with self.subTest(gate=gate), self.assertRaisesRegex(TaskError, "EPIC-001: mathematical implementation.*stale included contracts"):
                self.fx.gate(manifest, gate, epic["id"])
        self.fx.math_report(manifest, epic, "implementation")
        self.fx.gate(manifest, "completion", epic["id"])
        self.fx.gate(manifest, "resumption", epic["id"])

    def test_dependency_classification_change_invalidates_successor_scope(self):
        manifest = self.completed_epic(parent_required=False, first_required=False)
        _, first, second = manifest["items"]
        original_review = copy.deepcopy(second["mathematics"]["specification_review"])
        self.fx.classify(first, True)
        self.fx.finish_math(manifest, first)
        second["status"] = "ready"
        self.assertEqual(original_review, second["mathematics"]["specification_review"])
        with self.assertRaisesRegex(TaskError, "TASK-002: mathematical specification.*stale included contracts"):
            self.fx.gate(manifest, "start", second["id"])
        self.fx.math_report(manifest, second, "specification")
        self.fx.gate(manifest, "start", second["id"])

    def test_transitive_math_drift_crosses_nonmathematical_intermediary(self):
        self.fx.epic_with_children()
        self.fx.init("subtask", "TASK-003", "EPIC-001")
        manifest = self.fx.init("specification", "TASK-003")
        epic, first, middle, last = manifest["items"]
        for item in manifest["items"]:
            self.fx.fill(manifest, item["id"])
            self.fx.classify(item, item in (first, last))
        middle["depends_on"] = [first["id"]]
        last["depends_on"] = [middle["id"]]
        for item in (first, middle, last, epic):
            self.fx.finish_math(manifest, item)
        self.fx.gate(manifest, "completion", last["id"])
        self.change_formula(first)
        self.fx.finish_math(manifest, first)
        # The intermediate task has no mathematical report and needs no new
        # local contract evidence: its declared predecessor does carry drift.
        self.fx.gate(manifest, "completion", middle["id"])
        with self.assertRaisesRegex(TaskError, "TASK-003: mathematical specification.*stale included contracts"):
            self.fx.gate(manifest, "completion", last["id"])
        self.fx.math_report(manifest, last, "specification")
        with self.assertRaisesRegex(TaskError, "TASK-003: mathematical implementation.*stale included contracts"):
            self.fx.gate(manifest, "completion", last["id"])
        self.fx.math_report(manifest, last, "implementation")
        self.fx.gate(manifest, "completion", last["id"])

    def test_nonmathematical_dependency_text_change_does_not_stale_math_scope(self):
        manifest = self.completed_epic(parent_required=False, first_required=False)
        _, first, second = manifest["items"]
        previous = copy.deepcopy(second)
        path = self.fx.directory / first["specification"]
        path.write_text(path.read_text(encoding="utf-8") + "\nPresentation-only wording clarification.\n",
                        encoding="utf-8")
        self.fx.finish_math(manifest, first)
        self.assertEqual(previous, second)
        self.fx.gate(manifest, "completion", second["id"])

    def test_unrelated_sibling_and_runtime_progress_do_not_stale_scope(self):
        manifest = self.completed_epic(parent_required=False)
        _, first, unrelated = manifest["items"]
        previous = copy.deepcopy(first["mathematics"])
        self.change_formula(unrelated)
        unrelated["status"] = "in_progress"
        first["findings"] = [{"id": "PROGRESS-1", "blocking": False, "disposition": "resolved",
                              "reason": "Recorded follow-up finished."}]
        first["contributors"].append("additional-independent-contributor")
        self.assertEqual(previous, first["mathematics"])
        self.fx.gate(manifest, "completion", first["id"])
        self.fx.gate(manifest, "resumption", first["id"])

    def test_shared_contract_review_survives_later_child_creation_and_elaboration(self):
        manifest = self.fx.init("epic", "EPIC-001")
        epic = self.fx.fill(manifest, "EPIC-001")
        self.fx.classify(epic)
        self.fx.approve(manifest, epic)
        self.fx.math_report(manifest, epic, "specification")
        prior_epic = copy.deepcopy(epic)
        self.fx.save(manifest)
        # The shared contract is reviewed before there is even a child brief.
        self.fx.init("subtask", "TASK-001", "EPIC-001")
        manifest = self.fx.init("specification", "TASK-001")
        epic, child = manifest["items"]
        self.fx.fill(manifest, child["id"])
        self.fx.classify(child)
        self.fx.approve(manifest, child)
        self.fx.math_report(manifest, child, "specification")
        self.assertEqual(prior_epic, epic)
        self.fx.gate(manifest, "start", child["id"])
        self.change_formula(child)
        self.fx.approve(manifest, child)
        self.fx.math_report(manifest, child, "specification")
        self.assertEqual(prior_epic, epic)
        self.fx.gate(manifest, "start", child["id"])

    def test_added_child_invalidates_completed_epic_integration(self):
        manifest = self.completed_epic()
        prior_epic = copy.deepcopy(manifest["items"][0])
        self.fx.save(manifest)
        self.fx.init("subtask", "TASK-003", "EPIC-001")
        manifest = self.fx.init("specification", "TASK-003")
        epic, _, _, added = manifest["items"]
        self.fx.fill(manifest, added["id"])
        self.fx.classify(added)
        self.fx.finish_math(manifest, added)
        self.assertEqual(prior_epic, epic)
        with self.assertRaisesRegex(TaskError, "EPIC-001: mathematical implementation.*stale included contracts"):
            self.fx.gate(manifest, "completion", epic["id"])
        self.fx.math_report(manifest, epic, "implementation")
        self.fx.gate(manifest, "completion", epic["id"])


class MathematicsMigrationTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)

    def test_cli_migration_preserves_bytes_records_status_and_stale_bindings(self):
        original = self.fx.legacy(completed=True)
        before = self.fx.bytes()
        result = self.fx.cli("migrate", "--expect-sha256", digest(before["task.json"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertTrue(output["reassessment_required"])
        self.assertIn("not rebound", output["notice"])
        after = self.fx.bytes()
        self.assertEqual(after.pop("task.v1.backup.json"), before["task.json"])
        after.pop("task.json")
        self.assertEqual(after, {key: value for key, value in before.items() if key != "task.json"})
        migrated, _ = load(self.fx.directory)
        self.assertEqual(migrated["format_version"], 2)
        stripped = copy.deepcopy(migrated)
        stripped["format_version"] = 1
        for item in stripped["items"]:
            self.assertEqual(item.pop("mathematics"), new_mathematics())
        self.assertEqual(original, stripped)
        item = migrated["items"][0]
        with self.assertRaisesRegex(TaskError, "unassessed"):
            self.fx.gate(migrated, "completion")
        self.fx.classify(item, False)
        with self.assertRaisesRegex(TaskError, "approval"):
            self.fx.gate(migrated, "completion")

    def test_legacy_manifest_is_rejected_by_current_gates_before_migration(self):
        legacy = self.fx.legacy()
        with self.assertRaisesRegex(TaskError, "migration"):
            lint(self.fx.repo, self.fx.directory, legacy)
        with self.assertRaisesRegex(TaskError, "migration"):
            self.fx.gate(legacy)

    def test_migration_rejects_stale_input_without_writes(self):
        self.fx.legacy()
        before = self.fx.bytes()
        with self.assertRaisesRegex(TaskError, "current --expect-sha256"):
            migrate(self.fx.repo, self.fx.directory, "0" * 64)
        self.assertEqual(before, self.fx.bytes())

    def test_migration_rejects_wrong_branch_without_writes(self):
        self.fx.legacy()
        before = self.fx.bytes()
        self.fx.git("switch", "-q", "-c", "other")
        with self.assertRaisesRegex(TaskError, "branch"):
            migrate(self.fx.repo, self.fx.directory, digest(before["task.json"]))
        self.assertEqual(before, self.fx.bytes())

    def test_migration_refuses_conflicting_backup_and_reuses_identical_backup(self):
        self.fx.legacy()
        original = (self.fx.directory / "task.json").read_bytes()
        backup = self.fx.directory / "task.v1.backup.json"
        backup.write_bytes(b"existing unrelated backup\n")
        before = self.fx.bytes()
        with self.assertRaisesRegex(TaskError, "Conflicting migration backup"):
            migrate(self.fx.repo, self.fx.directory, digest(original))
        self.assertEqual(before, self.fx.bytes())
        backup.write_bytes(original)
        migrate(self.fx.repo, self.fx.directory, digest(original))
        self.assertEqual(backup.read_bytes(), original)

    def test_migration_strictly_rejects_invalid_v1_and_does_not_create_backup(self):
        legacy = self.fx.legacy()
        for mutate in (
            lambda m: m.update(format_version=True),
            lambda m: m.update(format_version=2),
            lambda m: m.update(extra="field"),
            lambda m: m["items"][0].update(mathematics=new_mathematics()),
            lambda m: m["items"][0].update(status="unknown"),
            lambda m: m["items"][0]["approval"].update(spec_sha256="invalid"),
        ):
            candidate = copy.deepcopy(legacy)
            mutate(candidate)
            self.fx.save(candidate)
            before = self.fx.bytes()
            with self.subTest(mutate=mutate), self.assertRaises(TaskError):
                migrate(self.fx.repo, self.fx.directory, digest(before["task.json"]))
            self.assertEqual(before, self.fx.bytes())

    def test_migration_refuses_duplicate_keys_without_writes(self):
        self.fx.legacy()
        path = self.fx.directory / "task.json"
        path.write_text(path.read_text(encoding="utf-8").replace(
            '"format_version": 1', '"format_version": 1, "format_version": 1'), encoding="utf-8")
        before = self.fx.bytes()
        with self.assertRaisesRegex(TaskError, "Duplicate JSON"):
            migrate(self.fx.repo, self.fx.directory, digest(before["task.json"]))
        self.assertEqual(before, self.fx.bytes())

    def test_migration_refuses_nonignored_task_manifest(self):
        self.fx.legacy()
        (self.fx.repo / ".gitignore").write_text("", encoding="utf-8")
        before = self.fx.bytes()
        with self.assertRaises(TaskError):
            migrate(self.fx.repo, self.fx.directory, digest(before["task.json"]))
        self.assertEqual(before, self.fx.bytes())

    def test_migration_refuses_existing_lock_without_modification(self):
        self.fx.legacy()
        (self.fx.directory / ".task.lock").write_text("pid=fixture\n", encoding="utf-8")
        before = self.fx.bytes()
        with self.assertRaisesRegex(TaskError, "lock"):
            migrate(self.fx.repo, self.fx.directory, digest(before["task.json"]))
        self.assertEqual(before, self.fx.bytes())

    def test_failed_manifest_replacement_retains_original_and_identical_backup(self):
        self.fx.legacy()
        before = self.fx.bytes()
        with patch("task_support.migration.atomic_write", side_effect=OSError("fixture replacement failure")):
            with self.assertRaisesRegex(OSError, "fixture replacement failure"):
                migrate(self.fx.repo, self.fx.directory, digest(before["task.json"]))
        after = self.fx.bytes()
        self.assertEqual(after.pop("task.v1.backup.json"), before["task.json"])
        self.assertEqual(after, before)
        migrate(self.fx.repo, self.fx.directory, digest(before["task.json"]))

    def test_migration_refuses_second_conversion_without_rewriting_original_backup(self):
        self.fx.legacy()
        migrate(self.fx.repo, self.fx.directory, load(self.fx.directory)[1])
        before = self.fx.bytes()
        with self.assertRaisesRegex(TaskError, "migration"):
            migrate(self.fx.repo, self.fx.directory, digest(before["task.json"]))
        self.assertEqual(before, self.fx.bytes())

    def test_migration_backup_preserves_bom_crlf_and_noncanonical_formatting(self):
        legacy = self.fx.legacy()
        legacy["handoff"]["notes"] = "Migration fixture: сохранённый контекст."
        original = ("\ufeff" + json.dumps(legacy, ensure_ascii=False, indent=4) + "\n").replace(
            "\n", "\r\n").encode("utf-8")
        (self.fx.directory / "task.json").write_bytes(original)
        migrate(self.fx.repo, self.fx.directory, digest(original))
        self.assertEqual((self.fx.directory / "task.v1.backup.json").read_bytes(), original)
        self.assertEqual(load(self.fx.directory)[0]["handoff"]["notes"], legacy["handoff"]["notes"])

    def test_migration_does_not_touch_other_legacy_task_directories(self):
        self.fx.legacy()
        sibling = self.fx.directory.parent / "other-task"
        sibling.mkdir()
        (sibling / "task.json").write_bytes(b'{"unrelated": "do not convert"}\r\n')
        before = (sibling / "task.json").read_bytes()
        migrate(self.fx.repo, self.fx.directory, load(self.fx.directory)[1])
        self.assertEqual((sibling / "task.json").read_bytes(), before)
        self.assertEqual([path.name for path in sibling.iterdir()], ["task.json"])

    def test_migration_detects_document_drift_before_writing_backup(self):
        from contextlib import contextmanager
        from task_support.artifacts import writer_lock

        legacy = self.fx.legacy()
        original = (self.fx.directory / "task.json").read_bytes()
        document = self.fx.directory / legacy["items"][0]["document"]

        @contextmanager
        def changing_writer(directory):
            document.write_bytes(document.read_bytes() + b"\nConcurrent fixture edit.\n")
            with writer_lock(directory):
                yield

        with patch("task_support.migration.writer_lock", changing_writer):
            with self.assertRaisesRegex(TaskError, "documents changed"):
                migrate(self.fx.repo, self.fx.directory, digest(original))
        self.assertEqual((self.fx.directory / "task.json").read_bytes(), original)
        self.assertFalse((self.fx.directory / "task.v1.backup.json").exists())
        self.assertFalse((self.fx.directory / ".task.lock").exists())


if __name__ == "__main__":
    unittest.main()
