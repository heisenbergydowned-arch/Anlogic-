"""Control lifecycle and request provenance fixtures; no board/physical claims."""
import copy,json,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from cabinet.policy import FixedRpmLoop
from cabinet.control_display import ControlDisplay
from commissioning import control_jobs
from commissioning.workbench import Workbench
from commissioning.fit import build,save
from tests.test_commissioning_ready import dataset,SOURCE
from tests import test_commissioning_ready as display_fixtures
from tests import test_control_startup as startup_fixtures

class Regulation(unittest.TestCase):
    def test_fresh_operator_owner_can_reenter_expired_target_fallback(self):
        helper=startup_fixtures.StartupTests();loop=helper.loop()
        status=helper.status(mode='FALLBACK',fan_action='FALLBACK',active=['CMD_EXPIRED'],applied_pwm_counts=1500,requested_rpm=2000)
        self.assertEqual(loop.update(status,0),1500)
        self.assertIsNone(loop.update(status,.1))

    def test_fallback_reentry_does_not_override_physical_fault(self):
        helper=startup_fixtures.StartupTests()
        for cause in ('CURRENT_HIGH','TEMP_WARN','FG_LOSS','OC_HARD','PS_LOSS'):
            status=helper.status(mode='FALLBACK',fan_action='FALLBACK',active=[cause],applied_pwm_counts=1500)
            self.assertIsNone(helper.loop().update(status,0))

    def test_fixed_speed_uses_pl_ramp_and_keeps_temperature_target_absent(self):
        helper=startup_fixtures.StartupTests();loop=FixedRpmLoop(helper.loop().c,2200)
        self.assertEqual(loop.update(helper.status(),0),2200)
        self.assertEqual(loop.update(helper.status(mode='STARTING',fan_action='STARTUP',requested_rpm=2200),.25),2200)
        sample=display_fixtures.ControlDisplayTests().sample(1);sample['control'].update(regulation_mode='speed',temperature_enabled=False)
        fields=ControlDisplay().fields(sample,1)
        self.assertEqual(fields['panel_control_target_valid'],'1');self.assertEqual(fields['panel_control_temp_target'],'--')

    def test_fixed_speed_never_restarts_after_local_stop(self):
        helper=startup_fixtures.StartupTests();loop=FixedRpmLoop(helper.loop().c,2200)
        loop.update(helper.status(mode='RUN',fan_action='PI',requested_rpm=2200),0)
        self.assertIsNone(loop.update(helper.status(mode='STOPPING'),.25))

    def test_fixed_speed_rejects_invalid_feedback_owner_and_limits(self):
        helper=startup_fixtures.StartupTests()
        for target in (True,0,999,4001):
            with self.assertRaises(ValueError):FixedRpmLoop(helper.loop().c,target)
        for values in (dict(raw_words=[0x5a40]+[0]*31),dict(raw_words=[0x5800]+[0]*31),dict(temp_age_ms=3000),dict(latched=['OC_HARD']),dict(active=['FG_LOSS'])):
            self.assertIsNone(FixedRpmLoop(helper.loop().c,2200).update(helper.status(**values),0))

