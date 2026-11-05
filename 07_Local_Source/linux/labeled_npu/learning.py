"""User-declared, independently identified physical episodes; automatic transport.

This is an engineering diagnostic corpus, not a relabelling of formal REAL
archives. The sole collector and hardware protection retain ownership.
"""
import hashlib
import json
import os
import re
import shutil
import tarfile
import time
import uuid
from cabinet.normal_reference_guard import bench_reason
from normal_npu.learning import Learning as NormalLearning, TERMINAL, save, sha, rpc
from normal_npu.live import read_state
from normal_npu.core import collector_observation
from cabinet.capture_web import verified_session
from .core import LABELS, INPUT_POLICY, live_input, feature_values
from normal_npu.recovery import TRANSIENT_INPUT
from normal_npu.baseline_store import durable_mkdir, fsync_directory, storage_status
from normal_npu.staging import activation_allowed
from .persistence import durable_copy_tree, saved_classifier_status, archive_status

KIND = 'labeled_classifier'
WINDOW_POLICY = 'INDEPENDENT_LABELED_NPU_WINDOWS'
MINIMUM = dict(train=2, validation=1, test=1)

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def corpus_identity(context):
    contract=dict(context['input_contract'])
    contract.pop('controller_mode',None);contract.pop('allowed_controller_modes',None)
    return dict(device_id=contract['device_id'],input_contract=contract,
                bitstream_sha256=context['bitstream_sha256'],config_sha256=context['config_sha256'])

def corpus_key(context): return fingerprint(corpus_identity(context))

def protection(status):
    return dict(mode=status['mode'],hard_inhibit=status.get('hard_inhibit'),latched=sorted(status.get('latched',[])))

