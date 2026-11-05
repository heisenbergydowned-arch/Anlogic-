"""Quantize a two-class candidate using the accelerator's five-logit wire ABI.

Only normal/clog are learned. The other three output slots are suppressed
constants, explicitly untrained; this package cannot pass the five-class loader.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
import onnx
import onnxruntime as ort
from onnxruntime.quantization import quantize_static, QuantFormat, QuantType


def main(a):
    root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str(a.runtime/'host'),str(root/'host'),str(root/'linux')]
    from train_labeled import export,uint8_io
    from train_normal import Reader
    from compile_labeled_bundle import compile_model
    from labeled_dataset import load_export,sha,save
    from normal_sweep_dataset import load_split
    from normal_npu.core import FEATURES,prepare
    from v4_runtime.postprocess import softmax_u8
    from train_normal_clog_candidate import quality

    report=json.loads((a.candidate/'training_report.json').read_text())
    if report['status']!='PASS_SCOPED_HOST_CANDIDATE' or report['trained_labels']!=['normal','clog']:
        raise ValueError('Passed scoped candidate required')
    w=np.load(a.candidate/'model_weights.npz',allow_pickle=False)
    if sha(a.candidate/'model_weights.npz')!=report['weights_sha256']:raise ValueError('Weights changed')
    dataset=Path(report['dataset_path'])
    if sha(dataset)!=report['dataset_sha256']:raise ValueError('Dataset changed')
    manifest=json.loads(dataset.read_text());raw={s:[] for s in ('train','validation','test')};y={s:[] for s in raw}
    for e in report['sessions']:
        folder=Path(manifest['sessions_root'])/e['session_id'];learning,meta,summary,x,ids=load_export(folder)
        if (sha(folder/'learning.json')!=e['learning_sha256'] or summary['files_sha256']['frames.jsonl']!=e['frames_sha256']):
            raise ValueError('Source changed')
        raw[e['split']].extend(x);y[e['split']].extend([int(e['label']=='clog')]*len(x))
    sweep_indices={};sweep_duties={}
    for split,name in (('train','train'),('validation','calibration'),('test','test')):
        x,ids,expected,p=load_split(name,None,a.normal_sweeps)
        if p!=report['normal_pwm_provenance'][split]:raise ValueError('Sweep source changed')
        sweep_indices[split]=np.arange(len(raw[split]),len(raw[split])+len(x))
        lookup={r['observation']['frame']['header'][3]:r['duty_percent']
                for r in map(json.loads,(a.normal_sweeps/name/'observations.jsonl').read_text().splitlines())
                if r['observation'].get('frame',{}).get('header')}
        sweep_duties[split]=np.array([lookup[i] for i in ids])
        raw[split].extend(x.tolist());y[split].extend([0]*len(x))
    raw={s:np.asarray(v,np.float32) for s,v in raw.items()};y={s:np.asarray(v) for s,v in y.items()}
    a.output.mkdir(parents=True,exist_ok=False)
    mean=w['mean'].astype(np.float32);scale=w['scale'].astype(np.float32)
    data={s:((x-mean)/scale).astype(np.float32) for s,x in raw.items()}
    coefs=[w['weight0'],w['weight1'],np.zeros((16,5),np.float32)]
    biases=[w['bias0'],w['bias1'],np.array([0,-16,-16,w['bias2'][0],-16],np.float32)]
    coefs[2][:,3]=w['weight2'][:,0]
    export(SimpleNamespace(coefs_=coefs,intercepts_=biases),a.output/'model_fp32.onnx')
    radius=max(1.,float(np.abs(data['train']).max())*1.25)
    quantize_static(str(a.output/'model_fp32.onnx'),str(a.output/'model_qdq.onnx'),Reader(data['train'][::2]),
        quant_format=QuantFormat.QDQ,activation_type=QuantType.QUInt8,weight_type=QuantType.QUInt8,
        per_channel=False,op_types_to_quantize=['Gemm','Relu'],
        extra_options={'TensorQuantOverrides':{'input':[{'rmin':np.float32(-radius),'rmax':np.float32(radius)}]}})
    norm=dict(uint8_io(a.output/'model_qdq.onnx',a.output/'model_u8.onnx'),
              features=FEATURES,mean=mean.tolist(),scale=scale.tolist(),normalization_fitted_on='train')
    save(a.output/'normalization.json',norm)
    session=ort.InferenceSession(str(a.output/'model_u8.onnx'),providers=['CPUExecutionProvider'])
    floating=ort.InferenceSession(str(a.output/'model_fp32.onnx'),providers=['CPUExecutionProvider'])
    results={};gold=[];passed=True
    for split in ('validation','test'):
        probabilities=[];agreement=[];max_export_error=0.;untrained_max=0;clipped_count=0
        for i,x in enumerate(raw[split]):
            h=(x-w['mean'])/w['scale']
            for layer in range(3):
                h=h@w['weight%d'%layer]+w['bias%d'%layer]
                if layer<2:h=np.maximum(h,0)
            clog=float(1/(1+np.exp(-np.clip(h[0],-700,700))))
            fl=floating.run(None,{'input':data[split][i:i+1]})[0][0]
            fp=np.exp(fl-fl.max());fp/=fp.sum()
            max_export_error=max(max_export_error,abs(float(fp[3])-clog))
            _,q,clipped=prepare(x.tolist(),norm)
            if clipped:
                probabilities.append([.5,.5]);agreement.append(False);clipped_count+=1;continue
            logits=session.run(None,{'input':np.frombuffer(q,np.uint8)[None]})[0][0].tolist()
            out=softmax_u8(logits,norm['logits_scale'],norm['logits_zero_point'])
            untrained_max=max(untrained_max,out[1],out[2],out[4])
            probabilities.append([out[0]/255.,out[3]/255.])
            agreement.append(int(out[3]>out[0])==int(clog>.5))
            # Balanced test vectors come from frozen labelled test episodes.
            label='clog' if y[split][i] else 'normal'
            if split=='test' and i<sweep_indices[split][0] and sum(g['label']==label for g in gold)<32:
                gold.append(dict(label=label,values=x.tolist(),input_u8=list(q),output_u8=out))
        probabilities=np.array(probabilities);qr=quality(y[split],probabilities)
        per_duty={}
        for duty in sorted(set(sweep_duties[split])):
            part=probabilities[sweep_indices[split][sweep_duties[split]==duty]]
            fp=float((part[:,1]>=.6).mean());normal=float((part[:,0]>=.6).mean())
            per_duty[str(int(duty))]=dict(rows=len(part),false_positive_rate=fp,normal_recall=normal,passed=fp<=.05 and normal>=.8)
        checks=dict(quality=qr['passed'],class_agreement=float(np.mean(agreement))>=.98,
            macro_f1_degradation=report['quality'][split]['macro_f1']-qr['macro_f1']<=.02,
            fp32_export=max_export_error<=1e-4,untrained_outputs_zero=untrained_max==0,
            normal_pwm=all(v['passed'] for v in per_duty.values()))
        results[split]=dict(checks=checks,quality=qr,class_agreement=float(np.mean(agreement)),
            clipped_count=clipped_count,fp32_export_max_error=max_export_error,untrained_output_max_u8=untrained_max,
            normal_pwm=per_duty)
        passed &= all(checks.values())
    save(a.output/'golden.json',dict(source=report['source'],trained_labels=['normal','clog'],vectors=gold))
    converted,offsets,audit_before,audit_after=compile_model((a.output/'model_u8.onnx').read_bytes())
    onnx.save(converted,a.output/'model_alnpu_u8.onnx')
    save(a.output/'conversion.json',dict(offsets=offsets,audit_before=audit_before,audit_after=audit_after,
        reference_unchanged=True,trained_weights_unchanged=True,hardware_executed=False))
    validation=dict(status='PASS_SCOPED_HOST_QUANTIZATION' if passed else 'FAIL_SCOPED_QUANTIZATION',
        trained_labels=['normal','clog'],untrained_labels=['imbalance','stall','overheat'],
        npu_executed=False,deployed=False,qualified=False,control_authority='NONE',results=results,
        training_report_sha256=sha(a.candidate/'training_report.json'),dataset_sha256=report['dataset_sha256'])
    save(a.output/'validation.json',validation)
    save(a.output/'manifest.json',dict(schema='cabinet-scoped-training-candidate-v1',
        trained_labels=['normal','clog'],wire_labels=['normal','imbalance','stall','clog','overheat'],
        untrained_output_policy='SUPPRESSED_CONSTANT_NOT_LEARNED_CLASS',input_shape=[1,39],output_shape=[1,5],
        source=report['source'],npu_executed=False,deployed=False,qualified=False,control_authority='NONE',
        ready_for_hardware_probe=passed,
        artifacts_sha256={p.name:sha(p) for p in a.output.iterdir() if p.is_file()}))
    print(json.dumps(dict(status=validation['status'],test=results['test'],npu_executed=False),indent=2))
    if not passed:raise RuntimeError('Quantized candidate failed; keep selected model unchanged')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('runtime','candidate','normal-sweeps','output'):p.add_argument('--'+key,type=Path,required=True)
    main(p.parse_args())
