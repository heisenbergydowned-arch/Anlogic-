"""Validated web commands, executed only on the collector's serial queue."""
import calendar
import datetime
import json
import re
import subprocess
import threading
import time
import uuid

from .baseline import BUSY, canonical, digest
from .protocol import elapsed32


COMMAND_SCHEMA = 'cabinet-learning-command-v1'
PERMISSIONS = {'learning.' + name for name in ('start', 'cancel', 'commit', 'rollback', 'takeover')}
PAYLOADS = {'start': {'healthy_confirmed', 'expected_baseline_id'},
            'cancel': {'job_id'},
            'commit': {'job_id', 'candidate_hash', 'expected_baseline_id'},
            'rollback': {'baseline_id', 'expected_baseline_id'}}


def strict_json(payload, limit=4096):
    if isinstance(payload, bytes):
        payload = payload.decode('utf-8')
    if len(payload.encode('utf-8')) > limit:
        raise ValueError('INVALID_REQUEST_SIZE')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('DUPLICATE_FIELD')
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError('NONFINITE_NUMBER')

    result = json.loads(payload, object_pairs_hook=unique, parse_constant=nonfinite)
    canonical(result)
    return result


def utc_text(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def utc_seconds(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value):
        raise ValueError('INVALID_TIME')
    return calendar.timegm(datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').timetuple())


def is_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def is_hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


class ClockTrust:
    def __init__(self):
        self.checked = None
        self.synchronized = False
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.probe, daemon=True)
        self.thread.start()

    def probe(self):
        while not self.stopping.is_set():
            trusted = False
            try:
                result = subprocess.run(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        universal_newlines=True, timeout=1)
                trusted = result.returncode == 0 and result.stdout.strip() == 'yes'
            except (OSError, subprocess.TimeoutExpired):
                pass
            self.synchronized = trusted
            self.checked = time.monotonic()
            self.stopping.wait(5)

    def trusted(self):
        return self.synchronized and self.checked is not None and time.monotonic() - self.checked <= 15

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=1.5)


