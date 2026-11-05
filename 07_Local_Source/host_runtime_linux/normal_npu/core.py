"""Shared, bounded live-input and normal-reference scoring contracts."""
import math
import struct
from cabinet.alarm_only import advisory_filtered_active

FEATURES = ([kind+'_a_'+axis for kind in ('rms','pp','kurt') for axis in 'xyz']
            + ['banda'+str(i) for i in range(8)]
            + [kind+'_b_'+axis for kind in ('rms','pp','kurt') for axis in 'xyz']
            + ['bandb'+str(i) for i in range(8)]
            + ['ratio_ab','current','temp','pressure','rpm'])
GROUPS = {'a':list(range(17))+[34], 'b':list(range(17,34))+[34],
          'current':[35], 'temperature':[36], 'airflow':[37,38]}
REFERENCE_GROUPS = {'amplitude': list(range(6)) + list(range(17, 23)),
                    'spectrum': list(range(6, 17)) + list(range(23, 34)),
                    'ratio': [34], 'process': list(range(35, 39))}
PL_BUILD=0x202610f7
ALLOWED_DIAGNOSTIC_QUALITY=0x3000
# The real-frame input and its read-only advisory share one bounded lifetime.
# This does not change protection, output ownership, or model qualification.
LIVE_FRAME_MAX_AGE_MS=1000
LIVE_FRAME_MAX_AGE_S=LIVE_FRAME_MAX_AGE_MS/1000.
PWM_REFERENCE = dict(schema='cabinet-user-normal-pwm-reference-v1',
    duty_nodes_percent=list(range(0,101,10)),
    source='THREE_REAL_USER_DECLARED_NORMAL_PWM_SWEEPS',steady_only=True)

def has_pwm_reference(expected):
    reference=expected.get('pwm_operating_reference')
    if reference is None:return False
    if reference!=PWM_REFERENCE:raise ValueError('PWM_REFERENCE_CONTRACT_INVALID')
    return True

def finite(value):
    return type(value) in (int,float) and math.isfinite(value)

def collector_observation(document):
    """Accept the collector's explicit offline envelope without inventing data."""
    if type(document) is not dict or 'observation' not in document:
        raise ValueError('COLLECTOR_MALFORMED')
    observation=document['observation']
    if observation is None:
        display=document.get('display')
        if (type(display) is not dict or display.get('link')!='ERROR' or
                type(display.get('message')) is not str or not display['message']):
            raise ValueError('COLLECTOR_MALFORMED')
        if display['message']=='COLLECTOR_STALE':raise ValueError('COLLECTOR_STALE')
        # A PL restart, protection transition or subscriber failure is not a
        # freshness timeout and must not enter bounded learning auto-recovery.
        raise ValueError('COLLECTOR_OFFLINE_REQUIRES_REVIEW: '+display['message'])
    if type(observation) is not dict:raise ValueError('COLLECTOR_MALFORMED')
    return observation

def fp32(value):
    return struct.unpack('<f',struct.pack('<f',value))[0]

