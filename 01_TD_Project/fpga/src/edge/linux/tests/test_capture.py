import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from cabinet.capture import CaptureRecorder, COEFFICIENT_SHA, EDGES, FEATURE_ID, digest, display_fields, frame_words
from cabinet.protocol import FEATURES, Frame
from export_capture import export
from hmi_daily.cabinet.learning_rpc import request


def contract():
    return dict(feature_config_id=FEATURE_ID, calibration_id=7, sample_mode_id=2,
                pl_build_id=0x202610f4,
                qualified=False, profile='V4-P800-Q17', coefficient_sha256=COEFFICIENT_SHA,
                fs=4000, adc_fs=50000, fft_size=1024, hop=512, edges=EDGES, feature_names=list(FEATURES))


def packet(sequence, now, **changes):
    header = [0] * 32
    header[:5] = [0x46524d31, 0x10000, 284, sequence, int(now * 1000) & 0xffffffff]
    header[9:15] = [25575000, 25575000, 1024, 1024, (25 << 16) | 12800, 128]
    header[16:23] = [FEATURE_ID, 7, 2, 3, 4000, 100000000, 50000]
    header[26] = 0x202610f4
    values = [0.1] * 39
    values[-5:] = [1.0, 0.8, 35, 0.05, 4200]
    result = dict(sequence=sequence, boot='unit-fixture-not-hardware/collector/1', link='ONLINE',
        received_at=now, now_ms=header[4], frame=Frame(tuple(header), tuple(values)),
        configuration_words=[FEATURE_ID, 7, 1] + [0] * 5 + EDGES,
        status=dict(uptime_ms=header[4], active=[], latched=[], hard_inhibit=False),
        mailbox=dict(queued_frames=1, dropped_frames=0), test=False, rejected=[])
    result.update(changes)
    return result


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / 'archive'
        self.directory.mkdir(mode=0o700)
        self.config = dict(device_id='UNIT_NOT_HARDWARE', contract=contract())
        self.bit = self.root / 'unit-not-bitstream.bin'
        self.bit.write_bytes(b'UNIT PROVENANCE FIXTURE NOT A BITSTREAM')
        self.calibration = self.root / 'unit-calibration.json'
        self.calibration.write_text('{"calibration_id":7,"physical":false}')
        self.evidence = self.root / 'unit-evidence.md'
        self.evidence.write_text('UNIT REVIEW FIXTURE: NO SENSOR OR BOARD OBSERVATION')
        self.recorder = CaptureRecorder(self.config, self.directory, self.root / 'view/capture.sock', contract())
        self.now = 100.0
        self.sequence = 0
        self.observe()

    def observe(self, **changes):
        self.sequence += 1
        self.now += 0.128
        value = packet(self.sequence, self.now, **changes)
        self.recorder.observe(value, self.now)
        return value

    def payload(self, **changes):
        value = dict(expected_boot=self.recorder.snapshot()['boot'], installation_id='unit-install',
            operator='unit-operator', label='normal', duration_s=60, capture_mode='REAL',
            bitstream_sha256=digest(self.bit), calibration_evidence_sha256=digest(self.calibration),
            note='unit test only, not real physical evidence')
        value.update(changes)
        return value

    def begin(self, **changes):
        return self.recorder.begin(self.payload(**changes), self.now)

    def save(self, label='normal'):
        self.begin(label=label)
        self.observe()
        self.observe()
        self.recorder.finish('COMPLETED', 'OPERATOR_STOP', self.now)
        return self.recorder.session_dir

    def review(self, directory, **changes):
        entry = dict(directory=str(directory), split='train', label='normal', label_reviewed=True,
                     reviewer='unit-reviewer', fault_episode_id=str(uuid.uuid4()),
                     label_evidence=str(self.evidence), calibration_evidence=str(self.calibration), bitstream=str(self.bit))
        entry.update(changes)
        path = self.root / ('review-' + str(uuid.uuid4()) + '.json')
        path.write_text(json.dumps(dict(schema='cabinet-capture-review-v1', sessions=[entry])))
        return path

    def test_capture_preserves_all_original_words_and_never_reviews_label(self):
        directory = self.save()
        rows = [json.loads(line) for line in (directory / 'frames.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows[0]['header']), 32)
        self.assertEqual(len(rows[0]['feature_words']), 39)
        self.assertEqual(rows[0]['feature_words'], frame_words(packet(1, 100)['frame']))
        summary = json.loads((directory / 'summary.json').read_text())
        self.assertEqual(summary['state'], 'COMPLETED')
        self.assertEqual(summary['durable_frames'], 2)
        self.assertFalse(summary['label_reviewed'])
        self.assertFalse(summary['training_ready'])
        for name, expected in summary['files_sha256'].items():
            self.assertEqual(digest(directory / name), expected)
        session = json.loads((directory / 'session.json').read_text())
        self.assertFalse(session['automatic_learning_changed'])
        self.assertFalse(session['controls_changed'])

    def test_float32_words_are_exact_including_negative_zero_and_subnormal(self):
        words = [0, 0x80000000, 1, 0x7f7fffff] + [0x3f800000] * 35
        frame = Frame.from_words(list(packet(1, 1)['frame'].header), words)
        self.assertEqual(frame_words(frame), words)

    def test_no_frame_does_not_erase_last_fresh_frame_for_start(self):
        self.observe(frame=None)
        self.begin()
        self.assertEqual(self.recorder.snapshot()['state'], 'RECORDING')
        self.recorder.finish('ABORTED', 'UNIT_END', self.now)

    def test_unlabelled_is_not_implicitly_normal(self):
        self.begin(label='unlabelled')
        self.assertEqual(self.recorder.snapshot()['label'], 'unlabelled')
        self.recorder.finish('ABORTED', 'UNIT_END', self.now)

    def test_r30_identity_archived_without_accepting_unknown_build(self):
        value = self.observe()
        header = list(value['frame'].header)
        header[26] = 0x202610f5
        value['frame'] = Frame(tuple(header), value['frame'].values)
        self.recorder.contract['pl_build_id'] = 0x202610f5
        self.assertEqual(self.recorder.reasons(value), [])
        header[26] = 0x202610f8
        value['frame'] = Frame(tuple(header), value['frame'].values)
        self.assertIn('V4_IDENTITY', self.recorder.reasons(value))

    def test_missing_provenance_cannot_begin_real(self):
        with self.assertRaisesRegex(ValueError, 'PROVENANCE'):
            self.begin(bitstream_sha256=None)

    def test_wrong_boot_and_stale_input_refuse_start(self):
        with self.assertRaisesRegex(ValueError, 'FRESH_COLLECTOR'):
            self.begin(expected_boot='old-collector')
        self.now += 2
        with self.assertRaisesRegex(ValueError, 'FRESH_COLLECTOR'):
            self.begin()

    def test_pending_queue_refuses_start(self):
        self.recorder.submit(packet(2, self.now))
        with self.assertRaisesRegex(ValueError, 'FRESH_COLLECTOR'):
            self.begin()

    def test_test_source_cannot_begin_real_but_diagnostic_is_archived(self):
        self.observe(test=True)
        with self.assertRaisesRegex(ValueError, 'REAL_CAPTURE_BLOCKED'):
            self.begin()
        self.begin(capture_mode='DIAGNOSTIC')
        self.observe(test=True)
        self.recorder.finish('COMPLETED', 'OPERATOR_STOP', self.now)
        self.assertEqual(self.recorder.snapshot()['state'], 'DIAGNOSTIC_SAVED')
        self.assertEqual(self.recorder.snapshot()['accepted'], 0)
        with self.assertRaisesRegex(ValueError, 'REAL sessions'):
            export(self.review(self.recorder.session_dir), self.root / 'export')

    def test_calibration_zero_and_wrong_readback_refuse_real(self):
        self.recorder.contract['calibration_id'] = 0
        with self.assertRaisesRegex(ValueError, 'CALIBRATION'):
            self.begin()
        self.recorder.contract['calibration_id'] = 7
        self.observe(configuration_words=[])
        with self.assertRaisesRegex(ValueError, 'CONFIG_READBACK'):
            self.begin()

    def test_normal_cannot_start_over_protection_and_invalid_frames_are_retained(self):
        self.observe(status=dict(active=['OC_HARD'], latched=[], hard_inhibit=True))
        with self.assertRaisesRegex(ValueError, 'FAULT_NOT_NORMAL'):
            self.begin()
        self.observe()
        self.begin()
        self.observe(status=dict(active=['OC_HARD'], latched=[], hard_inhibit=True))
        self.recorder.finish('COMPLETED', 'OPERATOR_STOP', self.now)
        self.assertEqual(self.recorder.snapshot()['rejected'], 1)
        row = json.loads((self.recorder.session_dir / 'frames.jsonl').read_text())
        self.assertIn('FAULT_NOT_NORMAL', row['rejected_reasons'])

    def test_config_change_aborts_and_preserves_previous_rows(self):
        self.begin()
        self.observe()
        self.observe(configuration_words=[])
        self.assertEqual(self.recorder.snapshot()['state'], 'ABORTED')
        self.assertEqual(self.recorder.snapshot()['frames'], 1)

    def test_sequence_gap_aborts(self):
        self.begin()
        self.sequence += 1
        self.observe()
        self.assertEqual(self.recorder.snapshot()['state'], 'ABORTED')
        self.assertEqual(self.recorder.snapshot()['gaps'], 1)

    def test_frame_gap_aborts_even_without_subscriber_gap(self):
        self.begin()
        self.observe()
        frame = packet(self.sequence + 5, self.now + 0.128)['frame']
        self.observe(frame=frame)
        self.assertEqual(self.recorder.snapshot()['reason'], 'FRAME_ID_GAP_OR_DUPLICATE')

    def test_offline_and_silence_abort_not_complete(self):
        self.begin()
        self.observe(link='OFFLINE', frame=None)
        self.assertEqual(self.recorder.snapshot()['state'], 'ABORTED')
        self.observe()
        self.begin()
        self.recorder.tick(self.now + 2)
        self.assertEqual(self.recorder.snapshot()['state'], 'ABORTED')

    def test_queue_overflow_does_not_block_hardware_and_aborts(self):
        self.begin()
        for identity in range(300):
            self.recorder.submit(packet(identity, self.now))
        self.assertTrue(self.recorder.overflow.is_set())
        self.recorder.tick(self.now)
        self.assertEqual(self.recorder.snapshot()['reason'], 'CAPTURE_QUEUE_OVERFLOW')

    def test_disk_reserve_refuses_start(self):
        usage = shutil.disk_usage(str(self.directory))._replace(free=1)
        with patch('cabinet.capture.shutil.disk_usage', return_value=usage):
            with self.assertRaisesRegex(ValueError, 'DISK_RESERVE'):
                self.begin()

    def test_disk_space_loss_during_recording_aborts(self):
        self.begin()
        self.observe()
        usage = shutil.disk_usage(str(self.directory))._replace(free=1)
        self.recorder.checked_disk_at = self.now - 2
        with patch('cabinet.capture.shutil.disk_usage', return_value=usage):
            self.recorder.tick(self.now)
        self.assertEqual(self.recorder.snapshot()['state'], 'ABORTED')
        self.assertEqual(self.recorder.snapshot()['reason'], 'DISK_RESERVE')

    def test_alive_status_without_new_sensor_frames_aborts(self):
        self.begin()
        self.observe()
        self.now += 2
        self.observe(frame=None)
        self.assertEqual(self.recorder.snapshot()['state'], 'ABORTED')
        self.assertEqual(self.recorder.snapshot()['reason'], 'NO_FRESH_FRAMES')

    def test_failed_fsync_never_publishes_completed(self):
        self.begin()
        self.observe()
        with patch('cabinet.capture.os.fsync', side_effect=OSError('UNIT disk failure')):
            with self.assertRaises(OSError):
                self.recorder.finish('COMPLETED', 'OPERATOR_STOP', self.now)
        self.assertNotEqual(self.recorder.snapshot()['state'], 'COMPLETED')
        self.assertFalse((self.recorder.session_dir / 'summary.json').exists())

    def test_same_fault_episode_cannot_leak_across_splits(self):
        first = self.save()
        self.observe()
        second = self.save()
        plan = json.loads(self.review(first, fault_episode_id='same-unit-episode').read_text())
        other = json.loads(self.review(second, split='test', fault_episode_id='same-unit-episode').read_text())
        plan['sessions'].extend(other['sessions'])
        path = self.root / 'leaked-review.json'
        path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, 'episode leaked'):
            export(path, self.root / 'export')

    def test_five_class_four_session_fixture_meets_only_import_readiness(self):
        from v4_runtime.import_frames import import_records
        entries = []
        for label in ('normal', 'imbalance', 'stall', 'clog', 'overheat'):
            for split in ('train', 'train', 'validation', 'test'):
                self.observe()
                directory = self.save(label)
                entries.extend(json.loads(self.review(directory, label=label, split=split).read_text())['sessions'])
        path = self.root / 'all-unit-reviews.json'
        path.write_text(json.dumps(dict(schema='cabinet-capture-review-v1', sessions=entries)))
        exported = export(path, self.root / 'export')
        imported = import_records(self.root / 'export/frames.jsonl', self.root / 'export/feature_contract.json', self.root / 'import')
        self.assertEqual(exported['sessions'], 20)
        self.assertTrue(imported['train_ready'])
        self.assertFalse(imported['production_qualified'])
        self.assertFalse(imported['physical_truth_verified'])

    def test_service_recorder_and_hdmi_use_only_one_mock_hardware_owner(self):
        from cabinet.service import Service
        from cabinet.local_display import LocalDisplay
        from hmi_daily.cabinet.baseline import DEFAULTS
        from test_local_display import CONFIG, TrustedClock, healthy_status
        config = copy.deepcopy(CONFIG)
        config.update(device_id='UNIT_NOT_HARDWARE', database=str(self.root / 'events.sqlite'), poll_ms=10)
        config['contract'].update(feature_config_id=FEATURE_ID, calibration_id=7, sample_mode_id=2)
        config['control']['enabled'] = config['temperature_loop']['enabled'] = False
        learning = copy.deepcopy(DEFAULTS)
        learning.update(device_id=config['device_id'], installation_id='unit-install')
        learning['contract'].update(feature_config_id=FEATURE_ID, calibration_id=7, sample_mode_id=2)
        learning_file = self.root / 'learning.json'
        learning_file.write_text(json.dumps(learning))

        class Controller:
            boot_cookie = 123
            feature_words = [FEATURE_ID, 7, 1] + [0] * 5 + EDGES
            frames = 0
            def identify(self):
                pass
            def frame(self):
                self.frames += 1
                return packet(self.frames, time.monotonic())['frame']
            def status(self):
                return healthy_status(time.monotonic())
            def event(self):
                return None
            def close(self):
                pass

        controller = Controller()
        recorder = CaptureRecorder(config, self.directory, self.root / 'integrated/capture.sock', contract())
        observer = LocalDisplay(config, self.root / 'integrated', learning_file, self.root / 'baseline.sqlite',
                                clock_factory=TrustedClock, recorder=recorder)
        service = Service(config, mock=True, controller=controller, observer=observer, recorder=recorder)
        with patch('cabinet.io.MMIO', side_effect=AssertionError('No actual hardware')):
            try:
                service.start()
                deadline = time.monotonic() + 3
                while recorder.snapshot()['boot'] is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                payload = self.payload(expected_boot=recorder.snapshot()['boot'], capture_mode='DIAGNOSTIC')
                result = request(self.root / 'integrated/capture.sock', dict(operation='start', request_id=str(uuid.uuid4()), payload=payload))
                self.assertTrue(result['ok'], result)
                time.sleep(0.2)
                before = controller.frames
                self.assertGreater(before, 5)
                result = request(self.root / 'integrated/capture.sock', dict(operation='stop', request_id=str(uuid.uuid4()),
                                 payload={'session_id': result['status']['session_id']}))
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['status']['state'], 'DIAGNOSTIC_SAVED')
                time.sleep(0.1)
                state = (self.root / 'integrated/state.txt').read_text(encoding='utf-8')
                self.assertIn('capture_schema=capture-v1', state)
                self.assertIn('capture_training_ready=0', state)
                self.assertIn('capture_state=DIAGNOSTIC_SAVED', state)
                self.assertEqual(len([thread for thread in service.threads if thread.name == 'cabinet-hardware']), 1)
            finally:
                service.close()

    def test_duration_completes_only_after_durable_write(self):
        self.begin(duration_s=1)
        self.observe()
        self.recorder.tick(self.now + 0.9)
        self.assertEqual(self.recorder.snapshot()['state'], 'COMPLETED')
        self.assertEqual(self.recorder.snapshot()['durable_frames'], 1)

    def test_stop_wrong_session_and_duplicate_request_are_safe(self):
        command = dict(operation='start', request_id=str(uuid.uuid4()), payload=self.payload())
        first = self.recorder.command(command, self.now)
        self.assertEqual(first, self.recorder.command(command, self.now))
        changed = copy.deepcopy(command)
        changed['payload']['label'] = 'clog'
        with self.assertRaisesRegex(ValueError, 'REQUEST_ID_REUSED'):
            self.recorder.command(changed, self.now)
        with self.assertRaisesRegex(ValueError, 'SESSION_MISMATCH'):
            self.recorder.command(dict(operation='stop', request_id=str(uuid.uuid4()), payload={'session_id': 'old'}), self.now)
        self.recorder.finish('ABORTED', 'UNIT_END', self.now)

    def test_projection_is_explicitly_unreviewed_and_stale_not_ready(self):
        state = display_fields(self.recorder.snapshot(), self.now + 5)
        self.assertEqual(state['capture_ready'], '0')
        self.assertEqual(state['capture_training_ready'], '0')
        self.assertEqual(state['capture_label_reviewed'], '0')

    def test_review_export_is_accepted_by_existing_real_importer(self):
        from v4_runtime.import_frames import import_records
        directory = self.save()
        result = export(self.review(directory), self.root / 'export')
        self.assertEqual(result['frames'], 2)
        imported = import_records(self.root / 'export/frames.jsonl', self.root / 'export/feature_contract.json', self.root / 'import')
        self.assertEqual(imported['source'], 'REAL_FRM1_DECLARED')
        self.assertFalse(imported['train_ready'])
        self.assertFalse(imported['physical_truth_verified'])
        self.assertEqual(imported['accepted']['train'], 2)

    def test_tampered_archive_and_missing_review_are_rejected(self):
        directory = self.save()
        with self.assertRaisesRegex(ValueError, 'reviewed label'):
            export(self.review(directory, label_reviewed=False), self.root / 'export')
        with (directory / 'frames.jsonl').open('a') as stream:
            stream.write('{}\n')
        with self.assertRaisesRegex(ValueError, 'Archive changed'):
            export(self.review(directory), self.root / 'export2')

    def test_root_exclusivity_socket_rpc_and_service_stop_do_not_fake_completion(self):
        self.recorder = CaptureRecorder(self.config, self.directory, self.root / 'view/capture.sock', contract())
        self.recorder.start()
        self.addCleanup(self.recorder.close)
        other = CaptureRecorder(self.config, self.directory, self.root / 'view/other.sock', contract())
        with self.assertRaisesRegex(RuntimeError, 'CAPTURE_START_FAILED'):
            other.start()
        other.close()
        now = time.monotonic()
        self.recorder.submit(packet(1, now))
        deadline = now + 2
        while self.recorder.snapshot()['boot'] is None and time.monotonic() < deadline:
            time.sleep(0.01)
        response = request(self.root / 'view/capture.sock', {'operation': 'status'})
        self.assertTrue(response['ok'])
        self.assertTrue(response['status']['ready'])
        payload = self.payload()
        result = request(self.root / 'view/capture.sock', dict(operation='start', request_id=str(uuid.uuid4()), payload=payload))
        self.assertTrue(result['ok'], result)
        self.recorder.close()
        self.assertEqual(self.recorder.snapshot()['state'], 'ABORTED')
        self.assertFalse((self.root / 'view/capture.sock').exists())


if __name__ == '__main__':
    unittest.main()
