"""Persistent shadow NPU daemon with bounded IPC and latched native faults."""
from cabinet.input_policy import fault_policy, model_values, semantics, input_state
import argparse
import ctypes
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import signal
import socket
import tempfile
import time
import uuid

from .bundle import Bundle, Rejected, digest, loads
from .frames import FrameValidator
from .native_lease import NativeLease
from .profiles import verify_native_profile
from .backend_audit import verify_alnpu_graph


class NativeBackend:
    def __init__(self, library, model, bundle):
        self.adapter = ctypes.CDLL(str(library))
        self.handle = None
        profile_function = getattr(self.adapter, 'edge_npu_profile', None)
        if profile_function is not None:
            profile_function.argtypes = []
            profile_function.restype = ctypes.c_char_p
            profile_bytes = profile_function()
            if not profile_bytes:
                raise ValueError('Empty native hardware profile')
            verify_native_profile(loads(profile_bytes.decode()), bundle)
        elif getattr(bundle, 'hardware_profile', None):
            raise ValueError('A restricted model requires a profile-aware native adapter')
        self.adapter.edge_npu_error.restype = ctypes.c_char_p
        self.adapter.edge_npu_open.argtypes = [ctypes.c_char_p]
        self.adapter.edge_npu_open.restype = ctypes.c_void_p
        self.adapter.edge_npu_close.argtypes = [ctypes.c_void_p]
        self.adapter.edge_npu_close.restype = None
        self.adapter.edge_npu_info.argtypes = [ctypes.c_void_p]
        self.adapter.edge_npu_info.restype = ctypes.c_char_p
        self.adapter.edge_npu_run_u8.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8)]
        self.adapter.edge_npu_run_u8.restype = ctypes.c_int
        self.handle = self.adapter.edge_npu_open(str(model).encode())
        if not self.handle:
            raise RuntimeError(self.adapter.edge_npu_error().decode(errors='replace'))
        try:
            info = loads(self.adapter.edge_npu_info(self.handle).decode())
            if getattr(bundle, 'hardware_profile', None):
                verify_native_profile(info, bundle)
            ps_softmax = bundle.manifest.get('native_abi') == 3
            expected = dict(abi_version=3 if ps_softmax else 2, input_shape=[1, 39], output_shape=[1, 5],
                            input_dtype='uint8', output_dtype='uint8', requested_backends=['Alnpu'])
            if type(info.get('abi_version')) is not int or any(info.get(key) != value for key, value in expected.items()):
                raise ValueError('Native ABI/tensor/backend contract mismatch')
            graph_function = getattr(self.adapter, 'edge_npu_graph_dot', None)
            if graph_function is None:
                raise ValueError('Native adapter must export its actual optimized graph')
            graph_function.argtypes = [ctypes.c_void_p]
            graph_function.restype = ctypes.c_char_p
            graph_bytes = graph_function(self.handle)
            if type(graph_bytes) is not bytes or not graph_bytes or len(graph_bytes) > 1048576:
                raise ValueError('Missing or oversized native optimized graph')
            self.backend_audit = verify_alnpu_graph(info, graph_bytes.decode('utf-8'))
            if any(type(value) is not int for key in ('input_shape', 'output_shape') for value in info[key]):
                raise ValueError('Native shape dimensions must be integers')
            quant = bundle.manifest['io_quantization']
            for key in ('input_scale', 'output_scale'):
                value = info.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or not math.isclose(value, quant[key], rel_tol=1e-6, abs_tol=1e-12):
                    raise ValueError('Native quantization scale mismatch')
            for key in ('input_zero_point', 'output_zero_point'):
                if type(info.get(key)) is not int or info[key] != quant[key]:
                    raise ValueError('Native quantization offset mismatch')
            if ps_softmax:
                if info.get('execution_model') != bundle.manifest['execution_model'] or info.get('postprocess') != bundle.postprocess['algorithm']:
                    raise ValueError('Native PS Softmax execution contract mismatch')
                if type(info.get('logits_scale')) not in (int, float) or not math.isfinite(info['logits_scale']) or not math.isclose(info['logits_scale'], bundle.logits_scale, rel_tol=1e-6, abs_tol=1e-12):
                    raise ValueError('Native logits scale mismatch')
                if type(info.get('logits_zero_point')) is not int or info['logits_zero_point'] != bundle.logits_zero:
                    raise ValueError('Native logits zero-point mismatch')
            self.info = info
        except BaseException:
            self.close()
            raise

    def run(self, encoded):
        inputs, outputs = (ctypes.c_uint8*39)(*encoded), (ctypes.c_uint8*5)()
        if self.adapter.edge_npu_run_u8(self.handle, inputs, outputs):
            raise RuntimeError(self.adapter.edge_npu_error().decode(errors='replace'))
        return list(outputs)

    def close(self):
        if self.handle:
            self.adapter.edge_npu_close(self.handle)
            self.handle = None


