"""Synthetic, isolated recovery tests. No board, training process or native NPU."""
import copy
import json
import shutil
import tarfile
import unittest
import uuid
from unittest.mock import patch
from normal_npu import recovery
from normal_npu.learning import save,sha
from tests import test_npu_learning as normal_fixture
from tests import test_labeled_learning as labeled_fixture
from tests import test_capture as capture_fixture
from tests.test_capture import packet
from cabinet.protocol import Frame
from cabinet.capture import CaptureRecorder,terminal_observation
from normal_npu.core import FEATURES
from hmi_daily.reader import publish


class DeadlineTests(unittest.TestCase):
    def test_three_second_deadline_is_bounded_and_does_not_accept_bad_data(self):
        now=[0.];published=[];calls=[]
        def probe():calls.append(now[0]);raise ValueError('SENSOR_OR_WINDOW_INVALID')
        with self.assertRaisesRegex(ValueError,'SENSOR_OR_WINDOW_INVALID'):
            recovery.await_stable(probe,published.append,clock=lambda:now[0],sleep=lambda s:now.__setitem__(0,now[0]+s))
        self.assertAlmostEqual(now[0],3.);self.assertLessEqual(len(calls),32)
        self.assertTrue(published[0]['waiting_stable']);self.assertFalse(published[-1]['waiting_stable'])
    def test_hard_errors_are_never_retried(self):
        for reason in ('TEST_FRAME_REJECTED','LEARNING_CONTEXT_CHANGED','HARDWARE_FAULT_ACTIVE','REFERENCE_WAIT_FULL_POST_TRIAL_WINDOW'):
            with self.subTest(reason=reason),patch.object(recovery.time,'sleep') as sleep,self.assertRaisesRegex(ValueError,reason):
                recovery.await_stable(lambda:(_ for _ in ()).throw(ValueError(reason)),lambda x:None)
            sleep.assert_not_called()


class NormalWaitTests(unittest.TestCase):
    setUp=normal_fixture.LearningTests.setUp
    body=normal_fixture.LearningTests.body
    start=normal_fixture.LearningTests.start

    def test_bad_sample_waits_then_recovers_and_public_status_explains_it(self):
        j=self.start();self.store.claim(self.worker);good=copy.deepcopy(self.document)
        self.document['observation']['frame']['header'][15]|=1;save(self.root/'state.json',self.document)
        observed=[]
        def sleep(seconds):
            observed.append(self.store.public_wait(j));save(self.root/'state.json',good)
        with patch.object(recovery.time,'sleep',side_effect=sleep):self.store.check(j)
        self.assertEqual(len(observed),1);self.assertEqual(observed[0]['display_state'],'WAITING_STABLE')
        self.assertEqual(observed[0]['waiting_reason_code'],'SENSOR_OR_WINDOW_INVALID')
        self.assertNotIn('waiting_stable',self.store.public_wait(j))
        self.assertEqual(self.store.records()[0]['state'],'PREPARING')

    def test_bad_window_cannot_mask_config_boot_or_protection_change(self):
        j=self.start()
        for mutate in (lambda d:d['observation']['feature_words'].__setitem__(3,991),
                       lambda d:d['observation'].__setitem__('boot','CHANGED'),
                       lambda d:d['observation']['status'].__setitem__('latched',['OC_HARD'])):
            d=copy.deepcopy(self.document);d['observation']['frame']['header'][15]|=1;mutate(d);save(self.root/'state.json',d)
            with patch.object(recovery.time,'sleep') as sleep,self.assertRaises(ValueError):self.store.check(j)
            sleep.assert_not_called()

    def test_cancel_is_seen_during_wait(self):
        j=self.start();self.document['observation']['frame']['header'][15]|=1;save(self.root/'state.json',self.document)
        def cancel(seconds):
            saved=self.store.records()[0];saved['cancel_requested']=True;save(self.store.folder(j['id'])/'job.json',saved)
        with patch.object(recovery.time,'sleep',side_effect=cancel),self.assertRaisesRegex(ValueError,'CANCEL_REQUESTED'):
            self.store.check(j)

    def test_actual_null_offline_publication_waits_then_recovers(self):
        j=self.start();publish(self.root,{'sequence':5,'link':'ERROR','message':'COLLECTOR_STALE'},None)
        seen=[]
        def restore(seconds):seen.append(self.store.public_wait(j));save(self.root/'state.json',self.document)
        with patch.object(recovery.time,'sleep',side_effect=restore):self.store.check(j)
        self.assertEqual(len(seen),1);self.assertEqual(seen[0]['waiting_reason_code'],'COLLECTOR_STALE')

    def test_null_snapshot_does_not_hide_fixed_identity_or_explicit_hard_errors(self):
        j=self.start()
        for message in ('PL_UPTIME_RESTART','HARDWARE_CONTEXT_CHANGED','PROTECTION_PHASE_CHANGED','SUBSCRIBER_ERROR'):
            publish(self.root,{'link':'ERROR','message':message},None)
            with self.subTest(message=message),patch.object(recovery.time,'sleep') as sleep,self.assertRaisesRegex(ValueError,'OFFLINE_REQUIRES_REVIEW'):
                self.store.check(j)
            sleep.assert_not_called()
        publish(self.root,{'link':'ERROR','message':'COLLECTOR_STALE'},None)
        for path in (self.store.config,self.store.platform,self.store.env):
            original=path.read_bytes();path.write_bytes(b'CHANGED_FIXED_IDENTITY')
            with self.subTest(path=path.name),patch.object(recovery.time,'sleep') as sleep,self.assertRaisesRegex(ValueError,'CONTEXT_CHANGED'):
                self.store.check(j)
            sleep.assert_not_called();path.write_bytes(original)
        self.boot='CHANGED_OS_BOOT'
        with patch.object(recovery.time,'sleep') as sleep,self.assertRaisesRegex(ValueError,'CONTEXT_CHANGED'):self.store.check(j)
        sleep.assert_not_called()


