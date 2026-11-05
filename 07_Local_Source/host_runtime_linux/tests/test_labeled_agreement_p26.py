"""Synthetic acceptance evidence only; never a physical NPU validation."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from labeled_npu import agreement, deploy
from labeled_npu.core import validate_header, runtime_decision, LEGACY_INPUT_POLICY
from labeled_npu.bundle import classify, CLASSIFICATION_POLICY
from tests import test_labeled_learning as learning_fixture

class AgreementV2Tests(unittest.TestCase):
    def setUp(self):
        self.f=learning_fixture.LabeledLearningTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.h[14]=0;self.f.h[15]|=0x800;self.f.st['input_validity']['rpm']=False;self.f.write()
        self.job=self.f.store.start(self.f.body('stall'));self.policy=CLASSIFICATION_POLICY
    def result(self,index=1,output=None):
        h=list(self.f.h);h[3]+=index;h[4]+=index*128
        st=copy.deepcopy(self.f.st);st['uptime_ms']=h[4]+50
        meta=validate_header(h,st,self.job['context']['input_contract'],'stall',True)
        output=[2,2,247,2,2] if output is None else output
        decision=runtime_decision(classify(output,self.policy),meta)
        return dict(decision,**meta,frame_header=h,frame_status=st,frame_id=h[3],inference_count=index,
            execute_ms=.4,output_u8=output,collector_boot=self.job['context']['collector_boot'],
            model_sha256='a'*64,status='RUNNING',valid=True,os_boot_id=self.f.boot,updated_at=1000.1)
    def sample(self,index=1,output=None):return agreement.snapshot(self.result(index,output),self.job,self.policy)
    def test_confirmed_user_label_can_agree_without_public_physical_confirmation(self):
        sample=self.sample()
        self.assertEqual(sample['state'],'UNCERTAIN');self.assertIsNone(sample['fault_class'])
        self.assertEqual(sample['model_class'],'stall')
        self.assertEqual(agreement.agreement([sample],self.job,self.policy),1.)
        receipt=agreement.receipt_fields(self.job)
        self.assertFalse(receipt['physical_condition_confirmed']);agreement.check_receipt(receipt,self.job)
    def test_low_confidence_top_candidate_and_wrong_class_do_not_count(self):
        for output in ([51]*5,[247,2,2,2,2]):
            self.assertEqual(agreement.agreement([self.sample(output=output)],self.job,self.policy),0)
    def test_no_declaration_or_changed_request_is_rejected(self):
        for change in (dict(condition_confirmed=False),dict(episode_confirmed=False),dict(label_source='INFERRED'),dict(request={})):
            with self.subTest(change=change),self.assertRaises(ValueError):
                agreement.checked_sample(self.sample(),dict(self.job,**change),self.policy)
    def test_saved_outputs_input_or_public_result_cannot_be_forged(self):
        for change in (dict(state='CLASSIFIED',fault_class='stall'),dict(model_class='normal'),dict(confidence=1.),
                       dict(hardware_stall_corroborated=True),dict(output_u8=[247,2,2,2,2]),dict(collector_boot='old/collector')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                agreement.checked_sample(dict(self.sample(),**change),self.job,self.policy)
    def test_repeated_frame_and_counter_do_not_prove_fresh_execution(self):
        first=self.sample();second=copy.deepcopy(first);second['inference_count']=2
        with self.assertRaisesRegex(ValueError,'REPEATED'):agreement.agreement([first,second],self.job,self.policy)
        second=self.sample(2);second['inference_count']=1
        with self.assertRaisesRegex(ValueError,'REPEATED'):agreement.agreement([first,second],self.job,self.policy)
    def test_model_thresholds_and_scope_are_not_relaxed(self):
        for policy in ({'confidence_min':.59,'margin_min':.1},{'confidence_min':.6,'margin_min':.09},None):
            with self.assertRaises(ValueError):agreement.checked_sample(self.sample(),self.job,policy)
        receipt=agreement.receipt_fields(self.job);receipt['physical_condition_confirmed']=True
        with self.assertRaises(ValueError):agreement.check_receipt(receipt,self.job)
    def test_legacy_receipt_cannot_be_reinterpreted_as_v2(self):
        old=copy.deepcopy(self.job);old['context']['input_contract']['input_policy']=LEGACY_INPUT_POLICY
        self.assertEqual(agreement.agreement([{'fault_class':'stall'}],old),1)
        with self.assertRaises(ValueError):agreement.check_receipt(agreement.receipt_fields(self.job),old)
    def run_live(self,wrong=0):
        rows=[self.result(i+1,[247,2,2,2,2] if i<wrong else None) for i in range(128)]
        path=self.f.root/'agreement.json'
        with patch.object(self.f.store,'check'),patch.object(deploy,'read_state',side_effect=rows),\
             patch.object(deploy.time,'monotonic',return_value=1000.2),patch.object(deploy.time,'sleep'):
            result=deploy.wait_live('a'*64,self.f.store,self.job,path,policy=self.policy)
        return result,json.loads(path.read_text())
    def test_actual_wait_live_collects128_uncertain_but_declared_class_agreement(self):
        result,report=self.run_live()
        self.assertEqual(result['observed_samples'],128);self.assertEqual(result['agreement'],1.)
        self.assertEqual(result['agreement_semantics'],agreement.SCOPE)
        self.assertTrue(all(s['fault_class'] is None for s in report['samples']))
        self.assertLess(len(json.dumps(report,indent=2).encode('utf-8'))+1,1048576)
        self.assertEqual(agreement.agreement(report['samples'],self.job,self.policy),1.)
    def test_fault_80_percent_gate_still_counts_mistakes(self):
        self.assertEqual(self.run_live(25)[0]['agreement'],103/128)
        with self.assertRaisesRegex(ValueError,'AGREEMENT_FAILED'):self.run_live(26)
    def test_no_shortened_hardware_acceptance(self):
        with self.assertRaisesRegex(ValueError,'128'):
            deploy.wait_live('a'*64,self.f.store,self.job,self.f.root/'unused',required=1,policy=self.policy)

if __name__=='__main__':unittest.main()
