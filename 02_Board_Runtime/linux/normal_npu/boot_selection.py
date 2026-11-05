"""Select an accepted saved baseline before startup, without capture or service calls.

Only an identified, same-boot deployment owner may start a pending candidate
for its existing live-validation gate. A new boot restores the last accepted
selection under the job/switch locks and the reviewed native recovery gate.
"""
import contextlib
import copy
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import time
from types import SimpleNamespace
import uuid

from .baseline_store import (_environment, _validated, _regular, file_sha,
                             durable_atomic, durable_save)
from .start_gate import validate_report
from v4_runtime.native_lease import NATIVE_LEASE_FILE

ENV=Path('/etc/cabinet/normal-npu.env')
ROOT=Path('/var/lib/cabinet/npu-learning')
PROC=Path('/proc')
SELFTEST=Path('/run/cabinet-normal-npu/selftest.json')
ID=re.compile('[0-9a-f]{32}')
PENDING=('PREPARED_SWITCH','SWITCHED_AWAITING_LIVE')
ARGUMENTS={'BUNDLE':'bundle','BUNDLE_SHA256':'manifest_sha256','LIBRARY':'library',
           'LIBRARY_SHA256':'library_sha256','ADMISSION':'admission','ADMISSION_SHA256':'admission_sha256'}


def _read(path):
    _regular(path,2*1024*1024)
    result=json.loads(Path(path).read_text(encoding='utf-8'))
    if type(result) is not dict:raise ValueError('START_SELECTION_OBJECT_REQUIRED')
    return result


def _boot(proc):
    value=(proc/'sys/kernel/random/boot_id').read_text().strip()
    if str(uuid.UUID(value))!=value:raise ValueError('START_SELECTION_BOOT_INVALID')
    return value


def _arguments_match(args,env,complete=False):
    for key,name in ARGUMENTS.items():
        if not complete and key.startswith('ADMISSION'):continue
        if str(getattr(args,name,None))!=env[key]:raise ValueError('START_SELECTION_ARGV_ENV_MISMATCH')


@contextlib.contextmanager
def _lock(path,wait=False):
    if path.parent.is_symlink() or not path.parent.is_dir():raise ValueError('START_SELECTION_LOCK_DIRECTORY')
    fd=os.open(str(path),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o022):
            raise ValueError('START_SELECTION_LOCK_UNSAFE')
        end=time.monotonic()+3
        while True:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);held=True;break
            except BlockingIOError:
                if not wait:held=False;break
                if time.monotonic()>=end:raise ValueError('START_SELECTION_JOB_LOCK_BUSY')
                time.sleep(.025)
        yield held,info
    finally:os.close(fd)


def _selected_job(env,env_pin,root):
    identity=Path(env['BUNDLE']).parent.name
    if not ID.fullmatch(identity):return None
    folder=root/'jobs'/identity
    if root.is_symlink() or (root/'jobs').is_symlink() or folder.is_symlink():raise ValueError('START_SELECTION_JOB_DIRECTORY')
    job=_read(folder/'job.json');transaction=_read(folder/'switch.json')
    if (job.get('id')!=identity or job.get('kind') not in (None,'normal') or
            transaction.get('candidate_manifest_sha256')!=env['BUNDLE_SHA256'] or
            transaction.get('current_env_sha256')!=env_pin):
        raise ValueError('START_SELECTION_TRANSACTION_MISMATCH')
    return folder,job,transaction


def _committed(folder,transaction):
    if transaction.get('state')!='COMPLETED':raise ValueError('PREVIOUS_SELECTION_NOT_ACCEPTED')
    if transaction.get('commit_protocol')=='durable-normal-model-v1':
        deployment=folder/'deployment.json';_regular(deployment,2*1024*1024)
        if transaction.get('deployment_sha256')!=file_sha(deployment):raise ValueError('COMMITTED_SELECTION_EVIDENCE_CHANGED')


