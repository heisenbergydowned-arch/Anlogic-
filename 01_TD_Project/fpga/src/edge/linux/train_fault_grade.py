"""Train a separately labelled grade head; does not issue NPU or physical receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from cabinet.fault_grade import GRADES,validate
from cabinet.protocol import FEATURES


def train(dataset):
    rows=dataset['train']
    if len(rows)<60 or any(row.get('test') is not False or row.get('grade') not in GRADES for row in rows):
        raise ValueError('Labelled, non-TEST training data required')
    identities=[row['sample_sha256'] for row in rows]
    held_out_identities={row['sample_sha256'] for row in dataset['held_out']}
    if len(set(identities))!=len(rows) or any(identity in held_out_identities for identity in identities):
        raise ValueError('Grade training/test sample leakage')
    features=np.asarray([row['features'] for row in rows],dtype=np.float64)
    if any(sum(row['grade']==grade for row in rows)<20 for grade in GRADES):raise ValueError('At least twenty training examples per grade required')
    if features.shape!=(len(rows),39) or not np.isfinite(features).all():raise ValueError('Finite physical 39-feature inputs required')
    center=features.mean(axis=0);scale=features.std(axis=0);scale[scale<1e-12]=1
    design=np.column_stack(((features-center)/scale,np.ones(len(rows))))
    labels=np.eye(3)[[GRADES.index(row['grade']) for row in rows]]
    penalty=np.eye(40)*0.01;penalty[-1,-1]=0
    weights=np.linalg.solve(design.T@design+penalty,design.T@labels).T
    model=dict(schema='cabinet-fault-grade-v1',source=dataset['source'],feature_names=FEATURES,grades=GRADES,
        label_definition=dataset['label_definition'],model_admission_sha256=dataset['model_admission_sha256'],
        contract=dataset['contract'],train_sessions=sorted({row['session_sha256'] for row in rows}),
        center=center.tolist(),scale=scale.tolist(),weights=weights.tolist(),held_out=dataset['held_out'])
    evaluation=validate(model)
    return model,evaluation


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dataset',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    arguments=parser.parse_args();model,evaluation=train(json.loads(arguments.dataset.read_text()))
    data=json.dumps(model,allow_nan=False,sort_keys=True).encode()
    with arguments.output.open('xb') as stream:stream.write(data)
    print(json.dumps(dict(status='PASS_OFFLINE_GRADE_HEAD_NOT_TARGET_ACCEPTANCE',sha256=hashlib.sha256(data).hexdigest(),evaluation=evaluation,npu_executed=False)))


if __name__=='__main__':main()
