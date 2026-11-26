"""Behavioral tests on isolated journals; no application or project journals are modified."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "journal.py"
SPEC = importlib.util.spec_from_file_location("harness_journal", SCRIPT)
journal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(journal)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".journal-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        for kind, name in journal.FILES.items():
            (self.directory / name).write_bytes(journal.render(kind, []))

    def records(self):
        return journal.load(journal.snapshot(self.directory))

    def signal(self, **extra):
        payload = dict(title="Focused reading", date="2026-11-10", origin="Human request",
                       owner="harness-maintainer", request="Read relevant material",
                       evidence="Proposal, not a reproduced incident")
        payload.update(extra)
        return journal.create(self.directory, "signal", payload)

    def decision(self, signal, **extra):
        payload = dict(title="Reading rule", date="2026-11-10", signals=[signal],
                       decision="Read coherent excerpts", why="Keep necessary context")
        payload.update(extra)
        return journal.create(self.directory, "decision", payload)

    def update(self, rid, patch, **extra):
        kind = "signal" if rid.startswith("SIG-") else "decision"
        expected = journal.digest(journal.snapshot(self.directory)[kind])
        return journal.update(self.directory, rid, patch, expected, **extra)

    def assert_unchanged_error(self, call, message):
        before = journal.snapshot(self.directory)
        with self.assertRaisesRegex(journal.JournalError, message):
            call()
        self.assertEqual(before, journal.snapshot(self.directory))
        self.assertFalse((self.directory / ".journal.lock").exists())

    def test_full_lifecycle_keeps_current_evidence_without_history(self):
        sig = self.signal()
        dec = self.decision(sig)
        self.update(sig, {"decisions": [dec], "status": "awaiting_agreement"})
        self.update(dec, {"agreement": "Human approved the exact rule in chat", "status": "agreed"})
        self.update(sig, {"status": "in_progress"})
        self.update(dec, {"result": "Added AGENTS.md#reading-files", "status": "implemented"})
        self.update(dec, {"check": "Seven textual scenarios passed; no runtime savings measured", "status": "verified"})
        self.update(sig, {"status": "resolved"})
        records = self.records()
        decision = records["decision"][0]
        self.assertEqual(decision["status"], "verified")
        self.assertEqual(decision["agreement"], "Human approved the exact rule in chat")
        self.assertEqual(decision["result"], "Added AGENTS.md#reading-files")
        self.assertIn("no runtime savings measured", decision["check"])
        for raw in journal.snapshot(self.directory).values():
            self.assertNotIn(b"- History:", raw)
            self.assertNotIn(b" -> ", raw)
        self.assertEqual(decision["signals"], [sig])
        self.assertEqual(records["signal"][0]["status"], "resolved")

    def test_failed_gates_leave_files_unchanged(self):
        sig = self.signal()
        dec = self.decision(sig)
        for patch, message in [
            ({"status": "agreed"}, "agreement"),
            ({"status": "implemented", "agreement": "Approved"}, "result"),
            ({"status": "verified", "agreement": "Approved", "result": "Done"}, "verification"),
        ]:
            with self.subTest(patch=patch):
                self.assert_unchanged_error(lambda: self.update(dec, patch), message)
        self.assert_unchanged_error(lambda: self.update(sig, {"status": "resolved"}), "unresolved")

    def test_approved_substance_and_identity_cannot_be_overwritten(self):
        sig = self.signal()
        dec = self.decision(sig, status="agreed", agreement="Approved in chat")
        for patch, message in [
            ({"decision": "Different policy"}, "locked"),
            ({"agreement": "Another approval"}, "locked"),
            ({"signals": []}, "locked"),
            ({"status": "proposed"}, "cannot return"),
            ({"id": "DEC-050"}, "immutable"),
            ({"history": []}, "immutable"),
            ({"date": "2026-11-11"}, "immutable"),
        ]:
            with self.subTest(patch=patch):
                self.assert_unchanged_error(lambda: self.update(dec, patch), message)

    def test_superseding_decision_keeps_old_substance(self):
        sig = self.signal()
        old = self.decision(sig, status="verified", agreement="Initial approval",
                            result="Initial instructions", check="Original tests passed")
        self.update(sig, {"decisions": [old], "status": "resolved"})
        self.update(sig, {"status": "investigating"})
        new = self.decision(sig, title="Revised rule", status="agreed", agreement="New human approval",
                            decision="Different rule", supersedes=[old])
        self.update(old, {"status": "superseded"})
        self.update(sig, {"decisions": [old, new]})
        self.assertEqual(self.records()["decision"][0]["decision"], "Read coherent excerpts")
        self.assert_unchanged_error(lambda: self.update(sig, {"status": "resolved"}), "unresolved")
        self.update(new, {"status": "verified", "result": "Revised instructions", "check": "Checks passed"})
        self.update(sig, {"status": "resolved"})
        self.assertEqual(self.records()["signal"][0]["status"], "resolved")

    def test_ids_are_sequential_and_noop_leaves_files_unchanged(self):
        first = self.signal()
        second = self.signal(title="Other signal")
        self.assertEqual((first, second), ("SIG-001", "SIG-002"))
        before = journal.snapshot(self.directory)
        self.assertFalse(self.update(first, {"title": "Focused reading"}))
        self.assertEqual(before, journal.snapshot(self.directory))

    def test_successive_supersession_preserves_the_chain(self):
        sig = self.signal()
        first = self.decision(sig, status="agreed", agreement="First approval")
        second = self.decision(sig, status="agreed", agreement="Second approval", supersedes=[first])
        self.update(first, {"status": "superseded"})
        third = self.decision(sig, status="agreed", agreement="Third approval", supersedes=[second])
        self.update(second, {"status": "superseded"})
        self.assertEqual([item["status"] for item in self.records()["decision"]],
                         ["superseded", "superseded", "agreed"])
        self.assert_unchanged_error(lambda: self.update(third, {"status": "rejected"}), "no agreed replacement")

    def test_unknown_fields_statuses_and_links_are_rejected(self):
        sig = self.signal()
        for patch, message in [
            ({"status": "finished-ish"}, "invalid status"),
            ({"custom": "content"}, "Unknown"),
            ({"decisions": ["DEC-999"]}, "missing"),
            ({"decisions": ["SIG-001"]}, "invalid reference"),
            ({"status": "duplicate"}, "requires one"),
        ]:
            with self.subTest(patch=patch):
                self.assert_unchanged_error(lambda: self.update(sig, patch), message)
        other = self.signal(title="Second signal")
        unrelated = self.decision(other)
        self.assert_unchanged_error(lambda: self.update(sig, {"decisions": [unrelated]}), "refer back")

    def test_duplicate_cycle_is_rejected(self):
        first, second = self.signal(), self.signal(title="Second")
        self.update(second, {"status": "duplicate", "duplicate_of": [first]})
        self.assert_unchanged_error(lambda: self.update(first, {"status": "duplicate", "duplicate_of": [second]}), "Cycle")

    def test_stale_update_cannot_overwrite_another_change(self):
        sig = self.signal()
        stale = journal.digest(journal.snapshot(self.directory)["signal"])
        self.update(sig, {"owner": "new-owner"})
        self.assert_unchanged_error(
            lambda: journal.update(self.directory, sig, {"owner": "old-owner"}, stale),
            "Stale",
        )

    def test_writer_lock_blocks_second_writer(self):
        lock = self.directory / ".journal.lock"
        lock.write_text("pid=existing-writer", encoding="utf-8")
        before = journal.snapshot(self.directory)
        with self.assertRaisesRegex(journal.JournalError, "Writer lock exists"):
            self.signal()
        self.assertEqual(before, journal.snapshot(self.directory))
        self.assertEqual(lock.read_text(encoding="utf-8"), "pid=existing-writer")

    def test_uncooperative_edit_before_save_is_detected(self):
        sig = self.signal()
        original_save = journal.save
        path = self.directory / "SIGNALS.md"
        external = path.read_bytes().replace(b"Focused reading", b"Human edit")

        def raced_save(directory, before, after):
            path.write_bytes(external)
            return original_save(directory, before, after)

        with mock.patch.object(journal, "save", side_effect=raced_save):
            with self.assertRaisesRegex(journal.JournalError, "changed during preparation"):
                self.update(sig, {"owner": "different"})
        self.assertEqual(path.read_bytes(), external)

    def test_replace_failure_preserves_existing_file(self):
        sig = self.signal()
        with mock.patch.object(journal.os, "replace", side_effect=PermissionError("fixture denial")):
            self.assert_unchanged_error(lambda: self.update(sig, {"owner": "another"}), "Write failed")
        self.assertFalse(list(self.directory.glob("*.tmp")))

    def migration_plan(self):
        old = {
            "signal": b"# Harness signals\n\n## SIG-001: Legacy signal\n- Request: Preserve scope.\n",
            "decision": b"# Harness decisions\n\n## DEC-001: Legacy decision\n- Resolution: Original choice.\n",
        }
        for kind, raw in old.items():
            (self.directory / journal.FILES[kind]).write_bytes(raw)
        return {
            "expected_sha256": {journal.FILES[kind]: journal.digest(raw) for kind, raw in old.items()},
            "signals": [dict(id="SIG-001", title="Legacy signal", date="2026-11-10", origin="Human",
                             owner="maintainer", request="Preserve scope", evidence="Supplied request",
                             status="resolved", decisions=["DEC-001"])],
            "decisions": [dict(id="DEC-001", title="Legacy decision", date="2026-11-10", signals=["SIG-001"],
                               status="verified", decision="Original choice", why="Preserve scope",
                               agreement="Explicit approval", result="Original change", check="Original checks passed")],
        }

    def test_migration_preserves_ids_without_creating_history(self):
        plan = self.migration_plan()
        journal.migrate(self.directory, plan)
        records = self.records()
        self.assertEqual(records["decision"][0]["decision"], "Original choice")
        self.assertEqual(records["signal"][0]["id"], "SIG-001")
        for kind in records:
            self.assertNotIn("history", records[kind][0])
        self.assert_unchanged_error(lambda: journal.migrate(self.directory, plan), "Already migrated")

    def test_migration_refuses_missing_ids_or_stale_sources(self):
        plan = self.migration_plan()
        plan["decisions"] = []
        self.assert_unchanged_error(lambda: journal.migrate(self.directory, plan), "preserve every ID")
        plan = self.migration_plan()
        plan["expected_sha256"]["SIGNALS.md"] = "0" * 64
        self.assert_unchanged_error(lambda: journal.migrate(self.directory, plan), "source changed")

    def install_v1_history(self):
        for kind, path in journal.FILES.items():
            content = (self.directory / path).read_text(encoding="utf-8")
            sections = content.split('\n\n<a id=')
            content = sections[0].replace("journal-format: 2", "journal-format: 1")
            for section in sections[1:]:
                content += '\n\n<a id=' + section.rstrip() + (
                    '\n- History:\n'
                    '  - 2026-11-10T00:00:00Z | maintainer | created\n'
                    '  - 2026-11-10T00:01:00Z | maintainer | agreed -> verified; checks passed\n'
                )
            (self.directory / path).write_text(content, encoding="utf-8")

    def test_remove_history_preserves_all_current_fields_and_is_idempotent(self):
        sig = self.signal(details="A failed check was corrected; preserve this important fact.")
        dec = self.decision(sig, status="verified", agreement="Specific human agreement",
                            result="Actual changed file", check="Passed with a documented limitation")
        self.update(sig, {"status": "resolved", "decisions": [dec]})
        expected = self.records()
        self.install_v1_history()
        with self.assertRaisesRegex(journal.JournalError, "unsupported format"):
            self.records()
        self.assertTrue(journal.remove_history(self.directory))
        self.assertEqual(expected, self.records())
        before = journal.snapshot(self.directory)
        self.assertFalse(journal.remove_history(self.directory))
        self.assertEqual(before, journal.snapshot(self.directory))
        for raw in before.values():
            self.assertNotIn(b"- History:", raw)
            self.assertNotIn(b"agreed -> verified", raw)

    def test_remove_history_refuses_invalid_current_fields_without_writing(self):
        sig = self.signal()
        self.decision(sig)
        self.install_v1_history()
        path = self.directory / "DECISIONS.md"
        path.write_bytes(path.read_bytes().replace(b"- Why:", b"- Unknown:"))
        self.assert_unchanged_error(lambda: journal.remove_history(self.directory), "Unknown")

    def test_v2_rejects_history_and_does_not_confuse_prose_with_version_marker(self):
        sig = self.signal(details="Legacy marker <!-- journal-format: 1 --> is reference data")
        self.assertFalse(journal.remove_history(self.directory))
        path = self.directory / "SIGNALS.md"
        path.write_bytes(path.read_bytes() + b"- History:\n  - ignored\n")
        self.assert_unchanged_error(lambda: self.update(sig, {"status": "investigating"}), "Unexpected")

    def test_migration_second_write_failure_rolls_back_first(self):
        plan = self.migration_plan()
        original = journal.atomic_write
        calls = 0

        def fail_second(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PermissionError("second file denied")
            original(path, data)

        with mock.patch.object(journal, "atomic_write", side_effect=fail_second):
            self.assert_unchanged_error(lambda: journal.migrate(self.directory, plan), "Write failed")

    def test_manual_format_drift_and_duplicate_ids_fail_validation(self):
        self.signal()
        raw = journal.snapshot(self.directory)
        corruptions = [
            raw["signal"].replace(b"- Owner:", b"- Surprise:"),
            raw["signal"].replace(b"- Status: open", b"- Status: open\n- Status: open"),
            raw["signal"].replace(b"- Date: 2026-11-10", b"- Date: 2026-02-30"),
            raw["signal"] + raw["signal"][raw["signal"].index(b'<a id='):],
        ]
        for bad in corruptions:
            with self.subTest(bad=bad[:100]):
                with self.assertRaises(journal.JournalError):
                    journal.load({**raw, "signal": bad})

    def test_unicode_and_multiline_input_round_trip(self):
        sig = self.signal(title="Чтение файлов", request="Прочитать функцию\nи её вызывающий код.")
        self.assertEqual(self.records()["signal"][0]["request"], "Прочитать функцию и её вызывающий код.")
        before = journal.snapshot(self.directory)
        self.update(sig, {"details": "Причина: контекст."})
        self.assertNotEqual(before, journal.snapshot(self.directory))
        self.update(sig, {"details": None})
        self.assertNotIn("details", self.records()["signal"][0])

    def test_cli_json_errors_and_check_are_read_only(self):
        self.signal()
        before = journal.snapshot(self.directory)
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--journal-dir", str(self.directory), "check"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sha256=", result.stdout)
        self.assertEqual(before, journal.snapshot(self.directory))
        payload = self.directory / "input.json"
        payload.write_text('{"title":"first", "title":"second"}', encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--journal-dir", str(self.directory),
                                 "create", "signal", "--input", str(payload)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Duplicate JSON key", result.stderr)
        self.assertEqual(before, journal.snapshot(self.directory))

    def test_cli_creates_and_updates_without_actor_or_reason(self):
        payload = self.directory / "input.json"
        payload.write_text(json.dumps(dict(title="CLI signal", origin="Human", owner="maintainer",
                                           request="Small change", evidence="Explicit request")), encoding="utf-8")
        command = [sys.executable, "-B", str(SCRIPT), "--journal-dir", str(self.directory)]
        result = subprocess.run([*command, "create", "signal", "--input", str(payload)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "SIG-001")
        payload.write_text('{"status":"investigating"}', encoding="utf-8")
        expected = journal.digest(journal.snapshot(self.directory)["signal"])
        result = subprocess.run([*command, "update", "SIG-001", "--input", str(payload),
                                 "--expect-sha256", expected], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.records()["signal"][0]["status"], "investigating")
        self.assertNotIn(b"- History:", journal.snapshot(self.directory)["signal"])


if __name__ == "__main__":
    unittest.main()
