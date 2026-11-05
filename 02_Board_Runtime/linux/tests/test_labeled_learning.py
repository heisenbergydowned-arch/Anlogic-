"""Explicit synthetic unit fixtures: not physical labels or hardware evidence."""
import copy
import http.client
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from normal_npu.learning import Learning as NormalLearning,save,sha
from normal_npu.core import validate_header as normal_header
from labeled_npu.learning import Learning,corpus_key,MINIMUM,WINDOW_POLICY
from labeled_npu.core import FEATURES,LABELS,validate_header,feature_values,live_input

class LabeledLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        h=[0]*32;h[:5]=[0x46524d31,0x10000,284,20,100000]
        start=100000*100000-25600000;end=100000*100000
        h[5:9]=[start&0xffffffff,start>>32,end&0xffffffff,end>>32]
        h[9:15]=[25600000,25600000,1024,1024,(25<<16)|12800,8]
        h[15:23]=[0x3000,1,0,2,5,4000,100000000,50000];h[24]=20;h[26]=0x202610f7
        self.h=h;self.x=[.1]*39;self.x[38]=1000.
        self.st=dict(uptime_ms=100050,mode='STOPPING',test_mode=True,active=['CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'],
            latched=[],input_validity=dict(rpm=True,adc=True,temperature=True,pressure=True),hard_inhibit=True,
            configured=False,applied_pwm_counts=0,requested_rpm=0)
        self.document=dict(observation=dict(link='ONLINE',received_at=1000.,boot='UNIT/collector',status=self.st,
            feature_words=[1,0,1]+[0]*14,frame=dict(state='RECEIVED_REAL',header=h,values=dict(zip(FEATURES,self.x))),
            icm_diagnostics=dict(state='DIAGNOSTIC_ONLY',test=False,boot_id='UNIT',snapshot_age_ms=0,
                sensors=[dict(channel=n,who=0x12,raw=[1,2,3],fresh=True,error=False,config_verified=True,
                    config_bad_mask=0,sample_age_ms=0) for n in ('A','B')])) )
        self.document['observation'].update(bench=dict(state='IDLE',controls_enabled=False,output_never_applied=True),
            normal_reference_guard=dict(schema='cabinet-normal-reference-output-v1',boot='UNIT/collector',state='IDLE',
                safe_since_uptime_ms=0,status_uptime_ms=self.st['uptime_ms'],bench_state='IDLE',bench_id=None))
        save(self.root/'edge.json',dict(device_id='UNIT'));save(self.root/'state.json',self.document)
        save(self.root/'platform.json',dict(device_id='UNIT',pl_build_id=h[26],bitstream_sha256='a'*64))
        (self.root/'env').write_text('UNIT_ENV_NOT_EXECUTABLE')
        self.now=1000.1;self.boot='UNIT_OS_BOOT';self.worker='b'*32
        args=[self.root/'learning',self.root/'edge.json',self.root/'state.json',self.root/'platform.json',
              self.root/'env',self.root/'socket',self.root/'captures']
        self.store=Learning(*args,boot=lambda:self.boot,clock=lambda:self.now)
        self.normal=NormalLearning(*args,boot=lambda:self.boot,clock=lambda:self.now)
        self.rpc=patch('labeled_npu.learning.rpc',return_value=dict(ok=True,status=dict(state='IDLE',session_id=None,boot='UNIT/collector'))).start()
        patch('normal_npu.learning.rpc',self.rpc).start();self.addCleanup(patch.stopall)
        self.store.heartbeat(self.worker)

    def test_queued_or_unconfirmed_bench_cannot_create_learning_context(self):
        for state in ('QUEUED_NOT_APPLIED','ACTIVE_BENCH_NOT_CLOSED_LOOP','OUTPUT_STOP_UNCONFIRMED'):
            with self.subTest(state=state):
                self.document['observation']['bench']=dict(state=state,controls_enabled=False)
                save(self.root/'state.json',self.document)
                with self.assertRaises(ValueError):self.store.context()
                self.assertEqual(self.store.records(),[])

    def body(self,label='normal',episode=None):
        return dict(request_id=str(uuid.uuid4()),label=label,condition_confirmed=True,episode_confirmed=True,
            episode_id=episode or str(uuid.uuid4()),context_fingerprint=self.store.status()['labels'][label]['context_fingerprint'],
            note='Synthetic unit declaration, not hardware',fg_connected_confirmed=label=='stall')

    def start(self,label='normal',episode=None): return self.store.start(self.body(label,episode))
    def write(self): save(self.root/'state.json',self.document)
    def expected(self): return self.store.context()['input_contract']
    def words(self): return list(struct.unpack('<39I',struct.pack('<39f',*self.x)))

    def exported(self,j):
        j=self.store.claim(self.worker);j=self.store.update(j['id'],self.worker,state='REGISTERING_DATA',
            sessions={'episode':dict(ok=True,complete_windows=700,status={'session_id':'SESSION-'+j['id']})},export_sha256='f'*64)
        coverage=self.store.coverage(j['corpus_key'],exported=True)
        from labeled_npu.learning import missing
        summary=dict(corpus_key=j['corpus_key'],coverage=coverage,source='REAL_USER_DECLARED_LABELED_DIAGNOSTIC',
            dataset_sha256='e'*64,registered_session='SESSION-'+j['id'],status='WAITING_DATA' if missing(coverage) else 'READY_TO_TRAIN')
        return self.store.finalize_collection(j['id'],self.worker,summary)

    def test_explicit_label_and_episode_confirmation_are_required(self):
        for field in ('condition_confirmed','episode_confirmed','label','episode_id'):
            b=self.body();b[field]=False if 'confirmed' in field else 'invalid label!'
            with self.subTest(field=field),self.assertRaises(ValueError):self.store.start(b)
        self.assertEqual(self.store.records(),[])

    def test_one_label_one_episode_is_idempotent_and_retains_provenance(self):
        b=self.body('imbalance');j=self.store.start(b)
        self.assertEqual(self.store.start(b),j)
        self.assertEqual(j['kind'],'labeled_classifier');self.assertEqual(j['label'],'imbalance')
        self.assertFalse(j['controls_changed']);self.assertFalse(j['formal_qualification_changed'])
        self.assertEqual(j['episode_split'],'train')
        b['label']='normal'
        with self.assertRaisesRegex(ValueError,'REQUEST_ID_REUSED'):self.store.start(b)

    def test_normal_gate_is_unchanged_when_labeled_fault_is_allowed(self):
        expected=self.expected();self.st['active'].append('VIB_WARN')
        validate_header(self.h,self.st,expected,'imbalance')
        with self.assertRaisesRegex(ValueError,'HARDWARE_FAULT'):normal_header(self.h,self.st,expected)
        with self.assertRaisesRegex(ValueError,'FAULT_OUTSIDE'):validate_header(self.h,self.st,expected,'normal')

    def test_each_fault_label_does_not_admit_an_unrelated_fault(self):
        expected=self.expected()
        for label,flag in [('imbalance','VIB_WARN'),('clog','CURRENT_HIGH'),('overheat','TEMP_WARN'),('stall','CURRENT_HIGH')]:
            s=copy.deepcopy(self.st);s['active'].append(flag)
            if label=='stall':s['active'].append('STALL_CORROBORATED')
            validate_header(self.h,s,expected,label,True)
            s['active'].append('PS_LOSS')
            with self.subTest(label=label),self.assertRaisesRegex(ValueError,'FAULT_OUTSIDE'):validate_header(self.h,s,expected,label,True)

    def test_stall_unknown_fg_requires_connection_and_physical_corroboration(self):
        from labeled_npu.core import LEGACY_INPUT_POLICY
        expected=dict(self.expected(),input_policy=LEGACY_INPUT_POLICY);h=list(self.h);h[14]=0;h[15]|=0x0800
        s=copy.deepcopy(self.st);s['input_validity']['rpm']=False;s['active']+=['FG_LOSS']
        with self.assertRaisesRegex(ValueError,'NOT_CORROBORATED'):feature_values(h,self.words(),s,expected,'stall',True)
        s['active'].append('STALL_CORROBORATED')
        with self.assertRaisesRegex(ValueError,'NOT_CORROBORATED'):feature_values(h,self.words(),s,expected,'stall',False)
        values=feature_values(h,self.words(),s,expected,'stall',True)
        self.assertEqual(values[38],-32768.);self.assertEqual(self.x[38],1000.)
        self.assertFalse(s['input_validity']['rpm'])
        self.assertEqual(feature_values(h,self.words(),s,expected)[38],-32768.)

    def test_disconnection_numeric_and_quality_failures_are_not_training_examples(self):
        expected=self.expected()
        for field in ('adc','temperature','pressure'):
            s=copy.deepcopy(self.st);s['input_validity'][field]=False
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'PROCESS_SENSOR'):validate_header(self.h,s,expected,'clog')
        for bit in (1,4,8,0x10,0x20,0x100,0x200,0x400,0x4000,0x8000):
            h=list(self.h);h[15]|=bit
            with self.subTest(bit=bit),self.assertRaises(ValueError):validate_header(h,self.st,expected,'imbalance')
        w=self.words();w[1]=0x7fc00000
        with self.assertRaisesRegex(ValueError,'NONFINITE'):feature_values(self.h,w,self.st,expected,'normal')

    def test_zero_speed_is_not_synthesized_as_a_valid_measurement(self):
        self.x[38]=0.
        with self.assertRaisesRegex(ValueError,'ZERO_RPM'):feature_values(self.h,self.words(),self.st,self.expected(),'normal')

    def test_mode_frame_status_consistency_and_protection_phase_are_frozen(self):
        j=self.start();self.st['hard_inhibit']=False;self.write()
        with self.assertRaisesRegex(ValueError,'PROTECTION_PHASE'):self.store.check(j)
        h=list(self.h);h[19]=7
        with self.assertRaisesRegex(ValueError,'MODE_MISMATCH'):validate_header(h,self.st,j['context']['input_contract'],'normal')

    def test_boot_configuration_and_model_context_cannot_change(self):
        for change in ('boot','config','model'):
            with self.subTest(change=change):
                j=self.start();before=(self.root/'env').read_bytes();old=copy.deepcopy(self.document)
                if change=='boot':self.document['observation']['boot']='UNIT/other'
                elif change=='config':self.document['observation']['feature_words'][3]=99
                else:(self.root/'env').write_text('CHANGED')
                self.write()
                with self.assertRaisesRegex(ValueError,'CONTEXT'):self.store.check(j)
                self.store.cancel({'job_id':j['id']});self.document=old;self.st=self.document['observation']['status'];self.write();(self.root/'env').write_bytes(before)

    def test_sensor_pair_must_be_real_fresh_and_present(self):
        expected=self.expected();self.document['observation']['icm_diagnostics']['sensors'][1]['fresh']=False
        with self.assertRaisesRegex(ValueError,'INDEPENDENT_ICM'):live_input(self.document,self.now,expected)

    def test_normal_and_labeled_jobs_are_mutually_exclusive_and_type_isolated(self):
        j=self.start();self.assertTrue(self.normal.busy());self.assertEqual(self.normal.records(),[])
        with self.assertRaisesRegex(ValueError,'WRONG_LEARNING_CHANNEL'):self.normal.cancel({'job_id':j['id']})
        with self.assertRaisesRegex(ValueError,'ALREADY_IN_PROGRESS'):
            self.normal.start(dict(request_id=str(uuid.uuid4()),healthy_confirmed=True,context_fingerprint='unused'))
        j=self.store.claim(self.worker)
        with self.assertRaisesRegex(ValueError,'WRONG_LEARNING_CHANNEL'):self.normal.owned(j['id'],self.worker)
        self.normal.heartbeat('c'*32)
        self.assertEqual(self.store.records()[0]['state'],'PREPARING')

    def test_existing_normal_job_also_blocks_new_label_job(self):
        self.normal.start(dict(request_id=str(uuid.uuid4()),healthy_confirmed=True,
            context_fingerprint=self.normal.status()['context_fingerprint']))
        with self.assertRaisesRegex(ValueError,'ALREADY_IN_PROGRESS'):self.start()

    def test_same_episode_is_one_independent_group_and_cannot_change_label(self):
        j=self.exported(self.start(episode='ONE_REAL_EPISODE'))
        self.assertEqual(j['state'],'COLLECTED_WAITING_DATA');self.assertEqual(self.store.coverage(j['corpus_key'])['normal']['train'],1)
        again=self.start(episode='ONE_REAL_EPISODE');self.assertEqual(again['episode_split'],'train')
        self.exported(again);self.assertEqual(self.store.coverage(j['corpus_key'])['normal']['train'],1)
        with self.assertRaisesRegex(ValueError,'EPISODE_LABEL_CONFLICT'):self.start('imbalance','ONE_REAL_EPISODE')

    def test_splits_are_fixed_and_do_not_leak_or_manufacture_classes(self):
        rows=[self.exported(self.start(episode='PHYSICAL_'+str(i))) for i in range(4)]
        self.assertEqual([j['episode_split'] for j in rows],['train','train','validation','test'])
        self.assertEqual(self.store.coverage(rows[0]['corpus_key'])['normal'],dict(train=2,validation=1,test=1))
        self.assertTrue(all(j['state']=='COLLECTED_WAITING_DATA' for j in rows))
        self.assertTrue(all(m['label']!='normal' for m in rows[-1]['missing']))

    def test_host_cannot_claim_independent_episodes_that_do_not_exist(self):
        j=self.start();j=self.store.claim(self.worker)
        self.store.update(j['id'],self.worker,state='REGISTERING_DATA',sessions={'episode':{'ok':True,'status':{'session_id':'UNIT'}}},export_sha256='a'*64)
        coverage={label:dict(MINIMUM) for label in LABELS}
        with self.assertRaisesRegex(ValueError,'OVERCLAIMED'):
            self.store.finalize_collection(j['id'],self.worker,dict(corpus_key=j['corpus_key'],coverage=coverage,
                source='REAL_USER_DECLARED_LABELED_DIAGNOSTIC',dataset_sha256='e'*64,registered_session='UNIT',status='READY_TO_TRAIN'))

    def test_corpus_identity_separates_configuration_but_not_collection_phase(self):
        c=self.store.context();other=copy.deepcopy(c);other['input_contract']['controller_mode']='LOCKED'
        self.assertEqual(corpus_key(c),corpus_key(other))
        other['input_contract']['configuration_words'][5]=9
        self.assertNotEqual(corpus_key(c),corpus_key(other))

    def test_capture_request_is_raw_diagnostic_and_user_label_stays_separate(self):
        j=self.start('clog');self.store.claim(self.worker)
        self.rpc.side_effect=[dict(ok=True,status=dict(state='IDLE',boot='UNIT/collector')),
            dict(ok=True,status=dict(session_id=str(uuid.uuid4())))]
        self.store.capture_begin(j['id'],self.worker)
        p=self.rpc.call_args.args[1]['payload']
        self.assertEqual(p['label'],'unlabelled');self.assertEqual(p['capture_mode'],'DIAGNOSTIC')
        self.assertEqual(p['duration_s'],90);self.assertEqual(p['window_policy'],WINDOW_POLICY)
        self.assertFalse(self.store.records()[0]['controls_changed'])

    def test_mid_capture_invalid_sample_and_protection_change_are_not_hidden(self):
        j=self.start();source=self.root/'raw';source.mkdir();meta=dict(boot_id='UNIT/collector',
            configuration_words=j['context']['input_contract']['configuration_words'],bitstream_sha256='a'*64,
            capture_mode='DIAGNOSTIC',label_declared='unlabelled',qualified=False,window_policy=WINDOW_POLICY,
            preceding_frame_id=19,session_id='UNIT')
        row=dict(schema='cabinet-capture-frame-v1',source='REAL_FRM1_DECLARED',boot_id='UNIT/collector',
            session_id='UNIT',header=self.h,feature_words=self.words(),status=copy.deepcopy(self.st),gap_before=0)
        row['status']['input_validity']['pressure']=False
        (source/'frames.jsonl').write_text(json.dumps(row)+'\n')
        with self.assertRaisesRegex(ValueError,'PROCESS_SENSOR'):self.store.audit_capture(source,meta,{'frames':1},j)
        row['status']=copy.deepcopy(self.st);row['status']['hard_inhibit']=False
        (source/'frames.jsonl').write_text(json.dumps(row)+'\n')
        with self.assertRaisesRegex(ValueError,'PROTECTION_PHASE'):self.store.audit_capture(source,meta,{'frames':1},j)

    def test_api_requires_separate_control_auth_and_rejects_cross_origin(self):
        from cabinet.web import server
        calls=[];wb=SimpleNamespace(labeled_learning=self.store,action=lambda name,body:calls.append((name,body)) or {'state':'QUEUED'})
        service=SimpleNamespace(workbench=wb);http=server('127.0.0.1',0,service,token='r'*32,control_token='w'*32)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        self.addCleanup(http.server_close);self.addCleanup(http.shutdown)
        import http.client as client
        def call(headers):
            c=client.HTTPConnection('127.0.0.1',http.server_port,timeout=3)
            try:c.request('POST','/api/labeled-learning/start','{}',headers);r=c.getresponse();r.read();return r.status
            finally:c.close()
        headers={'Authorization':'Bearer '+'r'*32,'Content-Type':'application/json'}
        self.assertEqual(call(headers),403);headers['X-Cabinet-Control-Token']='w'*32
        headers['Origin']='http://attacker.invalid';self.assertEqual(call(headers),403)
        headers.pop('Origin');self.assertEqual(call(headers),200);self.assertEqual(calls[0][0],'labeled-start')

    def test_finalize_is_idempotent_after_terminal_reply_is_lost(self):
        j=self.exported(self.start())
        self.assertEqual(self.store.finalize_collection(j['id'],self.worker,j['corpus_summary']),j)
        changed=copy.deepcopy(j['corpus_summary']);changed['dataset_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'RETRY_SUMMARY_CHANGED'):
            self.store.finalize_collection(j['id'],self.worker,changed)

    def test_cancelled_episodes_do_not_consume_missing_validation_or_test_slots(self):
        for unused in range(5):
            j=self.start();self.store.cancel({'job_id':j['id']})
        first=self.exported(self.start());self.assertEqual(first['episode_split'],'train')
        second=self.exported(self.start());self.assertEqual(second['episode_split'],'train')
        failed=self.start();self.assertEqual(failed['episode_split'],'validation');self.store.cancel({'job_id':failed['id']})
        completed=self.exported(self.start());self.assertEqual(completed['episode_split'],'validation')
        self.assertEqual(self.start()['episode_split'],'test')

    def test_normal_learning_cannot_replace_active_classifier_owner(self):
        (self.root/'labeled-npu.env').write_text('ACTIVE_CLASSIFIER_FIXTURE')
        with self.assertRaisesRegex(ValueError,'CLASSIFIER_ACTIVE'):self.normal.context()
        self.assertTrue(self.store.status()['labels']['normal']['ready'])

    def test_clean_confirmed_rollback_can_fail_without_permanent_recovery_hold(self):
        j=self.start();self.store.claim(self.worker)
        self.store.update(j['id'],self.worker,state='DEPLOYING')
        save(self.store.folder(j['id'])/'switch.json',dict(state='PREVIOUS_MODEL_RESTORED'))
        self.assertEqual(self.store.fail(j['id'],self.worker,'UNIT_FAILURE')['state'],'FAILED')

    def test_complete_diagnostic_capture_exports_and_registers_without_promoting_raw_data(self):
        from host.labeled_dataset import register
        j=self.start('imbalance');self.store.claim(self.worker);session=str(uuid.uuid4())
        self.rpc.side_effect=[dict(ok=True,status=dict(state='IDLE',boot='UNIT/collector')),
            dict(ok=True,status=dict(session_id=session))]
        self.store.capture_begin(j['id'],self.worker);self.rpc.side_effect=None
        source=self.root/'captures'/session;source.mkdir(parents=True)
        meta=dict(schema='cabinet-capture-session-v1',session_id=session,device_id='UNIT',boot_id='UNIT/collector',
            configuration_words=j['context']['input_contract']['configuration_words'],bitstream_sha256='a'*64,
            capture_mode='DIAGNOSTIC',label_declared='unlabelled',qualified=False,window_policy=WINDOW_POLICY,
            preceding_frame_id=self.h[3],duration_s=90,label_reviewed=False)
        save(source/'session.json',meta);save(source/'feature_contract.json',dict(qualified=False,calibration_id=0,unit_fixture=True))
        with (source/'frames.jsonl').open('w') as output:
            for i in range(700):
                h=list(self.h);h[3]+=i+1;h[4]+=128*(i+1);st=copy.deepcopy(self.st);st['uptime_ms']=h[4]+50
                row=dict(schema='cabinet-capture-frame-v1',source='REAL_FRM1_DECLARED',boot_id='UNIT/collector',session_id=session,
                    header=h,feature_words=self.words(),status=st,gap_before=0,accepted=False,rejected_reasons=['DIAGNOSTIC_NOT_TRAINING'])
                output.write(json.dumps(row)+'\n')
        summary=dict(state='DIAGNOSTIC_SAVED',session_id=session,durable_frames=700,frames=700,elapsed_s=90,
            duration_s=90,gaps=0,missing_frames=0,window_policy=WINDOW_POLICY,reason='NOT_TRAINING_DATA',
            files_sha256={n:sha(source/n) for n in ('session.json','feature_contract.json','frames.jsonl')})
        save(source/'summary.json',summary);self.rpc.return_value=dict(ok=True,status=summary)
        captured=self.store.capture_poll(j['id'],self.worker);self.assertEqual(captured['state'],'CAPTURE_SAVED')
        exported=self.store.export(j['id'],self.worker);self.assertEqual(sha(exported['path']),exported['sha256'])
        corpus=register(self.store.folder(j['id']),self.root/'registry')
        finished=self.store.finalize_collection(j['id'],self.worker,corpus)
        self.assertEqual(finished['state'],'COLLECTED_WAITING_DATA');self.assertEqual(corpus['coverage']['imbalance']['train'],1)
        self.assertFalse(json.loads((self.store.folder(j['id'])/'captures/episode/session.json').read_text())['qualified'])

    def test_all_five_independent_episode_coverage_transitions_to_training(self):
        for label in LABELS:
            self.st['active']=['CONFIG_UNQUALIFIED','STOP_UNCONFIRMED']+(['STALL_CORROBORATED'] if label=='stall' else [])
            self.write()
            for i in range(4):
                final=self.exported(self.start(label,label+'_'+str(i)))
        self.assertEqual(final['state'],'TRAINING');self.assertEqual(final['missing'],[])
        self.assertEqual(final['corpus_summary']['coverage'],{label:dict(MINIMUM) for label in LABELS})

class LabeledCapturePolicyTests(unittest.TestCase):
    def test_labelled_window_policy_does_not_promote_raw_archives_to_real(self):
        from test_capture import CaptureTests
        fixture=CaptureTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        for mode,label in [('REAL','normal'),('DIAGNOSTIC','clog')]:
            with self.assertRaisesRegex(ValueError,'DIAGNOSTIC_UNLABELLED_ONLY'):
                fixture.begin(capture_mode=mode,label=label,window_policy=WINDOW_POLICY)
        fixture.begin(capture_mode='DIAGNOSTIC',label='unlabelled',window_policy=WINDOW_POLICY)
        fixture.observe();fixture.recorder.finish('COMPLETED','UNIT_ONLY',fixture.now)
        result=fixture.recorder.snapshot()
        self.assertEqual(result['state'],'DIAGNOSTIC_SAVED');self.assertFalse(result['qualified'])
        self.assertFalse(result['training_ready'])

if __name__=='__main__':unittest.main()