def _online_owner(folder,job,boot,proc,lock_info):
    if (job.get('state')!='DEPLOYING' or job.get('context',{}).get('os_boot_id')!=boot or
            job.get('cancel_requested') is not False or not ID.fullmatch(str(job.get('worker_id')))):
        raise ValueError('PENDING_SELECTION_HAS_NO_CURRENT_DEPLOYMENT')
    owner=_read(folder/'deployment-process.json');request=_read(folder/'deploy-request.json')
    pid=owner.get('pid')
    if (type(pid) is not int or pid<=1 or owner.get('boot_id')!=boot or
            request.get('operation')!='deploy' or request.get('job_id')!=job['id'] or
            request.get('worker_id')!=job['worker_id'] or request.get('manifest_sha256')!=job['candidate_pin']):
        raise ValueError('PENDING_SELECTION_DEPLOYMENT_IDENTITY')
    fields=(proc/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
    command=(proc/str(pid)/'cmdline').read_bytes().split(b'\0')
    expected=str(folder/'deploy-request.json').encode()
    script=str(Path(__file__).resolve().parents[1]/'npu_learning_cli.py').encode()
    position=command.index(b'--request-file') if b'--request-file' in command else -1
    if (len(fields)<20 or fields[0]=='Z' or fields[19]!=owner.get('start_ticks') or
            position<1 or position+1>=len(command) or command[position-1]!=script or command[position+1]!=expected):
        raise ValueError('PENDING_SELECTION_DEPLOYMENT_PROCESS_CHANGED')
    expected_lock=(pid,os.major(lock_info.st_dev),os.minor(lock_info.st_dev),lock_info.st_ino)
    records=[]
    for line in (proc/'locks').read_text().splitlines():
        match=re.match(r'^\d+:\s+FLOCK\s+ADVISORY\s+WRITE\s+(\d+)\s+([0-9a-fA-F]+):([0-9a-fA-F]+):(\d+)\s+',line)
        if match:records.append((int(match[1]),int(match[2],16),int(match[3],16),int(match[4])))
    if expected_lock not in records:raise ValueError('PENDING_SELECTION_SWITCH_LOCK_OWNER_CHANGED')


def _clean_native(lease):
    from .boot_recovery import recover
    proof=recover(file=lease)
    state=_read(lease)
    if state.get('schema')!='cabinet-native-lease-v1' or state.get('state')!='CLEAN':
        raise ValueError('START_SELECTION_NATIVE_NOT_CLEAN')
    return proof


def prepare_selftest_selection(args,env_path=ENV,learning_root=ROOT,proc=PROC,lease_path=NATIVE_LEASE_FILE):
    env_path,root,proc,lease_path=map(Path,(env_path,learning_root,proc,lease_path))
    env=_environment(env_path);_arguments_match(args,env,complete=True)
    pin=file_sha(env_path);boot=_boot(proc);record=_selected_job(env,pin,root)
    result=dict(action='UNCHANGED_ACCEPTED_SELECTION',env_sha256=pin,boot_id=boot)
    if record is None:return args,result  # Legacy manually admitted, pinned selection.
    with _lock(root/'lock',wait=True):
        if file_sha(env_path)!=pin:raise ValueError('START_SELECTION_CHANGED_WHILE_LOCKING')
        folder,job,transaction=_selected_job(env,pin,root)
        with _lock(root/'model-switch.lock') as (held,info):
            state=transaction.get('state')
            if state=='COMPLETED':
                _committed(folder,transaction)
                if job.get('state')!='COMPLETED' and transaction.get('commit_protocol')=='durable-normal-model-v1':
                    if not held:raise ValueError('START_SELECTION_COMMIT_OWNER_BUSY')
                    from .learning_deploy import finish_committed_job
                    store=SimpleNamespace(env=env_path,folder=lambda identity:folder,clock=time.monotonic)
                    finish_committed_job(store,job,transaction)
                    result['action']='COMMITTED_JOB_RECONCILED'
                return args,result
            if state not in PENDING:raise ValueError('START_SELECTION_NOT_ACCEPTED')
            original_boot=job.get('context',{}).get('os_boot_id')
            if original_boot==boot:
                if held:raise ValueError('PENDING_SELECTION_WITHOUT_DEPLOYMENT_OWNER')
                _online_owner(folder,dict(job,candidate_pin=env['BUNDLE_SHA256']),boot,proc,info)
                _clean_native(lease_path)
                return args,dict(result,action='ONLINE_PENDING_VALIDATION')
            if not original_boot or str(uuid.UUID(original_boot))!=original_boot:
                raise ValueError('PENDING_SELECTION_BOOT_UNVERIFIED')
            if not held:raise ValueError('PENDING_SELECTION_SWITCH_OWNER_BUSY')
            previous=folder/'previous.env';_regular(previous,16384)
            if file_sha(previous)!=transaction.get('previous_env_sha256'):
                raise ValueError('PREVIOUS_SELECTION_BACKUP_CHANGED')
            previous_env=_environment(previous);_validated(previous_env)
            accepted=_selected_job(previous_env,file_sha(previous),root)
            if accepted is not None:_committed(accepted[0],accepted[2])
            result['native_recovery']=_clean_native(lease_path)
            if file_sha(env_path)!=pin:raise ValueError('START_SELECTION_CHANGED_BEFORE_RESTORE')
            durable_atomic(env_path,previous.read_bytes())
            durable_save(folder/'switch.json',dict(state='INTERRUPTED_PREVIOUS_MODEL_RESTORED',
                previous_env_sha256=file_sha(previous),restored_env_sha256=file_sha(env_path),
                candidate_manifest_sha256=env['BUNDLE_SHA256'],recovered_on_boot=boot,
                reason='NEW_BOOT_BEFORE_LIVE_VALIDATION_COMMIT'))
            durable_save(folder/'job.json',dict(job,state='INTERRUPTED',updated_at=time.monotonic(),
                error='Power interrupted baseline validation; previous accepted baseline restored without learning'))
            updated=copy.copy(args)
            for key,name in ARGUMENTS.items():setattr(updated,name,previous_env[key])
            return updated,dict(result,action='RESTORED_PREVIOUS_ACCEPTED_SELECTION',env_sha256=file_sha(env_path))


def require_selftest_selection_unchanged(args,expected_env_sha256,env_path=ENV):
    env=_environment(env_path);_arguments_match(args,env,complete=True)
    if file_sha(env_path)!=expected_env_sha256:raise ValueError('SELECTION_CHANGED_DURING_SELFTEST')


def require_live_selection(args,env_path=ENV,learning_root=ROOT,proc=PROC,selftest_path=SELFTEST):
    env_path,root,proc=map(Path,(env_path,learning_root,proc));env=_environment(env_path)
    _arguments_match(args,env);pin=file_sha(env_path);boot=_boot(proc)
    record=_selected_job(env,pin,root)
    if record is not None:
        folder,job,transaction=record
        if transaction.get('state')=='COMPLETED':_committed(folder,transaction)
        elif transaction.get('state') in PENDING:
            with _lock(root/'model-switch.lock') as (held,info):
                if held:raise ValueError('PENDING_SELECTION_WITHOUT_DEPLOYMENT_OWNER')
                _online_owner(folder,dict(job,candidate_pin=env['BUNDLE_SHA256']),boot,proc,info)
        else:raise ValueError('LIVE_SELECTION_NOT_ACCEPTED')
    selftest=_read(selftest_path)
    if (selftest.get('status')!='PASS_CURRENT_BOOT_HARDWARE_SELFTEST' or selftest.get('boot_id')!=boot or
            selftest.get('model_sha256')!=env['BUNDLE_SHA256'] or selftest.get('selection_env_sha256')!=pin or
            selftest.get('admission_sha256')!=env['ADMISSION_SHA256']):
        raise ValueError('LIVE_SELECTION_SELFTEST_BINDING_CHANGED')
    path=Path(selftest['report']);report=_read(path)
    if file_sha(path)!=selftest.get('report_sha256'):raise ValueError('LIVE_SELECTION_SELFTEST_REPORT_CHANGED')
    validate_report(report,env['BUNDLE_SHA256'],env['LIBRARY_SHA256'],boot,os.uname().release)
    if file_sha(env_path)!=pin:raise ValueError('LIVE_SELECTION_CHANGED_DURING_CHECK')
    return dict(env_sha256=pin,model_sha256=env['BUNDLE_SHA256'],boot_id=boot)
