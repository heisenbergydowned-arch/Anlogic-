import copy
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cabinet.journal_crypto import create_key
from cabinet.openssl_aead import OpenSSLAESGCM,cipher_provider
from cabinet.parameter_rpc import ParameterRPC,context_token
from cabinet.service import Service
from cabinet.policy import TemperatureLoop
from cabinet.mock import MockController
from cabinet.store import Store,EventTracker
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from test_chain import CONFIG
import test_r36_advanced as advanced_fixtures

ROOT=Path(__file__).resolve().parents[2]


def native_library():
    value=os.environ.get('CABINET_TEST_LIBCRYPTO')
    if not value:raise RuntimeError('Set CABINET_TEST_LIBCRYPTO to a reviewed local libcrypto file; no skipped crypto tests')
    path=Path(value).resolve()
    return path,hashlib.sha256(path.read_bytes()).hexdigest()


class NonblockingParameterTests(unittest.TestCase):
    def setUp(self):
        self.fixture=advanced_fixtures.ParameterTests('test_preview_queue_and_sole_owner_application_have_distinct_receipts');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def test_slow_durable_intent_does_not_block_hardware_owner(self):
        parameters=self.fixture.parameters;preview=parameters.preview(self.fixture.request());entered=threading.Event();release=threading.Event();errors=[]
        original=self.fixture.service.store.diagnostic
        def slow(*arguments):entered.set();release.wait(2);return original(*arguments)
        def commit():
            try:parameters.commit(dict(request_id=preview['request_id'],nonce=preview['nonce']))
            except Exception as error:errors.append(error)
        with patch.object(self.fixture.service.store,'diagnostic',side_effect=slow):
            worker=threading.Thread(target=commit);worker.start();self.assertTrue(entered.wait(1))
            try:
                begin=time.monotonic();self.assertIs(parameters.process(),False);elapsed=time.monotonic()-begin
                self.assertLess(elapsed,0.05);self.assertEqual(self.fixture.service.outer.c['setpoint_C'],35)
            finally:release.set();worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        self.fixture.service.updated=self.fixture.service.frame_received=time.monotonic()
        parameters.process();self.assertEqual(parameters.revision,1)

    def test_any_concurrent_profile_or_summary_lock_is_skipped(self):
        parameters=self.fixture.parameters;entered=threading.Event();release=threading.Event()
        def locked():
            with parameters.lock:entered.set();release.wait(1)
        worker=threading.Thread(target=locked);worker.start();self.assertTrue(entered.wait(1))
        try:self.assertIs(parameters.process(),False)
        finally:release.set();worker.join(2)

    def test_stopping_collector_rejects_new_parameter_intents(self):
        self.fixture.service.stop.set()
        with self.assertRaises(ValueError):self.fixture.parameters.preview(self.fixture.request())


