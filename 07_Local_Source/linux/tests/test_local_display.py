import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from cabinet.local_display import LocalDisplay
from cabinet.mock import MockController
from cabinet.protocol import Frame
from cabinet.service import Service
from hmi_daily.cabinet.baseline import DEFAULTS
from hmi_daily.cabinet.learning_web import utc_text
from hmi_daily.read_real import normalize_status


CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'config.example.json').read_text(encoding='utf-8'))
WORDS = [1, 7, 1] + [0] * 14


class TrustedClock:
    def trusted(self):
        return True

    def close(self):
        pass


def healthy_status(now):
    value = MockController().status()
    value.pop('raw_words', None)
    value.update(uptime_ms=int(now * 1000) & 0xffffffff, configured=True, configuration_id=1,
                 alarm_level=0, active=[], latched=[], hard_inhibit=False, mode='RUN',
                 fan_action='PI', reserved_meta_bits=0, measured_rpm=6000, ramped_rpm=6000,
                 requested_rpm=6000, test_mode=False, event_sequence=0, lost_events=0,
                 input_validity=dict(rpm=True, adc=True, temperature=True, pressure=True))
    return value


def healthy_frame(identity, now):
    value = MockController().frame()
    header = list(value.header)
    header[3:5] = [identity, int(now * 1000) & 0xffffffff]
    header[15], header[17], header[27] = 0, 7, 0
    return Frame(tuple(header), value.values)


class CountingController:
    boot_cookie = 123
    feature_words = WORDS

    def __init__(self):
        self.frames = self.statuses = 0
        self.now = 0

    def identify(self):
        pass

    def status(self):
        self.statuses += 1
        self.now = time.monotonic()
        return healthy_status(self.now)

    def frame(self):
        self.frames += 1
        return healthy_frame(self.frames, self.now)

    def event(self):
        return None

    def close(self):
        pass


class LocalDisplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.config = copy.deepcopy(CONFIG)
        self.config.update(device_id='test-device', database=str(self.root / 'events.sqlite'), poll_ms=10)
        self.config['contract']['calibration_id'] = 7
        learning = copy.deepcopy(DEFAULTS)
        learning.update(device_id='test-device', installation_id='test-install', stable_seconds=0.1,
                        capture_seconds=6, timeout_seconds=20, confirm_seconds=5, min_samples=12)
        learning['contract']['calibration_id'] = 7
        self.config_path = self.root / 'learning.json'
        self.config_path.write_text(json.dumps(learning), encoding='utf-8')
        self.observer = LocalDisplay(self.config, self.root / 'view', self.config_path,
                                     self.root / 'baseline.sqlite', clock_factory=TrustedClock)
        self.observer.initialize()
        self.now, self.identity = 1.0, 0

    def tearDown(self):
        if self.observer.rpc is not None:
            self.observer.rpc.close()
        if self.observer.clock is not None:
            self.observer.clock.close()
        if self.observer.store is not None:
            self.observer.store.close()
        self.directory.cleanup()

    def packet(self, **changes):
        self.now += 0.5
        self.identity += 1
        value = dict(sequence=self.identity, boot='test-device/123', link='ONLINE',
                     received_at=self.now, reported_at=time.time(), status=healthy_status(self.now),
                     frame=healthy_frame(self.identity, self.now), feature_words=WORDS,
                     mailbox=dict(queued_frames=1, dropped_frames=0), test=False,
                     model=None, model_fresh=False, model_formal=False, model_required=False)
        value.update(changes)
        return value

    def process(self, **changes):
        value = self.packet(**changes)
        self.observer.submit(value)
        self.observer.step(self.observer.queue.get_nowait(), self.now)
        return value

    def command(self, operation='start', **payload):
        if operation == 'start':
            payload.setdefault('healthy_confirmed', True)
        if operation in ('start', 'commit', 'rollback'):
            payload.setdefault('expected_baseline_id', self.observer.web.active_id())
        envelope = dict(schema='cabinet-learning-command-v1', device_id='test-device',
                        request_id=str(uuid.uuid4()), operation=operation, session_id=self.observer.web.session_id,
                        issued_at=utc_text(time.time()), expires_at=utc_text(time.time() + 30),
                        expected_contract=self.observer.web.contract(), payload=payload,
                        actor=dict(subject_id='operator', audit_id='unit-test', permissions=['learning.' + operation]))
        return self.observer.web.execute(envelope, self.now)

    def test_alnpu_label_cannot_bypass_observer_freshness_or_identity(self):
        for rejection in ('stale', 'wrong_calibration', 'test', 'rejected_confidence'):
            with self.subTest(rejection=rejection):
                model = dict(backend='Alnpu', test=False, probabilities=[1, 0, 0, 0, 0],
                             feature_config_id=1, calibration_id=7, label='normal')
                changes = dict(model=model, model_fresh=True, model_formal=False)
                if rejection == 'stale':
                    changes['model_fresh'] = False
                elif rejection == 'wrong_calibration':
                    model['calibration_id'] = 999
                elif rejection == 'test':
                    model['test'] = True
                else:
                    model['diagnostic_state'] = 'REJECTED_CONFIDENCE'
                self.process(**changes)
                published = json.loads((self.root / 'view/state.json').read_text(encoding='utf-8'))
                self.assertIsNone(published['observation']['model'])
                self.assertEqual(published['display']['panel_model_valid'], '0')
                self.assertEqual(published['display']['panel_prob_normal'], '--')

    def test_full_learning_and_display_share_the_same_frames(self):
        self.process()
        self.assertTrue(self.command()['ok'])
        for _ in range(20):
            self.process()
            if self.observer.learner.state == 'PENDING_CONFIRM':
                break
        status = self.observer.web.snapshot(self.now)
        self.assertEqual(status['job']['state'], 'PENDING_CONFIRM')
        result = self.command('commit', job_id=status['job']['job_id'], candidate_hash=status['job']['candidate_hash'])
        self.assertTrue(result['ok'], result)
        self.process()
        published = json.loads((self.root / 'view/state.json').read_text(encoding='utf-8'))
        self.assertEqual(published['observation']['baseline']['baseline_id'], result['baseline_id'])
        self.assertEqual(published['display']['frame_id'], str(self.identity))

    def test_context_backlog_rejects_mutations(self):
        self.process()
        self.observer.submit(self.packet())
        self.assertEqual(self.command()['reason'], 'COLLECTOR_BACKLOG')
        self.assertIsNone(self.observer.learner.job_id)

    def test_publication_preserves_actual_collector_identity_and_timestamp(self):
        packet = self.process()
        sample = json.loads((self.root / 'view/state.json').read_text())['observation']
        for key in ['link', 'received_at', 'boot', 'sequence']:
            self.assertEqual(sample[key], packet[key])

    def test_reference_guard_preserves_complete_stream_identity(self):
        from cabinet.normal_reference_guard import NormalReferenceGuard
        packet=self.packet()
        packet['boot']='test-device/6a7064ff/4ef7f5c5-744a-4fbd-a5f5-4d432b467466/1'
        packet['bench']=dict(state='IDLE',controls_enabled=False,output_never_applied=True)
        packet['normal_reference_guard']=NormalReferenceGuard().update(
            packet['boot'],packet['status'],packet['bench'],packet['frame'])
        self.observer.submit(packet);self.observer.step(self.observer.queue.get_nowait(),self.now)
        sample=json.loads((self.root/'view/state.json').read_text(encoding='utf-8'))['observation']
        self.assertEqual(sample['normal_reference_guard'],packet['normal_reference_guard'])
        self.assertEqual(sample['normal_reference_guard']['boot'],sample['boot'])
        self.assertEqual(sample['bench'],packet['bench'])
        self.assertEqual(sample['normal_reference_guard']['state'],'WAIT_FULL_WINDOW')

    def test_publication_does_not_retimestamp_delayed_packets(self):
        packet = self.packet()
        self.observer.submit(packet)
        self.observer.step(self.observer.queue.get_nowait(), self.now + 0.75)
        sample = json.loads((self.root / 'view/state.json').read_text())['observation']
        self.assertEqual(sample['received_at'], packet['received_at'])

    def test_frame_queue_overflow_aborts_task(self):
        self.process()
        self.assertTrue(self.command()['ok'])
        for _ in range(20):
            self.observer.submit(self.packet())
        self.assertEqual(self.observer.queue.qsize(), 16)
        first = self.observer.queue.get_nowait()
        self.observer.step(first, first['received_at'])
        self.assertEqual(self.observer.learner.state, 'ABORTED')

    def test_old_packets_cannot_refresh_freshness(self):
        value = self.packet()
        self.observer.step(value, self.now + 2)
        published = json.loads((self.root / 'view/state.json').read_text(encoding='utf-8'))
        self.assertEqual(published['display']['link'], 'ERROR')
        self.assertIsNone(published['observation'])

    def test_offline_aborts_and_marks_web_unavailable(self):
        self.process()
        self.command()
        self.observer.offline('PL_LINK_LOSS')
        self.assertEqual(self.observer.learner.state, 'ABORTED')
        self.assertFalse(self.observer.web.snapshot(self.now)['available'])

    def test_formal_model_conflict_without_a_new_frame_aborts(self):
        self.process()
        self.command()
        model = dict(frame_id=1, feature_config_id=1, calibration_id=7,
                     label='imbalance', backend='ALNPU', test=False)
        self.process(frame=None, model=model, model_fresh=True, model_formal=True, model_required=True)
        self.assertEqual(self.observer.learner.state, 'ABORTED')
        self.assertEqual(self.observer.learner.reason, 'MODEL_CONFLICT')

    def test_qualified_model_unavailable_blocks_learning(self):
        self.process(model_required=True)
        self.assertEqual(self.command()['reason'], 'MODEL_UNAVAILABLE')

    def test_model_status_does_not_claim_cpu_is_npu(self):
        model = dict(frame_id=1, feature_config_id=1, calibration_id=7, label='normal', backend='CPU_ONNX', test=False)
        self.process(model=model, model_fresh=True, model_formal=False)
        published = json.loads((self.root / 'view/state.json').read_text(encoding='utf-8'))
        self.assertIn('CPU_ONNX', published['display']['daily_model'])
        self.assertIn('观察', published['display']['daily_model'])
        self.assertTrue(published['observation']['learning_web']['qualification']['model_available'])

    def test_model_expired_is_not_published_as_healthy(self):
        model = dict(frame_id=1, feature_config_id=1, calibration_id=7, label='normal', backend='ALNPU', test=False)
        self.process(model=model, model_fresh=False)
        published = json.loads((self.root / 'view/state.json').read_text(encoding='utf-8'))
        self.assertIsNone(published['observation']['model'])
        self.assertFalse(published['observation']['learning_web']['qualification']['model_available'])

    def test_test_source_cannot_be_requalified_by_later_real_packet(self):
        self.process(test=True)
        self.process()
        self.assertEqual(self.command()['reason'], 'TEST_SOURCE')

    def test_collector_restart_changes_external_session(self):
        self.process()
        original = self.observer.web.session_id
        self.command()
        self.process(boot='test-device/456')
        self.assertNotEqual(original, self.observer.web.session_id)
        self.assertEqual(self.observer.learner.state, 'ABORTED')

    def test_device_identity_mismatch_does_not_create_a_learning_socket(self):
        config = dict(self.config, device_id='other-device')
        observer = LocalDisplay(config, self.root / 'mismatch', self.config_path,
                                self.root / 'mismatch.sqlite', clock_factory=TrustedClock)
        observer.initialize()
        self.assertEqual(observer.learning_error, 'DEVICE_ID_MISMATCH')
        self.assertIsNone(observer.rpc)

    def test_learning_contract_mismatch_is_fail_closed(self):
        config = copy.deepcopy(self.config)
        config['contract']['sample_mode_id'] = 2
        observer = LocalDisplay(config, self.root / 'contract', self.config_path,
                                self.root / 'contract.sqlite', clock_factory=TrustedClock)
        observer.initialize()
        self.assertEqual(observer.learning_error, 'LEARNING_CONTRACT_MISMATCH')
        self.assertIsNone(observer.rpc)

    def test_reconnect_with_same_pl_cookie_uses_a_new_stream(self):
        class BrokenController(CountingController):
            def status(self):
                if self.statuses >= 2:
                    raise OSError('simulated bus loss')
                return super().status()

        class Observer:
            def __init__(self):
                self.packets = []

            def start(self):
                pass

            def submit(self, packet):
                self.packets.append(packet)

            def close(self):
                pass

        observer = Observer()
        service = Service(self.config, controller=BrokenController(), observer=observer)
        with patch('cabinet.service.open_controller', return_value=CountingController()):
            try:
                service.start()
                deadline = time.monotonic() + 2
                streams = set()
                while time.monotonic() < deadline:
                    streams = {packet['boot'] for packet in observer.packets if packet['link'] == 'ONLINE'}
                    if len(streams) == 2:
                        break
                    time.sleep(0.01)
                self.assertEqual(len(streams), 2)
            finally:
                service.close()

    def test_input_packets_are_immutable_copies(self):
        value = self.packet()
        self.observer.submit(value)
        value['status']['active'].append('OC_HARD')
        queued = self.observer.queue.get_nowait()
        self.assertEqual(queued['status']['active'], [])

    def test_control_raw_status_is_preserved_for_temperature_loop(self):
        original = MockController().status()
        normalized = normalize_status(original, keep_raw=True)
        self.assertEqual(normalized['raw_words'], original['raw_words'])
        self.assertIn('input_validity', normalized)

    def test_frozen_pl_time_cannot_keep_old_model_fresh(self):
        service = Service(self.config, controller=CountingController())
        try:
            current = healthy_status(1)
            record = healthy_frame(1, 1).as_dict()
            service.set(link='ONLINE', status=current, frame=record, model={'frame_end_ms':1000})
            service.updated = time.monotonic()
            service.frame_received = time.monotonic() - 2
            state = service.public_state()
            self.assertIsNone(state['model'])
            self.assertGreaterEqual(state['frame_age_ms'], 2000)
        finally:
            service.close()

    def test_pl_clock_stopped_hides_display(self):
        self.process()
        fixed = healthy_status(self.now)
        for _ in range(5):
            self.process(status=fixed)
        published = json.loads((self.root / 'view/state.json').read_text(encoding='utf-8'))
        self.assertEqual(published['display']['link'], 'ERROR')

    def test_service_has_one_hardware_frame_consumer(self):
        controller = CountingController()
        observer = LocalDisplay(self.config, self.root / 'threaded', self.config_path,
                                self.root / 'threaded-baseline.sqlite', clock_factory=TrustedClock)
        service = Service(self.config, controller=controller, observer=observer)
        try:
            service.start()
            deadline = time.monotonic() + 2
            output = self.root / 'threaded/state.json'
            while time.monotonic() < deadline:
                if output.exists() and observer.last_source_sequence is not None:
                    break
                time.sleep(0.01)
            self.assertIsNotNone(observer.last_source_sequence)
            self.assertEqual(controller.frames, controller.statuses)
            state = json.loads(output.read_text(encoding='utf-8'))
            self.assertIn('learning_web', state['observation'])
            observation=state['observation']
            self.assertEqual(observation['normal_reference_guard']['boot'],observation['boot'])
            self.assertEqual(observation['boot'].split('/'),
                             [self.config['device_id'],'0000007b',service.collector_session,str(service.connection_epoch)])
            self.assertEqual(observation['bench']['state'],'IDLE')
        finally:
            service.close()

    def test_slow_learning_worker_does_not_block_hardware(self):
        controller = CountingController()
        observer = LocalDisplay(self.config, self.root / 'slow', self.config_path,
                                self.root / 'slow-baseline.sqlite', clock_factory=TrustedClock)
        original = observer.step

        def slow(packet, now):
            time.sleep(0.2)
            original(packet, time.monotonic())

        observer.step = slow
        service = Service(self.config, controller=controller, observer=observer)
        try:
            service.start()
            time.sleep(0.4)
            self.assertGreaterEqual(controller.frames, 10)
            self.assertLessEqual(observer.queue.qsize(), 16)
        finally:
            service.close()


if __name__ == '__main__':
    unittest.main()
