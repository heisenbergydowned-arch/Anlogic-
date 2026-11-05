"""Synthetic V2 contract/decision fixtures only; no real training, NPU or board."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from labeled_npu.core import (INPUT_POLICY, LEGACY_INPUT_POLICY, LABELS, FEATURES,
                             validate_header, feature_values, live_input, runtime_decision)
from labeled_npu.bundle import Bundle, FILES, SOURCE, CLASSIFICATION_POLICY, classify
from labeled_npu.learning import corpus_key
from normal_npu.core import validate_header as normal_header
from tests import test_labeled_learning as fixtures
from tests import test_labeled_presentation as display_fixtures


class GroundTruthV2(unittest.TestCase):
    def setUp(self):
        self.c=fixtures.LabeledLearningTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.expected=self.c.expected()
    def missing(self):
        self.c.h[14]=0;self.c.h[15]|=0x800;self.c.st['input_validity']['rpm']=False;self.c.write()

    def test_explicit_v2_user_stall_can_be_learned_before_hardware_recognition(self):
        self.missing();body=self.c.body('stall');job=self.c.store.start(body)
        self.assertEqual(job['label'],'stall');self.assertEqual(job['label_source'],'USER_DECLARES_CURRENT_CONDITION')
        self.assertEqual(job['context']['input_contract']['input_policy'],INPUT_POLICY)
        self.assertTrue(job['condition_confirmed']);self.assertTrue(job['fg_connected_confirmed'])
        self.assertNotIn('STALL_CORROBORATED',self.c.st['active']);self.assertFalse(self.c.st['configured'])
        values,meta=live_input(self.c.document,self.c.now,self.expected,'stall',True)
        self.assertEqual(values[38],-32768.);self.assertEqual(self.c.x[38],1000.)
        self.assertFalse(meta['rpm_measurement_available']);self.assertFalse(meta['hardware_stall_corroborated'])
        self.assertFalse(job['controls_changed']);self.assertFalse(job['formal_qualification_changed'])

    def test_missing_fg_public_context_only_enables_stall_with_confirmation(self):
        self.missing();status=self.c.store.status()
        self.assertTrue(status['labels']['stall']['ready'])
        self.assertTrue(status['labels']['stall']['fg_connection_confirmation_required'])
        for label in ('normal','imbalance','clog','overheat'):self.assertFalse(status['labels'][label]['ready'])
        for field in ('condition_confirmed','episode_confirmed','fg_connected_confirmed'):
            body=self.c.body('stall');body[field]=False
            with self.assertRaises(ValueError):self.c.store.start(body)
        self.assertEqual(self.c.store.records(),[])

    def test_observed_normal_rpm_and_old_latch_are_not_current_stall_ground_truth(self):
        with self.assertRaisesRegex(ValueError,'CURRENT_CORROBORATION'):
            validate_header(self.c.h,self.c.st,self.expected,'stall',True)
        self.c.st['latched']=['STALL_CORROBORATED']
        with self.assertRaisesRegex(ValueError,'CURRENT_CORROBORATION'):
            validate_header(self.c.h,self.c.st,self.expected,'stall',True)
        self.c.st['active'].append('STALL_CORROBORATED')
        self.assertTrue(validate_header(self.c.h,self.c.st,self.expected,'stall',True)['hardware_stall_corroborated'])

    def test_explicit_v1_retains_corroboration_gate_and_corpus_is_separate(self):
        context=self.c.store.context();legacy=copy.deepcopy(context)
        legacy['input_contract']['input_policy']=LEGACY_INPUT_POLICY
        self.assertNotEqual(corpus_key(context),corpus_key(legacy))
        self.missing()
        with self.assertRaisesRegex(ValueError,'CORROBORATED'):
            validate_header(self.c.h,self.c.st,legacy['input_contract'],'stall',True)
        self.c.st['active'].append('STALL_CORROBORATED')
        self.assertEqual(feature_values(self.c.h,self.c.words(),self.c.st,legacy['input_contract'],'stall',True)[38],-32768.)

    def test_no_policy_default_or_other_sensor_quality_relaxation(self):
        self.missing()
        for policy in (None,'UNKNOWN',False):
            with self.assertRaisesRegex(ValueError,'INPUT_POLICY'):
                validate_header(self.c.h,self.c.st,dict(self.expected,input_policy=policy))
        for sensor in ('adc','temperature','pressure'):
            status=copy.deepcopy(self.c.st);status['input_validity'][sensor]=False
            with self.assertRaisesRegex(ValueError,'PROCESS_SENSOR'):validate_header(self.c.h,status,self.expected,'stall',True)
        for flag in (1,4,0x400,0x4000,0x8000):
            h=list(self.c.h);h[15]|=flag
            with self.assertRaises(ValueError):validate_header(h,self.c.st,self.expected,'stall',True)
        for label in ('normal','clog','imbalance','overheat'):
            with self.assertRaisesRegex(ValueError,'NOT_ALLOWED_FOR_LABEL'):validate_header(self.c.h,self.c.st,self.expected,label,True)
        with self.assertRaises(ValueError):normal_header(self.c.h,self.c.st,self.expected)
        self.c.document['observation']['icm_diagnostics']['sensors'][1]['fresh']=False
        with self.assertRaisesRegex(ValueError,'ICM_PAIR'):live_input(self.c.document,self.c.now,self.expected,'stall',True)

    def test_missing_metadata_must_be_consistent_and_real_zero_remains_rejected(self):
        self.c.x[38]=0
        with self.assertRaisesRegex(ValueError,'ZERO_RPM'):feature_values(self.c.h,self.c.words(),self.c.st,self.expected,'normal')
        self.missing();self.c.h[14]=1
        with self.assertRaisesRegex(ValueError,'METADATA_INCONSISTENT'):validate_header(self.c.h,self.c.st,self.expected,'stall',True)


class PublicDecisionV2(unittest.TestCase):
    def meta(self,**changes):
        return dict(dict(input_policy=INPUT_POLICY,rpm_measurement_available=False,
            hardware_stall_corroborated=False,feedback_state='FG_UNKNOWN_NOT_MEASURED_ZERO',protection_window=False),**changes)
    def test_missing_fg_never_becomes_confirmed_fault_or_normal(self):
        for index,label in enumerate(LABELS):
            output=[2]*5;output[index]=247;raw=classify(output,CLASSIFICATION_POLICY);before=copy.deepcopy(raw)
            public=runtime_decision(raw,self.meta())
            self.assertEqual(raw,before);self.assertEqual(public['model_class'],label)
            self.assertEqual(public['model_state'],'CLASSIFIED');self.assertEqual(public['state'],'UNCERTAIN')
            self.assertIsNone(public['fault_class']);self.assertEqual(public['predicted_class'],label)
            self.assertEqual(public['reason'],'STALL_CANDIDATE_FG_UNCONFIRMED' if label=='stall' else 'FG_UNKNOWN_UNCONFIRMED')
            self.assertEqual(public['control_authority'],'NONE');self.assertFalse(public['fault_classification_qualified'])
    def test_low_confidence_top_candidate_is_not_accepted_model_class(self):
        raw=classify([51]*5,CLASSIFICATION_POLICY);public=runtime_decision(raw,self.meta())
        self.assertIsNone(public['model_class']);self.assertIsNone(public['fault_class'])
        self.assertEqual(public['model_state'],'UNCERTAIN')
    def test_observed_or_current_hardware_corroborated_inputs_keep_raw_model_gate(self):
        raw=classify([2,2,247,2,2],CLASSIFICATION_POLICY)
        for meta in (self.meta(hardware_stall_corroborated=True),self.meta(rpm_measurement_available=True,feedback_state='FG_OBSERVED'),
                     self.meta(input_policy=LEGACY_INPUT_POLICY)):
            self.assertEqual(runtime_decision(raw,meta)['fault_class'],'stall')
        self.assertIsNone(runtime_decision(classify([51]*5,CLASSIFICATION_POLICY),self.meta(hardware_stall_corroborated=True))['fault_class'])
    def test_missing_or_tampered_metadata_and_control_authority_are_refused(self):
        raw=classify([2,2,247,2,2],CLASSIFICATION_POLICY)
        for change in (dict(input_policy=None),dict(rpm_measurement_available=0),dict(hardware_stall_corroborated=1),dict(feedback_state='FG_OBSERVED')):
            with self.assertRaises(ValueError):runtime_decision(raw,self.meta(**change))
        with self.assertRaises(ValueError):runtime_decision(dict(raw,control_authority='PWM'),self.meta())


class V2Display(unittest.TestCase):
    def setUp(self):
        self.c=display_fixtures.LabeledPresentationTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.c.contract['input_policy']=INPUT_POLICY
        h=self.c.sample['frame']['header'];h[14]=0;h[15]|=0x800
        self.c.sample['status']['input_validity']['rpm']=False
        self.c.result.update(quality=h[15])
    def prediction(self,output):
        meta=validate_header(self.c.result['frame_header'],self.c.sample['status'],self.c.contract)
        self.c.result.update(meta);self.c.result.update(runtime_decision(classify(output,CLASSIFICATION_POLICY),meta))
        self.c.result['output_u8']=output
    def test_stall_candidate_is_visible_without_claiming_confirmed_stall(self):
        self.prediction([2,2,247,2,2]);shown=self.c.display()
        self.assertEqual(shown['panel_classifier_valid'],'1');self.assertEqual(shown['panel_classifier_label'],'uncertain')
        self.assertIn('卡死候选',shown['panel_model_note']);self.assertIn('FG未知',shown['panel_model_note'])
        self.assertEqual(shown['panel_model_state'],'未确认')
    def test_normal_prediction_cannot_make_missing_feedback_a_normal_health_banner(self):
        from hmi_daily.instrument import monitor_fields
        self.prediction([247,2,2,2,2]);shown=self.c.display()
        self.assertEqual(shown['panel_classifier_label'],'uncertain');self.assertIn('FG未知',shown['panel_model_note'])
        state=dict(shown,link='FCB1 + EDG1 ABI OK',frame_state='RECEIVED_REAL',panel_raw_features_valid='1')
        banner=monitor_fields(state,self.c.sample)
        self.assertNotEqual(banner.get('ui_severity'),'0')
    def test_forged_public_confirmation_or_corroboration_is_not_rendered(self):
        for changes in (dict(state='CLASSIFIED',fault_class='stall'),dict(hardware_stall_corroborated=True),dict(model_class='normal')):
            self.prediction([2,2,247,2,2]);self.c.result.update(changes)
            self.assertEqual(self.c.display().get('panel_classifier_valid'),'0')


class HostContractV2(unittest.TestCase):
    def setUp(self):
        self.c=fixtures.LabeledLearningTests();self.c.setUp();self.addCleanup(self.c.doCleanups)

    def export(self,name,policy=INPUT_POLICY,label='stall',missing=True):
        from host.labeled_dataset import save,sha
        root=self.c.root/name;source=root/'captures/episode';source.mkdir(parents=True)
        h=list(self.c.h);status=copy.deepcopy(self.c.st)
        if missing:h[14]=0;h[15]|=0x800;status['input_validity']['rpm']=False
        context=self.c.store.context();context['input_contract']['input_policy']=policy
        context['capture_guard']=dict(mode=status['mode'],hard_inhibit=status['hard_inhibit'],latched=status['latched'])
        session='SYNTHETIC-'+name
        meta=dict(schema='cabinet-capture-session-v1',session_id=session,device_id='UNIT',boot_id='UNIT/collector',
            configuration_words=context['input_contract']['configuration_words'],bitstream_sha256='a'*64,
            capture_mode='DIAGNOSTIC',label_declared='unlabelled',qualified=False,
            window_policy='INDEPENDENT_LABELED_NPU_WINDOWS',preceding_frame_id=h[3])
        save(source/'session.json',meta);save(source/'feature_contract.json',dict(qualified=False,unit_fixture=True))
        with (source/'frames.jsonl').open('w') as output:
            for index in range(600):
                header=list(h);header[3]+=index+1;header[4]+=128*(index+1)
                row_status=dict(status,uptime_ms=header[4]+50)
                output.write(json.dumps(dict(schema='cabinet-capture-frame-v1',source='REAL_FRM1_DECLARED',
                    boot_id='UNIT/collector',session_id=session,header=header,status=row_status,feature_words=self.c.words(),
                    gap_before=0,accepted=False,rejected_reasons=['DIAGNOSTIC_NOT_TRAINING']))+'\n')
        summary=dict(state='DIAGNOSTIC_SAVED',session_id=session,frames=600,durable_frames=600,gaps=0,missing_frames=0,
            files_sha256={n:sha(source/n) for n in ('session.json','feature_contract.json','frames.jsonl')})
        save(source/'summary.json',summary);save(root/'sessions.json',dict(episode=dict(status=summary)))
        job=dict(context=context,label=label,episode_id='unit-'+name,episode_split='train',fg_connected_confirmed=label=='stall')
        learning=dict(job,schema='cabinet-one-click-labeled-learning-v1',source=SOURCE,qualified=False,
            label_source='USER_DECLARES_CURRENT_CONDITION',condition_confirmed=True,episode_confirmed=True,
            raw_capture_qualification_changed=False,corpus_key=corpus_key(context),note='SYNTHETIC TEST ONLY')
        save(root/'learning.json',learning)
        return root,job,meta,summary

    def test_board_audit_and_host_loader_accept_same_declared_unknown_stall(self):
        from host.labeled_dataset import load_export
        root,job,meta,summary=self.export('v2-stall')
        self.assertEqual(self.c.store.audit_capture(root/'captures/episode',meta,summary,job),600)
        learning,unused,unused_summary,values,ids=load_export(root)
        self.assertTrue(all(row[38]==-32768. for row in values));self.assertEqual(len(ids),600)
        row=json.loads((root/'captures/episode/frames.jsonl').read_text().splitlines()[0])
        self.assertEqual(struct.unpack('<f',struct.pack('<I',row['feature_words'][38]))[0],1000.)
        self.assertFalse(row['status']['input_validity']['rpm']);self.assertFalse(meta['qualified'])
        self.assertEqual(learning['label_source'],'USER_DECLARES_CURRENT_CONDITION')

    def test_host_rejects_unconfirmed_declaration_and_v1_unknown_without_hardware(self):
        from host.labeled_dataset import load_export,save
        root,unused,unused_meta,unused_summary=self.export('declaration')
        original=json.loads((root/'learning.json').read_text())
        for field in ('condition_confirmed','episode_confirmed','fg_connected_confirmed'):
            save(root/'learning.json',dict(original,**{field:False}))
            with self.assertRaises(ValueError):load_export(root)
        legacy,unused,unused_meta,unused_summary=self.export('legacy-stall',LEGACY_INPUT_POLICY)
        with self.assertRaisesRegex(ValueError,'CORROBORATED'):load_export(legacy)

    def test_immutable_registry_does_not_merge_v1_and_v2_corpora(self):
        from host.labeled_dataset import register
        one,unused,unused_meta,unused_summary=self.export('v1-normal',LEGACY_INPUT_POLICY,'normal',False)
        two,unused,unused_meta,unused_summary=self.export('v2-normal',INPUT_POLICY,'normal',False)
        a=register(one,self.c.root/'registry');b=register(two,self.c.root/'registry')
        self.assertNotEqual(a['corpus_key'],b['corpus_key'])
        self.assertEqual(a['coverage']['normal']['train'],1);self.assertEqual(b['coverage']['normal']['train'],1)
        self.assertEqual(a['status'],'WAITING_DATA');self.assertEqual(b['status'],'WAITING_DATA')

    def test_new_trainer_refuses_historical_v1_without_relabelling_or_training(self):
        from host.train_labeled import load_dataset
        from host.labeled_dataset import save
        root=self.c.root/'old-dataset';root.mkdir()
        save(root/'dataset.json',dict(schema='cabinet-real-labeled-dataset-v1',source=SOURCE,train_ready=True,
            qualified=False,control_authority='NONE',entries=[],input_contract=dict(input_policy=LEGACY_INPUT_POLICY)))
        with self.assertRaisesRegex(ValueError,'V2_INPUT_POLICY_REQUIRED'):load_dataset(root)

    def test_host_helpers_import_the_matching_candidate_core(self):
        from host import labeled_dataset,train_labeled,compile_labeled_bundle
        import labeled_npu.core as core
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(Path(core.__file__).resolve(),root/'labeled_npu/core.py')
        self.assertIs(labeled_dataset.feature_values,core.feature_values)
        self.assertEqual(train_labeled.INPUT_POLICY,INPUT_POLICY)
        self.assertIs(train_labeled.Bundle,compile_labeled_bundle.Bundle)


class BundlePolicyV2(unittest.TestCase):
    def bundle(self,root,policy):
        root.mkdir()
        def save(name,value):(root/name).write_text(json.dumps(value))
        q=dict(status='PASS_ENGINEERING_QUALITY_ONLY',checks={k:True for k in ('normal_false_positive','every_class_recall','macro_f1','input_coverage')},
            normal_false_positive_window_rate=0,min_class_recall=1,macro_f1=1,input_coverage=1,per_class_recall={k:1 for k in LABELS})
        quant=dict(checks={k:True for k in ('fp32_export','class_agreement','macro_f1_degradation')},fp32_max_probability_error=0,
            class_agreement=1,macro_f1_degradation=0,rejected_and_out_of_range_count_against_quality=True)
        sessions=[dict(session_id=label+'-'+str(i),episode_id=label+'-'+str(i),label=label,split=split,rows=600)
                  for label in LABELS for i,split in enumerate(('train','train','validation','test'))]
        save('provenance.json',dict(source=SOURCE,raw_capture_qualification_changed=False,input_contract=dict(input_policy=policy),sessions=sessions))
        save('normalization.json',dict(features=FEATURES,normalization_fitted_on='train',mean=[0]*39,scale=[1]*39,
            input_scale=1,logits_scale=1,input_zero_point=128,logits_zero_point=128))
        save('policy.json',CLASSIFICATION_POLICY)
        save('training_validation.json',dict(status='PASS_REAL_LABELED_ADVISORY_HOST_TRAINING',source=SOURCE,qualified=False,
            test_used_for_selection=False,quality={k:q for k in ('validation','test')},quantization={k:quant for k in ('validation','test')}))
        save('golden.json',dict(source=SOURCE,vectors=[dict(label=label,split='test') for label in LABELS for unused in range(32)]))
        (root/'model_u8.onnx').write_bytes(b'EXPLICIT_SYNTHETIC_CONTRACT_ONLY_NOT_EXECUTABLE_MODEL')
        manifest=dict(schema='cabinet-real-labeled-npu-v1',source=SOURCE,qualified=False,control_authority='NONE',labels=list(LABELS),
            input_shape=[1,39],output_shape=[1,5],architecture=[39,32,16,5],native_abi=3,
            execution_model='ALNPU_LOGITS_PS_SOFTMAX',input_policy=policy,
            artifacts_sha256={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in FILES})
        save('manifest.json',manifest)
        return hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
    def test_explicit_v1_and_v2_load_but_rehashed_cross_policy_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            for i,policy in enumerate((LEGACY_INPUT_POLICY,INPUT_POLICY)):
                root=Path(directory)/str(i);pin=self.bundle(root,policy)
                self.assertEqual(Bundle(root,pin).expected['input_policy'],policy)
                manifest=json.loads((root/'manifest.json').read_text())
                manifest['input_policy']=INPUT_POLICY if policy==LEGACY_INPUT_POLICY else LEGACY_INPUT_POLICY
                (root/'manifest.json').write_text(json.dumps(manifest));pin=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
                with self.assertRaisesRegex(ValueError,'PROVENANCE_SCOPE'):Bundle(root,pin)


if __name__=='__main__':unittest.main(verbosity=2)

