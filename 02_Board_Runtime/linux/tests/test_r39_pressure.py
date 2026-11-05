import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cabinet.pressure_calibration import PressureCalibration, PREFIX
from cabinet.pressure_storage import PressureStorage, digest
from cabinet.web import server


class Fixture:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.now = 100.0
        self.sequence = 1
        self.profile = dict(schema=1, device_id='HOST_TEST_ONLY', fan_id='TEST_FAN', installation_id='TEST_DUCT',
                            sensor_id='TEST_SDP810', pickup='TEST_POSITIVE_PRESSURE_NOT_BOARD',
                            pressure_min_valid_pa=2, temperature_min_C=20, temperature_max_C=45)
        profile = self.root / 'profile.json'
        profile.write_text(json.dumps(self.profile))
        self.service = SimpleNamespace(config=dict(device_id='HOST_TEST_ONLY',
            contract=dict(calibration_id=1, feature_config_id=1, sample_mode_id=2),
            pressure_calibration=dict(enabled=True, profile=str(profile), sha256=hashlib.sha256(profile.read_bytes()).hexdigest(),
                                      sd_directory=str(self.root / 'private-sd-test-directory'))),
            collector_session='HOST_SESSION', connection_epoch=1, boot='HOST_BOOT', valid_input=True,
            mock=False, diagnostic_test=False, controller=None,
            store=SimpleNamespace(diagnostic=lambda *arguments: None))
        self.state = dict(link='ONLINE', test=False, status_age_ms=0, frame_age_ms=0,
            frame=dict(frame_id=1, end_ms=100000, quality=0, test=False, mode=3, calibration_id=1,
                       feature_config_id=1, sample_mode_id=2, bitstream_id='202610f7', pressure_source='SDP810-500Pa',
                       pressure_count=25, fg_count=2, values=dict(pressure=0.1, rpm=3000, temp=30)),
            status=dict(configured=True, config_id=1, mode='RUN', active=[], latched=[], applied_pwm_counts=2000,
                        measured_rpm=3000, fan_action='PI', hard_inhibit=False, temp_age_ms=0,
                        temp_raw_1_16_C=480, input_validity=dict(rpm=True, temperature=True, pressure=True)))
        self.service.public_state = lambda: copy.deepcopy(self.state)
        self.calibration = PressureCalibration(self.service, lambda: self.now)
        self.service.pressure = self.calibration

    def common(self):
        return dict(request_id=uuid.uuid4().hex, expected_revision=self.calibration.revision, context=self.calibration.context())

    def preview(self, kind, **values):
        route = {'config': '/config/preview', 'job': '/jobs/preview', 'save': '/baselines/preview-save'}[kind]
        return self.calibration.write(route, dict(self.common(), **values))

    def commit(self, kind, preview):
        route = {'config': '/config/commit', 'job': '/jobs/start', 'save': '/baselines/commit-save'}[kind]
        request = dict(request_id=uuid.uuid4().hex, preview_id=preview['preview_id'], nonce=preview['nonce'])
        result = self.calibration.write(route, request)
        self.calibration.process()
        return self.calibration.read('/operations/' + result['id'])

    def start_job(self, duties=None):
        if duties:
            configuration = dict(self.calibration.config, duties_percent=duties)
            self.commit('config', self.preview('config', config=configuration, persistence='runtime_only'))
        return self.commit('job', self.preview('job', mode='passive', healthy_confirmed=True, operator='HOST_TEST_OPERATOR'))

    def sample(self, pressure=100, duty=50, step=0.25, heartbeat=True):
        self.now += step
        self.sequence += 1
        self.state['frame'].update(frame_id=self.sequence, end_ms=int(self.now * 1000))
        self.state['frame']['values']['pressure'] = pressure / 1000
        self.state['status']['applied_pwm_counts'] = int(duty * 40)
        job = self.calibration.job
        if heartbeat and job and job['state'] == 'COLLECTING':
            self.calibration.write('/jobs/' + job['id'] + '/heartbeat', self.common())
        self.calibration.process()

    def collect(self, duties=None):
        self.start_job(duties or [50])
        for unused in range(55):
            self.sample()
        return self.calibration.job

    def save(self):
        job = self.calibration.job
        return self.commit('save', self.preview('save', candidate_sha256=job['candidate_sha256'], expected_storage_medium='sd'))


class PressureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(self.temporary.name)
        self.calibration = self.fixture.calibration
        self.addCleanup(lambda: self.fixture.calibration.close())

    def test_disabled_default_creates_no_storage_or_worker(self):
        service = SimpleNamespace(config={}, collector_session='test', connection_epoch=0, boot=None)
        disabled = PressureCalibration(service)
        self.assertFalse(disabled.read('/state')['enabled'])
        self.assertIsNone(disabled.thread)
        with self.assertRaises(ValueError):
            disabled.write('/jobs/preview', dict(request_id=uuid.uuid4().hex))
        disabled.close()

    def test_profile_hash_identity_and_units_cannot_be_invented(self):
        for key, value in [('sha256', '0' * 64), ('enabled', 1), ('unknown', True)]:
            service = copy.copy(self.fixture.service)
            service.config = copy.deepcopy(service.config)
            service.config['pressure_calibration'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                PressureCalibration(service)
        self.fixture.state['frame'].update(sample_mode_id=1, pressure_source='AD7606-CH2')
        with self.assertRaises(ValueError):
            self.fixture.start_job()

    def test_config_validation_rejects_active_nonfinite_unknown_and_bad_windows(self):
        for key, value in [('mode', 'active_sweep'), ('settle_s', True), ('stable_window_s', float('nan')),
                           ('pressure_cv_max', 0.06), ('duties_percent', [10, 10]), ('duties_percent', [False]),
                           ('retention_alarm_ratio', 0.6), ('temperature_min_C', 0), ('capture_window_s', 100)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.fixture.preview('config', config=dict(self.calibration.config, **{key: value}), persistence='sd')
        with self.assertRaises(ValueError):
            self.calibration.validate_config(dict(self.calibration.config, clear_protection=True))

    def test_config_commit_does_not_start_job_or_write_pwm(self):
        preview = self.fixture.preview('config', config=self.calibration.config, persistence='sd')
        self.assertIsNone(self.calibration.repository.load('config'))
        result = self.fixture.commit('config', preview)
        self.assertEqual(result['state'], 'APPLIED_CONFIG_NOT_PWM')
        self.assertIsNotNone(self.calibration.repository.load('config'))
        self.assertIsNone(self.calibration.job)
        self.assertIsNone(self.fixture.service.controller)

    def test_preview_revision_context_nonce_and_expiration(self):
        for field in ['collector_session', 'connection_epoch', 'boot_id']:
            request = self.fixture.common()
            request['context'][field] = 'changed'
            with self.assertRaises(ValueError):
                self.calibration.write('/config/preview', dict(request, config=self.calibration.config, persistence='sd'))
        preview = self.fixture.preview('config', config=self.calibration.config, persistence='sd')
        self.fixture.now += 31
        with self.assertRaises(ValueError):
            self.fixture.commit('config', preview)

    def test_queued_expiration_does_not_apply(self):
        preview = self.fixture.preview('config', config=self.calibration.config, persistence='sd')
        receipt = self.calibration.write('/config/commit', dict(request_id=uuid.uuid4().hex, preview_id=preview['preview_id'], nonce=preview['nonce']))
        self.fixture.now += 31
        self.calibration.process()
        self.assertEqual(self.calibration.read('/operations/' + receipt['id'])['state'], 'FAILED_NOT_CONFIRMED')
        self.assertEqual(self.calibration.revision, 0)

    def test_idempotence_conflict_and_consumed_preview(self):
        request = dict(self.fixture.common(), config=self.calibration.config, persistence='runtime_only')
        result = self.calibration.write('/config/preview', request)
        self.assertEqual(self.calibration.write('/config/preview', request), result)
        with self.assertRaises(ValueError):
            self.calibration.write('/config/preview', dict(request, persistence='sd'))
        self.fixture.commit('config', result)
        with self.assertRaises(ValueError):
            self.fixture.commit('config', result)
        self.assertEqual(self.calibration.revision, 1)

    def test_collect_units_stability_and_minimum_fresh_records(self):
        job = self.fixture.collect()
        self.assertEqual(job['state'], 'CANDIDATE_READY')
        point = job['points']['50']
        self.assertEqual(point['pressure_pa'], 100)
        self.assertGreaterEqual(point['records'], 20)
        self.assertGreaterEqual(point['duration_s'], 5)
        self.assertNotEqual(point['first_frame'], point['last_frame'])
        self.assertIsNone(self.calibration.baseline)
        self.assertIsNone(self.fixture.service.controller)

    def test_duplicate_frames_cannot_complete_sampling_or_extend_lease(self):
        self.fixture.start_job([50])
        for unused in range(100):
            self.fixture.now += 0.1
            self.calibration.process()
        self.assertEqual(self.calibration.job['points'], {})
        self.fixture.now += 1
        self.calibration.process()
        self.assertEqual(self.calibration.job['state'], 'ABORTED')
        with self.assertRaises(ValueError):
            self.calibration.write('/jobs/' + self.calibration.job['id'] + '/heartbeat', self.fixture.common())

    def test_duty_change_gap_and_noise_restart_window(self):
        self.fixture.start_job([50, 60])
        for unused in range(35):
            self.fixture.sample()
        self.fixture.sample(duty=60)
        self.assertEqual(self.calibration.job['phase'], 'SETTLING')
        self.fixture.sample(duty=50, step=2)
        self.assertEqual(self.calibration.job['points'], {})
        for index in range(60):
            self.fixture.sample(pressure=50 if index % 2 else 150)
        self.assertEqual(self.calibration.job['points'], {})

    def test_fault_stale_test_zero_negative_and_invalid_process_abort(self):
        changes = [('frame_age_ms', 1001), ('status_age_ms', 1001), ('test', True), ('link', 'OFFLINE')]
        for key, value in changes:
            self.fixture.state[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.fixture.start_job()
            self.fixture.state[key] = False if key == 'test' else 'ONLINE' if key == 'link' else 0
        for pressure in [0, -100, 1]:
            self.fixture.state['frame']['values']['pressure'] = pressure / 1000
            with self.assertRaises(ValueError):
                self.fixture.start_job()
        self.fixture.state['frame']['values']['pressure'] = 0.1
        self.fixture.start_job()
        self.fixture.state['status']['latched'] = ['TEMP_HARD']
        self.fixture.sample()
        self.assertEqual(self.calibration.job['state'], 'ABORTED')

    def test_context_change_aborts_and_old_candidate_cannot_be_saved(self):
        self.fixture.start_job()
        self.fixture.service.boot = 'DIFFERENT_BOOT'
        self.fixture.sample(heartbeat=False)
        self.assertEqual(self.calibration.job['state'], 'ABORTED')
        job = self.fixture.collect()
        self.fixture.service.connection_epoch += 1
        with self.assertRaises(ValueError):
            self.fixture.preview('save', candidate_sha256=job['candidate_sha256'], expected_storage_medium='sd')

    def test_cancel_and_partial_finish_never_fabricate_missing_bins(self):
        self.fixture.collect([50, 60])
        self.assertEqual(self.calibration.job['state'], 'COLLECTING')
        self.calibration.write('/jobs/' + self.calibration.job['id'] + '/finish', self.fixture.common())
        self.assertEqual(set(self.calibration.job['candidate']['points']), {'50'})
        self.fixture.start_job()
        self.calibration.write('/jobs/' + self.calibration.job['id'] + '/cancel', self.fixture.common())
        self.assertEqual(self.calibration.job['state'], 'ABORTED')
        self.assertIsNone(self.calibration.baseline)

    def test_sd_save_verify_restart_and_no_job_resume(self):
        self.fixture.collect()
        result = self.fixture.save()
        self.assertEqual(result['state'], 'SAVED_VERIFIED_AND_ACTIVE')
        self.assertEqual(result['sha256'], digest(self.calibration.baseline))
        original = copy.deepcopy(self.calibration.baseline)
        self.calibration.close()
        self.fixture.calibration = PressureCalibration(self.fixture.service, lambda: self.fixture.now)
        self.assertEqual(self.fixture.calibration.baseline, original)
        self.assertIsNone(self.fixture.calibration.job)

    def test_wrong_medium_and_candidate_hash_cannot_save(self):
        self.fixture.collect()
        for checksum, medium in [('0' * 64, 'sd'), (self.calibration.job['candidate_sha256'], 'flash')]:
            with self.assertRaises(ValueError):
                self.fixture.preview('save', candidate_sha256=checksum, expected_storage_medium=medium)

    def test_failed_save_is_not_active_and_requires_verified_restart(self):
        self.fixture.collect()
        preview = self.fixture.preview('save', candidate_sha256=self.calibration.job['candidate_sha256'], expected_storage_medium='sd')
        with patch.object(self.calibration.repository, 'atomic', side_effect=OSError('full')):
            result = self.fixture.commit('save', preview)
        self.assertEqual(result['state'], 'FAILED_NOT_CONFIRMED')
        self.assertIsNone(self.calibration.baseline)
        self.assertTrue(self.calibration.read('/state')['storage_uncertain'])
        with self.assertRaises(ValueError):
            self.fixture.start_job()

    def test_pl_config_and_live_process_invalidations(self):
        self.fixture.collect()
        self.fixture.save()
        self.fixture.state['status']['config_id'] = 2
        self.fixture.sample()
        self.assertEqual(self.calibration.detection['reason'], 'BASELINE_CONTEXT_MISMATCH')
        for key, value in [('hard_inhibit', True), ('input_validity', dict(rpm=True, temperature=True, pressure=False)),
                           ('temp_age_ms', 1001), ('fan_action', 'BOOST')]:
            previous = self.fixture.state['status'][key]
            self.fixture.state['status'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.calibration.guard(self.fixture.state)
            self.fixture.state['status'][key] = previous

    def test_transition_audit_never_changes_hardware(self):
        with patch.object(self.fixture.service.store, 'diagnostic') as audit:
            self.fixture.collect()
            self.fixture.save()
            for unused in range(60):
                self.fixture.sample(pressure=69)
        self.assertIn('PRESSURE_OPERATION_INTENT', [call.args[0] for call in audit.call_args_list])
        self.assertIn('PRESSURE_RETENTION_STATE', [call.args[0] for call in audit.call_args_list])
        self.assertIsNone(self.fixture.service.controller)

    def test_sd_failure_before_active_switch_preserves_previous_generation(self):
        self.fixture.collect()
        self.fixture.save()
        repository = self.calibration.repository
        previous = repository.load('baseline')
        with self.assertRaises(OSError):
            repository.save('baseline', dict(previous, id='OTHER'), lambda: (_ for unused in ()).throw(OSError('fault injection')))
        self.assertEqual(repository.load('baseline'), previous)
        with patch.object(repository, 'atomic', side_effect=OSError('full')), self.assertRaises(OSError):
            repository.save('baseline', previous, lambda: None)
        self.assertEqual(repository.load('baseline'), previous)

    def test_atomic_corrupt_pointer_symlink_and_owner_lock(self):
        repository = self.calibration.repository
        with self.assertRaises(OSError):
            PressureStorage(str(repository.root))
        (repository.root / 'baseline.active.json').write_text('{}')
        os.chmod(str(repository.root / 'baseline.active.json'), 0o600)
        with self.assertRaises(ValueError):
            repository.load('baseline')
        linked = self.fixture.root / 'link'
        linked.symlink_to(repository.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            PressureStorage(str(linked))
        public = self.fixture.root / 'public'
        public.mkdir(mode=0o755)
        with self.assertRaises(ValueError):
            PressureStorage(str(public))

    def test_tampered_record_rejected_on_readback(self):
        self.fixture.collect()
        self.fixture.save()
        repository = self.calibration.repository
        pointer = repository.read('baseline.active.json')
        record = repository.read(pointer['file'])
        record['payload']['points']['50']['pressure_pa'] = 90
        repository.atomic(pointer['file'], record)
        with self.assertRaises(ValueError):
            repository.load('baseline')

    def test_runtime_70_percent_hold_hysteresis_and_staleness(self):
        self.fixture.collect()
        self.fixture.save()
        for unused in range(60):
            self.fixture.sample(pressure=69)
        self.assertTrue(self.calibration.detection['maintenance_alarm'])
        self.assertAlmostEqual(self.calibration.detection['retention_ratio'], 0.69)
        for unused in range(60):
            self.fixture.sample(pressure=75)
        self.assertTrue(self.calibration.detection['maintenance_alarm'])
        self.fixture.state['frame_age_ms'] = 1001
        state = self.calibration.read('/state')
        self.assertIsNone(state['detection']['retention_ratio'])
        self.assertTrue(state['detection']['maintenance_alarm'])
        self.fixture.state['frame_age_ms'] = 0
        for unused in range(60):
            self.fixture.sample(pressure=85)
        self.assertFalse(self.calibration.detection['maintenance_alarm'])
        self.assertFalse(self.calibration.detection['control_authority'])
        self.assertFalse(self.calibration.detection['lifetime_qualified'])

    def test_reference_interpolation_does_not_cross_holes_or_extrapolate(self):
        self.fixture.collect()
        self.fixture.save()
        point = self.calibration.baseline['points']['50']
        self.calibration.baseline['points']['60'] = dict(point, pressure_pa=120)
        self.assertEqual(self.calibration.reference(55)[0], 110)
        self.calibration.baseline['points']['70'] = dict(point, pressure_pa=140)
        del self.calibration.baseline['points']['60']
        for duty in [5, 55, 65, 100]:
            with self.assertRaises(ValueError):
                self.calibration.reference(duty)

    def test_worker_has_no_controller_commands_and_stops_cleanly(self):
        self.calibration.start()
        self.assertTrue(self.calibration.thread.is_alive())
        self.calibration.close()
        self.assertFalse(self.calibration.thread.is_alive())
        self.assertIsNone(self.fixture.service.controller)

    def test_http_read_control_origin_strict_json_and_202_receipt(self):
        listener = server('127.0.0.1', 0, self.fixture.service, token='READ_TEST_ONLY', control_token='C' * 40)
        worker = threading.Thread(target=listener.serve_forever, daemon=True)
        worker.start()
        try:
            base = 'http://127.0.0.1:' + str(listener.server_port)
            with urlopen(base + '/pressure-calibration', timeout=2) as response:
                html = response.read().decode()
                self.assertIn('70%', html)
                self.assertNotIn('localStorage', html)
            request = dict(self.fixture.common(), config=self.calibration.config, persistence='sd')
            headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer READ_TEST_ONLY', 'X-Cabinet-Control-Token': 'C' * 40}
            for changes, expected in [({'Authorization': ''}, 401), ({'X-Cabinet-Control-Token': ''}, 403), ({'Origin': 'http://evil.test'}, 403)]:
                with self.assertRaises(HTTPError) as failure:
                    urlopen(Request(base + PREFIX + '/config/preview', data=json.dumps(request).encode(), headers=dict(headers, **changes)), timeout=2)
                self.assertEqual(failure.exception.code, expected)
            for raw in [b'{"request_id":"x","request_id":"y"}', b'{"value":NaN}']:
                with self.assertRaises(HTTPError) as failure:
                    urlopen(Request(base + PREFIX + '/config/preview', data=raw, headers=headers), timeout=2)
                self.assertEqual(failure.exception.code, 400)
            with urlopen(Request(base + PREFIX + '/config/preview', data=json.dumps(request).encode(), headers=headers), timeout=2) as response:
                preview = json.load(response)
            commit = dict(request_id=uuid.uuid4().hex, preview_id=preview['preview_id'], nonce=preview['nonce'])
            with urlopen(Request(base + PREFIX + '/config/commit', data=json.dumps(commit).encode(), headers=headers), timeout=2) as response:
                self.assertEqual(response.status, 202)
                receipt = json.load(response)
            self.calibration.process()
            with urlopen(Request(base + PREFIX + '/operations/' + receipt['id'], headers=headers), timeout=2) as response:
                self.assertEqual(json.load(response)['state'], 'APPLIED_CONFIG_NOT_PWM')
        finally:
            listener.shutdown()
            listener.server_close()
            worker.join(2)


if __name__ == '__main__':
    unittest.main()
