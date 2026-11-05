"""Independent controller regressions; synthetic fixtures, no MMIO or board I/O."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cabinet.parameters import ParameterControl
from cabinet.policy import FixedRpmLoop, Fusion
from commissioning import control_jobs, deploy
from commissioning.bench import AUTHORIZATION
from tests import test_control_startup as startup_fixture
from tests import test_control_completion as web_fixture
from tests import test_commissioning_deploy as deploy_fixture


class SetpointResponseReview(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        helper=startup_fixture.StartupTests()
        self.outer=helper.loop(setpoint_C=35,ki_rpm_per_C_s=0)
        self.status=helper.status(mode='RUN',fan_action='PI',requested_rpm=2000,measured_rpm=2000,
            configured=True,input_validity=dict(temperature=True),applied_pwm_counts=1600)
        self.state=dict(link='ONLINE',test=False,status_age_ms=0,frame_age_ms=0,status=self.status,
            frame=dict(quality=0,test=False,calibration_id=7,feature_config_id=1,bitstream_id='202610f7'))
        evidence='SYNTHETIC_CONTROLLER_REGRESSION_NOT_CALIBRATION'
        profile=dict(schema='cabinet-parameter-envelope-v1',device_id='fixture',control_evidence=evidence,
            temperature_evidence=evidence,calibration_id=7,feature_config_id=1,pl_build_id=0x202610f7,setpoint_C=[30,40])
        path=Path(self.temp.name)/'profile.json';path.write_text(json.dumps(profile))
        config=dict(device_id='fixture',control=dict(enabled=True,qualified=True,evidence=evidence,regulation_mode='temperature'),
            temperature_loop=dict(self.outer.c,evidence=evidence),contract=dict(calibration_id=7,feature_config_id=1),
            parameter_control=dict(enabled=True,profile=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        self.service=SimpleNamespace(config=config,stop=threading.Event(),mock=False,diagnostic_test=False,valid_input=True,
            boot='fixture-boot',collector_session='fixture-session',connection_epoch=1,outer=self.outer,
            public_state=lambda:copy.deepcopy(self.state),store=SimpleNamespace(diagnostic=Mock()),put_journal=Mock(return_value=True))
        self.parameters=ParameterControl(self.service)
        self.assertEqual(self.outer.update(self.status,10),2000)

    def queue(self,setpoint,identity='1'*32):
        p=self.parameters.preview(dict(request_id=identity,expected_revision=self.parameters.revision,
            context=self.parameters.context(),setpoint_C=setpoint))
        return p,self.parameters.commit(dict(request_id=identity,nonce=p['nonce']))

    def test_ki_zero_lower_setpoint_increases_rpm_with_existing_slew(self):
        prior=(self.outer.target,self.outer.last,self.outer.integral)
        p,queued=self.queue(30);self.assertEqual(queued['state'],'QUEUED_NOT_APPLIED')
        self.parameters.process()
        self.assertEqual((self.outer.target,self.outer.last,self.outer.integral),prior)
        self.assertEqual([self.outer.update(self.status,t) for t in (10.25,10.5,10.75,11)],
                         [2125,2250,2375,2500])
        self.assertEqual(self.parameters.results[p['request_id']]['state'],'APPLIED_PS_SETPOINT_NOT_PL_OUTPUT_CONFIRMATION')
        self.assertFalse(self.parameters.summary()['pl_output_confirmed'])

    def test_ki_zero_higher_setpoint_decreases_rpm_with_existing_slew(self):
        self.queue(40);self.parameters.process()
        self.assertEqual([self.outer.update(self.status,t) for t in (10.25,10.5,10.75,11)],
                         [1875,1750,1625,1500])

    def test_queued_fault_or_changed_owner_cannot_change_temperature_target(self):
        for change in ('fault','epoch'):
            p,unused=self.queue(30,'1'*32 if change=='fault' else '2'*32)
            if change=='fault':self.status['latched']=['TEMP_HARD']
            else:self.service.connection_epoch+=1
            self.parameters.process()
            self.assertEqual(self.outer.c['setpoint_C'],35)
            self.assertEqual(self.parameters.results[p['request_id']]['state'],'REJECTED_NOT_APPLIED')
            self.status['latched']=[]

    def test_loaded_profile_is_distinct_from_current_parameter_readiness(self):
        self.assertTrue(self.parameters.summary()['enabled'])
        cases=[('speed','FIXED_SPEED_MODE'),('disabled','CONTROL_DISABLED'),('stale','LIVE_OWNER_NOT_READY')]
        for kind,reason in cases:
            if kind=='speed':self.service.config['control']['regulation_mode']='speed'
            elif kind=='disabled':self.service.config['control']['enabled']=False
            else:self.state['status_age_ms']=501
            summary=self.parameters.summary()
            self.assertTrue(summary['profile_loaded']);self.assertFalse(summary['enabled'])
            self.assertEqual(summary['readiness_reason'],reason)
            with self.assertRaises(ValueError):self.queue(30)
            self.service.config['control'].update(regulation_mode='temperature',enabled=True)
            self.state['status_age_ms']=0

    def test_inner_saturation_still_holds_integral_after_setpoint_change(self):
        self.outer.c=dict(self.outer.c,ki_rpm_per_C_s=10)
        self.status['applied_pwm_counts']=self.outer.c['pwm_max_counts']
        integral=self.outer.integral;self.queue(30);self.parameters.process()
        self.assertEqual(self.outer.update(self.status,10.25),2125)
        self.assertEqual(self.outer.integral,integral)
        self.assertEqual(self.outer.coordination['state'],'INNER_SATURATION_INTEGRAL_HELD')

    def test_wrong_nonce_does_not_queue_or_change_pi_state(self):
        p=self.parameters.preview(dict(request_id='1'*32,expected_revision=0,context=self.parameters.context(),setpoint_C=30))
        with self.assertRaises(ValueError):self.parameters.commit(dict(request_id=p['request_id'],nonce='0'*32))
        self.assertIsNone(self.parameters.pending);self.assertEqual(self.outer.c['setpoint_C'],35)

    def test_commissioned_owner_readback_and_exact_context_are_required_for_readiness(self):
        self.service.config['commissioning']={'fixture':True}
        owner=dict(self.parameters.context(),verified=True,binding_error=None)
        self.state['control_owner']=owner
        self.assertTrue(self.parameters.summary()['enabled'])
        for field,value in [('verified',False),('binding_error','READBACK_MISMATCH'),
                            ('boot_id','old'),('collector_session','old'),('connection_epoch',0)]:
            self.state['control_owner']=dict(owner,**{field:value})
            summary=self.parameters.summary()
            self.assertTrue(summary['profile_loaded']);self.assertFalse(summary['enabled'])
            with self.assertRaisesRegex(ValueError,'verified.*owner'):self.queue(30)
        self.state.pop('control_owner')
        self.assertFalse(self.parameters.summary()['enabled'])


class FixedSpeedReview(unittest.TestCase):
    def test_fixed_target_does_not_follow_temperature_but_hard_fault_still_blocks(self):
        helper=startup_fixture.StartupTests();loop=FixedRpmLoop(helper.loop().c,2200)
        for index,temperature in enumerate((20,30,40,60)):
            status=helper.status(mode='RUN',fan_action='PI',requested_rpm=2200,measured_rpm=2150,
                temp_raw_1_16_C=temperature*16,applied_pwm_counts=1600)
            self.assertEqual(loop.update(status,index*.25),2200)
        for fault in ('TEMP_HARD','OC_HARD','STALL_CORROBORATED','OVERSPEED','VIB_HARD'):
            self.assertIsNone(loop.update(dict(status,active=[fault]),2))
        self.assertIsNone(loop.update(dict(status,mode='LOCKED',latched=['TEMP_HARD']),3))

    def test_physical_boost_and_severity_are_not_lowered_by_normal_model(self):
        status=dict(alarm_level=3,active=['TEMP_HARD'],latched=[],fan_action='BOOST')
        fusion=Fusion(dict(confidence_min=.8,confirm_ms=100,max_gap_ms=500))
        for now in (0,100,200):
            result=fusion.evaluate(dict(label='normal',confidence=.99),status,now,formal=True)
            self.assertEqual(result['level'],3);self.assertEqual(result['fan_action'],'BOOST')
            self.assertIn('TEMP_HARD',result['physical_causes'])


class ArmTransactionReview(unittest.TestCase):
    def setUp(self):
        self.case=deploy_fixture.Transactions();self.case.setUp();self.addCleanup(self.case.tearDown)
        deploy.apply(self.case.out,self.case.pin)
        self.case.status.update(configured=True,configuration_id=self.case.cw[1],active=[])
        self.case.status['raw_words'][0]=0x5a00  # Valid controller flags, KEY2 absent.
        self.case.calls.clear();self.case.writes.clear()

    def test_confirmed_arm_without_key_uses_exact_applied_fit_and_no_mmio_writes(self):
        result=deploy.arm(self.case.out,self.case.pin,True,mode='speed',target_rpm=2000)
        self.assertTrue(self.case.edge()['control']['enabled'])
        self.assertEqual(self.case.edge()['control']['target_rpm'],2000)
        self.assertEqual(result['status'],'CONTROLLED_TRIAL_REQUESTED')
        self.assertFalse(result['physical_closed_loop_accepted']);self.assertEqual(self.case.writes,[])

    def test_absent_key_does_not_bypass_fit_source_pin_or_explicit_confirmation(self):
        with self.assertRaises(ValueError):deploy.arm(self.case.out,self.case.pin,False)
        with self.assertRaises(ValueError):deploy.arm(self.case.out,'0'*64,True)
        with patch('commissioning.deploy.SOURCE','REAL_USER_MEASUREMENTS'):
            with self.assertRaisesRegex(ValueError,'Fixture'):deploy.arm(self.case.out,self.case.pin,True)
        self.assertEqual(self.case.calls,[]);self.assertFalse(self.case.edge()['control']['enabled'])

    def test_absent_key_does_not_bypass_exact_readback_or_physical_protection(self):
        original=copy.deepcopy(self.case.status)
        for change in ('latch','current','temperature','invalid'):
            self.case.status.clear();self.case.status.update(copy.deepcopy(original))
            if change=='latch':self.case.status['latched']=['OC_HARD']
            elif change=='current':self.case.status['raw_words'][22]=32767
            elif change=='temperature':self.case.status['temp_raw_1_16_C']=2000
            else:self.case.status['input_validity']['temperature']=False
            with self.assertRaises(ValueError):deploy.arm(self.case.out,self.case.pin,True)
        self.case.status.clear();self.case.status.update(original)
        self.case.obs['control']['control_words']=[0]*24
        with self.assertRaisesRegex(ValueError,'MISMATCH'):deploy.arm(self.case.out,self.case.pin,True)
        self.assertEqual(self.case.calls,[]);self.assertFalse(self.case.edge()['control']['enabled'])

    def test_apply_still_requires_real_local_configuration_permission(self):
        with self.assertRaisesRegex(ValueError,'KEY2'):deploy.apply(self.case.out,self.case.pin)
        self.assertEqual(self.case.calls,[]);self.assertEqual(self.case.writes,[])

    def test_arm_write_failure_after_replace_restores_standby_and_collector(self):
        original=deploy.json_write;injected=[]
        def fail_after_replace(path,value):
            original(path,value)
            if str(path)=='/etc/cabinet/edge.json' and value['control']['enabled'] and not injected:
                injected.append(True);raise OSError('DIRECTORY_FSYNC_FAILED_AFTER_RENAME')
        with patch('commissioning.deploy.json_write',side_effect=fail_after_replace):
            with self.assertRaisesRegex(OSError,'DIRECTORY_FSYNC'):deploy.arm(self.case.out,self.case.pin,True)
        self.assertFalse(self.case.edge()['control']['enabled'])
        self.assertIn(['systemctl','start','cabinet-edge','cabinet-local-display'],self.case.calls)

    def test_failed_arm_rollback_is_reported_for_review_not_as_disarmed(self):
        original=deploy.json_write
        def both_writes_fail(path,value):
            if value['control']['enabled']:
                original(path,value);raise OSError('ARM_RENAME_DONE_SYNC_FAILED')
            raise OSError('STANDBY_RESTORE_STORAGE_FAILED')
        with patch('commissioning.deploy.json_write',side_effect=both_writes_fail):
            with self.assertRaisesRegex(RuntimeError,'ROLLBACK_REQUIRES_REVIEW') as raised:
                deploy.arm(self.case.out,self.case.pin,True)
        self.assertIn('ARM_RENAME_DONE_SYNC_FAILED',str(raised.exception.__cause__))
        self.assertNotIn(['systemctl','start','cabinet-edge','cabinet-local-display'],self.case.calls)


class WebControlReview(unittest.TestCase):
    def setUp(self):
        self.case=web_fixture.ControlTransactions();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.base.write_bytes((self.case.package/'edge.standby.json').read_bytes())
        self.case.state['status'].update(configured=True,raw_words=[0x5a00]+[0]*31)
        self.bench=dict(state='IDLE',controls_enabled=False)
        self.case.service.bench.snapshot=lambda record_limit=None:dict(self.bench)

    def preview(self):return self.case.work.action('control-preview',self.case.request('arm','speed',2000))
    def queue(self):
        p=self.preview();r=self.case.work.action('control-confirm',dict(nonce=p['nonce'],confirm=True))
        return control_jobs.document(self.case.work.control.queue/(r['id']+'.json'))

    def test_arm_preview_without_key_retains_nonce_and_context_guard(self):
        p=self.preview();self.assertFalse(p['local_key_required'])
        with self.assertRaises(ValueError):self.case.work.action('control-confirm',dict(nonce='wrong',confirm=True))
        p=self.preview();self.case.service.connection_epoch+=1
        with self.assertRaisesRegex(ValueError,'context changed'):
            self.case.work.action('control-confirm',dict(nonce=p['nonce'],confirm=True))
        self.assertEqual(self.case.work.control.records(),[])

    def test_queued_or_unconfirmed_bench_blocks_formal_arm(self):
        for state in ('QUEUED_NOT_APPLIED','OUTPUT_STOP_UNCONFIRMED'):
            self.bench.update(state=state,controls_enabled=False)
            with self.assertRaisesRegex(ValueError,'bench'):self.preview()

    def test_bench_start_is_rejected_after_control_job_is_queued(self):
        self.queue()
        with self.assertRaisesRegex(ValueError,'CONTROL_TRANSACTION_PENDING'):
            self.case.work.bench_start(dict(preview_id='unused',start_controlled_trial=True,authorization=AUTHORIZATION))

    def test_executor_rechecks_bench_before_invoking_deployer(self):
        job=self.queue();original=control_jobs.document
        def read(path):
            return dict(observation=dict(boot='HW/SESSION/1',bench=dict(state='OUTPUT_STOP_UNCONFIRMED',controls_enabled=False))) if str(path)=='/run/cabinet-live/state.json' else original(path)
        with patch('commissioning.control_jobs.document',side_effect=read),patch('commissioning.deploy.arm') as arm:
            with self.assertRaisesRegex(ValueError,'bench'):control_jobs.execute(self.case.work.root,self.case.base,job)
        arm.assert_not_called()


class DurableCommissioningReview(unittest.TestCase):
    def test_config_replace_syncs_parent_and_keeps_private_permissions(self):
        from normal_npu import baseline_store
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'edge.json'
            with patch.object(baseline_store,'fsync_directory',wraps=baseline_store.fsync_directory) as sync:
                deploy.atomic(path,b'{"fixture":true}\n')
            self.assertEqual(path.read_bytes(),b'{"fixture":true}\n')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            sync.assert_called_once_with(path.parent)


class SoleHardwareOwnerReview(unittest.TestCase):
    def test_actual_hardware_loop_forwards_rpm_target_only_after_heartbeat(self):
        from cabinet.service import Service
        from tests.test_local_display import CONFIG, CountingController, healthy_status
        for mode,expected in (('temperature',2125),('speed',2200)):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                config=copy.deepcopy(CONFIG);config['database']=str(Path(directory)/'events.db')
                config['control'].update(enabled=True,qualified=True,evidence='SYNTHETIC_OWNER_TEST',regulation_mode=mode,target_rpm=2200)
                config['temperature_loop']=startup_fixture.StartupTests().loop(setpoint_C=30,ki_rpm_per_C_s=0).c
                controller=CountingController();commands=[];packets=[]
                controller.command=lambda *args:commands.append(args)
                controller.frame=lambda:None
                status=healthy_status(1000)
                status.update(raw_words=[0x7e00]+[0]*31,requested_rpm=2000,measured_rpm=2000,
                    applied_pwm_counts=1600,temp_raw_1_16_C=35*16,temp_age_ms=0)
                controller.status=lambda:copy.deepcopy(status)
                class Observer:
                    def submit(self,packet):packets.append(packet);service.stop.set()
                service=Service(config,controller=controller,observer=Observer())
                try:
                    if mode=='temperature':
                        service.outer.target=2000;service.outer.last=999.75;service.outer.integral=1000
                    with patch('cabinet.service.time.monotonic',return_value=1000):service.io_loop()
                    self.assertEqual(commands,[(3,),(1,expected)])
                    self.assertEqual(packets[-1]['control']['coordination']['outer_target_rpm'],expected)
                    self.assertTrue(packets[-1]['control']['enabled'])
                finally:service.store.close()

    def test_actual_binding_loss_blocks_queued_parameter_and_recovery_restores_readiness(self):
        from cabinet.service import Service
        from tests.test_local_display import CONFIG, CountingController, healthy_status
        with tempfile.TemporaryDirectory() as directory:
            config=copy.deepcopy(CONFIG);config['database']=str(Path(directory)/'events.db');config['poll_ms']=1
            evidence='SYNTHETIC_READBACK_REVIEW_NOT_CALIBRATION'
            config['control'].update(enabled=True,qualified=True,evidence=evidence,regulation_mode='temperature')
            config['temperature_loop']=startup_fixture.StartupTests().loop(setpoint_C=35,ki_rpm_per_C_s=0).c
            config['temperature_loop']['evidence']=evidence
            config['contract'].update(calibration_id=7,feature_config_id=1)
            cw=[15,55]+[0]*22;fw=[1,7,1]+[0]*14
            config['commissioning']=dict(source='REAL_USER_MEASUREMENTS',evidence_sha256='1'*64,control_words=cw,feature_words=fw)
            profile=dict(schema='cabinet-parameter-envelope-v1',device_id=config['device_id'],control_evidence=evidence,
                temperature_evidence=evidence,calibration_id=7,feature_config_id=1,pl_build_id=0x202610f7,setpoint_C=[30,40])
            path=Path(directory)/'profile.json';path.write_text(json.dumps(profile))
            config['parameter_control']=dict(enabled=True,profile=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            controller=CountingController();commands=[];packets=[];summaries=[];queued=[]
            controller.command=lambda *args:commands.append(args);controller.frame=lambda:None
            controller.io=SimpleNamespace(read=lambda address:123 if address==0x1050 else 0)
            status=healthy_status(1000)
            status.update(raw_words=[0x7e00]+[0]*31,configuration_id=55,requested_rpm=2000,measured_rpm=2000,
                applied_pwm_counts=1600,temp_raw_1_16_C=35*16,temp_age_ms=0)
            controller.status=lambda:copy.deepcopy(status)
            class Observer:
                def submit(self,packet):
                    packets.append(packet);summaries.append(service.parameters.summary())
                    if len(packets)==1:
                        preview=service.parameters.preview(dict(request_id='1'*32,expected_revision=0,
                            context=service.parameters.context(),setpoint_C=30))
                        queued.append(service.parameters.commit(dict(request_id=preview['request_id'],nonce=preview['nonce'])))
                    if len(packets)==3:service.stop.set()
            service=Service(config,controller=controller,observer=Observer())
            try:
                # Continue an already identified collector with a fresh prior
                # frame; a new connection intentionally invalidates old frames.
                service.boot=config['device_id']+'/0000007b';service.connection_epoch=1
                service.valid_input=True;service.frame_received=1000
                service.state['frame']=dict(end_ms=1000000,quality=0,test=False,calibration_id=7,feature_config_id=1,bitstream_id='202610f7')
                service.outer.target=2000;service.outer.last=999.75;service.outer.integral=1000
                bad=list(cw);bad[6]=1
                with patch('cabinet.service.time.monotonic',return_value=1000),\
                        patch('cabinet.service.read_control_words',side_effect=lambda io:bad if len(packets)==1 else cw),\
                        patch('cabinet.service.read_feature_configuration',return_value=fw),\
                        patch('cabinet.service.read_mailbox',return_value=dict(queued_frames=0,dropped_frames=0)):
                    service.io_loop()
                self.assertEqual([s['enabled'] for s in summaries],[True,False,True])
                self.assertTrue(all(s['profile_loaded'] for s in summaries))
                self.assertIn('MISMATCH',packets[1]['control']['binding_error'])
                self.assertFalse(packets[1]['control']['enabled'])
                self.assertEqual(service.outer.c['setpoint_C'],35)
                self.assertEqual(service.parameters.results[queued[0]['request_id']]['state'],'REJECTED_NOT_APPLIED')
                self.assertEqual(commands,[(3,),(1,2000)])
            finally:service.store.close()


if __name__=='__main__':unittest.main(verbosity=2)
