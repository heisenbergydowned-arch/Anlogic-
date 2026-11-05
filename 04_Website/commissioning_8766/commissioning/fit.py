"""Deterministic calibration and configuration compiler. No hardware access."""
import copy,csv,hashlib,json,math,statistics
from pathlib import Path
from cabinet.io import FCB1
from link_cli import pack_feature
from v4_runtime.bundle import FEATURE_ID,COEFFICIENT_SHA,EDGES,FEATURES
from v4_runtime.profiles import PL_BUILD_ID

from . import SOURCE
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def number(value,low,high,name):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise ValueError(name+': finite value required in [%s,%s]'%(low,high))
    return value
def text(value,name):
    if type(value) is not str or not value.strip() or len(value)>160:raise ValueError(name+': measurement identity required')
    return value

TEMPLATE={
 'schema':'cabinet-measured-commissioning-v1','source':SOURCE,'device_id':None,'installation_id':None,'fan_id':None,
 'wiring':{'pwm_and_fg_connected':False,'pwm_polarity_verified':False,'pwm_zero_is_not_power_disconnect':False},
 'actuator':{'rpm_min':None,'rpm_max':None,'startup_rpm':None,'duty_min_percent':None,'duty_max_percent':None,
             'startup_percent':None,'fallback_percent':None,'boost_percent':None,'limit_percent':None,'overspeed_hard_rpm':None},
 'pi':{'kp_pwm_percent_per_rpm':None,'ki_pwm_percent_per_rpm_per_update':None,
       'target_slew_rpm_per_s':None,'tracking_error_rpm':None},
 'temperature':{'setpoint_C':None,'allowed_setpoint_min_C':None,'allowed_setpoint_max_C':None,
                'kp_rpm_per_C':None,'ki_rpm_per_C_s':None,'slew_rpm_per_s':None,
                'warning_C':None,'hard_C':None,'recover_C':None},
 'current':{'warning_A':None,'hard_A':None,'recover_A':None},
 'vibration':{'warning_code':None,'hard_code':None,'fixed_4096_counts_per_g_verified':False},
 'fit_tolerance':{'current_A':None,'pressure_Pa':None,'rpm_relative':0.02,'temperature_C':None},
 'timing_reviewed':False,
 'timing':{'adc_age_ms':5,'temp_age_ms':2000,'fg_age_ms':400,'recovery_ms':1000,'startup_ms':2000,
           'transient_ms':1000,'stop_ms':2000,'manual_lease_ms':60000,'heartbeat_ms':1000,'target_lease_ms':1000,
           'current_confirm_ms':100,'temp_confirm_ms':2000,'tracking_confirm_ms':2000,'vibration_confirm_ms':1000,
           'silence_ms':30000,'soft_lease_ms':1000,'fg_period_min_clocks':1000,'fg_period_max_clocks':12000000}}

def initialize(directory,device_id):
    root=Path(directory);root.mkdir(parents=True,exist_ok=False)
    settings=copy.deepcopy(TEMPLATE);settings['device_id']=device_id
    save(root/'settings.json',settings)
    (root/'calibration.csv').write_text('channel,split,raw,reference,unit,session_id,source\n',encoding='utf-8')
    (root/'actuator.csv').write_text('duty_percent,rpm,current_A,temperature_C,session_id,source\n',encoding='utf-8')
    (root/'control_trace.csv').write_text('time_s,target_rpm,rpm,pwm_counts,temperature_C,setpoint_C,mode,valid,session_id,source\n',encoding='utf-8')
    return dict(status='MEASUREMENT_TEMPLATES_CREATED',directory=str(root))

def rows(path,source):
    with Path(path).open(newline='',encoding='utf-8') as f:result=list(csv.DictReader(f))
    if not result:raise ValueError(Path(path).name+': no measured rows')
    for row in result:
        if row.get('source')!=source:raise ValueError('Mixed or unreviewed measurement source')
        text(row.get('session_id'),'session_id')
    return result

