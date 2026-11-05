import copy
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from cabinet.local_display import LocalDisplay
from cabinet.policy import Fusion
from cabinet.service import Service
from cabinet.store import EventTracker, Store
from link_cli import pack_feature
from hmi_daily.cabinet.baseline import BaselineStore, DEFAULTS, Learner, digest, validate_config
from hmi_daily.cabinet.learning_rpc import LearningRPC
from test_local_display import CONFIG, WORDS, TrustedClock, healthy_frame, healthy_status


class ConfigurationTests(unittest.TestCase):
    def test_v4_example_contracts_match_and_do_not_enable_learning_or_actuation(self):
        linux = Path(__file__).resolve().parents[1]
        edge = json.loads((linux/'config.v4.example.json').read_text())
        learning = validate_config(json.loads((linux/'hmi_daily/learning_config.v4.example.json').read_text()))
        feature = json.loads((linux/'feature_config.v4.example.json').read_text())
        self.assertEqual(edge['device_id'], learning['device_id'])
        for field in ('feature_config_id', 'sample_mode_id', 'calibration_id'):
            self.assertEqual(edge['contract'][field], learning['contract'][field])
        self.assertEqual(edge['contract']['feature_config_id'], 0x2026f400)
        self.assertEqual(edge['contract']['sample_mode_id'], 2)
        self.assertEqual(edge['contract']['calibration_id'], 0)
        self.assertEqual(learning['installation_id'], '')
        self.assertFalse(learning['advisory_qualified'])
        for subsystem in ('control', 'temperature_loop'):
            self.assertFalse(edge[subsystem]['enabled'])
            self.assertFalse(edge[subsystem]['qualified'])
        self.assertEqual(edge['model']['backend'], 'disabled')
        self.assertFalse(edge['model']['qualified'])
        for field in ('feature_config_id', 'sample_mode_id', 'calibration_id'):
            self.assertEqual(feature[field], edge['contract'][field])
        self.assertIsNone(feature['ppr'])
        self.assertFalse(feature['qualified'])
        with self.assertRaises(ValueError):
            pack_feature(feature)


class LearningSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = copy.deepcopy(DEFAULTS)
        self.config.update(device_id='test-device', installation_id='test-install', stable_seconds=0.1,
            capture_seconds=6, timeout_seconds=20, confirm_seconds=1, min_samples=12, max_gap_seconds=2)
        self.config['contract']['calibration_id'] = 7
        self.store = BaselineStore(self.root/'baselines.sqlite')
        self.addCleanup(self.store.close)
        self.learner = Learner(self.store, self.config)
        self.now, self.identity = 1.0, 0

    def observe(self, amplitude=0, rpm=6000):
        self.now += 0.5
        self.identity += 1
        frame = healthy_frame(self.identity, self.now)
        values = list(frame.values)
        values[0] += amplitude
        values[38] = rpm
        frame = type(frame)(frame.header, tuple(values))
        status = healthy_status(self.now)
        status.update(measured_rpm=rpm, ramped_rpm=rpm, requested_rpm=rpm)
        self.learner.observe(frame, status, WORDS, 'UNIT_REAL_SHAPE_NOT_HARDWARE', self.now)

    def command(self, operation, **payload):
        return self.learner.command(dict(operation=operation, request_id=str(uuid.uuid4()), **payload), self.now)

    def candidate(self):
        self.observe()
        self.assertTrue(self.command('start', healthy_confirmed=True)['ok'])
        for unused in range(30):
            self.observe()
            if self.learner.state == 'PENDING_CONFIRM':
                return
        self.fail(self.learner.snapshot())

    def active(self):
        self.candidate()
        result = self.command('commit', job_id=self.learner.job_id, candidate_hash=digest(self.learner.candidate))
        self.assertTrue(result['ok'], result)
        self.observe()
        return result['baseline_id']

    def test_existing_baseline_deviation_during_relearning_aborts(self):
        previous = self.active()
        self.assertTrue(self.command('start', healthy_confirmed=True)['ok'])
        self.observe(amplitude=0.05)
        self.assertEqual(self.learner.state, 'ABORTED')
        self.assertEqual(self.store.profiles()[0]['id'], previous)
        self.assertEqual(self.store.profiles('CANDIDATE'), [])
        self.assertFalse(self.learner.allowed)

    def test_candidate_cannot_commit_after_new_signal_drifts(self):
        self.candidate()
        candidate_hash = digest(self.learner.candidate)
        self.observe(amplitude=0.05)
        result = self.command('commit', candidate_hash=candidate_hash, job_id=self.learner.job_id)
        self.assertFalse(result['ok'])
        self.assertEqual(self.learner.state, 'ABORTED')
        self.assertEqual(self.store.profiles(), [])

    def test_candidate_cannot_commit_after_operating_rpm_changes(self):
        self.candidate()
        candidate_hash = digest(self.learner.candidate)
        self.observe(rpm=7200)
        self.assertEqual(self.learner.state, 'ABORTED')
        self.assertFalse(self.command('commit', candidate_hash=candidate_hash, job_id=self.learner.job_id)['ok'])

    def test_direct_commit_enforces_confirmation_deadline_without_new_observe(self):
        self.candidate()
        candidate_hash = digest(self.learner.candidate)
        self.now += 1.1
        result = self.command('commit', job_id=self.learner.job_id, candidate_hash=candidate_hash)
        self.assertFalse(result['ok'])
        self.assertEqual(self.learner.state, 'TIMEOUT')
        self.assertEqual(self.store.profiles(), [])

    def test_rejected_normal_model_is_not_a_health_approval_for_learning(self):
        config = copy.deepcopy(CONFIG)
        config.update(device_id='test-device', database=str(self.root/'events.sqlite'))
        config['contract']['calibration_id'] = 7
        learning = self.root/'learning.json'
        learning.write_text(json.dumps(self.config))
        observer = LocalDisplay(config, self.root/'display', learning, self.root/'observer.sqlite', clock_factory=TrustedClock)
        observer.initialize()
        try:
            model = dict(frame_id=1, feature_config_id=1, calibration_id=7, label='normal',
                test=False, formal=True, backend='UNIT_FAKE_ALNPU', diagnostic_state='REJECTED_CONFIDENCE')
            packet = dict(sequence=1, boot='UNIT_STREAM', link='ONLINE', received_at=1.0, reported_at=time.time(),
                status=healthy_status(1), frame=healthy_frame(1, 1), feature_words=WORDS,
                mailbox=dict(queued_frames=0, dropped_frames=0), test=False, model=model,
                model_fresh=True, model_formal=True, model_required=True)
            observer.submit(packet)
            observer.step(observer.queue.get_nowait(), 1.0)
            self.assertEqual(observer.learner.reason, 'MODEL_UNAVAILABLE')
            self.assertFalse(observer.learner.allowed)
        finally:
            if observer.rpc is not None:
                observer.rpc.close()
            observer.clock.close()
            observer.store.close()

    def test_second_baseline_owner_cannot_delete_the_current_candidate(self):
        self.candidate()
        previous = self.learner.candidate['id']
        second = None
        try:
            with self.assertRaises(RuntimeError):
                second = BaselineStore(self.root/'baselines.sqlite')
            self.assertEqual(self.store.profiles('CANDIDATE')[0]['id'], previous)
            self.assertIsNotNone(self.store.connection.execute('SELECT body FROM task').fetchone())
        finally:
            if second is not None:
                second.close()

    def test_full_history_rejects_start_without_disabling_read_or_rollback(self):
        previous = self.active()
        template = self.store.profiles()[0]
        for unused in range(31):
            profile = dict(template, id=str(uuid.uuid4()))
            with self.store.connection:
                self.store.connection.execute('INSERT INTO profiles VALUES(?,?,?,?)',
                    (profile['id'], 'ARCHIVED', json.dumps(profile), digest(profile)))
        self.assertTrue(self.store.history_full())
        self.assertFalse(self.learner.snapshot()['can_start'])
        result = self.command('start', healthy_confirmed=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'PROFILE_HISTORY_FULL')
        self.assertEqual(self.store.profiles()[0]['id'], previous)
        self.assertEqual(len(self.store.profiles('ARCHIVED')), 31)


class RpcOwnershipTests(unittest.TestCase):
    def test_second_listener_cannot_replace_an_existing_learning_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary)/'learning.sock'
            first = LearningRPC(file)
            second = None
            try:
                try:
                    second = LearningRPC(file)
                except (RuntimeError, FileExistsError):
                    pass
                self.assertIsNone(second, 'A second collector stole the learning socket')
            finally:
                if second is not None:
                    second.close()
                first.close()

    def test_close_never_unlinks_a_replaced_socket_owned_by_someone_else(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary)/'learning.sock'
            first = LearningRPC(file)
            file.unlink()
            replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                replacement.bind(str(file))
                first.close()
                self.assertTrue(file.exists())
            finally:
                replacement.close()
                if file.exists():
                    file.unlink()


