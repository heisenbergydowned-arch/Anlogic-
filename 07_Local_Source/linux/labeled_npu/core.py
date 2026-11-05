"""Real labelled diagnostic inputs, distinct from the normal AE and formal REAL gates.

An absent FG is unknown, never measured zero. V2 separates the operator's
training declaration from runtime uncertainty; V1 retains its original gates.
"""
import struct
from cabinet.alarm_only import advisory_filtered_active
from normal_npu.core import FEATURES, PL_BUILD, finite, collector_observation
from cabinet.input_policy import MISSING_RPM
from fcb1_client import MODES

LABELS = ('normal', 'imbalance', 'stall', 'clog', 'overheat')
LEGACY_INPUT_POLICY = 'LABELED_DIAGNOSTIC_FG_UNKNOWN_V1'
INPUT_POLICY = 'LABELED_USER_GROUNDTRUTH_FG_UNKNOWN_V2'
INPUT_POLICIES = frozenset((LEGACY_INPUT_POLICY, INPUT_POLICY))
BASE_FLAGS = {'CONFIG_UNQUALIFIED', 'STOP_UNCONFIRMED'}
LABEL_FLAGS = {
    'normal': set(),
    'imbalance': {'VIB_WARN', 'VIB_HARD', 'TRACK_ERROR'},
    'stall': {'FG_LOSS', 'STALL_CORROBORATED', 'CURRENT_HIGH', 'OC_HARD', 'TRACK_ERROR'},
    'clog': {'CURRENT_HIGH', 'TRACK_ERROR'},
    'overheat': {'TEMP_WARN', 'TEMP_HARD'},
}

def _flags(status, label):
    if label is not None and label not in LABELS: raise ValueError('UNKNOWN_CONDITION_LABEL')
    active, latched = status.get('active'), status.get('latched')
    if (type(active) is not list or type(latched) is not list or
            any(type(v) is not str for v in active+latched)):
        raise ValueError('FAULT_STATUS_MALFORMED')
    allowed = BASE_FLAGS | (set().union(*LABEL_FLAGS.values()) if label is None else LABEL_FLAGS[label])
    if (advisory_filtered_active(status)|set(latched))-allowed: raise ValueError('FAULT_OUTSIDE_DECLARED_CONDITION')
    if set(latched) & BASE_FLAGS: raise ValueError('UNEXPECTED_LATCHED_BASE_FLAG')
    return set(active)|set(latched)

def validate_header(header, status, expected, label=None, fg_connected_confirmed=False):
    if (type(header) is not list or len(header) != 32 or
            any(type(v) is not int or not 0 <= v <= 0xffffffff for v in header)):
        raise ValueError('FRAME_HEADER_MISSING')
    if header[:3] != [0x46524d31, 0x10000, 284] or header[26] != PL_BUILD:
        raise ValueError('PL_IDENTITY_CHANGED')
    if header[27] or header[15]&0x4000: raise ValueError('TEST_FRAME_REJECTED')
    policy = expected.get('input_policy')
    if policy not in INPUT_POLICIES: raise ValueError('INPUT_POLICY_CHANGED')
    if [header[16],header[17],header[18]] != expected['frame_identity']:
        raise ValueError('FEATURE_OR_CALIBRATION_CHANGED')
    if header[11:13] != [1024,1024] or header[21] != 100000000 or header[20] != 4000 or header[22] != 50000:
        raise ValueError('WINDOW_CONTRACT_CHANGED')
    if any(not x or not 3880 <= 1023*header[21]/x <= 4120 for x in header[9:11]):
        raise ValueError('SAMPLE_RATE_INVALID')
    if type(status) is not dict: raise ValueError('STATUS_MALFORMED')
    modes = expected.get('allowed_controller_modes', [expected.get('controller_mode')])
    if status.get('mode') not in modes or status.get('mode') not in MODES:
        raise ValueError('OPERATING_MODE_OUTSIDE_REFERENCE')
    if header[19] != MODES.index(status['mode']): raise ValueError('FRAME_STATUS_MODE_MISMATCH')
    if type(status.get('test_mode')) is not bool or status['test_mode'] != expected['controller_diagnostic_mode']:
        raise ValueError('CONTROLLER_PROFILE_CHANGED')
    valid = status.get('input_validity', {})
    if any(valid.get(k) is not True for k in ('adc','temperature','pressure')):
        raise ValueError('PROCESS_SENSOR_INVALID')
    if not header[13]&0xffff or not header[13]>>16: raise ValueError('PROCESS_COUNT_INVALID')
    if header[24] > 2000: raise ValueError('TEMPERATURE_STALE')
    flags = _flags(status, label)
    hardware_stall = 'STALL_CORROBORATED' in status['active']
    if policy == LEGACY_INPUT_POLICY and label == 'stall' and 'STALL_CORROBORATED' not in flags:
        raise ValueError('PHYSICAL_STALL_NOT_CORROBORATED_BY_HARDWARE')
    missing = bool(header[15]&0x0800)
    if missing:
        if header[14] != 0 or valid.get('rpm') is not False:
            raise ValueError('FG_UNKNOWN_METADATA_INCONSISTENT')
        if policy == LEGACY_INPUT_POLICY:
            if (label not in (None,'stall') or 'STALL_CORROBORATED' not in flags or
                    (label == 'stall' and fg_connected_confirmed is not True)):
                raise ValueError('FG_UNKNOWN_NOT_CORROBORATED_STALL')
        elif label not in (None,'stall'):
            raise ValueError('FG_UNKNOWN_NOT_ALLOWED_FOR_LABEL')
    elif header[14] == 0 or valid.get('rpm') is not True:
        raise ValueError('FG_INPUT_INVALID')
    if policy == INPUT_POLICY and label == 'stall':
        # Learning.start and the independent host loader verify explicit current
        # condition/episode declarations before supplying this training label.
        if fg_connected_confirmed is not True:
            raise ValueError('CONFIRM_STALL_FG_PHYSICALLY_CONNECTED')
        if not missing and not hardware_stall:
            raise ValueError('STALL_LABEL_REQUIRES_FG_UNKNOWN_OR_CURRENT_CORROBORATION')
    if header[15] & ~(0x3000 | (0x0800 if missing else 0)):
        raise ValueError('SENSOR_OR_WINDOW_INVALID')
    uptime=status.get('uptime_ms')
    if type(uptime) is not int or not 0 <= uptime <= 0xffffffff or ((uptime-header[4])&0xffffffff)>1000:
        raise ValueError('FRAME_STALE')
    return dict(rpm_measurement_available=not missing,
                feedback_state='FG_UNKNOWN_NOT_MEASURED_ZERO' if missing else 'FG_OBSERVED',
                input_policy=policy, hardware_stall_corroborated=hardware_stall,
                protection_window=header[19] in (7,8))

