#!/usr/bin/env python3
"""Automatic Mac training worker. SSH keys, pinned board identity, no manual export."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tarfile
import threading
import time
import uuid
if __package__:
    from .utf8_io import configure_stdio
else:
    from utf8_io import configure_stdio

HERE=Path(__file__).resolve().parent

class TransportError(RuntimeError):pass

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    temp=p.with_suffix('.next');temp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n', encoding='utf-8');os.replace(temp,p)


class Worker:
    def __init__(self, host, alias, root, python, machine):
        self.host,self.alias,self.root,self.python,self.machine=host,alias,Path(root),python,machine
        self.identity=uuid.uuid4().hex;self.stop=threading.Event()
        control=Path.home()/'Library/Caches/CabinetCooling/ssh';control.mkdir(parents=True,exist_ok=True,mode=0o700)
        if control.is_symlink() or control.stat().st_uid!=os.getuid():raise ValueError('Private SSH control directory required')
        control.chmod(0o700)
        socket_path=control/('c-'+hashlib.sha256((host+alias).encode('utf-8')).hexdigest()[:16])
        self.options=['-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','HostKeyAlias='+alias,
                      '-o','ConnectTimeout=10','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2',
                      '-o','ControlMaster=auto','-o','ControlPersist=60','-o','ControlPath='+str(socket_path)]
        self.target='root@'+host
        self.remote='cd /opt/cabinet/linux && test "$(cat /etc/machine-id)" = '+shlex.quote(machine)+' && /usr/bin/python3 -B npu_learning_cli.py'
        self.root.mkdir(parents=True,exist_ok=True)

    def call(self,operation,timeout=25,channel='normal',**body):
        if channel not in ('normal','labeled'):raise ValueError('Unknown learning channel')
        remote=self.remote if channel=='normal' else self.remote.removesuffix('npu_learning_cli.py')+'labeled_learning_cli.py'
        data=json.dumps(dict(operation=operation,worker_id=self.identity,**body))
        failure=None
        for attempt in range(4):
            try:
                r=subprocess.run(['ssh']+self.options+[self.target,remote],input=data,
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=timeout, encoding='utf-8')
                if r.returncode==255:raise TransportError('Board SSH interrupted: '+r.stderr[-300:])
                try:result=json.loads(r.stdout)
                except ValueError:raise TransportError('Board RPC response unavailable: '+r.stderr[-300:])
                if r.returncode or not result.get('ok'):raise RuntimeError(result.get('error','Board RPC failed'))
                return result['result']
            except (subprocess.TimeoutExpired,TransportError) as e:
                failure=e
                if attempt<3:self.stop.wait(3)
        raise TransportError('Board connection did not recover within bounded retries: '+str(failure))

    def heartbeat(self):
        while not self.stop.is_set():
            try:
                self.call('heartbeat')
                self.call('heartbeat',channel='labeled')
            except Exception as e: save(self.root/'connection.json',dict(state='OFFLINE',error=str(e),at=time.time()))
            else: save(self.root/'connection.json',dict(state='ONLINE',host=self.host,at=time.time()))
            self.stop.wait(12)

    def copy(self,source,dest):
        failure=None
        for attempt in range(4):
            try:
                r=subprocess.run(['scp','-O']+self.options+[source,dest],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                 universal_newlines=True,timeout=120, encoding='utf-8')
                if not r.returncode:return
                if r.returncode!=255 and not any(s in r.stderr.lower() for s in ('connection','broken pipe','timed out')):
                    raise RuntimeError('Automatic data transfer refused: '+r.stderr[-700:])
                failure=r.stderr[-500:]
            except subprocess.TimeoutExpired as e:failure=str(e)
            if attempt<3:self.stop.wait(3)
        raise TransportError('Automatic data transfer did not recover: '+str(failure))

    def train(self,script,args,log,identity,channel='normal'):
        env=os.environ.copy();env['PYTHONPATH']=str(HERE.parent/'linux')
        env['PYTHONIOENCODING']='utf-8'
        env['PYTHONOPTIMIZE']='0'
        env['OMP_NUM_THREADS']='2';env['OPENBLAS_NUM_THREADS']='2'
        with log.open('w', encoding='utf-8') as stream:
            proc=subprocess.Popen([self.python,str(HERE/script)]+args,stdout=stream,stderr=subprocess.STDOUT,env=env)
            started=time.monotonic();checked=started
            try:
                while proc.poll() is None:
                    if self.stop.wait(.5) or time.monotonic()-started>600: raise RuntimeError('Training stopped or timed out')
                    if time.monotonic()-checked>5:
                        self.call('check',job_id=identity,channel=channel);checked=time.monotonic()
            except BaseException:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                raise
        if proc.returncode:
            report=Path(args[args.index('--output')+1])/'training_validation.json' if '--output' in args else None
            if script=='train_normal.py' and report and report.is_file():
                validation=json.loads(report.read_text(encoding='utf-8'))
                if validation['status']=='FAIL_QUANTIZED_LEARNING_GAIN':
                    comparison=validation['quantized_reconstruction_comparison']
                    def gain(value):return '不可计算' if value is None else '%.2f%%'%(value*100)
                    raise RuntimeError('学习效果未达标：校验改善 %s，独立测试改善 %s，均需超过 10%%。原模型已保留，请保持工况稳定后重试。'%(
                        gain(comparison['calibration']['improvement_fraction']),gain(comparison['independent_test']['improvement_fraction'])))
                if validation['status']=='FAIL_NORMAL_HOLDOUT_FALSE_ALARM':
                    raise RuntimeError('独立正常测试误报率 %.2f%%，超过 5%% 门限。原模型已保留，详细训练记录已保存。'%(validation['normal_holdout_alarm_rate']*100))
            raise RuntimeError(script+' failed: '+log.read_text(encoding='utf-8')[-1200:])

    @staticmethod
    def extract_capture(archive,data,splits):
        allowed={'sessions.json','learning.json','captures'}
        for split in splits:
            allowed.add('captures/'+split)
            allowed.update('captures/'+split+'/'+name for name in ('session.json','feature_contract.json','frames.jsonl','summary.json'))
        with tarfile.open(archive,'r:gz') as tar:
            members=tar.getmembers()
            if len({m.name for m in members})!=len(members) or any(m.name not in allowed or not (m.isfile() or m.isdir()) for m in members):
                raise ValueError('Unexpected capture export member')
            if sum(m.size for m in members)>128*1024*1024:raise ValueError('Capture export size limit')
            for m in members:
                dest=data/m.name
                if m.isdir():dest.mkdir(parents=True,exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    with tar.extractfile(m) as src,dest.open('xb') as dst:__import__('shutil').copyfileobj(src,dst)

    def calibration_precheck(self,identity,folder):
        exported=self.call('export-calibration-check',job_id=identity)
        prefix='/var/lib/cabinet/npu-learning/jobs/'+identity+'/prechecks/'
        remote=exported['path']
        if not remote.startswith(prefix) or not remote.endswith('/captures.tar.gz'):
            raise ValueError('Unexpected calibration precheck export path')
        index=remote[len(prefix):-len('/captures.tar.gz')]
        if not index.isdigit() or str(int(index))!=index or int(index)<1 or exported['report_path']!=prefix+index+'/report.json':
            raise ValueError('Unexpected calibration precheck identity')
        attempt=folder/'prechecks'/index;attempt.mkdir(parents=True,exist_ok=False,mode=0o700)
        archive=attempt/'captures.tar.gz';self.copy(self.target+':'+remote,str(archive))
        if sha(archive)!=exported['sha256']:raise ValueError('Calibration capture transfer checksum failed')
        data=attempt/'data';data.mkdir()
        self.extract_capture(archive,data,('train','calibration'))
        output=attempt/'quality'
        self.train('check_normal_calibration.py',['--capture-root',str(data),'--output',str(output)],attempt/'quality.log',identity)
        report=output/'report.json';decision=json.loads(report.read_text(encoding='utf-8'))
        if decision.get('status') not in ('PASS_CALIBRATION_INPUT_QUALITY','RETRY_CALIBRATION_TRANSIENT','REVIEW_CONDITION_REQUIRED') or decision.get('test_read') is not False:
            raise ValueError('Calibration input precheck refused')
        self.copy(str(report),self.target+':'+exported['report_path'])
        result=self.call('calibration-check-result',job_id=identity,report_sha256=sha(report))
        save(attempt/'board-result.json',result)
        return decision['status']

    def job(self,j):
        identity=j['id'];folder=self.root/identity;folder.mkdir(mode=0o700,exist_ok=False)
        save(folder/'request.json',j)
        try:
            for split in ('train','calibration','test'):
                self.call('capture-begin',job_id=identity,split=split)
                while True:
                    while True:
                        self.stop.wait(3)
                        if self.stop.is_set(): raise RuntimeError('Worker stopping')
                        state=self.call('capture-poll',job_id=identity)
                        save(folder/'progress.json',state)
                        if state['state']=='CAPTURE_SAVED': break
                    if split=='calibration' and self.calibration_precheck(identity,folder)=='RETRY_CALIBRATION_TRANSIENT':continue
                    break
            exported=self.call('export',job_id=identity)
            expected='/var/lib/cabinet/npu-learning/jobs/'+identity+'/captures.tar.gz'
            if exported['path']!=expected: raise ValueError('Unexpected capture export path')
            archive=folder/'captures.tar.gz';self.copy(self.target+':'+expected,str(archive))
            if sha(archive)!=exported['sha256']: raise ValueError('Capture transfer checksum failed')
            data=folder/'data';data.mkdir()
            self.extract_capture(archive,data,('train','calibration','test'))
            self.train('train_normal.py',['--capture-root',str(data),'--output',str(folder/'reference'),'--filter-invalid-diagnostic'],folder/'training.log',identity)
            self.train('compile_alnpu_bundle.py',['--reference',str(folder/'reference'),'--output',str(folder/'candidate')],folder/'compile.log',identity)
            candidate=folder/'candidate';receipt=json.loads((candidate/'receipt.json').read_text(encoding='utf-8'))
            with tarfile.open(folder/'candidate.tar.gz','w:gz') as output:
                names=set(json.loads((candidate/'manifest.json').read_text(encoding='utf-8'))['artifacts_sha256'])
                names.update(('manifest.json','training_validation.json','receipt.json'))
                for name in sorted(names): output.add(candidate/name,arcname=name)
            self.call('host-validated',job_id=identity)
            self.copy(str(folder/'candidate.tar.gz'),self.target+':/var/lib/cabinet/npu-learning/jobs/'+identity+'/candidate.tar.gz')
            self.call('deploy-start',job_id=identity,archive_sha256=sha(folder/'candidate.tar.gz'),manifest_sha256=receipt['manifest_sha256'])
            deadline=time.monotonic()+480
            while True:
                try:result=self.call('deployment-status',job_id=identity)
                except Exception:
                    if time.monotonic()>deadline:raise
                    self.stop.wait(3);continue
                if result['state']=='COMPLETED':break
                if result['state'] in ('FAILED','INTERRUPTED','CANCELLED','RECOVERY_REQUIRED'):raise RuntimeError(result.get('error',result['state']))
                if time.monotonic()>deadline:raise RuntimeError('Board deployment deadline exceeded; inspect durable board transaction')
                self.stop.wait(3)
            save(folder/'result.json',result)
        except Exception as error:
            save(folder/'failure.json',dict(error=str(error),at=time.time()))
            try: self.call('failed',job_id=identity,error=str(error))
            except Exception as reporting: save(folder/'reporting-failure.json',dict(error=str(reporting)))
            print('LEARNING_FAILED '+identity+' '+str(error),flush=True)
        else: print('LEARNING_COMPLETED '+identity,flush=True)

    def run(self,once=False,gateway_port=None):
        with (self.root/'worker.lock').open('a', encoding='utf-8') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.call('heartbeat')
            self.call('heartbeat',channel='labeled')
            gateway=None
            if gateway_port:
                if __package__:
                    from .gateway import serve
                else:
                    from gateway import serve
                gateway=serve(self,gateway_port,gateway_port+1)
            thread=threading.Thread(target=self.heartbeat,daemon=True);thread.start()
            try:
                while not self.stop.is_set():
                    if gateway and self.tunnel.poll() is not None:self.tunnel=self.start_tunnel()
                    for pending in self.root.glob('*/reporting-failure.json'):
                        request=json.loads((pending.parent/'request.json').read_text(encoding='utf-8'))
                        if request.get('worker_id')!=self.identity:continue
                        try:
                            result=self.call('failed',job_id=request['id'],error=json.loads((pending.parent/'failure.json').read_text(encoding='utf-8'))['error'],channel='labeled' if request.get('kind')=='labeled_classifier' else 'normal')
                            save(pending.parent/'remote_final.json',result)
                            pending.rename(pending.with_name('failure-reported.json'))
                        except Exception:pass
                    try:
                        j=self.call('claim')
                        if not j:j=self.call('claim',channel='labeled')
                    except Exception as e:
                        print('LEARNING_WAIT '+str(e),flush=True);j=None
                    if j:
                        if j.get('kind')=='labeled_classifier':
                            if __package__:
                                from .worker_labeled import run_labeled_job
                            else:
                                from worker_labeled import run_labeled_job
                            run_labeled_job(self,j)
                        else:self.job(j)
                    if once and j: break
                    self.stop.wait(3)
            finally:
                self.stop.set();thread.join(timeout=26)
                if gateway:gateway.shutdown();gateway.server_close();self.tunnel.terminate();self.tunnel.wait(timeout=5)


def main():
    configure_stdio()
    p=argparse.ArgumentParser();p.add_argument('--host',required=True);p.add_argument('--host-key-alias',required=True)
    p.add_argument('--machine-id',required=True);p.add_argument('--jobs',type=Path,required=True)
    p.add_argument('--python',default=sys.executable);p.add_argument('--once',action='store_true')
    p.add_argument('--gateway-port',type=int);a=p.parse_args()
    worker=Worker(a.host,a.host_key_alias,a.jobs,a.python,a.machine_id)
    for number in (signal.SIGTERM,signal.SIGINT):signal.signal(number,lambda *_:worker.stop.set())
    worker.run(a.once,a.gateway_port)

if __name__=='__main__': main()
