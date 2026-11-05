"""Independent first-configuration permission; never creates local KEY authority."""
import math
from cabinet.protocol import initial_configuration_flags
from . import SOURCE

REMOTE='REMOTE_INITIAL_CONFIGURATION'
LOCAL='LOCAL_MAINTENANCE'


def safe_start_values(status,control,allow_expired_owner=False):
    if any(status.get('input_validity',{}).get(k) is not True for k in ('adc','temperature')):
        raise ValueError('Current/temperature input unavailable')
    raw=status['raw_words'][22]&65535;raw=raw-65536 if raw&32768 else raw
    allowed={'CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'}
    if allow_expired_owner:allowed|={'PS_LOSS','CMD_EXPIRED'}
    if (abs(raw-control['current_zero'])>=control['current_recover'] or
            status['temp_raw_1_16_C']>=control['temp_recover'] or status['latched'] or
            set(status['active'])-allowed):
        raise ValueError('Present readings must be below recovery limits with no protection fault')


def configuration_policy(status,control_words=None,status_age_ms=None):
    """Report whether KEY is required. This does not validate a parameter package."""
    decoded=initial_configuration_flags(status.get('raw_words'))
    reason=None;initial=False
    if decoded['remote_initial_config_supported'] and decoded['initial_config_eligible']:
        raw=status['raw_words']
        if (type(status_age_ms) not in (int,float) or not math.isfinite(status_age_ms)
                or not 0<=status_age_ms<500):
            reason='INITIAL_CONFIGURATION_FRESH_STATUS_REQUIRED'
        elif (type(control_words) is not list or len(control_words)!=24 or
                any(type(v) is not int or not 0<=v<=0xffffffff for v in control_words) or
                control_words[0]!=0 or control_words[1]!=0):
            reason='INITIAL_CONFIGURATION_VIRGIN_READBACK_REQUIRED'
        elif (status.get('configured') is not False or
                any(type(status.get(k)) is not int or status[k]!=0 for k in
                    ('configuration_id','applied_pwm_counts','requested_rpm','ramped_rpm')) or
                status.get('hard_inhibit') is not True or status.get('test_mode') is not True or
                status.get('latched') or
                set(status.get('active',[]))-{'CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'} or
                raw[3] & ~((1<<16)|(1<<18)) or
                any(status.get('input_validity',{}).get(k) is not True for k in ('adc','temperature'))):
            reason='INITIAL_CONFIGURATION_IDLE_REAL_INPUTS_REQUIRED'
        else:initial=True
    elif not decoded['remote_initial_config_supported']:
        reason='LEGACY_FIRMWARE_LOCAL_KEY2_REQUIRED'
    else:reason='REMOTE_INITIAL_CONFIGURATION_NOT_ELIGIBLE'
    authority=REMOTE if initial else (LOCAL if decoded['local_permission'] else None)
    return dict(decoded,authorization=authority,local_key_required=not initial,
                remote_initial_configuration_ready=initial,reason=None if authority else reason)


def require_apply_permission(status,control_words,status_age_ms,package,active_feature=None):
    policy=configuration_policy(status,control_words,status_age_ms)
    if policy['authorization'] is None:
        raise ValueError('LOCAL_KEY2_PERMISSION_REQUIRED: '+str(policy['reason']))
    if policy['authorization']==REMOTE:
        # package is the result of deploy.check(): actual files/hash/schema and
        # measured binding have already been checked, not a browser declaration.
        from .fit import validate_control
        from .runtime import validate_binding
        unused,manifest,control,feature,armed=package
        if (type(active_feature) is not list or len(active_feature)!=17 or
                any(type(v) is not int or not 0<=v<=0xffffffff for v in active_feature)):
            raise ValueError('INITIAL_CONFIGURATION_FEATURE_READBACK_REQUIRED')
        # A prior partial transaction may already have installed this exact
        # feature package. Another qualified feature selection still needs KEY.
        if active_feature!=feature and (active_feature[1]!=0 or active_feature[2]!=0):
            if not policy['local_permission']:
                raise ValueError('LOCAL_KEY2_PERMISSION_REQUIRED: FEATURE_CONFIGURATION_ALREADY_CALIBRATED')
            return dict(policy,authorization=LOCAL,local_key_required=True,
                        remote_initial_configuration_ready=False,feature_update_requires_local_key=True)
        evidence=manifest.get('evidence_sha256')
        if (manifest.get('source')!=SOURCE or type(evidence) is not str or len(evidence)!=64 or
                any(c not in '0123456789abcdef' for c in evidence) or
                control.get('calibration_confirmed') is not True or
                control.get('calibration_evidence')!=evidence or
                control.get('qualifications')!={key:True for key in ('current','temperature','actuator','pi','vibration')}):
            raise ValueError('INITIAL_CONFIGURATION_COMPLETE_REAL_MEASUREMENTS_REQUIRED')
        words=validate_control(control)
        if (words[0]!=0x1f or type(feature) is not list or len(feature)!=17 or
                feature[2]!=1 or feature[1]!=words[1] or not feature[1]):
            raise ValueError('INITIAL_CONFIGURATION_COMPLETE_PARAMETER_BINDING_REQUIRED')
        validate_binding(armed,words,feature)
        raw=status['raw_words'];temperature=(raw[23]&65535)-(65536 if raw[23]&32768 else 0)
        if status.get('temp_raw_1_16_C')!=temperature:
            raise ValueError('INITIAL_CONFIGURATION_TEMPERATURE_READBACK_MISMATCH')
        safe_start_values(status,control)
    return policy
