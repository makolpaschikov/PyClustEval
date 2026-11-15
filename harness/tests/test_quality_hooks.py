import os
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'harness/scripts'))
from quality_support import hooks, doctor
from quality_support.common import QualityError


class HookTests(unittest.TestCase):
    def setUp(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        p = patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        scratch = ROOT / '.agent-work/tasks/q3-result'
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        self.git('init', '-b', 'work')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.repo / '.gitignore').write_text('.agent-work/\n')
        entry = self.repo / 'harness/scripts/quality.py'
        entry.parent.mkdir(parents=True)
        entry.write_text('print("fixture entrypoint")\n')
        self.git('add', '.gitignore', 'harness/scripts/quality.py')
        self.git('commit', '-m', 'initial fixture')

    def git(self, *args, check=True):
        result = subprocess.run(['git', '-C', str(self.repo), *args], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=300)
        if check and result.returncode:
            self.fail(result.stdout.decode('utf-8', 'replace'))
        return result

    def action(self, action, **kwargs):
        args = SimpleNamespace(command='hooks', action=action, **kwargs)
        return hooks.run_command(args, self.repo)

    def install(self, python=sys.executable):
        return self.action('install', python=Path(python), assignment=None, assignment_sha256=None)

    def test_foreign_and_configuration(self):
        hook = self.repo / '.git/hooks/pre-commit'
        hook.write_bytes(b'#!/bin/sh\nexit 0\n')
        self.assertEqual(hooks.hook_status(self.repo)['state'], 'unavailable')
        self.assertIn('Foreign hook', hooks.hook_status(self.repo)['diagnostics'][0]['message'])
        report = doctor.run_command(SimpleNamespace(python=Path(sys.executable)), self.repo.resolve())
        self.assertEqual(report['components']['hook']['state'], 'unavailable')
        self.assertNotIn('hook-not-configured', [d['code'] for d in report['diagnostics']])
        with self.assertRaises(QualityError): self.install()
        self.assertEqual(hook.read_bytes(), b'#!/bin/sh\nexit 0\n')
        hook.unlink()
        self.git('config', 'core.hooksPath', 'foreign')
        with self.assertRaises(QualityError): self.install()
        self.git('config', '--unset', 'core.hooksPath')
        with self.assertRaises(OSError): self.install(self.repo / 'missing-python')
        self.assertTrue(self.install()['ok'])
        self.assertEqual(hooks.hook_status(self.repo)['state'], 'ready')
        hook.write_bytes(hooks.LAUNCHER + b'# changed\n')
        self.assertEqual(hooks.hook_status(self.repo)['state'], 'unavailable')
        with self.assertRaises(QualityError): self.action('uninstall')

    def test_missing_index_entrypoint_is_unavailable_and_install_refuses(self):
        self.git('rm', '--cached', 'harness/scripts/quality.py')
        with self.assertRaises(QualityError): self.install()
        self.assertFalse((self.repo / '.git/hooks/pre-commit').exists())
        self.git('add', '-N', 'harness/scripts/quality.py')
        with self.assertRaises(QualityError): self.install()
        self.git('rm', '--cached', 'harness/scripts/quality.py')
        oid = self.git('rev-parse', 'HEAD:harness/scripts/quality.py').stdout.decode().strip()
        self.git('update-index', '--add', '--cacheinfo', f'120000,{oid},harness/scripts/quality.py')
        with self.assertRaises(QualityError): self.install()
        self.git('add', 'harness/scripts/quality.py')
        self.assertTrue(self.install()['ok'])
        self.git('rm', '--cached', 'harness/scripts/quality.py')
        status = hooks.hook_status(self.repo)
        self.assertEqual(status['state'], 'unavailable')
        self.assertIn('stage-0 regular', status['diagnostics'][0]['message'])
        report = doctor.run_command(SimpleNamespace(python=Path(sys.executable)), self.repo.resolve())
        self.assertEqual(report['components']['hook']['state'], 'unavailable')
        commit = self.git('commit', '-m', 'missing staged entrypoint', check=False)
        self.assertNotEqual(commit.returncode, 0)
        self.assertTrue((self.repo / 'harness/scripts/quality.py').exists())

    def test_selection_and_changed_index(self):
        self.assertEqual(hooks.select_tests(['harness/scripts/journal.py']), ['test_journal.py'])
        self.assertEqual(hooks.select_tests(['harness/tests/test_task.py']), ['test_task.py'])
        self.assertEqual(set(hooks.select_tests(['harness/scripts/new.py'])), hooks.FAST)
        self.assertTrue(self.install()['ok'])
        snapshot = Path(self.tmp.name) / 'snapshot'
        snapshot.mkdir()
        config = self.repo / hooks.CONFIG
        args = SimpleNamespace(snapshot=snapshot, binding=config)
        git_result = SimpleNamespace(stdout=b'')
        with patch.object(hooks, '_locations', return_value=(config, None, None)), \
             patch.object(hooks.git_checks, 'git_identity', side_effect=[{'head': 'a', 'index_sha256': '1'}, {'head': 'a', 'index_sha256': '2'}]), \
             patch.object(hooks.git_checks, 'git', return_value=git_result), \
             patch('quality_support.validation.validate_repository', return_value={'ok': True, 'diagnostics': []}):
            report = hooks._precommit(args, self.repo)
        self.assertFalse(report['ok'])
        self.assertIn('changed-input', [d['code'] for d in report['diagnostics']])

    def test_real_commits_and_worktree_isolation(self):
        # Copy tracked harness and references, plus newly implemented checkers.
        if (ROOT / '.git').exists():
            names = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).split(b'\0')
            selected = {os.fsdecode(p) for p in names if p}
        else:
            selected = set()
            for directory, dirs, files in os.walk(ROOT):
                dirs[:] = [name for name in dirs if name not in {'.agent-work', '.git', '__pycache__'}]
                selected.update((Path(directory) / name).relative_to(ROOT).as_posix() for name in files)
        selected.update(str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT / 'harness/scripts/quality_support').glob('*.py'))
        selected.add('harness/scripts/quality.py')
        selected.update(str(p.relative_to(ROOT)).replace('\\', '/') for p in (ROOT / 'harness/tests').glob('test_quality_*.py'))
        for name in selected:
            source = ROOT / name
            if not source.is_file() or name == '.gitignore': continue
            dest = self.repo / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
        (self.repo / 'harness/ita-old.md').write_text('tracked target\n')
        self.git('add', '.')
        self.git('commit', '-m', 'baseline')
        self.assertTrue(self.install()['ok'])
        child = Path(self.tmp.name) / 'child'
        self.git('worktree', 'add', '-b', 'child', str(child))
        self.assertEqual(hooks.hook_status(child)['state'], 'not_configured')
        (child / 'AGENTS.md').write_bytes(b'x' * 32001)
        subprocess.run(['git', '-C', str(child), 'add', 'AGENTS.md'], check=True, timeout=30)
        child_commit = subprocess.run(['git', '-C', str(child), 'commit', '-m', 'unconfigured'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
        self.assertEqual(child_commit.returncode, 0, child_commit.stdout.decode('utf-8', 'replace'))
        doc = self.repo / 'harness/ita-doc.md'
        new_target = self.repo / 'harness/ita-new.md'
        old_target = self.repo / 'harness/ita-old.md'
        for target, existed in ((new_target, False), (old_target, True)):
            doc.write_text(f'[link]({target.name})\n')
            if not existed: target.write_text('only working file\n')
            else: self.git('rm', '--cached', str(target.relative_to(self.repo)))
            self.git('add', str(doc.relative_to(self.repo)))
            self.git('add', '-N', str(target.relative_to(self.repo)))
            index_before = (self.repo / '.git/index').read_bytes()
            target_before = target.read_bytes()
            commit = self.git('commit', '-m', 'intent target absent', check=False)
            self.assertNotEqual(commit.returncode, 0, commit.stdout.decode('utf-8', 'replace'))
            self.assertIn(b'ita-', commit.stdout)
            self.assertEqual((self.repo / '.git/index').read_bytes(), index_before)
            self.assertEqual(target.read_bytes(), target_before)
            self.git('rm', '-f', '--cached', str(doc.relative_to(self.repo)), str(target.relative_to(self.repo)))
            doc.unlink()
            if existed: self.git('add', str(target.relative_to(self.repo)))
            else: target.unlink()
        module = self.repo / 'harness/tests/staged_probe_module.py'
        test_probe = self.repo / 'harness/tests/test_pythonpath_fixture.py'
        module.write_text('ANSWER = 42\n')
        test_probe.write_text('import unittest\nimport staged_probe_module\nclass Probe(unittest.TestCase):\n def test_value(self): self.assertEqual(staged_probe_module.ANSWER, 42)\n')
        self.git('add', str(test_probe.relative_to(self.repo)))
        with patch.dict(os.environ, {'PYTHONPATH': str(module.parent)}):
            commit = self.git('commit', '-m', 'unstaged pythonpath module', check=False)
            self.assertNotEqual(commit.returncode, 0)
            self.assertIn(b'staged_probe_module', commit.stdout)
            self.git('add', str(module.relative_to(self.repo)))
            commit = self.git('commit', '-m', 'staged local module', check=False)
            self.assertEqual(commit.returncode, 0, commit.stdout.decode('utf-8', 'replace'))
        agents = self.repo / 'AGENTS.md'
        original = agents.read_bytes()
        agents.write_bytes(original + b'\n')
        self.git('add', 'AGENTS.md')
        agents.write_bytes(original + b'\nunstaged\n')
        before = self.git('diff', '--cached', '--binary').stdout
        commit = self.git('commit', '-m', 'valid staged', check=False)
        self.assertEqual(commit.returncode, 0, commit.stdout.decode('utf-8', 'replace'))
        self.assertEqual(agents.read_bytes(), original + b'\nunstaged\n')
        self.assertTrue(before)
        agents.write_bytes(b'x' * 32001)
        self.git('add', 'AGENTS.md')
        agents.write_bytes(original)
        before = self.git('diff', '--cached', '--binary').stdout
        commit = self.git('commit', '-m', 'invalid staged', check=False)
        self.assertNotEqual(commit.returncode, 0)
        self.assertIn(b'agents-size', commit.stdout)
        self.assertEqual(before, self.git('diff', '--cached', '--binary').stdout)
        self.assertEqual(agents.read_bytes(), original)
        self.git('reset', 'HEAD', '--', 'AGENTS.md')
        assignment = {'format_version': 1, 'task_id': 'fixture', 'developer_id': 'fixture',
            'repository': str(self.repo.resolve()), 'worktree': str(self.repo.resolve()),
            'branch': 'work', 'base': self.git('rev-parse', 'HEAD').stdout.decode().strip(),
            'allowed_files': [], 'allowed_directories': ['harness/tests'],
            'authority': {'source': 'fixture', 'scope': 'test'}}
        assignment_path = self.repo / '.agent-work/tasks/assignment.json'
        data = json.dumps(assignment).encode()
        assignment_path.write_bytes(data)
        pin = hashlib.sha256(data).hexdigest()
        self.assertTrue(self.action('install', python=Path(sys.executable), assignment=assignment_path, assignment_sha256=pin)['ok'])
        test = self.repo / 'harness/tests/test_smoke_hook_fixture.py'
        test.write_text('import unittest\nclass Smoke(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
        self.git('add', str(test.relative_to(self.repo)))
        commit = self.git('commit', '-m', 'selected test succeeds', check=False)
        self.assertEqual(commit.returncode, 0, commit.stdout.decode('utf-8', 'replace'))
        self.assertIn(b'test_smoke_hook_fixture.py', commit.stdout)
        test.write_text('import unittest\nclass Smoke(unittest.TestCase):\n def test_bad(self): self.fail("staged failure")\n')
        self.git('add', str(test.relative_to(self.repo)))
        test.write_text('working tree differs\n')
        commit = self.git('commit', '-m', 'selected test fails', check=False)
        self.assertNotEqual(commit.returncode, 0)
        self.assertIn(b'staged failure', commit.stdout)
        assignment_path.write_bytes(data + b' ')
        commit = self.git('commit', '-m', 'stale assignment', check=False)
        self.assertNotEqual(commit.returncode, 0)
        self.assertIn(b'SHA-256', commit.stdout)
        self.action('uninstall')
        self.assertEqual(hooks.hook_status(self.repo)['state'], 'not_configured')
        self.assertTrue((self.repo / '.git/hooks/pre-commit').exists())


if __name__ == '__main__': unittest.main()
