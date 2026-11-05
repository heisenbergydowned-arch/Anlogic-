"""Only a prior confirmed normal state can be held during a short observation."""
import unittest
from normal_npu.advisory import Advisory,panel_fields
from tests.test_normal_npu_advisory_p21 import sample

class GrayGrace(unittest.TestCase):
    def setUp(self):self.a=Advisory()
    def feed(self,i,score=.5):
        d=sample(i,i*100,score);d['advisory']=self.a.observe(d,d['updated_at'])
        return d,panel_fields(d)
    def normal(self):
        for i in range(11):self.feed(i)
    def test_prior_normal_is_preserved_with_explicit_pending_and_real_score(self):
        self.normal();d,p=self.feed(11,1.3)
        self.assertEqual(d['state'],'BASELINE_DEVIATION');self.assertEqual(d['score'],1.3)
        self.assertEqual(p['panel_nn_advisory_state'],'PENDING')
        self.assertEqual(p['panel_nn_advisory_normal_latched'],'1')
    def test_startup_deviation_has_no_green_history(self):
        d,p=self.feed(1,1.3);self.assertEqual(p['panel_nn_advisory_normal_latched'],'0')
    def test_invalid_input_clears_green_history(self):
        self.normal();self.a.invalidate('PROCESS_SENSOR_INVALID')
        d,p=self.feed(11,1.3);self.assertEqual(p['panel_nn_advisory_normal_latched'],'0')
    def test_skipped_deliveries_do_not_extend_two_second_pending_grace(self):
        self.normal()
        for i in range(11,31,2):
            d,p=self.feed(i,1.3);self.assertEqual(p['panel_nn_advisory_state'],'PENDING')
            self.assertEqual(p['panel_nn_advisory_normal_latched'],'1')
        d,p=self.feed(31,1.3)
        self.assertEqual(p['panel_nn_advisory_state'],'WARN')
        self.assertEqual(p['panel_nn_advisory_normal_latched'],'0')
    def test_warning_recovery_cannot_claim_green_history(self):
        for i in range(21):self.feed(i,1.3)
        d,p=self.feed(21,.5);self.assertEqual(p['panel_nn_advisory_state'],'RECOVERING')
        self.assertEqual(p['panel_nn_advisory_normal_latched'],'0')
    def test_missing_or_expired_grace_cannot_be_green(self):
        self.normal();d,p=self.feed(11,1.3)
        d['advisory'].pop('normal_latched');self.assertEqual(panel_fields(d)['panel_nn_advisory_normal_latched'],'0')
        d['advisory'].update(normal_latched=True,elapsed_ms=2000,required_ms=2000)
        self.assertEqual(panel_fields(d)['panel_nn_advisory_normal_latched'],'0')

if __name__=='__main__':unittest.main()
