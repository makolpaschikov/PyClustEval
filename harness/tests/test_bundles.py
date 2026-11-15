"""Transport validation on real archives."""
import copy
import json
import tempfile
from pathlib import Path
import unittest
import zipfile
import test_task
from task_support.bundles import read_bundle, write_bundle, contexts_match, MAX_FILE_SIZE
from task_support.formats import TaskError

class BundleTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[2]/'.agent-work/tasks/harness-task-automation/m2'
        root.mkdir(parents=True,exist_ok=True); self.temp=tempfile.TemporaryDirectory(dir=root); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        self.ctx={'format_version':1,'task_root':'TASK','item_id':'TASK','spec_sha256':'a'*64,'source_sha256':'b'*64,'stage':None,'scope_sha256':None,'origin':{'repository':'repo','branch':'main','head':None}}
        self.meta={'format_version':1,'kind':'code_review','before':self.ctx,'after':self.ctx,'record':{'reviewer':'independent','verdict':'accepted'},'execution':None,'files':[]}
    def test_roundtrip_and_no_overwrite(self):
        out=self.root/'b.zip'; write_bundle(out,self.meta,{'report.bin':b'abc'})
        self.assertEqual(read_bundle(out)[1],{'report.bin':b'abc'})
        with self.assertRaises(FileExistsError): write_bundle(out,self.meta,{'report.bin':b'new'})
        other=copy.deepcopy(self.ctx); other['origin']['head']='a'*40
        self.assertTrue(contexts_match(self.ctx,other,execution=True)); other['origin']['branch']='other'
        self.assertTrue(contexts_match(self.ctx,other)); self.assertFalse(contexts_match(self.ctx,other,execution=True))
    def test_bad_payloads_and_zip(self):
        for name,data in [('../evil',b'x'),('a\\evil',b'x'),('big',b'x'*(MAX_FILE_SIZE+1))]:
            with self.assertRaises(TaskError): write_bundle(self.root/'bad',self.meta,{name:data})
        path=self.root/'bad.zip'; path.write_bytes(b'not zip')
        with self.assertRaises(TaskError): read_bundle(path)
        path.unlink(); write_bundle(path,self.meta,{'report.bin':b'ok'})
        with zipfile.ZipFile(path,'a') as z: z.writestr('report.bin',b'evil')
        with self.assertRaises(TaskError): read_bundle(path)

    def test_required_payloads_and_corruption(self):
        for payloads in ({}, {'report.bin':b''}):
            with self.assertRaises(TaskError): write_bundle(self.root/'empty',self.meta,payloads)
        check=copy.deepcopy(self.meta); check.update(kind='check', record={'id':'CHECK','command':['x'],'exit_code':0,'outcome':'passed'}, execution={'cwd':'repo','started_at':'start','finished_at':'end','timeout_seconds':1,'reason':'completed','inputs_stable':True})
        with self.assertRaises(TaskError): write_bundle(self.root/'streams',check,{'stdout.bin':b''})
        check['execution']['reason']='output_limit'
        with self.assertRaises(TaskError): write_bundle(self.root/'pass-limit',check,{'stdout.bin':b'','stderr.bin':b''})
        path=self.root/'hash.zip'; write_bundle(path,self.meta,{'report.bin':b'original'})
        with zipfile.ZipFile(path) as z:
            manifest=z.read('bundle.json')
        path.unlink()
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('bundle.json',manifest); z.writestr('report.bin',b'tampered')
        with self.assertRaises(TaskError): read_bundle(path)
        path.write_bytes(path.read_bytes()[:-8])
        with self.assertRaises(TaskError): read_bundle(path)
