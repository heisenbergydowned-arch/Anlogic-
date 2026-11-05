import copy,unittest
from types import SimpleNamespace
from cabinet.alarm_only import AlarmOnlyReporter,npu_alarm
from unittest.mock import Mock,patch

class AlarmOnlyTests(unittest.TestCase):
    def setUp(self):
        self.reporter=AlarmOnlyReporter();self.controller=SimpleNamespace(command=Mock())
        self.settings={'high_C':80,'guards':{'current_zero_code':16346,'mean_trip_code':970,'peak_trip_code':2425,'max_rpm':6600}}
        self.status={'input_validity':{'adc':True,'temperature':True},'temp_raw_1_16_C':840}
    def report(self,flags=8,raw=16346,now=10):
        with patch('cabinet.alarm_only.Path.stat',side_effect=FileNotFoundError):
            return self.reporter.poll(self.controller,self.status,flags,raw,self.settings,now,'context')
    def test_alarm_sends_only_heartbeat_and_audible_advisory(self):
        self.status['input_validity']['adc']=False;r=self.report(flags=8|(1<<16));self.assertEqual(r['alarm_causes'],['ADC_INVALID'])
        self.assertTrue(r['buzzer_requested']);self.assertFalse(r['alarm_can_stop_pwm'])
        calls=self.controller.command.call_args_list
        self.assertEqual([c.args[0] for c in calls],[3,5]);self.assertEqual(calls[-1].args[1]&0x13,0x12)
    def test_high_current_and_temperature_are_audible_without_motor_commands(self):
        self.status['temp_raw_1_16_C']=1280
        r=self.report(raw=19346);self.assertIn('CURRENT_PEAK',r['alarm_causes']);self.assertIn('OVER_TEMPERATURE',r['alarm_causes'])
        self.assertEqual(r['alarm_level'],3);self.assertTrue(all(c.args[0] in (3,5) for c in self.controller.command.call_args_list))
    def test_missing_adc_does_not_invent_a_current_limit_alarm(self):
        self.status['input_validity']['adc']=False;r=self.report(flags=1<<16,raw=0)
        self.assertEqual(r['alarm_causes'],['ADC_INVALID'])
    def test_notice_is_retained_then_cleared(self):
        self.status['input_validity']['adc']=False;self.report(flags=1<<16);self.status['input_validity']['adc']=True;self.assertTrue(self.report(now=11)['buzzer_requested'])
        self.assertFalse(self.report(now=13.1)['buzzer_requested'])
        self.assertEqual(self.controller.command.call_args.args,(5,0x100))
    def test_reporter_failure_does_not_attempt_stop_or_throw(self):
        self.controller.command.side_effect=RuntimeError('unavailable')
        r=self.report(flags=1<<16);self.assertEqual(r['alarm_output_error'],'unavailable')
        self.assertTrue(all(c.args[0]==3 for c in self.controller.command.call_args_list))
    def test_only_fresh_matching_real_npu_warning_is_audible(self):
        d=dict(schema='cabinet-normal-npu-live-v1',backend='Alnpu',valid=True,status='RUNNING',collector_boot='ctx',os_boot_id='boot',updated_at=10,received_at=10,source='REAL_CURRENT_SENSOR_FRAME',advisory=dict(state='WARN',warning_latched=True))
        self.assertEqual(npu_alarm(d,10.2,'ctx','boot'),'NPU_DEVIATION')
        for key,value in [('valid',False),('backend','MOCK'),('status','STOPPED'),('collector_boot','old'),('updated_at',8)]:
            x=dict(d);x[key]=value;self.assertIsNone(npu_alarm(x,10.2,'ctx','boot'))
        self.assertIsNone(npu_alarm(d,10.2,'ctx','old'))

if __name__=='__main__':unittest.main()

class AdvisoryIsolationTests(unittest.TestCase):
    def test_own_alarm_cannot_poison_model_input_but_real_faults_remain(self):
        from cabinet.alarm_only import advisory_filtered_active
        words=[0]*32;words[31]=0x52<<16
        s={'active':['SOFT_PS','CONFIG_UNQUALIFIED','OC_HARD'],'raw_words':words}
        self.assertEqual(advisory_filtered_active(s),{'CONFIG_UNQUALIFIED','OC_HARD'})
        s['raw_words'][31]=0x1234<<16
        self.assertIn('SOFT_PS',advisory_filtered_active(s))
    def test_alarm_test_is_bounded_and_never_sends_motor_commands(self):
        a=AlarmOnlyTests();a.setUp();a.reporter.test(5,now=10)
        out=a.report(now=10.1);self.assertIn('TEST_ALARM',out['alarm_causes'])
        with self.assertRaises(ValueError):a.reporter.test(0)
        with self.assertRaises(ValueError):a.reporter.test(11)
        self.assertTrue(all(c.args[0] in (3,5) for c in a.controller.command.call_args_list))
