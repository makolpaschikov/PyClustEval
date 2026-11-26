"""End-to-end isolated CLI checks for worker execution."""
import json
import subprocess
import tempfile
import sys
from pathlib import Path
import test_task
import unittest
from unittest.mock import patch
from task_support.bundles import read_bundle

CLI=Path(__file__).resolve().parents[2]/'harness/scripts/task/task.py'

class ExecutionTests(unittest.TestCase):
    git = test_task.TaskTests.git
    init = test_task.TaskTests.init
    fill = test_task.TaskTests.fill
    save = test_task.TaskTests.save
    tearDown = test_task.TaskTests.tearDown
    def setUp(self):
        self.fixture_root=Path(__file__).resolve().parents[2]/'.agent-work/tasks/harness-task-automation/m2/fixtures'
        self.fixture_root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=self.fixture_root)
        self.repo=Path(self.temp.name).resolve()
        self.git('init','-q','-b','test-main')
        (self.repo/'.gitignore').write_text('/.agent-work/tasks/\n',encoding='utf-8')
        (self.repo/'source.py').write_text('VALUE = 1\n',encoding='utf-8')
        self.git('add','.gitignore','source.py')
        self.directory=self.repo/'.agent-work/tasks/example'
        m=self.init(); self.fill(m,'TASK-001'); self.save(m)
    def runcheck(self, name, argv, check='CHECK-001', timeout='5'):
        output=self.directory/name
        p=subprocess.run([sys.executable,'-B',str(CLI),'--repo',str(self.repo),'run-check',str(self.directory),'--id','TASK-001','--check-id',check,'--source-repo',str(self.repo),'--output',str(output),'--timeout',timeout,'--',*argv],capture_output=True,text=True)
        return p, output
    def test_execution_outcomes_and_raw_bytes(self):
        for name,code,expected in [('ok',0,'passed'),('bad',7,'failed')]:
            p,out=self.runcheck(name,[sys.executable,'-c',f'import sys;sys.stdout.buffer.write(b"hello\\x00");sys.exit({code})'])
            self.assertEqual(p.returncode,0 if code==0 else 1,p.stderr)
            m,files=read_bundle(out); self.assertEqual(m['record']['outcome'],expected); self.assertEqual(files['stdout.bin'],b'hello\x00')
        p,out=self.runcheck('missing',['no-such-executable-743873'])
        self.assertEqual(p.returncode,1); self.assertEqual(read_bundle(out)[0]['execution']['reason'],'launch_error')
        p,out=self.runcheck('timeout',[sys.executable,'-c','import time;time.sleep(20)'],timeout='.2')
        self.assertEqual(p.returncode,1); self.assertEqual(read_bundle(out)[0]['execution']['reason'],'timeout')
    def test_drift_and_planned_and_overwrite(self):
        p,out=self.runcheck('drift',[sys.executable,'-c','from pathlib import Path;Path("source.py").write_text("changed")'])
        self.assertEqual(p.returncode,1); self.assertEqual(read_bundle(out)[0]['execution']['reason'],'input_drift')
        p,_=self.runcheck('drift',[sys.executable,'-c','pass']); self.assertNotEqual(p.returncode,0)
        p,out=self.runcheck('unplanned',[sys.executable,'-c','pass'],check='CHECK-OTHER'); self.assertNotEqual(p.returncode,0); self.assertFalse(out.exists())
    def test_output_limit(self):
        p,out=self.runcheck('large',[sys.executable,'-c','import sys;sys.stdout.buffer.write(b"x"*9000000)'])
        self.assertEqual(p.returncode,1,p.stderr); m,files=read_bundle(out)
        self.assertEqual(m['execution']['reason'],'output_limit'); self.assertEqual(len(files['stdout.bin']),8*1024*1024)


    def test_spec_drift_and_retry(self):
        target=self.directory/'TASK-001.md'
        # Use the declared contract, not a guessed template filename.
        m=json.loads((self.directory/'task.json').read_text()); target=self.directory/m['items'][0]['document']
        p,out=self.runcheck('contract-drift',[sys.executable,'-c',f'from pathlib import Path; p=Path({str(target)!r}); p.write_text(p.read_text()+"\\nChanged\\n")'])
        self.assertEqual(p.returncode,1,p.stderr); self.assertEqual(read_bundle(out)[0]['execution']['reason'],'input_drift')
        p,out=self.runcheck('retry',[sys.executable,'-c','print("ok")']); self.assertEqual(p.returncode,0,p.stderr)
    def test_outside_output_and_timeout_validation(self):
        p,_=self.runcheck('../outside.zip',[sys.executable,'-c','pass'],timeout='0')
        self.assertEqual(p.returncode,1); self.assertIn('Timeout',p.stderr)
        p,_=self.runcheck('../../../escape.zip',[sys.executable,'-c','pass'])
        self.assertEqual(p.returncode,1); self.assertIn('workspace',p.stderr)

    def test_application_record_required(self):
        manifest=json.loads((self.directory/'task.json').read_text()); manifest['scope']='application'; self.save(manifest)
        p,out=self.runcheck('auth',[sys.executable,'-c','pass']); self.assertEqual(p.returncode,1); self.assertIn('authorization',p.stderr); self.assertFalse(out.exists())
        manifest['application_authorization']={'source':'fixture only','scope':'fixture'}; self.save(manifest)
        p,out=self.runcheck('auth',[sys.executable,'-c','pass']); self.assertEqual(p.returncode,0,p.stderr)


    def test_resolved_output_escape(self):
        from task_support.execution import _safe_output
        from task_support.formats import TaskError
        output=self.directory/'escape.zip'
        original=Path.resolve
        def fake_resolve(path, *args, **kwargs):
            if path == output: return self.repo/'outside.zip'
            return original(path,*args,**kwargs)
        with patch.object(Path,'resolve',fake_resolve):
            with self.assertRaisesRegex(TaskError,'resolves outside'):
                _safe_output(self.repo,output)

    def test_child_arguments_are_not_helper_options(self):
        code='import sys;print("|".join(sys.argv[1:]))'
        p,out=self.runcheck('argv',[sys.executable,'-c',code,'--id','foreign','--timeout','99'])
        self.assertEqual(p.returncode,0,p.stderr)
        meta,payloads=read_bundle(out)
        self.assertEqual(meta['record']['command'][-4:],['--id','foreign','--timeout','99'])
        self.assertEqual(payloads['stdout.bin'].strip(),b'--id|foreign|--timeout|99')
    def test_legacy_repo_name_and_option_separator(self):
        old_repo, old_directory = self.repo, self.directory
        with tempfile.TemporaryDirectory(dir=self.fixture_root) as parent:
            self.repo = Path(parent) / 'run-check'
            self.repo.mkdir()
            self.directory = self.repo / '.agent-work/tasks/example'
            try:
                self.git('init', '-q', '-b', 'test-main')
                (self.repo / '.gitignore').write_text('/.agent-work/tasks/\n', encoding='utf-8')
                (self.repo / 'source.py').write_text('VALUE = 1\n', encoding='utf-8')
                self.git('add', '.gitignore', 'source.py')
                manifest = self.init()
                self.fill(manifest, 'TASK-001')
                self.save(manifest)
                p = subprocess.run(
                    [sys.executable, '-B', str(CLI), '--repo', 'run-check',
                     'lint', '--', '.agent-work/tasks/example'],
                    cwd=parent, capture_output=True, text=True,
                )
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(json.loads(p.stdout)['command'], 'lint')
            finally:
                self.repo, self.directory = old_repo, old_directory
