"""Durable normal-condition learning jobs. No actuator or second MMIO owner."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
from cabinet.normal_reference_guard import bench_reason
from cabinet.alarm_only import advisory_filtered_active
import re
import shutil
import tarfile
import time
import uuid

from cabinet.capture_web import verified_session
from .baseline_store import durable_atomic as atomic, durable_mkdir, fsync_directory
from hmi_daily.cabinet.learning_rpc import request as rpc
from .core import collector_observation, live_input
from .live import read_state
from .recovery import await_stable, description, RETRY_CAPTURE, MAX_EXTRA_CAPTURE_ATTEMPTS

from .staging import activation_allowed

ROOT = Path('/var/lib/cabinet/npu-learning')
STATE = Path('/run/cabinet-live/state.json')
CONFIG = Path('/etc/cabinet/edge.json')
PLATFORM = Path('/etc/cabinet/npu-learning-platform.json')
ENV = Path('/etc/cabinet/normal-npu.env')
SOCKET = Path('/run/cabinet-live/capture.sock')
CAPTURES = Path('/var/lib/cabinet/captures')
SPLITS = [('train', 180), ('calibration', 90), ('test', 90)]
TERMINAL = ('COMPLETED', 'FAILED', 'CANCELLED', 'INTERRUPTED', 'COLLECTED_WAITING_DATA')


class _StatusSnapshot:
    """Request-local display inputs; never used by learning mutations."""
    def __init__(self, root, records, heartbeat):
        self.root, self.records, self.heartbeat = root, records, heartbeat


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''): h.update(chunk)
    return h.hexdigest()


def save(path, value):
    atomic(Path(path), (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)+'\n').encode())


def boot_id(): return Path('/proc/sys/kernel/random/boot_id').read_text(encoding='utf-8').strip()


def environment(path=ENV):
    result = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'): continue
        k, v = line.split('=', 1)
        if k not in ('BUNDLE', 'BUNDLE_SHA256', 'LIBRARY', 'LIBRARY_SHA256', 'ADMISSION', 'ADMISSION_SHA256'):
            raise ValueError('Unknown normal NPU environment entry')
        result[k] = v
    if len(result) != 6: raise ValueError('Incomplete normal NPU environment')
    return result


class Learning:
    def __init__(self, root=ROOT, config=CONFIG, state=STATE, platform=PLATFORM, env=ENV,
                 socket=SOCKET, captures=CAPTURES, boot=boot_id, clock=time.monotonic):
        self.root, self.config, self.state = Path(root), Path(config), Path(state)
        self.platform, self.env, self.socket, self.captures = Path(platform), Path(env), Path(socket), Path(captures)
        self.boot, self.clock = boot, clock
        if self.root.is_symlink(): raise ValueError('Regular learning directory required')
        durable_mkdir(self.root)
        durable_mkdir(self.root/'jobs')
        self._busy_states = {}

    @contextlib.contextmanager
    def lock(self):
        with (self.root/'lock').open('a') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            yield

    def all_records(self):
        return [json.loads(p.read_text(encoding='utf-8')) for p in sorted((self.root/'jobs').glob('*/job.json'))]

    def status_snapshot(self):
        records=self.all_records()
        try:heartbeat=json.loads((self.root/'worker.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):heartbeat=None
        return _StatusSnapshot(self.root.resolve(),records,heartbeat)

    def _status_snapshot(self, snapshot):
        if snapshot is None:return self.status_snapshot()
        if not isinstance(snapshot,_StatusSnapshot) or snapshot.root!=self.root.resolve():
            raise ValueError('STATUS_SNAPSHOT_ROOT_MISMATCH')
        return snapshot

    def refresh_status_worker(self, result, snapshot):
        """Recheck the original heartbeat's age at output, without a reread."""
        snapshot=self._status_snapshot(snapshot);h=snapshot.heartbeat
        try:online=type(h) is dict and h.get('boot_id')==self.boot() and 0<=self.clock()-h['updated_at']<45
        except (OSError,ValueError,KeyError,TypeError):online=False
        result['worker_online']=online
        result['ready']=result['ready'] and online
        for label in result.get('labels',{}).values():label['ready']=label['ready'] and online
        return result

    def records(self):
        # Share the recorder/learning lock, not labels or model semantics.
        return [j for j in self.all_records() if j.get('kind') != 'labeled_classifier']

    def accepts(self, job): return job.get('kind') != 'labeled_classifier'

    def ordered_records(self, records=None):
        records = self.records() if records is None else records
        # Monotonic timestamps reset on reboot. Existing history must receive
        # an audited sequence migration; never guess its order from those times.
        sequences = [j.get('created_sequence') for j in records]
        if any(type(n) is not int or n < 1 for n in sequences):
            raise ValueError('LEARNING_HISTORY_SEQUENCE_MIGRATION_REQUIRED')
        if len(set(sequences)) != len(sequences):
            raise ValueError('LEARNING_HISTORY_SEQUENCE_INVALID_DUPLICATE')
        return sorted(records, key=lambda j:j['created_sequence'])

    def busy(self):
        # This query also runs in the BNC1 500 ms renewal loop. Historical job
        # records contain large capture/deployment reports; reparsing all of
        # them twice per poll can expire that hardware lease. Cache only the
        # state, and stat every path on every call. Durable job writes use
        # atomic replacement, so a new inode invalidates even same-size edits.
        for path in sorted((self.root/'jobs').glob('*/job.json')):
            stat = path.stat()
            version = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            cached = self._busy_states.get(path)
            if cached is None or cached[0] != version:
                state = json.loads(path.read_text(encoding='utf-8'))['state']
                cached = (version, state)
                self._busy_states[path] = cached
            if cached[1] not in TERMINAL:
                return True
        return False

    def folder(self, identity):
        if type(identity) is not str or not re.fullmatch('[0-9a-f]{32}', identity): raise ValueError('Invalid learning job')
        return self.root/'jobs'/identity

    def context(self, document=None):
        if self.env.with_name('labeled-npu.env').exists():
            raise ValueError('CLASSIFIER_ACTIVE_USE_LABELED_LEARNING')
        # The sole collector legitimately publishes EMPTY on polls between
        # 128 ms windows. Await its next real frame; do not flicker readiness or
        # manufacture features from a prior model's input contract.
        for unused in range(1 if document is not None else 12):
            d = read_state(self.state) if document is None else document
            o = collector_observation(d); frame=o.get('frame')
            if type(frame) is not dict:raise ValueError('TEST_OR_INVALID_FRAME_SOURCE')
            h=frame.get('header')
            if h or frame.get('state')!='EMPTY':break
            if document is None:time.sleep(.025)
        if not h: raise ValueError('WAIT_FOR_REAL_FRAME')
        if type(h) is not list or len(h)!=32:raise ValueError('FRAME_HEADER_MISSING')
        if type(o.get('status')) is not dict:raise ValueError('STATUS_MALFORMED')
        expected = dict(device_id=json.loads(self.config.read_text(encoding='utf-8'))['device_id'],
            configuration_words=o['feature_words'], frame_identity=[h[16], h[17], h[18]],
            controller_mode=o['status']['mode'], controller_diagnostic_mode=bool(o['status']['test_mode']))
        live_input(d, self.clock(), expected)
        platform = json.loads(self.platform.read_text(encoding='utf-8'))
        if platform.get('device_id') != expected['device_id'] or not re.fullmatch('[0-9a-f]{64}', platform.get('bitstream_sha256', '')):
            raise ValueError('INSTALLED_PLATFORM_RECEIPT_REQUIRED')
        if platform.get('pl_build_id') != h[26]: raise ValueError('PL_BUILD_CHANGED')
        if bench_reason(o.get('bench')): raise ValueError('STOP_BENCH_BEFORE_LEARNING')
        context = dict(os_boot_id=self.boot(), collector_boot=o['boot'],
            config_sha256=sha(self.config), platform_sha256=sha(self.platform),
            previous_env_sha256=sha(self.env), input_contract=expected,
            bitstream_sha256=platform['bitstream_sha256'],capture_guard=self.protection(o['status']))
        return context

    @staticmethod
    def protection(status):
        return dict(mode=status.get('mode'),hard_inhibit=status.get('hard_inhibit'),latched=sorted(status.get('latched',[])))

    def _fixed_context(self, job, document, after_switch):
        """Check hard boundaries before classifying any bad window as transient."""
        c=job['context'];expected=c['input_contract']
        if (self.boot()!=c['os_boot_id'] or sha(self.config)!=c['config_sha256'] or
                sha(self.platform)!=c['platform_sha256']):
            raise ValueError('LEARNING_CONTEXT_CHANGED')
        if not after_switch and sha(self.env)!=c['previous_env_sha256']:
            raise ValueError('LEARNING_CONTEXT_CHANGED')
        if job.get('kind')=='labeled_classifier' and not after_switch:
            classifier=self.env.with_name('labeled-npu.env')
            if (sha(classifier) if classifier.exists() else None)!=c['previous_classifier_env_sha256']:
                raise ValueError('LEARNING_CONTEXT_CHANGED')
        o=collector_observation(document)
        if (('boot' in o and o['boot']!=c['collector_boot']) or
                ('feature_words' in o and o['feature_words']!=expected['configuration_words'])):
            raise ValueError('LEARNING_CONTEXT_CHANGED')
        if o.get('link')!='ONLINE' or any(k not in o for k in ('status','boot','feature_words')):
            raise ValueError('COLLECTOR_STALE')
        status=o['status'];frame=o.get('frame') or {};h=frame.get('header')
        if frame.get('state') not in ('RECEIVED_REAL','EMPTY'):raise ValueError('TEST_OR_INVALID_FRAME_SOURCE')
        if h is not None:
            from .core import PL_BUILD
            if type(h) is not list or len(h)!=32:raise ValueError('FRAME_HEADER_MISSING')
            if h[26]!=PL_BUILD or h[16:19]!=expected['frame_identity']:raise ValueError('FEATURE_OR_CALIBRATION_CHANGED')
            if h[27] or h[15]&0x4000:raise ValueError('TEST_FRAME_REJECTED')
            if h[11:13]!=[1024,1024] or h[21]!=100000000:raise ValueError('WINDOW_CONTRACT_CHANGED')
        if job.get('kind')!='labeled_classifier' and (advisory_filtered_active(status)-{'CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'} or status.get('latched')):
            raise ValueError('HARDWARE_FAULT_ACTIVE')
        if (status.get('mode')!=expected['controller_mode'] or
                bool(status.get('test_mode'))!=expected['controller_diagnostic_mode'] or
                ('capture_guard' in c and self.protection(status)!=c['capture_guard'])):
            raise ValueError('LEARNING_CONTEXT_OR_PROTECTION_PHASE_CHANGED')
        if job.get('kind')=='labeled_classifier':
            from labeled_npu.core import _flags
            _flags(status,job['label'])

    def _job_context(self, job, document): return self.context(document=document)

    def _publish_wait(self, job, fields):
        # Separate atomic status avoids overwriting cancellation/worker updates.
        save(self.folder(job['id'])/'waiting.json',dict(fields,job_id=job['id'],os_boot_id=self.boot()))

    def public_wait(self, job):
        result={k:job[k] for k in ('capture_attempts','progress_detail') if k in job}
        if job['state'] in TERMINAL:return result
        try:
            waiting=json.loads((self.folder(job['id'])/'waiting.json').read_text(encoding='utf-8'))
            if (job['state'] not in TERMINAL and waiting.get('waiting_stable') and waiting.get('os_boot_id')==self.boot()
                    and 0<=time.monotonic()-waiting['waiting_since']<=waiting['waiting_deadline']-waiting['waiting_since']):
                result.update({k:v for k,v in waiting.items() if k not in ('job_id','os_boot_id')})
        except (OSError,ValueError,KeyError,TypeError):pass
        return result

    def check(self, job, after_switch=False):
        def probe():
            saved=json.loads((self.folder(job['id'])/'job.json').read_text(encoding='utf-8'))
            if saved.get('cancel_requested'):raise ValueError('CANCEL_REQUESTED')
            if saved.get('request')!=job.get('request'):raise ValueError('LEARNING_DECLARATION_CHANGED')
            document=read_state(self.state)
            self._fixed_context(job,document,after_switch)
            current=self._job_context(job,document);expected=dict(job['context'])
            if after_switch:
                for name in ('previous_env_sha256','previous_classifier_env_sha256'):
                    current.pop(name,None);expected.pop(name,None)
            if current!=expected:raise ValueError('LEARNING_CONTEXT_CHANGED')
        return await_stable(probe,lambda fields:self._publish_wait(job,fields))

    def worker_online(self):
        try:
            h = json.loads((self.root/'worker.json').read_text(encoding='utf-8'))
            return h.get('boot_id') == self.boot() and 0 <= self.clock()-h['updated_at'] < 45
        except (OSError, ValueError, KeyError): return False

    def status(self, snapshot=None):
        reason = None; fingerprint = None
        try:
            context = self.context()
            fingerprint = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
        except (OSError, ValueError, KeyError, TypeError) as e: reason = str(e)
        snapshot=self._status_snapshot(snapshot)
        records=self.ordered_records([j for j in snapshot.records if self.accepts(j)])
        busy=any(j['state'] not in TERMINAL for j in snapshot.records)
        current = None
        try:
            current = read_state('/run/cabinet-normal-npu/state.json')
            fresh = current.get('os_boot_id') == self.boot() and 0 <= self.clock()-current.get('updated_at', -1e9) < .75
            if not fresh: current = dict(status='STALE', valid=False)
            else:
                keys = ('status', 'valid', 'model_id', 'model_sha256', 'inference_count', 'execute_ms',
                    'score', 'neural_score', 'domain_score', 'input_clipped', 'assessment', 'state', 'reason', 'training_rows', 'advisory')
                current = {k: current[k] for k in keys if k in current}
        except (OSError, ValueError): pass
        public=[]
        for j in records[-20:]:
            item={k:j[k] for k in ('id','state','created_sequence','created_at','updated_at','progress_percent','capture_status','error','cancel_requested') if k in j}
            item.update(self.public_wait(j))
            if j.get('result',{}).get('status')=='TRAINED_SAVED_NOT_DEPLOYED':
                r=j['result'];item['result']={k:r[k] for k in ('status','deployed','saved','saved_on_sd','label','model_id','manifest_sha256','bundle_path','hardware_validation','awaiting')}
                item['result'].update(normal_holdout_frames=r['training']['normal_holdout_frames'],normal_holdout_alarm_rate=r['training']['normal_holdout_alarm_rate'])
            elif j.get('result'):
                r=j['result'];item['result']=dict(model_id=r['model_id'],manifest_sha256=r['manifest_sha256'],
                    normal_holdout_frames=r['training']['normal_holdout_frames'],
                    normal_holdout_alarm_rate=r['training']['normal_holdout_alarm_rate'],
                    npu_p99_ms=r['hardware']['execute_ms']['p99'],hardware_vectors=r['hardware']['vectors'],
                    hardware_irq_delta=r['hardware']['irq_delta'],post_deploy_alarm_rate=r['live']['alarm_rate'])
            public.append(item)
        from .baseline_store import saved_baseline_status
        result=dict(schema='cabinet-npu-learning-v1',
            saved_baseline=saved_baseline_status(self.env,self.root),
            ready=reason is None and not busy, reason=reason,
            context_fingerprint=fingerprint, jobs=public,
            plan=[dict(split=n, seconds=s) for n,s in SPLITS], capture_seconds=sum(s for n,s in SPLITS),
            current_model=current, scope='NORMAL_CONDITION_RECONSTRUCTION_NO_FAULT_CLASSES_NO_CONTROL',
            training_location='MAC_AUTOMATIC_WORKER', manual_export_required=False)
        return self.refresh_status_worker(result,snapshot)

    def start(self, body):
        if set(body) != {'request_id', 'healthy_confirmed', 'context_fingerprint'} or body['healthy_confirmed'] is not True:
            raise ValueError('CONFIRM_CURRENT_HEALTHY_CONDITION')
        if str(uuid.UUID(body['request_id'])) != body['request_id']: raise ValueError('Canonical request UUID required')
        with self.lock():
            records = self.records()
            for j in records:
                if j['request_id'] == body['request_id']:
                    if j.get('request') != body: raise ValueError('REQUEST_ID_REUSED')
                    return j
            records = self.ordered_records(records)
            if self.busy(): raise ValueError('LEARNING_ALREADY_IN_PROGRESS')
            if any(j['state']=='RECOVERY_REQUIRED' for j in records):raise ValueError('NPU_RECOVERY_REQUIRES_REVIEW')
            if not self.worker_online(): raise ValueError('TRAINING_HOST_OFFLINE')
            if len(records) >= 100: raise ValueError('LEARNING_HISTORY_STORAGE_LIMIT')
            context = self.context()
            if hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest() != body['context_fingerprint']:
                raise ValueError('CONDITION_CHANGED_REFRESH_PAGE')
            s = rpc(self.socket, {'operation':'status'})['status']
            if s['state'] == 'RECORDING': raise ValueError('RECORDER_BUSY')
            if shutil.disk_usage(str(self.root)).free < 256*1024*1024: raise ValueError('LEARNING_DISK_RESERVE')
            identity = uuid.uuid4().hex; folder = self.folder(identity); folder.mkdir(mode=0o700)
            fsync_directory(folder);fsync_directory(folder.parent)
            j = dict(id=identity, request_id=body['request_id'], request=body, state='QUEUED',
                created_sequence=max([r['created_sequence'] for r in records] or [0])+1,
                created_at=self.clock(), updated_at=self.clock(), context=context,
                healthy_confirmed=True, label_source='USER_DECLARES_CURRENT_CONDITION_NORMAL',
                auto_deploy=activation_allowed(), cancel_requested=False, sessions={}, controls_changed=False,
                formal_qualification_changed=False, progress_percent=0)
            save(folder/'job.json', j)
            return j

    def cancel(self, body):
        if set(body) != {'job_id'}: raise ValueError('Job identity required')
        with self.lock():
            p = self.folder(body['job_id'])/'job.json'; j = json.loads(p.read_text(encoding='utf-8'))
            if not self.accepts(j): raise ValueError('WRONG_LEARNING_CHANNEL')
            if j['state'] in TERMINAL: return j
            if j['state'] in ('HARDWARE_VALIDATING', 'DEPLOYING', 'ROLLING_BACK','RECOVERY_REQUIRED'):
                raise ValueError('MODEL_SWITCH_IN_PROGRESS_WAIT_FOR_ATOMIC_RESULT')
            j.update(cancel_requested=True, updated_at=self.clock())
            if j['state'] == 'QUEUED': j.update(state='CANCELLED')
            save(p,j); return j

    def heartbeat(self, worker):
        if type(worker) is not str or not re.fullmatch('[0-9a-f]{32}', worker): raise ValueError('Invalid worker identity')
        with self.lock():
            save(self.root/'worker.json', dict(worker_id=worker, boot_id=self.boot(), updated_at=self.clock()))
            # A missing worker never silently resumes an old healthy declaration.
            for j in self.records():
                if j['state'] in TERMINAL or j['state']=='RECOVERY_REQUIRED': continue
                if j['state'] in ('HARDWARE_VALIDATING','DEPLOYING') and (j.get('worker_id')!=worker or j['context']['os_boot_id']!=self.boot()):
                    from .learning_deploy import recover_interrupted
                    if recover_interrupted(self,j):continue
                if j['context']['os_boot_id'] != self.boot() or self.clock()-j['updated_at'] > 1800:
                    self._stop_owned(j)
                    j.update(state='INTERRUPTED', error='Boot changed or job expired; start a new normal-condition learning job')
                    save(self.folder(j['id'])/'job.json', j)
                elif j['state'] != 'QUEUED' and j.get('worker_id') != worker:
                    self._stop_owned(j)
                    j.update(state='INTERRUPTED', error='Training worker restarted; previous job not replayed')
                    save(self.folder(j['id'])/'job.json', j)
        return dict(online=True)

    def claim(self, worker):
        with self.lock():
            for j in self.ordered_records():
                if j['state'] != 'QUEUED': continue
                try:self.check(j)
                except (OSError,ValueError,KeyError) as e:
                    j.update(state='FAILED',error=str(e));save(self.folder(j['id'])/'job.json',j);continue
                j.update(worker_id=worker, state='PREPARING', updated_at=self.clock())
                save(self.folder(j['id'])/'job.json',j)
                return j
        return None

    def owned(self, identity, worker):
        j = json.loads((self.folder(identity)/'job.json').read_text(encoding='utf-8'))
        if not self.accepts(j): raise ValueError('WRONG_LEARNING_CHANNEL')
        if j.get('worker_id') != worker or j['state'] in TERMINAL: raise ValueError('JOB_NOT_OWNED_OR_TERMINAL')
        if j['cancel_requested']: raise ValueError('CANCEL_REQUESTED')
        return j

    def update(self, identity, worker, **values):
        with self.lock():
            j = self.owned(identity, worker)
            j.update(values, updated_at=self.clock()); save(self.folder(identity)/'job.json', j)
            return j

    def _stop_owned(self, j):
        identity = j.get('recording_session_id')
        if identity:
            try:
                s = rpc(self.socket, {'operation':'status'})['status']
                if s['state'] == 'RECORDING' and s['session_id'] == identity:
                    rpc(self.socket, dict(operation='stop',request_id=str(uuid.uuid4()),payload={'session_id':identity}))
            except (OSError, ValueError, RuntimeError): pass

    def fail(self, identity, worker, error):
        with self.lock():
            p = self.folder(identity)/'job.json'; j = json.loads(p.read_text(encoding='utf-8'))
            if not self.accepts(j): raise ValueError('WRONG_LEARNING_CHANNEL')
            if j.get('worker_id') != worker or j['state'] in TERMINAL or j['state']=='RECOVERY_REQUIRED': return j
            if j['state'] in ('HARDWARE_VALIDATING','DEPLOYING'):
                from .learning_deploy import recover_interrupted
                try:
                    if recover_interrupted(self,j):return j
                except ValueError as recovery:
                    if str(recovery)=='MODEL_SWITCH_STILL_RUNNING':raise
                    j.update(state='RECOVERY_REQUIRED',error=str(error)+'; '+str(recovery),updated_at=self.clock())
                    save(p,j);return j
                except Exception as recovery:
                    j.update(state='RECOVERY_REQUIRED',error=str(error)+'; '+str(recovery),updated_at=self.clock())
                    save(p,j);return j
            self._stop_owned(j)
            j.update(state='CANCELLED' if j['cancel_requested'] else 'FAILED', error=str(error)[:1500], updated_at=self.clock())
            save(p,j); return j

    def capture_begin(self, identity, worker, split):
        with self.lock():
            j = self.owned(identity,worker); self.check(j)
            if j.get('recording_session_id') and j.get('recording_split')==split:return j
            names = [n for n,s in SPLITS]
            if split not in names or list(j['sessions']) != names[:names.index(split)]: raise ValueError('CAPTURE_SPLIT_ORDER')
            if split=='test':
                precheck=j.get('calibration_precheck',{})
                if (precheck.get('decision')!='PASS_CALIBRATION_INPUT_QUALITY' or
                        precheck.get('calibration_session_id')!=j['sessions']['calibration']['status']['session_id']):
                    raise ValueError('CALIBRATION_INPUT_PRECHECK_REQUIRED_BEFORE_TEST')
            if j.get('recording_session_id'): raise ValueError('CAPTURE_ALREADY_STARTED')
            return self._start_capture(j,split)

    def _start_capture(self, j, split):
        status = rpc(self.socket, {'operation':'status'})['status']
        if status['state']=='RECORDING': raise ValueError('RECORDER_BUSY')
        if status['boot']!=j['context']['collector_boot']:raise ValueError('COLLECTOR_BOOT_CHANGED')
        payload = dict(expected_boot=status['boot'], installation_id='one-click-'+j['id'][:16],
            operator='authenticated-local-web', label='unlabelled', duration_s=dict(SPLITS)[split],
            capture_mode='DIAGNOSTIC',window_policy='INDEPENDENT_NORMAL_NPU_WINDOWS',bitstream_sha256=j['context']['bitstream_sha256'],
            calibration_evidence_sha256=None,
            note='User-confirmed healthy normal-only NPU learning; raw capture remains diagnostically unqualified. Job '+j['id'])
        response = rpc(self.socket,dict(operation='start',request_id=str(uuid.uuid4()),payload=payload))
        if not response.get('ok'): raise ValueError(response.get('reason','CAPTURE_REFUSED'))
        j.update(state='CAPTURING_'+split.upper(), recording_session_id=response['status']['session_id'],
            recording_split=split, updated_at=self.clock())
        save(self.folder(j['id'])/'job.json',j); return j

    def _check_capture_terminal(self, j, summary):
        terminal=summary.get('terminal_observation')
        if type(terminal) is not dict or terminal.get('schema')!='cabinet-capture-terminal-observation-v1':
            raise ValueError('CAPTURE_TERMINAL_EVIDENCE_REQUIRED')
        expected=j['context']['input_contract'];st=terminal.get('status');h=terminal.get('frame_header')
        if (terminal.get('source')!='REAL_COLLECTOR_DECLARED' or terminal.get('test') is not False or
                terminal.get('link')!='ONLINE' or terminal.get('boot')!=j['context']['collector_boot'] or
                terminal.get('configuration_words')!=expected['configuration_words'] or type(st) is not dict or
                terminal.get('raw_status_words')!=st.get('raw_words') or
                self.protection(st)!=j['context']['capture_guard'] or
                bool(st.get('test_mode'))!=expected['controller_diagnostic_mode']):
            raise ValueError('CAPTURE_TERMINAL_CONTEXT_OR_PROTECTION_CHANGED')
        if h is not None:
            from .core import PL_BUILD
            if (type(h) is not list or len(h)!=32 or h[26]!=PL_BUILD or h[27] or h[15]&0x4000 or
                    h[16:19]!=expected['frame_identity']):
                raise ValueError('CAPTURE_TERMINAL_FRAME_IDENTITY_CHANGED')
        if j.get('kind')=='labeled_classifier':
            from labeled_npu.core import _flags
            _flags(st,j['label'])
        elif advisory_filtered_active(st)-{'CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'} or st.get('latched'):
            raise ValueError('HARDWARE_FAULT_ACTIVE')

    def _retry_capture(self, j, status, reason):
        if status.get('overflow_dropped_packets',0):raise ValueError('CAPTURE_QUEUE_OVERFLOW_REQUIRES_CONDITION_REVIEW')
        if reason not in RETRY_CAPTURE:raise ValueError('CAPTURE_NOT_USABLE: '+reason)
        # Every retry preserves the declaration and exact hardware context.
        self.check(j)
        split=j['recording_split'];session=j['recording_session_id']
        if str(uuid.UUID(session))!=session:raise ValueError('CAPTURE_SESSION_ID_INVALID')
        source=self.captures/session
        names=('session.json','feature_contract.json','frames.jsonl','summary.json')
        if source.is_symlink() or any((source/n).is_symlink() or not (source/n).is_file() for n in names):
            raise ValueError('CAPTURE_RETRY_EVIDENCE_MISSING')
        if sum((source/n).stat().st_size for n in names)>128*1024*1024:
            raise ValueError('CAPTURE_RETRY_EVIDENCE_SIZE')
        meta=json.loads((source/'session.json').read_text(encoding='utf-8'))
        summary=json.loads((source/'summary.json').read_text(encoding='utf-8'))
        if summary.get('overflow_dropped_packets',0):raise ValueError('CAPTURE_QUEUE_OVERFLOW_REQUIRES_CONDITION_REVIEW')
        hashes=summary.get('files_sha256',{})
        if (set(hashes)!=set(names)-{'summary.json'} or any(sha(source/n)!=h for n,h in hashes.items()) or
                meta.get('session_id')!=session or summary.get('session_id')!=session or
                summary.get('state') not in ('ABORTED','DIAGNOSTIC_SAVED') or summary.get('state')!=status['state'] or
                summary.get('reason')!=status.get('reason') or
                (summary.get('state')=='ABORTED' and reason!=summary.get('reason')) or
                meta.get('boot_id')!=j['context']['collector_boot'] or
                meta.get('configuration_words')!=j['context']['input_contract']['configuration_words'] or
                meta.get('bitstream_sha256')!=j['context']['bitstream_sha256'] or
                meta.get('capture_mode')!='DIAGNOSTIC' or meta.get('label_declared')!='unlabelled' or meta.get('qualified') is not False):
            raise ValueError('CAPTURE_RETRY_PROVENANCE_CHANGED')
        if meta.get('window_policy')!=('INDEPENDENT_LABELED_NPU_WINDOWS' if j.get('kind')=='labeled_classifier' else 'INDEPENDENT_NORMAL_NPU_WINDOWS'):
            raise ValueError('CAPTURE_WINDOW_POLICY_CHANGED')
        # The aborting packet may never have entered frames.jsonl (for example
        # sequence gap + overcurrent in that same packet). Its immutable summary
        # evidence must pass before current recovery can authorize a new split.
        self._check_capture_terminal(j,summary)
        # A transient quality failure cannot conceal a boot/label/protection
        # change earlier in the abandoned capture, even if it later recovered.
        from .core import PL_BUILD
        with (source/'frames.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                if len(line)>65536:raise ValueError('CAPTURE_RETRY_ROW_SIZE')
                r=json.loads(line);h=r.get('header');st=r.get('status',{})
                if (r.get('schema')!='cabinet-capture-frame-v1' or r.get('source')!='REAL_FRM1_DECLARED' or
                        r.get('boot_id')!=j['context']['collector_boot'] or r.get('session_id')!=session or
                        type(h) is not list or len(h)!=32 or h[26]!=PL_BUILD or h[27] or h[15]&0x4000 or
                        h[16:19]!=j['context']['input_contract']['frame_identity'] or
                        self.protection(st)!=j['context']['capture_guard'] or
                        bool(st.get('test_mode'))!=j['context']['input_contract']['controller_diagnostic_mode']):
                    raise ValueError('CAPTURE_RETRY_CONTEXT_OR_PROTECTION_CHANGED')
                if j.get('kind')=='labeled_classifier':
                    from labeled_npu.core import _flags
                    _flags(st,j['label'])
                elif advisory_filtered_active(st)-{'CONFIG_UNQUALIFIED','STOP_UNCONFIRMED'} or st.get('latched'):
                    raise ValueError('HARDWARE_FAULT_ACTIVE')
        attempts=j.setdefault('capture_attempts',[])
        count=sum(a['split']==split for a in attempts)
        target=self.folder(j['id'])/'capture-attempts'/split/('%02d-'%(count+1)+session)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(str(source),str(target))
        attempts.append(dict(split=split,attempt=count+1,session_id=session,reason=reason,
            description=description(reason),evidence=str(target),files_sha256={n:sha(target/n) for n in names},
            retained_for_audit=True,used_for_training=False))
        j.update(progress_detail=('本段已重采两次仍未满足采集条件，请检查当前工况后重新学习'
            if count>=MAX_EXTRA_CAPTURE_ATTEMPTS else description(reason)),updated_at=self.clock())
        save(self.folder(j['id'])/'job.json',j)
        if count>=MAX_EXTRA_CAPTURE_ATTEMPTS:raise ValueError('CAPTURE_RETRY_LIMIT: '+reason)
        self.check(j)
        j.update(recording_session_id=None)
        save(self.folder(j['id'])/'job.json',j)
        return self._start_capture(j,split)

    def export_calibration_check(self, identity, worker):
        """Export only train/calibration, before a test capture can exist."""
        with self.lock():
            j=self.owned(identity,worker);self.check(j)
            if j.get('kind')=='labeled_classifier':raise ValueError('NORMAL_CALIBRATION_PRECHECK_ONLY')
            if set(j['sessions'])!={'train','calibration'} or j.get('recording_session_id') or j['state']!='CAPTURE_SAVED':
                raise ValueError('TRAIN_CALIBRATION_ONLY_PRECHECK_REQUIRED')
            session=j['sessions']['calibration']['status']['session_id']
            previous=j.get('calibration_precheck',{})
            if previous.get('calibration_session_id')==session:
                archive=self.folder(identity)/'prechecks'/str(previous['index'])/'captures.tar.gz'
                if sha(archive)!=previous['archive_sha256']:raise ValueError('CALIBRATION_EXPORT_CHANGED')
                return dict(path=str(archive),sha256=sha(archive),report_path=str(archive.parent/'report.json'))
            index=previous.get('index',0)+1
            folder=self.folder(identity)/'prechecks'/str(index);folder.mkdir(parents=True,exist_ok=False,mode=0o700)
            data=folder/'data';data.mkdir(mode=0o700)
            for split in ('train','calibration'):
                destination=data/'captures'/split;destination.parent.mkdir(exist_ok=True)
                shutil.copytree(str(self.folder(identity)/'captures'/split),str(destination))
            save(data/'sessions.json',j['sessions'])
            save(data/'learning.json',dict(schema='cabinet-one-click-normal-learning-v1',job_id=identity,
                healthy_confirmed=True,label_source=j['label_source'],context=j['context'],
                raw_capture_qualification_changed=False,auto_deploy=j.get('auto_deploy',True)))
            files={str(p.relative_to(data)):sha(p) for p in data.rglob('*') if p.is_file()}
            archive=folder/'captures.tar.gz'
            with tarfile.open(str(archive),'w:gz') as output:
                for name in ('captures','sessions.json','learning.json'):output.add(str(data/name),arcname=name)
            j['calibration_precheck']=dict(index=index,calibration_session_id=session,archive_sha256=sha(archive),
                source_sha256=files,decision=None)
            j.update(progress_detail='正在检查校验段输入覆盖，尚未采集独立测试段',updated_at=self.clock())
            save(self.folder(identity)/'job.json',j)
            return dict(path=str(archive),sha256=sha(archive),report_path=str(folder/'report.json'))

    def calibration_check_result(self, identity, worker, report_sha256):
        with self.lock():
            j=self.owned(identity,worker);self.check(j)
            precheck=j.get('calibration_precheck',{})
            if not precheck:raise ValueError('CALIBRATION_PRECHECK_NOT_EXPORTED')
            folder=self.folder(identity)/'prechecks'/str(precheck['index']);path=folder/'report.json'
            if path.is_symlink() or path.stat().st_size>65536 or sha(path)!=report_sha256:
                raise ValueError('CALIBRATION_PRECHECK_REPORT_PIN')
            if precheck.get('report_sha256'):
                if precheck['report_sha256']!=report_sha256:raise ValueError('CALIBRATION_PRECHECK_RETRY_PIN_CHANGED')
                if precheck.get('decision')=='REVIEW_CONDITION_REQUIRED':
                    raise ValueError('CALIBRATION_CONDITION_REVIEW_REQUIRED: '+str(precheck.get('reason_code')))
                if (precheck.get('decision_applied') or
                        (j['state']=='CAPTURING_CALIBRATION' and j.get('recording_session_id') and
                         j['recording_session_id']!=precheck['calibration_session_id'])):return j
                raise ValueError('CALIBRATION_PRECHECK_RETRY_INCOMPLETE_REVIEW')
            if set(j['sessions'])!={'train','calibration'} or j.get('recording_session_id'):
                raise ValueError('TEST_MUST_NOT_EXIST_BEFORE_CALIBRATION_CHECK')
            report=json.loads(path.read_text(encoding='utf-8'))
            if (report.get('schema')!='cabinet-normal-calibration-input-check-v1' or
                    report.get('policy',{}).get('schema')!='cabinet-normal-calibration-input-policy-v1' or
                    report.get('source_sha256')!=precheck['source_sha256'] or report.get('test_read') is not False or
                    report.get('model_scores_used') is not False):
                raise ValueError('CALIBRATION_PRECHECK_SOURCE_CHANGED')
            decision=report.get('status')
            if decision not in ('PASS_CALIBRATION_INPUT_QUALITY','RETRY_CALIBRATION_TRANSIENT','REVIEW_CONDITION_REQUIRED'):
                raise ValueError('CALIBRATION_PRECHECK_DECISION_INVALID')
            if report.get('input_contract')!=j['context']['input_contract']:
                raise ValueError('CALIBRATION_PRECHECK_CONTRACT_CHANGED')
            if decision=='RETRY_CALIBRATION_TRANSIENT' and report.get('reason_code')!='CALIBRATION_TRANSIENT_INPUT_COVERAGE':
                raise ValueError('CALIBRATION_RETRY_REASON_NOT_PREDECLARED')
            precheck.update(decision=decision,report_sha256=report_sha256,reason_code=report.get('reason_code'))
            save(self.folder(identity)/'job.json',j)
            if decision=='PASS_CALIBRATION_INPUT_QUALITY':
                precheck['decision_applied']=True
                j.update(progress_detail='校验段输入覆盖检查通过，开始采集固定独立测试段')
                save(self.folder(identity)/'job.json',j);return j
            if decision=='REVIEW_CONDITION_REQUIRED':
                raise ValueError('CALIBRATION_CONDITION_REVIEW_REQUIRED: '+str(report.get('reason_code')))
            # This decision is made before test capture and without model scores.
            # Keep the complete rejected calibration and report, sharing the same
            # two-extra-attempt budget as transport/quality retries.
            old=self.folder(identity)/'captures'/'calibration'
            session=j['sessions']['calibration']['status']['session_id']
            status=json.loads((old/'summary.json').read_text(encoding='utf-8'))
            old.rename(folder/'rejected-calibration')
            j['sessions'].pop('calibration')
            j.update(recording_session_id=session,recording_split='calibration')
            save(self.folder(identity)/'sessions.json',j['sessions']);save(self.folder(identity)/'job.json',j)
            result=self._retry_capture(j,status,'CALIBRATION_TRANSIENT_INPUT_COVERAGE')
            result['calibration_precheck']['decision_applied']=True
            save(self.folder(identity)/'job.json',result);return result

    def capture_poll(self, identity, worker):
        with self.lock():
            j = self.owned(identity,worker); self.check(j)
            if j['state']=='CAPTURE_SAVED' and not j.get('recording_session_id'):return j
            s = rpc(self.socket, {'operation':'status'})['status']
            if s['session_id'] != j.get('recording_session_id'): raise ValueError('RECORDER_OWNERSHIP_CHANGED')
            j.update(capture_status={k:s[k] for k in ('frames','elapsed_s','duration_s','state','gaps','missing_frames')}, updated_at=self.clock())
            before = sum(seconds for name,seconds in SPLITS if name in j['sessions'])
            j['progress_percent'] = min(60, int((before+s['elapsed_s'])/sum(v for n,v in SPLITS)*60))
            if s['state'] != 'RECORDING':
                if s['state']!='DIAGNOSTIC_SAVED':return self._retry_capture(j,s,s['reason'])
                if s['durable_frames'] < 600:return self._retry_capture(j,s,'INSUFFICIENT_COMPLETE_WINDOWS')
                if s.get('window_policy')!='INDEPENDENT_NORMAL_NPU_WINDOWS' or s['missing_frames']/max(1,s['frames']+s['missing_frames'])>.02:
                    if s.get('window_policy')!='INDEPENDENT_NORMAL_NPU_WINDOWS':raise ValueError('CAPTURE_WINDOW_POLICY_CHANGED')
                    return self._retry_capture(j,s,'INDEPENDENT_WINDOW_LOSS_BUDGET')
                source,meta,summary = verified_session(self.captures,s['session_id'])
                if meta['boot_id'] != j['context']['collector_boot']: raise ValueError('CAPTURE_BOOT_CHANGED')
                folder = self.folder(identity); target = folder/'captures'/j['recording_split']; target.parent.mkdir(exist_ok=True)
                shutil.copytree(str(source),str(target))
                j['sessions'][j['recording_split']] = dict(ok=True,status=s)
                j.update(recording_session_id=None,state='CAPTURE_SAVED',progress_detail='本段采集完成，正在继续学习')
                save(folder/'sessions.json',j['sessions'])
            save(self.folder(identity)/'job.json',j); return j

    def export(self, identity, worker):
        j = self.owned(identity,worker); self.check(j)
        if set(j['sessions']) != set(n for n,s in SPLITS): raise ValueError('THREE_REAL_SESSIONS_REQUIRED')
        folder = self.folder(identity)
        dest = folder/'captures.tar.gz'
        if j.get('export_sha256') and dest.is_file() and sha(dest)==j['export_sha256']:
            return dict(path=str(dest),sha256=sha(dest))
        save(folder/'learning.json',dict(schema='cabinet-one-click-normal-learning-v1',job_id=identity,
            healthy_confirmed=True, label_source=j['label_source'], context=j['context'],
            raw_capture_qualification_changed=False, auto_deploy=j.get('auto_deploy',True)))
        with tarfile.open(str(dest)+'.next','w:gz') as output:
            for name in ('captures','sessions.json','learning.json'): output.add(str(folder/name),arcname=name)
        os.replace(str(dest)+'.next',str(dest))
        self.update(identity,worker,state='TRAINING',progress_percent=65,export_sha256=sha(dest))
        return dict(path=str(dest),sha256=sha(dest))
