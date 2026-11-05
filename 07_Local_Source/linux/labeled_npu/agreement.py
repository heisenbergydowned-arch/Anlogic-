"""Recompute V2 user-label agreement without promoting it to physical truth."""
import math
from .bundle import classify
from .core import INPUT_POLICY, LEGACY_INPUT_POLICY, validate_header, runtime_decision

SCOPE='USER_DECLARED_LABEL_AGREEMENT_NOT_PHYSICAL_CONFIRMATION_V2'
META=('input_policy','rpm_measurement_available','hardware_stall_corroborated','feedback_state','protection_window')
DECISION=('state','fault_class','model_state','model_class','reason')
FIELDS=('frame_id','inference_count','execute_ms','confidence','margin','output_u8',
        'frame_header','frame_status','collector_boot')+META+DECISION

def v2_job(job):
    policy=job.get('context',{}).get('input_contract',{}).get('input_policy')
    if policy not in (None,LEGACY_INPUT_POLICY,INPUT_POLICY):raise ValueError('LIVE_AGREEMENT_INPUT_POLICY_UNKNOWN')
    # Unversioned historical receipts keep their original, stricter public
    # class comparison. New capture/job creation always declares V2 explicitly.
    return policy==INPUT_POLICY

def checked_sample(sample,job,policy):
    if not v2_job(job):raise ValueError('V2_AGREEMENT_REQUIRES_EXPLICIT_V2_JOB')
    request=job.get('request') or {}
    if (job.get('condition_confirmed') is not True or job.get('episode_confirmed') is not True or
            job.get('label_source')!='USER_DECLARES_CURRENT_CONDITION' or
            request.get('condition_confirmed') is not True or request.get('episode_confirmed') is not True or
            request.get('label')!=job.get('label') or request.get('episode_id')!=job.get('episode_id') or
            request.get('fg_connected_confirmed',False)!=job.get('fg_connected_confirmed',False)):
        raise ValueError('LIVE_AGREEMENT_EXPLICIT_USER_LABEL_REQUIRED')
    for key,minimum in (('confidence_min',.6),('margin_min',.1)):
        value=policy.get(key) if isinstance(policy,dict) else None
        if type(value) not in (int,float) or not math.isfinite(value) or not minimum<=value<=1:
            raise ValueError('LIVE_AGREEMENT_MODEL_POLICY_REQUIRED')
    if sample.get('collector_boot')!=job['context']['collector_boot']:
        raise ValueError('LIVE_AGREEMENT_COLLECTOR_CHANGED')
    expected=job['context']['input_contract']
    header=sample.get('frame_header')
    meta=validate_header(header,sample.get('frame_status'),expected,job['label'],job.get('fg_connected_confirmed',False))
    if header[3]!=sample.get('frame_id'):raise ValueError('LIVE_AGREEMENT_FRAME_CHANGED')
    for key in META:
        if sample.get(key)!=meta[key] or type(sample.get(key)) is not type(meta[key]):
            raise ValueError('LIVE_AGREEMENT_INPUT_METADATA_CHANGED')
    computed=runtime_decision(classify(sample.get('output_u8',[]),policy),meta)
    for key in DECISION:
        if sample.get(key)!=computed[key]:raise ValueError('LIVE_AGREEMENT_DECISION_CHANGED')
    for key in ('confidence','margin'):
        value=sample.get(key)
        if type(value) not in (int,float) or not math.isfinite(value) or abs(value-computed[key])>1e-9:
            raise ValueError('LIVE_AGREEMENT_CONFIDENCE_CHANGED')
    if (type(sample.get('execute_ms')) not in (int,float) or not math.isfinite(sample['execute_ms'])
            or not 0<sample['execute_ms']<=200 or type(sample.get('inference_count')) is not int or sample['inference_count']<0):
        raise ValueError('LIVE_AGREEMENT_EXECUTION_INVALID')
    # The model class already passed the original confidence and margin.
    # A user's explicit stall episode may agree while public runtime remains
    # UNCERTAIN because FG alone cannot prove mechanical stall.
    return computed['model_state']=='CLASSIFIED' and computed['model_class']==job['label']

def snapshot(result,job,policy):
    if not v2_job(job):
        return {k:result[k] for k in ('frame_id','inference_count','execute_ms','state','fault_class','confidence')}
    sample={k:result[k] for k in FIELDS}
    checked_sample(sample,job,policy)
    return sample

def agreement(samples,job,policy=None):
    if not samples:raise ValueError('LIVE_AGREEMENT_SAMPLES_REQUIRED')
    if v2_job(job):
        matches=[checked_sample(s,job,policy) for s in samples]
        for previous,current in zip(samples,samples[1:]):
            step=(current['frame_id']-previous['frame_id'])&0xffffffff
            if not 0<step<0x80000000 or current['inference_count']<=previous['inference_count']:
                raise ValueError('LIVE_AGREEMENT_REPEATED_OR_REVERSED_FRAME')
        return sum(matches)/len(matches)
    return sum(s.get('fault_class')==job['label'] for s in samples)/len(samples)

def receipt_fields(job):
    return dict(agreement_semantics=SCOPE,input_policy=INPUT_POLICY,
                user_fg_connected_confirmed=job.get('fg_connected_confirmed',False),physical_condition_confirmed=False) if v2_job(job) else {}

def check_receipt(report,job):
    if v2_job(job):
        for key,value in receipt_fields(job).items():
            if report.get(key)!=value or type(report.get(key)) is not type(value):
                raise ValueError('LIVE_AGREEMENT_RECEIPT_SCOPE_CHANGED')
    elif report.get('agreement_semantics')==SCOPE:
        raise ValueError('V2_AGREEMENT_CANNOT_REINTERPRET_LEGACY_JOB')
