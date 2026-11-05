"""Validate and atomically publish a one-click candidate with retained rollback."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

from .baseline_store import durable_atomic as atomic, durable_save as save, persist_candidate
from .bundle import Bundle
from .learning import environment, sha
from .live import read_state
from .start_gate import validate_report


def run(args, timeout=100, check=True, output=None):
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True, encoding='utf-8', timeout=timeout)
    if output: Path(output).write_text(r.stdout,encoding='utf-8')
    if check and r.returncode: raise RuntimeError('Command failed: '+repr(args[:3])+' '+r.stdout[-1500:])
    return r


def clean():
    if read_state(Path('/var/lib/cabinet/npu-lease/lease.json')).get('state') != 'CLEAN':
        raise ValueError('NATIVE_CLEANUP_NOT_VERIFIED_NO_FORCED_RECOVERY')



def finish_committed_job(store,job,transaction):
    """Reconcile the job journal after the durable model commit; no NPU action."""
    folder=store.folder(job['id']);deployment=folder/'deployment.json';live_path=folder/'live-validation.json'
    if (transaction.get('commit_protocol')!='durable-normal-model-v1' or
            transaction.get('current_env_sha256')!=sha(store.env) or
            transaction.get('deployment_sha256')!=sha(deployment)):
        raise ValueError('COMMITTED_MODEL_EVIDENCE_REQUIRES_REVIEW')
    result=json.loads(deployment.read_text(encoding='utf-8'));env=environment(store.env)
    pin=transaction['candidate_manifest_sha256']
    bundle=Bundle(env['BUNDLE'],pin);bundle.hardware_model()
    if (env['BUNDLE_SHA256']!=pin or result.get('status')!='DEPLOYED_REAL_NORMAL_NPU' or
            result.get('manifest_sha256')!=pin or result.get('model_id')!=bundle.manifest['model_id'] or
            result.get('controls_changed') is not False or result.get('qualified') is not False or
            result.get('fault_classes_trained')!=[] or
            sha(env['LIBRARY'])!=env['LIBRARY_SHA256'] or sha(env['ADMISSION'])!=env['ADMISSION_SHA256']):
        raise ValueError('COMMITTED_MODEL_IDENTITY_REQUIRES_REVIEW')
    hardware=result['hardware']
    validate_report(hardware,pin,env['LIBRARY_SHA256'],hardware['boot_id'],hardware['kernel_release'])
    summary=result['live']
    if (summary.get('report_path')!=str(live_path) or summary.get('report_sha256')!=sha(live_path)):
        raise ValueError('COMMITTED_LIVE_EVIDENCE_REQUIRES_REVIEW')
    live=json.loads(live_path.read_text(encoding='utf-8'));samples=live.get('samples',[])
    required=live.get('required_samples');observed=live.get('observed_samples')
    if (live.get('status')!='PASS' or live.get('manifest_sha256')!=pin or live.get('npu_executed') is not True or
            type(required) is not int or required<512 or type(observed) is not int or observed!=len(samples) or observed<required):
        raise ValueError('COMMITTED_LIVE_SAMPLE_GATE_REQUIRES_REVIEW')
    counts=[sample['inference_count'] for sample in samples]
    rate=sum(sample['state']!='BASELINE_MATCH' for sample in samples)/len(samples)
    if (any(type(n) is not int for n in counts) or any(b<=a for a,b in zip(counts,counts[1:])) or
            rate>.05 or live.get('alarm_rate')!=rate or summary.get('status')!='PASS'):
        raise ValueError('COMMITTED_LIVE_RESULT_GATE_REQUIRES_REVIEW')
    # Called while Learning's job lock and the model-switch lock are held.
    # Write directly: store.update would attempt to acquire the same job lock.
    recovered=dict(job,state='COMPLETED',progress_percent=100,result=result,
                   updated_at=store.clock(),completion_reconciled_from='DURABLE_MODEL_COMMIT')
    save(folder/'job.json',recovered)
    job.clear();job.update(recovered)
    return True


def recover_interrupted(store,job):
    """Recover only a recorded interrupted switch, never a retained native worker."""
    folder=store.folder(job['id'])
    with (store.root/'model-switch.lock').open('a') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('MODEL_SWITCH_STILL_RUNNING')
        transaction=json.loads((folder/'switch.json').read_text(encoding='utf-8'))
        if transaction.get('state')=='COMPLETED':
            return finish_committed_job(store,job,transaction)
        before=folder/'previous.env'
        permitted={sha(before),transaction.get('current_env_sha256')}
        if sha(store.env) not in permitted:raise ValueError('INTERRUPTED_SWITCH_ENV_CHANGED_REQUIRES_REVIEW')
        previous_active=json.loads((folder/'previous-service.json').read_text(encoding='utf-8'))['active']
        if (transaction['state'] in ('PREVIOUS_MODEL_RESTORED','INTERRUPTED_PREVIOUS_MODEL_RESTORED')
                and sha(store.env)==sha(before)
                and (run(['systemctl','is-active','cabinet-normal-npu'],check=False).stdout.strip()=='active')==previous_active):
            # deploy() already verified cleanup and restored the service. A
            # retried failure report must not restart it or erase the cause.
            return
        run(['systemctl','stop','cabinet-normal-npu'],timeout=40)
        # This recovery helper itself checks a different boot, pinned drivers,
        # zero IRQs, no device owners and the OS lease. Same-boot dirty fails.
        from .boot_recovery import recover
        recover();clean();atomic(store.env,before.read_bytes())
        if previous_active:
            run(['systemctl','start','cabinet-normal-npu'],timeout=100)
        save(folder/'switch.json',dict(state='INTERRUPTED_PREVIOUS_MODEL_RESTORED',previous_env_sha256=sha(before)))


def unpack(archive, destination, checksum):
    if archive.is_symlink() or archive.stat().st_size > 32*1024*1024 or sha(archive) != checksum:
        raise ValueError('Candidate archive pin/size differs')
    allowed = {'manifest.json','model_u8.onnx','normalization.json','thresholds.json','provenance.json',
               'golden.json','model_alnpu_u8.onnx','alnpu_conversion.json','training_validation.json','receipt.json'}
    with tarfile.open(str(archive),'r:gz') as source:
        members = source.getmembers()
        if (len(members)!=len(allowed) or {m.name for m in members}!=allowed or
                any(not m.isfile() or m.size>16*1024*1024 for m in members) or sum(m.size for m in members)>64*1024*1024):
            raise ValueError('Candidate inventory is not bounded regular model files')
        destination.mkdir(mode=0o700)
        for m in members:
            with source.extractfile(m) as src, (destination/m.name).open('xb') as dst:
                shutil.copyfileobj(src,dst)


def validate_candidate(store, job, bundle, pin):
    b = Bundle(bundle,pin); b.hardware_model()
    if b.expected != job['context']['input_contract']: raise ValueError('Trained input contract differs')
    v = json.loads((bundle/'training_validation.json').read_text(encoding='utf-8'))
    if (v['status']!='PASS_REAL_NORMAL_ADVISORY_HOST_TRAINING' or v['normal_holdout_frames']<512 or
            not 0<=v['normal_holdout_alarm_rate']<=.05 or v['test_used_for_training_selection_or_threshold'] is not False or
            v['selected']['calibration_mse']>=v['selected']['constant_mean_mse']*.9):
        raise ValueError('Independent normal holdout/reconstruction training gate failed')
    for split,receipt in job['sessions'].items():
        group = b.provenance['sessions'][split]; captures=group.get('captures',[])
        if len(captures)!=1 or group['session_ids'] != [receipt['status']['session_id']]:
            raise ValueError('Training must use exactly this job\'s three real sessions')
        folder=store.folder(job['id'])/'captures'/split
        if (captures[0]['session_sha256']!=sha(folder/'session.json') or
                captures[0]['frames_sha256']!=sha(folder/'frames.jsonl')):
            raise ValueError('Raw session provenance changed')
    return b,v


def wait_live(pin, store, job, limit=120, required_samples=512):
    # A 40-result check covers only about five seconds of overlapping windows.
    # Observe a fixed, longer sequence; retain the same <=5% acceptance limit.
    started=time.monotonic();deadline=started+limit;samples=[];last=None
    report=dict(status='RUNNING',manifest_sha256=pin,required_samples=required_samples,
        false_alarm_budget=.05,samples=samples,npu_executed=True,started_at=started)
    path=store.folder(job['id'])/'live-validation.json'
    save(path,report)
    try:
        while time.monotonic()<deadline:
            store.check(job, after_switch=True)
            try:d=read_state(Path('/run/cabinet-normal-npu/state.json'))
            except OSError:d={}
            if (d.get('model_sha256')==pin and d.get('valid') is True and d.get('status')=='RUNNING' and
                    d.get('os_boot_id')==store.boot() and 0<=time.monotonic()-d.get('updated_at',-1)<.5):
                count=d.get('inference_count')
                if type(count) is not int:raise ValueError('CANDIDATE_INFERENCE_COUNTER_INVALID')
                if last is not None and count<last:raise ValueError('CANDIDATE_SERVICE_RESTARTED_DURING_VALIDATION')
                if count!=last:
                    last=count
                    samples.append({k:d[k] for k in ('frame_id','inference_count','execute_ms','score','state',
                        'domain_score','input_clipped','neural_score','group_scores','assessment','input_values')})
                    report.update(observed_samples=len(samples),elapsed_s=time.monotonic()-started,
                        alarm_rate=sum(s['state']!='BASELINE_MATCH' for s in samples)/len(samples))
                    if len(samples)>=required_samples:
                        if report['alarm_rate']>.05:
                            raise ValueError('POST_DEPLOY_CURRENT_NORMAL_ALARM_RATE %.3f'%report['alarm_rate'])
                        report['status']='PASS';save(path,report);return report
                    if len(samples)%32==0:save(path,report)
            time.sleep(.05)
        raise ValueError('FRESH_CANDIDATE_INFERENCE_TIMEOUT')
    except BaseException as error:
        report.update(status='FAILED',error=str(error),elapsed_s=time.monotonic()-started,
                      observed_samples=len(samples))
        save(path,report)
        raise


def live_summary(report, path):
    # The web and worker repeatedly read job.json. Keep full input vectors in
    # the hash-bound evidence file, not in the frequently decoded job record.
    summary={k:v for k,v in report.items() if k!='samples'}
    summary.update(report_path=str(path),report_sha256=sha(path))
    return summary


def deploy(store, identity, worker, archive_sha256, manifest_sha256, destination_root=Path('/opt/cabinet/npu/learned')):
    folder=store.folder(identity)
    with (store.root/'model-switch.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (Path('/etc/cabinet/labeled-npu.env').exists() or
                run(['systemctl','is-active','cabinet-labeled-npu'],check=False).stdout.strip()=='active'):
            raise ValueError('LABELED_CLASSIFIER_ACTIVE_USE_LABELED_LEARNING')
        job=store.owned(identity,worker);store.check(job)
        from .staging import activation_allowed
        if not activation_allowed(job):raise ValueError('USER_REQUESTED_STAGE_ONLY_NO_ACTIVATION')
        if job['state']!='HOST_VALIDATED': raise ValueError('Candidate must pass host training first')
        candidate=folder/'candidate';unpack(folder/'candidate.tar.gz',candidate,archive_sha256)
        bundle,training=validate_candidate(store,job,candidate,manifest_sha256)
        previous=environment(store.env);previous_raw=store.env.read_bytes()
        if sha(previous['LIBRARY'])!=previous['LIBRARY_SHA256']: raise ValueError('Native adapter changed')
        if run(['systemctl','is-active','cabinet-npu-formal'],check=False).stdout.strip()=='active':
            raise ValueError('FORMAL_NPU_OWNER_ACTIVE')
        save(folder/'switch.json',dict(state='PREPARED',previous_env_sha256=sha(store.env),
            candidate_manifest_sha256=manifest_sha256,config_sha256=sha(store.config)))
        atomic(folder/'previous.env',previous_raw)
        old_active=run(['systemctl','is-active','cabinet-normal-npu'],check=False).stdout.strip()=='active'
        save(folder/'previous-service.json',dict(active=old_active))
        stopped=False;switched=False;committed=False
        try:
            store.update(identity,worker,state='HARDWARE_VALIDATING',progress_percent=85)
            run(['systemctl','stop','cabinet-normal-npu'],timeout=40);stopped=True;clean()
            store.check(job)
            env=os.environ.copy()
            # probe uses the same reviewed SDK and adapter as the live owner.
            env['LD_LIBRARY_PATH']='/opt/cabinet/releases/r45_icm_4khz_20261031/sdk/lib'
            args=[sys.executable,'-B','-m','normal_npu.probe','--bundle',str(candidate),
                '--manifest-sha256',manifest_sha256,'--library',previous['LIBRARY'],
                '--library-sha256',previous['LIBRARY_SHA256'],'--output',str(folder/'hardware-probe')]
            with (folder/'hardware-probe.log').open('w') as log:
                result=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,env=env,timeout=90)
            if result.returncode: raise ValueError('CANDIDATE_HARDWARE_PROBE_FAILED')
            admission=folder/'hardware-probe/validation.json';report=json.loads(admission.read_text(encoding='utf-8'))
            validate_report(report,manifest_sha256,previous['LIBRARY_SHA256'],store.boot(),os.uname().release)
            clean();store.check(job)
            store.update(identity,worker,state='DEPLOYING',progress_percent=93)
            target=destination_root/identity
            persistence=persist_candidate(candidate,admission,target,manifest_sha256)
            current=dict(previous,BUNDLE=persistence['bundle_path'],BUNDLE_SHA256=manifest_sha256,
                ADMISSION=persistence['admission_path'],ADMISSION_SHA256=persistence['admission_sha256'])
            current_raw=(''.join(k+'='+current[k]+'\n' for k in sorted(current))).encode()
            # Journal the exact planned bytes before rename. A power cut between
            # env rename and SWITCHED receipt can still restore previous.env.
            save(folder/'switch.json',dict(state='PREPARED_SWITCH',previous_env_sha256=sha(folder/'previous.env'),
                candidate_manifest_sha256=manifest_sha256,current_env_sha256=hashlib.sha256(current_raw).hexdigest()))
            atomic(store.env,current_raw);switched=True
            save(folder/'switch.json',dict(state='SWITCHED_AWAITING_LIVE',previous_env_sha256=sha(folder/'previous.env'),
                candidate_manifest_sha256=manifest_sha256,current_env_sha256=sha(store.env)))
            run(['systemctl','start','cabinet-normal-npu'],timeout=100,output=folder/'service-start.log')
            live=wait_live(manifest_sha256,store,job)
            store.check(job,after_switch=True)
            result=dict(status='DEPLOYED_REAL_NORMAL_NPU',manifest_sha256=manifest_sha256,
                model_id=bundle.manifest['model_id'],previous_model_sha256=previous['BUNDLE_SHA256'],
                training=training,hardware={k:v for k,v in report.items() if k!='rows'},
                live=live_summary(live,folder/'live-validation.json'),
                rollback_env=str(folder/'previous.env'),persistence=persistence,startup_policy='LOAD_SAVED_NO_AUTOMATIC_LEARNING',controls_changed=False,qualified=False,fault_classes_trained=[])
            save(folder/'deployment.json',result)
            save(folder/'switch.json',dict(state='COMPLETED',commit_protocol='durable-normal-model-v1',
                current_env_sha256=sha(store.env),candidate_manifest_sha256=manifest_sha256,deployment_sha256=sha(folder/'deployment.json')))
            committed=True
            return store.update(identity,worker,state='COMPLETED',progress_percent=100,result=result)
        except BaseException as error:
            if committed:
                # The durable switch receipt is the sole commit point. A lost
                # job-finalization write must never undo an accepted model.
                raise RuntimeError('MODEL_COMMITTED_JOB_FINALIZATION_PENDING: '+str(error))
            failures=[]
            try:
                if switched: run(['systemctl','stop','cabinet-normal-npu'],timeout=40)
                atomic(store.env,previous_raw)
                clean()
                if stopped and old_active: run(['systemctl','start','cabinet-normal-npu'],timeout=100)
            except Exception as rollback_error: failures.append(str(rollback_error))
            save(folder/'switch.json',dict(state='ROLLBACK_REQUIRES_REVIEW' if failures else 'PREVIOUS_MODEL_RESTORED',
                error=str(error),rollback_errors=failures,previous_model_sha256=previous['BUNDLE_SHA256']))
            raise RuntimeError(str(error)+('; ROLLBACK_REQUIRES_REVIEW '+str(failures) if failures else '; PREVIOUS_MODEL_RESTORED'))
