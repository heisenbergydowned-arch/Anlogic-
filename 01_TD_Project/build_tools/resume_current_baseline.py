"""Resume only the recorded host-startup failure, preserving both real captures."""
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time

HOST = Path('/Users/heisenberg/Documents/Codex/cabinet-cooling/fpga_work/adc_reset_w9_20261023/release_r46_truthful_20261101/software_candidates/learning_control_p26_20261103/host')
sys.path.insert(0, str(HOST))
from worker import Worker, sha, save

IDENTITY = '69e0862f7b1d4ea0bde75865e210b4c7'
ROOT = Path('/Users/heisenberg/Library/Application Support/CabinetCooling/npu-learning')
folder = ROOT / IDENTITY
original = json.loads((folder/'request.json').read_text())
w = Worker('192.168.0.112', '192.168.0.127', ROOT, sys.executable,
           '843ad8d6299240c898a32874a96fe333')
# The original worker remains responsible for heartbeats and the web gateway.
# It only claims QUEUED jobs. This explicit driver resumes this one failed job.
w.identity = original['worker_id']

repair = r'''
import json,time
from normal_npu.learning import Learning,save,sha
s=Learning();identity='69e0862f7b1d4ea0bde75865e210b4c7';folder=s.folder(identity)
with s.lock():
 j=json.loads((folder/'job.json').read_text())
 assert j['state']=='FAILED' and 'PermissionError: [Errno 1] Operation not permitted' in j['error']
 assert 'init_import_site' in j['error'] and 'check_normal_calibration.py' in j['error']
 assert set(j['sessions'])=={'train','calibration'} and not j.get('recording_session_id')
 assert not s.busy() and s.clock()-j['created_at']<1800 and not j['cancel_requested']
 assert j['calibration_precheck']['decision'] is None
 s.check(j)
 for split in ('train','calibration'):
  p=folder/'captures'/split;summary=json.loads((p/'summary.json').read_text())
  assert all(sha(p/n)==h for n,h in summary['files_sha256'].items())
 save(folder/'host-startup-failure.json',j)
 j['host_startup_recovery']={'reason':'Explicit continuation in accessible host Python runtime',
  'previous_error':j.pop('error'),'resumed_at':s.clock(),'captures_reused':['train','calibration']}
 j.update(state='CAPTURE_SAVED',updated_at=s.clock())
 save(folder/'job.json',j)
 print(json.dumps({'state':j['state'],'job':identity,'captures_reused':list(j['sessions'])}))
'''
r = subprocess.run(['ssh']+w.options+[w.target, 'cd /opt/cabinet/linux && python3 -'],
                   input=repair, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
if r.returncode:
    raise RuntimeError(r.stderr+r.stdout)
print(r.stdout.strip(), flush=True)

def wait_capture():
    last = None
    while True:
        time.sleep(3)
        state = w.call('capture-poll', job_id=IDENTITY)
        save(folder/'progress.json', state)
        marker = (state['state'], state.get('progress_percent'))
        if marker != last:
            print(json.dumps(dict(state=marker[0], progress_percent=marker[1])), flush=True)
            last = marker
        if state['state']=='CAPTURE_SAVED':
            return

try:
    exported = w.call('export-calibration-check', job_id=IDENTITY)
    attempt = folder/'prechecks'/str(original.get('calibration_precheck', {}).get('index', 1))
    assert sha(attempt/'captures.tar.gz')==exported['sha256']
    output = attempt/'quality-startup-retry'
    w.train('check_normal_calibration.py', ['--capture-root', str(attempt/'data'), '--output', str(output)],
            attempt/'quality-startup-retry.log', IDENTITY)
    report = output/'report.json'
    decision = json.loads(report.read_text())
    w.copy(str(report), w.target+':'+exported['report_path'])
    w.call('calibration-check-result', job_id=IDENTITY, report_sha256=sha(report))
    print(json.dumps({'calibration':decision['status']}), flush=True)
    while decision['status']=='RETRY_CALIBRATION_TRANSIENT':
        wait_capture()
        decision = {'status':w.calibration_precheck(IDENTITY, folder)}
    assert decision['status']=='PASS_CALIBRATION_INPUT_QUALITY'
    w.call('capture-begin', job_id=IDENTITY, split='test')
    wait_capture()
    exported = w.call('export', job_id=IDENTITY)
    expected = '/var/lib/cabinet/npu-learning/jobs/'+IDENTITY+'/captures.tar.gz'
    assert exported['path']==expected
    archive=folder/'captures.tar.gz';w.copy(w.target+':'+expected,str(archive))
    assert sha(archive)==exported['sha256']
    data=folder/'data';data.mkdir();w.extract_capture(archive,data,('train','calibration','test'))
    print('TRAINING',flush=True)
    w.train('train_normal.py',['--capture-root',str(data),'--output',str(folder/'reference'),
                              '--filter-invalid-diagnostic'],folder/'training.log',IDENTITY)
    w.train('compile_alnpu_bundle.py',['--reference',str(folder/'reference'),'--output',str(folder/'candidate')],
            folder/'compile.log',IDENTITY)
    candidate=folder/'candidate';receipt=json.loads((candidate/'receipt.json').read_text())
    with tarfile.open(folder/'candidate.tar.gz','w:gz') as output:
        names=set(json.loads((candidate/'manifest.json').read_text())['artifacts_sha256'])
        names.update(('manifest.json','training_validation.json','receipt.json'))
        for name in sorted(names):output.add(candidate/name,arcname=name)
    w.call('host-validated',job_id=IDENTITY)
    w.copy(str(folder/'candidate.tar.gz'),w.target+':/var/lib/cabinet/npu-learning/jobs/'+IDENTITY+'/candidate.tar.gz')
    w.call('deploy-start',job_id=IDENTITY,archive_sha256=sha(folder/'candidate.tar.gz'),manifest_sha256=receipt['manifest_sha256'])
    deadline=time.monotonic()+480;last=None
    while time.monotonic()<deadline:
        result=w.call('deployment-status',job_id=IDENTITY)
        if result['state']!=last:
            print(result['state'],flush=True);last=result['state']
        if result['state']=='COMPLETED':
            save(folder/'result.json',result)
            print(json.dumps(result['result'],ensure_ascii=False),flush=True)
            break
        if result['state'] in ('FAILED','INTERRUPTED','CANCELLED','RECOVERY_REQUIRED'):
            raise RuntimeError(result.get('error',result['state']))
        time.sleep(3)
    else:raise RuntimeError('Deployment deadline exceeded')
except BaseException as error:
    save(folder/'startup-recovery-failure.json',dict(error=str(error),at=time.time()))
    w.call('failed',job_id=IDENTITY,error=str(error))
    raise