class RetryFixture:
    def failed_capture(self,j,split,reason='COLLECTOR_GAP',row_mutation=None):
        identity=str(uuid.uuid4());source=self.store.captures/identity;source.mkdir(parents=True)
        o=self.document['observation'];h=o['frame']['header']
        row=dict(schema='cabinet-capture-frame-v1',source='REAL_FRM1_DECLARED',boot_id=o['boot'],session_id=identity,
            header=h,status=copy.deepcopy(o['status']),feature_words=[0]*39,gap_before=0)
        if row_mutation:row_mutation(row)
        policy='INDEPENDENT_LABELED_NPU_WINDOWS' if j.get('kind')=='labeled_classifier' else 'INDEPENDENT_NORMAL_NPU_WINDOWS'
        save(source/'session.json',dict(session_id=identity,boot_id=o['boot'],configuration_words=o['feature_words'],
            bitstream_sha256='a'*64,capture_mode='DIAGNOSTIC',label_declared='unlabelled',qualified=False,window_policy=policy))
        save(source/'feature_contract.json',{'qualified':False,'fixture':True})
        (source/'frames.jsonl').write_text(json.dumps(row)+'\n')
        status=dict(state='ABORTED',reason=reason,session_id=identity,frames=1,durable_frames=1,elapsed_s=1,duration_s=90,
            gaps=1,missing_frames=1,window_policy=policy,boot=o['boot'])
        terminal=terminal_observation(dict(sequence=1,boot=o['boot'],link='ONLINE',status=o['status'],
            configuration_words=o['feature_words'],test=False,frame=Frame(tuple(h),tuple([.1]*39))))
        save(source/'summary.json',dict(status,terminal_observation=terminal,
            files_sha256={n:sha(source/n) for n in ('session.json','feature_contract.json','frames.jsonl')}))
        j=self.store.update(j['id'],self.worker,state='CAPTURING_'+split.upper(),recording_split=split,recording_session_id=identity)
        self.starts=[]
        def rpc(path,body):
            if body['operation']=='status':return dict(ok=True,status=status)
            self.starts.append(body);return dict(ok=True,status={'session_id':str(uuid.uuid4())})
        self.rpc.side_effect=rpc
        return j,status,source

