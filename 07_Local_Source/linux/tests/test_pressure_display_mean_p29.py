import copy,unittest
from hmi_daily.pressure_units import factory_pressure,PressureDisplayMean,SOURCE


def observation(raw=60,t=1.,boot='board/session'):
    words=[0]*32;words[0]=1<<13;words[22]=(raw&65535)<<16
    sample=dict(link='ONLINE',boot=boot,received_at=t,status=dict(raw_words=words,pressure_raw_code=raw,
        uptime_ms=round(t*1000),input_validity={'pressure':True,'adc':False}))
    fields=dict(frame_sample_mode='2',frame_fresh='1',frame_state='RECEIVED_REAL',
                daily_pressure_value=str(raw),daily_pressure_unit='原始码',daily_pressure_valid='1')
    return fields,sample


class FactoryPressureDisplay(unittest.TestCase):
    def test_signed_factory_scale_and_full_range_use_pa(self):
        for raw,expected in ((60,1),(-60,-1),(30000,500),(-30000,-500),(0,0),(-5,-5/60)):
            fields,sample=observation(raw);before=copy.deepcopy(sample)
            self.assertEqual(factory_pressure(fields,sample),expected)
            self.assertEqual(sample,before)
    def test_wrong_source_stale_test_invalid_or_inconsistent_status_never_becomes_pa(self):
        for change in ('analog','stale','test','offline','invalid','flag','contradiction','range'):
            fields,sample=observation();status=sample['status']
            if change=='analog':fields['frame_sample_mode']='1'
            elif change=='stale':fields['frame_fresh']='0'
            elif change=='test':fields['frame_state']='REJECTED_TEST'
            elif change=='offline':sample['link']='OFFLINE'
            elif change=='invalid':status['input_validity']['pressure']=False
            elif change=='flag':status['raw_words'][0]=0
            elif change=='contradiction':status['pressure_raw_code']=100
            else:status['pressure_raw_code']=30001;status['raw_words'][22]=30001<<16
            with self.subTest(change=change):self.assertIsNone(factory_pressure(fields,sample))
    def test_mean_preserves_sign_and_raw_control_inputs(self):
        mean=PressureDisplayMean()
        for t,raw in ((1,-60),(1.25,0),(1.5,120)):
            fields,sample=observation(raw,t);before=copy.deepcopy(sample);mean.apply(fields,sample,t)
            self.assertEqual(sample,before)
        self.assertEqual(fields['daily_pressure_value'],'0.333')
        self.assertEqual(fields['daily_pressure_unit'],'Pa')
        self.assertEqual(fields['daily_pressure_site_zero_calibrated'],'0')
        self.assertEqual(fields['daily_pressure_average_count'],'3')
        public=mean.summary('board/session',1.5)
        self.assertTrue(public['factory_calibrated']);self.assertFalse(public['control_authority'])
        self.assertFalse(public['site_gain_calibrated'])
    def test_sensor_loss_clears_mean_and_recovery_does_not_reuse_it(self):
        mean=PressureDisplayMean()
        for t in (1,1.25,1.5):
            fields,sample=observation(600,t);mean.apply(fields,sample,t)
        fields,sample=observation(600,1.6);sample['status']['input_validity']['pressure']=False
        mean.apply(fields,sample,1.6)
        self.assertEqual(fields['daily_pressure_valid'],'0');self.assertEqual(len(mean.rows),0)
        fields,sample=observation(60,1.7);mean.apply(fields,sample,1.7)
        self.assertEqual(fields['daily_pressure_average_state'],'WARMING_UP')
        self.assertEqual(fields['daily_pressure_average_count'],'1')
    def test_api_summary_expires_and_old_collector_cannot_survive_reconnect(self):
        mean=PressureDisplayMean()
        for t in (1,1.25,1.5):
            fields,sample=observation(-60,t);mean.apply(fields,sample,t)
        self.assertTrue(mean.summary('board/session',1.6)['valid'])
        for boot,now in (('new/session',1.6),('board/session',2.51),('board/session',1.4)):
            value=mean.summary(boot,now);self.assertFalse(value['valid']);self.assertIsNone(value['mean_pressure_Pa'])
        copied=mean.summary('board/session',1.6);copied['mean_pressure_Pa']=999
        self.assertEqual(mean.summary('board/session',1.6)['mean_pressure_Pa'],-1)
    def test_duplicate_frames_do_not_weight_mean_or_extend_freshness(self):
        mean=PressureDisplayMean()
        for t in (1,1.25,1.5):
            fields,sample=observation(-60,t);mean.apply(fields,sample,t)
        fields,sample=observation(30000,1.6);sample['status']['uptime_ms']=1500
        mean.apply(fields,sample,1.6)
        self.assertEqual(fields['daily_pressure_value'],'-1.000')
        self.assertEqual(fields['daily_pressure_average_count'],'3')
        self.assertFalse(mean.summary('board/session',2.51)['valid'])
    def test_analog_mode_keeps_raw_units_and_clears_sdp_history(self):
        mean=PressureDisplayMean();fields,sample=observation()
        fields['frame_sample_mode']='1';before=dict(fields);mean.apply(fields,sample,1)
        self.assertEqual(fields,before);self.assertFalse(mean.summary('board/session',1)['valid'])


if __name__=='__main__':unittest.main()