def worker(pipe, config, bundle):
    backend = None
    lease = None
    native_fault = False
    if config['backend'] == 'alnpu':
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        with tempfile.TemporaryDirectory(prefix='cabinet-npu-') as temporary:
            model = Path(temporary)/'model.onnx'
            ps_softmax = getattr(bundle, 'ps_softmax', False)
            model.write_bytes(bundle.data['model_logits_u8.onnx' if ps_softmax else 'model_u8_io.onnx'])
            if config['backend'] == 'alnpu':
                lease = NativeLease()
                library = Path(temporary)/'libedge_npu.so'
                library.write_bytes(config['library_bytes'])
                backend = NativeBackend(library, model, bundle)
            else:
                import numpy as np
                import onnxruntime as ort
                options = ort.SessionOptions()
                options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
                backend = ort.InferenceSession(str(model), options, providers=['CPUExecutionProvider'])
                if backend.get_inputs()[0].shape != [1, 39] or backend.get_outputs()[0].shape != [1, 5]:
                    raise ValueError('Reference tensor shape mismatch')
            pipe.send(dict(ready=True, native_metadata=backend.info if config['backend']=='alnpu' else None,
                           backend_audit=backend.backend_audit if config['backend']=='alnpu' else None))
            while True:
                encoded = pipe.recv()
                if encoded is None:
                    break
                try:
                    started = time.monotonic()
                    if config['backend'] == 'alnpu':
                        output = backend.run(encoded)
                    else:
                        time.sleep(config['reference_delay_ms']/1000)
                        output = backend.run(None, {'input': np.asarray([encoded], dtype=np.uint8)})[0][0].tolist()
                        if ps_softmax:
                            from .postprocess import softmax_u8
                            output = softmax_u8(output, bundle.logits_scale, bundle.logits_zero)
                    bundle.decode(output)
                    pipe.send(dict(output=output, execute_ms=(time.monotonic()-started)*1000))
                except Exception as error:
                    native_fault = config['backend'] == 'alnpu'
                    pipe.send(dict(error=type(error).__name__+': '+str(error)))
                    break
    except BaseException as error:
        try:
            pipe.send(dict(error=type(error).__name__+': '+str(error)))
        except (OSError, EOFError):
            pass
    finally:
        if native_fault:
            pipe.close()
            print('NATIVE_FAULT_PARKED: retain engine/CMA until explicit driver recovery', flush=True)
            while True:
                time.sleep(3600)
        try:
            if config['backend'] == 'alnpu' and backend is not None:
                backend.close()
                if lease is not None:
                    lease.close(clean=True)
        finally:
            if lease is not None:
                lease.close()
            pipe.close()