def runtime_decision(model_result, input_meta):
    """Pure public decision; never turn unknown feedback into a measured stall.

    model_result is the unchanged output of bundle.classify. The model's
    accepted class remains available for explicitly scoped label agreement,
    while the public fault_class can remain unconfirmed. No control authority.
    """
    if type(model_result) is not dict or type(input_meta) is not dict:
        raise ValueError('RUNTIME_INPUT_METADATA_INVALID')
    policy=input_meta.get('input_policy')
    available=input_meta.get('rpm_measurement_available')
    corroborated=input_meta.get('hardware_stall_corroborated')
    if (type(policy) is not str or policy not in INPUT_POLICIES or type(available) is not bool or type(corroborated) is not bool
            or type(input_meta.get('protection_window')) is not bool
            or input_meta.get('feedback_state') != ('FG_OBSERVED' if available else 'FG_UNKNOWN_NOT_MEASURED_ZERO')):
        raise ValueError('RUNTIME_INPUT_METADATA_INVALID')
    state=model_result.get('state');label=model_result.get('fault_class')
    if (state not in ('CLASSIFIED','UNCERTAIN') or
            (state=='CLASSIFIED' and label not in LABELS) or (state=='UNCERTAIN' and label is not None)
            or model_result.get('predicted_class') not in LABELS
            or model_result.get('control_authority')!='NONE'
            or model_result.get('fault_classification_qualified') is not False):
        raise ValueError('MODEL_DECISION_SCOPE_INVALID')
    result=dict(model_result,model_state=state,model_class=label,
                reason=None if state=='CLASSIFIED' else 'MODEL_CONFIDENCE_OR_MARGIN_NOT_MET')
    if policy==INPUT_POLICY and not available and not corroborated:
        result.update(state='UNCERTAIN',fault_class=None,
            reason='STALL_CANDIDATE_FG_UNCONFIRMED' if label=='stall' else 'FG_UNKNOWN_UNCONFIRMED')
    return result

def _values(values, header):
    if len(values) != 39 or not all(finite(v) for v in values): raise ValueError('NONFINITE_OR_MISSING_FEATURE')
    if values[38] < 0 or values[38] > 32767: raise ValueError('RAW_RPM_OUT_OF_RANGE')
    result=list(values)
    if header[15]&0x0800: result[38]=MISSING_RPM
    elif result[38] == 0: raise ValueError('ZERO_RPM_IS_NOT_AN_OBSERVED_FG_MEASUREMENT')
    return result

def feature_values(header, feature_words, status, expected, label=None, fg_connected_confirmed=False):
    validate_header(header,status,expected,label,fg_connected_confirmed)
    if (type(feature_words) is not list or len(feature_words) != 39 or
            any(type(v) is not int or not 0 <= v <= 0xffffffff for v in feature_words)):
        raise ValueError('FEATURE_WORDS_INVALID')
    return _values(struct.unpack('<39f',struct.pack('<39I',*feature_words)),header)

def live_input(document, now, expected, label=None, fg_connected_confirmed=False):
    from cabinet.icm_display import display_fields
    from cabinet.feature_display import verified_sensor_pair_deadline
    o=collector_observation(document)
    if o.get('link') != 'ONLINE' or not finite(o.get('received_at')) or not 0 <= now-o['received_at'] <= 1:
        raise ValueError('COLLECTOR_STALE')
    if o.get('feature_words') != expected['configuration_words']: raise ValueError('CONFIGURATION_CHANGED')
    if not isinstance(o.get('boot'),str) or not o['boot'].startswith(expected['device_id']+'/'):
        raise ValueError('BOARD_IDENTITY_CHANGED')
    sf=display_fields(o.get('icm_diagnostics'),now,o['received_at'],o['boot'])
    if not verified_sensor_pair_deadline(sf,now): raise ValueError('INDEPENDENT_ICM_PAIR_INVALID')
    frame=o.get('frame') or {}
    if frame.get('state') == 'EMPTY': raise ValueError('NO_NEW_REAL_FRAME')
    if frame.get('state') != 'RECEIVED_REAL': raise ValueError('TEST_OR_INVALID_FRAME_SOURCE')
    h=frame.get('header');meta=validate_header(h,o.get('status'),expected,label,fg_connected_confirmed)
    values=_values([frame.get('values',{}).get(n) for n in FEATURES],h)
    meta.update(collector_boot=o['boot'],frame_id=h[3],frame_end_ms=h[4],received_at=o['received_at'],
                quality=h[15],control_mode=o['status']['mode'],calibration_id=h[17])
    return values,meta
