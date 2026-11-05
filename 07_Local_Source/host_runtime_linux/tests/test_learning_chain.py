import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from cabinet.local_display import LocalDisplay
from hmi_daily.cabinet.baseline import DEFAULTS
from hmi_daily.cabinet.learning_agent import LearningAgent, AgentJournal
from hmi_daily.cabinet.learning_web import utc_text
from test_local_display import CONFIG, WORDS, TrustedClock, healthy_frame, healthy_status


class Backend:
    def __init__(self):
        self.operation = None
        self.extra = {}
        self.results = []
        self.saved_command = None

    def exchange(self, outgoing):
        self.results.extend(outgoing['results'])
        command = None
        if self.operation:
            status = outgoing['status']
            payload = dict(self.extra)
            if self.operation == 'start':
                payload['healthy_confirmed'] = True
            if self.operation in ('start', 'commit', 'rollback'):
                payload['expected_baseline_id'] = status['baseline']['active_id']
            if self.operation in ('commit', 'cancel'):
                payload['job_id'] = status['job']['job_id']
            if self.operation == 'commit':
                payload['candidate_hash'] = status['job']['candidate_hash']
            command = dict(schema='cabinet-learning-command-v1', device_id='test-device', request_id=str(uuid.uuid4()),
                session_id=status['session_id'], operation=self.operation, issued_at=utc_text(time.time()),
                expires_at=utc_text(time.time()+30), expected_contract=status['contract'], payload=payload,
                actor=dict(subject_id='unit-operator', audit_id='UNIT_NOT_A_REAL_BACKEND',
                           permissions=['learning.'+self.operation]))
            self.saved_command = command
            self.operation = None
        return dict(schema='cabinet-learning-exchange-reply-v1', device_id='test-device', command=command,
            acknowledged_results=[dict(request_id=item['request_id'], result_hash=item['result_hash'])
                                  for item in outgoing['results']])


class LearningChainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = copy.deepcopy(CONFIG)
        self.config.update(device_id='test-device', database=str(self.root/'events.sqlite'))
        self.config['contract']['calibration_id'] = 7
        learning = copy.deepcopy(DEFAULTS)
        learning.update(device_id='test-device', installation_id='UNIT_INSTALL_NOT_HARDWARE', stable_seconds=0.1,
            capture_seconds=6, timeout_seconds=20, confirm_seconds=5, min_samples=12)
        learning['contract']['calibration_id'] = 7
        self.config_file = self.root/'learning.json'
        self.config_file.write_text(json.dumps(learning))
        self.backend = Backend()
        self.observer = self.make_observer()
        self.addCleanup(self.close_observer)
        self.now, self.sequence = 1.0, 0
        work = Path(os.environ.get('CABINET_NPU_WORK', Path(__file__).resolve().parents[2]))
        self.protected = [work/'bundle_003'/name for name in ('model_u8_io.onnx', 'normalization.json')]
        self.hashes = {str(file): hashlib.sha256(file.read_bytes()).hexdigest() for file in self.protected}

    def make_observer(self):
        observer = LocalDisplay(self.config, self.root/'view', self.config_file, self.root/'baseline.sqlite', clock_factory=TrustedClock)
        observer.initialize()
        self.assertIsNone(observer.learning_error)
        return observer

    def close_observer(self):
        if self.observer is not None:
            self.observer.rpc.close()
            self.observer.clock.close()
            self.observer.store.close()
            self.observer = None

    def observe(self, amplitude=0):
        self.now += 0.5
        self.sequence += 1
        frame = healthy_frame(self.sequence, self.now)
        values = list(frame.values)
        values[0] += amplitude
        frame = type(frame)(frame.header, tuple(values))
        packet = dict(sequence=self.sequence, boot='UNIT_REAL_SHAPE_NOT_HARDWARE', link='ONLINE', received_at=self.now,
            reported_at=time.time(), status=healthy_status(self.now), frame=frame, feature_words=WORDS,
            mailbox=dict(queued_frames=0, dropped_frames=0), test=False,
            model=None, model_fresh=False, model_formal=False, model_required=False)
        self.observer.submit(packet)
        self.observer.step(self.observer.queue.get_nowait(), self.now)

    def tick(self, operation=None, **extra):
        self.backend.operation, self.backend.extra = operation, extra
        failures, result = [], []
        def client():
            journal = AgentJournal(self.root/'agent.sqlite')
            try:
                agent = LearningAgent('test-device', self.root/'view/learning.sock', journal, self.backend)
                result.append(agent.tick())
            except Exception as error:
                failures.append(error)
            finally:
                journal.connection.close()
        thread = threading.Thread(target=client, daemon=True)
        thread.start()
        deadline = time.monotonic()+4
        while thread.is_alive() and time.monotonic() < deadline:
            self.observer.poll(self.now)
            thread.join(0.005)
        self.assertFalse(thread.is_alive(), 'Bounded agent/RPC chain did not finish')
        self.assertEqual(failures, [])
        self.assertTrue(result[0]['ok'])

    def learn(self, amplitude=0):
        self.observe(amplitude)
        self.tick('start')
        self.assertEqual(self.observer.learner.state, 'WAIT_STABLE')
        for unused in range(30):
            self.observe(amplitude)
            if self.observer.learner.state == 'PENDING_CONFIRM':
                break
        self.assertEqual(self.observer.learner.state, 'PENDING_CONFIRM')
        self.tick('commit')
        self.assertEqual(self.observer.learner.state, 'COMMITTED')
        return self.observer.learner.profiles[0]['id']

    def test_agent_rpc_collector_learn_commit_restart_and_rollback_preserve_model(self):
        with patch('cabinet.service.open_controller', side_effect=AssertionError('No hardware in learning test')), \
                patch('cabinet.io.MMIO', side_effect=AssertionError('No MMIO in learning test')):
            first = self.learn()
            self.observe()
            second = self.learn(amplitude=0.0001)
            self.assertNotEqual(first, second)
            self.tick()
            self.assertTrue(any(item['result']['operation']=='commit' and item['result']['ok'] for item in self.backend.results))
            old_session = self.observer.web.session_id
            self.close_observer()
            self.observer = self.make_observer()
            self.assertNotEqual(self.observer.web.session_id, old_session)
            self.observe(amplitude=0.0001)
            self.assertEqual(self.observer.learner.profiles[0]['id'], second)
            self.tick('rollback', baseline_id=first)
            self.assertEqual(self.observer.learner.profiles[0]['id'], first)
            self.observe()
            self.assertEqual(self.observer.learner.evidence['state'], 'CONSISTENT')
        for file, expected in self.hashes.items():
            self.assertEqual(hashlib.sha256(Path(file).read_bytes()).hexdigest(), expected)

    def test_agent_cancellation_preserves_active_baseline_and_never_silences_protection(self):
        previous = self.learn()
        self.observe()
        self.tick('start')
        self.tick('cancel')
        self.assertEqual(self.observer.learner.state, 'CANCELLED')
        self.assertEqual(self.observer.learner.profiles[0]['id'], previous)
        self.assertFalse(self.observer.learner.snapshot()['advisory_qualified'])

    def test_commit_rechecks_collector_after_durable_request_journaling(self):
        previous = self.learn()
        self.observe()
        self.tick('start')
        for unused in range(30):
            self.observe()
            if self.observer.learner.state == 'PENDING_CONFIRM':
                break
        original = self.observer.store.reserve_request
        def delayed(identity, fingerprint):
            original(identity, fingerprint)
            self.observer.latest_sequence += 1
        with patch.object(self.observer.store, 'reserve_request', side_effect=delayed):
            self.tick('commit')
        result = self.observer.web.result(self.backend.saved_command['request_id'])
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'COLLECTOR_BACKLOG')
        self.assertEqual(self.observer.learner.profiles[0]['id'], previous)
        self.assertEqual(self.observer.learner.state, 'PENDING_CONFIRM')


if __name__ == '__main__':
    unittest.main()
