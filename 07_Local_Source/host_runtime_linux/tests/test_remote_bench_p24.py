"""Remote bench authorization boundaries; fixtures never operate hardware."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch
import hashlib

from commissioning.bench import BenchController,plan
from commissioning.bench_admission import AUTHORIZATION
from commissioning.workbench import Workbench
from test_bench_guard_p18 import IO,status,prepared,service


class RemoteBenchGuardTests(unittest.TestCase):
    def setUp(self):
        self.s=service();self.io=IO();self.st=status()
        self.st['raw_words'][0]&=~0x8000
        self.b=BenchController(self.s,admission_check=lambda boot:{'fixture':True})
        self.ctrl=SimpleNamespace(io=self.io)

    def queue(self):
        with patch('commissioning.bench.time.monotonic',return_value=100):
            self.b.request_start(prepared(),self.s.boot)

    def test_explicit_remote_bench_arms_without_fabricating_key_permission(self):
        self.queue();self.b.poll(self.ctrl,self.st,100)
        self.assertTrue(self.b.snapshot()['controls_enabled'])
        self.assertEqual(self.b.snapshot()['authorization'],AUTHORIZATION)
        self.assertFalse(self.b.snapshot()['local_key_required'])
        self.assertIn((0x928,0x41524d32),self.io.writes)
        self.assertFalse(self.st['raw_words'][0]&0x8000)
        self.assertTrue(all(0x900<=a<0x940 for a,v in self.io.writes))

    def test_old_abi_cannot_receive_new_remote_commands(self):
        self.io.words[0x904]=0x10000
        self.queue();self.b.poll(self.ctrl,self.st,100)
        self.assertEqual(self.b.snapshot()['state'],'REJECTED')
        self.assertEqual(self.io.writes,[])

    def test_remote_authorization_does_not_override_configuration_or_faults(self):
        for field,value in [('configured',True),('latched',['OVERCURRENT']),('applied_pwm_counts',1)]:
            with self.subTest(field=field):
                self.setUp();self.st[field]=value;self.queue();self.b.poll(self.ctrl,self.st,100)
                self.assertEqual(self.b.snapshot()['state'],'REJECTED')
                self.assertEqual(self.io.writes,[])

    def test_collector_reconnect_revokes_queued_request_before_writes(self):
        self.queue();self.s.connection_epoch+=1;self.b.poll(self.ctrl,self.st,100)
        self.assertEqual(self.b.snapshot()['state'],'REJECTED')
        self.assertEqual(self.io.writes,[])

    def test_learning_job_created_after_queue_is_rejected_before_arm(self):
        self.queue();self.s.workbench=SimpleNamespace(learning=SimpleNamespace(busy=lambda:True))
        self.b.poll(self.ctrl,self.st,100)
        self.assertEqual(self.b.snapshot()['state'],'REJECTED')
        self.assertEqual(self.io.writes,[])

    def test_learning_job_created_during_trial_stops_before_duty_renewal(self):
        self.queue();self.b.poll(self.ctrl,self.st,100);self.io.writes=[]
        self.s.workbench=SimpleNamespace(learning=SimpleNamespace(busy=lambda:True))
        self.b.poll(self.ctrl,self.st,100.1)
        self.assertEqual(self.io.writes,[(0x930,0)])
        self.assertEqual(self.b.snapshot()['reason'],'LEARNING_TRANSACTION_STARTED')


class RemotePreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);base=root/'base.json';base.write_text(json.dumps({'device_id':'UNIT'}))
        self.w=Workbench(root/'work',base)
        self.s=service();self.calls=[]
        self.s.bench=SimpleNamespace(request_start=lambda *args:self.calls.append(args) or {'state':'QUEUED_NOT_APPLIED'})
        self.w.service=self.s
        self.w.learning=SimpleNamespace(busy=lambda:False)
        self.w.labeled_learning=SimpleNamespace(busy=lambda:False)
        p=prepared();self.w.preview=dict(id='test-preview',revision=self.w.revision(),expires=time.monotonic()+30,
            boot=self.s.boot,collector_boot=self.s.boot+'/'+self.s.collector_session+'/1',prepared=p)
        self.request=dict(preview_id='test-preview',start_controlled_trial=True,authorization=AUTHORIZATION)

    def test_legacy_or_wrong_scope_request_has_no_actuator_submission(self):
        for mode in ('missing','wrong','false'):
            with self.subTest(mode=mode):
                request=copy.deepcopy(self.request)
                if mode=='missing':request.pop('authorization')
                elif mode=='wrong':request['authorization']='FORMAL_CONTROL'
                else:request['start_controlled_trial']=False
                with self.assertRaisesRegex(ValueError,'authorization'):self.w.bench_start(request)
                self.assertEqual(self.calls,[])

    def test_fresh_scoped_confirmation_is_consumed_once(self):
        self.assertEqual(self.w.bench_start(self.request)['state'],'QUEUED_NOT_APPLIED')
        with self.assertRaises(ValueError):self.w.bench_start(self.request)
        self.assertEqual(len(self.calls),1)

    def test_preview_requires_current_admission_before_enabling_start(self):
        path=self.w.inputs/'calibration.csv'
        path.write_text(path.read_text()+'current,train,3000,0,A,fixture,REAL_USER_MEASUREMENTS\n')
        document=prepared()['document']
        document['profile']['reference_evidence_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        (self.w.inputs/'bench.json').write_text(json.dumps(document))
        with patch('commissioning.workbench.require_admission',side_effect=ValueError('OLD_ABI')):
            result=self.w.bench_preview({'revision':self.w.revision()})
        self.assertFalse(result['live_start_available'])
        self.assertEqual(result['start_unavailable_reason'],'REMOTE_PWM_FIRMWARE_NOT_ADMITTED')
        with patch('commissioning.workbench.require_admission',return_value={'fixture':True}):
            result=self.w.bench_preview({'revision':self.w.revision()})
        self.assertTrue(result['live_start_available'])
        self.assertIsNone(result['start_unavailable_reason'])

    def test_reconnected_collector_requires_new_preview(self):
        self.s.connection_epoch+=1
        with self.assertRaisesRegex(ValueError,'COLLECTOR_CHANGED'):self.w.bench_start(self.request)
        self.assertEqual(self.calls,[])

    def test_expired_changed_or_learning_context_cannot_start(self):
        for mode in ('expired','revision','normal_learning','labeled_learning'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode=='expired':self.w.preview['expires']=time.monotonic()-1
                elif mode=='revision':self.w.preview['revision']='changed'
                elif mode=='normal_learning':self.w.learning.busy=lambda:True
                else:self.w.labeled_learning.busy=lambda:True
                with self.assertRaises(ValueError):self.w.bench_start(self.request)
                self.assertEqual(self.calls,[])

    def test_queued_active_or_unconfirmed_bench_cannot_dispatch_either_learning(self):
        for state in ('QUEUED_NOT_APPLIED','ACTIVE_BENCH_NOT_CLOSED_LOOP','OUTPUT_STOP_UNCONFIRMED','UNKNOWN'):
            for action in ('npu-start','labeled-start'):
                with self.subTest(state=state,action=action):
                    self.s.bench.snapshot=lambda record_limit=None:dict(state=state,controls_enabled=False)
                    self.w.learning.start=lambda body:self.calls.append('normal')
                    self.w.labeled_learning.start=lambda body:self.calls.append('labeled')
                    with self.assertRaisesRegex(ValueError,'STOP_BENCH'):self.w.action(action,{})
                    self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main()
