"""Train a quantized normal-only autoencoder from three real, disjoint captures."""
from pathlib import Path
import argparse,hashlib,json,struct,sys,time,warnings,datetime,shutil
if __package__:
    from .utf8_io import configure_stdio
    from .normal_selection import CANDIDATES,selection_policy,reconstruction_metrics,select_candidate,validation_status,input_quality
else:
    from utf8_io import configure_stdio
    from normal_selection import CANDIDATES,selection_policy,reconstruction_metrics,select_candidate,validation_status,input_quality
from collections import Counter
import numpy as np
import onnx
from onnx import helper,numpy_helper,TensorProto
import onnxruntime as ort
from onnxruntime.quantization import CalibrationDataReader,QuantFormat,QuantType,quantize_static
from sklearn.neural_network import MLPRegressor
from sklearn.exceptions import ConvergenceWarning

E=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(E/'linux'))
from normal_npu.core import FEATURES,GROUPS,validate_header,prepare,reconstruction_errors,score
from normal_npu.bundle import Bundle
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,value):p.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n', encoding='utf-8')

def load_split(name,expected=None,root=E,filter_invalid=False):
    p=root/'captures'/name;meta=json.loads((p/'session.json').read_text(encoding='utf-8'));receipt=json.loads((root/'sessions.json').read_text(encoding='utf-8'))[name]
    assert receipt['status']['state']=='DIAGNOSTIC_SAVED'
    assert meta['capture_mode']=='DIAGNOSTIC' and meta['qualified'] is False
    learning=json.loads((root/'learning.json').read_text(encoding='utf-8'))
    assert learning['schema']=='cabinet-one-click-normal-learning-v1'
    assert learning['healthy_confirmed'] is True and learning['label_source']=='USER_DECLARES_CURRENT_CONDITION_NORMAL'
    assert learning['raw_capture_qualification_changed'] is False
    assert meta['bitstream_sha256']==learning['context']['bitstream_sha256']
    summary=json.loads((p/'summary.json').read_text(encoding='utf-8'))
    assert summary['state']=='DIAGNOSTIC_SAVED' and summary['session_id']==meta['session_id']
    assert summary['durable_frames']==summary['frames']
    independent=meta.get('window_policy')=='INDEPENDENT_NORMAL_NPU_WINDOWS'
    if not independent:assert summary['gaps']==0
    else:assert summary['missing_frames']/max(1,summary['frames']+summary['missing_frames'])<=.02
    for filename,digest in summary['files_sha256'].items():
        assert filename in ('session.json','feature_contract.json','frames.jsonl') and sha(p/filename)==digest
    assert set(summary['files_sha256'])=={'session.json','feature_contract.json','frames.jsonl'}
    rows=[json.loads(line) for line in (p/'frames.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(rows)>=600
    if expected is None:
        first=rows[0];h=first['header'];status=first['status']
        expected={'device_id':meta['device_id'],'configuration_words':meta['configuration_words'],
                  'frame_identity':[h[16],h[17],h[18]],'controller_mode':status['mode'],
                  'controller_diagnostic_mode':bool(status['test_mode'])}
    assert meta['configuration_words']==expected['configuration_words']
    assert meta['device_id']==expected['device_id']
    values=[];ids=[];last=meta.get('preceding_frame_id');excluded=[];missing=0;gap_events=0
    for row in rows:
        assert row['source']=='REAL_FRM1_DECLARED' and row['session_id']==meta['session_id']
        h=row['header']
        if last is not None:
            distance=(h[3]-last)&0xffffffff
            assert 1<=distance<=8 if independent else distance==1
            if independent:
                assert row['gap_before']==distance-1
                missing+=distance-1;gap_events+=int(distance>1)
        last=h[3]
        try:validate_header(h,row['status'],expected)
        except ValueError as error:
            if not filter_invalid or str(error) not in ('SENSOR_OR_WINDOW_INVALID','SAMPLE_RATE_INVALID',
                    'PROCESS_SENSOR_INVALID','HARDWARE_FAULT_ACTIVE','FRAME_STALE'):raise
            excluded.append({'frame_id':h[3],'reason':str(error)});continue
        words=row['feature_words'];assert len(words)==39
        x=struct.unpack('<39f',struct.pack('<39I',*words));assert all(np.isfinite(x))
        values.append(x);ids.append(h[3])
    if independent:assert missing==summary['missing_frames'] and gap_events==summary['gaps']
    assert expected==learning['context']['input_contract'],'Learning contract differs'
    assert len(excluded)/len(rows)<=.05,'Too many invalid sensor windows'
    assert len(values)>=512,'Insufficient valid real diagnostic windows'
    return np.asarray(values,dtype=np.float32),ids,expected,{
        'session_id':meta['session_id'],'source':'REAL_FRM1_DECLARED','rows':len(values),
        'boot_id':meta['boot_id'],'raw_rows':len(rows),'excluded_windows':excluded,'missing_windows':missing,'gap_events':gap_events,'window_policy':meta.get('window_policy','CONTIGUOUS'),
        'excluded_reason_counts':dict(Counter(v['reason'] for v in excluded)),
        'frames_sha256':sha(p/'frames.jsonl'),'session_sha256':sha(p/'session.json'),
        'first_frame':ids[0],'last_frame':ids[-1],'capture_formal_accepted':sum(bool(r['accepted']) for r in rows),
        'capture_label_declared':meta['label_declared'],'advisory_label_source':'USER_DECLARES_CURRENT_CONDITION_NORMAL',
        'quality_values':sorted({r['header'][15] for r in rows}),
        'formal_rejection_reasons':sorted({v for r in rows for v in r['rejected_reasons']})}

def export(model,path):
    nodes=[];weights=[];current='input'
    for i,(w,b) in enumerate(zip(model.coefs_,model.intercepts_)):
        wn,bn,out='weight%d'%i,'bias%d'%i,'linear%d'%i
        # Match the proven Alnpu FC layout while preserving X @ W + b.
        weights += [numpy_helper.from_array(w.T.astype(np.float32),wn),numpy_helper.from_array(b.astype(np.float32),bn)]
        nodes.append(helper.make_node('Gemm',[current,wn,bn],[out],name='normal_fc%d'%i,transB=1))
        current=out
        if i<2:
            current='hidden%d'%i;nodes.append(helper.make_node('Relu',[out],[current],name='normal_relu%d'%i))
    graph=helper.make_model(helper.make_graph(nodes,'real_normal_reconstruction_39_32_16_39',
        [helper.make_tensor_value_info('input',TensorProto.FLOAT,[1,39])],
        [helper.make_tensor_value_info(current,TensorProto.FLOAT,[1,39])],weights),opset_imports=[helper.make_opsetid('',13)])
    graph.ir_version=8;onnx.checker.check_model(graph);onnx.save(graph,path)

class Reader(CalibrationDataReader):
    def __init__(self,x):self.rows=iter(x)
    def get_next(self):
        row=next(self.rows,None)
        return None if row is None else {'input':row[None].astype(np.float32)}

def uint8_io(src,dest):
    model=onnx.load(src);initial={p.name:numpy_helper.to_array(p) for p in model.graph.initializer}
    qin=[n for n in model.graph.node if n.op_type=='QuantizeLinear' and n.input[0]=='input'];assert len(qin)==1
    qin=qin[0];input_scale=float(initial[qin.input[1]]);input_zero=int(initial[qin.input[2]])
    for node in model.graph.node:
        for i,v in enumerate(node.input):
            if v==qin.output[0]:node.input[i]='input'
    model.graph.node.remove(qin);model.graph.input[0].type.tensor_type.elem_type=TensorProto.UINT8
    end=model.graph.output[0].name
    dq=[n for n in model.graph.node if n.op_type=='DequantizeLinear' and list(n.output)==[end]];assert len(dq)==1
    dq=dq[0];output_scale=float(initial[dq.input[1]]);output_zero=int(initial[dq.input[2]])
    out=dq.input[0];model.graph.node.remove(dq)
    model.graph.output[0].CopyFrom(helper.make_tensor_value_info(out,TensorProto.UINT8,[1,39]))
    # The vendor parser dereferences intermediate type/shape metadata. ONNX
    # Runtime accepts missing value_info, but this SDK segfaults without it.
    # Recompute after changing the public input/output types, not before.
    del model.graph.value_info[:]
    model=onnx.shape_inference.infer_shapes(model,strict_mode=True,data_prop=True)
    onnx.checker.check_model(model);onnx.save(model,dest)
    return dict(input_scale=input_scale,input_zero_point=input_zero,output_scale=output_scale,output_zero_point=output_zero)

def infer_rows(path,x,norm):
    options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(path),options,providers=['CPUExecutionProvider'])
    predictions=[]
    for row in x:
        z,q,clipped=prepare(row.tolist(),norm)
        out=session.run(None,{'input':np.frombuffer(q,np.uint8)[None]})[0][0]
        predictions.append((z,q,out,clipped))
    return predictions

def group_loss_weights():
    # Equal average squared error per semantic group; ratio_ab belongs to both
    # vibration groups. Normalize total weight to the original 39-feature loss.
    weights=np.zeros(39,dtype=np.float64)
    for indices in GROUPS.values():weights[indices]+=39.0/(len(GROUPS)*len(indices))
    return np.sqrt(weights)

def training_objective():
    return dict(schema='cabinet-group-balanced-normal-loss-v1',
        squared_loss='equal_mean_per_GROUPS_with_shared_features_summed',
        feature_target_scales=group_loss_weights().tolist(),
        architecture_unchanged=[39,32,16,39],output_units_unchanged=True,
        thresholds_or_domain_limits_relaxed=False)

def fit_group_balanced(model,train):
    weights=group_loss_weights()
    model.fit(train,train*weights)
    # Fold back into the existing affine output layer, adding no runtime op or
    # direct input shortcut. The 16-unit bottleneck is retained.
    expected=model.predict(train[:64])/weights
    model.coefs_[-1]=model.coefs_[-1]/weights[None,:]
    model.intercepts_[-1]=model.intercepts_[-1]/weights
    error=float(np.max(np.abs(expected-model.predict(train[:64]))))
    if not np.isfinite(error) or error>1e-6:raise ValueError('OUTPUT_LOSS_WEIGHT_FOLD_CHANGED_FUNCTION')
    return error

def fit_quantized_candidate(index,train,cal,xcal,normalization,limit,directory):
    """This function has no independent-test input or access to its scores."""
    alpha,seed=CANDIDATES[index]
    directory.mkdir(parents=True,exist_ok=False)
    model=MLPRegressor(hidden_layer_sizes=(32,16),activation='relu',solver='lbfgs',
        alpha=alpha,random_state=seed,max_iter=6000,max_fun=100000,tol=1e-5)
    start=time.monotonic()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always');fold_error=fit_group_balanced(model,train)
    mse=float(np.mean((model.predict(cal)-cal)**2))
    export(model,directory/'model_fp32.onnx')
    quantize_static(str(directory/'model_fp32.onnx'),str(directory/'model_qdq.onnx'),Reader(train[::2]),
        quant_format=QuantFormat.QDQ,activation_type=QuantType.QUInt8,weight_type=QuantType.QUInt8,
        per_channel=False,op_types_to_quantize=['Gemm','Relu'],
        extra_options={'TensorQuantOverrides':{'input':[{'rmin':np.float32(-limit),'rmax':np.float32(limit)}]}})
    norm=dict(normalization,**uint8_io(directory/'model_qdq.onnx',directory/'model_u8.onnx'))
    predictions=infer_rows(directory/'model_u8.onnx',xcal,norm)
    item=dict(candidate_index=index,alpha=alpha,seed=seed,calibration_mse=mse,
              fp32_calibration_mse=mse,constant_mean_mse=float(np.mean(cal**2)),
              quantized_calibration=reconstruction_metrics(predictions,norm),
              model_u8_sha256=sha(directory/'model_u8.onnx'),
              iterations=int(model.n_iter_),seconds=time.monotonic()-start,
              training_objective=training_objective(),output_fold_max_absolute_error=fold_error,
              warnings=[str(w.message) for w in caught])
    return item,norm,predictions

def main():
    configure_stdio()
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--capture-root',type=Path,action='append',help='Directory containing captures/ and sessions.json')
    parser.add_argument('--filter-invalid-diagnostic',action='store_true')
    parser.add_argument('--sweep-root',type=Path,help='Three separately recorded train/calibration/test PWM sweeps')
    parser.add_argument('--extra-sweep-train-root',type=Path,action='append',default=[],
                        help='Additional explicitly confirmed complete sweeps used only for training')
    args=parser.parse_args()
    if args.sweep_root and args.capture_root:parser.error('Choose recorded sweeps or recorder captures')
    if args.extra_sweep_train_root and not args.sweep_root:parser.error('Extra sweeps require a primary sweep dataset')
    loader=load_split
    if args.sweep_root:
        from normal_sweep_dataset import load_split as loader
    output=args.output;output.mkdir(parents=True,exist_ok=False)
    def group(name,expected=None):
        arrays=[];identities=[];provenance=[]
        roots=([args.sweep_root]+(args.extra_sweep_train_root if name=='train' else [])
               if args.sweep_root else (args.capture_root or [E]))
        for root in roots:
            x,ids,expected,meta=loader(name,expected,root,args.filter_invalid_diagnostic)
            arrays.append(x);identities.extend((meta['session_id'],i) for i in ids);provenance.append(meta)
        return np.concatenate(arrays),identities,expected,dict(rows=sum(p['rows'] for p in provenance),
            session_ids=[p['session_id'] for p in provenance],captures=provenance)
    xtrain,trainids,contract,ptrain=group('train');xcal,calids,_,pcal=group('calibration',contract);xtest,testids,_,ptest=group('test',contract)
    all_ids=ptrain['session_ids']+pcal['session_ids']+ptest['session_ids'];assert len(set(all_ids))==len(all_ids)
    captures=ptrain['captures']+pcal['captures']+ptest['captures']
    assert len({c['boot_id'] for c in captures})==1
    assert max(c['last_frame'] for c in ptrain['captures'])<min(c['first_frame'] for c in pcal['captures'])
    assert max(c['last_frame'] for c in pcal['captures'])<min(c['first_frame'] for c in ptest['captures'])
    mean=xtrain.mean(0).astype(np.float32)
    floors=np.asarray(([.0001]*6+[.05]*3+[.01]*8)*2+[.05,.005,1.,2/65536,20.],dtype=np.float32)
    scale=np.maximum(xtrain.std(0),floors).astype(np.float32)
    train=((xtrain-mean)/scale).astype(np.float32);cal=((xcal-mean)/scale).astype(np.float32)
    limit=max(8.,float(np.max(np.abs(train)))*1.25)
    normalization=dict(features=FEATURES,mean=mean.tolist(),scale=scale.tolist(),normalization_fitted_on='train',
                       units='current_feature_encoding_relative_reference_only')
    policy=selection_policy();save(output/'selection_policy.json',policy)
    selection=[];candidates=[]
    for i in range(len(CANDIDATES)):
        directory=output/'candidates'/('candidate_%02d'%i)
        item,norm,predictions=fit_quantized_candidate(i,train,cal,xcal,normalization,limit,directory)
        candidates.append((directory,norm,predictions));selection.append(item)
        save(output/'selection.json',selection);print(json.dumps(item),flush=True)
    selected=select_candidate(selection)
    directory,norm,calibration=candidates[selected]
    for name in ('model_fp32.onnx','model_qdq.onnx','model_u8.onnx'):
        shutil.copyfile(str(directory/name),str(output/name))
    errors=[reconstruction_errors(z,q,norm) for z,_,q,_ in calibration]
    thresholds={'threshold_fitted_on':'calibration','quantization_margin_counts':3,
        'group_rmse':{n:max(.2,float(np.quantile([r[n] for r in errors],.995))*1.1)+3*norm['output_scale'] for n in GROUPS},
        'abs_z_limit':np.maximum(5.,np.max(np.abs(train),axis=0)*1.5).tolist()}
    # Freeze the quantized winner and calibration-only thresholds before the
    # single holdout evaluation. Failure never revisits candidate selection.
    locked=dict(policy=policy,selected=selection[selected],model_u8_sha256=sha(output/'model_u8.onnx'),
                thresholds_sha256=hashlib.sha256(json.dumps(thresholds,sort_keys=True,allow_nan=False).encode()).hexdigest())
    save(output/'selection_result.json',locked)
    tests=infer_rows(output/'model_u8.onnx',xtest,norm)
    results=[score(z,q,norm,thresholds,c) for z,_,q,c in tests]
    false_alarm=float(np.mean([r['state']!='BASELINE_MATCH' for r in results]))
    metrics={'calibration':reconstruction_metrics(calibration,norm),'independent_test':reconstruction_metrics(tests,norm)}
    validation={'status':validation_status(metrics,false_alarm),
        'quantized_reconstruction_comparison':metrics,'minimum_quantized_reconstruction_gain':.1,
        'normal_holdout_frames':len(results),'normal_holdout_alarm_rate':false_alarm,'false_alarm_budget':.05,
        'fault_detection_accuracy':None,'fault_classes_trained':[],'qualified':False,'selected':selection[selected],
        'selection_policy':policy,'independent_test_evaluations':1,
        'data_quality':{'calibration':input_quality(calibration,thresholds['abs_z_limit'],FEATURES),
                        'independent_test':input_quality(tests,thresholds['abs_z_limit'],FEATURES)},
        'holdout_scores':{n:float(np.quantile([r['score'] for r in results],q)) for n,q in [('p50',.5),('p95',.95),('p99',.99)]},
        'real_normal_training_only':True,'npu_executed':False,'normalization_fitted_on_train':True,
        'test_used_for_training_selection_or_threshold':False}
    save(output/'training_validation.json',validation)
    provenance={'source':'REAL_USER_DECLARED_NORMAL_DIAGNOSTIC','raw_capture_qualification_changed':False,
        'training_objective':training_objective(),
        'input_contract':contract,'sessions':{'train':ptrain,'calibration':pcal,'test':ptest},
        'calibration_used_for_model_selection_and_threshold':True,'test_used_for_training':False,
        'user_scope':'Use current user-declared normal data for live advisory NPU inference',
        'limitations':['no fault-class data','normal operating domain not independently certified']+(['physical units not calibrated'] if contract['frame_identity'][1]==0 else [])+(['controller diagnostic/inhibited profile'] if contract['controller_diagnostic_mode'] else [])}
    # Hardware comparison uses calibration rows first; independent test remains a separate acceptance set.
    gold=[]
    for split,data,preds,identities in [('calibration',xcal,calibration,calids),('test',xtest,tests,testids)]:
        for idx in np.linspace(0,len(data)-1,64,dtype=int):
            z,q,recon,clipped=preds[idx]
            gold.append({'split':split,'index':int(idx),'session_id':identities[idx][0],'frame_id':identities[idx][1],
                         'values':data[idx].tolist(),'input_u8':list(q),
                         'reconstruction_u8':recon.tolist(),'expected_advisory':score(z,recon,norm,thresholds,clipped)})
    save(output/'normalization.json',norm);save(output/'thresholds.json',thresholds);save(output/'provenance.json',provenance);save(output/'golden.json',{'source':'REAL_CAPTURE_ROWS','vectors':gold})
    artifacts=['model_u8.onnx','normalization.json','thresholds.json','provenance.json','golden.json']
    manifest={'schema':'cabinet-real-normal-npu-v1','model_id':'real-normal-ae39-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')+'-'+output.parent.name,
        'source':'REAL_USER_DECLARED_NORMAL_DIAGNOSTIC','qualified':False,'fault_classes_trained':[],
        'control_authority':'NONE','architecture':[39,32,16,39],'input_shape':[1,39],'output_shape':[1,39],
        'model_kind':'NORMAL_ONLY_RECONSTRUCTION','artifacts_sha256':{n:sha(output/n) for n in artifacts},
        'training_rows':len(xtrain),'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save(output/'manifest.json',manifest);pin=sha(output/'manifest.json');Bundle(output,pin)
    save(output/'receipt.json',{'manifest_sha256':pin,'status':validation['status'],'host_versions':{
        'python':sys.version,'numpy':np.__version__,'onnx':onnx.__version__,'onnxruntime':ort.__version__},'trainer_sha256':sha(Path(__file__))})
    print(json.dumps(validation,indent=2));print('MANIFEST_SHA256 '+pin,flush=True)
    if validation['status']!='PASS_REAL_NORMAL_ADVISORY_HOST_TRAINING':raise SystemExit(1)

if __name__=='__main__':main()
