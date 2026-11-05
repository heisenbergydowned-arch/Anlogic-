"""Actual subscriber packets: R45 mirrored frames cannot impersonate a missing ICM."""
import copy
import json
import unittest
from cabinet.protocol import FEATURES, Frame
import test_local_display as fixtures


class SensorIdentityDisplayTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.LocalDisplayTests()
        self.base.setUp()
        self.addCleanup(self.base.tearDown)
        self.words = [1, 0, 0] + [0] * 5 + [1, 13, 39, 65, 103, 154, 205, 257, 513]

    def publish(self, missing=None, condition='error', mirror=False, calibrated=False):
        packet = self.base.packet()
        packet['feature_words'] = ([1, 7, 1] + self.words[3:]) if calibrated else self.words
        header = list(packet['frame'].header)
        header[9:13] = [25575000, 25575000, 1024, 1024]
        header[15:19] = [0x3c00, 1, 0, 2]
        if calibrated:
            header[15], header[17] = 0, 7
        header[21] = 100000000
        header[27] = 0
        values = {name: 1.0 for name in FEATURES}
        for name in FEATURES:
            if name.startswith('band'): values[name] = 0.125
            elif '_a_' in name: values[name] = 0.01
            elif '_b_' in name: values[name] = 0.01 if mirror else 0.02
        packet['frame'] = Frame(tuple(header), tuple(values[name] for name in FEATURES))
        sensors = [dict(channel=point, who=0x2e, fresh=True, error=False, config_verified=True,
                        config_bad_mask=0, sample_age_ms=0.1, raw=raw, observed_rate_hz=4000)
                   for point, raw in [('A', [111, 112, 113]), ('B', [811, 812, 813])]]
        if missing:
            sensor = sensors['AB'.index(missing)]
            if condition == 'error': sensor.update(error=True, fresh=False)
            elif condition == 'stale': sensor.update(sample_age_ms=101)
            elif condition == 'configuration': sensor.update(config_verified=False, config_bad_mask=1)
        packet['icm_diagnostics'] = dict(state='DIAGNOSTIC_ONLY', test=False, boot_id='test-device',
                                       snapshot_age_ms=0, sensors=sensors)
        observer = self.base.observer
        observer.submit(packet)
        observer.step(observer.queue.get_nowait(), self.base.now)
        document = json.loads((self.base.root/'view/state.json').read_text())
        return document['display']

    def test_each_missing_sensor_is_hidden_while_healthy_raw_remains(self):
        for missing in 'AB':
            with self.subTest(missing=missing):
                self.publish()
                ready = self.publish()
                self.assertEqual(ready['panel_raw_features_valid'], '1')
                # The hardware frame still contains plausible two-sided values.
                for _ in range(5):
                    lost = self.publish(missing=missing, mirror=True)
                    self.assertEqual(lost['panel_raw_features_valid'], '0')
                    self.assertEqual(lost['panel_vibration_valid'], '0')
                    self.assertEqual(lost['panel_icm_'+missing.lower()+'_deadline_ms'], '0')
                    self.assertNotIn('raw_feature_rms_'+missing.lower()+'_x', lost)
                    healthy = 'b' if missing == 'A' else 'a'
                    self.assertNotEqual(lost['panel_icm_'+healthy+'_deadline_ms'], '0')
                    self.assertIn('811' if healthy == 'b' else '111', lost['panel_icm_'+healthy+'_raw'])
                # First recovery frame may contain old mirrored samples; wait a full window.
                first = self.publish()
                self.assertEqual(first['panel_raw_features_valid'], '0')
                restored = self.publish()
                self.assertEqual(restored['panel_raw_features_valid'], '1')
                self.assertNotEqual(restored['raw_feature_rms_a_x'], restored['raw_feature_rms_b_x'])

    def test_stale_or_unverified_channel_cannot_be_rescued_by_mirrored_frame(self):
        for condition in ('stale', 'configuration'):
            with self.subTest(condition=condition):
                self.publish(); self.publish()
                lost = self.publish(missing='B', condition=condition, mirror=True)
                self.assertEqual(lost['panel_raw_features_valid'], '0')
                self.assertEqual(lost['panel_icm_b_deadline_ms'], '0')
                self.assertNotEqual(lost['panel_icm_a_deadline_ms'], '0')

    def test_calibration_does_not_allow_physical_matrix_to_bypass_sensor_identity(self):
        self.publish(calibrated=True)
        ready = self.publish(calibrated=True)
        self.assertEqual(ready['panel_vibration_valid'], '1')
        lost = self.publish(missing='B', mirror=True, calibrated=True)
        self.assertEqual(lost['panel_vibration_valid'], '0')
        self.assertEqual(lost['panel_raw_features_valid'], '0')
        self.assertEqual(lost['panel_icm_b_deadline_ms'], '0')

    def test_collector_gap_requires_new_verified_pair_window(self):
        self.publish(calibrated=True)
        self.assertEqual(self.publish(calibrated=True)['panel_vibration_valid'], '1')
        self.base.identity += 1
        gap = self.publish(calibrated=True, mirror=True)
        self.assertEqual(gap['panel_raw_features_valid'], '0')
        self.assertEqual(gap['panel_vibration_valid'], '0')
        recovered = self.publish(calibrated=True)
        self.assertEqual(recovered['panel_raw_features_valid'], '1')
        self.assertEqual(recovered['panel_vibration_valid'], '1')


if __name__ == '__main__': unittest.main()
