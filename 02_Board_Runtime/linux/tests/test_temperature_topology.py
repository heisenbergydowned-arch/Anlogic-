import copy
from pathlib import Path
import tempfile
import unittest

from cabinet.environment import decode_environment
from cabinet.protocol import FEATURES, Frame, FrameGate
from hmi_daily.daily import build_daily
from hmi_daily.reader import view_state
from hmi_daily.cabinet.baseline import BaselineStore, DEFAULTS, Learner
from test_environment import snapshot
from test_local_display import WORDS, healthy_frame, healthy_status


def observation(core_c, inlet_code=393216, core_valid=True, aht_failed=False):
    original = healthy_frame(1, 1)
    values = list(original.values)
    values[36] = core_c
    header = list(original.header)
    if not core_valid:
        header[15] |= 1 << 9
    frame = Frame(tuple(header), tuple(values))
    status = copy.deepcopy(healthy_status(1))
    status['temp_raw_1_16_C'] = int(core_c * 16)
    status['input_validity']['temperature'] = core_valid
    if not core_valid:
        status.update(active=['TEMP_LOSS'], alarm_level=2)
    words = snapshot()
    words[8] = inlet_code
    if aht_failed:
        words[4] |= 8
    record = frame.as_dict()
    record.update(header=list(frame.header), state='RECEIVED_REAL')
    sample = dict(frame=record, status=status, feature_words=WORDS,
                  mailbox_before_read=dict(queued_frames=1, dropped_frames=0),
                  environment=decode_environment(words, 1000))
    state, _, _ = view_state(sample, None, None, 1, 1)
    baseline = dict(state='IDLE', reason='READY', evidence=dict(state='UNLEARNED', score=None))
    daily = build_daily(state, sample, baseline)
    return frame, state, daily


class TemperatureTopologyTests(unittest.TestCase):
    def test_core_display_and_feature_follow_only_single_probe_including_zero(self):
        self.assertEqual(FEATURES[36], 'temp')
        for core_c in (-5, 0, 65, 90):
            with self.subTest(core_c=core_c):
                frame, state, daily = observation(core_c)
                self.assertEqual(frame.values[36], core_c)
                self.assertEqual(float(state['feature_temp']), core_c)
                self.assertEqual(daily['core_temperature_c'], '%.1f' % core_c)
                self.assertEqual(daily['core_temperature_valid'], '1')
                self.assertEqual(daily['inlet_temperature_c'], '25.0')
                self.assertEqual(daily['core_temperature_source'], 'DS18B20/S4b')

    def test_inlet_changes_and_failure_cannot_replace_core_temperature(self):
        for inlet_code, failed in ((262144, False), (655360, False), (393216, True)):
            with self.subTest(inlet_code=inlet_code, failed=failed):
                frame, state, daily = observation(65, inlet_code, aht_failed=failed)
                self.assertEqual(frame.values[36], 65)
                self.assertEqual(state['ui_temp_value'], '65.0')
                self.assertEqual(daily['core_temperature_c'], '65.0')
                self.assertEqual(daily['core_temperature_valid'], '1')

    def test_core_loss_blanks_display_and_rejects_model_frame_despite_valid_inlet(self):
        frame, state, daily = observation(65, core_valid=False)
        self.assertEqual(daily['inlet_temperature_c'], '25.0')
        self.assertEqual(state['ui_temp_valid'], '0')
        self.assertEqual(daily['core_temperature_valid'], '0')
        self.assertEqual(daily['core_temperature_c'], '--')
        contract = dict(feature_config_id=frame.header[16], calibration_id=frame.header[17], sample_mode_id=frame.header[18])
        healthy, _, _ = observation(65)
        self.assertEqual(FrameGate(contract).check(healthy, healthy.header[4]), [])
        self.assertEqual(FrameGate(contract).check(frame, frame.header[4]), ['quality'])

    def test_automatic_learning_rejects_core_loss_even_with_valid_inlet(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BaselineStore(Path(directory) / 'baseline.sqlite')
            try:
                config = copy.deepcopy(DEFAULTS)
                config.update(device_id='single-core-test', installation_id='core-heatsink')
                config['contract']['calibration_id'] = 7
                learner = Learner(store, config)
                status = copy.deepcopy(healthy_status(1))
                self.assertIsNone(learner.guard(status))
                status['input_validity']['temperature'] = False
                self.assertTrue(decode_environment(snapshot(), 1000)['aht_valid'])
                self.assertEqual(learner.guard(status), 'SENSOR_INVALID')
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
