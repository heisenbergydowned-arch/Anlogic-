"""Hash-bound user-labelled advisory classifier; never formal control authority."""
import math
import re
from pathlib import Path
from normal_npu.core import FEATURES, finite, prepare as normalize
from v4_runtime.bundle import digest, loads
from .core import LABELS, INPUT_POLICY, INPUT_POLICIES

SOURCE = 'REAL_USER_DECLARED_LABELED_DIAGNOSTIC'
FILES = {'model_u8.onnx', 'normalization.json', 'policy.json', 'provenance.json', 'golden.json', 'training_validation.json'}
HARDWARE_FILES = {'model_alnpu_u8.onnx', 'alnpu_conversion.json'}
CLASSIFICATION_POLICY = dict(source='PREDECLARED_ADVISORY_ENGINEERING_GATES',confidence_min=.6,margin_min=.1)

def prepare(values, norm):
    z, encoded, clipped = normalize(values, norm)
    if clipped: raise ValueError('INPUT_OUTSIDE_QUANTIZATION_DOMAIN')
    return z, encoded

def classify(outputs, policy):
    if len(outputs) != 5 or any(type(v) is not int or not 0 <= v <= 255 for v in outputs):
        raise ValueError('INVALID_NATIVE_PROBABILITY_VECTOR')
    probabilities = [v / 255. for v in outputs]
    if abs(sum(probabilities) - 1) > .02: raise ValueError('INVALID_NATIVE_PROBABILITY_SUM')
    order = sorted(range(5), key=lambda i: probabilities[i], reverse=True)
    confidence = probabilities[order[0]]; margin = confidence - probabilities[order[1]]
    accepted = confidence >= policy['confidence_min'] and margin >= policy['margin_min']
    return dict(state='CLASSIFIED' if accepted else 'UNCERTAIN',
        fault_class=LABELS[order[0]] if accepted else None, predicted_class=LABELS[order[0]],
        probabilities=dict(zip(LABELS, probabilities)), confidence=confidence, margin=margin,
        fault_classification_qualified=False, control_authority='NONE')

def quality(labels, outputs, policy):
    """Same predeclared host gates, including uncertain/rejected windows in recall."""
    matrix=[[0]*6 for unused in LABELS]
    for label,out in zip(labels,outputs):
        result=classify(out,policy)
        predicted=LABELS.index(result['fault_class']) if result['state']=='CLASSIFIED' else 5
        matrix[LABELS.index(label)][predicted]+=1
    if any(sum(row)==0 for row in matrix): raise ValueError('ALL_TEST_CLASSES_REQUIRED')
    recalls=[]; f1=[]
    for i,row in enumerate(matrix):
        tp=row[i]; total=sum(row); predicted=sum(r[i] for r in matrix)
        recalls.append(tp/total); f1.append(2*tp/(total+predicted) if total+predicted else 0.)
    fp=sum(matrix[0][1:5])/sum(matrix[0]); coverage=1-sum(row[5] for row in matrix)/sum(sum(row) for row in matrix)
    checks=dict(normal_false_positive=fp<=.05,every_class_recall=min(recalls)>=.80,
        macro_f1=sum(f1)/5>=.85,input_coverage=coverage>=.99)
    return dict(status='PASS_ENGINEERING_QUALITY_ONLY' if all(checks.values()) else 'FAIL_MODEL_QUALITY_GATES',
        checks=checks,confusion_matrix=matrix,confusion_columns=list(LABELS)+['REJECTED_INPUT'],
        normal_false_positive_window_rate=fp,min_class_recall=min(recalls),macro_f1=sum(f1)/5,
        per_class_recall=dict(zip(LABELS,recalls)),input_coverage=coverage,qualified=False)