def fit_line(data,channel,unit,tolerance):
    selected=[r for r in data if r.get('channel')==channel]
    train=[r for r in selected if r.get('split')=='fit'];validation=[r for r in selected if r.get('split')=='validation']
    if len(train)<3 or len(validation)<2 or len({float(r['reference']) for r in train})<3:raise ValueError(channel+': 3 reference levels for fitting and 2 separate validation points required')
    if {r['session_id'] for r in train}&{r['session_id'] for r in validation}:raise ValueError(channel+': calibration and validation sessions overlap')
    for r in selected:
        if r['unit']!=unit or r['split'] not in ('fit','validation'):raise ValueError(channel+': unit/split mismatch')
        number(float(r['raw']),-32768,32767,channel+' raw');number(float(r['reference']),-1e6,1e6,channel+' reference')
    xs=[float(r['raw']) for r in train];ys=[float(r['reference']) for r in train]
    mx,my=statistics.mean(xs),statistics.mean(ys);den=sum((v-mx)**2 for v in xs)
    if den<=1e-12:raise ValueError(channel+': no input span')
    gain=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/den;offset=my-gain*mx
    if not math.isfinite(gain) or abs(gain)<1e-12:raise ValueError(channel+': zero/nonfinite gain')
    error=max(abs(gain*float(r['raw'])+offset-float(r['reference'])) for r in selected)
    if error>tolerance:raise ValueError(channel+': reference error %.6g exceeds %.6g'%(error,tolerance))
    return dict(gain=gain,offset=offset,zero=-offset/gain,maximum_reference_error=error,
                fit_rows=len(train),validation_rows=len(validation),unit=unit)

def validate_control(c):
    w=FCB1.pack_config(c);a=c
    if not (0<a['duty_min']<=a['duty_max']<=4000 and 0<a['rpm_min']<a['rpm_max']<=32767):raise ValueError('Duty/RPM envelope')
    if not all(0<a[k]<=a['duty_max'] for k in ('startup_duty','fallback_duty')):raise ValueError('Startup/fallback duty')
    if not all(a['duty_min']<=a[k]<=a['duty_max'] for k in ('boost_duty','limit_duty')):raise ValueError('Boost/limit duty')
    if not (0<a['kp_q8']<=32767 and 0<=a['ki_q8']<=32767):raise ValueError('PL Q8 gain range')
    if not 0<=a['current_recover']<a['current_high']<a['current_hard']<=65535:raise ValueError('Current hysteresis order')
    if not -880<=a['temp_recover']<a['temp_warning']<a['temp_hard']<=2000:raise ValueError('Temperature hysteresis order')
    if not 0<a['vibration_limit']<a['vibration_hard']<32767:raise ValueError('Vibration threshold order')
    if not a['rpm_max']<=a['overspeed_hard_rpm']<=32767:raise ValueError('Overspeed threshold')
    for k in TEMPLATE['timing']:
        if type(a[k]) is not int or a[k]<=0:raise ValueError('Positive integer timing: '+k)
    if not 128<=a['fg_period_min_clocks']<a['fg_period_max_clocks']:raise ValueError('FG interval limits')
    if a['target_slew']<=0 or a['tracking_error']<=0:raise ValueError('Positive slew and tracking tolerance')
    return w

