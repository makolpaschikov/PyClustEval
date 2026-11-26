"""Integration checks for evidence packaging and adoption in isolated Git fixtures."""
import json
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_snapshots as fixtures
from task_support import bundles, evidence
from task_support.artifacts import load
from task_support.formats import TaskError

ROOT = Path(__file__).resolve().parents[2]
fixtures.FIXTURES = ROOT / '.agent-work/tasks/harness-task-automation/m3/fixtures'


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.SnapshotTests(methodName='runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        manifest = self.f.init()
        item = self.f.fill(manifest, 'TASK-001')
        item['mathematics'].update(required=True, rationale='scope', authors=['author'])
        self.f.save(manifest)
        self.root = self.f.directory
        self.path = self.root / 'task.json'
        self.report = self.root / 'report.raw'
        self.report.write_bytes(b'raw\x00\xff\r\n')
        self.before = self.root / 'before.json'
        self.desc = self.root / 'descriptor.json'
        self.n = 0

    def cli(self, command, *args):
        return self.f.cli(command, *args)

    def context(self, stage=None):
        result = self.cli('context', self.root, '--id', 'TASK-001', *(['--stage', stage] if stage else []))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def package(self, kind='spec_review', verdict='accepted', reviewer='reviewer', role='readiness', context=None):
        self.n += 1
        self.before.write_text(json.dumps(context or self.context({'math_specification':'specification','math_implementation':'implementation'}.get(kind))), encoding='utf-8')
        desc = {'reviewer': reviewer, 'verdict': verdict}
        if kind == 'spec_review': desc['kind'] = role
        self.desc.write_text(json.dumps(desc), encoding='utf-8')
        output = self.root / f'review-{self.n}.zip'
        result = self.cli('package-review', self.root, '--id', 'TASK-001', '--kind', kind, '--before', self.before, '--descriptor', self.desc, '--report', self.report, '--output', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        return output

    def adopt(self, bundle, expect=None):
        return self.cli('import-evidence', self.root, '--bundle', bundle, '--adopt', '--expect-sha256', expect or load(self.root)[1])

    def test_package_inspect_archive_and_adoption(self):
        for kind in ('spec_review', 'code_review', 'math_specification', 'math_implementation'):
            with self.subTest(kind=kind):
                bundle = self.package(kind, reviewer='reviewer-' + kind)
                metadata, payloads = bundles.read_bundle(bundle)
                self.assertEqual(payloads['report.bin'], self.report.read_bytes())
                self.assertEqual(metadata['kind'], kind)
                inspect = self.cli('inspect-evidence', '--bundle', bundle)
                self.assertEqual(inspect.returncode, 0, inspect.stderr)
                previous = self.path.read_bytes()
                archive = self.cli('import-evidence', self.root, '--bundle', bundle)
                self.assertEqual(archive.returncode, 0, archive.stderr)
                self.assertEqual(self.path.read_bytes(), previous)
                first = self.adopt(bundle)
                self.assertEqual(first.returncode, 0, first.stderr)
                second = self.adopt(bundle)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertFalse(json.loads(second.stdout)['changed'])
                old_hash = json.loads(first.stdout)['before_sha256']
                self.assertEqual((self.root / '.state-history' / (old_hash + '.json')).read_bytes(), previous)

    def test_review_selection_independence_and_incomplete(self):
        for kind, reviewer, role in [('spec_review', 'analyst', 'readiness'), ('code_review', 'analyst', ''), ('math_specification', 'author', ''), ('math_implementation', 'author', ''), ('spec_review', 'someone', 'combined')]:
            with self.subTest(kind=kind, reviewer=reviewer):
                bundle = self.package(kind, reviewer=reviewer, role=role)
                previous = self.path.read_bytes()
                self.assertEqual(self.adopt(bundle).returncode, 1)
                self.assertEqual(previous, self.path.read_bytes())
        incomplete = self.package(verdict='incomplete')
        self.assertEqual(self.cli('import-evidence', self.root, '--bundle', incomplete).returncode, 0)
        self.assertEqual(self.adopt(incomplete).returncode, 1)
        accepted = self.package(reviewer='shared')
        self.assertEqual(self.adopt(accepted).returncode, 0)
        other = self.package(reviewer='shared', role='alignment')
        self.assertEqual(self.adopt(other).returncode, 1)
        changed = self.package(verdict='changes_requested', reviewer='new')
        self.assertEqual(self.adopt(changed).returncode, 0)
        self.assertEqual(load(self.root)[0]['items'][0]['spec_reviews'][0]['verdict'], 'changes_requested')

    def test_stale_source_spec_wrong_hash_and_corrupt(self):
        bundle = self.package()
        before = self.path.read_bytes()
        stale = self.adopt(bundle, '0' * 64)
        self.assertEqual(stale.returncode, 1)
        partial = json.loads(stale.stdout)
        self.assertFalse(partial['adopted'])
        self.assertTrue(Path(partial['bundle']).is_file())
        self.assertIn('error', partial)
        (self.f.repo / 'source.py').write_text('changed', encoding='utf-8')
        self.assertEqual(self.adopt(bundle).returncode, 1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.cli('import-evidence', self.root, '--bundle', bundle).returncode, 0)
        (self.f.repo / 'source.py').write_text('VALUE = 1\n', encoding='utf-8')
        doc = self.root / load(self.root)[0]['items'][0]['document']
        doc.write_bytes(doc.read_bytes() + b'\n')
        self.assertEqual(self.adopt(bundle).returncode, 1)
        bad = self.root / 'broken.zip'
        bad.write_bytes(bundle.read_bytes()[:-12])
        self.assertEqual(self.cli('inspect-evidence', '--bundle', bad).returncode, 1)
        self.f.git('symbolic-ref', 'HEAD', 'refs/heads/wrong')
        self.assertEqual(self.adopt(bundle).returncode, 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_copy_collision_and_atomic_failure(self):
        bundle = self.package()
        raw = bundle.read_bytes()
        archive = self.root / 'evidence' / (evidence.digest(raw) + '.zip')
        archive.parent.mkdir()
        archive.write_bytes(b'collision')
        self.assertEqual(self.adopt(bundle).returncode, 1)
        self.assertEqual(archive.read_bytes(), b'collision')
        archive.unlink()
        before = self.path.read_bytes()
        with patch('task_support.evidence.os.link', side_effect=OSError('injected copy')):
            with self.assertRaises(OSError): evidence._destination(self.f.repo, self.root, raw)
        self.assertEqual(self.path.read_bytes(), before)
        from task_support.state import mutate_task
        metadata, _ = bundles.read_bundle(bundle)
        target, _, _ = evidence._destination(self.f.repo, self.root, raw)
        def change(candidate, snapshot):
            evidence._adopt(candidate, snapshot, self.root, metadata, target.relative_to(self.root).as_posix(), evidence.digest(raw))
        with patch('task_support.state.atomic_write', side_effect=OSError('injected write')):
            with self.assertRaises(OSError): mutate_task(self.f.repo, self.root, load(self.root)[1], 'import-evidence', change)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.adopt(bundle).returncode, 0)

    def test_cross_checkout_and_drifting_review(self):
        other = self.f.root / 'other'
        other.mkdir()
        def git(*args):
            subprocess.run(['git', '-C', str(other), *args], check=True, capture_output=True)
        git('init', '-q', '-b', 'other-branch')
        (other / '.gitignore').write_bytes((self.f.repo / '.gitignore').read_bytes())
        (other / 'source.py').write_bytes((self.f.repo / 'source.py').read_bytes())
        git('add', '.gitignore', 'source.py')
        result = self.cli('context', self.root, '--id', 'TASK-001', '--source-repo', other)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = json.loads(result.stdout)
        self.before.write_text(json.dumps(before), encoding='utf-8')
        self.desc.write_text(json.dumps({'reviewer':'other-reviewer', 'verdict':'accepted', 'kind':'readiness'}), encoding='utf-8')
        outdir = other / '.agent-work/tasks/worker'
        outdir.mkdir(parents=True)
        bundle = outdir / 'review.zip'
        result = self.cli('package-review', self.root, '--id', 'TASK-001', '--kind', 'spec_review', '--before', self.before, '--descriptor', self.desc, '--report', self.report, '--output', bundle, '--source-repo', other)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.adopt(bundle).returncode, 0)
        stale_before = self.context()
        (self.f.repo / 'source.py').write_text('revised', encoding='utf-8')
        stale = self.package(context=stale_before)
        self.assertEqual(self.cli('import-evidence', self.root, '--bundle', stale).returncode, 0)
        self.assertEqual(self.adopt(stale).returncode, 1)

    def test_implementation_exclusions_include_reviewers_and_contributors(self):
        manifest = load(self.root)[0]
        item = manifest['items'][0]
        item['contributors'] = ['developer']
        self.f.save(manifest)
        code = self.package('code_review', reviewer='developer')
        self.assertEqual(self.adopt(code).returncode, 1)
        math_spec = self.package('math_specification', reviewer='math-reviewer')
        self.assertEqual(self.adopt(math_spec).returncode, 0)
        math_impl = self.package('math_implementation', reviewer='math-reviewer')
        self.assertEqual(self.adopt(math_impl).returncode, 1)

    def test_package_refuses_review_input_drift(self):
        before = self.context()
        self.before.write_text(json.dumps(before), encoding='utf-8')
        self.desc.write_text(json.dumps({'reviewer':'reviewer', 'verdict':'accepted', 'kind':'readiness'}), encoding='utf-8')
        target = self.root / 'drift.zip'
        args = SimpleNamespace(command='package-review', directory=self.root, id='TASK-001', kind='spec_review', before=self.before, descriptor=self.desc, report=self.report, output=target, source_repo=None)
        def capture(*args):
            self.report.write_bytes(b'changed')
            return before
        with patch('task_support.evidence.capture_context', side_effect=capture):
            with self.assertRaises(TaskError): evidence.run_command(args, self.f.repo)
        self.assertFalse(target.exists())

    def test_junction_cannot_redirect_archive(self):
        if sys.platform != 'win32':
            self.skipTest('Windows junction test')
        bundle = self.package()
        outside = self.f.root / 'outside'
        outside.mkdir()
        junction = self.root / 'evidence'
        env = dict(os.environ, M3_JUNCTION=str(junction), M3_TARGET=str(outside))
        result = subprocess.run(['powershell', '-NoProfile', '-Command',
                                 'New-Item -ItemType Junction -Path $env:M3_JUNCTION -Target $env:M3_TARGET | Out-Null'],
                                capture_output=True, text=True, env=env)
        if result.returncode:
            self.skipTest('Cannot create junction: ' + result.stderr)
        try:
            original = self.path.read_bytes()
            self.assertEqual(self.adopt(bundle).returncode, 1)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(self.path.read_bytes(), original)
        finally:
            junction.rmdir()

    def test_cleanup_failure_reports_committed_result(self):
        bundle = self.package()
        args = SimpleNamespace(command='import-evidence', directory=self.root, bundle=bundle,
                               adopt=True, expect_sha256=load(self.root)[1])
        actual = evidence.mutate_task
        def failed_cleanup(*args, **kwargs):
            report = actual(*args, **kwargs)
            report['cleanup_error'] = 'injected lock cleanup failure'
            return report
        with patch('task_support.evidence.mutate_task', side_effect=failed_cleanup):
            report, status = evidence.run_command(args, self.f.repo)
        self.assertEqual(status, 1)
        self.assertTrue(report['adopted'])
        self.assertTrue(report['changed'])
        self.assertEqual(report['manifest_sha256'], load(self.root)[1])
        self.assertIn('cleanup_error', report)
        self.assertEqual(len(load(self.root)[0]['items'][0]['spec_reviews']), 1)

    def test_cli_publication_cleanup_failure_and_retry(self):
        import task
        bundle = self.package()
        raw = bundle.read_bytes()
        original_manifest = self.path.read_bytes()
        argv = ['--repo', str(self.f.repo), 'import-evidence', str(self.root), '--bundle', str(bundle),
                '--adopt', '--expect-sha256', load(self.root)[1]]
        original_unlink = Path.unlink
        def fail_temp(path, *args, **kwargs):
            if path.name.startswith('.import-'):
                raise PermissionError('injected temporary cleanup failure')
            return original_unlink(path, *args, **kwargs)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('pathlib.Path.unlink', new=fail_temp), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = task.main(argv)
        self.assertEqual(status, 1)
        result = json.loads(stdout.getvalue())
        self.assertFalse(result['adopted'])
        self.assertIn('injected temporary cleanup failure', result['cleanup_error'])
        archived = Path(result['bundle'])
        temporary = Path(result['retained_temporary'])
        self.assertEqual(archived.read_bytes(), raw)
        self.assertEqual(temporary.read_bytes(), raw)
        self.assertEqual(result['sha256'], evidence.digest(raw))
        self.assertEqual(self.path.read_bytes(), original_manifest)
        self.assertEqual(stderr.getvalue(), '')
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = task.main(argv)
        self.assertEqual(status, 0, stderr.getvalue())
        self.assertTrue(json.loads(stdout.getvalue())['adopted'])
        self.assertEqual(archived.read_bytes(), raw)
        original_unlink(temporary)

    def test_cli_prepublication_failure_preserves_original_error(self):
        import task
        bundle = self.package()
        original_manifest = self.path.read_bytes()
        argv = ['--repo', str(self.f.repo), 'import-evidence', str(self.root), '--bundle', str(bundle),
                '--adopt', '--expect-sha256', load(self.root)[1]]
        original_unlink = Path.unlink
        def fail_temp(path, *args, **kwargs):
            if path.name.startswith('.import-'):
                raise PermissionError('injected cleanup failure')
            return original_unlink(path, *args, **kwargs)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch('task_support.evidence.os.link', side_effect=OSError('injected publication failure')), \
             patch('pathlib.Path.unlink', new=fail_temp), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = task.main(argv)
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('injected publication failure', stderr.getvalue())
        self.assertEqual(self.path.read_bytes(), original_manifest)
        directory = self.root / 'evidence'
        self.assertEqual(list(directory.glob('*.zip')), [])
        retained = list(directory.glob('.import-*'))
        self.assertEqual(len(retained), 1)
        original_unlink(retained[0])

    def test_inspect_selected_text_payload_is_read_only(self):
        self.report.write_bytes('Review: approved.\nПривет!\n'.encode('utf-8'))
        bundle = self.package()
        def tree():
            return {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        before = tree()
        default = self.cli('inspect-evidence', '--bundle', bundle)
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertNotIn('text_payload', json.loads(default.stdout))
        selected = self.cli('inspect-evidence', '--bundle', bundle, '--text-payload', 'report.bin')
        self.assertEqual(selected.returncode, 0, selected.stderr)
        result = json.loads(selected.stdout)
        self.assertEqual(result['text_payload'], {'path': 'report.bin', 'text': 'Review: approved.\nПривет!\n'})
        self.assertEqual(result['sha256'], evidence.digest(bundle.read_bytes()))
        self.assertEqual(result['metadata']['files'][0]['path'], 'report.bin')
        missing = self.cli('inspect-evidence', '--bundle', bundle, '--text-payload', '../report.bin')
        self.assertEqual(missing.returncode, 1)
        self.assertIn('does not exist', missing.stderr)
        self.assertEqual(tree(), before)
        for raw in (b'not utf8: \xff', b'binary\x00data'):
            self.report.write_bytes(raw)
            binary = self.package()
            before = tree()
            result = self.cli('inspect-evidence', '--bundle', binary, '--text-payload', 'report.bin')
            self.assertEqual(result.returncode, 1)
            self.assertIn('payload', result.stderr)
            self.assertEqual(result.stdout, '')
            self.assertEqual(tree(), before)

    def test_failed_check_replaces_pass(self):
        context = self.context()
        check_id = next(iter(next(iter(load(self.root)[0]['items'][0]['verification'].values()))))
        for outcome, exit_code in [('passed', 0), ('failed', 1)]:
            path = self.root / (outcome + '.zip')
            meta = {'format_version': 1, 'kind': 'check', 'before': context, 'after': context,
                    'record': {'id': check_id, 'command': ['example'], 'exit_code': exit_code, 'outcome': outcome},
                    'execution': {'cwd': str(self.f.repo), 'started_at': 'start', 'finished_at': 'end', 'timeout_seconds': 1, 'reason': 'completed', 'inputs_stable': True}}
            bundles.write_bundle(path, meta, {'stdout.bin': b'log', 'stderr.bin': b''})
            result = self.adopt(path)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(load(self.root)[0]['items'][0]['checks'][0]['outcome'], 'failed')
