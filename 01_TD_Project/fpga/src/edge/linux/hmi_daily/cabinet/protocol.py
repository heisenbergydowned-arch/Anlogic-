"""FRM1 version 1: 32 metadata words + exactly 39 binary32 features."""
from collections import namedtuple
import math
import struct

FEATURES = ([f'{kind}_a_{axis}' for kind in ('rms','pp','kurt') for axis in 'xyz']
            + [f'banda{i}' for i in range(8)]
            + [f'{kind}_b_{axis}' for kind in ('rms','pp','kurt') for axis in 'xyz']
            + [f'bandb{i}' for i in range(8)] + ['ratio_ab','current','temp','pressure','rpm'])
LABELS = ('normal','imbalance','stall','clog','overheat')
QUALITY = {0:'zero_variance',1:'bad_bands',2:'saturation',3:'numeric_overflow',
           4:'a_gap',5:'b_gap',6:'a_rate',7:'b_rate',8:'current_invalid',9:'temp_invalid',
           10:'pressure_invalid',11:'fg_invalid',12:'uncalibrated',13:'transient_window',14:'test_source'}

def elapsed32(now, then):
    return (int(now)-int(then)) & 0xffffffff

class Frame(namedtuple('FrameBase', 'header values')):
    __slots__ = ()

    @classmethod
    def from_words(cls, header, words):
        if len(header)!=32 or len(words)!=39:
            raise ValueError('FRM1 requires 32 header + 39 feature words')
        if any(type(x) is not int or not 0<=x<=0xffffffff for x in [*header,*words]):
            raise ValueError('Frame words must be uint32')
        if header[:3]!=[0x46524d31,0x00010000,284] and tuple(header[:3])!=(0x46524d31,0x00010000,284):
            raise ValueError('Unknown frame magic/version/length')
        values=struct.unpack('<39f',struct.pack('<39I',*words))
        if not all(math.isfinite(v) for v in values):
            raise ValueError('NaN/Inf feature rejected')
        return cls(tuple(header),tuple(values))

    @property
    def id(self):return self.header[3]
    @property
    def quality(self):return self.header[15]
    @property
    def test(self):return bool(self.header[27] or self.quality & 0x4000)
    @property
    def adc_count(self):return self.header[13]&0xffff if self.header[18]==2 else self.header[13]
    @property
    def pressure_count(self):return self.header[13]>>16 if self.header[18]==2 else self.header[13]
    def as_dict(self):
        h=self.header
        return dict(frame_id=self.id,end_ms=h[4],quality=self.quality,
                    quality_reasons=[n for b,n in QUALITY.items() if self.quality & 1<<b],
                    feature_config_id=h[16],calibration_id=h[17],sample_mode_id=h[18],
                    mode=h[19],test=self.test,adc_count=self.adc_count,fg_count=h[14],
                    pressure_count=self.pressure_count,
                    pressure_source={1:'AD7606-CH2',2:'SDP810-500Pa'}.get(h[18],'unknown'),
                    sample_rate_a=(h[11]-1)*h[21]/h[9] if h[9] else None,
                    sample_rate_b=(h[12]-1)*h[21]/h[10] if h[10] else None,
                    dropped_windows=h[23],bitstream_id=f'{h[26]:08x}',
                    values=dict(zip(FEATURES,self.values)))

class FrameGate:
    def __init__(self, contract):
        self.contract=contract
        self.last_id=None
    def reset(self):self.last_id=None
    def check(self, frame, now_ms, *, diagnostic_test=False):
        h=frame.header;c=self.contract;reasons=[]
        if self.last_id is not None and not 0<elapsed32(frame.id,self.last_id)<0x80000000:
            reasons.append('duplicate_or_reordered')
        # Consume the sequence even for a rejected new frame. An old result may
        # not become applicable when quality/config later changes.
        if self.last_id is None or 0<elapsed32(frame.id,self.last_id)<0x80000000:self.last_id=frame.id
        if elapsed32(now_ms,h[4])>c.get('max_frame_age_ms',1000):reasons.append('stale_frame')
        if h[19]!=3 and not (diagnostic_test and frame.test):reasons.append('not_stable_run')
        if (h[11],h[12])!=(1024,1024):reasons.append('sample_count')
        if h[18]!=c.get('sample_mode_id',1):reasons.append('sample_mode')
        if h[16]!=c.get('feature_config_id',1):reasons.append('feature_config')
        if not diagnostic_test and (h[17]==0 or h[17]!=c.get('calibration_id')):reasons.append('calibration')
        if frame.test and not diagnostic_test:reasons.append('test_frame')
        allowed=0x7000 if diagnostic_test and frame.test else 0
        if frame.quality & ~allowed:reasons.append('quality')
        if h[15] & 0xffff8000:reasons.append('unknown_quality_bits')
        if h[21]==0 or h[9]==0 or h[10]==0:reasons.append('sample_time')
        else:
            for n,count,span in [('a',h[11],h[9]),('b',h[12],h[10])]:
                fs=(count-1)*h[21]/span
                if not 3880<=fs<=4120:reasons.append('rate_'+n)
            if h[25]>h[21]/4000:reasons.append('alignment')
        if self.contract.get('sample_mode_id',1) not in (1,2):reasons.append('unsupported_sample_mode')
        if frame.adc_count==0 or frame.pressure_count==0 or h[14]==0:reasons.append('process_count')
        if h[24]>c.get('max_temp_age_ms',2000):reasons.append('temperature_age')
        if frame.values[38]<0 or frame.values[38]>32767:reasons.append('rpm_range')
        return list(dict.fromkeys(reasons))
