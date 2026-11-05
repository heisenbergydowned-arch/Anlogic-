"""Detached, rollback-capable real classifier installation sharing the sole NPU lease."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
from normal_npu.baseline_store import durable_atomic as atomic, fsync_directory, _environment
from .persistence import persist_candidate, validate_saved, PROTOCOL
from normal_npu.learning import save,sha,environment
from normal_npu.learning_deploy import run,clean
from normal_npu.live import read_state
from .bundle import Bundle,FILES,HARDWARE_FILES
from .probe import validate_report
from .agreement import (snapshot as agreement_sample, agreement as label_agreement,
                        receipt_fields, check_receipt, v2_job)

LIBRARY=Path('/opt/cabinet/npu/r46_alnpu_candidate4_20261101/libedge_npu_logits_ps.so')
LIBRARY_SHA256='6a898a65ca8395f74ed384fb08bea443e63988a27f0321d53bd1943cf1c6d1d1'
LABELED_ENV=Path('/etc/cabinet/labeled-npu.env')
SERVICE='cabinet-labeled-npu'
NORMAL='cabinet-normal-npu'
UNIT=Path('/etc/systemd/system/cabinet-labeled-npu.service')

def service_enablement(name):
    """Only explicit, exit-code-consistent systemd states are evidence."""
    result=run(['systemctl','is-enabled',name],check=False)
    state=result.stdout.strip()
    codes={'enabled':{0},'disabled':{1},'not-found':{1,4}}
    if state not in codes or result.returncode not in codes[state]:
        # This board's systemd emits only an error for a missing unit. Error
        # wording is not absence evidence: require a successful structured
        # query with the complete, unambiguous unloaded/inactive identity.
        if state not in codes and result.returncode in (1,4):
            proof=run(['systemctl','show',name,'--property=LoadState,UnitFileState,FragmentPath,ActiveState'],check=False)
            expected={'LoadState':'not-found','ActiveState':'inactive','FragmentPath':'','UnitFileState':''}
            fields={};malformed=False
            if proof.returncode==0 and len(proof.stdout)<=16384:
                for line in proof.stdout.splitlines():
                    if '=' not in line:malformed=True;break
                    key,value=line.split('=',1)
                    if key in fields:malformed=True;break
                    fields[key]=value
                if not malformed and fields==expected:return 'not-found'
        raise ValueError('SERVICE_ENABLEMENT_UNVERIFIED: '+name+' '+result.stdout[-500:])
    return state


def service_active(name,known_absent=False):
    result=run(['systemctl','is-active',name],check=False);state=result.stdout.strip()
    if state=='active' and result.returncode==0:return True
    if state in ('inactive','failed') and result.returncode==3:return False
    if known_absent and state=='unknown' and result.returncode==4:return False
    raise ValueError('SERVICE_ACTIVITY_UNVERIFIED: '+name+' '+result.stdout[-500:])


def set_service_enabled(name,enabled):
    if type(enabled) is not bool:raise ValueError('SERVICE_ENABLEMENT_BOOLEAN_REQUIRED')
    before=service_enablement(name)
    if before=='not-found':
        if enabled:raise ValueError('REQUIRED_SERVICE_UNIT_NOT_FOUND: '+name)
        return dict(state='not-found',changed=False)
    action='enable' if enabled else 'disable'
    result=run(['systemctl',action,name],check=True)
    if result.returncode:raise RuntimeError('SERVICE_'+action.upper()+'_FAILED: '+name+' '+result.stdout[-500:])
    after=service_enablement(name)
    if after!=('enabled' if enabled else 'disabled'):
        raise ValueError('SERVICE_ENABLEMENT_READBACK_DIFFERS: '+name+' '+after)
    return dict(state=after,changed=True)


def service_action(name,start,nonblocking=False):
    """An absent inactive unit needs no stop; a queued start is not inference."""
    state=service_enablement(name)
    if state=='not-found':
        if start:raise ValueError('REQUIRED_SERVICE_UNIT_NOT_FOUND: '+name)
        # A deleted unit file can still have an active loaded service.
        if not service_active(name,known_absent=True):return False
    args=['systemctl']+(['--no-block'] if nonblocking else [])+['start' if start else 'stop',name]
    result=run(args,timeout=100 if start else 40,check=True)
    if result.returncode:raise RuntimeError('SERVICE_ACTION_FAILED: '+name+' '+result.stdout[-500:])
    return True


def service_state(name):
    state=service_enablement(name)
    return dict(active=service_active(name,known_absent=state=='not-found'),enabled=state=='enabled')

def verify_restored(previous,folder,timeout=30):
    """A successful systemctl invocation alone is not evidence of resumed inference."""
    expected=previous.get('normal_model_pin') if previous['normal']['active'] else previous.get('labeled_model_pin')
    if not previous['normal']['active'] and not previous['labeled']['active']:
        save(folder/'rollback-validation.json',dict(status='PREVIOUS_SERVICES_WERE_INACTIVE',npu_resumed=False)); return
    path=Path('/run/cabinet-normal-npu/state.json' if previous['normal']['active'] else '/run/cabinet-labeled-npu/state.json')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(); started=time.monotonic(); counts=set()
    while time.monotonic()-started<timeout:
        try: r=read_state(path)
        except (OSError,ValueError): r={}
        if (r.get('model_sha256')==expected and r.get('status')=='RUNNING' and r.get('valid') is True
                and r.get('os_boot_id')==boot and started<=r.get('updated_at',-1)<=time.monotonic()
                and time.monotonic()-r['updated_at']<.5 and type(r.get('inference_count')) is int):
            counts.add(r['inference_count'])
            if len(counts)>=8:
                save(folder/'rollback-validation.json',dict(status='PASS_PREVIOUS_MODEL_RESUMED',model_sha256=expected,
                    fresh_inferences=len(counts),boot_id=boot,npu_resumed=True)); return
        time.sleep(.05)
    save(folder/'rollback-validation.json',dict(status='FAIL_PREVIOUS_MODEL_NOT_FRESH',model_sha256=expected,
        fresh_inferences=len(counts),npu_resumed=False))
    raise ValueError('PREVIOUS_MODEL_RESTARTED_BUT_FRESH_INFERENCE_NOT_VERIFIED')

def restore(previous, folder, env_path=LABELED_ENV, unit_path=UNIT):
    """Never restart an old owner if the candidate did not release the native lease."""
    service_action(SERVICE,start=False); clean()
    if previous.get('normal_env_path') and sha(Path(previous['normal_env_path']))!=previous['normal_env_sha256']:
        raise ValueError('PREVIOUS_NORMAL_ENVIRONMENT_CHANGED_REQUIRES_REVIEW')
    for path,key in ((env_path,'env'),(unit_path,'unit')):
        if previous[key+'_exists']: atomic(path,(folder/('previous-labeled.'+key)).read_bytes())
        elif path.exists(): path.unlink(); fsync_directory(path.parent)
    run(['systemctl','daemon-reload'])
    for name,key in ((SERVICE,'labeled'),(NORMAL,'normal')):
        set_service_enabled(name,previous[key]['enabled'])
    sync_service_selection(unit_path)
    for name,key in ((NORMAL,'normal'),(SERVICE,'labeled')):
        if previous[key]['active']: service_action(name,start=True)
    verify_restored(previous,folder)

def unpack(archive,target,pin):
    archive=Path(archive); target=Path(target)
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size>32*1024*1024 or sha(archive)!=pin:
        raise ValueError('CANDIDATE_ARCHIVE_PIN_CHANGED')
    allowed=FILES|HARDWARE_FILES|{'manifest.json','receipt.json'}
    with tarfile.open(str(archive),'r:gz') as source:
        members=source.getmembers()
        if (len(members)!=len(allowed) or {m.name for m in members}!=allowed
                or any(not m.isfile() or m.size>16*1024*1024 for m in members)
                or sum(m.size for m in members)>64*1024*1024):
            raise ValueError('CANDIDATE_ARCHIVE_INVENTORY_INVALID')
        target.mkdir(mode=0o700)
        for member in members:
            with source.extractfile(member) as src,(target/member.name).open('xb') as dst: shutil.copyfileobj(src,dst)

def validate_candidate(store,job,candidate,pin):
    bundle=Bundle(candidate,pin); bundle.hardware_model()
    expected=job['context']['input_contract']; actual=bundle.expected
    common=lambda d:{k:v for k,v in d.items() if k not in ('controller_mode','allowed_controller_modes')}
    if (common(expected)!=common(actual) or expected['controller_mode'] not in actual.get('allowed_controller_modes',[])
            or bundle.provenance['bitstream_sha256']!=job['context']['bitstream_sha256']):
        raise ValueError('CANDIDATE_CONTEXT_DIFFERS')
    current=job['sessions']['episode']['status']['session_id']
    sources=[s for s in bundle.provenance['sessions'] if s['session_id']==current]
    folder=store.folder(job['id'])
    if len(sources)!=1: raise ValueError('CURRENT_JOB_MISSING_FROM_CANDIDATE')
    source=sources[0]
    if (source['label']!=job['label'] or source['episode_id']!=job['episode_id'] or source['split']!=job['episode_split']
            or source['session_sha256']!=sha(folder/'captures/episode/session.json')
            or source['frames_sha256']!=sha(folder/'captures/episode/frames.jsonl')
            or source['learning_sha256']!=sha(folder/'learning.json')
            or bundle.provenance['dataset_sha256']!=job['corpus_summary'].get('dataset_sha256')):
        raise ValueError('CURRENT_JOB_PROVENANCE_CHANGED')
    return bundle

def wait_live(pin,store,job,output,required=128,seconds=45,policy=None):
    if type(required) is not int or required<128:raise ValueError('AT_LEAST_128_REAL_LIVE_WINDOWS_REQUIRED')
    deadline=time.monotonic()+seconds; samples=[]; last=None
    while time.monotonic()<deadline:
        store.check(job,after_switch=True)
        try: r=read_state(Path('/run/cabinet-labeled-npu/state.json'))
        except OSError: r={}
        if (r.get('model_sha256')==pin and r.get('status')=='RUNNING' and r.get('valid') is True
                and r.get('os_boot_id')==store.boot() and 0<=time.monotonic()-r.get('updated_at',-1)<.5):
            count=r.get('inference_count')
            if type(count) is not int or (last is not None and count<last): raise ValueError('CLASSIFIER_RESTARTED_DURING_VALIDATION')
            if count!=last:
                last=count; samples.append(agreement_sample(r,job,policy))
                if len(samples)>=required:
                    agreement=label_agreement(samples,job,policy)
                    minimum=.95 if job['label']=='normal' else .80
                    report=dict(status='PASS_CURRENT_USER_DECLARED_CONDITION' if agreement>=minimum else 'FAIL_CURRENT_DECLARED_CONDITION',
                        user_declared_label=job['label'],samples=samples,agreement=agreement,
                        required_samples=required,observed_samples=len(samples),boot_id=store.boot(),npu_executed=True,
                        manifest_sha256=pin,qualified=False,scope='CURRENT_EPISODE_ONLY_NOT_MULTICLASS_FIELD_ACCURACY',
                        **receipt_fields(job))
                    if len(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False).encode('utf-8'))+1>1048576:
                        raise ValueError('CLASSIFIER_LIVE_VALIDATION_TOO_LARGE')
                    save(output,report)
                    if agreement<minimum: raise ValueError('POST_DEPLOY_CURRENT_LABEL_AGREEMENT_FAILED')
                    return {k:v for k,v in report.items() if k!='samples'}
        time.sleep(.05)
    save(output,dict(status='FAIL_FRESH_CLASSIFIER_INFERENCE_TIMEOUT',samples=samples,manifest_sha256=pin))
    raise ValueError('FRESH_CLASSIFIER_INFERENCE_TIMEOUT')

def sync_service_selection(unit_path=UNIT):
    fsync_directory(Path(unit_path).parent)
    wants=Path(unit_path).parent/'multi-user.target.wants'
    if wants.is_dir():fsync_directory(wants)


def validate_commit(folder,job,transaction,env_path=None,unit_path=None):
    """Recompute the recorded gates before treating COMPLETED as a commit."""
    env_path=LABELED_ENV if env_path is None else env_path;unit_path=UNIT if unit_path is None else unit_path
    folder=Path(folder);env=_environment(env_path);pin=env['BUNDLE_SHA256']
    if (transaction.get('state')!='COMPLETED' or transaction.get('commit_protocol')!=PROTOCOL or
            transaction.get('manifest_sha256')!=pin or transaction.get('current_env_sha256')!=sha(env_path) or
            transaction.get('current_unit_sha256')!=sha(unit_path) or
            transaction.get('deployment_sha256')!=sha(folder/'deployment.json')):
        raise ValueError('COMMITTED_CLASSIFIER_SELECTION_OR_EVIDENCE_CHANGED')
    checked=validate_saved(env);result=read_state(folder/'deployment.json')
    if (result.get('status')!='DEPLOYED_REAL_LABELED_NPU_ADVISORY' or result.get('manifest_sha256')!=pin or
            result.get('model_id')!=checked['model_id'] or result.get('controls_changed') is not False or
            result.get('qualified') is not False or result.get('control_authority')!='NONE' or
            result.get('fault_classes_trained')!=checked['labels'][1:]):
        raise ValueError('COMMITTED_CLASSIFIER_RESULT_CHANGED')
    hardware=result['hardware'];validate_report(hardware,pin,env['LIBRARY_SHA256'],hardware['boot_id'],hardware['kernel_release'])
    if result.get('live_report_sha256')!=sha(folder/'live-validation.json'):raise ValueError('COMMITTED_CLASSIFIER_LIVE_PIN_CHANGED')
    live=read_state(folder/'live-validation.json');samples=live.get('samples',[]);required=live.get('required_samples')
    if (type(required) is not int or required<128 or len(samples)<required or live.get('observed_samples')!=len(samples) or
            live.get('status')!='PASS_CURRENT_USER_DECLARED_CONDITION' or live.get('manifest_sha256')!=pin or
            live.get('user_declared_label')!=job['label'] or live.get('boot_id')!=job['context']['os_boot_id'] or
            live.get('npu_executed') is not True or result.get('live')!={k:v for k,v in live.items() if k!='samples'}):
        raise ValueError('COMMITTED_CLASSIFIER_LIVE_GATE_CHANGED')
    counts=[x['inference_count'] for x in samples]
    check_receipt(live,job)
    policy=None
    if v2_job(job):
        committed_bundle=Bundle(env['BUNDLE'],pin)
        if committed_bundle.expected.get('input_policy')!=job['context']['input_contract']['input_policy']:
            raise ValueError('COMMITTED_CLASSIFIER_INPUT_POLICY_CHANGED')
        policy=committed_bundle.policy
    agreement=label_agreement(samples,job,policy)
    if (any(type(x) is not int for x in counts) or any(b<=a for a,b in zip(counts,counts[1:])) or
            agreement<(.95 if job['label']=='normal' else .80) or live.get('agreement')!=agreement):
        raise ValueError('COMMITTED_CLASSIFIER_RESULT_GATE_CHANGED')
    return result


def finish_committed_job(store,job,transaction,env_path=None,unit_path=None):
    result=validate_commit(store.folder(job['id']),job,transaction,env_path,unit_path)
    recovered=dict(job,state='COMPLETED',progress_percent=100,result=result,updated_at=store.clock(),
        completion_reconciled_from='DURABLE_CLASSIFIER_COMMIT')
    save(store.folder(job['id'])/'job.json',recovered);job.clear();job.update(recovered);return True


def reconcile_committed(store,job):
    folder=store.folder(job['id'])
    try:transaction=read_state(folder/'switch.json')
    except FileNotFoundError:return False
    if transaction.get('state')!='COMPLETED':return False
    with (store.root/'model-switch.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return finish_committed_job(store,job,transaction,env_path=store.env.with_name('labeled-npu.env'))


def deploy(store,identity,worker,archive_sha256,manifest_sha256,destination_root=Path('/opt/cabinet/npu/labeled')):
    folder=store.folder(identity)
    with (store.root/'model-switch.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        job=store.owned(identity,worker); store.check(job)
        from normal_npu.staging import activation_allowed
        if not activation_allowed(job):raise ValueError('USER_REQUESTED_STAGE_ONLY_NO_ACTIVATION')
        if job['state']!='HOST_VALIDATED': raise ValueError('HOST_VALIDATED_CLASSIFIER_REQUIRED')
        candidate=folder/'candidate'; unpack(folder/'candidate.tar.gz',candidate,archive_sha256)
        bundle=validate_candidate(store,job,candidate,manifest_sha256)
        if LIBRARY.is_symlink() or not LIBRARY.is_file() or sha(LIBRARY)!=LIBRARY_SHA256: raise ValueError('REVIEWED_CLASSIFIER_ADAPTER_REQUIRED')
        if run(['systemctl','is-active','cabinet-npu-formal'],check=False).stdout.strip()=='active': raise ValueError('FORMAL_NPU_OWNER_ACTIVE')
        previous=dict(normal=service_state(NORMAL),labeled=service_state(SERVICE),env_exists=LABELED_ENV.exists(),unit_exists=UNIT.exists())
        previous['normal_model_pin']=environment(store.env)['BUNDLE_SHA256']
        previous['normal_env_sha256']=sha(store.env)
        previous['normal_env_path']=str(store.env)
        if previous['env_exists']: previous['labeled_model_pin']=environment(LABELED_ENV)['BUNDLE_SHA256']
        if previous['normal']['active'] and previous['labeled']['active']: raise ValueError('CONFLICTING_NATIVE_SERVICES')
        for path,key in ((LABELED_ENV,'env'),(UNIT,'unit')):
            if path.is_symlink(): raise ValueError('REGULAR_CLASSIFIER_SERVICE_CONFIGURATION_REQUIRED')
            if previous[key+'_exists']: atomic(folder/('previous-labeled.'+key),path.read_bytes())
            previous[key+'_sha256']=sha(path) if previous[key+'_exists'] else None
        save(folder/'previous-services.json',previous)
        transaction=dict(state='PREPARED',commit_protocol=PROTOCOL,manifest_sha256=manifest_sha256,previous=previous,
            previous_services_sha256=sha(folder/'previous-services.json'),env_path=str(LABELED_ENV),unit_path=str(UNIT))
        save(folder/'switch.json',transaction)
        stopped=False; switched=False
        try:
            store.update(identity,worker,state='HARDWARE_VALIDATING',progress_percent=85)
            stopped=True; service_action(NORMAL,start=False); service_action(SERVICE,start=False); clean(); store.check(job)
            env=os.environ.copy(); env['LD_LIBRARY_PATH']='/opt/cabinet/releases/r45_icm_4khz_20261031/sdk/lib'
            args=[sys.executable,'-B','-m','labeled_npu.probe','--bundle',str(candidate),
                '--manifest-sha256',manifest_sha256,'--library',str(LIBRARY),'--library-sha256',LIBRARY_SHA256,
                '--output',str(folder/'hardware-probe')]
            with (folder/'hardware-probe.log').open('w') as log:
                result=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=90)
            if result.returncode: raise ValueError('CLASSIFIER_HARDWARE_PROBE_FAILED')
            admission=folder/'hardware-probe/validation.json'; report=read_state(admission)
            validate_report(report,manifest_sha256,LIBRARY_SHA256,store.boot(),os.uname().release); clean(); store.check(job)
            target=Path(destination_root)/identity
            if target.exists(): raise ValueError('IMMUTABLE_CLASSIFIER_DESTINATION_EXISTS')
            persist_candidate(candidate,admission,target,manifest_sha256)
            current=dict(BUNDLE=str(target/'bundle'),BUNDLE_SHA256=manifest_sha256,LIBRARY=str(LIBRARY),LIBRARY_SHA256=LIBRARY_SHA256,
                ADMISSION=str(target/'admission.json'),ADMISSION_SHA256=sha(target/'admission.json'))
            new_env=(''.join(k+'='+current[k]+'\n' for k in sorted(current))).encode()
            template=Path(__file__).resolve().parents[1]/'systemd/cabinet-labeled-npu.service.example'
            new_unit=template.read_bytes()
            import hashlib
            transaction.update(state='PREPARED_SWITCH',current_env_sha256=hashlib.sha256(new_env).hexdigest(),
                current_unit_sha256=hashlib.sha256(new_unit).hexdigest())
            save(folder/'switch.json',transaction)  # durable planned bytes before either selection write
            atomic(LABELED_ENV,new_env); atomic(UNIT,new_unit); switched=True
            run(['systemctl','daemon-reload']); set_service_enabled(NORMAL,False); set_service_enabled(SERVICE,True)
            sync_service_selection(UNIT)
            transaction.update(state='SWITCHED_AWAITING_LIVE');save(folder/'switch.json',transaction)
            store.update(identity,worker,state='DEPLOYING',progress_percent=93)
            run(['systemctl','start',SERVICE],timeout=100,output=folder/'service-start.log')
            live=wait_live(manifest_sha256,store,job,folder/'live-validation.json',policy=bundle.policy)
            clean_report={k:v for k,v in report.items() if k!='rows'}
            result=dict(status='DEPLOYED_REAL_LABELED_NPU_ADVISORY',manifest_sha256=manifest_sha256,
                model_id=bundle.manifest['model_id'],training=bundle.validation,hardware=clean_report,live=live,
                live_report_sha256=sha(folder/'live-validation.json'),controls_changed=False,qualified=False,
                control_authority='NONE',fault_classes_trained=bundle.manifest['labels'][1:],rollback_directory=str(folder))
            save(folder/'deployment.json',result)
            transaction.update(state='COMPLETED',deployment_sha256=sha(folder/'deployment.json'))
            validate_commit(folder,job,transaction)
            save(folder/'switch.json',transaction)  # sole durable commit point
            return store.update(identity,worker,state='COMPLETED',progress_percent=100,result=result)
        except BaseException as error:
            # A durable committed switch survives any later job-journal failure.
            if read_state(folder/'switch.json').get('state')=='COMPLETED':
                raise RuntimeError('MODEL_COMMITTED_JOB_FINALIZATION_PENDING: '+str(error))
            failures=[]
            if stopped:
                try:
                    from .boot_selection import validate_previous
                    validate_previous(folder,transaction,LABELED_ENV,UNIT,store.env,store.root)
                    restore(previous,folder)
                except Exception as rollback_error: failures.append(str(rollback_error))
            transaction.update(state='ROLLBACK_REQUIRES_REVIEW' if failures else 'PREVIOUS_MODEL_RESTORED',error=str(error),rollback_errors=failures)
            save(folder/'switch.json',transaction)
            raise RuntimeError(str(error)+('; ROLLBACK_REQUIRES_REVIEW '+str(failures) if failures else '; PREVIOUS_MODEL_RESTORED'))

def process_alive(store,folder):
    try:
        p=read_state(folder/'deployment-process.json'); fields=Path('/proc/%d/stat'%p['pid']).read_text().rsplit(')',1)[1].split()
        return p['boot_id']==store.boot() and fields[0]!='Z' and fields[19]==p['start_ticks']
    except (OSError,ValueError,KeyError): return False

def launch(store,identity,worker,archive_pin,manifest_pin):
    folder=store.folder(identity); request=dict(job_id=identity,worker_id=worker,archive_sha256=archive_pin,manifest_sha256=manifest_pin)
    with store.lock():
        job=read_state(folder/'job.json')
        if job.get('worker_id')!=worker or not store.accepts(job): raise ValueError('DEPLOYMENT_OWNER_OR_CHANNEL_CHANGED')
        from normal_npu.staging import activation_allowed, stage_candidate
        if not activation_allowed(job):
            return stage_candidate(store,job,archive_pin,manifest_pin)
        if (folder/'deploy-request.json').exists():
            if read_state(folder/'deploy-request.json')!=request: raise ValueError('DEPLOY_RETRY_PINS_CHANGED')
            if job['state']=='COMPLETED': return dict(state='COMPLETED')
            if process_alive(store,folder): return dict(state='BOARD_DEPLOYMENT_RUNNING')
            raise ValueError('PREVIOUS_DEPLOYMENT_ENDED_REVIEW_TRANSACTION')
        job=store.owned(identity,worker)
        store.check(job)
        if job['state']!='HOST_VALIDATED': raise ValueError('HOST_VALIDATION_REQUIRED')
        save(folder/'deploy-request.json',request)
        with (folder/'deployment-process.log').open('a') as log:
            child=subprocess.Popen([sys.executable,'-B','-m','labeled_npu.deploy','--request-file',str(folder/'deploy-request.json')],
                stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        fields=Path('/proc/%d/stat'%child.pid).read_text().rsplit(')',1)[1].split()
        save(folder/'deployment-process.json',dict(pid=child.pid,start_ticks=fields[19],boot_id=store.boot()))
    return dict(state='BOARD_DEPLOYMENT_STARTED')

def status(store,identity,worker=None):
    folder=store.folder(identity); job=read_state(folder/'job.json')
    if worker is not None and job.get('worker_id')!=worker: raise ValueError('DIFFERENT_DEPLOYMENT_WORKER')
    if job['state'] not in ('COMPLETED','FAILED','INTERRUPTED','CANCELLED') and not process_alive(store,folder):
        return store.fail(identity,job['worker_id'],'BOARD_DEPLOYMENT_PROCESS_ENDED_WITHOUT_COMPLETION')
    return job

def main():
    p=argparse.ArgumentParser(); choice=p.add_mutually_exclusive_group(required=True)
    choice.add_argument('--request-file',type=Path);choice.add_argument('--reconcile-boot',action='store_true');a=p.parse_args()
    if a.reconcile_boot:
        from .boot_selection import reconcile_boot
        try:result=reconcile_boot()
        except Exception as error:
            print(json.dumps(dict(status='RECOVERY_REQUIRES_REVIEW',reason=str(error),npu_inference_verified=False)));return 1
        print(json.dumps(result));return 0
    from .learning import Learning
    store=Learning(); body=read_state(a.request_file)
    if a.request_file.is_symlink() or a.request_file!=store.folder(body['job_id'])/'deploy-request.json': raise ValueError('FIXED_PRIVATE_REQUEST_REQUIRED')
    try: result=deploy(store,body['job_id'],body['worker_id'],body['archive_sha256'],body['manifest_sha256'])
    except Exception as error:
        store.fail(body['job_id'],body['worker_id'],str(error)); raise
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__': sys.exit(main())
