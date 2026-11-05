"""Configuration, unit calibration and model learning are independent states."""
import copy
import unittest
from instrument import protection_fields, monitor_fields
from presentation import build_presentation
from test_instrument import fixture


class ReadinessDisplayTests(unittest.TestCase):
    def test_unconfigured_protection_is_configuration_not_learning_or_unit_calibration(self):
        state,sample,unused=fixture();sample['status'].update(configured=False,test_mode=True)
        before=copy.deepcopy(sample);out=protection_fields(state,sample,True)
        self.assertEqual(out['panel_pl_oc'],'UNREADY')
        self.assertEqual(out['panel_pl_oc_readiness'],'CONFIGURATION_REQUIRED')
        self.assertEqual(out['panel_protection_scope'],'CONFIGURATION_REQUIRED')
        self.assertEqual(out['panel_protection_ready'],'0')
        self.assertEqual(sample,before)

    def test_configured_local_mode_is_not_reported_missing_configuration(self):
        state,sample,unused=fixture();sample['status'].update(configured=True,test_mode=True)
        out=protection_fields(state,sample,True)
        self.assertEqual(out['panel_pl_ot'],'UNREADY')
        self.assertEqual(out['panel_pl_ot_readiness'],'CONTROL_NOT_STARTED')
        self.assertEqual(out['panel_protection_scope'],'CONTROL_NOT_STARTED')
        self.assertEqual(out['panel_protection_ready'],'0')

    def test_partial_protection_qualification_is_not_hidden_by_global_configured(self):
        state,sample,unused=fixture();sample['status'].update(configured=True,test_mode=False,
            protection_qualifications=dict(current=True,temperature=True,actuator=True,pi=True,vibration=False))
        out=protection_fields(state,sample,True)
        self.assertEqual(out['panel_pl_oc'],'CLEAR')
        self.assertEqual(out['panel_pl_vib'],'UNREADY')
        self.assertEqual(out['panel_pl_vib_readiness'],'CONFIGURATION_REQUIRED')
        self.assertEqual(out['panel_protection_scope'],'PARTIAL_CONFIGURATION_REQUIRED')

    def test_model_learning_never_changes_protection_configuration(self):
        state,sample,unused=fixture();sample['status'].update(configured=False,test_mode=True)
        before=protection_fields(state,sample,True)
        state.update(panel_nn_valid='1',panel_nn_training_rows='99999',panel_classifier_valid='1',panel_classifier_label='normal')
        sample['model']=dict(label='normal',probabilities=[1,0,0,0,0])
        self.assertEqual(protection_fields(state,sample,True),before)

    def test_fault_and_missing_input_take_precedence_over_readiness_caption(self):
        state,sample,unused=fixture();sample['status'].update(configured=False,test_mode=True,latched=['OC_HARD'])
        sample['status']['input_validity']['temperature']=False
        out=protection_fields(state,sample,True)
        self.assertEqual(out['panel_pl_oc'],'LATCH')
        self.assertEqual(out['panel_pl_ot'],'UNKNOWN')

    def test_missing_status_or_offline_never_infers_ready_configuration(self):
        for configured in (None,True):
            state,sample,unused=fixture();sample['status']['configured']=configured
            if configured is True:state['link']='ERROR'
            out=protection_fields(state,sample,True)
            self.assertEqual(out['panel_protection_scope'],'UNKNOWN')
            self.assertEqual(out['panel_pl_oc_readiness'],'UNKNOWN')

    def test_banner_names_configuration_without_changing_raw_unit_truth(self):
        state,sample,unused=fixture();sample['status'].update(configured=False,test_mode=True)
        out=build_presentation(state,sample)
        self.assertIn('待配置',out['ui_configuration'])
        self.assertIn('尚未标定',out['ui_current_note'])
        self.assertIn('尚未标定',out['ui_pressure_note'])

    def test_protection_configuration_banner_does_not_follow_npu_freshness_or_advisory(self):
        cases = (
            (dict(configured=False, test_mode=True, hard_inhibit=True, applied_pwm_counts=0,
                  requested_rpm=0, active=['CONFIG_UNQUALIFIED', 'STOP_UNCONFIRMED'], alarm_level=1),
             'CONFIGURATION_REQUIRED', '保护阈值待配置'),
            (dict(protection_qualifications=dict(current=True, temperature=True, actuator=True,
                                                 pi=True, vibration=False)),
             'PARTIAL_CONFIGURATION_REQUIRED', '保护部分待配置'),
        )
        for status_updates, scope, title in cases:
            state, sample, _ = fixture()
            sample['status'].update(status_updates)
            state.update(build_presentation(state, sample), panel_raw_features_valid='1')
            for valid, advisory in (('1', 'WARN'), ('1', 'RECOVERING'), ('1', 'NORMAL'),
                                    ('1', 'PENDING'), ('0', 'UNKNOWN')):
                with self.subTest(scope=scope, valid=valid, advisory=advisory):
                    out = monitor_fields(dict(state, panel_nn_present='1', panel_nn_valid=valid,
                                              panel_nn_advisory_valid=valid, panel_nn_advisory_state=advisory), sample)
                    self.assertEqual(out['panel_protection_scope'], scope)
                    self.assertEqual((out.get('ui_banner_title'), out.get('ui_severity')), (title, '1'))

    def test_protection_configuration_banner_never_masks_a_live_hardware_problem(self):
        cases = (
            (dict(active=['CONFIG_UNQUALIFIED', 'OC_HARD'], alarm_level=3), True, '硬件保护报警', '3'),
            (dict(active=['CONFIG_UNQUALIFIED', 'AUX_LOSS'], alarm_level=1), True, '设备预警，请检查', '2'),
            (dict(active=['CONFIG_UNQUALIFIED'], alarm_level=1), False, '传感器数据不完整', '2'),
        )
        for status_updates, temperature_valid, title, severity in cases:
            with self.subTest(title=title):
                state, sample, _ = fixture()
                sample['status'].update(configured=False, test_mode=True, hard_inhibit=True,
                                        requested_rpm=0, applied_pwm_counts=0, **status_updates)
                sample['status']['input_validity']['temperature'] = temperature_valid
                state.update(panel_raw_features_valid='1', panel_nn_valid='1',
                             panel_nn_advisory_valid='1', panel_nn_advisory_state='WARN')
                out = monitor_fields(state, sample)
                self.assertEqual((out.get('ui_banner_title'), out.get('ui_severity')), (title, severity))

    def test_ready_protection_still_surfaces_npu_advisory(self):
        state, sample, _ = fixture()
        state.update(panel_raw_features_valid='1', panel_nn_valid='1',
                     panel_nn_advisory_valid='1', panel_nn_advisory_state='WARN')
        out = monitor_fields(state, sample)
        self.assertEqual(out['panel_protection_scope'], 'READY')
        self.assertEqual((out['ui_banner_title'], out['ui_severity']), ('实测基线持续偏离 · 预警', '2'))

    def test_classification_cannot_claim_control_ready_in_local_mode(self):
        state,sample,unused=fixture();sample['status'].update(configured=True,test_mode=True,active=[],latched=[],alarm_level=0)
        state.update(panel_classifier_valid='1',panel_classifier_label='normal',panel_raw_features_valid='1')
        out=monitor_fields(state,sample)
        self.assertEqual(out['ui_severity'],'1')
        self.assertIn('闭环未启用',out['ui_banner_title'])


if __name__=='__main__':unittest.main()
