"""Persistent 39-in/5-out NPU worker. Mock is explicit and always identified.

The native backend uses the board SDK's Alnpu-only ArmNN adapter. A timed-out
native job latches this daemon unavailable; it is never automatically restarted
while the driver may still own DMA. The PL receiver/control service is separate.
"""
import argparse
import ctypes
import json
import math
import multiprocessing as mp
from pathlib import Path
import socket
import signal
import sys
import time

def native_worker(pipe,config):
    try:
        if config['backend']=='mock':
            adapter=None
        else:
            adapter=ctypes.CDLL(config['library'])
            adapter.edge_npu_error.restype=ctypes.c_char_p
            adapter.edge_npu_open.argtypes=[ctypes.c_char_p];adapter.edge_npu_open.restype=ctypes.c_void_p
            adapter.edge_npu_run.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_float),ctypes.POINTER(ctypes.c_float)]
            adapter.edge_npu_run.restype=ctypes.c_int
            adapter.edge_npu_close.argtypes=[ctypes.c_void_p]
            handle=adapter.edge_npu_open(str(config['model']).encode())
            if not handle:raise RuntimeError(adapter.edge_npu_error().decode(errors='replace'))
        pipe.send({'ready':True,'backend':config['backend']})
        while True:
            request=pipe.recv()
            if request is None:break
            try:
                if adapter is None:
                    time.sleep(config.get('mock_delay_ms',0)/1000)
                    probabilities=[0.96,0.01,0.01,0.01,0.01]
                else:
                    x=(ctypes.c_float*39)(*request['values']);y=(ctypes.c_float*5)()
                    if adapter.edge_npu_run(handle,x,y):raise RuntimeError(adapter.edge_npu_error().decode(errors='replace'))
                    probabilities=list(y)
                pipe.send(dict(frame_id=request['frame_id'],feature_config_id=request['feature_config_id'],
                               calibration_id=request['calibration_id'],model_id=config['model_id'],
                               probabilities=probabilities,backend='MOCK' if adapter is None else 'Alnpu',test_backend=adapter is None))
            except Exception as e:pipe.send({'error':str(e)})
        if adapter is not None:adapter.edge_npu_close(handle)
    except BaseException as e:
        try:pipe.send({'error':type(e).__name__+': '+str(e)})
        except (BrokenPipeError,EOFError,OSError):pass
    finally:pipe.close()

def validate(request,config):
    if type(request) is not dict:raise ValueError('request object')
    for k in ('frame_id','feature_config_id','calibration_id'):
        if type(request.get(k)) is not int or not 0<=request[k]<=0xffffffff:raise ValueError(k)
    if (request.get('model_id'),request['feature_config_id'],request['calibration_id'])!=(
            config['model_id'],config['feature_config_id'],config['calibration_id']):raise ValueError('model/input contract mismatch')
    x=request.get('values')
    if type(x) is not list or len(x)!=39 or not all(type(v) in (float,int) and math.isfinite(v) and abs(v)<=3.4028234e38 for v in x):
        raise ValueError('finite FP32[39] input required')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--socket',default='/run/cabinet/npu.sock');p.add_argument('--model')
    p.add_argument('--tcp-port',type=int,help='Optional loopback-only TCP for Windows/PC integration tests')
    p.add_argument('--library',default='./npu/libedge_npu.so');p.add_argument('--model-id',required=True)
    p.add_argument('--feature-config-id',type=int,required=True);p.add_argument('--calibration-id',type=int,required=True)
    p.add_argument('--timeout-ms',type=int,default=200);p.add_argument('--load-timeout-s',type=float,default=20)
    p.add_argument('--mock',action='store_true');p.add_argument('--mock-delay-ms',type=int,default=0)
    args=p.parse_args()
    if not args.mock and not args.model:p.error('Native NPU needs a real model path')
    if args.timeout_ms<1 or args.timeout_ms>5000:p.error('timeout must be 1..5000 ms')
    config=vars(args);config['backend']='mock' if args.mock else 'Alnpu'
    path=Path(args.socket)
    unix=args.tcp_port is None
    if unix:
        if not hasattr(socket,'AF_UNIX'):p.error('AF_UNIX unavailable; use --tcp-port for PC testing')
        if path.exists():p.error('Socket already exists; inspect the current owner before removing it')
        path.parent.mkdir(parents=True,exist_ok=True)
    ctx=mp.get_context('spawn');parent,child=ctx.Pipe();worker=ctx.Process(target=native_worker,args=(child,config),daemon=True)
    worker.start();child.close()
    if not parent.poll(args.load_timeout_s):raise RuntimeError('NPU initialization deadline; inspect driver before retrying')
    ready=parent.recv()
    if not ready.get('ready'):raise RuntimeError(ready.get('error','NPU initialization failed'))
    fault=None
    def stop_signal(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop_signal)
    try:
        with socket.socket(socket.AF_UNIX if unix else socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(str(path) if unix else ('127.0.0.1',args.tcp_port))
            if unix:path.chmod(0o600)
            listener.listen(2);listener.settimeout(0.5)
            print('NPU WORKER READY '+json.dumps(dict(ready,address=listener.getsockname())),flush=True)
            while True:
                try:peer,_=listener.accept()
                except socket.timeout:continue
                with peer:
                    peer.settimeout(1)
                    try:
                        data=b'';deadline=time.monotonic()+1
                        while b'\n' not in data:
                            left=deadline-time.monotonic()
                            if left<=0:raise TimeoutError('Request deadline')
                            peer.settimeout(left)
                            part=peer.recv(4096)
                            if not part:raise ConnectionError('Request closed')
                            data+=part
                            if len(data)>65536:raise ValueError('Oversize request')
                        request=json.loads(data.split(b'\n')[0]);validate(request,config)
                        if fault:reply={'error':fault}
                        elif not worker.is_alive():fault='NPU worker exited';reply={'error':fault}
                        else:
                            parent.send(request)
                            if parent.poll(args.timeout_ms/1000):reply=parent.recv()
                            else:
                                fault='NPU timeout latched; inspect/reset driver before restarting daemon'
                                reply={'error':fault}
                                if args.mock:worker.terminate() # no hardware/DMA in mock
                        peer.sendall(json.dumps(reply,allow_nan=False).encode()+b'\n')
                    except (ValueError,TypeError,KeyError,ConnectionError,OSError,EOFError) as e:
                        try:peer.sendall(json.dumps({'error':str(e)}).encode()+b'\n')
                        except OSError:pass
    except KeyboardInterrupt:pass
    finally:
        if worker.is_alive() and not fault:
            parent.send(None);worker.join(timeout=2)
        if unix:
            try:path.unlink()
            except FileNotFoundError:pass
        parent.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