def build(input_dir,base_config,output,allow_fixture=False):
    root=Path(input_dir);s=json.loads((root/'settings.json').read_text(encoding='utf-8'));base=json.loads(Path(base_config).read_text(encoding='utf-8'))
    expected_source='SYNTHETIC_FIXTURE' if allow_fixture else SOURCE
    if s.get('schema')!=TEMPLATE['schema'] or s.get('source')!=expected_source:raise ValueError('Explicit measured-data source required')
    if s.get('device_id')!=base.get('device_id'):raise ValueError('Board identity mismatch')
    for k in ('device_id','installation_id','fan_id'):text(s.get(k),k)
    if any(s.get('wiring',{}).get(k) is not True for k in TEMPLATE['wiring']):raise ValueError('Measured PWM/FG wiring/polarity confirmation required')
    if s.get('timing_reviewed') is not True or s.get('vibration',{}).get('fixed_4096_counts_per_g_verified') is not True:raise ValueError('Timing and existing +/-8g vibration scale must be measured/reviewed')
    data=rows(root/'calibration.csv',expected_source)
    tol=s['fit_tolerance']
    current=fit_line(data,'current','A',number(tol['current_A'],1e-6,100,'current tolerance'))
    pressure=fit_line(data,'pressure','Pa',number(tol['pressure_Pa'],1e-6,500,'pressure tolerance'))
    if not any(float(r['reference'])==0 for r in data if r['channel']=='current' and r['split']=='fit'):raise ValueError('Measured zero-current point required')
    fg=[r for r in data if r['channel']=='fg'];temperature=[r for r in data if r['channel']=='temperature']
    if len(fg)<3 or len(temperature)<2:raise ValueError('3 reference tachometer and 2 temperature checks required')
    rpm_tol=number(tol['rpm_relative'],.0001,.02,'FG reference relative error')
    possible=[]
    for ppr in range(1,9):
        if all(r['unit']=='rpm' and float(r['raw'])>0 and float(r['reference'])>0 and
               abs(6000000000/(float(r['raw'])*ppr)-float(r['reference']))/float(r['reference'])<=rpm_tol for r in fg):possible.append(ppr)
    if len(possible)!=1:raise ValueError('FG pulses/revolution cannot be identified uniquely')
    ppr=possible[0];temp_tol=number(tol['temperature_C'],.001,10,'temperature tolerance')
    for r in temperature:
        number(float(r['raw']),-880,2000,'temperature code');number(float(r['reference']),-55,125,'temperature reference')
        if r['unit']!='C' or abs(float(r['raw'])/16-float(r['reference']))>temp_tol:raise ValueError('DS18B20 nominal conversion did not pass reference checks')
    c=json.loads((Path(__file__).with_name('control_template.json')).read_text(encoding='utf-8'))
    for k in ('rpm_min','rpm_max','startup_rpm','overspeed_hard_rpm'):
        value=s['actuator'][k]
        if type(value) is not int:raise ValueError('Measured integer actuator setting required: '+k)
        if k!='startup_rpm':c[k]=value
    for field,key in [('duty_min','duty_min_percent'),('duty_max','duty_max_percent'),('startup_duty','startup_percent'),
                      ('fallback_duty','fallback_percent'),('boost_duty','boost_percent'),('limit_duty','limit_percent')]:
        c[field]=int(round(number(s['actuator'][key],.025,100,key)*40))
    if not c['rpm_min']<=s['actuator']['startup_rpm']<=c['rpm_max']:raise ValueError('Startup RPM outside measured envelope')
    c['kp_q8']=round(number(s['pi']['kp_pwm_percent_per_rpm'],0,3.19,'RPM proportional gain')*40*256)
    c['ki_q8']=round(number(s['pi']['ki_pwm_percent_per_rpm_per_update'],0,3.19,'RPM integral gain per fresh update')*40*256)
    c['target_slew']=round(number(s['pi']['target_slew_rpm_per_s'],100,6553500,'RPM ramp rate')*.01)
    c['tracking_error']=int(number(s['pi']['tracking_error_rpm'],1,32767,'tracking error RPM'))
    for k in TEMPLATE['timing']:c[k]=s['timing'][k]
    if not (c['heartbeat_ms']>=500 and c['target_lease_ms']>=500):raise ValueError('64 ms collector requires reviewed >=500 ms heartbeat and target leases')
    t=s['temperature'];cur=s['current'];vib=s['vibration']
    for name in ('recover_A','warning_A','hard_A'):number(cur[name],0,1000,name)
    c['current_zero']=int(round(current['zero']))
    for k,n in [('current_recover','recover_A'),('current_high','warning_A'),('current_hard','hard_A')]:
        c[k]=int(math.floor(cur[n]/abs(current['gain'])))
    for k,n in [('temp_recover','recover_C'),('temp_warning','warning_C'),('temp_hard','hard_C')]:
        c[k]=int(round(number(t[n],-55,125,n)*16))
    c.update(vibration_limit=vib['warning_code'],vibration_hard=vib['hard_code'],fg_pulses_per_revolution=ppr)
    for key in ('setpoint_C','allowed_setpoint_min_C','allowed_setpoint_max_C'):number(t[key],-55,125,key)
    if not t['allowed_setpoint_min_C']<=t['setpoint_C']<=t['allowed_setpoint_max_C']<t['warning_C']:raise ValueError('Setpoint range must stay below temperature warning')
    if not t['allowed_setpoint_min_C']<t['allowed_setpoint_max_C']:raise ValueError('Setpoint range')
    for key in ('kp_rpm_per_C','ki_rpm_per_C_s'):number(t[key],0,1e6,key)
    number(t['slew_rpm_per_s'],1,1e5,'temperature target slew')
    sweep=rows(root/'actuator.csv',expected_source)
    duties={round(number(float(r['duty_percent']),0,100,'measured duty percent')*40) for r in sweep}
    if not {c[k] for k in ('startup_duty','fallback_duty','boost_duty','limit_duty','duty_min','duty_max')}<=duties:raise ValueError('Each configured duty must have a measured fan operating point')
    for r in sweep:
        number(float(r['rpm']),c['rpm_min'],c['rpm_max'],'measured sweep RPM')
        number(float(r['current_A']),0,cur['recover_A'],'measured sweep current')
        number(float(r['temperature_C']),-55,t['recover_C'],'measured sweep temperature')
    evidence_files={n:sha(root/n) for n in ('settings.json','calibration.csv','actuator.csv')}
    evidence=hashlib.sha256(json.dumps(evidence_files,sort_keys=True).encode()).hexdigest()
    identity=int(evidence[:8],16) or 1
    c.update(config_id=identity,calibration_confirmed=True,calibration_evidence=evidence,
             qualifications=dict(current=True,temperature=True,actuator=True,pi=True,vibration=True))
    control_words=validate_control(c)
    f=dict(schema='EDG1-config-v1',feature_config_id=FEATURE_ID,calibration_id=identity,qualified=True,evidence=evidence,
           current_zero_q16=round(current['zero']*65536),pressure_zero_q16=round(pressure['zero']*65536),
           current_gain_q30=round(current['gain']*(1<<30)),pressure_gain_q30=round(pressure['gain']/1000*(1<<30)),
           ppr=ppr,edges=EDGES,sample_mode_id=2)
    feature_words=pack_feature(f)
    # Validate the coefficients actually representable by the PL, not just the floating fit.
    for channel,gain,zero,scale,limit in [('current',f['current_gain_q30'],f['current_zero_q16'],1,tol['current_A']),
                                          ('pressure',f['pressure_gain_q30'],f['pressure_zero_q16'],1000,tol['pressure_Pa'])]:
        for row in data:
            if row['channel']==channel and abs((float(row['raw'])-zero/65536)*gain/(1<<30)*scale-float(row['reference']))>limit:
                raise ValueError(channel+': PL fixed-point coefficient error exceeds reference tolerance')
    report=dict(schema='cabinet-measured-fit-v1',source=expected_source,device_id=s['device_id'],evidence_sha256=evidence,
        evidence_files_sha256=evidence_files,current=current,pressure=pressure,ppr=ppr,
        physical_closed_loop_accepted=False,physical_fault_accuracy_accepted=False,
        status='READY_FOR_COMMISSIONING_TRIAL' if not allow_fixture else 'TEST_FIXTURE_NOT_DEPLOYABLE')
    directory='/etc/cabinet/commissioned/'+evidence
    armed=copy.deepcopy(base);armed['contract'].update(feature_config_id=FEATURE_ID,calibration_id=identity,sample_mode_id=2)
    armed['contract']['input_policy']='FAULT_WINDOWS_FG_UNKNOWN_V1'
    armed['control'].update(enabled=True,qualified=True,evidence=evidence,heartbeat_ms=250,target_refresh_ms=250,
        regulation_mode='temperature',target_rpm=s['actuator']['startup_rpm'])
    armed['temperature_loop']=dict(enabled=True,qualified=True,evidence=evidence,setpoint_C=t['setpoint_C'],
        kp_rpm_per_C=t['kp_rpm_per_C'],ki_rpm_per_C_s=t['ki_rpm_per_C_s'],rpm_min=c['rpm_min'],rpm_max=c['rpm_max'],
        startup_rpm=s['actuator']['startup_rpm'],pwm_min_counts=c['duty_min'],pwm_max_counts=c['duty_max'],
        slew_rpm_per_s=t['slew_rpm_per_s'],temp_age_ms=min(c['temp_age_ms'],2000))
    armed['model'].update(backend='disabled',qualified=False,evidence=None)
    armed['model'].pop('qualification',None)
    armed['commissioning']=dict(source=expected_source,evidence_sha256=evidence,control_words=control_words,feature_words=feature_words)
    capture=dict(feature_config_id=FEATURE_ID,calibration_id=identity,pl_build_id=PL_BUILD_ID,sample_mode_id=2,
        qualified=False,input_policy='FAULT_WINDOWS_FG_UNKNOWN_V1',profile='V4-P800-Q17',coefficient_sha256=COEFFICIENT_SHA,fs=4000,adc_fs=50000,fft_size=1024,hop=512,edges=EDGES,feature_names=FEATURES)
    learning=dict(schema='cabinet-learning-v1',device_id=s['device_id'],installation_id=s['installation_id'],
                  contract=copy.deepcopy(armed['contract']),advisory_qualified=True)
    envelope=dict(schema='cabinet-parameter-envelope-v1',device_id=s['device_id'],control_evidence=evidence,temperature_evidence=evidence,
        calibration_id=identity,feature_config_id=FEATURE_ID,pl_build_id=PL_BUILD_ID,
        setpoint_C=[t['allowed_setpoint_min_C'],t['allowed_setpoint_max_C']])
    dest=Path(output);dest.mkdir(parents=True,exist_ok=False)
    for n,d in [('control.json',c),('feature.json',f),('capture-contract.json',capture),('learning.json',learning),('parameter-envelope.json',envelope),('fit-report.json',report)]:save(dest/n,d)
    socket=base.get('parameter_control',{}).get('local_socket','/run/cabinet-operator/parameter.sock')
    if type(socket) is not str or not socket.startswith('/run/cabinet-operator/') or '..' in Path(socket).parts:raise ValueError('Private operator socket required')
    armed['parameter_control']=dict(enabled=True,profile=directory+'/parameter-envelope.json',sha256=sha(dest/'parameter-envelope.json'),local_socket=socket)
    standby=copy.deepcopy(armed)
    standby['control']['enabled']=standby['temperature_loop']['enabled']=standby['parameter_control']['enabled']=False
    save(dest/'edge.armed.json',armed);save(dest/'edge.standby.json',standby)
    save(dest/'manifest.json',dict(schema='cabinet-commissioned-parameters-v1',source=expected_source,device_id=s['device_id'],
        evidence_sha256=evidence,base_config_sha256=sha(base_config),files_sha256={p.name:sha(p) for p in sorted(dest.iterdir()) if p.is_file()}))
    return dict(status=report['status'],output=str(dest),manifest_sha256=sha(dest/'manifest.json'),physical_closed_loop_accepted=False)
