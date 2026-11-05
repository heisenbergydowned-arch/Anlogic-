"""Isolated null-envelope regression; synthetic fixtures, never board evidence."""
import copy
import json
from pathlib import Path
import signal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hmi_daily.reader import publish
from normal_npu.core import GROUPS, collector_observation, live_input
from normal_npu.learning import save
from tests import test_labeled_learning as fixture


class NullCollectorTests(unittest.TestCase):
    setUp=fixture.LabeledLearningTests.setUp

    def offline(self, reason='COLLECTOR_STALE'):
        publish(self.root,dict(link='ERROR',message=reason),None)
        return json.loads((self.root/'state.json').read_text())

    def test_normal_status_null_offline_then_real_input_recovers(self):
        self.assertTrue(self.normal.status()['ready'])
        self.offline()
        status=self.normal.status()
        self.assertFalse(status['ready']);self.assertEqual(status['reason'],'COLLECTOR_STALE')
        self.assertIsNone(status['context_fingerprint'])
        save(self.root/'state.json',self.document)
        self.assertTrue(self.normal.status()['ready'])

    def test_labeled_status_null_offline_then_real_input_recovers(self):
        self.assertTrue(self.store.status()['labels']['normal']['ready'])
        self.offline()
        status=self.store.status()
        self.assertFalse(status['ready'])
        for label in status['labels'].values():
            self.assertFalse(label['ready']);self.assertEqual(label['reason'],'COLLECTOR_STALE')
        save(self.root/'state.json',self.document)
        self.assertTrue(self.store.status()['labels']['normal']['ready'])

    def test_only_explicit_freshness_null_is_transient(self):
        for reason in ('PL_UPTIME_RESTART','PROTECTION_PHASE_CHANGED','SUBSCRIBER_ERROR'):
            doc=self.offline(reason)
            for store in (self.normal,self.store):
                with self.subTest(reason=reason,store=type(store).__module__),self.assertRaisesRegex(ValueError,'OFFLINE_REQUIRES_REVIEW: '+reason):
                    store.context(document=doc)
            status=self.normal.status()
            self.assertFalse(status['ready']);self.assertIn(reason,status['reason'])

    def test_unknown_document_shapes_are_rejected_as_malformed(self):
        for document in (None,[],{},dict(observation=None),dict(observation=[]),dict(observation='offline'),
                         dict(observation=None,display=dict(link='ONLINE',message='COLLECTOR_STALE'))):
            with self.subTest(document=document):
                with self.assertRaisesRegex(ValueError,'COLLECTOR_MALFORMED'):collector_observation(document)
                for store in (self.normal,self.store):
                    # context(None) means read from disk, so write the true
                    # malformed envelope as the public status route would see it.
                    save(self.root/'state.json',document)
                    with self.assertRaisesRegex(ValueError,'COLLECTOR_MALFORMED'):store.context()

    def run_live(self, labeled=False, gap=None, native_error=False):
        from normal_npu import live as normal_live
        from labeled_npu import live as labeled_live
        module=labeled_live if labeled else normal_live
        contract=(self.store if labeled else self.normal).context()['input_contract']
        good=copy.deepcopy(self.document);again=copy.deepcopy(good)
        again['observation']['frame']['header'][3]+=1
        gap=self.offline() if gap is None else gap
        documents=iter([good,good,gap,again]);handlers={};published=[];now=[1000.1]
        norm=dict(mean=[0.]*39,scale=[1.]*39,input_scale=1.,input_zero_point=128,
                  output_scale=1.,output_zero_point=128)
        bundle=SimpleNamespace(expected=contract,norm=norm,pin='a'*64,policy={},hardware_model=lambda:None,
            thresholds=dict(group_rmse={k:1. for k in GROUPS},abs_z_limit=[2000.]*39),
            manifest=dict(model_id='fixture',source='SYNTHETIC_UNIT_TEST_ONLY',training_rows=700,
                          labels=['normal','imbalance','stall','clog','overheat']),
            provenance=dict(sessions={k:dict(session_ids=[k],rows=700) for k in ('train','calibration','test')}))
        infer=Mock(side_effect=RuntimeError('NATIVE_EXECUTION_FAILED') if native_error else None,
                   return_value=dict(output=[128]*39,execute_ms=.4))
        close=Mock(return_value=True);native=SimpleNamespace(ready={},infer=infer,close=close)
        def out(path,value):
            published.append(copy.deepcopy(value))
            if value.get('status')=='RUNNING' and value['inference_count']==2:handlers[signal.SIGTERM]()
        original_read=Path.read_text
        def path_read(path,*args,**kwargs):
            return 'UNIT_OS_BOOT' if str(path)=='/proc/sys/kernel/random/boot_id' else original_read(path,*args,**kwargs)
        argv=['unit-live','--bundle',str(self.root),'--manifest-sha256','a'*64,
              '--library',str(self.root/'fixture.so'),'--library-sha256','b'*64,'--output',str(self.root/'npu.json')]
        patches=[patch('sys.argv',argv),patch.object(module,'Bundle',return_value=bundle),
            patch.object(module,'Supervisor',return_value=native),patch.object(module,'read_state',side_effect=lambda p:next(documents)),
            patch.object(module,'publish',side_effect=out),patch.object(module.time,'monotonic',side_effect=lambda:now[0]),
            patch.object(module.time,'sleep',side_effect=lambda s:now.__setitem__(0,now[0]+s)),
            patch.object(module.signal,'signal',side_effect=lambda kind,fn:handlers.update({kind:fn})),
            patch.object(Path,'read_text',path_read)]
        selection_check=Mock(return_value={'fixture_admission':True})
        decision_check=None
        if labeled:
            # P26 startup identity tests cover this guard separately.
            patches.append(patch.object(module,'require_live_selection',selection_check))
            from labeled_npu.bundle import CLASSIFICATION_POLICY
            bundle.policy=dict(CLASSIFICATION_POLICY)
            infer.return_value=dict(output=[247,2,2,2,2],execute_ms=.4)
            decision_check=Mock(wraps=module.runtime_decision)
            patches.extend([patch.object(module,'prepare',return_value=([0.]*39,bytes([128]*39))),
                            patch.object(module,'runtime_decision',decision_check)])
        else:
            # This fixture isolates post-admission collector/null behaviour.
            # Real env/job/boot/lock admission is covered by test_boot_selection_p25.
            selection_check=Mock(return_value={'fixture_admission':True})
            patches.append(patch.object(module,'check_start_selection',selection_check))
        import contextlib
        with contextlib.ExitStack() as stack:
            for item in patches:stack.enter_context(item)
            if native_error:
                with self.assertRaisesRegex(RuntimeError,'NATIVE_EXECUTION_FAILED'):module.main()
            else:module.main()
        close.assert_called_once_with()
        self.assertEqual(selection_check.call_count,2)
        if decision_check is not None:self.assertEqual(decision_check.call_count,0 if native_error else 2)
        return published,infer

    def test_normal_native_remains_loaded_on_null_and_resumes_on_new_real_frame(self):
        published,infer=self.run_live()
        self.assertEqual(infer.call_count,2)
        states=[d for d in published if d.get('status') in ('RUNNING','WAITING_INPUT')]
        self.assertEqual([d['status'] for d in states],['RUNNING','WAITING_INPUT','RUNNING'])
        self.assertFalse(states[1]['valid']);self.assertEqual(states[1]['reason'],'COLLECTOR_STALE')
        self.assertEqual(states[1]['inference_count'],1)
        self.assertTrue(states[2]['valid']);self.assertEqual(published[-1]['status'],'STOPPED')

    def test_labeled_native_remains_loaded_on_null_and_resumes_on_new_real_frame(self):
        published,infer=self.run_live(labeled=True)
        self.assertEqual(infer.call_count,2)
        states=[d for d in published if d.get('status') in ('RUNNING','WAITING_INPUT')]
        self.assertEqual([d['status'] for d in states],['RUNNING','WAITING_INPUT','RUNNING'])
        self.assertFalse(states[1]['valid']);self.assertEqual(states[1]['reason'],'COLLECTOR_STALE')
        self.assertTrue(states[2]['valid']);self.assertEqual(published[-1]['status'],'STOPPED')
        self.assertEqual(states[0]['model_state'],'CLASSIFIED');self.assertEqual(states[0]['model_class'],'normal')
        self.assertEqual(states[0]['frame_status'],self.document['observation']['status'])
        self.assertLess(len(json.dumps(states[0]).encode('utf-8')),32768)

    def test_malformed_null_never_reaches_native_or_becomes_freshness_wait(self):
        published,infer=self.run_live(gap=dict(observation=None))
        self.assertEqual(infer.call_count,2)
        waits=[d for d in published if d.get('status')=='WAITING_INPUT']
        self.assertEqual(len(waits),1);self.assertEqual(waits[0]['reason'],'COLLECTOR_MALFORMED')
        self.assertFalse(waits[0]['valid'])

    def test_real_native_failure_still_exits_with_clean_shutdown_evidence(self):
        for labeled in (False,True):
            save(self.root/'state.json',self.document)
            with self.subTest(labeled=labeled):
                published,infer=self.run_live(labeled=labeled,native_error=True)
                self.assertEqual(infer.call_count,1)
                self.assertEqual(published[-1]['status'],'NATIVE_FAULT')
                self.assertIn('NATIVE_EXECUTION_FAILED',published[-1]['reason'])
                self.assertFalse(published[-1]['valid']);self.assertTrue(published[-1]['native_cleanup_verified'])


if __name__=='__main__':unittest.main()
