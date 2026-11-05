"""Inspect train/calibration input coverage before any independent-test capture.

This is a fixed engineering triage policy, not a fault detector or proof that a
changed condition is abnormal. It never fits a model, reads a test capture,
or chooses new limits from calibration observations. Coverage does not remove
or relabel rows; the trainer's existing invalid-window exclusions stay explicit.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

if __package__:
    from .utf8_io import configure_stdio
    from .train_normal import FEATURES,load_split,prepare,save
else:
    from utf8_io import configure_stdio
    from train_normal import FEATURES,load_split,prepare,save

SCHEMA='cabinet-normal-calibration-input-check-v1'
FILES=('learning.json','sessions.json')+tuple(
    'captures/'+split+'/'+name for split in ('train','calibration')
    for name in ('session.json','feature_contract.json','frames.jsonl','summary.json'))


def policy():
    return dict(schema='cabinet-normal-calibration-input-policy-v1',
        normalization_fitted_on='train',quantization_range_fitted_on='train',
        minimum_input_abs_range=8.,train_abs_range_multiplier=1.25,
        domain_minimum_abs_z=5.,domain_train_feature_max_multiplier=1.5,
        maximum_clipped_window_fraction=.05,maximum_outside_domain_window_fraction=.05,
        maximum_transient_consecutive_clipped_fraction=.02,
        severe_peak_minimum_abs_z=32.,severe_peak_train_max_multiplier=4.,
        maximum_additional_calibration_captures_per_job=2,
        retry_budget_enforced_by='collector_job_and_worker',
        mild_isolated_clipping_requires_retry=False,
        test_read=False,model_scores_used=False,rows_removed_or_relabeled=0,
        existing_invalid_window_policy='UNCHANGED_TRAINER_DIAGNOSTIC_FILTER',
        limitations=['input coverage triage is not fault classification',
                     'a distribution change may reflect a legitimate new condition',
                     'passing this check does not predict model quality or holdout acceptance'])


def source_hashes(root):
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in FILES}


def fit_input_range(train):
    """Keep the trainer's train-only float32 normalizer and symmetric U8 range."""
    if train.ndim!=2 or train.shape[1]!=39 or len(train)<512 or not np.isfinite(train).all():
        raise ValueError('INVALID_TRAIN_INPUT')
    mean=train.mean(0).astype(np.float32)
    floors=np.asarray(([.0001]*6+[.05]*3+[.01]*8)*2+[.05,.005,1.,2/65536,20.],dtype=np.float32)
    scale=np.maximum(train.std(0),floors).astype(np.float32)
    normalized=((train-mean)/scale).astype(np.float32)
    if not np.isfinite(normalized).all() or not np.isfinite(mean).all() or not np.isfinite(scale).all():
        raise ValueError('NONFINITE_TRAIN_NORMALIZATION')
    peak=float(np.max(np.abs(normalized)))
    limit=max(8.,peak*1.25)
    norm=dict(features=FEATURES,mean=mean.tolist(),scale=scale.tolist(),
              normalization_fitted_on='train',input_scale=float(np.float32(2*limit/255)),input_zero_point=128)
    domain=np.maximum(5.,np.max(np.abs(normalized),axis=0)*1.5).tolist()
    return norm,domain,peak,limit


def input_statistics(values,norm,domain):
    if values.ndim!=2 or values.shape[1]!=39 or len(values)<512 or not np.isfinite(values).all():
        raise ValueError('INVALID_CALIBRATION_INPUT')
    maxima=[0.]*39;clipped_rows=clipped_values=outside=run=longest=0
    for value in values:
        z,_,clipped=prepare(value.tolist(),norm)
        if not all(np.isfinite(z)):
            raise ValueError('NONFINITE_NORMALIZED_INPUT')
        maxima=[max(old,abs(float(v))) for old,v in zip(maxima,z)]
        clipped_rows+=clipped>0;clipped_values+=clipped
        outside+=any(abs(v)>limit for v,limit in zip(z,domain))
        run=run+1 if clipped else 0;longest=max(longest,run)
    peak=max(range(39),key=lambda i:maxima[i]);count=len(values)
    return dict(rows=count,input_clipped_rows=clipped_rows,input_clipped_values=clipped_values,
                input_clipped_window_fraction=clipped_rows/count,
                outside_train_domain_rows=outside,outside_train_domain_window_fraction=outside/count,
                longest_consecutive_clipped_windows=longest,
                longest_consecutive_clipped_fraction=longest/count,
                maximum_abs_z=maxima[peak],maximum_abs_z_feature=FEATURES[peak],
                rows_removed_or_relabeled=0)


