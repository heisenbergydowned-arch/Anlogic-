"""Healthy-condition teach-in. This module has no hardware command capability."""
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import statistics
import time
import uuid

from .protocol import FEATURES, FrameGate, elapsed32


TERMINAL = {'IDLE', 'COMMITTED', 'ABORTED', 'REJECTED', 'CANCELLED', 'TIMEOUT'}
BUSY = {'WAIT_STABLE', 'CAPTURING', 'VALIDATING', 'PENDING_CONFIRM'}
MIN_SCALE = 1.0 / 65536
DEFAULTS = {
    'schema': 'cabinet-learning-v1', 'device_id': '', 'installation_id': '',
    'contract': {'feature_config_id': 1, 'sample_mode_id': 1, 'calibration_id': 0,
                 'max_frame_age_ms': 1000, 'max_temp_age_ms': 2000},
    'stable_seconds': 10.0, 'capture_seconds': 60.0, 'timeout_seconds': 180.0,
    'confirm_seconds': 120.0, 'sample_interval_ms': 500, 'min_samples': 100,
    'rpm_relative': 0.02, 'rpm_absolute': 60.0, 'max_temp_span': 2.0,
    'max_reject_fraction': 0.1, 'max_gap_seconds': 1.0,
    'warn_score': 6.0, 'recover_score': 3.0, 'confirm_deviation_seconds': 5.0,
    'advisory_qualified': False,
    'noise_floors': ([0.002] * 3 + [0.004] * 3 + [0.2] * 3 + [0.01] * 8) * 2
                    + [0.05, 0.03, 0.5, 0.02, 100.0],
}


class LearningOwnershipError(RuntimeError):
    pass


