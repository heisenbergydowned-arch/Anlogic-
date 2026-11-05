import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid

from cabinet.baseline import BaselineStore, Learner, digest
from cabinet.learning_rpc import LearningRPC, request
from cabinet.learning_web import WebLearningControl, strict_json, utc_text
from test_baseline import WORDS, config, frame, status


class FakeClock:
    synchronized = True

    def trusted(self):
        return self.synchronized


class WebHarness:
    def __init__(self, directory):
        self.path = Path(directory) / 'baseline.sqlite'
        self.store = BaselineStore(self.path)
        self.learner = Learner(self.store, config())
        self.clock = FakeClock()
        self.now, self.wall, self.identity = 1.0, 1792000000.0, 0
        self.web = WebLearningControl(self.learner, self.clock, lambda: self.wall)
        self.observe()

    def observe(self, status_modify=None, frame_modify=None, session=123):
        self.now += 0.5
        self.wall += 0.5
        self.identity += 1
        current = status(self.now)
        if status_modify:
            status_modify(current)
        self.learner.observe(frame(self.identity, self.now, frame_modify), current, WORDS, session, self.now)
        self.web.update(current, session, self.now)

    def envelope(self, operation='start', actor='operator-a', **payload):
        if operation == 'start':
            payload.setdefault('healthy_confirmed', True)
        if operation in ('start', 'commit', 'rollback'):
            payload.setdefault('expected_baseline_id', self.web.active_id())
        return {'schema': 'cabinet-learning-command-v1', 'device_id': 'test-device',
                'request_id': str(uuid.uuid4()), 'session_id': self.web.session_id, 'operation': operation,
                'issued_at': utc_text(self.wall), 'expires_at': utc_text(self.wall + 30),
                'actor': {'subject_id': actor, 'audit_id': str(uuid.uuid4()),
                          'permissions': ['learning.' + operation]},
                'expected_contract': self.web.contract(), 'payload': payload}

    def execute(self, envelope):
        return self.web.execute(envelope, self.now)

    def candidate(self):
        result = self.execute(self.envelope())
        if not result['ok']:
            raise AssertionError(result)
        for _ in range(20):
            self.observe()
            if self.learner.state == 'PENDING_CONFIRM':
                return self.learner.job_id, digest(self.learner.candidate)
        raise AssertionError(self.learner.snapshot())

    def commit(self):
        job_id, checksum = self.candidate()
        result = self.execute(self.envelope('commit', job_id=job_id, candidate_hash=checksum))
        if not result['ok']:
            raise AssertionError(result)
        self.observe()
        return result['baseline_id']


class WebLearningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.harness = WebHarness(self.directory.name)

    def tearDown(self):
        self.harness.store.close()
        self.directory.cleanup()

    def test_full_start_candidate_commit_history(self):
        harness = self.harness
        identity = harness.commit()
        current = harness.web.snapshot(harness.now)
        self.assertEqual(current['job']['state'], 'COMMITTED')
        self.assertEqual(current['baseline']['active_id'], identity)
        self.assertTrue(current['baseline']['observation_only'])
        self.assertEqual(current['evidence']['level'], 0)
        self.assertEqual(harness.web.history()['baselines'][0]['id'], identity)

    def test_second_job_does_not_inherit_old_sample_count(self):
        harness = self.harness
        harness.commit()
        self.assertTrue(harness.execute(harness.envelope())['ok'])
        self.assertEqual(harness.learner.snapshot()['samples'], 0)
        self.assertEqual(harness.web.snapshot(harness.now)['job']['samples'], 0)
        self.assertGreater(harness.web.snapshot(harness.now)['baseline']['samples'], 0)

    def test_replay_exact_result_not_new_job(self):
        harness = self.harness
        envelope = harness.envelope()
        original = harness.execute(envelope)
        harness.wall += 100
        self.assertEqual(harness.execute(envelope), original)
        self.assertEqual(harness.learner.job_id, original['job_id'])

    def test_changed_request_content_is_rejected(self):
        harness = self.harness
        envelope = harness.envelope()
        harness.execute(envelope)
        envelope['actor']['audit_id'] = 'different-audit'
        self.assertEqual(harness.execute(envelope)['reason'], 'REQUEST_ID_REUSED')

    def test_rejected_request_never_becomes_executable(self):
        harness = self.harness
        harness.clock.synchronized = False
        envelope = harness.envelope()
        original = harness.execute(envelope)
        harness.clock.synchronized = True
        self.assertEqual(harness.execute(envelope), original)
        self.assertIsNone(harness.learner.job_id)

    def test_busy_second_operator_cannot_start(self):
        harness = self.harness
        self.assertTrue(harness.execute(harness.envelope())['ok'])
        self.assertEqual(harness.execute(harness.envelope(actor='operator-b'))['reason'], 'BUSY')

    def test_cancel_owner_required(self):
        harness = self.harness
        result = harness.execute(harness.envelope())
        envelope = harness.envelope('cancel', actor='operator-b', job_id=result['job_id'])
        self.assertEqual(harness.execute(envelope)['reason'], 'FORBIDDEN')
        envelope['request_id'] = str(uuid.uuid4())
        envelope['actor']['permissions'].append('learning.takeover')
        self.assertTrue(harness.execute(envelope)['ok'])

    def test_cancel_is_not_blocked_by_sensor_health(self):
        harness = self.harness
        result = harness.execute(harness.envelope())
        harness.learner.last_valid = False
        harness.web.status['active'] = ['OC_HARD']
        self.assertTrue(harness.execute(harness.envelope('cancel', job_id=result['job_id']))['ok'])

    def test_cancel_after_automatic_abort_returns_real_terminal_state(self):
        harness = self.harness
        result = harness.execute(harness.envelope())
        harness.observe(status_modify=lambda value: value.update(active=['OC_HARD']))
        self.assertEqual(harness.execute(harness.envelope('cancel', job_id=result['job_id']))['reason'], 'JOB_MISMATCH')
        self.assertEqual(harness.web.snapshot(harness.now)['job']['state'], 'ABORTED')

    def test_commit_explicit_job_checked(self):
        harness = self.harness
        _, checksum = harness.candidate()
        envelope = harness.envelope('commit', job_id=str(uuid.uuid4()), candidate_hash=checksum)
        self.assertEqual(harness.execute(envelope)['reason'], 'JOB_MISMATCH')
        self.assertIsNone(harness.web.active_id())

    def test_legacy_commit_checks_supplied_job(self):
        harness = self.harness
        _, checksum = harness.candidate()
        result = harness.learner.command(dict(operation='commit', request_id=str(uuid.uuid4()),
                                             job_id=str(uuid.uuid4()), candidate_hash=checksum), harness.now)
        self.assertEqual(result['reason'], 'JOB_MISMATCH')

    def test_commit_owner_required(self):
        harness = self.harness
        job_id, checksum = harness.candidate()
        result = harness.execute(harness.envelope('commit', actor='operator-b', job_id=job_id, candidate_hash=checksum))
        self.assertEqual(result['reason'], 'FORBIDDEN')

    def test_hash_mismatch(self):
        harness = self.harness
        job_id, _ = harness.candidate()
        result = harness.execute(harness.envelope('commit', job_id=job_id, candidate_hash='0' * 64))
        self.assertEqual(result['reason'], 'CANDIDATE_HASH_MISMATCH')

    def test_active_compare_and_swap(self):
        harness = self.harness
        harness.commit()
        self.assertEqual(harness.execute(harness.envelope(expected_baseline_id=None))['reason'], 'ACTIVE_BASELINE_CHANGED')

    def test_rollback_compatible_and_permission_checked(self):
        harness = self.harness
        original = harness.commit()
        second = harness.commit()
        self.assertNotEqual(second, original)
        envelope = harness.envelope('rollback', baseline_id=original)
        envelope['actor']['permissions'] = ['learning.start']
        self.assertEqual(harness.execute(envelope)['reason'], 'FORBIDDEN')
        self.assertTrue(harness.execute(harness.envelope('rollback', baseline_id=original))['ok'])
        self.assertEqual(harness.web.active_id(), original)

    def test_confirmation_deadline_checked_inside_queue(self):
        harness = self.harness
        job_id, checksum = harness.candidate()
        harness.learner.pending_since = harness.now - harness.learner.config['confirm_seconds']
        self.assertEqual(harness.execute(harness.envelope('commit', job_id=job_id, candidate_hash=checksum))['reason'], 'CONFIRM_TIMEOUT')
        self.assertEqual(harness.learner.state, 'TIMEOUT')

    def test_expired_command(self):
        harness = self.harness
        envelope = harness.envelope()
        envelope.update(issued_at=utc_text(harness.wall - 31), expires_at=utc_text(harness.wall - 1))
        result = harness.execute(envelope)
        self.assertEqual(result['command_state'], 'EXPIRED')
        self.assertIsNone(harness.learner.job_id)

    def test_future_command(self):
        harness = self.harness
        envelope = harness.envelope()
        envelope.update(issued_at=utc_text(harness.wall + 10), expires_at=utc_text(harness.wall + 30))
        self.assertEqual(harness.execute(envelope)['reason'], 'COMMAND_FROM_FUTURE')

    def test_untrusted_clock(self):
        harness = self.harness
        harness.clock.synchronized = False
        self.assertEqual(harness.execute(harness.envelope())['reason'], 'CLOCK_UNTRUSTED')
        self.assertFalse(harness.web.snapshot(harness.now)['can_start'])

    def test_clock_step_blocks_mutation(self):
        harness = self.harness
        harness.wall += 120
        harness.observe()
        self.assertEqual(harness.execute(harness.envelope())['reason'], 'CLOCK_UNTRUSTED')

    def test_status_and_frame_freshness_independent(self):
        harness = self.harness
        harness.learner.qualified_at = harness.now - 2
        self.assertEqual(harness.execute(harness.envelope())['reason'], 'NO_FRESH_FRAME')
        harness.learner.qualified_at = harness.now
        harness.web.observed_at = harness.now - 2
        harness.web.reported_at = harness.wall - 2
        self.assertEqual(harness.execute(harness.envelope())['reason'], 'STATUS_STALE')

    def test_old_queued_frame_age_includes_pl_time(self):
        harness = self.harness
        harness.web.status['uptime_ms'] += 1001
        current = harness.web.snapshot(harness.now)
        self.assertEqual(current['qualification']['frame_age_ms'], 1001)
        self.assertFalse(current['can_start'])
        self.assertEqual(harness.execute(harness.envelope())['reason'], 'NO_FRESH_FRAME')

    def test_mode_two_does_not_reuse_mode_one_baseline(self):
        harness = self.harness
        harness.commit()
        harness.learner.config['contract']['sample_mode_id'] = 2
        harness.observe(frame_modify=lambda header, values: header.__setitem__(13, (12 << 16) | 12800) or header.__setitem__(18, 2))
        current = harness.web.snapshot(harness.now)
        self.assertEqual(current['contract']['sample_mode_id'], 2)
        self.assertFalse(current['baseline']['compatible'])
        self.assertEqual(current['evidence']['state'], 'VERSION_MISMATCH')

    def test_start_cannot_cover_existing_deviation(self):
        harness = self.harness
        harness.commit()
        harness.observe(frame_modify=lambda header, values: values.__setitem__(0, 1.0))
        self.assertEqual(harness.execute(harness.envelope())['reason'], 'EXISTING_BASELINE_DEVIATION')

    def test_unconfirmed_offline_candidate_times_out_without_activation(self):
        harness = self.harness
        original = harness.commit()
        harness.candidate()
        for _ in range(12):
            harness.observe()
        self.assertEqual(harness.learner.state, 'TIMEOUT')
        self.assertEqual(harness.web.active_id(), original)
        self.assertIsNone(harness.learner.candidate)

    def test_device_session_contract_mismatch(self):
        harness = self.harness
        for key, value, reason in (('device_id', 'other-device', 'DEVICE_MISMATCH'),
                                   ('session_id', str(uuid.uuid4()), 'SESSION_MISMATCH'),
                                   ('expected_contract', dict(harness.web.contract(), signature='0' * 64), 'CONTRACT_MISMATCH')):
            envelope = harness.envelope()
            envelope[key] = value
            self.assertEqual(harness.execute(envelope)['reason'], reason)

    def test_new_external_session_on_collector_and_pl_restart(self):
        harness = self.harness
        original = harness.web.session_id
        harness.observe(session=124)
        self.assertNotEqual(original, harness.web.session_id)
        restarted = WebLearningControl(harness.learner, harness.clock, lambda: harness.wall)
        self.assertNotEqual(harness.web.session_id, restarted.session_id)

    def test_restart_replay_is_history_not_new_task(self):
        harness = self.harness
        envelope = harness.envelope()
        original = harness.execute(envelope)
        harness.store.close()
        harness.store = BaselineStore(harness.path)
        harness.learner = Learner(harness.store, config())
        harness.web = WebLearningControl(harness.learner, harness.clock, lambda: harness.wall)
        harness.observe()
        self.assertEqual(harness.execute(envelope), original)
        self.assertEqual(harness.learner.state, 'IDLE')
        self.assertIsNone(harness.learner.job_id)

    def test_interrupted_intent_never_reexecuted(self):
        harness = self.harness
        envelope = harness.envelope()
        with harness.store.connection:
            harness.store.connection.execute('INSERT INTO web_requests VALUES(?,?,?,NULL)',
                                             (envelope['request_id'], digest(envelope), json.dumps(envelope)))
        self.assertEqual(harness.execute(envelope)['command_state'], 'UNKNOWN')
        self.assertIsNone(harness.learner.job_id)

    def test_core_exception_keeps_unknown_intent(self):
        harness = self.harness
        envelope = harness.envelope()
        original = harness.learner.command

        def interrupted(payload, now, context_guard=None):
            original(payload, now, context_guard=context_guard)
            raise OSError('simulated response failure')

        harness.learner.command = interrupted
        with self.assertRaises(OSError):
            harness.execute(envelope)
        harness.learner.command = original
        self.assertEqual(harness.execute(envelope)['command_state'], 'UNKNOWN')
        self.assertIsNotNone(harness.learner.job_id)

    def test_request_journal_full_fails_closed(self):
        harness = self.harness
        with harness.store.connection:
            harness.store.connection.executemany('INSERT INTO web_requests VALUES(?,?,?,NULL)',
                                                 [(str(uuid.uuid4()), 'unused', '{}') for _ in range(1024)])
        self.assertEqual(harness.execute(harness.envelope())['reason'], 'REQUEST_JOURNAL_FULL')
        self.assertIsNone(harness.learner.job_id)

    def test_readonly_status_does_not_refresh_collection_timestamp(self):
        harness = self.harness
        original = harness.web.snapshot(harness.now)
        later = harness.web.snapshot(harness.now + 4)
        self.assertEqual(original['reported_at'], later['reported_at'])
        self.assertEqual(original['status_sequence'], later['status_sequence'])
        self.assertFalse(later['available'])
        self.assertFalse(later['can_start'])
        self.assertEqual(later['evidence']['state'], 'STALE')

    def test_unknown_types_fields_and_bypasses_rejected(self):
        harness = self.harness
        changes = [lambda item: item.update(force=True),
                   lambda item: item['payload'].update(qualified=True),
                   lambda item: item['payload'].update(pwm=100),
                   lambda item: item['payload'].update(healthy_confirmed=1),
                   lambda item: item['payload'].pop('expected_baseline_id'),
                   lambda item: item['expected_contract'].update(calibration_id=True),
                   lambda item: item['expected_contract'].update(signature='A' * 64),
                   lambda item: item['actor'].update(permissions=['root.shell']),
                   lambda item: item['actor'].update(permissions='learning.start'),
                   lambda item: item['actor'].update(subject_id=[]),
                   lambda item: item.update(expires_at=utc_text(harness.wall + 31)),
                   lambda item: item.update(operation=[]),
                   lambda item: item.update(payload=[])]
        for change in changes:
            with self.subTest(change=change):
                envelope = harness.envelope()
                change(envelope)
                self.assertFalse(harness.execute(envelope)['ok'])
        self.assertIsNone(harness.learner.job_id)

    def test_strict_json_duplicate_nan_overflow_size(self):
        for payload in ('{"operation":"start","operation":"status"}', '{"value":NaN}',
                        '{"value":Infinity}', '{"value":1e999}', '"' + '中' * 2000 + '"'):
            with self.subTest(payload=payload[:50]), self.assertRaises(ValueError):
                strict_json(payload)

    def test_unqualified_inputs_never_unlocked(self):
        harness = self.harness
        harness.learner.config['contract']['calibration_id'] = 0
        self.assertEqual(harness.execute(harness.envelope())['reason'], 'CALIBRATION_UNQUALIFIED')

    def test_query_whitelist(self):
        harness = self.harness
        self.assertTrue(harness.web.query(dict(operation='status', view='web'), harness.now)['ok'])
        self.assertFalse(harness.web.query(dict(operation='start', view='web'), harness.now)['ok'])
        self.assertFalse(harness.web.query(dict(operation='status', view='web', force=True), harness.now)['ok'])

    def test_rpc_full_envelope_runs_on_collector_queue(self):
        harness = self.harness
        path = Path(self.directory.name) / 'learning.sock'
        rpc = LearningRPC(path)
        result = {}
        worker = threading.Thread(target=lambda: result.update(request(path, harness.envelope())))
        try:
            worker.start()
            deadline = time.monotonic() + 2
            while worker.is_alive() and time.monotonic() < deadline:
                rpc.poll(harness.learner, harness.now, harness.web)
                time.sleep(0.005)
            worker.join(timeout=1)
            self.assertTrue(result['ok'], result)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        finally:
            rpc.close()

    def test_schema_cannot_fall_back_to_legacy_start(self):
        harness = self.harness
        path = Path(self.directory.name) / 'learning.sock'
        rpc = LearningRPC(path)
        result = {}
        worker = threading.Thread(target=lambda: result.update(request(path, dict(
            schema='wrong-schema', operation='start', request_id=str(uuid.uuid4()), healthy_confirmed=True))))
        try:
            worker.start()
            deadline = time.monotonic() + 2
            while worker.is_alive() and time.monotonic() < deadline:
                rpc.poll(harness.learner, harness.now)
                time.sleep(0.005)
            worker.join(timeout=1)
            self.assertEqual(result['reason'], 'WEB_SERVICE_UNAVAILABLE')
            self.assertIsNone(harness.learner.job_id)
        finally:
            rpc.close()

    def test_web_mode_blocks_legacy_screen_mutations(self):
        harness = self.harness
        path = Path(self.directory.name) / 'learning.sock'
        rpc = LearningRPC(path)
        result = {}
        worker = threading.Thread(target=lambda: result.update(request(path, dict(
            operation='start', request_id=str(uuid.uuid4()), healthy_confirmed=True))))
        try:
            worker.start()
            deadline = time.monotonic() + 2
            while worker.is_alive() and time.monotonic() < deadline:
                rpc.poll(harness.learner, harness.now, harness.web)
                time.sleep(0.005)
            worker.join(timeout=1)
            self.assertEqual(result['reason'], 'LOCAL_MUTATION_DISABLED_USE_WEB')
            self.assertIsNone(harness.learner.job_id)
        finally:
            rpc.close()


if __name__ == '__main__':
    unittest.main()
