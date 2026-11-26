"""Focused read-only checks for the harness validator."""
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'harness/scripts'))
from quality_support import validation


class ValidationTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / '.agent-work/tasks/q1-result'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.repo = Path(self.tmp.name)
        shutil.copytree(ROOT / 'harness', self.repo / 'harness')
        shutil.copytree(ROOT / '.agents', self.repo / '.agents')
        shutil.copy2(ROOT / 'AGENTS.md', self.repo)
        shutil.copy2(ROOT / 'README.md', self.repo)

    def tearDown(self): self.tmp.cleanup()

    def report(self): return validation.validate_repository(self.repo)
    def codes(self): return {x['code'] for x in self.report()['diagnostics']}
    def file(self, name): return self.repo / name

    def test_repository_and_read_only(self):
        before = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        # Imported owning modules must not write bytecode into the checkout.
        old = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try: report = self.report()
        finally: sys.dont_write_bytecode = old
        after = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(report['ok'], report['diagnostics'])

    def test_metadata_failures(self):
        path = self.file('.agents/skills/code-scout/SKILL.md')
        original = path.read_text(encoding='utf-8')
        for metadata in ('name: code-scout\nname: code-scout\ndescription: x',
                         'name: code-scout\ndescription: >\n  nested',
                         'name: wrong\ndescription: x', 'name: code-scout\nextra: x',
                         'name: code-scout\ndescription: invalid: scalar',
                         'name: code-scout\ndescription:    ',
                         *('name: code-scout\ndescription: ' + v for v in
                           ('- nested-sequence', 'null', 'true', '123', ']', '0x12', '.5', 'OFF'))):
            with self.subTest(metadata=metadata):
                path.write_text('---\n' + metadata + '\n---\nbody\n', encoding='utf-8')
                self.assertIn('metadata', self.codes())
        path.write_text(original, encoding='utf-8')

    def test_links_anchors_comments_and_fences(self):
        path = self.file('harness/check.md')
        path.write_text('# Heading\n# Heading\n<a id="custom"></a>\n[ok](#heading-1) [id](#custom)\n<!-- [no](missing) -->\n```\n[no](missing)\n```\n', encoding='utf-8')
        self.assertTrue(self.report()['ok'], self.report()['diagnostics'])
        path.write_text('# Heading\n[bad](#absent) [missing](nowhere.md)\n', encoding='utf-8')
        self.assertIn('link', self.codes())
        path.write_text('[x][ref]\n[ref]: other.md\n', encoding='utf-8')
        self.assertIn('markdown', self.codes())
        path.write_text('```\nunclosed\n', encoding='utf-8')
        self.assertIn('markdown', self.codes())

    def test_exact_html_id_attributes(self):
        path = self.file('harness/html-anchor.md')
        path.write_text('<span data-id="not-an-anchor"></span>\n[x](#not-an-anchor)\n', encoding='utf-8')
        self.assertTrue(any(d['code'] == 'link' and 'missing anchor' in d['message']
                            for d in self.report()['diagnostics']))
        path.write_text('<span id = "real-anchor"></span>\n[x](#real-anchor)\n', encoding='utf-8')
        report = self.report()
        self.assertTrue(report['ok'], report['diagnostics'])

    def test_journal_template_and_limit(self):
        path = self.file('harness/signals/SIGNALS.md')
        path.write_text('broken', encoding='utf-8')
        self.assertIn('journal', self.codes())
        path = self.file('.agents/skills/analyst-orchestrator/assets/epic.md')
        path.write_text('bad template', encoding='utf-8')
        self.assertIn('template', self.codes())
        self.file('AGENTS.md').write_bytes(b'x' * 32001)
        self.assertIn('agents-size', self.codes())

    def test_linked_maintained_inputs_are_refused_before_reading(self):
        target = self.file('harness/README.md')
        original = Path.is_symlink
        def linked(path):
            return path == target or original(path)
        with patch.object(Path, 'is_symlink', linked):
            report = self.report()
        self.assertTrue(any(d['code'] == 'markdown' and 'linked input' in d['message']
                            for d in report['diagnostics']), report)

    def test_task_producer_drift_is_diagnosed(self):
        path = self.file('harness/scripts/task/task_support/artifacts.py')
        with path.open('a', encoding='utf-8') as f:
            f.write("\n_old_new_item = new_item\ndef new_item(*args):\n    item = _old_new_item(*args)\n    del item['status']\n    return item\n")
        report = self.report()
        self.assertTrue(any(d['code'] == 'compatibility' and 'status' in d['message']
                            for d in report['diagnostics']), report)

    def test_incompatible_context_and_bundle_are_diagnosed(self):
        path = self.file('harness/scripts/task/task_support/bundles.py')
        with path.open('a', encoding='utf-8') as f:
            f.write('\n_old_validate_context = validate_context\ndef validate_context(c):\n    raise TaskError("probe mismatch")\n')
        self.assertIn('compatibility', self.codes())


if __name__ == '__main__': unittest.main()
