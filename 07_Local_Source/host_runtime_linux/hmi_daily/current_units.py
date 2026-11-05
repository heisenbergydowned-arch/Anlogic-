"""Display-only ACS712 conversion; never qualifies protection or NPU inputs."""
import json
import math
if __package__:
    from .rolling_mean import SampleMean5s
else:
    from rolling_mean import SampleMean5s
from pathlib import Path

PROFILE = Path('/etc/cabinet/display-calibration.json')


def load_profile(path=PROFILE):
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            return None
        return json.loads(raw.decode('utf-8'))
    except (OSError, ValueError):
        return None


def convert_current(status, profile, collector_boot):
    if type(profile) is not dict or profile.get('schema') != 'cabinet-current-display-v1':
        return None
    if (profile.get('sensor') != 'ACS712-05B' or profile.get('supply_V') != 5
            or profile.get('adc_range_confirmed') is not True
            or profile.get('zero_source') != 'USER_CONFIRMED_LOAD_DISCONNECTED'
            or type(collector_boot) is not str
            or collector_boot.split('/')[0] != profile.get('device_id')):
        return None
    full_scale = profile.get('adc_positive_full_scale_V')
    zero = profile.get('zero_code')
    if (type(full_scale) not in (int, float) or full_scale not in (5, 10)
            or type(zero) not in (int, float) or not math.isfinite(zero)
            or not -32768 < zero < 32767):
        return None
    words = status.get('raw_words')
    if (status.get('input_validity', {}).get('adc') is not True
            or type(words) not in (list, tuple) or len(words) != 32
            or type(words[22]) is not int or not 0 <= words[22] <= 0xffffffff):
        return None
    raw = words[22] & 65535
    raw = raw - 65536 if raw & 32768 else raw
    if raw in (-32768, 32767):
        return None
    current = (raw - zero) * full_scale / 32768.0 / 0.185
    if not math.isfinite(current) or abs(current) > 5:
        return None
    return dict(value_A=current, raw_code=raw, zero_code=zero,
                conversion_id='%.12g/%.12g/ACS712-05B' % (zero, full_scale),
                source='MEASURED_ZERO_NOMINAL_SENSITIVITY',
                gain_calibrated=False, protection_qualified=False)


class CurrentDisplayMean(SampleMean5s):
    """Five-second mean of unique, valid collector samples; display only."""
    def apply(self,fields,sample,now):
        # Keep formally calibrated feature semantics and raw diagnostic units
        # unchanged. The nominal DC display is the observed flickering path.
        if fields.get('daily_current_kind')!='nominal':
            self.reset();return
        instant=fields.get('daily_current_instant_A',fields.get('daily_current_value','--'))
        input_valid=fields.get('daily_current_valid')=='1' and fields.get('daily_current_unit')=='A'
        fields.update(daily_current_instant_A=instant,daily_current_average_window_s='5',
                      daily_current_aggregation='ARITHMETIC_MEAN',daily_current_average_count='0',
                      daily_current_average_state='UNAVAILABLE')
        fields['daily_current_value']='--';fields['daily_current_valid']='0'
        status=sample.get('status',{});received=sample.get('received_at');stamp=status.get('uptime_ms')
        try:value=float(instant)
        except (ValueError,TypeError):self.reset();return
        if not input_valid or status.get('input_validity',{}).get('adc') is not True or not sample.get('boot'):
            self.reset();return
        identity=(sample['boot'],fields.get('daily_current_conversion_id'))
        result=self.push(value,received,stamp,identity,now)
        if result is None:return
        span=result['span_s']
        fields['daily_current_average_count']=str(len(self.rows))
        fields['daily_current_average_span_s']='%.3f' % span
        fields['daily_current_average_state']='WARMING_UP'
        if result['ready']:
            fields['daily_current_value']='%.3f' % (self.total/len(self.rows))
            fields['daily_current_valid']='1'
            fields['daily_current_average_state']='READY'
