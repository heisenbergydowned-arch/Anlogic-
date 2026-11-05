"""Compile a pinned reference bundle for the measured Alnpu integer rounding."""
from pathlib import Path
import argparse,copy,datetime,hashlib,json,math,shutil,sys
if __package__:
    from .utf8_io import configure_stdio
else:
    from utf8_io import configure_stdio
configure_stdio()
import numpy as np
import onnx
from onnx import numpy_helper
E=Path(__file__).resolve().parents[1];sys.path.insert(0,str(E/'linux'))
from normal_npu.bundle import Bundle
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n', encoding='utf-8')
p=argparse.ArgumentParser();p.add_argument('--reference',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();source=a.reference.resolve();out=a.output.resolve()
pin=json.loads((source/'receipt.json').read_text(encoding='utf-8'))['manifest_sha256'];b=Bundle(source,pin)
shutil.copytree(source,out)
model=onnx.load(out/'model_u8.onnx');reference=copy.deepcopy(model)
init={v.name:v for v in model.graph.initializer};arrays={n:numpy_helper.to_array(v) for n,v in init.items()}
assert len([n for n in model.graph.node if n.op_type=='Gemm'])==3
corrections=[]
for i,name in enumerate(['hidden0','hidden1','linear2']):
    scale=float(arrays['bias%d_quantized_scale'%i].reshape(-1)[0]);q=float(arrays[name+'_scale'])
    delta=int(math.floor(.5*q/scale+.5));key='bias%d_quantized'%i
    values=arrays[key].astype(np.int64)+delta;assert np.all((values>=-(2**31))&(values<2**31))
    init[key].CopyFrom(numpy_helper.from_array(values.astype(np.int32),key))
    corrections.append(dict(layer=i,initializer=key,integer_offset=delta,output_counts=delta*scale/q))
onnx.checker.check_model(model);onnx.save(model,out/'model_alnpu_u8.onnx')
original={v.name:numpy_helper.to_array(v) for v in reference.graph.initializer}
expected={c['initializer']:c['integer_offset'] for c in corrections}
for tensor in model.graph.initializer:
    delta=numpy_helper.to_array(tensor).astype(np.float64)-original[tensor.name].astype(np.float64)
    assert np.all(delta==expected.get(tensor.name,0)),tensor.name
check=copy.deepcopy(model);del check.graph.initializer[:];del reference.graph.initializer[:]
assert check.SerializeToString()==reference.SerializeToString()
conversion=dict(schema='cabinet-alnpu-half-lsb-bias-v1',source_model_sha256=sha(out/'model_u8.onnx'),
    hardware_model_sha256=sha(out/'model_alnpu_u8.onnx'),reference_and_thresholds_unchanged=True,
    trained_weights_unchanged=True,model_topology_unchanged=True,bias_integer_offsets=expected,
    correction_details=corrections,compiler_sha256=sha(Path(__file__)),
    source_normalization_sha256=sha(out/'normalization.json'),source_thresholds_sha256=sha(out/'thresholds.json'),
    source_golden_sha256=sha(out/'golden.json'),derived_program_hardware_tested=False,
    derivation='Nearest integer to half output quantization step, in bias units; no fitting against labels')
save(out/'alnpu_conversion.json',conversion)
manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
manifest.update(schema='cabinet-real-normal-npu-v2',model_id=b.manifest['model_id']+'-alnpu',
                created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
for name in ['model_alnpu_u8.onnx','alnpu_conversion.json']:manifest['artifacts_sha256'][name]=sha(out/name)
save(out/'manifest.json',manifest);pin=sha(out/'manifest.json');Bundle(out,pin).hardware_model()
save(out/'receipt.json',dict(status='COMPILED_REAL_NORMAL_REFERENCE_FOR_ALNPU_PENDING_VALIDATION',
    manifest_sha256=pin,reference_manifest_sha256=sha(source/'manifest.json'),compiler_sha256=sha(Path(__file__)),
    source_trainer_sha256=json.loads((source/'receipt.json').read_text(encoding='utf-8'))['trainer_sha256'],
    npu_executed=False,deployed=False))
print('MANIFEST_SHA256 '+pin)
