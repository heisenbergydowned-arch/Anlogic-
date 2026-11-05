"""Real-window output boundaries. All packets and services are local fixtures."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from cabinet.normal_reference_guard import NormalReferenceGuard, SCHEMA, MASK
from normal_npu.core import FEATURES, GROUPS, live_input, validate_header
from normal_npu.presentation import fields


def status(now, configured=False):
    return dict(uptime_ms=now & MASK, configured=configured, hard_inhibit=not configured,
                applied_pwm_counts=1200 if configured else 0, requested_rpm=3000 if configured else 0,
                mode='RUN' if configured else 'STOPPING', test_mode=not configured,
                active=[], latched=[], input_validity=dict(rpm=True,adc=True,temperature=True,pressure=True))


def frame(end_ms, identity=7, start_cycles=None):
    end=end_ms*100000;start=end-25575000 if start_cycles is None else start_cycles
    h=[0]*32;h[:5]=[0x46524d31,0x10000,284,identity,end_ms & MASK]
    h[5:9]=[start & MASK,start>>32,end & MASK,end>>32]
    h[9:13]=[end-start,end-start,1024,1024];h[15]=0x3000
    h[16:19]=[1,0,2];h[21]=100000000;h[26]=0x202610f7
    return SimpleNamespace(header=h)


def idle():return dict(state='IDLE',controls_enabled=False,output_never_applied=True)


def sample(configured=False):
    contract=dict(device_id='fixture-device',configuration_words=[1,0,2]+[0]*14,
                  frame_identity=[1,0,2],controller_mode='RUN' if configured else 'STOPPING',
                  controller_diagnostic_mode=not configured)
    boot='fixture-device/session/1';f=frame(1000000);st=status(1000001,configured)
    tracker=NormalReferenceGuard();tracker.update(boot,status(999000,configured),idle())
    guard=tracker.update(boot,st,idle(),f)
    o=dict(link='ONLINE',received_at=1000.,boot=boot,feature_words=contract['configuration_words'],
           status=st,bench=idle(),normal_reference_guard=guard,
           frame=dict(state='RECEIVED_REAL',header=f.header,values={n:0. for n in FEATURES}),
           icm_diagnostics=dict(state='DIAGNOSTIC_ONLY',test=False,boot_id='fixture-device',snapshot_age_ms=0,
                sensors=[dict(channel=c,who=0x12,raw=[1,2,3],fresh=True,error=False,
                              config_verified=True,config_bad_mask=0,sample_age_ms=0) for c in ('A','B')]))
    return o,contract


class CollectorBoundaryTests(unittest.TestCase):
    def setUp(self):self.g=NormalReferenceGuard();self.boot='fixture-device/session/1'
    def update(self,now,bench=None,f=None,configured=False):
        return self.g.update(self.boot,status(now,configured),bench if bench is not None else idle(),f)

    def test_initial_boundary_requires_a_whole_new_window(self):
        self.assertEqual(self.update(1000,f=frame(1000))['state'],'WAIT_FULL_WINDOW')
        self.assertEqual(self.update(1200,f=frame(1200))['state'],'WAIT_FULL_WINDOW')
        ready=self.update(1300,f=frame(1300))
        self.assertEqual(ready['state'],'IDLE');self.assertEqual(ready['safe_since_uptime_ms'],1000)
        self.assertEqual(self.update(1400)['safe_since_uptime_ms'],1000)

    def test_queued_active_unknown_and_unconfirmed_are_blocked(self):
        for name,enabled in [('QUEUED_NOT_APPLIED',False),('ACTIVE_BENCH_NOT_CLOSED_LOOP',True),
                             ('OUTPUT_STOP_UNCONFIRMED',False),('UNKNOWN',False)]:
            with self.subTest(name=name):
                out=self.update(1000,dict(state=name,controls_enabled=enabled,id='trial'))
                self.assertEqual(out['state'],'BLOCKED');self.assertIsNone(out['safe_since_uptime_ms'])

    def test_terminal_readback_cannot_reuse_pre_stop_status(self):
        self.update(1000,dict(state='ACTIVE_BENCH_NOT_CLOSED_LOOP',controls_enabled=True,id='trial'))
        done=dict(state='COMPLETED',controls_enabled=False,id='trial',output_stop_confirmed=True,applied_bench_pwm_counts=0)
        self.assertEqual(self.update(1100,done,frame(1100))['reason'],'REFERENCE_WAIT_POST_TRIAL_STATUS')
        self.assertIsNone(self.update(1100,done)['safe_since_uptime_ms'])
        out=self.update(1101,done,frame(1101));self.assertEqual(out['safe_since_uptime_ms'],1101)
        self.assertEqual(out['state'],'WAIT_FULL_WINDOW')
        self.assertEqual(self.update(1350,done,frame(1350))['state'],'WAIT_FULL_WINDOW')
        self.assertEqual(self.update(1360,done,frame(1360))['state'],'IDLE')

    def test_untouched_rejection_or_cancel_recovers_without_fake_stop_confirmation(self):
        for name in ('REJECTED','STOPPED'):
            with self.subTest(name=name):
                self.g=NormalReferenceGuard()
                done=dict(state=name,controls_enabled=False,id='trial',output_never_applied=True)
                self.assertEqual(self.update(1000,done)['state'],'WAIT_FULL_WINDOW')
                self.assertEqual(self.update(1001,done)['safe_since_uptime_ms'],1001)
                self.assertEqual(self.update(1300,done,frame(1300))['state'],'IDLE')

    def test_terminal_without_never_applied_or_confirmed_stop_stays_blocked(self):
        for extra in ({},{'output_never_applied':False},{'output_stop_confirmed':True,'applied_bench_pwm_counts':1}):
            with self.subTest(extra=extra):
                out=self.update(1000,dict(state='REJECTED',controls_enabled=False,**extra))
                self.assertEqual(out['reason'],'BENCH_STOP_UNCONFIRMED')

    def test_nonzero_unconfigured_actual_output_blocks_even_with_idle_bench(self):
        for key,value in [('hard_inhibit',False),('applied_pwm_counts',1),('requested_rpm',1)]:
            st=status(1000);st[key]=value
            out=self.g.update(self.boot,st,idle(),frame(1000))
            self.assertEqual(out['reason'],'OUTPUT_OUTSIDE_REFERENCE')

    def test_clock_wrap_uses_actual_64_bit_window(self):
        self.update(MASK-100)
        self.assertEqual(self.update(MASK+100,f=frame(MASK+100))['state'],'WAIT_FULL_WINDOW')
        self.assertEqual(self.update(MASK+300,f=frame(MASK+300))['state'],'IDLE')

    def test_reconnect_and_collector_restart_reestablish_boundary(self):
        self.update(1000);self.assertEqual(self.update(1300,f=frame(1300))['state'],'IDLE')
        self.boot='fixture-device/session/2'
        self.assertEqual(self.update(1400,f=frame(1400))['state'],'WAIT_FULL_WINDOW')
        fresh=NormalReferenceGuard().update(self.boot,status(1500),idle(),frame(1500))
        self.assertEqual(fresh['state'],'WAIT_FULL_WINDOW')

    def test_status_reorder_invalidates_boundary(self):
        self.update(1000)
        self.assertEqual(self.update(999)['reason'],'REFERENCE_STATUS_CLOCK_REORDERED')

    def test_long_safe_run_reproves_boundary_before_half_cycle_ambiguity(self):
        self.update(1000);self.assertEqual(self.update(1300,f=frame(1300))['state'],'IDLE')
        now=1000+0x80000000-1000
        out=self.update(now,f=frame(now))
        self.assertEqual(out['state'],'WAIT_FULL_WINDOW');self.assertEqual(out['safe_since_uptime_ms'],now)
        self.assertEqual(self.update(now+300,f=frame(now+300))['state'],'IDLE')

    def test_output_profile_changes_reestablish_complete_window(self):
        self.update(1000);self.assertEqual(self.update(1300,f=frame(1300))['state'],'IDLE')
        self.assertEqual(self.update(1400,f=frame(1400),configured=True)['state'],'WAIT_FULL_WINDOW')
        self.assertEqual(self.update(1700,f=frame(1700),configured=True)['state'],'IDLE')
        self.assertEqual(self.update(1800,f=frame(1800))['state'],'WAIT_FULL_WINDOW')
        self.assertEqual(self.update(2100,f=frame(2100))['state'],'IDLE')

    def test_configured_run_nonzero_preserves_future_baseline_capability(self):
        self.update(1000,configured=True)
        self.assertEqual(self.update(1300,f=frame(1300),configured=True)['state'],'IDLE')


class NormalRuntimeGuardTests(unittest.TestCase):
    def setUp(self):self.o,self.contract=sample()
    def read(self):return live_input(dict(observation=self.o),1000.01,self.contract)

    def test_stable_zero_output_remains_real_input(self):
        x,identity=self.read();self.assertEqual(len(x),39)
        self.assertEqual(identity['frame_start_cycles'],self.o['frame']['header'][5] | self.o['frame']['header'][6]<<32)

    def test_missing_guard_or_bench_fails_closed(self):
        for key in ('bench','normal_reference_guard'):
            saved=self.o.pop(key)
            with self.assertRaises(ValueError):self.read()
            self.o[key]=saved

    def test_actual_output_overrides_stale_idle_marker(self):
        for key,value in [('hard_inhibit',False),('applied_pwm_counts',1),('requested_rpm',10)]:
            with self.subTest(key=key):
                self.o,self.contract=sample();self.o['status'][key]=value
                with self.assertRaisesRegex(ValueError,'OUTPUT_OUTSIDE_REFERENCE'):self.read()

    def test_current_diagnostic_contract_remains_zero_even_if_configured_flag_changes(self):
        self.o['status'].update(configured=True,hard_inhibit=False,applied_pwm_counts=500,requested_rpm=1000)
        with self.assertRaisesRegex(ValueError,'OUTPUT_OUTSIDE_REFERENCE'):self.read()

    def test_configured_run_nonzero_matches_its_own_contract(self):
        self.o,self.contract=sample(configured=True);self.read()

    def test_runtime_window_proof_survives_uptime_wrap(self):
        now=MASK+300;f=frame(now)
        self.o['status']['uptime_ms']=now&MASK
        self.o['frame']['header']=f.header
        self.o['normal_reference_guard'].update(safe_since_uptime_ms=MASK-100,status_uptime_ms=now&MASK)
        self.read()

    def test_guard_boot_status_and_bench_identity_must_match(self):
        for key,value in [('boot','other'),('status_uptime_ms',0),('bench_id','other'),('bench_state','COMPLETED')]:
            with self.subTest(key=key):
                self.o,self.contract=sample();self.o['normal_reference_guard'][key]=value
                with self.assertRaisesRegex(ValueError,'BOUNDARY_UNAVAILABLE'):self.read()

    def test_crossing_window_rejected_despite_fresh_end_and_idle_marker(self):
        self.o['normal_reference_guard']['safe_since_uptime_ms']=999900
        with self.assertRaisesRegex(ValueError,'FULL_POST_TRIAL_WINDOW'):self.read()

    def test_boundary_millisecond_is_excluded_without_fixed_delay(self):
        start=self.o['frame']['header'][5] | self.o['frame']['header'][6]<<32
        self.o['normal_reference_guard']['safe_since_uptime_ms']=start//100000
        with self.assertRaisesRegex(ValueError,'FULL_POST_TRIAL_WINDOW'):self.read()
        self.o['normal_reference_guard']['safe_since_uptime_ms']-=1
        self.read()

    def test_invalid_missing_or_future_window_times_are_rejected(self):
        for mutation in ('missing','reverse','span','future'):
            with self.subTest(mutation=mutation):
                self.o,self.contract=sample();h=self.o['frame']['header']
                if mutation=='missing':h[5:9]=[0]*4
                elif mutation=='reverse':h[5:7]=h[7:9];h[7]=0
                elif mutation=='span':h[5]+=100000
                else:h[6]+=1;h[8]+=1
                with self.assertRaisesRegex(ValueError,'WINDOW_TIME_UNAVAILABLE'):self.read()

    def test_empty_runtime_poll_remains_no_new_frame_after_recovery(self):
        self.o['frame']=dict(state='EMPTY')
        with self.assertRaisesRegex(ValueError,'NO_NEW_REAL_FRAME'):self.read()

    def test_training_header_contract_is_unchanged(self):
        h=copy.deepcopy(self.o['frame']['header']);h[5:9]=[0]*4
        st=copy.deepcopy(self.o['status'])
        for key in ('hard_inhibit','applied_pwm_counts','requested_rpm','configured'):st.pop(key)
        validate_header(h,st,self.contract)


class DisplayGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'result.json';self.o,self.contract=sample()
        _,identity=live_input(dict(observation=self.o),1000.01,self.contract)
        self.result=dict(schema='cabinet-normal-npu-live-v1',backend='Alnpu',
            model_source='REAL_USER_DECLARED_NORMAL_DIAGNOSTIC',formal=False,control_authority='NONE',
            fault_classes_trained=[],input_contract=self.contract,os_boot_id='os-boot',updated_at=1000.01,
            valid=True,status='RUNNING',source='REAL_CURRENT_SENSOR_FRAME',
            score=.25,execute_ms=.4,group_scores={n:.25 for n in GROUPS},state='BASELINE_MATCH',
            domain_score=.5,input_clipped=0,inference_count=3,training_rows=700,**identity)

    def show(self):
        self.path.write_text(json.dumps(self.result),encoding='utf-8');self.path.chmod(0o600)
        return fields(self.o,1000.02,self.path,'os-boot')

    def test_empty_poll_can_display_a_proven_new_window(self):
        self.o['frame']=dict(state='EMPTY')
        self.assertEqual(self.show()['panel_nn_valid'],'1')

    def test_old_result_does_not_revive_after_complete_new_collector_window(self):
        self.result['frame_start_cycles']=(self.o['normal_reference_guard']['safe_since_uptime_ms']-1)*100000
        self.assertEqual(self.show()['panel_nn_valid'],'0')
        self.o['frame']=dict(state='EMPTY')
        self.assertEqual(self.show()['panel_nn_valid'],'0')

    def test_missing_result_window_proof_is_not_assumed_new(self):
        self.result.pop('frame_start_cycles')
        self.assertEqual(self.show()['panel_nn_valid'],'0')

    def test_queued_bench_hides_a_still_fresh_result(self):
        self.o['bench'].update(state='QUEUED_NOT_APPLIED',id='trial')
        self.assertEqual(self.show()['panel_nn_valid'],'0')


if __name__=='__main__':unittest.main()