def read_request(peer):
    deadline, data = time.monotonic()+1, b''
    while b'\n' not in data:
        left = deadline-time.monotonic()
        if left <= 0:
            raise TimeoutError('IPC read deadline')
        peer.settimeout(left)
        part = peer.recv(4096)
        if not part:
            raise ConnectionError('IPC request closed')
        data += part
        if len(data) > 65536:
            raise ValueError('IPC request too large')
    line, trailing = data.split(b'\n', 1)
    if trailing.strip():
        raise ValueError('Only one request per connection is supported')
    return loads(line.decode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--backend', choices=('alnpu', 'ort-reference'), required=True)
    parser.add_argument('--allow-synthetic-replay', action='store_true')
    parser.add_argument('--library', type=Path)
    parser.add_argument('--library-sha256')
    parser.add_argument('--profile-state', type=Path, default=Path('/run/cabinet-live/state.json'))
    parser.add_argument('--qualification', type=Path)
    parser.add_argument('--qualification-sha256')
    parser.add_argument('--release-registry', type=Path)
    parser.add_argument('--graph-audit', type=Path)
    parser.add_argument('--graph-audit-sha256')
    parser.add_argument('--timeout-ms', type=int, default=200)
    parser.add_argument('--load-timeout-s', type=float, default=20)
    parser.add_argument('--reference-delay-ms', type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.timeout_ms <= 5000 or not math.isfinite(args.load_timeout_s) or not 0.1 <= args.load_timeout_s <= 120:
        parser.error('Invalid execution/load deadline')
    if not 0 <= args.reference_delay_ms <= 5000 or (args.reference_delay_ms and args.backend != 'ort-reference'):
        parser.error('Delay injection is host-reference only')
    if args.backend == 'ort-reference' and not args.allow_synthetic_replay:
        parser.error('CPU reference requires explicit replay opt-in')
    qualification = None
    if any([args.qualification, args.qualification_sha256, args.release_registry]):
        if not all([args.qualification, args.qualification_sha256, args.release_registry]) or args.backend != 'alnpu' or args.allow_synthetic_replay:
            parser.error('Complete pinned admission requires native Alnpu and no replay')
        qualification = dict(directory=str(args.qualification), sha256=args.qualification_sha256,
                             registry=str(args.release_registry))
    if bool(args.graph_audit) != bool(args.graph_audit_sha256):
        parser.error('Candidate graph audit requires an external SHA256 pin')
    graph_audit = dict(path=str(args.graph_audit), sha256=args.graph_audit_sha256) if args.graph_audit else None
    bundle = Bundle(args.bundle, args.manifest_sha256, args.allow_synthetic_replay, qualification=qualification, graph_audit=graph_audit)
    config = dict(backend=args.backend, reference_delay_ms=args.reference_delay_ms)
    if args.backend == 'alnpu':
        if bundle.hardware_profile:
            from .platform_gate import verify_platform_state
            verify_platform_state(args.profile_state)
        if not args.library or args.library.is_symlink() or not args.library.is_file():
            parser.error('An explicit regular native library matching the bundle ABI is required')
        data = args.library.read_bytes()
        if digest(data) != args.library_sha256:
            parser.error('Native adapter SHA mismatch')
        if bundle.admission:
            bundle.admission.assert_current(args.library_sha256)
        config['library_bytes'] = data
    if os.path.lexists(str(args.socket)):
        parser.error('Socket exists; inspect its owner, never unlink it blindly')
    args.socket.parent.mkdir(parents=True, exist_ok=True)
    context = mp.get_context('spawn')
    parent, child = context.Pipe()
    process = context.Process(target=worker, args=(child, config, bundle), daemon=False)
    validator, instance = FrameValidator(bundle), uuid.uuid4().hex
    fault, socket_identity = None, None
    process.start()
    child.close()
    def stop_signal(*unused):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    try:
        if not parent.poll(args.load_timeout_s):
            fault = 'LOAD_TIMEOUT_LATCHED; inspect/reset native driver before retrying'
        else:
            ready = parent.recv()
            if ready.get('ready') is not True:
                raise RuntimeError(ready.get('error', 'Model initialization failed'))
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(args.socket))
            args.socket.chmod(0o600)
            stat = args.socket.stat()
            socket_identity = stat.st_dev, stat.st_ino
            listener.listen(2)
            listener.settimeout(0.5)
            print(json.dumps(dict(state='MODEL_UNAVAILABLE' if fault else ('FORMAL_READY' if bundle.admission else 'SHADOW_READY'), fault=fault,
                                  backend='Alnpu' if args.backend == 'alnpu' else 'ORT_CPU_REFERENCE',
                                  execution_model=bundle.manifest.get('execution_model', 'ALNPU_PROBABILITIES'),
                                  formal=bool(bundle.admission), daemon_instance=instance, worker_pid=process.pid)), flush=True)
            while True:
                try:
                    peer, unused = listener.accept()
                except socket.timeout:
                    continue
                with peer:
                    try:
                        request = read_request(peer)
                        frame, identity = validator.check(request)
                        if bundle.admission:
                            bundle.admission.assert_current(args.library_sha256)
                        if fault:
                            raise RuntimeError(fault)
                        started = time.monotonic()
                        unused, encoded = bundle.encode(model_values(frame, bundle.contract))
                        preprocess_ms = (time.monotonic()-started)*1000
                        if not process.is_alive():
                            fault = 'WORKER_EXITED_LATCHED'
                            raise RuntimeError(fault)
                        try:
                            parent.send(encoded)
                            if not parent.poll(args.timeout_ms/1000):
                                raise TimeoutError('Execution deadline')
                            output = parent.recv()
                            if 'error' in output:
                                raise RuntimeError(output['error'])
                            probabilities = bundle.decode(output['output'])
                        except (OSError, EOFError, TimeoutError, RuntimeError, ValueError) as error:
                            fault = 'INFERENCE_FAULT_LATCHED: '+str(error)
                            raise RuntimeError(fault)
                        reply = dict(identity, schema='cabinet-npu-result-v4', daemon_instance=instance,
                                     backend='Alnpu' if args.backend == 'alnpu' else 'ORT_CPU_REFERENCE',
                                     test_backend=True, formal=False, qualified=False, mode='SHADOW_ONLY',
                                     probabilities=probabilities, output_u8=output['output'], input_u8=encoded,
                                     preprocess_ms=preprocess_ms, execute_ms=output['execute_ms'])
                        if bundle.ps_softmax:
                            reply.update(execution_model=bundle.manifest['execution_model'], postprocess=bundle.postprocess['algorithm'])
                        if bundle.hardware_profile:
                            reply['hardware_profile'] = bundle.hardware_profile
                        if bundle.admission:
                            reply.update(formal=True, qualified=True, test_backend=False, mode='FORMAL_DIAGNOSTIC',
                                         admission_sha256=bundle.admission.assert_current(args.library_sha256))
                    except Exception as error:
                        reply = dict(schema='cabinet-npu-error-v4', error=type(error).__name__+': '+str(error),
                                     state='OUT_OF_DOMAIN' if isinstance(error, Rejected) else 'MODEL_UNAVAILABLE',
                                     formal=False, daemon_instance=instance)
                    try:
                        peer.settimeout(1)
                        peer.sendall(json.dumps(reply, allow_nan=False).encode()+b'\n')
                    except OSError:
                        pass
    except KeyboardInterrupt:
        pass
    finally:
        if process.is_alive():
            if args.backend == 'ort-reference':
                process.terminate()
                process.join(timeout=3)
            else:
                try:
                    parent.send(None)
                except (OSError, EOFError):
                    pass
                process.join(timeout=2)
                if process.is_alive():
                    print('NATIVE_JOB_STILL_ACTIVE: no forced termination; inspect/reset driver', flush=True)
                    process.join()
        else:
            process.join()
        parent.close()
        if socket_identity and os.path.lexists(str(args.socket)):
            stat = args.socket.lstat()
            if (stat.st_dev, stat.st_ino) == socket_identity:
                args.socket.unlink()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