class QueuedModelTests(unittest.TestCase):
    def test_stale_status_cannot_recover_pl_or_link_faults(self):
        with tempfile.TemporaryDirectory() as folder:
            config=copy.deepcopy(CONFIG);config['database']=str(Path(folder)/'events.db');service=Service(config)
            try:
                service.boot='boot';tracker=EventTracker(service.store,'unit','boot');service.trackers['boot']=tracker
                tracker.update('TEMP_HARD',3,True,{},source='PL')
                service.link_tracker.update('PL_LINK_LOSS',1,True,{},source='SYSTEM')
                status=MockController().status();status.update(active=[],latched=[])
                base=dict(link='ONLINE',snapshot_monotonic=time.monotonic(),status_age_ms=0,status=status)
                for change in [dict(snapshot_monotonic=None),dict(snapshot_monotonic=time.monotonic()+1),
                               dict(snapshot_monotonic=time.monotonic()-120),dict(status_age_ms=3000)]:
                    service.journal.put(('status','boot',dict(base,**change)))
                service.journal.put(('status','obsolete-boot',base));service.stop.set();service.journal_loop()
                self.assertIn('PL:TEMP_HARD',tracker.active);self.assertIn('SYSTEM:PL_LINK_LOSS',service.link_tracker.active)
                self.assertNotIn('obsolete-boot',service.trackers)
            finally:service.close()

    def test_only_fresh_offline_capture_creates_link_loss_even_without_status_age(self):
        with tempfile.TemporaryDirectory() as folder:
            config=copy.deepcopy(CONFIG);config['database']=str(Path(folder)/'events.db');service=Service(config)
            try:
                service.boot='boot';state=dict(link='OFFLINE',status_age_ms=None,status={})
                service.journal.put(('status','boot',dict(state,snapshot_monotonic=time.monotonic()-120)))
                service.stop.set();service.journal_loop();self.assertEqual(service.store.events(),[])
                service.journal.put(('status','boot',dict(state,snapshot_monotonic=time.monotonic())))
                service.journal_loop();self.assertIn('SYSTEM:PL_LINK_LOSS',service.link_tracker.active)
            finally:service.close()

    def test_stale_model_snapshot_cannot_create_new_formal_workorder(self):
        with tempfile.TemporaryDirectory() as folder:
            config=copy.deepcopy(CONFIG);config['database']=str(Path(folder)/'events.db');service=Service(config)
            try:
                tracker=EventTracker(service.store,'unit','boot');status=dict(uptime_ms=1000)
                state=dict(link='ONLINE',snapshot_monotonic=time.monotonic()-120,status_age_ms=0,frame_age_ms=0,
                    model=dict(label='imbalance',formal=True,frame_end_ms=1000),decision=dict(model_state='CONFIRMED_MAINTENANCE'))
                with patch.object(service.model,'formal_result',return_value=True):service.model_events(tracker,state,status)
                self.assertEqual(service.store.events(),[])
                state['snapshot_monotonic']=time.monotonic()
                with patch.object(service.model,'formal_result',return_value=True):service.model_events(tracker,state,status)
                self.assertEqual(service.store.events()[0]['source'],'MODEL')
            finally:service.close()


class CascadeCoordinationTests(unittest.TestCase):
    def loop(self):
        return TemperatureLoop(dict(enabled=True,qualified=True,evidence='TEST_ONLY',setpoint_C=30,kp_rpm_per_C=100,
            ki_rpm_per_C_s=10,rpm_min=1000,rpm_max=6000,slew_rpm_per_s=500,temp_age_ms=2000))

    def status(self):
        status=MockController().status();status.update(requested_rpm=3000,measured_rpm=2900,temp_raw_1_16_C=35*16,applied_pwm_counts=2000,fan_action='PI')
        return status

    def test_inner_saturation_cannot_wind_up_temperature_integrator(self):
        loop=self.loop();status=self.status();loop.update(status,0);original=loop.integral
        status['applied_pwm_counts']=4000
        for index in range(1,101):loop.update(status,index/10)
        self.assertEqual(loop.integral,original);self.assertEqual(loop.coordination['state'],'INNER_SATURATION_INTEGRAL_HELD')

    def test_pl_override_tracks_request_and_clear_is_bumpless(self):
        loop=self.loop();status=self.status();loop.update(status,0);status['fan_action']='BOOST'
        for index in range(1,5):self.assertEqual(loop.update(status,index/10),3000)
        self.assertEqual(loop.coordination['state'],'PL_OVERRIDE_TRACKING');status['fan_action']='PI'
        self.assertLessEqual(abs(loop.update(status,0.5)-3000),50)

    def test_manual_inhibit_and_latched_protection_keep_priority(self):
        for action in ['MANUAL','INHIBIT','FALLBACK','OFF','STARTUP']:
            loop=self.loop();status=self.status();status['fan_action']=action
            self.assertIsNone(loop.update(status,0));self.assertEqual(loop.integral,0)
        loop=self.loop();status=self.status();status['latched']=['TEMP_HARD'];self.assertIsNone(loop.update(status,0))

    def test_gap_and_clock_reversal_reset_without_step_or_multi_actuator_claim(self):
        loop=self.loop();status=self.status();loop.update(status,1);loop.update(status,1.1)
        self.assertIsNone(loop.update(status,1));self.assertEqual(loop.integral,0)
        self.assertEqual(loop.update(status,4),3000);self.assertEqual(loop.coordination['independent_actuators'],1)
        self.assertFalse(loop.coordination['physical_qualification'])

    def test_missing_future_or_stale_result_time_is_not_a_formal_event(self):
        with tempfile.TemporaryDirectory() as folder:
            config=copy.deepcopy(CONFIG);config['database']=str(Path(folder)/'events.db');service=Service(config)
            try:
                tracker=EventTracker(service.store,'unit','boot');status=dict(uptime_ms=1000)
                base=dict(link='ONLINE',snapshot_monotonic=time.monotonic(),status_age_ms=0,frame_age_ms=0,
                    model=dict(label='imbalance',formal=True,frame_end_ms=1000),decision=dict(model_state='CONFIRMED_MAINTENANCE'))
                for change in [dict(snapshot_monotonic=None),dict(snapshot_monotonic=time.monotonic()+1),dict(frame_age_ms=501),dict(model=dict(base['model'],frame_end_ms=0))]:
                    with self.subTest(change=change),patch.object(service.model,'formal_result',return_value=True):service.model_events(tracker,dict(base,**change),status)
                self.assertEqual(service.store.events(),[])
            finally:service.close()


