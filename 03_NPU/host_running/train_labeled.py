"""Train one real, user-labelled 39->32->16->5 advisory classifier."""
import argparse
import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
if __package__:
    from .utf8_io import configure_stdio
else:
    from utf8_io import configure_stdio
import numpy as np
import onnx
from onnx import helper, numpy_helper, TensorProto
import onnxruntime as ort
from onnxruntime.quantization import QuantFormat, QuantType, quantize_static
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'linux'))
if __package__:
    from .labeled_dataset import read, save, sha, load_export, coverage, common_contract, SOURCE
    from .labeled_quality import select, report as quality_report
    from .train_normal import Reader
else:
    from labeled_dataset import read, save, sha, load_export, coverage, common_contract, SOURCE
    from labeled_quality import select, report as quality_report
    from train_normal import Reader
from labeled_npu.bundle import Bundle, FILES, prepare, classify
from labeled_npu.core import LABELS, INPUT_POLICY, FEATURES
from v4_runtime.postprocess import softmax_u8

def export(model, path):
    nodes=[]; weights=[]; current='input'
    for i,(w,b) in enumerate(zip(model.coefs_,model.intercepts_)):
        wn,bn,out='weight%d'%i,'bias%d'%i,'linear%d'%i
        weights += [numpy_helper.from_array(w.T.astype(np.float32),wn),numpy_helper.from_array(b.astype(np.float32),bn)]
        nodes.append(helper.make_node('Gemm',[current,wn,bn],[out],name='labeled_fc%d'%i,transB=1)); current=out
        if i<2:
            current='hidden%d'%i; nodes.append(helper.make_node('Relu',[out],[current],name='labeled_relu%d'%i))
    graph=helper.make_model(helper.make_graph(nodes,'user_labeled_logits_39_32_16_5',
        [helper.make_tensor_value_info('input',TensorProto.FLOAT,[1,39])],
        [helper.make_tensor_value_info(current,TensorProto.FLOAT,[1,5])],weights),opset_imports=[helper.make_opsetid('',13)])
    graph.ir_version=8; onnx.checker.check_model(graph); onnx.save(graph,path)

def uint8_io(source, target):
    model=onnx.load(source); initial={p.name:numpy_helper.to_array(p) for p in model.graph.initializer}
    qin=[n for n in model.graph.node if n.op_type=='QuantizeLinear' and n.input[0]=='input']
    if len(qin)!=1: raise ValueError('INPUT_QUANTIZER_SHAPE_CHANGED')
    qin=qin[0]; scale=float(initial[qin.input[1]]); zero=int(initial[qin.input[2]])
    for node in model.graph.node:
        for i,value in enumerate(node.input):
            if value==qin.output[0]: node.input[i]='input'
    model.graph.node.remove(qin); model.graph.input[0].type.tensor_type.elem_type=TensorProto.UINT8
    output=model.graph.output[0].name
    end=[n for n in model.graph.node if n.op_type=='DequantizeLinear' and list(n.output)==[output]]
    if len(end)!=1: raise ValueError('LOGITS_DEQUANTIZER_SHAPE_CHANGED')
    end=end[0]; logits_scale=float(initial[end.input[1]]); logits_zero=int(initial[end.input[2]])
    model.graph.output[0].CopyFrom(helper.make_tensor_value_info(end.input[0],TensorProto.UINT8,[1,5]))
    model.graph.node.remove(end); del model.graph.value_info[:]
    model=onnx.shape_inference.infer_shapes(model,strict_mode=True,data_prop=True); onnx.checker.check_model(model); onnx.save(model,target)
    return dict(input_scale=scale,input_zero_point=zero,logits_scale=logits_scale,logits_zero_point=logits_zero)

