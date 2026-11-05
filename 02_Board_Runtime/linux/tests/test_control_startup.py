"""Controller-state fixtures, not physical fan acceptance."""
import copy
import unittest
from cabinet.policy import TemperatureLoop


class StartupTests(unittest.TestCase):
    def loop(self, **changes):
        return TemperatureLoop(dict(dict(enabled=True,qualified=True,evidence='TEST_ONLY',setpoint_C=30,
            kp_rpm_per_C=100,ki_rpm_per_C_s=10,rpm_min=1000,rpm_max=4000,startup_rpm=1500,
            slew_rpm_per_s=500,temp_age_ms=2000,pwm_min_counts=500,pwm_max_counts=2800),**changes))

    def status(self, **changes):
        return dict(dict(raw_words=[0x5a00]+[0]*31,mode='READY_OFF',latched=[],active=[],temp_age_ms=10,
            temp_raw_1_16_C=35*16,fan_action='MANUAL',requested_rpm=0,measured_rpm=0,applied_pwm_counts=0),**changes)

    def test_first_target_seeds_idle_without_any_rpm_feedback(self):
        loop=self.loop();self.assertEqual(loop.update(self.status(),0),1500)
        self.assertEqual(loop.coordination['state'],'STARTUP_REQUEST')

    def test_startup_continuously_renews_target_and_handoff_is_bumpless(self):
        loop=self.loop();loop.update(self.status(),0)
        status=self.status(mode='STARTING',fan_action='STARTUP',requested_rpm=1500,applied_pwm_counts=1500)
        for t in [.25,.5,.75,1.,1.25,1.5,1.75]:self.assertEqual(loop.update(status,t),1500)
        self.assertEqual(loop.coordination['state'],'STARTUP_TRACKING')
        status.update(mode='RUN',fan_action='PI',measured_rpm=1490)
        self.assertLessEqual(abs(loop.update(status,2)-1500),125)

    def test_manual_lease_faults_and_missing_critical_input_forbid_start(self):
        for changes in [dict(raw_words=[0x5a40]+[0]*31),dict(raw_words=[0x5800]+[0]*31),
                        dict(raw_words=[0x4a00]+[0]*31),dict(active=['TEMP_WARN']),dict(latched=['OC_HARD']),
                        dict(applied_pwm_counts=1000),dict(temp_age_ms=3000)]:
            self.assertIsNone(self.loop().update(self.status(**changes),0))

    def test_no_automatic_restart_after_explicit_stop(self):
        loop=self.loop();loop.update(self.status(mode='RUN',fan_action='PI',requested_rpm=1500,measured_rpm=1490),0)
        self.assertIsNone(loop.update(self.status(),.1))

    def test_stop_before_first_starting_sample_does_not_repeat_bootstrap(self):
        loop=self.loop();self.assertEqual(loop.update(self.status(),0),1500)
        self.assertIsNone(loop.update(self.status(mode='STOPPING'),.1))

    def test_bootstrap_requires_explicit_commissioned_startup_value(self):
        self.assertIsNone(self.loop(startup_rpm=None).update(self.status(),0))

    def test_outer_antiwindup_tracks_actual_not_fullscale_duty_limit(self):
        loop=self.loop();s=self.status(mode='RUN',fan_action='PI',requested_rpm=1500,measured_rpm=1490,applied_pwm_counts=2800)
        loop.update(s,0);initial=loop.integral
        for t in range(1,100):loop.update(s,t/10)
        self.assertEqual(loop.integral,initial)
        self.assertEqual(loop.coordination['state'],'INNER_SATURATION_INTEGRAL_HELD')

    def test_unsafe_startup_and_duty_envelopes_rejected(self):
        for change in [dict(startup_rpm=900),dict(startup_rpm=True),dict(pwm_max_counts=4001),dict(pwm_min_counts=3000)]:
            with self.assertRaises(ValueError):self.loop(**change)


if __name__=='__main__':unittest.main()
