"""Synthetic, temporary fixtures for the real-data toolchain. No hardware writes."""
import copy,csv,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from commissioning.fit import initialize,build,sha,save
from commissioning.deploy import check
from commissioning.runtime import validate_binding
from commissioning.measure import evaluate_trace
from cabinet.control_display import ControlDisplay

SOURCE='SYNTHETIC_FIXTURE'
ROOT=Path(__file__).resolve().parents[1]

def dataset(root):
    initialize(root,'TEST-BOARD')
    s=json.loads((root/'settings.json').read_text());s.update(source=SOURCE,installation_id='TEST_INSTALL',fan_id='TEST_FAN',timing_reviewed=True)
    s['wiring']={k:True for k in s['wiring']}
    s['actuator'].update(rpm_min=1000,rpm_max=4000,startup_rpm=1500,duty_min_percent=25,duty_max_percent=100,
        startup_percent=50,fallback_percent=50,boost_percent=100,limit_percent=25,overspeed_hard_rpm=4500)
    s['pi'].update(kp_pwm_percent_per_rpm=.002,ki_pwm_percent_per_rpm_per_update=.0001,target_slew_rpm_per_s=1000,tracking_error_rpm=100)
    s['temperature'].update(setpoint_C=30,allowed_setpoint_min_C=25,allowed_setpoint_max_C=35,kp_rpm_per_C=100,
        ki_rpm_per_C_s=10,slew_rpm_per_s=500,warning_C=50,hard_C=60,recover_C=40)
    s['current'].update(warning_A=3,hard_A=4,recover_A=2)
    s['vibration'].update(warning_code=10000,hard_code=20000,fixed_4096_counts_per_g_verified=True)
    s['fit_tolerance'].update(current_A=.01,pressure_Pa=.1,temperature_C=.1)
    save(root/'settings.json',s)
    with (root/'calibration.csv').open('a',newline='') as f:
        w=csv.writer(f)
        for ch,unit,gain,zero in [('current','A',.001,3000),('pressure','Pa',1/60,0)]:
            for split,refs in [('fit',[0,1,2]),('validation',[.5,1.5])]:
                for i,ref in enumerate(refs):w.writerow([ch,split,zero+ref/gain,ref,unit,ch+'-'+split+'-'+str(i),SOURCE])
        for i,rpm in enumerate([1000,2000,3000]):w.writerow(['fg','validation',6000000000/(rpm*2),rpm,'rpm','fg-'+str(i),SOURCE])
        for i,t in enumerate([20,30]):w.writerow(['temperature','validation',t*16,t,'C','temp-'+str(i),SOURCE])
    with (root/'actuator.csv').open('a',newline='') as f:
        w=csv.writer(f)
        for duty in [25,50,75,100]:w.writerow([duty,duty*40,.01*duty,25,'act-'+str(duty),SOURCE])
    base=json.loads((ROOT/'config.example.json').read_text());base['device_id']='TEST-BOARD'
    save(root/'base.json',base)
    return s

class FittingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'data';self.settings=dataset(self.root)
    def tearDown(self):self.tmp.cleanup()
    def fit(self):return build(self.root,self.root/'base.json',Path(self.tmp.name)/'out',allow_fixture=True)

    def test_empty_inputs_and_fixture_cannot_be_promoted_to_real(self):
        with self.assertRaises(ValueError):build(self.root,self.root/'base.json',Path(self.tmp.name)/'bad')
        self.settings['installation_id']=None;save(self.root/'settings.json',self.settings)
        with self.assertRaises(ValueError):self.fit()

    def test_fit_compiles_units_q_formats_and_consistent_contracts(self):
        report=self.fit();out=Path(report['output'])
        c=json.loads((out/'control.json').read_text());f=json.loads((out/'feature.json').read_text())
        self.assertEqual(c['current_zero'],3000);self.assertEqual(c['current_hard'],4000)
        self.assertEqual(c['duty_min'],1000);self.assertEqual(c['temp_hard'],960)
        self.assertEqual(c['fg_pulses_per_revolution'],2);self.assertEqual(c['target_slew'],10)
        self.assertEqual(f['pressure_gain_q30'],17896)
        self.assertEqual(f['current_zero_q16'],3000*65536)
        armed=json.loads((out/'edge.armed.json').read_text());standby=json.loads((out/'edge.standby.json').read_text())
        self.assertEqual(armed['temperature_loop']['startup_rpm'],1500)
        self.assertEqual(armed['temperature_loop']['pwm_min_counts'],1000)
        self.assertFalse(standby['control']['enabled']);self.assertFalse(standby['temperature_loop']['enabled'])
        for n in ['capture-contract.json','feature.json']:
            self.assertEqual(json.loads((out/n).read_text())['calibration_id'],armed['contract']['calibration_id'])
        self.assertFalse(json.loads((out/'fit-report.json').read_text())['physical_closed_loop_accepted'])
        with self.assertRaisesRegex(ValueError,'Fixture'):check(out,report['manifest_sha256'])

    def test_manifest_tamper_is_rejected_before_any_hardware_open(self):
        report=self.fit();out=Path(report['output']);(out/'control.json').write_text('{}')
        with patch('commissioning.deploy.SOURCE',SOURCE),self.assertRaisesRegex(ValueError,'Changed'):
            check(out,report['manifest_sha256'])

    def test_separate_validation_and_sensor_error_are_enforced(self):
        p=self.root/'calibration.csv';p.write_text(p.read_text().replace('current-validation-0','current-fit-0'))
        with self.assertRaisesRegex(ValueError,'overlap'):self.fit()

    def test_different_decimal_spellings_are_not_independent_reference_levels(self):
        p=self.root/'calibration.csv';p.write_text(p.read_text().replace('current,fit,5000.0,2,A','current,fit,4000.0,1.0,A'))
        with self.assertRaisesRegex(ValueError,'3 reference levels'):self.fit()

    def test_sweep_must_cover_each_configured_duty(self):
        self.settings['actuator']['fallback_percent']=35;save(self.root/'settings.json',self.settings)
        with self.assertRaisesRegex(ValueError,'operating point'):self.fit()

    def test_reversed_or_unmeasured_protection_limits_are_rejected(self):
        self.settings['current']['hard_A']=2;save(self.root/'settings.json',self.settings)
        with self.assertRaises(ValueError):self.fit()

    def test_runtime_cannot_control_with_changed_or_fixture_readback(self):
        report=self.fit();c=json.loads((Path(report['output'])/'edge.armed.json').read_text());binding=c['commissioning']
        with self.assertRaises(ValueError):validate_binding(c,binding['control_words'],binding['feature_words'])
        with patch('commissioning.runtime.SOURCE',SOURCE):
            validate_binding(c,binding['control_words'],binding['feature_words'])
            wrong=list(binding['control_words']);wrong[6]+=1
            with self.assertRaises(ValueError):validate_binding(c,wrong,binding['feature_words'])

