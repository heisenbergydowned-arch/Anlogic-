#!/usr/bin/env python3
"""Private automatic worker protocol for user-declared labelled episodes."""
import json
import sys
from labeled_npu.learning import Learning

def dispatch(store, body):
    if type(body) is not dict: raise ValueError('Object required')
    body=dict(body);operation=body.pop('operation')
    if operation=='heartbeat': return store.heartbeat(body['worker_id'])
    if operation=='claim': return store.claim(body['worker_id'])
    if operation=='status': return store.status()
    if operation=='capture-begin': return store.capture_begin(body['job_id'],body['worker_id'],body.get('split','episode'))
    if operation=='capture-poll': return store.capture_poll(body['job_id'],body['worker_id'])
    if operation=='export': return store.export(body['job_id'],body['worker_id'])
    if operation=='failed': return store.fail(body['job_id'],body['worker_id'],body['error'])
    if operation=='check':
        j=store.owned(body['job_id'],body['worker_id']);store.check(j);return dict(state=j['state'])
    if operation=='finalize-collection': return store.finalize_collection(body['job_id'],body['worker_id'],body['corpus_summary'])
    if operation=='host-validated':
        j=store.owned(body['job_id'],body['worker_id']);store.check(j)
        if j['state'] not in ('TRAINING','HOST_VALIDATED'): raise ValueError('Invalid host validation transition')
        return store.update(body['job_id'],body['worker_id'],state='HOST_VALIDATED',progress_percent=80)
    if operation=='deploy-start':
        from labeled_npu.deploy import launch
        return launch(store,body['job_id'],body['worker_id'],body['archive_sha256'],body['manifest_sha256'])
    if operation=='deployment-status':
        from labeled_npu.deploy import status
        j=json.loads((store.folder(body['job_id'])/'job.json').read_text(encoding='utf-8'))
        if j.get('worker_id')!=body['worker_id'] or not store.accepts(j): raise ValueError('Different deployment worker or channel')
        return status(store,body['job_id'],body['worker_id'])
    raise ValueError('Unknown worker operation')

def main():
    if len(sys.argv)!=1: raise ValueError('Unknown command line')
    raw=sys.stdin.buffer.read(65537)
    if len(raw)>65536: raise ValueError('Worker request too large')
    result=dispatch(Learning(),json.loads(raw.decode('utf-8')))
    sys.stdout.buffer.write((json.dumps(dict(ok=True,result=result),ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8'))

if __name__=='__main__':
    try: main()
    except Exception as error:
        sys.stdout.buffer.write((json.dumps(dict(ok=False,error=str(error)),ensure_ascii=False)+'\n').encode('utf-8'));sys.exit(1)
