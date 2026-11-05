"""Separately supervised PS grade head; never maps fault names to severity."""
import math
import re
from .protocol import FEATURES
from v4_runtime.qualification import pinned_json

GRADES=['normal','mild','severe']


def vector(values,length):
    if type(values) is not list or len(values)!=length or any(type(value) not in (int,float) or not math.isfinite(value) for value in values):
        raise ValueError('Finite grade feature/weight vector required')
    return values


def scores(model,values):
    values=vector(list(values),39)
    normalized=[(value-center)/scale for value,center,scale in zip(values,model['center'],model['scale'])]+[1]
    result=[sum(value*weight for value,weight in zip(normalized,weights)) for weights in model['weights']]
    if any(not math.isfinite(value) for value in result):raise ValueError('Grade arithmetic overflow')
    return result


def validate(model):
    if (model.get('schema')!='cabinet-fault-grade-v1' or model.get('source')!='REAL_FRM1_DECLARED'
            or model.get('feature_names')!=FEATURES or model.get('grades')!=GRADES
            or not re.fullmatch('[a-f0-9]{64}',str(model.get('model_admission_sha256','')))
            or type(model.get('label_definition')) is not str or not model['label_definition'].strip()):
        raise ValueError('Independent physical grade labels and pinned NPU model required')
    vector(model['center'],39);vector(model['scale'],39)
    if any(value<=0 for value in model['scale']):raise ValueError('Positive grade normalization scale required')
    if type(model['weights']) is not list or len(model['weights'])!=3:raise ValueError('Three independent grade outputs required')
    for weights in model['weights']:vector(weights,40)
    contract=model['contract']
    if (set(contract)!={'feature_config_id','calibration_id','sample_mode_id','pl_build_id'}
            or any(type(value) is not int or value<=0 for value in contract.values())):
        raise ValueError('Grade feature contract required')
    train=model.get('train_sessions');rows=model.get('held_out')
    if type(train) is not list or len(set(train))<2 or len(set(train))!=len(train) or any(not re.fullmatch('[a-f0-9]{64}',str(value)) for value in train):
        raise ValueError('At least two training sessions required')
    if type(rows) is not list or not 60<=len(rows)<=100000:raise ValueError('Independent grade evaluation required')
    confusion=[[0]*3 for unused in GRADES];identities=set();sessions=set()
    for row in rows:
        identity=row.get('sample_sha256');session=row.get('session_sha256')
        if (not re.fullmatch('[a-f0-9]{64}',str(identity)) or identity in identities or not re.fullmatch('[a-f0-9]{64}',str(session))
                or session in train or row.get('test') is not False or row.get('grade') not in GRADES):
            raise ValueError('Grade sample leakage, TEST or invalid provenance')
        identities.add(identity);sessions.add(session)
        prediction=max(range(3),key=scores(model,row['features']).__getitem__)
        confusion[GRADES.index(row['grade'])][prediction]+=1
    accuracy=sum(confusion[index][index] for index in range(3))/len(rows)
    if len(sessions)<2 or any(sum(row)<20 for row in confusion) or accuracy<0.95:
        raise ValueError('Grade head requires >=95% session-disjoint accuracy and >=20 per grade')
    return dict(accuracy=accuracy,confusion=confusion)


class FaultGrade:
    def __init__(self,config=None):
        self.config=config
        self.model=None
        if config is not None:
            if type(config) is not dict or set(config)!={'path','sha256'} or not re.fullmatch('[a-f0-9]{64}',str(config['sha256'])):
                raise ValueError('Externally pinned grade model required')
            self.model=pinned_json(config['path'],config['sha256']);self.evaluation=validate(self.model)

    def predict(self,frame,classification):
        unavailable=dict(state='GRADE_UNQUALIFIED',grade=None,qualified=False,control_authority=False)
        if self.model is None:return unavailable
        pinned_json(self.config['path'],self.config['sha256'])
        contract=self.model['contract']
        if (classification.get('formal') is not True or classification.get('qualified') is not True
                or classification.get('test') is not False or classification.get('backend')!='Alnpu'
                or classification.get('admission_sha256')!=self.model['model_admission_sha256']
                or classification.get('frame_id')!=frame.id or frame.test or frame.quality!=0
                or [frame.header[index] for index in (16,17,18,26)]!=[contract[name] for name in ('feature_config_id','calibration_id','sample_mode_id','pl_build_id')]):
            return unavailable
        values=scores(self.model,frame.values);order=sorted(range(3),key=values.__getitem__,reverse=True)
        if values[order[0]]-values[order[1]]<0.1:
            return dict(unavailable,state='GRADE_AMBIGUOUS')
        return dict(state='GRADE_PREDICTION',grade=GRADES[order[0]],qualified=True,control_authority=False,
            backend='PS_LINEAR_GRADE_HEAD_AFTER_ADMITTED_ALNPU',frame_id=frame.id,model_sha256=self.config['sha256'],
            admission_sha256=classification['admission_sha256'],held_out_accuracy=self.evaluation['accuracy'])
