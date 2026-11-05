"""Durable labeled archives/selection; read-only status never starts learning."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import threading
import time
from normal_npu.baseline_store import (durable_atomic, durable_mkdir, durable_save, fsync_directory,
    file_sha, storage_status, _environment, _regular, _fingerprint, _stamp, STARTUP_POLICY)
from .bundle import Bundle
from .probe import validate_report

_CACHE={}
_LOCK=threading.Lock()
PROTOCOL='durable-labeled-model-v1'


def cached_validation(key, fingerprint, check, seconds=30):
    with _LOCK:
        old=_CACHE.get(key);now=time.monotonic()
        if old and old[0]==fingerprint and 0<=now-old[1]<seconds:return copy.deepcopy(old[2]),True
        result=check()
        if len(_CACHE)>520:_CACHE.clear()
        _CACHE[key]=(fingerprint,time.monotonic(),copy.deepcopy(result))
        return result,False


def durable_copy_tree(source,target):
    source,target=Path(source),Path(target)
    if source.is_symlink() or not source.is_dir() or target.exists() or target.is_symlink():
        raise ValueError('IMMUTABLE_REGULAR_COPY_REQUIRED')
    entries=list(source.rglob('*'))
    if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in entries):raise ValueError('COPY_ENTRY_NOT_REGULAR')
    expected={str(p.relative_to(source)):file_sha(p) for p in entries if p.is_file()}
    durable_mkdir(target.parent);shutil.copytree(str(source),str(target))
    for name,pin in expected.items():
        p=target/name
        with p.open('rb') as stream:os.fsync(stream.fileno())
        if file_sha(p)!=pin:raise ValueError('DURABLE_COPY_READBACK_CHANGED')
    for p in sorted([target]+[p for p in target.rglob('*') if p.is_dir()],key=lambda p:len(p.parts),reverse=True):fsync_directory(p)
    fsync_directory(target.parent)
    return expected


def persist_candidate(candidate,admission,target,pin):
    target=Path(target)
    if target.exists() or target.is_symlink():raise ValueError('IMMUTABLE_CLASSIFIER_DESTINATION_EXISTS')
    _regular(admission,2*1024*1024);admission_pin=file_sha(admission)
    durable_mkdir(target);durable_copy_tree(candidate,target/'bundle')
    durable_atomic(target/'admission.json',Path(admission).read_bytes())
    if file_sha(target/'admission.json')!=admission_pin:raise ValueError('DURABLE_ADMISSION_READBACK_CHANGED')
    Bundle(target/'bundle',pin).hardware_model()
    return dict(manifest_sha256=pin,admission_sha256=admission_pin,files_synced=True,directories_synced=True)


def validate_saved(env):
    b=Bundle(env['BUNDLE'],env['BUNDLE_SHA256']);b.hardware_model()
    for name,limit in [('LIBRARY',64*1024*1024),('ADMISSION',2*1024*1024)]:
        _regular(env[name],limit)
        if file_sha(env[name])!=env[name+'_SHA256']:raise ValueError('SAVED_CLASSIFIER_ARTIFACT_CHANGED')
    admission=json.loads(Path(env['ADMISSION']).read_text(encoding='utf-8'))
    validate_report(admission,b.pin,env['LIBRARY_SHA256'],admission['boot_id'],admission['kernel_release'])
    return dict(model_id=b.manifest['model_id'],training_source=b.manifest['source'],
        labels=b.manifest['labels'],training_sessions=b.provenance['sessions'],qualified=False,control_authority='NONE')


def accepted_transaction(folder,env,env_path,unit_path=None):
    transaction=json.loads((folder/'switch.json').read_text(encoding='utf-8'));job=json.loads((folder/'job.json').read_text(encoding='utf-8'))
    if type(transaction) is not dict or type(job) is not dict:raise ValueError('SAVED_CLASSIFIER_JOURNAL_OBJECT_REQUIRED')
    if transaction.get('manifest_sha256')!=env['BUNDLE_SHA256']:raise ValueError('SAVED_CLASSIFIER_TRANSACTION_CHANGED')
    if transaction.get('commit_protocol')==PROTOCOL:
        if transaction.get('current_env_sha256')!=file_sha(env_path):raise ValueError('SAVED_CLASSIFIER_SELECTION_CHANGED')
        if transaction.get('state') not in ('PREPARED_SWITCH','SWITCHED_AWAITING_LIVE','COMPLETED'):raise ValueError('SAVED_CLASSIFIER_SWITCH_NOT_ACCEPTED')
        if transaction.get('state')=='COMPLETED':
            from .deploy import validate_commit
            validate_commit(folder,job,transaction,env_path=env_path,unit_path=Path(transaction['unit_path']) if unit_path is None else unit_path)
    elif transaction.get('state')=='COMPLETED':
        if job.get('state')!='COMPLETED' or job.get('result',{}).get('manifest_sha256')!=env['BUNDLE_SHA256']:
            raise ValueError('LEGACY_CLASSIFIER_COMPLETION_NOT_VERIFIED')
    else:raise ValueError('UNREVIEWED_CLASSIFIER_TRANSACTION')
    return transaction


def saved_classifier_status(env_path,learning_root):
    env_path,root=Path(env_path),Path(learning_root)
    result=dict(status='NO_SAVED_CLASSIFIER',saved=False,valid=False,saved_on_sd=False,selection_persisted=False,
        env_path=str(env_path),model_id=None,manifest_sha256=None,bundle_path=None,saved_at=None,
        startup_policy=STARTUP_POLICY,boot_selftest='LOAD_SAVED_MODEL_AND_CHECK_HARDWARE_ONLY',
        automatic_learning=False,boot_creates_training_job=False,boot_captures_training_data=False,
        host_required_for_saved_inference=False,storage={},reason=None)
    try:
        if not env_path.exists() and not env_path.is_symlink():return result
        env=_environment(env_path);fingerprint=_fingerprint(env_path,env)
        checked,cached=cached_validation(('model',str(env_path),env['BUNDLE_SHA256']),fingerprint,lambda:validate_saved(env))
        if _environment(env_path)!=env or _fingerprint(env_path,env)!=fingerprint:raise ValueError('SAVED_CLASSIFIER_CHANGED_DURING_READ')
        result.update(checked,valid=True,manifest_sha256=env['BUNDLE_SHA256'],bundle_path=env['BUNDLE'],validation_cached=cached,
            saved_at=datetime.fromtimestamp(env_path.stat().st_mtime,timezone.utc).isoformat())
        result['storage']={k:storage_status(p) for k,p in dict(env=env_path,bundle=env['BUNDLE'],admission=env['ADMISSION'],library=env['LIBRARY'],learning_root=root).items()}
        items=list(result['storage'].values());persistent=all(s['persistent'] is True for s in items)
        result.update(saved=persistent,selection_persisted=persistent,saved_on_sd=persistent and all(s['is_sd'] is True for s in items))
        result['status']='SAVED_CLASSIFIER_ON_SD' if result['saved_on_sd'] else 'SAVED_CLASSIFIER_ON_PERSISTENT_STORAGE' if persistent else 'VALID_CLASSIFIER_STORAGE_UNCONFIRMED'
        folder=root/'jobs'/Path(env['BUNDLE']).parent.name
        import re
        if re.fullmatch('[0-9a-f]{32}',folder.name) or (folder/'switch.json').exists():
            transaction=json.loads((folder/'switch.json').read_text(encoding='utf-8'))
            if type(transaction) is not dict:raise ValueError('SAVED_CLASSIFIER_JOURNAL_OBJECT_REQUIRED')
            bound=[folder/'switch.json',folder/'job.json']
            if transaction.get('state')=='COMPLETED' and transaction.get('commit_protocol')==PROTOCOL:
                bound += [folder/'deployment.json',folder/'live-validation.json',Path(transaction['unit_path'])]
            identity=fingerprint+tuple(_stamp(p) for p in bound)
            t,unused=cached_validation(('commit',str(env_path),env['BUNDLE_SHA256']),identity,lambda:accepted_transaction(folder,env,env_path))
            result['deployment_state']=t.get('state')
            if t.get('state')!='COMPLETED':result.update(status='SAVED_SELECTION_PENDING_VALIDATION',saved=False,saved_on_sd=False,reason='Live deployment gate has not committed')
        if _environment(env_path)!=env or _fingerprint(env_path,env)!=fingerprint:raise ValueError('SAVED_CLASSIFIER_CHANGED_DURING_READ')
        return result
    except (OSError,ValueError,KeyError,TypeError,OverflowError) as e:
        result.update(status='INVALID_SAVED_CLASSIFIER',saved=False,valid=False,saved_on_sd=False,selection_persisted=False,reason=str(e));return result


def archive_status(folder,job):
    """Verify retained immutable archive bytes, cached with immediate stat invalidation."""
    folder=Path(folder);result=dict(status='NO_SAVED_ARCHIVE',valid=False,saved=False,saved_on_sd=False,reason=None)
    if not job.get('export_sha256'):return result
    try:
        names=['captures.tar.gz','learning.json','sessions.json']+['captures/episode/'+x for x in ['session.json','summary.json','feature_contract.json','frames.jsonl']]
        paths=[folder/n for n in names];fingerprint=tuple(_stamp(p) for p in paths)+(job['export_sha256'],)
        def check():
            for p in paths:_regular(p,128*1024*1024)
            if file_sha(folder/'captures.tar.gz')!=job['export_sha256']:raise ValueError('SAVED_ARCHIVE_PIN_CHANGED')
            summary=json.loads((folder/'captures/episode/summary.json').read_text(encoding='utf-8'))
            meta=json.loads((folder/'captures/episode/session.json').read_text(encoding='utf-8'))
            if type(summary) is not dict or type(meta) is not dict:raise ValueError('SAVED_EPISODE_OBJECT_REQUIRED')
            if json.loads((folder/'sessions.json').read_text(encoding='utf-8'))!=job['sessions']:raise ValueError('SAVED_EPISODE_SESSIONS_CHANGED')
            session=job['sessions']['episode']['status']['session_id']
            if (meta.get('session_id')!=session or summary.get('session_id')!=session or
                    summary.get('durable_frames')!=summary.get('frames') or summary.get('frames',0)<600 or
                    set(summary.get('files_sha256',{}))!={'session.json','frames.jsonl','feature_contract.json'}):
                raise ValueError('SAVED_EPISODE_CONTRACT_CHANGED')
            for name,pin in summary['files_sha256'].items():
                if file_sha(folder/'captures/episode'/name)!=pin:raise ValueError('SAVED_EPISODE_BYTES_CHANGED')
            provenance=json.loads((folder/'learning.json').read_text(encoding='utf-8'))
            if type(provenance) is not dict:raise ValueError('SAVED_PROVENANCE_OBJECT_REQUIRED')
            if (provenance.get('job_id')!=job['id'] or any(provenance.get(k)!=job.get(k) for k in ('label','episode_id','episode_split','corpus_key','context'))):
                raise ValueError('SAVED_EPISODE_PROVENANCE_CHANGED')
            return dict(session_id=session,frames=summary['frames'])
        checked,cached=cached_validation(('archive',str(folder)),fingerprint,check,seconds=300)
        if tuple(_stamp(p) for p in paths)+(job['export_sha256'],)!=fingerprint:raise ValueError('SAVED_ARCHIVE_CHANGED_DURING_READ')
        storage=storage_status(folder);saved=storage['persistent'] is True
        result.update(checked,valid=True,saved=saved,saved_on_sd=saved and storage['is_sd'] is True,storage=storage,validation_cached=cached,
            status='SAVED_ARCHIVE_ON_SD' if saved and storage['is_sd'] is True else 'VERIFIED_ARCHIVE_STORAGE_UNCONFIRMED')
    except (OSError,ValueError,KeyError,TypeError) as e:result.update(status='ARCHIVE_MISSING_OR_CHANGED',reason=str(e))
    return result
