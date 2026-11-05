"""Reconcile classifier selection outside NPU ExecStartPre; never replay learning."""
import json
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace
import uuid
from normal_npu.baseline_store import (_environment, _regular, file_sha, durable_atomic, durable_save, fsync_directory)
from normal_npu.boot_selection import _read, _boot, _lock, _arguments_match, _clean_native
from v4_runtime.native_lease import NATIVE_LEASE_FILE
from .persistence import validate_saved, accepted_transaction, PROTOCOL
from .probe import validate_report

ENV=Path('/etc/cabinet/labeled-npu.env')
NORMAL_ENV=Path('/etc/cabinet/normal-npu.env')
UNIT=Path('/etc/systemd/system/cabinet-labeled-npu.service')
ROOT=Path('/var/lib/cabinet/npu-learning')
PROC=Path('/proc')
SELFTEST=Path('/run/cabinet-labeled-npu/selftest.json')
PENDING={'PREPARED','PREPARED_SWITCH','SWITCHED_AWAITING_LIVE','RESTORING_PREVIOUS_SELECTION'}
TERMINAL={'COMPLETED','FAILED','CANCELLED','INTERRUPTED','COLLECTED_WAITING_DATA'}


def selected_record(env,env_path,root):
    identity=Path(env['BUNDLE']).parent.name
    if not re.fullmatch('[0-9a-f]{32}',identity):return None
    folder=root/'jobs'/identity
    if folder.is_symlink() or (root/'jobs').is_symlink():raise ValueError('CLASSIFIER_SELECTION_UNSAFE_DIRECTORY')
    job=_read(folder/'job.json');t=_read(folder/'switch.json')
    if (job.get('id')!=identity or job.get('kind')!='labeled_classifier' or t.get('manifest_sha256')!=env['BUNDLE_SHA256']):
        raise ValueError('CLASSIFIER_SELECTION_TRANSACTION_CHANGED')
    if t.get('commit_protocol')==PROTOCOL and t.get('current_env_sha256')!=file_sha(env_path):
        raise ValueError('CLASSIFIER_SELECTION_ENV_CHANGED')
    return folder,job,t


def online_owner(folder,job,transaction,boot,proc,info):
    if (job.get('state')!='DEPLOYING' or job.get('context',{}).get('os_boot_id')!=boot or
            job.get('cancel_requested') is not False or not re.fullmatch('[0-9a-f]{32}',str(job.get('worker_id')))):
        raise ValueError('PENDING_CLASSIFIER_NO_CURRENT_DEPLOYMENT')
    owner=_read(folder/'deployment-process.json');request=_read(folder/'deploy-request.json');pid=owner.get('pid')
    if (type(pid) is not int or pid<=1 or owner.get('boot_id')!=boot or request.get('job_id')!=job['id'] or
            request.get('worker_id')!=job['worker_id'] or request.get('manifest_sha256')!=transaction['manifest_sha256']):
        raise ValueError('PENDING_CLASSIFIER_OWNER_IDENTITY')
    fields=(proc/str(pid)/'stat').read_text().rsplit(')',1)[1].split();command=(proc/str(pid)/'cmdline').read_bytes().split(b'\0')
    expected=[b'-m',b'labeled_npu.deploy',b'--request-file',str(folder/'deploy-request.json').encode()]
    if (len(fields)<20 or fields[0]=='Z' or fields[19]!=owner.get('start_ticks') or
            not any(command[i:i+4]==expected for i in range(len(command)-3))):
        raise ValueError('PENDING_CLASSIFIER_OWNER_PROCESS_CHANGED')
    target=(pid,os.major(info.st_dev),os.minor(info.st_dev),info.st_ino);found=[]
    for line in (proc/'locks').read_text().splitlines():
        m=re.match(r'^\d+:\s+FLOCK\s+ADVISORY\s+WRITE\s+(\d+)\s+([0-9a-fA-F]+):([0-9a-fA-F]+):(\d+)\s+',line)
        if m:found.append((int(m[1]),int(m[2],16),int(m[3],16),int(m[4])))
    if target not in found:raise ValueError('PENDING_CLASSIFIER_SWITCH_LOCK_OWNER_CHANGED')


