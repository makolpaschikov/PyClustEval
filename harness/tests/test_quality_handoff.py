import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quality_support import handoff as q
from quality_support.common import QualityError


class HandoffTest(unittest.TestCase):
    def setUp(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        p = patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        scratch = Path(__file__).resolve().parents[2] / ".agent-work/tasks/q4-result"
        scratch.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name).resolve()
        self.git("init", "-b", "work")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / ".gitignore").write_text(".agent-work/\n")
        (self.repo / "allowed").mkdir()
        (self.repo / "allowed/a").write_text("a\n")
        (self.repo / "outside").write_text("outside\n")
        self.commit("base")
        self.base = self.head()
        self.path = self.repo / ".agent-work/tasks/assignment.json"
        self.path.parent.mkdir(parents=True)
        self.assignment = {"format_version": 1, "task_id": "t", "developer_id": "d",
                           "repository": str(self.repo), "worktree": str(self.repo), "branch": "work",
                           "base": self.base, "allowed_files": [], "allowed_directories": ["allowed"],
                           "authority": {"source": "human", "scope": "fixture"}}
        self.save()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.STDOUT).decode().strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-m", message)

    def head(self):
        return self.git("rev-parse", "HEAD")

    def save(self):
        raw = json.dumps(self.assignment).encode()
        self.path.write_bytes(raw)
        self.pin = hashlib.sha256(raw).hexdigest()

    def check(self, head=None):
        return q.run_command(SimpleNamespace(assignment=self.path, assignment_sha256=self.pin, head=head or self.head()), self.repo)

    def test_valid_dirty_and_unchanged(self):
        (self.repo / "allowed/a").write_text("commit\n")
        self.commit("allowed")
        (self.repo / "allowed/a").write_text("remaining\n")
        before = q.git_identity(self.repo)
        report = self.check()
        self.assertTrue(report["ok"], report)
        self.assertFalse(report["worktree_clean"])
        self.assertIn(" M allowed/a", report["remaining_status"])
        self.assertEqual(report["commits"][0]["paths"], ["allowed/a"])
        self.assertEqual((report["head"], report["base"], report["assignment_sha256"]), (self.head(), self.base, self.pin))
        self.assertEqual(q.git_identity(self.repo), before)
        self.assertEqual((self.repo / "allowed/a").read_text(), "remaining\n")

    def test_reverted_violation_and_rename(self):
        (self.repo / "outside").write_text("violation\n")
        self.commit("violate")
        (self.repo / "outside").write_text("outside\n")
        self.commit("revert")
        self.git("mv", "outside", "allowed/moved")
        self.commit("rename")
        report = self.check()
        self.assertFalse(report["ok"])
        self.assertEqual(len([d for d in report["diagnostics"] if d["path"] == "outside"]), 3)
        self.assertEqual(set(report["commits"][-1]["paths"]), {"outside", "allowed/moved"})

    def test_wrong_head_base_and_stale_assignment(self):
        with self.assertRaises(QualityError): self.check("a" * 40)
        with self.assertRaises(QualityError): self.check(self.base[:8])
        self.assignment["base"] = "a" * 40
        self.save()
        with self.assertRaises(QualityError): self.check()
        self.path.write_text("{}")
        with self.assertRaises(QualityError): self.check()

    def test_merge_history_is_rejected(self):
        self.git("checkout", "-b", "side")
        (self.repo / "allowed/side").write_text("side")
        self.commit("side")
        self.git("checkout", "work")
        (self.repo / "allowed/main").write_text("main")
        self.commit("main")
        self.git("merge", "--no-ff", "side", "-m", "merge")
        report = self.check()
        self.assertIn("unsupported_history", [d["code"] for d in report["diagnostics"]])
        self.assertFalse(report["ok"])

    def test_changed_identity_and_unmerged(self):
        original = q.git_identity
        calls = 0
        def changing(repo):
            nonlocal calls
            calls += 1
            identity = original(repo)
            if calls == 2:
                identity["index_sha256"] = "changed"
            return identity
        with patch.object(q, "git_identity", side_effect=changing):
            self.assertIn("changed_input", [d["code"] for d in self.check()["diagnostics"]])
        oid = self.git("rev-parse", "HEAD:allowed/a")
        subprocess.run(["git", "-C", str(self.repo), "update-index", "--index-info"],
                       input=f"100644 {oid} 1\tallowed/a\n100644 {oid} 2\tallowed/a\n".encode(), check=True)
        self.assertIn("unmerged", [d["code"] for d in self.check()["diagnostics"]])

    def test_config_cannot_hide_committed_gitlink(self):
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.base},outside-link")
        self.git("commit", "-m", "gitlink")
        self.git("config", "diff.ignoreSubmodules", "all")
        report = self.check()
        self.assertFalse(report["ok"], report)
        self.assertTrue(any(d.get("path") == "outside-link" for d in report["diagnostics"]))

    def test_replacement_ref_cannot_hide_committed_violation(self):
        (self.repo / "outside").write_text("violation\n")
        self.commit("violation")
        delivered = self.head()
        tree = self.git("rev-parse", self.base + "^{tree}")
        replacement = subprocess.check_output(
            ["git", "-C", str(self.repo), "commit-tree", tree, "-p", self.base, "-m", "disguise"]
        ).decode().strip()
        self.git("replace", delivered, replacement)
        report = self.check(delivered)
        self.assertFalse(report["ok"], report)
        self.assertTrue(any(d.get("path") == "outside" for d in report["diagnostics"]))


if __name__ == "__main__":
    unittest.main()
