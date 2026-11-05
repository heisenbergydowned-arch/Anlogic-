import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from cabinet.journal_crypto import create_key,migrate
from cabinet.store import Store
from cabinet.service import Service
from cabinet.parameters import ParameterControl
from cabinet.web import server
from cabinet.maintenance import archive_database
from cabinet.fault_grade import FaultGrade,GRADES,validate
from cabinet.reports import MonitorReports
from cabinet.protocol import Frame
from journal_admin import export_report
from history_server import ArchiveStore
from train_fault_grade import train
from v4_runtime.bundle import Bundle
from v4_runtime.qualification import validate_evidence
from test_chain import CONFIG,real_frame
from test_r31_features import admitted_fixture,write_json
from test_waveform_archive import capture,WaveRegisters


def event(identity='fixture',revision=1):
    return dict(event_id=identity,event_revision=revision,device_id='unit',boot_id='unit/boot',source='MODEL',code='SECRET_FAULT_DETAIL_ABC',
                state='RECOVERED',acknowledged=True,severity_peak=1,notify=True)


class EncryptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.key=self.root/'journal.key';create_key(self.key)
        self.encryption=dict(enabled=True,key_file=str(self.key));self.path=self.root/'journal.db'

    def opened(self,path=None,encryption=None):
        store=Store(path or self.path,encryption=self.encryption if encryption is None else encryption)
        self.addCleanup(store.close);return store

    def test_event_outbox_ack_receipts_and_restart_roundtrip(self):
        store=Store(self.path,encryption=self.encryption);store.event(event())
        self.assertEqual(store.events(),[event()]);self.assertEqual(store.pending()[0]['payload'],event())
        store.receive(event());self.assertEqual(store.received(),[event()]);store.snapshot('unit',dict(secret='PRIVATE_SENSOR_VALUE'))
        store.close();store=self.opened();self.assertEqual(store.get_snapshot('unit')['secret'],'PRIVATE_SENSOR_VALUE')
        self.assertEqual(store.events()[0]['code'],'SECRET_FAULT_DETAIL_ABC')

    def test_database_and_wal_do_not_contain_fault_or_snapshot_plaintext(self):
        store=self.opened();store.event(event());store.snapshot('unit',dict(secret='PRIVATE_SENSOR_VALUE'))
        store.fifo('fifo-id',[0xabcdef],event('fifo-event'));store.diagnostic('PRIVATE_DIAG_CODE',dict(secret='PRIVATE_DIAGNOSTIC'))
        for path in self.root.glob('journal.db*'):
            data=path.read_bytes()
            for secret in [b'SECRET_FAULT_DETAIL_ABC',b'PRIVATE_SENSOR_VALUE',b'PRIVATE_DIAG_CODE',b'PRIVATE_DIAGNOSTIC']:
                self.assertNotIn(secret,data,path.name)

    def test_randomized_nonce_same_plaintext_differs(self):
        store=self.opened();store.snapshot('unit',dict(secret=1));first=store.db.execute('SELECT payload FROM snapshots').fetchone()[0]
        store.snapshot('unit',dict(secret=1));second=store.db.execute('SELECT payload FROM snapshots').fetchone()[0]
        self.assertNotEqual(first,second);self.assertEqual(store.get_snapshot('unit'),dict(secret=1))

    def test_ciphertext_tamper_and_plaintext_injection_fail_closed(self):
        store=self.opened();store.event(event())
        for payload in ['{"secret":"plaintext"}','CJE1:AA==','CJE1:not-base64']:
            with self.subTest(payload=payload):
                store.db.execute('UPDATE events SET payload=?',(payload,));store.db.commit()
                with self.assertRaises(ValueError):store.events()

    def test_aad_rejects_table_row_revision_and_database_transplant(self):
        store=self.opened();store.event(event());payload=store.db.execute('SELECT payload FROM events').fetchone()[0]
        for table,identity,revision in [('outbox','fixture',1),('events','another',1),('events','fixture',2)]:
            with self.subTest(table=table,identity=identity,revision=revision),self.assertRaises(ValueError):store.unpack(payload,table,identity,revision)
        other=self.opened(self.root/'other.db')
        with self.assertRaises(ValueError):other.unpack(payload,'events','fixture',1)

    def test_missing_wrong_and_overpermissive_keys_rejected(self):
        store=Store(self.path,encryption=self.encryption);store.event(event());store.close()
        with self.assertRaises(ValueError):Store(self.path)
        wrong=self.root/'wrong.key';create_key(wrong)
        with self.assertRaises(ValueError):Store(self.path,encryption=dict(enabled=True,key_file=str(wrong)))
        self.key.chmod(0o644)
        with self.assertRaises(ValueError):Store(self.path,encryption=self.encryption)

    def test_key_symlink_and_overwrite_rejected(self):
        with self.assertRaises(FileExistsError):create_key(self.key)
        link=self.root/'link';link.symlink_to(self.key)
        with self.assertRaises(OSError):Store(self.path,encryption=dict(enabled=True,key_file=str(link)))

    def test_enabling_encryption_on_nonempty_plaintext_requires_migration(self):
        store=Store(self.path);store.event(event());store.close()
        with self.assertRaises(ValueError):Store(self.path,encryption=self.encryption)
        store=Store(self.path);self.assertEqual(store.events(),[event()]);store.close()

    def test_wal_committed_migration_preserves_source_and_all_payloads(self):
        source=Store(self.path);self.addCleanup(source.close);source.db.execute('PRAGMA wal_autocheckpoint=0')
        source.event(event());source.snapshot('unit',dict(secret='PRIVATE_SENSOR_VALUE'));source.diagnostic('secret',dict(value=2))
        source.history.record('unit',dict(link='OFFLINE',test=False),recorded=100)
        destination=self.root/'encrypted.db';migrate(self.path,destination,self.encryption)
        self.assertEqual(source.events(),[event()]);encrypted=self.opened(destination)
        self.assertEqual(encrypted.events(),source.events());self.assertEqual(encrypted.get_snapshot('unit'),source.get_snapshot('unit'))
        self.assertEqual(encrypted.history.query('unit',0,200)['items'],source.history.query('unit',0,200)['items'])
        self.assertNotIn(b'SECRET_FAULT_DETAIL_ABC',destination.read_bytes())
        with self.assertRaises(FileExistsError):migrate(self.path,destination,self.encryption)

    def test_waveform_history_and_encrypted_archive_replay(self):
        store=self.opened();unused,records=capture(WaveRegisters());record=records[0][1];identity=records[0][0][2]
        store.waveform(identity,record,'unit');store.waveform(identity,record,'unit')
        self.assertEqual(store.history.get_waveform('unit',identity)['raw'],record)
        archive_database(self.path,self.root/'archive')
        with self.assertRaises(ValueError):ArchiveStore(self.root/'archive/events.sqlite3')
        archive=ArchiveStore(self.root/'archive/events.sqlite3',self.encryption)
        try:self.assertEqual(archive.history.get_waveform('unit',identity)['raw'],record)
        finally:archive.close()

    def test_encrypted_prune_keeps_pending_and_active_events(self):
        store=self.opened()
        for index in range(4):
            item=event(str(index));item['notify']=False;store.event(item)
        store.event(dict(event('active'),state='ACTIVE'))
        result=archive_database(self.path,self.root/'archive',True,1,self.encryption)
        self.assertEqual(result['pruned']['events'],4);self.assertEqual(store.events()[0]['state'],'ACTIVE')

    def test_batch_csv_requires_ack_preserves_source_and_escapes_formula(self):
        store=self.opened();store.event(dict(event(),code='=dangerous()'));output=self.root/'report.csv'
        with self.assertRaises(ValueError):export_report(self.path,output,self.encryption)
        self.assertFalse(output.exists());result=export_report(self.path,output,self.encryption,True)
        self.assertEqual(result['rows'],1);self.assertFalse(output.stat().st_mode&0o077)
        self.assertIn("'=dangerous()",output.read_text());self.assertEqual(store.events()[0]['code'],'=dangerous()')
        with self.assertRaises(FileExistsError):export_report(self.path,output,self.encryption,True)

    def test_advanced_service_rejects_unencrypted_journal_before_opening(self):
        config=copy.deepcopy(CONFIG);config.update(database=str(self.path),project_level='advanced')
        with self.assertRaises(ValueError):Service(config)
        self.assertFalse(self.path.exists())

    def test_mock_journal_worker_uses_real_encryption_and_stops_cleanly(self):
        config=copy.deepcopy(CONFIG);config.update(database=str(self.path),project_level='advanced',journal_encryption=self.encryption)
        service=Service(config,mock=True)
        try:
            service.start();deadline=time.monotonic()+2
            while time.monotonic()<deadline and service.store.get_snapshot(config['device_id']) is None:time.sleep(0.02)
            self.assertIsNotNone(service.store.get_snapshot(config['device_id']))
            self.assertTrue(service.store.db.execute('SELECT payload FROM snapshots').fetchone()[0].startswith('CJE1:'))
        finally:service.close()


class ParameterTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);key=self.root/'key';create_key(key)
        config=copy.deepcopy(CONFIG);config['database']=str(self.root/'events.db');config['contract']['calibration_id']=1
        config['journal_encryption']=dict(enabled=True,key_file=str(key))
        config['control'].update(enabled=True,qualified=True,evidence='TEST_ONLY_CONTROL_RECEIPT')
        config['temperature_loop'].update(enabled=True,qualified=True,evidence='TEST_ONLY_TEMPERATURE_RECEIPT',setpoint_C=35,
            kp_rpm_per_C=100,ki_rpm_per_C_s=10,rpm_min=1000,rpm_max=6000,slew_rpm_per_s=500,temp_age_ms=2000)
        self.profile=dict(schema='cabinet-parameter-envelope-v1',device_id=config['device_id'],control_evidence=config['control']['evidence'],
            temperature_evidence=config['temperature_loop']['evidence'],calibration_id=1,feature_config_id=1,pl_build_id=0x202610f7,setpoint_C=[30,40])
        self.profile_path=self.root/'profile.json';pin=write_json(self.profile_path,self.profile)
        config['parameter_control']=dict(enabled=True,profile=str(self.profile_path),sha256=pin)
        self.service=Service(config);self.addCleanup(self.service.close);self.service.boot='TEST_ONLY_BOOT';self.service.connection_epoch=1
        frame=real_frame().as_dict();frame['bitstream_id']='202610f7'
        self.service.state.update(link='ONLINE',test=False,frame=frame,status=dict(uptime_ms=frame['end_ms'],configured=True,mode='RUN',active=[],latched=[],
            input_validity=dict(temperature=True),temp_age_ms=0,alarm_level=0))
        self.service.updated=self.service.frame_received=time.monotonic();self.service.valid_input=True
        self.parameters=self.service.parameters

    def request(self,value=36,identity='1'*32):
        return dict(request_id=identity,expected_revision=self.parameters.revision,context=self.parameters.context(),setpoint_C=value)

    def queued(self):
        preview=self.parameters.preview(self.request());request=dict(request_id=preview['request_id'],nonce=preview['nonce'])
        return request,self.parameters.commit(request)

    def test_preview_queue_and_sole_owner_application_have_distinct_receipts(self):
        preview=self.parameters.preview(self.request());self.assertEqual(self.service.outer.c['setpoint_C'],35)
        request=dict(request_id=preview['request_id'],nonce=preview['nonce']);result=self.parameters.commit(request)
        self.assertEqual(result['state'],'QUEUED_NOT_APPLIED');self.assertEqual(self.service.outer.c['setpoint_C'],35)
        self.parameters.process();self.assertEqual(self.service.outer.c['setpoint_C'],36)
        self.assertEqual(self.parameters.commit(request)['state'],'APPLIED_PS_SETPOINT_NOT_PL_OUTPUT_CONFIRMATION')
        self.assertFalse(self.parameters.summary()['pl_output_confirmed']);self.assertIsNone(self.service.controller)

    def test_duplicate_commit_never_applies_twice(self):
        request,result=self.queued();self.assertEqual(self.parameters.commit(request),result)
        self.parameters.process();self.parameters.process();self.parameters.commit(request)
        self.assertEqual(self.parameters.revision,1)

    def test_unknown_fields_nonfinite_bool_and_outside_envelope_rejected(self):
        for value in [True,None,float('nan'),float('inf'),29,41]:
            with self.subTest(value=value),self.assertRaises(ValueError):self.parameters.preview(self.request(value))
        for extra in [dict(enabled=True),dict(kp=0),dict(clear_protection=True)]:
            with self.assertRaises(ValueError):self.parameters.preview(dict(self.request(),**extra))

    def test_preview_expires_and_wrong_nonce_fails(self):
        preview=self.parameters.preview(self.request())
        with self.assertRaises(ValueError):self.parameters.commit(dict(request_id=preview['request_id'],nonce='wrong'))
        with patch('cabinet.parameters.time.monotonic',return_value=preview['expires_at']+1),self.assertRaises(ValueError):
            self.parameters.commit(dict(request_id=preview['request_id'],nonce=preview['nonce']))

    def test_boot_reset_and_session_epoch_reject_queued_commands(self):
        for field in ['boot','collector_session','connection_epoch']:
            with self.subTest(field=field):
                self.parameters.revision=0;self.parameters.results.clear();self.parameters.previews.clear()
                unused,result=self.queued();old=getattr(self.service,field);setattr(self.service,field,2 if field=='connection_epoch' else 'different')
                self.parameters.process();self.assertEqual(self.service.outer.c['setpoint_C'],35)
                self.assertEqual(self.parameters.results[result['request_id']]['state'],'REJECTED_NOT_APPLIED');setattr(self.service,field,old)

    def test_alarm_stale_input_or_test_mode_cannot_change_parameter(self):
        for field,value in [('test',True),('link','OFFLINE')]:
            old=self.service.state[field];self.service.state[field]=value
            with self.assertRaises(ValueError):self.parameters.preview(self.request())
            self.service.state[field]=old
        self.service.state['status']['latched']=['TEMP_HARD']
        with self.assertRaises(ValueError):self.parameters.preview(self.request())
        self.service.state['status']['latched']=[];self.service.updated=time.monotonic()-2
        with self.assertRaises(ValueError):self.parameters.preview(self.request())

    def test_audit_failure_rejects_before_queue_and_queue_backpressure_before_apply(self):
        preview=self.parameters.preview(self.request());request=dict(request_id=preview['request_id'],nonce=preview['nonce'])
        with patch.object(self.service.store,'diagnostic',side_effect=OSError('disk full')),self.assertRaises(OSError):self.parameters.commit(request)
        self.assertIsNone(self.parameters.pending);self.parameters.commit(request)
        with patch.object(self.service,'put_journal',return_value=False):self.parameters.process()
        self.assertEqual(self.service.outer.c['setpoint_C'],35);self.assertEqual(self.parameters.revision,0)

    def test_execution_does_no_filesystem_or_database_work(self):
        self.queued()
        with patch('cabinet.parameters.pinned_json',side_effect=AssertionError('disk read in IO owner')),patch.object(self.service.store,'diagnostic',side_effect=AssertionError('DB in IO owner')):
            self.parameters.process()
        self.assertEqual(self.parameters.revision,1)

    def test_profile_pin_and_configuration_binding_are_required(self):
        self.service.config['parameter_control']['sha256']=None
        with self.assertRaises(ValueError):ParameterControl(self.service)
        self.service.config['parameter_control']['sha256']=write_json(self.profile_path,dict(self.profile,device_id='wrong'))
        with self.assertRaises(ValueError):ParameterControl(self.service)

    def test_queued_expiry_and_fault_after_preview_cannot_apply(self):
        request,result=self.queued()
        with patch('cabinet.parameters.time.monotonic',return_value=result['expires_at']+1):self.parameters.process()
        self.assertEqual(self.parameters.results[request['request_id']]['state'],'REJECTED_NOT_APPLIED')
        self.assertEqual(self.service.outer.c['setpoint_C'],35)
        preview=self.parameters.preview(self.request(identity='2'*32));self.service.state['status']['active']=['TEMP_HARD']
        with self.assertRaises(ValueError):self.parameters.commit(dict(request_id=preview['request_id'],nonce=preview['nonce']))
        self.assertIsNone(self.parameters.pending)

    def test_read_token_cannot_write_cross_origin_or_remote_control(self):
        listener=server('127.0.0.1',0,self.service,token='read',control_token='CONTROL_TEST_ONLY_'+'a'*32)
        worker=threading.Thread(target=listener.serve_forever,daemon=True);worker.start()
        try:
            base='http://127.0.0.1:'+str(listener.server_port)
            with urlopen(base+'/parameters',timeout=2) as response:
                html=response.read().decode();self.assertIn('受控参数配置',html);self.assertNotIn('localStorage',html)
            for headers,expected in [({},401),({'Authorization':'Bearer read'},403),
                    ({'Authorization':'Bearer read','X-Cabinet-Control-Token':'CONTROL_TEST_ONLY_'+'a'*32,'Origin':'http://evil.invalid'},403)]:
                request=Request(base+'/api/parameters/preview',data=json.dumps(self.request()).encode(),headers=dict(headers,**{'Content-Type':'application/json'}))
                with self.assertRaises(HTTPError) as failure:urlopen(request,timeout=2)
                self.assertEqual(failure.exception.code,expected)
            headers={'Authorization':'Bearer read','X-Cabinet-Control-Token':'CONTROL_TEST_ONLY_'+'a'*32,'Content-Type':'application/json'}
            with urlopen(Request(base+'/api/parameters/preview',data=json.dumps(self.request()).encode(),headers=headers),timeout=2) as response:
                preview=json.load(response);self.assertEqual(preview['state'],'PREVIEW_NOT_APPLIED')
            command=dict(request_id=preview['request_id'],nonce=preview['nonce'])
            self.service.updated=self.service.frame_received=time.monotonic()
            with patch.object(self.service.store,'diagnostic',side_effect=OSError('storage unavailable')):
                with self.assertRaises(HTTPError) as failure:
                    urlopen(Request(base+'/api/parameters/commit',data=json.dumps(command).encode(),headers=headers),timeout=2)
                self.assertEqual(failure.exception.code,503)
            self.assertIsNone(self.parameters.pending)
        finally:listener.shutdown();listener.server_close();worker.join(timeout=2)


