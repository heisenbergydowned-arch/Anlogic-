"""Finite bench plans; only the existing collector thread touches BNC1 registers."""
import copy, hashlib, json, math, threading, time, uuid
from .bench_admission import require_admission,collector_identity,collector_cookie,ABI_VERSION,AUTHORIZATION
from .configuration_permission import configuration_policy
from .runtime import read_control_words

MAGIC=0x424e4331
BASE=0x900
SOURCE='REAL_USER_MEASUREMENTS'

TRIP_CAUSES=((7,'IDLE_OR_OWNER_CHANGED'),(6,'ADC_INVALID'),(5,'TEMPERATURE_INVALID'),
    (4,'CURRENT_LIMIT'),(3,'TEMPERATURE_LIMIT'),(2,'FG_OVERSPEED'),
    (1,'HARDWARE_LEASE_EXPIRED'),(0,'HARDWARE_DURATION_EXPIRED'))

def trip_evidence(flags):
    if not uint32(flags):raise ValueError('BNC1_STATUS_MALFORMED')
    mask=(flags>>24)&255;tripped=bool(flags&2)
    if flags&0x00fffff8 or (mask and not tripped):raise ValueError('BNC1_TRIP_CAUSE_INCONSISTENT')
    return dict(flags_raw=flags,tripped=tripped,cause_mask=mask,
        causes=[name for bit,name in TRIP_CAUSES if mask&(1<<bit)],
        cause_known=tripped and bool(mask),
        source='PL_LATCHED_TRIP_CAUSE' if mask else ('LEGACY_OR_UNKNOWN_TRIP_CAUSE' if tripped else 'NO_LATCHED_TRIP'))

def uint32(value):
    return type(value) is int and 0<=value<=0xffffffff

def observe_output(tracking,expected,status,profile):
    """Compare this sample with the preceding write, not the next step.

    A BNC health gate can inhibit output immediately without latching a trip.
    Plan completion therefore does not prove that PWM followed the plan.
    """
    if expected is None:return
    applied=status['applied_pwm_counts']
    tracking['samples']+=1
    if applied==expected:
        tracking['matched_samples']+=1
        return
    tracking['mismatch_samples']+=1
    conditions=[]
    raw=status['raw_words'][22]&65535;raw=raw-65536 if raw&32768 else raw
    if abs(raw-profile['current_zero_code'])>=profile['current_trip_distance_code']:conditions.append('CURRENT_RAW_LIMIT')
    if status['temp_raw_1_16_C']/16>=profile['temperature_trip_C']:conditions.append('TEMPERATURE_LIMIT')
    validity=status.get('input_validity',{})
    if validity.get('adc') is False:conditions.append('ADC_INVALID')
    if validity.get('temperature') is False:conditions.append('TEMPERATURE_INVALID')
    if status['raw_words'][24]<profile['minimum_fg_period_clocks']:conditions.append('FG_OVERSPEED')
    if expected>0 and applied==0:tracking['unexpected_zero_samples']+=1
    tracking['observed_conditions']=sorted(set(tracking['observed_conditions'])|set(conditions))
    evidence=dict(uptime_ms=status['uptime_ms'],expected_pwm_counts=expected,applied_pwm_counts=applied,
                  current_raw_code=raw,conditions=conditions)
    if tracking['first_mismatch'] is None:tracking['first_mismatch']=evidence
    tracking['last_mismatch']=evidence

def feedback_observation(status):
    """Retain raw failure evidence without serializing NaN as a real reading."""
    status=status if type(status) is dict else {}
    words=status.get('raw_words');words=words if type(words) is list else []
    def value(v):
        if v is None or type(v) in (bool,str,int):return v
        if type(v) is float and math.isfinite(v):return v
        return 'INVALID_REPRESENTATION:'+repr(v)[:100]
    validity=status.get('input_validity');validity=validity if type(validity) is dict else {}
    return dict(source='REAL_PL_STATUS_RAW',rpm_calibrated=False,
        uptime_ms=value(status.get('uptime_ms')),fg_valid=value(validity.get('rpm')),
        rpm_age_ms=value(status.get('rpm_age_ms')),
        raw_words={str(i):value(words[i]) if len(words)>i else None for i in (0,1,8,12,18,24,25)})

