"""Behavioral checks for Python review independence across epic scope."""
import unittest

import test_task
from task_support.formats import TaskError


class ReviewIndependenceTests(unittest.TestCase):
    def setUp(self):
        self.fx = test_task.TaskTests(methodName="runTest")
        self.fx.setUp()
        self.addCleanup(self.fx.tearDown)
        self.manifest = self.fx.epic_with_children()
        self.epic, self.first, self.second = self.manifest["items"]
        for item in (self.first, self.second, self.epic):
            self.fx.completed(self.manifest, item)
        self.epic["contributors"] = ["epic-author"]
        self.first["contributors"] = ["first-author"]
        self.second["contributors"] = ["second-author"]

    def gate(self, item, gate="completion"):
        return self.fx.gate(self.manifest, gate, item["id"])

    def test_epic_rejects_each_child_author_at_completion_and_resumption(self):
        for author in ("first-author", "second-author"):
            for gate in ("completion", "resumption"):
                with self.subTest(author=author, gate=gate):
                    self.epic["code_review"]["reviewer"] = author
                    with self.assertRaisesRegex(TaskError, "Implementation reviewer must be independent"):
                        self.gate(self.epic, gate)

    def test_epic_rejects_own_author_and_coordinator(self):
        for reviewer in ("epic-author", self.manifest["coordinator"]):
            with self.subTest(reviewer=reviewer):
                self.epic["code_review"]["reviewer"] = reviewer
                with self.assertRaisesRegex(TaskError, "Implementation reviewer must be independent"):
                    self.gate(self.epic)

    def test_independent_epic_reviewer_passes_completion_and_resumption(self):
        self.gate(self.epic)
        self.gate(self.epic, "resumption")

    def test_child_reviewer_may_be_sibling_author(self):
        self.first["code_review"]["reviewer"] = "second-author"
        self.gate(self.first)
        self.gate(self.first, "resumption")

    def test_child_still_rejects_own_author_and_coordinator(self):
        for reviewer in ("first-author", self.manifest["coordinator"]):
            with self.subTest(reviewer=reviewer):
                self.first["code_review"]["reviewer"] = reviewer
                with self.assertRaisesRegex(TaskError, "Implementation reviewer must be independent"):
                    self.gate(self.first)

    def test_dependency_reuse_checks_child_own_scope(self):
        self.first["code_review"]["reviewer"] = "second-author"
        self.second["status"] = "ready"
        self.gate(self.second, "start")
        self.first["code_review"]["reviewer"] = "first-author"
        with self.assertRaisesRegex(TaskError, "Implementation reviewer must be independent"):
            self.gate(self.second, "start")


if __name__ == "__main__":
    unittest.main()
