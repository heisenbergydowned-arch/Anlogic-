"""Explicit synthetic display fixtures; never admitted as training captures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from labeled_npu.core import LEGACY_INPUT_POLICY, LABELS
from labeled_npu.presentation import fields
import test_normal_npu_freshness as freshness_fixtures


class LabeledPresentationTests(unittest.TestCase):
    def setUp(self):
        fixture=freshness_fixtures.NormalNpuFreshnessTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.sample=copy.deepcopy(fixture.sample);self.path=fixture.path
        self.contract=dict(fixture.contract,input_policy=LEGACY_INPUT_POLICY)
        h=self.sample['frame']['header'];h[13]=65537;h[14]=4;h[19]=5;h[20]=4000;h[22]=50000
        self.result=dict(schema='cabinet-labeled-npu-live-v1',backend='Alnpu',
            model_source='REAL_USER_DECLARED_LABELED_DIAGNOSTIC',formal=False,qualified=False,
            control_authority='NONE',labels=list(LABELS),input_contract=self.contract,os_boot_id='os-boot',
            updated_at=1000.01,received_at=1000.,valid=True,status='RUNNING',collector_boot=self.sample['boot'],
            frame_id=h[3],frame_end_ms=h[4],frame_header=h,quality=h[15],source='REAL_CURRENT_SENSOR_FRAME',
            execute_ms=.4,state='CLASSIFIED',fault_class='clog',confidence=.96,
            probabilities=dict(normal=.01,imbalance=.01,stall=.01,clog=.96,overheat=.01))
    def display(self,now=1000.02):
        self.path.write_text(json.dumps(self.result));self.path.chmod(0o600)
        return fields(self.sample,1000.,self.path,'os-boot',clock=lambda:now)
    def test_fresh_advisory_uses_classifier_without_formal_qualification(self):
        d=self.display();self.assertEqual(d.get('panel_model_valid'),'1')
        self.assertEqual(d['panel_prob_clog'],'96.00');self.assertEqual(d['panel_nn_present'],'0')
        self.assertNotIn('formal',d);self.assertNotIn('control',d)
        self.assertIn('仅诊断',d['panel_model_note']);self.assertNotIn('未标定',d['panel_model_note'])
    def test_empty_collector_frame_does_not_hide_fresh_verified_prediction(self):
        self.sample['frame']={'state':'EMPTY'}
        self.assertEqual(self.display().get('panel_model_valid'),'1')
    def test_stale_future_and_disconnected_inputs_clear_probabilities(self):
        for variant in ('future','expired','temperature','icm','header','probability'):
            original_sample=copy.deepcopy(self.sample);original_result=copy.deepcopy(self.result)
            with self.subTest(variant=variant):
                if variant=='future':self.result['updated_at']=1001.
                if variant=='expired':self.result['received_at']=999.
                if variant=='temperature':self.sample['status']['input_validity']['temperature']=False
                if variant=='icm':self.sample['icm_diagnostics']['sensors'][1]['fresh']=False
                if variant=='header':self.result['frame_header'][26]=0
                if variant=='probability':self.result['confidence']=.5
                d=self.display();self.assertNotEqual(d.get('panel_model_valid'),'1')
                self.assertNotEqual(d.get('panel_prob_clog'),'96.00')
            self.sample=original_sample;self.result=original_result
    def test_stopped_classifier_does_not_hide_fallback_model(self):
        self.result.update(status='STOPPED',valid=False)
        self.assertEqual(self.display(),{})
    def test_test_source_or_changed_current_frame_cannot_reuse_recent_prediction(self):
        for state in ('REJECTED_TEST','RECEIVED_TEST','INVALID'):
            self.sample['frame']={'state':state}
            self.assertEqual(self.display().get('panel_model_valid'),'0')
        self.sample['frame']={'state':'RECEIVED_REAL','header':list(self.result['frame_header'])}
        self.sample['frame']['header'][27]=1
        self.assertEqual(self.display().get('panel_model_valid'),'0')
    def test_untrusted_scope_never_becomes_visible_classifier(self):
        for key,value in [('backend','CPU'),('formal',True),('control_authority','PWM'),('qualified',True)]:
            old=self.result[key];self.result[key]=value
            self.assertEqual(self.display(),{});self.result[key]=old


if __name__=='__main__':unittest.main()
