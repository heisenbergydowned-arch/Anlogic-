import unittest
import tempfile
from pathlib import Path
from reader import view_state, publish
from cabinet.protocol import FEATURES
from cabinet.io import Controller
from read_real import read_sample


def sample(state='EMPTY', quality=0):
    frame = {'state': state}
    if state != 'EMPTY':
        frame.update(frame_id=123, end_ms=10, quality=quality, quality_reasons=['uncalibrated'] if quality else [], values={name: 2.5 for name in FEATURES})
    return {'status': {'uptime_ms': 10, 'input_validity': {}, 'hard_inhibit': True},
            'frame': frame, 'mailbox_before_read': {'queued_frames': 0, 'dropped_frames': 0}}


class DisplayTests(unittest.TestCase):
    def test_empty_does_not_fabricate_values(self):
        view, frame, stamp = view_state(sample(), None, None, 10, 1)
        self.assertEqual(view['message'], 'WAITING FOR SAMPLES')
        self.assertTrue(all(view['feature_' + name] == '--' for name in FEATURES))
        self.assertEqual(view['temp'], 'INVALID / --')
        self.assertIsNone(frame)
        self.assertIsNone(stamp)

    def test_valid_frame_and_stale_hiding(self):
        view, frame, stamp = view_state(sample('RECEIVED_REAL'), None, None, 10, 1)
        self.assertEqual(view['feature_rms_a_x'], '2.5')
        view, _, _ = view_state(sample(), frame, stamp, 11.1, 2)
        self.assertEqual(view['feature_rms_a_x'], '--')
        self.assertIn('STALE', view['message'])

    def test_test_frame_rejected(self):
        view, frame, _ = view_state(sample('REJECTED_TEST'), None, None, 10, 1)
        self.assertEqual(view['feature_rpm'], '--')
        self.assertIn('TEST', view['message'])
        self.assertIsNone(frame)

    def test_quality_not_hidden(self):
        view, _, _ = view_state(sample('RECEIVED_REAL', 0x1000), None, None, 10, 1)
        self.assertEqual(view['quality'], '0x00001000')
        self.assertIn('not model-qualified', view['message'])

    def test_old_queued_frame_is_not_fresh_on_arrival(self):
        observation = sample('RECEIVED_REAL')
        observation['status']['uptime_ms'] = 2010
        view, _, _ = view_state(observation, None, None, 10, 1)
        self.assertEqual(view['feature_rms_a_x'], '--')
        self.assertIn('STALE', view['message'])

    def test_unqualified_control_is_not_a_test_data_source(self):
        observation = sample('RECEIVED_REAL')
        observation['status']['test_mode'] = True
        view, _, _ = view_state(observation, None, None, 10, 1)
        self.assertEqual(view['feature_rms_a_x'], '2.5')
        self.assertNotIn('TEST source', view['message'])

    def test_frame_completed_just_after_status_snapshot(self):
        observation = sample('RECEIVED_REAL')
        observation['frame']['end_ms'] = 11
        view, _, _ = view_state(observation, None, None, 10, 1)
        self.assertEqual(view['feature_rpm'], '2.5')

    def test_observer_only_writes_snapshot_and_frame_ack(self):
        class Registers:
            def __init__(self):
                self.writes = []
                self.values = {0: 0x46434231, 4: 0x10000, 0x1000: 0x45444731, 0x1004: 0x10000,
                               0x1050: 123, 0x1008: 1, 0x1010: 12}
                header = [0x46524d31, 0x10000, 284, 12] + [0] * 28
                self.values.update({0x1100 + index * 4: word for index, word in enumerate(header)})

            def read(self, address):
                return self.values.get(address, 0)

            def write(self, address, value):
                self.writes.append((address, value))

        registers = Registers()
        controller = Controller(registers)
        controller.identify()
        read_sample(controller)
        self.assertEqual(registers.writes, [(0x1010, 12), (0xc, 1), (0x10, 0), (0x14, 7)])

    def test_chinese_empty_state_never_claims_healthy(self):
        view, _, _ = view_state(sample(), None, None, 10, 1)
        self.assertEqual(view['ui_banner_title'], '等待有效采样')
        self.assertEqual(view['ui_rpm_value'], '--')
        self.assertEqual(view['ui_pressure_value'], '--')
        self.assertNotEqual(view['ui_severity'], '0')

    def test_valid_native_units_and_runtime_source(self):
        observation = sample()
        observation['status'].update(input_validity=dict(rpm=True, temperature=True, adc=True, pressure=True),
                                     measured_rpm=6000, temp_raw_1_16_C=408, current_distance_raw_code=23,
                                     pressure_raw_code=-32768, uptime_ms=3661000)
        view, _, _ = view_state(observation, None, None, 10, 1)
        self.assertEqual(view['ui_runtime'], '01:01:01')
        self.assertEqual(view['ui_temp_value'], '25.5')
        self.assertEqual(view['ui_pressure_value'], '-32768')
        self.assertEqual(view['ui_current_unit'], '原始码')
        self.assertEqual(view['ui_pressure_unit'], '原始码')

    def test_critical_alarm_overrides_waiting_banner(self):
        observation = sample()
        observation['status'].update(alarm_level=3, active=['OC_HARD'])
        view, _, _ = view_state(observation, None, None, 10, 1)
        self.assertEqual(view['ui_severity'], '3')
        self.assertEqual(view['ui_banner_title'], '严重告警，请检查设备')
        self.assertEqual(view['ui_fault_0_title'], '严重过流')

    def test_utf8_text_file_has_bounded_complete_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            publish(Path(directory), {'note': '测' * 512}, None)
            encoded = (Path(directory) / 'state.txt').read_bytes()
            self.assertLessEqual(len(encoded), 506)
            self.assertTrue(encoded.decode('utf-8').startswith('note=测'))

    def test_signed_pressure_code_is_not_fabricated_pascal(self):
        class EmptyRegisters:
            def read(self, address):
                return 0

        class StatusController:
            io = EmptyRegisters()

            def __init__(self, raw):
                self.raw = raw

            def status(self):
                words = [0] * 32
                words[0] = 1 << 13
                words[22] = self.raw << 16
                return {'raw_words': words}

            def frame(self):
                return None

        for raw, signed in [(0, 0), (0x7fff, 32767), (0x8000, -32768), (0xffff, -1)]:
            self.assertEqual(read_sample(StatusController(raw))['status']['pressure_raw_code'], signed)

    def test_test_frame_does_not_show_native_values_as_real_measurements(self):
        observation = sample('REJECTED_TEST')
        observation['status'].update(input_validity=dict(rpm=True, temperature=True, adc=True, pressure=True),
                                     measured_rpm=6000, temp_raw_1_16_C=408, current_distance_raw_code=23,
                                     pressure_raw_code=12)
        view, _, _ = view_state(observation, None, None, 10, 1)
        for name in ('rpm', 'temp', 'current', 'pressure'):
            self.assertEqual(view['ui_' + name + '_value'], '--')
            self.assertEqual(view['ui_' + name + '_valid'], '0')


if __name__ == '__main__':
    unittest.main()
