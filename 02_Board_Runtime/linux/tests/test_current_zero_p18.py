"""Synthetic unit packets for physical-zero contracts; never hardware evidence."""
import copy
import csv
import http.client
import json
import re
import shutil
import subprocess
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from commissioning.fit import initialize,fit_line,SOURCE
from commissioning.measure import record_current_zero,record_point
from commissioning.workbench import Workbench
from commissioning.deploy import atomic
from cabinet.web import server

class Clock:
    def __init__(self,path,change=None,duplicate=False):
        self.path=path;self.now=1000.;self.steps=0;self.change=change;self.duplicate=duplicate
        raw=[0]*32;raw[0]=0x810;raw[1]=100000;raw[22]=3000
        self.document=dict(observation=dict(link='ONLINE',received_at=self.now,boot='UNIT/aabbccdd/fixture-session/1',
            frame=dict(state='EMPTY',test=False),status=dict(uptime_ms=100000,configuration_id=0,
            input_validity={'adc':True},hard_inhibit=True,applied_pwm_counts=0,requested_rpm=0,raw_words=raw)))
        self.write()
    def write(self):self.path.write_text(json.dumps(self.document),encoding='utf-8')
    def monotonic(self):return self.now
    def sleep(self,seconds):
        self.now+=seconds;self.steps+=1;o=self.document['observation'];s=o['status'];o['received_at']=self.now
        if not self.duplicate:s['uptime_ms']+=80;s['raw_words'][1]=s['uptime_ms']
        s['raw_words'][22]=3000+self.steps%3
        if self.change:self.change(self)
        self.write()

class CurrentZeroTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.inputs=self.root/'inputs';initialize(self.inputs,'UNIT');self.state=self.root/'state.json'
    def capture(self,clock,**changes):
        arguments=dict(seconds=1.,operator='现场确认人',load_path_open=True,sensor_chain_powered=True,state=self.state)
        arguments.update(changes)
        with patch('commissioning.measure.time.monotonic',clock.monotonic),patch('commissioning.measure.time.sleep',clock.sleep):
            return record_current_zero(self.inputs,**arguments)
    def test_confirmed_physical_zero_keeps_raw_evidence_without_claiming_instrument_or_gain(self):
        result=self.capture(Clock(self.state))
        self.assertEqual(result['reference_origin'],'USER_CONFIRMED_PHYSICAL_LOAD_DISCONNECTION')
        self.assertEqual((result['channel'],result['reference'],result['unit']),('current',0.,'A'))
        self.assertEqual(result['operator'],'现场确认人');self.assertEqual(result['source'],SOURCE)
        self.assertFalse(result['current_gain_calibrated']);self.assertFalse(result['formal_calibration_qualified'])
        self.assertFalse(result['software_controls_issued']);self.assertGreaterEqual(len(result['samples']),8)
        self.assertGreater(result['raw_mean'],3000)
        self.assertTrue(all(s['adc_valid'] and s['hard_inhibit'] and s['applied_pwm_counts']==0 and s['requested_rpm']==0 for s in result['samples']))
        stored=json.loads((self.inputs/'points'/(result['session_id']+'.json')).read_text(encoding='utf-8'))
        self.assertEqual(stored,result)
        with (self.inputs/'calibration.csv').open(encoding='utf-8') as f:rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['split'],'fit');self.assertEqual(float(rows[0]['reference']),0.)
        with self.assertRaisesRegex(ValueError,'3 reference levels'):fit_line(rows,'current','A',.1)
    def test_physical_flags_and_operator_must_be_explicit_before_reading(self):
        clock=Clock(self.state);before=(self.inputs/'calibration.csv').read_bytes()
        for change in (dict(load_path_open=False),dict(sensor_chain_powered=False),dict(load_path_open=1),
                       dict(sensor_chain_powered='true'),dict(operator=' '),dict(operator='name\n'),dict(seconds=float('nan'))):
            with self.subTest(change=change),self.assertRaises(ValueError),patch('commissioning.measure.observation',side_effect=AssertionError('Must reject before sensor access')):
                self.capture(clock,**change)
        self.assertEqual((self.inputs/'calibration.csv').read_bytes(),before)
    def test_active_output_missing_inhibit_or_adc_invalid_cannot_record_a_zero(self):
        changes=(lambda s:s.update(applied_pwm_counts=1),lambda s:s.update(requested_rpm=1200),
                 lambda s:s.update(hard_inhibit=False),lambda s:s['input_validity'].update(adc=False),
                 lambda s:s['raw_words'].__setitem__(7,1),lambda s:s['raw_words'].__setitem__(0,0x10))
        before=(self.inputs/'calibration.csv').read_bytes()
        for change in changes:
            with self.subTest(change=change):
                clock=Clock(self.state);change(clock.document['observation']['status']);clock.write()
                with self.assertRaises(ValueError):self.capture(clock)
                self.assertEqual((self.inputs/'calibration.csv').read_bytes(),before)
    def test_mid_capture_reboot_config_change_or_adc_loss_never_commits_partial_csv(self):
        before=(self.inputs/'calibration.csv').read_bytes()
        for fault in ('boot','config','adc','output','test'):
            def change(c):
                if c.steps!=4:return
                o=c.document['observation'];s=o['status']
                if fault=='boot':o['boot']='UNIT/aabbccdd/another-session/1'
                if fault=='config':s['configuration_id']=1;s['raw_words'][18]=1
                if fault=='adc':s['input_validity']['adc']=False
                if fault=='output':s['applied_pwm_counts']=10
                if fault=='test':o['frame']['test']=True
            with self.subTest(fault=fault),self.assertRaises(ValueError):self.capture(Clock(self.state,change))
            self.assertEqual((self.inputs/'calibration.csv').read_bytes(),before)
        self.assertFalse((self.inputs/'points').exists())
    def test_duplicate_status_is_not_eight_fresh_samples(self):
        before=(self.inputs/'calibration.csv').read_bytes()
        with self.assertRaisesRegex(ValueError,'Insufficient fresh'):self.capture(Clock(self.state,duplicate=True))
        self.assertEqual((self.inputs/'calibration.csv').read_bytes(),before)
    def test_runtime_learning_or_bench_guard_abort_keeps_csv_unchanged(self):
        before=(self.inputs/'calibration.csv').read_bytes();clock=Clock(self.state)
        def guard():
            if clock.steps>=4:raise ValueError('WAIT_FOR_NPU_LEARNING_OR_CANCEL_IT')
        with self.assertRaisesRegex(ValueError,'WAIT_FOR_NPU'):self.capture(clock,guard=guard)
        self.assertEqual((self.inputs/'calibration.csv').read_bytes(),before)
    def test_existing_external_reference_source_remains_explicit_instrument(self):
        clock=Clock(self.state)
        with patch('commissioning.measure.time.monotonic',clock.monotonic),patch('commissioning.measure.time.sleep',clock.sleep):
            result=record_point(self.inputs,'current',.7,'fit',1,self.state)
        self.assertEqual(result['reference_origin'],'USER_ENTERED_EXTERNAL_INSTRUMENT')
        self.assertEqual(result['reference'],.7);self.assertNotIn('physical_declaration',result)

class WorkbenchZeroTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.base=self.root/'base.json';self.base.write_text(json.dumps(dict(device_id='UNIT')),encoding='utf-8')
        self.state=self.root/'state.json';self.work=Workbench(self.root/'work',self.base,state_path=str(self.state))
    def body(self):return dict(revision=self.work.revision(),seconds=1,operator='Operator',load_path_open=True,sensor_chain_powered=True)
    def online(self):
        self.bench=dict(state='IDLE',controls_enabled=False)
        self.work.service=SimpleNamespace(bench=SimpleNamespace(snapshot=lambda record_limit=None:copy.deepcopy(self.bench)))
    def test_api_rejects_offline_and_cannot_override_zero_channel_reference_or_split(self):
        api=server('127.0.0.1',0,SimpleNamespace(workbench=self.work),token='unit-read',control_token='unit-control-'+32*'x')
        thread=threading.Thread(target=api.serve_forever,daemon=True);thread.start()
        try:
            for body in (self.body(),dict(self.body(),reference=1)):
                connection=http.client.HTTPConnection('127.0.0.1',api.server_address[1],timeout=3)
                connection.request('POST','/api/commissioning/current-zero',json.dumps(body),
                    {'Authorization':'Bearer unit-read','X-Cabinet-Control-Token':'unit-control-'+32*'x','Content-Type':'application/json'})
                response=connection.getresponse();data=response.read();connection.close()
                self.assertEqual(response.status,409)
            self.assertEqual(self.work.jobs,{})
        finally:api.shutdown();api.server_close();thread.join()
    def test_learning_active_or_bench_queued_refuses_zero_before_creating_job(self):
        self.online()
        self.work.service.mock=True
        with self.assertRaisesRegex(ValueError,'REAL_COLLECTOR'):self.work.action('current-zero',self.body())
        self.work.service.mock=False
        with patch.object(self.work.learning,'busy',return_value=True),self.assertRaisesRegex(ValueError,'NPU_LEARNING'):
            self.work.action('current-zero',self.body())
        self.bench['state']='QUEUED_NOT_APPLIED'
        with self.assertRaisesRegex(ValueError,'STOP_BENCH'):self.work.action('current-zero',self.body())
        self.assertEqual(self.work.jobs,{})
    def test_background_job_commits_zero_and_provenance_through_revision_checked_inputs(self):
        self.online();clock=Clock(self.state);before=self.work.revision()
        class InlineThread:
            def __init__(self,target,**unused):self.target=target
            def start(self):self.target()
        with patch('commissioning.workbench.threading.Thread',InlineThread),patch('commissioning.measure.time.monotonic',clock.monotonic),patch('commissioning.measure.time.sleep',clock.sleep):
            job=self.work.action('current-zero',self.body())
        self.assertEqual(job['state'],'COMPLETED');self.assertNotEqual(self.work.revision(),before)
        result=job['result'];self.assertFalse(result['current_gain_calibrated'])
        self.assertTrue((self.work.inputs/'points'/(result['session_id']+'.json')).exists())
    def run_zero_inline(self):
        clock=Clock(self.state)
        class InlineThread:
            def __init__(self,target,**unused):self.target=target
            def start(self):self.target()
        with patch('commissioning.workbench.threading.Thread',InlineThread),patch('commissioning.measure.time.monotonic',clock.monotonic),patch('commissioning.measure.time.sleep',clock.sleep):
            return self.work.action('current-zero',self.body())
    def test_evidence_write_or_readback_failure_does_not_commit_csv(self):
        self.online();before=(self.work.inputs/'calibration.csv').read_bytes();revision=self.work.revision()
        target=self.work.inputs/'points';read_bytes=Path.read_bytes
        for failure in ('write','readback'):
            def injected_atomic(path,data):
                if failure=='write' and Path(path).parent==target:raise OSError('injected evidence write failure')
                return atomic(path,data)
            def injected_read(path):
                if failure=='readback' and path.parent==target:raise OSError('injected evidence readback failure')
                return read_bytes(path)
            with self.subTest(failure=failure),patch('commissioning.workbench.atomic',side_effect=injected_atomic),patch.object(Path,'read_bytes',injected_read):
                job=self.run_zero_inline()
            self.assertEqual(job['state'],'FAILED');self.assertIn('evidence '+failure,job['error'])
            self.assertEqual((self.work.inputs/'calibration.csv').read_bytes(),before)
            self.assertEqual(self.work.revision(),revision)
    def test_csv_failure_leaves_only_uncommitted_origin_evidence(self):
        self.online();csv_path=self.work.inputs/'calibration.csv';before=csv_path.read_bytes();revision=self.work.revision()
        def injected_atomic(path,data):
            if Path(path)==csv_path:raise OSError('injected CSV commit failure')
            return atomic(path,data)
        with patch('commissioning.workbench.atomic',side_effect=injected_atomic):job=self.run_zero_inline()
        self.assertEqual(job['state'],'FAILED');self.assertIn('CSV commit failure',job['error'])
        self.assertEqual(csv_path.read_bytes(),before);self.assertEqual(self.work.revision(),revision)
        evidence=list((self.work.inputs/'points').glob('*.json'));self.assertEqual(len(evidence),1)
        self.assertEqual(json.loads(evidence[0].read_text(encoding='utf-8'))['reference_origin'],'USER_CONFIRMED_PHYSICAL_LOAD_DISCONNECTION')
    def test_point_copy_refuses_different_existing_bytes_and_preserves_history(self):
        identity='b09f966c-67bb-4b30-b21c-275ac07b36ae';source=self.root/'source';source.mkdir()
        result=dict(session_id=identity,reference_origin='USER_CONFIRMED_PHYSICAL_LOAD_DISCONNECTION')
        data=json.dumps(result).encode();(source/(identity+'.json')).write_bytes(data)
        target=self.work.inputs/'points';target.mkdir();(target/'history.json').write_bytes(b'history must remain')
        destination=target/(identity+'.json');destination.write_bytes(b'original conflicting evidence')
        with self.assertRaisesRegex(ValueError,'refusing overwrite'):self.work._copy_point(source,result)
        self.assertEqual(destination.read_bytes(),b'original conflicting evidence')
        self.assertEqual((target/'history.json').read_bytes(),b'history must remain')
        destination.write_bytes(data);self.work._copy_point(source,result)
        self.assertEqual(destination.read_bytes(),data)
    def test_zero_collection_blocks_new_learning_and_bench_start(self):
        self.online();self.work.jobs['fixture']=dict(state='RUNNING',operation='current-zero')
        for action,body in (('bench-start',{}),('npu-start',{}),('labeled-start',{})):
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'WAIT_FOR_CURRENT_ZERO'):
                self.work.action(action,body)