def validate_quality(report):
    if report.get('status')!='PASS_ENGINEERING_QUALITY_ONLY': raise ValueError('QUALITY_NOT_PASSED')
    checks=report.get('checks',{})
    if set(checks)!=set(('normal_false_positive','every_class_recall','macro_f1','input_coverage')) or any(v is not True for v in checks.values()):
        raise ValueError('QUALITY_CHECKS_INCOMPLETE')
    for key,low,high in (('normal_false_positive_window_rate',0,.05),('min_class_recall',.8,1),('macro_f1',.85,1),('input_coverage',.99,1)):
        if not finite(report.get(key)) or not low<=report[key]<=high: raise ValueError('QUALITY_METRIC_FAILED: '+key)
    recalls=report.get('per_class_recall',{})
    if set(recalls)!=set(LABELS) or any(not finite(v) or not .8<=v<=1 for v in recalls.values()):
        raise ValueError('PER_CLASS_RECALL_REQUIRED')

class Bundle:
    def __init__(self, directory, pin):
        self.root = Path(directory); self.pin = pin
        if type(pin) is not str or not re.fullmatch('[0-9a-f]{64}', pin): raise ValueError('MANIFEST_PIN_REQUIRED')
        def read(name, limit=16777216):
            p = self.root / name
            if p.is_symlink() or not p.is_file() or p.stat().st_size > limit: raise ValueError('UNSAFE_BUNDLE_ARTIFACT')
            return p.read_bytes()
        raw = read('manifest.json', 131072)
        if digest(raw) != pin: raise ValueError('MANIFEST_PIN_CHANGED')
        self.manifest = m = loads(raw.decode())
        if (m.get('schema') not in ('cabinet-real-labeled-npu-v1', 'cabinet-real-labeled-npu-v2')
                or m.get('source') != SOURCE or m.get('qualified') is not False
                or m.get('control_authority') != 'NONE' or m.get('labels') != list(LABELS)
                or m.get('input_shape') != [1,39] or m.get('output_shape') != [1,5]
                or m.get('architecture') != [39,32,16,5] or m.get('native_abi') != 3
                or m.get('execution_model') != 'ALNPU_LOGITS_PS_SOFTMAX'
                or m.get('input_policy') not in INPUT_POLICIES):
            raise ValueError('REAL_LABELED_ADVISORY_SCOPE_REQUIRED')
        required = FILES | HARDWARE_FILES if m['schema'].endswith('v2') else FILES
        if set(m.get('artifacts_sha256', {})) != required: raise ValueError('BUNDLE_INVENTORY_CHANGED')
        self.data = {}
        for name, expected in m['artifacts_sha256'].items():
            raw = read(name)
            if digest(raw) != expected: raise ValueError('BUNDLE_ARTIFACT_CHANGED: ' + name)
            self.data[name] = raw
        self.norm = n = loads(self.data['normalization.json'].decode())
        if n.get('features') != FEATURES or n.get('normalization_fitted_on') != 'train': raise ValueError('TRAIN_ONLY_NORMALIZATION_REQUIRED')
        for key in ('mean', 'scale'):
            if len(n.get(key, [])) != 39 or not all(finite(v) for v in n[key]): raise ValueError('INVALID_NORMALIZATION')
        if min(n['scale']) <= 0: raise ValueError('INVALID_NORMALIZATION_SCALE')
        for key in ('input_scale', 'logits_scale'):
            if not finite(n.get(key)) or n[key] <= 0: raise ValueError('INVALID_QUANTIZATION_SCALE')
        for key in ('input_zero_point', 'logits_zero_point'):
            if type(n.get(key)) is not int or not 0 <= n[key] <= 255: raise ValueError('INVALID_QUANTIZATION_ZERO')
        self.policy = loads(self.data['policy.json'].decode())
        if (self.policy.get('source') != 'PREDECLARED_ADVISORY_ENGINEERING_GATES'
                or self.policy.get('confidence_min') != .6 or self.policy.get('margin_min') != .1):
            raise ValueError('PREDECLARED_CLASSIFICATION_POLICY_CHANGED')
        self.provenance = p = loads(self.data['provenance.json'].decode()); self.expected = p['input_contract']
        if (p.get('source') != SOURCE or p.get('raw_capture_qualification_changed') is not False
                or self.expected.get('input_policy') != m['input_policy']): raise ValueError('PROVENANCE_SCOPE_CHANGED')
        seen = {}; counts = {l: {s:set() for s in ('train','validation','test')} for l in LABELS}
        for e in p['sessions']:
            if e['label'] not in LABELS or e['split'] not in ('train','validation','test'): raise ValueError('UNKNOWN_PROVENANCE_LABEL')
            if e['session_id'] in seen: raise ValueError('DUPLICATE_SESSION')
            seen[e['session_id']] = True
            if type(e.get('rows')) is not int or e['rows']<600: raise ValueError('INSUFFICIENT_REAL_SESSION_ROWS')
            counts[e['label']][e['split']].add(e['episode_id'])
        episodes = {}
        for e in p['sessions']:
            binding = (e['label'], e['split'])
            if episodes.setdefault(e['episode_id'], binding) != binding: raise ValueError('EPISODE_SPLIT_LEAKAGE')
        if any(len(counts[l][s]) < (2 if s == 'train' else 1) for l in LABELS for s in counts[l]):
            raise ValueError('INDEPENDENT_EPISODES_INSUFFICIENT')
        self.validation = v = loads(self.data['training_validation.json'].decode())
        if (v.get('status') != 'PASS_REAL_LABELED_ADVISORY_HOST_TRAINING' or v.get('source') != SOURCE
                or v.get('qualified') is not False or v.get('test_used_for_selection') is not False
                or any(v.get('quality', {}).get(s, {}).get('status') != 'PASS_ENGINEERING_QUALITY_ONLY' for s in ('validation','test'))):
            raise ValueError('INDEPENDENT_CLASSIFIER_QUALITY_REQUIRED')
        for split in ('validation','test'): validate_quality(v['quality'][split])
        for split in ('validation','test'):
            q=v.get('quantization',{}).get(split,{})
            checks=q.get('checks',{})
            if (set(checks)!=set(('fp32_export','class_agreement','macro_f1_degradation'))
                    or any(value is not True for value in checks.values())
                    or not finite(q.get('fp32_max_probability_error')) or not 0<=q['fp32_max_probability_error']<=1e-4
                    or not finite(q.get('class_agreement')) or not .98<=q['class_agreement']<=1
                    or not finite(q.get('macro_f1_degradation')) or not -1<=q['macro_f1_degradation']<=.02
                    or q.get('rejected_and_out_of_range_count_against_quality') is not True):
                raise ValueError('QUANTIZED_CLASSIFICATION_CONTRACT_FAILED')
        self.golden = loads(self.data['golden.json'].decode())
        vectors = self.golden.get('vectors', [])
        if (self.golden.get('source') != SOURCE or len(vectors) != 160
                or any(sum(v.get('label') == l for v in vectors) != 32 for l in LABELS)
                or any(v.get('split') != 'test' for v in vectors)):
            raise ValueError('BALANCED_REAL_TEST_GOLDENS_REQUIRED')

    def hardware_model(self):
        if self.manifest['schema'] != 'cabinet-real-labeled-npu-v2': raise ValueError('HARDWARE_CONVERSION_REQUIRED')
        c = loads(self.data['alnpu_conversion.json'].decode())
        if (c.get('schema') != 'cabinet-labeled-alnpu-half-lsb-bias-v1'
                or c.get('source_model_sha256') != digest(self.data['model_u8.onnx'])
                or c.get('hardware_model_sha256') != digest(self.data['model_alnpu_u8.onnx'])
                or c.get('reference_unchanged') is not True or c.get('trained_weights_unchanged') is not True):
            raise ValueError('HARDWARE_CONVERSION_CHANGED')
        return self.data['model_alnpu_u8.onnx']
