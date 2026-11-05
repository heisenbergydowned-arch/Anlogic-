"""ABI3 classifier in the same persistent OS lease as the normal AE."""
import ctypes
import json
import math
import multiprocessing as mp
from pathlib import Path
import re
import signal
import tempfile
import time
from normal_npu.native import Supervisor as BaseSupervisor
from v4_runtime.native_lease import NativeLease
from v4_runtime.backend_audit import verify_alnpu_graph
from v4_runtime.profiles import PROFILE, PL_BUILD_ID
from .bundle import Bundle, digest

class Engine:
    def __init__(self, library, model, norm):
        self.lib=ctypes.CDLL(str(library)); self.handle=None; self.poisoned=False
        l=self.lib
        l.edge_npu_open.argtypes=[ctypes.c_char_p]; l.edge_npu_open.restype=ctypes.c_void_p
        l.edge_npu_error.argtypes=[]; l.edge_npu_error.restype=ctypes.c_char_p
        for name in ('info','graph_dot'):
            f=getattr(l,'edge_npu_'+name); f.argtypes=[ctypes.c_void_p]; f.restype=ctypes.c_char_p
        l.edge_npu_run_u8.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint8),ctypes.POINTER(ctypes.c_uint8)]
        l.edge_npu_run_u8.restype=ctypes.c_int; l.edge_npu_close.argtypes=[ctypes.c_void_p]; l.edge_npu_close.restype=None
        try:
            self.handle=l.edge_npu_open(str(model).encode())
            if not self.handle: raise RuntimeError(self.error())
            self.info=json.loads(l.edge_npu_info(self.handle).decode()); self.graph=l.edge_npu_graph_dot(self.handle).decode()
            expected=dict(abi_version=3,input_shape=[1,39],output_shape=[1,5],input_dtype='uint8',output_dtype='uint8',
                requested_backends=['Alnpu'],execution_model='ALNPU_LOGITS_PS_SOFTMAX',
                postprocess='FP32_STABLE_SOFTMAX_TIES_TO_EVEN_V1',hardware_profile=PROFILE,compatible_pl_build_ids=[PL_BUILD_ID])
            if any(self.info.get(k)!=v for k,v in expected.items()): raise ValueError('CLASSIFIER_NATIVE_ABI_CHANGED')
            for key in ('input_scale','input_zero_point','logits_scale','logits_zero_point'):
                if not math.isclose(self.info[key],norm[key],rel_tol=1e-6,abs_tol=1e-12): raise ValueError('NATIVE_QUANTIZATION_CHANGED')
            if not math.isclose(self.info['output_scale'],1/255.,rel_tol=1e-6) or self.info['output_zero_point']!=0:
                raise ValueError('NATIVE_PROBABILITY_QUANTIZATION_CHANGED')
            self.audit=verify_alnpu_graph(self.info,self.graph)
            if len(re.findall(r'LayerType\s*:\s*ALHardNPU',self.graph))!=3: raise ValueError('EXACTLY_THREE_HARD_FC_LAYERS_REQUIRED')
        except BaseException:
            self.close(); raise
    def error(self): return (self.lib.edge_npu_error() or b'Native error').decode(errors='replace')
    def run(self,q):
        if len(q)!=39 or self.poisoned: raise ValueError('INVALID_NATIVE_INPUT_OR_POISONED_OWNER')
        x=(ctypes.c_uint8*39).from_buffer_copy(q); y=(ctypes.c_uint8*5)(); start=time.monotonic()
        if self.lib.edge_npu_run_u8(self.handle,x,y):
            self.poisoned=True; raise RuntimeError(self.error())
        return list(y),(time.monotonic()-start)*1000
    def close(self):
        # ABI3 close is void; only an unpoisoned, completed stream may call it.
        # The parent also requires a successful child exit before marking cleanup verified.
        if self.poisoned: return False
        if self.handle: self.lib.edge_npu_close(self.handle); self.handle=None
        return True

def worker(pipe,bundle_path,pin,library_path,library_pin):
    lease=None; engine=None; clean=False
    signal.signal(signal.SIGTERM,signal.SIG_IGN); signal.signal(signal.SIGINT,signal.SIG_IGN)
    try:
        b=Bundle(bundle_path,pin); library=Path(library_path)
        if library.is_symlink() or not library.is_file():
            raise ValueError('CLASSIFIER_ADAPTER_PIN_CHANGED')
        adapter_bytes=library.read_bytes()
        if digest(adapter_bytes)!=library_pin: raise ValueError('CLASSIFIER_ADAPTER_PIN_CHANGED')
        with tempfile.TemporaryDirectory(prefix='cabinet-labeled-native-') as directory:
            model=Path(directory)/'model.onnx'; adapter=Path(directory)/'adapter.so'
            model.write_bytes(b.hardware_model()); adapter.write_bytes(adapter_bytes)
            lease=NativeLease(); engine=Engine(adapter,model,b.norm)
            pipe.send(dict(status='READY',metadata=engine.info,graph=engine.graph,audit=engine.audit))
            while True:
                request=pipe.recv()
                if request['op']=='stop': break
                outputs,elapsed=engine.run(request['input'])
                pipe.send(dict(status='RESULT',output=outputs,execute_ms=elapsed,request_id=request['id']))
            clean=engine.close(); engine=None if clean else engine
            pipe.send(dict(status='CLOSED',clean=clean))
    except (Exception,KeyboardInterrupt) as error:
        try: pipe.send(dict(status='ERROR',error=type(error).__name__+': '+str(error)))
        except (OSError,EOFError): pass
    finally:
        if engine is not None: clean=engine.close()
        if lease is not None: lease.close(clean=clean)
        pipe.close()

class Supervisor(BaseSupervisor):
    def __init__(self,bundle,pin,library,library_pin):
        context=mp.get_context('spawn'); self.pipe,child=context.Pipe()
        self.process=context.Process(target=worker,args=(child,str(bundle),pin,str(library),library_pin))
        self.process.daemon=False; self.process.start(); child.close(); self.busy=False; self.closed=False; self.sequence=0
        if not self.pipe.poll(20): raise RuntimeError('Native load timeout; retained worker pid=%d'%self.process.pid)
        try: self.ready=self.pipe.recv()
        except EOFError: raise RuntimeError('Native child exited before READY; inspect retained lease')
        if self.ready.get('status')!='READY':
            self.process.join(.5); raise RuntimeError('Native initialization failed: '+str(self.ready))