def require_selection(args,env_path=ENV,learning_root=ROOT,proc=PROC,complete=False):
    env_path,root,proc=map(Path,(env_path,learning_root,proc));env=_environment(env_path);_arguments_match(args,env,complete)
    pin=file_sha(env_path);boot=_boot(proc);record=selected_record(env,env_path,root);action='UNCHANGED_ACCEPTED_SELECTION'
    if record:
        folder,job,t=record
        if t.get('state')=='COMPLETED':accepted_transaction(folder,env,env_path)
        elif t.get('state') in PENDING:
            if t.get('commit_protocol')!=PROTOCOL:raise ValueError('PENDING_CLASSIFIER_PROTOCOL_UNVERIFIED')
            if job.get('context',{}).get('os_boot_id')!=boot:raise ValueError('PENDING_CLASSIFIER_REQUIRES_BOOT_RECONCILIATION')
            with _lock(root/'model-switch.lock') as (held,info):
                if held:raise ValueError('PENDING_CLASSIFIER_WITHOUT_DEPLOYMENT_OWNER')
                online_owner(folder,job,t,boot,proc,info)
            action='ONLINE_PENDING_VALIDATION'
        else:raise ValueError('CLASSIFIER_SELECTION_NOT_ACCEPTED')
    if file_sha(env_path)!=pin:raise ValueError('CLASSIFIER_SELECTION_CHANGED_DURING_CHECK')
    return dict(env_sha256=pin,boot_id=boot,action=action),env


def prepare_selftest_selection(args,env_path=ENV,learning_root=ROOT,proc=PROC):
    result,unused=require_selection(args,env_path,learning_root,proc,complete=True);return args,result


def require_selftest_selection_unchanged(args,pin,env_path=ENV):
    _arguments_match(args,_environment(env_path),complete=True)
    if file_sha(env_path)!=pin:raise ValueError('CLASSIFIER_SELECTION_CHANGED_DURING_SELFTEST')


def require_live_selection(args,env_path=ENV,learning_root=ROOT,proc=PROC,selftest_path=SELFTEST):
    result,env=require_selection(args,env_path,learning_root,proc);r=_read(selftest_path)
    if (r.get('status')!='PASS_CURRENT_BOOT_HARDWARE_SELFTEST' or r.get('boot_id')!=result['boot_id'] or
            r.get('model_sha256')!=env['BUNDLE_SHA256'] or r.get('selection_env_sha256')!=result['env_sha256'] or
            r.get('admission_sha256')!=env['ADMISSION_SHA256']):raise ValueError('CLASSIFIER_LIVE_SELFTEST_BINDING_CHANGED')
    report=Path(r['report']);proof=_read(report)
    if file_sha(report)!=r.get('report_sha256'):raise ValueError('CLASSIFIER_LIVE_SELFTEST_REPORT_CHANGED')
    validate_report(proof,env['BUNDLE_SHA256'],env['LIBRARY_SHA256'],result['boot_id'],os.uname().release)
    if file_sha(env_path)!=result['env_sha256']:raise ValueError('CLASSIFIER_SELECTION_CHANGED_DURING_CHECK')
    return result


