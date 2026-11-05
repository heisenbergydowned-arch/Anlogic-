import copy
import unittest

from cabinet.feature_display import raw_feature_fields
from cabinet.protocol import FEATURES, Frame, FrameGate


class RawFeatureDisplayTests(unittest.TestCase):
    def setUp(self):
        header = [0] * 32
        header[:3] = [0x46524d31, 0x10000, 284]
        header[3:5] = [1, 1000]
        header[9:13] = [25575000, 25575000, 1024, 1024]
        header[15:19] = [0x3c00, 1, 0, 2]
        header[21] = 100000000
        values = {name: 1.0 for name in FEATURES}
        for name in FEATURES:
            if name.startswith('band'):
                values[name] = 0.125
        self.frame = Frame(tuple(header), tuple(values[name] for name in FEATURES))
        self.record = self.frame.as_dict()
        self.record.update(state='RECEIVED_REAL', header=list(header))
        self.words = [1, 0, 0] + [0] * 5 + [1, 13, 39, 65, 103, 154, 205, 257, 513]
        self.status = dict(uptime_ms=1100)
        self.sensors = dict(panel_icm_a_deadline_ms='11500', panel_icm_b_deadline_ms='11600')

    def fields(self, **changes):
        arguments = dict(frame=self.record, words=self.words, status=self.status, now=10.1, received_at=10.0,
                         sensor_fields=self.sensors, sensor_pair_since_ms=0)
        arguments.update(changes)
        return raw_feature_fields(**arguments)

    def test_uncalibrated_missing_rpm_pressure_is_diagnostic_not_g_or_formal(self):
        result = self.fields()
        self.assertEqual(result['panel_raw_features_valid'], '1')
        self.assertEqual(result['raw_feature_rms_a_x'], '4096.0')
        self.assertEqual(result['raw_feature_banda0'], '12.50')
        self.assertNotIn('daily_rms_a_x', result)
        self.assertNotIn('panel_vibration_valid', result)

    def test_frame_gate_and_input_remain_unchanged(self):
        before = copy.deepcopy(self.record)
        self.fields()
        self.assertEqual(self.record, before)
        gate = FrameGate(dict(feature_config_id=1, calibration_id=0, sample_mode_id=2))
        self.assertTrue(gate.check(self.frame, 1100))

    def test_absent_frame(self):
        self.assertEqual(self.fields(frame=None)['panel_raw_features_valid'], '0')

    def test_each_vibration_quality_fault_rejected(self):
        for bit in list(range(8)) + [14, 15, 31]:
            self.record['quality'] = self.record['header'][15] = 1 << bit
            self.assertEqual(self.fields()['panel_raw_features_valid'], '0')

    def test_old_queued_frame_not_refreshed(self):
        self.status['uptime_ms'] = 3100
        self.assertEqual(self.fields()['panel_raw_features_valid'], '0')

    def test_future_packet_rejected(self):
        self.assertEqual(self.fields(received_at=10.2)['panel_raw_features_valid'], '0')

    def test_actual_rate_must_meet_original_4khz_budget(self):
        self.record['header'][9] = 36535714
        self.assertEqual(self.fields()['panel_raw_features_valid'], '0')

    def test_current_source_configuration_must_match(self):
        self.words[0] = 2
        self.assertEqual(self.fields()['panel_raw_features_valid'], '0')

    def test_bad_bins_rejected(self):
        self.words[-1] = 1024
        self.assertEqual(self.fields()['panel_raw_features_valid'], '0')

    def test_nan_feature_rejected(self):
        self.record['values']['rms_a_x'] = float('nan')
        self.assertEqual(self.fields()['panel_raw_features_valid'], '0')

    def test_impossible_band_fraction_rejected(self):
        self.record['values']['banda0'] = 2
        self.assertEqual(self.fields()['panel_raw_features_valid'], '0')

    def test_energy_sum_up_to_105_accepted(self):
        for name in FEATURES:
            if name.startswith('banda'):
                self.record['values'][name] = 1.04 / 8.0
        self.assertEqual(self.fields()['panel_raw_features_valid'], '1')

    def test_test_source_rejected(self):
        self.record['test'] = True
        self.assertEqual(self.fields()['panel_raw_features_valid'], '0')

    def test_display_deadline_subtracts_hardware_and_queue_age(self):
        result = self.fields()
        self.assertEqual(result['panel_raw_features_deadline_ms'], '11500')

    def test_missing_independent_sensor_evidence_rejects_mirrored_frame(self):
        self.assertEqual(self.fields(sensor_fields=None)['panel_raw_features_valid'], '0')
        for point in 'ab':
            sensors = dict(self.sensors)
            sensors['panel_icm_' + point + '_deadline_ms'] = '0'
            self.assertEqual(self.fields(sensor_fields=sensors)['panel_raw_features_valid'], '0')

    def test_sensor_deadline_cannot_be_refreshed_by_new_feature_frames(self):
        sensors = dict(self.sensors, panel_icm_b_deadline_ms='10099')
        self.assertEqual(self.fields(sensor_fields=sensors)['panel_raw_features_valid'], '0')

    def test_recovery_requires_whole_window_after_pair_verified(self):
        self.assertEqual(self.fields(sensor_pair_since_ms=900)['panel_raw_features_valid'], '0')
        self.assertEqual(self.fields(sensor_pair_since_ms=740)['panel_raw_features_valid'], '1')
