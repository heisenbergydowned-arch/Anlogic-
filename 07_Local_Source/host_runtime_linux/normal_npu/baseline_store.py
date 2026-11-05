"""Durable normal-model selection and read-only saved-baseline diagnostics.

normal-npu.env remains the only authoritative selection. A boot self-test loads
that selection; this module never captures data, trains, starts jobs or services.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
import time
from datetime import datetime, timezone

from .bundle import Bundle
from .start_gate import validate_report

STARTUP_POLICY='LOAD_SAVED_NO_AUTOMATIC_LEARNING'
CACHE_SECONDS=30.0
_CACHE={}
_CACHE_LOCK=threading.Lock()
MOUNTINFO=Path('/proc/self/mountinfo')
SYS_DEV_BLOCK=Path('/sys/dev/block')
ENV_FIELDS={'BUNDLE','BUNDLE_SHA256','LIBRARY','LIBRARY_SHA256','ADMISSION','ADMISSION_SHA256'}
TEMP_FILESYSTEMS={'tmpfs','ramfs','devtmpfs','overlay','aufs','proc','sysfs','squashfs'}
DISK_FILESYSTEMS={'ext2','ext3','ext4','f2fs','xfs','btrfs','vfat','exfat','ntfs','ntfs3'}


def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(65536),b''):h.update(chunk)
    return h.hexdigest()


def fsync_directory(path):
    fd=os.open(str(path),os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
    try:os.fsync(fd)
    finally:os.close(fd)


def durable_mkdir(path):
    path=Path(path)
    if path.exists():
        if path.is_symlink() or not path.is_dir():raise ValueError('Unsafe model directory')
        return
    durable_mkdir(path.parent)
    path.mkdir(mode=0o700)
    fsync_directory(path);fsync_directory(path.parent)


def durable_atomic(path,data):
    """Return only after the new file and its parent directory are synced."""
    path=Path(path)
    if path.is_symlink():raise ValueError('Refusing symlink model selection')
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.baseline-',dir=str(path.parent))
    pending=Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),0o600)
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(str(pending),str(path))
        fsync_directory(path.parent)
    finally:
        if pending.exists():pending.unlink()


def durable_save(path,value):
    durable_atomic(path,(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode('utf-8'))


def persist_candidate(candidate,admission,target,manifest_pin):
    """Copy immutable validated bytes, sync/read back, then permit env switch.