class LearningContextChanged(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def signature_document(config, header, feature_words, protection_config_id):
    return json.loads(canonical(dict(device=config['device_id'], installation=config['installation_id'],
        config=config, feature_words=list(feature_words), build=header[26], clock=header[21],
        sample_mode=header[18], nominal_fs=header[20], adc_fs=header[22],
        protection_config_id=protection_config_id)))


def provenance_context(profile):
    provenance = profile.get('provenance')
    expected = {'device', 'installation', 'config', 'feature_words', 'build', 'clock',
                'sample_mode', 'nominal_fs', 'adc_fs', 'protection_config_id'}
    if type(provenance) is not dict or set(provenance) != expected:
        raise ValueError('Original baseline signature provenance required; legacy profiles need reviewed relearning')
    config = validate_config(provenance['config'])
    if config != provenance['config'] or (provenance['device'], provenance['installation']) != (
            profile['device_id'], profile['installation_id']) or (config['device_id'], config['installation_id']) != (
            profile['device_id'], profile['installation_id']):
        raise ValueError('Baseline provenance owner/configuration mismatch')
    words = provenance['feature_words']
    if type(words) is not list or len(words) != 17 or any(type(word) is not int or not 0 <= word <= 0xffffffff for word in words):
        raise ValueError('Original seventeen-word feature readback required')
    contract = config['contract']
    if not contract['calibration_id'] or words[:3] != [contract['feature_config_id'], contract['calibration_id'], 1]:
        raise ValueError('Baseline provenance feature/calibration readback mismatch')
    if any(type(provenance[key]) is not int or not 0 < provenance[key] <= 0xffffffff
           for key in ('build', 'clock', 'sample_mode', 'nominal_fs', 'adc_fs', 'protection_config_id')):
        raise ValueError('Exact baseline clock/build/configuration identities required')
    if provenance['sample_mode'] != contract['sample_mode_id'] or digest(provenance) != profile['signature']:
        raise ValueError('Baseline signature differs from original provenance')
    return dict(device_id=provenance['device'], installation_id=provenance['installation'],
                feature_config_id=words[0], calibration_id=words[1], sample_mode_id=provenance['sample_mode'],
                pl_build_id=provenance['build'], protection_config_id=provenance['protection_config_id'])


def validate_profile(profile):
    if not isinstance(profile, dict) or profile.get('schema') != 1 or profile.get('source') != 'REAL':
        raise ValueError('Invalid baseline schema/source')
    for name in ('center', 'scale'):
        values = profile.get(name)
        if not isinstance(values, list) or len(values) != 39 or any(type(number) not in (int, float) or not math.isfinite(number) for number in values):
            raise ValueError('Invalid baseline statistics')
    if any(number < MIN_SCALE for number in profile['scale']):
        raise ValueError('Invalid baseline noise scale')
    if type(profile.get('samples')) is not int or not 12 <= profile['samples'] <= 1000:
        raise ValueError('Invalid baseline sample count')
    for name in ('id', 'signature', 'device_id', 'installation_id', 'job_id'):
        if not isinstance(profile.get(name), str) or not 1 <= len(profile[name]) <= 128:
            raise ValueError('Invalid baseline identity')
    if any(type(profile.get(name)) not in (int, float) or not math.isfinite(profile[name]) for name in ('rpm_min', 'rpm_max')):
        raise ValueError('Invalid baseline RPM coverage')
    if profile['rpm_min'] >= profile['rpm_max']:
        raise ValueError('Empty baseline RPM coverage')
    if type(profile.get('advisory_qualified')) is not bool:
        raise ValueError('Invalid baseline qualification')
    if 'provenance' in profile:
        provenance_context(profile)
    return profile


def validate_config(value):
    config = json.loads(canonical(DEFAULTS))
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Unknown learning configuration fields')
    config.update(value)
    if config['schema'] != DEFAULTS['schema']:
        raise ValueError('Learning schema mismatch')
    for name in ('device_id', 'installation_id'):
        if not isinstance(config[name], str) or len(config[name]) > 128:
            raise ValueError('Invalid ' + name)
    if not isinstance(config['advisory_qualified'], bool):
        raise ValueError('advisory_qualified must be boolean')
    bounds = {
        'stable_seconds': (0.1, 120), 'capture_seconds': (1, 3600),
        'timeout_seconds': (1, 7200), 'confirm_seconds': (1, 600),
        'sample_interval_ms': (256, 10000), 'min_samples': (12, 1000),
        'rpm_relative': (0.001, 0.05), 'rpm_absolute': (1, 150),
        'max_temp_span': (0.1, 5), 'max_reject_fraction': (0, 0.2),
        'max_gap_seconds': (0.1, 2), 'warn_score': (2, 12),
        'recover_score': (1, 10), 'confirm_deviation_seconds': (1, 60),
    }
    for name, limits in bounds.items():
        number = config[name]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not limits[0] <= number <= limits[1]:
            raise ValueError('Invalid ' + name)
    for name in ('min_samples', 'sample_interval_ms'):
        if type(config[name]) is not int:
            raise ValueError(name + ' must be integer')
    if config['recover_score'] >= config['warn_score']:
        raise ValueError('Recovery threshold must be below warning')
    if config['timeout_seconds'] <= config['stable_seconds'] + config['capture_seconds']:
        raise ValueError('Learning timeout too short')
    floors = config['noise_floors']
    if not isinstance(floors, list) or len(floors) != 39 or any(type(number) not in (int, float) or not math.isfinite(number) or number < MIN_SCALE for number in floors):
        raise ValueError('Exactly 39 positive noise floors required')
    contract = config['contract']
    expected = set(DEFAULTS['contract'])
    if not isinstance(contract, dict) or set(contract) != expected or any(type(number) is not int or not 0 <= number <= 0xffffffff for number in contract.values()):
        raise ValueError('Invalid frame contract')
    if not contract['feature_config_id'] or not contract['sample_mode_id'] or not 1 <= contract['max_frame_age_ms'] <= 1000 or not 1 <= contract['max_temp_age_ms'] <= 2000:
        raise ValueError('Invalid qualification/freshness bounds')
    return config


class BaselineStore:
    def __init__(self, path):
        import fcntl
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        self.connection = None
        self.owner_fd = None
        owner_file = path.with_name(path.name + '.owner.lock')
        descriptor = os.open(str(owner_file), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
                raise LearningOwnershipError('Unsafe baseline ownership file')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise LearningOwnershipError('Baseline database already has a learning owner')
            self.owner_fd = descriptor
            self.initialize(path)
        except BaseException:
            if self.owner_fd is not None:
                self.close()
            else:
                os.close(descriptor)
            raise

    def initialize(self, path):
        self.connection = sqlite3.connect(str(path))
        path.chmod(0o600)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY, state TEXT NOT NULL, body TEXT NOT NULL, checksum TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS task (singleton INTEGER PRIMARY KEY CHECK(singleton=1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response TEXT);
        ''')
        unfinished = self.connection.execute('SELECT body FROM task WHERE singleton=1').fetchone()
        if unfinished:
            self.record({'event': 'INTERRUPTED_BY_RESTART', 'task': json.loads(unfinished[0])})
            with self.connection:
                self.connection.execute("DELETE FROM profiles WHERE state='CANDIDATE'")
                self.connection.execute('DELETE FROM task')

    def record(self, event):
        event = dict(event, recorded_at=time.time())
        with self.connection:
            self.connection.execute('INSERT INTO audit(body) VALUES(?)', (canonical(event),))
            self.connection.execute('DELETE FROM audit WHERE sequence NOT IN (SELECT sequence FROM audit ORDER BY sequence DESC LIMIT 256)')

    def task(self, value):
        with self.connection:
            if value is None:
                self.connection.execute('DELETE FROM task')
            else:
                self.connection.execute('INSERT OR REPLACE INTO task VALUES(1,?)', (canonical(value),))

    def previous_request(self, identity, fingerprint):
        row = self.connection.execute('SELECT fingerprint,response FROM requests WHERE id=?', (identity,)).fetchone()
        if row is None:
            return None
        if row[0] != fingerprint:
            return {'ok': False, 'reason': 'REQUEST_ID_REUSED'}
        return json.loads(row[1]) if row[1] else {'ok': False, 'reason': 'INTERRUPTED_REQUEST_CHECK_STATUS'}

    def reserve_request(self, identity, fingerprint):
        with self.connection:
            if self.connection.execute('SELECT count(*) FROM requests').fetchone()[0] >= 1024:
                raise ValueError('Request journal full; maintenance required')
            self.connection.execute('INSERT INTO requests VALUES(?,?,NULL)', (identity, fingerprint))

    def complete_request(self, identity, result):
        with self.connection:
            self.connection.execute('UPDATE requests SET response=? WHERE id=?', (canonical(result), identity))

    def save_candidate(self, body):
        with self.connection:
            count = self.connection.execute('SELECT count(*) FROM profiles').fetchone()[0]
            if count >= 32:
                raise ValueError('Profile history is full; export/archive before relearning')
            self.connection.execute('INSERT INTO profiles VALUES(?,?,?,?)',
                                    (body['id'], 'CANDIDATE', canonical(body), digest(body)))

    def history_full(self):
        return self.connection.execute('SELECT count(*) FROM profiles').fetchone()[0] >= 32

    def profiles(self, state='ACTIVE'):
        results = []
        for identity, body, checksum in self.connection.execute('SELECT id,body,checksum FROM profiles WHERE state=?', (state,)):
            profile = json.loads(body)
            if digest(profile) != checksum or profile['id'] != identity:
                raise ValueError('Baseline checksum mismatch')
            results.append(validate_profile(profile))
        return results

    def activate(self, profile, source='CANDIDATE', context_guard=None):
        row = self.connection.execute('SELECT body,checksum,state FROM profiles WHERE id=?', (profile['id'],)).fetchone()
        if not row or row[2] != source or digest(json.loads(row[0])) != row[1] or row[1] != digest(profile):
            raise ValueError('Candidate changed or is unavailable')
        with self.connection:
            reason = context_guard() if context_guard is not None else None
            if reason:
                raise LearningContextChanged(reason)
            self.connection.execute("UPDATE profiles SET state='ARCHIVED' WHERE state='ACTIVE'")
            self.connection.execute("UPDATE profiles SET state='ACTIVE' WHERE id=?", (profile['id'],))
            self.connection.execute('DELETE FROM task')
            event = canonical({'event': 'BASELINE_' + ('ROLLBACK' if source == 'ARCHIVED' else 'COMMIT'),
                               'baseline_id': profile['id'], 'checksum': digest(profile), 'recorded_at': time.time()})
            self.connection.execute('INSERT INTO audit(body) VALUES(?)', (event,))

    def discard(self, identity):
        with self.connection:
            self.connection.execute("DELETE FROM profiles WHERE id=? AND state='CANDIDATE'", (identity,))

    def close(self):
        try:
            if self.connection is not None:
                self.connection.close()
                self.connection = None
        finally:
            if self.owner_fd is not None:
                os.close(self.owner_fd)
                self.owner_fd = None


class Learner:
    def __init__(self, store, config):
        self.store = store
        self.config = validate_config(config)
        self.gate = FrameGate(self.config['contract'])
        self.profiles = store.profiles()
        self.state = 'IDLE'
        self.reason = 'NO_FRAME'
        self.job_id = None
        self.candidate = None
        self.rows = []
        self.accepted = self.rejected = 0
        self.started = self.stable_since = self.capture_since = None
        self.last_time = self.last_frame = self.last_selected = None
        self.last_signature = self.session = self.last_event_sequence = None
        self.last_provenance = None
        self.stable_rpm = None
        self.allowed = False
        self.job_reason = None
        self.last_valid = False
        self.qualified_at = None
        self.evidence = {'state': 'UNLEARNED', 'score': None, 'level': 0}
        self.deviation_since = None
        self.deviation_active = False

    def signature(self, frame, feature_words, status):
        return digest(signature_document(self.config, frame.header, feature_words, status['configuration_id']))

    def guard(self, status):
        if not self.config['device_id'] or not self.config['installation_id']:
            return 'INSTALLATION_UNQUALIFIED'
        if not self.config['contract']['calibration_id']:
            return 'CALIBRATION_UNQUALIFIED'
        if not status.get('configured') or not status.get('configuration_id'):
            return 'PROTECTION_UNQUALIFIED'
        if status.get('test_mode'):
            return 'CONTROL_UNQUALIFIED'
        if status.get('active') or status.get('latched') or status.get('alarm_level', 0):
            return 'ACTIVE_ALARM'
        if status.get('lost_events', 0):
            return 'PROTECTION_HISTORY_GAP'
        if status.get('hard_inhibit') or status.get('mode') != 'RUN':
            return 'NOT_STABLE_RUN'
        validity = status.get('input_validity', {})
        if not all(validity.get(name) for name in ('rpm', 'adc', 'temperature', 'pressure')):
            return 'SENSOR_INVALID'
        if status.get('fan_action') not in ('PI', 'MANUAL') or status.get('reserved_meta_bits', 0) != 0:
            return 'CONTROL_CONFLICT'
        measured = status.get('measured_rpm', 0)
        target = status.get('ramped_rpm', 0)
        tolerance = max(self.config['rpm_absolute'], measured * self.config['rpm_relative'])
        if measured <= 0 or target <= 0 or abs(measured - target) > tolerance:
            return 'RPM_TRACKING'
        return None

    def finish(self, state, reason):
        self.state, self.reason, self.allowed = state, reason, False
        self.job_reason = reason
        if self.candidate:
            self.store.discard(self.candidate['id'])
        self.candidate = None
        self.rows = []
        self.store.record({'event': state, 'reason': reason, 'job_id': self.job_id,
                           'accepted': self.accepted, 'rejected': self.rejected})
        self.store.task(None)

    def invalidate(self, reason):
        self.allowed = self.last_valid = False
        self.qualified_at = None
        self.reason = reason
        self.evidence = {'state': 'INVALID_INPUT', 'score': None, 'level': 0}
        self.deviation_since = None
        self.deviation_active = False
        if self.state in BUSY:
            self.finish('ABORTED', reason)

    def observe(self, frame, status, feature_words, session, now, model_result=None):
        if self.last_time is not None and now < self.last_time:
            raise ValueError('Monotonic clock moved backwards')
        self.last_time = now
        changed_session = self.session is not None and session != self.session
        changed_event = self.last_event_sequence is not None and status.get('event_sequence') != self.last_event_sequence
        self.session = session
        self.last_event_sequence = status.get('event_sequence')
        reason = self.guard(status)
        if changed_session:
            self.gate.reset()
            self.qualified_at = None
            reason = 'PL_RESTART'
        if self.state in BUSY and changed_event:
            reason = reason or 'PROTECTION_EVENT_DURING_LEARN'
        if self.state in BUSY and reason:
            self.finish('ABORTED', reason)
        self.allowed = False
        self.last_valid = False
        self.reason = reason or 'NO_FRAME'
        if reason:
            self.qualified_at = None
            self.evidence = {'state': 'INVALID_INPUT', 'score': None, 'level': 0}
            self.deviation_since = None
            self.deviation_active = False
        if self.state in ('WAIT_STABLE', 'CAPTURING', 'VALIDATING') and now - self.started >= self.config['timeout_seconds']:
            self.finish('TIMEOUT', 'LEARNING_TIMEOUT')
        if self.state == 'PENDING_CONFIRM' and now - self.pending_since > self.config['confirm_seconds']:
            self.finish('TIMEOUT', 'CONFIRM_TIMEOUT')
        if frame is None:
            if self.qualified_at is None or now - self.qualified_at > self.config['max_gap_seconds']:
                self.evidence = {'state': 'STALE', 'score': None, 'level': 0}
                self.deviation_since = None
                self.deviation_active = False
                if self.state in BUSY:
                    self.finish('ABORTED', 'FRAME_GAP')
            elif not reason:
                self.allowed = self.state not in BUSY and self.evidence['state'] not in ('CANDIDATE', 'DEVIATION')
                self.last_valid = True
                self.reason = 'READY' if self.allowed or self.state in BUSY else 'EXISTING_BASELINE_DEVIATION'
            return
        rejections = self.gate.check(frame, status['uptime_ms'])
        if rejections:
            self.reason = 'FRAME_' + rejections[0].upper()
        if len(feature_words) != 17 or feature_words[:3] != [frame.header[16], frame.header[17], 1]:
            self.reason = 'FEATURE_CONFIG_UNQUALIFIED'
            rejections.append('feature_active_config')
        if model_result and model_result.get('formal') and model_result.get('label') != 'normal':
            self.reason = 'MODEL_CONFLICT'
            rejections.append('model_conflict')
        if reason or rejections:
            self.qualified_at = None
            self.evidence = {'state': 'INVALID_INPUT', 'score': None, 'level': 0}
            self.deviation_since = None
            self.deviation_active = False
            if self.state in BUSY:
                self.rejected += 1
                if reason or any(item in rejections for item in ('test_frame', 'calibration', 'feature_config', 'feature_active_config', 'model_conflict')):
                    self.finish('ABORTED', self.reason)
                elif self.state == 'PENDING_CONFIRM' or self.rejected / max(1, self.accepted + self.rejected) > self.config['max_reject_fraction']:
                    self.finish('REJECTED', 'FRAME_QUALITY_REJECTED')
                else:
                    self.stable_since = None
            return
        for index, number in enumerate(frame.values):
            if not math.isfinite(number) or (index < 34 and number < 0) or (index in list(range(9, 17)) + list(range(26, 34)) and number > 1.0001):
                self.invalidate('FEATURE_RANGE')
                return
        if not 0.3 <= frame.values[34] <= 6 or any(abs(number) > 32768 for number in frame.values):
            self.invalidate('FEATURE_RANGE')
            return
        if any(abs(sum(frame.values[start:start + 8]) - 1) > 0.001 for start in (9, 26)):
            self.invalidate('BAND_POWER_INVALID')
            return
        if abs(frame.values[38] - status['measured_rpm']) > max(self.config['rpm_absolute'], status['measured_rpm'] * self.config['rpm_relative']):
            self.invalidate('FRAME_RPM_NOT_STABLE')
            return
        signature = self.signature(frame, feature_words, status)
        if self.state in BUSY and self.last_signature != signature:
            self.finish('ABORTED', 'CONTRACT_CHANGED')
        self.last_signature = signature
        self.last_provenance = signature_document(self.config, frame.header, feature_words, status['configuration_id'])
        self.last_frame = frame
        self.last_valid = True
        self.qualified_at = now
        self.reason = 'READY'
        self.evidence = self.compare(frame, signature, now)
        if self.state in BUSY and self.evidence['state'] in ('CANDIDATE', 'DEVIATION'):
            self.finish('ABORTED', 'EXISTING_BASELINE_DEVIATION_DURING_LEARN')
            return
        if self.state == 'PENDING_CONFIRM' and self.candidate is not None:
            problem = self.candidate_problem(self.candidate, frame)
            if problem:
                self.finish('ABORTED', problem)
                return
        self.allowed = self.state not in BUSY and self.evidence['state'] not in ('DEVIATION', 'CANDIDATE')
        if not self.allowed and self.state not in BUSY:
            self.reason = 'EXISTING_BASELINE_DEVIATION'
        if self.state not in ('WAIT_STABLE', 'CAPTURING'):
            return
        rpm = frame.values[38]
        tolerance = max(self.config['rpm_absolute'], rpm * self.config['rpm_relative'])
        if self.stable_rpm is None or abs(rpm - self.stable_rpm) > tolerance:
            self.stable_rpm = rpm
            self.stable_since = now
            if self.state == 'CAPTURING':
                self.rows = []
                self.capture_since = None
                self.last_selected = None
                self.state = 'WAIT_STABLE'
        if self.stable_since is None:
            self.stable_since = now
        if self.state == 'WAIT_STABLE':
            if now - self.stable_since < self.config['stable_seconds']:
                return
            self.state, self.capture_since = 'CAPTURING', now
            self.store.task({'job_id': self.job_id, 'state': self.state})
        self.accepted += 1
        duration_ms = max(frame.header[9], frame.header[10]) * 1000.0 / frame.header[21]
        interval_ms = max(self.config['sample_interval_ms'], duration_ms + 1)
        end_ms = frame.header[4]
        if self.last_selected is None or elapsed32(end_ms, self.last_selected) >= interval_ms:
            self.rows.append(list(frame.values))
            self.last_selected = end_ms
        if len(self.rows) > 1000:
            self.finish('REJECTED', 'SAMPLE_BUDGET')
            return
        if now - self.capture_since >= self.config['capture_seconds'] and len(self.rows) >= self.config['min_samples']:
            self.validate_candidate(now)

    def candidate_problem(self, profile, frame):
        if not profile['rpm_min'] <= frame.values[38] <= profile['rpm_max']:
            return 'CANDIDATE_OPERATING_POINT_CHANGED'
        score = max(abs(frame.values[index] - profile['center'][index]) / profile['scale'][index] for index in range(38))
        if score >= self.config['warn_score']:
            return 'CANDIDATE_DRIFT'
        return None

    def compare(self, frame, signature, now):
        if not self.profiles:
            return {'state': 'UNLEARNED', 'score': None, 'level': 0}
        compatible = [profile for profile in self.profiles if profile['signature'] == signature]
        if not compatible:
            self.deviation_since = None
            self.deviation_active = False
            return {'state': 'VERSION_MISMATCH', 'score': None, 'level': 0}
        rpm = frame.values[38]
        profile = compatible[0]
        if not profile['rpm_min'] <= rpm <= profile['rpm_max']:
            self.deviation_since = None
            self.deviation_active = False
            return {'state': 'OUT_OF_COVERAGE', 'score': None, 'level': 0}
        contributions = [abs(frame.values[index] - profile['center'][index]) / profile['scale'][index] for index in range(38)]
        score = max(contributions)
        group_scores = {
            'amplitude': max(contributions[index] for index in list(range(9)) + list(range(17, 26))),
            'spectrum': max(contributions[index] for index in list(range(9, 17)) + list(range(26, 34))),
            'ratio': contributions[34], 'process': max(contributions[35:38])}
        feature = FEATURES[contributions.index(score)]
        if score >= self.config['warn_score']:
            if self.deviation_since is None:
                self.deviation_since = now
            if now - self.deviation_since >= self.config['confirm_deviation_seconds']:
                self.deviation_active = True
            state = 'DEVIATION' if self.deviation_active else 'CANDIDATE'
        elif score <= self.config['recover_score']:
            self.deviation_since = None
            self.deviation_active = False
            state = 'CONSISTENT'
        else:
            state = 'DEVIATION' if self.deviation_active else 'CANDIDATE'
        return {'state': state, 'score': score, 'group_scores': group_scores, 'feature': feature, 'baseline_id': profile['id'],
                'level': 1 if self.deviation_active and self.config['advisory_qualified'] else 0,
                'observation_only': not self.config['advisory_qualified']}

    def validate_candidate(self, now):
        self.state = 'VALIDATING'
        split = int(len(self.rows) * 0.7)
        training = self.rows[:split]
        holdout = self.rows[split + 1:]
        if len(holdout) < 3:
            self.finish('REJECTED', 'HOLDOUT_TOO_SMALL')
            return
        center, scale = [], []
        for index in range(39):
            median = statistics.median(row[index] for row in training)
            spread = statistics.median(abs(row[index] - median) for row in training)
            center.append(median)
            scale.append(max(1.4826 * spread, self.config['noise_floors'][index]))
        if max(row[36] for row in self.rows) - min(row[36] for row in self.rows) > self.config['max_temp_span']:
            self.finish('REJECTED', 'THERMAL_DRIFT')
            return
        maximum = max(abs(row[index] - center[index]) / scale[index] for row in holdout for index in range(38))
        if maximum >= self.config['warn_score']:
            self.finish('REJECTED', 'HOLDOUT_DEVIATION')
            return
        rpm = center[38]
        tolerance = max(self.config['rpm_absolute'], rpm * self.config['rpm_relative'])
        self.candidate = {'schema': 1, 'id': str(uuid.uuid4()), 'signature': self.last_signature,
                          'provenance': json.loads(canonical(self.last_provenance)),
                          'device_id': self.config['device_id'], 'installation_id': self.config['installation_id'],
                          'operator': self.operator, 'job_id': self.job_id, 'source': 'REAL',
                          'created_at': time.time(), 'center': center, 'scale': scale,
                          'rpm_min': rpm - tolerance, 'rpm_max': rpm + tolerance,
                          'samples': len(self.rows), 'holdout_max': maximum,
                          'accepted': self.accepted, 'rejected': self.rejected,
                          'advisory_qualified': self.config['advisory_qualified']}
        self.store.save_candidate(self.candidate)
        self.state = 'PENDING_CONFIRM'
        self.pending_since = now
        self.store.task({'job_id': self.job_id, 'state': self.state, 'candidate_id': self.candidate['id']})
        self.store.record({'event': 'CANDIDATE_VALIDATED', 'candidate_id': self.candidate['id'], 'job_id': self.job_id})

    def command(self, request, now, context_guard=None):
        entered = time.monotonic()
        if not isinstance(request, dict) or request.get('operation') not in ('status', 'start', 'cancel', 'commit', 'rollback'):
            return {'ok': False, 'reason': 'INVALID_OPERATION'}
        if request['operation'] == 'status':
            return dict(self.snapshot(), ok=True)
        identity = request.get('request_id')
        if not isinstance(identity, str) or not 1 <= len(identity) <= 64:
            return {'ok': False, 'reason': 'REQUEST_ID_REQUIRED'}
        fingerprint = digest(request)
        previous = self.store.previous_request(identity, fingerprint)
        if previous is not None:
            return previous
        self.store.reserve_request(identity, fingerprint)
        now += time.monotonic() - entered
        operation = request['operation']
        recent = self.qualified_at is not None and 0 <= now - self.qualified_at <= self.config['max_gap_seconds']
        expired = None
        if self.state == 'PENDING_CONFIRM' and now - self.pending_since >= self.config['confirm_seconds']:
            expired = 'CONFIRM_TIMEOUT'
        elif self.state in ('WAIT_STABLE', 'CAPTURING', 'VALIDATING') and now - self.started >= self.config['timeout_seconds']:
            expired = 'LEARNING_TIMEOUT'
        if expired:
            self.finish('TIMEOUT', expired)
        result = {'ok': False, 'reason': self.reason}
        context_reason = context_guard() if context_guard is not None else None
        if context_reason:
            result['reason'] = context_reason
        elif expired:
            result['reason'] = expired
        elif operation == 'start':
            if self.state in BUSY:
                result['reason'] = 'BUSY'
            elif request.get('healthy_confirmed') is not True:
                result['reason'] = 'HEALTHY_CONFIRMATION_REQUIRED'
            elif self.store.history_full():
                result['reason'] = 'PROFILE_HISTORY_FULL'
            elif self.allowed and recent:
                self.operator = str(request.get('operator', 'local'))[:80]
                self.job_id = str(uuid.uuid4())
                self.job_reason = None
                self.started = now
                self.stable_since = self.capture_since = self.stable_rpm = self.last_selected = None
                self.rows = []
                self.accepted = self.rejected = 0
                self.candidate = None
                self.state = 'WAIT_STABLE'
                self.allowed = False
                self.store.task({'job_id': self.job_id, 'state': self.state})
                self.store.record({'event': 'LEARN_START', 'job_id': self.job_id, 'operator': self.operator, 'healthy_confirmed': True})
                result = {'ok': True, 'job_id': self.job_id}
            elif not recent:
                result['reason'] = self.reason if self.reason != 'READY' else 'NO_FRESH_FRAME'
        elif operation == 'cancel':
            if request.get('job_id') == self.job_id and self.state in BUSY:
                self.finish('CANCELLED', 'OPERATOR_CANCELLED')
                result = {'ok': True}
            else:
                result['reason'] = 'JOB_MISMATCH'
        elif operation == 'commit':
            if self.state != 'PENDING_CONFIRM' or not self.candidate:
                result['reason'] = 'NO_CANDIDATE'
            elif 'job_id' in request and request['job_id'] != self.job_id:
                result['reason'] = 'JOB_MISMATCH'
            elif request.get('candidate_hash') != digest(self.candidate):
                result['reason'] = 'CANDIDATE_HASH_MISMATCH'
            elif not recent or not self.last_valid:
                result['reason'] = 'NO_FRESH_FRAME'
            elif self.evidence['state'] in ('CANDIDATE', 'DEVIATION'):
                self.finish('ABORTED', 'EXISTING_BASELINE_DEVIATION_DURING_LEARN')
                result['reason'] = self.reason
            elif self.candidate['signature'] != self.last_signature:
                self.finish('ABORTED', 'CONTRACT_CHANGED')
                result['reason'] = self.reason
            elif self.candidate_problem(self.candidate, self.last_frame):
                self.finish('ABORTED', self.candidate_problem(self.candidate, self.last_frame))
                result['reason'] = self.reason
            else:
                try:
                    self.store.activate(self.candidate, context_guard=context_guard)
                except LearningContextChanged as error:
                    result['reason'] = str(error)
                    self.store.complete_request(identity, result)
                    return result
                self.profiles = self.store.profiles()
                self.state, self.reason = 'COMMITTED', 'BASELINE_SAVED'
                self.candidate = None
                self.rows = []
                result = {'ok': True, 'baseline_id': self.profiles[0]['id']}
        elif operation == 'rollback':
            if self.state in BUSY or not recent or not self.last_valid:
                result['reason'] = 'NO_FRESH_FRAME_OR_BUSY'
            else:
                match = [profile for profile in self.store.profiles('ARCHIVED') if profile['id'] == request.get('baseline_id') and profile['signature'] == self.last_signature]
                if match:
                    try:
                        self.store.activate(match[0], source='ARCHIVED', context_guard=context_guard)
                    except LearningContextChanged as error:
                        result['reason'] = str(error)
                        self.store.complete_request(identity, result)
                        return result
                    self.profiles = self.store.profiles()
                    self.deviation_since = None
                    self.deviation_active = False
                    result = {'ok': True, 'baseline_id': match[0]['id']}
                else:
                    result['reason'] = 'INCOMPATIBLE_BASELINE'
        self.store.complete_request(identity, result)
        return result

    def snapshot(self):
        full = self.store.history_full()
        reason = 'PROFILE_HISTORY_FULL' if self.allowed and full else self.reason
        return {'state': self.state, 'reason': reason, 'can_start': self.allowed and not full,
                'job_reason': self.job_reason,
                'job_id': self.job_id, 'samples': len(self.rows) if self.rows or self.state in BUSY else self.profiles[0]['samples'] if self.profiles else 0,
                'required': self.config['min_samples'],
                'accepted': self.accepted, 'rejected': self.rejected,
                'candidate_hash': digest(self.candidate) if self.candidate else None,
                'baseline_id': self.profiles[0]['id'] if self.profiles else None,
                'advisory_qualified': self.config['advisory_qualified'],
                'warning_score': self.config['warn_score'],
                'evidence': self.evidence}
