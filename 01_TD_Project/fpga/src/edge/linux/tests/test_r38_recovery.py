import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from cabinet.capabilities import implementation_scope
from cabinet.parameter_rpc import ParameterRPC
from cabinet.store import Store
from cabinet.uplink import Uplink
from train_fault_grade import train
import test_r36_advanced as fixtures

ROOT=Path(__file__).resolve().parents[2]


class ImplementationScopeTests(unittest.TestCase):
    def test_scope_cannot_be_promoted_by_user_claims(self):
        result=implementation_scope();self.assertEqual(result['implementation']['independent_actuators'],1)
        self.assertFalse(result['qualification_granted'])
        for name in ['npu_multitask_deployed','multiple_independent_control_loops','advanced_all_accepted','board_accepted']:
            with self.subTest(name=name),self.assertRaises(ValueError):implementation_scope({name:True})
        with self.assertRaises(ValueError):implementation_scope(dict(independent_actuators=2))
        with self.assertRaises(ValueError):implementation_scope(dict(independent_actuators=True))

    def test_pinned_grade_onnx_matches_ps_but_never_claims_npu(self):
        spec=importlib.util.spec_from_file_location('grade_export',ROOT/'tools/export_grade_onnx.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        model,unused=train(fixtures.grade_dataset())
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'model.json';path.write_text(json.dumps(model));pin=hashlib.sha256(path.read_bytes()).hexdigest()
            result=module.export(path,pin,Path(folder)/'export')
            self.assertEqual(result['cases'],10076);self.assertGreater(result['decisive_cases'],0)
            self.assertFalse(result['npu_executed']);self.assertFalse(result['qualification_granted']);self.assertFalse(result['production_runtime_modified'])
            destination=os.environ.get('CABINET_GRADE_EXPORT_REPORT')
            if destination:Path(destination).write_text(json.dumps(result,indent=2)+'\n')
            with self.assertRaises(ValueError):module.export(path,'0'*64,Path(folder)/'bad')


class RPCRecoveryTests(unittest.TestCase):
    def test_killed_owner_stale_socket_is_recovered_without_stealing_live_owner(self):
        with tempfile.TemporaryDirectory(prefix='cb38-',dir='/tmp') as folder:
            path=Path(folder)/'operator.sock'
            code='from cabinet.parameter_rpc import ParameterRPC;import time;rpc=ParameterRPC(None,'+repr(str(path))+');print("READY",flush=True);time.sleep(30)'
            child=subprocess.Popen([sys.executable,'-B','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(),'READY')
                with self.assertRaises(ValueError):ParameterRPC(None,path)
                child.kill();child.wait(timeout=5);self.assertTrue(path.exists())
                rpc=ParameterRPC(None,path)
                try:
                    with self.assertRaises(ValueError):ParameterRPC(None,path)
                finally:rpc.close()
                self.assertFalse(path.exists())
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=5)
                child.stdout.close();child.stderr.close()

    def test_unlocked_but_live_foreign_listener_is_never_unlinked(self):
        with tempfile.TemporaryDirectory(prefix='cb38-',dir='/tmp') as folder:
            path=Path(folder)/'operator.sock'
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
                listener.bind(str(path));path.chmod(0o600);listener.listen(1)
                identity=path.stat().st_ino
                with self.assertRaises(ValueError):ParameterRPC(None,path)
                self.assertEqual(path.stat().st_ino,identity)

    def test_ownership_lock_symlink_and_untrusted_stale_file_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix='cb38-',dir='/tmp') as folder:
            path=Path(folder)/'operator.sock';lock=Path(str(path)+'.owner.lock');victim=Path(folder)/'protected';victim.write_text('KEEP')
            lock.symlink_to(victim)
            with self.assertRaises(OSError):ParameterRPC(None,path)
            self.assertEqual(victim.read_text(),'KEEP');lock.unlink();path.write_text('NOT_A_SOCKET')
            with self.assertRaises(ValueError):ParameterRPC(None,path)
            self.assertEqual(path.read_text(),'NOT_A_SOCKET')


class DatabaseRecoveryTests(unittest.TestCase):
    def test_busy_writer_does_not_partially_record_event_and_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'events.db';store=Store(path);other=sqlite3.connect(str(path))
            try:
                store.db.execute('PRAGMA busy_timeout=20');other.execute('BEGIN IMMEDIATE')
                with self.assertRaises(sqlite3.OperationalError):store.event(fixtures.event())
                self.assertEqual(store.events(),[]);self.assertEqual(store.pending(),[])
                other.rollback();self.assertTrue(store.event(fixtures.event()))
            finally:other.close();store.close()
            store=Store(path)
            try:self.assertEqual(len(store.events()),1);self.assertEqual(len(store.pending()),1)
            finally:store.close()

    def test_real_sqlite_full_rolls_back_without_deleting_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'events.db';store=Store(path)
            try:
                store.snapshot('unit',dict(keep='OLD'));pages=store.db.execute('PRAGMA page_count').fetchone()[0]
                store.db.execute('PRAGMA max_page_count='+str(pages))
                with self.assertRaises(sqlite3.OperationalError):store.snapshot('unit',dict(large='X'*1048576))
                self.assertEqual(store.get_snapshot('unit'),dict(keep='OLD'))
            finally:store.close()
            store=Store(path)
            try:self.assertEqual(store.get_snapshot('unit'),dict(keep='OLD'));self.assertEqual(store.db.execute('PRAGMA integrity_check').fetchone(),('ok',))
            finally:store.close()

    def test_process_death_between_event_and_outbox_insert_is_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'events.db';store=Store(path);store.close()
            code='import os;from cabinet.store import Store;store=Store('+repr(str(path))+');store.db.set_trace_callback(lambda statement:os._exit(92) if statement.startswith("INSERT OR IGNORE INTO outbox") else None);store.event('+repr(fixtures.event())+')'
            result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,92,result.stderr);store=Store(path)
            try:self.assertEqual(store.events(),[]);self.assertEqual(store.pending(),[])
            finally:store.close()

    def test_outbox_survives_restart_and_false_receipt_cannot_delete_it(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'events.db';store=Store(path);store.event(fixtures.event());store.close();store=Store(path)
            try:
                queued=store.pending()[0];uploader=Uplink(dict(url='http://127.0.0.1:9/events',loopback_test=True),store)
                class Reply:
                    status=200
                    def __init__(self,document):
                        from email.message import Message
                        self.headers=Message();self.headers['Content-Type']='application/json';self.document=document
                    def __enter__(self):return self
                    def __exit__(self,*arguments):pass
                    def read(self,limit):return json.dumps(self.document).encode()
                wrong=dict(accepted=True,event_id='wrong',event_revision=queued['revision'])
                with patch.object(uploader.opener,'open',return_value=Reply(wrong)):self.assertEqual(uploader.once(),0)
                self.assertEqual(store.db.execute('SELECT count(*) FROM outbox').fetchone()[0],1)
                correct=dict(wrong,event_id=queued['event_id'])
                store.reset_retry_clock()
                with patch.object(uploader.opener,'open',return_value=Reply(correct)):
                    self.assertEqual(uploader.once(),1)
                self.assertEqual(store.pending(),[])
            finally:store.close()


if __name__=='__main__':unittest.main()