class EVPProviderTests(unittest.TestCase):
    def test_known_aes256_gcm_answer_and_random_cross_provider_equivalence(self):
        path,pin=native_library();key=bytes(32);nonce=bytes(12);native=OpenSSLAESGCM(key,str(path),pin)
        self.assertEqual(native.encrypt(nonce,bytes(16),b'').hex(),'cea7403d4d606b6e074ec5d3baf39d18d0d1c8a799996bf0265b98b5d48ab919')
        for length in [0,1,15,16,17,31,32,255,4096,65537]:
            key=secrets.token_bytes(32);nonce=secrets.token_bytes(12);native=OpenSSLAESGCM(key,str(path),pin);reference=AESGCM(key)
            for aad in [b'',b'row/table/revision',secrets.token_bytes(64)]:
                data=secrets.token_bytes(length);encrypted=native.encrypt(nonce,data,aad)
                self.assertEqual(encrypted,reference.encrypt(nonce,data,aad));self.assertEqual(native.decrypt(nonce,encrypted,aad),data)
                self.assertEqual(reference.decrypt(nonce,encrypted,aad),data)

    def test_wrong_tag_nonce_aad_key_and_library_pin_are_rejected(self):
        path,pin=native_library();native=OpenSSLAESGCM(bytes(32),str(path),pin);encrypted=native.encrypt(bytes(12),b'secret',b'context')
        for nonce,data,aad in [(bytes([1])+bytes(11),encrypted,b'context'),(bytes(12),encrypted[:-1]+bytes([encrypted[-1]^1]),b'context'),(bytes(12),encrypted,b'wrong')]:
            with self.assertRaises(ValueError):native.decrypt(nonce,data,aad)
        with self.assertRaises(ValueError):OpenSSLAESGCM(bytes(32),str(path),'0'*64)
        with self.assertRaises(ValueError):cipher_provider(bytes(32),dict(enabled=True,key_file='unused',provider='unknown'))

    def test_cross_provider_journal_reopen_needs_no_data_rewrite(self):
        path,pin=native_library()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);key=root/'key';create_key(key);database=root/'events.db'
            classic=dict(enabled=True,key_file=str(key));native=dict(classic,provider='openssl-evp',library=str(path),library_sha256=pin)
            store=Store(database,encryption=classic);store.snapshot('unit',dict(secret='PRIVATE_CROSS_PROVIDER'));store.close()
            store=Store(database,encryption=native);self.assertEqual(store.get_snapshot('unit')['secret'],'PRIVATE_CROSS_PROVIDER');store.snapshot('unit',dict(value=2));store.close()
            store=Store(database,encryption=classic)
            try:self.assertEqual(store.get_snapshot('unit'),dict(value=2))
            finally:store.close()

    def test_evp_preflight_is_readonly_and_refuses_host_as_target(self):
        path,pin=native_library()
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'key';create_key(key)
            command=[os.sys.executable,'-B',str(ROOT/'tools/advanced_preflight.py'),'--key-file',str(key),'--provider','openssl-evp','--library',str(path),'--library-sha256',pin]
            result=subprocess.run(command,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr);document=json.loads(result.stdout)
            self.assertEqual(document['provider'],'openssl-evp');self.assertFalse(document['mmio_opened']);self.assertFalse(document['key_exported'])
            if os.sys.platform!='linux':
                rejected=subprocess.run(command+['--require-target'],capture_output=True,text=True,timeout=10);self.assertNotEqual(rejected.returncode,0)


