import copy,json,os,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from cabinet.temperature_pwm import TemperaturePWM,validate,curve_counts,words,BASE,MAGIC,ABI,ARM,CAPABILITY,SCHEMA

def config(enabled=True):
    return dict(schema=SCHEMA,device_id='test-device',revision=1,enabled=enabled,low_C=25,high_C=80,
        guards=dict(current_zero_code=16346,mean_trip_code=970,peak_trip_code=2425,max_rpm=6600,
                    reference=dict(qualified=False,source='TEST_FIXTURE')))

def status(actual=0,capable=True):
    raw=[0]*32;raw[0]=CAPABILITY if capable else 0;raw[7]=actual
    return dict(raw_words=raw,input_validity=dict(temperature=True,adc=True,rpm=True),
        temp_raw_1_16_C=352,applied_pwm_counts=actual,measured_rpm=1024)

class Registers:
    def __init__(self):
        self.cfg=[0]*4;self.flags=0;self.written=0;self.ready=False;self.accept=True
        self.target=2000;self.actual=2000;self.writes=[];self.reads=[];self.drop_write=None
    def read(self,address):
        self.reads.append(address);offset=address-BASE
        if offset==0:return MAGIC
        if offset==4:return ABI
        if offset==8:return self.flags|(4 if self.written==15 else 0)|(8 if self.ready else 0)
        if offset in (0x10,0x14,0x18,0x1c):return self.cfg[(offset-0x10)//4]
        if offset==0x2c:return 16346
        if offset==0x28:return ((self.target<<16)|self.actual) if self.flags&1 else 0
        raise AssertionError('Unexpected register')
    def write(self,address,value):
        self.writes.append((address,value));offset=address-BASE
        if address==self.drop_write:return
        if offset==0x20 and value==0:self.flags=0;self.written=0
        elif offset in (0x10,0x14,0x18,0x1c):
            i=(offset-0x10)//4;self.cfg[i]=value;self.written|=1<<i
        elif offset==0x20 and value==ARM:
            if self.written==15 and self.accept:self.flags=1
        elif offset==0x24:pass
        else:raise AssertionError('Unexpected command')

class TemperaturePWMTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'curve.json'
        self.path.write_text(json.dumps(config()))
        self.bench_active=False
        self.service=SimpleNamespace(config=dict(device_id='test-device',control=dict(enabled=False)),
            mock=False,diagnostic_test=False,bench=SimpleNamespace(snapshot=lambda **unused:dict(controls_enabled=self.bench_active)))
        self.ctrl=TemperaturePWM(self.service,self.path);self.io=Registers();self.device=SimpleNamespace(io=self.io)
        self.now=time.monotonic()
    def tearDown(self):self.temp.cleanup()
    def poll(self,feedback=None):
        self.now+=.1;self.ctrl.poll(self.device,feedback or status(),self.now,'boot/session/1')
        return self.ctrl.snapshot(self.now)
    def arm(self):
        self.assertEqual(self.poll()['state'],'RUNNING')
    def request(self,**changes):
        d=dict(expected_revision=1,enabled=True,low_C=25,high_C=80);d.update(changes);return d
    def test_curve_all_sensor_values_and_required_points(self):
        for raw in range(-880,2001):
            expected=0 if raw<=400 else 4000 if raw>=1280 else int((raw-400)/880*4000+.5)
            self.assertEqual(curve_counts(raw),expected)
        for temp,pct in [(25,0),(36,20),(47,40),(52.5,50),(58,60),(69,80),(80,100)]:
            self.assertEqual(curve_counts(int(temp*16)),pct*40)
    def test_old_firmware_never_touches_new_registers(self):
        self.assertEqual(self.poll(status(capable=False))['state'],'FIRMWARE_REQUIRED')
        self.assertEqual(self.io.reads,[]);self.assertEqual(self.io.writes,[])
    def test_only_temperature_readiness_precedes_arm(self):
        feedback=status();feedback['input_validity']['temperature']=False
        view=self.poll(feedback);self.assertEqual(view['state'],'WAITING_SENSOR')
        self.assertNotIn((BASE+0x20,ARM),self.io.writes)
        self.assertEqual(self.io.cfg,words(config()))
        feedback['input_validity']['temperature']=True
        feedback['input_validity']['adc']=False
        view=self.poll(feedback);self.assertEqual(view['state'],'RUNNING')
        self.assertFalse(self.io.ready);self.assertTrue(view['hardware_armed'])
        self.assertFalse(view['current_sensor_cutoff_enabled'])
    def test_published_actual_duty_is_observation_not_requested_duty(self):
        self.arm();view=self.poll(status(actual=1600))
        self.assertEqual(view['target_pwm_percent'],50);self.assertEqual(view['actual_pwm_percent'],40)
        self.assertEqual(self.ctrl.snapshot(self.now+1.01)['actual_pwm_percent'],None)
    def test_curve_commit_waits_for_new_actual_sample(self):
        view=self.poll(status(actual=3600))
        self.assertTrue(view['hardware_armed'])
        self.assertFalse(view['feedback_valid'])
        self.assertIsNone(view['actual_pwm_percent'])
        self.assertIsNone(view['target_pwm_percent'])
        view=self.poll(status(actual=1600))
        self.assertTrue(view['feedback_valid'])
        self.assertEqual(view['actual_pwm_percent'],40)
        self.assertEqual(view['target_pwm_percent'],50)
    def test_fault_is_not_rearmed_by_poll_or_service_restart(self):
        self.arm();self.io.flags=2|(4<<8)
        self.assertEqual(self.poll()['faults'],['CURRENT_PEAK'])
        count=len(self.io.writes);self.poll();self.assertEqual(len(self.io.writes),count)
        self.ctrl=TemperaturePWM(self.service,self.path)
        self.assertEqual(self.poll()['state'],'FAULT_LATCHED');self.assertEqual(len(self.io.writes),count)
    def test_explicit_new_revision_can_rearm_only_if_hardware_accepts(self):
        self.arm();self.io.flags=2|(4<<8);self.poll()
        self.ctrl.save(self.request());self.io.accept=False
        self.assertEqual(self.poll()['state'],'ARM_REJECTED')
        count=len(self.io.writes);self.io.accept=True
        self.assertEqual(self.poll()['state'],'APPLY_FAILED');self.assertEqual(len(self.io.writes),count)
    def test_saved_curve_and_enabled_state_survive_new_controller(self):
        result=self.ctrl.save(self.request(low_C=23,high_C=80))
        self.assertEqual(result['state'],'SAVED_PENDING_HARDWARE');self.assertEqual(self.io.writes,[])
        restored=TemperaturePWM(self.service,self.path).snapshot(self.now)
        self.assertEqual(restored['settings']['low_C'],23);self.assertTrue(restored['settings']['enabled'])
        self.assertEqual(os.stat(self.path).st_mode&0o777,0o600)
    def test_corrupt_config_does_not_enable_output(self):
        self.path.write_text('{broken');self.ctrl=TemperaturePWM(self.service,self.path)
        self.assertEqual(self.poll()['state'],'NOT_CONFIGURED');self.assertNotIn((BASE+0x20,ARM),self.io.writes)
    def test_revision_conflict_does_not_overwrite_settings(self):
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.ctrl.save(self.request(expected_revision=0))
        self.assertEqual(self.path.read_bytes(),before)
    def test_protection_fields_cannot_be_supplied_from_curve_api(self):
        with self.assertRaises(ValueError):self.ctrl.save(dict(self.request(),guards=config()['guards']))
    def test_bad_endpoints_and_nonfinite_values_rejected(self):
        for low,high in [(25,25),(-1,80),(61,80),(25,101),(float('nan'),80),(25,float('inf'))]:
            with self.subTest(low=low,high=high),self.assertRaises(ValueError):self.ctrl.save(self.request(low_C=low,high_C=high))
    def test_failed_enable_save_does_not_change_live_intent(self):
        self.path.write_text(json.dumps(config(False)));self.ctrl=TemperaturePWM(self.service,self.path)
        with patch('cabinet.temperature_pwm.atomic',side_effect=OSError('SD full')),self.assertRaises(OSError):
            self.ctrl.save(self.request())
        self.assertEqual(self.poll()['state'],'STOPPED_UNSAVED');self.assertNotIn((BASE+0x20,ARM),self.io.writes)
    def test_disable_still_reaches_hardware_when_sd_write_fails(self):
        self.arm()
        with patch('cabinet.temperature_pwm.atomic',side_effect=OSError('SD full')),self.assertRaises(OSError):
            self.ctrl.save(self.request(enabled=False))
        self.assertEqual(self.poll(status(actual=2000))['state'],'STOPPING')
        self.assertEqual(self.io.flags,0)
        view=self.poll(status(actual=0));self.assertEqual(view['state'],'STOPPED_UNSAVED')
        self.assertTrue(view['settings']['enabled']);self.assertTrue(view['runtime_stop_requested'])
    def test_bad_readback_never_arms(self):
        self.io.drop_write=BASE+0x14
        self.assertEqual(self.poll()['state'],'CONFIGURATION_REJECTED')
        self.assertNotIn((BASE+0x20,ARM),self.io.writes)
    def test_other_owner_prevents_enable(self):
        self.bench_active=True
        with self.assertRaises(ValueError):self.ctrl.save(self.request())
        self.assertEqual(self.poll()['state'],'OWNER_CONFLICT')
        self.bench_active=False;self.service.config['control']['enabled']=True
        with self.assertRaises(ValueError):self.ctrl.save(self.request())
    def test_invalid_readback_warns_without_stop_and_recovers(self):
        self.arm();before=len(self.io.writes);self.io.actual=4001
        view=self.poll();self.assertEqual(view['state'],'READBACK_INVALID')
        self.assertIn('CONTROL_READBACK_INVALID',view['faults']);self.assertIsNone(view['actual_pwm_percent'])
        self.assertEqual(self.io.flags,1);self.assertNotIn((BASE+0x20,0),self.io.writes[before:])
        self.io.actual=2000;self.assertEqual(self.poll()['state'],'RUNNING')
        self.assertNotIn((BASE+0x20,0),self.io.writes[before:])
    def test_monitor_restart_does_not_stop_autonomous_pwm(self):
        self.arm();before=list(self.io.writes);self.ctrl.shutdown(self.device)
        self.assertEqual(self.io.flags,1);self.assertEqual(self.io.writes,before)
        self.ctrl=TemperaturePWM(self.service,self.path)
        self.assertEqual(self.poll()['state'],'RUNNING')
        self.assertEqual(self.io.writes[len(before):],[(BASE+0x24,1)])

if __name__=='__main__':unittest.main()
