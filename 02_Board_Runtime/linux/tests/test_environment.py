import copy
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cabinet.environment import age_environment, compensate_bmp280, decode_environment, display_fields, read_environment
from cabinet.local_display import LocalDisplay
from cabinet.model import Model
from cabinet.protocol import FEATURES
from cabinet.service import Service
from hmi_daily.cabinet.baseline import DEFAULTS
from test_local_display import CONFIG, TrustedClock, WORDS, healthy_frame, healthy_status


CALIBRATION = struct.pack('<HhhHhhhhhhhh', 27504, 26435, -1000, 36477, -10685,
                          3024, 2855, 140, -7, 15500, -14600, 6000)


def snapshot(now=1000):
    return [0x454e5631, 0x10000, 1, now, 0x27, 0, 0, 524288, 393216,
            519888, 415148, *struct.unpack('<6I', CALIBRATION), 1, 1, 2]


class Registers:
    def __init__(self, words=None):
        self.words = words or snapshot()
        self.reads = []
        self.changed = False

    def read(self, address):
        self.reads.append((address, threading.get_ident()))
        index = (address - 0x3000) // 4
        if not 0x3000 <= address <= 0x304c:
            raise AssertionError('Unexpected MMIO read')
        if self.changed and address == 0x3008 and sum(item[0] == address for item in self.reads) == 2:
            return self.words[index] + 1
        return self.words[index]