class LocalOperatorTests(unittest.TestCase):
    def setUp(self):
        self.fixture=advanced_fixtures.ParameterTests('test_preview_queue_and_sole_owner_application_have_distinct_receipts');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.temporary=tempfile.TemporaryDirectory(prefix='cb37-',dir='/tmp');self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'p.sock';self.rpc=ParameterRPC(self.fixture.service,self.path);self.addCleanup(self.rpc.close)

    def request(self,operation,payload,identity='1'*32):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(2);connection.connect(str(self.path))
            connection.sendall((json.dumps(dict(schema='cabinet-parameter-local-v1',call_id=identity,operation=operation,payload=payload))+'\n').encode())
            data=b''
            while b'\n\n' not in data:
                part=connection.recv(4096)
                if not part:break
                data+=part
        return dict(line.split('\t',1) for line in data.decode().strip().splitlines())

    def test_private_status_preview_commit_uses_same_collector_gate(self):
        self.assertFalse(self.path.stat().st_mode&0o077);status=self.request('status',{})
        self.assertEqual(status['current_tenths'],'350')
        payload=dict(request_id='2'*32,revision=0,context_token=status['context_token'],setpoint_tenths=360)
        preview=self.request('preview',payload);self.assertEqual(preview['state'],'PREVIEW_NOT_APPLIED')
        commit=self.request('commit',dict(request_id='2'*32,nonce=preview['nonce']));self.assertEqual(commit['state'],'QUEUED_NOT_APPLIED')
        self.assertEqual(self.fixture.service.outer.c['setpoint_C'],35)
        self.fixture.parameters.process();status=self.request('status',{})
        self.assertEqual(status['revision'],'1');self.assertEqual(status['last_state'],'APPLIED_PS_SETPOINT_NOT_PL_OUTPUT_CONFIRMATION')
        self.assertIsNone(self.fixture.service.controller)

    def test_other_uid_wrong_context_and_unknown_command_are_denied(self):
        with patch('cabinet.parameter_rpc.peer_uid',return_value=os.geteuid()+1):self.assertEqual(self.request('status',{})['state'],'REJECTED_NOT_APPLIED')
        for operation,payload in [('reset',{}),('preview',dict(request_id='2'*32,revision=0,context_token='0'*64,setpoint_tenths=360))]:
            self.assertEqual(self.request(operation,payload)['state'],'REJECTED_NOT_APPLIED')
        self.assertEqual(self.fixture.parameters.revision,0)

    def test_existing_socket_and_insecure_directory_are_not_replaced(self):
        with self.assertRaises(ValueError):ParameterRPC(self.fixture.service,self.path)
        insecure=Path(self.temporary.name)/'insecure';insecure.mkdir(mode=0o755)
        with self.assertRaises(ValueError):ParameterRPC(self.fixture.service,insecure/'socket')

    def test_real_lvgl_button_callbacks_and_c_socket_client(self):
        binary=Path(os.environ.get('CABINET_TEST_HMI',''))
        if not binary.is_file():raise RuntimeError('Build the R37 headless native HMI before tests; no skipped GUI tests')
        root=Path(self.temporary.name);state=root/'state.txt';state.write_text('sequence=1\nlink=ERROR\npanel_schema=industrial-v2\n')
        actions=root/'actions.txt';actions.write_text('0\n'+'2\n'*10+'3\n4\n0\n');audit=root/'audit.txt';image=root/'screen.ppm'
        stop=threading.Event()
        def owner_steps():
            while not stop.wait(0.005):
                self.fixture.service.updated=self.fixture.service.frame_received=time.monotonic();self.fixture.parameters.process()
        owner=threading.Thread(target=owner_steps);owner.start()
        try:
            result=subprocess.run([str(binary),str(state),str(image)],capture_output=True,text=True,timeout=15,
                env=dict(os.environ,CABINET_OPERATOR_SOCKET=str(self.path),CABINET_OPERATOR_ACTIONS=str(actions),CABINET_UI_AUDIT=str(audit)))
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            fields=dict(line.split('=',1) for line in audit.read_text().splitlines())
            self.assertEqual(fields['parameter_revision'],'1');self.assertEqual(fields['parameter_current_tenths'],'360');self.assertEqual(fields['parameter_output_confirmed'],'0')
            self.assertIn('PS setpoint applied',fields['parameter_message']);self.assertTrue(image.read_bytes().startswith(b'P6\n1280 720\n'))
            destination=os.environ.get('CABINET_HMI_TEST_IMAGE')
            if destination:Path(destination).write_bytes(image.read_bytes())
        finally:stop.set();owner.join(2)