def inspect_arrays(train,calibration):
    rules=policy();norm,domain,train_peak,limit=fit_input_range(train)
    train_quality=input_statistics(train,norm,domain)
    cal_quality=input_statistics(calibration,norm,domain)
    severe=max(rules['severe_peak_minimum_abs_z'],rules['severe_peak_train_max_multiplier']*train_peak)
    review=(cal_quality['input_clipped_window_fraction']>rules['maximum_clipped_window_fraction'] or
            cal_quality['outside_train_domain_window_fraction']>rules['maximum_outside_domain_window_fraction'] or
            cal_quality['longest_consecutive_clipped_fraction']>rules['maximum_transient_consecutive_clipped_fraction'])
    transient=(cal_quality['input_clipped_rows']>0 and cal_quality['maximum_abs_z']>severe)
    if review:
        status='REVIEW_CONDITION_REQUIRED';reason='CALIBRATION_DISTRIBUTION_REVIEW_REQUIRED'
    elif transient:
        status='RETRY_CALIBRATION_TRANSIENT';reason='CALIBRATION_TRANSIENT_INPUT_COVERAGE'
    else:
        status='PASS_CALIBRATION_INPUT_QUALITY';reason='CALIBRATION_INPUT_COVERAGE_ACCEPTABLE'
    return dict(schema=SCHEMA,status=status,reason_code=reason,policy=rules,test_read=False,
                model_scores_used=False,data_quality=dict(train=train_quality,calibration=cal_quality),
                train_fitted_input_range=dict(symmetric_abs_limit=limit,input_scale=norm['input_scale'],
                    input_zero_point=norm['input_zero_point'],maximum_abs_z=train_peak,
                    severe_peak_abs_z_threshold=severe,feature_domain_abs_z_limits=domain),
                rows_removed_or_relabeled=0,qualified=False)


def inspect_capture(root):
    sources=source_hashes(root)
    train,_,contract,train_meta=load_split('train',None,root,True)
    calibration,_,_,cal_meta=load_split('calibration',contract,root,True)
    if train_meta['session_id']==cal_meta['session_id']:
        raise ValueError('TRAIN_CALIBRATION_SESSION_OVERLAP')
    if train_meta['boot_id']!=cal_meta['boot_id']:
        raise ValueError('TRAIN_CALIBRATION_BOOT_CHANGED')
    if not train_meta['last_frame']<cal_meta['first_frame']<cal_meta['last_frame']:
        raise ValueError('TRAIN_CALIBRATION_FRAME_ORDER_CHANGED')
    report=inspect_arrays(train,calibration)
    for split,meta in (('train',train_meta),('calibration',cal_meta)):
        report['data_quality'][split].update(raw_rows=meta['raw_rows'],
            existing_invalid_window_exclusions=len(meta['excluded_windows']))
    if sources!=source_hashes(root):
        raise ValueError('CAPTURE_CHANGED_DURING_CHECK')
    report.update(source_sha256=sources,input_contract=contract,
                  sessions=dict(train=train_meta,calibration=cal_meta))
    return report


def main():
    configure_stdio()
    parser=argparse.ArgumentParser()
    parser.add_argument('--capture-root',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:
        report=inspect_capture(args.capture_root)
    except (AssertionError,OSError,ValueError,TypeError,KeyError,OverflowError) as error:
        report=dict(schema=SCHEMA,status='REJECTED_CAPTURE_CONTRACT',reason_code='CAPTURE_CONTRACT_REJECTED',
                    error=type(error).__name__+': '+str(error),policy=policy(),test_read=False,
                    model_scores_used=False,rows_removed_or_relabeled=0,qualified=False)
        save(args.output/'report.json',report)
        print(json.dumps(report,ensure_ascii=False),flush=True)
        raise SystemExit(1)
    save(args.output/'report.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