class WebLearningControl:
    def __init__(self, learner, clock, wall_time=time.time, context_guard=None):
        self.learner = learner
        self.connection = learner.store.connection
        self.clock = clock
        self.wall_time = wall_time
        self.context_guard = context_guard
        self.session_id = str(uuid.uuid4())
        self.pl_session = None
        self.sequence = 0
        self.observed_at = self.reported_at = None
        self.block_clock_until = 0
        self.status = {}
        self.model_available = False
        self.linked = True
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS web_requests (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, envelope TEXT NOT NULL, response TEXT);
            CREATE TABLE IF NOT EXISTS web_jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL);
        ''')

    def update(self, status, pl_session, now, reported_at=None):
        wall = self.wall_time() if reported_at is None else reported_at
        if self.observed_at is not None and abs((wall - self.reported_at) - (now - self.observed_at)) > 2:
            self.block_clock_until = now + 30
        if self.pl_session is not None and pl_session != self.pl_session:
            self.session_id = str(uuid.uuid4())
            self.sequence = 0
        self.pl_session = pl_session
        self.sequence += 1
        self.status = dict(status)
        self.linked = True
        self.observed_at, self.reported_at = now, wall

    def contract(self):
        frame = self.learner.last_frame
        contract = self.learner.config['contract']
        return {'feature_config_id': frame.header[16] if frame else contract['feature_config_id'],
                'calibration_id': frame.header[17] if frame else contract['calibration_id'],
                'sample_mode_id': frame.header[18] if frame else contract['sample_mode_id'],
                'signature': self.learner.last_signature}

    def fresh(self, now):
        learner = self.learner
        age = self.frame_age_ms(now)
        return (self.linked and self.observed_at is not None and 0 <= now - self.observed_at <= 1 and
                learner.qualified_at is not None and
                0 <= now - learner.qualified_at <= learner.config['max_gap_seconds'] and learner.last_valid and
                age is not None and age <= learner.config['contract']['max_frame_age_ms'])

    def frame_age_ms(self, now):
        frame = self.learner.last_frame
        uptime = self.status.get('uptime_ms')
        if frame is None or type(uptime) is not int or self.observed_at is None:
            return None
        return elapsed32(uptime, frame.header[4]) + int(max(0, now - self.observed_at) * 1000)

    def clock_trusted(self, now):
        return (self.clock.trusted() and self.reported_at is not None and
                self.wall_time() >= 1735689600 and now >= self.block_clock_until and
                abs((self.wall_time() - self.reported_at) - (now - self.observed_at)) <= 2)

    def active_id(self):
        return self.learner.profiles[0]['id'] if self.learner.profiles else None

    def history(self):
        profiles = []
        for state in ('ACTIVE', 'ARCHIVED'):
            for profile in self.learner.store.profiles(state):
                profiles.append({key: profile[key] for key in
                                 ('id', 'signature', 'device_id', 'installation_id', 'created_at',
                                  'samples', 'rpm_min', 'rpm_max', 'advisory_qualified')})
                profiles[-1].update(state=state, compatible=profile['signature'] == self.learner.last_signature)
        return {'ok': True, 'device_id': self.learner.config['device_id'],
                'session_id': self.session_id, 'baselines': profiles}

    def snapshot(self, now):
        learner = self.learner
        fresh = self.fresh(now)
        clock = self.clock_trusted(now)
        context_ready = self.context_guard is None or self.context_guard() is None
        healthy = fresh and context_ready and learner.guard(self.status) is None
        available = self.linked and self.observed_at is not None and 0 <= now - self.observed_at <= 1
        pending = learner.state == 'PENDING_CONFIRM' and learner.candidate is not None
        remaining = max(0, learner.config['confirm_seconds'] - (now - learner.pending_since)) if pending else 0
        phase = (learner.pending_since if pending else learner.capture_since if learner.state == 'CAPTURING'
                 else learner.stable_since or learner.started if learner.state == 'WAIT_STABLE' else None)
        active = learner.profiles[0] if learner.profiles else None
        samples = active['samples'] if learner.state == 'COMMITTED' and active and active['job_id'] == learner.job_id else len(learner.rows)
        evidence = learner.evidence
        age = self.frame_age_ms(now)
        if not available or (age is not None and age > learner.config['contract']['max_frame_age_ms']):
            evidence = {'state': 'STALE', 'score': None, 'level': 0}
        return {'ok': True, 'schema': 'cabinet-learning-status-v1',
                'device_id': learner.config['device_id'], 'installation_id': learner.config['installation_id'],
                'session_id': self.session_id, 'reported_at': utc_text(self.reported_at) if self.reported_at else None,
                'status_sequence': self.sequence, 'available': available, 'online': available,
                'status_age_ms': int(max(0, now - self.observed_at) * 1000) if self.observed_at is not None else None,
                'clock_trusted': clock, 'contract': self.contract(),
                'operating_point': {'measured_rpm': self.status.get('measured_rpm'),
                                    'target_rpm': self.status.get('ramped_rpm'), 'mode': self.status.get('mode')},
                'qualification': {'source': 'REAL' if fresh else 'UNQUALIFIED',
                                  'frame_age_ms': self.frame_age_ms(now),
                                  'calibrated': bool(self.contract()['calibration_id']),
                                  'protection_configured': bool(self.status.get('configured') and self.status.get('configuration_id')),
                                  'physical_fault': bool(self.status.get('active') or self.status.get('latched') or self.status.get('alarm_level') or self.status.get('hard_inhibit')),
                                  'model_conflict': learner.reason == 'MODEL_CONFLICT', 'model_available': self.model_available},
                'job': {'state': learner.state, 'reason': learner.snapshot()['reason'], 'job_reason': learner.job_reason,
                        'job_id': learner.job_id, 'candidate_hash': digest(learner.candidate) if pending else None,
                        'candidate_expires_at': utc_text(self.wall_time() + remaining) if pending and clock else None,
                        'samples': samples, 'required': learner.config['min_samples'],
                        'accepted': learner.accepted, 'rejected': learner.rejected,
                        'phase_elapsed_seconds': max(0, now - phase) if phase is not None else 0},
                'can_start': clock and healthy and learner.allowed and not learner.store.history_full() and learner.state not in BUSY,
                'can_cancel': clock and available and context_ready and learner.state in BUSY,
                'can_commit': clock and healthy and pending and remaining > 0,
                'can_rollback': clock and healthy and learner.state not in BUSY and
                                any(profile['signature'] == learner.last_signature for profile in learner.store.profiles('ARCHIVED')),
                'baseline': {'active_id': self.active_id(), 'samples': active['samples'] if active else 0,
                             'compatible': bool(active and active['signature'] == learner.last_signature),
                             'observation_only': not learner.config['advisory_qualified']},
                'evidence': evidence,
                'effective_parameters': {key: learner.config[key] for key in
                                         ('stable_seconds', 'capture_seconds', 'timeout_seconds', 'confirm_seconds',
                                          'sample_interval_ms', 'min_samples', 'rpm_relative', 'rpm_absolute',
                                          'max_temp_span', 'max_gap_seconds', 'advisory_qualified')}}

    def result(self, identity):
        if not is_uuid(identity):
            return {'ok': False, 'reason': 'INVALID_REQUEST_ID'}
        row = self.connection.execute('SELECT envelope,response FROM web_requests WHERE id=?', (identity,)).fetchone()
        if not row:
            return {'ok': False, 'request_id': identity, 'reason': 'NOT_FOUND'}
        envelope = json.loads(row[0])
        return json.loads(row[1]) if row[1] else self.receipt(envelope, False, 'RESULT_UNKNOWN', 'UNKNOWN')

    def receipt(self, envelope, ok, reason, state=None, **extra):
        result = {'schema': 'cabinet-learning-result-v1', 'device_id': self.learner.config['device_id'],
                  'request_id': envelope.get('request_id'), 'operation': envelope.get('operation'),
                  'session_id': envelope.get('session_id'), 'ok': ok, 'reason': reason,
                  'command_state': state or ('SUCCEEDED' if ok else 'REJECTED')}
        result.update(extra)
        return result

    def validate(self, envelope):
        fields = {'schema', 'device_id', 'request_id', 'operation', 'session_id', 'issued_at', 'expires_at',
                  'actor', 'expected_contract', 'payload'}
        if not isinstance(envelope, dict) or set(envelope) != fields or envelope['schema'] != COMMAND_SCHEMA:
            raise ValueError('INVALID_ENVELOPE')
        if len(canonical(envelope).encode('utf-8')) > 4096:
            raise ValueError('INVALID_REQUEST_SIZE')
        if not is_uuid(envelope['request_id']) or not is_uuid(envelope['session_id']):
            raise ValueError('INVALID_REQUEST_ID')
        if not isinstance(envelope['device_id'], str) or not 1 <= len(envelope['device_id']) <= 128:
            raise ValueError('INVALID_DEVICE_ID')
        operation = envelope['operation']
        if not isinstance(operation, str) or operation not in PAYLOADS:
            raise ValueError('INVALID_OPERATION')
        actor = envelope['actor']
        if not isinstance(actor, dict) or set(actor) != {'subject_id', 'audit_id', 'permissions'}:
            raise ValueError('INVALID_ACTOR')
        if any(not isinstance(actor[key], str) or not 1 <= len(actor[key]) <= 128 or any(ord(char) < 32 for char in actor[key])
               for key in ('subject_id', 'audit_id')):
            raise ValueError('INVALID_ACTOR')
        permissions = actor['permissions']
        if not isinstance(permissions, list) or len(permissions) > len(PERMISSIONS) or any(not isinstance(item, str) or item not in PERMISSIONS for item in permissions) or len(set(permissions)) != len(permissions):
            raise ValueError('INVALID_PERMISSIONS')
        contract = envelope['expected_contract']
        if not isinstance(contract, dict) or set(contract) != {'feature_config_id', 'calibration_id', 'sample_mode_id', 'signature'}:
            raise ValueError('INVALID_CONTRACT')
        if any(type(contract[key]) is not int or not 0 <= contract[key] <= 0xffffffff
               for key in ('feature_config_id', 'calibration_id', 'sample_mode_id')) or not is_hash(contract['signature']):
            raise ValueError('INVALID_CONTRACT')
        payload = envelope['payload']
        if not isinstance(payload, dict) or set(payload) != PAYLOADS[operation]:
            raise ValueError('INVALID_PAYLOAD')
        if operation == 'start' and payload['healthy_confirmed'] is not True:
            raise ValueError('HEALTHY_CONFIRMATION_REQUIRED')
        for key in ('job_id', 'baseline_id', 'expected_baseline_id'):
            if key in payload and not (key == 'expected_baseline_id' and payload[key] is None):
                value = payload[key]
                valid = is_uuid(value) if key == 'job_id' else isinstance(value, str) and 1 <= len(value) <= 128 and all(ord(char) >= 32 for char in value)
                if not valid:
                    raise ValueError('INVALID_' + key.upper())
        if 'candidate_hash' in payload and not is_hash(payload['candidate_hash']):
            raise ValueError('CANDIDATE_HASH_MISMATCH')
        issued, expires = utc_seconds(envelope['issued_at']), utc_seconds(envelope['expires_at'])
        if not 0 < expires - issued <= 30:
            raise ValueError('INVALID_COMMAND_LIFETIME')
        return issued, expires

    def rejection(self, envelope, now, issued, expires):
        learner = self.learner
        operation, payload, actor = envelope['operation'], envelope['payload'], envelope['actor']
        if envelope['device_id'] != learner.config['device_id']:
            return 'DEVICE_MISMATCH'
        if 'learning.' + operation not in actor['permissions']:
            return 'FORBIDDEN'
        if not self.clock_trusted(now):
            return 'CLOCK_UNTRUSTED'
        if self.wall_time() >= expires:
            return 'REQUEST_EXPIRED'
        if self.wall_time() + 2 < issued:
            return 'COMMAND_FROM_FUTURE'
        if envelope['session_id'] != self.session_id:
            return 'SESSION_MISMATCH'
        if not self.linked or self.observed_at is None or not 0 <= now - self.observed_at <= 1:
            return 'STATUS_STALE'
        if self.context_guard is not None:
            reason = self.context_guard()
            if reason:
                return reason
        if envelope['expected_contract'] != self.contract():
            return 'CONTRACT_MISMATCH'
        if 'expected_baseline_id' in payload and payload['expected_baseline_id'] != self.active_id():
            return 'ACTIVE_BASELINE_CHANGED'
        if operation in ('cancel', 'commit'):
            if payload['job_id'] != learner.job_id:
                return 'JOB_MISMATCH'
            row = self.connection.execute('SELECT owner FROM web_jobs WHERE id=?', (payload['job_id'],)).fetchone()
            if (not row or row[0] != actor['subject_id']) and 'learning.takeover' not in actor['permissions']:
                return 'FORBIDDEN'
        if operation != 'cancel':
            guard = learner.guard(self.status)
            if guard:
                return guard
            if not self.fresh(now):
                return learner.reason if learner.qualified_at is None and learner.reason != 'READY' else 'NO_FRESH_FRAME'
        if operation == 'commit' and learner.state == 'PENDING_CONFIRM' and now - learner.pending_since >= learner.config['confirm_seconds']:
            learner.finish('TIMEOUT', 'CONFIRM_TIMEOUT')
            return 'CONFIRM_TIMEOUT'
        return None

    def execute(self, envelope, now):
        started = time.monotonic()
        try:
            issued, expires = self.validate(envelope)
        except (ValueError, TypeError, OverflowError, RecursionError) as error:
            return self.receipt(envelope if isinstance(envelope, dict) else {}, False, str(error)[:100])
        identity = envelope['request_id']
        fingerprint = digest(envelope)
        previous = self.connection.execute('SELECT fingerprint FROM web_requests WHERE id=?', (identity,)).fetchone()
        if previous:
            return self.result(identity) if previous[0] == fingerprint else self.receipt(envelope, False, 'REQUEST_ID_REUSED')
        if self.connection.execute('SELECT count(*) FROM web_requests').fetchone()[0] >= 1024:
            return self.receipt(envelope, False, 'REQUEST_JOURNAL_FULL')
        with self.connection:
            self.connection.execute('INSERT INTO web_requests VALUES(?,?,?,NULL)', (identity, fingerprint, canonical(envelope)))
        now += time.monotonic() - started
        reason = self.rejection(envelope, now, issued, expires)
        if reason:
            result = self.receipt(envelope, False, reason, 'EXPIRED' if reason == 'REQUEST_EXPIRED' else None)
        else:
            command = dict(envelope['payload'], request_id=identity, operation=envelope['operation'])
            command.pop('expected_baseline_id', None)
            if envelope['operation'] == 'start':
                command['operator'] = envelope['actor']['subject_id']
            validation_started = time.monotonic()
            def execution_guard():
                current = now + time.monotonic() - validation_started
                if not self.clock_trusted(current):
                    return 'CLOCK_UNTRUSTED'
                if self.wall_time() >= expires:
                    return 'REQUEST_EXPIRED'
                if self.context_guard is not None:
                    pending = self.context_guard()
                    if pending:
                        return pending
                if envelope['operation'] != 'cancel' and not self.fresh(current):
                    return 'NO_FRESH_FRAME'
                return None
            response = self.learner.command(command, now, context_guard=execution_guard)
            if response.get('ok') and envelope['operation'] == 'start':
                with self.connection:
                    self.connection.execute('INSERT INTO web_jobs VALUES(?,?)', (response['job_id'], envelope['actor']['subject_id']))
            result = self.receipt(envelope, bool(response.get('ok')), response.get('reason', 'EXECUTED'),
                                  'EXPIRED' if response.get('reason') == 'REQUEST_EXPIRED' else None,
                                  **{key: response[key] for key in ('job_id', 'baseline_id') if key in response})
            if response.get('ok'):
                result.update(observation_only=not self.learner.config['advisory_qualified'])
                if envelope['operation'] != 'rollback':
                    result.update(job_id=self.learner.job_id, job_state_at_execution=self.learner.state)
        with self.connection:
            self.connection.execute('UPDATE web_requests SET response=? WHERE id=?', (canonical(result), identity))
        self.learner.store.record({'event': 'WEB_COMMAND', 'request_id': identity,
                                   'actor': envelope['actor'], 'operation': envelope['operation'],
                                   'reason': result['reason'], 'command_state': result['command_state']})
        return result

    def query(self, payload, now):
        view = payload.get('view')
        expected = {'operation', 'view', 'request_id'} if view == 'command' else {'operation', 'view'}
        if set(payload) != expected or payload.get('operation') != 'status':
            return {'ok': False, 'reason': 'INVALID_QUERY'}
        if view == 'web':
            return self.snapshot(now)
        if view == 'baselines':
            return self.history()
        if view == 'command':
            return self.result(payload['request_id'])
        return {'ok': False, 'reason': 'INVALID_QUERY'}
