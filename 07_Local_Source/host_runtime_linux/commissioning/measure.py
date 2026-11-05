"""Record explicit external references or physically confirmed current zero."""
import csv,json,math,statistics,time,uuid
from pathlib import Path
from . import SOURCE
from cabinet.tracking_contract import MIN_SAMPLES, MIN_SECONDS, WINDOW_SECONDS, MAX_GAP_SECONDS, MAX_RELATIVE_ERROR, target_stable

UNITS={'current':'A','pressure':'Pa','fg':'rpm','temperature':'C'}

def current_zero_declaration(operator,load_path_open,sensor_chain_powered):
    if load_path_open is not True or sensor_chain_powered is not True:
        raise ValueError('CONFIRM_PHYSICAL_LOAD_DISCONNECTION_AND_POWERED_SENSOR_CHAIN')
    if (type(operator) is not str or not operator.strip() or len(operator)>80
            or any(ord(c)<32 for c in operator)):
        raise ValueError('CURRENT_ZERO_OPERATOR_REQUIRED')
    return dict(operator=operator,load_path_open=True,sensor_chain_powered=True,
                declaration='FAN_12V_MAIN_CURRENT_PATH_OPEN_ACS712_ADC_AND_BOARD_POWERED')

def zero_observation(o,s):
    raw=s.get('raw_words')
    if type(raw) is not list or len(raw)!=32 or any(type(v) is not int or not 0<=v<=0xffffffff for v in raw):
        raise ValueError('CURRENT_ZERO_RAW_STATUS_REQUIRED')
    if s.get('input_validity',{}).get('adc') is not True or not raw[0]&(1<<11):
        raise ValueError('CURRENT_ZERO_ADC_INVALID')
    if (s.get('hard_inhibit') is not True or not raw[0]&(1<<4)
            or type(s.get('applied_pwm_counts')) is not int or s['applied_pwm_counts']!=0 or raw[7]&65535
            or type(s.get('requested_rpm')) is not int or s['requested_rpm']!=0 or raw[8]>>16):
        raise ValueError('CURRENT_ZERO_OUTPUT_NOT_INHIBITED_IDLE')
    for key,index in (('uptime_ms',1),('configuration_id',18)):
        if type(s.get(key)) is not int or not 0<=s[key]<=0xffffffff or s[key]!=raw[index]:
            raise ValueError('CURRENT_ZERO_STATUS_IDENTITY_MISMATCH')
    value=raw[22]&65535;value=value-65536 if value&32768 else value
    return dict(boot_id=o['boot'],configuration_id=s['configuration_id'],uptime_ms=s['uptime_ms'],
        current_raw_code=value,status_flags=raw[0],applied_pwm_counts=0,requested_rpm=0,
        adc_valid=True,hard_inhibit=True,source='REAL_PL_STATUS_RAW')

def observation(path):
    d=json.loads(Path(path).read_text(encoding='utf-8'));o=d['observation'];s=o['status']
    if o.get('link')!='ONLINE' or not 0<=time.monotonic()-o['received_at']<1:raise ValueError('Fresh collector required')
    if o.get('frame',{}).get('test') is True or o.get('frame',{}).get('state')=='REJECTED_TEST':raise ValueError('Synthetic inputs rejected')
    return d,o,s

