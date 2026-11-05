"""Legacy 500 ms policy regressions. Production default is tested in P44."""
import copy
import unittest
from normal_npu.advisory import Advisory,panel_fields
from tests import test_normal_npu_freshness as fixtures
from tests import test_npu_null_collector_p19a as live_fixtures


def sample(fid,ms,score=.5,**changes):
    value=dict(valid=True,status='RUNNING',received_at=1000.+ms/1000.,updated_at=1000.+ms/1000.,
        frame_id=fid,frame_end_ms=ms&0xffffffff,score=score,
        state='BASELINE_MATCH' if score<=1 else 'BASELINE_DEVIATION',
        model_sha256='a'*64,os_boot_id='os-boot',collector_boot='board/session',input_contract={'fixture':1})
    value.update(changes);return value


class AdvisoryTests(unittest.TestCase):
    def setUp(self):self.a=Advisory(warning_ms=500)
    def feed(self,fid,ms,score=.5,**changes):
        d=sample(fid,ms,score,**changes);return self.a.observe(d,d['updated_at'])
    def warn(self):
        for i in range(6):out=self.feed(i,i*100,1.2)
        self.assertEqual(out['state'],'WARN');return out

    def test_startup_requires_full_second_of_fresh_frames(self):
        for i in range(10):self.assertEqual(self.feed(i,i*100)['state'],'UNKNOWN')
        self.assertEqual(self.feed(10,1000)['state'],'NORMAL')

    def test_point95_is_valid_initial_normal_but_not_latched_recovery(self):
        for i in range(11):out=self.feed(i,i*100,.95)
        self.assertEqual(out['state'],'NORMAL')
        for i in range(11,17):out=self.feed(i,i*100,1.2)
        self.assertEqual(out['state'],'WARN')
        for i in range(17,35):out=self.feed(i,i*100,.95)
        self.assertEqual(out['state'],'RECOVERING');self.assertTrue(out['warning_latched'])

    def test_alarm_requires_500ms_and_at_least_three_frames(self):
        self.assertEqual(self.feed(1,0,1.2)['state'],'PENDING')
        self.assertEqual(self.feed(2,500,1.2)['state'],'PENDING')
        self.assertEqual(self.feed(3,501,1.2)['state'],'WARN')

    def test_below_half_second_does_not_warn(self):
        for i,ms in enumerate((0,100,200,300,499)):
            self.assertEqual(self.feed(i,ms,1.01)['state'],'PENDING')
        self.assertEqual(self.feed(5,500,1.01)['state'],'WARN')

    def test_raw_threshold_one_is_not_a_deviation(self):
        for i in range(11):out=self.feed(i,i*100,1.)
        self.assertEqual(out['state'],'NORMAL')

    def test_duplicate_does_not_advance_elapsed_or_samples(self):
        d=sample(1,0,1.5);before=self.a.observe(d,1000.)
        for now in (1000.1,1000.2,1000.4):self.assertEqual(self.a.observe(d,now),before)

    def test_duplicate_cannot_refresh_original_measurement_timestamp(self):
        self.feed(1,0,1.2)
        out=self.a.observe(sample(1,0,1.2,received_at=1000.6,updated_at=1000.6),1000.6)
        self.assertEqual(out['state'],'UNKNOWN');self.assertEqual(out['reason'],'DUPLICATE_FRAME_STALE')

    def test_duplicate_changed_source_time_is_rejected(self):
        self.feed(1,0)
        self.assertEqual(self.feed(1,100)['reason'],'DUPLICATE_FRAME_CHANGED')

    def test_warning_clears_only_after_full_second_below_recovery_threshold(self):
        self.warn()
        for i in range(6,16):
            out=self.feed(i,i*100,.9);self.assertEqual(out['state'],'RECOVERING')
        self.assertEqual(self.feed(16,1600,.9)['state'],'NORMAL')

    def test_recovery_middle_band_restarts_recovery_confirmation(self):
        self.warn()
        for i in range(6,12):self.feed(i,i*100,.8)
        out=self.feed(12,1200,.95);self.assertEqual(out['elapsed_ms'],0)
        self.assertEqual(self.feed(13,1300,.8)['state'],'RECOVERING')
        for i in range(14,23):self.feed(i,i*100,.8)
        self.assertEqual(self.feed(23,2300,.8)['state'],'NORMAL')

    def test_gap_resets_pending_and_cannot_supply_missing_evidence(self):
        self.feed(1,0,1.3);self.feed(2,250,1.3)
        out=self.feed(4,500,1.3)
        self.assertEqual(out['state'],'UNKNOWN');self.assertEqual(out['reason'],'SOURCE_GAP')
        self.assertEqual(self.feed(5,750,1.3)['state'],'PENDING')
        self.assertEqual(self.feed(6,1000,1.3)['state'],'WARN')

    def test_warn_gap_retains_latch_and_one_match_cannot_clear_it(self):
        self.warn();out=self.feed(8,800,.5)
        self.assertEqual(out['state'],'UNKNOWN');self.assertTrue(out['warning_latched'])
        self.assertEqual(self.feed(9,900,.5)['state'],'RECOVERING')
        for i in range(10,18):self.feed(i,i*100,.5)
        self.assertEqual(self.feed(18,1800,.5)['state'],'NORMAL')

    def test_stale_input_does_not_clear_warning(self):
        self.warn();out=self.a.observe(sample(6,600,.5),1001.2)
        self.assertEqual(out['state'],'UNKNOWN');self.assertTrue(out['warning_latched'])
        self.assertNotEqual(self.feed(7,700,.5)['state'],'NORMAL')

    def test_explicit_invalid_input_cannot_bridge_confirmation(self):
        self.feed(0,0,1.5);self.feed(1,200,1.5);self.a.invalidate('PROCESS_SENSOR_INVALID')
        self.assertEqual(self.feed(2,400,1.5)['elapsed_ms'],0)
        self.assertEqual(self.feed(3,600,1.5)['state'],'PENDING')

    def test_scope_changes_reset_normal_and_confirmation(self):
        for field,value in (('model_sha256','b'*64),('os_boot_id','new-os'),('collector_boot','board/new'),('input_contract',{'fixture':2})):
            self.a=Advisory(warning_ms=500)
            for i in range(11):self.feed(i,i*100)
            out=self.feed(11,1100,**{field:value})
            self.assertEqual(out['state'],'UNKNOWN');self.assertEqual(out['reason'],'CONTEXT_CHANGED')

    def test_frame_and_pl_uptime_wrap_are_adjacent(self):
        start=0xffffffff-200
        for i in range(6):
            d=sample((0xffffffff-2+i)&0xffffffff,start+i*100,1.2)
            out=self.a.observe(d,d['updated_at'])
        self.assertEqual(out['state'],'WARN')

    def test_source_time_jump_and_reordering_are_unknown(self):
        self.feed(10,1000)
        self.assertEqual(self.feed(11,1600)['reason'],'SOURCE_GAP')
        self.assertEqual(self.feed(9,1700)['reason'],'SOURCE_GAP')

    def test_future_and_nonfinite_input_are_unknown(self):
        for changed in ({'received_at':1001.},{'score':float('nan')},{'valid':False},{'frame_id':True}):
            d=sample(1,0,**changed);self.assertEqual(self.a.observe(d,1000.)['state'],'UNKNOWN')

    def test_observe_does_not_mutate_raw_score_state_or_input(self):
        d=sample(1,0,1.3);before=copy.deepcopy(d);self.a.observe(d,1000.)
        self.assertEqual(d,before)

    def test_old_or_malformed_producer_never_becomes_green(self):
        for a in (None,{},dict(schema='wrong',state='NORMAL'),dict(schema='cabinet-normal-advisory-v1',state='NORMAL')):
            fields=panel_fields(dict(state='BASELINE_MATCH',score=.5,advisory=a))
            self.assertEqual(fields['panel_nn_advisory_valid'],'0');self.assertEqual(fields['panel_nn_advisory_state'],'UNKNOWN')

    def test_panel_rejects_normal_when_raw_is_deviating(self):
        for i in range(11):a=self.feed(i,i*100)
        fields=panel_fields(dict(state='BASELINE_DEVIATION',score=1.1,advisory=a))
        self.assertEqual(fields['panel_nn_advisory_valid'],'0')