def measurement_fixture(root):
    headers={
        'control.csv':['time_s','target_rpm','measured_rpm','steady'],
        'acquisition.csv':['sequence','source_ticks','received_ticks','clock_hz'],
        'npu.csv':['case_id','input_sha256','duration_ms','backend','hardware_executed'],
        'bus.csv':['sequence','sent','received','crc_errors','timeouts','duration_s'],
        'reliability.csv':['elapsed_s','reset_count','error_count'],
    }
    tables={
        'control.csv':[[index,1000,1001,1] for index in range(20)],
        'acquisition.csv':[[index,index*25000,index*25000+100,100000000] for index in range(20)],
        'npu.csv':[[str(index),hashlib.sha256(str(index).encode()).hexdigest(),10+index/100,'Alnpu',1] for index in range(40)],
        'bus.csv':[[0,1000,1000,0,0,60]],'reliability.csv':[[0,0,0],[7200,0,0]],
    }
    files={}
    for name,rows in tables.items():
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(headers[name]);writer.writerows(rows)
        data=stream.getvalue().encode();(root/name).write_bytes(data);files[name]=hashlib.sha256(data).hexdigest()
    manifest=dict(schema='cabinet-quantitative-input-v1',source='HOST_FIXTURE',device_id='TEST_ONLY',calibration_id=1,bit_sha256='a'*64,pl_build_id=0x202610f7,files_sha256=files)
    data=json.dumps(manifest).encode();(root/'measurements.json').write_bytes(data)
    return manifest,hashlib.sha256(data).hexdigest()


class QuantitativeReportTests(unittest.TestCase):
    def module(self):
        spec=importlib.util.spec_from_file_location('quantitative_report',ROOT/'tools/quantitative_report.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def test_recomputed_units_percentiles_and_fixture_never_grant_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);unused,pin=measurement_fixture(root);report=self.module().calculate(root,pin)
            self.assertIn('FIXTURE_ONLY',report['status']);self.assertTrue(all(report['gates'].values()));self.assertFalse(report['qualification_granted'])
            self.assertEqual(report['metrics']['effective_acquisition_rate_hz'],4000);self.assertEqual(report['metrics']['acquisition_latency_ms']['p99'],0.001)
            self.assertAlmostEqual(report['metrics']['control_relative_error_percent']['maximum'],0.1)

    def test_missing_tables_are_null_not_fabricated_zero_results(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest,unused=measurement_fixture(root);manifest['files_sha256']={};raw=json.dumps(manifest).encode();(root/'measurements.json').write_bytes(raw)
            report=self.module().calculate(root,hashlib.sha256(raw).hexdigest());self.assertIn('INCOMPLETE',report['status'])
            self.assertIsNone(report['metrics']['npu_latency_ms']['mean']);self.assertIsNone(report['gates']['steady_error_below_2_percent'])

    def test_table_tamper_and_wrong_pin_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);unused,pin=measurement_fixture(root)
            with self.assertRaises(ValueError):self.module().calculate(root,'0'*64)
            (root/'npu.csv').write_text('wrong\n')
            with self.assertRaises(ValueError):self.module().calculate(root,pin)

    def test_measured_failure_cpu_reference_and_nan_cannot_pass(self):
        for mode in ['cpu','nan','crc']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);manifest,unused=measurement_fixture(root)
                name='control.csv' if mode=='nan' else 'bus.csv' if mode=='crc' else 'npu.csv'
                text=(root/name).read_text()
                if mode=='nan':text=text.replace('1001','nan')
                elif mode=='cpu':text=text.replace('Alnpu','CPU_REFERENCE')
                else:text=text.replace('1000,1000,0,0','1000,999,1,0')
                (root/name).write_text(text);manifest['files_sha256'][name]=hashlib.sha256((root/name).read_bytes()).hexdigest();raw=json.dumps(manifest).encode();(root/'measurements.json').write_bytes(raw);pin=hashlib.sha256(raw).hexdigest()
                if mode=='nan':
                    with self.assertRaises(ValueError):self.module().calculate(root,pin)
                else:self.assertIn('FAIL_MEASURED',self.module().calculate(root,pin)['status'])
