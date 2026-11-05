"""Admit a measured normal PWM model, switch it durably, verify live, or restore."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, '/opt/cabinet/linux')
os.environ['PYTHONPATH'] = '/opt/cabinet/linux'
from normal_npu.baseline_store import durable_atomic, durable_save, persist_candidate
from normal_npu.bundle import Bundle
from normal_npu.learning import environment, Learning
from normal_npu.start_gate import validate_report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--target', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    pin = sha(a.candidate / 'manifest.json')
    bundle = Bundle(a.candidate, pin)
    bundle.hardware_model()
    assert bundle.expected.get('pwm_operating_reference')
    validation = json.loads((a.candidate / 'training_validation.json').read_text())
    assert validation['status'] == 'PASS_REAL_NORMAL_ADVISORY_HOST_TRAINING'
    assert validation['normal_holdout_frames'] >= 600
    assert validation['normal_holdout_alarm_rate'] <= .05
    assert validation['test_used_for_training_selection_or_threshold'] is False
    assert not Learning().busy()
    previous = environment()
    env_path = Path('/etc/cabinet/normal-npu.env')
    old_bytes = env_path.read_bytes()
    durable_atomic(a.output / 'previous.env', old_bytes)
    report = dict(state='PREPARING', manifest_sha256=pin, control_authority='NONE',
                  previous_manifest_sha256=previous['BUNDLE_SHA256'], samples=[])
    switched = False

    def run(args, timeout=120, logfile=None):
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, timeout=timeout)
        if logfile:
            (a.output / logfile).write_text(result.stdout, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Command failed: ' + repr(args[:3]) + ' ' + result.stdout[-1000:])

    try:
        run(['systemctl', 'stop', 'cabinet-normal-npu'])
        assert json.loads(Path('/var/lib/cabinet/npu-lease/lease.json').read_text())['state'] == 'CLEAN'
        os.environ['LD_LIBRARY_PATH'] = '/opt/cabinet/releases/r45_icm_4khz_20261031/sdk/lib'
        run([sys.executable, '-B', '-m', 'normal_npu.probe', '--saved-startup',
             '--bundle', str(a.candidate), '--manifest-sha256', pin,
             '--library', previous['LIBRARY'], '--library-sha256', previous['LIBRARY_SHA256'],
             '--output', str(a.output / 'hardware-probe')], logfile='hardware-probe.log')
        admission = a.output / 'hardware-probe/validation.json'
        hardware = json.loads(admission.read_text())
        validate_report(hardware, pin, previous['LIBRARY_SHA256'],
                        Path('/proc/sys/kernel/random/boot_id').read_text().strip(), os.uname().release)
        persisted = persist_candidate(a.candidate, admission, a.target, pin)
        current = dict(previous, BUNDLE=persisted['bundle_path'], BUNDLE_SHA256=pin,
                       ADMISSION=persisted['admission_path'], ADMISSION_SHA256=persisted['admission_sha256'])
        durable_save(a.output / 'transition.json', dict(state='ADMITTED_CURRENT_CONDITION_TRIAL',
                     candidate_manifest_sha256=pin, previous_env_sha256=sha(a.output / 'previous.env')))
        durable_atomic(env_path, ''.join(k + '=' + current[k] + '\n' for k in sorted(current)).encode())
        switched = True
        run(['systemctl', 'reset-failed', 'cabinet-normal-npu'])
        run(['systemctl', 'start', 'cabinet-normal-npu'], logfile='service-start.log')
        deadline = time.monotonic() + 180
        last = None
        while time.monotonic() < deadline:
            state = json.loads(Path('/run/cabinet-normal-npu/state.json').read_text())
            count = state.get('inference_count')
            if (state.get('model_sha256') == pin and state.get('valid') is True and
                    state.get('baseline_eligible') is True and state.get('status') == 'RUNNING' and
                    0 <= time.monotonic() - state.get('updated_at', -1) < .8):
                if last is not None and count < last:
                    raise RuntimeError('Candidate NPU service restarted')
                if count != last:
                    last = count
                    report['samples'].append({k: state.get(k) for k in
                        ('inference_count', 'frame_id', 'score', 'state', 'assessment', 'execute_ms',
                         'applied_pwm_percent', 'advisory', 'input_values')})
                    if len(report['samples']) >= 512:
                        break
            time.sleep(.05)
        assert len(report['samples']) >= 512, 'Insufficient fresh live NPU results'
        rate = sum(x['state'] != 'BASELINE_MATCH' for x in report['samples']) / len(report['samples'])
        report['live_alarm_rate'] = rate
        assert rate <= .05, 'Current normal condition outside trained baseline: %.3f' % rate
        report.update(state='DEPLOYED_VERIFIED', hardware=hardware, persistence=persisted,
                      startup_policy='LOAD_SAVED_NO_AUTOMATIC_LEARNING')
        durable_save(a.output / 'transition.json', dict(state='COMPLETED', current_env_sha256=sha(env_path),
                     candidate_manifest_sha256=pin, live_frames=len(report['samples']), live_alarm_rate=rate))
    except BaseException as error:
        report.update(state='FAILED_PREVIOUS_MODEL_RESTORED', error=str(error))
        run(['systemctl', 'stop', 'cabinet-normal-npu'])
        assert json.loads(Path('/var/lib/cabinet/npu-lease/lease.json').read_text())['state'] == 'CLEAN'
        if switched:
            durable_atomic(env_path, old_bytes)
        run(['systemctl', 'reset-failed', 'cabinet-normal-npu'])
        run(['systemctl', 'start', 'cabinet-normal-npu'])
        raise
    finally:
        durable_save(a.output / 'deployment.json', report)
        print(json.dumps({k: v for k, v in report.items() if k not in ('samples', 'hardware')},
                         ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
