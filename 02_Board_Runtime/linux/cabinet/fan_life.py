"""User-declared life budget and measured full-speed degradation estimate.

This is a read-only empirical estimate, not a calibrated failure-life model.
No PWM, MMIO, protection limit or NPU model is written by this module.
"""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import statistics
import time

CONFIG=Path('/etc/cabinet/fan-life.json')
STORE=Path('/var/lib/cabinet/fan-life/ledger.json')
STATE=Path('/run/cabinet-fan-life/state.json')
SOURCE=Path('/run/cabinet-live/npu_input.json')
NPU=Path('/run/cabinet-normal-npu/state.json')
SCHEMA='cabinet-fan-life-estimate-v1'
MASK=0xffffffff
NON_LIFE_STATUS={'CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'}

def number(value,low,high):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError('Finite value outside allowed range')
    return value

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_name(path.name+'.next')
    data=(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode('utf-8')
    fd=os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.chmod(str(temp),0o600);os.replace(str(temp),str(path))
    fd=os.open(str(path.parent),os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def validate_config(value):
    if (type(value) is not dict or value.get('schema')!='cabinet-fan-life-settings-v1' or
            type(value.get('device_id')) is not str or not value['device_id'] or
            type(value.get('revision')) is not int or value['revision']<1 or
            type(value.get('reference_request')) is not int or value['reference_request']<1):
        raise ValueError('Invalid fan-life settings')
    number(value['nominal_hours'],1,1000000);number(value['end_speed_ratio'],.1,.99)
    return value

def initial_config(device_id):
    return dict(schema='cabinet-fan-life-settings-v1',revision=1,device_id=device_id,
                nominal_hours=5000.,end_speed_ratio=.8,reference_request=1,
                declaration='USER_SUPPLIED_NOMINAL_LIFE',curve='LINEAR_FULL_SPEED_RETENTION')

def configure(body,action,config_path=CONFIG):
    path=Path(config_path)
    with path.with_name(path.name+'.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        config=validate_config(read(path))
        expected={'expected_revision','nominal_hours','end_speed_ratio'} if action=='configure' else {'expected_revision'}
        if set(body)!=expected or type(body['expected_revision']) is not int or body['expected_revision']!=config['revision']:
            raise ValueError('Settings changed; reload before saving')
        if action=='configure':
            config.update(nominal_hours=number(body['nominal_hours'],1,1000000),
                          end_speed_ratio=number(body['end_speed_ratio'],.1,.99))
        elif action=='reference':config['reference_request']+=1
        else:raise ValueError('Unknown life action')
        config['revision']+=1;atomic(path,config)
        return dict(state='SAVED_TO_SD',settings=config,actuator_command_sent=False)

def estimate(config,ledger):
    hours=ledger['operating_seconds']/3600.
    budget=max(0.,config['nominal_hours']-hours)
    reference=ledger.get('reference')
    if not reference or ledger.get('reference_request')!=config['reference_request']:
        return dict(kind='NOMINAL_ONLY',estimated_remaining_h=None,nominal_remaining_h=budget,
                    reference_rpm=None,latest_rpm=None,speed_retention=None,speed_loss_percent=None,
                    point_count=0,reference_pending=True)
    points=[p for p in ledger['points'] if p['reference_request']==config['reference_request']]
    rechecks=[p for p in points if p['id']!=reference['id']]
    latest=statistics.median([p['rpm'] for p in rechecks[-3:]]) if rechecks else reference['rpm']
    retention=latest/reference['rpm']
    fraction=max(0.,min(1.,(retention-config['end_speed_ratio'])/(1.-config['end_speed_ratio'])))
    remaining=min(budget,config['nominal_hours']*fraction)
    return dict(kind='DECLARED_LIFE_AND_FULL_SPEED_CURVE',estimated_remaining_h=remaining,
                nominal_remaining_h=budget,reference_rpm=reference['rpm'],latest_rpm=latest,
                speed_retention=retention,speed_loss_percent=max(0.,100*(1-retention)),
                point_count=len(points),reference_pending=False,
                speed_based_remaining_h=config['nominal_hours']*fraction)

class Tracker:
    def __init__(self,config,ledger=None):
        self.config=validate_config(config)
        self.ledger=ledger if ledger is not None else dict(schema='cabinet-fan-life-ledger-v1',device_id=config['device_id'],
            operating_seconds=0.,reference_request=config['reference_request'],reference=None,points=[],events=[],next_id=1)
        if self.ledger.get('schema')!='cabinet-fan-life-ledger-v1' or self.ledger.get('device_id')!=config['device_id']:
            raise ValueError('Life ledger identity mismatch; preserve existing record')
        number(self.ledger['operating_seconds'],0,3600000000)
        if not isinstance(self.ledger.get('points'),list) or not isinstance(self.ledger.get('events'),list):
            raise ValueError('Invalid life ledger')
        for point in self.ledger['points'] + ([self.ledger['reference']] if self.ledger.get('reference') else []):
            number(point['rpm'],1,20000);number(point['time'],0,1e12)
            if type(point.get('id')) is not int or type(point.get('reference_request')) is not int:
                raise ValueError('Invalid recorded full-speed point; preserve existing record')
        if type(self.ledger.get('next_id')) is not int or self.ledger['next_id']<1:
            raise ValueError('Invalid ledger sequence')
        self.previous=None;self.full_since=None;self.rows=[];self.recorded=False
        self.alarm_active=bool(self.ledger.get('alarm_active'));self.event_pending=next((e for e in reversed(self.ledger['events']) if e.get('state')=='WAIT_FULL_SPEED_SAMPLE'),None);self.last_reason='WAIT_INPUT'
        self.dirty=False;self.important=False
        for event in self.ledger['events']:
            if event.get('state')=='WAIT_FULL_SPEED_SAMPLE' and not set(event.get('causes',[]))-NON_LIFE_STATUS:
                event.update(state='IGNORED_CONFIGURATION_STATUS',reason='Configuration state is not an over-limit life event')
                self.dirty=self.important=True
        self.event_pending=next((e for e in reversed(self.ledger['events']) if e.get('state')=='WAIT_FULL_SPEED_SAMPLE'),None)
        self.active_causes=set(self.ledger.get('active_causes',[]))-NON_LIFE_STATUS

    def reload_config(self,config):
        config=validate_config(config)
        if config['device_id']!=self.config['device_id']:raise ValueError('Device identity changed')
        if config['reference_request']!=self.ledger['reference_request']:
            self.ledger.update(reference_request=config['reference_request'],reference=None)
            self.full_since=None;self.rows=[];self.recorded=False;self.important=self.dirty=True
        self.config=config

    def invalidate(self,reason):
        self.previous=None;self.full_since=None;self.rows=[];self.recorded=False;self.last_reason=reason

    def update(self,document,now,wall,npu=None):
        o=document.get('observation') if type(document) is dict else None
        try:
            if type(o) is not dict or o.get('link')!='ONLINE':raise ValueError('WAIT_INPUT')
            number(o['received_at'],now-1.,now)
            boot=o['boot'];status=o['status'];frame=o.get('frame') or {}
            if (type(boot) is not str or not boot.startswith(self.config['device_id']+'/') or
                    frame.get('test') is True or frame.get('state') not in ('RECEIVED_REAL','EMPTY')):
                raise ValueError('REAL_COLLECTOR_REQUIRED')
            valid=status.get('input_validity') or {}
            if valid.get('rpm') is not True or valid.get('temperature') is not True:
                raise ValueError('FG_OR_TEMPERATURE_INVALID')
            rpm=number(status['measured_rpm'],0,20000);temperature=number(status['temp_raw_1_16_C']/16.,-55,125)
            stamp=status['uptime_ms'];duty=status['applied_pwm_counts']
            if type(stamp) is not int or not 0<=stamp<=MASK or type(duty) is not int or not 0<=duty<=4000:
                raise ValueError('HARDWARE_READBACK_INVALID')
            latched=status.get('latched')
            if type(latched) is not list:raise ValueError('PROTECTION_STATUS_INVALID')
        except (KeyError,TypeError,ValueError) as error:
            self.invalidate(str(error));return self.snapshot(now,False)
        identity=(boot,stamp)
        if self.previous and identity==self.previous[:2]:return self.snapshot(now,True)
        if self.previous:
            previous_boot,previous_stamp,previous_running=self.previous
            elapsed=((stamp-previous_stamp)&MASK)/1000.
            if previous_boot==boot and 0<elapsed<=2:
                if previous_running and rpm>0:self.ledger['operating_seconds']+=elapsed;self.dirty=True
            else:self.full_since=None;self.rows=[];self.recorded=False
        self.previous=(boot,stamp,rpm>0)
        if self.ledger.get('full_cycle_boot')!=boot:self.ledger.pop('full_cycle_recorded',None)
        causes=[name for name in latched if name not in NON_LIFE_STATUS]
        active=set(status.get('active') or [])
        words=status.get('raw_words') or []
        if len(words)==32 and type(words[31]) is int and words[31]>>16==0x52:
            # The P52 notification channel also carries the manual alarm test.
            # Record real sensor/NPU causes below, not this duplicate transport.
            active-={'SOFT_PS','SOFT_EXPIRED'}
        for name in sorted(active):
            if name not in causes and name not in NON_LIFE_STATUS:causes.append(name)
        if temperature>=80:causes.append('TEMPERATURE_AT_FULL_SPEED_ENDPOINT')
        if (type(npu) is dict and npu.get('valid') is True and npu.get('status')=='RUNNING' and
                type(npu.get('updated_at')) in (int,float) and 0<=now-npu['updated_at']<1 and
                npu.get('advisory',{}).get('warning_latched') is True):causes.append('NPU_SUSTAINED_DEVIATION')
        alarm=bool(causes)
        rising=sorted(set(causes)-self.active_causes)
        if rising:
            event=dict(id=self.ledger['next_id'],time=wall,causes=rising,pwm_counts=duty,rpm=rpm,
                       temperature_C=temperature,state='WAIT_FULL_SPEED_SAMPLE',source='REAL_FCB1_COLLECTOR')
            self.ledger['next_id']+=1;self.ledger['events']=(self.ledger['events']+[event])[-256:]
            self.event_pending=event;self.important=self.dirty=True
            if duty==4000:
                self.full_since=None;self.rows=[];self.recorded=False
                self.ledger.pop('full_cycle_recorded',None)
        if self.alarm_active!=alarm:self.dirty=True
        self.alarm_active=alarm;self.ledger['alarm_active']=alarm
        if set(causes)!=self.active_causes:self.dirty=True
        self.active_causes=set(causes);self.ledger['active_causes']=sorted(self.active_causes)
        for event in self.ledger['events']:
            if event.get('state')=='WAIT_FULL_SPEED_SAMPLE' and wall-event['time']>600:
                event.update(state='NO_COMPARABLE_FULL_SPEED_SAMPLE',reason='No stable unprotected full-speed sample within ten minutes')
                self.important=self.dirty=True
        pending=[event for event in self.ledger['events'] if event.get('state')=='WAIT_FULL_SPEED_SAMPLE']
        self.event_pending=pending[-1] if pending else None
        if duty!=4000 or rpm<=0 or latched:
            if self.ledger.pop('full_cycle_recorded',None):self.important=self.dirty=True
            self.full_since=None;self.rows=[];self.recorded=False
            self.last_reason='PROTECTION_ACTIVE_NO_LIFE_SAMPLE' if latched else 'WAIT_ACTUAL_FULL_PWM'
            return self.snapshot(now,True)
        if self.ledger.get('full_cycle_recorded')==self.config['reference_request']:
            self.last_reason='FULL_SPEED_POINT_RECORDED';return self.snapshot(now,True)
        if self.full_since is None:self.full_since=now
        self.last_reason='FULL_SPEED_SETTLING'
        if now-self.full_since<2:return self.snapshot(now,True)
        if self.recorded:self.last_reason='FULL_SPEED_POINT_RECORDED';return self.snapshot(now,True)
        self.rows.append((now,rpm,temperature));self.rows=[r for r in self.rows if now-r[0]<=2.5]
        if len(self.rows)<8 or now-self.rows[0][0]<1.8:return self.snapshot(now,True)
        speeds=[r[1] for r in self.rows];median=statistics.median(speeds)
        if statistics.pstdev(speeds)/median>.05:
            self.last_reason='FULL_SPEED_NOT_STABLE';return self.snapshot(now,True)
        point=dict(id=self.ledger['next_id'],time=wall,operating_hours=self.ledger['operating_seconds']/3600.,
            reference_request=self.config['reference_request'],rpm=median,samples=len(speeds),
            rpm_range=[min(speeds),max(speeds)],actual_pwm_percent=100.,
            temperature_C=statistics.median([r[2] for r in self.rows]),source='REAL_FCB1_COLLECTOR',
            collector_boot=boot,uptime_ms=stamp,event_id=self.event_pending['id'] if self.event_pending else None,
            event_ids=[event['id'] for event in pending])
        self.ledger['next_id']+=1;self.ledger['points']=(self.ledger['points']+[point])[-512:]
        if self.ledger['reference'] is None:
            self.ledger['reference']=dict(point);point['role']='INITIAL_REFERENCE'
        else:point['role']='FULL_SPEED_RECHECK'
        for event in pending:event.update(state='FULL_SPEED_SAMPLE_RECORDED',point_id=point['id'])
        self.event_pending=None
        self.ledger.update(full_cycle_recorded=self.config['reference_request'],full_cycle_boot=boot)
        self.recorded=True;self.last_reason='FULL_SPEED_POINT_RECORDED';self.important=self.dirty=True
        return self.snapshot(now,True)

    def snapshot(self,now,source_valid):
        estimate_value=estimate(self.config,self.ledger)
        return dict(schema=SCHEMA,updated_at=now,source_valid=source_valid,status=self.last_reason,
            settings=self.config,operating_hours=self.ledger['operating_seconds']/3600.,
            estimate=estimate_value,points=self.ledger['points'][-40:],events=self.ledger['events'][-40:],
            lifetime_qualified=False,estimate_basis='USER_DECLARED_NOMINAL_HOURS_AND_FULL_SPEED_RETENTION',
            control_authority=False,actuator_command_sent=False,saved_on_sd=True,
            reference_progress_s=0 if self.full_since is None else max(0.,min(4.,now-self.full_since)),
            curve_formula='min(nominal_hours - observed_running_hours, nominal_hours * clamp((rpm/reference_rpm - end_speed_ratio)/(1-end_speed_ratio), 0, 1))',
            note='Empirical maintenance estimate; no observed end-of-life calibration or failure-time guarantee.')

def public_status(config_path=CONFIG,state_path=STATE,clock=time.monotonic):
    config=validate_config(read(config_path));now=clock()
    try:
        result=read(state_path)
        if result.get('schema')!=SCHEMA or result.get('os_boot_id')!=Path('/proc/sys/kernel/random/boot_id').read_text().strip() or not 0<=now-result['updated_at']<=5:
            raise ValueError('Life observer not current')
        result['settings']=config
        if result.get('applied_revision')!=config['revision']:
            result['configuration_pending']=True;result['estimate']=None
        return result
    except (OSError,ValueError,KeyError,TypeError):
        return dict(schema=SCHEMA,status='OBSERVER_UNAVAILABLE',settings=config,estimate=None,points=[],events=[],
                    saved_on_sd=True,lifetime_qualified=False,control_authority=False)

def display_fields(state):
    e=state['estimate'];config=state['settings'];estimate_ready=e['estimated_remaining_h'] is not None
    return dict(display_schema='cabinet-life-display-v1',display_os_boot=state['os_boot_id'],
        panel_life_deadline_ms=str(int((state['updated_at']+5)*1000)),panel_life_available='1',
        panel_life_source_valid='1' if state['source_valid'] else '0',panel_life_status=state['status'],
        panel_life_kind=e['kind'],panel_life_hours='%.1f'%(e['estimated_remaining_h'] if estimate_ready else config['nominal_hours']),
        panel_life_nominal_hours='%.0f'%config['nominal_hours'],panel_life_operating_hours='%.2f'%state['operating_hours'],
        panel_life_reference_rpm='--' if e['reference_rpm'] is None else '%.0f'%e['reference_rpm'],
        panel_life_latest_rpm='--' if e['latest_rpm'] is None else '%.0f'%e['latest_rpm'],
        panel_life_loss='--' if e['speed_loss_percent'] is None else '%.1f'%e['speed_loss_percent'],
        panel_life_points=str(e['point_count']),panel_life_endpoint_loss='%.0f'%(100*(1-config['end_speed_ratio'])),
        panel_life_progress_s='%.1f'%state['reference_progress_s'])

def publish(state,path=STATE):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    # /run publications are atomic but need no SD fsync on every UI update.
    temp=path.with_name(path.name+'.next');temp.write_text(json.dumps(state,separators=(',',':'),allow_nan=False));temp.chmod(0o600);os.replace(str(temp),str(path))
    fields=display_fields(state);target=path.with_name('state.display.txt');temp=target.with_name(target.name+'.next')
    temp.write_text(''.join(k+'='+str(v).replace('\n',' ')+'\n' for k,v in fields.items()));temp.chmod(0o600);os.replace(str(temp),str(target))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',type=Path,default=CONFIG);ap.add_argument('--store',type=Path,default=STORE);a=ap.parse_args()
    config=validate_config(read(a.config));tracker=Tracker(config,read(a.store) if a.store.exists() else None)
    if not a.store.exists():atomic(a.store,tracker.ledger)
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();stop=[False]
    signal.signal(signal.SIGTERM,lambda *unused:stop.__setitem__(0,True));signal.signal(signal.SIGINT,lambda *unused:stop.__setitem__(0,True))
    flushed=published=0.;last_state=None
    try:
        while not stop[0]:
            now=time.monotonic()
            tracker.reload_config(read(a.config))
            try:document=read(SOURCE)
            except (OSError,ValueError):document={}
            try:npu=read(NPU)
            except (OSError,ValueError):npu=None
            result=tracker.update(document,time.monotonic(),time.time(),npu)
            result.update(os_boot_id=boot,applied_revision=tracker.config['revision'])
            if tracker.important or (tracker.dirty and now-flushed>=60):
                atomic(a.store,tracker.ledger);flushed=now;tracker.important=tracker.dirty=False
            if now-published>=1 or result['status']!=last_state:
                publish(result);published=now;last_state=result['status']
            time.sleep(.2)
    finally:
        atomic(a.store,tracker.ledger)
        result=tracker.snapshot(time.monotonic(),False);result.update(os_boot_id=boot,applied_revision=tracker.config['revision'],status='OBSERVER_STOPPED');publish(result)

if __name__=='__main__':main()