class PresentationTests(unittest.TestCase):
    setUp=fixtures.NormalNpuFreshnessTests.setUp
    write_result=fixtures.NormalNpuFreshnessTests.write_result
    display=fixtures.NormalNpuFreshnessTests.display

    def test_verified_advisory_is_displayed_without_changing_raw_result(self):
        a=Advisory(warning_ms=500)
        for i in range(11):temporal=a.observe(sample(i,i*100),1000.+i*.1)
        self.result['advisory']=temporal;self.write_result();before=copy.deepcopy(self.result)
        fields=self.display(lambda:1000.02)
        self.assertEqual(fields['panel_nn_valid'],'1');self.assertEqual(fields['panel_nn_advisory_valid'],'1')
        self.assertEqual(fields['panel_nn_advisory_state'],'NORMAL');self.assertEqual(self.result,before)

    def test_missing_advisory_keeps_raw_inference_but_temporal_unknown(self):
        fields=self.display(lambda:1000.02)
        self.assertEqual(fields['panel_nn_valid'],'1');self.assertEqual(fields['panel_nn_advisory_valid'],'0')

    def test_expired_raw_result_cannot_keep_normal_advisory(self):
        a=Advisory(warning_ms=500)
        for i in range(11):self.result['advisory']=a.observe(sample(i,i*100),1000.+i*.1)
        self.write_result();fields=self.display(lambda:1001.01)
        self.assertEqual(fields['panel_nn_valid'],'0');self.assertEqual(fields['panel_nn_advisory_state'],'UNKNOWN')


class LiveIntegrationTests(unittest.TestCase):
    setUp=live_fixtures.NullCollectorTests.setUp
    offline=live_fixtures.NullCollectorTests.offline
    run_live=live_fixtures.NullCollectorTests.run_live

    def test_live_publishes_temporal_state_and_null_cannot_keep_it_normal(self):
        published,infer=self.run_live()
        self.assertEqual(infer.call_count,2)
        for result in published:
            if result.get('status')=='RUNNING':
                self.assertEqual(result['advisory']['schema'],'cabinet-normal-advisory-v1')
                self.assertNotEqual(result['advisory']['state'],'NORMAL')
                self.assertIn(result['state'],('BASELINE_MATCH','BASELINE_DEVIATION'))
            if result.get('status')=='WAITING_INPUT':
                self.assertEqual(result['advisory']['state'],'UNKNOWN')
                self.assertEqual(result['advisory']['reason'],'COLLECTOR_STALE')
        self.assertEqual(published[-1]['advisory']['state'],'UNKNOWN')


if __name__=='__main__':unittest.main()