class EnvironmentTests(unittest.TestCase):
    def test_bosch_datasheet_numeric_reference(self):
        temperature, pressure = compensate_bmp280(519888, 415148, CALIBRATION)
        self.assertAlmostEqual(temperature, 25.08247793081682, places=10)
        self.assertAlmostEqual(pressure * 100, 100653.26677582515, places=6)

    def test_aht_conversion_and_separate_absolute_pressure(self):
        value = decode_environment(snapshot(), 1000)
        self.assertEqual(value['state'], 'VALID')
        self.assertEqual(value['inlet_temperature_c'], 25)
        self.assertEqual(value['relative_humidity_pct'], 50)
        self.assertAlmostEqual(value['ambient_pressure_hpa'], 1006.5326677582515)
        self.assertEqual(value['core_source'], 'DS18B20/S4b')

    def test_aht_negative_and_endpoints(self):
        for temperature in (-40, -10, 0, 25, 85):
            for humidity in (0, 50, 99.9):
                words = snapshot()
                words[8] = max(52429, min(707788, round((temperature + 50) / 200 * 1048576)))
                words[7] = round(humidity / 100 * 1048576)
                result = decode_environment(words, 1000)
                self.assertTrue(result['aht_valid'])
                self.assertAlmostEqual(result['inlet_temperature_c'], temperature, delta=0.0002)
                self.assertAlmostEqual(result['relative_humidity_pct'], humidity, delta=0.0001)

    def test_old_firmware_never_reads_new_page(self):
        registers = Registers()
        self.assertEqual(read_environment(registers, {})['state'], 'FIRMWARE_UNAVAILABLE')
        self.assertEqual(registers.reads, [])

    def test_atomic_snapshot_and_double_identity_check(self):
        registers = Registers()
        self.assertEqual(read_environment(registers, {'capabilities': 1 << 31})['state'], 'VALID')
        self.assertEqual([address for address, _ in registers.reads], list(range(0x3000, 0x3050, 4)) + [0x3008])
        registers = Registers()
        registers.changed = True
        self.assertEqual(read_environment(registers, {'capabilities': 1 << 31})['state'], 'INCOHERENT_ENV1')

    def test_slow_snapshot_fails_closed(self):
        with patch('cabinet.environment.time.monotonic', side_effect=[1, 1.3]):
            result = read_environment(Registers(), {'capabilities': 1 << 31})
        self.assertEqual(result['state'], 'STALE_ENV1')

    def test_snapshot_read_latency_consumes_remaining_sensor_lifetime(self):
        words = snapshot()
        words[5] = 2400
        with patch('cabinet.environment.time.monotonic', side_effect=[1, 1.101]):
            result = read_environment(Registers(words), {'capabilities': 1 << 31})
        self.assertFalse(result['aht_valid'])
        self.assertIsNone(result['inlet_temperature_c'])
        self.assertTrue(result['bmp_valid'])
        self.assertAlmostEqual(result['read_latency_ms'], 101)

    def test_sensor_errors_and_stale_independently_blank(self):
        for mask, key, other in [(8, 'aht_valid', 'bmp_valid'), (16, 'aht_valid', 'bmp_valid'),
                                 (64, 'bmp_valid', 'aht_valid'), (128, 'bmp_valid', 'aht_valid')]:
            words = snapshot()
            words[4] |= mask
            result = decode_environment(words, 1000)
            self.assertFalse(result[key])
            self.assertTrue(result[other])
        for index, key in [(5, 'aht_valid'), (6, 'bmp_valid')]:
            words = snapshot()
            words[index] = 2501
            self.assertFalse(decode_environment(words, 1000)[key])

    def test_stale_future_wrap_and_identity(self):
        self.assertEqual(decode_environment(snapshot(), 3501)['state'], 'STALE_ENV1')
        self.assertEqual(decode_environment(snapshot(), 999)['state'], 'STALE_ENV1')
        self.assertEqual(decode_environment(snapshot(0xfffffff0), 16)['state'], 'VALID')
        for index in (0, 1, 19):
            words = snapshot()
            words[index] = 0
            self.assertEqual(decode_environment(words, 1000)['state'], 'INVALID_ENV1')

    def test_subscriber_and_public_state_age_never_extend_sensor_lifetime(self):
        words = snapshot()
        words[5] = 2400
        initial = decode_environment(words, 1000)
        self.assertTrue(initial['aht_valid'])
        old = age_environment(initial, 101)
        self.assertFalse(old['aht_valid'])
        self.assertIsNone(old['inlet_temperature_c'])
        self.assertTrue(old['bmp_valid'])
        self.assertTrue(initial['aht_valid'])
        with patch('cabinet.environment.time.clock_gettime', return_value=10):
            fields = display_fields(old)
        self.assertEqual(fields['environment_aht_deadline_ms'], '0')
        self.assertNotIn('environment_bmp_deadline_ms', fields)
        self.assertNotIn('ambient_pressure_hpa', fields)
        self.assertEqual(fields['environment_state'], 'DEGRADED')
        self.assertEqual(age_environment(initial, -1)['state'], 'STALE_ENV1')

    def test_invalid_calibration_skipped_conversion_and_ranges(self):
        for calibration in (bytes(24), bytes([255]) * 24, CALIBRATION[:6] + bytes(2) + CALIBRATION[8:]):
            with self.assertRaises(ValueError):
                compensate_bmp280(519888, 415148, calibration)
        for temperature, pressure in [(0x80000, 415148), (519888, 0x80000), (-1, 1), (0, 0), (1048576, 1)]:
            with self.assertRaises(ValueError):
                compensate_bmp280(temperature, pressure, CALIBRATION)
        for index in (7, 8):
            words = snapshot()
            words[index] = 1048576
            self.assertFalse(decode_environment(words, 1000)['aht_valid'])

    def test_no_core_temperature_or_39d_replacement(self):
        self.assertEqual(len(FEATURES), 39)
        self.assertEqual(FEATURES[35:39], ['current', 'temp', 'pressure', 'rpm'])
        frame = healthy_frame(1, 1)
        original = tuple(frame.values)
        for temperature in (52429, 707788):
            words = snapshot()
            words[8] = temperature
            result = decode_environment(words, 1000)
            self.assertNotIn('temp', result)
            self.assertNotIn('values', result)
            self.assertEqual(tuple(frame.values), original)
        self.assertEqual(display_fields(None)['inlet_temperature_c'], '--')

    def test_model_payload_uses_original_core_feature(self):
        frame = healthy_frame(1, 1)
        model = Model(dict(backend='command', command=['unused'], model_id='test', timeout_ms=1000))
        response = dict(frame_id=frame.id, model_id='test', feature_config_id=frame.header[16],
                        calibration_id=frame.header[17], probabilities=[1, 0, 0, 0, 0])
        with patch('cabinet.model.subprocess.run') as run:
            run.return_value.stdout = json.dumps(response)
            model.infer(frame)
        payload = json.loads(run.call_args[1]['input'])
        self.assertEqual(payload['values'], list(frame.values))
        self.assertEqual(payload['values'][36], frame.values[36])
        self.assertNotIn('environment', payload)

    def test_same_collector_delivers_environment_to_hmi_and_learning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = copy.deepcopy(CONFIG)
            config.update(device_id='environment-test', database=str(root / 'events.sqlite'))
            config['contract']['calibration_id'] = 7
            learning = copy.deepcopy(DEFAULTS)
            learning.update(device_id='environment-test')
            learning['contract']['calibration_id'] = 7
            path = root / 'learning.json'
            path.write_text(json.dumps(learning))
            display = LocalDisplay(config, root / 'view', path, root / 'baseline.sqlite', clock_factory=TrustedClock)
            display.initialize()
            try:
                frame = healthy_frame(1, 1)
                packet = dict(sequence=1, boot='test/123', link='ONLINE', received_at=1, reported_at=time.time(),
                              status=healthy_status(1), frame=frame, feature_words=WORDS,
                              mailbox=dict(queued_frames=1, dropped_frames=0), test=False,
                              model=None, model_required=False, model_formal=False, model_fresh=False,
                              environment=decode_environment(snapshot(), 1000))
                packet['status']['active'] = ['AUX_LOSS', 'CURRENT_HIGH']
                display.step(packet, 1)
                result = json.loads((root / 'view/state.json').read_text())
                self.assertEqual(result['display']['inlet_temperature_c'], '25.0')
                self.assertNotIn('ambient_pressure_hpa', result['display'])
                self.assertAlmostEqual(result['observation']['environment']['ambient_pressure_hpa'], 1006.5326677582515)
                self.assertEqual(result['observation']['status']['active'], ['AUX_LOSS', 'CURRENT_HIGH'])
                self.assertEqual(result['display']['faults'], 'AUX_LOSS, CURRENT_HIGH')
                self.assertEqual(result['observation']['frame']['values']['temp'], frame.values[36])
                display.offline('PL_LINK_LOSS')
                result = json.loads((root / 'view/state.json').read_text())
                self.assertIsNone(result['observation'])
                self.assertNotIn('inlet_temperature_c', result['display'])
            finally:
                display.rpc.close()
                display.clock.close()
                display.store.close()

    def test_actual_aht_only_inventory_does_not_require_uninstalled_bmp(self):
        words = snapshot()
        words[4] = 0xc5  # AHT present/valid, legacy BMP error/stale.
        words[6] = 0xffffffff
        words[18] = 0
        original = list(words)
        value = decode_environment(words, 1000)
        self.assertEqual(value['state'], 'VALID')
        self.assertEqual(value['raw_environment_state'], 'DEGRADED')
        self.assertEqual(value['installed_environment_sensors'], ['AHT20'])
        self.assertEqual(value['hardware_profile'], 'AHT20_ONLY_V1')
        self.assertFalse(value['bmp_valid'])
        self.assertEqual((value['bmp_samples'], value['bmp_age_ms']), (0, 0xffffffff))
        self.assertIsNone(value['ambient_pressure_hpa'])
        self.assertEqual(words, original)
        fields = display_fields(value)
        self.assertEqual(fields['environment_state'], 'VALID')
        self.assertEqual((fields['inlet_temperature_c'], fields['relative_humidity_pct']), ('25.0', '50.0'))
        self.assertFalse(any('bmp' in key or key.startswith('ambient_pressure') for key in fields))

    def test_installed_aht_error_missing_or_stale_still_degrades_with_good_bmp(self):
        for mask in (0x08, 0x10):
            words = snapshot(); words[4] |= mask
            value = decode_environment(words, 1000)
            self.assertTrue(value['bmp_valid'])
            self.assertFalse(value['aht_valid'])
            self.assertEqual(value['state'], 'DEGRADED')
            self.assertEqual(display_fields(value)['inlet_temperature_c'], '--')
        words = snapshot(); words[17] = 0
        self.assertEqual(decode_environment(words, 1000)['state'], 'DEGRADED')
        value = decode_environment(snapshot(), 1000)
        expired = age_environment(value, 2501)
        self.assertEqual(expired['state'], 'DEGRADED')
        self.assertFalse(expired['aht_valid'])
        self.assertEqual(display_fields(expired)['environment_aht_deadline_ms'], '0')
        self.assertEqual(value['state'], 'VALID')

    def test_raw_bmp_diagnostics_do_not_become_installed_product_fields(self):
        value = decode_environment(snapshot(), 1000)
        self.assertTrue(value['bmp_valid'])
        self.assertEqual(value['raw_environment_state'], 'VALID')
        self.assertEqual(value['legacy_uninstalled_sensors'], ['BMP280'])
        fields = display_fields(value)
        self.assertEqual(fields['environment_installed_sensors'], 'AHT20')
        self.assertFalse(any('bmp' in key or 'ambient_pressure' in key for key in fields))


if __name__ == '__main__':
    unittest.main()