def load_dataset(directory):
    path=Path(directory)/'dataset.json'; pin=sha(path); manifest=read(path)
    if (manifest.get('schema')!='cabinet-real-labeled-dataset-v1' or manifest.get('source')!=SOURCE
            or manifest.get('train_ready') is not True or manifest.get('qualified') is not False
            or manifest.get('control_authority')!='NONE'):
        raise ValueError('WAITING_DATA: complete real labelled corpus required')
    entries=manifest['entries']; counts,missing,ready=coverage(entries)
    if manifest.get('input_contract',{}).get('input_policy')!=INPUT_POLICY:
        raise ValueError('V2_INPUT_POLICY_REQUIRED_FOR_NEW_TRAINING')
    if not ready: raise ValueError('WAITING_DATA: independent episodes missing')
    data={s:[] for s in ('train','validation','test')}; labels={s:[] for s in data}; provenance=[]; seen=set(); episodes={}
    common=common_contract(manifest['input_contract']); root=Path(manifest['sessions_root'])
    for e in entries:
        if e['session_id'] in seen or Path(e['session_id']).name!=e['session_id']: raise ValueError('DUPLICATE_OR_UNSAFE_SESSION')
        seen.add(e['session_id'])
        if episodes.setdefault(e['episode_id'],(e['label'],e['split']))!=(e['label'],e['split']): raise ValueError('EPISODE_SPLIT_LEAKAGE')
        folder=root/e['session_id']; learning,meta,summary,values,ids=load_export(folder)
        if (sha(folder/'learning.json')!=e['learning_sha256'] or summary['files_sha256']['frames.jsonl']!=e['frames_sha256']
                or summary['files_sha256']['session.json']!=e['session_sha256']
                or common_contract(learning['context']['input_contract'])!=common
                or learning['context']['bitstream_sha256']!=manifest['bitstream_sha256']
                or (learning['label'],learning['episode_id'],learning['episode_split'])!=(e['label'],e['episode_id'],e['split'])
                or len(values)!=e['rows']): raise ValueError('REGISTERED_SOURCE_CHANGED')
        data[e['split']].extend(values); labels[e['split']].extend([LABELS.index(e['label'])]*len(values)); provenance.append(e)
    if sha(path)!=pin: raise ValueError('DATASET_CHANGED_DURING_LOAD')
    return manifest,pin,{s:np.asarray(v,dtype=np.float32) for s,v in data.items()},{s:np.asarray(v,dtype=np.int64) for s,v in labels.items()},provenance

