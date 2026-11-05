"""Display only fresh hardware classifier results; no control qualification."""
import json
import os
from pathlib import Path
import stat
from normal_npu.core import finite
from cabinet.icm_display import display_fields
from cabinet.feature_display import verified_sensor_pair_deadline
from .core import LABELS, INPUT_POLICY, validate_header, runtime_decision
from .bundle import CLASSIFICATION_POLICY, classify

RESULT=Path('/run/cabinet-labeled-npu/state.json')
NAMES=dict(normal='正常',imbalance='失衡',stall='卡死',clog='堵塞',overheat='过热')


def fields(sample, now, path=RESULT, os_boot=None, clock=None):
    result={}
    try:
        fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022 or info.st_size>32768:
                return result
            with os.fdopen(fd,'r',closefd=False) as stream:d=json.load(stream)
        finally:os.close(fd)
        if clock is not None:now=clock()
        if (type(d) is not dict or d.get('schema')!='cabinet-labeled-npu-live-v1' or
                d.get('backend')!='Alnpu' or d.get('model_source')!='REAL_USER_DECLARED_LABELED_DIAGNOSTIC' or
                d.get('formal') is not False or d.get('qualified') is not False or
                d.get('control_authority')!='NONE' or d.get('labels')!=list(LABELS)):
            return result
        if os_boot is None:os_boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if d.get('os_boot_id')!=os_boot:return result
        # A stopped old classifier must not hide a currently running normal AE.
        if d.get('status')=='STOPPED':return result
        result=dict(panel_classifier_present='1',panel_classifier_valid='0',panel_classifier_deadline_ms='0',
                    panel_model_valid='0',panel_model_state='MODEL_UNAVAILABLE',
                    panel_model_note='没有新鲜的真实模型结果',panel_nn_present='0',panel_nn_valid='0',
                    panel_ref_valid='0',panel_nn_assessment='UNAVAILABLE')
        for label in LABELS:result['panel_prob_'+label]='--'
        if (not finite(d.get('updated_at')) or not 0<=now-d['updated_at']<=.5 or
                not finite(d.get('received_at')) or not 0<=now-d['received_at']<=.5 or
                d.get('valid') is not True or d.get('status')!='RUNNING' or
                d.get('source')!='REAL_CURRENT_SENSOR_FRAME'):
            return result
        expected=d['input_contract']
        if (sample.get('link')!='ONLINE' or sample.get('boot')!=d.get('collector_boot') or
                sample.get('feature_words')!=expected.get('configuration_words') or
                not sample['boot'].startswith(expected['device_id']+'/') or
                not finite(sample.get('received_at')) or not 0<=now-sample['received_at']<=.5):
            return result
        frame=sample.get('frame') or {}
        if frame.get('state') not in ('RECEIVED_REAL','EMPTY'):return result
        if frame['state']=='RECEIVED_REAL':
            validate_header(frame.get('header'),sample.get('status'),expected)
        sf=display_fields(sample.get('icm_diagnostics'),now,sample['received_at'],sample['boot'])
        if not verified_sensor_pair_deadline(sf,now):return result
        header=d.get('frame_header')
        meta=validate_header(header,sample.get('status'),expected)
        if header[3]!=d.get('frame_id') or header[4]!=d.get('frame_end_ms') or header[15]!=d.get('quality'):
            return result
        if ((sample['status']['uptime_ms']-header[4])&0xffffffff)>500:return result
        probabilities=d.get('probabilities',{})
        if (set(probabilities)!=set(LABELS) or not all(finite(v) and 0<=v<=1 for v in probabilities.values()) or
                abs(sum(probabilities.values())-1)>.02 or not finite(d.get('confidence')) or
                abs(d['confidence']-max(probabilities.values()))>1e-6 or
                not finite(d.get('execute_ms')) or not 0<d['execute_ms']<=200):
            return result
        label=d.get('fault_class')
        if d.get('state') not in ('CLASSIFIED','UNCERTAIN'):return result
        if d['state']=='CLASSIFIED' and (label not in LABELS or probabilities[label]!=max(probabilities.values())):return result
        if d['state']=='UNCERTAIN' and label is not None:return result
        if expected.get('input_policy')==INPUT_POLICY:
            # Recompute public uncertainty from the actual quantized result and
            # current sensor metadata. A forged/stale confirmed label cannot
            # turn missing FG into a confirmed fault or a healthy indication.
            checked=runtime_decision(classify(d.get('output_u8',[]),CLASSIFICATION_POLICY),meta)
            if any(d.get(k)!=v for k,v in meta.items()):return result
            if any(d.get(k)!=checked[k] for k in ('model_state','model_class','state','fault_class','predicted_class','reason')):return result
            if any(not finite(d.get(k)) or abs(d[k]-checked[k])>1e-6 for k in ('confidence','margin')):return result
            if any(abs(probabilities[k]-checked['probabilities'][k])>1e-6 for k in LABELS):return result
        result.update(panel_classifier_valid='1',panel_model_valid='1',
                      panel_classifier_deadline_ms=str(int((min(d['received_at'],d['updated_at'])+.5)*1000)),
                      panel_classifier_label=label or 'uncertain',
                      panel_model_state='实推理' if label else '未确认',
                      panel_model_note='%s %.1f%% | %.2fms | 仅诊断'%(NAMES.get(label,'未确认'),d['confidence']*100,d['execute_ms']))
        if expected.get('input_policy')==INPUT_POLICY and not meta['rpm_measurement_available']:
            result['panel_model_note']='%s%s · FG未知 | %.2fms'%(NAMES.get(d.get('model_class') or d.get('predicted_class'),'未确认'),
                '候选' if not label else '',d['execute_ms'])
        for name,value in probabilities.items():result['panel_prob_'+name]='%.2f'%(100*value)
        return result
    except (OSError,ValueError,TypeError,KeyError,OverflowError):return result
