import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from cabinet.alarm_only import AlarmOnlyReporter


class AlarmMessageTests(unittest.TestCase):
    def report(self, hardware_fault=False):
        reporter=AlarmOnlyReporter()
        document=dict(schema='cabinet-normal-npu-live-v1',backend='Alnpu',valid=True,status='RUNNING',
            collector_boot='context',os_boot_id=reporter.os_boot,updated_at=10,received_at=10,
            input_deadline=11,source='REAL_CURRENT_SENSOR_FRAME',
            advisory=dict(state='WARN',warning_latched=True))
        ctl=SimpleNamespace(command=Mock())
        settings={'high_C':80,'guards':{'current_zero_code':16346,'mean_trip_code':970,'peak_trip_code':2425,'max_rpm':5000}}
        status=dict(input_validity={'adc':True,'temperature':True,'rpm':not hardware_fault},
                    measured_rpm=1000,temp_raw_1_16_C=380)
        with patch('cabinet.alarm_only.Path.stat',return_value=SimpleNamespace(st_size=100)),\
                patch('cabinet.alarm_only.Path.read_text',return_value=json.dumps(document)):
            out=reporter.poll(ctl,status,0,16346,settings,10.2,'context')
        return out,ctl

    def test_baseline_deviation_is_warning_without_motor_or_buzzer_command(self):
        out,ctl=self.report()
        self.assertEqual(out['alarm_causes'],['NPU_DEVIATION'])
        self.assertEqual(out['alarm_level'],1)
        self.assertFalse(out['buzzer_requested'])
        self.assertFalse(out['alarm_can_stop_pwm'])
        self.assertEqual(ctl.command.call_args.args[1]&0x13,1)
        self.assertEqual([call.args[0] for call in ctl.command.call_args_list],[3,5])

    def test_real_sensor_alarm_keeps_priority_over_baseline_warning(self):
        out,ctl=self.report(hardware_fault=True)
        self.assertIn('FG_MISSING',out['alarm_causes'])
        self.assertEqual(out['alarm_level'],2)
        self.assertTrue(out['buzzer_requested'])
        self.assertEqual(ctl.command.call_args.args[1]&0x13,0x12)


if __name__=='__main__':unittest.main()