def validate_header(header,status,expected):
    if (type(header) is not list or len(header)!=32 or
            any(type(x) is not int or not 0<=x<=0xffffffff for x in header)):
        raise ValueError('FRAME_HEADER_MISSING')
    if header[:3]!=[0x46524d31,0x10000,284] or header[26]!=PL_BUILD:
        raise ValueError('PL_IDENTITY_CHANGED')
    if header[27] or header[15]&0x4000:
        raise ValueError('TEST_FRAME_REJECTED')
    if header[15]&~ALLOWED_DIAGNOSTIC_QUALITY:
        raise ValueError('SENSOR_OR_WINDOW_INVALID')
    if [header[16],header[17],header[18]]!=expected['frame_identity']:
        raise ValueError('FEATURE_OR_CALIBRATION_CHANGED')
    if header[11:13]!=[1024,1024] or header[21]!=100000000:
        raise ValueError('WINDOW_CONTRACT_CHANGED')
    if any(not x or not 3880<=1023*header[21]/x<=4120 for x in header[9:11]):
        raise ValueError('SAMPLE_RATE_INVALID')
    if type(status) is not dict or status.get('mode')!=expected['controller_mode']:
        raise ValueError('OPERATING_MODE_OUTSIDE_REFERENCE')
    # The controller's diagnostic/inhibit mode does not mean synthetic FRM1.
    # Both are recorded separately and this model never grants qualification.
    if bool(status.get('test_mode'))!=expected['controller_diagnostic_mode']:
        raise ValueError('CONTROLLER_PROFILE_CHANGED')
    if any(status.get('input_validity',{}).get(k) is not True
           for k in ('rpm','adc','temperature','pressure')):
        raise ValueError('PROCESS_SENSOR_INVALID')
    if advisory_filtered_active(status)-{'CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'} or status.get('latched'):
        raise ValueError('HARDWARE_FAULT_ACTIVE')
    uptime=status.get('uptime_ms')
    if type(uptime) is not int or ((uptime-header[4])&0xffffffff)>LIVE_FRAME_MAX_AGE_MS:
        raise ValueError('FRAME_STALE')

