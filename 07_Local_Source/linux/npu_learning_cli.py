#!/usr/bin/env python3
"""Private SSH worker protocol; the web cannot submit paths or shell commands."""
import json
import os
from pathlib import Path
import subprocess
import sys
from normal_npu.learning import Learning,save

def process_alive(store,folder):
    try:
        p=json.loads((folder/'deployment-process.json').read_text(encoding='utf-8'))
        fields=Path('/proc/%d/stat'%p['pid']).read_text().rsplit(')',1)[1].split()
        return p['boot_id']==store.boot() and fields[0]!='Z' and fields[19]==p['start_ticks']
    except (OSError,ValueError,KeyError):return False

def launch(store,body):
    identity,worker=body['job_id'],body['worker_id'];folder=store.folder(identity)
    with store.lock():
        j=json.loads((folder/'job.json').read_text(encoding='utf-8'))
        if j.get('worker_id')!=worker:raise ValueError('Deployment job owner changed')
        from normal_npu.staging import activation_allowed, stage_candidate
        if not activation_allowed(j):
            return stage_candidate(store,j,body['archive_sha256'],body['manifest_sha256'])
        if (folder/'deploy-request.json').exists():
            if json.loads((folder/'deploy-request.json').read_text(encoding='utf-8'))!=dict(body,operation='deploy'):
                raise ValueError('Deployment retry pins changed')
            if j['state']=='COMPLETED':return dict(state='COMPLETED')
            if process_alive(store,folder):return dict(state='BOARD_DEPLOYMENT_RUNNING')
        j=store.owned(identity,worker);store.check(j)
        if j['state']!='HOST_VALIDATED':raise ValueError('Host validation required before deployment')
        if (folder/'deploy-request.json').exists():raise ValueError('Previous deploy process ended; inspect transaction')
        request=dict(body,operation='deploy')
        save(folder/'deploy-request.json',request)
        with (folder/'deployment-process.log').open('a') as log:
            p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--request-file',str(folder/'deploy-request.json')],
                stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        fields=Path('/proc/%d/stat'%p.pid).read_text().rsplit(')',1)[1].split()
        save(folder/'deployment-process.json',dict(pid=p.pid,start_ticks=fields[19],boot_id=store.boot()))
    return dict(state='BOARD_DEPLOYMENT_STARTED')

def main():
    if len(sys.argv)==3 and sys.argv[1]=='--request-file':
        path=Path(sys.argv[2]);body=json.loads(path.read_text(encoding='utf-8'))
        if path!=Learning().folder(body['job_id'])/'deploy-request.json' or path.is_symlink():raise ValueError('Fixed private deployment request required')
    elif len(sys.argv)==1:body=json.loads(sys.stdin.buffer.read(16385).decode('utf-8'))
    else:raise ValueError('Unknown command line')
    if type(body) is not dict: raise ValueError('Object required')
    operation=body.pop('operation');store=Learning()
    if operation=='heartbeat': result=store.heartbeat(body['worker_id'])
    elif operation=='claim': result=store.claim(body['worker_id'])
    elif operation=='status': result=store.status()
    elif operation=='capture-begin': result=store.capture_begin(body['job_id'],body['worker_id'],body['split'])
    elif operation=='capture-poll': result=store.capture_poll(body['job_id'],body['worker_id'])
    elif operation=='export': result=store.export(body['job_id'],body['worker_id'])
    elif operation=='export-calibration-check': result=store.export_calibration_check(body['job_id'],body['worker_id'])
    elif operation=='calibration-check-result': result=store.calibration_check_result(body['job_id'],body['worker_id'],body['report_sha256'])
    elif operation=='failed': result=store.fail(body['job_id'],body['worker_id'],body['error'])
    elif operation=='check':
        j=store.owned(body['job_id'],body['worker_id']);store.check(j);result=dict(state=j['state'])
    elif operation=='host-validated':
        j=store.owned(body['job_id'],body['worker_id']);store.check(j)
        if j['state'] not in ('TRAINING','HOST_VALIDATED'): raise ValueError('Invalid host validation transition')
        result=store.update(body['job_id'],body['worker_id'],state='HOST_VALIDATED',progress_percent=80)
    elif operation=='deploy':
        from normal_npu.learning_deploy import deploy
        try:result=deploy(store,body['job_id'],body['worker_id'],body['archive_sha256'],body['manifest_sha256'])
        except Exception as e:
            store.fail(body['job_id'],body['worker_id'],str(e));raise
    elif operation=='deploy-start':result=launch(store,body)
    elif operation=='deployment-status':
        folder=store.folder(body['job_id']);result=json.loads((folder/'job.json').read_text(encoding='utf-8'))
        if result.get('worker_id')!=body['worker_id']:raise ValueError('Different deployment worker')
        if result['state'] not in ('COMPLETED','FAILED','INTERRUPTED','CANCELLED') and not process_alive(store,folder):
            result=store.fail(body['job_id'],body['worker_id'],'BOARD_DEPLOYMENT_PROCESS_ENDED_WITHOUT_COMPLETION')
    else: raise ValueError('Unknown worker operation')
    sys.stdout.buffer.write((json.dumps(dict(ok=True,result=result),ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8'))

if __name__=='__main__':
    try: main()
    except Exception as error:
        sys.stdout.buffer.write((json.dumps(dict(ok=False,error=str(error)),ensure_ascii=False)+'\n').encode('utf-8'));sys.exit(1)