class ControlDisplayTests(unittest.TestCase):
    def sample(self,t,error=.01):
        return dict(boot='TEST/1',link='ONLINE',received_at=t,frame={'state':'RECEIVED_REAL'},
            control=dict(enabled=True,temperature_enabled=True,setpoint_C=30),status=dict(configured=True,test_mode=False,
                raw_words=[0x300]+[0]*31,mode='RUN',fan_action='PI',active=[],latched=[],requested_rpm=2000,ramped_rpm=2000,
                measured_rpm=2000*(1+error),configuration_id=1,uptime_ms=int(t*1000),input_validity={'rpm':True}))
    def test_one_matching_point_is_not_settled_acceptance(self):
        r=ControlDisplay().fields(self.sample(1),1)
        self.assertEqual(r['panel_control_error_pct'],'1.00');self.assertEqual(r['panel_control_settled'],'0')
    def test_continuous_same_unit_target_comparison_and_reset_on_loss(self):
        display=ControlDisplay()
        for i in range(102):r=display.fields(self.sample(i/10),i/10)
        self.assertEqual(r['panel_control_settled'],'1');self.assertEqual(r['panel_control_10s_error_pct'],'1.00')
        s=self.sample(10.2);s['status']['input_validity']['rpm']=False
        r=display.fields(s,10.2);self.assertEqual(r['panel_control_error_pct'],'--');self.assertEqual(r['panel_control_settled'],'0')
    def test_disabled_and_stale_do_not_invent_targets(self):
        s=self.sample(1);s['control']['enabled']=False
        r=ControlDisplay().fields(s,1);self.assertEqual(r['panel_control_target_rpm'],'--');self.assertEqual(r['panel_control_temp_target'],'--')
        self.assertEqual(ControlDisplay().fields(self.sample(1),3)['panel_control_target_valid'],'0')
    def test_real_target_ramp_is_not_misreported_as_steady_success(self):
        d=ControlDisplay()
        for i in range(102):
            s=self.sample(i/10);s['status'].update(ramped_rpm=1000+i*5,measured_rpm=1000+i*5)
            r=d.fields(s,i/10)
        self.assertEqual(r['panel_control_settled'],'0')
    def test_above_two_percent_does_not_pass(self):
        d=ControlDisplay()
        for i in range(102):r=d.fields(self.sample(i/10,.025),i/10)
        self.assertEqual(r['panel_control_state'],'TRACKING_ERROR')

class TraceTests(unittest.TestCase):
    def test_gap_stale_and_wrong_units_cannot_certify_tracking(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'trace.csv'
            def write(error=.01,gap=False):
                with p.open('w',newline='') as f:
                    w=csv.writer(f);w.writerow(['time_s','target_rpm','rpm','pwm_counts','temperature_C','setpoint_C','mode','valid','session_id','source'])
                    for i in range(121):w.writerow([i/10+(1 if gap and i>50 else 0),2000,2000*(1+error),2000,30,30,'RUN',1,'TEST',SOURCE])
            write();r=evaluate_trace(p,source=SOURCE);self.assertEqual(r['status'],'PASS_RPM_TRACKING_MEASUREMENT')
            write(.025);self.assertTrue(evaluate_trace(p,source=SOURCE)['status'].startswith('FAIL'))
            write(gap=True)
            with self.assertRaises(ValueError):evaluate_trace(p,source=SOURCE)

if __name__=='__main__':unittest.main()
