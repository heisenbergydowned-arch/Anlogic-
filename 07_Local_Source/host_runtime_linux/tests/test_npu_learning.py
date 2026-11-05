"""Learning lifecycle and archive fixtures. No hardware acceptance claims."""
import copy
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
import uuid
from unittest.mock import patch
from types import SimpleNamespace
from normal_npu.learning import Learning,save,sha
from normal_npu.learning_deploy import unpack
from normal_npu.core import FEATURES,score,GROUPS

OLD=Path('/Users/heisenberg/Documents/Codex/2026-11-01/kan/work/r46_real_normal_npu_20261101')


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        with (OLD/'captures/test/frames.jsonl').open() as f:row=json.loads(next(f))
        expected=json.loads((OLD/'model_r3/provenance.json').read_text())['input_contract']
        x=struct.unpack('<39f',struct.pack('<39I',*row['feature_words']))
        self.document=dict(observation=dict(link='ONLINE',received_at=1000.,boot=row['boot_id'],status=row['status'],
            feature_words=expected['configuration_words'],frame=dict(state='RECEIVED_REAL',header=row['header'],values=dict(zip(FEATURES,x))),
            icm_diagnostics=dict(state='DIAGNOSTIC_ONLY',test=False,boot_id=expected['device_id'],snapshot_age_ms=0,
                sensors=[dict(channel=n,who=0x12,raw=[1,2,3],fresh=True,error=False,config_verified=True,
                              config_bad_mask=0,sample_age_ms=0) for n in ('A','B')])))
        self.document['observation'].update(bench=dict(state='IDLE',controls_enabled=False,output_never_applied=True),
            normal_reference_guard=dict(schema='cabinet-normal-reference-output-v1',boot=row['boot_id'],state='IDLE',
                safe_since_uptime_ms=0,status_uptime_ms=row['status']['uptime_ms'],bench_state='IDLE',bench_id=None))
        save(self.root/'state.json',self.document);save(self.root/'edge.json',dict(device_id=expected['device_id']))
        save(self.root/'platform.json',dict(device_id=expected['device_id'],pl_build_id=row['header'][26],bitstream_sha256='a'*64))
        (self.root/'env').write_text('fixture-not-an-executable-environment\n')
        self.now=1000.1;self.boot='TEST-OS-BOOT';self.worker='b'*32
        self.store=Learning(self.root/'learning',self.root/'edge.json',self.root/'state.json',self.root/'platform.json',
            self.root/'env',self.root/'socket',self.root/'captures',boot=lambda:self.boot,clock=lambda:self.now)
        self.rpc=patch('normal_npu.learning.rpc',return_value=dict(ok=True,status=dict(state='IDLE',session_id=None,boot=row['boot_id']))).start()
        self.addCleanup(patch.stopall);self.store.heartbeat(self.worker)

    def test_queued_or_unconfirmed_bench_cannot_create_learning_context(self):
        for state in ('QUEUED_NOT_APPLIED','ACTIVE_BENCH_NOT_CLOSED_LOOP','OUTPUT_STOP_UNCONFIRMED'):
            with self.subTest(state=state):
                self.document['observation']['bench']=dict(state=state,controls_enabled=False)
                save(self.root/'state.json',self.document)
                with self.assertRaises(ValueError):self.store.context()
                self.assertEqual(self.store.records(),[])

    def body(self):
        return dict(request_id=str(uuid.uuid4()),healthy_confirmed=True,context_fingerprint=self.store.status()['context_fingerprint'])

    def start(self): return self.store.start(self.body())

    def test_confirmation_is_required_and_input_is_not_self_labelled(self):
        body=self.body();body['healthy_confirmed']=False
        with self.assertRaisesRegex(ValueError,'CONFIRM_CURRENT'):self.store.start(body)
        self.assertEqual(self.store.records(),[])

    def test_one_click_persists_normal_declaration_and_is_idempotent(self):
        body=self.body();j=self.store.start(body)
        self.assertEqual(j,self.store.start(body));self.assertEqual(len(self.store.records()),1)
        self.assertEqual(j['created_sequence'],1)
        self.assertTrue(j['auto_deploy']);self.assertFalse(j['controls_changed'])
        with self.assertRaisesRegex(ValueError,'ALREADY_IN_PROGRESS'):self.start()
        body['context_fingerprint']='changed'
        with self.assertRaisesRegex(ValueError,'REQUEST_ID_REUSED'):self.store.start(body)

    def test_new_sequence_is_monotonic_within_boot_and_uses_max_not_count(self):
        first=self.start();self.store.cancel(dict(job_id=first['id']))
        p=self.store.folder(first['id'])/'job.json';record=json.loads(p.read_text())
        record['created_sequence']=7;save(p,record)
        self.now+=.1
        second=self.start()
        self.assertEqual(second['created_sequence'],8)
        self.assertEqual(second['created_at'],self.now)
        self.assertEqual([j['created_sequence'] for j in self.store.status()['jobs']],[7,8])

    def test_cross_boot_new_job_is_last_even_when_monotonic_time_is_lower(self):
        first=self.start();self.store.cancel(dict(job_id=first['id']))
        self.boot='SECOND-OS-BOOT';self.now=500.
        self.document['observation']['received_at']=499.9;save(self.root/'state.json',self.document)
        self.store.heartbeat(self.worker)
        second=self.start()
        self.assertLess(second['created_at'],first['created_at'])
        self.assertEqual(second['created_sequence'],2)
        self.assertEqual([j['id'] for j in self.store.status()['jobs']],[first['id'],second['id']])
        self.assertEqual(self.store.claim(self.worker)['id'],second['id'])

    def test_claim_uses_sequence_not_monotonic_timestamp(self):
        first=self.start();self.store.cancel(dict(job_id=first['id']))
        second=self.start()
        p=self.store.folder(first['id'])/'job.json';a=json.loads(p.read_text());a['state']='QUEUED';a['cancel_requested']=False;save(p,a)
        p=self.store.folder(second['id'])/'job.json';b=json.loads(p.read_text());b['created_at']=1.;save(p,b)
        self.assertEqual(self.store.claim(self.worker)['id'],first['id'])

    def test_idempotent_request_does_not_change_or_allocate_sequence(self):
        body=self.body();first=self.store.start(body);path=self.store.folder(first['id'])/'job.json'
        before=path.read_bytes();self.now+=.1
        self.assertEqual(self.store.start(body),first)
        self.assertEqual(path.read_bytes(),before)
        self.store.cancel(dict(job_id=first['id']))
        self.assertEqual(self.start()['created_sequence'],2)

    def test_legacy_history_requires_explicit_migration_without_mutating_records(self):
        body=self.body();first=self.store.start(body);new_body=self.body()
        p=self.store.folder(first['id'])/'job.json';legacy=json.loads(p.read_text())
        legacy.pop('created_sequence');legacy['state']='CANCELLED';save(p,legacy);before=p.read_bytes()
        # Existing request identity remains idempotent, including legacy jobs.
        self.assertEqual(self.store.start(body),legacy)
        for operation in (lambda:self.store.start(new_body),self.store.status,lambda:self.store.claim(self.worker)):
            with self.assertRaisesRegex(ValueError,'SEQUENCE_MIGRATION_REQUIRED'):operation()
        self.assertEqual(p.read_bytes(),before);self.assertEqual(len(self.store.records()),1)

    def test_invalid_or_duplicate_sequences_cannot_silently_reorder_history(self):
        first=self.start();self.store.cancel(dict(job_id=first['id']))
        second=self.start();self.store.cancel(dict(job_id=second['id']))
        p=self.store.folder(second['id'])/'job.json';record=json.loads(p.read_text())
        for sequence in (True,0,-1,'2',1):
            record['created_sequence']=sequence;save(p,record)
            with self.assertRaisesRegex(ValueError,'SEQUENCE_'):self.store.status()

    def test_host_offline_rejects_new_job(self):
        self.now+=46
        body=self.body()
        with self.assertRaisesRegex(ValueError,'TRAINING_HOST_OFFLINE'):self.store.start(body)

    def test_missing_sensor_and_synthetic_frames_do_not_enter_training(self):
        body=self.body()
        for mutate in (lambda d:d['observation']['frame']['header'].__setitem__(27,1),
                       lambda d:d['observation']['status']['input_validity'].__setitem__('pressure',False),
                       lambda d:d['observation']['icm_diagnostics']['sensors'][1].__setitem__('fresh',False)):
            d=copy.deepcopy(self.document);mutate(d);save(self.root/'state.json',d)
            with self.assertRaises(ValueError):self.store.start(body)
        self.assertEqual(self.store.records(),[])

    def test_changed_context_does_not_replay_queued_declaration(self):
        j=self.start();(self.root/'edge.json').write_text(json.dumps(dict(device_id='CHANGED')))
        self.assertIsNone(self.store.claim(self.worker))
        self.assertEqual(self.store.records()[0]['state'],'FAILED')

    def test_restart_and_reboot_interrupt_without_replaying(self):
        self.start();self.store.claim(self.worker);self.store.heartbeat('c'*32)
        self.assertEqual(self.store.records()[0]['state'],'INTERRUPTED')
        self.assertIsNone(self.store.claim('c'*32))

    def test_cancel_does_not_stop_someone_elses_capture(self):
        j=self.start();self.store.claim(self.worker)
        self.store.update(j['id'],self.worker,recording_session_id='ours')
        self.store.cancel(dict(job_id=j['id']))
        self.rpc.return_value=dict(ok=True,status=dict(state='RECORDING',session_id='other'))
        result=self.store.fail(j['id'],self.worker,'cancel');self.assertEqual(result['state'],'CANCELLED')
        self.assertFalse(any(c.args[1]['operation']=='stop' for c in self.rpc.call_args_list))

    def test_model_switch_is_not_cancelled_mid_transaction(self):
        j=self.start();self.store.claim(self.worker);self.store.update(j['id'],self.worker,state='HARDWARE_VALIDATING')
        with self.assertRaisesRegex(ValueError,'MODEL_SWITCH_IN_PROGRESS'):self.store.cancel(dict(job_id=j['id']))

    def test_recovery_required_cannot_be_cleared_by_worker_failure_or_restart(self):
        j=self.start();self.store.claim(self.worker)
        self.store.update(j['id'],self.worker,state='RECOVERY_REQUIRED',error='fixture retained owner')
        self.assertEqual(self.store.fail(j['id'],self.worker,'retry')['state'],'RECOVERY_REQUIRED')
        self.store.heartbeat('c'*32)
        self.assertEqual(self.store.records()[0]['state'],'RECOVERY_REQUIRED');self.assertTrue(self.store.busy())

    def test_deployment_start_is_idempotent_while_board_process_is_alive(self):
        import npu_learning_cli as cli
        j=self.start();self.store.claim(self.worker);self.store.update(j['id'],self.worker,state='HOST_VALIDATED')
        body=dict(job_id=j['id'],worker_id=self.worker)
        save(self.store.folder(j['id'])/'deploy-request.json',dict(body,operation='deploy'))
        with patch.object(cli,'process_alive',return_value=True),patch.object(cli.subprocess,'Popen') as popen:
            result=cli.launch(self.store,body)
            self.assertEqual(result['state'],'BOARD_DEPLOYMENT_RUNNING');popen.assert_not_called()

    def test_split_order_and_fault_recheck(self):
        j=self.start();self.store.claim(self.worker)
        with self.assertRaisesRegex(ValueError,'CAPTURE_SPLIT_ORDER'):self.store.capture_begin(j['id'],self.worker,'test')
        d=copy.deepcopy(self.document);d['observation']['status']['latched']=['OC_HARD'];save(self.root/'state.json',d)
        with self.assertRaisesRegex(ValueError,'HARDWARE_FAULT_ACTIVE'):self.store.capture_begin(j['id'],self.worker,'train')

    def test_new_model_cannot_export_partial_sessions(self):
        j=self.start();self.store.claim(self.worker)
        with self.assertRaisesRegex(ValueError,'THREE_REAL_SESSIONS'):self.store.export(j['id'],self.worker)

    def test_capture_keeps_diagnostic_label_separate_from_declared_normal(self):
        j=self.start();self.store.claim(self.worker)
        def call(path,body):
            if body['operation']=='status':return dict(ok=True,status=dict(state='IDLE',boot=self.document['observation']['boot']))
            self.assertEqual(body['payload']['label'],'unlabelled');self.assertEqual(body['payload']['capture_mode'],'DIAGNOSTIC')
            return dict(ok=True,status=dict(session_id=str(uuid.uuid4())))
        self.rpc.side_effect=call
        result=self.store.capture_begin(j['id'],self.worker,'train')
        self.assertEqual(result['state'],'CAPTURING_TRAIN');self.assertTrue(result['healthy_confirmed'])
        before=self.rpc.call_count
        self.assertEqual(self.store.capture_begin(j['id'],self.worker,'train'),result)
        self.assertEqual(self.rpc.call_count,before)

    def test_archive_rejects_paths_links_and_duplicate_names_before_extracting(self):
        for names,kind in [(['../escape'],tarfile.REGTYPE),(['manifest.json'],tarfile.SYMTYPE),(['manifest.json']*2,tarfile.REGTYPE)]:
            archive=self.root/'candidate.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                for name in names:
                    info=tarfile.TarInfo(name);info.type=kind;info.size=0;tar.addfile(info,io.BytesIO())
            target=self.root/'output'
            with self.assertRaises(ValueError):unpack(archive,target,sha(archive))
            self.assertFalse(target.exists())

    def test_live_gate_retains_failed_inputs_and_does_not_accept_short_sequence(self):
        from normal_npu.learning_deploy import wait_live
        j=self.start();d=dict(model_sha256='a'*64,valid=True,status='RUNNING',os_boot_id=self.boot,
            updated_at=1000.,frame_id=1,inference_count=1,execute_ms=.4,score=1.2,
            state='BASELINE_DEVIATION',domain_score=.5,input_clipped=0,neural_score=1.2,
            group_scores={'a':1.2},assessment='NEURAL_DEVIATION',input_values=[0.]*39)
        with patch('normal_npu.learning_deploy.time.monotonic',return_value=1000.), \
                patch('normal_npu.learning_deploy.time.sleep'),patch.object(self.store,'check'), \
                patch('normal_npu.learning_deploy.read_state',side_effect=[dict(d,inference_count=n,frame_id=n) for n in range(1,513)]):
            with self.assertRaisesRegex(ValueError,'ALARM_RATE'):wait_live('a'*64,self.store,j)
        report=json.loads((self.store.folder(j['id'])/'live-validation.json').read_text())
        self.assertEqual(report['observed_samples'],512);self.assertEqual(report['status'],'FAILED')
        self.assertEqual(report['samples'][0]['input_values'],[0.]*39)
        self.assertEqual(report['alarm_rate'],1.)

    def test_live_gate_accepts_same_budget_and_rejects_stale_or_duplicate_results(self):
        from normal_npu.learning_deploy import wait_live
        j=self.start();d=dict(model_sha256='a'*64,valid=True,status='RUNNING',os_boot_id=self.boot,
            updated_at=1000.,frame_id=1,inference_count=1,execute_ms=.4,score=.5,
            state='BASELINE_MATCH',domain_score=.5,input_clipped=0,neural_score=.5,
            group_scores={'a':.5},assessment='NORMAL_RECONSTRUCTION_MATCH',input_values=[0.]*39)
        rows=[dict(d,updated_at=998),d,d]+[dict(d,inference_count=n,frame_id=n,
            state='BASELINE_DEVIATION' if n<=25 else 'BASELINE_MATCH') for n in range(2,513)]
        with patch('normal_npu.learning_deploy.time.monotonic',return_value=1000.), \
                patch('normal_npu.learning_deploy.time.sleep'),patch.object(self.store,'check'), \
                patch('normal_npu.learning_deploy.read_state',side_effect=rows):
            report=wait_live('a'*64,self.store,j)
        self.assertEqual(report['observed_samples'],512);self.assertEqual(report['status'],'PASS')
        self.assertEqual(report['alarm_rate'],24/512)

    def test_live_job_summary_retains_gate_and_pins_full_evidence_without_vectors(self):
        from normal_npu.learning_deploy import live_summary
        report=dict(status='PASS',observed_samples=512,alarm_rate=.02,samples=[dict(input_values=[0.]*39)]*512)
        path=self.root/'live-validation.json';save(path,report)
        summary=live_summary(report,path)
        self.assertNotIn('samples',summary);self.assertLess(len(json.dumps(summary)),1024)
        self.assertEqual(summary['alarm_rate'],.02);self.assertEqual(summary['observed_samples'],512)
        self.assertEqual(summary['report_sha256'],sha(path));self.assertEqual(json.loads(path.read_text()),report)

    def test_completed_rollback_is_not_restarted_or_overwritten_by_failure_retry(self):
        from normal_npu.learning_deploy import recover_interrupted
        j=self.start();folder=self.store.folder(j['id'])
        (folder/'previous.env').write_bytes(self.store.env.read_bytes())
        save(folder/'previous-service.json',dict(active=True))
        transaction=dict(state='PREVIOUS_MODEL_RESTORED',error='ORIGINAL_VALIDATION_FAILURE')
        save(folder/'switch.json',transaction)
        with patch('normal_npu.learning_deploy.run',return_value=SimpleNamespace(stdout='active')) as commands:
            recover_interrupted(self.store,j)
        self.assertEqual(commands.call_count,1)
        self.assertEqual(commands.call_args.args[0],['systemctl','is-active','cabinet-normal-npu'])
        self.assertEqual(json.loads((folder/'switch.json').read_text()),transaction)

    def test_heartbeat_preserves_reconciled_model_commit_after_boot_change(self):
        j=self.start();self.store.claim(self.worker);self.store.update(j['id'],self.worker,state='DEPLOYING')
        def reconcile(store,job):
            job.update(state='COMPLETED');save(store.folder(job['id'])/'job.json',job);return True
        self.boot='NEXT-OS-BOOT'
        with patch('normal_npu.learning_deploy.recover_interrupted',side_effect=reconcile),patch.object(self.store,'_stop_owned') as stop:
            self.store.heartbeat(self.worker)
        self.assertEqual(self.store.records()[0]['state'],'COMPLETED');stop.assert_not_called()

    def test_failure_report_preserves_reconciled_model_commit(self):
        j=self.start();self.store.claim(self.worker);self.store.update(j['id'],self.worker,state='DEPLOYING')
        def reconcile(store,job):
            job.update(state='COMPLETED');save(store.folder(job['id'])/'job.json',job);return True
        with patch('normal_npu.learning_deploy.recover_interrupted',side_effect=reconcile),patch.object(self.store,'_stop_owned') as stop:
            result=self.store.fail(j['id'],self.worker,'job finalization interrupted')
        self.assertEqual(result['state'],'COMPLETED');self.assertEqual(self.store.records()[0]['state'],'COMPLETED');stop.assert_not_called()

    def test_neural_and_domain_results_are_distinct(self):
        norm=dict(output_scale=.1,output_zero_point=0)
        limits=dict(abs_z_limit=[1]*39,group_rmse={g:10 for g in GROUPS})
        result=score([2.]*39,[20]*39,norm,limits)
        self.assertAlmostEqual(result['neural_score'],0.)
        self.assertEqual(result['domain_score'],2.)
        self.assertEqual(result['assessment'],'OUTSIDE_TRAINING_DOMAIN')

    def test_failed_live_check_restores_previous_model_environment(self):
        from normal_npu import learning_deploy as deploy
        adapter=self.root/'adapter';adapter.write_bytes(b'HOST_FIXTURE_NOT_A_LIBRARY')
        before=dict(BUNDLE='/previous/bundle',BUNDLE_SHA256='d'*64,LIBRARY=str(adapter),
            LIBRARY_SHA256=sha(adapter),ADMISSION='/previous/admission',ADMISSION_SHA256='e'*64)
        self.store.env.write_text(''.join(k+'='+v+'\n' for k,v in before.items()))
        raw=self.store.env.read_bytes();j=self.start();self.store.claim(self.worker)
        self.store.update(j['id'],self.worker,state='HOST_VALIDATED')
        def command(args,**kwargs):
            active=args[:2]==['systemctl','is-active'] and args[2]=='cabinet-normal-npu'
            return SimpleNamespace(stdout='active' if active else '',returncode=0)
        def probe(args,**kwargs):
            out=Path(args[args.index('--output')+1]);out.mkdir();save(out/'validation.json',{})
            return SimpleNamespace(returncode=0)
        def persist(candidate,admission,target,pin):
            target.mkdir(parents=True);(target/'bundle').mkdir();(target/'admission.json').write_bytes(admission.read_bytes())
            return dict(bundle_path=str(target/'bundle'),admission_path=str(target/'admission.json'),admission_sha256=sha(target/'admission.json'))
        with patch.object(deploy,'persist_candidate',side_effect=persist),patch.object(deploy,'unpack',side_effect=lambda archive,dest,pin:dest.mkdir()), \
                patch.object(deploy,'validate_candidate',return_value=(None,{})), \
                patch.object(deploy,'run',side_effect=command) as commands,patch.object(deploy,'clean'), \
                patch.object(deploy.subprocess,'run',side_effect=probe),patch.object(deploy,'validate_report'), \
                patch.object(deploy,'wait_live',side_effect=ValueError('BAD_LIVE_RESULT')):
            with self.assertRaisesRegex(RuntimeError,'BAD_LIVE_RESULT; PREVIOUS_MODEL_RESTORED'):
                deploy.deploy(self.store,j['id'],self.worker,'f'*64,'a'*64,self.root/'models')
        self.assertEqual(self.store.env.read_bytes(),raw)
        switch=json.loads((self.store.folder(j['id'])/'switch.json').read_text())
        self.assertEqual(switch['state'],'PREVIOUS_MODEL_RESTORED')
        self.assertEqual(commands.call_args_list[-1].args[0],['systemctl','start','cabinet-normal-npu'])


if __name__=='__main__':unittest.main()
