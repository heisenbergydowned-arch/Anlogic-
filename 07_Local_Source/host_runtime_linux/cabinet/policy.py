"""No invented physical thresholds. PL physical causes always retain priority.

Temperature outer-loop is opt-in with qualified configuration. Models produce
maintenance evidence only; a class label cannot switch off a fan or clear PL.
"""
import math
from .protocol import elapsed32

class TemperatureLoop:
    def __init__(self,config):
        self.c=config;self.target=None;self.last=None;self.started=False
        if config.get('enabled'):
            required=['setpoint_C','kp_rpm_per_C','ki_rpm_per_C_s','rpm_min','rpm_max','slew_rpm_per_s','temp_age_ms']
            if config.get('qualified') is not True or not config.get('evidence'):
                raise ValueError('Temperature loop needs qualified configuration and evidence')
            if any(type(config.get(k)) not in (int,float) or not math.isfinite(config[k]) for k in required):
                raise ValueError('Missing/invalid temperature loop coefficients')
            if not 0<config['rpm_min']<config['rpm_max']<=32767 or config['slew_rpm_per_s']<=0:
                raise ValueError('Temperature loop RPM/slew bounds')
            if not -55<=config['setpoint_C']<=125 or config['kp_rpm_per_C']<0 or config['ki_rpm_per_C_s']<0 or not 0<config['temp_age_ms']<=60000:
                raise ValueError('Temperature loop gain/setpoint/age bounds')
            if config.get('startup_rpm') is not None and (type(config['startup_rpm']) is not int or not config['rpm_min']<=config['startup_rpm']<=config['rpm_max']):
                raise ValueError('Commissioned startup RPM must be within the operating envelope')
            low,high=config.get('pwm_min_counts',0),config.get('pwm_max_counts',4000)
            if type(low) is not int or type(high) is not int or not 0<=low<high<=4000:
                raise ValueError('Temperature anti-windup requires the actual PL duty limits')
        self.integral=0.0
        self.coordination=dict(state='DISABLED',topology='SINGLE_FAN_TEMP_PI_TO_PL_RPM_PI',independent_actuators=1,physical_qualification=False)
    def update(self,status,now):
        c=self.c
        if not c.get('enabled'):return None
        raw=status['raw_words']
        mode=status['mode']
        blocked={'TEMP_LOSS','CURRENT_PROTECTION_LOST','PS_LOSS'}
        if mode!='STARTING':blocked.add('FG_LOSS')
        healthy=(raw[0] & 0x4000) and (raw[0] & 0x1800)==0x1800 \
            and not status['latched'] and status['temp_age_ms']<=c['temp_age_ms'] \
            and not set(status['active']) & blocked
        if not healthy:
            self.target=None;self.last=None;self.integral=0
            self.coordination=dict(state='INPUT_OR_PROTECTION_INVALID',topology='SINGLE_FAN_TEMP_PI_TO_PL_RPM_PI',independent_actuators=1,physical_qualification=False)
            return None
        if type(now) not in (int,float) or not math.isfinite(now) or (self.last is not None and now<self.last):
            self.target=None;self.last=None;self.integral=0;return None
        if self.last is not None and now-self.last>2:self.target=None;self.last=None;self.integral=0
        dt=0 if self.last is None else min(max(now-self.last,0),1)
        temperature=status['temp_raw_1_16_C']/16
        error=temperature-c['setpoint_C'];p=c['kp_rpm_per_C']*error
        action=status.get('fan_action')
        # A qualified owner must seed the first target: PI-only updates cannot
        # leave READY_OFF. A local manual lease and hardware alarms still win.
        if (not self.started and c.get('startup_rpm') is not None and
                mode in ('READY_OFF','STOPPING','FALLBACK') and
                (mode=='FALLBACK' or (status.get('requested_rpm')==0 and status.get('applied_pwm_counts')==0))
                and raw[0]&0x200 and not raw[0]&0x40 and
                not set(status['active'])-{'STOP_UNCONFIRMED','CMD_EXPIRED'}):
            self.started=True
            self.target=c['startup_rpm'];self.integral=self.target-c['rpm_min']-p;self.last=now
            self.coordination=dict(state='STARTUP_REQUEST',topology='SINGLE_FAN_TEMP_PI_TO_PL_RPM_PI',
                independent_actuators=1,outer_target_rpm=self.target,physical_qualification=False)
            return self.target
        if mode not in ('RUN','TRANSIENT','STARTING'):
            self.target=None;self.last=None;self.integral=0
            self.coordination=dict(state='PL_PRIORITY_OUTER_ABSTAINS',pl_action=action,physical_qualification=False)
            return None
        self.started=True
        if mode=='STARTING' and action=='STARTUP':
            requested=status.get('requested_rpm')
            if type(requested) is not int or not c['rpm_min']<=requested<=c['rpm_max']:return None
            # Keep the target lease alive through the full startup timeout.
            # Integrator tracking makes the subsequent PI handoff bumpless.
            self.target=requested;self.integral=requested-c['rpm_min']-p;self.last=now
            self.coordination=dict(state='STARTUP_TRACKING',topology='SINGLE_FAN_TEMP_PI_TO_PL_RPM_PI',
                independent_actuators=1,outer_target_rpm=requested,physical_qualification=False)
            return requested
        if action in ('BOOST','LIMIT'):
            requested=status.get('requested_rpm')
            if type(requested) is not int or not c['rpm_min']<=requested<=c['rpm_max']:
                self.target=None;self.last=None;self.integral=0;return None
            self.target=requested;self.integral=requested-c['rpm_min']-p;self.last=now
            self.coordination=dict(state='PL_OVERRIDE_TRACKING',pl_action=action,topology='SINGLE_FAN_TEMP_PI_TO_PL_RPM_PI',
                independent_actuators=1,physical_qualification=False,outer_target_rpm=requested,physical_output_confirmed=False)
            return requested
        if action!='PI':
            self.target=None;self.last=None;self.integral=0
            self.coordination=dict(state='PL_PRIORITY_OUTER_ABSTAINS',pl_action=action,physical_qualification=False)
            return None
        if self.target is None:
            self.target=max(c['rpm_min'],min(c['rpm_max'],status['requested_rpm'] or status['measured_rpm'] or c['rpm_min']))
            self.integral=self.target-c['rpm_min']-p
        pwm=status.get('applied_pwm_counts')
        saturation=type(pwm) is int and ((pwm>=c.get('pwm_max_counts',4000) and error>0) or
                                        (pwm<=c.get('pwm_min_counts',0) and error<0))
        candidate=self.integral if saturation else self.integral+c['ki_rpm_per_C_s']*error*dt
        u=c['rpm_min']+p+candidate
        if not ((u>=c['rpm_max'] and error>0) or (u<=c['rpm_min'] and error<0)):self.integral=candidate
        desired=max(c['rpm_min'],min(c['rpm_max'],c['rpm_min']+p+self.integral))
        limit=c['slew_rpm_per_s']*dt
        self.target=max(self.target-limit,min(self.target+limit,desired));self.last=now
        self.coordination=dict(state='INNER_SATURATION_INTEGRAL_HELD' if saturation else 'CASCADE_TRACKING',
            topology='SINGLE_FAN_TEMP_PI_TO_PL_RPM_PI',independent_actuators=1,outer_target_rpm=int(round(self.target)),
            inner_measured_rpm=status.get('measured_rpm'),inner_pwm_counts=pwm,physical_qualification=False)
        return int(round(self.target))

