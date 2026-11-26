"""Exercise doctor with a real Python and Git worktree and replaceable checkers."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / ".agent-work/tasks/q5-result/fixtures"
sys.path.insert(0, str(ROOT / "harness/scripts"))

from quality_support import doctor
from quality_support.common import QualityError


class DoctorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FIXTURES.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=FIXTURES)
        cls.repo = Path(temp.name).resolve()
        if not cls.repo.is_relative_to(FIXTURES.resolve()):
            raise AssertionError("Unexpected fixture location")
        cls.addClassCleanup(temp.cleanup)
        subprocess.run(["git", "init", "-q", "--template=", str(cls.repo)],
                       capture_output=True, check=True, timeout=10)
        (cls.repo / "file.txt").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(cls.repo), "add", "file.txt"],
                       capture_output=True, check=True, timeout=10)

    def setUp(self):
        self.modules = {
            name: SimpleNamespace(COMMANDS=commands, add_commands=Mock(), run_command=Mock())
            for name, commands in doctor.CHECKERS.items()
        }
        self.hook = self.modules["hooks"]
        self.hook.hook_status = Mock(return_value={"state": "not_configured", "diagnostics": []})
        self.git_checks = self.modules["git_checks"]
        self.git_checks.load_assignment = Mock(return_value={"task_id": "example"})
        self.git_checks.validate_checkout = Mock()
        imports = patch.object(doctor, "importlib", SimpleNamespace(import_module=self.import_checker))
        imports.start()
        self.addCleanup(imports.stop)

    def import_checker(self, module, package):
        name = module.removeprefix(".")
        if name not in self.modules:
            raise ModuleNotFoundError(name)
        return self.modules[name]

    def run_doctor(self, *, python=None, repo=None):
        parser = argparse.ArgumentParser()
        doctor.add_commands(parser.add_subparsers(dest="command"))
        args = parser.parse_args(["doctor", "--python", str(python)] if python else ["doctor"])
        return doctor.run_command(args, repo or self.repo)

    def configure_hook(self, *, python=sys.executable, assignment=None, digest=None):
        self.hook.hook_status.return_value = {
            "state": "ready", "diagnostics": [], "python": python,
            "assignment": assignment, "assignment_sha256": digest,
        }

    def assert_state(self, report, component, state):
        self.assertEqual(report["components"][component]["state"], state, report)

    def test_optional_hook_is_reported_and_git_files_stay_unchanged(self):
        git_dir = self.repo / ".git"
        files = {item: item.read_bytes() for item in git_dir.rglob("*") if item.is_file()}
        report = self.run_doctor()

        self.assertTrue(report["ok"], report)
        self.assert_state(report, "python", "ready")
        self.assertEqual(Path(report["components"]["python"]["executable"]), Path(sys.executable))
        self.assert_state(report, "git", "ready")
        self.assert_state(report, "repository", "ready")
        self.assert_state(report, "hook", "not_configured")
        self.assert_state(report, "assignment", "not_applicable")
        self.assertEqual(report["diagnostics"][0]["code"], "hook-not-configured")
        self.hook.hook_status.assert_called_once_with(self.repo)
        self.assertEqual(files, {item: item.read_bytes() for item in git_dir.rglob("*") if item.is_file()})

    def test_explicit_missing_python_is_reported(self):
        executable = self.repo / "missing-python.exe"
        report = self.run_doctor(python=executable)

        self.assertFalse(report["ok"])
        self.assert_state(report, "python", "unavailable")
        self.assertEqual(report["components"]["python"]["executable"], str(executable))

    def test_old_python_and_invalid_probe_output_fail(self):
        for output, version in ((b'["python", [3, 9, 8]]', "3.9.8"), (b"null", None)):
            with self.subTest(output=output), patch.object(
                doctor, "probe", return_value=subprocess.CompletedProcess([], 0, output)
            ):
                diagnostics = []
                runtime = doctor.inspect_python(sys.executable, diagnostics, "python")
                self.assertEqual(runtime["state"], "unavailable")
                self.assertEqual(runtime.get("version"), version)
                self.assertEqual(diagnostics[0]["code"], "python")

    def test_timed_out_python_probe_reports_reason_without_process_output(self):
        failure = subprocess.TimeoutExpired([], doctor.PROBE_TIMEOUT, stderr=b"private diagnostic")
        with patch.object(doctor, "probe", side_effect=failure):
            diagnostics = []
            runtime = doctor.inspect_python(sys.executable, diagnostics, "python")

        self.assertEqual(runtime["state"], "unavailable")
        self.assertIn("timed out", diagnostics[0]["message"])
        self.assertNotIn("private diagnostic", diagnostics[0]["message"])

    def test_missing_git_prevents_hook_probe(self):
        with patch.object(doctor.shutil, "which", return_value=None):
            report = self.run_doctor()

        self.assertFalse(report["ok"])
        self.assert_state(report, "git", "unavailable")
        self.assert_state(report, "repository", "unavailable")
        self.assert_state(report, "hook", "unavailable")
        self.assertEqual(report["diagnostics"][0]["code"], "git-missing")
        self.hook.hook_status.assert_not_called()

    def test_nested_directory_does_not_pass_as_selected_worktree(self):
        nested = self.repo / "nested"
        nested.mkdir()
        report = self.run_doctor(repo=nested)

        self.assertFalse(report["ok"])
        self.assert_state(report, "git", "ready")
        self.assert_state(report, "repository", "unavailable")
        self.assert_state(report, "hook", "unavailable")
        self.hook.hook_status.assert_not_called()

    def test_missing_checker_modules_cannot_pass(self):
        del self.modules["validation"]
        del self.modules["hooks"]
        report = self.run_doctor()

        self.assertFalse(report["ok"])
        for name in ("validation", "hooks"):
            self.assertEqual(report["components"]["checkers"][name]["state"], "unavailable")
        self.assert_state(report, "hook", "unavailable")
        self.assert_state(report, "assignment", "unavailable")
        self.assertEqual([item["code"] for item in report["diagnostics"]],
                         ["checker-unavailable", "checker-unavailable"])

    def test_conflicting_hook_is_not_reported_as_unconfigured(self):
        self.hook.hook_status.return_value = {
            "state": "unavailable",
            "diagnostics": [{"code": "hook-conflict", "message": "Another hook is active."}],
        }
        report = self.run_doctor()

        self.assertFalse(report["ok"])
        self.assert_state(report, "hook", "unavailable")
        self.assert_state(report, "assignment", "unavailable")
        self.assertEqual(report["diagnostics"], self.hook.hook_status.return_value["diagnostics"])

    def test_configured_hook_must_have_a_working_python(self):
        self.configure_hook(python=str(self.repo / "missing-hook-python.exe"))
        report = self.run_doctor()

        self.assertFalse(report["ok"])
        self.assert_state(report, "python", "ready")
        self.assert_state(report, "hook", "unavailable")
        self.assertEqual(report["components"]["hook"]["python"]["state"], "unavailable")
        self.assert_state(report, "assignment", "not_applicable")

    def test_maintainer_hook_has_no_assignment(self):
        self.configure_hook()
        report = self.run_doctor()

        self.assertTrue(report["ok"], report)
        self.assert_state(report, "hook", "ready")
        self.assert_state(report, "assignment", "not_applicable")
        self.git_checks.load_assignment.assert_not_called()

    def test_developer_hook_loads_the_pin_and_verifies_the_selected_checkout(self):
        assignment_path = self.repo / "assignment.json"
        digest = "a" * 64
        self.configure_hook(assignment=str(assignment_path), digest=digest)
        report = self.run_doctor()

        self.assertTrue(report["ok"], report)
        self.assert_state(report, "hook", "ready")
        self.assert_state(report, "assignment", "ready")
        self.assertEqual(report["components"]["assignment"]["sha256"], digest)
        self.git_checks.load_assignment.assert_called_once_with(assignment_path, digest)
        self.git_checks.validate_checkout.assert_called_once_with(
            self.repo, self.git_checks.load_assignment.return_value,
        )

    def test_stale_missing_and_incomplete_assignment_bindings_fail(self):
        assignment_path = self.repo / "assignment.json"
        for error, code in (
            (QualityError("The assignment hash changed."), "assignment-invalid"),
            (FileNotFoundError, "assignment-unavailable"),
            (None, "assignment-binding"),
        ):
            with self.subTest(code=code):
                self.configure_hook(assignment=str(assignment_path), digest="b" * 64 if error else None)
                self.git_checks.load_assignment.side_effect = error
                report = self.run_doctor()

                self.assertFalse(report["ok"])
                self.assert_state(report, "hook", "unavailable")
                self.assert_state(report, "assignment", "unavailable")
                self.assertEqual(report["diagnostics"][0]["code"], code)
                self.git_checks.validate_checkout.assert_not_called()

    def test_assignment_for_another_checkout_fails(self):
        self.configure_hook(assignment=str(self.repo / "assignment.json"), digest="a" * 64)
        self.git_checks.validate_checkout.side_effect = QualityError("Wrong worktree.")
        report = self.run_doctor()

        self.assertFalse(report["ok"])
        self.assert_state(report, "hook", "unavailable")
        self.assert_state(report, "assignment", "unavailable")
        self.assertIn("Wrong worktree", report["diagnostics"][0]["message"])
