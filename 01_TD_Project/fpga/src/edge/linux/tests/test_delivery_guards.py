import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid


from cabinet.local_display import LocalDisplay
from cabinet.service import Service
from cabinet.store import EventTracker, Store
from hmi_daily.cabinet.baseline import DEFAULTS, digest
from hmi_daily.cabinet.learning_web import utc_text
from test_local_display import CONFIG, WORDS, TrustedClock, healthy_frame, healthy_status


class LearningContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.configuration = copy.deepcopy(CONFIG)
        self.configuration['contract']['calibration_id'] = 7
        learning = copy.deepcopy(DEFAULTS)
        learning.update(device_id=self.configuration['device_id'], installation_id='REVIEW_FIXTURE_NOT_HARDWARE',
                        stable_seconds=0.1, capture_seconds=6, timeout_seconds=20,
                        min_samples=12, confirm_seconds=5)
        learning['contract']['calibration_id'] = 7
        learning_file = self.root / 'learning.json'
        learning_file.write_text(json.dumps(learning))
        self.observer = LocalDisplay(self.configuration, self.root / 'view', learning_file,
                                     self.root / 'baseline.sqlite', clock_factory=TrustedClock)
        self.observer.initialize()
        self.assertIsNone(self.observer.learning_error)
        self.now = 1.0
        self.packet_sequence = 0
        self.frame_sequence = 0
        self.window_drops = 0
        self.mailbox_drops = 0

    def tearDown(self):
        self.observer.rpc.close()
        self.observer.clock.close()
        self.observer.store.close()
        self.temporary.cleanup()

    def observe(self, frame_advance=1):
        self.now += 0.5
        self.packet_sequence += 1
        self.frame_sequence += frame_advance
        frame = healthy_frame(self.frame_sequence, self.now)
        header = list(frame.header)
        header[23] = self.window_drops
        frame = type(frame)(tuple(header), frame.values)
        packet = dict(sequence=self.packet_sequence, boot='REVIEW_SINGLE_PL_BOOT', link='ONLINE',
                      received_at=self.now, reported_at=time.time(), status=healthy_status(self.now),
                      frame=frame, feature_words=WORDS,
                      mailbox=dict(queued_frames=0, dropped_frames=self.mailbox_drops),
                      test=False, model=None, model_fresh=False, model_formal=False, model_required=False)
        self.observer.submit(packet)
        self.observer.step(self.observer.queue.get_nowait(), self.now)

    def command(self, operation, **payload):
        if operation in ('start', 'commit', 'rollback'):
            payload['expected_baseline_id'] = self.observer.web.active_id()
        envelope = dict(schema='cabinet-learning-command-v1', request_id=str(uuid.uuid4()),
                        device_id=self.configuration['device_id'], operation=operation,
                        session_id=self.observer.web.session_id, issued_at=utc_text(time.time()),
                        expires_at=utc_text(time.time() + 30), payload=payload,
                        expected_contract=self.observer.web.contract(),
                        actor=dict(subject_id='review-operator', audit_id='REVIEW_FIXTURE_NOT_HARDWARE',
                                   permissions=['learning.' + operation]))
        return self.observer.web.execute(envelope, self.now)

    def start(self):
        self.observe()
        self.assertTrue(self.command('start', healthy_confirmed=True)['ok'])
        self.observe()
        self.observe()
        self.assertEqual(self.observer.learner.state, 'CAPTURING')

    def test_hardware_frame_jump_aborts_learning_even_without_subscriber_gap(self):
        self.start()
        self.observe(frame_advance=3)
        self.assertIn(self.observer.learner.state, ('ABORTED', 'REJECTED'),
                      'Sequential collector packets concealed a missing FRM1 frame sequence')

    def test_window_drop_counter_change_prevents_baseline_activation(self):
        self.start()
        self.window_drops += 1
        self.observe()
        for unused in range(25):
            self.observe()
            if self.observer.learner.state == 'PENDING_CONFIRM':
                break
        learner = self.observer.learner
        if learner.candidate is not None:
            self.command('commit', job_id=learner.job_id, candidate_hash=digest(learner.candidate))
        self.assertEqual(self.observer.store.profiles(), [],
                         'A known PL window drop still produced an ACTIVE healthy baseline')

    def test_mailbox_drop_counter_change_aborts_learning(self):
        self.start()
        self.mailbox_drops += 1
        self.observe()
        self.assertIn(self.observer.learner.state, ('ABORTED', 'REJECTED'),
                      'EDG1 mailbox dropped_frames increased but the learning job continued')


class RestartedEventTrackerTests(unittest.TestCase):
    def test_old_active_alarm_reloads_without_history_listing_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events.sqlite'
            store = Store(path)
            tracker = EventTracker(store, 'review-device', 'review-pl-boot')
            tracker.update('imbalance', 1, True, healthy_status(1), source='MODEL')
            identity = tracker.active['MODEL:imbalance']['event_id']
            event = store.get_event(identity)
            with store.transaction() as database:
                for index in range(1001):
                    filler = dict(event, event_id='review-filler-' + str(index), state='RECOVERED',
                                  boot_id='other-pl-boot', code='FILLER', notify=False)
                    database.execute('INSERT INTO events VALUES(?,?,?)',
                                     (filler['event_id'], filler['event_revision'], json.dumps(filler)))
            store.close()
            store = Store(path)
            try:
                restored = EventTracker(store, 'review-device', 'review-pl-boot')
                restored.update('imbalance', 0, False, healthy_status(2), source='MODEL')
                self.assertEqual(store.get_event(identity)['state'], 'RECOVERED',
                                 'A stored ACTIVE alarm was omitted at restart and never recovered')
            finally:
                store.close()


class FifoAcknowledgementTests(unittest.TestCase):
    def test_full_command_queue_does_not_permanently_wedge_durable_fifo_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            configuration = copy.deepcopy(CONFIG)
            configuration.update(database=str(Path(temporary) / 'events.sqlite'), poll_ms=10)
            configuration['model']['backend'] = 'disabled'
            service = Service(configuration)
            event_words = [7, 1000, 1, 1, 3, 1, 1, 0]
            boot = configuration['device_id'] + '/0000007b'

            class FakeController:
                boot_cookie = 123

                def __init__(self):
                    self.polls = 0
                    self.commands = []

                def status(self):
                    self.polls += 1
                    return healthy_status(self.polls)

                def frame(self):
                    return None

                def event(self):
                    if self.polls >= 12:
                        service.stop.set()
                    return event_words

                def command(self, operation, payload=0):
                    self.commands.append((operation, payload))

                def close(self):
                    pass

            controller = FakeController()
            service.controller = controller
            service.boot = boot
            service.pending_fifo = (boot, event_words[0])
            for index in range(service.commands.maxsize):
                service.commands.put_nowait((boot, 4, index))
            service.journal.put_nowait(('fifo', boot, event_words))
            service.stop.set()
            try:
                service.journal_loop()
                self.assertEqual(service.store.db.execute('SELECT count(*) FROM fifo_records').fetchone()[0], 1)
                service.stop.clear()
                service.io_loop()
                self.assertIn((8, event_words[0]), controller.commands,
                              'The durable FIFO POP was dropped; the head remained pending after queue drain')
            finally:
                service.close()
                service.store.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