class ControlTransactions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.inputs=self.root/'inputs';dataset(self.inputs)
        self.base=self.inputs/'base.json';base=json.loads(self.base.read_text());base['control']['enabled']=False;save(self.base,base)
        self.state=dict(link='ONLINE',status_age_ms=1,status=dict(raw_words=[0x8000]+[0]*31,configured=False))
        self.service=SimpleNamespace(stop=threading.Event(),boot='HW',collector_session='SESSION',connection_epoch=1,
            public_state=lambda:copy.deepcopy(self.state),bench=SimpleNamespace(snapshot=lambda record_limit=None:dict(controls_enabled=False,state='IDLE')))
        self.addCleanup(self.service.stop.set)
        self.work=Workbench(self.root/'work',self.base,self.service)
        self.fit_id='1'*32;folder=self.work.root/'jobs'/self.fit_id;folder.mkdir()
        result=build(self.inputs,self.base,folder/'fitted',allow_fixture=True)
        self.fit=dict(id=self.fit_id,operation='fit',state='COMPLETED',revision=self.work.revision(),result=result)
        save(folder/'job.json',self.fit);self.work.jobs[self.fit_id]=self.fit;self.package=folder/'fitted'
        for target,value in (('commissioning.deploy.SOURCE',SOURCE),('commissioning.runtime.SOURCE',SOURCE),
                             ('commissioning.control_jobs.boot_id','TEST-BOOT'),('commissioning.control_jobs.manager_alive',True)):
            if target.endswith(('boot_id','manager_alive')):mock=patch(target,return_value=value)
            else:mock=patch(target,value)
            mock.start();self.addCleanup(mock.stop)
    def request(self,operation='apply',mode=None,target=None):
        return dict(revision=self.work.revision(),fit_job_id=self.fit_id,operation=operation,mode=mode,target_rpm=target)
    def confirmed(self):
        p=self.work.action('control-preview',self.request())
        result=self.work.action('control-confirm',dict(nonce=p['nonce'],confirm=True))
        return control_jobs.document(self.work.control.queue/(result['id']+'.json'))
    def test_preview_does_not_apply_and_confirm_only_creates_durable_job(self):
        with patch('commissioning.deploy.apply') as apply:
            job=self.confirmed()
        apply.assert_not_called();self.assertEqual(job['state'],'QUEUED')
        self.assertEqual(job['context']['collector_boot'],'HW/SESSION/1')
        with self.assertRaises(ValueError):self.work.action('control-confirm',dict(nonce=job['nonce'],confirm=True))
    def test_learning_started_after_preview_blocks_control_confirmation(self):
        preview=self.work.action('control-preview',self.request())
        with patch.object(self.work.learning,'busy',return_value=True):
            with self.assertRaisesRegex(ValueError,'WAIT_FOR_NPU_LEARNING'):
                self.work.action('control-confirm',dict(nonce=preview['nonce'],confirm=True))
        self.assertEqual(self.work.control.records(),[])
    def test_unknown_fit_is_rejected_as_request_not_storage_failure(self):
        request=self.request();request['fit_job_id']='9'*32
        with self.assertRaisesRegex(ValueError,'Known completed'):self.work.action('control-preview',request)
    def test_nameplate_caps_rpm_but_does_not_supply_calibration_or_enable(self):
        save(self.work.root/'fan-nameplate.json',dict(source='USER_DECLARED_NAMEPLATE_NOT_CALIBRATION',rated_voltage_V=12,rated_current_A=.7,rated_speed_rpm=3000))
        with self.assertRaisesRegex(ValueError,'rated speed'):self.work.action('control-preview',self.request())
        self.assertFalse(self.work.control.summary()['enabled'])
        self.assertEqual(self.work.control.summary()['nameplate']['rated_current_A'],.7)
    def test_nameplate_change_invalidates_prepared_operation(self):
        p=self.work.action('control-preview',self.request())
        save(self.work.root/'fan-nameplate.json',dict(source='USER_DECLARED_NAMEPLATE_NOT_CALIBRATION',rated_voltage_V=12,rated_current_A=.7,rated_speed_rpm=6000))
        with self.assertRaisesRegex(ValueError,'context changed'):self.work.action('control-confirm',dict(nonce=p['nonce'],confirm=True))
    def test_key_permission_manager_and_revision_required(self):
        self.state['status']['raw_words'][0]=0
        with self.assertRaisesRegex(ValueError,'KEY2'):self.work.action('control-preview',self.request())
        self.state['status']['raw_words'][0]=0x8000
        with patch('commissioning.control_jobs.manager_alive',return_value=False),self.assertRaisesRegex(ValueError,'MANAGER_OFFLINE'):
            self.work.action('control-preview',self.request())
        request=self.request();request['revision']='stale'
        with self.assertRaisesRegex(ValueError,'REVISION'):self.work.action('control-preview',request)
    def test_changed_context_and_package_cannot_be_confirmed(self):
        p=self.work.action('control-preview',self.request());self.service.connection_epoch=2
        with self.assertRaisesRegex(ValueError,'context changed'):self.work.action('control-confirm',dict(nonce=p['nonce'],confirm=True))
        p=self.work.action('control-preview',self.request());(self.package/'control.json').write_text('{}')
        with self.assertRaises(ValueError):self.work.action('control-confirm',dict(nonce=p['nonce'],confirm=True))
    def test_old_boot_or_expired_jobs_are_never_replayed(self):
        job=self.confirmed()
        with patch('commissioning.deploy.apply') as apply:
            for field,value in [('boot','OTHER'),('expires_at',0)]:
                altered=copy.deepcopy(job)
                if field=='boot':altered['context']['os_boot_id']=value
                else:altered[field]=value
                with self.assertRaisesRegex(ValueError,'Expired'):control_jobs.execute(self.work.root,self.base,altered)
        apply.assert_not_called()
    def test_worker_executes_only_pinned_current_fit_and_collector(self):
        job=self.confirmed();original=control_jobs.document
        def read(path):
            if str(path)=='/run/cabinet-live/state.json':return dict(observation=dict(boot='HW/SESSION/1',bench=dict(state='IDLE',controls_enabled=False)))
            return original(path)
        with patch('commissioning.control_jobs.document',side_effect=read),patch('commissioning.control_jobs.wait_feedback',return_value={'fixture':True}),patch('commissioning.deploy.apply',return_value={'status':'FIXTURE'}) as apply:
            result=control_jobs.execute(self.work.root,self.base,job)
        self.assertEqual(result['status'],'FIXTURE');apply.assert_called_once_with(self.package,job['manifest_sha256'])
    def test_fixed_speed_preview_requires_applied_package_and_measured_range(self):
        with self.assertRaisesRegex(ValueError,'standby'):self.work.action('control-preview',self.request('arm','speed',2000))
        self.base.write_bytes((self.package/'edge.standby.json').read_bytes())
        with self.assertRaisesRegex(ValueError,'envelope'):self.work.action('control-preview',self.request('arm','speed',5000))
        result=self.work.action('control-preview',self.request('arm','speed',2000))
        self.assertEqual(result['target_rpm'],2000)
    def test_completed_fits_survive_collector_restart(self):
        restored=Workbench(self.work.root,self.base)
        self.assertEqual(restored.jobs[self.fit_id]['state'],'COMPLETED')
        self.assertEqual(restored.control.summary()['fits'][0]['id'],self.fit_id)
    def test_fixture_is_refused_without_explicit_unit_test_patch(self):
        with patch('commissioning.deploy.SOURCE','REAL_USER_MEASUREMENTS'),self.assertRaisesRegex(ValueError,'Fixture'):
            self.work.action('control-preview',self.request())
    def test_disarm_does_not_require_key_or_fresh_sensor_data(self):
        self.base.write_bytes((self.package/'edge.armed.json').read_bytes())
        self.state.update(link='OFFLINE',status_age_ms=10000);self.state['status']['raw_words'][0]=0
        self.assertEqual(self.work.action('control-preview',self.request('disarm'))['operation'],'disarm')
    def test_exit_remains_available_after_new_measurements_and_during_trace(self):
        self.base.write_bytes((self.package/'edge.armed.json').read_bytes())
        self.work.jobs['recording']=dict(state='RUNNING')
        with (self.work.inputs/'calibration.csv').open('a') as out:out.write('\n')
        self.service.boot=None
        self.assertEqual(self.work.action('control-preview',self.request('disarm'))['operation'],'disarm')
    def test_arm_without_actual_readback_is_disarmed_and_reported_failed(self):
        self.base.write_bytes((self.package/'edge.standby.json').read_bytes())
        preview=self.work.action('control-preview',self.request('arm','speed',2000))
        result=self.work.action('control-confirm',dict(nonce=preview['nonce'],confirm=True))
        job=control_jobs.document(self.work.control.queue/(result['id']+'.json'));original=control_jobs.document
        def read(path):
            return dict(observation=dict(boot='HW/SESSION/1',bench=dict(state='IDLE',controls_enabled=False))) if str(path)=='/run/cabinet-live/state.json' else original(path)
        with patch('commissioning.control_jobs.document',side_effect=read),patch('commissioning.deploy.arm',return_value={}), \
                patch('commissioning.control_jobs.wait_feedback',side_effect=RuntimeError('CONTROL_READBACK_TIMEOUT')),patch('commissioning.deploy.disarm') as disarm:
            with self.assertRaisesRegex(RuntimeError,'READBACK_TIMEOUT'):control_jobs.execute(self.work.root,self.base,job)
        disarm.assert_called_once_with(self.package,job['manifest_sha256'])
    def test_manager_does_not_replay_interrupted_transactions(self):
        job=self.confirmed();path=self.work.control.queue/(job['id']+'.json');job['state']='RUNNING';save(path,job)
        stop=threading.Event();stop.set()
        with patch('commissioning.control_jobs.MANAGER_STATE',self.root/'run/state.json'),patch('commissioning.control_jobs.execute') as execute:
            control_jobs.run_manager(self.work.root,self.base,stop)
        execute.assert_not_called();self.assertEqual(control_jobs.document(path)['state'],'INTERRUPTED_REQUIRES_REVIEW')

if __name__=='__main__':unittest.main()