def validate_reference_guard(o,expected,result=None):
    from cabinet.normal_reference_guard import (SCHEMA, HALF, MASK, uint32,
        output_reason, bench_reason, window_start, require_after_boundary)
    status=o['status']
    reason=output_reason(status,require_zero=expected['controller_diagnostic_mode'] is True)
    if reason:raise ValueError(reason)
    reason=bench_reason(o.get('bench'))
    if reason:raise ValueError(reason)
    guard=o.get('normal_reference_guard')
    if (type(guard) is not dict or guard.get('schema')!=SCHEMA or guard.get('boot')!=o['boot']
            or not uint32(guard.get('status_uptime_ms'))
            or guard.get('status_uptime_ms')!=status['uptime_ms']
            or guard.get('bench_id')!=o['bench'].get('id')
            or guard.get('bench_state')!=o['bench'].get('state')):
        raise ValueError('REFERENCE_RECOVERY_BOUNDARY_UNAVAILABLE')
    if guard.get('state')!='IDLE':
        raise ValueError(guard.get('reason') or 'REFERENCE_WAIT_FULL_POST_TRIAL_WINDOW')
    boundary=guard.get('safe_since_uptime_ms')
    if not uint32(boundary) or ((status['uptime_ms']-boundary)&MASK)>=HALF:
        raise ValueError('REFERENCE_RECOVERY_BOUNDARY_UNAVAILABLE')
    frame=o.get('frame')
    if type(frame) is dict and frame.get('state')=='RECEIVED_REAL':
        require_after_boundary(window_start(frame.get('header'),status['uptime_ms']),boundary,status['uptime_ms'])
    if result is not None:
        if result.get('collector_boot')!=o['boot']:
            raise ValueError('REFERENCE_RESULT_BOOT_CHANGED')
        require_after_boundary(result.get('frame_start_cycles'),boundary,status['uptime_ms'])
        end=result.get('frame_end_ms')
        if (not uint32(end) or ((end-(result['frame_start_cycles']//100000))&MASK)>=HALF
                or ((status['uptime_ms']-end)&MASK)>LIVE_FRAME_MAX_AGE_MS):
            raise ValueError('REFERENCE_RESULT_WINDOW_INVALID')

def validate_temperature_pwm_context(o,now,result=None,baseline_eligible=False):
    """Allow inference on real TPW1 data without extending the learned baseline."""
    from cabinet.normal_reference_guard import SCHEMA,uint32,bench_reason,window_start
    status=o['status'];guard=o.get('normal_reference_guard');bench=o.get('bench')
    reason=bench_reason(bench)
    if reason:raise ValueError(reason)
    if (type(guard) is not dict or guard.get('schema')!=SCHEMA or
            guard.get('boot')!=o['boot'] or guard.get('status_uptime_ms')!=status.get('uptime_ms') or
            guard.get('bench_id')!=bench.get('id') or guard.get('bench_state')!=bench.get('state') or
            guard.get('state')!='BLOCKED' or guard.get('reason')!='OUTPUT_OUTSIDE_REFERENCE'):
        raise ValueError('REFERENCE_RECOVERY_BOUNDARY_UNAVAILABLE')
    control=o.get('control')
    c=control.get('temperature_pwm') if type(control) is dict else None
    settings=c.get('settings') if type(c) is dict else None
    if type(c) is not dict or type(settings) is not dict:raise ValueError('TEMPERATURE_PWM_CONTEXT_INVALID')
    duty=status.get('applied_pwm_counts');revision=settings.get('revision')
    if (not uint32(duty) or duty>4000 or type(status.get('hard_inhibit')) is not bool or
            status.get('requested_rpm')!=0 or c.get('state')!='RUNNING' or
            any(c.get(k) is not True for k in ('hardware_supported','hardware_armed','feedback_valid')) or
            c.get('target_source')!='FPGA_TPW1_READBACK' or settings.get('enabled') is not True or
            type(revision) is not int or c.get('applied_revision')!=revision or
            not finite(c.get('observed_at')) or not 0<=now-c['observed_at']<=LIVE_FRAME_MAX_AGE_S or
            not finite(c.get('deadline_ms')) or now*1000>=c['deadline_ms'] or
            not finite(c.get('actual_pwm_percent')) or not 0<=c['actual_pwm_percent']<=100 or
            abs(c['actual_pwm_percent']-duty/40.)>.026):
        raise ValueError('TEMPERATURE_PWM_CONTEXT_INVALID')
    frame=o.get('frame')
    if type(frame) is dict and frame.get('state')=='RECEIVED_REAL':
        window_start(frame.get('header'),status['uptime_ms'])
    reference='SAVED_BASELINE_CONTEXT' if baseline_eligible else 'TEMPERATURE_PWM_OUTSIDE_BASELINE'
    if result is not None and (result.get('collector_boot')!=o['boot'] or
            result.get('baseline_eligible') is not baseline_eligible or
            result.get('operating_reference')!=reference):
        raise ValueError('RESULT_OPERATING_REFERENCE_MISMATCH')

def validate_context(o,now,expected,result=None,allow_temperature_pwm=False):
    from cabinet.icm_display import display_fields
    from cabinet.feature_display import verified_sensor_pair_deadline
    if type(o) is not dict:raise ValueError('COLLECTOR_MALFORMED')
    if o.get('link')!='ONLINE' or not finite(o.get('received_at')) or not 0<=now-o['received_at']<=1:
        raise ValueError('COLLECTOR_STALE')
    if o.get('feature_words')!=expected['configuration_words']:
        raise ValueError('CONFIGURATION_CHANGED')
    if not isinstance(o.get('boot'),str) or not o['boot'].startswith(expected['device_id']+'/'):
        raise ValueError('BOARD_IDENTITY_CHANGED')
    status=o.get('status',{})
    if type(status) is not dict:raise ValueError('STATUS_MALFORMED')
    baseline_eligible=True
    try:validate_reference_guard(o,expected,result)
    except ValueError as error:
        if not allow_temperature_pwm or str(error)!='OUTPUT_OUTSIDE_REFERENCE':raise
        baseline_eligible=has_pwm_reference(expected)
        validate_temperature_pwm_context(o,now,result,baseline_eligible=baseline_eligible)
    if status.get('mode')!=expected['controller_mode'] or bool(status.get('test_mode'))!=expected['controller_diagnostic_mode']:
        raise ValueError('OPERATING_MODE_OUTSIDE_REFERENCE')
    if any(status.get('input_validity',{}).get(k) is not True for k in ('rpm','adc','temperature','pressure')):
        raise ValueError('PROCESS_SENSOR_INVALID')
    if advisory_filtered_active(status)-{'CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'} or status.get('latched'):
        raise ValueError('HARDWARE_FAULT_ACTIVE')
    frame=o.get('frame')
    if type(frame) is not dict or frame.get('state') not in ('RECEIVED_REAL','EMPTY'):
        raise ValueError('TEST_OR_INVALID_FRAME_SOURCE')
    if frame['state']=='RECEIVED_REAL':validate_header(frame.get('header'),status,expected)
    sensor_fields=display_fields(o.get('icm_diagnostics'),now,o['received_at'],o['boot'])
    if not verified_sensor_pair_deadline(sensor_fields,now):
        raise ValueError('INDEPENDENT_ICM_PAIR_INVALID')
    return baseline_eligible

def live_input(document,now,expected,allow_temperature_pwm=False):
    o=collector_observation(document)
    eligible=validate_context(o,now,expected,allow_temperature_pwm=allow_temperature_pwm)
    frame=o.get('frame')
    if type(frame) is not dict or frame.get('state')!='RECEIVED_REAL':
        raise ValueError('NO_NEW_REAL_FRAME')
    h=frame.get('header');validate_header(h,o.get('status'),expected)
    values=frame.get('values',{})
    x=[values.get(n) for n in FEATURES]
    if not all(finite(v) for v in x):raise ValueError('NONFINITE_OR_MISSING_FEATURE')
    identity={'collector_boot':o['boot'],'frame_id':h[3], 'frame_end_ms':h[4],
              'frame_start_cycles':h[5] | (h[6]<<32),
              'input_deadline':o['received_at']+(LIVE_FRAME_MAX_AGE_MS-((o['status']['uptime_ms']-h[4])&0xffffffff))/1000.,
              'received_at':o['received_at'],'quality':h[15],
              'control_mode':o['status']['mode'],'calibration_id':h[17]}
    if allow_temperature_pwm:
        identity.update(baseline_eligible=eligible,
            operating_reference='SAVED_BASELINE_CONTEXT' if eligible else 'TEMPERATURE_PWM_OUTSIDE_BASELINE',
            applied_pwm_percent=o['status']['applied_pwm_counts']/40.)
    return x,identity

def prepare(values,norm):
    if len(values)!=39 or not all(finite(v) for v in values):raise ValueError('INVALID_FEATURE_VECTOR')
    z=[fp32(fp32(fp32(v)-m)/s) for v,m,s in zip(values,norm['mean'],norm['scale'])]
    raw=[round(fp32(fp32(v/norm['input_scale'])+norm['input_zero_point'])) for v in z]
    clipped=sum(v<0 or v>255 for v in raw)
    return z,bytes(max(0,min(255,v)) for v in raw),clipped

def reconstruction_errors(z,outputs,norm):
    if len(outputs)!=39:raise ValueError('WRONG_RECONSTRUCTION_SIZE')
    recon=[fp32((int(q)-norm['output_zero_point'])*norm['output_scale']) for q in outputs]
    return {name:math.sqrt(sum((z[i]-recon[i])**2 for i in indices)/len(indices))
            for name,indices in GROUPS.items()}

def score(z,outputs,norm,thresholds,clipped=0):
    errors=reconstruction_errors(z,outputs,norm)
    groups={n:errors[n]/thresholds['group_rmse'][n] for n in GROUPS}
    domain_values=[abs(v)/limit for v,limit in zip(z,thresholds['abs_z_limit'])]
    reference={name:max(domain_values[i] for i in indices) for name,indices in REFERENCE_GROUPS.items()}
    domain=max(reference.values())
    overall=max([domain]+list(groups.values())+[1.01 if clipped else 0])
    neural=max(groups.values())
    return {'score':min(overall,1000000.),'threshold':1.,'group_scores':groups,
            'neural_score':min(neural,1000000.),
            'assessment':'OUTSIDE_TRAINING_DOMAIN' if domain>1 or clipped else ('NEURAL_DEVIATION' if neural>1 else 'NORMAL_RECONSTRUCTION_MATCH'),
            'domain_score':domain,'input_clipped':clipped,
            'reference_kind':'TRAIN_NORMALIZED_INPUT_RANGE_V1','reference_group_scores':reference,
            'state':'BASELINE_MATCH' if overall<=1 else 'BASELINE_DEVIATION',
            'fault_class':None,'fault_classification_qualified':False}
