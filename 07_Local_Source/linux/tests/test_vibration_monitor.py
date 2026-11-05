import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cabinet.protocol import Frame
from cabinet.vibration_monitor import VibrationMonitor, panel_fields
from cabinet.alarm_only import AlarmOnlyReporter


class VibrationMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=Path(self.tmp.name)/'vibration.json'
        p.write_text(json.dumps(dict(schema='cabinet-vibration-monitor-v1',enabled=True,device_id='board',
            thresholds={k:dict(warning_rms=.2,alarm_rms=.4) for k in 'ab'},reference={'model':'saved-normal'})))
        self.monitor=VibrationMonitor('board',p)
        self.diag=dict(state='DIAGNOSTIC_ONLY',test=False,boot_id='board/boot',snapshot_age_ms=0,
            sensors=[dict(channel=k,fresh=True,error=False,config_verified=True,config_bad_mask=0) for k in 'AB'])

    def frame(self,number,amplitude=.03,quality=0x3000):
        h=[0]*32;h[3]=number;h[4]=number*128;h[9:13]=[25575000,25575000,1024,1024];h[15]=quality;h[21]=100000000
        x=[0.]*39
        for i in (0,1,2,17,18,19):x[i]=amplitude
        return Frame(tuple(h),tuple(x))

    def observe(self,i,amplitude=.03,quality=0x3000):
        return self.monitor.observe(self.frame(i,amplitude,quality),{'uptime_ms':i*128},self.diag,i*.128,'board/boot/session')

    def test_enabled_real_normal_becomes_clear(self):
        d=self.observe(1);self.assertEqual(d['state'],'CLEAR');self.assertTrue(d['valid'])
        self.assertEqual(panel_fields(d,.128)['panel_pl_vib'],'CLEAR')

    def test_knock_reports_alarm_and_holds_then_recovers(self):
        d=self.observe(1,.5);self.assertEqual(d['state'],'ALARM');self.assertEqual(d['event_count'],1)
        self.assertEqual(self.observe(2)['state'],'ALARM')
        self.assertEqual(self.observe(18)['state'],'CLEAR')

    def test_missing_sensor_test_or_overflow_never_becomes_normal(self):
        self.assertFalse(self.observe(1,quality=0x3001)['valid'])
        self.diag['sensors'][1]['fresh']=False
        self.assertFalse(self.observe(2)['valid'])

    def test_fg_missing_does_not_mask_independent_valid_vibration(self):
        self.assertTrue(self.observe(1,quality=0x3800)['valid'])
        self.assertFalse(self.observe(2,quality=0x3010)['valid'])

    def test_duplicate_cannot_extend_data_deadline(self):
        d=self.observe(1)
        out=self.monitor.observe(self.frame(1),{'uptime_ms':128},self.diag,2.,'board/boot/session')
        self.assertFalse(out['valid']);self.assertEqual(d['deadline_ms'],1128)

    def test_alarm_reporter_only_sends_alarm_commands(self):
        class Controller:
            def __init__(self):self.commands=[]
            def command(self,*args):self.commands.append(args)
        c=Controller();r=AlarmOnlyReporter();r.os_boot='boot'
        settings=dict(guards=dict(max_rpm=6600,current_zero_code=0,peak_trip_code=2000,mean_trip_code=1000),high_C=80)
        v=dict(valid=True,collector_boot='ctx',deadline_ms=2000,state='ALARM')
        with patch('cabinet.alarm_only.Path.read_text',side_effect=FileNotFoundError),patch('cabinet.alarm_only.Path.stat',side_effect=FileNotFoundError):
            d=r.poll(c,{'input_validity':{}},0,0,settings,1,'ctx',vibration=v)
        self.assertIn('VIBRATION_HIGH',d['alarm_causes']);self.assertEqual(d['alarm_level'],3)
        self.assertFalse(d['alarm_can_stop_pwm']);self.assertEqual([cmd[0] for cmd in c.commands],[3,5])


if __name__=='__main__':unittest.main()