class FixedRpmLoop:
    """Measured speed commissioning uses the same PL PI and protection owner."""
    def __init__(self,config,target):
        # Validate the same measured actuator/temperature envelope; fixed speed
        # does not create a second PWM controller or replace hardware limits.
        if config.get('enabled') is not True:raise ValueError('Measured control envelope must be enabled')
        TemperatureLoop(config)
        if type(target) is not int or not config['rpm_min']<=target<=config['rpm_max']:
            raise ValueError('Fixed RPM target must be within the measured envelope')
        self.c=dict(config);self.target_rpm=target;self.target=None;self.last=None;self.integral=0;self.started=False
        self.coordination=dict(state='SPEED_READY',topology='FIXED_TARGET_TO_PL_RPM_PI',physical_qualification=False)
    def update(self,status,now):
        raw=status.get('raw_words',[]);mode=status.get('mode');active=set(status.get('active',[]))
        healthy=(len(raw)==32 and raw[0]&0x4000 and raw[0]&0x1800==0x1800 and raw[0]&0x200 and not raw[0]&0x40
            and not status.get('latched') and status.get('temp_age_ms',1e9)<=self.c['temp_age_ms']
            and not active&{'TEMP_LOSS','CURRENT_PROTECTION_LOST','PS_LOSS','OC_HARD','TEMP_HARD','OVERSPEED','VIB_HARD','STALL_CORROBORATED'})
        allowed=mode in ('READY_OFF','STOPPING','FALLBACK','STARTING','TRANSIENT','RUN')
        if mode!='STARTING' and 'FG_LOSS' in active:healthy=False
        if mode in ('READY_OFF','STOPPING','FALLBACK') and active-{'STOP_UNCONFIRMED','CMD_EXPIRED'}:healthy=False
        if mode in ('READY_OFF','STOPPING','FALLBACK') and self.started:healthy=False
        if not healthy or not allowed or type(now) not in (int,float) or not math.isfinite(now):
            self.coordination=dict(state='INPUT_OR_PROTECTION_INVALID',topology='FIXED_TARGET_TO_PL_RPM_PI',physical_qualification=False)
            return None
        self.target=self.target_rpm;self.last=now;self.started=True
        self.coordination=dict(state='SPEED_TRACKING',topology='FIXED_TARGET_TO_PL_RPM_PI',outer_target_rpm=self.target_rpm,
            inner_measured_rpm=status.get('measured_rpm'),inner_pwm_counts=status.get('applied_pwm_counts'),physical_qualification=False)
        return self.target_rpm

