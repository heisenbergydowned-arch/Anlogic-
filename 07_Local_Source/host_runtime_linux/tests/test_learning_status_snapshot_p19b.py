"""Request-local status reuse with synthetic fixtures, never hardware evidence."""
import copy
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from normal_npu.learning import save
from labeled_npu.learning import corpus_key
from labeled_npu.core import LABELS
from commissioning.workbench import Workbench
from tests import test_labeled_learning as fixture


class StatusSnapshotTests(unittest.TestCase):
    setUp=fixture.LabeledLearningTests.setUp

    def job(self,kind='normal',state='COMPLETED',sequence=1,**changes):
        job=dict(id=uuid.uuid4().hex,kind=kind,state=state,created_sequence=sequence,
                 created_at=self.now,updated_at=self.now,progress_percent=100,
                 label='normal',episode_id=str(uuid.uuid4()),episode_split='train',
                 context=self.store.context(),corpus_key=corpus_key(self.store.context()),collection_finalized=True)
        job.update(changes);folder=self.store.folder(job['id']);folder.mkdir()
        save(folder/'job.json',job);return job

    def workbench(self):
        work=Workbench(self.root/'workbench',self.root/'edge.json',state_path=self.root/'state.json')
        work.learning=self.normal;work.labeled_learning=self.store;return work

    def reads(self):
        original=Path.read_text;paths=[]
        def read(path,*args,**kwargs):paths.append(path);return original(path,*args,**kwargs)
        return paths,patch.object(Path,'read_text',read)

    def test_normal_status_reads_history_and_heartbeat_once(self):
        normal=self.job();self.job('labeled_classifier')
        paths,reader=self.reads()
        with reader,patch.object(self.normal,'all_records',wraps=self.normal.all_records) as scan,patch.object(self.normal,'worker_online',side_effect=AssertionError('unexpected reread')):
            status=self.normal.status()
        self.assertEqual(scan.call_count,1)
        self.assertEqual(sum(p.name=='worker.json' for p in paths),1)
        self.assertEqual(sum(p.name=='job.json' for p in paths),2)
        self.assertEqual([j['id'] for j in status['jobs']],[normal['id']]);self.assertTrue(status['ready'])

    def test_labeled_reuses_history_but_still_checks_every_label(self):
        from labeled_npu import learning
        self.job();labeled=self.job('labeled_classifier')
        paths,reader=self.reads()
        with reader,patch.object(self.store,'all_records',wraps=self.store.all_records) as scan,patch.object(learning,'live_input',wraps=learning.live_input) as validate:
            status=self.store.status()
        self.assertEqual(scan.call_count,1);self.assertEqual(sum(p.name=='worker.json' for p in paths),1)
        self.assertEqual([c[0][3] for c in validate.call_args_list],[None]+list(LABELS))
        self.assertEqual(status['coverage']['normal']['train'],1)
        self.assertEqual([j['id'] for j in status['jobs']],[labeled['id']])
        self.assertFalse(status['labels']['stall']['ready'])
        self.assertEqual(status['labels']['stall']['reason'],'STALL_LABEL_REQUIRES_FG_UNKNOWN_OR_CURRENT_CORROBORATION')

    def test_missing_historical_contract_does_not_hide_current_status(self):
        job=self.job('labeled_classifier');job.pop('context')
        save(self.store.folder(job['id'])/'job.json',job)
        status=self.store.status();history=status['historical_corpora'][0]
        self.assertTrue(status['ready']);self.assertFalse(history['contract_available'])
        self.assertFalse(history['current_contract'])
        self.assertEqual(history['contract_error'],'HISTORICAL_CONTRACT_UNAVAILABLE')
        self.assertEqual(history['verified_archives'],0)

    def test_workbench_shares_one_snapshot_and_next_request_reads_new_history(self):
        work=self.workbench();paths,reader=self.reads()
        with reader,patch.object(self.normal,'all_records',wraps=self.normal.all_records) as normal_scan,patch.object(self.store,'all_records',wraps=self.store.all_records) as labeled_scan:
            first=work.status()
            self.assertTrue(first['npu_learning']['ready']);self.assertTrue(first['labeled_learning']['ready'])
            self.job('labeled_classifier','QUEUED')
            second=work.status()
        self.assertEqual(normal_scan.call_count,2);self.assertEqual(labeled_scan.call_count,0)
        self.assertEqual(sum(p.name=='worker.json' for p in paths),2)
        self.assertFalse(second['npu_learning']['ready']);self.assertFalse(second['labeled_learning']['ready'])

    def test_cross_kind_active_jobs_keep_both_start_buttons_disabled(self):
        for kind in ('normal','labeled_classifier'):
            job=self.job(kind,'QUEUED')
            try:
                snapshot=self.normal.status_snapshot()
                self.assertFalse(self.normal.status(snapshot)['ready'])
                status=self.store.status(snapshot)
                self.assertFalse(status['ready']);self.assertFalse(any(s['ready'] for s in status['labels'].values()))
            finally:(self.store.folder(job['id'])/'job.json').unlink()

    def test_terminal_waiting_file_is_not_opened_but_active_wait_is_visible(self):
        terminal=self.job(capture_attempts={'train':2},progress_detail='retained evidence')
        active=self.job('labeled_classifier','CAPTURING_EPISODE')
        for job in (terminal,active):
            save(self.store.folder(job['id'])/'waiting.json',dict(os_boot_id=self.boot,waiting_stable=True,
                 waiting_since=1000.,waiting_deadline=1003.,display_state='WAITING_STABLE'))
        paths,reader=self.reads()
        with reader,patch('normal_npu.learning.time.monotonic',return_value=1000.2):
            result=self.normal.public_wait(terminal);waiting=self.store.public_wait(active)
        self.assertEqual(result,{'capture_attempts':{'train':2},'progress_detail':'retained evidence'})
        self.assertTrue(waiting['waiting_stable'])
        self.assertEqual([p for p in paths if p.name=='waiting.json'],[self.store.folder(active['id'])/'waiting.json'])

    def test_heartbeat_is_rechecked_after_status_work_for_both_channels(self):
        self.job();self.job('labeled_classifier')
        for store in (self.normal,self.store):
            self.now=1000.1;original=store.public_wait
            def delay(job):self.now=1045.2;return original(job)
            with patch.object(store,'public_wait',side_effect=delay):status=store.status()
            self.assertFalse(status['worker_online']);self.assertFalse(status['ready'])
            self.assertFalse(any(s['ready'] for s in status.get('labels',{}).values()))

    def test_workbench_rechecks_first_channel_after_second_channel_delay(self):
        work=self.workbench();original=self.store.status
        def delayed(snapshot=None):
            result=original(snapshot);self.now=1045.2;return result
        with patch.object(self.store,'status',side_effect=delayed):result=work.status()
        for name in ('npu_learning','labeled_learning'):
            self.assertFalse(result[name]['worker_online']);self.assertFalse(result[name]['ready'])

    def test_raw_heartbeat_identity_future_malformed_and_exact_expiry_boundaries(self):
        for heartbeat,age,expected in (({'boot_id':self.boot,'updated_at':1000.},44.999,True),
                ({'boot_id':self.boot,'updated_at':1000.},45.,False),
                ({'boot_id':self.boot,'updated_at':1000.},-.01,False),
                ({'boot_id':'wrong','updated_at':1000.},.1,False),
                ({'boot_id':self.boot,'updated_at':'bad'},.1,False),(None,.1,False),([], .1,False)):
            save(self.store.root/'worker.json',heartbeat);snapshot=self.normal.status_snapshot();self.now=1000.+age
            with self.subTest(heartbeat=heartbeat,age=age):
                result=self.normal.refresh_status_worker(dict(ready=True),snapshot)
                self.assertEqual(result['worker_online'],expected);self.assertEqual(result['ready'],expected)

    def test_same_request_does_not_replace_raw_heartbeat_with_later_file(self):
        snapshot=self.normal.status_snapshot()
        save(self.store.root/'worker.json',dict(boot_id=self.boot,updated_at=1045.))
        self.now=1045.2
        self.assertFalse(self.normal.refresh_status_worker(dict(ready=True),snapshot)['ready'])
        self.assertTrue(self.normal.refresh_status_worker(dict(ready=True),self.normal.status_snapshot())['ready'])

    def test_snapshot_cannot_be_reused_for_a_different_learning_root(self):
        snapshot=self.normal.status_snapshot();snapshot.root=self.root/'different'
        for store in (self.normal,self.store):
            with self.assertRaisesRegex(ValueError,'STATUS_SNAPSHOT_ROOT_MISMATCH'):store.status(snapshot)

    def test_sequence_validation_remains_per_kind_and_rejects_duplicate_within_kind(self):
        self.job();self.job('labeled_classifier')
        snapshot=self.normal.status_snapshot()
        self.normal.status(snapshot);self.store.status(snapshot)
        self.job('labeled_classifier',sequence=1)
        with self.assertRaisesRegex(ValueError,'SEQUENCE_INVALID_DUPLICATE'):self.store.status()

    def test_coverage_conflicting_episode_still_rejected(self):
        first=self.job('labeled_classifier')
        self.job('labeled_classifier',sequence=2,episode_id=first['episode_id'],label='clog')
        with self.assertRaisesRegex(ValueError,'EPISODE_LABEL_OR_SPLIT_CONFLICT'):self.store.status()

    def test_start_rechecks_new_job_instead_of_using_previous_ready_snapshot(self):
        ready=self.normal.status()
        self.job('labeled_classifier','QUEUED')
        body=dict(request_id=str(uuid.uuid4()),healthy_confirmed=True,context_fingerprint=ready['context_fingerprint'])
        with self.assertRaisesRegex(ValueError,'LEARNING_ALREADY_IN_PROGRESS'):self.normal.start(body)


if __name__=='__main__':unittest.main()