class NormalRetryTests(RetryFixture,unittest.TestCase):
    setUp=normal_fixture.LearningTests.setUp
    body=normal_fixture.LearningTests.body
    start=normal_fixture.LearningTests.start

    def test_only_failed_split_retries_twice_with_immutable_failed_evidence(self):
        j=self.start();j=self.store.claim(self.worker)
        prior={'train':{'ok':True,'status':{'session_id':'FIXTURE_PREVIOUS_TRAIN'}}}
        j=self.store.update(j['id'],self.worker,sessions=prior)
        for attempt in range(3):
            j,s,source=self.failed_capture(j,'calibration')
            before=(source/'frames.jsonl').read_bytes()
            if attempt==2:
                with self.assertRaisesRegex(ValueError,'CAPTURE_RETRY_LIMIT'):self.store.capture_poll(j['id'],self.worker)
                self.assertEqual(self.starts,[])
            else:
                j=self.store.capture_poll(j['id'],self.worker)
                self.assertEqual(j['state'],'CAPTURING_CALIBRATION');self.assertEqual(len(self.starts),1)
                self.assertTrue(j['healthy_confirmed']);self.assertEqual(self.starts[0]['payload']['duration_s'],90)
            saved=self.store.records()[0];self.assertEqual(saved['sessions'],prior)
            self.assertEqual(len(saved['capture_attempts']),attempt+1)
            evidence=saved['capture_attempts'][-1]
            self.assertFalse(evidence['used_for_training']);self.assertEqual((source/'frames.jsonl').read_bytes(),before)
            from pathlib import Path
            self.assertEqual((Path(evidence['evidence'])/'frames.jsonl').read_bytes(),before)

    def test_model_scores_and_unsafe_capture_causes_do_not_trigger_retries(self):
        j=self.start();j=self.store.claim(self.worker)
        for reason in ('POST_DEPLOY_CURRENT_NORMAL_ALARM_RATE','CONFIGURATION_CHANGED','COLLECTOR_RESTART_OR_OFFLINE','FRAME_ID_GAP_OR_DUPLICATE','CAPTURE_QUEUE_OVERFLOW'):
            j,s,source=self.failed_capture(j,'test',reason)
            with self.subTest(reason=reason),self.assertRaises(ValueError):self.store.capture_poll(j['id'],self.worker)
            self.assertEqual(self.starts,[])
        self.assertNotIn('capture_attempts',self.store.records()[0])

    def test_a_past_protection_change_cannot_be_hidden_by_current_recovery(self):
        j=self.start();j=self.store.claim(self.worker)
        j,s,source=self.failed_capture(j,'train',row_mutation=lambda row:row['status'].__setitem__('latched',['OC_HARD']))
        with self.assertRaisesRegex(ValueError,'PROTECTION_CHANGED'):self.store.capture_poll(j['id'],self.worker)
        self.assertEqual(self.starts,[])


class LabeledRetryTests(RetryFixture,unittest.TestCase):
    setUp=labeled_fixture.LabeledLearningTests.setUp
    body=labeled_fixture.LabeledLearningTests.body
    start=labeled_fixture.LabeledLearningTests.start

    def test_recollection_retains_label_episode_and_fixed_split(self):
        j=self.start('imbalance','ONE_SYNTHETIC_EPISODE');j=self.store.claim(self.worker)
        j,s,source=self.failed_capture(j,'episode')
        result=self.store.capture_poll(j['id'],self.worker)
        self.assertEqual(result['label'],'imbalance');self.assertEqual(result['episode_id'],'ONE_SYNTHETIC_EPISODE')
        self.assertEqual(result['episode_split'],j['episode_split']);self.assertEqual(result['sessions'],{})
        self.assertEqual(self.starts[0]['payload']['label'],'unlabelled')
        self.assertEqual(result['state'],'CAPTURING_EPISODE')

    def test_changed_protection_is_hard_even_when_sampling_window_is_bad(self):
        j=self.start();self.st['hard_inhibit']=False;self.h[15]|=1;save(self.root/'state.json',self.document)
        with patch.object(recovery.time,'sleep') as sleep,self.assertRaisesRegex(ValueError,'PROTECTION_PHASE'):
            self.store.check(j)
        sleep.assert_not_called()

    def test_labeled_actual_null_offline_publication_waits_then_recovers(self):
        j=self.start();publish(self.root,{'link':'ERROR','message':'COLLECTOR_STALE'},None)
        with patch.object(recovery.time,'sleep',side_effect=lambda unused:save(self.root/'state.json',self.document)) as sleep:
            self.store.check(j)
        self.assertEqual(sleep.call_count,1)
        publish(self.root,{'link':'ERROR','message':'COLLECTOR_STALE'},None)
        (self.root/'labeled-npu.env').write_text('CHANGED_CLASSIFIER_IDENTITY')
        with patch.object(recovery.time,'sleep') as sleep,self.assertRaisesRegex(ValueError,'CONTEXT_CHANGED'):self.store.check(j)
        sleep.assert_not_called()


