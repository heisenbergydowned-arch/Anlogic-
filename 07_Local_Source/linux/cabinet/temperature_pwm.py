"""Durable temperature curve; only the collector worker touches TPW1 hardware."""
import copy
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid
from .alarm_only import AlarmOnlyReporter
from .speed_alarm import validate_policy

BASE=0x0a00
MAGIC=0x54505731
ABI=0x10000
CAPABILITY=1<<22
ARM=0x54484d31
SCHEMA='cabinet-temperature-pwm-v1'
CAUSES=('ADC_INVALID','TEMPERATURE_INVALID','CURRENT_PEAK','CURRENT_MEAN',
        'OVERSPEED','FG_MISSING','WATCHDOG_EXPIRED','OWNER_CONFLICT')

def number(value):return type(value) in (int,float) and math.isfinite(value)

def curve_counts(raw,low_C=25,high_C=80):
    if type(raw) is not int or not -880<=raw<=2000:raise ValueError('TEMPERATURE_INVALID')
    low,high=round(low_C*16),round(high_C*16)
    if high<=low:raise ValueError('TEMPERATURE_ENDPOINT_ORDER')
    if raw<=low:return 0
    if raw>=high:return 4000
    return ((raw-low)*4000+(high-low)//2)//(high-low)

def validate(document,device):
    required={'schema','device_id','revision','enabled','low_C','high_C','guards'}
    if type(document) is not dict or not required <= set(document) <= required | {'speed_alarm'}:
        raise ValueError('TEMPERATURE_PWM_CONFIG_SCHEMA')
    d=copy.deepcopy(document)
    if d['schema']!=SCHEMA or d['device_id']!=device:raise ValueError('TEMPERATURE_PWM_DEVICE_MISMATCH')
    if type(d['revision']) is not int or not 1<=d['revision']<=0xffffffff or type(d['enabled']) is not bool:
        raise ValueError('TEMPERATURE_PWM_CONFIG_REVISION')
    low,high=d['low_C'],d['high_C']
    if not number(low) or not number(high) or not 0<=low<=60 or not low+5<=high<=100:
        raise ValueError('端点要求：低温 0–60°C，高温至少高 5°C 且不超过 100°C')
    d['low_C'],d['high_C']=round(low*16)/16.,round(high*16)/16.
    g=d['guards']
    if type(g) is not dict or set(g)!={'current_zero_code','mean_trip_code','peak_trip_code','max_rpm','reference'}:
        raise ValueError('TEMPERATURE_PWM_PROTECTION_PROFILE_REQUIRED')
    if (any(type(g[k]) is not int for k in ('current_zero_code','mean_trip_code','peak_trip_code','max_rpm'))
            or not -32768<=g['current_zero_code']<=32767
            or not 0<g['mean_trip_code']<g['peak_trip_code']<=8192 or not 1000<=g['max_rpm']<=7200
            or type(g['reference']) is not dict or g['reference'].get('qualified') is not False):
        raise ValueError('TEMPERATURE_PWM_PROTECTION_PROFILE_INVALID')
    if 'speed_alarm' in d:
        d['speed_alarm']=validate_policy(d['speed_alarm'],g['max_rpm'])
    return d

def words(d):
    g=d['guards']
    return [round(d['low_C']*16)|(round(d['high_C']*16)<<16),
            (g['current_zero_code']&65535)|(g['mean_trip_code']<<16),
            g['peak_trip_code']|(g['max_rpm']<<16),d['revision']]

def atomic(path,document):
    if path.is_symlink() or not path.parent.is_dir():raise ValueError('TEMPERATURE_PWM_STORAGE_PATH')
    raw=(json.dumps(document,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode('utf-8')
    temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    try:
        fd=os.open(str(temporary),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(str(temporary),str(path))
        directory=os.open(str(path.parent),os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if temporary.exists():temporary.unlink()

class TemperaturePWM:
    def __init__(self,service,path=None):
        self.service=service
        self.alarm_reporter=AlarmOnlyReporter();self.last_alarm={}
        self.path=Path(path or service.config.get('temperature_pwm',{}).get('config_path','/etc/cabinet/temperature-pwm.json'))
        self.lock=threading.Lock();self.save_lock=threading.Lock()
        self.settings=None;self.load_error=None;self.forced_off=False;self.save_error=None
        try:
            if self.path.is_symlink():raise ValueError('TEMPERATURE_PWM_CONFIG_SYMLINK')
            if self.path.exists():self.settings=validate(json.loads(self.path.read_text()),service.config['device_id'])
        except (OSError,ValueError,TypeError) as error:self.load_error=str(error)
        self.context=None;self.supported=False;self.phase='NEW';self.applying=None
        self.applied=None;self.blocked=None;self.heartbeat_at=0;self.apply_started=None
        self.view=dict(state='NOT_CONFIGURED' if self.settings is None else 'CONNECTING',hardware_supported=False,
                       hardware_armed=False,actual_pwm_percent=None,target_pwm_percent=None,reason=self.load_error)

    def snapshot(self,now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            result=copy.deepcopy(self.view);settings=copy.deepcopy(self.settings)
            result.update(runtime_stop_requested=self.forced_off,save_error=self.save_error)
        result.update(schema=SCHEMA,settings=settings,saved=settings is not None,
                      configured_path=str(self.path),independent_meter_calibration=False,
                      current_threshold_cutoff_enabled=False,current_sensor_cutoff_enabled=False,alarm_can_stop_pwm=False,
                      zero_pwm_is_power_disconnected=False)
        stamp=result.get('observed_at')
        result['feedback_remaining_ms']=max(0,int((stamp+1-now)*1000)) if number(stamp) and 0<=now-stamp<=1 else 0
        if stamp is None or not 0<=now-stamp<=1:
            result.update(actual_pwm_percent=None,target_pwm_percent=None,temperature_C=None,rpm=None,
                          feedback_valid=False,deadline_ms=0)
            if stamp is not None:result['state']='STALE_FEEDBACK'
        return result

    def save(self,request):
        if type(request) is not dict or set(request)!={'expected_revision','low_C','high_C','enabled'}:
            raise ValueError('TEMPERATURE_PWM_EXPLICIT_SETTINGS_REQUIRED')
        with self.save_lock:
            with self.lock:current=copy.deepcopy(self.settings)
            if current is None:raise ValueError('TEMPERATURE_PWM_PROTECTION_PROFILE_REQUIRED')
            if type(request['expected_revision']) is not int or request['expected_revision']!=current['revision']:
                raise ValueError('参数已经更新，请刷新后重试')
            if request['enabled'] is True:
                if self.service.mock or self.service.diagnostic_test:raise ValueError('REAL_COLLECTOR_REQUIRED')
                if self.service.config['control'].get('enabled'):raise ValueError('先停用转速闭环控制')
                if self.service.bench.snapshot(record_limit=0).get('controls_enabled'):raise ValueError('先结束 PWM 台架试验')
                workspace=getattr(self.service,'workbench',None)
                if workspace and any(getattr(workspace,n,None) and getattr(workspace,n).busy() for n in ('learning','labeled_learning')):
                    raise ValueError('请先完成或取消当前学习，避免改变采集工况')
            candidate=validate(dict(current,revision=current['revision']+1,enabled=request['enabled'],
                                    low_C=request['low_C'],high_C=request['high_C']),self.service.config['device_id'])
            # Never hold the fast hardware-state lock across SD I/O.
            if not candidate['enabled']:
                with self.lock:self.forced_off=True
            try:atomic(self.path,candidate)
            except (OSError,ValueError) as error:
                with self.lock:self.save_error=str(error)
                raise
            with self.lock:
                self.settings=candidate;self.load_error=None;self.forced_off=not candidate['enabled'];self.save_error=None
            return dict(state='SAVED_PENDING_HARDWARE',saved=True,revision=candidate['revision'],settings=copy.deepcopy(candidate))

    def alarm_test(self,request):
        if type(request) is not dict or set(request)!={'duration_s'}:raise ValueError('Explicit duration_s required')
        return self.alarm_reporter.test(request['duration_s'])

    def _publish(self,state,status,now,**extra):
        valid=status.get('input_validity',{});raw=status.get('temp_raw_1_16_C')
        actual=status.get('applied_pwm_counts')
        with self.lock:
            settings=self.settings
            calculated=(curve_counts(raw,settings['low_C'],settings['high_C'])/40.
                if settings and valid.get('temperature') is True and type(raw) is int and -880<=raw<=2000 else None)
            value=dict(state=state,hardware_supported=self.supported,hardware_armed=False,
                observed_at=now,deadline_ms=int((now+1)*1000),feedback_valid=True,
                temperature_C=raw/16. if valid.get('temperature') is True and type(raw) is int and -880<=raw<=2000 else None,
                rpm=status.get('measured_rpm') if valid.get('rpm') is True else None,
                curve_pwm_percent=calculated,target_pwm_percent=None,
                actual_pwm_percent=actual/40. if type(actual) is int and 0<=actual<=4000 else None,
                applied_revision=self.applied,reason=None,faults=[])
            value.update(self.last_alarm);value.update(extra)
            value['faults']=sorted(set(value.get('faults',[])+self.last_alarm.get('alarm_causes',[])))
            self.view=value

    def poll(self,controller,status,now,context):
        applied_this_poll=False
        raw=status.get('raw_words',[])
        capable=len(raw)==32 and bool(raw[0]&CAPABILITY)
        if context!=self.context:
            self.context=context;self.supported=False;self.phase='NEW';self.applying=None
            self.applied=None;self.blocked=None;self.heartbeat_at=0
        with self.lock:settings=self.settings;forced_off=self.forced_off;save_error=self.save_error
        if self.service.mock or self.service.diagnostic_test or not hasattr(controller,'io'):
            self.supported=False;self._publish('LOCAL_PREVIEW_ONLY',status,now);return
        if not capable:
            self.supported=False;self._publish('FIRMWARE_REQUIRED',status,now,reason='当前固件尚无持续温控 PWM 通道');return
        io=controller.io
        if not self.supported:
            if (io.read(BASE),io.read(BASE+4))!=(MAGIC,ABI):
                self._publish('HARDWARE_MISMATCH',status,now,reason='温控硬件版本不匹配');return
            self.supported=True
        flags=io.read(BASE+8);armed=bool(flags&1);tripped=bool(flags&2)
        if settings is not None:
            self.last_alarm=self.alarm_reporter.poll(controller,status,flags,io.read(BASE+0x2c),settings,now,context,vibration=getattr(self.service,'state',{}).get('vibration_monitor'))
        if settings is None or not settings['enabled'] or forced_off:
            if armed or tripped:io.write(BASE+0x20,0)
            stopped=io.read(BASE+8)&3==0 and io.read(BASE+0x28)&65535==0 and status.get('applied_pwm_counts')==0
            self.phase='NEW';self.applied=settings['revision'] if settings and stopped else None
            stopped_state='STOPPED_UNSAVED' if save_error else ('DISABLED' if settings else 'NOT_CONFIGURED')
            self._publish(stopped_state if stopped else 'STOPPING',status,now,
                          reason='停用未写入 SD，重启可能恢复旧设置' if save_error else self.load_error);return
        revision=settings['revision'];expected=words(settings)
        if self.service.config['control'].get('enabled') or self.service.bench.snapshot(record_limit=0).get('controls_enabled'):
            self._publish('OWNER_CONFLICT',status,now,reason='另一控制模式正在使用风机');return
        hardware_revision=io.read(BASE+0x1c)
        # Reattach to a running saved curve after a service restart without STOP.
        if self.applying is None and armed and not tripped and hardware_revision==revision:
            if [io.read(BASE+0x10+4*i) for i in range(4)]==expected:
                self.applying=revision;self.applied=revision;self.phase='RUNNING'
        if tripped and hardware_revision==revision:
            self.blocked=revision
        if self.blocked==revision:
            faults=[name for bit,name in enumerate(CAUSES) if flags&(1<<(8+bit))]
            self._publish('FAULT_LATCHED' if tripped else 'APPLY_FAILED',status,now,faults=faults,
                          fault_latched=tripped,reason='输出未启用；排除原因后重新保存并启用');return
        if self.applying!=revision:
            io.write(BASE+0x20,0)
            if io.read(BASE+8)&3:
                self.blocked=revision;self._publish('STOP_REJECTED',status,now);return
            for index,value in enumerate(expected):io.write(BASE+0x10+4*index,value)
            if [io.read(BASE+0x10+4*i) for i in range(4)]!=expected:
                self.blocked=revision;self._publish('CONFIGURATION_REJECTED',status,now);return
            self.applying=revision;self.phase='WAIT_MEAN';self.apply_started=now
        if self.phase=='WAIT_MEAN':
            flags=io.read(BASE+8)
            if status.get('input_validity',{}).get('temperature') is not True:
                self._publish('WAITING_SENSOR',status,now,reason='等待有效温度样本');return
            io.write(BASE+0x20,ARM);flags=io.read(BASE+8)
            if flags&1:
                self.phase='RUNNING';self.applied=revision;self.heartbeat_at=0
                applied_this_poll=True
            else:
                self.blocked=revision;self._publish('ARM_REJECTED',status,now,reason='输入或保护条件不满足');return
        if self.phase=='RUNNING':
            flags=io.read(BASE+8)
            if not flags&1 or flags&2:
                self.blocked=revision
                faults=[name for bit,name in enumerate(CAUSES) if flags&(1<<(8+bit))]
                self._publish('FAULT_LATCHED',status,now,faults=faults,reason='温控输出已停止，等待重新启用');return
            if now>=self.heartbeat_at:
                io.write(BASE+0x24,revision);self.heartbeat_at=now+.25
            applied=io.read(BASE+0x28);target=applied>>16;actual=applied&65535
            flags=io.read(BASE+8)
            if not flags&1 or flags&2:
                self.blocked=revision
                self._publish('FAULT_LATCHED',status,now,faults=[name for bit,name in enumerate(CAUSES) if flags&(1<<(8+bit))]);return
            if target>4000 or actual>4000:
                self.alarm_reporter.note('CONTROL_READBACK_INVALID',now)
                self._publish('READBACK_INVALID',status,now,hardware_armed=armed,
                              actual_pwm_percent=None,target_pwm_percent=None,feedback_valid=False,
                              faults=['CONTROL_READBACK_INVALID'],reason='PWM读回异常；温控继续运行')
                return
            alarms=self.last_alarm
            if applied_this_poll:
                # FCB1 was sampled before this poll committed the new curve.
                # Wait for the next real output sample rather than pair that old
                # global output with the new target or substitute a request.
                self._publish('RUNNING',status,now,hardware_armed=True,
                              actual_pwm_percent=None,target_pwm_percent=None,
                              feedback_valid=False,feedback_pending=True,
                              reason='新曲线已启用，等待下一次实际输出读回',**alarms)
                return
            self._publish('RUNNING',status,now,hardware_armed=True,target_pwm_percent=target/40.,
                          tpw_pwm_percent=actual/40.,target_source='FPGA_TPW1_READBACK',faults=alarms['alarm_causes'],**alarms)

    def lost_link(self,error):
        with self.lock:
            self.view=dict(state='OFFLINE',hardware_supported=self.supported,hardware_armed=False,
                           actual_pwm_percent=None,target_pwm_percent=None,reason=str(error),feedback_valid=False)

    def shutdown(self,controller):
        # A monitor restart must not interrupt the FPGA's saved temperature curve.
        # The explicit user disable path in poll() still sends STOP.
        pass
