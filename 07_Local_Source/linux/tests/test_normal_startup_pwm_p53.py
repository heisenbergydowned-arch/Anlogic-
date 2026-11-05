"""Saved hardware selftest and live TPW inference do not require zero fan PWM."""
import copy
import json
from pathlib import Path
import signal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from normal_npu import live, probe
from normal_npu.core import GROUPS, live_input, PWM_REFERENCE
from normal_npu.advisory import Advisory
from normal_npu.presentation import fields
from tests.test_normal_npu_freshness import NormalNpuFreshnessTests as Fixture


class RuntimeReferenceTests(unittest.TestCase):
    setUp = Fixture.setUp
    write_result = Fixture.write_result

    def thermal(self):
        self.sample['status'].update(applied_pwm_counts=1200,hard_inhibit=False)
        self.sample['normal_reference_guard'].update(state='BLOCKED',reason='OUTPUT_OUTSIDE_REFERENCE',safe_since_uptime_ms=None)
        self.sample['control']={'temperature_pwm':dict(state='RUNNING',hardware_supported=True,
            hardware_armed=True,feedback_valid=True,target_source='FPGA_TPW1_READBACK',
            settings=dict(enabled=True,revision=14),applied_revision=14,observed_at=1000.,
            deadline_ms=1001000,actual_pwm_percent=30.)}

    def test_inference_runs_without_relaxing_learning_reference(self):
        self.thermal();before=copy.deepcopy(self.sample)
        with self.assertRaisesRegex(ValueError,'OUTPUT_OUTSIDE_REFERENCE'):
            live_input(dict(observation=self.sample),1000.02,self.contract)
        values,identity=live_input(dict(observation=self.sample),1000.02,self.contract,allow_temperature_pwm=True)
        self.assertEqual(len(values),39);self.assertFalse(identity['baseline_eligible'])
        self.assertEqual(identity['applied_pwm_percent'],30.)
        self.assertEqual(self.sample,before)

    def test_runtime_still_rejects_missing_or_untrusted_input(self):
        self.thermal();original=copy.deepcopy(self.sample)
        changes=[
            lambda o:o['control']['temperature_pwm'].update(feedback_valid=False),
            lambda o:o['control']['temperature_pwm'].update(observed_at=998.),
            lambda o:o['control']['temperature_pwm'].update(actual_pwm_percent=0.),
            lambda o:o['control'].update(temperature_pwm=None),
            lambda o:o['status']['input_validity'].update(pressure=False),
            lambda o:o['frame']['header'].__setitem__(15,1),
            lambda o:o.update(boot='another-device'),
            lambda o:o['bench'].update(controls_enabled=True),
            lambda o:o['status'].update(active=['OC_HARD']),
            lambda o:o['normal_reference_guard'].update(status_uptime_ms=0),
        ]
        for change in changes:
            o=copy.deepcopy(original);change(o)
            with self.subTest(change=changes.index(change)),self.assertRaises(ValueError):
                live_input(dict(observation=o),1000.02,self.contract,allow_temperature_pwm=True)

    def test_trained_pwm_contract_allows_thermal_scope_but_not_bad_feedback(self):
        self.thermal()
        trained=dict(self.contract,pwm_operating_reference=copy.deepcopy(PWM_REFERENCE))
        _,identity=live_input(dict(observation=self.sample),1000.02,trained,allow_temperature_pwm=True)
        self.assertTrue(identity['baseline_eligible'])
        self.assertEqual(identity['operating_reference'],'SAVED_BASELINE_CONTEXT')
        self.sample['control']['temperature_pwm']['feedback_valid']=False
        with self.assertRaisesRegex(ValueError,'TEMPERATURE_PWM_CONTEXT_INVALID'):
            live_input(dict(observation=self.sample),1000.02,trained,allow_temperature_pwm=True)

    def test_partial_unproven_pwm_scope_is_rejected(self):
        self.thermal()
        trained=dict(self.contract,pwm_operating_reference={'duty_nodes_percent':[0,100]})
        with self.assertRaisesRegex(ValueError,'PWM_REFERENCE_CONTRACT_INVALID'):
            live_input(dict(observation=self.sample),1000.02,trained,allow_temperature_pwm=True)

    def test_display_shows_execution_but_cannot_claim_matched_reference(self):
        self.thermal()
        self.result.update(baseline_eligible=False,operating_reference='TEMPERATURE_PWM_OUTSIDE_BASELINE')
        self.result['advisory']=Advisory().observe(self.result,1000.02)
        self.write_result()
        result=fields(self.sample,1000.02,self.path,'os-boot')
        self.assertEqual(result['panel_nn_valid'],'1')
        self.assertEqual(result['panel_nn_reference_eligible'],'0')
        self.assertEqual(result['panel_nn_assessment'],'OUTSIDE_OPERATING_REFERENCE')
        self.assertEqual(result['panel_nn_advisory_state'],'UNKNOWN')
        self.result.pop('baseline_eligible');self.write_result()
        self.assertEqual(fields(self.sample,1000.02,self.path,'os-boot')['panel_nn_valid'],'0')

    def test_outside_operating_context_clears_stale_warning(self):
        a=Advisory();a.warning=True;a.normal=True
        out=a.observe(dict(baseline_eligible=False),1000.)
        self.assertEqual(out['state'],'UNKNOWN')
        self.assertFalse(out['warning_latched']);self.assertFalse(out['normal_latched'])

    def test_saved_probe_is_bound_to_board_without_waiting_for_sensors(self):
        bundle=SimpleNamespace(expected={'device_id':'machine:abc'})
        with patch.object(Path,'read_text',return_value='abc\n'),patch.object(probe,'live_input') as read:
            probe.require_probe_context(bundle,saved_startup=True);read.assert_not_called()
        with patch.object(Path,'read_text',return_value='other'),self.assertRaisesRegex(ValueError,'another board'):
            probe.require_probe_context(bundle,saved_startup=True)

    def test_live_waits_for_late_sensor_then_recovers_in_same_process(self):
        norm=dict(mean=[0.]*39,scale=[1.]*39,input_scale=1.,input_zero_point=128,
                  output_scale=1.,output_zero_point=128)
        bundle=SimpleNamespace(expected=self.contract,norm=norm,
            thresholds=dict(group_rmse={k:1. for k in GROUPS},abs_z_limit=[5.]*39),
            manifest=dict(model_id='fixture',source='REAL_USER_DECLARED_NORMAL_DIAGNOSTIC',training_rows=700),
            provenance=dict(sessions={k:dict(session_ids=[k],rows=700) for k in ('train','calibration','test')}))
        handlers={};published=[];reads=[0]
        def read(path):
            reads[0]+=1
            if reads[0]==1:raise FileNotFoundError('collector not ready')
            return dict(observation=copy.deepcopy(self.sample))
        def publish(path,value):
            published.append(value)
            if value.get('status')=='RUNNING':handlers[signal.SIGTERM]()
        native=SimpleNamespace(ready={},infer=lambda q:dict(output=bytes([128]*39),execute_ms=.4),close=lambda:True)
        argv=['normal_npu.live','--bundle',str(self.root),'--manifest-sha256','a'*64,
              '--library',str(self.root/'fixture.so'),'--library-sha256','b'*64,'--output',str(self.root/'state.json')]
        with patch('sys.argv',argv),patch.object(live,'check_start_selection'),patch.object(live,'Bundle',return_value=bundle), \
                patch.object(live,'Supervisor',return_value=native) as owner,patch.object(live,'read_state',side_effect=read), \
                patch.object(live,'publish',side_effect=publish),patch.object(live.time,'monotonic',return_value=1000.02), \
                patch.object(live.time,'sleep'),patch.object(live.signal,'signal',side_effect=lambda kind,fn:handlers.update({kind:fn})), \
                patch.object(Path,'read_text',return_value='os-boot'):
            live.main()
        owner.assert_called_once()
        states=[d.get('status') for d in published]
        self.assertIn('WAITING_INPUT',states);self.assertIn('RUNNING',states)
        self.assertNotIn('NATIVE_FAULT',states)


if __name__=='__main__':unittest.main()
