"""Bounded inference adapters; every result must match its exact input frame."""
import json
import math
import subprocess
import socket
import time
from .protocol import LABELS

def validate_qualification(config):
    if 'qualified' in config and type(config['qualified']) is not bool:
        raise ValueError('Model qualification must be an exact boolean')
    if config.get('qualified') is True:
        qualification=config.get('qualification')
        if (config.get('backend')!='npu_v4' or type(qualification) is not dict or
                type(qualification.get('sha256')) is not str or len(qualification['sha256'])!=64 or
                any(character not in '0123456789abcdef' for character in qualification['sha256']) or
                config.get('evidence')!=qualification['sha256'] or
                not qualification.get('directory') or not qualification.get('registry') or
                config.get('allow_synthetic_replay') is True):
            raise ValueError('Formal model requires a pinned, registered npu_v4 admission; legacy backends are observation-only')

class Model:
    def __init__(self, config):
        validate_qualification(config)
        self.config=config
    def formal_result(self,result):
        if (self.config.get('backend')!='npu_v4' or self.config.get('qualified') is not True or
                result.get('formal') is not True or result.get('qualified') is not True or
                result.get('test') is not False or result.get('backend')!='Alnpu'):
            return False
        adapter=getattr(self,'v4',None)
        admission=adapter.bundle.admission if adapter is not None else None
        if admission is None:return False
        pin=admission.assert_current()
        return result.get('admission_sha256')==pin==self.config['evidence']
    def infer(self,frame,context=None):
        c=self.config;begin=time.monotonic()
        if c['backend']=='npu_v4':
            from v4_runtime.client import V4Model
            if not hasattr(self,'v4'):self.v4=V4Model(c)
            return self.v4.infer(frame,context)
        if c['backend']=='disabled':raise RuntimeError('model_unavailable')
        if c['backend']=='mock':
            label=(frame.id//10)%5
            probabilities=[0.01]*5;probabilities[label]=0.96
        elif c['backend'] in ('command','unix','tcp'):
            payload=dict(frame_id=frame.id,feature_config_id=frame.header[16],calibration_id=frame.header[17],
                         model_id=c['model_id'],values=list(frame.values))
            if c['backend']=='command':
                result=subprocess.run(c['command'],input=json.dumps(payload,allow_nan=False),stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,
                                      timeout=c.get('timeout_ms',200)/1000,check=True,shell=False)
                if len(result.stdout)>65536:raise ValueError('Oversize model result')
                raw=json.loads(result.stdout)
            else:
                tcp=c['backend']=='tcp'
                if tcp and c.get('host','127.0.0.1')!='127.0.0.1':raise ValueError('NPU TCP transport is loopback-only')
                address=('127.0.0.1',c['port']) if tcp else c['socket']
                with socket.socket(socket.AF_INET if tcp else socket.AF_UNIX,socket.SOCK_STREAM) as peer:
                    peer.settimeout(c.get('timeout_ms',200)/1000)
                    peer.connect(address);peer.sendall(json.dumps(payload,allow_nan=False).encode()+b'\n')
                    data=b''
                    while b'\n' not in data:
                        remaining=c.get('timeout_ms',200)/1000-(time.monotonic()-begin)
                        if remaining<=0:raise TimeoutError('Model deadline exceeded')
                        peer.settimeout(remaining)
                        chunk=peer.recv(4096)
                        if not chunk:raise ConnectionError('NPU daemon closed without result')
                        data+=chunk
                        if len(data)>65536:raise ValueError('Oversize model result')
                    raw=json.loads(data.split(b'\n')[0])
                if 'error' in raw:raise RuntimeError('NPU: '+raw['error'])
            if (raw.get('frame_id'),raw.get('model_id'),raw.get('feature_config_id'),raw.get('calibration_id'))!= (
                    frame.id,c['model_id'],frame.header[16],frame.header[17]):raise ValueError('Model result frame/version mismatch')
            probabilities=raw['probabilities']
        elif c['backend']=='onnx':
            # Optional CPU reference, not an NPU performance claim. The pure
            # FP32 MLP already contains its scaler; no second StandardScaler.
            import numpy as np
            import onnxruntime as ort
            if not hasattr(self,'session'):self.session=ort.InferenceSession(c['path'],providers=['CPUExecutionProvider'])
            output=self.session.run(None,{self.session.get_inputs()[0].name:np.array([frame.values],dtype=np.float32)})[0]
            probabilities=np.asarray(output).reshape(-1).tolist()
        else:raise ValueError('Unknown model backend')
        elapsed=(time.monotonic()-begin)*1000
        if elapsed>c.get('timeout_ms',200):raise TimeoutError('Model deadline exceeded')
        if len(probabilities)!=5 or not all(type(x) in (int,float) and math.isfinite(x) and 0<=x<=1 for x in probabilities):
            raise ValueError('Invalid five-class probabilities')
        if abs(sum(probabilities)-1)>0.02:raise ValueError('Probabilities do not sum to one')
        index=max(range(5),key=probabilities.__getitem__)
        backend='MOCK' if c['backend']=='mock' else 'CPU_ONNX' if c['backend']=='onnx' else 'EXTERNAL_'+c['backend'].upper()
        return dict(frame_id=frame.id,model_id=c['model_id'],feature_config_id=frame.header[16],calibration_id=frame.header[17],
                    label=LABELS[index],label_id=index,confidence=probabilities[index],probabilities=probabilities,
                    inference_ms=round(elapsed,3),backend=backend,formal=False,qualified=False,policy_qualified=False,
                    test=frame.test or c['backend']=='mock' or (c['backend'] in ('unix','tcp','command') and raw.get('test_backend',False)))