class TerminalCaptureTests(unittest.TestCase):
    setUp=normal_fixture.LearningTests.setUp
    body=normal_fixture.LearningTests.body
    start=normal_fixture.LearningTests.start

    def captured_gap(self,change=None,overflow=False):
        j=self.start();j=self.store.claim(self.worker);o=self.document['observation']
        contract=capture_fixture.contract();contract.update(pl_build_id=o['frame']['header'][26])
        recorder=CaptureRecorder({'device_id':j['context']['input_contract']['device_id'],'contract':contract},
            self.store.captures,self.root/'unused.sock',contract)
        self.store.captures.mkdir(parents=True,exist_ok=True)
        def packet(seq,index):
            h=list(o['frame']['header']);h[3]+=index;h[4]+=128*index
            st=copy.deepcopy(o['status']);st['uptime_ms']+=128*index
            return dict(sequence=seq,boot=o['boot'],link='ONLINE',received_at=self.now+.128*index,
                now_ms=st['uptime_ms'],frame=Frame(tuple(h),tuple(o['frame']['values'][n] for n in FEATURES)),
                configuration_words=o['feature_words'],status=st,mailbox={'queued_frames':1,'dropped_frames':0},test=False,rejected=[])
        first=packet(1,0);recorder.observe(first,first['received_at'])
        recorder.begin(dict(expected_boot=o['boot'],installation_id='UNIT',operator='UNIT',label='unlabelled',duration_s=90,
            capture_mode='DIAGNOSTIC',window_policy='INDEPENDENT_NORMAL_NPU_WINDOWS',bitstream_sha256=j['context']['bitstream_sha256'],
            calibration_evidence_sha256=None,note='SYNTHETIC UNIT REPLAY, NOT HARDWARE'),self.now)
        safe=packet(2,1);recorder.observe(safe,safe['received_at'])
        trigger=packet(4,2)
        if change:change(trigger)
        if overflow:
            pending=packet(3,2)
            for unused in range(recorder.queue.maxsize):recorder.submit(pending)
            recorder.submit(trigger)
            observed=recorder.queue.get_nowait();recorder.observe(observed,observed['received_at'])
        else:
            observed=trigger;recorder.observe(trigger,trigger['received_at'])
        status=recorder.snapshot()
        self.assertEqual(status['reason'],'CAPTURE_QUEUE_OVERFLOW' if overflow else 'COLLECTOR_GAP')
        self.assertEqual(status['frames'],1)
        summary=json.loads((recorder.session_dir/'summary.json').read_text())
        self.assertEqual(summary['terminal_observation']['sequence'],observed['sequence'])
        self.assertEqual(summary['terminal_observation']['status'],observed['status'])
        j=self.store.update(j['id'],self.worker,state='CAPTURING_TRAIN',recording_split='train',recording_session_id=status['session_id'])
        self.starts=[]
        def rpc(path,body):
            if body['operation']=='status':return {'ok':True,'status':status}
            self.starts.append(body);return {'ok':True,'status':{'session_id':str(uuid.uuid4())}}
        self.rpc.side_effect=rpc
        return j,recorder.session_dir,summary

    def test_same_gap_packet_overcurrent_cannot_be_erased_by_current_recovery(self):
        j,source,summary=self.captured_gap(lambda p:p['status'].update(latched=['OC_HARD'],hard_inhibit=True))
        with self.assertRaisesRegex(ValueError,'TERMINAL_CONTEXT_OR_PROTECTION'):self.store.capture_poll(j['id'],self.worker)
        self.assertEqual(self.starts,[])
        self.assertEqual(json.loads((source/'frames.jsonl').read_text())['status']['latched'],[])
        self.assertEqual(summary['terminal_observation']['status']['latched'],['OC_HARD'])

    def test_same_gap_packet_boot_change_cannot_be_erased_by_current_recovery(self):
        j,source,summary=self.captured_gap(lambda p:p.update(boot='DIFFERENT/collector'))
        with self.assertRaisesRegex(ValueError,'TERMINAL_CONTEXT_OR_PROTECTION'):self.store.capture_poll(j['id'],self.worker)
        self.assertEqual(self.starts,[])

    def test_ordinary_gap_retains_hash_bound_terminal_evidence_and_can_retry(self):
        j,source,summary=self.captured_gap()
        result=self.store.capture_poll(j['id'],self.worker)
        self.assertEqual(len(self.starts),1);self.assertEqual(result['state'],'CAPTURING_TRAIN')
        attempt=result['capture_attempts'][0]
        self.assertEqual(attempt['files_sha256']['summary.json'],sha(source/'summary.json'))
        self.assertFalse(attempt['used_for_training'])

    def test_missing_terminal_evidence_cannot_authorize_recollection(self):
        j,source,summary=self.captured_gap();summary.pop('terminal_observation');save(source/'summary.json',summary)
        with self.assertRaisesRegex(ValueError,'TERMINAL_EVIDENCE_REQUIRED'):self.store.capture_poll(j['id'],self.worker)
        self.assertEqual(self.starts,[])

    def test_queue_overflow_retains_dropped_hard_event_and_never_retries(self):
        j,source,summary=self.captured_gap(lambda p:p['status'].update(latched=['OC_HARD'],hard_inhibit=True),overflow=True)
        self.assertEqual(summary['terminal_observation']['status']['latched'],[])
        self.assertEqual(summary['overflow_observation']['sequence'],4)
        self.assertEqual(summary['overflow_observation']['status']['latched'],['OC_HARD'])
        self.assertEqual(summary['overflow_dropped_packets'],1)
        with self.assertRaisesRegex(ValueError,'QUEUE_OVERFLOW_REQUIRES_CONDITION_REVIEW'):
            self.store.capture_poll(j['id'],self.worker)
        self.assertEqual(self.starts,[])