class AdvancedAccuracyTests(unittest.TestCase):
    def test_95_percent_passes_94_percent_and_explicit_90_gate_rejected(self):
        for errors,minimum,allowed in [(5,0.95,True),(6,0.95,False),(0,0.9,False)]:
            with self.subTest(errors=errors,minimum=minimum),tempfile.TemporaryDirectory() as temporary:
                release,documents,receipt=admitted_fixture(Path(temporary))
                for row in documents['predictions.json'][:errors]:row['predicted']='imbalance'
                receipt['minimum_accuracy']=minimum
                receipt['evidence_sha256']['predictions.json']=write_json(Path(release['directory'])/'predictions.json',documents['predictions.json'])
                pin=write_json(Path(release['directory'])/'release.json',receipt)
                bundle=Bundle(release['bundle'],release['manifest_sha256'],allow_synthetic=True)
                if allowed:self.assertEqual(validate_evidence(release['directory'],pin,dict(bundle.manifest,_pin=bundle.manifest_sha256),bundle.contract)['accuracy'],0.95)
                else:
                    with self.assertRaises(ValueError):validate_evidence(release['directory'],pin,dict(bundle.manifest,_pin=bundle.manifest_sha256),bundle.contract)


class MonitorReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.store=Store(Path(self.temporary.name)/'events.db');self.addCleanup(self.store.close)
        self.report=MonitorReports(self.store,'unit',dict(enabled=True,interval_s=10))

    def sample(self,identity=1):
        return dict(valid=True,test=False,boot_id='unit/boot',frame_id=identity,recorded=100+identity,
            values=dict(rpm=1000,temperature=30,current=2),measurement_validity=dict(rpm=True,temperature=True,current=False))

    def test_summary_only_uses_valid_metrics_and_durable_outbox(self):
        with patch('cabinet.reports.time.monotonic',return_value=1):self.report.observe(self.sample())
        with patch('cabinet.reports.time.monotonic',return_value=11):identity=self.report.observe(self.sample(2))
        event=self.store.get_event(identity);statistics=event['monitoring']['statistics']
        self.assertEqual(statistics['rpm']['mean'],1000);self.assertIsNone(statistics['current']['mean'])
        self.assertEqual(self.store.pending()[0]['payload'],event);self.assertFalse(event['monitoring']['live_now'])
        self.assertFalse(event['monitoring']['classification_qualification_granted'])

    def test_invalid_test_and_duplicate_frames_are_not_counted(self):
        for change in [dict(valid=False),dict(test=True)]:self.report.observe(dict(self.sample(),**change))
        self.assertFalse(self.report.rows)
        self.report.observe(self.sample());self.report.observe(self.sample());self.assertEqual(len(self.report.rows),1)

    def test_buffer_is_bounded_and_boot_change_discards_old_session(self):
        with patch('cabinet.reports.time.monotonic',return_value=1):
            for identity in range(400):self.report.observe(self.sample(identity))
        self.assertEqual(len(self.report.rows),256);self.assertEqual(self.report.omitted,144)
        self.report.observe(dict(self.sample(401),boot_id='different'));self.assertEqual(len(self.report.rows),1)

    def test_default_off_and_invalid_config(self):
        self.assertIsNone(MonitorReports(self.store,'unit').observe(self.sample()))
        for config in [dict(enabled=1),dict(enabled=True,interval_s=0),dict(enabled=True,unknown=True)]:
            with self.assertRaises(ValueError):MonitorReports(self.store,'unit',config)

    def test_storage_high_water_defers_report_without_deleting_data(self):
        with patch('cabinet.reports.time.monotonic',return_value=1):self.report.observe(self.sample())
        with patch('cabinet.reports.time.monotonic',return_value=11),patch.object(self.store,'storage_health',return_value=dict(state='ARCHIVE_REQUIRED')):
            self.assertIsNone(self.report.observe(self.sample(2)))
        self.assertEqual(len(self.report.rows),2);self.assertEqual(self.store.events(),[])

    def test_actual_loopback_http_report_receipt_and_outbox_delete(self):
        from cabinet.uplink import Uplink
        from cloud_receiver import CloudStore,receiver
        with patch('cabinet.reports.time.monotonic',return_value=1):self.report.observe(self.sample())
        with patch('cabinet.reports.time.monotonic',return_value=11):identity=self.report.observe(self.sample(2))
        cloud=CloudStore(Path(self.temporary.name)/'cloud.db');listener=receiver(('127.0.0.1',0),cloud,{'unit':'TEST_ONLY_TOKEN'},'TEST_ADMIN')
        worker=threading.Thread(target=listener.serve_forever,daemon=True);worker.start()
        try:
            with patch.dict(os.environ,{'CABINET_UPLINK_TOKEN':'TEST_ONLY_TOKEN'}):
                uplink=Uplink(dict(url='http://127.0.0.1:'+str(listener.server_port)+'/v1/devices/events',loopback_test=True),self.store)
                self.assertEqual(uplink.once(),1)
            self.assertFalse(self.store.pending());received=cloud.list('unit')['items'][0]
            self.assertEqual(received['event_id'],identity);self.assertEqual(received['source'],'MONITOR_REPORT')
        finally:listener.shutdown();listener.server_close();worker.join(timeout=2);cloud.close()


