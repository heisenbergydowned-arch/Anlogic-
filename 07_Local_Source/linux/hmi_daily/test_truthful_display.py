"""Regression cases for real missing sensors and unqualified model displays."""
import copy
import unittest

from daily import build_daily
from reader import view_state
from test_instrument import fixture


def attached_model():
    return dict(backend='Alnpu', feature_config_id=1, calibration_id=7,
                frame_id=123, test=False, label='normal', probabilities=[1, 0, 0, 0, 0])


class TruthfulDisplayTests(unittest.TestCase):
    def render(self, sample, baseline):
        view, _, _ = view_state(sample, None, None, 10, 1)
        return view, build_daily(view, sample, baseline)

    def test_model_cannot_create_missing_process_measurements(self):
        _, sample, baseline = fixture()
        sample['model'] = attached_model()
        sample['status']['input_validity'].update(rpm=False, pressure=False, adc=False)
        original = copy.deepcopy(sample)
        view, daily = self.render(sample, baseline)
        for name in ('rpm', 'pressure', 'current'):
            self.assertEqual(view['ui_' + name + '_value'], '--')
            self.assertEqual(view['ui_' + name + '_valid'], '0')
            self.assertEqual(daily['daily_' + name + '_value'], '--')
            self.assertEqual(daily['daily_' + name + '_valid'], '0')
        self.assertEqual(sample, original)

    def test_adc_raw_code_is_not_a_calibrated_current(self):
        _, sample, baseline = fixture()
        sample['model'] = attached_model()
        sample['frame']['calibration_id'] = 0
        sample['frame']['quality'] = 0x1000
        sample['status']['raw_words'] = [0] * 32
        sample['status']['raw_words'][22] = 0xfff4
        view, daily = self.render(sample, baseline)
        self.assertEqual(view['frame_calibrated'], '0')
        self.assertEqual(daily['daily_current_value'], '-12')
        self.assertEqual(daily['daily_current_unit'], '原始码')
        self.assertEqual(daily['daily_current_kind'], 'raw_sample')

    def test_backend_label_cannot_override_calibration_or_contract(self):
        _, sample, baseline = fixture()
        sample['model'] = attached_model()
        sample['frame']['calibration_id'] = 0
        sample['feature_words'] = [99, 0, 0] + [0] * 14
        view, daily = self.render(sample, baseline)
        self.assertEqual(view['frame_calibrated'], '0')
        self.assertEqual(view['frame_contract_current'], '0')
        self.assertEqual(daily['panel_vibration_valid'], '0')
        self.assertEqual(daily['daily_rms_a_x'], '--')
        self.assertEqual(daily['panel_model_valid'], '0')

    def test_uncalibrated_quality_cannot_render_g_even_with_nonzero_id(self):
        _, sample, baseline = fixture()
        sample['model'] = attached_model()
        sample['frame']['quality'] = 0x1000
        view, daily = self.render(sample, baseline)
        self.assertEqual(view['frame_calibrated'], '0')
        self.assertEqual(daily['panel_vibration_valid'], '0')

    def test_alnpu_label_cannot_bypass_model_quality_or_binding(self):
        for change in ('quality', 'calibration', 'test', 'binding', 'confidence'):
            with self.subTest(change=change):
                _, sample, baseline = fixture()
                sample['model'] = attached_model()
                if change == 'quality':
                    sample['frame']['quality'] = 0x0400
                elif change == 'calibration':
                    sample['frame']['calibration_id'] = 0
                elif change == 'test':
                    sample['model']['test'] = True
                elif change == 'binding':
                    sample['model']['calibration_id'] = 42
                else:
                    sample['model']['diagnostic_state'] = 'REJECTED_CONFIDENCE'
                _, daily = self.render(sample, baseline)
                self.assertEqual(daily['panel_model_valid'], '0')
                self.assertEqual(daily['panel_prob_normal'], '--')

    def test_model_cannot_invent_health_baseline(self):
        _, sample, baseline = fixture()
        sample['model'] = attached_model()
        _, daily = self.render(sample, baseline)
        self.assertEqual(daily['panel_baseline_valid'], '0')
        self.assertEqual(daily['ui_learn_score'], '--')
        self.assertEqual(daily['ui_learn_evidence'], '尚无健康基线')
        for group in ('amplitude', 'spectrum', 'ratio', 'process'):
            self.assertEqual(daily['panel_group_' + group], '--')

    def test_true_temperature_and_signed_raw_adc_are_preserved(self):
        _, sample, baseline = fixture()
        sample['status']['temp_raw_1_16_C'] = 398
        sample['status']['input_validity'].update(rpm=False, pressure=False)
        sample['status']['raw_words'] = [0] * 32
        sample['status']['raw_words'][22] = 11654
        sample['frame']['quality'] = 0x3c00
        _, daily = self.render(sample, baseline)
        self.assertEqual(daily['core_temperature_c'], '24.9')
        self.assertEqual(daily['core_temperature_valid'], '1')
        self.assertEqual(daily['daily_current_value'], '11654')
        self.assertEqual(daily['daily_current_kind'], 'raw_sample')
        self.assertEqual(daily['daily_pressure_value'], '--')

    def test_test_source_cannot_restore_adc_or_temperature_via_daily_fields(self):
        _, sample, baseline = fixture()
        sample['frame']['state'] = 'REJECTED_TEST'
        sample['status']['raw_words'] = [0] * 32
        sample['status']['raw_words'][22] = 123
        _, daily = self.render(sample, baseline)
        self.assertEqual(daily['core_temperature_valid'], '0')
        self.assertEqual(daily['core_temperature_c'], '--')
        for name in ('rpm', 'pressure', 'current'):
            self.assertEqual(daily['daily_' + name + '_valid'], '0')
            self.assertEqual(daily['daily_' + name + '_value'], '--')

    def test_stale_frame_cannot_keep_model_or_baseline_visible(self):
        _, sample, baseline = fixture()
        sample['model'] = attached_model()
        sample['status']['uptime_ms'] += 2000
        baseline.update(warning_score=6, evidence=dict(state='CONSISTENT', score=1,
                        group_scores=dict(amplitude=1, spectrum=1, ratio=1, process=1)))
        _, daily = self.render(sample, baseline)
        self.assertEqual(daily['panel_model_valid'], '0')
        self.assertEqual(daily['panel_baseline_valid'], '0')


if __name__ == '__main__':
    unittest.main()
