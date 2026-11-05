"""Report alarms through FCB1; this module never sends actuator commands."""
import json
import math
from pathlib import Path
import time
from .speed_alarm import SpeedAlarm

def signed16(v):return v-65536 if v&32768 else v

def npu_alarm(document,now,context,os_boot):
    if not isinstance(document,dict):return None
    d=document
    if (d.get('backend')!='Alnpu' or d.get('valid') is not True or d.get('status')!='RUNNING'
            or d.get('collector_boot')!=context or d.get('os_boot_id')!=os_boot
            or d.get('source')!='REAL_CURRENT_SENSOR_FRAME'):return None
    stamp=d.get('updated_at')
    if type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0<=now-stamp<=1:return None
    received=d.get('received_at')
    if type(received) not in (int,float) or not math.isfinite(received) or not 0<=now-received<=1:return None
    if 'input_deadline' in d and (type(d['input_deadline']) not in (int,float) or not now<d['input_deadline']):return None
    if d.get('schema')=='cabinet-normal-npu-live-v1':
        a=d.get('advisory',{})
        if a.get('state') in ('WARN','RECOVERING') and a.get('warning_latched') is True:return 'NPU_DEVIATION'
    if d.get('schema')=='cabinet-labeled-npu-live-v1' and d.get('state')=='CLASSIFIED':
        label=d.get('fault_class')
        if label in ('imbalance','stall','clog','overheat'):return 'NPU_'+label.upper()
    return None

def advisory_filtered_active(status):
    active=set(status.get('active',[]));raw=status.get('raw_words',[])
    if (len(raw)==32 and type(raw[31]) is int and raw[31]>>16==0x52):
        active-= {'SOFT_PS','SOFT_EXPIRED'}
    return active

class AlarmOnlyReporter:
    def __init__(self):
        self.test_until=0;self.next_update=0;self.held_until=0;self.held=[];self.level=0;self.last_error=None
        self.speed=SpeedAlarm()
        try:self.os_boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        except OSError:self.os_boot=None
    def note(self,cause,now):
        self.held=sorted(set(self.held+[cause]));self.held_until=max(self.held_until,now+3);self.next_update=0
    def test(self,duration,now=None):
        if type(duration) is not int or not 1<=duration<=10:raise ValueError('Duration must be 1 to 10 seconds')
        now=time.monotonic() if now is None else now
        self.test_until=now+duration;self.next_update=0
        return dict(status='ALARM_TEST_SCHEDULED',duration_s=duration,pwm_changed=False)
    def poll(self,controller,status,flags,current_word,settings,now,context,vibration=None):
        if now>=self.next_update:
            self.next_update=now+.25
            g=settings['guards'];valid=status.get('input_validity',{})
            causes=[]
            if (isinstance(vibration,dict) and vibration.get('valid') is True and
                    vibration.get('collector_boot')==context and now*1000<vibration.get('deadline_ms',0)):
                if vibration.get('state')=='ALARM':causes.append('VIBRATION_HIGH')
                elif vibration.get('state')=='WARN':causes.append('VIBRATION_WARN')
            for name,key in [('ADC_INVALID','adc'),('TEMPERATURE_INVALID','temperature'),('FG_MISSING','rpm')]:
                if valid.get(key) is False:causes.append(name)
            if flags&1 and flags&(1<<23):causes.append('OWNER_CONFLICT')
            speed=self.speed.observe(status,now,settings.get('speed_alarm'),g['max_rpm'],context)
            speed_causes=(['OVERSPEED'] if speed['state']=='ALARM' else
                          ['RPM_HIGH_SUSTAINED'] if speed['state']=='WARNING' else [])
            if speed['state']=='DISABLED' and valid.get('rpm') and status.get('measured_rpm',0)>g['max_rpm']:
                causes.append('OVERSPEED')
            if valid.get('adc'):
                raw=signed16(current_word&65535);mean=signed16(current_word>>16)
                if abs(raw-g['current_zero_code'])>=g['peak_trip_code']:causes.append('CURRENT_PEAK')
                if flags&4 and flags&8 and abs(mean)>=g['mean_trip_code']:causes.append('CURRENT_MEAN')
            if valid.get('temperature') and status.get('temp_raw_1_16_C',0)>=round(settings['high_C']*16):causes.append('OVER_TEMPERATURE')
            for path in ('/run/cabinet-normal-npu/state.json','/run/cabinet-labeled-npu/state.json'):
                try:
                    p=Path(path)
                    if p.stat().st_size>32768:continue
                    source=npu_alarm(json.loads(p.read_text()),now,context,self.os_boot)
                    if source:causes.append(source)
                except (OSError,ValueError,TypeError):pass
            causes=sorted(set(causes))
            if causes:self.held=causes;self.held_until=now+3
            elif now>=self.held_until:self.held=[]
            effective=sorted(set(self.held+speed_causes+(['TEST_ALARM'] if now<self.test_until else [])))
            self.effective=effective
            self.level=(3 if any(x in effective for x in ('CURRENT_PEAK','OVER_TEMPERATURE','NPU_STALL','NPU_OVERHEAT','OVERSPEED','VIBRATION_HIGH'))
                        else 2 if any(x not in ('RPM_HIGH_SUSTAINED','NPU_DEVIATION') for x in effective) else 1 if effective else 0)
            if hasattr(controller,'command'):
                try:
                    # Heartbeat establishes only the advisory lease, never PS motor ownership.
                    controller.command(3,0)
                    controller.command(5,0x100 | (0x0052<<16 if self.level else 0) | (0x10 if self.level>=2 else 0) | self.level)
                    self.last_error=None
                except Exception as e:self.last_error=str(e)
        return dict(alarm_only=True,alarm_level=self.level,alarm_causes=list(getattr(self,'effective',self.held)),
                    buzzer_requested=self.level>=2,alarm_output_error=self.last_error,
                    alarm_can_stop_pwm=False,speed_alarm=dict(self.speed.value))
