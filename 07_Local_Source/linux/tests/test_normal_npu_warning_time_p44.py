"""The production two-second display policy must not change actual NPU scores."""
import copy
import unittest
from normal_npu.advisory import Advisory,panel_fields
from tests.test_normal_npu_advisory_p21 import sample

class ProductionTiming(unittest.TestCase):
    def setUp(self):self.a=Advisory()
    def feed(self,i,score=.5,**kw):
        d=sample(i,i*100,score,**kw)
        return self.a.observe(d,d['updated_at'])
    def normal(self):
        for i in range(11):value=self.feed(i)
        self.assertEqual(value['state'],'NORMAL')
    def test_warning_requires_two_seconds(self):
        for i in range(20):
            value=self.feed(i,1.2)
            self.assertEqual(value['state'],'PENDING')
            self.assertEqual(value['required_ms'],2000)
        self.assertEqual(self.feed(20,1.2)['state'],'WARN')
    def test_one_point_five_second_transient_is_not_yellow_or_false_green(self):
        self.normal()
        for i in range(11,27):
            value=self.feed(i,22.)
            self.assertEqual(value['state'],'PENDING')
            fields=panel_fields(dict(state='BASELINE_DEVIATION',score=22.,advisory=value))
            self.assertEqual(fields['panel_nn_advisory_state'],'PENDING')
        self.assertEqual(self.feed(27)['state'],'NORMAL')
    def test_warning_stays_latched_until_one_second_below_recovery_limit(self):
        for i in range(21):self.feed(i,1.2)
        for i in range(21,31):self.assertEqual(self.feed(i,.8)['state'],'RECOVERING')
        self.assertEqual(self.feed(31,.8)['state'],'NORMAL')
    def test_stale_and_invalid_still_clear_the_display(self):
        self.normal();d=sample(11,1100)
        self.assertEqual(self.a.observe(d,1001.7)['state'],'UNKNOWN')
        self.assertNotEqual(self.feed(12)['state'],'NORMAL')
    def test_repeated_frame_does_not_supply_two_seconds_of_evidence(self):
        d=sample(1,100,1.5)
        self.a.observe(d,1000.1)
        d.update(received_at=1002.2,updated_at=1002.2)
        self.assertEqual(self.a.observe(d,1002.2)['state'],'UNKNOWN')
        self.assertFalse(self.a.warning)
    def test_short_gap_preserves_confirmed_history_but_not_false_green(self):
        self.normal()
        self.assertEqual(self.feed(12,1.4)['state'],'PENDING')
        self.assertEqual(self.feed(14)['state'],'NORMAL')
    def test_long_gap_and_new_model_require_confirmation(self):
        self.normal();self.assertEqual(self.feed(25)['state'],'UNKNOWN')
        self.normal();self.assertEqual(self.feed(12,model_sha256='b'*64)['state'],'UNKNOWN')
    def test_raw_score_and_state_are_unchanged(self):
        d=sample(1,100,22.);before=copy.deepcopy(d)
        self.a.observe(d,1000.1);self.assertEqual(d,before)

if __name__=='__main__':unittest.main()
