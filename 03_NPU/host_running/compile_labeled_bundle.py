"""Derive Alnpu integer rounding program without fitting labels or changing reference."""
import argparse
import copy
import math
from pathlib import Path
import shutil
import sys
if __package__:
    from .utf8_io import configure_stdio
else:
    from utf8_io import configure_stdio
import numpy as np
import onnx
from onnx import numpy_helper
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'linux'))
if __package__:
    from .labeled_dataset import read,save,sha
    from .labeled_graph import audit
else:
    from labeled_dataset import read,save,sha
    from labeled_graph import audit
from labeled_npu.bundle import Bundle

def compile_model(reference_bytes):
    model=onnx.load_model_from_string(reference_bytes); before=copy.deepcopy(model)
    original=audit(model.SerializeToString())
    initial={v.name:v for v in model.graph.initializer}; arrays={k:numpy_helper.to_array(v) for k,v in initial.items()}
    corrections={}
    for i,name in enumerate(('hidden0','hidden1','linear2')):
        scale=float(arrays['bias%d_quantized_scale'%i].reshape(-1)[0]); q=float(arrays[name+'_scale'])
        if not math.isfinite(scale) or not math.isfinite(q) or min(scale,q)<=0: raise ValueError('INVALID_LAYER_QUANTIZATION')
        delta=int(math.floor(.5*q/scale+.5)); key='bias%d_quantized'%i
        values=arrays[key].astype(np.int64)+delta
        if not np.all((values>=-(2**31))&(values<2**31)): raise ValueError('BIAS_CORRECTION_OVERFLOW')
        initial[key].CopyFrom(numpy_helper.from_array(values.astype(np.int32),key)); corrections[key]=delta
    onnx.checker.check_model(model); graph=audit(model.SerializeToString())
    originals={v.name:numpy_helper.to_array(v) for v in before.graph.initializer}
    for item in model.graph.initializer:
        if not np.all(numpy_helper.to_array(item).astype(np.float64)-originals[item.name].astype(np.float64)==corrections.get(item.name,0)):
            raise ValueError('NON_ANALYTICAL_MODEL_CHANGE')
    topology=copy.deepcopy(model); del topology.graph.initializer[:]; del before.graph.initializer[:]
    if topology.SerializeToString()!=before.SerializeToString(): raise ValueError('GRAPH_TOPOLOGY_CHANGED')
    return model,corrections,original,graph

def compile_bundle(reference, output):
    reference=Path(reference); output=Path(output)
    b=Bundle(reference,read(reference/'receipt.json')['manifest_sha256'])
    if output.exists(): raise ValueError('FRESH_COMPILATION_DIRECTORY_REQUIRED')
    output.mkdir(parents=True)
    for name in list(b.data)+['manifest.json','receipt.json']:
        shutil.copy2(str(reference/name),str(output/name))
    model,corrections,original,graph=compile_model(b.data['model_u8.onnx'])
    onnx.save(model,output/'model_alnpu_u8.onnx')
    conversion=dict(schema='cabinet-labeled-alnpu-half-lsb-bias-v1',source_model_sha256=sha(output/'model_u8.onnx'),
        hardware_model_sha256=sha(output/'model_alnpu_u8.onnx'),reference_unchanged=True,trained_weights_unchanged=True,
        bias_integer_offsets=corrections,compiler_sha256=sha(Path(__file__)),graph_audit=graph,
        reference_graph_audit=original,derived_program_hardware_tested=False,
        derivation='Nearest integer to half output quantization step in bias units; no label fitting')
    save(output/'alnpu_conversion.json',conversion)
    m=b.manifest.copy(); m['schema']='cabinet-real-labeled-npu-v2'; m['model_id']+='-alnpu'
    for name in ('model_alnpu_u8.onnx','alnpu_conversion.json'): m['artifacts_sha256'][name]=sha(output/name)
    save(output/'manifest.json',m); pin=sha(output/'manifest.json'); Bundle(output,pin).hardware_model()
    save(output/'receipt.json',dict(status='COMPILED_REAL_LABELED_CANDIDATE_PENDING_HARDWARE',manifest_sha256=pin,
        reference_manifest_sha256=b.pin,compiler_sha256=sha(Path(__file__)),npu_executed=False,deployed=False))
    return pin

def main():
    configure_stdio()
    p=argparse.ArgumentParser(); p.add_argument('--reference',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); print('MANIFEST_SHA256 '+compile_bundle(a.reference,a.output))

if __name__=='__main__': main()
