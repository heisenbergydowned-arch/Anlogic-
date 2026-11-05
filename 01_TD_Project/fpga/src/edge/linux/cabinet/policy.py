"""No invented physical thresholds. PL physical causes always retain priority.

Temperature outer-loop is opt-in with qualified configuration. Models produce
maintenance evidence only; a class label cannot switch off a fan or clear PL.
"""
import math
from .protocol import elapsed32

class TemperatureLoop:
    def __init__(self,config):
        self.c=config;self.target=None;self.last=None
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
        self.integral=0.0
        self.coordination=dict(state='DISABLED',topology='SINGLE_FAN_TEMP_PI_TO_PL_RPM_PI',independent_actuators=1,physical_qualification=False)
    def update(self,status,now):
        c=self.c
        if not c.get('enabled'):return None
        raw=status['raw_words']
        healthy=(raw[0] & 0x4000) and (raw[0] & 0x1800)==0x1800 and status['mode'] in ('RUN','TRANSIENT','STARTING') \
            and not status['latched'] and status['temp_age_ms']<=c['temp_age_ms'] \
            and not set(status['active']) & {'TEMP_LOSS','CURRENT_PROTECTION_LOST','PS_LOSS','FG_LOSS'}
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
        saturation=type(pwm) is int and ((pwm>=4000 and error>0) or (pwm<=0 and error<0))
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
