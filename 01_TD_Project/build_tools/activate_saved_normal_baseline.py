"""Explicitly activate one pinned saved baseline without enabling automatic learning."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, '/opt/cabinet/linux')
from normal_npu.baseline_store import durable_atomic, durable_save, persist_candidate
from normal_npu.bundle import Bundle
from normal_npu.core import live_input
from normal_npu.learning import Learning, environment
from normal_npu.start_gate import validate_report

JOB = '5c119b68ea784df9879f09438c52148a'
PIN = '4edf2cc5d189cd50aa8710167313bb39c2c67725f3fbea9b5562e3b6b474f0a8'
ROOT = Path('/var/lib/cabinet/npu-learning')
OUT = ROOT / 'activations/baseline_20261104_5c119_001'
TARGET = Path('/opt/cabinet/npu/learned/baseline_20261104_5c119_001')
ENV = Path('/etc/cabinet/normal-npu.env')
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(args, name, timeout=100):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True, timeout=timeout)
    (OUT / (name+'.log')).write_text(p.stdout, encoding='utf-8')
    if p.returncode:
        raise RuntimeError(name+': '+p.stdout[-1800:])


def data_pins():
    return {str(p): sha(p) for p in (ROOT/'jobs').glob('*/captures/*/frames.jsonl')}


def main():
    assert Path('/etc/machine-id').read_text().strip() == '843ad8d6299240c898a32874a96fe333'
    assert str(Path('/opt/cabinet/linux').resolve()) == '/opt/cabinet/releases/r46_alarm_only_pwm_p52_20261103/linux'
    assert not (OUT/'deployment.json').exists() and not TARGET.exists()
    store = Learning()
    with (ROOT/'model-switch.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not store.busy(), 'Another learning operation is active'
        assert not Path('/etc/cabinet/labeled-npu.env').exists()
        folder = ROOT/'jobs'/JOB
        job_bytes = (folder/'job.json').read_bytes()
        job = json.loads(job_bytes)
        staged = json.loads((folder/'staged-candidate.json').read_text())
        candidate = Path(staged['bundle_path'])
        assert job['state'] == 'COMPLETED' and staged['status'] == 'TRAINED_SAVED_NOT_DEPLOYED'
        assert staged['manifest_sha256'] == PIN and sha(candidate/'manifest.json') == PIN
        bundle = Bundle(candidate, PIN)
        bundle.hardware_model()
        training = staged['training']
        assert training['status'] == 'PASS_REAL_NORMAL_ADVISORY_HOST_TRAINING'
        assert training['normal_holdout_frames'] >= 600 and training['normal_holdout_alarm_rate'] <= .05
        assert training['test_used_for_training_selection_or_threshold'] is False
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        previous = environment()
        old_bytes = ENV.read_bytes()
        assert previous['BUNDLE_SHA256'] == 'c53958fb53b879ff295078d2b32745a4ec891f12d58b6f009a66d42227f479de'
        configuration = {str(Path('/etc/cabinet')/name): sha(Path('/etc/cabinet')/name)
                         for name in ('edge.json','temperature-pwm.json','capture-contract.json',
                                      'display-calibration.json','npu-deployment-policy.json')}
        captures = data_pins()
        live_input(json.loads(Path('/run/cabinet-live/state.json').read_text()),
                   time.monotonic(), bundle.expected, allow_temperature_pwm=True)
        durable_atomic(OUT/'previous.env', old_bytes)
        durable_save(OUT/'before.json', dict(boot=boot, config_pins=configuration, capture_pins=captures,
                     previous_model=previous['BUNDLE_SHA256'], manifest_sha256=PIN,
                     authorization='USER_EXPLICIT_LOAD_SAVED_BASELINE_ON_SCREEN',
                     global_automatic_activation_changed=False))
        stopped = switched = committed = False
        report = dict(status='PREPARING', manifest_sha256=PIN, samples=[])
        try:
            print('STOPPING_PREVIOUS_NPU_ONLY', flush=True)
            run(['systemctl','stop','cabinet-normal-npu'], 'stop-previous')
            stopped = True
            assert json.loads(Path('/var/lib/cabinet/npu-lease/lease.json').read_text())['state'] == 'CLEAN'
            os.environ['LD_LIBRARY_PATH'] = '/opt/cabinet/releases/r45_icm_4khz_20261031/sdk/lib'
            run([sys.executable,'-B','-m','normal_npu.probe','--saved-startup',
                 '--bundle',str(candidate),'--manifest-sha256',PIN,'--library',previous['LIBRARY'],
                 '--library-sha256',previous['LIBRARY_SHA256'],'--output',str(OUT/'hardware-probe')], 'hardware-probe')
            admission = OUT/'hardware-probe/validation.json'
            hardware = json.loads(admission.read_text())
            validate_report(hardware,PIN,previous['LIBRARY_SHA256'],boot,os.uname().release)
            print('PASS_SAVED_BASELINE_HARDWARE_PROBE', flush=True)
            assert all(sha(p) == pin for p,pin in configuration.items())
            assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
            persistence = persist_candidate(candidate,admission,TARGET,PIN)
            current = dict(previous,BUNDLE=persistence['bundle_path'],BUNDLE_SHA256=PIN,
                           ADMISSION=persistence['admission_path'],ADMISSION_SHA256=persistence['admission_sha256'])
            durable_save(OUT/'transition.json', dict(status='CURRENT_CONDITION_TRIAL',
                         manifest_sha256=PIN, previous_env_sha256=sha(OUT/'previous.env')))
            durable_atomic(ENV, ''.join(k+'='+current[k]+'\n' for k in sorted(current)).encode())
            switched = True
            run(['systemctl','reset-failed','cabinet-normal-npu'], 'reset-failed')
            run(['systemctl','start','cabinet-normal-npu'], 'start-saved')
            start = time.monotonic()
            last = None
            while time.monotonic()-start < 150:
                n = json.loads(Path('/run/cabinet-normal-npu/state.json').read_text())
                count = n.get('inference_count')
                if (n.get('model_sha256') == PIN and n.get('status') == 'RUNNING' and n.get('valid') is True
                        and n.get('baseline_eligible') is True and 0 <= time.monotonic()-n.get('updated_at',0) < .8):
                    if last is not None and count < last:
                        raise RuntimeError('New model service restarted during validation')
                    if count != last:
                        last = count
                        report['samples'].append({k:n.get(k) for k in ('inference_count','frame_id','score','state',
                            'assessment','execute_ms','advisory','applied_pwm_percent')})
                        if len(report['samples']) % 128 == 0:
                            print('LIVE_RESULTS '+str(len(report['samples'])),flush=True)
                        if len(report['samples']) >= 512: break
                time.sleep(.05)
            assert len(report['samples']) >= 512, 'Not enough fresh inferences'
            rate = sum(s['state'] != 'BASELINE_MATCH' for s in report['samples']) / len(report['samples'])
            assert rate <= .05, 'Current-condition deviation rate %.4f exceeds acceptance'%rate
            assert all(sha(p) == pin for p,pin in configuration.items()), 'Unrelated settings changed'
            assert data_pins() == captures, 'Raw capture files changed'
            assert sha(folder/'job.json') == hashlib.sha256(job_bytes).hexdigest(), 'Source job changed'
            result = dict(status='DEPLOYED_REAL_NORMAL_NPU', deployed=True,saved=True,saved_on_sd=True,
                          model_id=bundle.manifest['model_id'],manifest_sha256=PIN,
                          previous_model_sha256=previous['BUNDLE_SHA256'],persistence=persistence,
                          hardware_probe=hardware['status'],hardware_irq=hardware['irq_delta'],
                          live_results=len(report['samples']),live_deviation_rate=rate,
                          startup_policy='LOAD_SAVED_NO_AUTOMATIC_LEARNING',
                          activation_reason='USER_EXPLICIT_LOAD_SAVED_BASELINE_ON_SCREEN',
                          automatic_activation_changed=False,controls_changed=False,raw_capture_files_preserved=len(captures))
            report.update(result)
            durable_save(OUT/'deployment.json',report)
            durable_save(OUT/'transition.json',dict(status='COMPLETED',manifest_sha256=PIN,current_env_sha256=sha(ENV)))
            # Retain the original staged record and all capture provenance.
            durable_atomic(OUT/'source-job-before.json',job_bytes)
            with store.lock():
                assert sha(folder/'job.json') == hashlib.sha256(job_bytes).hexdigest()
                job.update(result=dict(staged,**result),progress_detail='已按用户指令启用 SD 保存基线',
                           activation_receipt=str(OUT/'deployment.json'),updated_at=time.monotonic())
                durable_save(folder/'job.json',job)
            committed = True
            os.sync()
            print(json.dumps(result,ensure_ascii=False),flush=True)
        except BaseException as error:
            if committed: raise
            report.update(status='FAILED_PREVIOUS_MODEL_RESTORED',error=str(error))
            if stopped:
                if switched: run(['systemctl','stop','cabinet-normal-npu'],'stop-candidate')
                assert json.loads(Path('/var/lib/cabinet/npu-lease/lease.json').read_text())['state'] == 'CLEAN'
                durable_atomic(ENV,old_bytes)
                run(['systemctl','reset-failed','cabinet-normal-npu'],'reset-previous')
                run(['systemctl','start','cabinet-normal-npu'],'restore-previous')
            durable_save(OUT/'failure.json',report)
            print(json.dumps({'status':report['status'],'error':str(error)},ensure_ascii=False),flush=True)
            raise


if __name__ == '__main__': main()
