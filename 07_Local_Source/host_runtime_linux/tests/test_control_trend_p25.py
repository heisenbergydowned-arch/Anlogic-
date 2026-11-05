"""Display contracts only: no control writes or physical acceptance."""
import unittest
from cabinet.control_display import ControlDisplay
import test_commissioning_ready as fixtures

class TrendContractTests(unittest.TestCase):
    def sample(self):
        sample=fixtures.ControlDisplayTests().sample(1)
        sample['status']['applied_pwm_counts']=800
        sample['status']['raw_words'][7]=800
        return sample

    def test_requested_target_is_not_replaced_by_intermediate_PI_ramp(self):
        sample=self.sample()
        sample['status'].update(requested_rpm=3000,ramped_rpm=1500,measured_rpm=1400,mode='TRANSIENT')
        fields=ControlDisplay().fields(sample,1)
        self.assertEqual(fields['panel_control_target_rpm'],'3000')
        self.assertEqual(fields['panel_control_inner_target_rpm'],'1500')
        self.assertEqual(fields['panel_control_error_rpm'],'-1600')
        self.assertEqual(fields['panel_control_error_pct'],'-53.33')
        self.assertEqual(fields['panel_control_phase'],'TRANSIENT')
        self.assertEqual(fields['panel_control_settled'],'0')

    def test_PWM_is_readback_counts_over_4000_not_requested_duty(self):
        fields=ControlDisplay().fields(self.sample(),1)
        self.assertEqual(fields['panel_control_pwm_percent'],'20.00')
        self.assertEqual(fields['panel_control_pwm_valid'],'1')
        self.assertEqual(fields['panel_control_identity'],'TEST/1/1')

    def test_open_loop_PWM_never_manufactures_closed_loop_target(self):
        sample=self.sample();sample['control']['enabled']=False
        sample['status'].update(configured=False,test_mode=True)
        sample['bench']={'state':'ACTIVE_BENCH_NOT_CLOSED_LOOP','controls_enabled':True}
        fields=ControlDisplay().fields(sample,1)
        self.assertEqual(fields['panel_control_pwm_percent'],'20.00')
        self.assertEqual(fields['panel_control_state'],'BENCH_OPEN_LOOP')
        self.assertEqual(fields['panel_control_enabled'],'0')
        self.assertEqual(fields['panel_control_target_valid'],'0')
        self.assertEqual(fields['panel_control_error_rpm'],'--')

    def test_mismatched_invalid_or_old_readback_cannot_show_PWM(self):
        for bad in ('mismatch','invalid','boolean','missing','stale','test_frame'):
            with self.subTest(bad=bad):
                sample=self.sample();now=1
                if bad=='mismatch':sample['status']['raw_words'][7]=900
                elif bad=='invalid':sample['status']['applied_pwm_counts']=4001
                elif bad=='boolean':sample['status']['applied_pwm_counts']=True
                elif bad=='missing':sample['status'].pop('applied_pwm_counts')
                elif bad=='stale':now=3
                else:sample['frame']['state']='REJECTED_TEST'
                fields=ControlDisplay().fields(sample,now)
                self.assertEqual(fields['panel_control_pwm_valid'],'0')
                self.assertEqual(fields['panel_control_pwm_percent'],'--')

    def test_ten_second_error_uses_requested_blue_line_at_tolerance_boundary(self):
        for inner,rpm,error,settled in ((2008,2042,'2.10','0'),(1992,2035,'1.75','1')):
            with self.subTest(inner=inner):
                display=ControlDisplay()
                for i in range(102):
                    sample=self.sample();sample['received_at']=i/10
                    sample['status'].update(requested_rpm=2000,ramped_rpm=inner,measured_rpm=rpm,uptime_ms=i*100)
                    fields=display.fields(sample,i/10)
                self.assertEqual(fields['panel_control_target_rpm'],'2000')
                self.assertEqual(fields['panel_control_error_pct'],error)
                self.assertEqual(fields['panel_control_10s_error_pct'],error)
                self.assertEqual(fields['panel_control_settled'],settled)

    def test_missing_FG_drops_error_without_dropping_real_PWM(self):
        sample=self.sample();sample['status']['input_validity']['rpm']=False
        fields=ControlDisplay().fields(sample,1)
        self.assertEqual(fields['panel_control_error_rpm'],'--')
        self.assertEqual(fields['panel_control_pwm_valid'],'1')
        self.assertEqual(fields['panel_control_settled'],'0')

    def test_absent_or_nonmapping_bench_state_does_not_break_sensor_display(self):
        for bench in (None,[],False,'UNKNOWN'):
            with self.subTest(bench=bench):
                sample=self.sample();sample['bench']=bench
                fields=ControlDisplay().fields(sample,1)
                self.assertEqual(fields['panel_control_pwm_percent'],'20.00')
                self.assertNotEqual(fields['panel_control_state'],'BENCH_OPEN_LOOP')

if __name__=='__main__':unittest.main()
