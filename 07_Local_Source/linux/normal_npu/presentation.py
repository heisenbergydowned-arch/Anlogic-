"""Display a fresh real NPU advisory without granting model/control qualification."""
import json
import math
import os
from pathlib import Path
import re
import stat
from .core import GROUPS,REFERENCE_GROUPS,finite,validate_context,LIVE_FRAME_MAX_AGE_MS,LIVE_FRAME_MAX_AGE_S
from .advisory import panel_fields as advisory_fields

RESULT=Path('/run/cabinet-normal-npu/state.json')

def fields(sample,now,path=RESULT,os_boot=None,clock=None):
    result={'panel_nn_present':'0','panel_nn_valid':'0','panel_nn_state':'WAITING_INPUT',
            'panel_nn_reason':'SERVICE_RESULT_UNAVAILABLE',
            'panel_nn_score':'--','panel_nn_latency_ms':'--','panel_nn_deadline_ms':'0',
            'panel_nn_count':'0','panel_nn_training_rows':'0',
            'panel_nn_reference_eligible':'0',
            'panel_nn_assessment':'UNAVAILABLE','panel_nn_input_clipped':'0',
            'panel_ref_valid':'0','panel_ref_score':'--','panel_ref_deadline_ms':'0',
            'panel_ref_sessions':'0','panel_ref_total_rows':'0'}
    for group in GROUPS:result['panel_nn_group_'+group]='--'
    for group in REFERENCE_GROUPS:result['panel_ref_group_'+group]='--'
    result.update(advisory_fields({}))
    try:
        fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022 or info.st_size>32768:
                return result
            with os.fdopen(fd,'r',closefd=False) as stream:d=json.load(stream)
        finally:os.close(fd)
        # The NPU may publish while this subscriber is processing its packet.
        # Production checks against a clock sampled after the atomic file read;
        # an explicitly supplied now remains available for deterministic replay.
        if clock is not None:now=clock()
        if (type(d) is not dict or d.get('schema')!='cabinet-normal-npu-live-v1' or d.get('backend')!='Alnpu' or
                d.get('model_source')!='REAL_USER_DECLARED_NORMAL_DIAGNOSTIC' or
                d.get('formal') is not False or d.get('control_authority')!='NONE' or
                d.get('fault_classes_trained')!=[]):return result
        result['panel_nn_model_sha256']=str(d.get('model_sha256',''))
        if sample.get('feature_words')!=d.get('input_contract',{}).get('configuration_words'):return result
        result['panel_nn_present']='1'
        result['panel_nn_state']=d.get('status','WAITING_INPUT')
        if type(d.get('inference_count')) is int and d['inference_count']>=0:
            result['panel_nn_count']=str(d['inference_count'])
        if os_boot is None:os_boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if d.get('os_boot_id')!=os_boot:
            result['panel_nn_reason']='RESULT_BOOT_CHANGED';return result
        if not finite(d.get('updated_at')) or not 0<=now-d['updated_at']<=LIVE_FRAME_MAX_AGE_S:
            result['panel_nn_reason']='RESULT_EXPIRED';return result
        if not d.get('valid') or d.get('status')!='RUNNING':
            result['panel_nn_reason']=str(d.get('reason') or d.get('status','WAITING_INPUT'));return result
        validate_context(sample,now,d['input_contract'],result=d,allow_temperature_pwm=True)
        if d.get('collector_boot')!=sample.get('boot') or sample.get('link')!='ONLINE':return result
        if not finite(d.get('received_at')) or not 0<=now-d['received_at']<=LIVE_FRAME_MAX_AGE_S:
            result['panel_nn_reason']='FRAME_STALE';return result
        st=sample.get('status',{})
        if any(st.get('input_validity',{}).get(k) is not True for k in ('rpm','adc','temperature','pressure')):return result
        if type(st.get('uptime_ms')) is not int or type(d.get('frame_end_ms')) is not int:return result
        frame_age_ms=(st['uptime_ms']-d['frame_end_ms'])&0xffffffff
        if frame_age_ms>LIVE_FRAME_MAX_AGE_MS:return result
        # Preserve the acquisition time. Republishing a result or a newer
        # status packet cannot give an old FPGA frame another full second.
        deadline=min(d['received_at']+LIVE_FRAME_MAX_AGE_S,
                     d['updated_at']+LIVE_FRAME_MAX_AGE_S,
                     sample['received_at']+(LIVE_FRAME_MAX_AGE_MS-frame_age_ms)/1000.)
        if 'input_deadline' in d:
            if not finite(d['input_deadline']) or not d['received_at']<=d['input_deadline']<=d['received_at']+LIVE_FRAME_MAX_AGE_S:return result
            deadline=min(deadline,d['input_deadline'])
        if now>=deadline:
            result['panel_nn_reason']='FRAME_STALE';return result
        if d.get('source')!='REAL_CURRENT_SENSOR_FRAME' or d.get('quality',0)&~0x3000:return result
        if not finite(d.get('score')) or not 0<=d['score']<=1000000:return result
        if not finite(d.get('execute_ms')) or not 0<d['execute_ms']<=200:return result
        groups=d.get('group_scores',{})
        if set(groups)!=set(GROUPS) or not all(finite(x) and x>=0 for x in groups.values()):return result
        if d.get('state') not in ('BASELINE_MATCH','BASELINE_DEVIATION'):return result
        neural=min(max(groups.values()),1000000.)
        outside=(finite(d.get('domain_score')) and d['domain_score']>1) or d.get('input_clipped',0)>0
        result.update(panel_nn_valid='1',panel_nn_reason='',panel_nn_state=d['state'],panel_nn_score='%.2f'%neural,
            panel_nn_assessment='OUTSIDE_TRAINING_DOMAIN' if outside else ('NEURAL_DEVIATION' if neural>1 else 'NORMAL_RECONSTRUCTION_MATCH'),
            panel_nn_input_clipped=str(d.get('input_clipped',0)),
            panel_nn_latency_ms='%.2f'%d['execute_ms'],panel_nn_deadline_ms=str(int(deadline*1000)),
            panel_nn_count=str(int(d['inference_count'])),panel_nn_training_rows=str(int(d['training_rows'])))
        result['panel_nn_reference_eligible']='0' if d.get('baseline_eligible') is False else '1'
        if d.get('baseline_eligible') is False:result['panel_nn_assessment']='OUTSIDE_OPERATING_REFERENCE'
        for n,v in groups.items():result['panel_nn_group_'+n]='%.2f'%v
        result.update(advisory_fields(d))
        reference=d.get('reference_group_scores',{})
        if (d.get('reference_kind')=='TRAIN_NORMALIZED_INPUT_RANGE_V1' and
                set(reference)==set(REFERENCE_GROUPS) and
                all(finite(v) and 0<=v<=1000000 for v in reference.values()) and
                finite(d.get('domain_score')) and abs(d['domain_score']-max(reference.values()))<=1e-6 and
                type(d.get('reference_session_count')) is int and 3<=d['reference_session_count']<=999 and
                type(d.get('reference_total_rows')) is int and d['reference_total_rows']>=d['training_rows']>0):
            result.update(panel_ref_valid='1',panel_ref_score='%.2f'%d['domain_score'],
                          panel_ref_deadline_ms=result['panel_nn_deadline_ms'],
                          panel_ref_sessions=str(d['reference_session_count']),panel_ref_total_rows=str(d['reference_total_rows']))
            for n,v in reference.items():result['panel_ref_group_'+n]='%.2f'%v
        return result
    except (OSError,ValueError,TypeError,KeyError,OverflowError) as error:
        result['panel_nn_reason']=str(error) if isinstance(error,ValueError) else type(error).__name__
        return result
