"""Balanced offline compatibility/latency probe through the actual shadow daemon."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import uuid

from .bundle import Bundle, digest
from .client import V4Model
from .frames import synthetic_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--backend', choices=('ort-reference', 'alnpu'), required=True)
    parser.add_argument('--library', type=Path)
    parser.add_argument('--library-sha256')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Fresh probe output directory required')
    bundle = Bundle(args.bundle, args.manifest_sha256, allow_synthetic=True)
    if not bundle.synthetic:
        parser.error('This compatibility probe is synthetic-only; real evidence needs original labelled FRM1')
    if args.backend == 'alnpu' and (platform.system() != 'Linux' or platform.machine().lower() not in ('aarch64', 'arm64')):
        parser.error('Alnpu execution evidence requires the actual ARM64 Linux board')
    if args.backend == 'alnpu' and (not args.library or not args.library_sha256):
        parser.error('Pinned ABI v2 library required')
    args.output.mkdir(parents=True)
    socket_dir = tempfile.mkdtemp(prefix='np4-')
    socket_path = Path(socket_dir)/'n.sock'
    command = [sys.executable, '-m', 'v4_runtime.server', '--bundle', str(args.bundle.resolve()),
        '--manifest-sha256', args.manifest_sha256, '--socket', str(socket_path), '--backend', args.backend,
        '--allow-synthetic-replay', '--timeout-ms', '200']
    if args.backend == 'alnpu':
        command += ['--library', str(args.library.resolve()), '--library-sha256', args.library_sha256]
    report = dict(status='RUNNING', source=bundle.manifest['source'], backend=args.backend,
                  qualified=False, hardware_verified=False, model_manifest_sha256=args.manifest_sha256,
                  npu_executed=False, npu_execution_requested=args.backend == 'alnpu',
                  boot_modified=False, fpga_bitstream_modified=False, actuator_commands_issued=False)
    process = None
    with (args.output/'daemon.log').open('w') as log:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic()+25
            while not socket_path.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if not socket_path.exists():
                raise RuntimeError('Shadow daemon initialization failed/deadline')
            model = V4Model(dict(backend='npu_v4', bundle=str(args.bundle), bundle_manifest_sha256=args.manifest_sha256,
                model_id=bundle.manifest['model_id'], qualified=False, evidence=None, allow_synthetic_replay=True,
                socket=str(socket_path), timeout_ms=500))
            session = uuid.uuid4().hex
            errors, agreements, latencies, execution, preprocessing = [], [], [], [], []
            vectors = bundle.json('runtime_golden.json')['vectors']
            for sequence, vector in enumerate(vectors, 1):
                frame = synthetic_frame(vector['physical'], sequence, 1000+sequence*128, bundle.contract,
                                        bundle.manifest['compatible_pl_build_ids'][0])
                result = model.infer(frame, dict(session_id=session, boot_id='OFFLINE_SYNTHETIC_COMPATIBILITY',
                    generation=1, now_ms=frame.header[4], received_at=time.monotonic()))
                expected_backend = 'Alnpu' if args.backend == 'alnpu' else 'ORT_CPU_REFERENCE'
                if result['backend'] != expected_backend or result['formal'] is not False or result['test'] is not True:
                    raise ValueError('Backend or shadow boundary violated')
                report.update(npu_executed=args.backend == 'alnpu', completed_golden_vectors=sequence)
                errors.append(max(abs(actual-expected) for actual, expected in zip(result['probabilities'], vector['probabilities'])))
                agreements.append(max(range(5), key=result['probabilities'].__getitem__) == max(range(5), key=vector['probabilities'].__getitem__))
                latencies.append(result['inference_ms'])
                execution.append(result['execute_ms'])
                preprocessing.append(result['preprocess_ms'])
            budget = 2/255+1e-6 if args.backend == 'alnpu' else 1e-7
            if max(errors) > budget or sum(agreements)/len(agreements) < 0.98:
                raise ValueError('Golden probability/class equivalence failed')
            def percentiles(values):
                ordered = sorted(values)
                result = {}
                for name, fraction in [('p50', 0.50), ('p95', 0.95), ('p99', 0.99)]:
                    position = fraction*(len(ordered)-1)
                    lower = int(position)
                    upper = min(lower+1, len(ordered)-1)
                    result[name] = ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)
                return result
            report.update(status='PASS_ALNPU_OFFLINE_GOLDEN_ONLY' if args.backend == 'alnpu' else 'PASS_HOST_DAEMON_GOLDEN_ONLY',
                npu_executed=args.backend == 'alnpu', vectors=len(vectors), class_counts=bundle.json('runtime_golden.json')['class_counts'],
                max_probability_error=max(errors), class_agreement=sum(agreements)/len(agreements),
                end_to_end_ms=percentiles(latencies), execute_ms=percentiles(execution), preprocessing_ms=percentiles(preprocessing),
                end_to_end_p99_below_128ms=percentiles(latencies)['p99'] < 128,
                performance_is_observation_not_qualification=True)
        except Exception as error:
            report.update(status='FAIL', error=type(error).__name__+': '+str(error))
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    report.update(status='FAIL_NATIVE_JOB_REQUIRES_MANUAL_DRIVER_RECOVERY',
                                  retained_daemon_pid=process.pid, retained_socket_directory=socket_dir,
                                  forced_native_kill=False)
            if process is None or process.poll() is not None:
                if process is not None:
                    report['daemon_exit_code'] = process.returncode
                    if process.returncode != 0:
                        report.update(status='FAIL', error='Daemon exited abnormally after probe')
                if socket_path.exists():
                    socket_path.unlink()
                os.rmdir(socket_dir)
    (args.output/'validation.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps(report, indent=2))
    return 0 if report['status'].startswith('PASS_') else 1


if __name__ == '__main__':
    raise SystemExit(main())