def file_pin(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('RECOVERY_SELECTION_SYMLINK')
    if not path.exists():return None
    _regular(path,65536);return file_sha(path)


def validate_previous(folder,t,env_path,unit_path,normal_env,root):
    if (t.get('commit_protocol')!=PROTOCOL or t.get('env_path')!=str(env_path) or t.get('unit_path')!=str(unit_path) or
            t.get('previous_services_sha256')!=file_sha(folder/'previous-services.json')):
        raise ValueError('RECOVERY_TRANSACTION_IDENTITY_CHANGED')
    previous=_read(folder/'previous-services.json')
    if previous!=t.get('previous'):raise ValueError('RECOVERY_PREVIOUS_SERVICE_SNAPSHOT_CHANGED')
    for key in ('normal','labeled'):
        if any(type(previous.get(key,{}).get(x)) is not bool for x in ('enabled','active')):raise ValueError('RECOVERY_SERVICE_STATE_INVALID')
    if all(previous[k]['active'] or previous[k]['enabled'] for k in ('normal','labeled')):raise ValueError('RECOVERY_PREVIOUS_OWNERS_CONFLICT')
    if previous.get('normal_env_path')!=str(normal_env) or file_pin(normal_env)!=previous.get('normal_env_sha256'):
        raise ValueError('RECOVERY_PREVIOUS_NORMAL_SELECTION_CHANGED')
    from normal_npu.baseline_store import _validated
    from normal_npu.boot_selection import _selected_job, _committed
    normal=_environment(normal_env);_validated(normal)
    if normal['BUNDLE_SHA256']!=previous.get('normal_model_pin'):raise ValueError('RECOVERY_NORMAL_MODEL_PIN_CHANGED')
    record=_selected_job(normal,file_sha(normal_env),root)
    if record:_committed(record[0],record[2])
    for path,key in ((env_path,'env'),(unit_path,'unit')):
        before=folder/('previous-labeled.'+key);exists=previous.get(key+'_exists');pin=previous.get(key+'_sha256')
        if type(exists) is not bool or (exists and (pin is None or file_pin(before)!=pin)) or (not exists and pin is not None):
            raise ValueError('RECOVERY_PREVIOUS_BYTES_CHANGED')
        if file_pin(path) not in {pin,t.get('current_'+key+'_sha256')}:raise ValueError('RECOVERY_CURRENT_BYTES_CHANGED')
    if previous['env_exists']:
        old=_environment(folder/'previous-labeled.env');validate_saved(old)
        prior=selected_record(old,folder/'previous-labeled.env',root)
        if prior:accepted_transaction(prior[0],old,folder/'previous-labeled.env',unit_path=folder/'previous-labeled.unit')
    elif previous['labeled']['active'] or previous['labeled']['enabled']:
        raise ValueError('RECOVERY_PREVIOUS_CLASSIFIER_ENV_MISSING')
    return previous


def reconcile_boot(learning_root=ROOT,env_path=ENV,unit_path=UNIT,normal_env=NORMAL_ENV,proc=PROC,lease_path=NATIVE_LEASE_FILE):
    """Systemd oneshot entry; no classifier transaction means no write/native call."""
    root,env_path,unit_path,normal_env,proc=map(Path,(learning_root,env_path,unit_path,normal_env,proc))
    from .deploy import finish_committed_job,run,sync_service_selection,set_service_enabled,service_action
    pending=[]
    for p in sorted((root/'jobs').glob('*/job.json')):
        job=_read(p)
        if job.get('kind')!='labeled_classifier' or not (p.parent/'switch.json').exists():continue
        t=_read(p.parent/'switch.json')
        if (t.get('state') in PENDING or (t.get('state')=='COMPLETED' and job.get('state')!='COMPLETED') or
                (t.get('state')=='PREVIOUS_MODEL_RESTORED' and job.get('state') not in TERMINAL)):
            pending.append((p.parent,job,t))
        elif t.get('state')=='ROLLBACK_REQUIRES_REVIEW':raise ValueError('PRIOR_CLASSIFIER_ROLLBACK_REQUIRES_REVIEW')
    if not pending:return dict(status='PASS_NO_RECOVERY',automatic_learning=False,npu_inference_verified=False)
    if len(pending)!=1:raise ValueError('MULTIPLE_CLASSIFIER_SWITCHES_REQUIRE_REVIEW')
    folder,job,t=pending[0];boot=_boot(proc)
    with _lock(root/'lock',wait=True):
        if _read(folder/'job.json')!=job or _read(folder/'switch.json')!=t:raise ValueError('CLASSIFIER_RECOVERY_CHANGED_WHILE_LOCKING')
        with _lock(root/'model-switch.lock') as (held,info):
            if t.get('state')=='COMPLETED':
                if not held:raise ValueError('CLASSIFIER_COMMIT_OWNER_BUSY')
                store=SimpleNamespace(folder=lambda unused:folder,clock=time.monotonic)
                finish_committed_job(store,job,t,env_path,unit_path)
                return dict(status='PASS_COMMITTED_CLASSIFIER_RECONCILED',automatic_learning=False,npu_inference_verified=False)
            if t.get('state')=='PREVIOUS_MODEL_RESTORED':
                if not held:raise ValueError('CLASSIFIER_ROLLBACK_OWNER_BUSY')
                previous=validate_previous(folder,t,env_path,unit_path,normal_env,root)
                if any(file_pin(path)!=previous[key+'_sha256'] for path,key in ((env_path,'env'),(unit_path,'unit'))):
                    raise ValueError('CLASSIFIER_RESTORED_BYTES_CHANGED')
                restored_boot=t.get('recovered_on_boot',job.get('context',{}).get('os_boot_id'))
                if not restored_boot or str(uuid.UUID(restored_boot))!=restored_boot:
                    raise ValueError('CLASSIFIER_RESTORE_BOOT_UNVERIFIED')
                queue=[]
                if restored_boot!=boot:
                    # A systemd start queue does not survive another power loss.
                    # Reapply the recorded active state even when enablement was
                    # deliberately false. Never repeat this on the recorded boot.
                    proof=_clean_native(Path(lease_path))
                    validate_previous(folder,t,env_path,unit_path,normal_env,root)
                    if any(file_pin(path)!=previous[key+'_sha256'] for path,key in ((env_path,'env'),(unit_path,'unit'))):
                        raise ValueError('CLASSIFIER_RESTORED_BYTES_CHANGED')
                    for name,key in [('cabinet-normal-npu','normal'),('cabinet-labeled-npu','labeled')]:
                        should_start=previous[key]['active'] or previous[key]['enabled']
                        service_action(name,start=should_start,nonblocking=True)
                        if should_start:queue.append(name)
                    t=dict(t,recovered_on_boot=boot,queued_start=queue,native_recovery=proof,
                        requeue_reason='PREVIOUS_BOOT_START_QUEUE_LOST_BEFORE_JOB_FINALIZATION')
                    durable_save(folder/'switch.json',t)
                durable_save(folder/'job.json',dict(job,state='INTERRUPTED',updated_at=time.monotonic(),
                    error='Previous saved model restoration already committed; no learning replayed'))
                return dict(status='PASS_PREVIOUS_NPU_SELECTION_RESTORED',
                    previous_backend='LABELED' if previous['labeled']['active'] or previous['labeled']['enabled'] else 'NORMAL',
                    queued_start=queue,automatic_learning=False,npu_inference_verified=False)
            old_boot=job.get('context',{}).get('os_boot_id')
            if old_boot==boot:
                if held:raise ValueError('PENDING_CLASSIFIER_WITHOUT_DEPLOYMENT_OWNER')
                online_owner(folder,job,t,boot,proc,info)
                return dict(status='PASS_CURRENT_BOOT_DEPLOYMENT_ACTIVE',automatic_learning=False,npu_inference_verified=False)
            if not old_boot or str(uuid.UUID(old_boot))!=old_boot:raise ValueError('CLASSIFIER_PREVIOUS_BOOT_UNVERIFIED')
            if not held:raise ValueError('CLASSIFIER_SWITCH_OWNER_BUSY')
            previous=validate_previous(folder,t,env_path,unit_path,normal_env,root)
            proof=_clean_native(Path(lease_path))  # reviewed boot reset only; same-boot dirty never cleared
            # Recheck every selection after the recovery gate before writing.
            validate_previous(folder,t,env_path,unit_path,normal_env,root)
            t=dict(t,state='RESTORING_PREVIOUS_SELECTION',recovered_on_boot=boot);durable_save(folder/'switch.json',t)
            for path,key in ((env_path,'env'),(unit_path,'unit')):
                if previous[key+'_exists']:durable_atomic(path,(folder/('previous-labeled.'+key)).read_bytes())
                elif path.exists():path.unlink();fsync_directory(path.parent)
            run(['systemctl','daemon-reload'])
            for name,key in [('cabinet-normal-npu','normal'),('cabinet-labeled-npu','labeled')]:
                set_service_enabled(name,previous[key]['enabled'])
            sync_service_selection(unit_path)
            queue=[]
            for name,key in [('cabinet-normal-npu','normal'),('cabinet-labeled-npu','labeled')]:
                should_start=previous[key]['active'] or previous[key]['enabled']
                service_action(name,start=should_start,nonblocking=True)
                if should_start:queue.append(name)
            t.update(state='PREVIOUS_MODEL_RESTORED',recovery='NEW_BOOT_BEFORE_CLASSIFIER_LIVE_COMMIT',native_recovery=proof,queued_start=queue)
            durable_save(folder/'switch.json',t)
            durable_save(folder/'job.json',dict(job,state='INTERRUPTED',updated_at=time.monotonic(),
                error='Interrupted classifier validation; previous saved NPU selection restored without new learning'))
            return dict(status='PASS_PREVIOUS_NPU_SELECTION_RESTORED',previous_backend='LABELED' if 'cabinet-labeled-npu' in queue else 'NORMAL',
                queued_start=queue,automatic_learning=False,npu_inference_verified=False)
