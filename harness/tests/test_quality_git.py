import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quality_support import git_checks as q
from quality_support.common import QualityError


class GitChecksTest(unittest.TestCase):
    def setUp(self):
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        patcher = patch.dict(os.environ, environment, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        scratch = Path(__file__).resolve().parents[2] / ".agent-work" / "tasks" / "q2-result"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        self.git("init", "-b", "work")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / ".gitignore").write_text(".agent-work/\n", encoding="utf-8")
        (self.repo / "allowed").mkdir()
        (self.repo / "allowed/a.txt").write_text("base\n", encoding="utf-8")
        (self.repo / "outside.txt").write_text("other\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.path = self.repo / ".agent-work/tasks/assignment.json"
        self.path.parent.mkdir(parents=True)
        self.assignment = {"format_version": 1, "task_id": "t", "developer_id": "d",
            "repository": str(self.repo), "worktree": str(self.repo), "branch": "work",
            "base": self.base, "allowed_files": [], "allowed_directories": ["allowed"],
            "authority": {"source": "human", "scope": "fixture"}}
        self.save()

    def git(self, *args):
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("GIT_"):
                env.pop(key)
        return subprocess.check_output(["git", "-C", str(self.repo), *args], env=env, stderr=subprocess.STDOUT).decode().strip()

    def save(self):
        data = json.dumps(self.assignment).encode()
        self.path.write_bytes(data)
        self.pin = hashlib.sha256(data).hexdigest()

    def run_check(self):
        return q.run_command(SimpleNamespace(assignment=self.path, assignment_sha256=self.pin), self.repo)

    def test_partial_staging_and_no_mutation(self):
        file = self.repo / "allowed/a.txt"
        file.write_text("staged\n", encoding="utf-8")
        self.git("add", "allowed/a.txt")
        file.write_text("unstaged\n", encoding="utf-8")
        before = q.git_identity(self.repo)
        report = self.run_check()
        self.assertTrue(report["ok"], report)
        self.assertEqual((report["assignment_path"], report["assignment_sha256"], report["task_id"], report["developer_id"], report["base"], report["branch"]),
                         (str(self.path.resolve()), self.pin, "t", "d", self.base, "work"))
        self.assertEqual(report["staged_paths"], ["allowed/a.txt"])
        self.assertIn("MM allowed/a.txt", report["remaining_status"])
        self.assertEqual(before, q.git_identity(self.repo))
        self.assertEqual(file.read_text(), "unstaged\n")

    def test_rename_both_sides_and_forbidden(self):
        self.git("mv", "outside.txt", "allowed/moved.txt")
        report = self.run_check()
        self.assertEqual(set(report["staged_paths"]), {"outside.txt", "allowed/moved.txt"})
        self.assertFalse(report["ok"])
        self.assertFalse(q.path_allowed(".agent-work/tasks/file", {"allowed_files": [], "allowed_directories": [".agent-work"]}))
        self.assertFalse(q.path_allowed("allowed-other/a", self.assignment))

    def test_stale_pin_schema_and_checkout(self):
        self.path.write_text("{}", encoding="utf-8")
        with self.assertRaises(QualityError): self.run_check()
        self.save()
        self.assignment["allowed_directories"] = ["allowed/*"]
        self.save()
        with self.assertRaises(QualityError): self.run_check()
        self.assignment["allowed_directories"] = ["allowed"]
        self.assignment["branch"] = "wrong"
        self.save()
        with self.assertRaises(QualityError): self.run_check()

    def test_changed_input_and_unmerged(self):
        original = q.git_identity
        calls = 0
        def changing(repo):
            nonlocal calls
            calls += 1
            identity = original(repo)
            if calls == 2: identity["index_sha256"] = "changed"
            return identity
        with patch.object(q, "git_identity", side_effect=changing):
            self.assertIn("changed_input", [x["code"] for x in self.run_check()["diagnostics"]])
        oid = self.git("rev-parse", "HEAD:allowed/a.txt")
        subprocess.run(["git", "-C", str(self.repo), "update-index", "--index-info"],
            input=f"100644 {oid} 1\tallowed/a.txt\n100644 {oid} 2\tallowed/a.txt\n".encode(), check=True)
        self.assertIn("unmerged", [x["code"] for x in self.run_check()["diagnostics"]])

    def test_alternate_index_is_used(self):
        alternate = self.repo / "alternate-index"
        shutil.copyfile(self.repo / ".git/index", alternate)
        (self.repo / "outside.txt").write_text("alternate staged\n", encoding="utf-8")
        with patch.dict(os.environ, {"GIT_INDEX_FILE": str(alternate)}):
            subprocess.run(["git", "-C", str(self.repo), "add", "outside.txt"], check=True)
            report = self.run_check()
            self.assertFalse(report["ok"])
            self.assertIn("outside.txt", report["staged_paths"])
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_detached_and_invalid_base(self):
        self.git("checkout", "--detach")
        with self.assertRaises(QualityError): self.run_check()
        self.git("checkout", "work")
        self.assignment["base"] = self.base[:8]
        self.save()
        with self.assertRaises(QualityError): self.run_check()

    def test_duplicate_field_and_wrong_common_repository(self):
        raw = self.path.read_text(encoding="utf-8")
        raw = raw.replace('"task_id": "t"', '"task_id": "t", "task_id": "other"')
        self.path.write_text(raw, encoding="utf-8")
        self.pin = hashlib.sha256(raw.encode()).hexdigest()
        with self.assertRaises(QualityError): self.run_check()
        self.save()
        foreign = self.repo / "foreign"
        foreign.mkdir()
        subprocess.run(["git", "-C", str(foreign), "init", "-b", "work"], check=True, capture_output=True)
        self.assignment["worktree"] = str(foreign.resolve())
        self.save()
        with self.assertRaisesRegex(QualityError, "common repository"):
            q.validate_checkout(foreign, q.load_assignment(self.path, self.pin))

    def test_real_linked_worktree(self):
        linked = self.repo / ".agent-work" / "linked"
        self.git("worktree", "add", "-b", "linked", str(linked), self.base)
        self.addCleanup(lambda: self.git("worktree", "remove", "--force", str(linked)))
        self.assignment["worktree"] = str(linked.resolve())
        self.assignment["branch"] = "linked"
        self.save()
        report = q.run_command(SimpleNamespace(assignment=self.path, assignment_sha256=self.pin), linked)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["head"], self.base)
        self.assertEqual(report["branch"], "linked")

    def test_task_root_symlink_escape_rejected(self):
        task_root = self.repo / ".agent-work" / "tasks"
        displaced = self.repo / "displaced"
        task_root.rename(displaced)
        try:
            task_root.symlink_to(displaced, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"Directory symlink unavailable: {exc}")
        self.path = task_root / "assignment.json"
        with self.assertRaises(QualityError):
            q.load_assignment(self.path, self.pin)

    def test_ignored_submodule_configuration_cannot_hide_gitlink(self):
        self.git("config", "diff.ignoreSubmodules", "all")
        before = q.git_identity(self.repo)
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.base},out-of-scope")
        report = self.run_check()
        self.assertFalse(report["ok"])
        self.assertIn("out-of-scope", report["staged_paths"])
        self.assertTrue(any(entry.startswith("A") and entry[3:] == "out-of-scope" for entry in report["remaining_status"]))
        self.assertNotEqual(before["index_sha256"], report["index_sha256"])

    def test_replacement_ref_cannot_change_observed_commit(self):
        tree = self.git("rev-parse", "HEAD^{tree}")
        replacement = subprocess.run(["git", "-C", str(self.repo), "commit-tree", tree],
            input=b"replacement message\n", stdout=subprocess.PIPE, check=True).stdout.decode().strip()
        self.git("replace", self.base, replacement)
        self.assertEqual(self.git("show", "-s", "--format=%s", self.base), "replacement message")
        self.assertEqual(q.git(self.repo, "show", "-s", "--format=%s", self.base).stdout.decode().strip(), "fixture")
        self.assertTrue(self.run_check()["ok"])

    def test_tag_matching_branch_does_not_reject_checkout(self):
        self.git("tag", "work")
        self.assertTrue(self.run_check()["ok"])

    def test_nul_parsing(self):
        self.assertEqual(q.changed_paths(b"R100\0old\0new\0M\0line\nname\0"), ["old", "new", "line\nname"])
        with self.assertRaises(QualityError): q.changed_paths(b"R100\0old\0")


if __name__ == "__main__": unittest.main()
