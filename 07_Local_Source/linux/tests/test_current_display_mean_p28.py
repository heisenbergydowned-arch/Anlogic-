import copy,json,statistics,unittest
from pathlib import Path
from hmi_daily.current_units import CurrentDisplayMean


class DisplayCurrentMean(unittest.TestCase):
    def setUp(self):self.mean=CurrentDisplayMean()
    def sample(self,t,value,boot='board/session',conversion='zero/range',valid=True,stamp=None,now=None):
        sample=dict(boot=boot,received_at=t,status=dict(uptime_ms=round(t*1000) if stamp is None else stamp,input_validity={'adc':valid}))
        fields=dict(daily_current_kind='nominal',daily_current_valid='1' if valid else '0',
                    daily_current_unit='A',daily_current_value=str(value),daily_current_gain_calibrated='0',
                    daily_current_conversion_id=conversion)
        before=copy.deepcopy(sample);self.mean.apply(fields,sample,t if now is None else now)
        self.assertEqual(sample,before)
        return fields
    def ready(self):
        for i in range(11):value=self.sample(i*.1,.4)
        return value
    def test_average_is_arithmetic_with_signed_samples_not_rms_or_peak(self):
        self.sample(0,-.2);self.sample(.25,.4);result=self.sample(.5,1)
        self.assertEqual(result['daily_current_value'],'0.400')
        self.assertEqual(result['daily_current_gain_calibrated'],'0')
        self.assertEqual(result['daily_current_average_count'],'3')
    def test_duplicate_publication_never_counts_or_renews_old_samples(self):
        self.ready()
        repeated=self.sample(1.1,5,stamp=1000)
        self.assertEqual(repeated['daily_current_value'],'0.400')
        self.assertEqual(repeated['daily_current_average_count'],'11')
        expired=self.sample(2.1,5,stamp=1000)
        self.assertEqual(expired['daily_current_valid'],'0')
    def test_only_last_five_seconds_remain(self):
        for i in range(101):result=self.sample(i*.1,.4 if i<50 else .8)
        self.assertEqual(result['daily_current_value'],'0.800')
        self.assertEqual(result['daily_current_average_span_s'],'5.000')
        self.assertEqual(result['daily_current_average_count'],'51')
    def test_invalid_adc_immediately_clears_history_and_recovery_warms_up(self):
        self.ready();invalid=self.sample(1.1,.4,valid=False)
        self.assertEqual(invalid['daily_current_value'],'--')
        self.assertEqual(len(self.mean.rows),0)
        recovered=self.sample(1.2,.8)
        self.assertEqual(recovered['daily_current_valid'],'0')
        self.assertEqual(recovered['daily_current_average_state'],'WARMING_UP')
    def test_boot_profile_and_link_gap_each_clear_previous_values(self):
        for change in (dict(boot='new/session'),dict(conversion='new-zero/range'),dict(t=3)):
            self.setUp();self.ready();args=dict(t=1.1,value=.8);args.update(change)
            result=self.sample(**args)
            self.assertEqual(result['daily_current_average_count'],'1')
            self.assertEqual(result['daily_current_valid'],'0')
    def test_nonfinite_stale_future_and_reordered_data_do_not_display_average(self):
        for args in (dict(value=float('nan')),dict(now=2.2),dict(now=1),dict(stamp=1)):
            self.setUp();self.ready();kw=dict(t=1.1,value=.4);kw.update(args)
            result=self.sample(**kw)
            self.assertEqual(result['daily_current_valid'],'0')
    def test_formal_calibration_and_raw_units_keep_original_semantics(self):
        self.ready()
        for kind in ('calibrated','raw_sample','raw_distance'):
            fields=dict(daily_current_kind=kind,daily_current_value='123',daily_current_valid='1')
            before=dict(fields);self.mean.apply(fields,{},2)
            self.assertEqual(fields,before);self.assertEqual(len(self.mean.rows),0)
    def test_captured_full_speed_sequence_matches_recomputed_mean(self):
        path=Path(__file__).resolve().parents[2]/'current_full_speed_observation_001.json'
        if not path.exists():self.skipTest('captured board trace not in standalone source package')
        rows=json.loads(path.read_text())['rows'];values=[]
        for row in rows:
            value=(row['raw_current']-16345.668674698794)*5/32768/.185
            fields=self.sample(row['received_at'],value,stamp=row['uptime_ms'],now=row['read_at'])
            values.append((row['received_at'],value))
            wanted=[v for t,v in values if t>=row['received_at']-5]
            if fields['daily_current_valid']=='1':
                self.assertAlmostEqual(float(fields['daily_current_value']),statistics.mean(wanted),delta=.00051)
        self.assertEqual(fields['daily_current_average_state'],'READY')


if __name__=='__main__':unittest.main()
