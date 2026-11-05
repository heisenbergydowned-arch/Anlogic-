import unittest
from hmi_daily.instrument import monitor_fields

class AdvisoryUiTests(unittest.TestCase):
    def view(self, advisory='NORMAL', configured=False, **changes):
        state=dict(link='FCB1 + EDG1 ABI OK', frame_state='RECEIVED_REAL',
                   panel_raw_features_valid='1', ui_severity='1', panel_nn_valid='1',
                   panel_nn_state='BASELINE_DEVIATION', panel_nn_score='1.01',
                   panel_nn_advisory_valid='1', panel_nn_advisory_state=advisory)
        status=dict(configured=configured,test_mode=not configured,active=[],latched=[],
                    input_validity=dict(rpm=True,adc=True,temperature=True,pressure=True))
        status.update(changes)
        return monitor_fields(state,dict(status=status)),state,status
    def test_unqualified_match_keeps_control_status_neutral(self):
        out,_,_=self.view();self.assertEqual(out['ui_severity'],'1')
        self.assertEqual(out['ui_banner_title'],'保护阈值待配置');self.assertEqual(out['panel_pl_oc'],'UNREADY')
    def test_pending_and_unknown_never_green_or_yellow_warning(self):
        for value in ('PENDING','UNKNOWN'):
            out,_,_=self.view(value);self.assertEqual(out['ui_severity'],'1')
    def test_confirmed_and_recovery_warning_are_yellow(self):
        for value in ('WARN','RECOVERING'):
            out,_,_=self.view(value,configured=True);self.assertEqual(out['ui_severity'],'2')
    def test_hardware_alarm_bypasses_every_temporal_state(self):
        for value in ('NORMAL','PENDING','UNKNOWN','WARN','RECOVERING'):
            out,_,_=self.view(value,active=['OC_HARD']);self.assertEqual(out['ui_severity'],'3')
    def test_missing_sensor_bypasses_normal(self):
        out,_,_=self.view(input_validity=dict(rpm=False,adc=True,temperature=True,pressure=True))
        self.assertEqual(out['ui_severity'],'2');self.assertIn('不完整',out['ui_banner_title'])
    def test_unmapped_hardware_warning_not_hidden(self):
        out,_,_=self.view(active=['TRACK_ERROR']);self.assertEqual(out['ui_severity'],'2')
    def test_missing_advisory_not_inferred_from_raw_score(self):
        _,state,status=self.view(configured=True);state.pop('panel_nn_advisory_valid');state['panel_nn_state']='BASELINE_MATCH'
        out=monitor_fields(state,dict(status=status));self.assertEqual(out['ui_severity'],'1');self.assertIn('等待确认',out['ui_banner_title'])
    def test_test_mode_never_claims_normal_control(self):
        out,_,_=self.view(configured=True,test_mode=True);self.assertEqual(out['ui_severity'],'1')
        self.assertIn('闭环未启用',out['ui_banner_title'])
        self.assertNotIn('待配置',out['ui_banner_title'])
    def test_configured_stop_unconfirmed_is_still_warning(self):
        out,_,_=self.view(configured=True,test_mode=False,active=['STOP_UNCONFIRMED'])
        self.assertEqual(out['ui_severity'],'2')
    def test_unexplained_hardware_level_is_not_masked(self):
        out,_,_=self.view(alarm_level=1);self.assertEqual(out['ui_severity'],'2')
    def test_only_diagnostic_inhibited_stop_is_static(self):
        out,_,_=self.view(active=['CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'],alarm_level=1,
                         hard_inhibit=True,applied_pwm_counts=0,requested_rpm=0)
        self.assertEqual(out['ui_severity'],'1')
    def test_only_qualified_normal_is_green(self):
        out,_,_=self.view(configured=True,test_mode=False);self.assertEqual(out['ui_severity'],'0')

if __name__=='__main__':unittest.main()