class CalibrationBarrierTests(RetryFixture,unittest.TestCase):
    setUp=normal_fixture.LearningTests.setUp
    body=normal_fixture.LearningTests.body
    start=normal_fixture.LearningTests.start

    def ready(self):
        j=self.start();j=self.store.claim(self.worker);sessions={}
        for split in ('train','calibration'):
            j,status,source=self.failed_capture(j,split)
            status.update(state='DIAGNOSTIC_SAVED',reason='NOT_TRAINING_DATA')
            summary=json.loads((source/'summary.json').read_text());summary.update(status);save(source/'summary.json',summary)
            target=self.store.folder(j['id'])/'captures'/split;target.parent.mkdir(exist_ok=True)
            shutil.copytree(str(source),str(target))
            sessions[split]={'ok':True,'status':status}
        j=self.store.update(j['id'],self.worker,state='CAPTURE_SAVED',recording_session_id=None,sessions=sessions)
        return j

    def report(self,j,decision):
        exported=self.store.export_calibration_check(j['id'],self.worker)
        j=self.store.records()[0];p=j['calibration_precheck']
        result=dict(schema='cabinet-normal-calibration-input-check-v1',policy={'schema':'cabinet-normal-calibration-input-policy-v1'},
            status=decision,input_contract=j['context']['input_contract'],source_sha256=p['source_sha256'],test_read=False,model_scores_used=False,
            reason_code='CALIBRATION_TRANSIENT_INPUT_COVERAGE' if decision=='RETRY_CALIBRATION_TRANSIENT' else 'FIXTURE')
        from pathlib import Path
        path=Path(exported['report_path']);save(path,result)
        return j,exported,path

    def test_test_capture_requires_quality_pass_and_export_never_contains_test(self):
        j=self.ready()
        with self.assertRaisesRegex(ValueError,'PRECHECK_REQUIRED'):self.store.capture_begin(j['id'],self.worker,'test')
        j,exported,report=self.report(j,'PASS_CALIBRATION_INPUT_QUALITY')
        with tarfile.open(exported['path']) as archive:
            self.assertTrue(all('/test' not in m.name for m in archive.getmembers()))
        self.assertEqual(len(j['calibration_precheck']['source_sha256']),10)
        result=self.store.calibration_check_result(j['id'],self.worker,sha(report))
        self.assertEqual(result,self.store.calibration_check_result(j['id'],self.worker,sha(report)))
        self.assertEqual(self.store.capture_begin(j['id'],self.worker,'test')['state'],'CAPTURING_TEST')

    def test_calibration_retry_preserves_train_and_is_idempotent_without_test(self):
        j=self.ready();prior=copy.deepcopy(j['sessions']['train'])
        j,exported,report=self.report(j,'RETRY_CALIBRATION_TRANSIENT')
        result=self.store.calibration_check_result(j['id'],self.worker,sha(report))
        self.assertEqual(result['state'],'CAPTURING_CALIBRATION');self.assertEqual(set(result['sessions']),{'train'})
        self.assertEqual(result['sessions']['train'],prior);self.assertEqual(len(result['capture_attempts']),1)
        self.assertEqual(self.store.calibration_check_result(j['id'],self.worker,sha(report)),result)
        self.assertEqual(len(self.starts),1)
        self.assertFalse((self.store.folder(j['id'])/'captures/test').exists())
        self.assertTrue((report.parent/'rejected-calibration'/'frames.jsonl').is_file())

    def test_precheck_cannot_hide_test_use_or_change_export_provenance(self):
        j=self.ready();j,exported,path=self.report(j,'PASS_CALIBRATION_INPUT_QUALITY')
        original=json.loads(path.read_text())
        for field,value in [('test_read',True),('source_sha256',{})]:
            bad=copy.deepcopy(original);bad[field]=value;save(path,bad)
            with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):self.store.calibration_check_result(j['id'],self.worker,sha(path))
        self.assertEqual(self.starts,[])

    def test_sustained_distribution_change_requires_review_without_retry(self):
        j=self.ready();j,exported,path=self.report(j,'REVIEW_CONDITION_REQUIRED')
        for unused in range(2):
            with self.assertRaisesRegex(ValueError,'CONDITION_REVIEW_REQUIRED'):
                self.store.calibration_check_result(j['id'],self.worker,sha(path))
        self.assertEqual(self.starts,[]);self.assertNotIn('capture_attempts',self.store.records()[0])

    def test_quality_retry_shares_transport_retry_budget(self):
        j=self.ready();self.store.update(j['id'],self.worker,capture_attempts=[{'split':'calibration'},{'split':'calibration'}])
        j,exported,path=self.report(j,'RETRY_CALIBRATION_TRANSIENT')
        with self.assertRaisesRegex(ValueError,'CAPTURE_RETRY_LIMIT'):
            self.store.calibration_check_result(j['id'],self.worker,sha(path))
        self.assertEqual(self.starts,[]);self.assertEqual(len(self.store.records()[0]['capture_attempts']),3)