class Learning(NormalLearning):
    def records(self): return [j for j in self.all_records() if j.get('kind') == KIND]
    def accepts(self, job): return job.get('kind') == KIND

    def read_document(self):
        for unused in range(12):
            d=read_state(self.state);o=collector_observation(d);f=o.get('frame')
            if type(f) is not dict:raise ValueError('TEST_OR_INVALID_FRAME_SOURCE')
            h=f.get('header')
            if h or f.get('state')!='EMPTY': break
            time.sleep(.025)
        if not h: raise ValueError('WAIT_FOR_REAL_FRAME')
        return d

    def context(self, label=None, fg_connected_confirmed=False, document=None):
        d=self.read_document() if document is None else document
        o=collector_observation(d);f=o.get('frame')
        if type(f) is not dict:raise ValueError('TEST_OR_INVALID_FRAME_SOURCE')
        h=f.get('header')
        if type(h) is not list or len(h)!=32:raise ValueError('FRAME_HEADER_MISSING')
        if type(o.get('status')) is not dict:raise ValueError('STATUS_MALFORMED')
        expected=dict(device_id=json.loads(self.config.read_text(encoding='utf-8'))['device_id'],
            configuration_words=o['feature_words'],frame_identity=[h[16],h[17],h[18]],
            controller_mode=o['status']['mode'],controller_diagnostic_mode=o['status']['test_mode'],input_policy=INPUT_POLICY)
        live_input(d,self.clock(),expected,label,fg_connected_confirmed)
        platform=json.loads(self.platform.read_text(encoding='utf-8'))
        if platform.get('device_id') != expected['device_id'] or not re.fullmatch('[0-9a-f]{64}',platform.get('bitstream_sha256','')):
            raise ValueError('INSTALLED_PLATFORM_RECEIPT_REQUIRED')
        if platform.get('pl_build_id') != h[26]: raise ValueError('PL_BUILD_CHANGED')
        if bench_reason(o.get('bench')): raise ValueError('STOP_BENCH_BEFORE_LEARNING')
        classifier_env=self.env.with_name('labeled-npu.env')
        return dict(os_boot_id=self.boot(),collector_boot=o['boot'],config_sha256=sha(self.config),
            platform_sha256=sha(self.platform),previous_env_sha256=sha(self.env),input_contract=expected,
            previous_classifier_env_sha256=sha(classifier_env) if classifier_env.exists() else None,
            bitstream_sha256=platform['bitstream_sha256'],capture_guard=protection(o['status']))

    def _job_context(self, job, document):
        # One read per attempt: the shared three-second deadline includes all waits.
        frame=collector_observation(document).get('frame')
        if type(frame) is not dict:raise ValueError('TEST_OR_INVALID_FRAME_SOURCE')
        if not frame.get('header'):
            raise ValueError('WAIT_FOR_REAL_FRAME')
        return self.context(job['label'],job.get('fg_connected_confirmed',False),document=document)

    def coverage(self, key, exported=False, records=None):
        coverage={label:{split:0 for split in MINIMUM} for label in LABELS};seen={}
        for j in self.ordered_records() if records is None else records:
            if j.get('corpus_key') != key: continue
            if exported:
                if not j.get('export_sha256') or not j.get('sessions',{}).get('episode',{}).get('ok'): continue
            elif not j.get('collection_finalized'): continue
            episode=j['episode_id'];definition=(j['label'],j['episode_split'])
            if episode in seen and seen[episode]!=definition: raise ValueError('EPISODE_LABEL_OR_SPLIT_CONFLICT')
            if episode not in seen:
                coverage[j['label']][j['episode_split']]+=1;seen[episode]=definition
        return coverage

    def status(self, snapshot=None):
        labels={};current=None;key=None
        common_error=None
        try:
            document=self.read_document();current=self.context(document=document);key=corpus_key(current)
        except (OSError,ValueError,KeyError,TypeError) as e: common_error=str(e)
        snapshot=self._status_snapshot(snapshot)
        records=self.ordered_records([j for j in snapshot.records if self.accepts(j)])
        busy=any(j['state'] not in TERMINAL for j in snapshot.records)
        context_fingerprint=fingerprint(current) if common_error is None else None
        for label in LABELS:
            try:
                if common_error: raise ValueError(common_error)
                live_input(document,self.clock(),current['input_contract'],label,True)
                labels[label]=dict(ready=not busy,reason=None,
                    context_fingerprint=context_fingerprint,fg_connection_confirmation_required=label=='stall')
            except (OSError,ValueError,KeyError,TypeError) as e:
                labels[label]=dict(ready=False,reason=str(e),context_fingerprint=None,
                    fg_connection_confirmation_required=label=='stall')
        episodes={}
        for j in records:
            if j.get('corpus_key')==key:
                episodes.setdefault(j['episode_id'],dict(episode_id=j['episode_id'],label=j['label'],
                    episode_split=j['episode_split'],created_sequence=j['created_sequence'],collected=False))
                episodes[j['episode_id']]['collected'] |= bool(j.get('collection_finalized'))
        fields=('id','kind','state','label','episode_id','episode_split','created_sequence','updated_at','progress_percent',
                'capture_status','cancel_requested','error','missing','result','collection_finalized')
        coverage=self.coverage(key,records=records) if key else {label:{s:0 for s in MINIMUM} for label in LABELS}
        model=None
        try:
            model=read_state('/run/cabinet-labeled-npu/state.json')
            if model.get('os_boot_id')!=self.boot() or not 0<=self.clock()-model.get('updated_at',-1e9)<.75:
                model=dict(status='STALE',valid=False)
            else:
                fields_model=('status','valid','model_id','model_sha256','inference_count','execute_ms','predicted_label',
                    'label','fault_class','predicted_class','confidence','assessment','state','reason','training_rows','labels','probabilities')
                model={k:model[k] for k in fields_model if k in model}
        except (OSError,ValueError,KeyError,TypeError): pass
        result=dict(schema='cabinet-labeled-learning-status-v1',
            ready=any(x['ready'] for x in labels.values()),labels=labels,corpus_key=key,coverage=coverage,
            missing=missing(coverage),episodes=list(episodes.values()),jobs=[dict({k:j[k] for k in fields if k in j},**self.public_wait(j)) for j in records[-40:]],
            plan=[dict(split='episode',seconds=90)],capture_seconds=90,minimum_complete_windows=600,
            minimum_independent_episodes=MINIMUM,scope='USER_LABELED_DIAGNOSTIC_FIVE_CLASS_NO_CONTROL',
            source='REAL_USER_DECLARED_LABELED_DIAGNOSTIC',qualified=False,manual_export_required=False,
            current_model=model,training_location='MAC_AUTOMATIC_WORKER')
        result.update(self.storage_diagnostics(records,current,key,common_error))
        result['saved_classifier']=saved_classifier_status(self.env.with_name('labeled-npu.env'),self.root)
        return self.refresh_status_worker(result,snapshot)

    def storage_diagnostics(self,records,current,key,context_error):
        groups={};archives={}
        for job in records:
            if not job.get('collection_finalized'):continue
            archives[job['id']]=archive_status(self.folder(job['id']),job)
            groups.setdefault(job['corpus_key'],[]).append(job)
        historical=[]
        for old_key,jobs in groups.items():
            differences=[];contract_error=None
            try:previous=corpus_identity(jobs[-1]['context'])
            except (KeyError,TypeError,ValueError):
                previous=None;contract_error='HISTORICAL_CONTRACT_UNAVAILABLE'
            if current is not None and previous is not None:
                now=corpus_identity(current)
                for name in sorted(set(previous)|set(now)):
                    if previous.get(name)!=now.get(name):differences.append(dict(field=name,previous=previous.get(name),current=now.get(name)))
            checks=[archives[j['id']] for j in jobs]
            historical.append(dict(corpus_key=old_key,current_contract=previous is not None and old_key==key,
                contract_available=previous is not None,contract_error=contract_error,coverage=self.coverage(old_key,records=jobs),
                contract_differences=differences,episodes=len({j['episode_id'] for j in jobs}),
                archive_jobs=len(jobs),verified_archives=sum(x['valid'] for x in checks),saved_on_sd_archives=sum(x['saved_on_sd'] for x in checks),
                archive_issues=[dict(job_id=j['id'],status=archives[j['id']]['status'],reason=archives[j['id']]['reason']) for j in jobs if not archives[j['id']]['valid']]))
        current_jobs=groups.get(key,[]);other=sum(len(jobs) for k,jobs in groups.items() if k!=key)
        state=('CONTEXT_UNAVAILABLE' if current is None else 'CURRENT_CONTRACT_SAMPLES' if current_jobs else
               'NO_CURRENT_SAMPLES_HISTORICAL_AVAILABLE' if other else 'NO_SAMPLES')
        return dict(current_coverage_state=dict(status=state,context_available=current is not None,reason=context_error,
            corpus_key=key,current_registered_jobs=len(current_jobs),historical_registered_jobs=other,
            coverage_basis='REGISTERED_INDEPENDENT_EPISODES_FOR_EXACT_CONTRACT',historical_samples_merged=False),
            historical_corpora=historical,data_storage=dict(learning_root=storage_status(self.root),capture_root=storage_status(self.captures),
                archive_jobs=len(archives),verified_archives=sum(v['valid'] for v in archives.values()),
                saved_on_sd_archives=sum(v['saved_on_sd'] for v in archives.values()),archives=archives,
                automatic_learning=False,boot_creates_training_job=False))

    def start(self, body):
        required={'request_id','label','condition_confirmed','episode_id','episode_confirmed','context_fingerprint','note'}
        if type(body) is not dict or set(body)-{'fg_connected_confirmed'} != required:
            raise ValueError('EXPLICIT_LABEL_EPISODE_CONFIRMATION_REQUIRED')
        if body['condition_confirmed'] is not True or body['episode_confirmed'] is not True:
            raise ValueError('CONFIRM_CURRENT_CONDITION_AND_INDEPENDENT_EPISODE')
        if body['label'] not in LABELS: raise ValueError('UNKNOWN_CONDITION_LABEL')
        if type(body['note']) is not str or len(body['note'])>500 or any(ord(c)<32 for c in body['note']): raise ValueError('INVALID_NOTE')
        if type(body['request_id']) is not str or str(uuid.UUID(body['request_id'])) != body['request_id']:
            raise ValueError('Canonical request UUID required')
        if type(body['episode_id']) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',body['episode_id']):
            raise ValueError('EXPLICIT_PHYSICAL_EPISODE_ID_REQUIRED')
        fg=body.get('fg_connected_confirmed',False)
        if type(fg) is not bool or body['label']=='stall' and not fg: raise ValueError('CONFIRM_STALL_FG_PHYSICALLY_CONNECTED')
        with self.lock():
            records=self.ordered_records()
            for j in records:
                if j['request_id']==body['request_id']:
                    if j['request'] != body: raise ValueError('REQUEST_ID_REUSED')
                    return j
            if self.busy(): raise ValueError('LEARNING_ALREADY_IN_PROGRESS')
            if not self.worker_online(): raise ValueError('TRAINING_HOST_OFFLINE')
            if len(records)>=500: raise ValueError('LEARNING_HISTORY_STORAGE_LIMIT')
            context=self.context(body['label'],fg)
            if fingerprint(context)!=body['context_fingerprint']: raise ValueError('CONDITION_CHANGED_REFRESH_PAGE')
            key=corpus_key(context);existing=[j for j in records if j.get('corpus_key')==key]
            matches=[j for j in existing if j['episode_id']==body['episode_id']]
            if any(j['label']!=body['label'] for j in matches): raise ValueError('EPISODE_LABEL_CONFLICT')
            if matches: split=matches[0]['episode_split']
            else:
                counts=self.coverage(key)[body['label']]
                split=next((s for s,n in MINIMUM.items() if counts[s]<n),'train')
            s=rpc(self.socket,{'operation':'status'})['status']
            if s['state']=='RECORDING': raise ValueError('RECORDER_BUSY')
            if shutil.disk_usage(str(self.root)).free < 256*1024*1024: raise ValueError('LEARNING_DISK_RESERVE')
            identity=uuid.uuid4().hex;folder=self.folder(identity);durable_mkdir(folder)
            j=dict(id=identity,kind=KIND,request_id=body['request_id'],request=body,label=body['label'],
                episode_id=body['episode_id'],episode_split=split,corpus_key=key,condition_confirmed=True,
                episode_confirmed=True,fg_connected_confirmed=fg,note=body['note'],operator='authenticated-local-web',
                label_source='USER_DECLARES_CURRENT_CONDITION',state='QUEUED',
                created_sequence=max([r['created_sequence'] for r in records] or [0])+1,
                created_at=self.clock(),updated_at=self.clock(),context=context,auto_deploy=activation_allowed(),
                cancel_requested=False,sessions={},controls_changed=False,formal_qualification_changed=False,progress_percent=0)
            save(folder/'job.json',j);return j

    def heartbeat(self, worker):
        if type(worker) is not str or not re.fullmatch('[0-9a-f]{32}',worker): raise ValueError('Invalid worker identity')
        with self.lock():
            save(self.root/'worker.json',dict(worker_id=worker,boot_id=self.boot(),updated_at=self.clock()))
            for j in self.records():
                if j['state'] in TERMINAL or j['state']=='RECOVERY_REQUIRED': continue
                changed=j['context']['os_boot_id']!=self.boot() or self.clock()-j['updated_at']>1800
                changed |= j['state']!='QUEUED' and j.get('worker_id')!=worker
                if changed:
                    from .deploy import reconcile_committed
                    if reconcile_committed(self,j):continue
                    self._stop_owned(j)
                    j.update(state='RECOVERY_REQUIRED' if j['state'] in ('HARDWARE_VALIDATING','DEPLOYING','ROLLING_BACK') else 'INTERRUPTED',
                        error='Worker/boot changed or job expired; physical declaration not replayed',updated_at=self.clock())
                    save(self.folder(j['id'])/'job.json',j)
        return dict(online=True)

    def fail(self, identity, worker, error):
        with self.lock():
            p=self.folder(identity)/'job.json';j=json.loads(p.read_text(encoding='utf-8'))
            if not self.accepts(j): raise ValueError('WRONG_LEARNING_CHANNEL')
            if j.get('worker_id')!=worker or j['state'] in TERMINAL or j['state']=='RECOVERY_REQUIRED': return j
            from .deploy import reconcile_committed
            if reconcile_committed(self,j):return j
            self._stop_owned(j)
            switching=j['state'] in ('HARDWARE_VALIDATING','DEPLOYING','ROLLING_BACK')
            if switching:
                try:
                    receipt=json.loads((self.folder(identity)/'switch.json').read_text(encoding='utf-8'))
                    if receipt.get('state')=='PREVIOUS_MODEL_RESTORED': switching=False
                except (OSError,ValueError): pass
            j.update(state='RECOVERY_REQUIRED' if switching else ('CANCELLED' if j['cancel_requested'] else 'FAILED'),
                error=str(error)[:1500],updated_at=self.clock());save(p,j);return j

    def capture_begin(self, identity, worker, split='episode'):
        with self.lock():
            j=self.owned(identity,worker);self.check(j)
            if split!='episode': raise ValueError('ONE_PHYSICAL_EPISODE_PER_CAPTURE')
            if j.get('recording_session_id'): return j
            if j['sessions'] or j['state'] not in ('PREPARING','CAPTURING_EPISODE'): raise ValueError('CAPTURE_ALREADY_SAVED')
            return self._start_capture(j,split)

    def _start_capture(self, j, split):
        if split!='episode':raise ValueError('ONE_PHYSICAL_EPISODE_PER_CAPTURE')
        status=rpc(self.socket,{'operation':'status'})['status']
        if status['state']=='RECORDING': raise ValueError('RECORDER_BUSY')
        if status['boot']!=j['context']['collector_boot']: raise ValueError('COLLECTOR_BOOT_CHANGED')
        payload=dict(expected_boot=status['boot'],installation_id='labeled-'+j['corpus_key'][:24],
            operator=j['operator'],label='unlabelled',duration_s=90,capture_mode='DIAGNOSTIC',window_policy=WINDOW_POLICY,
            bitstream_sha256=j['context']['bitstream_sha256'],calibration_evidence_sha256=None,
            note='User-declared '+j['label']+'; diagnostic raw qualification unchanged; job '+j['id'])
        response=rpc(self.socket,dict(operation='start',request_id=str(uuid.uuid4()),payload=payload))
        if not response.get('ok'): raise ValueError(response.get('reason','CAPTURE_REFUSED'))
        j.update(state='CAPTURING_EPISODE',recording_session_id=response['status']['session_id'],recording_split='episode',updated_at=self.clock())
        save(self.folder(j['id'])/'job.json',j);return j

    def audit_capture(self, source, meta, summary, j):
        c=j['context']
        if (meta.get('boot_id')!=c['collector_boot'] or meta.get('configuration_words')!=c['input_contract']['configuration_words'] or
                meta.get('bitstream_sha256')!=c['bitstream_sha256'] or meta.get('capture_mode')!='DIAGNOSTIC' or
                meta.get('label_declared')!='unlabelled' or meta.get('qualified') is not False or meta.get('window_policy')!=WINDOW_POLICY):
            raise ValueError('CAPTURE_PROVENANCE_CHANGED')
        count=0;previous=meta.get('preceding_frame_id');lost=0;quality_error=None
        with (source/'frames.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                if len(line)>65536 or count>=1000: raise ValueError('CAPTURE_SIZE_BOUND')
                r=json.loads(line);h=r.get('header')
                if (r.get('schema')!='cabinet-capture-frame-v1' or r.get('source')!='REAL_FRM1_DECLARED' or
                        r.get('boot_id')!=c['collector_boot'] or r.get('session_id')!=meta['session_id']):
                    raise ValueError('CAPTURE_ROW_PROVENANCE_CHANGED')
                if protection(r['status']) != c['capture_guard']: raise ValueError('PROTECTION_PHASE_CHANGED_DURING_CAPTURE')
                # Audit the whole archive's hard boundaries before permitting a
                # quality-only retry; no bad row is copied into the training corpus.
                from .core import _flags
                _flags(r['status'],j['label'])
                try:feature_values(h,r.get('feature_words'),r.get('status'),c['input_contract'],j['label'],j['fg_connected_confirmed'])
                except ValueError as error:
                    if str(error) not in TRANSIENT_INPUT:raise
                    quality_error=quality_error or str(error)
                distance=(h[3]-previous)&0xffffffff if previous is not None else 1
                if not 1<=distance<=8 or r.get('gap_before',0)!=distance-1: raise ValueError('CAPTURE_SEQUENCE_INVALID')
                lost+=distance-1;previous=h[3];count+=1
        if quality_error:raise ValueError(quality_error)
        if count<600 or count!=summary['frames'] or lost/max(1,count+lost)>.02: raise ValueError('CAPTURE_WINDOW_COVERAGE_INVALID')
        return count

    def capture_poll(self, identity, worker):
        with self.lock():
            j=self.owned(identity,worker);self.check(j)
            if j['state']=='CAPTURE_SAVED' and not j.get('recording_session_id'): return j
            s=rpc(self.socket,{'operation':'status'})['status']
            if s['session_id']!=j.get('recording_session_id'): raise ValueError('RECORDER_OWNERSHIP_CHANGED')
            j.update(capture_status={k:s[k] for k in ('frames','elapsed_s','duration_s','state','gaps','missing_frames')},
                updated_at=self.clock(),progress_percent=min(60,int(s['elapsed_s']/90*60)))
            if s['state']!='RECORDING':
                if s['state']!='DIAGNOSTIC_SAVED':return self._retry_capture(j,s,s['reason'])
                if s.get('window_policy')!=WINDOW_POLICY:raise ValueError('CAPTURE_WINDOW_POLICY_CHANGED')
                if s['durable_frames']<600:return self._retry_capture(j,s,'INSUFFICIENT_COMPLETE_WINDOWS')
                source,meta,summary=verified_session(self.captures,s['session_id'])
                try:count=self.audit_capture(source,meta,summary,j)
                except ValueError as error:
                    if str(error) not in TRANSIENT_INPUT:raise
                    return self._retry_capture(j,s,str(error))
                folder=self.folder(identity);target=folder/'captures'/'episode'
                durable_copy_tree(source,target)
                j['sessions']['episode']=dict(ok=True,status=s,complete_windows=count)
                j.update(recording_session_id=None,state='CAPTURE_SAVED',progress_detail='本段采集完成，正在继续学习')
                save(folder/'sessions.json',j['sessions'])
            save(self.folder(identity)/'job.json',j);return j

    def export(self, identity, worker):
        j=self.owned(identity,worker);self.check(j)
        if set(j['sessions'])!={'episode'}: raise ValueError('ONE_REAL_EPISODE_REQUIRED')
        folder=self.folder(identity);dest=folder/'captures.tar.gz'
        if j.get('export_sha256') and dest.is_file() and sha(dest)==j['export_sha256']: return dict(path=str(dest),sha256=sha(dest))
        fields=('kind','label','episode_id','episode_split','corpus_key','condition_confirmed','episode_confirmed',
                'fg_connected_confirmed','note','operator','label_source','context')
        provenance={k:j[k] for k in fields}
        save(folder/'learning.json',dict(schema='cabinet-one-click-labeled-learning-v1',job_id=identity,
            source='REAL_USER_DECLARED_LABELED_DIAGNOSTIC',raw_capture_qualification_changed=False,
            qualified=False,auto_deploy=j.get('auto_deploy',True),**provenance))
        with tarfile.open(str(dest)+'.next','w:gz') as output:
            for name in ('captures','sessions.json','learning.json'): output.add(str(folder/name),arcname=name)
        with open(str(dest)+'.next','rb') as stream:os.fsync(stream.fileno())
        os.replace(str(dest)+'.next',str(dest));fsync_directory(dest.parent)
        self.update(identity,worker,state='REGISTERING_DATA',progress_percent=65,export_sha256=sha(dest))
        return dict(path=str(dest),sha256=sha(dest))

    def finalize_collection(self, identity, worker, corpus_summary):
        with self.lock():
            previous=json.loads((self.folder(identity)/'job.json').read_text(encoding='utf-8'))
            if previous.get('worker_id')!=worker or not self.accepts(previous): raise ValueError('JOB_NOT_OWNED_OR_WRONG_CHANNEL')
            if previous.get('collection_finalized'):
                if previous.get('corpus_summary')!=corpus_summary: raise ValueError('COLLECTION_RETRY_SUMMARY_CHANGED')
                return previous
            j=self.owned(identity,worker);self.check(j)
            if j['state'] not in ('REGISTERING_DATA','TRAINING'): raise ValueError('EXPORTED_COLLECTION_REQUIRED')
            if type(corpus_summary) is not dict or corpus_summary.get('corpus_key')!=j['corpus_key']:
                raise ValueError('CORPUS_IDENTITY_CHANGED')
            if (corpus_summary.get('source')!='REAL_USER_DECLARED_LABELED_DIAGNOSTIC' or
                    type(corpus_summary.get('dataset_sha256')) is not str or
                    not re.fullmatch('[0-9a-f]{64}',corpus_summary['dataset_sha256']) or
                    corpus_summary.get('registered_session')!=j['sessions']['episode']['status']['session_id']):
                raise ValueError('CORPUS_PROVENANCE_REQUIRED')
            actual=self.coverage(j['corpus_key'],exported=True);coverage=corpus_summary.get('coverage')
            if type(coverage) is not dict or set(coverage)!=set(LABELS): raise ValueError('FIVE_CLASS_COVERAGE_REQUIRED')
            for label in LABELS:
                if type(coverage[label]) is not dict or set(coverage[label])!=set(MINIMUM): raise ValueError('SPLIT_COVERAGE_REQUIRED')
                for split,n in coverage[label].items():
                    if type(n) is not int or n<0 or n>actual[label][split]: raise ValueError('CORPUS_INDEPENDENT_EPISODES_OVERCLAIMED')
            if coverage[j['label']][j['episode_split']]<1: raise ValueError('CURRENT_EPISODE_NOT_IN_CORPUS')
            needed=missing(coverage)
            if corpus_summary.get('status')!=('WAITING_DATA' if needed else 'READY_TO_TRAIN'):
                raise ValueError('CORPUS_READINESS_OVERCLAIMED')
            j.update(state='COLLECTED_WAITING_DATA' if needed else 'TRAINING',collection_finalized=True,
                corpus_summary=corpus_summary,missing=needed,updated_at=self.clock(),progress_percent=100 if needed else 70)
            save(self.folder(identity)/'job.json',j);return j

def missing(coverage):
    return [dict(label=label,split=split,have=coverage[label][split],need=minimum,
                 missing=max(0,minimum-coverage[label][split]))
            for label in LABELS for split,minimum in MINIMUM.items() if coverage[label][split]<minimum]
