"""Same-unit control comparisons from fresh FPGA feedback; no control writes."""
from collections import deque
import math
from .tracking_contract import MIN_SAMPLES, MIN_SECONDS, WINDOW_SECONDS, MAX_GAP_SECONDS, MAX_RELATIVE_ERROR, target_stable

def finite(v):return type(v) in (int,float) and math.isfinite(v)

class ControlDisplay:
    def __init__(self):self.samples=deque();self.identity=None;self.last_sample=None
    def fields(self,sample,now):
        result=dict(panel_control_schema='CASCADE_TRACKING_V2',panel_control_enabled='0',
            panel_control_target_valid='0',panel_control_target_rpm='--',panel_control_requested_rpm='--',
            panel_control_inner_target_rpm='--',panel_control_error_rpm='--',panel_control_phase='DISABLED',
            panel_control_pwm_valid='0',panel_control_pwm_percent='--',panel_control_identity='--',
            panel_control_temp_target='--',panel_control_error_pct='--',panel_control_10s_error_pct='--',
            panel_control_deadline_ms='0',panel_control_state='DISABLED',panel_control_settled='0',
            panel_temperature_pwm_present='0',panel_temperature_pwm_deadline_ms='0',
            panel_temperature_pwm_enabled='0',panel_temperature_pwm_target_valid='0',
            panel_temperature_pwm_target_percent='--',panel_temperature_pwm_state='NOT_CONFIGURED',
            panel_temperature_pwm_low_C='--',panel_temperature_pwm_high_C='--',
            panel_temperature_pwm_revision='--',panel_temperature_pwm_faults='',
            panel_temperature_pwm_alarm_level='0',panel_speed_present='0',panel_speed_state='UNKNOWN',
            panel_speed_warning_rpm='--',panel_speed_alarm_rpm='--',panel_speed_warning_hold_ms='0',
            panel_speed_elapsed_ms='0')
        st=sample['status'];control=sample.get('control',{})
        age=now-sample.get('received_at',-1e9)
        identity=(sample.get('boot'),st.get('configuration_id'))
        if identity!=self.identity:self.samples.clear();self.last_sample=None;self.identity=identity
        if sample.get('link')!='ONLINE' or not 0<=age<=1 or sample.get('frame',{}).get('state')=='REJECTED_TEST':
            self.samples.clear();return result
        result['panel_control_deadline_ms']=str(int((sample['received_at']+1)*1000))
        result['panel_control_identity']='%s/%s'%identity
        enabled=control.get('enabled') is True and (control.get('temperature_enabled') is True or control.get('regulation_mode')=='speed')
        if control.get('binding_error'):result['panel_control_state']='CONFIGURATION_RESTORE_REQUIRED'
        result['panel_control_enabled']='1' if enabled else '0'
        raw=st.get('raw_words',[])
        duty=st.get('applied_pwm_counts')
        if (len(raw)==32 and type(raw[7]) is int and type(duty) is int and 0<=duty<=4000 and raw[7]&65535==duty):
            result.update(panel_control_pwm_valid='1',panel_control_pwm_percent='%.2f'%(duty/40.))
        thermal=control.get('temperature_pwm')
        if isinstance(thermal,dict) and isinstance(thermal.get('settings'),dict):
            settings=thermal['settings']
            result.update(panel_temperature_pwm_present='1',panel_temperature_pwm_state=str(thermal.get('state','UNKNOWN')),
                panel_temperature_pwm_low_C=str(settings.get('low_C','--')),panel_temperature_pwm_high_C=str(settings.get('high_C','--')),
                panel_temperature_pwm_revision=str(settings.get('revision','--')),
                panel_temperature_pwm_faults=','.join(thermal.get('faults',[])),
                panel_temperature_pwm_alarm_level=str(thermal.get('alarm_level',0)))
            speed=thermal.get('speed_alarm',{})
            if isinstance(speed,dict) and isinstance(settings.get('speed_alarm'),dict):
                policy=settings['speed_alarm']
                result.update(panel_speed_present='1',panel_speed_state=str(speed.get('state','UNKNOWN')),
                    panel_speed_warning_rpm=str(policy['warning_rpm']),
                    panel_speed_alarm_rpm=str(settings['guards']['max_rpm']),
                    panel_speed_warning_hold_ms=str(policy['warning_hold_ms']),
                    panel_speed_elapsed_ms=str(speed.get('elapsed_ms',0)))
            observed=thermal.get('observed_at')
            if finite(observed) and 0<=now-observed<=1 and thermal.get('feedback_valid') is True:
                result['panel_temperature_pwm_deadline_ms']=str(int(min(sample['received_at']+1,observed+1)*1000))
                if thermal.get('state')=='RUNNING' and thermal.get('hardware_armed') is True:
                    result['panel_temperature_pwm_enabled']='1'
                    target=thermal.get('target_pwm_percent')
                    if finite(target) and 0<=target<=100 and thermal.get('target_source')=='FPGA_TPW1_READBACK':
                        result.update(panel_temperature_pwm_target_valid='1',panel_temperature_pwm_target_percent='%.2f'%target)
        bench=sample.get('bench')
        if isinstance(bench,dict) and bench.get('state')=='ACTIVE_BENCH_NOT_CLOSED_LOOP':
            result['panel_control_state']='BENCH_OPEN_LOOP'
        target=control.get('setpoint_C')
        if enabled and control.get('temperature_enabled') is True and finite(target) and -55<=target<=125:result['panel_control_temp_target']='%.1f'%target
        ready=(enabled and st.get('configured') is True and len(raw)==32 and raw[0]&0x300==0x300 and
               st.get('test_mode') is False and not st.get('latched') and st.get('mode') in ('STARTING','TRANSIENT','RUN'))
        request=st.get('requested_rpm');inner=st.get('ramped_rpm');rpm=st.get('measured_rpm')
        ready=ready and all(type(v) is int and 0<v<=32767 for v in (request,inner))
        if ready:
            result.update(panel_control_target_valid='1',panel_control_target_rpm=str(request),panel_control_requested_rpm=str(request),
                          panel_control_inner_target_rpm=str(inner),panel_control_phase=st['mode'],panel_control_state='TRACKING')
        elif enabled:result['panel_control_state']='WAITING_READBACK'
        rpm_valid=st.get('input_validity',{}).get('rpm') is True and finite(rpm) and rpm>=0
        if ready and rpm_valid:
            result['panel_control_error_pct']='%.2f'%(100*(rpm-request)/request)
            result['panel_control_error_rpm']='%+.0f'%(rpm-request)
        stable=(ready and rpm_valid and st['mode']=='RUN' and st.get('fan_action')=='PI' and
                not st.get('active') and abs(request-inner)<=max(1,request*.005))
        if not stable:self.samples.clear();return result
        stamp=st.get('uptime_ms')
        if stamp!=self.last_sample:
            if self.samples and now-self.samples[-1][0]>MAX_GAP_SECONDS:self.samples.clear()
            self.samples.append((now,request,abs(rpm-request)/request));self.last_sample=stamp
        while self.samples and now-self.samples[0][0]>WINDOW_SECONDS:self.samples.popleft()
        if len(self.samples)>=MIN_SAMPLES and self.samples[-1][0]-self.samples[0][0]>=MIN_SECONDS:
            targets=[r[1] for r in self.samples]
            if target_stable(targets):
                error=max(r[2] for r in self.samples)
                result['panel_control_10s_error_pct']='%.2f'%(error*100)
                result['panel_control_settled']='1' if error<MAX_RELATIVE_ERROR else '0'
                result['panel_control_state']='TRACKING_IN_TOLERANCE' if error<MAX_RELATIVE_ERROR else 'TRACKING_ERROR'
        return result
