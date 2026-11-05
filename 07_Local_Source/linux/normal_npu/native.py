"""Exclusive Alnpu-only worker. Native timeouts never trigger forced termination."""
import ctypes
import json
import multiprocessing as mp
from pathlib import Path
import re
import tempfile
import time
from .bundle import Bundle,digest
from v4_runtime.native_lease import NativeLease
from v4_runtime.backend_audit import verify_alnpu_graph

class Engine:
    def __init__(self,library):
        self.lib=ctypes.CDLL(str(library));self.handle=None;self.poisoned=False
        l=self.lib
        l.edge_normal_open.argtypes=[ctypes.c_char_p];l.edge_normal_open.restype=ctypes.c_void_p
        l.edge_normal_error.argtypes=[];l.edge_normal_error.restype=ctypes.c_char_p
        for n in ['info','graph_dot']:
            f=getattr(l,'edge_normal_'+n);f.argtypes=[ctypes.c_void_p];f.restype=ctypes.c_char_p
        l.edge_normal_run_u8.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint8),ctypes.POINTER(ctypes.c_uint8)]
        l.edge_normal_run_u8.restype=ctypes.c_int
        l.edge_normal_close.argtypes=[ctypes.c_void_p];l.edge_normal_close.restype=ctypes.c_int
    def initialize(self,model,norm):
        l=self.lib
        try:
            self.handle=l.edge_normal_open(str(model).encode())
            if not self.handle:raise RuntimeError(self.error())
            self.info=json.loads(l.edge_normal_info(self.handle).decode())
            self.graph=l.edge_normal_graph_dot(self.handle).decode()
            i=self.info
            if (i.get('abi_version')!=1 or i.get('input_shape')!=[1,39] or i.get('output_shape')!=[1,39]
                    or i.get('execution_model')!='ALNPU_NORMAL_RECONSTRUCTION_39'
                    or i.get('hardware_profile')!='DR1M90_NORMAL_AE39_V1'):
                raise ValueError('Native normal-model ABI differs')
            self.audit=verify_alnpu_graph(i,self.graph)
            if len(re.findall(r'LayerType\s*:\s*ALHardNPU',self.graph))!=3:
                raise ValueError('Expected three hardware FC layers')
            for key in ['input_scale','output_scale','input_zero_point','output_zero_point']:
                if abs(i[key]-norm[key])>1e-7*max(1,abs(norm[key])):raise ValueError('Quantization metadata differs: '+key)
        except BaseException:
            self.close();raise
    def error(self):return (self.lib.edge_normal_error() or b'Native error').decode(errors='replace')
    def run(self,q):
        if len(q)!=39 or self.poisoned:raise ValueError('Native input or state invalid')
        x=(ctypes.c_uint8*39).from_buffer_copy(q);y=(ctypes.c_uint8*39)();start=time.monotonic()
        if self.lib.edge_normal_run_u8(self.handle,x,y)!=0:
            self.poisoned=True;raise RuntimeError(self.error())
        return bytes(y),(time.monotonic()-start)*1000
    def close(self):
        if self.handle:
            if self.poisoned or self.lib.edge_normal_close(self.handle)!=0:return False
            self.handle=None
        return True

def worker(pipe,bundle_path,pin,library_path,library_pin):
    lease=None;engine=None;clean=False
    try:
        b=Bundle(bundle_path,pin);p=Path(library_path)
        if p.is_symlink() or not p.is_file():raise ValueError('Regular pinned native library required')
        data=p.read_bytes()
        if digest(data)!=library_pin:raise ValueError('Native library hash mismatch')
        with tempfile.TemporaryDirectory(prefix='cabinet-normal-native-') as folder:
            model=Path(folder)/'model.onnx';lib=Path(folder)/'adapter.so'
            model.write_bytes(b.hardware_model());lib.write_bytes(data)
            lease=NativeLease();engine=Engine(lib);engine.initialize(model,b.norm)
            pipe.send({'status':'READY','metadata':engine.info,'graph':engine.graph,'audit':engine.audit})
            while True:
                request=pipe.recv()
                if request['op']=='stop':break
                output,elapsed=engine.run(request['input'])
                pipe.send({'status':'RESULT','output':output,'execute_ms':elapsed,'request_id':request['id']})
            clean=engine.close();engine=None if clean else engine
            pipe.send({'status':'CLOSED','clean':clean})
    except (Exception,KeyboardInterrupt) as error:
        try:pipe.send({'status':'ERROR','error':type(error).__name__+': '+str(error)})
        except (BrokenPipeError,EOFError,OSError):pass
    finally:
        if engine is not None:clean=engine.close()
        if lease is not None:lease.close(clean=clean)
        pipe.close()

class Supervisor:
    def __init__(self,bundle,pin,library,library_pin):
        context=mp.get_context('spawn');self.pipe,child=context.Pipe()
        self.process=context.Process(target=worker,args=(child,str(bundle),pin,str(library),library_pin))
        self.process.daemon=False;self.process.start();child.close();self.busy=False;self.closed=False;self.sequence=0
        if not self.pipe.poll(20):raise RuntimeError('Native load timed out; retained worker pid=%d; no forced kill'%self.process.pid)
        try:self.ready=self.pipe.recv()
        except EOFError:
            self.process.join(.5)
            raise RuntimeError('Native worker exited before READY: pid=%d exitcode=%s; inspect native lease and initialization trace before retry'%(self.process.pid,self.process.exitcode))
        if self.ready.get('status')!='READY':
            self.process.join(.5)
            raise RuntimeError('Native initialization failed: pid=%d exitcode=%s detail=%s'%(self.process.pid,self.process.exitcode,self.ready))
    def infer(self,data,deadline=.2):
        if self.busy:raise RuntimeError('Unresolved native job')
        self.sequence+=1;self.busy=True
        try:
            self.pipe.send({'op':'infer','id':self.sequence,'input':data})
            if not self.pipe.poll(deadline):raise RuntimeError('Native inference timeout; worker retained, no forced kill')
            r=self.pipe.recv()
        except (EOFError,OSError) as error:
            raise RuntimeError('Native worker connection failed; inspect retained lease: '+repr(error))
        self.busy=False
        if r.get('status')!='RESULT' or r['request_id']!=self.sequence:raise RuntimeError(str(r))
        return r
    def close(self):
        try:return self._close()
        except (EOFError,OSError):return False
    def _close(self):
        if self.closed:return True
        if self.busy:
            if not self.pipe.poll(5):return False
            r=self.pipe.recv();self.busy=False
            if r.get('status')!='RESULT':return False
        if self.process.is_alive():
            self.pipe.send({'op':'stop'})
            if not self.pipe.poll(5):return False
            r=self.pipe.recv()
            if r.get('status')!='CLOSED' or not r.get('clean'):return False
        self.process.join(5)
        self.closed=not self.process.is_alive() and self.process.exitcode==0
        if self.closed:self.pipe.close()
        return self.closed