class CurrentZeroPageTests(unittest.TestCase):
    def test_live_button_is_disabled_for_offline_revision_bench_or_learning_conflicts(self):
        node=shutil.which('node')
        if node is None:self.skipTest('Node is required for the browser guard unit test')
        html=(Path(__file__).resolve().parents[1]/'static/commissioning.html').read_text(encoding='utf-8')
        script=html.split('<script>',1)[1].split('</script>',1)[0]
        syntax=subprocess.run([node,'--check'],input=script,stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',timeout=10)
        self.assertEqual(syntax.returncode,0,syntax.stderr)
        helper=re.search(r'function currentZeroBlocked\(s\)\{.*?\}\n',script).group(0)
        checks='''
const assert=require('assert');let revision='v1';
const healthy={mode:'BOARD_COLLECTOR',revision:'v1',live:{link:'ONLINE'},bench:{state:'IDLE',controls_enabled:false},jobs:[],npu_learning:{jobs:[]},labeled_learning:{jobs:[]},control:{jobs:[]}};
assert.strictEqual(Boolean(currentZeroBlocked(healthy)),false);
for(const change of [{mode:'LOCAL_FILES_ONLY'},{live:{link:'OFFLINE'}},{revision:'v2'},{bench:{state:'QUEUED_NOT_APPLIED'}},{jobs:[{state:'RUNNING'}]},{npu_learning:{jobs:[{state:'CAPTURING_TRAIN'}]}},{labeled_learning:{jobs:[{state:'TRAINING'}]}},{control:{jobs:[{state:'QUEUED'}]}}])assert.strictEqual(Boolean(currentZeroBlocked({...healthy,...change})),true);
assert.strictEqual(Boolean(currentZeroBlocked({...healthy,labeled_learning:{jobs:[{state:'COLLECTED_WAITING_DATA'}]}})),false);
'''
        result=subprocess.run([node,'-e',helper+checks],stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        expired=script.split('function expireLive()',1)[1].split('\n',1)[0]
        self.assertIn("'current-zero'",expired)
        refresh=script.split('async function refresh',1)[1].split('\n',1)[0]
        self.assertIn("'current-zero'",refresh)
        self.assertIn('拔掉 PWM 线不算断电',html)
        self.assertIn("load_path_open=$('current-zero-load-open').checked",script)
        self.assertIn("sensor_chain_powered=$('current-zero-sensor-powered').checked",script)

if __name__=='__main__':unittest.main()