def record_point(directory,channel,reference,split,seconds=5,state='/run/cabinet-live/state.json',*,_physical_zero=None,_guard=None):
    if channel not in UNITS or split not in ('fit','validation') or not math.isfinite(reference) or not 1<=seconds<=60:raise ValueError('Point arguments')
    root=Path(directory);settings=json.loads((root/'settings.json').read_text(encoding='utf-8'))
    if settings['source']!=SOURCE:raise ValueError('Live capture requires a measured-data input directory')
    if _physical_zero is not None and (channel!='current' or reference!=0 or split!='fit'):
        raise ValueError('PHYSICAL_ZERO_IS_CURRENT_FIT_ZERO_ONLY')
    values=[];seen=set();identities=set();zero_samples=[];zero_identity=None;last_uptime=None;until=time.monotonic()+seconds
    while time.monotonic()<until:
        if _guard is not None:_guard()
        d,o,s=observation(state)
        if not o['boot'].startswith(settings['device_id']+'/'):raise ValueError('Board changed')
        if _physical_zero is not None:
            sample=zero_observation(o,s);current=(sample['boot_id'],sample['configuration_id'])
            if zero_identity is not None and current!=zero_identity:raise ValueError('CURRENT_ZERO_BOOT_OR_CONFIGURATION_CHANGED')
            zero_identity=current
            if last_uptime is not None and ((sample['uptime_ms']-last_uptime)&0xffffffff)>=0x80000000:
                raise ValueError('CURRENT_ZERO_STATUS_REORDERED')
            last_uptime=sample['uptime_ms']
        key=(o['boot'],s['uptime_ms'])
        if key not in seen:
            validity={'current':'adc','pressure':'pressure','fg':'rpm','temperature':'temperature'}[channel]
            if s['input_validity'].get(validity) is not True:raise ValueError('Sensor is invalid: '+channel)
            raw=s['raw_words'];v=raw[22]&65535 if channel=='current' else s['pressure_raw_code'] if channel=='pressure' else raw[24] if channel=='fg' else s['temp_raw_1_16_C']
            if channel=='current' and v&32768:v-=65536
            values.append(v);seen.add(key);identities.add(o['boot'])
            if _physical_zero is not None:zero_samples.append(sample)
        time.sleep(.08)
    if len(values)<8 or len(identities)!=1:raise ValueError('Insufficient fresh points or collector restarted')
    if _guard is not None:_guard()
    identity=str(uuid.uuid4());path=root/'calibration.csv'
    result=dict(schema='cabinet-measured-reference-point-v1',channel=channel,reference=reference,unit=UNITS[channel],
        reference_origin='USER_ENTERED_EXTERNAL_INSTRUMENT',source=SOURCE,session_id=identity,boot=list(identities)[0],
        raw_mean=statistics.mean(values),raw_stdev=statistics.pstdev(values),raw_values=values,software_controls_issued=False)
    if _physical_zero is not None:
        result.update(reference_origin='USER_CONFIRMED_PHYSICAL_LOAD_DISCONNECTION',operator=_physical_zero['operator'],
            physical_declaration=_physical_zero,current_gain_calibrated=False,formal_calibration_qualified=False,
            configuration_id=zero_identity[1],samples=zero_samples,
            scope='CURRENT_ZERO_ONLY_NOT_GAIN_OR_RPM_CALIBRATION')
    evidence=root/'points';evidence.mkdir(exist_ok=True)
    (evidence/(identity+'.json')).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    with path.open('a',newline='',encoding='utf-8') as f:
        csv.writer(f).writerow([channel,split,statistics.mean(values),reference,UNITS[channel],identity,SOURCE])
    return result

def record_current_zero(directory,seconds,operator,load_path_open,sensor_chain_powered,
                        state='/run/cabinet-live/state.json',*,guard=None):
    declaration=current_zero_declaration(operator,load_path_open,sensor_chain_powered)
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 1<=seconds<=60:
        raise ValueError('CURRENT_ZERO_DURATION_1_TO_60_SECONDS')
    return record_point(directory,'current',0.,'fit',seconds,state,_physical_zero=declaration,_guard=guard)

