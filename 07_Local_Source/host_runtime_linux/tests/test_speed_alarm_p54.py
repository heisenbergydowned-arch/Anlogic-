import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cabinet.alarm_only import AlarmOnlyReporter
from cabinet.speed_alarm import SpeedAlarm, validate_policy
from cabinet.temperature_pwm import validate, words
from tests.test_temperature_pwm_p39 import config


POLICY = dict(warning_rpm=4500, warning_hold_ms=10000,
              warning_clear_rpm=4400, recovery_ms=1000,
              source='USER_MEASURED_4500RPM_20261104')


def sample(rpm=4500, now=0, valid=True):
    return dict(measured_rpm=rpm, uptime_ms=round(now * 1000) & 0xffffffff,
                input_validity=dict(rpm=valid, adc=True, temperature=True),
                temp_raw_1_16_C=400)


class SpeedAlarmTests(unittest.TestCase):
    def setUp(self):
        self.a = SpeedAlarm()

    def feed(self, rpm, now, valid=True, context='boot'):
        return self.a.observe(sample(rpm, now, valid), now, POLICY, 5000, context)

    def test_4500_requires_full_ten_seconds(self):
        for i in range(40):
            self.assertEqual(self.feed(4500, i / 4)['state'], 'PENDING')
        self.assertEqual(self.feed(4500, 10)['state'], 'WARNING')

    def test_below_hysteresis_band_restarts_confirmation(self):
        for i in range(40): self.feed(4500, i / 4)
        self.assertEqual(self.feed(4399, 10)['state'], 'NORMAL')
        self.assertEqual(self.feed(4500, 10.25)['elapsed_ms'], 0)

    def test_fg_jitter_near_4500_does_not_restart_confirmation(self):
        self.assertEqual(self.feed(4499, 0)['state'],'NORMAL')
        self.feed(4500,.25)
        for i in range(2,41):self.feed(4470 if i%2 else 4530,i/4)
        self.assertEqual(self.feed(4490,10.25)['state'],'WARNING')

    def test_exactly_5000_is_not_red_but_5001_is(self):
        self.assertEqual(self.feed(5000, 0)['state'], 'PENDING')
        self.assertEqual(self.feed(5001, .25)['state'], 'ALARM')

    def test_red_recovery_requires_one_second_of_fresh_samples(self):
        self.feed(5100, 0)
        for i in range(1, 5): self.assertEqual(self.feed(4300, i / 4)['state'], 'ALARM')
        self.assertEqual(self.feed(4300, 1.25)['state'], 'NORMAL')

    def test_yellow_hysteresis(self):
        for i in range(41): self.feed(4500, i / 4)
        self.assertEqual(self.feed(4450, 10.25)['state'], 'WARNING')
        self.assertEqual(self.feed(4400, 10.5)['state'], 'WARNING')
        for i in range(3): self.assertEqual(self.feed(4399, 10.75 + i / 4)['state'], 'WARNING')
        self.assertEqual(self.feed(4399, 11.75)['state'], 'NORMAL')

    def test_duplicate_or_missing_samples_cannot_advance_hold(self):
        s=sample(4500, 0)
        self.a.observe(s, 0, POLICY, 5000, 'boot')
        self.assertEqual(self.a.observe(s, .75, POLICY, 5000, 'boot')['elapsed_ms'], 0)
        self.assertEqual(self.a.observe(s, 10, POLICY, 5000, 'boot')['state'], 'UNKNOWN')
        self.assertEqual(self.feed(4500, 10.25)['elapsed_ms'], 0)

    def test_invalid_fg_is_not_false_overspeed(self):
        self.assertEqual(self.feed(39473, 0, False)['state'], 'UNKNOWN')
        self.assertEqual(self.feed(5100, .25, False)['state'], 'UNKNOWN')
        self.assertEqual(self.feed(4500, .5)['elapsed_ms'], 0)

    def test_long_gap_context_change_and_backwards_clock_reset(self):
        for i in range(36): self.feed(4500, i / 4)
        self.assertEqual(self.feed(4500, 12)['elapsed_ms'], 0)
        self.assertEqual(self.feed(4500, 12.25, context='new')['elapsed_ms'], 0)
        self.assertEqual(self.feed(4500, 11)['elapsed_ms'], 0)

    def test_policy_is_optional_and_preserved_by_validation(self):
        old=config();self.assertNotIn('speed_alarm',validate(old,'test-device'))
        new=copy.deepcopy(old);new['guards']['max_rpm']=5000;new['speed_alarm']=POLICY
        out=validate(new,'test-device');self.assertEqual(out['speed_alarm'],POLICY)
        self.assertEqual(words(out)[2] >> 16,5000)
        for key,value in [('warning_rpm',5000),('warning_clear_rpm',4500),('warning_hold_ms',0)]:
            bad=dict(POLICY);bad[key]=value
            with self.assertRaises(ValueError): validate_policy(bad,5000)

    def test_reporter_yellow_and_red_use_alarm_commands_only(self):
        a=AlarmOnlyReporter();ctl=SimpleNamespace(command=Mock())
        settings=config();settings['guards']['max_rpm']=5000;settings['speed_alarm']=POLICY
        with patch('cabinet.alarm_only.Path.stat',side_effect=FileNotFoundError):
            for i in range(41): out=a.poll(ctl,sample(4500,i/4),0,16346,settings,i/4,'boot')
            self.assertEqual(out['alarm_level'],1)
            self.assertEqual(out['alarm_causes'],['RPM_HIGH_SUSTAINED'])
            self.assertFalse(out['buzzer_requested'])
            self.assertEqual(ctl.command.call_args.args[1]&0x13,1)
            out=a.poll(ctl,sample(5001,10.25),0,16346,settings,10.25,'boot')
            self.assertEqual(out['alarm_level'],3)
            self.assertEqual(out['alarm_causes'],['OVERSPEED'])
            self.assertTrue(out['buzzer_requested'])
            self.assertEqual(ctl.command.call_args.args[1]&0x13,0x13)
            self.assertTrue(all(call.args[0] in (3,5) for call in ctl.command.call_args_list))
            for i in range(42,47): out=a.poll(ctl,sample(4300,i/4),0,16346,settings,i/4,'boot')
            self.assertEqual(out['alarm_level'],0)
            self.assertFalse(out['alarm_can_stop_pwm'])


if __name__ == '__main__': unittest.main()
