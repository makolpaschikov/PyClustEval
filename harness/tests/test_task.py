"""Behavioral fixtures for the task helper; no application imports or runs."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "harness/scripts/task"
sys.path.insert(0, str(HELPER))
from task_support.artifacts import (contained, initialize, load, source_snapshot,
                                    spec_digest, workspace)
from task_support.formats import VERSION, TaskError, digest
from task_support.gates import check_gate
from task_support.lint import lint, parse_document


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.fixture_root = ROOT / ".agent-work/tasks/_task-tests"
        self.fixture_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.fixture_root)
        self.repo = Path(self.temp.name).resolve()
        self.git("init", "-q", "-b", "test-main")
        (self.repo / ".gitignore").write_text("/.agent-work/tasks/\n", encoding="utf-8")
        (self.repo / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.git("add", ".gitignore", "source.py")
        self.directory = self.repo / ".agent-work/tasks/example"

    def tearDown(self):
        self.assertTrue(self.repo.is_relative_to(self.fixture_root.resolve()))
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True).stdout

    def save(self, manifest):
        (self.directory / "task.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def init(self, kind="specification", item_id="TASK-001", parent=None):
        exists = (self.directory / "task.json").exists()
        expected = load(self.directory)[1] if exists else None
        return initialize(self.repo, self.directory, item_id, kind, "test-main", "harness", parent, expected)

    def fill(self, manifest, item_id):
        item = next(item for item in manifest["items"] if item["id"] == item_id)
        for field in ("document", "specification"):
            if item[field]:
                path = self.directory / item[field]
                text = path.read_text(encoding="utf-8")
                text = re.sub(r"\[TODO:[^\]]*\]", "Explicit fixture contract.", text)
                path.write_text(text, encoding="utf-8")
        if item["kind"] != "subtask" or item["specification"]:
            item["coverage"] = {"REQ-001": ["AC-001"]}
            item["verification"] = {"AC-001": ["CHECK-001"]}
        item["status"] = "ready"
        item["mathematics"].update(required=False, rationale="Fixture changes no mathematical behavior.")
        return item

    def report(self, name, spec, source=None, **extra):
        path = self.directory / "evidence" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("Isolated test fixture evidence; not a real application execution.\n", encoding="utf-8")
        result = {"artifact": path.relative_to(self.directory).as_posix(),
                  "sha256": digest(path.read_bytes()), "spec_sha256": spec, **extra}
        if source:
            result["source_sha256"] = source
        return result

    def approve(self, manifest, item):
        signature = spec_digest(self.directory, manifest, item)
        item["approval"] = {"source": "Fixture human decision", "spec_sha256": signature}
        kinds = ("readiness", "alignment") if item["review_policy"] == "separate" else ("combined",)
        item["spec_reviews"] = [self.report(f"{item['id']}-{kind}.md", signature,
            kind=kind, reviewer=f"reviewer-{kind}", verdict="accepted") for kind in kinds]
        return signature

    def completed(self, manifest, item):
        signature = self.approve(manifest, item)
        source = source_snapshot(self.repo)["source_sha256"]
        item["contributors"] = ["developer"]
        item["checks"] = [self.report(f"{item['id']}-checks.txt", signature, source,
            id="CHECK-001", command=["fixture-check"], exit_code=0, outcome="passed")]
        item["code_review"] = self.report(f"{item['id']}-code.md", signature, source,
            reviewer="reviewer-code", verdict="accepted")
        item["completion"] = {"spec_sha256": signature, "source_sha256": source}
        item["checkpoint"] = dict(item["completion"])
        item["status"] = "done"

    def gate(self, manifest, gate="start", item_id="TASK-001"):
        return check_gate(self.repo, self.directory, manifest, item_id, gate, source_snapshot(self.repo))

    def ready(self):
        manifest = self.init()
        item = self.fill(manifest, "TASK-001")
        self.approve(manifest, item)
        return manifest, item

    def test_generated_draft_lints_but_cannot_pass_readiness(self):
        manifest = self.init()
        lint(self.repo, self.directory, manifest)
        with self.assertRaisesRegex(TaskError, "placeholder"):
            self.gate(manifest, "specification")

    def test_standalone_start_completion_and_resume(self):
        manifest, item = self.ready()
        self.gate(manifest)
        self.completed(manifest, item)
        receipt = self.gate(manifest, "completion")
        self.assertEqual(receipt, item["completion"])
        self.gate(manifest, "resumption")

    def test_cli_read_only_commands_report_hashes_without_changing_artifacts(self):
        manifest, item = self.ready()
        self.save(manifest)
        before = {p.relative_to(self.directory): p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        for command in (("lint",), ("snapshot", "--id", item["id"]),
                        ("check", "--id", item["id"], "--gate", "start")):
            result = subprocess.run([sys.executable, "-B", str(HELPER / "task.py"), "--repo", str(self.repo),
                                     command[0], str(self.directory), *command[1:]], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("manifest_sha256", json.loads(result.stdout))
        after = {p.relative_to(self.directory): p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_source_snapshot_detects_dirty_added_and_deleted_files(self):
        previous = source_snapshot(self.repo)["source_sha256"]
        for operation in (lambda: (self.repo / "source.py").write_text("VALUE = 2\n"),
                          lambda: (self.repo / "new.py").write_text("NEW = 1\n"),
                          lambda: (self.repo / "source.py").unlink()):
            operation()
            current = source_snapshot(self.repo)["source_sha256"]
            self.assertNotEqual(current, previous)
            previous = current

    def test_source_snapshot_ignores_task_state(self):
        manifest = self.init()
        before = source_snapshot(self.repo)
        manifest["handoff"]["notes"] = "Next session context"
        self.save(manifest)
        self.assertEqual(source_snapshot(self.repo), before)

    def test_snapshot_is_stable_across_staging_and_committing_deletion(self):
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Initial fixture")
        original = source_snapshot(self.repo)
        (self.repo / "source.py").unlink()
        deleted = source_snapshot(self.repo)
        self.assertNotEqual(original, deleted)
        self.git("add", "-u")
        self.assertEqual(deleted, source_snapshot(self.repo))
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Delete fixture source")
        self.assertEqual(deleted, source_snapshot(self.repo))

    def test_changed_contract_invalidates_approval(self):
        manifest, item = self.ready()
        path = self.directory / item["document"]
        path.write_text(path.read_text() + "\nChanged requirement context.\n")
        with self.assertRaisesRegex(TaskError, "approval"):
            self.gate(manifest)

    def test_changed_verification_plan_invalidates_approval(self):
        manifest, item = self.ready()
        item["verification"]["AC-001"].append("CHECK-002")
        with self.assertRaisesRegex(TaskError, "approval"):
            self.gate(manifest)

    def test_dirty_source_invalidates_completion_and_resume(self):
        manifest, item = self.ready()
        self.completed(manifest, item)
        (self.repo / "source.py").write_text("VALUE = 99\n")
        for gate in ("completion", "resumption"):
            with self.subTest(gate=gate), self.assertRaises(TaskError):
                self.gate(manifest, gate)

    def test_check_failure_not_run_missing_or_corrupt_report_rejects_completion(self):
        manifest, item = self.ready()
        self.completed(manifest, item)
        for alteration in (lambda data: data["checks"][0].update(exit_code=1),
                           lambda data: data["checks"][0].update(outcome="not_run", exit_code=None),
                           lambda data: data.update(checks=[]),
                           lambda data: data["checks"][0].update(sha256="0" * 64),
                           lambda data: data["checks"][0].update(artifact="missing.log")):
            candidate = copy.deepcopy(manifest)
            alteration(candidate["items"][0])
            with self.assertRaises(TaskError):
                self.gate(candidate, "completion")

    def test_independence_and_separate_review_requirements(self):
        manifest, item = self.ready()
        item["spec_reviews"][1]["reviewer"] = item["spec_reviews"][0]["reviewer"]
        with self.assertRaisesRegex(TaskError, "separate reviewers"):
            self.gate(manifest)
        self.completed(manifest, item)
        item["code_review"]["reviewer"] = "developer"
        with self.assertRaisesRegex(TaskError, "independent"):
            self.gate(manifest, "completion")

    def test_combined_review_requires_small_task_and_rationale(self):
        manifest = self.init()
        item = self.fill(manifest, "TASK-001")
        item["review_policy"] = "combined"
        with self.assertRaisesRegex(TaskError, "rationale"):
            lint(self.repo, self.directory, manifest)
        item["review_rationale"] = "Small isolated behavior change"
        self.approve(manifest, item)
        self.gate(manifest)
        item["scale"] = "risky"
        with self.assertRaises(TaskError):
            self.gate(manifest)

    def test_bootstrap_record_required_for_application_execution(self):
        manifest, item = self.ready()
        manifest["scope"] = "application"
        self.approve(manifest, item)
        with self.assertRaisesRegex(TaskError, "bootstrap"):
            self.gate(manifest)
        manifest["application_authorization"] = {"source": "Fixture explicit human expansion", "scope": "This fixture task"}
        self.gate(manifest)

    def test_branch_mismatch_rejected(self):
        manifest, _ = self.ready()
        self.git("switch", "-q", "-c", "other")
        with self.assertRaisesRegex(TaskError, "branch"):
            self.gate(manifest)

    def test_open_blocker_prevents_start_and_active_resume(self):
        manifest, item = self.ready()
        item["findings"] = [{"id": "F-1", "blocking": True, "disposition": "open", "reason": "Unresolved behavior"}]
        item["status"] = "in_progress"
        item["checkpoint"] = {"spec_sha256": spec_digest(self.directory, manifest, item),
                              "source_sha256": source_snapshot(self.repo)["source_sha256"]}
        for gate in ("start", "resumption"):
            with self.subTest(gate=gate), self.assertRaisesRegex(TaskError, "blocking"):
                self.gate(manifest, gate)

    def test_unresolved_and_deferred_blockers_prevent_completion(self):
        manifest, item = self.ready()
        self.completed(manifest, item)
        for blocking, disposition in ((True, "deferred"), (False, "open")):
            item["findings"] = [{"id": "F-1", "blocking": blocking, "disposition": disposition, "reason": "Fixture finding"}]
            with self.assertRaises(TaskError):
                self.gate(manifest, "completion")

    def test_format_drift_unknown_fields_types_and_versions_fail(self):
        manifest = self.init()
        for mutate in (lambda m: m.update(format_version=VERSION + 1),
                       lambda m: m.update(format_version=True),
                       lambda m: m.update(surprise="unknown"),
                       lambda m: m["items"][0].update(depends_on="TASK-2")):
            candidate = copy.deepcopy(manifest)
            mutate(candidate)
            with self.assertRaises(TaskError):
                lint(self.repo, self.directory, candidate)
        path = self.directory / manifest["items"][0]["document"]
        path.write_text(path.read_text().replace("## Scope", "## Unplanned heading"))
        with self.assertRaisesRegex(TaskError, "sections"):
            lint(self.repo, self.directory, manifest)

    def test_duplicate_json_keys_and_unknown_reference_fail(self):
        manifest = self.init()
        path = self.directory / "task.json"
        original = path.read_text()
        version_field = f'"format_version": {VERSION}'
        path.write_text(original.replace(version_field, f'{version_field}, {version_field}'))
        with self.assertRaisesRegex(TaskError, "Duplicate JSON"):
            load(self.directory)
        manifest["items"][0]["depends_on"] = ["MISSING"]
        with self.assertRaisesRegex(TaskError, "dependency"):
            lint(self.repo, self.directory, manifest)

    def test_document_and_evidence_paths_cannot_escape(self):
        manifest, item = self.ready()
        for name in ("../escape.md", str(self.repo / "source.py"), "C:/escape.md"):
            with self.subTest(name=name), self.assertRaises(TaskError):
                contained(self.directory, name)
        item["document"] = "../escape.md"
        with self.assertRaises(TaskError):
            lint(self.repo, self.directory, manifest)
        with self.assertRaises(TaskError):
            workspace(self.repo, self.repo / "outside")

    def test_missing_local_link_and_duplicate_acceptance_rejected(self):
        manifest, item = self.ready()
        path = self.directory / item["document"]
        original = path.read_text()
        path.write_text(original + "\n[broken](missing.md)\n")
        with self.assertRaisesRegex(TaskError, "missing local link"):
            lint(self.repo, self.directory, manifest)
        path.write_text(original.replace("## Verification", "- AC-001: duplicated\n\n## Verification"))
        with self.assertRaisesRegex(TaskError, "duplicate AC"):
            lint(self.repo, self.directory, manifest)

    def test_example_ids_inside_code_fences_do_not_supply_acceptance(self):
        manifest, item = self.ready()
        path = self.directory / item["document"]
        text = path.read_text().replace("- AC-001: Explicit fixture contract.", "```text\n- AC-001: example only\n```")
        with self.assertRaisesRegex(TaskError, "Acceptance"):
            parse_document(text, "specification", item["id"], ready=True)

    def test_hidden_definitions_links_and_headings_are_not_active(self):
        manifest, item = self.ready()
        path = self.directory / item["document"]
        original = path.read_text()
        text = original.replace("- REQ-001: Explicit fixture contract.",
                                "Introduction.\n<!--\n- REQ-001: old hidden definition\n-->")
        with self.assertRaisesRegex(TaskError, "Requirements"):
            parse_document(text, "specification", item["id"], ready=True)
        path.write_text(original + "\n<!--\n## Hidden heading\n- AC-001: old hidden definition\n[old](missing.md)\n-->\n")
        lint(self.repo, self.directory, manifest)
        parse_document(path.read_text(), "specification", item["id"], ready=True)
        with self.assertRaisesRegex(TaskError, "unclosed HTML"):
            parse_document(original + "\n<!-- hidden", "specification", item["id"])

    def test_inline_code_comment_tokens_remain_literal(self):
        manifest, item = self.ready()
        path = self.directory / item["document"]
        original = path.read_text()
        for literal in ("The parser handles `<!--` in examples.",
                        "The parser handles ``a ` <!-- b`` in examples.",
                        "```<!--```", "A `<!--` token. <!-- hidden --> Visible."):
            with self.subTest(literal=literal):
                parse_document(original + "\n" + literal, "specification", item["id"], ready=True)

    def test_init_rejects_overwrite_stale_hash_and_wrong_branch(self):
        manifest = self.init("epic", "EPIC-001")
        before = (self.directory / "task.json").read_bytes()
        for expected, branch in (("0" * 64, "test-main"), (digest(before), "wrong")):
            with self.assertRaises(TaskError):
                initialize(self.repo, self.directory, "TASK-001", "subtask", branch, "harness", "EPIC-001", expected)
        self.assertEqual(before, (self.directory / "task.json").read_bytes())
        with self.assertRaises(TaskError):
            self.init("epic", "EPIC-001")

    def test_init_manifest_failure_removes_new_document(self):
        self.init("epic", "EPIC-001")
        before = (self.directory / "task.json").read_bytes()
        with patch("task_support.artifacts.atomic_write", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                self.init("subtask", "TASK-001", "EPIC-001")
        self.assertEqual(before, (self.directory / "task.json").read_bytes())
        self.assertFalse((self.directory / "items/TASK-001/subtask.md").exists())
        self.assertFalse((self.directory / ".task.lock").exists())

    def test_existing_writer_lock_is_not_removed(self):
        self.init()
        lock = self.directory / ".task.lock"
        lock.write_text("pid=fixture\n")
        with self.assertRaisesRegex(TaskError, "lock"):
            load(self.directory)
        self.assertTrue(lock.exists())

    def epic_with_children(self):
        self.init("epic", "EPIC-001")
        self.init("subtask", "TASK-001", "EPIC-001")
        self.init("specification", "TASK-001")
        self.init("subtask", "TASK-002", "EPIC-001")
        manifest = self.init("specification", "TASK-002")
        for item in manifest["items"]:
            self.fill(manifest, item["id"])
        manifest["items"][2]["depends_on"] = ["TASK-001"]
        return manifest

    def test_epic_dependencies_and_incremental_source_revisions(self):
        manifest = self.epic_with_children()
        epic, first, second = manifest["items"]
        self.approve(manifest, second)
        with self.assertRaisesRegex(TaskError, "dependency is not completed"):
            self.gate(manifest, item_id="TASK-002")
        self.completed(manifest, first)
        (self.repo / "source.py").write_text("VALUE = 2\n")
        self.gate(manifest, item_id="TASK-002")
        self.completed(manifest, second)
        self.completed(manifest, epic)
        self.gate(manifest, "completion", "EPIC-001")
        second["status"] = "in_progress"
        with self.assertRaises(TaskError):
            self.gate(manifest, "completion", "EPIC-001")

    def test_subtask_requires_ready_parent_verification_contract(self):
        manifest = self.epic_with_children()
        epic, first, _ = manifest["items"]
        epic["coverage"], epic["verification"] = {}, {}
        self.approve(manifest, first)
        with self.assertRaisesRegex(TaskError, "coverage"):
            self.gate(manifest)
        self.completed(manifest, first)
        with self.assertRaisesRegex(TaskError, "coverage"):
            self.gate(manifest, "completion")

    def test_dependency_cycle_and_changed_parent_contract_detected(self):
        manifest = self.epic_with_children()
        epic, first, second = manifest["items"]
        first["depends_on"] = ["TASK-002"]
        with self.assertRaisesRegex(TaskError, "cycle"):
            lint(self.repo, self.directory, manifest)
        first["depends_on"] = []
        self.completed(manifest, first)
        self.approve(manifest, second)
        path = self.directory / epic["document"]
        path.write_text(path.read_text() + "\nShared interface changed.\n")
        with self.assertRaisesRegex(TaskError, "approval"):
            self.gate(manifest, item_id="TASK-002")


if __name__ == "__main__":
    unittest.main()