def train(dataset, output):
    manifest,dataset_pin,raw,labels,provenance=load_dataset(dataset)
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    scaler=StandardScaler().fit(raw['train']); mean=scaler.mean_.astype(np.float32); scale=np.maximum(scaler.scale_,1e-6).astype(np.float32)
    data={s:((v-mean)/scale).astype(np.float32) for s,v in raw.items()}
    model,selection=select(data['train'],labels['train'],data['validation'],labels['validation'],20261103)
    export(model,output/'model_fp32.onnx')
    radius=max(1.,float(np.max(np.abs(data['train'])))*1.25)
    quantize_static(str(output/'model_fp32.onnx'),str(output/'model_qdq.onnx'),Reader(data['train'][::2]),
        quant_format=QuantFormat.QDQ,activation_type=QuantType.QUInt8,weight_type=QuantType.QUInt8,
        per_channel=False,op_types_to_quantize=['Gemm','Relu'],
        extra_options={'TensorQuantOverrides':{'input':[{'rmin':np.float32(-radius),'rmax':np.float32(radius)}]}})
    norm=dict(uint8_io(output/'model_qdq.onnx',output/'model_u8.onnx'),features=FEATURES,
        mean=mean.tolist(),scale=scale.tolist(),normalization_fitted_on='train')
    policy=dict(source='PREDECLARED_ADVISORY_ENGINEERING_GATES',confidence_min=.6,margin_min=.1,
        qualified=False,control_authority='NONE')
    options=ort.SessionOptions(); options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    native=ort.InferenceSession(str(output/'model_u8.onnx'),options,providers=['CPUExecutionProvider'])
    floating=ort.InferenceSession(str(output/'model_fp32.onnx'),options,providers=['CPUExecutionProvider'])
    quality={}; quantization={}; gold=[]; golden_counts={l:0 for l in LABELS}; export_pass=True
    for split in ('validation','test'):
        probs=[]; covered=[]; reference=model.predict_proba(data[split]); agreements=[]; exported=[]
        for i,values in enumerate(raw[split]):
            logits=floating.run(None,{'input':data[split][i:i+1]})[0][0]
            ex=np.exp(logits-np.max(logits)); exported.append(ex/ex.sum())
            try: z,q=prepare(values.tolist(),norm)
            except ValueError:
                probs.append([.2]*5); covered.append(False); agreements.append(False); continue
            logits_u8=native.run(None,{'input':np.frombuffer(q,np.uint8)[None]})[0][0].tolist()
            out=softmax_u8(logits_u8,norm['logits_scale'],norm['logits_zero_point'])
            result=classify(out,policy); probs.append([x/255. for x in out]); covered.append(result['state']=='CLASSIFIED')
            agreements.append(int(np.argmax(out))==int(np.argmax(reference[i])))
            label=LABELS[int(labels[split][i])]
            if split=='test' and golden_counts[label]<32:
                gold.append(dict(split='test',index=i,label=label,values=values.tolist(),input_u8=list(q),output_u8=out))
                golden_counts[label]+=1
        quality[split]=quality_report(labels[split],np.asarray(probs),np.asarray(covered,dtype=bool))
        fp_error=float(np.max(np.abs(np.asarray(exported)-reference)))
        agreement=float(np.mean(agreements)) if agreements else 0.
        ordered=np.sort(reference,axis=1)
        float_covered=(ordered[:,-1]>=policy['confidence_min']) & (ordered[:,-1]-ordered[:,-2]>=policy['margin_min'])
        floating_quality=quality_report(labels[split],reference,float_covered)
        degradation=floating_quality['macro_f1']-quality[split]['macro_f1']
        checks=dict(fp32_export=fp_error<=1e-4,class_agreement=agreement>=.98,macro_f1_degradation=degradation<=.02)
        quantization[split]=dict(fp32_max_probability_error=fp_error,class_agreement=agreement,
            float_macro_f1=floating_quality['macro_f1'],quantized_macro_f1=quality[split]['macro_f1'],
            macro_f1_degradation=degradation,max_macro_f1_degradation=.02,
            rejected_and_out_of_range_count_against_quality=True,checks=checks)
        export_pass &= all(checks.values())
    validation=dict(status='PASS_REAL_LABELED_ADVISORY_HOST_TRAINING',source=SOURCE,qualified=False,
        control_authority='NONE',test_used_for_selection=False,quality=quality,quantization=quantization,
        selection=selection,rows={s:len(v) for s,v in raw.items()},dataset_sha256=dataset_pin,
        fault_detection_accuracy_scope='USER_DECLARED_HELD_OUT_EPISODES_ONLY',npu_executed=False,
        host_versions={name:importlib.metadata.version(name) for name in ('numpy','scikit-learn','onnx','onnxruntime')},
        source_sha256={name:sha(ROOT/name) for name in ('host/train_labeled.py','host/labeled_quality.py',
            'host/labeled_dataset.py','linux/labeled_npu/core.py','linux/labeled_npu/bundle.py',
            'linux/normal_npu/core.py','linux/v4_runtime/postprocess.py')})
    if not export_pass or any(v['status']!='PASS_ENGINEERING_QUALITY_ONLY' for v in quality.values()) or min(golden_counts.values())<32:
        validation['status']='FAIL_MODEL_QUALITY_GATES'; save(output/'training_validation.json',validation)
        raise ValueError('CLASSIFIER_HOST_QUALITY_FAILED; prior model must remain active')
    save(output/'normalization.json',norm); save(output/'policy.json',policy); save(output/'training_validation.json',validation)
    save(output/'golden.json',dict(source=SOURCE,vectors=gold))
    save(output/'provenance.json',dict(source=SOURCE,input_contract=manifest['input_contract'],
        bitstream_sha256=manifest['bitstream_sha256'],sessions=provenance,dataset_sha256=dataset_pin,
        raw_capture_qualification_changed=False,independent_episodes=manifest['independent_episodes']))
    manifest_out=dict(schema='cabinet-real-labeled-npu-v1',source=SOURCE,qualified=False,control_authority='NONE',
        model_id='user-labeled-mlp39-'+dataset_pin[:16],labels=list(LABELS),input_policy=INPUT_POLICY,
        input_shape=[1,39],output_shape=[1,5],architecture=[39,32,16,5],native_abi=3,
        execution_model='ALNPU_LOGITS_PS_SOFTMAX',training_rows=len(raw['train']),
        artifacts_sha256={n:sha(output/n) for n in sorted(FILES)})
    save(output/'manifest.json',manifest_out); pin=sha(output/'manifest.json'); Bundle(output,pin)
    save(output/'receipt.json',dict(status=validation['status'],manifest_sha256=pin,trainer_sha256=sha(Path(__file__)),
        dataset_sha256=dataset_pin,npu_executed=False,deployed=False))
    return pin

def main():
    configure_stdio()
    p=argparse.ArgumentParser(); p.add_argument('--dataset',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); print('MANIFEST_SHA256 '+train(a.dataset,a.output))

if __name__=='__main__': main()