class Fusion:
    def __init__(self,config):
        if not 0<config.get('confidence_min',0.8)<=1 or type(config.get('confirm_ms',2000)) is not int or not 1<=config.get('confirm_ms',2000)<=60000 or type(config.get('max_gap_ms',500)) is not int or not 1<=config.get('max_gap_ms',500)<=5000:
            raise ValueError('Model confidence/confirmation interval bounds')
        self.c=config;self.candidate=None;self.since=None;self.last_result_ms=None
    def reset(self):self.candidate=None;self.since=None;self.last_result_ms=None
    def evaluate(self,result,status,now_ms,*,formal=False):
        # Only evidence from this accepted new frame extends result lifetime.
        physical_level=status['alarm_level'];physical=status['active']+status['latched']
        if result is None:
            self.reset()
            return dict(level=physical_level,reason='model_unavailable',model_state='UNAVAILABLE',physical_causes=physical,
                        buzzer_requested=False,fan_action=status['fan_action'])
        if self.last_result_ms is not None and elapsed32(now_ms,self.last_result_ms)>self.c.get('max_gap_ms',500):
            self.reset() # Missing inference intervals cannot extend confirmation.
        label=result['label'];confidence=result['confidence']
        rejected=result.get('diagnostic_state') in ('REJECTED_CONFIDENCE','REJECTED_MARGIN')
        if rejected or confidence<self.c.get('confidence_min',0.8):
            self.reset();model_state=result.get('diagnostic_state') if rejected else 'REJECTED_CONFIDENCE';model_level=0
        elif not formal:
            self.reset();model_level=0
            model_state='TEST_OBSERVATION' if result.get('test') else 'OBSERVATION_UNQUALIFIED'
        elif label=='normal':
            if self.candidate!='normal':self.candidate='normal';self.since=now_ms
            confirmed=elapsed32(now_ms,self.since)>=self.c.get('confirm_ms',2000)
            model_state='NORMAL_OBSERVATION' if confirmed else 'NORMAL_CANDIDATE';model_level=0
        else:
            if self.candidate!=label:self.candidate=label;self.since=now_ms
            confirmed=elapsed32(now_ms,self.since)>=self.c.get('confirm_ms',2000)
            model_state='CONFIRMED_MAINTENANCE' if confirmed else 'CANDIDATE'
            model_level=1 if confirmed else 0
        self.last_result_ms=now_ms
        return dict(level=max(physical_level,model_level),reason=label,model_state=model_state,
                    physical_causes=physical,buzzer_requested=False,
                    fan_action=status['fan_action'])
