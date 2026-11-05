"""Hash-bound normal-only model, with no path into formal classification."""
import hashlib
import math
from pathlib import Path
from v4_runtime.bundle import loads
from .core import FEATURES,GROUPS,finite,has_pwm_reference

FILES={'model_u8.onnx','normalization.json','thresholds.json','provenance.json','golden.json'}
HARDWARE_FILES={'model_alnpu_u8.onnx','alnpu_conversion.json'}
def digest(data):return hashlib.sha256(data).hexdigest()

class Bundle:
    def __init__(self,directory,pin):
        self.root=Path(directory)
        p=self.root/'manifest.json'
        if p.is_symlink() or not p.is_file() or p.stat().st_size>131072:raise ValueError('Unsafe manifest')
        raw=p.read_bytes()
        if digest(raw)!=pin:raise ValueError('Model manifest hash mismatch')
        self.manifest=loads(raw.decode());m=self.manifest
        if (m.get('schema') not in ('cabinet-real-normal-npu-v1','cabinet-real-normal-npu-v2') or
                m.get('source')!='REAL_USER_DECLARED_NORMAL_DIAGNOSTIC' or
                m.get('qualified') is not False or m.get('fault_classes_trained')!=[] or
                m.get('control_authority')!='NONE' or m.get('input_shape')!=[1,39] or
                m.get('output_shape')!=[1,39] or m.get('architecture')!=[39,32,16,39]):
            raise ValueError('Normal-only scope mismatch')
        required=FILES|HARDWARE_FILES if m['schema'].endswith('v2') else FILES
        if set(m.get('artifacts_sha256',{}))!=required:raise ValueError('Incomplete model bundle')
        self.data={}
        for name,sha in m['artifacts_sha256'].items():
            p=self.root/name
            if p.is_symlink() or not p.is_file() or p.stat().st_size>16777216:raise ValueError('Unsafe artifact')
            data=p.read_bytes()
            if digest(data)!=sha:raise ValueError('Artifact hash mismatch: '+name)
            self.data[name]=data
        self.norm=loads(self.data['normalization.json'].decode())
        self.thresholds=loads(self.data['thresholds.json'].decode())
        self.provenance=loads(self.data['provenance.json'].decode())
        self.expected=self.provenance['input_contract']
        n=self.norm;t=self.thresholds
        if n.get('features')!=FEATURES or n.get('normalization_fitted_on')!='train':raise ValueError('Normalizer contract differs')
        for key in ['mean','scale']:
            if len(n[key])!=39 or not all(finite(v) for v in n[key]):raise ValueError('Invalid normalization')
        if any(v<=0 for v in n['scale']):raise ValueError('Invalid scale')
        for key in ['input_scale','output_scale']:
            if not finite(n[key]) or n[key]<=0:raise ValueError('Invalid quantization scale')
        for key in ['input_zero_point','output_zero_point']:
            if type(n[key]) is not int or not 0<=n[key]<=255:raise ValueError('Invalid zero point')
        if set(t['group_rmse'])!=set(GROUPS) or not all(finite(v) and v>0 for v in t['group_rmse'].values()):raise ValueError('Invalid group thresholds')
        if len(t['abs_z_limit'])!=39 or not all(finite(v) and v>0 for v in t['abs_z_limit']):raise ValueError('Invalid domain limits')
        if t.get('threshold_fitted_on')!='calibration':raise ValueError('Test leakage into threshold')
        if self.provenance.get('raw_capture_qualification_changed') is not False:raise ValueError('Capture qualification must be preserved')
        sessions=self.provenance['sessions']
        if set(sessions)!=set(('train','calibration','test')):raise ValueError('All three disjoint splits required')
        identities=[]
        for name,group in sessions.items():
            if 'session_ids' in group:
                captures=group.get('captures',[])
                if not captures or group['session_ids']!=[c['session_id'] for c in captures]:
                    raise ValueError('Capture group provenance differs')
                if group['rows']!=sum(c['rows'] for c in captures):raise ValueError('Capture group row counts differ')
                identities.extend(group['session_ids'])
            else:identities.append(group['session_id'])
        if len(identities)<3 or len(set(identities))!=len(identities):raise ValueError('Disjoint real sessions required')
        if has_pwm_reference(self.expected):
            for group in sessions.values():
                captures=group.get('captures',[])
                if not captures:raise ValueError('PWM sweep provenance missing')
                coverage={str(d):0 for d in range(0,101,10)}
                for capture in captures:
                    if (capture.get('source')!='REAL_FRM1_USER_DECLARED_NORMAL_PWM_SWEEP' or
                            capture.get('advisory_label_source')!='USER_CONFIRMED_BLOCKAGE_REMOVED' or
                            capture.get('raw_capture_qualification_changed') is not False or
                            capture.get('settling_excluded_seconds',0)<4):
                        raise ValueError('PWM sweep provenance differs')
                    for duty in coverage:coverage[duty]+=capture.get('pwm_coverage',{}).get(duty,0)
                if group['rows']<600 or any(count<40 for count in coverage.values()):
                    raise ValueError('PWM sweep coverage incomplete')
        self.pin=pin
    def hardware_model(self):
        if self.manifest['schema']!='cabinet-real-normal-npu-v2':
            raise ValueError('Verified hardware rounding conversion required before native execution')
        conversion=loads(self.data['alnpu_conversion.json'].decode())
        if (conversion.get('schema')!='cabinet-alnpu-half-lsb-bias-v1' or
                conversion.get('source_model_sha256')!=digest(self.data['model_u8.onnx']) or
                conversion.get('hardware_model_sha256')!=digest(self.data['model_alnpu_u8.onnx']) or
                conversion.get('reference_and_thresholds_unchanged') is not True):
            raise ValueError('Hardware conversion provenance differs')
        return self.data['model_alnpu_u8.onnx']