An incomplete target is retained for diagnosis, never selected or overwritten.
"""
    candidate,admission,target=Path(candidate),Path(admission),Path(target)
    if target.exists() or target.is_symlink():raise ValueError('Immutable candidate target already exists')
    if candidate.is_symlink() or not candidate.is_dir():raise ValueError('Unsafe candidate directory')
    _regular(admission,2*1024*1024)
    expected={p.name:file_sha(p) for p in candidate.iterdir() if p.is_file() and not p.is_symlink()}
    if len(expected)!=len(list(candidate.iterdir())):raise ValueError('Unexpected candidate entry')
    admission_pin=file_sha(admission)
    durable_mkdir(target)
    shutil.copytree(str(candidate),str(target/'bundle'))
    shutil.copy2(str(admission),str(target/'admission.json'))
    for path in list((target/'bundle').iterdir())+[target/'admission.json']:
        if path.is_symlink() or not path.is_file():raise ValueError('Copied model must be regular files')
        with path.open('rb') as stream:os.fsync(stream.fileno())
    fsync_directory(target/'bundle');fsync_directory(target);fsync_directory(target.parent)
    actual={p.name:file_sha(p) for p in (target/'bundle').iterdir()}
    if actual!=expected or file_sha(target/'admission.json')!=admission_pin:
        raise ValueError('Durable model copy readback differs')
    bundle=Bundle(target/'bundle',manifest_pin);bundle.hardware_model()
    return dict(bundle_path=str(target/'bundle'),admission_path=str(target/'admission.json'),
                manifest_sha256=manifest_pin,admission_sha256=admission_pin,files_synced=True,directories_synced=True)


def _regular(path,limit):
    st=Path(path).lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size>limit:raise ValueError('Unsafe saved file: '+str(path))
    return st


def _environment(path):
    _regular(path,16384)
    result={}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):continue
        k,v=line.split('=',1)
        if k not in ENV_FIELDS or k in result:raise ValueError('Invalid saved environment entry')
        result[k]=v
    if set(result)!=ENV_FIELDS:raise ValueError('Incomplete saved environment')
    for name in ('BUNDLE','LIBRARY','ADMISSION'):
        if not Path(result[name]).is_absolute():raise ValueError('Saved model path must be absolute')
        if not re.fullmatch('[0-9a-f]{64}',result[name+'_SHA256']):raise ValueError('Invalid saved artifact pin')
    return result


def _stamp(path):
    st=Path(path).lstat()
    return (str(path),st.st_dev,st.st_ino,st.st_mode,st.st_size,st.st_mtime_ns,st.st_ctime_ns)


def _fingerprint(env_path,env):
    root=Path(env['BUNDLE'])
    if root.is_symlink() or not root.is_dir():raise ValueError('Unsafe saved model directory')
    files=sorted(root.iterdir())
    if len(files)>32:raise ValueError('Unexpected saved model inventory')
    return tuple(_stamp(p) for p in [Path(env_path),root,Path(env['LIBRARY']),Path(env['ADMISSION'])]+files)


def _validated(env):
    bundle=Bundle(env['BUNDLE'],env['BUNDLE_SHA256']);bundle.hardware_model()
    if type(bundle.manifest.get('model_id')) is not str or not bundle.manifest['model_id']:
        raise ValueError('Saved model identifier missing')
    _regular(env['LIBRARY'],64*1024*1024);_regular(env['ADMISSION'],2*1024*1024)
    if file_sha(env['LIBRARY'])!=env['LIBRARY_SHA256'] or file_sha(env['ADMISSION'])!=env['ADMISSION_SHA256']:
        raise ValueError('Saved adapter/admission hash mismatch')
    admission=json.loads(Path(env['ADMISSION']).read_text(encoding='utf-8'))
    if not admission.get('boot_id') or not admission.get('kernel_release'):raise ValueError('Saved hardware probe identity missing')
    # Historical admission proves saved provenance, not readiness on this boot.
    validate_report(admission,env['BUNDLE_SHA256'],env['LIBRARY_SHA256'],admission['boot_id'],admission['kernel_release'])
    sessions={k:dict(session_ids=v.get('session_ids',[v.get('session_id')]),rows=v.get('rows'))
              for k,v in bundle.provenance['sessions'].items()}
    return dict(model_id=bundle.manifest['model_id'],training_source=bundle.manifest['source'],
                training_sessions=sessions,scope='NORMAL_BASELINE_ADVISORY',formal_control_authority=False)


def _unescape(value):return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m.group(1),8)),value)


def storage_status(path):
    """Resolve actual mount and sysfs card type; a /dev/mmc name alone is insufficient."""
    p=Path(path);result=dict(path=str(p),mount_point=None,filesystem=None,device=None,card_type=None,
                            is_sd=None,persistent=None,writable=None)
    try:
        resolved=p.resolve();existing=resolved
        while not existing.exists() and existing!=existing.parent:existing=existing.parent
        dev=existing.stat().st_dev;device_number='%d:%d'%(os.major(dev),os.minor(dev))
        matches=[]
        for line in MOUNTINFO.read_text(encoding='utf-8').splitlines():
            left,right=line.split(' - ',1);fields=left.split();tail=right.split()
            mount=Path(_unescape(fields[4]))
            if fields[2]==device_number and (resolved==mount or mount in resolved.parents):
                matches.append((len(mount.parts),mount,fields,tail))
        if not matches:raise ValueError('No matching mount identity')
        unused,mount,fields,tail=max(matches,key=lambda item:item[0]);filesystem=tail[0]
        writable='rw' in fields[5].split(',') and 'ro' not in tail[2].split(',')
        persistent=False if filesystem in TEMP_FILESYSTEMS else (True if filesystem in DISK_FILESYSTEMS and os.major(dev)>0 else None)
        card=None
        block=(SYS_DEV_BLOCK/device_number).resolve()
        for item in (block,)+tuple(block.parents):
            if re.fullmatch(r'mmcblk[0-9]+',item.name):
                try:card=(item/'device/type').read_text(encoding='ascii').strip()
                except OSError:pass
                break
        result.update(mount_point=str(mount),filesystem=filesystem,device=_unescape(tail[1]),
                      device_number=device_number,card_type=card,is_sd=(card=='SD' if card else None),
                      persistent=persistent,writable=writable)
    except (OSError,ValueError,IndexError) as error:result['reason']=str(error)
    return result


def saved_baseline_status(env_path,learning_root):
    """Read-only, bounded-cache diagnostics; errors never break the status API."""
    env_path,learning_root=Path(env_path),Path(learning_root)
    result=dict(status='NO_SAVED_MODEL',saved=False,valid=False,saved_on_sd=False,selection_persisted=False,
        env_path=str(env_path),model_id=None,manifest_sha256=None,bundle_path=None,admission_path=None,saved_at=None,
        startup_policy=STARTUP_POLICY,boot_selftest='LOAD_SAVED_MODEL_AND_CHECK_HARDWARE_ONLY',
        automatic_learning=False,boot_creates_training_job=False,boot_captures_training_data=False,
        host_required_for_saved_inference=False,validation_cached=False,storage={},reason=None)
    try:
        if not env_path.exists() and not env_path.is_symlink():return result
        env=_environment(env_path)
        result.update(manifest_sha256=env['BUNDLE_SHA256'],bundle_path=env['BUNDLE'],admission_path=env['ADMISSION'],
            saved_at=datetime.fromtimestamp(env_path.stat().st_mtime,timezone.utc).isoformat())
        key=(str(env_path.absolute()),str(learning_root.absolute()),env['BUNDLE_SHA256'])
        fingerprint=_fingerprint(env_path,env);now=time.monotonic()
        with _CACHE_LOCK:
            cached=_CACHE.get(key)
            if cached and cached['fingerprint']==fingerprint and 0<=now-cached['checked_at']<CACHE_SECONDS:
                checked=copy.deepcopy(cached['value']);result['validation_cached']=True;checked_at=cached['checked_at']
            else:
                checked=_validated(env)
                if _environment(env_path)!=env or _fingerprint(env_path,env)!=fingerprint:
                    raise ValueError('Saved model changed during validation')
                checked_at=time.monotonic()
                if len(_CACHE)>=8:_CACHE.clear()
                _CACHE[key]=dict(fingerprint=fingerprint,checked_at=checked_at,value=copy.deepcopy(checked))
        result.update(checked,valid=True,checked_at=checked_at)
        paths=dict(env=env_path,bundle=env['BUNDLE'],admission=env['ADMISSION'],library=env['LIBRARY'],learning_root=learning_root)
        result['storage']={name:storage_status(path) for name,path in paths.items()}
        essential=[result['storage'][n] for n in ('env','bundle','admission','library')]
        persistent=all(s['persistent'] is True for s in essential)
        result.update(selection_persisted=persistent,saved=persistent,
                      saved_on_sd=persistent and all(s['is_sd'] is True for s in essential))
        result['status']=('SAVED_BASELINE_ON_SD' if result['saved_on_sd'] else 'SAVED_BASELINE_ON_PERSISTENT_STORAGE'
                          if persistent else 'VALID_MODEL_NOT_PERSISTENT' if any(s['persistent'] is False for s in essential)
                          else 'VALID_MODEL_STORAGE_UNKNOWN')
        # Env can temporarily select a candidate during the existing live gate.
        # Keep that persisted selection distinct from a completed learned baseline.
        switch=learning_root/'jobs'/Path(env['BUNDLE']).parent.name/'switch.json'
        if switch.exists():
            _regular(switch,65536);transaction=json.loads(switch.read_text(encoding='utf-8'))
            result['deployment_state']=transaction.get('state')
            if (transaction.get('state') not in ('PREPARED_SWITCH','SWITCHED_AWAITING_LIVE','COMPLETED') or
                    transaction.get('candidate_manifest_sha256')!=env['BUNDLE_SHA256'] or
                    transaction.get('current_env_sha256')!=file_sha(env_path)):
                raise ValueError('Saved switch does not match selected model/environment')
            if transaction.get('state')=='COMPLETED' and transaction.get('commit_protocol')=='durable-normal-model-v1':
                deployment=switch.with_name('deployment.json');_regular(deployment,2*1024*1024)
                if transaction.get('current_env_sha256')!=file_sha(env_path) or transaction.get('deployment_sha256')!=file_sha(deployment):
                    raise ValueError('Committed model selection/deployment evidence changed')
            if transaction.get('candidate_manifest_sha256')==env['BUNDLE_SHA256'] and transaction.get('state')!='COMPLETED':
                result.update(status='SAVED_SELECTION_PENDING_VALIDATION',saved=False,saved_on_sd=False,
                              reason='Selected candidate has not completed deployment validation')
        return result
    except (OSError,ValueError,KeyError,TypeError,OverflowError) as error:
        result.update(status='INVALID_SAVED_MODEL',saved=False,valid=False,saved_on_sd=False,selection_persisted=False,reason=str(error))
        return result