def feedback_contract(io,status,prepared):
    # FCB1 active configuration is a known existing register window. Its FG
    # age/range defaults also exist when configuration qualification is zero.
    words=read_control_words(io)
    if len(words)!=24 or any(not uint32(v) for v in words):raise ValueError('FG_CONFIGURATION_MALFORMED')
    age=words[14]&65535;low=max(words[21],prepared['words'][4]);high=words[22]
    if not age or not 128<=low<high:raise ValueError('FG_CONFIGURATION_INVALID')
    result=dict(configuration_id=words[1],max_age_ms=age,minimum_period_clocks=low,maximum_period_clocks=high,
                source='FCB1_ACTIVE_CONFIGURATION_READBACK',calibration_qualification_changed=False)
    require_feedback(status,result)
    return result

def require_feedback(status,contract,extra_age_ms=0):
    if type(status) is not dict:raise ValueError('FG_STATUS_MALFORMED')
    raw=status.get('raw_words')
    if type(raw) is not list or len(raw)!=32 or any(not uint32(v) for v in raw):raise ValueError('FG_STATUS_MALFORMED')
    validity=status.get('input_validity')
    if type(validity) is not dict or validity.get('rpm') is not True or not raw[0]&(1<<10):raise ValueError('FG_FEEDBACK_INVALID')
    for key,index in (('uptime_ms',1),('rpm_age_ms',12),('configuration_id',18)):
        if not uint32(status.get(key)) or status[key]!=raw[index]:raise ValueError('FG_STATUS_READBACK_MISMATCH')
    if status['configuration_id']!=contract['configuration_id']:raise ValueError('FG_CONFIGURATION_CHANGED')
    rpm=status.get('measured_rpm')
    if type(rpm) is not int or not 1<=rpm<=65535 or rpm!=raw[8]&65535:raise ValueError('FG_RPM_STATUS_INVALID')
    period=raw[24]
    if not contract['minimum_period_clocks']<=period<=contract['maximum_period_clocks']:raise ValueError('FG_PERIOD_INVALID')
    if (type(extra_age_ms) not in (int,float) or not math.isfinite(extra_age_ms) or extra_age_ms<0
            or status['rpm_age_ms']+extra_age_ms>=contract['max_age_ms']):raise ValueError('FG_FEEDBACK_STALE')
    return feedback_observation(status)

def plan(document):
    if type(document) is not dict or set(document)!={'profile','steps'}:raise ValueError('Profile and steps required')
    p=document['profile'];steps=document['steps']
    fields={'source','operator','reference_evidence_sha256','wiring_verified','zero_pwm_not_poweroff_confirmed',
            'max_duty_percent','current_zero_code','current_trip_distance_code','temperature_trip_C','minimum_fg_period_clocks','duration_limit_s'}
    if type(p) is not dict or set(p)!=fields or p['source']!=SOURCE:raise ValueError('Reviewed bench profile required')
    if not isinstance(p['operator'],str) or not 1<=len(p['operator'])<=80:raise ValueError('Operator required')
    if p['wiring_verified'] is not True or p['zero_pwm_not_poweroff_confirmed'] is not True:raise ValueError('Wiring and PWM stop behavior must be confirmed')
    pin=p['reference_evidence_sha256']
    if type(pin) is not str or len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin):raise ValueError('Pin preliminary reference measurements')
    def number(k,lo,hi):
        v=p[k]
        if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Invalid bench limit: '+k)
        return v
    duty=round(number('max_duty_percent',.025,100)*40)
    zero=number('current_zero_code',-32768,32767);current=number('current_trip_distance_code',1,65535)
    period=number('minimum_fg_period_clocks',128,2**32-1)
    if any(v!=int(v) for v in (zero,current,period)):raise ValueError('Raw limits must be integers')
    words=[duty,int(zero)&65535,int(current),round(number('temperature_trip_C',-55,125)*16)&65535,int(period),round(number('duration_limit_s',1,30)*1000)]
    if type(steps) is not list or not 1<=len(steps)<=12:raise ValueError('1..12 finite steps required')
    total=0
    for s in steps:
        if type(s) is not dict or set(s)!={'duty_percent','seconds'}:raise ValueError('Step shape')
        d,t=s['duty_percent'],s['seconds']
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (d,t)) or not 0<=d<=p['max_duty_percent'] or not .25<=t<=10:raise ValueError('Step outside limits')
        total+=t
    if total*1000>words[-1]:raise ValueError('Steps exceed absolute trial duration')
    return dict(document=copy.deepcopy(document),words=words,total_seconds=total,
        sha256=hashlib.sha256(json.dumps(document,sort_keys=True,allow_nan=False).encode()).hexdigest())


