"""SDP810-500Pa factory transfer function and five-second display mean.

Sensirion SDP8xx Digital v1.1 sections 6.3.6 and 6.5. The existing FPGA driver
accepts product family 0x03020A, CRC-valid samples and scale factor 60 before
asserting pressure validity. Its product/serial registers are not exported to
Linux; sample mode 2 and live validity bind this display to that driver path.
No running pressure is used as an invented zero or installation reference.
"""
import math
if __package__:
    from .rolling_mean import SampleMean5s
else:
    from rolling_mean import SampleMean5s

SOURCE='SDP810_FACTORY_60_COUNTS_PER_PA'
DATASHEET='https://sensirion.com/file/datasheet_sdp800-d/'


def factory_pressure(fields,sample):
    if (fields.get('frame_sample_mode')!='2' or fields.get('frame_fresh')!='1'
            or fields.get('frame_state')=='REJECTED_TEST' or sample.get('link')!='ONLINE'):
        return None
    status=sample.get('status',{});words=status.get('raw_words')
    if (status.get('input_validity',{}).get('pressure') is not True
            or type(words) is not list or len(words)!=32
            or any(type(words[i]) is not int or not 0<=words[i]<=0xffffffff for i in (0,22))
            or not words[0]&(1<<13)):
        return None
    raw=(words[22]>>16)&65535;raw=raw-65536 if raw&32768 else raw
    if status.get('pressure_raw_code')!=raw or abs(raw)>30000:return None
    return raw/60.0


class PressureDisplayMean(SampleMean5s):
    def reset(self):
        super().reset();self.published=None

    def apply(self,fields,sample,now):
        # Other sensor modes retain their existing raw/calibrated presentation.
        if fields.get('frame_sample_mode')!='2':self.reset();return
        value=factory_pressure(fields,sample)
        fields.update(daily_pressure_value='--',daily_pressure_unit='Pa',daily_pressure_valid='0',
            daily_pressure_kind='factory_calibrated',daily_pressure_source=SOURCE,
            daily_pressure_scale_counts_per_Pa='60',daily_pressure_site_zero_calibrated='0',
            daily_pressure_instant_Pa='--' if value is None else '%.9f' % value,
            daily_pressure_aggregation='ARITHMETIC_MEAN',daily_pressure_average_window_s='5',
            daily_pressure_average_state='UNAVAILABLE',daily_pressure_average_count='0')
        if value is None or not sample.get('boot'):self.reset();return
        status=sample['status'];identity=(sample['boot'],SOURCE)
        result=self.push(value,sample.get('received_at'),status.get('uptime_ms'),identity,now)
        if result is None:return
        fields.update(daily_pressure_average_state='READY' if result['ready'] else 'WARMING_UP',
            daily_pressure_average_count=str(result['count']),daily_pressure_average_span_s='%.3f' % result['span_s'])
        if result['ready']:
            fields['daily_pressure_value']='%.3f' % result['mean'];fields['daily_pressure_valid']='1'
        self.published=dict(state=fields['daily_pressure_average_state'],valid=result['ready'],
            source=SOURCE,sensor='SDP810-500Pa',unit='Pa',scale_counts_per_Pa=60,
            average_window_s=5,average_span_s=result['span_s'],sample_count=result['count'],
            mean_pressure_Pa=result['mean'] if result['ready'] else None,instant_pressure_Pa=value,
            boot=sample['boot'],received_at=result['received_at'],status_uptime_ms=status['uptime_ms'],
            factory_calibrated=True,site_zero_calibrated=False,site_gain_calibrated=False,
            control_authority=False)

    def summary(self,boot,now):
        p=self.published
        if (p is None or p['boot']!=boot or not math.isfinite(now) or not 0<=now-p['received_at']<=1):
            return dict(state='UNAVAILABLE',valid=False,mean_pressure_Pa=None,instant_pressure_Pa=None,
                        source=SOURCE,unit='Pa',control_authority=False)
        return dict(p)
