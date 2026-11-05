"""Passive FRM1 pressure baseline; maintenance indication, never actuator authority."""
import copy
import hashlib
import math
import re
import sqlite3
import statistics
import threading
import time
import uuid
from collections import deque, OrderedDict
from pathlib import Path
from hmi_daily.cabinet.learning_web import strict_json
from .pressure_storage import PressureStorage, digest


PREFIX = '/api/pressure-calibration/v1'
DEFAULTS = dict(mode='passive', duties_percent=list(range(10, 101, 10)), duty_tolerance_pp=1,
                settle_s=3, stable_window_s=3, capture_window_s=5, min_fresh_records=20,
                rpm_cv_max=0.03, pressure_cv_max=0.05, point_timeout_s=30,
                retention_alarm_ratio=0.70, alarm_hold_s=5, retention_recover_ratio=0.80,
                recover_hold_s=5, temperature_min_C=None, temperature_max_C=None)


def fields(document, required):
    if type(document) is not dict or set(document) != set(required):
        raise ValueError('Unknown or missing fields')


def number(value, minimum, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError('Finite numeric value outside allowed range')
    return value


def cv(values):
    average = statistics.mean(values)
    return statistics.pstdev(values) / average if average > 0 else float('inf')


class PressureCalibration:
    def __init__(self, service, clock=time.monotonic):
        self.service = service
        self.clock = clock
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.repository = None
        self.error = None
        self.storage_uncertain = False
        self.audit_error = None
        self.audited_detection = None
        self.profile = None
        self.config = copy.deepcopy(DEFAULTS)
        self.revision = 0
        self.persistence = 'runtime_only'
        self.previews = OrderedDict()
        self.requests = OrderedDict()
        self.operations = OrderedDict()
        self.pending = deque()
        self.job = None
        self.baseline = None
        self.previous_identity = None
        self.previous_end = None
        self.previous_time = None
        self.runtime = deque(maxlen=10000)
        self.runtime_duty = None
        self.runtime_since = None
        self.alarm = False
        self.low_since = self.recover_since = None
        self.detection = dict(state='UNAVAILABLE', reason='NO_BASELINE', retention_ratio=None,
                              maintenance_alarm=False, control_authority=False, lifetime_qualified=False)
        setup = service.config.get('pressure_calibration', {})
        if type(setup) is not dict or set(setup) - {'enabled', 'profile', 'sha256', 'sd_directory'}:
            raise ValueError('Unknown pressure calibration setup')
        if type(setup.get('enabled', False)) is not bool:
            raise ValueError('Pressure enable must be boolean')
        self.enabled = setup.get('enabled', False)
        if not self.enabled:
            return
        try:
            raw = Path(setup['profile']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != setup['sha256']:
                raise ValueError('Commissioned pressure profile hash mismatch')
            self.profile = strict_json(raw, limit=65536)
            fields(self.profile, ('schema', 'device_id', 'fan_id', 'installation_id', 'sensor_id',
                                 'pickup', 'pressure_min_valid_pa', 'temperature_min_C', 'temperature_max_C'))
            if type(self.profile['schema']) is not int or self.profile['schema'] != 1 or self.profile['device_id'] != service.config['device_id']:
                raise ValueError('Pressure profile identity mismatch')
            for key in ('fan_id', 'installation_id', 'sensor_id', 'pickup'):
                if type(self.profile[key]) is not str or not 1 <= len(self.profile[key].strip()) <= 160:
                    raise ValueError('Commissioned installation and pickup identity required')
            number(self.profile['pressure_min_valid_pa'], 0.001, 500)
            number(self.profile['temperature_min_C'], -40, 125)
            number(self.profile['temperature_max_C'], self.profile['temperature_min_C'] + 1, 125)
            for key in ('temperature_min_C', 'temperature_max_C'):
                self.config[key] = self.profile[key]
            self.repository = PressureStorage(setup['sd_directory'])
            saved = self.repository.load('config')
            if saved:
                if saved['profile_sha256'] != digest(self.profile):
                    raise ValueError('Stored configuration belongs to another installation')
                self.config = self.validate_config(saved['config'])
                self.persistence = 'sd'
            self.baseline = self.repository.load('baseline')
            if self.baseline:
                self.validate_baseline(self.baseline)
        except BaseException:
            if self.repository:
                self.repository.close()
            raise

    def validate_config(self, configuration):
        fields(configuration, DEFAULTS)
        if configuration['mode'] != 'passive':
            raise ValueError('ACTIVE_SWEEP_NOT_COMMISSIONED_NO_PWM_COMMAND')
        duties = configuration['duties_percent']
        if type(duties) is not list or not duties or any(type(item) is not int for item in duties):
            raise ValueError('Duty list required')
        if duties != sorted(set(duties)) or any(item not in range(10, 101, 10) for item in duties):
            raise ValueError('Select distinct 10-percent bins')
        for key, low, high in [('duty_tolerance_pp', 0.1, 1), ('settle_s', 3, 60),
                               ('stable_window_s', 3, 60), ('capture_window_s', 5, 120),
                               ('rpm_cv_max', 0.001, 0.03), ('pressure_cv_max', 0.001, 0.05),
                               ('point_timeout_s', 30, 300), ('alarm_hold_s', 5, 120),
                               ('recover_hold_s', 5, 120), ('retention_recover_ratio', 0.71, 1)]:
            number(configuration[key], low, high)
        if type(configuration['min_fresh_records']) is not int:
            raise ValueError('Fresh count must be integer')
        number(configuration['min_fresh_records'], 20, 1000)
        if type(configuration['retention_alarm_ratio']) not in (int, float) or configuration['retention_alarm_ratio'] != 0.7:
            raise ValueError('Project maintenance threshold is fixed at 70 percent')
        number(configuration['temperature_min_C'], self.profile['temperature_min_C'], self.profile['temperature_max_C'])
        number(configuration['temperature_max_C'], configuration['temperature_min_C'] + 1, self.profile['temperature_max_C'])
        if configuration['point_timeout_s'] < sum(configuration[key] for key in ('settle_s', 'stable_window_s', 'capture_window_s')):
            raise ValueError('Point timeout shorter than required windows')
        return copy.deepcopy(configuration)

    def binding(self, snapshot):
        frame = snapshot.get('frame') or {}
        return dict(profile_sha256=digest(self.profile), device_id=self.service.config['device_id'],
                    calibration_id=frame.get('calibration_id'), feature_config_id=frame.get('feature_config_id'),
                    sample_mode_id=frame.get('sample_mode_id'), bitstream_id=frame.get('bitstream_id'),
                    pressure_source=frame.get('pressure_source'), pl_config_id=(snapshot.get('status') or {}).get('config_id'), units='Pa')

    def context(self):
        return dict(collector_session=self.service.collector_session, connection_epoch=self.service.connection_epoch,
                    boot_id=self.service.boot)

    def snapshot(self):
        return self.service.public_state()

    def guard(self, snapshot):
        status = snapshot.get('status') or {}
        frame = snapshot.get('frame') or {}
        if (self.service.mock or self.service.diagnostic_test or snapshot.get('test') is not False
                or snapshot.get('link') != 'ONLINE' or not self.service.valid_input
                or not self.service.boot or not status.get('configured') or status.get('mode') != 'RUN'
                or status.get('active') or status.get('latched') or frame.get('test') is not False
                or frame.get('quality') != 0 or not frame.get('calibration_id') or frame.get('mode') != 3):
            raise ValueError('LIVE_CALIBRATED_FAULT_FREE_RUN_REQUIRED')
        for key in ('status_age_ms', 'frame_age_ms'):
            number(snapshot.get(key), 0, 1000)
        if type(status.get('config_id')) is not int or status['config_id'] <= 0:
            raise ValueError('PL configuration identity required')
        validity = status.get('input_validity') or {}
        if any(validity.get(key) is not True for key in ('rpm', 'temperature', 'pressure')) or status.get('hard_inhibit') is not False:
            raise ValueError('Live process inputs and uninhibited state required')
        number(status.get('temp_age_ms'), 0, min(1000, self.service.config['contract'].get('max_temp_age_ms', 1000)))
        number(status.get('temp_raw_1_16_C'), self.config['temperature_min_C'] * 16, self.config['temperature_max_C'] * 16)
        contract = self.service.config['contract']
        for key in ('calibration_id', 'feature_config_id', 'sample_mode_id'):
            if frame.get(key) != contract.get(key):
                raise ValueError('Frame contract mismatch')
        if frame.get('sample_mode_id') != 2 or frame.get('pressure_source') != 'SDP810-500Pa':
            raise ValueError('Calibrated SDP810 Pa source required; raw ADC is not Pa')
        if not frame.get('pressure_count') or not frame.get('fg_count'):
            raise ValueError('Process sample counts required')
        number(frame.get('frame_id'), 0, 0xffffffff)
        number(frame.get('end_ms'), 0, 0xffffffff)
        number(status.get('applied_pwm_counts'), 0, 4000)
        if status.get('fan_action') != 'PI':
            raise ValueError('Protection or unknown fan action owns output')
        values = frame.get('values') or {}
        pressure = number(values.get('pressure'), self.profile['pressure_min_valid_pa'] / 1000, 0.5) * 1000
        number(values.get('rpm'), 1, 32767)
        number(status.get('measured_rpm'), 1, 32767)
        number(values.get('temp'), self.config['temperature_min_C'], self.config['temperature_max_C'])
        return dict(duty=status['applied_pwm_counts'] / 40, pressure=pressure,
                    rpm=values['rpm'], temperature=values['temp'],
                    time=self.clock() - snapshot['frame_age_ms'] / 1000,
                    identity=frame['frame_id'], end=frame['end_ms'])

    def validate_baseline(self, baseline):
        fields(baseline, ('schema', 'id', 'binding', 'config', 'points', 'operator', 'healthy_confirmed', 'source', 'created_unix_s'))
        if type(baseline['schema']) is not int or baseline['schema'] != 1 or baseline['binding']['profile_sha256'] != digest(self.profile):
            raise ValueError('Baseline installation mismatch')
        configuration = self.validate_config(baseline['config'])
        if not baseline['points'] or baseline['healthy_confirmed'] is not True or baseline['source'] != 'LIVE_FRM1_PASSIVE':
            raise ValueError('Invalid baseline evidence')
        for key, point in baseline['points'].items():
            if str(int(key)) != key or int(key) not in configuration['duties_percent']:
                raise ValueError('Invalid baseline bin')
            number(point['pressure_pa'], self.profile['pressure_min_valid_pa'], 500)
            number(point['rpm'], 1, 32767)
            number(point['pressure_cv'], 0, configuration['pressure_cv_max'])
            number(point['rpm_cv'], 0, configuration['rpm_cv_max'])
            number(point['records'], configuration['min_fresh_records'], 10000)

    def start(self):
        if self.enabled and self.thread is None:
            self.thread = threading.Thread(target=self.run, name='cabinet-pressure-sd', daemon=True)
            self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(5)
            if self.thread.is_alive():
                raise RuntimeError('Pressure SD worker still active')
        if self.repository:
            self.repository.close()

    def run(self):
        while not self.stop.wait(0.1):
            self.process()

    def process(self):
        with self.lock:
            if not self.enabled:
                return
            try:
                if self.storage_uncertain:
                    self.unavailable('SD_STATE_UNCERTAIN_RESTART_AND_VERIFY')
                    return
                self.tick()
                audit_identity = (self.detection['state'], self.detection['maintenance_alarm'])
                if audit_identity != self.audited_detection:
                    try:
                        self.service.store.diagnostic('PRESSURE_RETENTION_STATE', self.detection)
                        self.audited_detection = audit_identity
                        self.audit_error = None
                    except (OSError, sqlite3.Error) as failure:
                        self.audit_error = str(failure)
                if self.pending:
                    operation = self.pending.popleft()
                    try:
                        self.execute(operation)
                    except (OSError, sqlite3.Error) as failure:
                        self.storage_uncertain = True
                        self.baseline = None
                        self.abort('SD_STATE_UNCERTAIN_RESTART_AND_VERIFY')
                        self.unavailable('SD_STATE_UNCERTAIN_RESTART_AND_VERIFY')
                        operation.update(state='FAILED_NOT_CONFIRMED', error=str(failure))
                    except (ValueError, KeyError, TypeError) as failure:
                        operation.update(state='FAILED_NOT_CONFIRMED', error=str(failure))
                self.error = None
            except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as failure:
                self.error = str(failure)
                self.abort('WORKER_ERROR')
                self.unavailable('WORKER_ERROR')

    def abort(self, reason):
        if self.job and self.job['state'] == 'COLLECTING':
            self.job.update(state='ABORTED', reason=reason)
            self.job.pop('window', None)

    def unavailable(self, reason):
        self.runtime.clear()
        self.runtime_since = self.low_since = self.recover_since = None
        self.detection = dict(state='UNAVAILABLE', reason=reason, retention_ratio=None,
                              maintenance_alarm=self.alarm, control_authority=False, lifetime_qualified=False)

    def tick(self):
        if not self.enabled:
            return
        now = self.clock()
        if self.job and self.job['state'] == 'COLLECTING':
            if now > self.job['lease_until'] or now > self.job['deadline']:
                self.abort('HEARTBEAT_OR_TASK_EXPIRED')
        snapshot = self.snapshot()
        try:
            sample = self.guard(snapshot)
            if self.job and self.job['state'] == 'COLLECTING':
                if self.job['context'] != self.context() or self.job['binding'] != self.binding(snapshot):
                    raise ValueError('SESSION_OR_MEASUREMENT_CONTEXT_CHANGED')
        except ValueError as failure:
            self.abort(str(failure))
            self.unavailable(str(failure))
            self.previous_identity = self.previous_end = self.previous_time = None
            return
        if self.previous_identity is not None:
            delta = (sample['identity'] - self.previous_identity) & 0xffffffff
            if delta == 0:
                return
            if delta >= 0x80000000 or not 0 < ((sample['end'] - self.previous_end) & 0xffffffff) < 0x80000000:
                self.abort('REORDERED_FRAME')
                self.unavailable('REORDERED_FRAME')
                return
            if sample['time'] - self.previous_time > 1 or sample['time'] <= self.previous_time:
                if self.job and self.job['state'] == 'COLLECTING':
                    self.job['window'] = None
                self.unavailable('FRAME_GAP')
        self.previous_identity, self.previous_end, self.previous_time = sample['identity'], sample['end'], sample['time']
        self.observe(sample, snapshot)
        self.detect(sample, snapshot)

    def stable(self, samples):
        return bool(samples) and cv([item['pressure'] for item in samples]) <= self.config['pressure_cv_max'] and cv([item['rpm'] for item in samples]) <= self.config['rpm_cv_max']

    def observe(self, sample, snapshot):
        job = self.job
        if not job or job['state'] != 'COLLECTING':
            return
        duty = min(self.config['duties_percent'], key=lambda value: abs(sample['duty'] - value))
        if abs(sample['duty'] - duty) > self.config['duty_tolerance_pp'] or str(duty) in job['points']:
            job.update(window=None, phase='WAIT_NEXT_POINT')
            return
        window = job.get('window')
        if not window or window['duty'] != duty or abs(window['actual'] - sample['duty']) > 0.1:
            window = dict(duty=duty, actual=sample['duty'], since=sample['time'], stable_at=None, capture_at=None, samples=[])
            job['window'] = window
        elapsed = sample['time'] - window['since']
        if elapsed > self.config['point_timeout_s']:
            job.update(window=None, phase='POINT_TIMEOUT', reason='No stable fresh window before timeout')
            return
        if elapsed < self.config['settle_s']:
            job['phase'] = 'SETTLING'
            return
        samples = window['samples']
        samples.append(sample)
        if len(samples) > 10000:
            raise ValueError('Sampling capacity exceeded')
        if not self.stable(samples):
            window.update(samples=[], stable_at=None, capture_at=None)
            job['phase'] = 'WAIT_STABLE'
            return
        if window['stable_at'] is None:
            window['stable_at'] = sample['time']
        if window['capture_at'] is None:
            job['phase'] = 'WAIT_STABLE'
            if sample['time'] - window['stable_at'] >= self.config['stable_window_s']:
                window.update(capture_at=sample['time'], samples=[sample])
            return
        job['phase'] = 'CAPTURING'
        if sample['time'] - window['capture_at'] < self.config['capture_window_s'] or len(samples) < self.config['min_fresh_records']:
            return
        job['points'][str(duty)] = dict(duty_percent=duty, actual_pwm_percent=statistics.mean([item['duty'] for item in samples]),
                                       pressure_pa=statistics.mean([item['pressure'] for item in samples]),
                                       rpm=statistics.mean([item['rpm'] for item in samples]),
                                       temperature_C=statistics.mean([item['temperature'] for item in samples]),
                                       pressure_cv=cv([item['pressure'] for item in samples]), rpm_cv=cv([item['rpm'] for item in samples]),
                                       records=len(samples), duration_s=sample['time'] - samples[0]['time'],
                                       first_frame=samples[0]['identity'], last_frame=samples[-1]['identity'])
        job.update(window=None, phase='POINT_COMPLETE')
        if len(job['points']) == len(self.config['duties_percent']):
            self.finish()

    def finish(self):
        if not self.job or self.job['state'] != 'COLLECTING' or not self.job['points']:
            raise ValueError('At least one completed point required')
        self.job.update(state='CANDIDATE_READY', phase='CANDIDATE_READY', window=None)
        self.job['candidate'] = dict(schema=1, id=self.job['id'], binding=self.job['binding'],
                                     config=copy.deepcopy(self.config), points=copy.deepcopy(self.job['points']),
                                     operator=self.job['operator'], healthy_confirmed=True, source='LIVE_FRM1_PASSIVE',
                                     created_unix_s=time.time())
        self.job['candidate_sha256'] = digest(self.job['candidate'])

    def reference(self, duty):
        points = self.baseline['points']
        for key, point in points.items():
            if abs(duty - int(key)) <= self.config['duty_tolerance_pp']:
                return point['pressure_pa'], point['rpm']
        low, high = int(math.floor(duty / 10) * 10), int(math.ceil(duty / 10) * 10)
        if low == high or str(low) not in points or str(high) not in points:
            raise ValueError('UNCALIBRATED_BIN_NO_GAP_INTERPOLATION')
        fraction = (duty - low) / (high - low)
        return tuple(points[str(low)][key] * (1 - fraction) + points[str(high)][key] * fraction for key in ('pressure_pa', 'rpm'))

    def detect(self, sample, snapshot):
        if not self.baseline:
            self.unavailable('NO_BASELINE')
            return
        if self.baseline['binding'] != self.binding(snapshot):
            self.unavailable('BASELINE_CONTEXT_MISMATCH')
            return
        limits = self.baseline['config']
        if not limits['temperature_min_C'] <= sample['temperature'] <= limits['temperature_max_C']:
            self.unavailable('BASELINE_TEMPERATURE_MISMATCH')
            return
        try:
            pressure, rpm = self.reference(sample['duty'])
        except ValueError as failure:
            self.unavailable(str(failure))
            return
        if self.runtime_since is None or self.runtime_duty is None or abs(self.runtime_duty - sample['duty']) > 0.1:
            self.runtime.clear()
            self.runtime_since = sample['time']
            self.runtime_duty = sample['duty']
            self.low_since = self.recover_since = None
        if sample['time'] - self.runtime_since < self.config['settle_s']:
            self.detection.update(state='SETTLING', retention_ratio=None)
            return
        self.runtime.append(sample)
        while self.runtime and sample['time'] - self.runtime[0]['time'] > self.config['stable_window_s'] + 1:
            self.runtime.popleft()
        if not self.stable(self.runtime) or sample['time'] - self.runtime[0]['time'] < self.config['stable_window_s']:
            self.low_since = self.recover_since = None
            self.detection.update(state='WAIT_STABLE', retention_ratio=None)
            return
        ratio = statistics.mean([item['pressure'] for item in self.runtime]) / pressure
        if ratio <= 0.7:
            self.low_since = sample['time'] if self.low_since is None else self.low_since
            self.recover_since = None
            if sample['time'] - self.low_since >= self.config['alarm_hold_s']:
                self.alarm = True
        elif ratio >= self.config['retention_recover_ratio']:
            self.recover_since = sample['time'] if self.recover_since is None else self.recover_since
            self.low_since = None
            if sample['time'] - self.recover_since >= self.config['recover_hold_s']:
                self.alarm = False
        else:
            self.low_since = self.recover_since = None
        self.detection = dict(state='MAINTENANCE' if self.alarm else 'COMPARABLE', retention_ratio=ratio,
                              maintenance_alarm=self.alarm, reference_pressure_pa=pressure, reference_rpm=rpm,
                              current_rpm=sample['rpm'], control_authority=False, lifetime_qualified=False,
                              threshold_basis='USER_SELECTED_70_PERCENT_NOT_RUL')

    def read(self, route):
        with self.lock:
            if route == '/state':
                detection = copy.deepcopy(self.detection)
                live = dict(eligible=False, reason='NOT_COMMISSIONED')
                if self.enabled:
                    try:
                        snapshot = self.snapshot()
                        live = dict(self.guard(snapshot), eligible=True)
                        if self.baseline and self.baseline['binding'] != self.binding(snapshot):
                            detection.update(state='UNAVAILABLE', reason='BASELINE_CONTEXT_MISMATCH', retention_ratio=None)
                    except ValueError as failure:
                        live = dict(eligible=False, reason=str(failure))
                        detection.update(state='UNAVAILABLE', reason=str(failure), retention_ratio=None)
                return dict(enabled=self.enabled, context=self.context(), revision=self.revision, config=self.config,
                            persistence=self.persistence, profile=self.profile, active_sweep_available=False,
                            storage=dict(medium='sd', configured=bool(self.repository), physical_media_verified=False),
                            job=self.public_job(), baseline=self.baseline, baseline_sha256=digest(self.baseline) if self.baseline else None,
                            detection=detection, live=live, error=self.error,
                            storage_uncertain=self.storage_uncertain, audit_error=self.audit_error, pending=[item['id'] for item in self.pending])
            if route == '/config':
                return dict(config=self.config, revision=self.revision, persistence=self.persistence)
            if route == '/baselines/active':
                return dict(baseline=self.baseline, sha256=digest(self.baseline) if self.baseline else None)
            if route.startswith('/jobs/') and self.job and route == '/jobs/' + self.job['id']:
                return self.public_job()
            if route.startswith('/operations/'):
                return {key: copy.deepcopy(value) for key, value in self.operations[route.split('/')[-1]].items() if key != 'preview'}
            raise KeyError('not_found')

    def public_job(self):
        return {key: copy.deepcopy(value) for key, value in self.job.items() if key != 'window'} if self.job else None

    def write(self, route, request):
        with self.lock:
            if not self.enabled:
                raise ValueError('PRESSURE_PROFILE_AND_SD_NOT_COMMISSIONED')
            if self.storage_uncertain:
                raise ValueError('SD_STATE_UNCERTAIN_RESTART_AND_VERIFY')
            if not re.fullmatch('[0-9a-f]{32}', request.get('request_id', '') if type(request.get('request_id')) is str else ''):
                raise ValueError('32 hex request_id required')
            key = request['request_id']
            fingerprint = digest(dict(route=route, request=request))
            if key in self.requests:
                previous = self.requests[key]
                if previous[0] != fingerprint:
                    raise ValueError('IDEMPOTENCY_CONFLICT')
                return copy.deepcopy(previous[1])
            if len(self.requests) >= 2048:
                raise ValueError('SESSION_REQUEST_LIMIT_RESTART_AND_REVIEW')
            now = self.clock()
            if route.endswith('/preview') or route == '/baselines/preview-save':
                required = ['request_id', 'expected_revision', 'context']
                required += ['config', 'persistence'] if route == '/config/preview' else ['operator', 'healthy_confirmed', 'mode'] if route == '/jobs/preview' else ['candidate_sha256', 'expected_storage_medium']
                fields(request, required)
                self.check_context(request)
                if self.pending or self.job and self.job['state'] == 'COLLECTING':
                    raise ValueError('BUSY')
                if route == '/config/preview':
                    self.validate_config(request['config'])
                    if request['persistence'] not in ('runtime_only', 'sd'):
                        raise ValueError('Only runtime or SD persistence supported')
                elif route == '/jobs/preview':
                    self.guard(self.snapshot())
                    if request['healthy_confirmed'] is not True or request['mode'] != 'passive':
                        raise ValueError('Explicit healthy confirmation and passive mode required')
                    if type(request['operator']) is not str or not 1 <= len(request['operator'].strip()) <= 80:
                        raise ValueError('Operator identity required')
                elif route == '/baselines/preview-save':
                    self.save_guard(request['candidate_sha256'])
                    if request['expected_storage_medium'] != 'sd':
                        raise ValueError('Only SD storage supported')
                else:
                    raise ValueError('Unknown preview')
                result = dict(state='PREVIEW_NOT_APPLIED', nonce=uuid.uuid4().hex, expires_in_s=30,
                              preview_id=key, payload_sha256=digest(request), route=route)
                self.previews[key] = dict(request=copy.deepcopy(request), route=route, result=result, expires=now + 30)
                while len(self.previews) > 64:
                    self.previews.popitem(last=False)
            elif route in ('/config/commit', '/jobs/start', '/baselines/commit-save'):
                fields(request, ('request_id', 'preview_id', 'nonce'))
                preview = self.previews[request['preview_id']]
                expected = {'/config/commit': '/config/preview', '/jobs/start': '/jobs/preview', '/baselines/commit-save': '/baselines/preview-save'}[route]
                if preview['route'] != expected or preview['result']['nonce'] != request['nonce'] or now > preview['expires'] or preview.get('used'):
                    raise ValueError('Expired, consumed or mismatched preview')
                self.check_context(preview['request'])
                if self.pending:
                    raise ValueError('BUSY')
                if route in ('/config/commit', '/jobs/start') and self.job and self.job['state'] == 'COLLECTING':
                    raise ValueError('BUSY_COLLECTING')
                result = dict(id=uuid.uuid4().hex, state='QUEUED_NOT_APPLIED', request_id=key)
                operation = dict(result, route=route, preview=copy.deepcopy(preview))
                self.operations[result['id']] = operation
                self.pending.append(operation)
                preview['used'] = True
                while len(self.operations) > 64:
                    self.operations.popitem(last=False)
            elif self.job and route.startswith('/jobs/' + self.job['id'] + '/'):
                fields(request, ('request_id', 'expected_revision', 'context'))
                self.check_context(request)
                if self.job['context'] != self.context() or self.job['state'] != 'COLLECTING':
                    raise ValueError('Job no longer collecting')
                if route.endswith('/cancel'):
                    self.abort('USER_CANCELLED')
                elif route.endswith('/heartbeat'):
                    if now > self.job['lease_until'] or now > self.job['deadline']:
                        self.abort('HEARTBEAT_OR_TASK_EXPIRED')
                        raise ValueError('Expired job cannot be revived')
                    self.job['lease_until'] = now + 10
                elif route.endswith('/finish'):
                    self.guard(self.snapshot())
                    self.finish()
                else:
                    raise ValueError('Unknown job action')
                result = self.public_job()
            else:
                raise ValueError('Unknown pressure action')
            self.requests[key] = (fingerprint, copy.deepcopy(result))
            return copy.deepcopy(result)

    def check_context(self, request):
        if type(request['expected_revision']) is not int or request['expected_revision'] != self.revision or request['context'] != self.context():
            raise ValueError('STALE_REVISION_OR_SESSION')

    def save_guard(self, checksum):
        snapshot = self.snapshot()
        self.guard(snapshot)
        if not self.job or self.job['state'] != 'CANDIDATE_READY' or checksum != self.job['candidate_sha256']:
            raise ValueError('Candidate unavailable or changed')
        if self.job['context'] != self.context() or self.job['binding'] != self.binding(snapshot):
            raise ValueError('Candidate context changed')
        self.validate_baseline(self.job['candidate'])

    def execute(self, operation):
        preview = operation['preview']
        request = preview['request']
        if self.clock() > preview['expires']:
            raise ValueError('Queued preview expired')
        self.check_context(request)
        self.service.store.diagnostic('PRESSURE_OPERATION_INTENT', dict(operation_id=operation['id'], route=operation['route'],
                                     payload_sha256=digest(request), context=self.context()))
        if operation['route'] == '/config/commit':
            configuration = self.validate_config(request['config'])
            if request['persistence'] == 'sd':
                self.repository.save('config', dict(profile_sha256=digest(self.profile), config=configuration),
                                     lambda: self.check_context(request))
            self.config = configuration
            self.persistence = request['persistence']
            self.revision += 1
            self.unavailable('CONFIG_CHANGED')
            if self.job:
                self.job = None
            operation.update(state='APPLIED_CONFIG_NOT_PWM', revision=self.revision)
        elif operation['route'] == '/jobs/start':
            snapshot = self.snapshot()
            self.guard(snapshot)
            self.job = dict(id=uuid.uuid4().hex, state='COLLECTING', phase='WAIT_DUTY', context=self.context(),
                            binding=self.binding(snapshot), points={}, operator=request['operator'],
                            lease_until=self.clock() + 10, deadline=self.clock() + 1800, window=None)
            operation.update(state='STARTED_PASSIVE_NO_PWM', job_id=self.job['id'])
        else:
            self.save_guard(request['candidate_sha256'])
            candidate = copy.deepcopy(self.job['candidate'])
            checksum = self.repository.save('baseline', candidate, lambda: self.save_guard(request['candidate_sha256']))
            self.baseline = candidate
            self.unavailable('BASELINE_CHANGED')
            operation.update(state='SAVED_VERIFIED_AND_ACTIVE', sha256=checksum, storage_medium='sd')