class BenchController:
    def __init__(self,service,admission_check=None):
        self.service=service;self.lock=threading.RLock();self.pending=None;self.active=None
        self.runtime_probe=None;self.probe_attempt_identity=None
        self.allow_runtime_probe=admission_check is None
        self.admission_check=admission_check or self.current_admission
        self.state=dict(state='IDLE',hardware_supported=None,records=[],controls_enabled=False,output_never_applied=True)
    def current_admission(self,identity):
        """An in-memory read-only P27 probe is bound to this collector/PL boot.

        Older firmware retains the artifact-admission path. This does not
        manufacture a deployment receipt or change calibration qualifications.
        """
        with self.lock:
            proof=self.runtime_probe
            if proof is not None and proof['collector_boot']==identity and identity==collector_identity(self.service):
                return copy.deepcopy(proof)
        return require_admission(identity)
    def _discover_p27(self,io,status):
        # Only the existing MMIO owner calls this, after its fresh FCB1/EDG1
        # status read. P27's validated initial-configuration flags identify
        # the register-map family containing the bounded BNC1 window.
        if not self.allow_runtime_probe or io is None or self.active or self.pending:
            return
        if self.service.mock or self.service.diagnostic_test or self.service.config['control']['enabled']:
            return
        identity=collector_identity(self.service)
        if self.probe_attempt_identity==identity:return
        live=self.service.public_state()
        try:
            policy=configuration_policy(status,live.get('control_words'),live.get('status_age_ms'))
        except (ValueError,KeyError,TypeError):return
        if not policy['remote_initial_configuration_ready'] or not policy['output_zero_confirmed']:
            return
        self.probe_attempt_identity=identity;self.runtime_probe=None
        try:
            cookie=collector_cookie(identity)
            if io.read(0x1050)!=cookie:raise ValueError('P27_PROBE_PL_COOKIE_CHANGED')
            magic,abi=io.read(BASE),io.read(BASE+4)
            if (magic,abi)!=(MAGIC,ABI_VERSION):raise ValueError('P27_PROBE_BNC1_ABI2_REQUIRED')
            if io.read(0x1050)!=cookie:raise ValueError('P27_PROBE_PL_COOKIE_CHANGED')
            self.runtime_probe=dict(schema='cabinet-bnc1-live-probe-v1',
                verification='READ_ONLY_P27_ABI2_CURRENT_COLLECTOR',collector_boot=identity,
                pl_boot_cookie=cookie,magic=magic,abi_version=abi,
                scope='FINITE_BENCH_ONLY',control_configuration_changed=False)
            self.state.update(hardware_supported=True,hardware_admission=copy.deepcopy(self.runtime_probe))
        except (ValueError,OSError,RuntimeError) as error:
            self.state.update(hardware_supported=False,hardware_probe_error=str(error))
    def _learning_busy(self):
        workbench=getattr(self.service,'workbench',None)
        # Normal Learning.busy reads the shared normal/labeled durable job store.
        return workbench is not None and workbench.learning.busy()
    def snapshot(self,record_limit=None):
        # Trace rows contain only immutable scalar measurements. Deep-copying
        # every scalar here made the collector's work grow with trial duration
        # on the ARM target. Keep trace copies out of the renewal critical path.
        if record_limit is not None and (type(record_limit) is not int or record_limit<0):
            raise ValueError('Nonnegative trace limit required')
        with self.lock:
            result=copy.deepcopy({k:v for k,v in self.state.items() if k!='records'})
            records=self.state['records']
            result['record_count']=len(records)
            selected=records if record_limit is None else (records[-record_limit:] if record_limit else [])
            result['records']=[dict(row) for row in selected]
            result['records_truncated']=len(selected)<len(records)
            return result
    def request_start(self,prepared,boot):
        with self.lock:
            if self.active or self.pending:raise ValueError('Bench already busy')
            if self.state.get('state')=='OUTPUT_STOP_UNCONFIRMED':raise ValueError('BENCH_PREVIOUS_OUTPUT_STOP_UNCONFIRMED')
            s=self.service.public_state()
            if self.service.mock or self.service.diagnostic_test or s.get('link')!='ONLINE' or boot!=self.service.boot:raise ValueError('Fresh real collector required')
            if self.service.config['control']['enabled']:raise ValueError('Disarm production control first')
            thermal=getattr(self.service,'temperature_pwm',None)
            if thermal and (thermal.snapshot().get('settings') or {}).get('enabled'):raise ValueError('先停用温度调速，再进行 PWM 台架试验')
            identity=uuid.uuid4().hex
            self.pending=dict(prepared=prepared,boot=boot,collector_boot=collector_identity(self.service),id=identity,requested=time.monotonic())
            self.state=dict(state='QUEUED_NOT_APPLIED',id=identity,hardware_supported=self.state.get('hardware_supported'),records=[],controls_enabled=False,output_never_applied=True)
            return self.snapshot()
    def heartbeat(self,identity):
        with self.lock:
            if not self.active or self.active['id']!=identity:raise ValueError('No matching active trial')
            self.active['heartbeat']=time.monotonic()
            return self.snapshot(record_limit=8)
    def stop(self):
        with self.lock:
            self.pending=None
            if self.active:self.active['stop']=True
            elif self.state.get('state')!='OUTPUT_STOP_UNCONFIRMED':self.state['state']='STOPPED'
            return self.snapshot()
    def lost_link(self,error):
        with self.lock:
            self.runtime_probe=None;self.probe_attempt_identity=None
            pending=self.pending
            self.pending=None
            if self.active:
                boot=self.active['boot'];self.active=None
                self.state.update(state='OUTPUT_STOP_UNCONFIRMED',reason='COLLECTOR_LINK_LOST',error=str(error),controls_enabled=False,
                                  output_stop_confirmed=False,power_disconnected=False)
                self.service.put_journal(('bench_trace',boot,copy.deepcopy(self.state)))
            elif pending:
                self.state.update(state='REJECTED',reason='COLLECTOR_LINK_LOST_BEFORE_APPLY',error=str(error),controls_enabled=False)
    def _stop_output(self,io,reason,boot,terminal):
        try:
            io.write(BASE+0x30,0)
            flags=io.read(BASE+8);duty=io.read(BASE+0x34)
            evidence=trip_evidence(flags)
            self.state['hardware_status_after_stop']=evidence
            if evidence['tripped'] or not self.state.get('hardware_trip',{}).get('tripped'):
                self.state['hardware_trip']=evidence
            if not uint32(flags) or flags&1 or duty!=0 or type(duty) is not int:
                raise RuntimeError('BENCH_STOP_READBACK_NOT_ZERO')
        except Exception as error:
            self.active=None
            self.state.update(state='OUTPUT_STOP_UNCONFIRMED',reason=reason,error=str(error),controls_enabled=False,
                              output_stop_confirmed=False,power_disconnected=False)
            self.state['journal_queued']=self.service.put_journal(('bench_trace',boot,copy.deepcopy(self.state)))
            raise
        self.active=None
        # A protection edge can occur after the poll's flags read but before
        # STOP readback. Output-zero proof alone cannot turn that into success.
        trip=self.state.get('hardware_trip',{})
        if terminal=='COMPLETED' and trip.get('tripped'):
            terminal='STOPPED'
            reason='HARDWARE_TRIP' if trip.get('cause_known') else 'HARDWARE_TRIP_OR_TIMEOUT'
        self.state.update(state=terminal,reason=reason,controls_enabled=False,output_stop_confirmed=True,
                          applied_bench_pwm_counts=0,power_disconnected=False)
        self.state['journal_queued']=self.service.put_journal(('bench_trace',boot,copy.deepcopy(self.state)))
    def poll(self,controller,status,now=None):
        # This method is invoked exclusively from Service.io_loop, after readback.
        with self.lock:
            # Timestamp after acquiring the queue lock. The status-sample
            # timestamp may predate a just-arrived start request; comparing
            # that old timestamp against the request made it look expired.
            if now is None:now=time.monotonic()
            io=getattr(controller,'io',None)
            self._discover_p27(io,status)
            capability_verified=False
            if self.pending or self.active:
                try:
                    admission=self.admission_check(collector_identity(self.service))
                    if io is None or (io.read(BASE),io.read(BASE+4))!=(MAGIC,ABI_VERSION):raise ValueError('BNC1_FIRMWARE_REQUIRED')
                    capability_verified=True
                    self.state.update(hardware_supported=True,boot_admission=admission)
                except Exception as error:
                    self.state['hardware_supported']=False
                    if self.active:
                        # No read/write to an unadmitted or unverified BNC window.
                        # The existing hardware lease is the remaining fallback.
                        self.lost_link(error)
                        self.state['output_stop_confirmed']=False
                        raise
                    self.pending=None
                    self.state.update(state='REJECTED',error=str(error),controls_enabled=False)
                    return
            if self.pending:
                item=self.pending;self.pending=None
                touched=False
                try:
                    if (type(now) not in (int,float) or not math.isfinite(now) or item['boot']!=self.service.boot
                            or item['collector_boot']!=collector_identity(self.service)
                            or not 0<=now-item['requested']<=2):raise ValueError('Start request expired')
                    if (self.service.config['control']['enabled'] or status['configured'] or status['applied_pwm_counts']!=0 or
                            status['latched']):raise ValueError('Unconfigured idle output without latched faults required')
                    if self._learning_busy():raise ValueError('WAIT_FOR_NPU_LEARNING_OR_CANCEL_IT')
                    if self.service.recorder and self.service.recorder.snapshot()['state']=='RECORDING':raise ValueError('Finish data capture first')
                    p=item['prepared']
                    self.state['last_fg_observation']=feedback_observation(status)
                    fg=feedback_contract(io,status,p)
                    self.state['feedback_contract']=fg
                    touched=True
                    self.state['output_never_applied']=False
                    io.write(BASE+0x30,0)
                    for i,w in enumerate(p['words']):io.write(BASE+0x10+4*i,w)
                    if [io.read(BASE+0x10+4*i) for i in range(6)]!=p['words']:raise ValueError('Bench profile readback mismatch')
                    io.write(BASE+0x28,0x41524d32)
                    if io.read(BASE+8)&3!=1:raise ValueError('Hardware refused bench arm')
                    self.active=dict(item,start=now,heartbeat=now,stop=False,last_stamp=None,feedback_contract=fg,
                                     status_uptime=status['uptime_ms'],status_seen_at=now)
                    self.state.update(state='ACTIVE_BENCH_NOT_CLOSED_LOOP',controls_enabled=True,plan=p['document'],started=now,boot=self.service.boot,authorization=AUTHORIZATION,local_key_required=False,
                        output_tracking=dict(samples=0,matched_samples=0,mismatch_samples=0,unexpected_zero_samples=0,
                            observed_conditions=[],first_mismatch=None,last_mismatch=None,scope='SAMPLED_READBACK_NOT_PIN_WAVEFORM'))
                except Exception as e:
                    self.state.update(state='REJECTED',error=str(e),controls_enabled=False)
                    if io is not None and capability_verified and touched:
                        self._stop_output(io,'ARM_REJECTED',item['boot'],'REJECTED')
            if not self.active:return
            a=self.active;limit=a['prepared']['total_seconds']
            reason=None
            if a['stop']:reason='OPERATOR_STOP'
            elif self.service.boot!=a['boot']:reason='BOOT_CHANGED'
            elif self._learning_busy():reason='LEARNING_TRANSACTION_STARTED'
            elif type(now) not in (int,float) or not math.isfinite(now) or now<a['status_seen_at']:reason='BENCH_CLOCK_INVALID'
            elif now-a['heartbeat']>1:reason='BROWSER_HEARTBEAT_LOST'
            else:
                flags=io.read(BASE+8);evidence=trip_evidence(flags)
                if flags&3!=1:
                    self.state['hardware_trip']=evidence
                    reason='HARDWARE_TRIP' if evidence['cause_known'] else 'HARDWARE_TRIP_OR_TIMEOUT'
                elif now-a['start']>=limit:reason='PLAN_FINISHED'
            if reason is None:
                self.state['last_fg_observation']=feedback_observation(status)
                try:
                    uptime=status.get('uptime_ms') if type(status) is dict else None
                    if not uint32(uptime):raise ValueError('FG_STATUS_MALFORMED')
                    distance=(uptime-a['status_uptime'])&0xffffffff
                    if distance>=0x80000000:raise ValueError('FG_STATUS_CLOCK_REORDERED')
                    if distance:
                        a['status_uptime']=uptime;a['status_seen_at']=now
                    require_feedback(status,a['feedback_contract'],(now-a['status_seen_at'])*1000)
                except ValueError as error:reason=str(error)
            if reason:
                self._stop_output(io,reason,a['boot'],'COMPLETED' if reason=='PLAN_FINISHED' else 'STOPPED')
                return
            if status['uptime_ms']!=a.get('tracking_stamp'):
                observe_output(self.state['output_tracking'],a.get('last_requested'),status,a['prepared']['document']['profile'])
                a['tracking_stamp']=status['uptime_ms']
            elapsed=now-a['start']
            end=0
            for i,s in enumerate(a['prepared']['document']['steps']):
                end+=s['seconds']
                if elapsed<end:break
            duty=round(s['duty_percent']*40);io.write(BASE+0x2c,duty)
            a['last_requested']=duty
            renewed=time.monotonic()
            gap=(renewed-a['last_renewed'])*1000 if a.get('last_renewed') is not None else None
            a['last_renewed']=renewed
            if gap is not None:self.state['renewal_gap_max_ms']=max(gap,self.state.get('renewal_gap_max_ms',0))
            self.state.update(step=i+1,elapsed_s=elapsed,requested_pwm_counts=duty,applied_bench_pwm_counts=io.read(BASE+0x34))
            if status['uptime_ms']!=a['last_stamp']:
                raw=status['raw_words'][22]&65535;raw=raw-65536 if raw&32768 else raw
                self.state['records'].append(dict(time_s=elapsed,step=i+1,requested_pwm_counts=duty,
                    applied_pwm_counts=status['applied_pwm_counts'],rpm=status['measured_rpm'] if status['input_validity']['rpm'] else None,
                    rpm_calibrated=False,fg_valid=status['input_validity']['rpm'],fg_period_clocks=status['raw_words'][24],current_raw_code=raw,
                    fg_pulses=status['raw_words'][25],rpm_age_ms=status['rpm_age_ms'],uptime_ms=status['uptime_ms'],
                    temperature_C=status['temp_raw_1_16_C']/16,renewal_gap_ms=gap,source=SOURCE))
                self.state['records']=self.state['records'][-1000:];a['last_stamp']=status['uptime_ms']
