"""Evaluate a scoped normal/clog model without altering the five-class registry.

All source exports retain their operator labels and frozen episode splits.
This local candidate does not select a board model or claim hardware execution.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

LABELS = ('normal', 'clog')
SPLITS = ('train', 'validation', 'test')
POLICY = dict(max_normal_false_positive_rate=.05, min_class_recall=.8,
              min_macro_f1=.85, min_coverage=.99, confidence_min=.6, margin_min=.1)


def quality(y, p):
    covered=(p.max(axis=1)>=POLICY['confidence_min']) & (np.abs(p[:, 0]-p[:, 1])>=POLICY['margin_min'])
    predictions=np.where(covered, p.argmax(axis=1), 2)
    matrix=confusion_matrix(y, predictions, labels=[0, 1, 2])[:2]
    recall=np.diag(matrix)/matrix.sum(axis=1)
    fp=float(matrix[0, 1]/matrix[0].sum())
    macro=float(f1_score(y, predictions, labels=[0, 1], average='macro', zero_division=0))
    checks=dict(normal_false_positive=fp<=POLICY['max_normal_false_positive_rate'],
                recall=bool(min(recall)>=POLICY['min_class_recall']),
                macro_f1=macro>=POLICY['min_macro_f1'], coverage=float(covered.mean())>=POLICY['min_coverage'])
    return dict(passed=all(checks.values()), checks=checks, normal_false_positive_rate=fp,
                recall=dict(zip(LABELS, recall.tolist())), macro_f1=macro,
                coverage=float(covered.mean()), rows=len(y), confusion_matrix=matrix.tolist(),
                confusion_columns=['normal', 'clog', 'rejected'])


def train(runtime, dataset, output, normal_sweeps=None):
    sys.path[:0]=[str(runtime/'host'), str(runtime/'linux')]
    from labeled_dataset import read, sha, save, load_export, common_contract, SOURCE
    manifest=read(dataset); dataset_sha=sha(dataset)
    if manifest.get('source')!=SOURCE or manifest.get('qualified') is not False or manifest.get('control_authority')!='NONE':
        raise ValueError('Real advisory corpus required')
    entries=[e for e in manifest['entries'] if e['label'] in LABELS]
    episodes={}; seen=set(); counts={l:{s:set() for s in SPLITS} for l in LABELS}
    raw={s:[] for s in SPLITS}; labels={s:[] for s in SPLITS}; sessions=[]
    for e in entries:
        sid=e['session_id']
        if sid in seen or Path(sid).name!=sid: raise ValueError('Duplicate or unsafe session')
        seen.add(sid)
        if episodes.setdefault(e['episode_id'], (e['label'],e['split']))!=(e['label'],e['split']):
            raise ValueError('Episode leakage')
        folder=Path(manifest['sessions_root'])/sid
        learning, meta, summary, values, ids=load_export(folder)
        if (sha(folder/'learning.json')!=e['learning_sha256']
                or summary['files_sha256']['frames.jsonl']!=e['frames_sha256']
                or summary['files_sha256']['session.json']!=e['session_sha256']
                or len(values)!=e['rows']
                or common_contract(learning['context']['input_contract'])!=common_contract(manifest['input_contract'])
                or learning['context']['bitstream_sha256']!=manifest['bitstream_sha256']
                or (learning['label'],learning['episode_id'],learning['episode_split'])!=(e['label'],e['episode_id'],e['split'])):
            raise ValueError('Registered source changed')
        counts[e['label']][e['split']].add(e['episode_id'])
        raw[e['split']].extend(values); labels[e['split']].extend([LABELS.index(e['label'])]*len(values))
        sessions.append(e)
    coverage={l:{s:len(v) for s,v in groups.items()} for l,groups in counts.items()}
    if any(coverage[l][s] < (2 if s=='train' else 1) for l in LABELS for s in SPLITS):
        raise ValueError('Independent train/validation/test episodes missing')
    if sha(dataset)!=dataset_sha: raise ValueError('Dataset changed during read')
    sweep_data={}; sweep_provenance={}; sweep_duties={}
    if normal_sweeps is not None:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
        from normal_sweep_dataset import load_split
        for split,name in (('train','train'),('validation','calibration'),('test','test')):
            x,ids,expected,provenance=load_split(name,None,normal_sweeps)
            for key in ('device_id','configuration_words','frame_identity','controller_diagnostic_mode'):
                if expected[key]!=manifest['input_contract'][key]:
                    raise ValueError('Normal sweep sensor contract differs: '+key)
            lookup={row['observation']['frame']['header'][3]:row['duty_percent']
                    for row in map(json.loads,(normal_sweeps/name/'observations.jsonl').read_text().splitlines())
                    if row['observation'].get('frame',{}).get('header')}
            sweep_duties[split]=np.asarray([lookup[i] for i in ids])
            sweep_data[split]=x; sweep_provenance[split]=provenance
            raw[split].extend(x.tolist());labels[split].extend([0]*len(x))
    raw={s:np.asarray(v,dtype=np.float32) for s,v in raw.items()}
    labels={s:np.asarray(v,dtype=np.int64) for s,v in labels.items()}
    scaler=StandardScaler().fit(raw['train']); data={s:scaler.transform(x) for s,x in raw.items()}
    def sweep_quality(model,split):
        if split not in sweep_data:return None
        probabilities=model.predict_proba(scaler.transform(sweep_data[split]))
        result={}
        for duty in sorted(set(sweep_duties[split])):
            part=probabilities[sweep_duties[split]==duty]
            fp=float((part[:,1]>=.6).mean());normal=float((part[:,0]>=.6).mean())
            result[str(int(duty))]=dict(rows=len(part),false_positive_rate=fp,normal_recall=normal,
                passed=fp<=.05 and normal>=.8)
        return dict(passed=all(v['passed'] for v in result.values()),by_duty=result)
    output.mkdir(parents=True, exist_ok=False)
    candidates=[]; models=[]
    for i,weight in enumerate((1.,2.,4.)):
        model=MLPClassifier(hidden_layer_sizes=(32,16),activation='relu',solver='lbfgs',
                            random_state=20261103,max_iter=1500,max_fun=30000,alpha=.1)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always',ConvergenceWarning)
            model.fit(data['train'],labels['train'],sample_weight=np.where(labels['train']==0,weight,1.))
        converged=not any(issubclass(w.category,ConvergenceWarning) for w in caught)
        result=quality(labels['validation'],model.predict_proba(data['validation']))
        sweep_result=sweep_quality(model,'validation')
        candidates.append(dict(index=i,normal_weight=weight,converged=converged,validation=result,
                               normal_pwm_validation=sweep_result))
        if converged:
            score=(result['checks']['normal_false_positive'] and result['checks']['recall']
                   and (sweep_result is None or sweep_result['passed']),
                   result['macro_f1']-2*result['normal_false_positive_rate'],min(result['recall'].values()),-i)
            models.append((score,i,model))
    if not models: raise RuntimeError('No converged candidate')
    _,selected,model=max(models,key=lambda x:x[0])
    # Selection is complete before the held-out test is evaluated.
    quality_splits={s:quality(labels[s],model.predict_proba(data[s])) for s in ('validation','test')}
    sweep_quality_splits={s:sweep_quality(model,s) for s in ('validation','test')}
    params=dict(mean=scaler.mean_,scale=scaler.scale_,classes=model.classes_)
    for i,(w,b) in enumerate(zip(model.coefs_,model.intercepts_)):
        params['weight%d'%i]=w; params['bias%d'%i]=b
    np.savez(output/'model_weights.npz',**params)
    per_episode=[]
    for e in sessions:
        _,_,_,v,_=load_export(Path(manifest['sessions_root'])/e['session_id'])
        p=model.predict_proba(scaler.transform(np.asarray(v,dtype=np.float32)))
        per_episode.append(dict(session_id=e['session_id'],label=e['label'],split=e['split'],
            rows=len(v),mean_clog_probability=float(p[:,1].mean()),
            agreement=float((p.argmax(axis=1)==LABELS.index(e['label'])).mean())))
    passed=all(q['passed'] for q in quality_splits.values()) and all(
        q is None or q['passed'] for q in sweep_quality_splits.values())
    report=dict(schema='cabinet-normal-clog-candidate-v1',
        status='PASS_SCOPED_HOST_CANDIDATE' if passed else 'FAIL_SCOPED_MODEL_QUALITY',
        source=SOURCE, trained_labels=list(LABELS), untrained_labels=['imbalance','stall','overheat'],
        dataset_sha256=dataset_sha, dataset_path=str(dataset), source_sha256=sha(Path(__file__)),
        qualified=False,control_authority='NONE',npu_executed=False,deployed=False,
        architecture=[39,32,16,1],output='binary logistic probability, not five-class logits',
        quality_scope='user-declared independent episodes at captured operating conditions only',
        policy=POLICY,coverage=coverage,rows={s:len(v) for s,v in raw.items()},
        selection=dict(selected_index=selected,candidates=candidates,split='validation',test_used=False),
        quality=quality_splits,per_episode=per_episode,sessions=sessions,
        normal_pwm_quality=sweep_quality_splits,normal_pwm_provenance=sweep_provenance,
        existing_normal_baseline_changed=False, full_classifier_readiness_changed=False,
        weights_sha256=sha(output/'model_weights.npz'))
    save(output/'training_report.json',report)
    print(json.dumps({k:report[k] for k in ('status','rows','coverage','quality','normal_pwm_quality','deployed')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True,type=Path)
    p.add_argument('--dataset',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--normal-sweeps',type=Path)
    a=p.parse_args();train(a.runtime,a.dataset,a.output,a.normal_sweeps)