def record_trace(path,seconds=30,state='/run/cabinet-live/state.json'):
    if not 10<=seconds<=600:raise ValueError('Trace duration must be 10..600 seconds')
    p=Path(path);seen=set();session=str(uuid.uuid4());until=time.monotonic()+seconds;identity=None
    with p.open('x',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['time_s','target_rpm','rpm','pwm_counts','temperature_C','setpoint_C','mode','valid','session_id','source'])
        while time.monotonic()<until:
            d,o,s=observation(state);key=(o['boot'],s['uptime_ms'])
            current=(o['boot'],s.get('configuration_id'))
            if identity is not None and current!=identity:raise ValueError('Collector/configuration changed during trace; start a new file')
            identity=current
            if key not in seen:
                valid=(s.get('configured') is True and s.get('test_mode') is False and not s.get('active') and not s.get('latched') and
                       s.get('input_validity',{}).get('rpm') is True and d['display'].get('panel_control_target_valid')=='1')
                writer.writerow([s['uptime_ms']/1000,s['ramped_rpm'],s['measured_rpm'],s['applied_pwm_counts'],s['temp_raw_1_16_C']/16,
                    d['display'].get('panel_control_temp_target',''),s['mode'],int(valid),session,SOURCE]);seen.add(key)
            time.sleep(.08)
    return dict(status='REAL_CONTROL_TRACE_RECORDED',rows=len(seen),path=str(p),control_commands_issued=False)

def evaluate_trace(path,source=SOURCE,temperature_tolerance_C=None):
    with Path(path).open(newline='',encoding='utf-8') as f:rows=list(csv.DictReader(f))
    if len(rows)<MIN_SAMPLES or any(r['source']!=source for r in rows):raise ValueError('At least 40 real source records required')
    data=[]
    for r in rows:
        x={k:float(r[k]) for k in ('time_s','target_rpm','rpm','pwm_counts','temperature_C')}
        if any(not math.isfinite(v) for v in x.values()):raise ValueError('Nonfinite control trace')
        data.append((r,x))
    if any(b[1]['time_s']<=a[1]['time_s'] or b[1]['time_s']-a[1]['time_s']>MAX_GAP_SECONDS for a,b in zip(data,data[1:])):raise ValueError('Control trace gaps or nonmonotonic time')
    end=data[-1][1]['time_s'];tail=[(r,x) for r,x in data if x['time_s']>=end-WINDOW_SECONDS]
    if len(tail)<MIN_SAMPLES or tail[-1][1]['time_s']-tail[0][1]['time_s']<MIN_SECONDS:raise ValueError('Ten continuous seconds of settled evidence required')
    if len({r['session_id'] for r,x in tail})!=1 or any(r['valid']!='1' or r['mode']!='RUN' or x['target_rpm']<=0 for r,x in tail):raise ValueError('No continuous valid fault-free RUN interval')
    targets=[x['target_rpm'] for r,x in tail]
    if not target_stable(targets):raise ValueError('Target did not settle')
    errors=[abs(x['rpm']-x['target_rpm'])/x['target_rpm'] for r,x in tail]
    result=dict(status='PASS_RPM_TRACKING_MEASUREMENT' if max(errors)<MAX_RELATIVE_ERROR else 'FAIL_RPM_TRACKING_MEASUREMENT',
        maximum_steady_error_percent=max(errors)*100,mean_steady_error_percent=statistics.mean(errors)*100,
        criterion_percent=2,window_seconds=tail[-1][1]['time_s']-tail[0][1]['time_s'],samples=len(tail),
        temperature_control_accepted=False,whole_project_accepted=False)
    if temperature_tolerance_C is not None:
        if not math.isfinite(temperature_tolerance_C) or temperature_tolerance_C<=0:raise ValueError('Positive measured temperature tolerance required')
        setpoints=[float(r['setpoint_C']) for r,x in tail]
        if any(not math.isfinite(v) for v in setpoints) or max(setpoints)-min(setpoints)>.05:raise ValueError('Fixed temperature setpoint required')
        thermal=max(abs(x['temperature_C']-float(r['setpoint_C'])) for r,x in tail)
        result.update(temperature_max_error_C=thermal,temperature_tolerance_C=temperature_tolerance_C,
            temperature_within_tolerance_in_this_window=thermal<=temperature_tolerance_C,
            temperature_control_accepted=False,thermal_scope='Observed steady window only; heat-load step response still requires a separate run')
    return result
