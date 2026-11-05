"""Bounded, read-only FRM1 session archive; never grants training or control authority."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import stat
import struct
import threading
import time
import uuid

from .protocol import FEATURES, FrameGate, elapsed32
from hmi_daily.cabinet.learning_rpc import LearningRPC


LABELS = ('unlabelled', 'normal', 'imbalance', 'stall', 'clog', 'overheat')
FEATURE_ID = 0x2026f400
BUILD_ID = 0x202610f4
CAPTURE_BUILD_IDS = (BUILD_ID, 0x202610f5, 0x202610f6, 0x202610f7)
EDGES = [1, 13, 39, 65, 103, 154, 205, 257, 513]
COEFFICIENT_SHA = 'ce82c6cf263aeaac69fd78fd68831f20b10d58269e8e02a0d22ba9e7814bf1bc'


def digest(file):
    result = hashlib.sha256()
    with Path(file).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def text(value, name, limit=80):
    if type(value) is not str or not 1 <= len(value) <= limit or any(ord(char) < 32 for char in value):
        raise ValueError('INVALID_' + name.upper())
    return value


def atomic_json(file, value):
    temporary = file.with_name(file.name + '.new')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temporary), str(file))


def frame_words(frame):
    return list(struct.unpack('<39I', struct.pack('<39f', *frame.values)))


def terminal_observation(packet):
    """Retain an observed abort trigger even when it cannot enter frames.jsonl."""
    if type(packet) is not dict:return None
    frame=packet.get('frame');status=copy.deepcopy(packet.get('status'))
    test=bool(packet.get('test') or (frame is not None and frame.test))
    return dict(schema='cabinet-capture-terminal-observation-v1',
        source='SYNTHETIC_FIXTURE' if test else 'REAL_COLLECTOR_DECLARED',test=test,
        sequence=packet.get('sequence'),boot=packet.get('boot'),link=packet.get('link'),
        received_monotonic=packet.get('received_at'),now_ms=packet.get('now_ms'),
        configuration_words=copy.deepcopy(packet.get('configuration_words')),
        status=status,raw_status_words=copy.deepcopy(status.get('raw_words') if type(status) is dict else None),
        frame_header=list(frame.header) if frame is not None else None)


class CaptureRecorder:
    def __init__(self, config, directory, socket_path, contract, capacity=256):
        self.config = config
        self.directory = Path(directory)
        self.socket_path = Path(socket_path)
        self.contract = copy.deepcopy(contract)
        if type(self.contract.get('pl_build_id')) is not int or self.contract['pl_build_id'] not in CAPTURE_BUILD_IDS:
            raise ValueError('EXPLICIT_REVIEWED_PL_BUILD_REQUIRED')
        self.queue = queue.Queue(maxsize=capacity)
        self.stopping = threading.Event()
        self.overflow = threading.Event()
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.thread = self.rpc = self.owner = None
        self.error = None
        self.latest = None
        self.latest_frame = None
        self.overflow_observation = None
        self.last_sequence = None
        self.stream = self.session_dir = self.session = None
        self.gate = None
        self.started_at = self.flushed_at = self.checked_disk_at = None
        self.frame_bytes = 0
        self.last_frame_id = None
        self.requests = {}
        self.state = dict(schema='cabinet-capture-status-v1', state='IDLE', reason='NO_SESSION',
                          session_id=None, frames=0, accepted=0, rejected=0, durable_frames=0,
                          gaps=0, elapsed_s=0, duration_s=0, file=None, label='unlabelled',
                          capture_mode=None, window_policy='CONTIGUOUS', missing_frames=0,overflow_dropped_packets=0,
                          ready=False, ready_reason='NO_FRAME', boot=None,
                          qualified=False, label_reviewed=False, training_ready=False)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def start(self):
        if self.thread is not None:
            raise RuntimeError('CAPTURE_ALREADY_STARTED')
        self.thread = threading.Thread(target=self.run, name='cabinet-capture', daemon=True)
        self.thread.start()
        if not self.ready.wait(3) or self.error:
            raise RuntimeError('CAPTURE_START_FAILED: ' + str(self.error))

    def submit(self, packet):
        try:
            self.queue.put_nowait(copy.deepcopy(packet))
        except queue.Full:
            # Queue loss can conceal a protection transition. Retain the first
            # known dropped packet for audit; a count is explicit when more
            # packets were lost. This condition is never automatically retried.
            with self.lock:
                if self.overflow_observation is None:self.overflow_observation=terminal_observation(packet)
                self.state['overflow_dropped_packets']+=1
                self.overflow.set()

    def reasons(self, packet, gate=None):
        if not packet or packet.get('link') != 'ONLINE':
            return ['COLLECTOR_OFFLINE']
        frame = packet.get('frame')
        if frame is None:
            return ['NO_FRAME']
        result = (gate or FrameGate(self.config['contract'])).check(frame, packet['now_ms'])
        result.extend(packet.get('rejected', []))
        header = frame.header
        if packet.get('test') or frame.test:
            result.append('TEST_SOURCE')
        if header[16] != FEATURE_ID or header[26] not in CAPTURE_BUILD_IDS:
            result.append('V4_IDENTITY')
        if header[26] != self.contract['pl_build_id']:
            result.append('PL_BUILD_IDENTITY')
        if header[20] != 4000 or header[22] != 50000:
            result.append('SAMPLE_CONTRACT')
        if header[17] == 0 or header[17] != self.contract.get('calibration_id'):
            result.append('CALIBRATION')
        if (self.contract.get('feature_config_id'), self.contract.get('sample_mode_id'),
            self.contract.get('profile'), self.contract.get('coefficient_sha256'),
            self.contract.get('fs'), self.contract.get('adc_fs'), self.contract.get('fft_size'),
            self.contract.get('hop'), self.contract.get('edges'), self.contract.get('feature_names'),
            self.contract.get('qualified')) != (FEATURE_ID, 2, 'V4-P800-Q17', COEFFICIENT_SHA,
                4000, 50000, 1024, 512, EDGES, list(FEATURES), False):
            result.append('CONTRACT_NOT_REVIEWED')
        words = packet.get('configuration_words', [])
        if len(words) != 17 or words[:3] != [header[16], header[17], 1] or words[8:] != EDGES:
            result.append('CONFIG_READBACK')
        return sorted(set(result))

    def command(self, request, now):
        if type(request) is not dict:
            raise ValueError('INVALID_REQUEST')
        operation = request.get('operation')
        if operation == 'status' and set(request) == {'operation'}:
            return dict(ok=True, status=self.snapshot())
        if operation not in ('start', 'stop') or set(request) != {'operation', 'request_id', 'payload'}:
            raise ValueError('INVALID_OPERATION')
        request_id = request['request_id']
        if type(request_id) is not str or str(uuid.UUID(request_id)) != request_id:
            raise ValueError('INVALID_REQUEST_ID')
        encoded = json.dumps(request, sort_keys=True, allow_nan=False)
        if request_id in self.requests:
            previous, result = self.requests[request_id]
            if previous != encoded:
                raise ValueError('REQUEST_ID_REUSED')
            return copy.deepcopy(result)
        if len(self.requests) >= 256:
            raise ValueError('REQUEST_HISTORY_FULL_RESTART_ONLY_WHEN_IDLE')
        payload = request['payload']
        if type(payload) is not dict:
            raise ValueError('INVALID_PAYLOAD')
        if operation == 'start':
            result = self.begin(payload, now)
        else:
            if set(payload) != {'session_id'} or payload['session_id'] != self.state['session_id']:
                raise ValueError('SESSION_MISMATCH')
            if self.stream is None:
                raise ValueError('NO_ACTIVE_SESSION')
            self.finish('COMPLETED', 'OPERATOR_STOP', now)
            result = dict(ok=True, status=self.snapshot())
        self.requests[request_id] = encoded, copy.deepcopy(result)
        return result

    def begin(self, payload, now):
        allowed = {'expected_boot', 'installation_id', 'operator', 'label', 'duration_s',
                   'capture_mode', 'bitstream_sha256', 'calibration_evidence_sha256', 'note'}
        if set(payload)-{'window_policy'} != allowed or self.stream is not None:
            raise ValueError('INVALID_START_OR_BUSY')
        policy=payload.get('window_policy','CONTIGUOUS')
        if policy not in ('CONTIGUOUS','INDEPENDENT_NORMAL_NPU_WINDOWS','INDEPENDENT_LABELED_NPU_WINDOWS'):
            raise ValueError('INVALID_WINDOW_POLICY')
        if policy!='CONTIGUOUS' and (payload['capture_mode']!='DIAGNOSTIC' or payload['label']!='unlabelled'):
            raise ValueError('INDEPENDENT_WINDOWS_ARE_DIAGNOSTIC_UNLABELLED_ONLY')
        installation = text(payload['installation_id'], 'installation_id')
        operator = text(payload['operator'], 'operator')
        text(payload['note'], 'note', 240)
        duration = payload['duration_s']
        if type(duration) is not int or not 1 <= duration <= 3600 or payload['label'] not in LABELS:
            raise ValueError('INVALID_DURATION_OR_LABEL')
        if payload['capture_mode'] not in ('REAL', 'DIAGNOSTIC'):
            raise ValueError('INVALID_CAPTURE_MODE')
        packet = self.latest_frame
        if (not packet or packet.get('link') != 'ONLINE' or packet.get('frame') is None or
                not 0 <= now - packet['received_at'] <= 1 or payload['expected_boot'] != packet['boot'] or
                not self.queue.empty() or self.overflow.is_set()):
            raise ValueError('FRESH_COLLECTOR_REQUIRED')
        reasons = self.reasons(packet)
        status = packet.get('status', {})
        if payload['label'] == 'normal' and (packet['frame'].quality or packet['frame'].header[19]!=3 or status.get('active') or status.get('latched') or status.get('hard_inhibit')):
            reasons.append('FAULT_NOT_NORMAL')
        if payload['capture_mode'] == 'REAL':
            if reasons:
                raise ValueError('REAL_CAPTURE_BLOCKED:' + ','.join(reasons))
            for name in ('bitstream_sha256', 'calibration_evidence_sha256'):
                if type(payload[name]) is not str or not re.fullmatch('[0-9a-f]{64}', payload[name]):
                    raise ValueError('PROVENANCE_REQUIRED:' + name)
        if shutil.disk_usage(str(self.directory)).free < 64 * 1024 * 1024:
            raise ValueError('DISK_RESERVE')
        identity = str(uuid.uuid4())
        directory = self.directory / identity
        directory.mkdir(mode=0o700)
        session = dict(schema='cabinet-capture-session-v1', session_id=identity,
                       device_id=self.config['device_id'], installation_id=installation, operator=operator,
                       label_declared=payload['label'], label_reviewed=False, qualified=False,
                       pl_build_id=self.contract['pl_build_id'],
                       capture_mode=payload['capture_mode'], duration_s=duration,window_policy=policy,
                       preceding_frame_id=packet['frame'].id,
                       bitstream_sha256=payload['bitstream_sha256'],
                       calibration_evidence_sha256=payload['calibration_evidence_sha256'],
                       note=payload['note'], boot_id=packet['boot'],
                       configuration_words=packet.get('configuration_words', []),
                       started_monotonic=now, wall_time_untrusted=time.time(),
                       automatic_learning_changed=False, model_changed=False, controls_changed=False)
        atomic_json(directory / 'session.json', session)
        atomic_json(directory / 'feature_contract.json', self.contract)
        stream = (directory / 'frames.jsonl').open('x', encoding='utf-8')
        self.session_dir, self.session, self.stream = directory, session, stream
        self.gate = FrameGate(self.config['contract'])
        self.started_at = self.flushed_at = self.checked_disk_at = now
        self.frame_bytes = 0
        self.last_frame_id = packet['frame'].id
        with self.lock:self.overflow_observation=None
        self.update(state='RECORDING', reason='WRITING_NOT_YET_REVIEWED', session_id=identity,
                    frames=0, accepted=0, rejected=0, durable_frames=0, gaps=0, missing_frames=0,overflow_dropped_packets=0,
                    window_policy=policy,elapsed_s=0,
                    duration_s=duration, file=str(directory / 'frames.jsonl'), label=payload['label'],
                    capture_mode=payload['capture_mode'], installation_id=installation, operator=operator)
        return dict(ok=True, status=self.snapshot())

    def observe(self, packet, now):
        sequence = packet['sequence']
        gap = self.last_sequence is not None and sequence != self.last_sequence + 1
        self.last_sequence = sequence
        self.latest = packet
        if packet.get('frame') is not None:
            self.latest_frame = packet
        elif packet.get('link') != 'ONLINE':
            self.latest_frame = None
        reference = self.latest_frame
        reasons = self.reasons(reference)
        frame_fresh = reference is not None and 0 <= now - reference['received_at'] <= 1
        self.update(ready=not reasons and frame_fresh,
                    ready_reason=','.join(reasons) or 'FRAME_CONTRACT_OK_NOT_HEALTH_PROOF',
                    boot=packet.get('boot'), last_frame_id=packet['frame'].id if packet.get('frame') else None,
                    last_received_at=packet['received_at'], last_quality=packet['frame'].quality if packet.get('frame') else None)
        if self.stream is None:
            return
        if not self.latest_frame or not 0 <= now - self.latest_frame['received_at'] <= 1:
            self.finish('ABORTED', 'NO_FRESH_FRAMES', now)
            return
        if self.overflow.is_set():
            self.update(gaps=self.state['gaps'] + 1)
            self.finish('ABORTED', 'CAPTURE_QUEUE_OVERFLOW', now)
            return
        if gap:
            self.update(gaps=self.state['gaps'] + 1)
            self.finish('ABORTED', 'COLLECTOR_GAP', now)
            return
        if packet.get('boot') != self.session['boot_id'] or packet.get('link') != 'ONLINE':
            self.finish('ABORTED', 'COLLECTOR_RESTART_OR_OFFLINE', now)
            return
        if packet.get('configuration_words') != self.session['configuration_words']:
            self.finish('ABORTED', 'CONFIGURATION_CHANGED', now)
            return
        frame = packet.get('frame')
        if frame is None:
            return
        distance=elapsed32(frame.id,self.last_frame_id) if self.last_frame_id is not None else 1
        gap_before=0
        if distance != 1:
            self.update(gaps=self.state['gaps'] + 1)
            if self.session.get('window_policy') not in ('INDEPENDENT_NORMAL_NPU_WINDOWS','INDEPENDENT_LABELED_NPU_WINDOWS') or not 2<=distance<=8:
                self.finish('ABORTED', 'FRAME_ID_GAP_OR_DUPLICATE', now)
                return
            gap_before=distance-1
            self.update(missing_frames=self.state['missing_frames']+gap_before)
            # A short early burst must not fail solely because the denominator
            # is still tiny. Reserve only the loss that the fixed-duration
            # session could ultimately afford; finish() enforces the actual 2%.
            # Use the accepted 4120 Hz upper sampling bound and two boundary
            # windows, not nominal 4 kHz, to avoid rejecting a recoverable tail.
            expected_windows=int(self.state['duration_s']*4120/512)+2
            if self.state['missing_frames']>max(4,.02*expected_windows):
                self.finish('ABORTED','INDEPENDENT_WINDOW_LOSS_BUDGET',now)
                return
        self.last_frame_id = frame.id
        reasons = self.reasons(packet, self.gate)
        if 'PL_BUILD_IDENTITY' in reasons:
            self.finish('ABORTED', 'PL_BUILD_IDENTITY_CHANGED', now)
            return
        status = packet['status']
        if self.session['label_declared'] == 'normal' and (frame.quality or frame.header[19]!=3 or status.get('active') or status.get('latched') or status.get('hard_inhibit')):
            reasons = sorted(set(reasons + ['FAULT_NOT_NORMAL']))
        if self.session['capture_mode'] == 'DIAGNOSTIC':
            reasons = sorted(set(reasons + ['DIAGNOSTIC_NOT_TRAINING']))
        record = dict(schema='cabinet-capture-frame-v1',
                      source='SYNTHETIC_FIXTURE' if packet.get('test') or frame.test else 'REAL_FRM1_DECLARED',
                      session_id=self.session['session_id'], boot_id=packet['boot'], sequence=sequence,
                      gap_before=gap_before,
                      now_ms=packet['now_ms'], received_monotonic=packet['received_at'],
                      header=list(frame.header), feature_words=frame_words(frame),
                      accepted=not reasons, rejected_reasons=reasons, status=packet['status'],
                      mailbox=packet.get('mailbox', {}), environment=packet.get('environment'))
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n'
        self.frame_bytes += len(line.encode('utf-8'))
        if self.frame_bytes > 64 * 1024 * 1024:
            self.finish('ABORTED', 'SESSION_SIZE_LIMIT', now)
            return
        self.stream.write(line)
        self.update(frames=self.state['frames'] + 1,
                    accepted=self.state['accepted'] + int(not reasons),
                    rejected=self.state['rejected'] + int(bool(reasons)))

    def tick(self, now):
        if self.overflow.is_set():
            if self.stream is not None:
                self.update(gaps=self.state['gaps'] + 1)
                self.finish('ABORTED', 'CAPTURE_QUEUE_OVERFLOW', now)
            self.overflow.clear()
        if self.latest and not 0 <= now - self.latest['received_at'] <= 1:
            self.update(ready=False, ready_reason='COLLECTOR_STALE')
            if self.stream is not None:
                self.finish('ABORTED', 'COLLECTOR_STALE', now)
        if self.stream is None:
            return
        self.update(elapsed_s=round(max(0, now - self.started_at), 1))
        if now - self.checked_disk_at >= 1:
            self.checked_disk_at = now
            if shutil.disk_usage(str(self.directory)).free < 32 * 1024 * 1024:
                self.finish('ABORTED', 'DISK_RESERVE', now)
                return
        if now - self.flushed_at >= 1:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.flushed_at = now
            self.update(durable_frames=self.state['frames'])
        if now - self.started_at >= self.state['duration_s']:
            self.finish('COMPLETED', 'DURATION_REACHED', now)

    def finish(self, state, reason, now):
        if self.stream is None:
            return
        stream, self.stream = self.stream, None
        try:
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            stream.close()
        if state == 'COMPLETED' and self.state['frames'] == 0:
            state, reason = 'ABORTED', 'NO_FRAMES'
        if (state=='COMPLETED' and self.session.get('window_policy') in ('INDEPENDENT_NORMAL_NPU_WINDOWS','INDEPENDENT_LABELED_NPU_WINDOWS') and
                self.state['missing_frames']/max(1,self.state['frames']+self.state['missing_frames'])>.02):
            state,reason='ABORTED','INDEPENDENT_WINDOW_LOSS_BUDGET'
        if state == 'COMPLETED' and self.session['capture_mode'] == 'DIAGNOSTIC':
            state, reason = 'DIAGNOSTIC_SAVED', 'NOT_TRAINING_DATA'
        summary = self.snapshot()
        summary.update(state=state, reason=reason, elapsed_s=round(max(0, now - self.started_at), 1),
                       durable_frames=self.state['frames'])
        # observe() stores latest before any gap/overflow/identity early return.
        # This includes the triggering status/header; the whole summary is later
        # hash-bound by the immutable failed-attempt archive.
        summary['terminal_observation']=terminal_observation(self.latest)
        with self.lock:summary['overflow_observation']=copy.deepcopy(self.overflow_observation)
        summary['files_sha256'] = {name: digest(self.session_dir / name)
                                   for name in ('frames.jsonl', 'session.json', 'feature_contract.json')}
        atomic_json(self.session_dir / 'summary.json', summary)
        for directory in (self.session_dir, self.directory):
            descriptor = os.open(str(directory), os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        self.update(state=state, reason=reason, elapsed_s=summary['elapsed_s'], durable_frames=summary['durable_frames'])

    def run(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            info = self.directory.lstat()
            if self.directory.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError('PRIVATE_CAPTURE_DIRECTORY_REQUIRED')
            descriptor = os.open(str(self.directory / '.capture.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            self.owner = os.fdopen(descriptor, 'r+')
            owner_info = os.fstat(descriptor)
            if (not stat.S_ISREG(owner_info.st_mode) or owner_info.st_uid != os.geteuid() or
                    owner_info.st_nlink != 1 or owner_info.st_mode & 0o077):
                raise ValueError('UNSAFE_CAPTURE_LOCK')
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.rpc = LearningRPC(self.socket_path)
            self.ready.set()
            while not self.stopping.is_set():
                try:
                    packet = self.queue.get(timeout=0.02)
                except queue.Empty:
                    packet = None
                now = time.monotonic()
                if packet is not None:
                    self.observe(packet, now)
                self.tick(now)
                if self.queue.empty():
                    self.rpc.poll(self, time.monotonic())
            self.finish('ABORTED', 'SERVICE_STOPPED', time.monotonic())
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, struct.error) as error:
            self.error = type(error).__name__ + ': ' + str(error)
            if self.stream is not None:
                try:
                    self.finish('ABORTED', 'ARCHIVE_IO_OR_SCHEMA_ERROR', time.monotonic())
                except (OSError, ValueError):
                    pass
            self.update(state='ERROR', reason=self.error, ready=False)
        finally:
            self.ready.set()
            if self.rpc is not None:
                self.rpc.close()
            if self.owner is not None:
                self.owner.close()

    def close(self):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('CAPTURE_WRITER_BUSY_KEEP_PROCESS_FOR_INSPECTION')


def display_fields(snapshot, now):
    last = snapshot.get('last_received_at')
    fresh = last is not None and 0 <= now - last <= 1
    fields = {'capture_schema': 'capture-v1', 'capture_state': snapshot.get('state', 'UNAVAILABLE'),
              'capture_reason': snapshot.get('reason', 'SERVICE_UNAVAILABLE'),
              'capture_ready': '1' if fresh and snapshot.get('ready') else '0',
              'capture_ready_reason': snapshot.get('ready_reason', 'NO_FRAME') if fresh else 'COLLECTOR_STALE',
              'capture_label_reviewed': '0', 'capture_training_ready': '0'}
    for key in ('session_id', 'capture_mode', 'label', 'installation_id', 'operator', 'file', 'frames',
                'accepted', 'rejected', 'durable_frames', 'gaps', 'elapsed_s', 'duration_s', 'last_frame_id', 'last_quality'):
        fields['capture_' + key] = str(snapshot.get(key) if snapshot.get(key) is not None else '--')
    return fields