def grade_dataset():
    def rows(split):
        result=[]
        for grade_index,grade in enumerate(GRADES):
            for index in range(24):
                features=[0.0]*39;features[grade_index]=1+index/10000
                result.append(dict(grade=grade,features=features,test=False,
                    sample_sha256=hashlib.sha256((split+grade+str(index)).encode()).hexdigest(),
                    session_sha256=hashlib.sha256((split+str(index%2)).encode()).hexdigest()))
        return result
    return dict(source='REAL_FRM1_DECLARED',label_definition='TEST FIXTURE ONLY: independent normal/mild/severe labels, not a real qualification',
        model_admission_sha256='a'*64,contract=dict(feature_config_id=1,calibration_id=1,sample_mode_id=1,pl_build_id=0x202610f7),train=rows('training'),held_out=rows('heldout'))


class GradeTests(unittest.TestCase):
    def test_labelled_training_and_recomputed_independent_confusion(self):
        model,evaluation=train(grade_dataset());self.assertEqual(evaluation['accuracy'],1)
        self.assertEqual([sum(row) for row in evaluation['confusion']],[24,24,24]);self.assertEqual(validate(model),evaluation)

    def test_test_session_and_sample_leakage_rejected(self):
        for kind in ['session','sample','test','accuracy']:
            dataset=grade_dataset()
            if kind=='session':dataset['held_out'][0]['session_sha256']=dataset['train'][0]['session_sha256']
            elif kind=='sample':dataset['held_out'][0]['sample_sha256']=dataset['train'][0]['sample_sha256']
            elif kind=='test':dataset['held_out'][0]['test']=True
            else:
                for row in dataset['held_out']:row['grade']='severe'
            with self.subTest(kind=kind),self.assertRaises(ValueError):train(dataset)

    def test_grade_requires_current_admitted_npu_not_class_name_or_protection(self):
        model,unused=train(grade_dataset())
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'grade.json';pin=write_json(path,model);head=FaultGrade(dict(path=str(path),sha256=pin))
            frame=real_frame();header=list(frame.header);header[26]=0x202610f7;features=[0.0]*39;features[2]=1;frame=Frame(tuple(header),tuple(features))
            result=dict(formal=True,qualified=True,test=False,backend='Alnpu',frame_id=frame.id,admission_sha256='a'*64,label='normal')
            self.assertEqual(head.predict(frame,result)['grade'],'severe');self.assertFalse(head.predict(frame,result)['control_authority'])
            for change in [dict(backend='CPU_ONNX'),dict(formal=False),dict(test=True),dict(frame_id=frame.id+1),dict(admission_sha256='b'*64)]:
                with self.subTest(change=change):self.assertFalse(head.predict(frame,dict(result,**change))['qualified'])
            self.assertFalse(FaultGrade().predict(frame,result)['qualified'])

    def test_grade_artifact_tampering_rejected(self):
        model,unused=train(grade_dataset())
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'grade.json';pin=write_json(path,model);head=FaultGrade(dict(path=str(path),sha256=pin))
            path.write_text('{}')
            with self.assertRaises(ValueError):head.predict(real_frame(),{})