class ControlBoundaryTests(unittest.TestCase):
    def test_normal_diagnosis_needs_continuous_new_evidence_before_recovery(self):
        fusion = Fusion(dict(confidence_min=0.8, confirm_ms=100, max_gap_ms=60))
        status = healthy_status(1)
        normal = dict(label='normal', confidence=0.99, test=False)
        self.assertEqual(fusion.evaluate(normal, status, 1000, formal=True)['model_state'], 'NORMAL_CANDIDATE')
        self.assertEqual(fusion.evaluate(normal, status, 1050, formal=True)['model_state'], 'NORMAL_CANDIDATE')
        self.assertEqual(fusion.evaluate(normal, status, 1100, formal=True)['model_state'], 'NORMAL_OBSERVATION')
        fusion.evaluate(None, status, 1150, formal=True)
        self.assertEqual(fusion.evaluate(normal, status, 1200, formal=True)['model_state'], 'NORMAL_CANDIDATE')

    def test_mock_and_diagnostic_modes_cannot_enable_a_physical_load_executor(self):
        with tempfile.TemporaryDirectory() as temporary:
            for mock in (True, False):
                config = copy.deepcopy(CONFIG)
                config['database'] = str(Path(temporary)/('events-'+str(mock)+'.sqlite'))
                config['diagnostic_test'] = True
                config['load_executor']=dict(enabled=True, qualified=True,
                    evidence='UNIT_FIXTURE_NOT_HARDWARE', command=['/bin/false'])
                service = None
                try:
                    with self.assertRaises(ValueError):
                        service = Service(config, mock=mock)
                finally:
                    if service is not None:
                        service.close()

    def test_model_unavailable_is_not_published_as_fault_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = copy.deepcopy(CONFIG)
            config['database'] = str(Path(temporary)/'events.sqlite')
            service = Service(config)
            boot = 'UNIT_BOOT_NO_HARDWARE'
            service.boot = boot
            status = healthy_status(1)
            model = dict(label='imbalance', formal=True, test=False, frame_id=1, frame_end_ms=status['uptime_ms'])
            state = dict(status=status, link='ONLINE', test=False, load={}, frame={}, model=model,
                snapshot_monotonic=time.monotonic(),status_age_ms=0,frame_age_ms=0,
                decision=dict(model_state='CONFIRMED_MAINTENANCE'))
            service.journal.put(('status', boot, state))
            service.journal.put(('status', boot, dict(state, model=None, decision=dict(model_state='UNAVAILABLE'))))
            service.stop.set()
            try:
                with patch.object(service.model,'formal_result',side_effect=lambda result:result.get('formal') is True):
                    service.journal_loop()
                events = [item for item in service.store.events() if item['source'] == 'MODEL']
                self.assertEqual(len(events), 1)
                self.assertNotEqual(events[0]['state'], 'RECOVERED')
                self.assertEqual(events[0]['severity_current'], 1)
            finally:
                service.close()


class EventAtomicityTests(unittest.TestCase):
    def test_ack_of_an_old_active_event_survives_more_than_a_thousand_new_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary)/'events.sqlite')
            self.addCleanup(store.close)
            tracker = EventTracker(store, 'unit-device', 'unit-boot')
            status = healthy_status(1)
            tracker.update('OC_HARD', 1, True, status)
            event = store.events()[0]
            identity = event['event_id']
            acknowledged = store.acknowledge(identity)
            with store.transaction() as database:
                for index in range(1001):
                    filler = dict(event, event_id='UNIT_HISTORY_'+str(index), notify=False)
                    database.execute('INSERT INTO events VALUES(?,?,?)',
                        (filler['event_id'], filler['event_revision'], json.dumps(filler)))
            tracker.update('OC_HARD', 3, True, status)
            row = store.db.execute('SELECT payload FROM events WHERE event_id=?', (identity,)).fetchone()
            updated = json.loads(row[0])
            self.assertTrue(updated['acknowledged'])
            self.assertEqual(updated['event_revision'], acknowledged['event_revision']+1)
            self.assertEqual(updated['severity_current'], 3)

    def test_concurrent_ack_and_severity_update_preserve_both(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary)/'events.sqlite')
            tracker = EventTracker(store, 'unit-device', 'unit-boot')
            status = healthy_status(1)
            tracker.update('OC_HARD', 1, True, status)
            identity = store.events()[0]['event_id']
            paused, release = threading.Event(), threading.Event()
            original = store.event
            failures = []
            def delayed(event):
                if threading.current_thread().name == 'unit-ack':
                    paused.set()
                    if not release.wait(2):
                        raise RuntimeError('Unit scheduling timeout')
                return original(event)
            def acknowledge():
                try:
                    store.acknowledge(identity)
                except Exception as error:
                    failures.append(error)
            def update():
                try:
                    tracker.update('OC_HARD', 3, True, status)
                except Exception as error:
                    failures.append(error)
            with patch.object(store, 'event', side_effect=delayed):
                ack = threading.Thread(target=acknowledge, name='unit-ack')
                severity = threading.Thread(target=update, name='unit-severity')
                try:
                    ack.start()
                    self.assertTrue(paused.wait(2))
                    severity.start()
                    time.sleep(0.05)
                    release.set()
                    ack.join(2)
                    severity.join(2)
                    self.assertFalse(ack.is_alive() or severity.is_alive())
                    self.assertEqual(failures, [])
                    event = store.events()[0]
                    self.assertTrue(event['acknowledged'])
                    self.assertEqual(event['severity_current'], 3)
                finally:
                    release.set()
                    ack.join(2)
                    if severity.ident is not None:
                        severity.join(2)
                    store.close()


if __name__ == '__main__':
    unittest.main()