class PrefixBudgetTests(unittest.TestCase):
    setUp=capture_fixture.CaptureTests.setUp
    observe=capture_fixture.CaptureTests.observe
    begin=capture_fixture.CaptureTests.begin
    payload=capture_fixture.CaptureTests.payload

    def test_five_early_missing_windows_can_recover_to_final_two_percent_budget(self):
        self.begin(capture_mode='DIAGNOSTIC',label='unlabelled',duration_s=90,window_policy='INDEPENDENT_NORMAL_NPU_WINDOWS')
        for unused in range(300):
            value=packet(self.sequence+1,self.now+.128);h=list(value['frame'].header);h[3]+=5
            self.observe(frame=Frame(tuple(h),value['frame'].values))
        self.recorder.finish('COMPLETED','DURATION_REACHED',self.now)
        result=self.recorder.snapshot();self.assertEqual(result['state'],'DIAGNOSTIC_SAVED')
        self.assertEqual(result['missing_frames'],5);self.assertFalse(result['qualified'])

    def test_final_loss_still_fails_even_if_prefix_was_allowed(self):
        self.begin(capture_mode='DIAGNOSTIC',label='unlabelled',duration_s=90,window_policy='INDEPENDENT_NORMAL_NPU_WINDOWS')
        value=packet(self.sequence+1,self.now+.128);h=list(value['frame'].header);h[3]+=5
        self.observe(frame=Frame(tuple(h),value['frame'].values))
        self.assertEqual(self.recorder.snapshot()['state'],'RECORDING')
        self.recorder.finish('COMPLETED','DURATION_REACHED',self.now)
        self.assertEqual(self.recorder.snapshot()['reason'],'INDEPENDENT_WINDOW_LOSS_BUDGET')

if __name__=='__main__':unittest.main()
