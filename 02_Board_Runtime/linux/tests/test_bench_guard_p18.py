"""Synthetic register fixtures: no hardware, no deployment admission is created."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from commissioning.bench import BenchController,plan
from commissioning import bench_admission

class IO:
    def __init__(self):
        self.words={0x900:0x424e4331,0x904:0x20000,0x908:0,0x934:0,
                    0x538:400,0x554:1000,0x558:12000000}
        self.reads=[];self.writes=[];self.fail_read=None;self.fail_stop=False;self.ignore_stop=False
    def read(self,address):
        self.reads.append(address)
        if address==self.fail_read:raise OSError('fixture read failure')
        return self.words.get(address,0)
    def write(self,address,value):
        self.writes.append((address,value))
        if address==0x930 and self.fail_stop:raise OSError('fixture stop write failure')
        self.words[address]=value
        if address==0x928:self.words[0x908]=5
        if address==0x92c:self.words[0x934]=value
        if address==0x930 and not self.ignore_stop:self.words[0x908]=0;self.words[0x934]=0

def status():
    words=[0]*32;words[0]=0x8400;words[1]=100;words[8]=1000;words[22]=3000;words[24]=3000000;words[25]=25
    return dict(configured=False,configuration_id=0,applied_pwm_counts=0,raw_words=words,latched=[],uptime_ms=100,
                rpm_age_ms=0,input_validity={'rpm':True},measured_rpm=1000,temp_raw_1_16_C=400)

def prepared():
    profile=dict(source='REAL_USER_MEASUREMENTS',operator='UNIT_FIXTURE',reference_evidence_sha256='a'*64,
        wiring_verified=True,zero_pwm_not_poweroff_confirmed=True,max_duty_percent=30,current_zero_code=3000,
        current_trip_distance_code=500,temperature_trip_C=40,minimum_fg_period_clocks=100000,duration_limit_s=5)
    return plan(dict(profile=profile,steps=[dict(duty_percent=20,seconds=2)]))

def service():
    journal=[]
    return SimpleNamespace(mock=False,diagnostic_test=False,config={'control':{'enabled':False}},boot='UNIT/a1b2c3d4',
        collector_session='4ef7f5c5-744a-4fbd-a5f5-4d432b467466',connection_epoch=1,
        recorder=None,public_state=lambda:{'link':'ONLINE'},put_journal=lambda row:journal.append(row) or True,journal=journal)

class FeedbackGuardTests(unittest.TestCase):
    def setUp(self):
        self.service=service();self.io=IO();self.controller=SimpleNamespace(io=self.io);self.status=status();self.now=1000.
        self.bench=BenchController(self.service,admission_check=lambda boot:{'test_fixture_admission':True})
    def start(self):
        with patch('commissioning.bench.time.monotonic',return_value=self.now):self.bench.request_start(prepared(),self.service.boot)
        self.bench.poll(self.controller,self.status,self.now)
    def active_update(self,elapsed=.1):
        self.status['uptime_ms']+=int(elapsed*1000);self.status['raw_words'][1]=self.status['uptime_ms']
        self.bench.poll(self.controller,self.status,self.now+elapsed)
    def test_fresh_raw_feedback_and_existing_unqualified_cfg_can_arm(self):
        self.start();s=self.bench.snapshot()
        self.assertTrue(s['controls_enabled']);self.assertEqual(s['feedback_contract']['max_age_ms'],400)
        self.assertFalse(s['output_never_applied'])
        self.assertFalse(s['feedback_contract']['calibration_qualification_changed'])
        self.assertEqual(s['records'][0]['fg_period_clocks'],3000000);self.assertEqual(s['records'][0]['fg_pulses'],25)
        self.assertFalse(s['records'][0]['rpm_calibrated'])
        self.assertFalse(any(0x300<=a<0x360 or a==0x18 for a,v in self.io.writes))
    def test_arm_rejects_invalid_missing_stale_zero_and_nonfinite_feedback_without_writes(self):
        changes=[lambda s:s['input_validity'].update(rpm=False),lambda s:s.pop('rpm_age_ms'),
            lambda s:s.update(rpm_age_ms=float('nan')),lambda s:s['raw_words'].__setitem__(24,0),
            lambda s:s['raw_words'].__setitem__(24,True),lambda s:s['raw_words'].__setitem__(24,12000001),
            lambda s:(s.update(rpm_age_ms=400),s['raw_words'].__setitem__(12,400))]
        for change in changes:
            with self.subTest(change=change):
                self.setUp();change(self.status);self.start()
                self.assertEqual(self.bench.snapshot()['state'],'REJECTED');self.assertEqual(self.io.writes,[])
                self.assertTrue(self.bench.snapshot()['output_never_applied'])
                json.dumps(self.bench.snapshot(),allow_nan=False)
    def test_active_feedback_loss_stops_before_duty_renewal_and_keeps_raw_failure(self):
        self.start();before=len(self.io.writes);self.status['input_validity']['rpm']=False;self.status['raw_words'][0]&=~0x400
        self.active_update();s=self.bench.snapshot()
        self.assertEqual(self.io.writes[before:],[(0x930,0)]);self.assertEqual(s['reason'],'FG_FEEDBACK_INVALID')
        self.assertEqual(s['state'],'STOPPED');self.assertTrue(s['output_stop_confirmed']);self.assertFalse(s['power_disconnected'])
        self.assertIs(s['last_fg_observation']['fg_valid'],False);self.assertEqual(s['last_fg_observation']['raw_words']['24'],3000000)
    def test_active_stale_and_invalid_period_stop_without_renewal(self):
        for age,period,reason in [(400,3000000,'FG_FEEDBACK_STALE'),(0,0,'FG_PERIOD_INVALID')]:
            with self.subTest(reason=reason):
                self.setUp();self.start();before=len(self.io.writes)
                self.status['rpm_age_ms']=age;self.status['raw_words'][12]=age;self.status['raw_words'][24]=period
                self.active_update();self.assertEqual(self.bench.snapshot()['reason'],reason)
                self.assertEqual(self.io.writes[before:],[(0x930,0)])
    def test_duplicate_frozen_status_cannot_keep_age_zero_forever(self):
        self.start();before=len(self.io.writes)
        self.bench.poll(self.controller,self.status,self.now+.401)
        self.assertEqual(self.bench.snapshot()['reason'],'FG_FEEDBACK_STALE')
        self.assertEqual(self.io.writes[before:],[(0x930,0)])
    def test_actual_active_cfg_age_limit_is_used_without_new_defaults(self):
        self.io.words[0x538]=150;self.start();self.status['rpm_age_ms']=150;self.status['raw_words'][12]=150
        self.active_update();self.assertEqual(self.bench.snapshot()['reason'],'FG_FEEDBACK_STALE')
    def test_cached_capability_never_authorizes_write_after_new_magic_or_read_failure(self):
        for failure in ('magic','read'):
            with self.subTest(failure=failure):
                self.setUp();self.start();self.bench.stop();self.active_update()
                self.assertTrue(self.bench.snapshot()['hardware_supported']);self.io.writes=[]
                if failure=='magic':self.io.words[0x900]=0
                else:self.io.fail_read=0x904
                self.start();self.assertEqual(self.bench.snapshot()['state'],'REJECTED');self.assertEqual(self.io.writes,[])
    def test_active_capability_loss_does_not_touch_unknown_window_after_probe(self):
        self.start();self.io.writes=[];self.io.words[0x900]=0
        with self.assertRaisesRegex(ValueError,'BNC1_FIRMWARE_REQUIRED'):self.active_update()
        self.assertEqual(self.io.writes,[]);self.assertEqual(self.bench.snapshot()['state'],'OUTPUT_STOP_UNCONFIRMED')
    def test_revoked_admission_during_trial_performs_zero_bnc_access(self):
        self.start();self.io.reads=[];self.io.writes=[]
        def refused(boot):raise ValueError('BNC1_BOOT_ADMISSION_OLD_BOOT')
        self.bench.admission_check=refused
        with self.assertRaisesRegex(ValueError,'OLD_BOOT'):self.active_update()
        self.assertEqual(self.io.reads,[]);self.assertEqual(self.io.writes,[])
        self.assertEqual(self.bench.snapshot()['state'],'OUTPUT_STOP_UNCONFIRMED')
    def test_stop_write_failure_propagates_and_remains_unconfirmed(self):
        self.start();self.io.fail_stop=True;self.status['input_validity']['rpm']=False
        with self.assertRaisesRegex(OSError,'stop write failure'):self.active_update()
        s=self.bench.snapshot();self.assertEqual(s['state'],'OUTPUT_STOP_UNCONFIRMED');self.assertFalse(s['output_stop_confirmed'])
        self.assertFalse(s['controls_enabled']);self.assertIsNone(self.bench.active)
        self.bench.lost_link(OSError('outer IO failure'))
        self.assertEqual(self.bench.snapshot()['reason'],'FG_FEEDBACK_INVALID')
        self.bench.stop()
        self.assertEqual(self.bench.snapshot()['state'],'OUTPUT_STOP_UNCONFIRMED')
        with self.assertRaisesRegex(ValueError,'PREVIOUS_OUTPUT_STOP_UNCONFIRMED'):
            self.bench.request_start(prepared(),self.service.boot)
        self.assertFalse(self.bench.snapshot()['output_never_applied'])
    def test_stop_readback_failure_never_reports_completed(self):
        self.start();self.io.ignore_stop=True;self.bench.active['heartbeat']=self.now+2
        with self.assertRaisesRegex(RuntimeError,'STOP_READBACK'):self.bench.poll(self.controller,self.status,self.now+2)
        self.assertEqual(self.bench.snapshot()['state'],'OUTPUT_STOP_UNCONFIRMED')
        self.assertEqual(self.bench.snapshot()['reason'],'PLAN_FINISHED')
    def test_successful_completion_requires_zero_output_readback(self):
        self.start();self.bench.active['heartbeat']=self.now+2
        self.bench.poll(self.controller,self.status,self.now+2);s=self.bench.snapshot()
        self.assertEqual(s['state'],'COMPLETED');self.assertTrue(s['output_stop_confirmed'])
        self.assertEqual(self.io.words[0x934],0);self.assertFalse(s['power_disconnected'])
    def test_operator_stop_confirms_signal_zero_without_asserting_poweroff(self):
        self.start();self.bench.stop();self.active_update();s=self.bench.snapshot()
        self.assertEqual(s['state'],'STOPPED');self.assertEqual(s['reason'],'OPERATOR_STOP')
        self.assertTrue(s['output_stop_confirmed']);self.assertFalse(s['power_disconnected'])

class BootAdmissionTests(unittest.TestCase):
    BOOT='11111111-1111-4111-8111-111111111111'
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.admission=self.root/'admission.json';self.boot=self.root/'boot_id';self.boot.write_text(self.BOOT,encoding='utf-8')
        self.service=service();self.io=IO();self.controller=SimpleNamespace(io=self.io);self.now=1000.
        self.document=dict(schema=bench_admission.SCHEMA,verification=bench_admission.VERIFICATION,abi_version=0x20000,
            os_boot_id=self.BOOT,collector_boot=bench_admission.collector_identity(self.service),pl_boot_cookie=0xa1b2c3d4,
            boot_bin_sha256='a'*64,bitstream_sha256='b'*64)
    def tearDown(self):self.temp.cleanup()
    def write(self):
        self.admission.write_text(json.dumps(self.document),encoding='utf-8');self.admission.chmod(0o600)
    def invoke(self,owner=0):
        real_fstat=os.fstat
        def info(fd):
            s=real_fstat(fd)
            return SimpleNamespace(st_mode=s.st_mode,st_uid=owner,st_nlink=s.st_nlink,st_size=s.st_size)
        with patch.object(bench_admission,'ADMISSION_PATH',self.admission),patch.object(bench_admission,'BOOT_ID_PATH',self.boot),patch.object(bench_admission.os,'fstat',side_effect=info):
            b=BenchController(self.service)
            with patch('commissioning.bench.time.monotonic',return_value=self.now):b.request_start(prepared(),self.service.boot)
            b.poll(self.controller,status(),self.now)
            return b.snapshot()
    def test_valid_boot_bound_receipt_allows_only_subsequent_capability_check(self):
        self.write();s=self.invoke();self.assertTrue(s['controls_enabled'])
        self.assertEqual(self.io.reads[:2],[0x900,0x904]);self.assertEqual(s['boot_admission']['os_boot_id'],self.BOOT)
    def test_production_four_part_observer_identity_is_exactly_bound(self):
        self.service.boot='machine:843ad8d6299240c898a32874a96fe333/6a7064ff'
        self.document.update(collector_boot=bench_admission.collector_identity(self.service),pl_boot_cookie=0x6a7064ff)
        self.write();s=self.invoke();self.assertTrue(s['controls_enabled'])
        self.service.connection_epoch=2;self.io.reads=[];self.io.writes=[]
        s=self.invoke();self.assertEqual(s['state'],'REJECTED');self.assertEqual(self.io.reads,[])
    def test_short_or_extra_collector_suffix_cannot_weaken_binding(self):
        for value in ('UNIT/a1b2c3d4','UNIT/a1b2c3d4/4ef7f5c5-744a-4fbd-a5f5-4d432b467466/01',
                      'UNIT/a1b2c3d4/4ef7f5c5-744a-4fbd-a5f5-4d432b467466/1/extra'):
            with self.subTest(value=value),self.assertRaises(ValueError):bench_admission.collector_cookie(value)
    def test_missing_admission_performs_zero_mmio_reads_or_writes(self):
        s=self.invoke();self.assertEqual(s['state'],'REJECTED');self.assertEqual(self.io.reads,[]);self.assertEqual(self.io.writes,[])
    def test_old_boot_cookie_malformed_hash_nonroot_and_wide_permissions_have_zero_bnc_access(self):
        cases=('boot','cookie','collector','hash','nonroot','permissions')
        for case in cases:
            with self.subTest(case=case):
                original=copy.deepcopy(self.document)
                if case=='boot':self.document['os_boot_id']='22222222-2222-4222-8222-222222222222'
                if case=='cookie':self.document['pl_boot_cookie']+=1
                if case=='collector':self.document['collector_boot']='UNIT/12345678'
                if case=='hash':self.document['boot_bin_sha256']='not-a-hash'
                self.write()
                if case=='permissions':self.admission.chmod(0o644)
                self.io.reads=[];self.io.writes=[];s=self.invoke(owner=501 if case=='nonroot' else 0)
                self.assertEqual(s['state'],'REJECTED');self.assertEqual(self.io.reads,[]);self.assertEqual(self.io.writes,[])
                self.document=original
    def test_symlink_admission_has_zero_bnc_access(self):
        self.write();real=self.root/'real.json';self.admission.rename(real);self.admission.symlink_to(real)
        s=self.invoke();self.assertEqual(s['state'],'REJECTED');self.assertEqual(self.io.reads,[]);self.assertEqual(self.io.writes,[])
    def test_nonregular_admission_has_zero_bnc_access(self):
        self.admission.mkdir(mode=0o700)
        s=self.invoke();self.assertEqual(s['state'],'REJECTED');self.assertEqual(self.io.reads,[]);self.assertEqual(self.io.writes,[])

if __name__=='__main__':unittest.main()
