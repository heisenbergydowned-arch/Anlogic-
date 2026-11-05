"""An unlatched health inhibit must not disappear behind plan completion."""
import json
from pathlib import Path
import unittest
from commissioning.bench import observe_output
from tests import test_bench_guard_p18 as fixtures
prepared=fixtures.prepared
status=fixtures.status


def tracking():
    return dict(samples=0,matched_samples=0,mismatch_samples=0,unexpected_zero_samples=0,
                observed_conditions=[],first_mismatch=None,last_mismatch=None)


class OutputTracking(unittest.TestCase):
    def test_pre_arm_sample_is_not_reported_as_output_failure(self):
        result=tracking();observe_output(result,None,status(),prepared()['document']['profile'])
        self.assertEqual(result['samples'],0)

    def test_compares_previous_command_at_a_step_boundary(self):
        result=tracking();s=status();s['applied_pwm_counts']=800
        observe_output(result,800,s,prepared()['document']['profile'])
        self.assertEqual(result['matched_samples'],1)
        self.assertEqual(result['mismatch_samples'],0)

    def test_raw_limit_zero_is_retained_even_without_a_latched_trip(self):
        result=tracking();s=status();s['raw_words'][22]=3600
        observe_output(result,800,s,prepared()['document']['profile'])
        s['raw_words'][22]=3000;s['applied_pwm_counts']=800
        observe_output(result,800,s,prepared()['document']['profile'])
        self.assertEqual(result['mismatch_samples'],1)
        self.assertEqual(result['unexpected_zero_samples'],1)
        self.assertEqual(result['observed_conditions'],['CURRENT_RAW_LIMIT'])
        self.assertEqual(result['first_mismatch']['current_raw_code'],3600)
        self.assertEqual(result['matched_samples'],1)

    def test_measured_full_speed_trace_exposes_ten_transient_inhibits(self):
        # Captured evidence is optional in standalone exported source tests.
        path=Path(__file__).resolve().parents[2]/'pwm_trial_003_50_100.json'
        if not path.exists():self.skipTest('board trace not in standalone source package')
        trace=json.loads(path.read_text());result=tracking();expected=None
        for row in trace['terminal']['records']:
            sample=status();sample.update(uptime_ms=row['uptime_ms'],applied_pwm_counts=row['applied_pwm_counts'],temp_raw_1_16_C=round(row['temperature_C']*16))
            sample['raw_words'][22]=row['current_raw_code']&65535;sample['raw_words'][24]=row['fg_period_clocks']
            observe_output(result,expected,sample,trace['profile']['profile']);expected=row['requested_pwm_counts']
        self.assertEqual(result['mismatch_samples'],10)
        self.assertEqual(result['unexpected_zero_samples'],10)
        self.assertEqual(result['observed_conditions'],['CURRENT_RAW_LIMIT'])

    def test_plan_finished_and_output_zero_proof_do_not_clear_mismatch(self):
        f=fixtures.FeedbackGuardTests();f.setUp();f.start()
        f.status['raw_words'][22]=3600;f.active_update(.1)
        f.bench.active['heartbeat']=f.now+2
        f.bench.poll(f.controller,f.status,f.now+2)
        value=f.bench.snapshot()
        self.assertEqual(value['state'],'COMPLETED')
        self.assertTrue(value['output_stop_confirmed'])
        self.assertEqual(value['output_tracking']['mismatch_samples'],1)
        self.assertEqual(value['output_tracking']['observed_conditions'],['CURRENT_RAW_LIMIT'])


if __name__=='__main__':unittest.main()
